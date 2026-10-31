# **load_from_db 组件任务清单（数据库适配层）**

> **生成时间**：2026-10-29（命名校正版）
> **对应设计文档**：`.codeartsdoer/specs/db_adapter/design.md`
> **对应规格文档**：`.codeartsdoer/specs/db_adapter/spec.md`
> **产品模块文件（新建）**：`prescription/load_from_db.py`
> **测试文件（新建）**：`tests/test_load_from_db.py`
> **硬约束**：不新增任何第三方依赖；不修改 `prescription/rule_engine.py`、`prescription/schema.sql`、`labelmap.py`；
> **验收口径**：`cd E:\柚子病虫害AI识别\code\pomelo-algorithm && "D:/anaconda3/python.exe" -m pytest tests -q` 全绿（含原有约 150 个用例）。

> **命名校正说明（相对上一版）**：上一版误将模块命名为 `prescription/db_adapter.py`、测试命名为 `tests/test_db_adapter.py`。
> 按用户原始需求，**模块文件统一为 `prescription/load_from_db.py`、测试文件统一为 `tests/test_load_from_db.py`**，本清单所有路径均已校正。
> `db_adapter` 仅为规格目录名，不作为文件/模块名。

---

## **任务概览**

| 任务编号 | 任务名称 | 所属任务组 | 前置依赖 | 涉及文件 | 复杂度 | 状态 |
|---------|---------|-----------|---------|---------|--------|------|
| T-001 | 新建模块与 `DbConn` Protocol | 1. 模块骨架与连接协议 | 无 | `prescription/load_from_db.py`（新建） | 低 | 待开始 |
| T-002 | 实现 5 个 `_parse_*` 解析工具 | 2. 字段解析与行加载 | T-001 | `prescription/load_from_db.py` | 中 | 待开始 |
| T-003 | 实现 5 个 `load_*` 加载函数 | 2. 字段解析与行加载 | T-002 | `prescription/load_from_db.py` | 中 | 待开始 |
| T-004 | 实现 5 个 `fetch_*` + `_fetch_orchard_row` | 3. 参数化数据查询 | T-001, T-003 | `prescription/load_from_db.py` | 高 | 待开始 |
| T-005 | 实现 `build_filter_input` | 4. 编排与便捷入口 | T-004 | `prescription/load_from_db.py` | 低 | 待开始 |
| T-006 | 实现 `run_prescription` | 4. 编排与便捷入口 | T-005 | `prescription/load_from_db.py` | 低 | 待开始 |
| T-007 | 实现 `FakeConn` + schema 列名校验器 | 5. 测试基建 | T-001 | `tests/test_load_from_db.py`（新建） | 高 | 待开始 |
| T-008 | 编写 24 个单元测试用例 | 6. 测试用例 | T-002~T-007 | `tests/test_load_from_db.py` | 高 | 待开始 |
| T-009 | 全量回归验证 | 7. 回归验证 | T-008 | 全仓库（只读） | 低 | 待开始 |

**总预估工时**：约 6.5 人天。

---

## **导出函数覆盖矩阵（12 个导出函数）**

| 序号 | 导出函数 | 类型 | 归属任务 |
|------|---------|------|---------|
| 1 | `load_pesticide(row) -> Pesticide` | 加载 | T-003 |
| 2 | `load_orchard(row) -> Orchard` | 加载 | T-003 |
| 3 | `load_spray_record(row) -> SprayRecord` | 加载 | T-003 |
| 4 | `load_conflict(row) -> PesticideConflict` | 加载 | T-003 |
| 5 | `load_contraindication(row) -> PhenophaseContraindication` | 加载 | T-003 |
| 6 | `fetch_candidates(conn, pest_name, citrus_only=True)` | 查询 | T-004 |
| 7 | `fetch_spray_history(conn, orchard_id, limit=100)` | 查询 | T-004 |
| 8 | `fetch_conflicts(conn)` | 查询 | T-004 |
| 9 | `fetch_contraindications(conn)` | 查询 | T-004 |
| 10 | `fetch_orchard(conn, block_name)` | 查询 | T-004 |
| 11 | `build_filter_input(conn, pest_name, block_name, today)` | 编排 | T-005 |
| 12 | `run_prescription(conn, pest_name, block_name, today=None)` | 入口 | T-006 |

> 另含协议 `DbConn`（T-001）与 5 个私有解析工具 `_parse_*`（T-002）、私有辅助 `_fetch_orchard_row`（T-004）。

---

## **测试用例覆盖矩阵（24 个用例，≥ 用户要求的 14 类场景）**

| 编号 | 测试函数 | 场景 | 预期 | 归属任务 |
|------|---------|------|------|---------|
| TC-01 | `test_registered_crops_json` | `'["柑橘","柚子"]'` | 两个元素 | T-008 |
| TC-02 | `test_registered_crops_comma` | `"柑橘,柚子"` | 两个元素 | T-008 |
| TC-03 | `test_registered_crops_empty` | `None` / `""` | `[]` | T-008 |
| TC-04 | `test_is_banned_truthy_forms` | `1,"1",True,"true","True"` | 全 `True` | T-008 |
| TC-05 | `test_is_banned_falsy_forms` | `0,"0",False,None,""` | 全 `False` | T-008 |
| TC-06 | `test_phi_days_empty_str` | `phi_days=""` | `None` | T-008 |
| TC-07 | `test_phi_days_invalid_str` | `phi_days="abc"` | `None` | T-008 |
| TC-08 | `test_phi_days_valid` | `phi_days=15` / `"15"` | `15` | T-008 |
| TC-09 | `test_harvest_date_object` | `date(2026,11,20)` | `date(2026,11,20)` | T-008 |
| TC-10 | `test_harvest_date_str` | `"2026-11-20"` | 与 TC-09 一致 | T-008 |
| TC-11 | `test_spray_date_two_forms` | `date` 与 `"2026-11-20"` | 同一 `date` | T-008 |
| TC-12 | `test_load_defaults_missing` | 缺 `tree_age`/`current_phenophase` | `0` / `""` | T-008 |
| TC-13 | `test_load_pesticide_full_row` | 完整行 | 11 字段逐一断言 | T-008 |
| TC-14 | `test_load_orchard_row` | 完整行 | 日期解析 + `area_mu` 为 `float` | T-008 |
| TC-15 | `test_fetch_candidates_invalid_pest` | `"melanose"` | `ValueError`，消息含病害名 | T-008 |
| TC-16 | `test_fetch_candidates_parametrized` | `"anthracnose"` | SQL 不含字面量；`params` 正确 | T-008 |
| TC-17 | `test_fetch_spray_history_ascending_and_joined` | 乱序 3 条 | 升序 + `pesticide_name`/`frac_irac_code` 已 join | T-008 |
| TC-18 | `test_fetch_all_sql_columns_exist` | 全部 `fetch_*` | 列名白名单校验不抛异常 | T-008 |
| TC-19 | `test_build_filter_input_tuple` | 正常地块 | tuple 长度 5，类型依次正确 | T-008 |
| TC-20 | `test_build_filter_input_missing_orchard` | 荒地地块名 | `ValueError` 含 `地块不存在` 与地块名 | T-008 |
| TC-21 | `test_run_prescription_output` | 禁用药 + 正常药 | 返回 `FilterOutput`，`allowed`/`rejected` 均非空 | T-008 |
| TC-22 | `test_dirty_missing_registered_crops` | 缺 `registered_crops` | 不抛异常，`== []` | T-008 |
| TC-23 | `test_dirty_missing_phi_days` | 缺 `phi_days` | 不抛异常，`is None` | T-008 |
| TC-24 | `test_dirty_missing_frac_irac_code` | 缺 `frac_irac_code` | 不抛异常，`is None` | T-008 |

> 用户要求覆盖的 14 类场景（JSON 解析 / 逗号解析 / 空值 / 布尔化 / phi 非法 / phi 有效 / 日期双格式 / spray_date 双格式 / 非法 pest_name / 参数化 / 升序 join / tuple 长度 / 地块缺失 / 跑通 FilterOutput / 脏数据）已全部包含，并额外覆盖参数化断言、列名白名单与组合脏数据。

---

# **1. 模块骨架与连接协议**

> **任务组目标**：建立 `prescription/load_from_db.py` 基础结构，定义不依赖任何 MySQL 驱动的 `DbConn` 协议。

### **1.1 T-001 新建模块与 `DbConn` Protocol**

- **前置依赖**：无
- **涉及文件**：`prescription/load_from_db.py`（新建）
- **实现要点**：
  1. 文件首行 `from __future__ import annotations`（与 `rule_engine.py:13` 一致），统一用 PEP 604 注解风格（`int | None`）。
  2. 定义模块级 `logger = logging.getLogger(__name__)`。
  3. 定义 `DbConn(Protocol)`，方法 `query(self, sql: str, params: Sequence[Any] | None = None) -> list[dict]`；鸭子类型，不 `@runtime_checkable`。
  4. **禁止**硬 `import pymysql` / `mysql-connector`；如需标注驱动类型，仅放 `if TYPE_CHECKING:` 下。
  5. 导入 `from prescription.rule_engine import Pesticide, Orchard, SprayRecord, PesticideConflict, PhenophaseContraindication, FilterOutput, filter_pesticides`。
  6. 导入 `from labelmap import CLASS_NAMES`（`pest_name` 白名单）。
- **验收标准**：
  - [ ] 文件路径为 `prescription/load_from_db.py`，首行为 `from __future__ import annotations`
  - [ ] `DbConn` 为 `Protocol`，签名与上述一致
  - [ ] 模块无任何第三方运行时依赖，`python -c "import prescription.load_from_db"` 无报错
  - [ ] 不修改 `rule_engine.py` / `schema.sql` / `labelmap.py`

---

# **2. 字段解析与行加载**

> **任务组目标**：实现"数据库行 → rule_engine dataclass"的字段级容错转换，**任何脏数据只降级、不抛异常**。

### **2.1 T-002 实现 5 个 `_parse_*` 解析工具**

- **前置依赖**：T-001
- **涉及文件**：`prescription/load_from_db.py`
- **实现要点**：
  1. `_parse_registered_crops(value)`：原生 `list/tuple` → `json.loads`（仅当结果为 `list`）→ 分隔符回退（`,` `，` `、` `;` `；`）→ `[]`；每项 `strip` 且过滤空串。
  2. `_parse_bool(value)`：`1/"1"/True/"true"/"True"/"TRUE"/"yes"` → `True`；`0/"0"/False/None/""` → `False`；非上述类型一律 `False`。
  3. `_parse_int_or_none(value)`：`None/""/"abc"/bool` → `None`；`15/"15"/"15.0"` → `15`（`float` 先转 `int`）。
  4. `_parse_float_or_none(value)`：规则同构，返回 `float`；兼容 `Decimal`（`area_mu` 为 `DECIMAL(10,2)`）。
  5. `_parse_date(value)`：**先判 `datetime`**（`datetime` 是 `date` 子类）再判 `date`；字符串按 `"%Y-%m-%d"`、`"%Y/%m/%d"`、`"%Y-%m-%d %H:%M:%S"` 依次尝试；失败 → `None`。
- **验收标准**：
  - [ ] 5 个函数全部实现且有完整类型注解，对任意输入**不抛异常**
  - [ ] `'["柑橘","柚子"]'` → `["柑橘","柚子"]`；`"柑橘,柚子"` → `["柑橘","柚子"]`；`None`/`""` → `[]`
  - [ ] `1/"1"/True/"true"/"True"` → `True`；`0/"0"/False/None/""` → `False`
  - [ ] `""`/`"abc"` → `None`；`15/"15"` → `15`
  - [ ] `date(2026,11,20)` 与 `"2026-11-20"` → 同一 `date(2026,11,20)`
  - [ ] 支撑 TC-01 ~ TC-12 通过

### **2.2 T-003 实现 5 个 `load_*` 加载函数**

- **前置依赖**：T-002
- **涉及文件**：`prescription/load_from_db.py`
- **实现要点**：
  1. 统一用 `row.get("xxx")` 取字段，**严禁** `row["xxx"]` 下标（防 `KeyError`）。
  2. `load_pesticide(row) -> Pesticide`：11 字段全兜底——`formulation`/`content`/`common_name`/`active_ingredient` → `""`；`toxicity_level`/`frac_irac_code` → `None`；`id` 缺失 → `0`；`phi_days` 与 `max_times_per_season` 走 `_parse_int_or_none`；`is_banned` 走 `_parse_bool`；`registered_crops` 走 `_parse_registered_crops`。
     - **R-3**：`Pesticide.formulation`/`content` 为无默认值的必填 `str`，不可传 `None`。
  3. `load_orchard(row) -> Orchard`：`tree_age` 缺失/非法 → `0`；`current_phenophase` 缺失 → `""`；`variety`/`block_name` → `""`；`expected_harvest_date` 走 `_parse_date`（失败 `None`）；`area_mu` 走 `_parse_float_or_none`。**不读 `id`**（`Orchard` 无该字段）。
  4. `load_spray_record(row) -> SprayRecord`：`orchard_id`/`pesticide_id` 缺失 → `0`；`pesticide_name` → `""`；`frac_irac_code` → `None`；`spray_date` 走 `_parse_date`，解析失败兜底 `date.today()`（保 `date` 类型）；`dilution_ratio` → `None`。
  5. `load_conflict(row) -> PesticideConflict`：`pesticide_a_id`/`pesticide_b_id` → `0`；`conflict_type`/`description` → `""`；`severity` 显式兜底 `"中等"`（防行内 `None`）。
  6. `load_contraindication(row) -> PhenophaseContraindication`：`pesticide_id` → `0`；`phenophase`/`reason` → `""`。
- **验收标准**：
  - [ ] 5 个函数全部实现，输入缺任意字段的 `dict` **不抛异常**
  - [ ] `load_pesticide` 完整行 11 字段逐一正确（TC-13）
  - [ ] `load_orchard` 日期解析正确、`area_mu` 为 `float`（TC-14）
  - [ ] `spray_date` 支持 `date` 与 `"YYYY-MM-DD"` 双格式（TC-11）
  - [ ] 缺失 `tree_age`/`current_phenophase` → `0`/`""`（TC-12）
  - [ ] 支撑 TC-22 ~ TC-24 脏数据用例通过

---

# **3. 参数化数据查询**

> **任务组目标**：实现全部查询函数，使用 `%s` 参数化 SQL、逐列显式列出，白名单校验 `pest_name`。

### **3.1 T-004 实现 5 个 `fetch_*` + 私有 `_fetch_orchard_row`**

- **前置依赖**：T-001, T-003
- **涉及文件**：`prescription/load_from_db.py`
- **实现要点**：
  1. SQL 以模块级常量保存（如 `_SQL_CANDIDATES_CITRUS`、`_SQL_SPRAY_HISTORY`、`_SQL_ORCHARD`、`_SQL_CONFLICTS`、`_SQL_CONTRAINDICATIONS`），便于测试读取与断言。
  2. **列名白名单约束**：所有 SQL **逐列显式列出**（**禁 `SELECT *`**），列名必须与 `schema.sql` 真实列一致；这是"断言 SQL 只引用真实列"测试的硬前提（`p.*` 无法逐列校验）。
  3. `_fetch_orchard_row(conn, block_name) -> dict | None`（私有）：`SELECT id, block_name, variety, tree_age, current_phenophase, expected_harvest_date, area_mu FROM orchard WHERE block_name = %s`；返回**原始行**（含 `id`），供 `fetch_orchard` 与 `build_filter_input` 复用。
  4. `fetch_orchard(conn, block_name) -> Orchard | None`：复用 `_fetch_orchard_row`，缺失返回 `None`（**不抛异常**）。
  5. `fetch_candidates(conn, pest_name, citrus_only=True) -> list[Pesticide]`：
     - 入口先校验 `pest_name in CLASS_NAMES`，否则 `raise ValueError(f"病害名称不合法: {pest_name}")`。
     - SQL：`SELECT p.id, p.common_name, p.active_ingredient, p.formulation, p.content, p.frac_irac_code, p.phi_days, p.max_times_per_season, p.toxicity_level, p.is_banned, p.registered_crops FROM pesticide p JOIN pest_pesticide pp ON pp.pesticide_id = p.id WHERE pp.pest_name = %s [AND pp.is_registered_for_citrus = 1] ORDER BY p.id`；`params=(pest_name,)`；`citrus_only=False` 时去掉 `AND` 子句。
  6. `fetch_spray_history(conn, orchard_id, limit=100) -> list[SprayRecord]`：
     - SQL：`SELECT sr.orchard_id, sr.spray_date, sr.pesticide_id, p.common_name AS pesticide_name, p.frac_irac_code, sr.dilution_ratio FROM spray_record sr JOIN pesticide p ON p.id = sr.pesticide_id WHERE sr.orchard_id = %s ORDER BY sr.spray_date DESC LIMIT %s`；`params=(orchard_id, limit)`。
     - **R-2**：SQL 用 `DESC LIMIT` 取最近 N 条，**Python 端再按 `spray_date` 升序排序后返回**（`records.sort(key=lambda r: r.spray_date)`）。
  7. `fetch_conflicts(conn)`：`SELECT pesticide_a_id, pesticide_b_id, conflict_type, description, severity FROM pesticide_conflict` 全量。
  8. `fetch_contraindications(conn)`：`SELECT pesticide_id, phenophase, reason FROM phenophase_contraindication` 全量。
  9. **红线**：`spray_record` 表**无** `pesticide_name` / `frac_irac_code` 列，只能 JOIN `pesticide` 取（`p.common_name AS pesticide_name`）。
- **验收标准**：
  - [ ] 6 个函数全部实现（5 `fetch_*` + `_fetch_orchard_row`），均有完整类型注解
  - [ ] `fetch_candidates("melanose")` → `ValueError`，消息含病害名（TC-15）
  - [ ] `fetch_candidates` SQL 文本**不含** `pest_name` 字面量，`params` 正确传递（TC-16）
  - [ ] `fetch_spray_history` 返回**升序**，`pesticide_name` 非空、`frac_irac_code` 来自农药表（TC-17）
  - [ ] 全部 `fetch_*` 的 SQL 引用列均存在于 `schema.sql`（TC-18 列名白名单校验通过）
  - [ ] 所有 SQL 均 `%s` 参数化，逐列显式列出，无字符串拼接用户输入

---

# **4. 编排与便捷入口**

> **任务组目标**：一次组装规则引擎所需的五元组，并提供一站式 `FilterOutput` 入口。

### **4.1 T-005 实现 `build_filter_input`**

- **前置依赖**：T-004
- **涉及文件**：`prescription/load_from_db.py`
- **实现要点**：
  1. 签名 `build_filter_input(conn, pest_name, block_name, today) -> tuple[Orchard, list[Pesticide], list[SprayRecord], list[PesticideConflict], list[PhenophaseContraindication]]`。
  2. `pest_name ∉ CLASS_NAMES` → `ValueError(f"病害名称不合法: {pest_name}")`。
  3. 调用 `_fetch_orchard_row(conn, block_name)`；返回 `None` → `ValueError(f"地块不存在: {block_name}")`。
  4. **R-1（硬约束）**：`Orchard` dataclass **无 `id` 字段**，`orchard_id` 必须取自**原始行** `row["id"]`（经 `_parse_int_or_none`，缺失兜底 `0`）；**禁止**写 `orchard.id`。`orchard = load_orchard(row)` 与 `orchard_id` 源自**同一行**，保证一致。
  5. 依次调用 `fetch_candidates(pest_name)`、`fetch_spray_history(orchard_id)`、`fetch_conflicts(conn)`、`fetch_contraindications(conn)`。
  6. 返回 `tuple` 长度恒为 5，顺序与类型符合设计；`today` 为接口对齐保留（可供日志），组装本身不依赖它。
- **验收标准**：
  - [ ] 正常地块返回 `tuple` 长度 5，类型依次为 `Orchard, list[Pesticide], list[SprayRecord], list[PesticideConflict], list[PhenophaseContraindication]`（TC-19）
  - [ ] 地块不存在 → `ValueError`，消息含 `地块不存在` 与地块名（TC-20）
  - [ ] 代码中**不出现** `orchard.id`，`orchard_id` 来自 `row["id"]`
  - [ ] 地块查询仅执行 1 次（不重复查 `orchard` 表）

### **4.2 T-006 实现 `run_prescription`**

- **前置依赖**：T-005
- **涉及文件**：`prescription/load_from_db.py`
- **实现要点**：
  1. 签名 `run_prescription(conn, pest_name, block_name, today=None) -> FilterOutput`；`today = today or date.today()`。
  2. 调用 `build_filter_input(conn, pest_name, block_name, today)` 得五元组，再链式调用 `filter_pesticides(pest_name, orchard, spray_history, today, candidates, conflicts, contraindications)`（`disease` 为**位置**参数，传 `pest_name`）。
  3. **只返回 `FilterOutput`**，**不**调用 `format_rejection_report`（报告由调用方生成）；不处理用户交互。
  4. `build_filter_input` 的 `ValueError` 与驱动异常向上传播。
- **验收标准**：
  - [ ] 返回 `FilterOutput` 且 `allowed` 与 `rejected` 均非空（含禁用药场景，`rejected` 含"已被禁用"）（TC-21）
  - [ ] 未调用 `format_rejection_report`
  - [ ] `today` 缺省时使用 `date.today()`

---

# **5. 测试基建**

> **任务组目标**：在 `tests/test_load_from_db.py` 中构建内存数据库 FakeConn 与 `schema.sql` 列名白名单校验器。

### **5.1 T-007 实现 `FakeConn` + schema 列名校验器**

- **前置依赖**：T-001
- **涉及文件**：`tests/test_load_from_db.py`（新建）
- **实现要点**：
  1. `FakeConn(tables: dict[str, list[dict]])` 实现 `DbConn.query(sql, params=None) -> list[dict]`；内部 `self._tables` 为 `dict[str, list[dict]]`，`self.queries` 记录每次 `(sql, params)`。
  2. SQL 路由：用正则识别五类查询——
     - `FROM\s+pesticide\s+p\s+JOIN\s+pest_pesticide\s+pp` → 候选查询；
     - `FROM\s+spray_record\s+sr` → 施药查询；
     - `FROM\s+orchard\b` → 地块查询；
     - `FROM\s+pesticide_conflict\b` → 配伍字典；
     - `FROM\s+phenophase_contraindication\b` → 禁忌字典。
     未命中的 SQL 抛 `AssertionError`（防静默返回空导致假绿）。
  3. WHERE 参数绑定：从 `params` 顺序取（`pest_name`/`orchard_id`/`block_name`），`fetch_spray_history` 第 2 个作 `limit`；候选查询按 `pest_name` 及 `is_registered_for_citrus` 过滤后 join `pesticide` 并按 `p.id` 升序；施药查询按 `orchard_id` 过滤、按 `spray_date` 倒序取前 `limit` 条并 join `pesticide` 补 `pesticide_name`/`frac_irac_code`。
  4. `_schema_columns()`：读取 `Path(__file__).resolve().parent.parent / "prescription" / "schema.sql"`，用正则提取每个 `CREATE TABLE ...` 的列名集合 `{表名: {列}}`；跳过 `PRIMARY KEY / UNIQUE / INDEX / FOREIGN / CONSTRAINT` 开头的行，剥离反引号。
  5. `_assert_columns_exist(sql)`：建立 `FROM/JOIN <table> [AS] <alias>` 别名映射，提取所有 `alias.col` 与裸列，校验 `col ∈ tables[该表]`，否则 `AssertionError("<col> 不在 <table>")`；**排除 `AS 别名`** 右侧标识符。
  6. `assert_no_literal(literal) -> bool`：断言所有被记录 SQL 文本均不含指定字面量（如 `"anthracnose"`）。
  7. 不引入 `sqlparse` 等第三方库（手写正则）。
- **验收标准**：
  - [ ] `FakeConn` 实现 `query`，记录 `(sql, params)`，未识别的 SQL 抛 `AssertionError`
  - [ ] `_schema_columns()` 从 `prescription/schema.sql` 正确提取六张表列集合
  - [ ] `_assert_columns_exist` 能校验真实列、拒绝对不存在列（如 `spray_record.pesticide_name`）
  - [ ] `assert_no_literal` 可用于参数化断言
  - [ ] 调用全部 `fetch_*` 时列名校验**不抛异常**（证明 SQL 只引用真实列）

---

# **6. 测试用例**

> **任务组目标**：编写 24 个用例（覆盖用户要求的 14 类场景），全部含中文 docstring，无 skip。

### **6.1 T-008 编写 24 个单元测试用例**

- **前置依赖**：T-002, T-003, T-004, T-005, T-006, T-007
- **涉及文件**：`tests/test_load_from_db.py`
- **实现要点**：
  1. 统一 `unittest.TestCase` 风格（与 `tests/test_rule_engine.py` 一致，pytest 自动收集），**每个用例含中文 docstring**。
  2. `setUp` 构造标准 `FakeConn` 内存数据：`pesticide`、`pest_pesticide`、`orchard`、`spray_record`、`pesticide_conflict`、`phenophase_contraindication` 六张表。
  3. 用例清单见上文《测试用例覆盖矩阵》TC-01 ~ TC-24，逐一实现。
  4. TC-21 构造：一张 `is_banned=1` 的药（必被拒）+ 一张正常药（可通过），确保 `allowed` 与 `rejected` 均非空。
  5. 涉及"今天"的断言使用固定 `today`（如 `date(2026,10,28)`）以稳定结果。
  6. **脏数据组**（TC-22/23/24）：行缺 `registered_crops`/`phi_days`/`frac_irac_code` 均不得抛异常。
- **验收标准**：
  - [ ] 24 个用例全部实现且**每个含中文 docstring**，无 `skip`、无硬编码跳过
  - [ ] 覆盖 12 个导出函数与所有边界（解析 / 加载 / 查询 / 编排 / 入口 / 脏数据）
  - [ ] `"D:/anaconda3/python.exe" -m pytest tests/test_load_from_db.py -q` **全绿**

---

# **7. 回归验证**

> **任务组目标**：确认新增用例与原有约 150 个用例全部通过，且未触碰只读文件。

### **7.1 T-009 全量回归验证**

- **前置依赖**：T-008
- **涉及文件**：全仓库（只读）
- **实现要点**：
  1. 在项目根目录执行完整测试套件。
  2. 核对未修改 `prescription/rule_engine.py`、`prescription/schema.sql`、`labelmap.py`。
  3. 核对 `git status` 仅新增 `prescription/load_from_db.py` 与 `tests/test_load_from_db.py`（及规格文档）。
- **验收标准**：
  - [ ] `cd E:\柚子病虫害AI识别\code\pomelo-algorithm && "D:/anaconda3/python.exe" -m pytest tests -q` **全绿**（含原有约 150 个用例）
  - [ ] 无 `error` / `failed`；无因新增模块导致的 import 报错
  - [ ] `prescription/rule_engine.py`、`prescription/schema.sql`、`labelmap.py` 未被修改
  - [ ] `git status` 仅显示新增 `prescription/load_from_db.py` 与 `tests/test_load_from_db.py`（及文档）

---

## **执行顺序与依赖关系**

```
T-001 ──┬──→ T-002 ──→ T-003 ──→ T-004 ──→ T-005 ──→ T-006 ──┐
        │                                                      │
        └──→ T-007 ─────────────────────────────────────────────┴──→ T-008 ──→ T-009
```

**并行建议**：
- T-002 与 T-007 在 T-001 完成后可并行。
- T-008 必须在 T-002~T-007 全部完成后执行。

---

## **风险与红线**

1. **命名红线**：模块文件必须是 `prescription/load_from_db.py`，测试文件必须是 `tests/test_load_from_db.py`（本清单已统一，禁止出现 `db_adapter.py` / `test_db_adapter.py`）。
2. **R-1 硬约束**：`Orchard` dataclass **无 `id` 字段**，`build_filter_input` 禁止写 `orchard.id`，必须用 `_fetch_orchard_row` 原始行的 `row["id"]` 取 `orchard_id`。
3. **R-2 顺序约束**：`fetch_spray_history` SQL 用 `DESC LIMIT` 取最近 N 条，Python 端再升序返回，不可直接用 `ASC LIMIT`。
4. **R-3 必填字段**：`Pesticide` 的 `formulation`/`content`/`toxicity_level`/`frac_irac_code` 等无默认值，`load_pesticide` 必须显式传值。
5. **列名红线**：`spray_record` 无 `pesticide_name`/`frac_irac_code` 列，只能 JOIN `pesticide` 取；所有 SQL 逐列显式列出，禁用 `SELECT *`。
6. **参数化红线**：所有 SQL 用 `%s` + `params`，禁止字符串拼接；`pest_name` 过 `CLASS_NAMES` 白名单（`fetch_candidates` 与 `build_filter_input` 双保险）。
7. **依赖隔离**：禁止硬依赖 `pymysql` / `mysql-connector`，仅 `TYPE_CHECKING`；不新增任何第三方包。
8. **改文件红线**：不改 `rule_engine.py` / `schema.sql` / `labelmap.py`；只新增两个文件。
9. **回归红线**：原有约 150 个用例必须保持全绿。

---

**文档结束**