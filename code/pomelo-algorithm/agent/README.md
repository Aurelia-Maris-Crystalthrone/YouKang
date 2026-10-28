# 病害鉴别判断模块对接说明

## 模块定位

本模块是智能体"视觉识别"节点之后的"鉴别判断"分支节点。

**核心逻辑**：
1. 云端服务返回检测结果（含 top2 字段）
2. 本模块判断是否需要澄清（置信度差 < margin）
3. 需要澄清 → 追问关键鉴别特征
4. 用户回答 → 更新置信度后验 → 输出最终结论

## ModelArts Studio Agent 编排流程

```
[视觉识别节点] → [鉴别判断节点] → [需要澄清？]
                      │                  │
                      │                  ├─ 否 → [输出结论]
                      │                  │
                      │                  └─ 是 → [追问节点] → [用户回答] → [后验更新] → [输出结论]
                      │
                      └─ 无 top2 字段 → [输出结论]
```

### 节点配置

**鉴别判断节点**（Python 代码节点）：

```python
from agent.discriminate import needs_clarification, next_question, apply_answer

# 输入：云端服务返回的 detection
detection = inputs["detection"]

# 判断是否需要澄清
if needs_clarification(detection, margin=0.15):
    # 获取追问问题
    question = next_question(detection)
    outputs["needs_clarification"] = True
    outputs["question"] = question
else:
    outputs["needs_clarification"] = False
    outputs["conclusion"] = detection
```

**追问节点**（对话节点）：

- 使用 `question["question"]` 作为追问文案
- 使用 `question["answers"]` 作为答案选项
- 用户回答后，调用 `apply_answer()` 更新结论

**后验更新节点**（Python 代码节点）：

```python
from agent.discriminate import apply_answer

detection = inputs["detection"]
answer_key = inputs["answer_key"]

result = apply_answer(detection, answer_key)
outputs["conclusion"] = result
```

## 关键 API

### needs_clarification(detection, margin=0.15)

判断是否需要澄清。

**参数**：
- `detection`：云端服务返回的单个检测框，含 top2 字段
- `margin`：置信度差阈值，默认 0.15

**返回**：
- `True`：需要澄清（置信度差 < margin）
- `False`：可以硬下结论

### next_question(detection)

获取下一个追问问题。

**参数**：
- `detection`：云端服务返回的单个检测框，含 top2 字段

**返回**：
```json
{
  "best": "canker",
  "second": "anthracnose",
  "question": "病斑摸起来是隆起凸出来的，还是平塌陷下去的？",
  "question_key": "morphology",
  "answers": [
    {"key": "raised", "label": "隆起凸出", "likelihood": {"canker": 0.85, "anthracnose": 0.10}},
    {"key": "flat", "label": "平塌下陷", "likelihood": {"canker": 0.15, "anthracnose": 0.80}}
  ]
}
```

### apply_answer(detection, answer_key)

根据回答更新置信度后验。

**参数**：
- `detection`：云端服务返回的单个检测框，含 top2 字段
- `answer_key`：用户选择的答案 key

**返回**：
```json
{
  "best": "anthracnose",
  "second": "canker",
  "confidence": 0.72,
  "top2": [
    {"label": "anthracnose", "score": 0.72},
    {"label": "canker", "score": 0.28}
  ],
  "likelihood_used": {"canker": 0.15, "anthracnose": 0.80},
  "answer_key": "flat"
}
```

## 问题库结构

问题库位于 `agent/questions.json`，包含以下病害对：

| 病害对 | 区分特征 | 追问问题数 |
|--------|----------|-----------|
| canker vs anthracnose | 病斑形态、黄晕、轮纹小黑点 | 3 |
| canker vs scab | 穿透性、叶片变形 | 2 |
| greening vs deficiency | 黄化模式、发病部位、发病范围 | 3 |
| red_spider_mite vs healthy | 虫体、蛛丝、叶面斑点 | 3 |
| anthracnose vs greasy_spot | 轮纹小黑点、病斑形状、黄晕 | 3 |
| canker vs healthy | 病斑、黄晕 | 2 |

## 注意事项

1. **top2 字段必须存在**：云端服务返回的 detection 必须包含 top2 字段，否则本模块无法工作。
2. **margin 参数可调**：根据实际业务需求调整 margin，默认 0.15。
3. **问题库可扩展**：如需新增病害对，编辑 `questions.json` 即可。
4. **后验更新为简单贝叶斯**：当前实现为简单贝叶斯式加权，如需更复杂的推理模型，可替换 `apply_answer()` 函数。