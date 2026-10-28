#!/usr/bin/env bash
# 评估脚本（ModelArts Notebook Terminal 直接 bash 执行，spec 5.2.1-5）
# 用法：bash val_notebook.sh
# 产出：
#   runs/val/pomelo_v1/          — YOLOv5 val.py 原始输出（mAP、PR 曲线、混淆矩阵）
#   runs/val/pomelo_v1/per_class_metrics.csv — 分类别 P/R/F1/mAP
#   runs/val/pomelo_v1/confusion_matrix.png  — 混淆矩阵（val.py 自动生成）
#   runs/val/pomelo_v1/negative_sample_report.txt — 负样本误报率
set -euo pipefail

WORK_DIR=/home/ma-user/work
YOLOV5_DIR="$WORK_DIR/yolov5"
DATASET_DIR="$WORK_DIR/dataset"
DATASET_YAML="$DATASET_DIR/citrus.yaml"
VAL_NAME=pomelo_v1
VAL_DIR="runs/val/$VAL_NAME"
BEST_PT="runs/train/$VAL_NAME/weights/best.pt"
VAL_LOG="/tmp/val_output.txt"

cd "$YOLOV5_DIR"

# 前置校验
if [ ! -f "$BEST_PT" ]; then
  echo "[评估] 未找到 $BEST_PT，请先完成训练（bash train_notebook.sh）"; exit 1
fi
if [ ! -f "$DATASET_YAML" ]; then
  echo "[评估] $DATASET_YAML 不存在，请先运行 train_notebook.sh"; exit 1
fi

# ---- 步骤 1：val.py 评估 mAP@0.5 与 mAP@0.5:0.95 ----
echo "[1/4] 运行 val.py 评估 mAP@0.5 与 mAP@0.5:0.95"
python val.py --weights "$BEST_PT" \
  --data "$DATASET_YAML" --img 640 \
  --name "$VAL_NAME" --exist-ok --verbose 2>&1 | tee "$VAL_LOG"
if [ ${PIPESTATUS[0]} -ne 0 ]; then
  echo "[评估] val.py 失败"; exit 1
fi
echo "[1/4] val.py 完成"

# ---- 步骤 2：分类别 per_class_metrics.csv ----
echo "[2/4] 生成分类别 per_class_metrics.csv"
python - "$VAL_LOG" "$VAL_DIR" <<'PYEOF'
import csv
import re
import sys
from pathlib import Path

val_log_path = Path(sys.argv[1])
val_dir = Path(sys.argv[2])
val_dir.mkdir(parents=True, exist_ok=True)

lines = val_log_path.read_text(encoding="utf-8", errors="replace").splitlines()

# 解析 YOLOv5 val.py 输出表格
# 格式：Class  Images  Instances  P  R  mAP50  mAP50-95
pattern = re.compile(
    r"^\s*(\S+)\s+(\d+)\s+(\d+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)"
)
rows = []
for line in lines:
    m = pattern.match(line)
    if m:
        cls = m.group(1)
        if cls == "all":
            continue
        p = float(m.group(4))
        r = float(m.group(5))
        map50 = float(m.group(6))
        map5095 = float(m.group(7))
        f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0.0
        rows.append({
            "class": cls,
            "precision": round(p, 4),
            "recall": round(r, 4),
            "f1": round(f1, 4),
            "mAP50": round(map50, 4),
            "mAP50-95": round(map5095, 4),
        })

csv_path = val_dir / "per_class_metrics.csv"
with open(csv_path, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=["class", "precision", "recall", "f1", "mAP50", "mAP50-95"])
    writer.writeheader()
    writer.writerows(rows)

print(f"per_class_metrics.csv 已生成：{csv_path}（{len(rows)} 类）")
for row in rows:
    print(f"  {row['class']:20s}  P={row['precision']:.3f}  R={row['recall']:.3f}  F1={row['f1']:.3f}  mAP50={row['mAP50']:.3f}  mAP50-95={row['mAP50-95']:.3f}")
PYEOF
echo "[2/4] per_class_metrics.csv 生成完成"

# ---- 步骤 3：混淆矩阵 ----
echo "[3/4] 混淆矩阵"
if [ -f "$VAL_DIR/confusion_matrix.png" ]; then
  echo "  混淆矩阵已生成：$VAL_DIR/confusion_matrix.png"
else
  echo "[评估] 警告：未找到 confusion_matrix.png，请检查 val.py 版本"
fi
echo "[3/4] 混淆矩阵完成"

# ---- 步骤 4：负样本专项评估 ----
echo "[4/4] 负样本专项评估（拒识能力量化指标）"
python - "$BEST_PT" "$DATASET_DIR" "$VAL_DIR" <<'PYEOF'
import sys
from pathlib import Path

import torch

best_pt = sys.argv[1]
dataset_dir = Path(sys.argv[2])
val_dir = Path(sys.argv[3])

labels_dir = dataset_dir / "labels" / "test"
images_dir = dataset_dir / "images" / "test"

if not labels_dir.exists():
    print(f"负样本评估跳过：未找到 {labels_dir}")
    sys.exit(0)

# 找到空标注文件（负样本）
negative_images = []
for txt in sorted(labels_dir.glob("*.txt")):
    if txt.stat().st_size == 0:
        stem = txt.stem
        for ext in (".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG", ".bmp", ".BMP"):
            img = images_dir / (stem + ext)
            if img.exists():
                negative_images.append(str(img))
                break

if not negative_images:
    print("负样本评估跳过：未找到空标注文件（负样本）")
    sys.exit(0)

print(f"负样本数量：{len(negative_images)} 张")

# 加载模型（local source，无需网络）
model = torch.hub.load(
    "/home/ma-user/work/yolov5", "custom",
    path=best_pt, source="local",
)

# 推理负样本
results = model(negative_images, conf=0.25, iou=0.45)

false_positive = 0
false_positive_details = []
for i, result in enumerate(results):
    n_detections = len(result)
    if n_detections > 0:
        false_positive += 1
        labels = result.names
        cls_ids = result.xyxy[0][:, -1].int().tolist() if len(result) > 0 else []
        detected_labels = [labels.get(c, str(c)) for c in cls_ids]
        false_positive_details.append((negative_images[i], n_detections, detected_labels))

total = len(negative_images)
fpr = false_positive / total if total > 0 else 0.0

# 输出报告
report_path = val_dir / "negative_sample_report.txt"
with open(report_path, "w", encoding="utf-8") as f:
    f.write(f"负样本专项评估报告\n")
    f.write(f"=" * 50 + "\n")
    f.write(f"负样本总数：{total} 张\n")
    f.write(f"误报为病害：{false_positive} 张\n")
    f.write(f"误报率（FPR）：{fpr:.2%}\n")
    f.write(f"拒识准确率：{(1 - fpr):.2%}\n")
    f.write(f"=" * 50 + "\n")
    f.write(f"\n误报明细（前 20 条）：\n")
    for img_path, n, labels in false_positive_details[:20]:
        f.write(f"  {Path(img_path).name}: 检测到 {n} 个目标 {labels}\n")
    if len(false_positive_details) > 20:
        f.write(f"  ... 共 {len(false_positive_details)} 条\n")

print(f"负样本误报率：{false_positive}/{total} = {fpr:.2%}")
print(f"拒识准确率：{(1 - fpr):.2%}")
print(f"报告已保存：{report_path}")
PYEOF
echo "[4/4] 负样本专项评估完成"

echo ""
echo "========================================"
echo "[评估] 全部完成，产出文件："
echo "  $VAL_DIR/per_class_metrics.csv      — 分类别 P/R/F1/mAP"
echo "  $VAL_DIR/confusion_matrix.png       — 混淆矩阵"
echo "  $VAL_DIR/negative_sample_report.txt — 负样本误报率"
echo ""
echo "  达标线：mAP@0.5 ≥ 0.5"
echo "  - 达标 → 先下载 best.pt 至本地/OBS，再停止 Notebook；可进入导出阶段"
echo "  - 未达标 → 补充数据重训，禁止交付未达标权重"
echo "========================================"