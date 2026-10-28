"""病害鉴别判断模块（discriminate）。

核心职责：当模型置信度低时，不硬下结论，而是追问关键鉴别特征。
- LLM 负责对话与解释
- 本模块负责：低置信判定、问题匹配、后验更新

输入：云端服务返回的 detections（每个框带 top2 字段）
输出：是否需要澄清、追问文案、更新后的结论
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


# 加载问题库
_QUESTIONS_PATH = Path(__file__).parent / "questions.json"
with open(_QUESTIONS_PATH, "r", encoding="utf-8") as f:
    _QUESTIONS_DATA = json.load(f)


def _get_pair_key(label_a: str, label_b: str) -> tuple[str, str] | None:
    """获取标准化后的病害对 key。"""
    pair = sorted([label_a, label_b])
    for item in _QUESTIONS_DATA["pairs"]:
        if sorted(item["pair"]) == pair:
            return tuple(pair)
    return None


def _get_questions_for_pair(label_a: str, label_b: str) -> list[dict] | None:
    """获取病害对对应的问题列表。"""
    pair = sorted([label_a, label_b])
    for item in _QUESTIONS_DATA["pairs"]:
        if sorted(item["pair"]) == pair:
            return item["questions"]
    return None


def needs_clarification(detection: dict, margin: float = 0.15) -> bool:
    """判断是否需要澄清。

    当 top2[0].score - top2[1].score < margin 时返回 True，
    表示不该硬下结论。

    Args:
        detection: 云端服务返回的单个检测框，含 top2 字段：
            {
                "label": str,
                "confidence": float,
                "bbox": [x1, y1, x2, y2],
                "top2": [
                    {"label": str, "score": float},
                    {"label": str, "score": float}
                ]
            }
        margin: 置信度差阈值，默认 0.15

    Returns:
        bool: True 表示需要澄清，False 表示可以硬下结论
    """
    top2 = detection.get("top2", [])
    if len(top2) < 2:
        return False
    score1 = top2[0].get("score", 0.0)
    score2 = top2[1].get("score", 0.0)
    return (score1 - score2) < margin


def next_question(detection: dict) -> dict | None:
    """获取下一个追问问题。

    按 "best|second" 组合查问题库，返回给柚农的追问文案。

    Args:
        detection: 云端服务返回的单个检测框，含 top2 字段

    Returns:
        {
            "best": str,           # 第一候选 label
            "second": str,         # 第二候选 label
            "question": str,       # 追问文案（中文、口语化）
            "question_key": str,   # 问题 key
            "answers": [           # 答案选项
                {"key": str, "label": str, "likelihood": dict}
            ]
        }
        或 None（无匹配问题）
    """
    top2 = detection.get("top2", [])
    if len(top2) < 2:
        return None

    best = top2[0].get("label", "")
    second = top2[1].get("label", "")

    if not best or not second:
        return None

    questions = _get_questions_for_pair(best, second)
    if not questions:
        return None

    # 返回第一个问题
    q = questions[0]
    return {
        "best": best,
        "second": second,
        "question": q["question"],
        "question_key": q["key"],
        "answers": q["answers"],
    }


def apply_answer(detection: dict, answer_key: str) -> dict:
    """根据回答更新置信度后验。

    简单贝叶斯式加权的似然修正：
    后验 = (先验 * 似然) / 归一化

    Args:
        detection: 云端服务返回的单个检测框，含 top2 字段
        answer_key: 用户选择的答案 key

    Returns:
        {
            "best": str,           # 更新后的第一候选 label
            "second": str,         # 更新后的第二候选 label
            "confidence": float,   # 更新后的置信度
            "top2": [              # 更新后的 top2
                {"label": str, "score": float},
                {"label": str, "score": float}
            ],
            "likelihood_used": dict,  # 使用的似然修正系数
            "answer_key": str,        # 用户选择的答案 key
        }
    """
    top2 = detection.get("top2", [])
    if len(top2) < 2:
        return {
            "best": detection.get("label", ""),
            "second": "",
            "confidence": detection.get("confidence", 0.0),
            "top2": top2,
            "likelihood_used": {},
            "answer_key": answer_key,
        }

    best = top2[0].get("label", "")
    second = top2[1].get("label", "")
    score1 = top2[0].get("score", 0.0)
    score2 = top2[1].get("score", 0.0)

    # 获取问题库中的似然修正系数
    questions = _get_questions_for_pair(best, second)
    likelihood = {}
    if questions:
        for q in questions:
            for ans in q["answers"]:
                if ans["key"] == answer_key:
                    likelihood = ans["likelihood"]
                    break
            if likelihood:
                break

    # 如果没有找到似然修正系数，返回原结论
    if not likelihood:
        return {
            "best": best,
            "second": second,
            "confidence": score1,
            "top2": top2,
            "likelihood_used": {},
            "answer_key": answer_key,
        }

    # 贝叶斯后验更新
    # 先验 = 模型原始置信度（归一化）
    prior1 = score1 / (score1 + score2) if (score1 + score2) > 0 else 0.5
    prior2 = score2 / (score1 + score2) if (score1 + score2) > 0 else 0.5

    # 似然 = 问题库中的修正系数
    like1 = likelihood.get(best, 0.5)
    like2 = likelihood.get(second, 0.5)

    # 后验 = (先验 * 似然) / 归一化
    post1 = prior1 * like1
    post2 = prior2 * like2
    post_sum = post1 + post2
    post1 = post1 / post_sum if post_sum > 0 else 0.5
    post2 = post2 / post_sum if post_sum > 0 else 0.5

    # 更新后的置信度（归一化到 0-1）
    new_confidence = post1

    # 确定新的 top2 顺序
    if post1 >= post2:
        new_best = best
        new_second = second
    else:
        new_best = second
        new_second = best
        new_confidence = post2

    return {
        "best": new_best,
        "second": new_second,
        "confidence": round(new_confidence, 4),
        "top2": [
            {"label": new_best, "score": round(max(post1, post2), 4)},
            {"label": new_second, "score": round(min(post1, post2), 4)},
        ],
        "likelihood_used": likelihood,
        "answer_key": answer_key,
    }


def get_all_questions_for_pair(label_a: str, label_b: str) -> list[dict] | None:
    """获取病害对对应的全部问题（用于调试或批量处理）。

    Args:
        label_a: 第一候选 label
        label_b: 第二候选 label

    Returns:
        问题列表或 None
    """
    return _get_questions_for_pair(label_a, label_b)


def get_distinguishing_features(label_a: str, label_b: str) -> list[str] | None:
    """获取病害对的区分特征（用于调试或文档生成）。

    Args:
        label_a: 第一候选 label
        label_b: 第二候选 label

    Returns:
        区分特征列表或 None
    """
    pair = sorted([label_a, label_b])
    for item in _QUESTIONS_DATA["pairs"]:
        if sorted(item["pair"]) == pair:
            return item["distinguishing_features"]
    return None


def get_source(label_a: str, label_b: str) -> str | None:
    """获取病害对问题的依据来源。

    Args:
        label_a: 第一候选 label
        label_b: 第二候选 label

    Returns:
        来源字符串或 None
    """
    pair = sorted([label_a, label_b])
    for item in _QUESTIONS_DATA["pairs"]:
        if sorted(item["pair"]) == pair:
            return item["source"]
    return None