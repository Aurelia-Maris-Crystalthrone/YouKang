import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from expert_knowledge import (
    PreventionAdvice,
    MONTH_PEST_MAP,
    PEST_ADVICE,
    GENERAL_ADVICE,
    get_month_pests,
    get_advice,
    get_general_advice,
)


class TestMonthCoverage(unittest.TestCase):
    def test_all_12_months_return_valid(self):
        for month in range(1, 13):
            pests = get_month_pests(month)
            self.assertIsInstance(pests, list)
            self.assertGreater(len(pests), 0, f"月份 {month} 须返回非空列表")

    def test_month_pest_map_covers_all_months(self):
        self.assertEqual(set(MONTH_PEST_MAP.keys()), set(range(1, 13)))


class TestMonthPestRelation(unittest.TestCase):
    def test_july_returns_red_spider_mite_and_anthracnose(self):
        pests = get_month_pests(7)
        self.assertIn("red_spider_mite", pests)
        self.assertIn("anthracnose", pests)

    def test_january_returns_healthy(self):
        pests = get_month_pests(1)
        self.assertIn("healthy", pests)

    def test_may_returns_anthracnose_and_canker(self):
        pests = get_month_pests(5)
        self.assertIn("anthracnose", pests)
        self.assertIn("canker", pests)

    def test_october_returns_canker(self):
        pests = get_month_pests(10)
        self.assertIn("canker", pests)


class TestAdviceStructure(unittest.TestCase):
    def test_advice_fields_non_empty(self):
        for key, advice in PEST_ADVICE.items():
            self.assertIsInstance(advice, PreventionAdvice)
            self.assertTrue(advice.prevention_measures, f"{key}.prevention_measures 须非空")
            self.assertTrue(advice.medication_advice, f"{key}.medication_advice 须非空")
            self.assertTrue(advice.farming_advice, f"{key}.farming_advice 须非空")

    def test_prevention_and_occurred_differ(self):
        for label in ("red_spider_mite", "anthracnose", "canker"):
            prev = get_advice(label, "prevention")
            occurred = get_advice(label, "occurred")
            self.assertNotEqual(prev.medication_advice, occurred.medication_advice,
                                f"{label} 的 prevention 与 occurred 用药建议须不同")

    def test_all_6_advice_entries_present(self):
        expected = {
            ("red_spider_mite", "prevention"), ("red_spider_mite", "occurred"),
            ("anthracnose", "prevention"), ("anthracnose", "occurred"),
            ("canker", "prevention"), ("canker", "occurred"),
            ("greening", "prevention"), ("greening", "occurred"),
        }
        self.assertEqual(set(PEST_ADVICE.keys()), expected)


class TestGeneralAdvice(unittest.TestCase):
    def test_all_12_months_non_empty(self):
        self.assertEqual(set(GENERAL_ADVICE.keys()), set(range(1, 13)))
        for month in range(1, 13):
            advice = get_general_advice(month)
            self.assertIsInstance(advice, str)
            self.assertTrue(advice, f"月份 {month} 常规建议须非空")


class TestInterfaceRobustness(unittest.TestCase):
    def test_month_zero_returns_empty_list(self):
        self.assertEqual(get_month_pests(0), [])

    def test_month_thirteen_returns_empty_list(self):
        self.assertEqual(get_month_pests(13), [])

    def test_month_negative_returns_empty_list(self):
        self.assertEqual(get_month_pests(-1), [])

    def test_general_advice_invalid_month_returns_empty_string(self):
        self.assertEqual(get_general_advice(0), "")
        self.assertEqual(get_general_advice(13), "")

    def test_get_advice_unknown_label_returns_default(self):
        advice = get_advice("unknown_pest", "prevention")
        self.assertIsInstance(advice, PreventionAdvice)
        self.assertTrue(advice.prevention_measures)

    def test_get_advice_unknown_status_returns_default(self):
        advice = get_advice("anthracnose", "unknown_status")
        self.assertIsInstance(advice, PreventionAdvice)


if __name__ == "__main__":
    unittest.main()