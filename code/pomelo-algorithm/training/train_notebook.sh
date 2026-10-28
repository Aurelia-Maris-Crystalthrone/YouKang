#!/usr/bin/env bash
# 训练启动脚本（ModelArts Notebook 内执行，spec 5.2.1-4，design 接口 8）
# 用法（在 yolov5 目录内）：
#   bash train_notebook.sh        # 默认 30 epochs 先行验证流程
#   bash train_notebook.sh 100    # 评估达标后再跑 100 epochs
# 产出：runs/train/pomelo_baseline_v1/weights/best.pt
set -uo pipefail

EPOCHS="${1:-30}"
DATASET_YAML=/home/ma-user/work/dataset/citrus.yaml

# 训练前校验（spec 5.2.1-7、5.1.1-6、5.2.3-2）：校验失败拒绝启动训练
if [ ! -f "$DATASET_YAML" ]; then
  echo "[训练] 报错：$DATASET_YAML 不存在，请先运行 setup_notebook_env.sh"
  exit 1
fi
if grep -q "<DATASET_ROOT>" "$DATASET_YAML"; then
  echo "[训练] 报错：citrus.yaml 路径占位符未修正（spec 5.2.3-2）"
  echo "[训练] 处理：将 train/val/test 修正为 /home/ma-user/work/dataset/images/<split> 后重试"
  exit 1
fi
if grep -E "^(train|val|test):" "$DATASET_YAML" | grep -Eqi "^[a-z]+: *[A-Za-z]:\\\\"; then
  echo "[训练] 报错：citrus.yaml 为 Windows 路径（spec 5.2.3-2），修正为 Notebook Linux 绝对路径后重试"
  exit 1
fi
if [ -f /home/ma-user/work/dataset/dataset_stats.txt ] \
   && grep -q "\[0 样本\]" /home/ma-user/work/dataset/dataset_stats.txt; then
  echo "[训练] 报错：统计报告存在 0 样本标记（spec 5.1.1-6），拒绝启动训练"
  grep "\[0 样本\]" /home/ma-user/work/dataset/dataset_stats.txt
  exit 1
fi

if [ "$EPOCHS" != "30" ] && [ "$EPOCHS" != "100" ]; then
  echo "[训练] 提示：baseline 流程为先 30 epochs 验证，评估达标后再跑 100 epochs（spec 5.2.1-4）"
fi

# 封装 YOLOv5 官方 train.py（固定 baseline 参数，spec 5.2.1-4）
python train.py --img 640 --batch 16 --epochs "$EPOCHS" \
  --data "$DATASET_YAML" \
  --weights yolov5s.pt --name pomelo_baseline_v1

if [ ! -f "runs/train/pomelo_baseline_v1/weights/best.pt" ]; then
  echo "[训练] 报错：未产出 runs/train/pomelo_baseline_v1/weights/best.pt，请检查训练日志"
  exit 1
fi
echo "[训练] 完成：runs/train/pomelo_baseline_v1/weights/best.pt"
echo "[训练] 下一步：bash val_notebook.sh 评估（达标线 mAP@0.5 ≥ 0.5）；达标后先下载 best.pt 再停止 Notebook"