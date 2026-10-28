#!/usr/bin/env bash
# 评估脚本（ModelArts Notebook 内执行，spec 5.2.1-5，design 接口 9）
# 用法（在 yolov5 目录内）：bash val_notebook.sh
# 达标线：mAP@0.5 ≥ 0.5（baseline 阶段）；未达标阻断导出与部署并补充数据重训
set -uo pipefail

BEST_PT="runs/train/pomelo_baseline_v1/weights/best.pt"
DATASET_YAML=/home/ma-user/work/dataset/citrus.yaml

if [ ! -f "$BEST_PT" ]; then
  echo "[评估] 报错：未找到 $BEST_PT，请先完成训练（bash train_notebook.sh）"
  exit 1
fi
if [ ! -f "$DATASET_YAML" ]; then
  echo "[评估] 报错：$DATASET_YAML 不存在，请先运行 setup_notebook_env.sh"
  exit 1
fi

# 封装 YOLOv5 官方 val.py（固定 baseline 参数，spec 5.2.1-5）
python val.py --weights "$BEST_PT" \
  --data "$DATASET_YAML" --img 640

echo "[评估] 请在上方输出中核对 mAP@0.5："
echo "  - mAP@0.5 ≥ 0.5 → 达标：先下载 best.pt 至本地/OBS，再停止 Notebook；可进入导出阶段"
echo "  - mAP@0.5 < 0.5 → 未达标：阻断导出与部署，补充数据重训（spec 5.2.3-1），禁止交付"