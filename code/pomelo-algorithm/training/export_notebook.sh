#!/usr/bin/env bash
# 模型导出脚本（ModelArts Notebook 内执行，design 接口：export_notebook.sh）
# 前置：环境准备与训练评估完成，best.pt 已达标（mAP@0.5 ≥ 0.5）
# 产出：runs/train/pomelo_baseline_v1/weights/best.onnx（输入 shape [1,3,640,640]）
set -uo pipefail

WORK=/home/ma-user/work
YOLov5_DIR="$WORK/yolov5"
BEST_PT="runs/train/pomelo_baseline_v1/weights/best.pt"

# 禁止交付未达标权重：导出前确认 best.pt 存在（达标记录按守则检查清单人工核对）
if [ ! -f "$BEST_PT" ]; then
  echo "[导出] 报错：未找到 $BEST_PT"
  echo "[导出] 请先完成训练与评估且 mAP@0.5 ≥ 0.5（未达标禁止导出与交付）"
  exit 1
fi

cd "$YOLov5_DIR" || { echo "[导出] 报错：$YOLov5_DIR 不存在，请先运行 setup_notebook_env.sh"; exit 1; }

# YOLOv5 export.py：--include onnx --img 640 --batch 1（spec 5.3.1-1）
python export.py --weights "$BEST_PT" --include onnx --img 640 --batch 1

ONNX_PATH="runs/train/pomelo_baseline_v1/weights/best.onnx"
if [ ! -f "$ONNX_PATH" ]; then
  echo "[导出] 报错：未生成 $ONNX_PATH，请检查导出日志"
  exit 1
fi

# 输入 shape 校验：优先用 onnx 库（Notebook 依赖已装）；失败则提示人工 netron.app 校验
python - "$ONNX_PATH" <<'PYEOF'
import sys
try:
    import onnx
except ImportError:
    print("[导出] 提示：onnx 库不可用，请用 netron.app 人工确认输入 shape 为 [1,3,640,640]")
    sys.exit(0)
model = onnx.load(sys.argv[1])
shape = [d.dim_value for d in model.graph.input[0].type.tensor_type.shape.dim]
if shape != [1, 3, 640, 640]:
    print(f"[导出] 报错：输入 shape {shape} != [1,3,640,640]，请以 --batch 1 --img 640 重新导出")
    sys.exit(1)
print(f"[导出] 输入 shape 校验通过: {shape}")
PYEOF
if [ $? -ne 0 ]; then
  exit 1
fi

echo "[导出] 完成：$ONNX_PATH"
echo "[导出] 输入节点名一般为 images（netron.app 复核可选）；后续按 export/README_convert.md 执行 converter_lite 转换（本地环境）"