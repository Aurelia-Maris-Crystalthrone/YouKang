"""质保方案生成 CLI（spec 5.7、design 模块 G、接口 12）。

根据月份查询专家知识库，生成结构化质保方案 JSON（spec 6.7）。
纯 Python 标准库 + labelmap.py + expert_knowledge.py，离线可用。

用法：
    python generate_prevention_plan.py --month 7
    python generate_prevention_plan.py --month 7 --detected anthracnose
    python generate_prevention_plan.py --month 7 --detected anthracnose,red_spider_mite
"""
import argparse
import json
import sys

import labelmap
import expert_knowledge


def _normalize_label_key(name: str) -> str | None:
    """大小写不敏感；空格与连字符统一为下划线。非字符串返回 None。"""
    if not isinstance(name, str):
        return None
    key = name.strip().lower().replace("-", "_")
    return "_".join(key.split())


def _parse_detected(raw: str | None) -> tuple[set[str], int]:
    """解析 --detected 参数，返回 (合法 label 集合, 非法 label 计数)。

    双重口径（design 1.2.3）：
      1. normalize_class_name 返回非 None → 检测类（red_spider_mite/anthracnose/canker/greening）
      2. 归一化后键等于 HEALTHY_LABEL → healthy
    非法 label 丢弃不报错退出（spec 5.7.3-2）。
    """
    if not raw:
        return set(), 0
    detected_set: set[str] = set()
    ignored = 0
    for token in raw.split(","):
        label = token.strip()
        if not label:
            continue
        key = _normalize_label_key(label)
        class_id = labelmap.normalize_class_name(label)
        if class_id is not None:
            detected_set.add(labelmap.CLASS_NAMES[class_id])
        elif key == labelmap.HEALTHY_LABEL:
            detected_set.add(labelmap.HEALTHY_LABEL)
        else:
            ignored += 1
    return detected_set, ignored


def _build_risk_item(label: str, status: str) -> dict:
    """组装单个 RiskItem（spec 6.7-3/4）。

    is_quarantine 为 true 时上层必须输出上报提示（greening = 柑橘黄龙病）；
    data_source 为合规字段，须随建议一并透出，供合规护栏校验。
    """
    advice = expert_knowledge.get_advice(label, status)
    return {
        "label": label,
        "status": status,
        "is_quarantine": expert_knowledge.is_quarantine(label),
        "prevention_measures": advice.prevention_measures,
        "medication_advice": advice.medication_advice,
        "farming_advice": advice.farming_advice,
        "data_source": advice.data_source,
    }


def generate_plan(month: int, detected: set[str]) -> dict:
    """生成质保方案字典（spec 6.7-1）。

    month: 1-12 月份整数。
    detected: 已归一化的合法 label 集合（检测类 4 类；healthy 允许传入但会被忽略，
    因其非模型输出类别，见 labelmap 体系说明 1）。
    """
    risk_pests = expert_knowledge.get_risk_labels(month)

    risks: list[dict] = []
    covered_labels: set[str] = set()

    for pest in risk_pests:
        status = "occurred" if pest in detected else "prevention"
        risks.append(_build_risk_item(pest, status))
        covered_labels.add(pest)

    for pest in detected:
        if pest == labelmap.HEALTHY_LABEL or pest in covered_labels:
            continue
        risks.append(_build_risk_item(pest, "occurred"))
        covered_labels.add(pest)

    return {
        "month": month,
        # 无特定病虫害风险期（1/2/3/11/12 月）：risks 必然为空，
        # 上层据此直接输出常规养护建议，不得表述为"检出健康"
        "is_no_risk_month": expert_knowledge.is_no_risk_month(month),
        "risks": risks,
        "general_advice": expert_knowledge.get_general_advice(month),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="根据月份生成柚子病虫害预防质保方案（spec 5.7）",
    )
    parser.add_argument("--month", type=int, required=True, help="月份，1-12 整数（必选）")
    parser.add_argument("--detected", type=str, default=None, help="已检测到的病虫害 label 列表，逗号分隔（可选）")
    args = parser.parse_args()

    if not (1 <= args.month <= 12):
        print("错误：月份取值无效应为 1-12 整数", file=sys.stderr)
        sys.exit(1)

    detected_set, ignored = _parse_detected(args.detected)
    if ignored > 0:
        print(f"提示：已忽略 {ignored} 个非法识别结果", file=sys.stderr)

    plan = generate_plan(args.month, detected_set)
    print(json.dumps(plan, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()