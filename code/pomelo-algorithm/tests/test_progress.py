"""打药效果追踪模块单元测试。

覆盖：
1. 扩散判定（SPREADING）
2. 稳定判定（STABLE）
3. 收敛判定（RECOVERING）
4. 新增病斑检测
5. 消失病斑检测
6. 建议生成
"""
import unittest

from tracking.progress import (
    compare,
    advise_on_progress,
    Conclusion,
    Observation,
    Detection,
)


def _make_detection(label, confidence, bbox):
    """创建检测对象。"""
    return Detection(label=label, confidence=confidence, bbox=bbox, top2=[])


class TestCompare(unittest.TestCase):
    """compare 函数测试。"""

    def test_spreading_by_count(self):
        """扩散：病斑数量增加。"""
        prev = Observation(
            orchard_id=1, captured_at="2026-10-20",
            detections=[
                _make_detection("canker", 0.85, [100, 100, 150, 150]),
                _make_detection("canker", 0.80, [200, 200, 250, 250]),
            ]
        )
        curr = Observation(
            orchard_id=1, captured_at="2026-10-28",
            detections=[
                _make_detection("canker", 0.85, [100, 100, 150, 150]),
                _make_detection("canker", 0.80, [200, 200, 250, 250]),
                _make_detection("canker", 0.75, [300, 300, 350, 350]),  # 新增
            ]
        )
        result = compare(prev, curr)
        self.assertEqual(result.conclusion, Conclusion.SPREADING)
        self.assertEqual(result.lesion_count_change, 1)
        self.assertEqual(len(result.new_lesions), 1)

    def test_spreading_by_area(self):
        """扩散：病斑面积扩大 > 20%。"""
        prev = Observation(
            orchard_id=1, captured_at="2026-10-20",
            detections=[
                _make_detection("canker", 0.85, [100, 100, 110, 110]),  # 面积 100
            ]
        )
        curr = Observation(
            orchard_id=1, captured_at="2026-10-28",
            detections=[
                _make_detection("canker", 0.85, [100, 100, 150, 150]),  # 面积 2500
            ]
        )
        result = compare(prev, curr)
        self.assertEqual(result.conclusion, Conclusion.SPREADING)
        self.assertGreater(result.total_area_change_rate, 0.2)

    def test_stable(self):
        """稳定：病斑数量与面积基本不变。"""
        prev = Observation(
            orchard_id=1, captured_at="2026-10-20",
            detections=[
                _make_detection("canker", 0.85, [100, 100, 150, 150]),
                _make_detection("canker", 0.80, [200, 200, 250, 250]),
            ]
        )
        curr = Observation(
            orchard_id=1, captured_at="2026-10-28",
            detections=[
                _make_detection("canker", 0.85, [100, 100, 150, 150]),
                _make_detection("canker", 0.80, [200, 200, 250, 250]),
            ]
        )
        result = compare(prev, curr)
        self.assertEqual(result.conclusion, Conclusion.STABLE)
        self.assertEqual(result.lesion_count_change, 0)
        self.assertAlmostEqual(result.total_area_change_rate, 0.0, places=5)

    def test_recovering_by_count(self):
        """收敛：病斑数量减少。"""
        prev = Observation(
            orchard_id=1, captured_at="2026-10-20",
            detections=[
                _make_detection("canker", 0.85, [100, 100, 150, 150]),
                _make_detection("canker", 0.80, [200, 200, 250, 250]),
                _make_detection("canker", 0.75, [300, 300, 350, 350]),
            ]
        )
        curr = Observation(
            orchard_id=1, captured_at="2026-10-28",
            detections=[
                _make_detection("canker", 0.85, [100, 100, 150, 150]),
                _make_detection("canker", 0.80, [200, 200, 250, 250]),
            ]
        )
        result = compare(prev, curr)
        self.assertEqual(result.conclusion, Conclusion.RECOVERING)
        self.assertEqual(result.lesion_count_change, -1)
        self.assertEqual(len(result.disappeared_lesions), 1)

    def test_recovering_by_area(self):
        """收敛：病斑面积缩小 > 20%。"""
        prev = Observation(
            orchard_id=1, captured_at="2026-10-20",
            detections=[
                _make_detection("canker", 0.85, [100, 100, 150, 150]),  # 面积 2500
            ]
        )
        curr = Observation(
            orchard_id=1, captured_at="2026-10-28",
            detections=[
                _make_detection("canker", 0.85, [100, 100, 110, 110]),  # 面积 100
            ]
        )
        result = compare(prev, curr)
        self.assertEqual(result.conclusion, Conclusion.RECOVERING)
        self.assertLess(result.total_area_change_rate, -0.2)

    def test_new_lesions(self):
        """新增病斑检测。"""
        prev = Observation(
            orchard_id=1, captured_at="2026-10-20",
            detections=[
                _make_detection("canker", 0.85, [100, 100, 150, 150]),
            ]
        )
        curr = Observation(
            orchard_id=1, captured_at="2026-10-28",
            detections=[
                _make_detection("canker", 0.85, [100, 100, 150, 150]),
                _make_detection("canker", 0.75, [300, 300, 350, 350]),  # 新增
            ]
        )
        result = compare(prev, curr)
        self.assertEqual(len(result.new_lesions), 1)
        self.assertEqual(result.new_lesions[0]["x"], 325.0)

    def test_disappeared_lesions(self):
        """消失病斑检测。"""
        prev = Observation(
            orchard_id=1, captured_at="2026-10-20",
            detections=[
                _make_detection("canker", 0.85, [100, 100, 150, 150]),
                _make_detection("canker", 0.75, [300, 300, 350, 350]),
            ]
        )
        curr = Observation(
            orchard_id=1, captured_at="2026-10-28",
            detections=[
                _make_detection("canker", 0.85, [100, 100, 150, 150]),
            ]
        )
        result = compare(prev, curr)
        self.assertEqual(len(result.disappeared_lesions), 1)

    def test_empty_prev_observation(self):
        """前一次观测为空：所有病斑都是新增。"""
        prev = Observation(
            orchard_id=1, captured_at="2026-10-20",
            detections=[]
        )
        curr = Observation(
            orchard_id=1, captured_at="2026-10-28",
            detections=[
                _make_detection("canker", 0.85, [100, 100, 150, 150]),
            ]
        )
        result = compare(prev, curr)
        self.assertEqual(result.conclusion, Conclusion.SPREADING)
        self.assertEqual(len(result.new_lesions), 1)

    def test_both_empty(self):
        """两次观测都为空：稳定。"""
        prev = Observation(
            orchard_id=1, captured_at="2026-10-20",
            detections=[]
        )
        curr = Observation(
            orchard_id=1, captured_at="2026-10-28",
            detections=[]
        )
        result = compare(prev, curr)
        self.assertEqual(result.conclusion, Conclusion.STABLE)

    def test_different_labels_not_matched(self):
        """不同类别的病斑不匹配。"""
        prev = Observation(
            orchard_id=1, captured_at="2026-10-20",
            detections=[
                _make_detection("canker", 0.85, [100, 100, 150, 150]),
            ]
        )
        curr = Observation(
            orchard_id=1, captured_at="2026-10-28",
            detections=[
                _make_detection("anthracnose", 0.85, [100, 100, 150, 150]),  # 不同类别
            ]
        )
        result = compare(prev, curr)
        # 不同类别不匹配，数量与面积均未变化，结论为稳定
        self.assertEqual(result.conclusion, Conclusion.STABLE)


class TestAdviseOnProgress(unittest.TestCase):
    """advise_on_progress 函数测试。"""

    def test_spreading_advice(self):
        """扩散 → 建议换药。"""
        advice = advise_on_progress(
            conclusion=Conclusion.SPREADING,
            spray_history=[
                {"spray_date": "2026-10-21", "pesticide_name": "阿维菌素", "frac_irac_code": "6"}
            ],
            current_pesticide="阿维菌素",
            disease="red_spider_mite"
        )
        self.assertEqual(advice["action"], "换药")
        self.assertTrue(advice["switch_needed"])
        self.assertIn("换用", advice["recommendation"])

    def test_stable_advice(self):
        """稳定 → 继续观察。"""
        advice = advise_on_progress(
            conclusion=Conclusion.STABLE,
            spray_history=[]
        )
        self.assertEqual(advice["action"], "继续观察")
        self.assertFalse(advice["switch_needed"])

    def test_recovering_advice(self):
        """收敛 → 维持方案。"""
        advice = advise_on_progress(
            conclusion=Conclusion.RECOVERING,
            spray_history=[]
        )
        self.assertEqual(advice["action"], "维持方案")
        self.assertFalse(advice["switch_needed"])

    def test_spreading_without_history(self):
        """扩散但无施药历史 → 通用换药建议。"""
        advice = advise_on_progress(
            conclusion=Conclusion.SPREADING,
            spray_history=[]
        )
        self.assertEqual(advice["action"], "换药")
        self.assertIn("换用不同作用机理组的药剂", advice["recommendation"])


class TestConclusionEnum(unittest.TestCase):
    """结论枚举测试。"""

    def test_conclusion_values(self):
        self.assertEqual(Conclusion.SPREADING.value, "SPREADING")
        self.assertEqual(Conclusion.STABLE.value, "STABLE")
        self.assertEqual(Conclusion.RECOVERING.value, "RECOVERING")


if __name__ == "__main__":
    unittest.main()