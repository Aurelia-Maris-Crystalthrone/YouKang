import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from labelmap import (
    CLASS_NAMES, CONF_THRESHOLD, IOU_THRESHOLD, HEALTHY_LABEL,
    normalize_class_name, is_negative_class,
)


class TestClassNames(unittest.TestCase):
    def test_detect_class_system(self):
        # healthy 不再是检测类，改为负样本；greening 因数据充足提前纳入
        self.assertEqual(CLASS_NAMES, ("red_spider_mite", "anthracnose", "canker", "greening"))
        self.assertEqual(CONF_THRESHOLD, 0.25)
        self.assertEqual(IOU_THRESHOLD, 0.45)
        self.assertEqual(HEALTHY_LABEL, "healthy")
        self.assertNotIn(HEALTHY_LABEL, CLASS_NAMES)


class TestNormalizeClassName(unittest.TestCase):
    def test_canonical_mapping(self):
        self.assertEqual(normalize_class_name("red_spider_mite"), 0)
        self.assertEqual(normalize_class_name("anthracnose"), 1)
        self.assertEqual(normalize_class_name("canker"), 2)
        self.assertEqual(normalize_class_name("greening"), 3)

    def test_case_insensitive(self):
        self.assertEqual(normalize_class_name("Antracnose"), 1)
        self.assertEqual(normalize_class_name("Canker"), 2)
        self.assertEqual(normalize_class_name("Greening"), 3)
        self.assertEqual(normalize_class_name("GREENING"), 3)

    def test_aliases(self):
        self.assertEqual(normalize_class_name("spider mites"), 0)
        self.assertEqual(normalize_class_name("spider_mites"), 0)
        self.assertEqual(normalize_class_name("citrus mite"), 0)
        self.assertEqual(normalize_class_name("citrus_mite"), 0)
        self.assertEqual(normalize_class_name("antracnose"), 1)
        self.assertEqual(normalize_class_name("citrus canker"), 2)
        self.assertEqual(normalize_class_name("Citrus Canker"), 2)
        self.assertEqual(normalize_class_name("huanglongbing"), 3)
        self.assertEqual(normalize_class_name("hlb"), 3)


class TestNegativeClasses(unittest.TestCase):
    """负样本：健康叶与易误判非目标类，不占检测类别编号。"""

    def test_healthy_is_negative(self):
        self.assertIsNone(normalize_class_name("healthy"))
        self.assertTrue(is_negative_class("healthy"))
        self.assertTrue(is_negative_class("Healthy"))

    def test_confusable_classes_are_negative(self):
        for name in ("deficiency_leaf", "Deficiency Leaf", "melanose",
                     "sooty_mould", "greasy_spot", "black_spot", "curl_leaf"):
            self.assertIsNone(normalize_class_name(name), name)
            self.assertTrue(is_negative_class(name), name)

    def test_detect_classes_are_not_negative(self):
        for name in CLASS_NAMES:
            self.assertFalse(is_negative_class(name), name)

    def test_unknown_returns_none(self):
        for name in ("", "未知", "unknown_class", "random_thing"):
            self.assertIsNone(normalize_class_name(name), name)
            self.assertFalse(is_negative_class(name), name)

    def test_none_and_whitespace(self):
        self.assertIsNone(normalize_class_name(None))
        self.assertIsNone(normalize_class_name(123))
        self.assertIsNone(normalize_class_name("  healthy  "))
        self.assertTrue(is_negative_class("  healthy  "))


if __name__ == "__main__":
    unittest.main()
