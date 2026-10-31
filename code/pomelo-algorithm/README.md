# pomelo-algorithm（柚子病虫害 AI 识别 · 算法子项目）

负责柚子病虫害数据集准备、YOLOv5s 模型训练评估、模型格式转换与识别推理服务交付，为端云协同识别提供全部算法能力。

## 项目结构

```
pomelo-algorithm/
├── README.md                     # 本文件：项目说明 + 算法操作守则
├── labelmap.py                   # 类别映射表唯一口径（4 类体系 + 拼写别名 + 端云共用阈值）
├── prepare_dataset.py            # 数据准备：整理/切分/伪框/目录/配置/统计（纯标准库）
├── merge_roboflow.py             # Roboflow 合并：多边形转 bbox/映射过滤/rf_ 前缀（纯标准库）
├── training/                     # ModelArts Notebook 训练评估与导出脚本
│   ├── setup_notebook_env.sh     # 环境准备四段式（git clone + pip + OBS 拉取解压 + 路径校验）
│   ├── train_notebook.sh         # train.py 封装（img 640, batch 16, epochs 30 先行验证）
│   ├── val_notebook.sh           # val.py 封装（达标线 mAP@0.5 ≥ 0.5）
│   └── export_notebook.sh        # export.py 封装（--include onnx --img 640 --batch 1）
├── export/
│   └── README_convert.md         # converter_lite 端侧转换守则（FP32 + WEIGHT_QUANT 量化）
├── tools/
│   └── check_model_size.py       # .ms 体积校验门禁（FP32 ≤ 20MB / 量化 ≤ 7MB）
├── model/                        # ModelArts 在线服务部署包（自包含，zip 上传 OBS）
│   ├── config.json               # runtime 声明（python3.7 / pytorch1.8）
│   ├── customize_service.py      # BaseService 三段式：预处理/推理/后处理
│   └── README_deploy.md          # 打包 → OBS → AI 应用导入 → 部署 → API+Token 交付
├── postprocess/
│   ├── yolo_postprocess.py       # 端侧后处理参考实现（纯 numpy NMS，自包含）
│   └── README.md                 # 交付与端云对拍说明
├── agent/                        # 智能体主链路（唯一对外入口）
│   ├── orchestrator.py           # 主编排：诊断→问诊→处方→文案→护栏（已完成）
│   ├── demo_offline.py           # 一键离线演示（已完成；--with-api 待接真实 API）
│   ├── vision_client.py          # 华为云 MaaS 多模态客户端
│   ├── vision_prompt.py          # 多模态诊断系统提示词
│   ├── discriminate.py           # 病害鉴别判断（低置信追问 + 贝叶斯后验）
│   ├── questions.json            # 鉴别问题库
│   └── README.md                 # 鉴别判断对接说明 + 智能体主链路
├── prescription/                 # 处方规则引擎（本地）
│   ├── rule_engine.py            # 安全间隔期/抗药性/复配禁忌过滤
│   ├── load_from_db.py           # RDS 行 → dataclass 适配层（已完成）
│   ├── guardrail.py              # 出口药名白名单护栏（最后一道闸）
│   └── schema.sql                # 处方数据库表结构
├── expert_knowledge.py           # 专家知识库（月份-病虫害-防治建议）
└── tests/                        # 单元/功能测试（含离线端到端冒烟 test_e2e_offline.py）
```

## 类别映射表（唯一口径，交付工程与产品）

| 编号 | 类别名 | 中文 |
|------|--------|------|
| 0 | red_spider_mite | 红蜘蛛 |
| 1 | anthracnose | 炭疽病 |
| 2 | canker | 溃疡病 |
| 3 | healthy | 健康 |

二期扩展（如黄龙病）仅允许在末尾追加，禁止修改既有编号。

## 算法操作守则

### 1. ModelArts Notebook 用完即停
- Notebook 为 GPU 按需计费（如 T4/单卡），**训练/评估完成后必须立即停止实例**。
- 评估确认达标后，先下载 `best.pt` 至本地/OBS，再停止实例。

### 2. 训练达标线
- baseline 阶段：**mAP@0.5 ≥ 0.5**，未达标不得进入导出与部署，需补充数据重训。
- **禁止交付未评估或未达标的权重文件**。

### 3. 交付物清单
| 交付物 | 位置 | 交付对象 |
|--------|------|---------|
| YOLOv5 标准数据集 + citrus.yaml + 统计报告 | `--dst` 指定目录（打包 zip 上传 OBS） | 算法训练环节 |
| best.pt（达标）+ mAP@0.5 指标 | Notebook → 本地/OBS 备份 | 算法导出环节 |
| yolov5s_pomelo.ms / yolov5s_pomelo_quant.ms | `export/` 流程产出（项目目录保留副本） | 工程（鸿蒙 APP 资源目录） |
| 在线识别 API 地址 + Token | Token **线下交付**，禁止硬编码于仓库 | 工程（智能体"视觉识别"工具） |
| yolo_postprocess.py 参考实现 | `postprocess/` | 工程（翻译 OnDeviceDetector.ets postprocess()） |
| 类别映射表 | `labelmap.py` | 工程与产品（统一口径） |

### 4. 模型版本命名规范
- 训练运行名/交付文件名必须可追溯（如 `pomelo_baseline_v1`），禁止使用无版本标识的交付文件名。
- FP32 端侧模型命名 `yolov5s_pomelo.ms`，量化版命名 `yolov5s_pomelo_quant.ms`（决赛阶段前产出）。

### 5. 本地工具用法
```bash
# 数据准备（8:1:1 切分，种子 42，整图伪框）
python prepare_dataset.py --src "E:/datasets/raw" --dst "E:/datasets/pomelo_yolo"
# Roboflow 检测集合并（可选，多边形转 bbox，rf_ 前缀）
python merge_roboflow.py --rf-src "<Roboflow导出目录>" --dst "E:/datasets/pomelo_yolo"
# 端侧模型体积校验
python tools/check_model_size.py --file yolov5s_pomelo_quant.ms
# 运行全部测试
python -m unittest discover -s tests -v
```