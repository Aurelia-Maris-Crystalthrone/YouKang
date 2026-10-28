#!/usr/bin/env bash
# 训练启动脚本（ModelArts Notebook Terminal 直接 bash 执行，spec 5.2.1-4）
# 用法：
#   bash train_notebook.sh        # 默认 100 epochs
#   bash train_notebook.sh 30     # 先跑 30 epoch 验证流程，确认出 best.pt 再跑满 100
# 产出：runs/train/pomelo_v1/weights/best.pt
set -euo pipefail

EPOCHS="${1:-100}"
WORK_DIR=/home/ma-user/work
YOLOV5_DIR="$WORK_DIR/yolov5"
DATASET_DIR="$WORK_DIR/dataset"
DATASET_YAML="$DATASET_DIR/citrus.yaml"
OBS_PATH="obs://pomelo-agent/yolov5/pomelo_yolo.zip"
ZIP_FILE="$WORK_DIR/pomelo_yolo.zip"

# ---- 步骤 1：环境搭建 ----
echo "[1/5] 环境搭建：克隆 yolov5 + 安装依赖"
cd "$WORK_DIR"
if [ ! -d "$YOLOV5_DIR" ]; then
  git clone https://github.com/ultralytics/yolov5.git || { echo "[训练] git clone 失败，确认 Notebook 可访问外网"; exit 1; }
fi
cd "$YOLOV5_DIR"
pip install -r requirements.txt || { echo "[训练] pip install 失败，尝试配置 pip 镜像源后重试"; exit 1; }
echo "[1/5] 环境搭建完成"

# ---- 步骤 2：数据集拉取 ----
echo "[2/5] 从 OBS 拉取数据集 zip"
if [ ! -f "$DATASET_YAML" ]; then
  if [ ! -f "$ZIP_FILE" ]; then
    obsutil cp "$OBS_PATH" "$ZIP_FILE" || { echo "[训练] OBS 拉取失败，核对 obsutil 配置与数据集上传"; exit 1; }
  fi
  echo "[2/5] 数据集拉取完成"
else
  echo "[2/5] 数据集已存在，跳过拉取"
fi

# ---- 步骤 3：解压 ----
echo "[3/5] 解压数据集"
if [ ! -f "$DATASET_YAML" ]; then
  unzip -o "$ZIP_FILE" -d "$WORK_DIR" || { echo "[训练] 解压失败"; exit 1; }
  if [ -d "$WORK_DIR/pomelo_yolo" ] && [ ! -d "$DATASET_DIR" ]; then
    mv "$WORK_DIR/pomelo_yolo" "$DATASET_DIR"
  fi
fi
if [ ! -f "$DATASET_YAML" ]; then
  echo "[训练] 解压后未找到 $DATASET_YAML"; exit 1
fi
echo "[3/5] 解压完成"

# ---- 步骤 4：路径修正（sed 批量替换 Windows 路径为 Notebook 绝对路径）----
echo "[4/5] 修正 citrus.yaml 路径为 Notebook 绝对路径"
sed -i 's|E:/柚子病虫害AI识别/dataset/pomelo_yolo|/home/ma-user/work/dataset|g' "$DATASET_YAML"
sed -i 's|E:\\柚子病虫害AI识别\\dataset\\pomelo_yolo|/home/ma-user/work/dataset|g' "$DATASET_YAML"
sed -i 's|E:\\\\柚子病虫害AI识别\\\\dataset\\\\pomelo_yolo|/home/ma-user/work/dataset|g' "$DATASET_YAML"
if grep -q "E:" "$DATASET_YAML" || grep -q "柚子病虫害AI识别" "$DATASET_YAML"; then
  echo "[训练] citrus.yaml 路径修正后仍含 Windows 路径，请手动检查："
  cat "$DATASET_YAML"
  exit 1
fi
echo "[4/5] 路径修正完成，当前 citrus.yaml："
cat "$DATASET_YAML"

# ---- 步骤 5：训练 ----
echo "[5/5] 启动训练：epochs=$EPOCHS，img=640，batch=16"
python train.py --img 640 --batch 16 --epochs "$EPOCHS" \
  --data "$DATASET_YAML" \
  --weights yolov5s.pt \
  --name pomelo_v1 \
  --exist-ok || { echo "[训练] 训练失败，请检查上方日志"; exit 1; }

BEST_PT="runs/train/pomelo_v1/weights/best.pt"
if [ ! -f "$BEST_PT" ]; then
  echo "[训练] 未产出 $BEST_PT，请检查训练日志"; exit 1
fi
echo ""
echo "========================================"
echo "[训练] 完成：$BEST_PT"
echo "[训练] 下一步：bash val_notebook.sh 评估"
echo "========================================"