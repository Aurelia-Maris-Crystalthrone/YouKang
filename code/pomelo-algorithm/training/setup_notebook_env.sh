#!/usr/bin/env bash
# Notebook 环境准备四段式脚本（spec 5.2.1-2/3/7，design 接口 7）
# 在 ModelArts Notebook Terminal 于 /home/ma-user/work 下执行：
#   bash setup_notebook_env.sh          # 全部四段
#   bash setup_notebook_env.sh deps     # 仅段1：依赖搭建
#   bash setup_notebook_env.sh data     # 仅段2+3：OBS 拉取 + 解压
#   bash setup_notebook_env.sh check    # 仅段4：路径校验
set -uo pipefail

WORK=/home/ma-user/work
OBS_PATH="obs://pomelo-agent/yolov5/pomelo_yolo.zip"

step_deps() {
  echo "== 段1/4 依赖搭建：git clone yolov5 + pip install =="
  cd "$WORK" || { echo "[环境准备] 报错：$WORK 不存在"; return 1; }
  if [ ! -d "$WORK/yolov5" ]; then
    git clone https://github.com/ultralytics/yolov5.git \
      || { echo "[环境准备] git clone 失败（spec 5.2.3-5）"; \
           echo "[环境准备] 处理：确认 Notebook 可访问外网或配置 pip/git 镜像源后重试环境搭建段"; return 1; }
  fi
  cd "$WORK/yolov5" || return 1
  pip install -r requirements.txt \
    || { echo "[环境准备] pip install 失败（spec 5.2.3-5）"; \
         echo "[环境准备] 处理：确认外网可访问或配置 pip 镜像源后重试环境搭建段"; return 1; }
  echo "[环境准备] 段1 完成：$WORK/yolov5 存在，train.py/val.py 可执行"
}

step_data() {
  echo "== 段2/4 数据集拉取：obsutil cp $OBS_PATH =="
  cd "$WORK" || { echo "[环境准备] 报错：$WORK 不存在"; return 1; }
  obsutil cp "$OBS_PATH" ./ \
    || { echo "[环境准备] OBS 拉取失败/中断，流程在数据集准备段终止，解压与训练不得启动（spec 5.2.3-4）"; \
         echo "[环境准备] 处理：核对数据集已上传 OBS 与 obsutil 配置（ak/sk/endpoint）后重试"; return 1; }
  echo "== 段3/4 解压至 $WORK/dataset =="
  unzip -o pomelo_yolo.zip -d "$WORK/dataset" \
    || { echo "[环境准备] 解压失败，请检查 pomelo_yolo.zip 完整性后重试"; return 1; }
  echo "[环境准备] 段2/3 完成"
}

step_check() {
  echo "== 段4/4 路径校验：citrus.yaml 存在且为 Linux 绝对路径 =="
  local yaml="$WORK/dataset/citrus.yaml"
  if [ ! -f "$yaml" ]; then
    echo "[环境准备] 报错：$yaml 不存在（spec 5.2.1-3）"
    return 1
  fi
  # 占位符未修正或 Windows 路径 → 修正后重试（spec 5.2.3-2）
  if grep -q "<DATASET_ROOT>" "$yaml"; then
    echo "[环境准备] 报错：citrus.yaml 路径占位符未修正（spec 5.2.3-2）"
    echo "[环境准备] 处理：将 train/val/test 改为 $WORK/dataset/images/<split> 后重试"
    return 1
  fi
  if grep -E "^(train|val|test):" "$yaml" | grep -Eqi "^[a-z]+: *[A-Za-z]:\\\\"; then
    echo "[环境准备] 报错：citrus.yaml 为 Windows 路径（spec 5.2.3-2）"
    echo "[环境准备] 处理：修正为 $WORK/dataset 下 Linux 绝对路径后重试"
    return 1
  fi
  if [ -f "$WORK/dataset/dataset_stats.txt" ] && grep -q "\[0 样本\]" "$WORK/dataset/dataset_stats.txt"; then
    echo "[环境准备] 报错：统计报告存在 0 样本标记（spec 5.1.1-6），训练环节须拒绝启动"
    grep "\[0 样本\]" "$WORK/dataset/dataset_stats.txt"
    return 1
  fi
  echo "[环境准备] 段4 完成：环境就绪，允许进入训练段"
}

MODE="${1:-all}"
case "$MODE" in
  deps)  step_deps ;;
  data)  step_data ;;
  check) step_check ;;
  all)
    step_deps && step_data && step_check \
      && echo "[环境准备] 四段式全部完成，可进入训练段（bash train_notebook.sh）" \
      || exit 1
    ;;
  *) echo "用法: bash setup_notebook_env.sh [deps|data|check|all]"; exit 1 ;;
esac