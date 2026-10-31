# 智能体编排器 · 可执行任务清单（v2 · 覆盖旧版）

> 依据：`.codeartsdoer/specs/orchestrator/spec.md`、`.codeartsdoer/specs/orchestrator/design.md`
> 目标产出：`agent/orchestrator.py`、`tests/test_orchestrator.py`
> 只读约束（禁止修改）：`labelmap.py`、`agent/vision_client.py`、`agent/vision_prompt.py`、`expert_knowledge.py`、`agent/discriminate.py`、`prescription/guardrail.py`、`prescription/load_from_db.py`、`prescription/rule_engine.py`
> 已确认的方案决策：D1 本地直出卡片；`__init__` 允许注入 `prescriber`；降级路径药名被护栏替换接受

---

## 0. 实施前置：实测结论与必须遵守的裁决

以下结论由对本仓库存量代码的**实际运行探针**得到，是后续所有任务与断言的既成事实，实施者不得按直觉改写：

| # | 实测项 | 实测结论 | 影响 |
|---|---|---|---|
| F1 | `prescription/load_from_db.py` | 存在，导出 `build_filter_input(conn, pest_name, block_name, today)` / `run_prescription(conn, pest_name, block_name, today=None)` | B5 可直连规则引擎 |
| F2 | `agent/prescribe_prompt.py` | **不存在** | 必须惰性导入 + 优雅降级到 D1 |
| F3 | `guardrail.validate_output` 对"…药…"文案 | `"当前条件下无合规可用药剂，请联系当地农技人员。"` → `violations=['规可用药']`，`suggested_text` 破坏原句为"当前条件下无合请咨询当地农技人员剂…" | **B6 必须跳过护栏** |
| F4 | 同上，对检疫四要点 | 含"无药可治""不可滥用农药""先喷药" → `violations` 非空（4 项） | **B4 必须跳过护栏**；原"以空白名单复核通过"断言不可用 |
| F5 | 同上，对健康月度建议 | 10 月建议含"采前 15 天停止用药" → `violations=['停止用药']` | B3 沿用 design 的"跳过护栏"，与 spec R12 一致 |
| F6 | 同上，对 D0 降级三段文本 | `violations=['用药','螺螨酯']`，药名被替换 | 属安全预期；warnings 必须记录 |
| F7 | 护栏安全写法验证 | 卡片写 `"推荐方案：\n 1. 阿维菌素（1.8% 乳油，安全间隔期 7 天）"` + 白名单 `['阿维菌素']` → `is_valid=True` | D1 卡片与 B5 文案采用此规范 |
| F8 | 护栏反面写法 | `"推荐用药：…"` → `violations=['推荐用药']`；`"可选用药剂：…"` → `['可选用药']` | 禁止使用此类措辞 |
| F9 | `discriminate.needs_clarification` | `top2=[(canker,0.55),(anthracnose,0.45)]`，margin 0.15 → `True`；`len(top2)<2` → `False` | 用例构造基准 |
| F10 | `next_question` | 仅当两候选组合存在于 `agent/questions.json` 的 `pairs` 中才返回；`top2` 不足两项返回 `None` | 用例 5/10/11/12 必须使用 `canker↔anthracnose`（或 `red_spider_mite↔healthy`、`canker↔healthy`）组合 |
| F11 | `apply_answer` | `answer_key="raised"` → `best=canker, conf=0.9122`（>0.6）；`answer_key` 不在问题库 → 原样返回 `conf=0.55`（<0.6） | 用例 11 用 `"raised"`，用例 12 用无效 key（等价"回答后仍低于地板"，同时覆盖 spec 5.7.3 异常场景 1） |
| F12 | 导入路径 | `from agent.orchestrator import PomeloAgent` 可用（命名空间包）；`from test_load_from_db import FakeConn` 仅在 pytest 将 `tests/` 加入 `sys.path` 时可用 | 测试文件必须自行插入 `ROOT` 与 `ROOT/tests` 到 `sys.path` |
| F13 | `token_summary` 一致性 | `MaaSClient.summary()` 与自持累加器格式相同，但 False/未返值场景下二者会分叉 | 统一以编排器自持 `_tokens` 为准，不委托 client |

### 裁决 D-A：出口护栏适用矩阵（本任务清单的强制约束）

| 分支 | 是否执行护栏 | 白名单 | 依据 |
|---|---|---|---|
| B1 解析失败兜底 | 跳过 | — | 编排器自撰、不含药名 |
| B2 鉴别问诊 | **执行** | `[]` | spec R12；实测追问文案不含"药"字（F7/F14） |
| B3 健康结论 | 跳过 | — | spec R12 明文允许 |
| B4 检疫性病害 | **跳过** | — | spec R12 明文允许；实测四要点必然误报（F4） |
| B5 规则引擎开方 | **执行** | `allowed[].common_name ∪ parsed 处方药名` | spec R12 |
| B6 无合规药剂降级 | **跳过** | — | spec R10 要求固定文案；实测护栏必破坏（F3） |
| B7/D0 未接数据库降级 | **执行** | `[]` | spec R12；药名被替换为安全预期（F6） |
| B8/D2 缺地块名降级 | **执行** | `[]` | 同上 |
| D1 本地直出卡片 | **执行** | `allowed[].common_name` | 卡片文案按规范 F7 编写即通过 |

### 裁决 D-B：护栏安全文案规范（编排器自撰文案必须遵守）

1. 文案中**不得出现"汉字 + 药"结构**（如"用药""药剂"紧跟汉字之后）；护栏后缀模式会把任何以"药"结尾的 1-3 字前缀窗口判定为违规药名。
2. 允许的写法：以标点/换行/空格把"药"与其他汉字隔开（如 `"方案："+"…"`、`"阿维菌素（1.8% 乳油…）"`），或改用"防治方案 / 可选成分 / 推荐剂型"等措辞。
3. 所有推荐药名必须**逐字取自白名单**（`allowed[].common_name`），不得由编排器自行拼写。
4. 该规范适用于 `_render_local_card`（D1）与 B2 的退化追问文案；B6 提示语沿用 spec 原文但**跳过护栏**。

### 裁决 D-C：需用户确认的一项

原需求中"用例 4 以 guardrail 空白名单校验四要点文本不报违规""用例 8 断言 final_text 含'无合规可用药剂'"与护栏实测行为冲突（F3/F4）。本清单已按 D-A 裁决为 **B4/B6 跳过护栏**，并相应调整断言；如用户坚持"必须过护栏"，则需同步修改 spec R7/R10 的固定文案措辞（超出本次新增文件范围）。

---

## 阶段一 · 数据契约与归一化

### T1 定义 AgentResult 数据契约与依赖协议

- **任务编号**：T1
- **前置依赖**：无
- **涉及文件**：`agent/orchestrator.py`（模块顶部：导入与类型声明区）
- **实现要点**：
  - 模块顶部插入 `sys.path.insert(0, str(Path(__file__).resolve().parent.parent))`，随后以顶层形式导入：`from vision_prompt import VISION_SYSTEM_PROMPT`、`from vision_client import validate_diagnosis, MaaSClient`、`from labelmap import HEALTHY_LABEL`、`from expert_knowledge import get_general_advice, get_advice, is_quarantine`、`from discriminate import needs_clarification, next_question, apply_answer`、`from prescription.guardrail import validate_output`（`run_prescription` 与 `prescribe_prompt` 见 T13 的惰性导入）。
  - 定义 `@dataclass AgentResult`，字段与 spec 6.1 逐字一致：
    `label: str`、`confidence: float`、`symptom: str`、`distinguish: str`、`final_text: str`、`prescription: dict | None`、`question: dict | None`、`degraded: bool`、`warnings: list[str]`、`steps: list[str]`、`tokens: dict`、`detection: dict | None = None`。
  - `tokens` 规范形态为 `{"prompt": 0, "completion": 0, "total": 0, "calls": 0}`。
  - 定义 `Protocol`：`DiagnoseClient`（`diagnose(images, extra_text, system_prompt) -> dict`）、`DbConn`（`query(sql, params=None) -> list[dict]`）、`Prescriber`（`generate_prescription(...) -> dict` / `render_prescription_card(result) -> str`）。
  - 全部中文 docstring；标识符英文 snake_case；使用 dataclass + 显式类型注解，不使用 `Any`。
- **验收标准**：
  - `from agent.orchestrator import AgentResult, PomeloAgent` 成功，且导入过程不触发网络/文件写入。
  - `dataclasses.asdict(AgentResult(label="", confidence=0.0, symptom="", distinguish="", final_text="x", prescription=None, question=None, degraded=False, warnings=[], steps=[], tokens={"prompt":0,"completion":0,"total":0,"calls":0}))` 字段齐全且键名与 spec 6.1 一致。

### T2 诊断结论 → 检测对象归一化（alternatives → top2）

- **任务编号**：T2
- **前置依赖**：T1
- **涉及文件**：`agent/orchestrator.py`（`_as_float`、`_normalize_detection`）
- **实现要点**：
  - `_as_float(value, default=0.0) -> float`：接受 `int/float`（显式排除 `bool`）；字符串尝试 `float()`；其余返回 `default`；绝不抛异常。
  - `_normalize_detection(diagnosis: dict) -> dict` 严格实现 design 2.1.3(3) 的 N1–N8：
    - `label`：仅当 `isinstance(diagnosis.get("label"), str)` 时取值，否则 `""`；
    - `confidence`：`_as_float(diagnosis.get("confidence"))`；
    - `bbox = []`；
    - `top2[0] = {"label": label, "score": _as_float(confidence)}`；
    - 第二候选：仅当 `isinstance(alts, list) and len(alts) >= 1 and isinstance(alts[0], dict)` 时取 `alts[0]`，**键名改名 `confidence` → `score`**；
    - 兜底 A（缺失/非 list/空）→ `top2` 长度 1；兜底 B（仅一条）→ 取该条为第二项；兜底 C（第二项 label 为空或与第一项相同）→ 丢弃第二项，长度 1。
  - 纯函数；不得在此函数内调用 `discriminate`。
- **验收标准**：
  - `alternatives` 含两条 → `len(top2)==2`、`top2[1]["label"]==alternatives[0]["label"]`、`top2[1]["score"]==alternatives[0]["confidence"]`；含一条 → `len==2`；缺失/为空 → `len==1`。
  - `detection["confidence"] == diagnosis["confidence"]`；`alternatives[0]["confidence"] == "0.3"` 时 `top2[1]["score"] == 0.3`；`confidence` 为 `True` 时归一化为 `0.0`。
  - `alternatives[0]["label"]` 与主 label 相同 → `len(top2)==1`。

---

## 阶段二 · 编排器骨架与 Token 计量

### T3 PomeloAgent 构造与 prescriber 注入点

- **任务编号**：T3
- **前置依赖**：T1
- **涉及文件**：`agent/orchestrator.py`（`PomeloAgent.__init__`）
- **实现要点**：
  - 签名严格为 `__init__(self, client, conn=None, month: int | None = None, conf_floor: float = 0.6, margin: float = 0.15, prescriber=None)`；`month` 缺省取 `datetime.now().month`。
  - 保存 `client / conn / month / conf_floor / margin`；`self._prescriber_injected = prescriber`（**注入点**，见 T13）。
  - 初始化 `self._tokens = {"prompt": 0, "completion": 0, "total": 0, "calls": 0}`。
  - 中文 docstring 注明"`conn=None` 表示未接入数据库，进入降级模式"；构造过程不发起任何网络请求、不读日历外的外部资源。
- **验收标准**：
  - `PomeloAgent(FakeClient(), conn=None).month == datetime.now().month`；显式 `month=10` 时为 10。
  - 传入 `prescriber=FakePrescriber()` 后 `agent._prescriber_injected` 为该对象；不传为 `None`。

### T4 Token 累加器与 token_summary

- **任务编号**：T4
- **前置依赖**：T3
- **涉及文件**：`agent/orchestrator.py`（`_accumulate_tokens`、`token_summary`）
- **实现要点**：
  - `_accumulate_tokens(self, payload: dict, count_call: bool = True)`：`prompt += _as_int(payload.get("prompt_tokens"))`、`completion += _as_int(payload.get("completion_tokens"))`；`count_call` 为真时 `calls += 1`；每次重算 `total = prompt + completion`。
  - `_as_int(value)`：`int/float`（排除 `bool`）取整，字符串尝试 `int(float())`，其余 0，不抛异常。
  - `token_summary(self) -> str` 固定格式 `"调用 N 次 | 输入 X | 输出 Y | 合计 Z tokens"`；**以编排器自持 `_tokens` 为准**，不委托 `client.summary()`（裁决 F13）。
- **验收标准**：
  - 两次累加 `{"prompt_tokens": 10, "completion_tokens": 5}` 后 `token_summary()` 含 `"调用 2 次"`、`"输入 20"`、`"输出 10"`、`"合计 30 tokens"`。
  - `payload` 缺 token 字段时按 0 计入且 `calls` 仍按参数递增，不抛异常。

---

## 阶段三 · 主链路诊断与分支收口

### T5 diagnose 步骤 1–3（调用 / 校验 / 归一化 / 解析兜底）

- **任务编号**：T5
- **前置依赖**：T2、T4
- **涉及文件**：`agent/orchestrator.py`（`diagnose` 前半段）
- **实现要点**：
  - 步骤 1：`r = self.client.diagnose(images, extra_text=extra_text, system_prompt=VISION_SYSTEM_PROMPT)`；`_accumulate_tokens(r)`；`steps` 追加 `"① 调用图文诊断大模型"`。
  - 步骤 2：`parsed = r.get("parsed")`；`problems = validate_diagnosis(parsed)`；逐条记入 `warnings`；`steps` 追加 `"② 校验诊断结论类别口径"`。
  - 步骤 3：`parsed is None or not isinstance(parsed, dict)` → 返回 `AgentResult(..., degraded=True, final_text="图片未能识别，请重拍清晰叶片照片后再试。", detection=None)`，同时 `warnings` 记 `"结论无法解析为 JSON"`，`steps` 追加 `"③ 结论不可用，输出重拍兜底提示"`，**立即返回**。
  - `parsed` 合法 → `detection = _normalize_detection(parsed)`，`steps` 追加 `"③ 归一化为检测对象（含 top2）"`。
  - `label`、`confidence`、`symptom`、`distinguish` 从 `parsed` 容错读取（`label` 非 str → `""`；`confidence` 用 `_as_float`；`symptom`/`distinguish` 非 str → `""`）。
  - 全流程不得静默吞异常；`client` 抛出的异常（`ValueError`/`FileNotFoundError`/`RuntimeError`）**不在此处捕获**，交由 CLI 层（T16）。
- **验收标准**：
  - 非 JSON 文本 → `degraded is True`、`final_text` 含"重拍"、`client.call_count == 1`、`detection is None`。
  - `label` 非法 → `warnings` 中任一条含 `"label 非法"`，但流程继续。
  - 一次完整调用后 `steps` 按序含 `"调用图文诊断大模型"`、`"校验诊断结论类别口径"`、`"归一化为检测对象"`。

### T6 _finalize 收口与八分支短路顺序

- **任务编号**：T6
- **前置依赖**：T5
- **涉及文件**：`agent/orchestrator.py`（`_finalize(detection, meta)`、`_base_result`）
- **实现要点**：
  - 新增 `_finalize(self, detection: dict, orchard_name: str | None) -> AgentResult`，按 design 2.1.3(1)(2) 的**短路顺序**依次判定，命中即返回：
    `B2 问诊 → B3 健康 → B4 检疫 → B5 开方 → B6 无合规药剂 → B7 未接数据库 → B8 缺地块名`。
  - 各分支实现分别见 T7–T13；本任务只负责调度骨架、`steps`/`warnings`/`prescription`/`degraded` 的组装与统一返回。
  - 统一出口：调用 `_apply_guardrail`（T14）并写入 `final_text`、`warnings`。
  - 每次返回前 `steps` 追加一行该分支的中文日志（如 `"④ 判定进入鉴别问诊分支"`）。
  - 所有分支的 `final_text` 必须非空（spec DFX 4.1-1）。
- **验收标准**：
  - 分支顺序可被验证：构造"低置信 + label=healthy"结论 → 走 B2 而非 B3（`question is not None`）。
  - 构造"高置信 + label=greening"→ 走 B4（`final_text` 含"上报"）。
  - 构造"高置信 + label=red_spider_mite + conn 非空 + orchard 非空"→ 走 B5。
  - 任意分支返回的 `AgentResult.final_text` 均非空。

---

## 阶段四 · 八分支落地

### T7 B2 鉴别问诊分支

- **任务编号**：T7
- **前置依赖**：T6
- **涉及文件**：`agent/orchestrator.py`（`_branch_ask`）
- **实现要点**：
  - 触发条件（任一命中）：`confidence < self.conf_floor` **或** `parsed.get("need_more_info") is True` **或** `parsed.get("image_quality") == "poor"` **或** `needs_clarification(detection, self.margin)`。
  - `question = next_question(detection)`；`final_text` 取值优先级：`parsed.get("follow_up_question")` 非空 → 用它；否则 `question["question"]`；两者皆空 → 使用**不含"药"字**的退化提示（如 `"图片置信度不足，请补拍一张叶背清晰照片以便进一步鉴别。"`，符合裁决 D-B）。
  - `final_text` 附加症状与区分点（`symptom`/`distinguish` 非空时拼接）。
  - **禁止**再次调用 `self.client.diagnose`（不烧 Token）；`prescription = None`；`degraded = False`（问诊不是降级）；护栏按 D-A 执行。
  - 结果对象必须携带 `detection`（供 T15 `answer_followup` 使用）。
- **验收标准**：
  - `confidence=0.45` + `alternatives=[{"label":"anthracnose","confidence":0.40}]`（label=canker）→ `question is not None`、`final_text` 含 `question["question"]`、`client.call_count == 1`。
  - 仅 `image_quality="poor"` 触发时行为一致。
  - `top2` 长度 1（无 alternatives）且 `confidence=0.45` 时 `question is None`，仍返回带症状/区分点的提示且 `final_text` 非空。

### T8 B3 健康结论分支

- **任务编号**：T8
- **前置依赖**：T6
- **涉及文件**：`agent/orchestrator.py`（`_branch_healthy`）
- **实现要点**：
  - 触发：`detection["label"] == HEALTHY_LABEL`（`labelmap` 唯一口径）。
  - `final_text = "未检出目标病害。" + get_general_advice(self.month)`；`get_general_advice` 返回空串时仅输出声明句，不崩。
  - **禁止**调用处方引擎与 `conn.query`；`prescription = None`；`degraded = False`；按 D-A 跳过护栏。
  - `steps` 追加 `"④-5 健康结论，输出当月常规养护建议"`。
- **验收标准**：
  - 注入 `label="healthy"`（`confidence=0.9`，无 alternatives）→ `prescription is None`、`conn.queries == []`、`degraded is False`。
  - `month=10` 时 `final_text` 含 `"采收"`；`month=1` 时含 `"清园"`。
  - 未调用 `validate_output`（用例内以 monkeypatch 计数器断言）。

### T9 B4 检疫性病害分支

- **任务编号**：T9
- **前置依赖**：T6
- **涉及文件**：`agent/orchestrator.py`（`_branch_quarantine`）
- **实现要点**：
  - 触发：`is_quarantine(detection["label"])` 为真（当前仅 `greening`）。
  - `final_text` 由编排器**硬编码四要点**组装：① 立即上报当地植保/农业部门；② 挖除病株（挖除前先灭除树上木虱）；③ 防治传播媒介柑橘木虱；④ 该病害无有效治疗药剂，不可依赖施药治愈。
    - **禁止**取 `get_advice(label,"occurred").medication_advice`（该字段含木虱药名）。
    - 文案措辞遵循裁决 D-B：不得出现"汉字+药"结构；用"无有效治疗药剂""不可依赖施药治愈"替代"无药可治"避免护栏语义混淆（本分支虽跳过护栏，但保持文案规范以便独立复核）。
  - `prescription = None`；`degraded = False`；按 D-A **跳过护栏**；`steps` 追加 `"④-6 检疫性病害，输出上报与防木虱指引"`。
- **验收标准**：
  - 注入 `label="greening"` → `final_text` 同含 `"上报"`、`"木虱"`、`"挖除"`。
  - `final_text` **不含任何真实药剂名**：对清单 `["吡虫啉","阿维菌素","螺螨酯","氢氧化铜","代森锰锌","咪鲜胺","苯醚甲环唑","农用链霉素","联苯菊酯","噻虫嗪","矿物油"]` 逐项 `not in`。
  - `validate_output` 未被调用。

### T10 B5 规则引擎开方分支

- **任务编号**：T10
- **前置依赖**：T6
- **涉及文件**：`agent/orchestrator.py`（`_branch_prescribe`）
- **实现要点**：
  - 触发：`self.conn is not None and orchard_name`。
  - `try: output = run_prescription(self.conn, detection["label"], orchard_name, today=date.today())`；`except ValueError`（地块不存在 / 病害非法）→ 记 `warnings`（含原异常中文消息），转入 T12 的 D2/D0 降级，**不外抛**。
  - `output.allowed` 非空 → 取 `prescriber = self._load_prescriber()`（T13）：
    - 可用：`res = prescriber.generate_prescription(self.client, parsed, output.allowed, output.rejected, orchard_name, self.month)` → `_accumulate_tokens(res)`（`calls += 1`）→ `final_text = prescriber.render_prescription_card(res)`；`prescription = res`；`degraded = False`。
    - 不可用：走 T13 的 D1 本地直出卡片。
  - `steps` 追加 `"④-4 规则引擎过滤候选药剂"` 与 `"⑤ 生成/渲染处方卡片"`。
  - 白名单按 T14 构造（`allowed` 通用名 ∪ `parsed` 处方药名）。
- **验收标准**：
  - `FakeConn` 场景 `red_spider_mite` + `FakePrescriber` → `degraded is False`、`prescription is not None`、`final_text` 含放行通用名（如 `"阿维菌素"`）、`tokens["calls"] == 2`。
  - 地块不存在（`block_name` 未注册）→ 不抛异常，`degraded is True` 且 `warnings` 非空。
  - `output.allowed` 非空但 `prescriber` 返回 `used_fallback=True` 时不视为编排器降级（沿用 prescriber 语义）。

### T11 B6 无合规可用药剂降级

- **任务编号**：T11
- **前置依赖**：T10
- **涉及文件**：`agent/orchestrator.py`（`_branch_no_pesticide`）
- **实现要点**：
  - 触发：T10 已执行 `run_prescription` 且 `output.allowed == []`。
  - `final_text = "当前条件下无合规可用药剂，请联系当地农技人员。"`（spec R10 原文，保持不改写）。
  - `degraded = True`；`warnings` 记 `"全部候选药剂被规则拒绝（安全间隔期/抗药性/次数上限/物候期/配伍禁忌）"`；`prescription = {"allowed": [], "rejected": [...], "source": "local_rule_engine", "used_fallback": True}`。
  - 按裁决 D-A **跳过护栏**（否则 F3 会破坏固定文案）。
  - `steps` 追加 `"⑤-1 无合规可用药剂，输出降级提示"`。
- **验收标准**：
  - 注入全部候选被禁用的 `FakeConn` → `degraded is True`、`final_text` 含 `"无合规可用药剂"`、`warnings` 非空、`validate_output` 未被调用。

### T12 B7/D0 未接数据库降级与 B8/D2 缺地块名降级

- **任务编号**：T12
- **前置依赖**：T6
- **涉及文件**：`agent/orchestrator.py`（`_branch_fallback_advice`）
- **实现要点**：
  - D0（`conn is None`）与 D2（`conn` 非空但 `orchard_name` 为空，含 T10 的 `ValueError` 转降级）共用本分支。
  - 文本来源：`adv = get_advice(label, "occurred")`；`final_text = adv.prevention_measures + "\n" + adv.medication_advice + "\n" + adv.farming_advice + "\n数据来源：" + adv.data_source`（四段拼接，`data_source` 为合规必透出字段）。
  - `degraded = True`；`prescription = None`。
  - `warnings`：D0 记 `"未接数据库，处方未经安全间隔期/抗药性/复配禁忌校验"`；D2 记 `"未提供地块名，未走处方引擎，已改用专家库通用防治建议"`。
  - 护栏按 D-A **执行**（空白名单）；药名被替换属预期，护栏命中时追加 `warnings`：`"降级路径含未校验参考药名，已由护栏替换为安全提示"`。
  - `steps` 追加 `"④-7 进入降级路径，改用专家库防治建议"`。
- **验收标准**：
  - `conn=None`、`label="red_spider_mite"` → `degraded is True`、任一 `warnings` 含 `"未接数据库"`、`final_text` 含 `"剪除"` 或 `"集中销毁"`（`occurred` 建议正文；不依赖"通风透光"这类 `prevention` 措辞）。
  - `conn` 非空 + `orchard_name=None` → `degraded is True`、`warnings` 非空、`conn.queries == []`（未走处方引擎）。
  - `final_text` 含 `"数据来源"`（合规字段透出）。

### T13 D1 本地直出卡片与 prescriber 惰性导入

- **任务编号**：T13
- **前置依赖**：T10
- **涉及文件**：`agent/orchestrator.py`（`_load_prescriber`、`_render_local_card`）
- **实现要点**：
  - **注入点（用户已确认）**：`_load_prescriber(self)` → 若 `self._prescriber_injected is not None` 直接返回之；否则 `try: from agent import prescribe_prompt as mod; return mod` / `except ImportError: return None`。**不得写死导入**，严禁在模块顶层无条件 `import prescribe_prompt`。
  - `_render_local_card(self, output, block_name, pest_name) -> str`：仅渲染 `output.allowed` 中的药剂（来源为规则引擎放行，从源头杜绝幻觉），格式遵循裁决 D-B：
    ```
    【防治方案·规则引擎直出】
    地块：<block_name>
    防治对象：<pest_name>
    可选成分：
      1. <common_name>（<content>，安全间隔期 <phi_days> 天）
    ...
    数据来源：规则引擎本地直出（未经文案生成组件润色）
    ```
    不得出现"用药/药剂/推荐用药"等"汉字+药"措辞（实测 F8 会被护栏拦截）。
  - D1 触发条件：`self.conn` 非空、`orchard_name` 非空、`run_prescription` 成功且 `allowed` 非空，但 prescriber 不可用。
  - D1 的结果：`degraded = True`（表示"未经 LLM 文案生成"，**不表示**未经规则引擎）；`prescription = {"parsed": None, "text": 本地卡片, "used_fallback": True, "source": "local_rule_engine", "allowed": allowed}`；`warnings` 记 `"文案生成组件缺失，处方为规则引擎直出"`；Token `calls` 不增。
  - 护栏按 D-A 执行，白名单 = `allowed[].common_name`；按 F7 编写的卡片应 `is_valid=True`。
- **验收标准**：
  - 未注入 prescriber 且 `agent/prescribe_prompt.py` 不存在 → 不抛异常，走 D1：`degraded is True`、`prescription["source"] == "local_rule_engine"`、`final_text` 含放行通用名（如 `"阿维菌素"`）、`tokens["calls"] == 1`（仅诊断一次）。
  - 注入 `FakePrescriber` → 走正常态（`degraded is False`、`prescription["source"] != "local_rule_engine"`）。
  - D1 卡片文本 + 白名单 `allowed` 通用名 → `validate_output(...)["is_valid"] is True`。

---

## 阶段五 · 出口护栏

### T14 白名单构造与护栏适用矩阵

- **任务编号**：T14
- **前置依赖**：T7–T13
- **涉及文件**：`agent/orchestrator.py`（`_build_whitelist`、`_apply_guardrail`）
- **实现要点**：
  - `_build_whitelist(prescription: dict | None, allowed: list | None) -> list[str]`：
    - 来源①：`prescription["parsed"]["prescription"][*]["pesticide_name"]`（字段缺失/类型不符一律容错跳过）；
    - 来源②：`allowed[*].common_name`（支持 dataclass 属性与 dict 两种形态）；
    - 无处方 → `[]`；结果去重并剔除空串。
  - `_apply_guardrail(self, text: str, whitelist: list[str], skip: bool = False) -> tuple[str, list[str]]`：
    - `skip is True` → 原样返回、不产生告警；
    - 否则 `res = validate_output(text, whitelist)`；`res["is_valid"] is False` → 返回 `res["suggested_text"]` 并追加告警 `"出口护栏拦截白名单外药名：{violations}"`；
    - `text` 为空串 → 直接返回（不调用护栏）。
  - 适用矩阵严格按裁决 D-A：B1/B3/B4/B6 传 `skip=True`；B2/B5/B7/B8/D1 执行护栏。
  - 白名单宽严策略沿用手册"宁可误报，不可漏报"，**不额外放松**。
- **验收标准**：
  - `_build_whitelist(None, None) == []`；`_build_whitelist({"parsed": {"prescription": [{"pesticide_name": "阿维菌素"}]}}, [Pesticide(common_name="螺螨酯", ...)])` 含 `"阿维菌素"` 与 `"螺螨酯"`；缺 `parsed` 时不抛异常。
  - 文本含白名单外药名（如 `"多菌灵"`，白名单 `["阿维菌素"]`）→ 返回文本含 `"请咨询当地农技人员"`、告警非空。
  - `skip=True` 时不调用 `validate_output`（monkeypatch 计数为 0）。

---

## 阶段六 · 追问续答

### T15 answer_followup 后验续答

- **任务编号**：T15
- **前置依赖**：T14
- **涉及文件**：`agent/orchestrator.py`（`answer_followup`）
- **实现要点**：
  - 前置：`result.detection` 非空（首次问诊分支返回的结果）；否则记 `warnings` 并原样返回 `result`。
  - `updated = apply_answer(result.detection, answer_key)`；用 `updated["best"]` 覆盖 `detection["label"]`、`updated["confidence"]` 覆盖 `detection["confidence"]`、`updated["top2"]` 覆盖 `detection["top2"]`（`apply_answer` 可能翻转 best，必须同步）。
  - `steps` 追加 `"⑥ 追问后验更新（label/confidence/top2）"`；**不调用** `self.client.diagnose`（不烧 Token）。
  - 新 `confidence < self.conf_floor` → 取 `question = next_question(detection)` 返回携带新追问的结果（复用 `result.tokens`，不清零）。
  - 否则 → 复用 `_finalize(detection, orchard_name)`（B3/B4/B5/B6 + 护栏）；`tokens` 基于 `result.tokens` 继续累加（进 B5 正常态时 `calls += 1`）。
  - `orchard_name` 由 `result` 携带（`AgentResult` 不含该字段，需在 `diagnose` 时把 `orchard_name` 存入实例或经 `steps` 元信息回传；实现上建议 `answer_followup` 增加可选参数 `orchard_name: str | None = None`，缺省沿用 `self._last_orchard`）。
- **验收标准**：
  - 低置信 0.55（`canker`/`anthracnose`）→ `answer_followup(result, "raised")` → `tokens["calls"] == 2`、`degraded is False`（有 conn+地块时进 B5）、`question is None`。
  - `answer_followup(result, "不存在的key")` → 置信度保持 0.55（<0.6）→ 新 `question is not None`、`conn.queries == []`（未走处方引擎）、`tokens["calls"]` 不增。
  - 对 `detection is None` 的 `result` 调用不抛异常。

---

## 阶段七 · 命令行入口

### T16 CLI main 与缺 Key 友好退出

- **任务编号**：T16
- **前置依赖**：T15
- **涉及文件**：`agent/orchestrator.py`（`main`、`if __name__ == "__main__"`）
- **实现要点**：
  - `argparse`：`--image`（必填）、`--extra`（默认 `""`）、`--orchard`（默认 `None`）、`--month`（`int`，可选）、`--json`（写出路径，可选）。
  - `try: client = MaaSClient(); except RuntimeError as e: print(友好中文指引); return 1`——**不打印堆栈、不泄露 Key**（指引文案复述"MaaS 控制台创建 Key + `setx MAAS_API_KEY` + 区域一致"三点）。
  - 正常流程逐段打印：诊断结论（label + 中文名，中文名可引用 `vision_client.CLASS_CN`）、症状、区分点、处方卡片（`final_text`）、`agent.token_summary()`、降级标记与全部告警。
  - `--json` 时 `json.dump(dataclasses.asdict(result), ensure_ascii=False, indent=2)` 写入指定路径（`Path.write_text(..., encoding="utf-8")`）。
  - 诊断过程中的 `ValueError`/`FileNotFoundError`（如图片不存在）需捕获并打印可读中文提示，返回非零码。
- **验收标准**：
  - 清空 `MAAS_API_KEY` 运行 `main(["--image", "x.jpg"])` → 返回 `1`、输出含 `"MAAS_API_KEY"` 指引、输出不含 `"Traceback"`。
  - 桩客户端路径下运行 → 输出含结论/症状/区分点/处方卡片/`token_summary`/告警六类信息（以 monkeypatch 替换 `MaaSClient` 验证）。
  - `--json` 输出文件可被 `json.load` 解析且含 `label`/`final_text`/`tokens` 键。

---

## 阶段八 · 测试与验收

### T17 测试桩（FakeClient / FakeConn / FakePrescriber）

- **任务编号**：T17
- **前置依赖**：T1
- **涉及文件**：`tests/test_orchestrator.py`（文件头 + 桩定义）
- **实现要点**：
  - 文件顶部插入 `ROOT = Path(__file__).resolve().parent.parent`，并 `sys.path.insert(0, str(ROOT))`、`sys.path.insert(0, str(ROOT / "tests"))`（裁决 F12）。
  - `FakeClient`：**不继承** `MaaSClient`（避免缺 Key 抛 `RuntimeError`）；构造入参 `responses: list[str] | None`；
    - `diagnose(images, extra_text="", system_prompt=None)`：从预设队列弹一条文本，用真实 `parse_json_relaxed` 解析，返回 `{"text", "parsed", "prompt_tokens", "completion_tokens", "total_tokens", "latency_s", "model"}`；`call_count += 1`、`total_prompt_tokens += …`；记录 `last_system_prompt`；
    - `chat(content, system=None, **kwargs)`：返回预设处方 JSON 文本并累计；`summary()` 返回与 `MaaSClient` 同格式字符串。
  - `FakeConn`：优先 `from test_load_from_db import FakeConn, _pesticide_row`（pytest 下 `tests/` 在 `sys.path` 中；若导入失败则内联极简版）。内联版需支持 SQL 路由（`candidate / spray_record / orchard / conflict / contraindication` 五类）与 `queries` 记录；可省略 `schema.sql` 列名校验以降低耦合。
  - `FakePrescriber`：`generate_prescription(client, diagnosis, allowed, rejected, orchard, month)` → `{"text": "<按裁决 D-B 编写的卡片>", "parsed": {"prescription": [{"pesticide_name": allowed[0].common_name}]}, "prompt_tokens": 12, "completion_tokens": 8, "used_fallback": False}`；`render_prescription_card(result)` → `result["text"]`。
  - 全部桩中文 docstring；**零真实网络**、不写 `agent/token_usage.jsonl`。
- **验收标准**：
  - 三个桩可被 `PomeloAgent` 直接使用，全程无 `requests` 调用。
  - `FakeClient()` 构造不抛异常（即使环境无 `MAAS_API_KEY`）。

### T18 测试用例（16 个，覆盖 spec R1–R17）

- **任务编号**：T18
- **前置依赖**：T2–T17
- **涉及文件**：`tests/test_orchestrator.py`
- **实现要点**（用例与断言清单）：

| # | 用例 | 关键构造 | 断言 | 覆盖 |
|---|---|---|---|---|
| C1 | 正常病害 + 有 DB | `label="red_spider_mite"`, `conf=0.9`, `conn=FakeConn`, `orchard="测试地块"`, `prescriber=FakePrescriber` | `degraded is False`；`prescription is not None`；`final_text` 含 `"阿维菌素"`；`tokens["calls"]==2` | R8 |
| C2 | 无 DB 降级 | `conn=None`, 同上 label | `degraded is True`；任一 warning 含 `"未接数据库"`；`final_text` 含 `"数据来源"` | R9 |
| C3 | 健康结论 | `label="healthy"`, `conf=0.9`, `month=10`, `conn=FakeConn` | `conn.queries == []`；`final_text` 含 `"采收"`；`prescription is None` | R6 |
| C4 | 检疫性病害 | `label="greening"`, `conf=0.9` | `final_text` 含 `"上报"`/`"木虱"`/`"挖除"`；真实药剂名清单逐项 `not in`；`validate_output` 未被调用 | R7 |
| C5 | 低置信问诊 | `label="canker"`, `conf=0.45`, `alternatives=[{"label":"anthracnose","confidence":0.40}]` | `question is not None`；`final_text` 含追问问题；`client.call_count == 1` | R5 |
| C6 | 解析失败兜底 | `FakeClient(responses=["抱歉，我无法识别这张图"])` | `degraded is True`；`final_text` 含 `"重拍"`；`detection is None` | R3 |
| C7 | 类别口径非法 | `label="melanose"`, `conf=0.9` | 任一 warning 含 `"label 非法"`；流程继续（`final_text` 非空） | R2 |
| C8 | 无合规药剂 | `FakeConn` 中候选药均 `is_banned=1` | `degraded is True`；`final_text` 含 `"无合规可用药剂"`；`validate_output` 未被调用 | R10 |
| C9 | 白名单外药名 | `FakePrescriber` 卡片含 `"多菌灵"`；白名单仅 `"阿维菌素"` | `final_text` 含 `"请咨询当地农技人员"`；`warnings` 非空 | R12 |
| C10 | 归一化兜底 | 三次诊断：`alternatives` 两条 / 一条 / 缺省 | `len(detection["top2"])` 分别为 2 / 2 / 1；`detection["confidence"]` 与结论一致 | R4 |
| C11 | 续答提升 | 先 C5 问诊 → `answer_followup(result, "raised")` | 进入开方；`tokens["calls"] == 2`；`question is None` | R13 |
| C12 | 续答仍低于地板 | 先 C5 问诊 → `answer_followup(result, "badkey")` | 新 `question is not None`；`conn.queries == []`；`tokens["calls"] == 1` | R14 |
| C13 | Token 汇总 | 任意一次诊断后 | `"tokens" in agent.token_summary()`；含 `"调用 1 次"` | R15 |
| C14 | 有 DB 无地块名 | `conn=FakeConn`, `orchard_name=None`, `label="canker"`, `conf=0.9` | `degraded is True`；`warnings` 非空；`conn.queries == []` | R11 |
| C15 | CLI 缺 Key | 清空 `MAAS_API_KEY`，调用 `main(["--image","x.jpg"])` | 返回 `1`；输出含 `"MAAS_API_KEY"`；无 `"Traceback"` | R16 |
| C16 | 零真实网络 | 全量用例仅用 `FakeClient`（可 `monkeypatch` 令 `requests.post` 抛异常以证明未被调用） | 所有用例通过且无网络异常 | R17 |

  - 用例 4/8 的"跳过护栏"通过 `monkeypatch` 计数断言（或在测试内包裹 `validate_output` 记录调用）。
  - 用例 5/10/11/12 必须使用 `questions.json` 中已存在的组合（`canker↔anthracnose`），否则 `next_question` 返回 `None`（裁决 F10）。
  - 中文 docstring；pytest 风格（必要时用 `pytest.mark.parametrize` 覆盖 C10 三态）。
- **验收标准**：
  - `"D:/anaconda3/python.exe" -m pytest tests/test_orchestrator.py -q` 全绿（≥16 passed）。
  - 无任何用例依赖真实 `MAAS_API_KEY` 或网络。

### T19 全量回归与只读约束核验

- **任务编号**：T19
- **前置依赖**：T18
- **涉及文件**：无（仅运行与核验）
- **实现要点**：
  - 运行 `cd E:\柚子病虫害AI识别\code\pomelo-algorithm && "D:/anaconda3/python.exe" -m pytest tests -q`。
  - 用 `git status --porcelain` / `git diff --name-only` 核验变更范围。
  - 若存量用例失败，逐一确认失败原因是否由新增文件引入（编排器不得反向修改存量模块）。
- **验收标准**：
  - 全量测试通过（含 `test_load_from_db.py`、`test_discriminate.py`、`test_expert_knowledge.py`、`test_labelmap.py`、`test_rule_engine.py` 等存量套件）。
  - 变更文件仅含 `agent/orchestrator.py`、`tests/test_orchestrator.py`、`.codeartsdoer/specs/orchestrator/*`；`labelmap.py / agent/vision_client.py / agent/vision_prompt.py / expert_knowledge.py / agent/discriminate.py / prescription/*.py` 未被修改。
  - 无临时探针/调试文件残留。

---

## 附：验收命令

```
cd E:\柚子病虫害AI识别\code\pomelo-algorithm && "D:/anaconda3/python.exe" -m pytest tests -q
```

全绿，且仅新增 `agent/orchestrator.py`、`tests/test_orchestrator.py` 两个文件。