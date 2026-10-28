#!/usr/bin/env bash
# 模型导出脚本（ModelArts Notebook Terminal 直接 bash 执行）
# 前置：训练评估完成，best.pt 已达标（mAP@0.5 ≥ 0.5）
# 产出：
#   runs/train/pomelo_v1/weights/best.torchscript — 部署 ModelArts 在线服务
#   runs/train/pomelo_v1/weights/best.onnx        — 端侧 converter_lite 转 .ms
set -euo pipefail

WORK_DIR=/home/ma-user/work
YOLOV5_DIR="$WORK_DIR/yolov5"
WEIGHTS_DIR="runs/train/pomelo_v1/weights"
BEST_PT="$WEIGHTS_DIR/best.pt"
TS_PATH="$WEIGHTS_DIR/best.torchscript"
ONNX_PATH="$WEIGHTS_DIR/best.onnx"

cd "$YOLOV5_DIR"

if [ ! -f "$BEST_PT" ]; then
  echo "[导出] 未找到 $BEST_PT"
  echo "[导出] 请先完成训练与评估且 mAP@0.5 ≥ 0.5（未达标禁止导出与交付）"
  exit 1
fi

# ---- 步骤 1：导出 TorchScript + ONNX ----
echo "[1/3] 导出 TorchScript + ONNX"
echo "  --batch 1 必须带，否则 converter_lite 转 .ms 会失败"
python export.py --weights "$BEST_PT" \
  --include torchscript onnx --img 640 --batch 1 \
  --simplify || { echo "[导出] export.py 失败"; exit 1; }
echo "[1/3] 导出完成"

# ---- 步骤 2：校验产出文件 ----
echo "[2/3] 校验产出文件"
if [ ! -f "$TS_PATH" ]; then
  echo "[导出] 未生成 $TS_PATH"; exit 1
fi
if [ ! -f "$ONNX_PATH" ]; then
  echo "[导出] 未生成 $ONNX_PATH"; exit 1
fi
echo "  TorchScript: $TS_PATH"
echo "  ONNX:        $ONNX_PATH"
echo "[2/3] 校验完成"

# ---- 步骤 3：校验 ONNX 输入 shape ----
echo "[3/3] 校验 ONNX 输入 shape（须为 NCHW [1,3,640,640]）"
python - "$ONNX_PATH" <<'PYEOF'
import sys
try:
    import onnx
except ImportError:
    print("[导出] onnx 库不可用，请用 netron.app 人工确认输入 shape 为 [1,3,640,640]")
    sys.exit(0)
model = onnx.load(sys.argv[1])
shape = [d.dim_value for d in model.graph.input[0].type.tensor_type.shape.dim]
if shape != [1, 3, 640, 640]:
    print(f"[导出] 输入 shape {shape} != [1,3,640,640]，请以 --batch 1 --img 640 重新导出")
    sys.exit(1)
print(f"[导出] 输入 shape 校验通过: {shape}")
PYEOF
if [ $? -ne 0 ]; then
  exit 1
fi
echo "[3/3] 校验完成"

echo ""
echo "========================================"
echo "[导出] 全部完成："
echo "  $TS_PATH  → 部署 ModelArts 在线服务"
echo "  $ONNX_PATH → 端侧 converter_lite 转 .ms"
echo ""
echo "下一步："
echo "  1. 部署云端服务：bash package_model.sh"
echo "  2. 端侧转换（本地 converter_lite 环境）："
echo "     converter_lite --fmk=ONNX --modelFile=best.onnx \\"
echo "       --outputFile=yolov5s_pomelo --inputShape=\"images:1,3,640,640\""
echo "     注意：inputShape 必须是 NCHW（1,3,640,640），端侧已同口径，勿改 NHWC"
echo "========================================"