import unittest
from pathlib import Path

from risk_rules import RiskRuleEvaluator, RiskRuleInput, load_risk_rules
from safety_models import SafetyLevel


ROOT = Path(__file__).resolve().parents[1]
RULES_PATH = ROOT / "tests" / "fixtures" / "risk_rules" / "normal_climb_rules.json"


class RiskRuleEvaluatorTests(unittest.TestCase):
    def test_composite_hazard_requires_all_factors_and_duration(self):
        evaluator = RiskRuleEvaluator(load_risk_rules(RULES_PATH))

        early = evaluator.evaluate(
            RiskRuleInput(
                hazard_types=["dense_bamboo", "cliff_exposure"],
                duration_s=29.0,
                map_confidence=0.8,
            )
        )
        sustained = evaluator.evaluate(
            RiskRuleInput(
                hazard_types=["dense_bamboo", "cliff_exposure"],
                duration_s=30.0,
                map_confidence=0.8,
            )
        )

        self.assertIsNone(early)
        self.assertIsNotNone(sustained)
        self.assertEqual(sustained.rule_id, "dense_bamboo_cliff_l2")
        self.assertEqual(sustained.level, SafetyLevel.CONCERN)

    def test_composite_hazard_does_not_match_single_factor(self):
        evaluator = RiskRuleEvaluator(load_risk_rules(RULES_PATH))

        decision = evaluator.evaluate(
            RiskRuleInput(
                hazard_types=["dense_bamboo"],
                duration_s=30.0,
                map_confidence=0.8,
            )
        )

        self.assertEqual(decision.level, SafetyLevel.WATCH)
        self.assertEqual(decision.rule_id, "low_confidence_hazard_watch")

    def test_low_map_confidence_prevents_l2_rule(self):
        evaluator = RiskRuleEvaluator(load_risk_rules(RULES_PATH))

        decision = evaluator.evaluate(
            RiskRuleInput(
                hazard_types=["dense_bamboo", "cliff_exposure"],
                duration_s=30.0,
                map_confidence=0.4,
            )
        )

        self.assertIsNotNone(decision)
        self.assertEqual(decision.level, SafetyLevel.WATCH)

    def test_weak_gps_requirement_is_enforced(self):
        evaluator = RiskRuleEvaluator(load_risk_rules(RULES_PATH))

        without_weak_gps = evaluator.evaluate(
            RiskRuleInput(
                hazard_types=["steep_slope"],
                duration_s=30.0,
                map_confidence=0.8,
                weak_gps=False,
            )
        )
        with_weak_gps = evaluator.evaluate(
            RiskRuleInput(
                hazard_types=["steep_slope"],
                duration_s=30.0,
                map_confidence=0.8,
                weak_gps=True,
            )
        )

        self.assertEqual(without_weak_gps.level, SafetyLevel.WATCH)
        self.assertEqual(with_weak_gps.rule_id, "steep_slope_weak_gps_l2")
        self.assertEqual(with_weak_gps.level, SafetyLevel.CONCERN)


if __name__ == "__main__":
    unittest.main()
