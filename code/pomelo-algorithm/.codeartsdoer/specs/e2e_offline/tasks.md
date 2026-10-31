# 全离线端到端交付物 · 任务清单（tasks.md）

> 对应文档：`.codeartsdoer/specs/e2e_offline/spec.md`（需求）、`.codeartsdoer/specs/e2e_offline/design.md`（设计）。
> 工作目录：`E:\柚子病虫害AI识别\code\pomelo-algorithm`
> 运行环境：`D:/anaconda3/python.exe`；测试命令 `python -m pytest tests -q`；演示命令 `python agent/demo_offline.py`。
> 红线：`labelmap.py` / `prescription/rule_engine.py` / `prescription/guardrail.py` / `expert_knowledge.py` 既有行为不得改动；`*.jsonl` / `eval_*.json` / 含密钥文件不入库。

---

## 零、关键事实与已确认决策（进入实现前必读）

### 0.1 已核实事实（实现时以本表为准）

| 项 | 核实结论 |
|----|---------|
| `prescription/load_from_db.py` | 已完成，入口 `run_prescription(conn, pest_name, block_name, today) -> FilterOutput` |
| `agent/orchestrator.py` | 已完成（八分支短路口序 + B5→D1 本地直出卡片，共 548 行） |
| `agent/prescribe_prompt.py` | **不存在** → 可开方场景必走 D1（`_branch_local_card`），`degraded=True` |
| 基线测试 | 当前 `pytest tests -q` = 200 全绿 |
| git 仓库根 | `E:/柚子病虫害AI识别`（**非** `code/pomelo-algorithm`）；相对路径前缀为 `code/pomelo-algorithm/...` |
| 忽略规则 | 根 `.gitignore` 已覆盖 `*.jsonl`、`eval_*.json`、`.env`、`*.key`、`*secret*`、`*credential*` |
| tests 目录 | 无 `__init__.py`，桩通过 pytest 注入 `sys.path` 复用（既有约定，`test_orchestrator.py:17-22`） |
| 白名单取值路径 | D1 场景 `prescription["parsed"] is None`，白名单**唯一来源**是 `prescription["allowed"]`（`list[Pesticide]`），取 `item.common_name` |
| README 插入点 | `agent/README.md` 在第 140 行末尾追加；主 `README.md` 仅替换第 29 行单行 |

### 0.2 用户已确认决策（不可再协商）

1. **断言口径**：可开方三例（红蜘蛛/炭疽/溃疡）断言整段 `validate_output(final_text, 实际药名)["is_valid"] is True`；检疫（黄龙）/健康场景**豁免**整段 `is_valid`，改断言「`violations` ∩ 真实药剂名黑名单 = ∅」+ 黄龙零真实药剂。
2. **演示脚本桩策略**：`agent/demo_offline.py` 采用**脚本内自建等价桩**，禁止物理 import `tests` 目录。
3. **E2E 桩复用**：`tests/test_e2e_offline.py` 复用现有桩 —— `from test_orchestrator import FakeClient, _diag, _make_conn` + `from test_load_from_db import FakeConn, _pesticide_row`。

### 0.3 关键接口契约（实现对照，均已核实）

```python
# FakeClient.diagnose（tests/test_orchestrator.py:38-55）返回字段
{"text": str, "parsed": parse_json_relaxed(text), "prompt_tokens": 10,
 "completion_tokens": 5, "total_tokens": 15, "latency_s": 0.0, "model": "fake-vl"}

# FakeConn.query（tests/test_load_from_db.py:110-130）SQL 路由（正则 → 内存表）
"FROM pesticide p JOIN pest_pesticide pp"       → _candidates(params[0]=pest_name)
"FROM spray_record sr"                          → _spray_history(params=(orchard_id, limit))
"FROM orchard o\b"                              → _orchard(params[0]=block_name)
"FROM pesticide_conflict pc"                    → _tables["pesticide_conflict"]
"FROM phenophase_contraindication pct"          → _tables["phenophase_contraindication"]
# 注意：FakeConn.query 会先调用 _assert_columns_exist（列白名单校验），演示自建桩应跳过此步

# validate_output（prescription/guardrail.py:108）
validate_output(text: str, allowed_pesticide_names: list[str]) -> dict
# 返回 {"is_valid": bool, "detected": list[str], "violations": list[str], "suggested_text": str}
# 关键：PESTICIDE_SUFFIXES 含 "药"，检疫"无药可治"/健康"停止用药"会被判疑似药名 → 整段必 is_valid=False

# PomeloAgent 构造与结果
PomeloAgent(client, conn=None, month=None, conf_floor=0.6, margin=0.15, prescriber=None)
# AgentResult: label/confidence/symptom/distinguish/final_text/prescription/question/
#              degraded/warnings/steps/tokens/detection
# D1 prescription 结构: {"parsed": None, "text": ..., "used_fallback": True,
#                        "source": "local_rule_engine", "allowed": list[Pesticide]}
# tokens: {"prompt", "completion", "total", "calls"}

# 真实药剂名黑名单（spec 6.5，须与 test_orchestrator.py:201-202 一致）
BLACKLIST = ["吡虫啉", "阿维菌素", "螺螨酯", "氢氧化铜", "代森锰锌",
             "咪鲜胺", "苯醚甲环唑", "农用链霉素", "联苯菊酯", "噻虫嗪", "矿物油"]
```

---

## 任务总览

| 编号 | 名称 | 前置 | 涉及文件 | 优先级 |
|------|------|------|---------|--------|
| T1 | 基线回归与只读红线确认 | — | 无（只读排查） | P0 |
| T2 | 新建 E2E 冒烟测试 | T1 | `tests/test_e2e_offline.py` | P0 |
| T3 | 新建一键离线演示脚本 | T1 | `agent/demo_offline.py` | P0 |
| T4 | 更新 `agent/README.md` 追加主链路章节 | T2、T3 | `agent/README.md` | P0 |
| T5 | 更新主 `README.md` 模块清单 | T2、T3 | `README.md` | P1 |
| T6 | 全量回归与验收 | T2–T5 | 无 | P0 |
| T7 | 仓库卫生复核 | T6 | 根 `.gitignore`（只读核对） | P0 |

---

## T1 · 基线回归与只读红线确认

**前置依赖**：无
**涉及文件**：无（只读排查）

**实现要点**：
- [ ] T1.1 运行 `D:/anaconda3/python.exe -m pytest tests -q`，记录基线用例总数（预期 200）与通过状态，作为后续「用例数 ≥190」的对照锚点。
- [ ] T1.2 记录 `git status --porcelain` 初始状态；确认新增未跟踪项为 `code/pomelo-algorithm/agent/orchestrator.py`、`code/pomelo-algorithm/prescription/load_from_db.py`、`code/pomelo-algorithm/tests/test_{orchestrator,load_from_db}.py`、`code/pomelo-algorithm/.codeartsdoer/`，作为「仅应动文件」的对照基线。
- [ ] T1.3 若基线存在失败用例：逐条定位根因，修复**优先**落在本任务新写文件（`tests/test_e2e_offline.py`、`agent/demo_offline.py`）或已交付的 `orchestrator.py` / `load_from_db.py`；确需改动只读文件（`labelmap.py` / `rule_engine.py` / `guardrail.py` / `expert_knowledge.py`）时，**先说明理由并等待确认**，不得擅自规避。
- [ ] T1.4 确认 `labelmap.py` / `prescription/rule_engine.py` / `prescription/guardrail.py` / `expert_knowledge.py` 零改动（`git diff` 为空）。

**验收标准**：
- `pytest tests -q` 退出码 0、无 failed/error、用例总数 ≥190（基线 200）。
- 四个只读文件 diff 为空（或改动已附理由并经确认）。
- 基线用例数与 git 初始状态已记录。

---

## T2 · 新建 E2E 冒烟测试（`tests/test_e2e_offline.py`）

**前置依赖**：T1
**涉及文件**：`tests/test_e2e_offline.py`（新建）

**实现要点**：
- [ ] T2.1 **桩复用（复用现有桩，禁止自建）**：文件顶部按 `tests/test_orchestrator.py:17-22` 同一方式注入 `sys.path`（仓库根 + `tests/`），随后：
  `from test_load_from_db import FakeConn, _pesticide_row`
  `from test_orchestrator import FakeClient, _diag, _make_conn`
  `from agent.orchestrator import PomeloAgent`
  `from prescription.guardrail import validate_output`
- [ ] T2.2 **五场景构造**（统一 `month=10`，`PomeloAgent(client, conn=conn, month=10)`，**不注入 `prescriber`** 以真实触发 D1）：
  - 红蜘蛛：`_diag("red_spider_mite", 0.9)` + `_make_conn` 候选含阿维菌素（`pest_pesticide.pest_name="red_spider_mite"`、`is_registered_for_citrus=1`、`is_banned=0`）+ `orchard_name="测试地块"`。
  - 炭疽：`_diag("anthracnose", 0.9)` + 候选含螺螨酯 + `orchard_name="测试地块"`。
  - 溃疡：`_diag("canker", 0.9)` + 候选含氢氧化铜（可用 `_pesticide_row(3, "氢氧化铜", phi=14)`）+ `orchard_name="测试地块"`。
  - 黄龙：`_diag("greening", 0.9)` + `conn=None` + `orchard_name=None`。
  - 健康：`_diag("healthy", 0.9)` + `conn=None` + `orchard_name=None`。
  - 候选构造口径：`is_registered_for_citrus=1`、`is_banned=0`、`phi_days` 合规、无收获期约束（规避 design RK3 误拒）。
- [ ] T2.3 **通用断言**：5 例 `result.final_text` 均为非空字符串（`isinstance(str)` 且 `strip()` 非空）。
- [ ] T2.4 **可开方三例断言（同路径白名单）**：
  - `result.degraded is True`（D1 降级）；
  - 白名单**同路径**取值，禁止硬编码药名：`whitelist = [p.common_name for p in result.prescription["allowed"]]`；
  - 断言 `whitelist` 非空且含预期药名（阿维菌素 / 螺螨酯 / 氢氧化铜）；
  - `validate_output(result.final_text, whitelist)["is_valid"] is True` 且 `result["violations"] == []`；
  - 红蜘蛛额外断言 `"阿维菌素" in result.final_text`。
- [ ] T2.5 **黄龙断言（豁免整段 is_valid）**：
  - `final_text` 含"上报""木虱""挖除"；
  - `BLACKLIST` 逐一断言 `not in final_text`（零真实药剂）；
  - `violations = validate_output(final_text, [])["violations"]`，断言 `set(violations) & set(BLACKLIST) == set()`（允许"龙病无药"类误报）。
- [ ] T2.6 **健康断言（豁免整段 is_valid）**：
  - `final_text` 含"未检出目标病害"；
  - `BLACKLIST` 逐一不出现；
  - 同上 `violations ∩ BLACKLIST = ∅`。
- [ ] T2.7 **零网络**：文件级 `autouse` fixture 内 `monkeypatch.setattr("requests.post", boom)`，`boom` 抛 `AssertionError("不应发起真实网络请求")`，覆盖全文件所有用例；桩为纯进程内实现。
- [ ] T2.8 **中文汇总表**：`print` 一张中文表，列头固定"病害 | 结论 | 是否降级 | Token 数 | 处方药名"；`Token 数 = result.tokens["total"]`，药名取 T2.4 白名单（无则"—"）；表含 5 行；另设一个用例用 `capsys` 捕获 stdout，断言表头与 5 个场景行。

**验收标准**：
- `python -m pytest tests/test_e2e_offline.py -q` 全绿；
- 5 场景 `final_text` 非空；可开方三例 `is_valid is True` 且 `violations == []`；黄龙零真药剂 + 含"上报/木虱/挖除"；健康含"未检出目标病害"；
- 屏蔽 `requests.post` 后仍全绿（零真实网络）；
- stdout 含 5 行中文汇总表，列头字段齐全。

---

## T3 · 新建一键离线演示脚本（`agent/demo_offline.py`）

**前置依赖**：T1
**涉及文件**：`agent/demo_offline.py`（新建）

**实现要点**：
- [ ] T3.1 **脚本入口与路径注入**：脚本顶部注入 `_ROOT`（仓库根）与 `_AGENT_DIR`（agent 目录）到 `sys.path`，再 `from orchestrator import PomeloAgent` 与 `from vision_client import MaaSClient, parse_json_relaxed`（与 `orchestrator.py:23-34` 同风格）；实现 `main(argv: list[str] | None = None) -> int`。
- [ ] T3.2 **自建 `_FakeClient`（语义与 `tests/test_orchestrator.py:FakeClient` 等价）**：
  - `diagnose(images, extra_text="", system_prompt=None)` 返回结构**逐字段对齐**：
    `{"text", "parsed": parse_json_relaxed(text), "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15, "latency_s": 0.0, "model": "fake-vl"}`；
  - 预留 `chat(content, system=None, temperature=0.0, max_tokens=2048, model=None)` 供未来文案生成；
  - `parse_json_relaxed` 直接复用生产模块 `agent.vision_client`。
- [ ] T3.3 **自建 `_FakeConn`（SQL 路由与 `tests/test_load_from_db.py:FakeConn` 等价）**：
  - `query(sql, params=None) -> list[dict]`，按 SQL 文本正则路由，覆盖五类（与 0.3 契约一致）：
    `pesticide JOIN pest_pesticide`（候选，按 `params[0]=pest_name` 过滤 `pest_pesticide.pest_name`，join 出 `pesticide` 行）、`orchard`（按 `block_name`）、`spray_record`（按 `orchard_id` + `limit`）、`pesticide_conflict`、`phenophase_contraindication`；
  - **不实现** `_assert_columns_exist` 列校验（测试专用职责，演示桩仅做路由）；
  - 记录 `self.queries`（可选，便于自检）。
- [ ] T3.4 **五场景渲染**：与 T2.2 场景表一致（红蜘蛛/炭疽/溃疡/黄龙/健康，`month` 默认 10）。逐场景打印：诊断结论（中文 `CLASS_CN`）→ `final_text` → 步骤日志（`result.steps`）→ 是否降级（`result.degraded`）→ Token；可开方场景的 `final_text` 即 `_render_local_card` 卡片，直接打印。
- [ ] T3.5 **顶部离线横幅**：醒目 `print` 含关键字"【离线演示】未调用真实 API，Token 为模拟值；配置 MAAS_API_KEY 后自动切到真实链路"（须含"离线演示""模拟值""MAAS_API_KEY"）。
- [ ] T3.6 **`--with-api` 分支**：`argparse` 解析 `--with-api`（开关）与 `--month`（默认 10）；
  `use_api = args.with_api and bool(os.getenv("MAAS_API_KEY"))`；为真 → `client = MaaSClient()`；为假 → `client = _FakeClient(...)`；`--with-api` 但无 Key → **回退离线桩并打印提示，不中断**；真实调用异常用 `try/except` 包住，打印可读提示，**禁止打印 Key 内容、禁止抛堆栈**。
- [ ] T3.7 **末尾 Token 汇总表**：聚合 5 场景 `result.tokens`，输出"调用次数 / 输入 / 输出 / 合计"（`total = prompt + completion`）。
- [ ] T3.8 **禁止项**：文件内**无** `import tests` / `from test_* import`；**不实现任何落盘开关**（不产出 `token_usage.jsonl` / `eval_*.json` 等需 gitignore 的产物）。

**验收标准**：
- `D:/anaconda3/python.exe agent/demo_offline.py` 退出码 0，打印 5 场景完整对话与卡片、顶部离线提示、Token 汇总表；
- 无 `MAAS_API_KEY` 时完整跑完 5 场景；`--with-api` 无 Key 时回退离线桩且不报错；
- 文件内无 `tests` 目录导入；桩 `diagnose` 返回字段与 `FakeConn` 路由与测试桩语义等价（T2 输出与 T3 输出对同一场景结论一致）。

---

## T4 · 更新 `agent/README.md` 追加"智能体主链路"章节

**前置依赖**：T2、T3
**涉及文件**：`agent/README.md`（**仅在第 140 行末尾之后追加**；第 1-140 行原样保留）

**实现要点**：
- [ ] T4.1 在文档**末尾**追加顶级章节标题 `## 智能体主链路`，并写"一句话定位"：本模块是本项目**唯一对外入口**。
- [ ] T4.2 追加 ASCII 顺序图（纯文本）：
  `图片 → [MaaS 多模态诊断] → 口径校验 → 置信度判据 → 鉴别问诊(可选) → 处方规则引擎(本地) → 文案生成(MaaS) → 药名护栏(本地) → 输出`
  并标注每步是否消耗 Token：诊断（消耗）/ 问诊（不新增调用，避免二次消耗）/ 文案生成（消耗，现缺失故走 D1）；口径校验、规则引擎、护栏**纯本地不消耗**。
- [ ] T4.3 追加"三种运行方式"：① 离线演示 `python agent/demo_offline.py`；② 接数据库（传入 `conn`）；③ 接真实 API（`setx MAAS_API_KEY "你的Key"` + `python agent/orchestrator.py --image <图片>`）。
- [ ] T4.4 追加"降级说明"：`degraded=True` 四种触发条件 —— ① 诊断结论无法解析（重拍兜底）；② 处方文案组件缺失（走 D1 本地直出卡片）；③ 放行药剂为空（"无合规可用药剂，请联系当地农技人员"）；④ 未接数据库 或 未提供地块名（专家库通用建议）。
- [ ] T4.5 追加"红线"：药名**只能**来自处方引擎放行清单（`allowed`），护栏是最后一道闸。

**验收标准**：
- `agent/README.md` 含"智能体主链路"章节及上述六项要素；
- 第 1-140 行（"病害鉴别判断模块对接说明"全文）diff 为空，既有内容未被破坏。

---

## T5 · 更新主 `README.md` 模块清单

**前置依赖**：T2、T3
**涉及文件**：`README.md`（**仅替换第 29 行 `└── tests/ ...` 整行**；第 1-28、30-77 行保留）

**实现要点**：
- [ ] T5.1 将第 29 行 `└── tests/                        # 单元/功能测试（本地 Python 3.12.7 可直接运行）` 整行替换为树形块（详见 design 2.1.3-C2），登记：`agent/`（含 `orchestrator.py`、`demo_offline.py`、`vision_client.py`、`README.md`）、`prescription/`（含 `load_from_db.py`、`rule_engine.py`、`guardrail.py`）、`tests/`（含 `test_e2e_offline.py` 与既有测试），保持 ASCII 树连接符正确闭合。
- [ ] T5.2 状态标注：`prescription/load_from_db.py`（已完成）、`agent/orchestrator.py`（已完成）、`agent/demo_offline.py`（已完成；`--with-api` 待接真实 API）、`tests/test_e2e_offline.py`（已完成）。
- [ ] T5.3 不得改动"类别映射表""算法操作守则"等其余章节。

**验收标准**：
- 主 `README.md` "项目结构"清单含上述 4 个新条目与状态标注；
- 除第 29 行外其余行 diff 为空。

---

## T6 · 全量回归与验收

**前置依赖**：T2–T5
**涉及文件**：无

**实现要点**：
- [ ] T6.1 运行 `D:/anaconda3/python.exe -m pytest tests -q`，确认退出码 0、用例总数 ≥190（含 T2 新增用例）。
- [ ] T6.2 运行 `D:/anaconda3/python.exe agent/demo_offline.py`，确认打印 5 场景、离线提示与 Token 汇总表，退出码 0。
- [ ] T6.3 若失败：按 T1.3 修复优先级处理（优先新写文件），重跑至全绿；修改只读文件须附理由。

**验收标准**：
- 全量测试全绿、用例数 ≥190；
- 演示脚本可跑完并打印"5 场景 + 离线横幅 + Token 汇总表"。

---

## T7 · 仓库卫生复核

**前置依赖**：T6
**涉及文件**：根 `.gitignore`（`E:/柚子病虫害AI识别/.gitignore`，只读核对）

**实现要点**：
- [ ] T7.1 **应纳入库（新增交付物）**：确认 `code/pomelo-algorithm/tests/test_e2e_offline.py`、`code/pomelo-algorithm/agent/demo_offline.py`、`code/pomelo-algorithm/agent/README.md`、`code/pomelo-algorithm/README.md`，以及设计产物 `code/pomelo-algorithm/.codeartsdoer/specs/e2e_offline/{spec,design,tasks}.md` 可被 `git add`（未被 ignore）。
- [ ] T7.2 **禁止入库**：`git status --porcelain` 复核变更仅含 T7.1 所列应动文件（及 T1 记录的既有未跟踪源码）；不得出现运行产物、密钥文件、无关文件。
- [ ] T7.3 **忽略复核**：`git check-ignore -v` 复核 `code/pomelo-algorithm/agent/token_usage.jsonl`、任意 `*.jsonl`、`eval_*.json`、`.env` / `*.key` / `*secret*` / `*credential*` 均被根 `.gitignore` 忽略；确认索引与暂存区无此类文件。
- [ ] T7.4 （若需提交）`git add` 仅添加 T7.1 应动文件；提交前再次 `git status --porcelain` 确认无产物/密钥混入。

**验收标准**：
- git 变更仅含应动文件；新增 4 个源码/文档交付物已纳入版本库；
- `*.jsonl` / `eval_*.json` / 含密钥文件均被忽略且未入索引/暂存区。

---

## 附：需求追溯（任务 → spec 需求）

| 任务 | 覆盖需求 |
|------|---------|
| T1 | R1、R2 |
| T2 | R3、R4、R5、R6、R7、R8 |
| T3 | R9、R10、R11、R12、R13 |
| T4 | R14 |
| T5 | R15 |
| T6 | R1、R3、R9 |
| T7 | R16、R17 |