import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from postprocess.yolo_postprocess import (INPUT_SIZE, box_iou, letterbox_params,
                                          postprocess)


def make_output(boxes, num_classes=4, anchors=25200):
    arr = np.zeros((1, anchors, 5 + num_classes), dtype=np.float32)
    for i, b in enumerate(boxes):
        arr[0, i, :4] = b[:4]
        arr[0, i, 4] = b[4]
        arr[0, i, 5:5 + num_classes] = b[5:]
    return arr


BOX1 = (0.5, 0.5, 0.2, 0.2, 0.9, 0.1, 0.8, 0.05, 0.05)
BOX2 = (0.51, 0.51, 0.2, 0.2, 0.85, 0.1, 0.9, 0.05, 0.05)
BOX3_LOW = (0.5, 0.5, 0.2, 0.2, 0.4, 0.4, 0.1, 0.1, 0.1)
BOX4 = (0.8, 0.8, 0.1, 0.1, 0.9, 0.1, 0.1, 0.05, 0.95)


class TestDimensionValidation(unittest.TestCase):
    def test_valid_shape(self):
        result = postprocess(make_output([BOX1]))
        self.assertIn("detections", result)

    def test_wrong_shape_rejected(self):
        with self.assertRaises(ValueError):
            postprocess(np.zeros((1, 9, 25200), dtype=np.float32))
        with self.assertRaises(ValueError):
            postprocess(np.zeros((25200, 9), dtype=np.float32))
        with self.assertRaises(ValueError):
            postprocess(make_output([BOX1], num_classes=3, anchors=100))

    def test_num_classes_dimension_linkage(self):
        box_nc3 = (0.5, 0.5, 0.2, 0.2, 0.9, 0.1, 0.8, 0.1)
        result = postprocess(make_output([box_nc3], num_classes=3), num_classes=3)
        self.assertEqual(len(result["detections"]), 1)
        with self.assertRaises(ValueError):
            postprocess(make_output([BOX1]), num_classes=3)


class TestScoreDecodeAndFilter(unittest.TestCase):
    def test_score_obj_times_cls_max(self):
        result = postprocess(make_output([BOX1]))
        self.assertEqual(len(result["detections"]), 1)
        det = result["detections"][0]
        self.assertEqual(det["label"], "anthracnose")
        self.assertAlmostEqual(det["confidence"], 0.72, places=3)

    def test_low_score_filtered(self):
        result = postprocess(make_output([BOX3_LOW]))
        self.assertEqual(result["detections"], [])

    def test_all_filtered_returns_empty(self):
        result = postprocess(make_output([BOX3_LOW, BOX3_LOW]))
        self.assertEqual(result["detections"], [])

    def test_threshold_boundary(self):
        box = (0.5, 0.5, 0.2, 0.2, 0.5, 0.9, 0.0, 0.0, 0.0)
        result = postprocess(make_output([box]), conf_threshold=0.45)
        self.assertEqual(len(result["detections"]), 1)

    def test_invalid_threshold_rejected(self):
        with self.assertRaises(ValueError):
            postprocess(make_output([BOX1]), conf_threshold=0.0)
        with self.assertRaises(ValueError):
            postprocess(make_output([BOX1]), iou_threshold=1.5)


class TestCoordConvertAndMap(unittest.TestCase):
    def test_xywh_to_xyxy_640_system(self):
        result = postprocess(make_output([BOX1]))
        self.assertEqual(result["detections"][0]["bbox"], [256.0, 256.0, 384.0, 384.0])

    def test_map_to_original_size(self):
        result = postprocess(make_output([BOX1]), original_size=(1920, 1080))
        self.assertEqual(result["detections"][0]["bbox"], [768.0, 348.0, 1152.0, 732.0])

    def test_letterbox_params(self):
        r, left, top = letterbox_params(1920, 1080)
        self.assertAlmostEqual(r, 640 / 1920)
        self.assertEqual(left, 0)
        self.assertEqual(top, 140)
        r, left, top = letterbox_params(1080, 1920)
        self.assertEqual(left, 140)
        self.assertEqual(top, 0)


class TestNMS(unittest.TestCase):
    def test_same_class_suppression(self):
        result = postprocess(make_output([BOX1, BOX2, BOX4]))
        labels = [d["label"] for d in result["detections"]]
        self.assertEqual(len(result["detections"]), 2)
        self.assertIn("anthracnose", labels)
        self.assertIn("greening", labels)
        best = [d for d in result["detections"] if d["label"] == "anthracnose"][0]
        self.assertAlmostEqual(best["confidence"], 0.765, places=3)

    def test_box_iou(self):
        a = np.array([[0.0, 0.0, 2.0, 2.0]])
        b = np.array([[1.0, 1.0, 3.0, 3.0]])
        self.assertAlmostEqual(box_iou(a, b)[0, 0], 1.0 / 7.0, places=6)
        self.assertEqual(box_iou(a, np.array([[10.0, 10.0, 12.0, 12.0]]))[0, 0], 0.0)


if __name__ == "__main__":
    unittest.main()