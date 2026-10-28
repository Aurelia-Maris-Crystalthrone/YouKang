"""ModelArts 在线病虫害识别服务（spec 5.4，design 模块 D / 接口 3）。

继承 ModelArts BaseService，三段式：
- _preprocess：multipart 图片接收 + letterbox 缩放至 640×640（保持长宽比、
  灰边填充、记录缩放参数）；图片缺失/无法解码返回 INPUT_INVALID。
- _inference：YOLOv5 前向推理（raw 输出 [1,25200,9]，spec 6.4-1）。
- _postprocess：置信度过滤（> 0.45）+ 同类内 NMS（IOU 0.45）+
  xywh→xyxy + 按 letterbox 参数还原原图像素坐标 + labelmap 映射；
  返回 {"detections":[{"label","confidence","bbox":[x1,y1,x2,y2]}]}。

部署包自包含：本文件与 labelmap.py（打包副本）同目录，权重文件位于包根
（model_path 由 config.json 声明）。

健康判定：healthy 在本体系中为负样本（空标注），不占类别编号。
后处理无检测框时返回 {"detections": [], "is_healthy": true}，
由智能体业务层映射为"健康"结论。
"""
import math

import cv2
import numpy as np
import torch
from model_service.pytorch_service import BaseService

from labelmap import CLASS_NAMES, CONF_THRESHOLD, IOU_THRESHOLD

INPUT_SIZE: int = 640


def _letterbox(img: np.ndarray, dst: int = INPUT_SIZE) -> tuple:
    """保持长宽比、灰边(114)填充缩放至 dst×dst；返回 (img, r, left_pad, top_pad)。"""
    h, w = img.shape[:2]
    r = min(dst / h, dst / w)
    new_w, new_h = round(w * r), round(h * r)
    left = int(round((dst - new_w) / 2.0))
    top = int(round((dst - new_h) / 2.0))
    resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    right, bottom = dst - new_w - left, dst - new_h - top
    out = cv2.copyMakeBorder(resized, top, bottom, left, right,
                             cv2.BORDER_CONSTANT, value=(114, 114, 114))
    return out, r, left, top


def _iou_one(box: np.ndarray, others: np.ndarray) -> np.ndarray:
    lt = np.maximum(box[:2], others[:, :2])
    rb = np.minimum(box[2:], others[:, 2:])
    wh = np.clip(rb - lt, 0, None)
    inter = wh[:, 0] * wh[:, 1]
    area = np.clip(others[:, 2] - others[:, 0], 0, None) * np.clip(others[:, 3] - others[:, 1], 0, None)
    union = np.clip(box[2] - box[0], 0, None) * np.clip(box[3] - box[1], 0, None) + area - inter
    return np.where(union > 0, inter / union, 0.0)


def _class_nms(boxes: np.ndarray, scores: np.ndarray, class_ids: np.ndarray,
               iou_threshold: float) -> list:
    """同类内贪心 NMS（纯 numpy，端云同口径），返回保留索引。"""
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
                ious = _iou_one(boxes[order[i_pos]].astype(np.float64),
                                boxes[order[i_pos + 1:]].astype(np.float64))
                suppressed[i_pos + 1:] |= ious > iou_threshold
    return keep


class PomeloDetectService(BaseService):
    """在线病虫害识别服务（云端智能体"视觉识别"能力的数据源）。"""

    def __init__(self, model_name, model_path):
        super().__init__(model_name, model_path)
        self.model = None

    def _load_model(self) -> None:
        """加载权重：优先 TorchScript，回退 torch.load。

        背景：best.pt 中 ckpt["model"] 是完整 nn.Module，反序列化依赖训练环境的
        ultralytics 类定义；而 ModelArts runtime 为 python3.7 / torch1.8，
        与本地训练环境不一致时极易失败。TorchScript 自包含、无此问题。
        部署前建议：python export.py --weights best.pt --include torchscript
        """
        path = str(self.model_path)
        if path.endswith((".ts", ".torchscript", ".ptjit")):
            self.model = torch.jit.load(path, map_location="cpu").float().eval()
            return

        try:
            ckpt = torch.load(path, map_location="cpu")
        except Exception as exc:
            raise RuntimeError(
                f"权重加载失败：{exc}。多为训练/部署环境 torch 或 ultralytics 版本不一致"
                f"导致 nn.Module 反序列化失败；请改用 TorchScript 导出后重新部署。") from exc
        model = ckpt["model"] if isinstance(ckpt, dict) and "model" in ckpt else ckpt
        self.model = model.float().eval()

    def _preprocess(self, data):
        try:
            file_value = data.get("images") if isinstance(data, dict) else None
            if file_value is None:
                return {"error_code": "INPUT_INVALID", "message": "缺少 images 图片字段"}
            content = file_value.read() if hasattr(file_value, "read") else file_value
            img = cv2.imdecode(np.frombuffer(content, dtype=np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                return {"error_code": "INPUT_INVALID", "message": "图片无法解码"}
            lb, r, left, top = _letterbox(img)
            rgb = cv2.cvtColor(lb, cv2.COLOR_BGR2RGB)
            tensor = torch.from_numpy(rgb).permute(2, 0, 1).unsqueeze(0).float() / 255.0
            return {"tensor": tensor, "r": r, "left": left, "top": top}
        except Exception as exc:
            return {"error_code": "INPUT_INVALID", "message": f"预处理失败: {exc}"}

    def _inference(self, data):
        if "error_code" in data:
            return data
        try:
            if self.model is None:
                self._load_model()
            with torch.no_grad():
                pred = self.model(data["tensor"])
            if isinstance(pred, (list, tuple)):
                pred = pred[0]
            if pred.dim() == 3 and pred.shape[1] == 9 and pred.shape[2] == 25200:
                pred = pred.transpose(1, 2)
            return {"pred": pred, "r": data["r"], "left": data["left"], "top": data["top"]}
        except Exception as exc:
            return {"error_code": "INTERNAL_ERROR", "message": f"推理失败: {exc}"}

    def _postprocess(self, data):
        if "error_code" in data:
            return {"error_code": data["error_code"], "message": data["message"]}
        try:
            pred = data["pred"].detach().cpu().numpy()
            pred = pred[0] if pred.ndim == 3 else pred
            obj = pred[:, 4]
            cls_scores = pred[:, 5:]
            if cls_scores.shape[1] != len(CLASS_NAMES):
                return {"error_code": "MODEL_MISMATCH",
                        "message": f"模型类别数 {cls_scores.shape[1]} 与 labelmap "
                                   f"{len(CLASS_NAMES)} 不一致，请核对权重版本"}
            cls_idx = cls_scores.argmax(axis=1)
            scores = obj * cls_scores.max(axis=1)
            mask = scores > CONF_THRESHOLD
            if not mask.any():
                return {"detections": [], "is_healthy": True}
            boxes_xywh = pred[mask][:, :4].astype(np.float64)
            scores_m = scores[mask].astype(np.float64)
            cls_m = cls_idx[mask]
            # 保留 top-2 类别：智能体据此判断 best 与 second 是否过于接近，
            # 接近时不直接下结论，而是发起鉴别性追问（避免误判）。
            cls_scores_m = cls_scores[mask].astype(np.float64)
            obj_m = obj[mask].astype(np.float64)
            xy, wh = boxes_xywh[:, :2], boxes_xywh[:, 2:]
            xyxy = np.concatenate([xy - wh / 2.0, xy + wh / 2.0], axis=1) * INPUT_SIZE
            r, left, top = data["r"], data["left"], data["top"]
            xyxy_orig = np.stack([
                (xyxy[:, 0] - left) / r, (xyxy[:, 1] - top) / r,
                (xyxy[:, 2] - left) / r, (xyxy[:, 3] - top) / r,
            ], axis=1)
            keep = _class_nms(xyxy_orig, scores_m, cls_m, IOU_THRESHOLD)
            detections = []
            for i in keep:
                x1, y1, x2, y2 = xyxy_orig[i]
                order = np.argsort(-cls_scores_m[i])[:2]
                top2 = [{"label": CLASS_NAMES[int(t)],
                         "score": round(float(obj_m[i] * cls_scores_m[i][t]), 4)}
                        for t in order]
                detections.append({
                    "label": CLASS_NAMES[int(cls_m[i])],
                    "confidence": round(float(scores_m[i]), 4),
                    "bbox": [round(float(min(x1, x2)), 1), round(float(min(y1, y2)), 1),
                             round(float(max(x1, x2)), 1), round(float(max(y1, y2)), 1)],
                    "top2": top2,
                })
            return {"detections": detections, "is_healthy": False}
        except Exception as exc:
            return {"error_code": "INTERNAL_ERROR", "message": f"后处理失败: {exc}"}