import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import labelmap
import expert_knowledge
from generate_prevention_plan import generate_plan, _parse_detected, _normalize_label_key

SCRIPT_PATH = Path(__file__).resolve().parent.parent / "generate_prevention_plan.py"
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        capture_output=True, text=True, timeout=10,
        cwd=str(PROJECT_ROOT),
    )


class TestMonthValidation(unittest.TestCase):
    def test_month_zero_exits_nonzero(self):
        result = _run_cli("--month", "0")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_month_thirteen_exits_nonzero(self):
        result = _run_cli("--month", "13")
        self.assertNotEqual(result.returncode, 0)

    def test_month_non_integer_exits_nonzero(self):
        result = _run_cli("--month", "abc")
        self.assertNotEqual(result.returncode, 0)

    def test_month_missing_exits_nonzero(self):
        result = _run_cli()
        self.assertNotEqual(result.returncode, 0)


class TestDetectedNormalization(unittest.TestCase):
    def test_valid_labels_parsed(self):
        detected, ignored = _parse_detected("anthracnose,red_spider_mite")
        self.assertEqual(detected, {"anthracnose", "red_spider_mite"})
        self.assertEqual(ignored, 0)

    def test_healthy_label_parsed(self):
        detected, ignored = _parse_detected("healthy")
        self.assertIn(labelmap.HEALTHY_LABEL, detected)
        self.assertEqual(ignored, 0)

    def test_alias_normalized(self):
        detected, ignored = _parse_detected("antracnose")
        self.assertIn("anthracnose", detected)

    def test_case_insensitive(self):
        detected, _ = _parse_detected("Anthracnose")
        self.assertIn("anthracnose", detected)

    def test_invalid_label_ignored(self):
        detected, ignored = _parse_detected("anthracnose,greasy_spot")
        self.assertIn("anthracnose", detected)
        self.assertNotIn("greasy_spot", detected)
        self.assertEqual(ignored, 1)

    def test_none_detected_returns_empty(self):
        detected, ignored = _parse_detected(None)
        self.assertEqual(detected, set())
        self.assertEqual(ignored, 0)

    def test_cli_invalid_label_warning(self):
        result = _run_cli("--month", "7", "--detected", "anthracnose,greasy_spot")
        self.assertEqual(result.returncode, 0)
        self.assertIn("已忽略", result.stderr)


class TestStatusAnnotation(unittest.TestCase):
    def test_detected_label_status_occurred(self):
        plan = generate_plan(7, {"anthracnose"})
        risks = {r["label"]: r for r in plan["risks"]}
        self.assertEqual(risks["anthracnose"]["status"], "occurred")

    def test_non_detected_label_status_prevention(self):
        plan = generate_plan(7, {"anthracnose"})
        risks = {r["label"]: r for r in plan["risks"]}
        self.assertEqual(risks["red_spider_mite"]["status"], "prevention")

    def test_no_detected_all_prevention(self):
        plan = generate_plan(7, set())
        for risk in plan["risks"]:
            self.assertEqual(risk["status"], "prevention")

    def test_detected_outside_month_risk_included(self):
        plan = generate_plan(1, {"anthracnose"})
        risks = {r["label"]: r for r in plan["risks"]}
        self.assertIn("anthracnose", risks)
        self.assertEqual(risks["anthracnose"]["status"], "occurred")

    def test_occurred_advice_differs_from_prevention(self):
        plan_prev = generate_plan(7, set())
        plan_occ = generate_plan(7, {"anthracnose"})
        risks_prev = {r["label"]: r for r in plan_prev["risks"]}
        risks_occ = {r["label"]: r for r in plan_occ["risks"]}
        self.assertNotEqual(
            risks_prev["anthracnose"]["medication_advice"],
            risks_occ["anthracnose"]["medication_advice"],
        )


class TestJsonStructure(unittest.TestCase):
    def test_top_level_fields(self):
        plan = generate_plan(7, set())
        self.assertIn("month", plan)
        self.assertIn("risks", plan)
        self.assertIn("general_advice", plan)

    def test_month_is_int(self):
        plan = generate_plan(7, set())
        self.assertEqual(plan["month"], 7)
        self.assertIsInstance(plan["month"], int)

    def test_risk_item_fields(self):
        plan = generate_plan(7, set())
        for risk in plan["risks"]:
            self.assertIn("label", risk)
            self.assertIn("status", risk)
            self.assertIn("prevention_measures", risk)
            self.assertIn("medication_advice", risk)
            self.assertIn("farming_advice", risk)

    def test_label_in_class_system(self):
        valid_labels = set(labelmap.CLASS_NAMES) | {labelmap.HEALTHY_LABEL}
        plan = generate_plan(7, {"anthracnose"})
        for risk in plan["risks"]:
            self.assertIn(risk["label"], valid_labels)

    def test_status_in_valid_values(self):
        plan = generate_plan(7, {"anthracnose"})
        for risk in plan["risks"]:
            self.assertIn(risk["status"], ("prevention", "occurred"))

    def test_cli_output_valid_json(self):
        result = _run_cli("--month", "7")
        self.assertEqual(result.returncode, 0)
        plan = json.loads(result.stdout)
        self.assertEqual(plan["month"], 7)


class TestHealthyMonth(unittest.TestCase):
    def test_january_risks_empty_or_healthy(self):
        plan = generate_plan(1, set())
        for risk in plan["risks"]:
            self.assertEqual(risk["label"], "healthy")
        self.assertTrue(plan["general_advice"])

    def test_january_general_advice_non_empty(self):
        plan = generate_plan(1, set())
        self.assertTrue(plan["general_advice"])

    def test_cli_january_output(self):
        result = _run_cli("--month", "1")
        self.assertEqual(result.returncode, 0)
        plan = json.loads(result.stdout)
        self.assertEqual(plan["month"], 1)
        self.assertTrue(plan["general_advice"])


class TestDetectedOutsideMonth(unittest.TestCase):
    def test_january_with_anthracnose_includes_occurred(self):
        plan = generate_plan(1, {"anthracnose"})
        risks = {r["label"]: r for r in plan["risks"]}
        self.assertIn("anthracnose", risks)
        self.assertEqual(risks["anthracnose"]["status"], "occurred")


class TestOfflineAvailability(unittest.TestCase):
    def test_script_runs_without_network(self):
        env = os.environ.copy()
        env["NO_NETWORK"] = "1"
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--month", "7"],
            capture_output=True, text=True, timeout=10,
            cwd=str(PROJECT_ROOT), env=env,
        )
        self.assertEqual(result.returncode, 0)
        plan = json.loads(result.stdout)
        self.assertEqual(plan["month"], 7)
        self.assertTrue(plan["general_advice"])


class TestAllMonthsEndToEnd(unittest.TestCase):
    def test_all_12_months_produce_valid_plan(self):
        for month in range(1, 13):
            plan = generate_plan(month, set())
            self.assertEqual(plan["month"], month)
            self.assertTrue(plan["general_advice"])
            self.assertIsInstance(plan["risks"], list)


if __name__ == "__main__":
    unittest.main()