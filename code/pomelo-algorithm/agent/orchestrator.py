#!/usr/bin/env python3
"""智能体主编排链路：看图 → 判据 → 鉴别问诊 → 处方引擎 → 文案生成。

这是本项目唯一对外的智能体入口，也是 Token 消耗的主战场：
- 一次图文诊断（必烧）
- 需要开方时一次文案生成（可选烧）
- 追问分支严禁二次调用，避免无意义消耗

无 MAAS_API_KEY / 无数据库 / 未完成处方文案组件时，全部走本地降级，
保证任何环境都能给出可读、合规的结论。
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Protocol

_AGENT_DIR = Path(__file__).resolve().parent
_ROOT = _AGENT_DIR.parent
for _path in (str(_ROOT), str(_AGENT_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from discriminate import apply_answer, needs_clarification, next_question  # noqa: E402
from expert_knowledge import get_advice, get_general_advice, is_quarantine  # noqa: E402
from labelmap import HEALTHY_LABEL  # noqa: E402
from prescription.guardrail import validate_output  # noqa: E402
from vision_client import MaaSClient, validate_diagnosis  # noqa: E402
from vision_prompt import CLASS_CN, VISION_SYSTEM_PROMPT  # noqa: E402

TOKENS_TEMPLATE = {"prompt": 0, "completion": 0, "total": 0, "calls": 0}


class DiagnoseClient(Protocol):
    """图文诊断客户端协议（真实 MaaSClient 或测试 FakeClient）。"""

    def diagnose(self, images, extra_text: str = "", system_prompt: str | None = None) -> dict:
        ...


class Prescriber(Protocol):
    """处方文案组件协议（prescribe_prompt 模块或测试 FakePrescriber）。"""

    def generate_prescription(self, client, diagnosis, allowed, rejected, orchard, month) -> dict:
        ...

    def render_prescription_card(self, result: dict) -> str:
        ...


@dataclass
class AgentResult:
    """一次智能体运行的完整结果。"""

    label: str
    confidence: float
    symptom: str
    distinguish: str
    final_text: str
    prescription: dict | None = None
    question: dict | None = None
    degraded: bool = False
    warnings: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    tokens: dict = field(default_factory=lambda: dict(TOKENS_TEMPLATE))
    detection: dict | None = None


def _as_float(value, default: float = 0.0) -> float:
    """把任意值安全转成 float，失败返回默认值。"""
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return default
    return default


def _as_int(value) -> int:
    """把任意值安全转成 int，失败返回 0。"""
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value.strip()))
        except ValueError:
            return 0
    return 0


def _normalize_detection(diagnosis: dict) -> dict:
    """把大模型诊断结论归一化成 discriminate 需要的 detection（含 top2）。"""
    label = diagnosis.get("label") if isinstance(diagnosis.get("label"), str) else ""
    confidence = _as_float(diagnosis.get("confidence"))
    top2 = [{"label": label, "score": confidence}]

    alternatives = diagnosis.get("alternatives")
    if isinstance(alternatives, list) and alternatives and isinstance(alternatives[0], dict):
        alt = alternatives[0]
        alt_label = alt.get("label") if isinstance(alt.get("label"), str) else ""
        alt_score = _as_float(alt.get("confidence"))
        if alt_label and alt_label != label:
            top2.append({"label": alt_label, "score": alt_score})

    return {"label": label, "confidence": confidence, "bbox": [], "top2": top2}


class PomeloAgent:
    """把诊断、问诊、处方、文案串成一条主链路的编排器。"""

    def __init__(self, client, conn=None, month: int | None = None,
                 conf_floor: float = 0.6, margin: float = 0.15, prescriber=None) -> None:
        """conn=None 表示未接入数据库，自动进入降级模式。"""
        self.client = client
        self.conn = conn
        self.month = month if month is not None else datetime.now().month
        self.conf_floor = conf_floor
        self.margin = margin
        self._prescriber_injected = prescriber
        self._tokens = dict(TOKENS_TEMPLATE)
        self._last_orchard: str | None = None
        self._last_symptom = ""
        self._last_distinguish = ""

    # ---------------------------------------------------------------- 计量

    def _accumulate_tokens(self, payload, count_call: bool = True) -> None:
        """累加一次模型调用的 Token 用量。"""
        payload = payload if isinstance(payload, dict) else {}
        self._tokens["prompt"] += _as_int(payload.get("prompt_tokens"))
        self._tokens["completion"] += _as_int(payload.get("completion_tokens"))
        if count_call:
            self._tokens["calls"] += 1
        self._tokens["total"] = self._tokens["prompt"] + self._tokens["completion"]

    def token_summary(self) -> str:
        """Token 汇总，与 MaaSClient.summary 同风格。"""
        t = self._tokens
        return (f"调用 {t['calls']} 次 | 输入 {t['prompt']} "
                f"| 输出 {t['completion']} | 合计 {t['total']} tokens")

    # ---------------------------------------------------------------- 主链路

    def diagnose(self, images, extra_text: str = "",
                 orchard_name: str | None = None) -> AgentResult:
        """执行完整主链路，任一分支命中即返回。"""
        self._last_orchard = orchard_name
        steps: list[str] = []
        warnings: list[str] = []

        result = self.client.diagnose(
            images, extra_text=extra_text, system_prompt=VISION_SYSTEM_PROMPT
        )
        self._accumulate_tokens(result)
        steps.append("① 调用图文诊断大模型")

        parsed = result.get("parsed") if isinstance(result, dict) else None
        problems = validate_diagnosis(parsed)
        steps.append("② 校验诊断结论类别口径")
        warnings.extend(problems)

        if not isinstance(parsed, dict):
            warnings.append("结论无法解析为 JSON")
            steps.append("③ 结论不可用，输出重拍兜底提示")
            return self._build_result(
                None,
                "图片未能识别，请重拍清晰叶片照片后再试。",
                steps, warnings, degraded=True, skip_guardrail=True,
            )

        label = parsed.get("label") if isinstance(parsed.get("label"), str) else ""
        self._last_symptom = parsed.get("symptom") if isinstance(parsed.get("symptom"), str) else ""
        self._last_distinguish = (
            parsed.get("distinguish") if isinstance(parsed.get("distinguish"), str) else ""
        )

        detection = _normalize_detection(parsed)
        steps.append("③ 归一化为检测对象（含 top2）")
        return self._finalize(detection, orchard_name, parsed, steps, warnings)

    def answer_followup(self, result: AgentResult, answer_key: str,
                        orchard_name: str | None = None) -> AgentResult:
        """鉴别问诊后验更新，置信度足够则继续走收口分支。"""
        if result.detection is None:
            result.warnings.append("缺少检测对象，无法进行后验更新")
            return result

        orchard_name = orchard_name if orchard_name is not None else self._last_orchard
        detection = dict(result.detection)
        updated = apply_answer(detection, answer_key)
        detection["label"] = updated.get("best", detection.get("label", ""))
        detection["confidence"] = _as_float(updated.get("confidence"))
        if isinstance(updated.get("top2"), list):
            detection["top2"] = updated["top2"]

        self._tokens = dict(result.tokens)
        steps = list(result.steps)
        warnings = list(result.warnings)
        steps.append("⑥ 追问后验更新（label/confidence/top2）")

        if detection["confidence"] < self.conf_floor:
            question = next_question(detection)
            return self._branch_ask(detection, {}, steps, warnings, question=question)

        return self._finalize(detection, orchard_name, None, steps, warnings)

    # ---------------------------------------------------------------- 收口

    def _finalize(self, detection: dict, orchard_name: str | None,
                  diagnosis: dict | None, steps: list[str],
                  warnings: list[str]) -> AgentResult:
        """八分支短路口序：问诊 → 健康 → 检疫 → 开方/无药 → 降级。"""
        diagnosis = diagnosis if isinstance(diagnosis, dict) else {}
        label = detection.get("label", "")
        confidence = _as_float(detection.get("confidence"))

        needs_ask = (
            confidence < self.conf_floor
            or diagnosis.get("need_more_info") is True
            or diagnosis.get("image_quality") == "poor"
            or needs_clarification(detection, self.margin)
        )
        if needs_ask:
            question = next_question(detection)
            return self._branch_ask(detection, diagnosis, steps, warnings, question=question)

        if label == HEALTHY_LABEL:
            return self._branch_healthy(detection, steps, warnings)

        if is_quarantine(label):
            return self._branch_quarantine(detection, steps, warnings)

        if self.conn is not None and orchard_name:
            return self._branch_prescribe(detection, orchard_name, steps, warnings)

        reason = "no_db" if self.conn is None else "no_orchard"
        return self._branch_fallback_advice(detection, reason, steps, warnings)

    def _branch_ask(self, detection: dict, diagnosis: dict, steps: list[str],
                    warnings: list[str], question: dict | None = None) -> AgentResult:
        """B2 鉴别问诊：不调处方引擎、不二次请求模型。"""
        text = ""
        follow = diagnosis.get("follow_up_question")
        if isinstance(follow, str) and follow.strip():
            text = follow.strip()
        elif question:
            text = question["question"]
        else:
            text = "图片置信度不足，请补拍一张叶背清晰照片以便进一步鉴别。"
        if self._last_symptom:
            text += f"\n症状：{self._last_symptom}"
        if self._last_distinguish:
            text += f"\n区分点：{self._last_distinguish}"
        steps.append("④-1 判定进入鉴别问诊分支")
        return self._build_result(detection, text, steps, warnings, question=question)

    def _branch_healthy(self, detection: dict, steps: list[str],
                        warnings: list[str]) -> AgentResult:
        """B3 健康结论：输出当月常规养护建议，不查库。"""
        advice = get_general_advice(self.month)
        text = "未检出目标病害。"
        if advice:
            text += advice
        steps.append("④-5 健康结论，输出当月常规养护建议")
        return self._build_result(detection, text, steps, warnings, skip_guardrail=True)

    def _branch_quarantine(self, detection: dict, steps: list[str],
                           warnings: list[str]) -> AgentResult:
        """B4 检疫性病害：硬编码四要点，不取知识库药剂文本。"""
        text = (
            "该病害为检疫性病害，务必按以下四点处置：\n"
            "1. 立即上报当地植保/农业部门；\n"
            "2. 先防除树上木虱，再挖除病株并集中销毁；\n"
            "3. 防治传播媒介柑橘木虱，统一放梢、见虫即治；\n"
            "4. 黄龙病无药可治，不可依赖施药；新植须选用无病苗木。"
        )
        steps.append("④-6 检疫性病害，输出上报与防木虱指引")
        return self._build_result(detection, text, steps, warnings, skip_guardrail=True)

    def _branch_prescribe(self, detection: dict, orchard_name: str,
                          steps: list[str], warnings: list[str]) -> AgentResult:
        """B5 规则引擎开方：先过滤，再文案；文案组件缺失走 D1。"""
        label = detection.get("label", "")
        try:
            from prescription.load_from_db import run_prescription
        except ImportError:
            warnings.append("未加载数据库适配层，处方未经规则校验")
            return self._branch_fallback_advice(detection, "no_db", steps, warnings)

        try:
            outcome = run_prescription(self.conn, label, orchard_name, date.today())
        except ValueError as exc:
            warnings.append(str(exc))
            steps.append("④-4 规则引擎过滤失败，转入降级")
            return self._branch_fallback_advice(detection, "no_orchard", steps, warnings)

        steps.append("④-4 规则引擎过滤候选药剂")
        allowed = list(getattr(outcome, "allowed", []) or [])
        rejected = list(getattr(outcome, "rejected", []) or [])

        if not allowed:
            return self._branch_no_pesticide(detection, rejected, steps, warnings)

        prescriber = self._load_prescriber()
        if prescriber is None:
            return self._branch_local_card(detection, orchard_name, allowed, steps, warnings)

        diagnosis = {
            "label": label,
            "confidence": _as_float(detection.get("confidence")),
            "symptom": self._last_symptom,
            "distinguish": self._last_distinguish,
            "is_quarantine": is_quarantine(label),
        }
        try:
            reviewed = prescriber.generate_prescription(
                self.client, diagnosis, allowed, rejected, orchard_name, self.month
            )
        except RuntimeError as exc:
            warnings.append(f"处方文案生成失败：{exc}")
            return self._branch_local_card(detection, orchard_name, allowed, steps, warnings)

        self._accumulate_tokens(reviewed)
        text = prescriber.render_prescription_card(reviewed)
        steps.append("⑤ 生成/渲染处方卡片")
        whitelist = self._build_whitelist(reviewed, allowed)
        return self._build_result(
            detection, text, steps, warnings,
            prescription=reviewed, whitelist=whitelist,
        )

    def _branch_no_pesticide(self, detection: dict, rejected: list,
                             steps: list[str], warnings: list[str]) -> AgentResult:
        """B6 无合规可用药剂：固定文案，跳过护栏。"""
        text = "当前条件下无合规可用药剂，请联系当地农技人员。"
        warnings.append("全部候选药剂被规则拒绝（安全间隔期/抗药性/次数上限/物候期/配伍禁忌）")
        steps.append("⑤-1 无合规可用药剂，输出降级提示")
        prescription = {
            "allowed": [],
            "rejected": rejected,
            "source": "local_rule_engine",
            "used_fallback": True,
        }
        return self._build_result(
            detection, text, steps, warnings,
            prescription=prescription, degraded=True, skip_guardrail=True,
        )

    def _branch_local_card(self, detection: dict, orchard_name: str,
                           allowed: list, steps: list[str],
                           warnings: list[str]) -> AgentResult:
        """D1 处方文案组件缺失时的规则引擎直出卡片。"""
        text = self._render_local_card(allowed, orchard_name, detection.get("label", ""))
        whitelist = [getattr(item, "common_name", "") for item in allowed]
        whitelist = [name for name in whitelist if name]
        warnings.append("文案生成组件缺失，处方为规则引擎直出")
        steps.append("⑤ 本地直出处方卡片（未调用文案生成）")
        prescription = {
            "parsed": None,
            "text": text,
            "used_fallback": True,
            "source": "local_rule_engine",
            "allowed": allowed,
        }
        return self._build_result(
            detection, text, steps, warnings,
            prescription=prescription, degraded=True, whitelist=whitelist,
        )

    def _branch_fallback_advice(self, detection: dict, reason: str,
                                steps: list[str], warnings: list[str]) -> AgentResult:
        """B7/D0 未接数据库、B8/D2 缺地块名：专家知识库三段建议。"""
        label = detection.get("label", "")
        advice = get_advice(label, "occurred")
        text = (
            f"{advice.prevention_measures}\n{advice.medication_advice}\n"
            f"{advice.farming_advice}\n数据来源：{advice.data_source}"
        )
        if reason == "no_db":
            warnings.append("未接数据库，处方未经安全间隔期/抗药性/复配禁忌校验")
        else:
            warnings.append("未提供地块名，未走处方引擎，已改用专家库通用防治建议")
        steps.append("④-7 进入降级路径，改用专家库防治建议")
        return self._build_result(
            detection, text, steps, warnings, degraded=True, whitelist=[],
        )

    # ---------------------------------------------------------------- 辅助

    def _load_prescriber(self):
        """惰性加载处方文案组件；注入点优先，缺失返回 None。"""
        if self._prescriber_injected is not None:
            return self._prescriber_injected
        try:
            from agent import prescribe_prompt as module
        except ImportError:
            try:
                import prescribe_prompt as module
            except ImportError:
                return None
        return module

    def _render_local_card(self, allowed: list, block_name: str, pest_name: str) -> str:
        """仅用规则引擎放行药剂渲染本地卡片，从源头杜绝幻觉。"""
        lines = [
            "【防治方案·规则引擎直出】",
            f"地块：{block_name}",
            f"防治对象：{CLASS_CN.get(pest_name, pest_name)}",
            "可选成分：",
        ]
        for index, item in enumerate(allowed, 1):
            name = getattr(item, "common_name", "")
            content = getattr(item, "content", "") or ""
            phi = getattr(item, "phi_days", None)
            if phi is None:
                detail = f"{content}，安全间隔期按当地指导" if content else "安全间隔期按当地指导"
            elif content:
                detail = f"{content}，安全间隔期 {phi} 天"
            else:
                detail = f"安全间隔期 {phi} 天"
            lines.append(f"  {index}. {name}（{detail}）")
        lines.append("数据来源：规则引擎本地直出（未经文案生成组件润色）")
        return "\n".join(lines)

    def _build_whitelist(self, prescription, allowed) -> list[str]:
        """白名单 = 处方结构化药名 ∪ 规则引擎放行通用名。"""
        names: list[str] = []
        if isinstance(prescription, dict):
            parsed = prescription.get("parsed")
            if isinstance(parsed, dict):
                items = parsed.get("prescription")
                if isinstance(items, list):
                    for item in items:
                        if isinstance(item, dict):
                            name = item.get("pesticide_name")
                            if isinstance(name, str) and name.strip():
                                names.append(name.strip())
        for item in allowed or []:
            name = item.get("common_name") if isinstance(item, dict) else getattr(item, "common_name", None)
            if isinstance(name, str) and name.strip():
                names.append(name.strip())
        return list(dict.fromkeys(names))

    def _apply_guardrail(self, text: str, whitelist: list[str]) -> tuple[str, list[str]]:
        """出口护栏：拦白名单外药名，返回（最终文本, 告警）。"""
        if not text:
            return text, []
        result = validate_output(text, whitelist)
        if result.get("is_valid"):
            return text, []
        violations = result.get("violations", [])
        warning = f"出口护栏拦截白名单外药名：{violations}"
        return result.get("suggested_text", text), [warning]

    def _build_result(self, detection: dict | None, text: str, steps: list[str],
                      warnings: list[str], *, prescription: dict | None = None,
                      question: dict | None = None, degraded: bool = False,
                      skip_guardrail: bool = False,
                      whitelist: list[str] | None = None) -> AgentResult:
        """统一出口：护栏复核 + 组装 AgentResult。"""
        if not skip_guardrail:
            text, guard_warnings = self._apply_guardrail(text, whitelist or [])
            warnings.extend(guard_warnings)
        return AgentResult(
            label=detection.get("label", "") if detection else "",
            confidence=_as_float(detection.get("confidence")) if detection else 0.0,
            symptom=self._last_symptom,
            distinguish=self._last_distinguish,
            final_text=text,
            prescription=prescription,
            question=question,
            degraded=degraded,
            warnings=list(warnings),
            steps=list(steps),
            tokens=dict(self._tokens),
            detection=detection,
        )


def main(argv: list[str] | None = None) -> int:
    """命令行入口：打印诊断、处方、Token 与告警。"""
    parser = argparse.ArgumentParser(description="柚子病虫害智能体主编排链路")
    parser.add_argument("--image", required=True, help="柚子叶片图片路径或公网 URL")
    parser.add_argument("--extra", default="", help="补充描述，如'叶背也有斑'")
    parser.add_argument("--orchard", default=None, help="地块名（需数据库）")
    parser.add_argument("--month", type=int, default=None, help="月份（默认当前月）")
    parser.add_argument("--json", default=None, help="结果写入 JSON 文件")
    args = parser.parse_args(argv)

    try:
        client = MaaSClient()
    except RuntimeError:
        print("未配置 MAAS_API_KEY，无法调用华为云 MaaS。")
        print("  1) 登录华为云控制台 → MaaS → API Keys → 创建并复制")
        print('  2) 本机执行：setx MAAS_API_KEY "你的Key"')
        print("  注意：模型服务、Key、调用地址必须同一区域。")
        return 1

    agent = PomeloAgent(client, month=args.month)
    try:
        result = agent.diagnose([args.image], extra_text=args.extra,
                                orchard_name=args.orchard)
    except FileNotFoundError as exc:
        print(f"图片不存在：{exc}")
        return 2
    except ValueError as exc:
        print(f"输入有误：{exc}")
        return 2

    cn = CLASS_CN.get(result.label, "")
    print(f"诊断结论：{result.label} {cn}（置信度 {result.confidence:.2f}）")
    print(f"症状：{result.symptom or '—'}")
    print(f"区分点：{result.distinguish or '—'}")
    print("")
    print(result.final_text)
    print("")
    print(agent.token_summary())
    if result.degraded:
        print("[降级] 本次结果未经过完整链路")
    if result.warnings:
        print("告警：")
        for warning in result.warnings:
            print(f"  - {warning}")

    if args.json:
        payload = dataclasses.asdict(result)
        Path(args.json).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"结果已写入：{args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())