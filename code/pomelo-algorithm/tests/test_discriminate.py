"""病害鉴别判断模块单元测试。

覆盖：
1. margin 判定
2. 问题匹配
3. 后验更新
4. 验证 4：top2 = [canker 0.52, anthracnose 0.44] 返回 True 且问出"隆起还是平塌"
"""
import unittest

from agent.discriminate import (
    needs_clarification,
    next_question,
    apply_answer,
    get_distinguishing_features,
    get_source,
)


class TestNeedsClarification(unittest.TestCase):
    """margin 判定测试。"""

    def test_confidence_diff_above_margin(self):
        """正例：置信度差 > margin，不需要澄清。"""
        detection = {
            "label": "canker",
            "confidence": 0.85,
            "bbox": [10, 10, 100, 100],
            "top2": [
                {"label": "canker", "score": 0.85},
                {"label": "anthracnose", "score": 0.30}
            ]
        }
        self.assertFalse(needs_clarification(detection, margin=0.15))

    def test_confidence_diff_below_margin(self):
        """反例：置信度差 < margin，需要澄清。"""
        detection = {
            "label": "canker",
            "confidence": 0.52,
            "bbox": [10, 10, 100, 100],
            "top2": [
                {"label": "canker", "score": 0.52},
                {"label": "anthracnose", "score": 0.44}
            ]
        }
        self.assertTrue(needs_clarification(detection, margin=0.15))

    def test_confidence_diff_equal_margin(self):
        """边界：置信度差 = margin，需要澄清（严格小于才通过）。"""
        detection = {
            "label": "canker",
            "confidence": 0.60,
            "bbox": [10, 10, 100, 100],
            "top2": [
                {"label": "canker", "score": 0.60},
                {"label": "anthracnose", "score": 0.45}
            ]
        }
        # 置信度差 = 0.15 = margin，严格小于才通过，所以需要澄清
        self.assertTrue(needs_clarification(detection, margin=0.15))

    def test_single_top2(self):
        """边界：只有 top2[0]，不需要澄清。"""
        detection = {
            "label": "canker",
            "confidence": 0.85,
            "bbox": [10, 10, 100, 100],
            "top2": [
                {"label": "canker", "score": 0.85}
            ]
        }
        self.assertFalse(needs_clarification(detection, margin=0.15))


class TestNextQuestion(unittest.TestCase):
    """问题匹配测试。"""

    def test_canker_vs_anthracnose(self):
        """canker vs anthracnose：问出"隆起还是平塌"。"""
        detection = {
            "label": "canker",
            "confidence": 0.52,
            "bbox": [10, 10, 100, 100],
            "top2": [
                {"label": "canker", "score": 0.52},
                {"label": "anthracnose", "score": 0.44}
            ]
        }
        result = next_question(detection)
        self.assertIsNotNone(result)
        self.assertEqual(result["best"], "canker")
        self.assertEqual(result["second"], "anthracnose")
        self.assertIn("隆起", result["question"])
        self.assertIn("平塌", result["question"])
        self.assertEqual(result["question_key"], "morphology")
        self.assertEqual(len(result["answers"]), 2)

    def test_greening_vs_deficiency(self):
        """greening vs deficiency：问出"斑驳还是均匀"。"""
        detection = {
            "label": "greening",
            "confidence": 0.50,
            "bbox": [10, 10, 100, 100],
            "top2": [
                {"label": "greening", "score": 0.50},
                {"label": "deficiency", "score": 0.48}
            ]
        }
        result = next_question(detection)
        self.assertIsNotNone(result)
        self.assertEqual(result["best"], "greening")
        self.assertEqual(result["second"], "deficiency")
        self.assertIn("斑点", result["question"])
        self.assertIn("均匀", result["question"])

    def test_red_spider_mite_vs_healthy(self):
        """red_spider_mite vs healthy：问出"红色小虫"。"""
        detection = {
            "label": "red_spider_mite",
            "confidence": 0.55,
            "bbox": [10, 10, 100, 100],
            "top2": [
                {"label": "red_spider_mite", "score": 0.55},
                {"label": "healthy", "score": 0.45}
            ]
        }
        result = next_question(detection)
        self.assertIsNotNone(result)
        self.assertEqual(result["best"], "red_spider_mite")
        self.assertEqual(result["second"], "healthy")
        self.assertIn("红色", result["question"])

    def test_unknown_pair(self):
        """未知病害对：返回 None。"""
        detection = {
            "label": "unknown",
            "confidence": 0.50,
            "bbox": [10, 10, 100, 100],
            "top2": [
                {"label": "unknown", "score": 0.50},
                {"label": "another", "score": 0.48}
            ]
        }
        result = next_question(detection)
        self.assertIsNone(result)

    def test_no_top2(self):
        """无 top2 字段：返回 None。"""
        detection = {
            "label": "canker",
            "confidence": 0.85,
            "bbox": [10, 10, 100, 100]
        }
        result = next_question(detection)
        self.assertIsNone(result)


class TestApplyAnswer(unittest.TestCase):
    """后验更新测试。"""

    def test_canker_vs_anthracnose_flat_answer(self):
        """canker vs anthracnose，回答"平塌"，结论转向 anthracnose。"""
        detection = {
            "label": "canker",
            "confidence": 0.52,
            "bbox": [10, 10, 100, 100],
            "top2": [
                {"label": "canker", "score": 0.52},
                {"label": "anthracnose", "score": 0.44}
            ]
        }
        result = apply_answer(detection, "flat")
        self.assertEqual(result["best"], "anthracnose")
        self.assertEqual(result["second"], "canker")
        self.assertGreater(result["confidence"], 0.5)
        self.assertEqual(result["answer_key"], "flat")
        self.assertIn("anthracnose", result["likelihood_used"])
        self.assertIn("canker", result["likelihood_used"])

    def test_canker_vs_anthracnose_raised_answer(self):
        """canker vs anthracnose，回答"隆起"，结论保持 canker。"""
        detection = {
            "label": "canker",
            "confidence": 0.52,
            "bbox": [10, 10, 100, 100],
            "top2": [
                {"label": "canker", "score": 0.52},
                {"label": "anthracnose", "score": 0.44}
            ]
        }
        result = apply_answer(detection, "raised")
        self.assertEqual(result["best"], "canker")
        self.assertEqual(result["second"], "anthracnose")
        self.assertGreater(result["confidence"], 0.5)

    def test_greening_vs_deficiency_mottled_answer(self):
        """greening vs deficiency，回答"斑驳"，结论转向 greening。"""
        detection = {
            "label": "deficiency",
            "confidence": 0.48,
            "bbox": [10, 10, 100, 100],
            "top2": [
                {"label": "deficiency", "score": 0.48},
                {"label": "greening", "score": 0.50}
            ]
        }
        result = apply_answer(detection, "mottled")
        self.assertEqual(result["best"], "greening")
        self.assertEqual(result["second"], "deficiency")

    def test_unknown_answer_key(self):
        """未知答案 key：返回原结论。"""
        detection = {
            "label": "canker",
            "confidence": 0.52,
            "bbox": [10, 10, 100, 100],
            "top2": [
                {"label": "canker", "score": 0.52},
                {"label": "anthracnose", "score": 0.44}
            ]
        }
        result = apply_answer(detection, "unknown_key")
        self.assertEqual(result["best"], "canker")
        self.assertEqual(result["second"], "anthracnose")
        self.assertEqual(result["confidence"], 0.52)

    def test_no_top2(self):
        """无 top2 字段：返回原结论。"""
        detection = {
            "label": "canker",
            "confidence": 0.85,
            "bbox": [10, 10, 100, 100]
        }
        result = apply_answer(detection, "flat")
        self.assertEqual(result["best"], "canker")
        self.assertEqual(result["confidence"], 0.85)


class TestValidation4(unittest.TestCase):
    """验证 4：top2 = [canker 0.52, anthracnose 0.44] 输入。"""

    def test_validation_4_needs_clarification(self):
        """确认返回 True。"""
        detection = {
            "label": "canker",
            "confidence": 0.52,
            "bbox": [10, 10, 100, 100],
            "top2": [
                {"label": "canker", "score": 0.52},
                {"label": "anthracnose", "score": 0.44}
            ]
        }
        self.assertTrue(needs_clarification(detection, margin=0.15))

    def test_validation_4_question_content(self):
        """确认问出"隆起还是平塌"。"""
        detection = {
            "label": "canker",
            "confidence": 0.52,
            "bbox": [10, 10, 100, 100],
            "top2": [
                {"label": "canker", "score": 0.52},
                {"label": "anthracnose", "score": 0.44}
            ]
        }
        result = next_question(detection)
        self.assertIsNotNone(result)
        self.assertIn("隆起", result["question"])
        self.assertIn("平塌", result["question"])

    def test_validation_4_apply_answer(self):
        """模拟回答"平塌"后结论应转向 anthracnose。"""
        detection = {
            "label": "canker",
            "confidence": 0.52,
            "bbox": [10, 10, 100, 100],
            "top2": [
                {"label": "canker", "score": 0.52},
                {"label": "anthracnose", "score": 0.44}
            ]
        }
        result = apply_answer(detection, "flat")
        self.assertEqual(result["best"], "anthracnose")
        self.assertGreater(result["confidence"], 0.5)


class TestDistinguishingFeatures(unittest.TestCase):
    """区分特征测试。"""

    def test_canker_vs_anthracnose_features(self):
        features = get_distinguishing_features("canker", "anthracnose")
        self.assertIsNotNone(features)
        self.assertIn("隆起", features[0])
        self.assertIn("黄晕", features[1])
        self.assertIn("轮纹", features[2])

    def test_unknown_pair_features(self):
        features = get_distinguishing_features("unknown", "another")
        self.assertIsNone(features)


class TestSource(unittest.TestCase):
    """来源测试。"""

    def test_canker_vs_anthracnose_source(self):
        source = get_source("canker", "anthracnose")
        self.assertIsNotNone(source)
        self.assertIn("柑橘病虫害防治手册", source)


if __name__ == "__main__":
    unittest.main()