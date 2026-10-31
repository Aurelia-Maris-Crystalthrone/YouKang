"""数据库适配层：把 RDS 查询结果转换成规则引擎要的 dataclass。

设计原则：不硬依赖任何 MySQL 驱动，用 Protocol 鸭子类型。
调用方传入任何实现了 ``query(sql, params) -> list[dict]`` 的对象即可
（真实 MySQL 封装、SQLite 封装、测试 FakeConn 都行）。

本模块只做"数据库行 -> dataclass"的搬运与字段容错，
不含任何业务规则（安全间隔期 / 抗药性 / 物候期判断一律交给 rule_engine）。
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any, Protocol

from labelmap import CLASS_NAMES
from prescription.rule_engine import (
    FilterOutput,
    Orchard,
    Pesticide,
    PesticideConflict,
    PhenophaseContraindication,
    SprayRecord,
    filter_pesticides,
)

logger = logging.getLogger(__name__)

_CROP_SPLIT_RE = re.compile(r"[,，、;；]")


class DbConn(Protocol):
    """数据库连接抽象（鸭子类型，不绑定任何 MySQL 驱动）。"""

    def query(self, sql: str, params: Sequence[Any] | None = None) -> list[dict]:
        """执行参数化查询，返回每行一个 dict（键为列名）。"""
        ...


def _as_str(value: Any) -> str:
    """把任意值安全转成 str，None 给空串。"""
    if value is None:
        return ""
    return str(value)


def _as_opt_str(value: Any) -> str | None:
    """把任意值转成 str，None/空白给 None。"""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_registered_crops(value: Any) -> list[str]:
    """解析登记作物：原生 list -> JSON 数组字符串 -> 逗号/顿号分隔文本 -> []。"""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    if not isinstance(value, str):
        return []
    text = value.strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        parsed = None
    if isinstance(parsed, list):
        return [str(item).strip() for item in parsed if str(item).strip()]
    return [part.strip() for part in _CROP_SPLIT_RE.split(text) if part.strip()]


def _parse_bool(value: Any) -> bool:
    """布尔化：1/"1"/True/"true"/"True"/"TRUE"/"yes" 为真，其余为假。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return False


def _parse_int_or_none(value: Any) -> int | None:
    """整数容错解析：None / "" / 非法字符串 -> None。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            try:
                return int(float(text))
            except ValueError:
                return None
    return None


def _parse_float_or_none(value: Any) -> float | None:
    """浮点容错解析：None / "" / 非法字符串 -> None，兼容 Decimal。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_date(value: Any) -> date | None:
    """日期容错解析：支持 date/datetime 对象与常见字符串格式，失败返回 None。"""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
    return None


def load_pesticide(row: dict) -> Pesticide:
    """把 pesticide 表行转换成 Pesticide（逐字段容错，脏数据不抛异常）。"""
    return Pesticide(
        id=_parse_int_or_none(row.get("id")) or 0,
        common_name=_as_str(row.get("common_name")),
        active_ingredient=_as_str(row.get("active_ingredient")),
        formulation=_as_str(row.get("formulation")),
        content=_as_str(row.get("content")),
        frac_irac_code=_as_opt_str(row.get("frac_irac_code")),
        phi_days=_parse_int_or_none(row.get("phi_days")),
        max_times_per_season=_parse_int_or_none(row.get("max_times_per_season")),
        toxicity_level=_as_opt_str(row.get("toxicity_level")),
        is_banned=_parse_bool(row.get("is_banned")),
        registered_crops=_parse_registered_crops(row.get("registered_crops")),
    )


def load_orchard(row: dict) -> Orchard:
    """把 orchard 表行转换成 Orchard（不读 id，Orchard 无该字段）。"""
    return Orchard(
        block_name=_as_str(row.get("block_name")),
        variety=_as_str(row.get("variety")),
        tree_age=_parse_int_or_none(row.get("tree_age")) or 0,
        current_phenophase=_as_str(row.get("current_phenophase")),
        expected_harvest_date=_parse_date(row.get("expected_harvest_date")),
        area_mu=_parse_float_or_none(row.get("area_mu")),
    )


def load_spray_record(row: dict) -> SprayRecord:
    """把 spray_record JOIN 行转换成 SprayRecord（药剂名/机理码由 JOIN 补齐）。"""
    return SprayRecord(
        orchard_id=_parse_int_or_none(row.get("orchard_id")) or 0,
        spray_date=_parse_date(row.get("spray_date")) or date.today(),
        pesticide_id=_parse_int_or_none(row.get("pesticide_id")) or 0,
        pesticide_name=_as_str(row.get("pesticide_name")),
        frac_irac_code=_as_opt_str(row.get("frac_irac_code")),
        dilution_ratio=_as_opt_str(row.get("dilution_ratio")),
    )


def load_conflict(row: dict) -> PesticideConflict:
    """把 pesticide_conflict 表行转换成 PesticideConflict。"""
    return PesticideConflict(
        pesticide_a_id=_parse_int_or_none(row.get("pesticide_a_id")) or 0,
        pesticide_b_id=_parse_int_or_none(row.get("pesticide_b_id")) or 0,
        conflict_type=_as_str(row.get("conflict_type")),
        description=_as_str(row.get("description")),
        severity=_as_opt_str(row.get("severity")) or "中等",
    )


def load_contraindication(row: dict) -> PhenophaseContraindication:
    """把 phenophase_contraindication 表行转换成 PhenophaseContraindication。"""
    return PhenophaseContraindication(
        pesticide_id=_parse_int_or_none(row.get("pesticide_id")) or 0,
        phenophase=_as_str(row.get("phenophase")),
        reason=_as_str(row.get("reason")),
    )


_CANDIDATE_COLUMNS = (
    "p.id, p.common_name, p.active_ingredient, p.formulation, p.content, "
    "p.frac_irac_code, p.phi_days, p.max_times_per_season, p.toxicity_level, "
    "p.is_banned, p.registered_crops"
)

_SQL_CANDIDATES_CITRUS = (
    f"SELECT {_CANDIDATE_COLUMNS} "
    "FROM pesticide p "
    "JOIN pest_pesticide pp ON pp.pesticide_id = p.id "
    "WHERE pp.pest_name = %s AND pp.is_registered_for_citrus = 1 "
    "ORDER BY p.id"
)

_SQL_CANDIDATES_ALL = (
    f"SELECT {_CANDIDATE_COLUMNS} "
    "FROM pesticide p "
    "JOIN pest_pesticide pp ON pp.pesticide_id = p.id "
    "WHERE pp.pest_name = %s "
    "ORDER BY p.id"
)

_SQL_SPRAY_HISTORY = (
    "SELECT sr.orchard_id, sr.spray_date, sr.pesticide_id, "
    "p.common_name AS pesticide_name, p.frac_irac_code, sr.dilution_ratio "
    "FROM spray_record sr "
    "JOIN pesticide p ON p.id = sr.pesticide_id "
    "WHERE sr.orchard_id = %s "
    "ORDER BY sr.spray_date DESC "
    "LIMIT %s"
)

_SQL_ORCHARD = (
    "SELECT o.id, o.block_name, o.variety, o.tree_age, o.current_phenophase, "
    "o.expected_harvest_date, o.area_mu "
    "FROM orchard o "
    "WHERE o.block_name = %s"
)

_SQL_CONFLICTS = (
    "SELECT pc.pesticide_a_id, pc.pesticide_b_id, pc.conflict_type, "
    "pc.description, pc.severity "
    "FROM pesticide_conflict pc"
)

_SQL_CONTRAINDICATIONS = (
    "SELECT pct.pesticide_id, pct.phenophase, pct.reason "
    "FROM phenophase_contraindication pct"
)


def _fetch_orchard_row(conn: DbConn, block_name: str) -> dict | None:
    """取地块原始行（含 id），供 fetch_orchard 与 build_filter_input 复用。"""
    rows = conn.query(_SQL_ORCHARD, (block_name,))
    if not rows:
        return None
    return rows[0]


def fetch_orchard(conn: DbConn, block_name: str) -> Orchard | None:
    """按地块名查询 Orchard；不存在返回 None（不抛异常）。"""
    row = _fetch_orchard_row(conn, block_name)
    if row is None:
        return None
    return load_orchard(row)


def fetch_candidates(conn: DbConn, pest_name: str, citrus_only: bool = True) -> list[Pesticide]:
    """查询某病害的候选药剂；pest_name 必须在 CLASS_NAMES 内，否则 ValueError。"""
    if pest_name not in CLASS_NAMES:
        raise ValueError(f"病害名称不合法: {pest_name}")
    sql = _SQL_CANDIDATES_CITRUS if citrus_only else _SQL_CANDIDATES_ALL
    rows = conn.query(sql, (pest_name,))
    return [load_pesticide(row) for row in rows]


def fetch_spray_history(conn: DbConn, orchard_id: int, limit: int = 100) -> list[SprayRecord]:
    """查询地块最近 limit 条施药记录，返回按 spray_date 升序排列。"""
    rows = conn.query(_SQL_SPRAY_HISTORY, (orchard_id, limit))
    records = [load_spray_record(row) for row in rows]
    records.sort(key=lambda record: record.spray_date)
    return records


def fetch_conflicts(conn: DbConn) -> list[PesticideConflict]:
    """全量查询配伍禁忌。"""
    rows = conn.query(_SQL_CONFLICTS)
    return [load_conflict(row) for row in rows]


def fetch_contraindications(conn: DbConn) -> list[PhenophaseContraindication]:
    """全量查询物候期禁忌。"""
    rows = conn.query(_SQL_CONTRAINDICATIONS)
    return [load_contraindication(row) for row in rows]


def build_filter_input(
    conn: DbConn,
    pest_name: str,
    block_name: str,
    today: date,
) -> tuple[
    Orchard,
    list[Pesticide],
    list[SprayRecord],
    list[PesticideConflict],
    list[PhenophaseContraindication],
]:
    """一次组装规则引擎所需的五元组，可直接展开喂给 filter_pesticides。

    today 为接口对齐而保留（组装本身不依赖它）。
    """
    if pest_name not in CLASS_NAMES:
        raise ValueError(f"病害名称不合法: {pest_name}")
    row = _fetch_orchard_row(conn, block_name)
    if row is None:
        raise ValueError(f"地块不存在: {block_name}")
    orchard = load_orchard(row)
    orchard_id = _parse_int_or_none(row.get("id")) or 0
    candidates = fetch_candidates(conn, pest_name)
    spray_history = fetch_spray_history(conn, orchard_id)
    conflicts = fetch_conflicts(conn)
    contraindications = fetch_contraindications(conn)
    return orchard, candidates, spray_history, conflicts, contraindications


def run_prescription(
    conn: DbConn,
    pest_name: str,
    block_name: str,
    today: date | None = None,
) -> FilterOutput:
    """便捷入口：build_filter_input -> filter_pesticides，只返回 FilterOutput。

    中文拒绝报告由调用方用 format_rejection_report 自行生成。
    """
    if today is None:
        today = date.today()
    orchard, candidates, spray_history, conflicts, contraindications = build_filter_input(
        conn, pest_name, block_name, today
    )
    return filter_pesticides(
        pest_name,
        orchard,
        spray_history,
        today,
        candidates,
        conflicts,
        contraindications,
    )