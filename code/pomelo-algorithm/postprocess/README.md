# 端侧后处理参考实现交付与对拍说明

> 交付物：`yolo_postprocess.py`（自包含，仅依赖 numpy；cv2 仅 visualize 调试用）。
> 交付对象：工程同学，翻译为 OnDeviceDetector.ets 的 postprocess() 实现
>（ArkTS 或 C++ NAPI）。

## 1. 接口契约（spec 5.5.1、design 接口 4）

```python
postprocess(output, conf_threshold=0.45, iou_threshold=0.45,
            num_classes=4, original_size=None) -> dict
```

| 参数 | 说明 |
|------|------|
| output | YOLOv5 640×640 模型输出张量 **[1, 25200, 9]**（4 box + 1 obj + 4 类得分）；若原生导出为 [1, 9, 25200] 须先转置 |
| conf_threshold | 置信度阈值 0.45（score = obj × cls_max，过滤 < 阈值） |
| iou_threshold | 同类内 NMS IOU 阈值 0.45（纯 numpy，禁止 torchvision） |
| num_classes | 类别数（默认 4；类别数变化仅改此参数，维度校验联动 5+num_classes） |
| original_size | 原图 (宽, 高)；None 时输出 640×640 letterbox 坐标系 |

返回：`{"detections": [{"label": "...", "confidence": 0.87, "bbox": [x1,y1,x2,y2]}]}`，
label 与 labelmap.py 对齐（red_spider_mite/anthracnose/canker/healthy）。

辅助函数：
- `letterbox_params(src_w, src_h, dst=640) -> (r, left, top)`：与云端预处理同口径
- `box_iou(a, b) -> np.ndarray`：纯 numpy IOU
- `visualize(image_path, detections, out_path)`：OpenCV 画框（仅调试）

## 2. 翻译指引（工程 → OnDeviceDetector.ets）

1. 解码：对每 anchor 计算 `score = obj × max(cls)`，过滤 score < 0.45。
2. 坐标：xywh → xyxy（x1=x−w/2 等），再按 letterbox 参数还原原图坐标：
   `x_orig = (x_640 − left) / r`。
3. NMS：同类内按 score 降序贪心抑制（IOU > 0.45 抑制），保留最优框。
4. 输出：`{"detections":[...]}`；无候选时 detections 为空列表
  （对应端侧"未识别到病斑"表现，spec 5.5.3-2）。
5. 翻译完成后与参考实现**同输入同输出**（spec 5.5.1-7 验收条件）。

## 3. 端云对拍流程（spec 5.5.3-3）

同一测试图端云结果差异显著时，按三环节对拍定位：

| 环节 | 对拍点 |
|------|--------|
| 预处理 | letterbox 参数（r/left/top）是否一致：图片尺寸 → r, left, top 数值对比 |
| 解码 | 同一模型原始张量输入两侧，对比 score = obj×cls_max 与过滤结果数量 |
| NMS | 同一组候选框输入两侧 NMS，对比保留框数量与坐标 |

定位到差异环节后，按参考实现修正端侧翻译实现。

## 4. 依赖与移植约束

- NMS 纯 numpy 实现，**禁止依赖 torchvision**（spec 5.5.1-6），便于移植 ArkTS/C++。
- 端侧识别完全离线可用，不依赖网络状态（spec DFX 4.2-4）。
- 端侧单张端到端识别时间 ≤ 1 秒（中端真机 CPU/NPU，待联调确认，spec DFX 4.1-2）。