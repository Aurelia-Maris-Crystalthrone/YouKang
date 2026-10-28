"""农药规则引擎（纯 Python，不依赖 LLM）。

核心职责：对药剂推荐做硬规则校验，拒绝不安全、不合规、可能产生抗药性或配伍冲突的药剂。
每条拒绝理由都是能直接展示给柚农的中文，不是英文错误码。

规则：
a) 安全间隔期：距采收天数 < PHI 的药剂一律拒绝
b) 抗药性轮换：与最近一次施药作用机理组相同的药剂拒绝
c) 每季次数上限：超过 max_times_per_season 拒绝
d) 物候期禁忌：花期/幼果期禁用的药剂拒绝
e) 复配禁忌：与近期用过的药剂有配伍冲突的拒绝
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional


@dataclass
class Pesticide:
    """农药信息（对应 pesticide 表）。"""
    id: int
    common_name: str
    active_ingredient: str
    formulation: str
    content: str
    frac_irac_code: Optional[str]  # 作用机理分组码
    phi_days: Optional[int]  # 安全间隔期（天）
    max_times_per_season: Optional[int]  # 每季最多使用次数
    toxicity_level: Optional[str]
    is_banned: bool = False
    registered_crops: list[str] = field(default_factory=list)


@dataclass
class PestPesticide:
    """病害-药剂关联（对应 pest_pesticide 表）。"""
    pest_name: str
    pesticide_id: int
    is_registered_for_citrus: bool = True
    dilution_ratio: Optional[str] = None
    application_method: Optional[str] = None
    application_timing: Optional[str] = None


@dataclass
class Orchard:
    """地块信息（对应 orchard 表）。"""
    block_name: str
    variety: str
    tree_age: int
    current_phenophase: str  # 萌芽期/花期/幼果期/膨大期/转色期/采收期/休眠期
    expected_harvest_date: Optional[date] = None
    area_mu: Optional[float] = None


@dataclass
class SprayRecord:
    """施药记录（对应 spray_record 表）。"""
    orchard_id: int
    spray_date: date
    pesticide_id: int
    pesticide_name: str
    frac_irac_code: Optional[str]  # 作用机理分组码（冗余字段，避免 join）
    dilution_ratio: Optional[str] = None


@dataclass
class PesticideConflict:
    """配伍禁忌（对应 pesticide_conflict 表）。"""
    pesticide_a_id: int
    pesticide_b_id: int
    conflict_type: str
    description: str
    severity: str = "中等"


@dataclass
class PhenophaseContraindication:
    """物候期禁忌（对应 phenophase_contraindication 表）。"""
    pesticide_id: int
    phenophase: str
    reason: str


@dataclass
class FilterResult:
    """单条过滤结果。"""
    pesticide_id: int
    name: str
    reason: str  # 中文拒绝理由


@dataclass
class FilterOutput:
    """过滤输出。"""
    allowed: list[Pesticide] = field(default_factory=list)
    rejected: list[FilterResult] = field(default_factory=list)


# 花期/幼果期禁用物候期集合
SENSITIVE_PHENOPHASES = {"花期", "幼果期"}


def _days_until_harvest(orchard: Orchard, today: date) -> Optional[int]:
    """计算距采收天数。无预计采收日期返回 None。"""
    if orchard.expected_harvest_date is None:
        return None
    return (orchard.expected_harvest_date - today).days


def _check_phi(pesticide: Pesticide, orchard: Orchard, today: date) -> Optional[str]:
    """规则 a) 安全间隔期校验。

    距采收天数 < PHI 的药剂一律拒绝。
    返回拒绝理由（中文），通过返回 None。
    """
    if pesticide.phi_days is None:
        return None  # 无 PHI 数据，不拒绝（但需标注）
    days = _days_until_harvest(orchard, today)
    if days is None:
        return None  # 无预计采收日期，无法校验
    if days < pesticide.phi_days:
        return (
            f"距采收仅 {days} 天，该药安全间隔期需 {pesticide.phi_days} 天，"
            f"采收前 {pesticide.phi_days} 天必须停用"
        )
    return None


def _check_resistance_rotation(
    pesticide: Pesticide,
    spray_history: list[SprayRecord],
    today: date,
    lookback_days: int = 30,
) -> Optional[str]:
    """规则 b) 抗药性轮换校验。

    与最近一次施药作用机理组相同的药剂拒绝，必须换组。
    返回拒绝理由（中文），通过返回 None。
    """
    if pesticide.frac_irac_code is None:
        return None  # 无作用机理码，不拒绝（但需标注）
    recent = [r for r in spray_history if (today - r.spray_date).days <= lookback_days]
    if not recent:
        return None
    # 按日期倒序取最近一次
    recent.sort(key=lambda r: r.spray_date, reverse=True)
    last = recent[0]
    if last.frac_irac_code is None:
        return None
    # 比较作用机理组（取前缀，如 FRAC 11 vs FRAC 11+3 视为同组）
    last_group = last.frac_irac_code.split("+")[0].strip()
    this_group = pesticide.frac_irac_code.split("+")[0].strip()
    if last_group == this_group:
        return (
            f"与 {last.spray_date.month} 月 {last.spray_date.day} 日使用的 "
            f"{last.pesticide_name} 同属第 {last_group} 组，"
            f"存在抗药性风险，须换用不同作用机理的药剂"
        )
    return None


def _check_max_times(pesticide: Pesticide, spray_history: list[SprayRecord]) -> Optional[str]:
    """规则 c) 每季次数上限校验。

    超过 max_times_per_season 拒绝。
    返回拒绝理由（中文），通过返回 None。
    """
    if pesticide.max_times_per_season is None:
        return None
    count = sum(1 for r in spray_history if r.pesticide_id == pesticide.id)
    if count >= pesticide.max_times_per_season:
        return (
            f"本季已使用 {count} 次，该药每季最多使用 {pesticide.max_times_per_season} 次，"
            f"已达上限"
        )
    return None


def _check_phenophase(
    pesticide: Pesticide,
    orchard: Orchard,
    contraindications: list[PhenophaseContraindication],
) -> Optional[str]:
    """规则 d) 物候期禁忌校验。

    花期/幼果期禁用的药剂拒绝。
    返回拒绝理由（中文），通过返回 None。
    """
    if orchard.current_phenophase not in SENSITIVE_PHENOPHASES:
        return None
    # 检查物候期禁忌表
    for c in contraindications:
        if c.pesticide_id == pesticide.id and c.phenophase == orchard.current_phenophase:
            return (
                f"当前处于 {orchard.current_phenophase}，{c.reason}"
            )
    return None


def _check_conflict(
    pesticide: Pesticide,
    spray_history: list[SprayRecord],
    conflicts: list[PesticideConflict],
    lookback_days: int = 14,
) -> Optional[str]:
    """规则 e) 复配禁忌校验。

    与近期用过的药剂有配伍冲突的拒绝。
    返回拒绝理由（中文），通过返回 None。
    """
    recent = [r for r in spray_history if (today := date.today()) and (today - r.spray_date).days <= lookback_days]
    if not recent:
        return None
    recent_ids = {r.pesticide_id for r in recent}
    for c in conflicts:
        if c.severity == "轻微":
            continue  # 轻微冲突不拒绝，仅提示
        if (c.pesticide_a_id == pesticide.id and c.pesticide_b_id in recent_ids) or \
           (c.pesticide_b_id == pesticide.id and c.pesticide_a_id in recent_ids):
            return (
                f"与近期用过的药剂存在{c.conflict_type}：{c.description}，"
                f"{c.severity}风险，禁止混用"
            )
    return None


def filter_pesticides(
    disease: str,
    orchard: Orchard,
    spray_history: list[SprayRecord],
    today: date,
    candidate_pesticides: list[Pesticide],
    conflicts: list[PesticideConflict] | None = None,
    contraindications: list[PhenophaseContraindication] | None = None,
    lookback_resistance: int = 30,
    lookback_conflict: int = 14,
) -> FilterOutput:
    """对候选药剂列表做规则过滤。

    Args:
        disease: 病害名（如 "red_spider_mite"）
        orchard: 地块信息
        spray_history: 施药记录列表
        today: 当前日期
        candidate_pesticides: 候选药剂列表（通常来自 pest_pesticide 表查询）
        conflicts: 配伍禁忌列表（可选）
        contraindications: 物候期禁忌列表（可选）
        lookback_resistance: 抗药性轮换回溯天数（默认 30 天）
        lookback_conflict: 复配禁忌回溯天数（默认 14 天）

    Returns:
        FilterOutput：allowed 为通过的药剂，rejected 为被拒绝的药剂及理由
    """
    conflicts = conflicts or []
    contraindications = contraindications or []
    output = FilterOutput()

    for p in candidate_pesticides:
        # 禁用药剂直接拒绝
        if p.is_banned:
            output.rejected.append(FilterResult(
                pesticide_id=p.id,
                name=p.common_name,
                reason="该药剂已被禁用，禁止使用",
            ))
            continue

        # 规则 a) 安全间隔期
        reason = _check_phi(p, orchard, today)
        if reason:
            output.rejected.append(FilterResult(
                pesticide_id=p.id,
                name=p.common_name,
                reason=reason,
            ))
            continue

        # 规则 b) 每季次数上限
        reason = _check_max_times(p, spray_history)
        if reason:
            output.rejected.append(FilterResult(
                pesticide_id=p.id,
                name=p.common_name,
                reason=reason,
            ))
            continue

        # 规则 c) 抗药性轮换
        reason = _check_resistance_rotation(p, spray_history, today, lookback_resistance)
        if reason:
            output.rejected.append(FilterResult(
                pesticide_id=p.id,
                name=p.common_name,
                reason=reason,
            ))
            continue

        # 规则 d) 物候期禁忌
        reason = _check_phenophase(p, orchard, contraindications)
        if reason:
            output.rejected.append(FilterResult(
                pesticide_id=p.id,
                name=p.common_name,
                reason=reason,
            ))
            continue

        # 规则 e) 复配禁忌
        reason = _check_conflict(p, spray_history, conflicts, lookback_conflict)
        if reason:
            output.rejected.append(FilterResult(
                pesticide_id=p.id,
                name=p.common_name,
                reason=reason,
            ))
            continue

        # 全部通过
        output.allowed.append(p)

    return output


def format_rejection_report(output: FilterOutput) -> str:
    """生成中文拒绝报告，可直接展示给柚农。"""
    lines = []
    lines.append(f"药剂推荐筛选结果：通过 {len(output.allowed)} 种，拒绝 {len(output.rejected)} 种")
    lines.append("")
    if output.allowed:
        lines.append("【通过】")
        for p in output.allowed:
            lines.append(f"  ✓ {p.common_name}（{p.active_ingredient}）")
        lines.append("")
    if output.rejected:
        lines.append("【拒绝】")
        for r in output.rejected:
            lines.append(f"  ✗ {r.name}：{r.reason}")
    return "\n".join(lines)