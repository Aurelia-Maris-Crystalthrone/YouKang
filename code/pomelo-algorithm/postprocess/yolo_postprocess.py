"""端侧推理后处理参考实现（spec 5.5，design 接口 4）。

自包含交付：仅依赖 numpy（NMS 纯 numpy 实现，禁止 torchvision，spec 5.5.1-6），
cv2 仅 visualize 调试用（函数内延迟导入）。

输入：YOLOv5 640×640 模型输出张量 [1, 25200, 5 + n]
（4 box + 1 obj + n 类得分；n 由 labelmap.CLASS_NAMES 决定，当前为 4 类）。
类别名、置信度阈值、IOU 阈值统一引用 labelmap.py（端云同口径，禁止各自硬编码）。

交付对象：工程翻译为 OnDeviceDetector.ets 的 postprocess()（ArkTS/C++ NAPI），
翻译后与参考实现"同输入同输出"（spec 5.5.1-7）。

注意：YOLOv5 原生导出若为 channels-first 布局 [1, 5+n, 25200]，须先转置为
[1, 25200, 5+n] 再调用本实现。

健康判定：本体系 healthy 为负样本（空标注），不占类别编号。
推理返回空 detections 时，业务层应输出 HEALTHY_LABEL（"healthy"）。
"""
import numpy as np

from labelmap import CLASS_NAMES, CONF_THRESHOLD, IOU_THRESHOLD

INPUT_SIZE: int = 640


def letterbox_params(src_w: int, src_h: int, dst: int = 640) -> tuple:
    """计算 letterbox 缩放比与填充量 (r, left_pad, top_pad)，与云端预处理同口径。"""
    r = min(dst / src_h, dst / src_w)
    new_w, new_h = round(src_w * r), round(src_h * r)
    left = int(round((dst - new_w) / 2.0))
    top = int(round((dst - new_h) / 2.0))
    return r, left, top


def box_iou(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """纯 numpy IOU 矩阵：a (n,4) xyxy，b (m,4) xyxy → (n,m)。"""
    a = np.asarray(a, dtype=np.float64).reshape(-1, 4)
    b = np.asarray(b, dtype=np.float64).reshape(-1, 4)
    lt = np.maximum(a[:, None, :2], b[None, :, :2])
    rb = np.minimum(a[:, None, 2:], b[None, :, 2:])
    wh = np.clip(rb - lt, 0.0, None)
    inter = wh[..., 0] * wh[..., 1]
    area_a = np.clip(a[:, 2] - a[:, 0], 0.0, None) * np.clip(a[:, 3] - a[:, 1], 0.0, None)
    area_b = np.clip(b[:, 2] - b[:, 0], 0.0, None) * np.clip(b[:, 3] - b[:, 1], 0.0, None)
    union = area_a[:, None] + area_b[None, :] - inter
    return np.where(union > 0, inter / union, 0.0)


def _class_nms(boxes: np.ndarray, scores: np.ndarray, class_ids: np.ndarray,
               iou_threshold: float) -> list:
    """同类内贪心 NMS（纯 numpy），返回保留索引列表。"""
    keep = []
    for c in np.unique(class_ids):
        idx = np.where(class_ids == c)[0]
        order = idx[np.argsort(-scores[idx])]
        suppressed = np.zeros(len(order), dtype=bool)
        for i_pos in range(len(order)):
            if suppressed[i_pos]:
                continue
            keep.append(int(order[i_pos]))
            if i_pos + 1 < len(order):
                ious = box_iou(boxes[order[i_pos]].reshape(1, 4),
                               boxes[order[i_pos + 1:]])[0]
                suppressed[i_pos + 1:] |= ious > iou_threshold
    return keep


def postprocess(output, conf_threshold: float = CONF_THRESHOLD,
                iou_threshold: float = IOU_THRESHOLD,
                num_classes: int = len(CLASS_NAMES), original_size=None) -> dict:
    """YOLOv5 输出张量 → 检测框列表。

    :param output: 张量 [1, 25200, 5+num_classes]（4 box + 1 obj + N 类得分）
    :param conf_threshold: 置信度阈值（score = obj × cls_max，过滤 < 阈值候选框）
    :param iou_threshold: 同类内 NMS IOU 阈值
    :param num_classes: 类别数（默认 4 类体系；变化仅改此参数，算法逻辑不变）
    :param original_size: 原图 (宽, 高)；None 时输出 640×640 letterbox 坐标系
    :return: {"detections": [{"label", "confidence", "bbox": [x1,y1,x2,y2]}]}
    :raises ValueError: 维度不符（维度校验随 num_classes 联动）或阈值越界
    """
    if not (0.0 < conf_threshold < 1.0) or not (0.0 < iou_threshold < 1.0):
        raise ValueError(f"阈值取值须在 (0,1)：conf={conf_threshold}, iou={iou_threshold}")
    arr = np.asarray(output)
    expected = (1, 25200, 5 + num_classes)
    if arr.ndim != 3 or arr.shape != expected:
        raise ValueError(
            f"维度错误：期望张量 {expected}（4 box + 1 obj + {num_classes} 类得分），"
            f"实际 shape={arr.shape}；请检查模型版本与输出格式（spec 5.5.3-1）")

    pred = arr[0]
    obj = pred[:, 4]
    cls_scores = pred[:, 5:]
    cls_idx = cls_scores.argmax(axis=1)
    scores = obj * cls_scores.max(axis=1)
    mask = scores >= conf_threshold
    if not mask.any():
        return {"detections": []}

    boxes_xywh = pred[mask][:, :4].astype(np.float64)
    scores_m = scores[mask].astype(np.float64)
    cls_m = cls_idx[mask]
    xy, wh = boxes_xywh[:, :2], boxes_xywh[:, 2:]
    xyxy = np.concatenate([xy - wh / 2.0, xy + wh / 2.0], axis=1) * INPUT_SIZE

    if original_size is not None:
        src_w, src_h = int(original_size[0]), int(original_size[1])
        r, left, top = letterbox_params(src_w, src_h)
        xyxy = np.stack([
            (xyxy[:, 0] - left) / r, (xyxy[:, 1] - top) / r,
            (xyxy[:, 2] - left) / r, (xyxy[:, 3] - top) / r,
        ], axis=1)

    keep = _class_nms(xyxy, scores_m, cls_m, iou_threshold)
    detections = []
    for i in keep:
        x1, y1, x2, y2 = xyxy[i]
        cid = int(cls_m[i])
        label = CLASS_NAMES[cid] if cid < len(CLASS_NAMES) else str(cid)
        detections.append({
            "label": label,
            "confidence": round(float(scores_m[i]), 4),
            "bbox": [round(float(min(x1, x2)), 1), round(float(min(y1, y2)), 1),
                     round(float(max(x1, x2)), 1), round(float(max(y1, y2)), 1)],
        })
    return {"detections": detections}


def visualize(image_path: str, detections: dict, out_path: str) -> None:
    """OpenCV 画框保存可视化图（仅调试用途，非端侧翻译范围）。"""
    import cv2
    img = cv2.imread(image_path)
    if img is None:
        raise FileNotFoundError(f"图片无法读取: {image_path}")
    for det in detections.get("detections", []):
        x1, y1, x2, y2 = [int(v) for v in det["bbox"]]
        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 200, 0), 2)
        cv2.putText(img, f"{det['label']} {det['confidence']:.2f}",
                    (x1, max(y1 - 4, 12)), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (0, 200, 0), 1)
    cv2.imwrite(out_path, img)