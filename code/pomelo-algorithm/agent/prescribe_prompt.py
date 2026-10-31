#!/usr/bin/env python3
"""处方文案生成组件（指令 A）。

职责：把规则引擎算出的"可用/禁用"药剂列表，交给大模型翻译成柚农读得懂的处方卡片。

为什么要这个组件，而不是让编排层直接把 allowed 列表拼成文本？
    规则引擎的输出是结构化的（药名/含量/稀释倍数/PHI），但柚农需要的是
    "先打哪个、隔几天再打哪个、为什么这个药不能用"这样的连贯说明。
    这一层由大模型来做最合适——但正因为它由大模型做，就必须有硬护栏：
    模型只能从 allowed 里选药，稀释倍数只能照抄输入，不许编。

设计要点（对应 spec 5.1/5.2/5.3）：
1. payload 里每个药剂都带上含量/稀释倍数/方法/时机/PHI/毒性，
   不给模型"自由发挥数值"的空间——它没得编，只能抄。
2. 护栏（guardrail.validate_output）卡在模型输出之后、渲染之前，
   白名单外的药名一律替换，两次不过就降级到本地模板。
3. 降级模板 FALLBACK_TEMPLATE 零大模型参与，纯拼装，
   保证在没有 API Key、401、网络故障时依然能给出合规处方。

契约说明（重要）：
    编排层 agent/orchestrator.py 以位置参数调用 generate_prescription，
    第 5 个实参传的是**地块名字符串**（orchard_name），而 spec 6.4 描述的是
    Orchard 对象。两者不一致会导致主链路 AttributeError。
    因此本模块对第 5 个参数做类型自适应：字符串 / Orchard 对象 / dict / None
    全部接受，统一归一化后再用。这样 spec 与编排层的契约同时成立。
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Optional

_AGENT_DIR = Path(__file__).resolve().parent
_ROOT = _AGENT_DIR.parent
for _path in (str(_ROOT), str(_AGENT_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

try:  # 护栏是最后一道闸，必须能用；导入失败时由调用方自行兜底
    from prescription.guardrail import validate_output
except ImportError:  # pragma: no cover - 独立使用时缺少包路径
    validate_output = None  # type: ignore[assignment]

try:  # 复用视觉客户端的宽松 JSON 解析，避免重复实现
    from vision_client import parse_json_relaxed
except ImportError:  # pragma: no cover
    def parse_json_relaxed(text: str) -> Any:  # type: ignore[misc]
        """导入失败时的极简回退，保证本模块不依赖 requests。"""
        s = (text or "").strip()
        if s.startswith("```"):
            s = s.strip("`")
            if s.lower().startswith("json"):
                s = s[4:]
            s = s.strip()
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            start, end = s.find("{"), s.rfind("}")
            if start >= 0 and end > start:
                try:
                    return json.loads(s[start:end + 1])
                except json.JSONDecodeError:
                    return None
        return None

try:
    from vision_prompt import CLASS_CN
except ImportError:  # pragma: no cover
    CLASS_CN = {
        "red_spider_mite": "红蜘蛛",
        "anthracnose": "炭疽病",
        "canker": "溃疡病",
        "greening": "黄龙病",
    }

# payload 外层包裹语（spec 5.1.1-5：payload 以该句开头）
PAYLOAD_HEADER = "请严格按系统提示词输出 JSON。"

# 模型输出 schema 要求的 8 个键（spec 6.5）
PARSED_REQUIRED_KEYS = (
    "diagnosis_summary",
    "prescription",
    "application_order",
    "precautions",
    "rejected_explanation",
    "non_chemical_advice",
    "disclaimer",
    "data_source",
)

FALLBACK_NO_DRUG = "暂无可用药剂，请咨询当地农技人员。"
DEGRADED_MARK = "[降级输出] 本次未调用大模型，为规则引擎直出方案。"
DISCLAIMER = "本建议仅供参考，药剂以当地植保站意见为准。"


PRESCRIPTION_SYSTEM_PROMPT = """你是一名资深柑橘植保技术员，负责把结构化数据翻译成柚农看得懂的处方。

# 任务
读取输入 JSON 里已通过安全校验的药剂列表，生成一份施药处方。

# 硬约束（违反即视为失败）
1. **只能从输入 JSON 的 allowed_pesticides 里选药**，药名一字都不许改，
   禁止推荐 allowed_pesticides 之外的任何药剂，禁止自创药名。
2. 稀释倍数 / 施用方法 / 施用时机**只能照抄输入 JSON 给的字段**；
   输入里没有就填 null，不许自己编数字、不许写"约""大概"这类模糊用量。
3. rejected_pesticides 里的药**只能出现在 rejected_explanation 段落**，
   且必须原样引用其中的 reason 文字，不许改写成"效果不好"这类模糊说法。
4. **当 disease 为 greening（黄龙病）时禁止输出任何治疗药剂**：
   黄龙病是检疫性病害，无药可治。只能写：立即上报当地植保部门、
   挖除病株并集中销毁、防治柑橘木虱、选用无病苗木。
5. 不得推荐未登记作物、未登记含量的用法，不得推荐具体品牌或商品名。
6. 只输出 JSON，不要加 ``` 标记，不要加任何前后缀文字。

# 输出格式（严格 JSON）
{
  "diagnosis_summary": "一句话说明诊断结论与严重度（≤40 字）",
  "prescription": [
    {
      "pesticide_name": "必须来自 allowed_pesticides 的 common_name",
      "dilution_ratio": "照抄输入，缺失填 null",
      "application_method": "照抄输入，缺失填 null",
      "application_timing": "照抄输入，缺失填 null",
      "phi_days": "照抄输入的安全间隔期天数，缺失填 null",
      "toxicity_level": "照抄输入的毒性等级，缺失填 null"
    }
  ],
  "application_order": "多种药时的先后顺序与间隔天数（≤40 字）",
  "precautions": "注意事项，含防护用具、施药天气、安全间隔期（≤120 字）",
  "rejected_explanation": "为什么某些常用药这次不能用，原样引用 reason（≤60 字）",
  "non_chemical_advice": "农业与物理防治措施（≤60 字）",
  "disclaimer": "本建议仅供参考，药剂以当地植保站意见为准。",
  "data_source": "照抄输入 JSON 的 data_source 字段"
}
"""


FALLBACK_TEMPLATE = """【处方·规则引擎直出】
地块：{block_name}
防治对象：{pest_cn}（置信度 {confidence}）
症状：{symptom}
区分要点：{distinguish}

【可用药剂】
{allowed_block}

【不可用药剂及原因】
{rejected_block}

【提示】
距采收天数：{days_until_harvest}；当前物候期：{phenophase}。
{disclaimer}
数据来源：规则引擎本地直出（未经文案生成组件润色）。
"""


# ---------------------------------------------------------------- 归一化辅助

def _get(obj: Any, key: str, default: Any = None) -> Any:
    """从 dataclass / dict / 任意对象取值，取不到给默认值。"""
    if obj is None:
        return default
    if isinstance(obj, dict):
        value = obj.get(key, default)
    else:
        value = getattr(obj, key, default)
    return default if value is None else value


def _resolve_orchard(orchard: Any) -> dict:
    """把第 5 个参数归一化成地块信息字典。

    编排层传的是地块名字符串，spec 描述的是 Orchard 对象，两者都要支持；
    传 None 或空字符串时退化为"未知地块"，不抛异常。
    """
    if isinstance(orchard, str):
        return {
            "block_name": orchard or "未知地块",
            "variety": "",
            "tree_age": None,
            "current_phenophase": "",
            "expected_harvest_date": None,
            "area_mu": None,
        }
    if orchard is None:
        return _resolve_orchard("")
    return {
        "block_name": _get(orchard, "block_name", "未知地块"),
        "variety": _get(orchard, "variety", ""),
        "tree_age": _get(orchard, "tree_age"),
        "current_phenophase": _get(orchard, "current_phenophase", ""),
        "expected_harvest_date": _get(orchard, "expected_harvest_date"),
        "area_mu": _get(orchard, "area_mu"),
    }


def _days_until_harvest(expected: Any, today: date) -> Optional[int]:
    """距采收天数；无预计采收日期返回 None。"""
    if expected is None:
        return None
    if isinstance(expected, str):
        try:
            expected = date.fromisoformat(expected)
        except ValueError:
            return None
    if isinstance(expected, datetime):
        expected = expected.date()
    if not isinstance(expected, date):
        return None
    return (expected - today).days


def _pesticide_entry(item: Any) -> dict:
    """单个候选药剂 → payload 条目（spec 5.1.1-2 的 8 个字段）。"""
    return {
        "common_name": _get(item, "common_name", ""),
        "active_ingredient": _get(item, "active_ingredient", ""),
        "content": _get(item, "content", ""),
        "formulation": _get(item, "formulation", ""),
        "dilution_ratio": _get(item, "dilution_ratio"),
        "application_method": _get(item, "application_method"),
        "application_timing": _get(item, "application_timing"),
        "phi_days": _get(item, "phi_days"),
        "toxicity_level": _get(item, "toxicity_level"),
    }


# ---------------------------------------------------------------- 5.1 载荷构建

def build_prescription_payload(
    diagnosis: dict,
    allowed: Iterable[Any],
    rejected: Iterable[Any],
    orchard: Any,
    month: int,
    extra: Optional[dict] = None,
    today: Optional[date] = None,
) -> str:
    """构造送给大模型的中文 JSON 载荷。

    Args:
        diagnosis: 诊断结论（label / confidence / symptom / distinguish / is_quarantine）
        allowed: 规则引擎放行的药剂（Pesticide 或等价 dict）
        rejected: 规则引擎拒绝的药剂（FilterResult 或等价 dict），只取 name 与 reason
        orchard: 地块名字符串 / Orchard 对象 / dict / None
        month: 月份，用于月度农事提醒
        extra: 附加字段（如 data_source），合并进载荷顶层
        today: 计算距采收天数的基准日期，默认今天

    Returns:
        以 PAYLOAD_HEADER 开头、以 JSON 正文续接的字符串（ensure_ascii=False, indent=2）
    """
    today = today or date.today()
    info = _resolve_orchard(orchard)
    days = _days_until_harvest(info["expected_harvest_date"], today)

    payload: dict = {
        "diagnosis": {
            "label": _get(diagnosis, "label", ""),
            "label_cn": CLASS_CN.get(_get(diagnosis, "label", ""), ""),
            "confidence": _get(diagnosis, "confidence", 0.0),
            "symptom": _get(diagnosis, "symptom", ""),
            "distinguish": _get(diagnosis, "distinguish", ""),
            "is_quarantine": bool(_get(diagnosis, "is_quarantine", False)),
        },
        "allowed_pesticides": [_pesticide_entry(p) for p in allowed or []],
        "rejected_pesticides": [
            {"name": _get(r, "name", ""), "reason": _get(r, "reason", "")}
            for r in rejected or []
        ],
        "orchard": {
            "block_name": info["block_name"],
            "variety": info["variety"],
            "tree_age": info["tree_age"],
            "current_phenophase": info["current_phenophase"],
            "expected_harvest_date": (
                info["expected_harvest_date"].isoformat()
                if isinstance(info["expected_harvest_date"], (date, datetime))
                else None
            ),
            "area_mu": info["area_mu"],
            "days_until_harvest": days if days is not None else "未知",
        },
        "month": month,
    }
    if extra:
        payload.update(extra)

    body = json.dumps(payload, ensure_ascii=False, indent=2)
    return f"{PAYLOAD_HEADER}\n{body}"


# ---------------------------------------------------------------- 5.2 处方生成

def _fallback_text(diagnosis: dict, allowed: list, rejected: list,
                   orchard: Any, month: int, today: date) -> str:
    """纯本地降级文本：只用规则引擎已放行的数据拼装，零幻觉。"""
    info = _resolve_orchard(orchard)
    days = _days_until_harvest(info["expected_harvest_date"], today)
    label = _get(diagnosis, "label", "")

    if allowed:
        lines = []
        for index, item in enumerate(allowed, 1):
            name = _get(item, "common_name", "")
            content = _get(item, "content", "") or ""
            phi = _get(item, "phi_days")
            dilution = _get(item, "dilution_ratio") or ""
            parts = [p for p in (content, f"{dilution}倍液" if dilution else "",
                                 f"安全间隔期 {phi} 天" if phi is not None else "")
                     if p]
            detail = "，".join(parts) if parts else "按当地农技人员指导"
            lines.append(f"  {index}. {name}（{detail}）")
        allowed_block = "\n".join(lines)
    else:
        allowed_block = f"  {FALLBACK_NO_DRUG}"

    if rejected:
        rejected_block = "\n".join(
            f"  ✗ {_get(r, 'name', '')}：{_get(r, 'reason', '')}" for r in rejected
        )
    else:
        rejected_block = "  本次无被拒绝药剂。"

    return FALLBACK_TEMPLATE.format(
        block_name=info["block_name"],
        pest_cn=CLASS_CN.get(label, label),
        confidence=_get(diagnosis, "confidence", 0.0),
        symptom=_get(diagnosis, "symptom", "") or "（未描述）",
        distinguish=_get(diagnosis, "distinguish", "") or "（未描述）",
        allowed_block=allowed_block,
        rejected_block=rejected_block,
        days_until_harvest=days if days is not None else "未知",
        phenophase=info["current_phenophase"] or "未知",
        disclaimer=DISCLAIMER,
    )


def generate_prescription(
    client: Any,
    diagnosis: dict,
    allowed: Iterable[Any],
    rejected: Iterable[Any],
    orchard: Any,
    month: int,
    temperature: float = 0.2,
    today: Optional[date] = None,
) -> dict:
    """生成处方文案：大模型翻译 + 护栏复核 + 失败降级。

    Args:
        client: MaaSClient（需实现 chat(content, system, temperature, max_tokens, model)）
        diagnosis: 诊断结论 dict
        allowed: 规则引擎放行的药剂列表
        rejected: 规则引擎拒绝的药剂列表
        orchard: 地块名字符串 / Orchard 对象 / dict / None
        month: 月份
        temperature: 采样温度，spec 固定 0.2
        today: 基准日期（测试可注入）

    Returns:
        dict，含 text / parsed / tokens / prompt_tokens / completion_tokens /
        total_tokens / guardrail / used_fallback / warnings / model
        其中 prompt_tokens 与 completion_tokens 是编排层累计 Token 的依据，
        字段名不可更改（orchestrator._accumulate_tokens 按这两个 key 取值）。
    """
    today = today or date.today()
    diagnosis = diagnosis if isinstance(diagnosis, dict) else {}
    allowed = list(allowed or [])
    rejected = list(rejected or [])
    warnings: list[str] = []

    label = _get(diagnosis, "label", "")
    is_greening = bool(_get(diagnosis, "is_quarantine", False)) or label == "greening"

    payload = build_prescription_payload(
        diagnosis, allowed, rejected, orchard, month, today=today
    )

    # 白名单：黄龙病场景传空列表——不该出现任何药剂（spec 5.2.1-12）
    whitelist = [] if is_greening else [
        name for name in (_get(p, "common_name", "") for p in allowed) if name
    ]

    empty_result = {
        "text": "",
        "parsed": None,
        "tokens": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "guardrail": {"is_valid": True, "detected": [], "violations": []},
        "used_fallback": True,
        "warnings": warnings,
        "model": "",
    }

    # ---- 调用大模型（失败一律降级，不向上抛）
    try:
        resp = client.chat(
            [{"type": "text", "text": payload}],
            system=PRESCRIPTION_SYSTEM_PROMPT,
            temperature=temperature,
            max_tokens=1200,
        )
    except RuntimeError as exc:
        warnings.append(f"处方文案生成失败：{exc}")
        empty_result["text"] = _fallback_text(
            diagnosis, allowed, rejected, orchard, month, today
        )
        return empty_result

    resp = resp if isinstance(resp, dict) else {}
    prompt_tokens = int(resp.get("prompt_tokens") or 0)
    completion_tokens = int(resp.get("completion_tokens") or 0)
    text_raw = resp.get("text") or ""

    parsed = parse_json_relaxed(text_raw)
    if not isinstance(parsed, dict):
        warnings.append("JSON解析失败，已降级为规则引擎直出")
        return {
            **empty_result,
            "text": _fallback_text(diagnosis, allowed, rejected, orchard, month, today),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "tokens": prompt_tokens + completion_tokens,
            "model": resp.get("model", ""),
        }

    # ---- 护栏：先整体校验，不过则用 suggested_text 复核一次
    guard: dict = {"is_valid": True, "detected": [], "violations": [], "suggested_text": ""}
    if validate_output is not None:
        guard = validate_output(json.dumps(parsed, ensure_ascii=False), whitelist)
        if not guard.get("is_valid"):
            suggested = guard.get("suggested_text") or ""
            guard2 = validate_output(suggested, whitelist)
            if guard2.get("is_valid"):
                # 关键：护栏替换的是字符串，若不同步回 parsed，渲染时会把原药名
                # 原样带回来，护栏就白做了。这里用替换后的文本重建 parsed。
                fixed = parse_json_relaxed(suggested)
                if isinstance(fixed, dict):
                    parsed = fixed
                warnings.append(f"护栏拦截并已替换违规药名：{guard.get('violations')}")
                guard = guard2
            else:
                guard = guard2
                warnings.append("护栏两次拦截，已降级为规则引擎直出")
                return {
                    **empty_result,
                    "text": _fallback_text(
                        diagnosis, allowed, rejected, orchard, month, today
                    ),
                    "guardrail": guard,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                    "tokens": prompt_tokens + completion_tokens,
                    "model": resp.get("model", ""),
                }

    # ---- 清洗：白名单外药名剔除；黄龙病强制清空
    items = parsed.get("prescription")
    if isinstance(items, list):
        kept = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("pesticide_name")
            if not isinstance(name, str) or not name.strip():
                continue
            if name.strip() not in whitelist:
                warnings.append(f"药名不在白名单内，已剔除：{name}")
                continue
            kept.append(item)
        parsed["prescription"] = kept
    else:
        parsed["prescription"] = []

    if is_greening and parsed["prescription"]:
        warnings.append("黄龙病场景已清空治疗药剂")
        parsed["prescription"] = []

    text = render_prescription_card({
        "text": text_raw, "parsed": parsed, "used_fallback": False, "warnings": warnings,
    })

    return {
        "text": text,
        "parsed": parsed,
        "tokens": prompt_tokens + completion_tokens,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "guardrail": guard,
        "used_fallback": False,
        "warnings": warnings,
        "model": resp.get("model", ""),
    }


# ---------------------------------------------------------------- 5.3 卡片渲染

def render_prescription_card(result: dict) -> str:
    """把生成结果渲染成柚农可读的纯文本卡片。

    顺序：诊断结论 → 用药方案 → 施药顺序 → 注意事项 → 不可用说明 → 数据来源 → 免责声明
    """
    result = result if isinstance(result, dict) else {}
    parsed = result.get("parsed")
    warnings = result.get("warnings") or []
    used_fallback = bool(result.get("used_fallback"))

    # 降级路径：直接展示降级文本，但必须补齐数据来源与免责声明
    if not isinstance(parsed, dict):
        lines = [result.get("text") or ""]
        lines.append("")
        lines.append("数据来源：规则引擎本地直出")
        lines.append(f"免责声明：{DISCLAIMER}")
        if used_fallback:
            lines.append(DEGRADED_MARK)
        return "\n".join(line for line in lines if line is not None).strip()

    items = parsed.get("prescription")
    items = items if isinstance(items, list) else []

    lines: list[str] = []
    lines.append("【诊断结论】")
    lines.append(f"  {parsed.get('diagnosis_summary') or '（未给出）'}")
    lines.append("")

    lines.append("【用药方案】")
    if items:
        for index, item in enumerate(items, 1):
            name = item.get("pesticide_name") or ""
            dilution = item.get("dilution_ratio")
            method = item.get("application_method")
            timing = item.get("application_timing")
            phi = item.get("phi_days")
            detail_bits = []
            if dilution:
                detail_bits.append(f"{dilution}")
            if method:
                detail_bits.append(f"{method}")
            if timing:
                detail_bits.append(f"{timing}")
            if phi is not None:
                detail_bits.append(f"安全间隔期 {phi} 天")
            detail = "，".join(detail_bits) if detail_bits else "按当地农技人员指导"
            lines.append(f"  {index}. {name}（{detail}）")
    else:
        lines.append(f"  {FALLBACK_NO_DRUG}")
    lines.append("")

    lines.append("【施药顺序】")
    lines.append(f"  {parsed.get('application_order') or '按标签说明施用，避免重复用药。'}")
    lines.append("")

    lines.append("【注意事项】")
    precautions = parsed.get("precautions")
    if isinstance(precautions, list):
        for p in precautions:
            lines.append(f"  · {p}")
    else:
        lines.append(f"  {precautions or '施药时穿戴防护用具，避开高温与雨天，遵守安全间隔期。'}")
    lines.append("")

    lines.append("【不可用说明】")
    lines.append(f"  {parsed.get('rejected_explanation') or '本次无被拒绝药剂。'}")
    lines.append("")

    non_chemical = parsed.get("non_chemical_advice")
    if non_chemical:
        lines.append("【非化学防治】")
        lines.append(f"  {non_chemical}")
        lines.append("")

    lines.append("【数据来源】")
    lines.append(f"  {parsed.get('data_source') or '规则引擎与本地知识库'}")
    lines.append("")

    lines.append("【免责声明】")
    lines.append(f"  {parsed.get('disclaimer') or DISCLAIMER}")

    if used_fallback:
        lines.append(DEGRADED_MARK)

    # warnings 只做审计，不展示给柚农（spec 5.3.3-2）；此处保留在返回值里由上层记录
    _ = warnings
    return "\n".join(lines)
