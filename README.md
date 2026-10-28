# 柚康 · 柚子叶片病虫害 AI 识别（端云协同）

> **一句话定位**：基于鸿蒙（HarmonyOS）与华为云智能体的柚子病虫害识别助手——柚农拍张叶片照，端侧离线秒出类别、云端智能体给出防治建议与多轮问答。

---

## 赛题与背景

- **赛题**：第十一届华为 ICT 大赛创新赛 · **赛题一「基于华为云产品打造 AI 创新应用」**
- **选题**：柚子叶片病虫害 AI 识别（首发 3 类：红蜘蛛 / 炭疽病 / 溃疡病；黄龙病留作二期扩展）
- **主交付物**：**智能体（AI Agent）**，以 ModelArts Studio Agent开发 可视化对话 Demo 为主演示
- **前端形态**：鸿蒙原生 APP（ArkTS）+ 端侧 YOLOv5s 识别，与云端智能体形成"端云协同"
- **技术栈**：YOLOv5s + ModelArts + CodeArts 代码智能体 + RDS + 华为云部署 + HarmonyOS NEXT

**核心痛点**：柚农常把溃疡病当疮痂、黄龙病当缺素 → 误判 → 滥用药 → 成本升、果降级；农技覆盖不足，"拍照问专家"需求真实高频。

---

## 团队分工

| 角色 | 职责 |
|---|---|
| **算法** | YOLOv5s 训练/评估、自采数据、导出 ONNX→MindSpore Lite `.ms`、端侧后处理 |
| **工程** | 华为云环境/RDS/OBS/CodeArts、智能体编排与双 MCP、鸿蒙 APP 工程与端云联调、部署 |
| **产品** | RDS 防治表内容、智能体提示词、Demo 剧本、PPT、开源仓与文档 |

---

## 目录结构

```
柚子病虫害AI识别/
├── README.md                       # 本文件（项目总入口）
├── dataset/                        # 构建好的 YOLO 数据集（8:1:1）+ citrus.yaml
├── archive/                        # 原始公开数据集（CLP-14）
├── code/pomelo-algorithm/          # 算法侧：数据构建、训练、导出、在线服务
└── harmony-app/                    # 鸿蒙 ArkTS 工程骨架（DevEco Studio 打开）
    ├── README.md                   # 工程运行步骤与模型准备
    └── entry/src/main/
        ├── module.json5            # 权限（INTERNET/CAMERA/READ_MEDIA）
        ├── ets/
        │   ├── entryability/EntryAbility.ets   # 应用入口
        │   ├── pages/Index.ets                 # 主页面：拍照→双路识别→画框
        │   ├── common/AgentClient.ets          # 云端智能体 API 封装
        │   ├── common/OnDeviceDetector.ets      # 端侧 MindSpore Lite 推理封装
        │   └── model/Disease.ets               # 病害数据类型与类别映射
        └── resources/rawfile/      # 放置 yolov5s_pomelo.ms（转换后放入）
```

---

## 系统架构（端云协同）

```
鸿蒙 APP（ArkTS/ArkUI）
 ├─ 端侧（离线优先）：MindSpore Lite 加载 yolov5s_pomelo.ms → NPU/CPU 推理 → 病斑框
 └─ 云端（复杂任务）：POST 华为云智能体 API
       ├─ 工具① 视觉识别：YOLOv5s 在线服务（ModelArts）
       ├─ 工具② 知识检索：RDS 防治建议表
       └─ LLM 节点：自然语言防治建议 + 多轮追问
```

UI 标注结果来源（"端侧识别"/"云端智能体"），体现协同。工程运行步骤见
[harmony-app/README.md](./harmony-app/README.md)。

---

## 技术栈

| 分层 | 语言/框架 | 说明 |
|---|---|---|
| 模型训练 | Python + PyTorch | YOLOv5s 官方栈，ModelArts Notebook |
| 云端推理/工具 | Python | ModelArts 在线服务 + RDS 查询（pymysql） |
| 智能体编排 | 平台低代码 | ModelArts Studio Agent开发 |
| 前端/UI | **ArkTS + ArkUI** | HarmonyOS NEXT（API 11/12，Stage 模型） |
| 端侧推理 | **MindSpore Lite（.ms）**，ArkTS 直调或 C++ NAPI | 端侧 Native 层用 C++ |
| 云端通信 | ArkTS（`@ohos.net.http`） | 调智能体 API |
| 知识库 | SQL（MySQL / RDS） | `disease_advice(name, symptom, diff, control)` |

---

## 文档导航

| 文档 | 看什么 |
|---|---|
| [harmony-app/README.md](./harmony-app/README.md) | 鸿蒙工程运行步骤、端云协同方案、`.ms` 模型准备 |
| [code/pomelo-algorithm/README.md](./code/pomelo-algorithm/README.md) | 算法侧目录说明与训练/导出流程 |

---

## 快速开始

**算法**
1. 下载 CLP-14 + Roboflow 检测集，统一 4 类；建 ModelArts GPU Notebook 训练 YOLOv5s。
2. 部署为在线服务拿 API；导出 ONNX 并用 `converter_lite` 转 `.ms`：
   ```bash
   python export.py --weights best.pt --include onnx --img 640 --batch 1
   converter_lite --fmk=ONNX --modelFile=best.onnx \
     --outputFile=yolov5s_pomelo --inputShape="images:1,3,640,640"
   ```
3. 把 `yolov5s_pomelo.ms` 交给工程放入 `harmony-app/entry/src/main/resources/rawfile/`。

**工程**
1. 华为云实名+学生认证，开 ModelArts Studio / OBS / RDS / CodeArts。
2. DevEco Studio 打开 `harmony-app/`，配权限，填入智能体 API 地址/鉴权。
3. 真机/模拟器运行，验证"拍照→双路识别→画框"。

**产品**
1. 把病害档案录成 RDS 表内容；写智能体提示词与 Demo 剧本；建 Gitee 仓。

---

## 数据集

自建数据集由 `code/pomelo-algorithm/build_dataset.py` 一键构建（合并公开柑橘叶部数据集，
统一类别口径后按 8:1:1 切分），产出目录 `dataset/pomelo_yolo` 与 `citrus.yaml`，可直接喂 YOLOv5s。

```bash
cd code/pomelo-algorithm
python build_dataset.py --clp <CLP-14目录> --rf <Roboflow目录> --dst ../../dataset/pomelo_yolo
```

类别体系（nc=4）：`red_spider_mite` / `anthracnose` / `canker` / `greening`；
健康叶与易混淆非目标类（缺素、煤污、黑斑等）作为**负样本**参与训练，用于抑制误报。

---

## 需核实项

1. 代金券到账方式与额度。
2. 赛题一智能体平台确切名称（ModelArts Studio Agent开发 vs AgentArts）。
3. 自定义 MCP 的 SSE 地址要求与替代方案。
4. RDS 最低配规格与费用。
5. 竞品功能口径（AI 柚卫 / 耘眼）。
6. 鸿蒙端侧 MindSpore Lite 导入路径与 API（`@ohos.ai.mindsporelite` vs `@kit.MindSporeLiteKit`）。
7. 智能体 API 的 endpoint / 鉴权 / 请求体结构。

---

## 开源与答辩

- 入围中国总决赛/全球总决赛需开源至 Gitee/GitHub；README 中英对照，代码注释英文。
- 答辩：全球总决赛英文（大陆可用中文，英文加分）；PPT 中文为主+核心页英文。
- **演示为王**：必须演示真实系统；代码无法复现 PPT 效果即取消资格。

© 2026 柚子病虫害识别团队 · 华为 ICT 大赛创新赛赛题一
