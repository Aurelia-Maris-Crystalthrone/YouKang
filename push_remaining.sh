#!/bin/bash
# 推送剩余数据（Aug val/test + Roboflow 源），拆小批次规避 curl 55 断连
cd "E:/柚子病虫害AI识别" || exit 1
exec > push_remaining.log 2>&1

step() {
  local msg="$1"; shift
  echo "=== [$(date +%H:%M:%S)] add: $*"
  git add -- "$@" || { echo "ADD_FAIL"; return 1; }
  git -c user.name="pomelo-team" -c user.email="team@example.com" commit -q -m "$msg" || { echo "COMMIT_FAIL"; return 1; }
  for try in 1 2 3; do
    echo "=== [$(date +%H:%M:%S)] push try$try: $msg"
    git push origin main >> push.log 2>&1
    local code=$?
    echo "=== [$(date +%H:%M:%S)] push exit=$code try$try"
    [ $code -eq 0 ] && return 0
    tail -5 push.log
    sleep 10
  done
  return 1
}

step "data: CLP-14-Aug 增强集 val/test" \
  archive/CitrusLeafPathology-14-Aug/CitrusLeafPathology-14-Aug/val \
  archive/CitrusLeafPathology-14-Aug/CitrusLeafPathology-14-Aug/test \
  archive/CLP-14-Aug_metadata.csv
step "data: Roboflow 柑橘叶病检测集（原始标注）" citrus-leaf-disease-2.v1-test1.yolov5pytorch
step "chore: 忽略 CodeArts 本地索引 .arts；同步后处理测试断言" .gitignore code/pomelo-algorithm/tests/test_yolo_postprocess.py
echo "=== [$(date +%H:%M:%S)] ALL_DONE"
