"""数据库适配层单元测试。

覆盖：
- 字段解析（registered_crops / is_banned / phi_days / 日期）
- 行加载（load_pesticide / load_orchard / load_spray_record / ...）
- 参数化查询（fetch_candidates / fetch_spray_history / ...）
- 编排与入口（build_filter_input / run_prescription）
- 列名白名单校验（断言 SQL 只引用 schema.sql 真实存在的列）
"""
import re
import unittest
from datetime import date
from pathlib import Path

from prescription.load_from_db import (
    DbConn,
    build_filter_input,
    fetch_candidates,
    fetch_conflicts,
    fetch_contraindications,
    fetch_orchard,
    fetch_spray_history,
    load_conflict,
    load_contraindication,
    load_orchard,
    load_pesticide,
    load_spray_record,
    run_prescription,
)
from prescription.rule_engine import (
    FilterOutput,
    Orchard,
    Pesticide,
    PesticideConflict,
    PhenophaseContraindication,
    SprayRecord,
)

_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "prescription" / "schema.sql"

_SQL_KEYWORDS = {
    "WHERE", "ON", "JOIN", "ORDER", "GROUP", "LIMIT", "AS", "BY",
    "LEFT", "RIGHT", "INNER", "OUTER", "CROSS", "USING", "SET",
    "AND", "OR", "NOT", "NULL", "SELECT", "FROM", "DESC", "ASC",
}


def _truthy(value) -> bool:
    """把内存数据里的 1/True/"1" 归一为真。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return False


def _schema_columns() -> dict[str, set[str]]:
    """从 schema.sql 提取每张表的真实列集合。"""
    text = _SCHEMA_PATH.read_text(encoding="utf-8")
    tables: dict[str, set[str]] = {}
    pattern = re.compile(
        r"CREATE TABLE (?:IF NOT EXISTS )?`?(\w+)`?\s*\((.*?)\)\s*ENGINE", re.S
    )
    for match in pattern.finditer(text):
        name = match.group(1)
        body = match.group(2)
        columns: set[str] = set()
        for line in body.split("\n"):
            line = line.strip().rstrip(",")
            if not line:
                continue
            head = line.split()[0].strip("`").upper()
            if head in {"PRIMARY", "UNIQUE", "INDEX", "KEY", "FOREIGN", "CONSTRAINT"}:
                continue
            column = re.match(r"`?(\w+)`?", line)
            if column:
                columns.add(column.group(1))
        tables[name] = columns
    return tables


def _assert_columns_exist(sql: str) -> None:
    """断言 SQL 中形如 alias.col 的引用都存在于对应表的真实列集合。"""
    tables = _schema_columns()
    aliases: dict[str, str] = {}
    for match in re.finditer(
        r"\b(?:FROM|JOIN)\s+`?(\w+)`?(?:\s+(?:AS\s+)?`?(\w+)`?)?", sql, re.I
    ):
        table = match.group(1)
        alias = match.group(2)
        aliases[table] = table
        if alias and alias.upper() not in _SQL_KEYWORDS:
            aliases[alias] = table
    for alias, column in re.findall(r"\b([A-Za-z_]\w*)\.([A-Za-z_]\w*)\b", sql):
        if alias in aliases:
            table = aliases[alias]
            if column not in tables.get(table, set()):
                raise AssertionError(f"列 {column} 不在表 {table} 中")


class FakeConn:
    """内存数据库连接（测试桩），按表名与参数路由 SQL。"""

    def __init__(self, tables: dict[str, list[dict]] | None = None):
        self._tables = tables or {}
        self.queries: list[tuple[str, tuple | None]] = []

    def query(self, sql: str, params=None) -> list[dict]:
        self.queries.append((sql, tuple(params) if params else params))
        _assert_columns_exist(sql)
        return self._route(sql, params or ())

    def assert_no_literal(self, literal: str) -> bool:
        """断言所有被记录的 SQL 文本中都不含指定字面量。"""
        return all(literal not in sql for sql, _ in self.queries)

    def _route(self, sql: str, params: tuple) -> list[dict]:
        if re.search(r"FROM\s+pesticide\s+p\s+JOIN\s+pest_pesticide\s+pp", sql):
            return self._candidates(sql, params)
        if re.search(r"FROM\s+spray_record\s+sr", sql):
            return self._spray_history(params)
        if re.search(r"FROM\s+orchard\s+o\b", sql):
            return self._orchard(params)
        if re.search(r"FROM\s+pesticide_conflict\s+pc", sql):
            return [dict(row) for row in self._tables.get("pesticide_conflict", [])]
        if re.search(r"FROM\s+phenophase_contraindication\s+pct", sql):
            return [dict(row) for row in self._tables.get("phenophase_contraindication", [])]
        raise AssertionError(f"未识别的 SQL: {sql}")

    def _candidates(self, sql: str, params: tuple) -> list[dict]:
        pest_name = params[0]
        citrus_only = "is_registered_for_citrus = 1" in sql
        pesticides = {row["id"]: row for row in self._tables.get("pesticide", [])}
        result: list[dict] = []
        for link in self._tables.get("pest_pesticide", []):
            if link.get("pest_name") != pest_name:
                continue
            if citrus_only and not _truthy(link.get("is_registered_for_citrus")):
                continue
            row = pesticides.get(link.get("pesticide_id"))
            if row is None:
                continue
            result.append(dict(row))
        result.sort(key=lambda item: item.get("id"))
        return result

    def _spray_history(self, params: tuple) -> list[dict]:
        orchard_id, limit = params[0], params[1]
        pesticides = {row["id"]: row for row in self._tables.get("pesticide", [])}
        records = [
            dict(row)
            for row in self._tables.get("spray_record", [])
            if row.get("orchard_id") == orchard_id
        ]
        records.sort(key=lambda item: item.get("spray_date"), reverse=True)
        records = records[: int(limit)]
        for record in records:
            pesticide = pesticides.get(record.get("pesticide_id"), {})
            record["pesticide_name"] = pesticide.get("common_name", "")
            record["frac_irac_code"] = pesticide.get("frac_irac_code")
        return records

    def _orchard(self, params: tuple) -> list[dict]:
        block_name = params[0]
        for row in self._tables.get("orchard", []):
            if row.get("block_name") == block_name:
                return [dict(row)]
        return []


def _pesticide_row(pid, name, banned=0, phi=7, frac="6", crops='["柑橘","柚子"]'):
    """构造一行 pesticide 内存数据。"""
    return {
        "id": pid,
        "common_name": name,
        "active_ingredient": name,
        "formulation": "乳油",
        "content": "1.8%",
        "frac_irac_code": frac,
        "phi_days": phi,
        "max_times_per_season": 2,
        "toxicity_level": "低毒",
        "is_banned": banned,
        "registered_crops": crops,
    }


class TestParseHelpers(unittest.TestCase):
    """字段解析工具测试。"""

    def test_registered_crops_json(self):
        """JSON 数组字符串解析为列表。"""
        self.assertEqual(load_pesticide({"registered_crops": '["柑橘","柚子"]'}).registered_crops,
                         ["柑橘", "柚子"])

    def test_registered_crops_comma(self):
        """逗号分隔文本解析为列表。"""
        self.assertEqual(load_pesticide({"registered_crops": "柑橘,柚子"}).registered_crops,
                         ["柑橘", "柚子"])

    def test_registered_crops_dun_comma(self):
        """顿号分隔文本解析为列表。"""
        self.assertEqual(load_pesticide({"registered_crops": "柑橘、柚子"}).registered_crops,
                         ["柑橘", "柚子"])

    def test_registered_crops_empty(self):
        """None / 空串解析为空列表。"""
        self.assertEqual(load_pesticide({"registered_crops": None}).registered_crops, [])
        self.assertEqual(load_pesticide({"registered_crops": ""}).registered_crops, [])

    def test_is_banned_truthy_forms(self):
        """1 / "1" / True / "true" / "True" 都解析为 True。"""
        for value in [1, "1", True, "true", "True", "TRUE", "yes"]:
            self.assertTrue(load_pesticide({"is_banned": value}).is_banned,
                            f"{value!r} 应为 True")

    def test_is_banned_falsy_forms(self):
        """0 / "0" / False / None / 空串都解析为 False。"""
        for value in [0, "0", False, None, "", "abc"]:
            self.assertFalse(load_pesticide({"is_banned": value}).is_banned,
                             f"{value!r} 应为 False")

    def test_phi_days_empty_str(self):
        """空字符串解析为 None。"""
        self.assertIsNone(load_pesticide({"phi_days": ""}).phi_days)

    def test_phi_days_invalid_str(self):
        """非法字符串解析为 None，不抛异常。"""
        self.assertIsNone(load_pesticide({"phi_days": "abc"}).phi_days)

    def test_phi_days_valid(self):
        """数值与数字字符串解析为整数。"""
        self.assertEqual(load_pesticide({"phi_days": 15}).phi_days, 15)
        self.assertEqual(load_pesticide({"phi_days": "15"}).phi_days, 15)

    def test_harvest_date_object(self):
        """date 对象原样返回。"""
        orchard = load_orchard({"expected_harvest_date": date(2026, 11, 20)})
        self.assertEqual(orchard.expected_harvest_date, date(2026, 11, 20))

    def test_harvest_date_str(self):
        """"YYYY-MM-DD" 字符串解析结果与 date 对象一致。"""
        orchard = load_orchard({"expected_harvest_date": "2026-11-20"})
        self.assertEqual(orchard.expected_harvest_date, date(2026, 11, 20))

    def test_spray_date_two_forms(self):
        """spray_date 支持 date 对象与字符串两种输入，结果一致。"""
        record_a = load_spray_record({"orchard_id": 1, "spray_date": date(2026, 11, 20),
                                      "pesticide_id": 1, "pesticide_name": "阿维菌素",
                                      "frac_irac_code": "6"})
        record_b = load_spray_record({"orchard_id": 1, "spray_date": "2026-11-20",
                                      "pesticide_id": 1, "pesticide_name": "阿维菌素",
                                      "frac_irac_code": "6"})
        self.assertEqual(record_a.spray_date, date(2026, 11, 20))
        self.assertEqual(record_a.spray_date, record_b.spray_date)

    def test_load_defaults_missing(self):
        """缺失 tree_age / current_phenophase 时给 0 / 空串。"""
        orchard = load_orchard({"block_name": "X"})
        self.assertEqual(orchard.tree_age, 0)
        self.assertEqual(orchard.current_phenophase, "")


class TestLoadFunctions(unittest.TestCase):
    """行加载函数测试。"""

    def test_load_pesticide_full_row(self):
        """完整行 11 字段逐一正确。"""
        row = {
            "id": 7,
            "common_name": "螺螨酯",
            "active_ingredient": "螺螨酯",
            "formulation": "悬浮剂",
            "content": "240g/L",
            "frac_irac_code": "20B",
            "phi_days": 14,
            "max_times_per_season": 2,
            "toxicity_level": "低毒",
            "is_banned": 0,
            "registered_crops": '["柑橘","柚子"]',
        }
        pesticide = load_pesticide(row)
        self.assertEqual(pesticide.id, 7)
        self.assertEqual(pesticide.common_name, "螺螨酯")
        self.assertEqual(pesticide.active_ingredient, "螺螨酯")
        self.assertEqual(pesticide.formulation, "悬浮剂")
        self.assertEqual(pesticide.content, "240g/L")
        self.assertEqual(pesticide.frac_irac_code, "20B")
        self.assertEqual(pesticide.phi_days, 14)
        self.assertEqual(pesticide.max_times_per_season, 2)
        self.assertEqual(pesticide.toxicity_level, "低毒")
        self.assertFalse(pesticide.is_banned)
        self.assertEqual(pesticide.registered_crops, ["柑橘", "柚子"])

    def test_load_orchard_row(self):
        """完整地块行：日期解析正确，area_mu 为 float。"""
        row = {
            "id": 1,
            "block_name": "测试地块",
            "variety": "琯溪蜜柚",
            "tree_age": 8,
            "current_phenophase": "膨大期",
            "expected_harvest_date": "2026-11-20",
            "area_mu": "5.5",
        }
        orchard = load_orchard(row)
        self.assertEqual(orchard.block_name, "测试地块")
        self.assertEqual(orchard.variety, "琯溪蜜柚")
        self.assertEqual(orchard.tree_age, 8)
        self.assertEqual(orchard.current_phenophase, "膨大期")
        self.assertEqual(orchard.expected_harvest_date, date(2026, 11, 20))
        self.assertIsInstance(orchard.area_mu, float)
        self.assertEqual(orchard.area_mu, 5.5)

    def test_load_conflict_defaults(self):
        """配伍禁忌缺失 severity 时兜底为中等。"""
        conflict = load_conflict({"pesticide_a_id": 1, "pesticide_b_id": 2,
                                  "conflict_type": "药害", "description": "说明"})
        self.assertEqual(conflict.severity, "中等")
        self.assertEqual(conflict.pesticide_a_id, 1)

    def test_load_contraindication_row(self):
        """物候期禁忌行映射正确。"""
        contraindication = load_contraindication({"pesticide_id": 3, "phenophase": "花期",
                                                  "reason": "花期禁用"})
        self.assertEqual(contraindication.pesticide_id, 3)
        self.assertEqual(contraindication.phenophase, "花期")
        self.assertEqual(contraindication.reason, "花期禁用")

    def test_dirty_missing_registered_crops(self):
        """脏数据：缺 registered_crops 时返回空列表，不抛异常。"""
        row = _pesticide_row(9, "某药")
        row.pop("registered_crops")
        self.assertEqual(load_pesticide(row).registered_crops, [])

    def test_dirty_missing_phi_days(self):
        """脏数据：缺 phi_days 时为 None，不抛异常。"""
        row = _pesticide_row(9, "某药")
        row.pop("phi_days")
        self.assertIsNone(load_pesticide(row).phi_days)

    def test_dirty_missing_frac_irac_code(self):
        """脏数据：缺 frac_irac_code 时为 None，不抛异常。"""
        row = _pesticide_row(9, "某药")
        row.pop("frac_irac_code")
        self.assertIsNone(load_pesticide(row).frac_irac_code)


class TestFetchFunctions(unittest.TestCase):
    """查询函数测试。"""

    def setUp(self):
        """构造标准内存数据。"""
        self.conn = FakeConn({
            "pesticide": [
                _pesticide_row(1, "阿维菌素"),
                _pesticide_row(2, "禁用神药", banned=1),
                _pesticide_row(3, "螺螨酯", phi=14, frac="20B"),
            ],
            "pest_pesticide": [
                {"id": 1, "pest_name": "red_spider_mite", "pesticide_id": 1,
                 "is_registered_for_citrus": 1, "dilution_ratio": "3000 倍液"},
                {"id": 2, "pest_name": "red_spider_mite", "pesticide_id": 2,
                 "is_registered_for_citrus": 1, "dilution_ratio": "1000 倍液"},
                {"id": 3, "pest_name": "anthracnose", "pesticide_id": 3,
                 "is_registered_for_citrus": 1, "dilution_ratio": "2000 倍液"},
            ],
            "orchard": [
                {"id": 1, "block_name": "测试地块", "variety": "琯溪蜜柚", "tree_age": 8,
                 "current_phenophase": "膨大期", "expected_harvest_date": None, "area_mu": 5.0},
                {"id": 2, "block_name": "干净地块", "variety": "琯溪蜜柚", "tree_age": 6,
                 "current_phenophase": "膨大期", "expected_harvest_date": None, "area_mu": 3.0},
            ],
            "spray_record": [
                {"id": 1, "orchard_id": 1, "spray_date": date(2026, 10, 1),
                 "pesticide_id": 1, "dilution_ratio": "3000 倍液"},
                {"id": 2, "orchard_id": 1, "spray_date": date(2026, 9, 1),
                 "pesticide_id": 3, "dilution_ratio": "2000 倍液"},
                {"id": 3, "orchard_id": 1, "spray_date": date(2026, 9, 20),
                 "pesticide_id": 1, "dilution_ratio": "3000 倍液"},
            ],
            "pesticide_conflict": [
                {"id": 1, "pesticide_a_id": 1, "pesticide_b_id": 3, "conflict_type": "药效降低",
                 "description": "混用降低药效", "severity": "中等"},
            ],
            "phenophase_contraindication": [
                {"id": 1, "pesticide_id": 1, "phenophase": "花期", "reason": "花期禁用"},
            ],
        })

    def test_fetch_candidates_invalid_pest(self):
        """非法病害名抛 ValueError，消息含病害名。"""
        with self.assertRaises(ValueError) as ctx:
            fetch_candidates(self.conn, "melanose")
        self.assertIn("melanose", str(ctx.exception))

    def test_fetch_candidates_parametrized(self):
        """pest_name 走参数化，SQL 文本不含病害字面量。"""
        candidates = fetch_candidates(self.conn, "anthracnose")
        self.assertTrue(all(isinstance(p, Pesticide) for p in candidates))
        self.assertEqual([p.common_name for p in candidates], ["螺螨酯"])
        self.assertTrue(self.conn.assert_no_literal("anthracnose"))
        sql, params = self.conn.queries[-1]
        self.assertEqual(params, ("anthracnose",))

    def test_fetch_candidates_citrus_only_false(self):
        """citrus_only=False 时不附加柑橘登记过滤子句。"""
        fetch_candidates(self.conn, "red_spider_mite", citrus_only=False)
        sql, _ = self.conn.queries[-1]
        self.assertNotIn("is_registered_for_citrus", sql)

    def test_fetch_spray_history_ascending_and_joined(self):
        """施药记录按日期升序返回，药剂名与机理码已 join 填充。"""
        records = fetch_spray_history(self.conn, 1)
        self.assertEqual([r.spray_date for r in records],
                         [date(2026, 9, 1), date(2026, 9, 20), date(2026, 10, 1)])
        self.assertTrue(all(isinstance(r, SprayRecord) for r in records))
        self.assertTrue(all(r.pesticide_name for r in records))
        self.assertEqual(records[0].pesticide_name, "螺螨酯")
        self.assertEqual(records[0].frac_irac_code, "20B")

    def test_fetch_conflicts_and_contraindications(self):
        """配伍禁忌与物候期禁忌全量查询。"""
        conflicts = fetch_conflicts(self.conn)
        contraindications = fetch_contraindications(self.conn)
        self.assertEqual(len(conflicts), 1)
        self.assertIsInstance(conflicts[0], PesticideConflict)
        self.assertEqual(len(contraindications), 1)
        self.assertIsInstance(contraindications[0], PhenophaseContraindication)

    def test_fetch_orchard_found_and_missing(self):
        """地块存在返回 Orchard，缺失返回 None。"""
        orchard = fetch_orchard(self.conn, "测试地块")
        self.assertIsInstance(orchard, Orchard)
        self.assertEqual(orchard.block_name, "测试地块")
        self.assertIsNone(fetch_orchard(self.conn, "不存在的地块"))

    def test_fetch_all_sql_columns_exist(self):
        """全部 fetch_* 的 SQL 只引用 schema.sql 真实列，列名校验不抛异常。"""
        fetch_candidates(self.conn, "red_spider_mite")
        fetch_spray_history(self.conn, 1)
        fetch_conflicts(self.conn)
        fetch_contraindications(self.conn)
        fetch_orchard(self.conn, "测试地块")

    def test_column_checker_rejects_unknown_column(self):
        """列名校验器必须拒绝 schema.sql 中不存在的列。"""
        with self.assertRaises(AssertionError):
            _assert_columns_exist("SELECT sr.pesticide_name FROM spray_record sr")


class TestOrchestration(unittest.TestCase):
    """编排与入口测试。"""

    def setUp(self):
        """构造标准内存数据（含一块干净地块用于入口测试）。"""
        self.conn = FakeConn({
            "pesticide": [
                _pesticide_row(1, "阿维菌素"),
                _pesticide_row(2, "禁用神药", banned=1),
            ],
            "pest_pesticide": [
                {"id": 1, "pest_name": "red_spider_mite", "pesticide_id": 1,
                 "is_registered_for_citrus": 1, "dilution_ratio": "3000 倍液"},
                {"id": 2, "pest_name": "red_spider_mite", "pesticide_id": 2,
                 "is_registered_for_citrus": 1, "dilution_ratio": "1000 倍液"},
            ],
            "orchard": [
                {"id": 1, "block_name": "测试地块", "variety": "琯溪蜜柚", "tree_age": 8,
                 "current_phenophase": "膨大期", "expected_harvest_date": None, "area_mu": 5.0},
                {"id": 2, "block_name": "干净地块", "variety": "琯溪蜜柚", "tree_age": 6,
                 "current_phenophase": "膨大期", "expected_harvest_date": None, "area_mu": 3.0},
            ],
            "spray_record": [
                {"id": 1, "orchard_id": 1, "spray_date": date(2026, 10, 1),
                 "pesticide_id": 1, "dilution_ratio": "3000 倍液"},
            ],
            "pesticide_conflict": [],
            "phenophase_contraindication": [],
        })

    def test_build_filter_input_tuple(self):
        """返回五元组，长度 5 且类型依次正确。"""
        result = build_filter_input(self.conn, "red_spider_mite", "测试地块", date(2026, 10, 28))
        self.assertEqual(len(result), 5)
        orchard, candidates, spray_history, conflicts, contraindications = result
        self.assertIsInstance(orchard, Orchard)
        self.assertTrue(all(isinstance(p, Pesticide) for p in candidates))
        self.assertTrue(all(isinstance(r, SprayRecord) for r in spray_history))
        self.assertTrue(all(isinstance(c, PesticideConflict) for c in conflicts))
        self.assertTrue(all(isinstance(c, PhenophaseContraindication) for c in contraindications))

    def test_build_filter_input_missing_orchard(self):
        """地块不存在抛 ValueError，消息含地块名。"""
        with self.assertRaises(ValueError) as ctx:
            build_filter_input(self.conn, "red_spider_mite", "不存在的地块", date(2026, 10, 28))
        self.assertIn("地块不存在", str(ctx.exception))
        self.assertIn("不存在的地块", str(ctx.exception))

    def test_build_filter_input_invalid_pest(self):
        """非法病害名抛 ValueError。"""
        with self.assertRaises(ValueError):
            build_filter_input(self.conn, "melanose", "测试地块", date(2026, 10, 28))

    def test_run_prescription_output(self):
        """FakeConn 场景下跑通并产出 FilterOutput，allowed 与 rejected 均非空。"""
        output = run_prescription(self.conn, "red_spider_mite", "干净地块", date(2026, 10, 28))
        self.assertIsInstance(output, FilterOutput)
        self.assertTrue(output.allowed)
        self.assertTrue(output.rejected)
        self.assertEqual([p.common_name for p in output.allowed], ["阿维菌素"])
        self.assertIn("禁用神药", [r.name for r in output.rejected])


if __name__ == "__main__":
    unittest.main()