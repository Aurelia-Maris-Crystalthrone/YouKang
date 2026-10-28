#!/usr/bin/env bash
# 打包 ModelArts 在线服务部署包（自包含）
# 用法：bash package_model.sh [best_torchscript_path]
#   默认路径：/home/ma-user/work/yolov5/runs/train/pomelo_v1/weights/best.torchscript
# 产出：model.zip（config.json + customize_service.py + labelmap.py + best.torchscript）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
MODEL_DIR="$PROJECT_DIR/model"
TS_PATH="${1:-/home/ma-user/work/yolov5/runs/train/pomelo_v1/weights/best.torchscript}"
OUTPUT_DIR="$PROJECT_DIR/model_package"
ZIP_PATH="$OUTPUT_DIR/model.zip"

# ---- 前置校验 ----
echo "[打包] 校验文件"
if [ ! -f "$TS_PATH" ]; then
  echo "[打包] 未找到 best.torchscript：$TS_PATH"
  echo "[打包] 请先运行 export_notebook.sh 导出 TorchScript"
  exit 1
fi
for f in config.json customize_service.py labelmap.py; do
  if [ ! -f "$MODEL_DIR/$f" ]; then
    echo "[打包] 未找到 $MODEL_DIR/$f"; exit 1
  fi
done
echo "[打包] 校验通过"

# ---- 准备打包目录 ----
echo "[打包] 准备部署包目录"
rm -rf "$OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR"
cp "$MODEL_DIR/config.json"        "$OUTPUT_DIR/"
cp "$MODEL_DIR/customize_service.py" "$OUTPUT_DIR/"
cp "$MODEL_DIR/labelmap.py"        "$OUTPUT_DIR/"
cp "$TS_PATH"                      "$OUTPUT_DIR/best.torchscript"

# ---- 打包 ----
echo "[打包] 生成 model.zip"
cd "$OUTPUT_DIR"
zip -r model.zip config.json customize_service.py labelmap.py best.torchscript
if [ ! -f "$ZIP_PATH" ]; then
  echo "[打包] zip 打包失败"; exit 1
fi

echo ""
echo "========================================"
echo "[打包] 完成：$ZIP_PATH"
echo ""
echo "部署步骤："
echo "  1. 上传 OBS：obsutil cp $ZIP_PATH obs://pomelo-agent/model/model.zip"
echo "  2. ModelArts → AI 应用 → 导入 → 选择 OBS 路径 obs://pomelo-agent/model/model.zip"
echo "  3. 部署为在线服务 → 等待状态变为 Running"
echo "  4. 交付 API 地址与 Token（Token 线下交付，禁止硬编码于仓库）"
echo ""
echo "验证：在 ModelArts 在线服务页「预测」上传测试图，确认返回 JSON 的"
echo "  detections[].label 与实际病害一致，且带有 top2 字段与 is_healthy 字段"
echo "========================================"