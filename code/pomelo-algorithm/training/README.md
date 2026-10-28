# 训练操作守则（ModelArts Notebook）

> 对应 spec 5.2 模型训练与评估；覆盖指令 2.1/2.2 的 Notebook Terminal 逐段执行步骤。
> baseline 固定配置：img 640、batch 16、epochs 30 先行验证（达标后再 100）、
> 预训练权重 yolov5s.pt、运行名 pomelo_baseline_v1。

## 0. 前置准备（本地 → OBS）

1. 本地完成数据准备与合并，产出 YOLOv5 数据集目录（含 citrus.yaml、dataset_stats.txt）。
2. 打包数据集并上传 OBS（行动指南 4.2，obsutil 已配置 ak/sk/endpoint）：
   ```bash
   # 本地压缩 pomelo_yolo 目录为 pomelo_yolo.zip 后
   obsutil cp pomelo_yolo.zip obs://pomelo-agent/yolov5/pomelo_yolo.zip
   ```
3. 华为云控制台：开通 ModelArts → 全局访问授权 → 新建 Notebook（GPU，如 T4/单卡按需）→ 打开 JupyterLab → Terminal。

## 1. 环境搭建段（spec 5.2.1-2）

```bash
cd /home/ma-user/work
git clone https://github.com/ultralytics/yolov5.git
cd yolov5 && pip install -r requirements.txt
```

或整脚本运行（支持分段）：`bash setup_notebook_env.sh deps`

**失败处理（spec 5.2.3-5）**：git clone 或 pip install 因网络/版本冲突失败时，
确认 Notebook 可访问外网或配置 pip 镜像源后重试环境搭建段。

## 2. 数据集段（spec 5.2.1-3）

```bash
cd /home/ma-user/work
obsutil cp obs://pomelo-agent/yolov5/pomelo_yolo.zip ./
unzip pomelo_yolo.zip -d /home/ma-user/work/dataset
```

或：`bash setup_notebook_env.sh data`

**失败处理（spec 5.2.3-4）**：OBS 拉取失败/中断时，流程在数据集准备段终止、
解压与训练不得启动；核对数据集已上传与 obsutil 配置后重试。

## 3. 路径校验段（spec 5.2.1-7）

```bash
bash setup_notebook_env.sh check
```

校验清单：
- `/home/ma-user/work/dataset/citrus.yaml` 存在
- train/val/test 为 Notebook Linux 绝对路径（如 `/home/ma-user/work/dataset/images/train`），
  非占位符 `<DATASET_ROOT>`、非 Windows 路径（spec 5.2.3-2）
- `dataset_stats.txt` 无 `[0 样本]` 标记（spec 5.1.1-6）

## 4. 训练段（spec 5.2.1-4，指令 2.1）

```bash
cd /home/ma-user/work/yolov5
bash train_notebook.sh          # 30 epochs 先行验证流程
```

- 产出：`runs/train/pomelo_baseline_v1/weights/best.pt`
- 流程验证通过且评估达标后：`bash train_notebook.sh 100` 跑完整轮次

## 5. 评估段（spec 5.2.1-5，指令 2.2）

```bash
cd /home/ma-user/work/yolov5
bash val_notebook.sh
```

```bash
# 等价原始命令：
python val.py --weights runs/train/pomelo_baseline_v1/weights/best.pt \
  --data /home/ma-user/work/dataset/citrus.yaml --img 640
```

**达标线：mAP@0.5 ≥ 0.5（baseline 阶段）**
- 达标 → 进入权重保全；未达标 → 阻断导出与部署，补充数据重训（spec 5.2.3-1）。

## 6. 权重保全与用完即停（spec 5.2.1-1/6）

1. 评估确认达标后，**先下载 best.pt 至本地/OBS**：
   ```bash
   obsutil cp runs/train/pomelo_baseline_v1/weights/best.pt obs://pomelo-agent/yolov5/weights/best_pomelo_baseline_v1.pt
   ```
2. 再在华为云控制台**停止 Notebook 实例**（GPU 按需计费，用完即停）。

## 7. 禁止项

- 禁止在未评估或未达标的情况下交付任何权重文件（spec 5.2.1-8）。
- 禁止训练完成后让 Notebook 持续运行（按需计费费用，spec 5.2.3-3）。