"""农药规则引擎单元测试。

覆盖：
a) 安全间隔期
b) 抗药性轮换
c) 每季次数上限
d) 物候期禁忌
e) 复配禁忌
guardrail 拦截幻觉药名
"""
import unittest
from datetime import date, timedelta

from prescription.rule_engine import (
    Pesticide, Orchard, SprayRecord, PesticideConflict, PhenophaseContraindication,
    filter_pesticides, format_rejection_report,
)
from prescription.guardrail import validate_output, format_guardrail_report


class TestRuleEngine(unittest.TestCase):
    """规则引擎测试。"""

    def setUp(self):
        """设置测试数据。"""
        self.today = date(2026, 10, 28)
        self.orchard = Orchard(
            block_name="测试地块",
            variety="琯溪蜜柚",
            tree_age=8,
            current_phenophase="膨大期",
            expected_harvest_date=date(2026, 11, 15),  # 距采收 18 天
            area_mu=5.0,
        )
        self.spray_history: list[SprayRecord] = []

    # ============================================================
    # 规则 a) 安全间隔期
    # ============================================================
    def test_phi_pass(self):
        """正例：距采收天数 > PHI，通过。"""
        # 距采收 18 天，PHI 7 天，应通过
        pesticide = Pesticide(
            id=1, common_name="阿维菌素", active_ingredient="阿维菌素",
            formulation="乳油", content="1.8%", frac_irac_code="6",
            phi_days=7, max_times_per_season=2, toxicity_level="低毒",
            is_banned=False, registered_crops=["柑橘"],
        )
        output = filter_pesticides(
            disease="red_spider_mite",
            orchard=self.orchard,
            spray_history=self.spray_history,
            today=self.today,
            candidate_pesticides=[pesticide],
        )
        self.assertEqual(len(output.allowed), 1)
        self.assertEqual(len(output.rejected), 0)

    def test_phi_reject(self):
        """反例：距采收天数 < PHI，拒绝。"""
        # 距采收 18 天，PHI 30 天，应拒绝
        pesticide = Pesticide(
            id=1, common_name="某长效药剂", active_ingredient="某成分",
            formulation="悬浮剂", content="10%", frac_irac_code="20B",
            phi_days=30, max_times_per_season=2, toxicity_level="低毒",
            is_banned=False, registered_crops=["柑橘"],
        )
        output = filter_pesticides(
            disease="red_spider_mite",
            orchard=self.orchard,
            spray_history=self.spray_history,
            today=self.today,
            candidate_pesticides=[pesticide],
        )
        self.assertEqual(len(output.allowed), 0)
        self.assertEqual(len(output.rejected), 1)
        self.assertIn("距采收仅 18 天", output.rejected[0].reason)
        self.assertIn("需 30 天", output.rejected[0].reason)

    # ============================================================
    # 规则 b) 抗药性轮换
    # ============================================================
    def test_resistance_rotation_pass(self):
        """正例：与最近一次施药作用机理组不同，通过。"""
        # 最近一次施药是 IRAC 6，候选药剂是 IRAC 20B，应通过
        self.spray_history = [
            SprayRecord(
                orchard_id=1, spray_date=self.today - timedelta(days=7),
                pesticide_id=1, pesticide_name="阿维菌素", frac_irac_code="6",
                dilution_ratio="3000 倍液",
            )
        ]
        pesticide = Pesticide(
            id=2, common_name="螺螨酯", active_ingredient="螺螨酯",
            formulation="悬浮剂", content="240g/L", frac_irac_code="20B",
            phi_days=14, max_times_per_season=2, toxicity_level="低毒",
            is_banned=False, registered_crops=["柑橘"],
        )
        output = filter_pesticides(
            disease="red_spider_mite",
            orchard=self.orchard,
            spray_history=self.spray_history,
            today=self.today,
            candidate_pesticides=[pesticide],
        )
        self.assertEqual(len(output.allowed), 1)
        self.assertEqual(len(output.rejected), 0)

    def test_resistance_rotation_reject(self):
        """反例：与最近一次施药作用机理组相同，拒绝。"""
        # 最近一次施药是 IRAC 6，候选药剂也是 IRAC 6，应拒绝
        self.spray_history = [
            SprayRecord(
                orchard_id=1, spray_date=self.today - timedelta(days=7),
                pesticide_id=1, pesticide_name="阿维菌素", frac_irac_code="6",
                dilution_ratio="3000 倍液",
            )
        ]
        pesticide = Pesticide(
            id=3, common_name="伊维菌素", active_ingredient="伊维菌素",
            formulation="乳油", content="1.8%", frac_irac_code="6",
            phi_days=7, max_times_per_season=2, toxicity_level="低毒",
            is_banned=False, registered_crops=["柑橘"],
        )
        output = filter_pesticides(
            disease="red_spider_mite",
            orchard=self.orchard,
            spray_history=self.spray_history,
            today=self.today,
            candidate_pesticides=[pesticide],
        )
        self.assertEqual(len(output.allowed), 0)
        self.assertEqual(len(output.rejected), 1)
        self.assertIn("同属第 6 组", output.rejected[0].reason)
        self.assertIn("抗药性风险", output.rejected[0].reason)

    # ============================================================
    # 规则 c) 每季次数上限
    # ============================================================
    def test_max_times_pass(self):
        """正例：本季使用次数未达上限，通过。"""
        # 已使用 1 次阿维菌素（IRAC 6），候选药剂是螺螨酯（IRAC 20B），不同组，应通过
        self.spray_history = [
            SprayRecord(
                orchard_id=1, spray_date=self.today - timedelta(days=30),
                pesticide_id=1, pesticide_name="阿维菌素", frac_irac_code="6",
                dilution_ratio="3000 倍液",
            )
        ]
        pesticide = Pesticide(
            id=2, common_name="螺螨酯", active_ingredient="螺螨酯",
            formulation="悬浮剂", content="240g/L", frac_irac_code="20B",
            phi_days=14, max_times_per_season=2, toxicity_level="低毒",
            is_banned=False, registered_crops=["柑橘"],
        )
        output = filter_pesticides(
            disease="red_spider_mite",
            orchard=self.orchard,
            spray_history=self.spray_history,
            today=self.today,
            candidate_pesticides=[pesticide],
        )
        self.assertEqual(len(output.allowed), 1)

    def test_max_times_reject(self):
        """反例：本季使用次数已达上限，拒绝。"""
        # 已使用 2 次，上限 2 次，应拒绝
        self.spray_history = [
            SprayRecord(
                orchard_id=1, spray_date=self.today - timedelta(days=60),
                pesticide_id=1, pesticide_name="阿维菌素", frac_irac_code="6",
                dilution_ratio="3000 倍液",
            ),
            SprayRecord(
                orchard_id=1, spray_date=self.today - timedelta(days=30),
                pesticide_id=1, pesticide_name="阿维菌素", frac_irac_code="6",
                dilution_ratio="3000 倍液",
            ),
        ]
        pesticide = Pesticide(
            id=1, common_name="阿维菌素", active_ingredient="阿维菌素",
            formulation="乳油", content="1.8%", frac_irac_code="6",
            phi_days=7, max_times_per_season=2, toxicity_level="低毒",
            is_banned=False, registered_crops=["柑橘"],
        )
        output = filter_pesticides(
            disease="red_spider_mite",
            orchard=self.orchard,
            spray_history=self.spray_history,
            today=self.today,
            candidate_pesticides=[pesticide],
        )
        self.assertEqual(len(output.allowed), 0)
        self.assertIn("本季已使用 2 次", output.rejected[0].reason)
        self.assertIn("最多使用 2 次", output.rejected[0].reason)

    # ============================================================
    # 规则 d) 物候期禁忌
    # ============================================================
    def test_phenophase_pass(self):
        """正例：非敏感物候期，通过。"""
        pesticide = Pesticide(
            id=16, common_name="氢氧化铜", active_ingredient="氢氧化铜",
            formulation="可湿性粉剂", content="77%", frac_irac_code=None,
            phi_days=14, max_times_per_season=3, toxicity_level="低毒",
            is_banned=False, registered_crops=["柑橘"],
        )
        # 当前物候期是"膨大期"，非花期/幼果期，应通过
        output = filter_pesticides(
            disease="canker",
            orchard=self.orchard,
            spray_history=self.spray_history,
            today=self.today,
            candidate_pesticides=[pesticide],
            contraindications=[
                PhenophaseContraindication(pesticide_id=16, phenophase="幼果期", reason="铜制剂易产生锈斑药害"),
            ],
        )
        self.assertEqual(len(output.allowed), 1)

    def test_phenophase_reject(self):
        """反例：幼果期禁用铜制剂，拒绝。"""
        pesticide = Pesticide(
            id=16, common_name="氢氧化铜", active_ingredient="氢氧化铜",
            formulation="可湿性粉剂", content="77%", frac_irac_code=None,
            phi_days=14, max_times_per_season=3, toxicity_level="低毒",
            is_banned=False, registered_crops=["柑橘"],
        )
        # 当前物候期改为"幼果期"
        orchard = Orchard(
            block_name="测试地块", variety="琯溪蜜柚", tree_age=8,
            current_phenophase="幼果期",
            expected_harvest_date=date(2026, 11, 15), area_mu=5.0,
        )
        output = filter_pesticides(
            disease="canker",
            orchard=orchard,
            spray_history=self.spray_history,
            today=self.today,
            candidate_pesticides=[pesticide],
            contraindications=[
                PhenophaseContraindication(pesticide_id=16, phenophase="幼果期", reason="铜制剂易产生锈斑药害"),
            ],
        )
        self.assertEqual(len(output.allowed), 0)
        self.assertIn("幼果期", output.rejected[0].reason)
        self.assertIn("铜制剂易产生锈斑药害", output.rejected[0].reason)

    # ============================================================
    # 规则 e) 复配禁忌
    # ============================================================
    def test_conflict_pass(self):
        """正例：近期无配伍禁忌药剂，通过。"""
        pesticide = Pesticide(
            id=9, common_name="咪鲜胺", active_ingredient="咪鲜胺",
            formulation="乳油", content="25%", frac_irac_code="3",
            phi_days=14, max_times_per_season=2, toxicity_level="低毒",
            is_banned=False, registered_crops=["柑橘"],
        )
        # 近期施药是阿维菌素（IRAC 6），与咪鲜胺无配伍禁忌
        self.spray_history = [
            SprayRecord(
                orchard_id=1, spray_date=self.today - timedelta(days=7),
                pesticide_id=1, pesticide_name="阿维菌素", frac_irac_code="6",
                dilution_ratio="3000 倍液",
            )
        ]
        output = filter_pesticides(
            disease="anthracnose",
            orchard=self.orchard,
            spray_history=self.spray_history,
            today=self.today,
            candidate_pesticides=[pesticide],
            conflicts=[
                PesticideConflict(pesticide_a_id=16, pesticide_b_id=9, conflict_type="药效降低",
                                 description="铜制剂与咪鲜胺混用可能降低药效", severity="中等"),
            ],
        )
        self.assertEqual(len(output.allowed), 1)

    def test_conflict_reject(self):
        """反例：近期用过铜制剂，与候选药剂有配伍禁忌，拒绝。"""
        pesticide = Pesticide(
            id=9, common_name="咪鲜胺", active_ingredient="咪鲜胺",
            formulation="乳油", content="25%", frac_irac_code="3",
            phi_days=14, max_times_per_season=2, toxicity_level="低毒",
            is_banned=False, registered_crops=["柑橘"],
        )
        # 近期施药是氢氧化铜（ID 16），与咪鲜胺有配伍禁忌
        self.spray_history = [
            SprayRecord(
                orchard_id=1, spray_date=self.today - timedelta(days=7),
                pesticide_id=16, pesticide_name="氢氧化铜", frac_irac_code=None,
                dilution_ratio="500 倍液",
            )
        ]
        output = filter_pesticides(
            disease="anthracnose",
            orchard=self.orchard,
            spray_history=self.spray_history,
            today=self.today,
            candidate_pesticides=[pesticide],
            conflicts=[
                PesticideConflict(pesticide_a_id=16, pesticide_b_id=9, conflict_type="药效降低",
                                 description="铜制剂与咪鲜胺混用可能降低药效", severity="中等"),
            ],
        )
        self.assertEqual(len(output.allowed), 0)
        self.assertIn("药效降低", output.rejected[0].reason)
        self.assertIn("铜制剂与咪鲜胺混用", output.rejected[0].reason)

    # ============================================================
    # 综合测试：DEMO 场景
    # ============================================================
    def test_demo_scenario(self):
        """DEMO：同一块地（预计 15 天后采收、7 天前打过阿维菌素）识别为红蜘蛛。

        期望：
        - 阿维菌素：距采收 15 天，PHI 7 天，通过（但与上次同组，应拒绝）
        - 螺螨酯：距采收 15 天，PHI 14 天，通过（不同组）
        - 某长效药剂：距采收 15 天，PHI 30 天，拒绝（安全间隔期）
        """
        orchard = Orchard(
            block_name="A 区 1 号", variety="琯溪蜜柚", tree_age=8,
            current_phenophase="膨大期",
            expected_harvest_date=self.today + timedelta(days=15),
            area_mu=5.0,
        )
        spray_history = [
            SprayRecord(
                orchard_id=1, spray_date=self.today - timedelta(days=7),
                pesticide_id=1, pesticide_name="阿维菌素", frac_irac_code="6",
                dilution_ratio="3000 倍液",
            )
        ]
        candidates = [
            Pesticide(id=1, common_name="阿维菌素", active_ingredient="阿维菌素",
                     formulation="乳油", content="1.8%", frac_irac_code="6",
                     phi_days=7, max_times_per_season=2, toxicity_level="低毒",
                     is_banned=False, registered_crops=["柑橘"]),
            Pesticide(id=2, common_name="螺螨酯", active_ingredient="螺螨酯",
                     formulation="悬浮剂", content="240g/L", frac_irac_code="20B",
                     phi_days=14, max_times_per_season=2, toxicity_level="低毒",
                     is_banned=False, registered_crops=["柑橘"]),
            Pesticide(id=3, common_name="某长效药剂", active_ingredient="某成分",
                     formulation="悬浮剂", content="10%", frac_irac_code="20B",
                     phi_days=30, max_times_per_season=2, toxicity_level="低毒",
                     is_banned=False, registered_crops=["柑橘"]),
        ]
        output = filter_pesticides(
            disease="red_spider_mite",
            orchard=orchard,
            spray_history=spray_history,
            today=self.today,
            candidate_pesticides=candidates,
        )
        # 阿维菌素：与上次同组，拒绝
        self.assertEqual(len(output.allowed), 1)
        self.assertEqual(output.allowed[0].common_name, "螺螨酯")
        self.assertEqual(len(output.rejected), 2)
        rejected_names = {r.name for r in output.rejected}
        self.assertIn("阿维菌素", rejected_names)
        self.assertIn("某长效药剂", rejected_names)


class TestGuardrail(unittest.TestCase):
    """护栏测试。"""

    def test_valid_output(self):
        """正例：所有药名都在白名单内。"""
        text = "建议使用阿维菌素或螺螨酯防治红蜘蛛，稀释倍数 3000 倍液。"
        result = validate_output(text, ["阿维菌素", "螺螨酯", "螺螨酯", "矿物油"])
        self.assertTrue(result["is_valid"])
        self.assertEqual(len(result["violations"]), 0)

    def test_hallucinated_pesticide(self):
        """反例：检测到白名单外的药名，拦截。"""
        text = "建议使用阿维菌素或某未知神药防治红蜘蛛，稀释倍数 3000 倍液。"
        result = validate_output(text, ["阿维菌素", "螺螨酯", "矿物油"])
        self.assertFalse(result["is_valid"])
        # "未知神药" 含"药"字，被判定为疑似药名（"某"被拆分）
        self.assertIn("未知神药", result["violations"])
        self.assertIn("请咨询当地农技人员", result["suggested_text"])
        self.assertNotIn("未知神药", result["suggested_text"])

    def test_multiple_hallucinations(self):
        """反例：多个白名单外的药名，全部拦截。"""
        text = "建议使用阿维菌素、某神药、另一个假药防治红蜘蛛。"
        result = validate_output(text, ["阿维菌素", "螺螨酯"])
        self.assertFalse(result["is_valid"])
        # "某神药" 和 "另一个假药" 都含"药"字，被判定为疑似药名
        self.assertIn("某神药", result["violations"])
        self.assertIn("另一个假药", result["violations"])
        self.assertIn("请咨询当地农技人员", result["suggested_text"])

    def test_english_pesticide_name(self):
        """英文药名检测。"""
        text = "建议使用 Abamectin 防治红蜘蛛。"
        result = validate_output(text, ["阿维菌素", "螺螨酯"])
        # Abamectin 不在白名单内，应被拦截
        self.assertFalse(result["is_valid"])

    def test_no_pesticide_in_text(self):
        """文本中无药名，通过。"""
        text = "建议加强果园通风透光，及时清除行间杂草。"
        result = validate_output(text, ["阿维菌素", "螺螨酯"])
        self.assertTrue(result["is_valid"])
        self.assertEqual(len(result["detected"]), 0)


class TestFormatReports(unittest.TestCase):
    """报告格式化测试。"""

    def test_rejection_report(self):
        """拒绝报告格式化。"""
        from prescription.rule_engine import FilterResult, FilterOutput
        output = FilterOutput(
            allowed=[
                Pesticide(id=1, common_name="螺螨酯", active_ingredient="螺螨酯",
                         formulation="悬浮剂", content="240g/L", frac_irac_code="20B",
                         phi_days=14, max_times_per_season=2, toxicity_level="低毒",
                         is_banned=False, registered_crops=["柑橘"]),
            ],
            rejected=[
                FilterResult(pesticide_id=2, name="阿维菌素", reason="与上次施药同属第 6 组，存在抗药性风险"),
                FilterResult(pesticide_id=3, name="某长效药剂", reason="距采收仅 15 天，该药需间隔 30 天"),
            ],
        )
        report = format_rejection_report(output)
        self.assertIn("通过 1 种", report)
        self.assertIn("拒绝 2 种", report)
        self.assertIn("螺螨酯", report)
        self.assertIn("阿维菌素", report)
        self.assertIn("某长效药剂", report)

    def test_guardrail_report(self):
        """护栏报告格式化。"""
        result = {
            "is_valid": False,
            "detected": ["阿维菌素", "某神药"],
            "violations": ["某神药"],
            "suggested_text": "建议使用阿维菌素或请咨询当地农技人员防治红蜘蛛。",
        }
        report = format_guardrail_report(result)
        self.assertIn("拦截", report)
        self.assertIn("某神药", report)


if __name__ == "__main__":
    unittest.main()