"""打药效果追踪模块（progress）。

核心价值：把一次性识别变成持续管理服务。
- 比较同一地块相邻两次观测，判断病情趋势
- 根据趋势给出针对性建议（扩散→换药、稳定→观察、收敛→维持）

输出结论枚举：
- SPREADING（扩散）：病斑数量增加或面积扩大
- STABLE（稳定）：病斑数量与面积基本不变
- RECOVERING（收敛）：病斑数量减少或面积缩小
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Conclusion(Enum):
    """病情趋势结论枚举。"""
    SPREADING = "SPREADING"  # 扩散
    STABLE = "STABLE"        # 稳定
    RECOVERING = "RECOVERING"  # 收敛


@dataclass
class Detection:
    """单个检测结果。"""
    label: str
    confidence: float
    bbox: list[float]  # [x1, y1, x2, y2]
    top2: list[dict] = field(default_factory=list)


@dataclass
class Observation:
    """一次观测记录。"""
    orchard_id: int
    captured_at: str
    detections: list[Detection] = field(default_factory=list)
    image_obs_path: Optional[str] = None
    gps_lat: Optional[float] = None
    gps_lng: Optional[float] = None


@dataclass
class ComparisonResult:
    """比较结果。"""
    conclusion: Conclusion
    prev_lesion_count: int
    curr_lesion_count: int
    lesion_count_change: int  # 正=增加，负=减少
    prev_total_area: float
    curr_total_area: float
    total_area_change_rate: float  # 正=扩大，负=缩小
    new_lesions: list[dict] = field(default_factory=list)  # [{"x":..., "y":...}]
    disappeared_lesions: list[dict] = field(default_factory=list)
    summary: str = ""  # 中文摘要


def _calc_bbox_area(bbox: list[float]) -> float:
    """计算 bbox 面积。"""
    x1, y1, x2, y2 = bbox
    return max(0.0, (x2 - x1)) * max(0.0, (y2 - y1))


def _bbox_center(bbox: list[float]) -> dict:
    """计算 bbox 中心点。"""
    x1, y1, x2, y2 = bbox
    return {"x": round((x1 + x2) / 2, 1), "y": round((y1 + y2) / 2, 1)}


def _bbox_iou(bbox1: list[float], bbox2: list[float]) -> float:
    """计算两个 bbox 的 IOU。"""
    x1 = max(bbox1[0], bbox2[0])
    y1 = max(bbox1[1], bbox2[1])
    x2 = min(bbox1[2], bbox2[2])
    y2 = min(bbox1[3], bbox2[3])
    if x2 <= x1 or y2 <= y1:
        return 0.0
    inter = (x2 - x1) * (y2 - y1)
    area1 = _calc_bbox_area(bbox1)
    area2 = _calc_bbox_area(bbox2)
    union = area1 + area2 - inter
    return inter / union if union > 0 else 0.0


def _match_lesions(
    prev_detections: list[Detection],
    curr_detections: list[Detection],
    iou_threshold: float = 0.3,
) -> tuple[list[int], list[int], list[int], list[int]]:
    """匹配前后两次观测的病斑。

    Returns:
        matched_prev_idx: 前一次被匹配的索引
        matched_curr_idx: 本次被匹配的索引
        new_idx: 本次新增的索引
        disappeared_idx: 前一次消失的索引
    """
    if not prev_detections:
        return [], [], list(range(len(curr_detections))), []
    if not curr_detections:
        return list(range(len(prev_detections))), [], [], []

    matched_prev = set()
    matched_curr = set()
    matches = []

    # 贪心匹配：按 IOU 从高到低
    pairs = []
    for i, p in enumerate(prev_detections):
        for j, c in enumerate(curr_detections):
            # 只匹配同类别
            if p.label == c.label:
                iou = _bbox_iou(p.bbox, c.bbox)
                if iou >= iou_threshold:
                    pairs.append((iou, i, j))

    pairs.sort(key=lambda x: x[0], reverse=True)

    for iou, i, j in pairs:
        if i not in matched_prev and j not in matched_curr:
            matched_prev.add(i)
            matched_curr.add(j)
            matches.append((i, j, iou))

    new_idx = [j for j in range(len(curr_detections)) if j not in matched_curr]
    disappeared_idx = [i for i in range(len(prev_detections)) if i not in matched_prev]

    return list(matched_prev), list(matched_curr), new_idx, disappeared_idx


def compare(prev_obs: Observation, curr_obs: Observation) -> ComparisonResult:
    """比较同一地块相邻两次观测。

    Args:
        prev_obs: 前一次观测
        curr_obs: 本次观测

    Returns:
        ComparisonResult：包含结论、病斑变化、新增/消失位置、中文摘要
    """
    prev_detections = prev_obs.detections
    curr_detections = curr_obs.detections

    prev_count = len(prev_detections)
    curr_count = len(curr_detections)
    count_change = curr_count - prev_count

    # 计算总面积
    prev_area = sum(_calc_bbox_area(d.bbox) for d in prev_detections)
    curr_area = sum(_calc_bbox_area(d.bbox) for d in curr_detections)
    area_change_rate = (curr_area - prev_area) / prev_area if prev_area > 0 else 0.0

    # 匹配病斑
    matched_prev, matched_curr, new_idx, disappeared_idx = _match_lesions(
        prev_detections, curr_detections
    )

    # 收集新增和消失的位置
    new_lesions = [_bbox_center(curr_detections[j].bbox) for j in new_idx]
    disappeared_lesions = [_bbox_center(prev_detections[i].bbox) for i in disappeared_idx]

    # 判断结论
    # 扩散条件：病斑数量增加 或 面积扩大 > 20% 或 新增多于消失
    # 收敛条件：病斑数量减少 或 面积缩小 > 20% 或 消失多于新增
    # 否则稳定
    net_change = len(new_idx) - len(disappeared_idx)
    if count_change > 0 or area_change_rate > 0.2 or net_change > 0:
        conclusion = Conclusion.SPREADING
    elif count_change < 0 or area_change_rate < -0.2 or net_change < 0:
        conclusion = Conclusion.RECOVERING
    else:
        conclusion = Conclusion.STABLE

    # 生成中文摘要
    summary_parts = []
    if conclusion == Conclusion.SPREADING:
        summary_parts.append("病情扩散")
        if count_change > 0:
            summary_parts.append(f"病斑数量从 {prev_count} 个增加到 {curr_count} 个")
        if area_change_rate > 0.2:
            summary_parts.append(f"病斑总面积扩大 {area_change_rate:.1%}")
        if new_lesions:
            summary_parts.append(f"新增 {len(new_lesions)} 个病斑")
    elif conclusion == Conclusion.RECOVERING:
        summary_parts.append("病情收敛")
        if count_change < 0:
            summary_parts.append(f"病斑数量从 {prev_count} 个减少到 {curr_count} 个")
        if area_change_rate < -0.2:
            summary_parts.append(f"病斑总面积缩小 {abs(area_change_rate):.1%}")
        if disappeared_lesions:
            summary_parts.append(f"{len(disappeared_lesions)} 个病斑消失")
    else:
        summary_parts.append("病情稳定")
        summary_parts.append(f"病斑数量 {prev_count} → {curr_count} 个，面积变化 {area_change_rate:.1%}")

    summary = "，".join(summary_parts) + "。"

    return ComparisonResult(
        conclusion=conclusion,
        prev_lesion_count=prev_count,
        curr_lesion_count=curr_count,
        lesion_count_change=count_change,
        prev_total_area=prev_area,
        curr_total_area=curr_area,
        total_area_change_rate=area_change_rate,
        new_lesions=new_lesions,
        disappeared_lesions=disappeared_lesions,
        summary=summary,
    )


def advise_on_progress(
    conclusion: Conclusion,
    spray_history: list[dict],
    current_pesticide: Optional[str] = None,
    disease: Optional[str] = None,
) -> dict:
    """基于病情趋势给出建议。

    Args:
        conclusion: 病情趋势结论
        spray_history: 施药历史 [{"spray_date": str, "pesticide_name": str, "frac_irac_code": str}]
        current_pesticide: 当前使用的药剂名（可选）
        disease: 当前病害 label（可选）

    Returns:
        {
            "action": str,           # 建议动作
            "reasoning": str,        # 推理过程（中文）
            "recommendation": str,   # 具体建议
            "switch_needed": bool,   # 是否需要换药
        }
    """
    if conclusion == Conclusion.SPREADING:
        # 扩散 → 须换用不同作用机理组的药剂。
        # 具体药剂必须由处方引擎筛选（过 PHI / 抗药性轮换 / 复配禁忌），
        # 本模块禁止点名：不同病害对应药剂完全不同（如溃疡病是细菌性病害，
        # 固定推荐杀螨剂会造成无效防治），且未经筛选的推荐可能是未登记药剂。
        reasoning = "病情扩散，当前药剂效果不足或已产生抗药性，须换用不同作用机理组的药剂。"

        last_group = None
        if spray_history:
            last_group = spray_history[-1].get("frac_irac_code")

        if last_group and current_pesticide:
            head = f"近期使用过 {current_pesticide}（第 {last_group} 组），须换用不同作用机理组。"
        elif last_group:
            head = f"近期施药属第 {last_group} 组，须换用不同作用机理组。"
        else:
            head = "须换用不同作用机理组的药剂。"

        recommendation = (
            head + "请交由处方引擎按当前病害、距采收天数与施药史重新筛选药剂；"
            "本模块不直接指定药名，以保证所推药剂针对该病害且满足安全间隔期。"
        )

        return {
            "action": "换药",
            "reasoning": reasoning,
            "recommendation": recommendation,
            "switch_needed": True,
            # 供上层编排：拿到本标记后必须再调一次处方引擎，不得直接输出
            "need_prescription_engine": True,
            "disease": disease,
        }

    elif conclusion == Conclusion.STABLE:
        # 稳定 → 继续观察
        return {
            "action": "继续观察",
            "reasoning": "病情稳定，当前方案有效，建议继续观察。",
            "recommendation": "维持现有防治方案，7 天后再次观测确认趋势。",
            "switch_needed": False,
        }

    else:  # RECOVERING
        # 收敛 → 维持现有方案
        return {
            "action": "维持方案",
            "reasoning": "病情收敛，当前方案有效，建议维持。",
            "recommendation": "维持现有防治方案，注意观察是否反弹。",
            "switch_needed": False,
        }


def format_tracking_report(comparison: ComparisonResult, advice: dict) -> str:
    """生成追踪报告（中文，可直接展示给柚农）。

    Args:
        comparison: 比较结果
        advice: 建议结果

    Returns:
        中文报告字符串
    """
    lines = []
    lines.append("📊 病情追踪报告")
    lines.append("")
    lines.append(f"结论：{comparison.summary}")
    lines.append("")
    lines.append(f"病斑数量：{comparison.prev_lesion_count} → {comparison.curr_lesion_count} 个（{comparison.lesion_count_change:+d}）")
    lines.append(f"病斑面积：{comparison.prev_total_area:.1f} → {comparison.curr_total_area:.1f}（{comparison.total_area_change_rate:+.1%}）")
    lines.append("")
    if comparison.new_lesions:
        lines.append(f"新增病斑：{len(comparison.new_lesions)} 个")
    if comparison.disappeared_lesions:
        lines.append(f"消失病斑：{len(comparison.disappeared_lesions)} 个")
    lines.append("")
    lines.append(f"💡 建议：{advice['recommendation']}")
    lines.append("")
    lines.append("⚠️ 免责声明：以上建议仅供参考，严重时请立即联系当地植保站或农技人员。")
    return "\n".join(lines)