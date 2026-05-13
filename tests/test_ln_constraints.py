import unittest
from pathlib import Path

from ln_constraints import LnConstraintEvaluator, LnConstraintPolicyError


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "phase2" / "policies"


def load_policy(name: str) -> LnConstraintEvaluator:
    return LnConstraintEvaluator.from_file(FIXTURE_DIR / name)


class LnConstraintEvaluatorTests(unittest.TestCase):
    def test_l0_preflight_skill_is_allowed_without_registry(self):
        decision = load_policy("same_day_loop.json").evaluate(
            skill_id="device-capability-check",
            safety_level="L0",
            route_type="loop",
            duration_class="same_day",
            activity="moving",
            weather="clear",
            team_state="nominal",
            evidence_refs=["fact.device.leader_watch.capabilities"],
        )

        self.assertEqual(decision.decision, "allow")
        self.assertEqual(decision.policy_id, "policy.same_day_loop")
        self.assertEqual(decision.policy_version, "2026-05-13.1")
        self.assertEqual(decision.evidence_refs, ("fact.device.leader_watch.capabilities",))

    def test_same_skill_suppressed_on_loop_l1_but_allowed_on_traverse_l1(self):
        loop_decision = load_policy("same_day_loop.json").evaluate(
            skill_id="retreat-decision-support",
            safety_level="L1",
            route_type="loop",
            duration_class="same_day",
            activity="moving",
            weather="clear",
            team_state="nominal",
            evidence_refs=["measurement.delay.cp2"],
            previous_evidence_refs=[],
        )
        traverse_decision = load_policy("traverse.json").evaluate(
            skill_id="retreat-decision-support",
            safety_level="L1",
            route_type="traverse",
            duration_class="same_day",
            activity="moving",
            weather="clear",
            team_state="nominal",
            evidence_refs=["measurement.delay.cp2"],
            previous_evidence_refs=[],
        )

        self.assertEqual(loop_decision.decision, "disallow")
        self.assertIn("below required L2", loop_decision.reasons[0])
        self.assertEqual(traverse_decision.decision, "allow")
        self.assertEqual(traverse_decision.policy_id, "policy.traverse_same_day")

    def test_multi_day_expedition_degrades_retreat_support_in_severe_weather(self):
        decision = load_policy("multi_day_expedition.json").evaluate(
            skill_id="retreat-decision-support",
            safety_level="L1",
            route_type="expedition",
            duration_class="multi_day",
            activity="moving",
            weather="severe",
            team_state="nominal",
            evidence_refs=["fact.weather.severe", "measurement.margin.low"],
        )

        self.assertEqual(decision.decision, "degrade")
        self.assertEqual(decision.policy_id, "policy.multi_day_expedition")
        self.assertIn("severe weather", decision.reasons[0])

    def test_activity_can_defer_intrusive_support(self):
        decision = load_policy("same_day_loop.json").evaluate(
            skill_id="retreat-decision-support",
            safety_level="L2",
            route_type="loop",
            duration_class="same_day",
            activity="resting",
            weather="clear",
            team_state="nominal",
            evidence_refs=["measurement.delay.cp2"],
        )

        self.assertEqual(decision.decision, "defer")
        self.assertIn("resting", decision.reasons[0])

    def test_cooldown_suppresses_repeat_prompt_without_new_evidence(self):
        decision = load_policy("traverse.json").evaluate(
            skill_id="retreat-decision-support",
            safety_level="L2",
            route_type="traverse",
            duration_class="same_day",
            activity="moving",
            weather="clear",
            team_state="nominal",
            evidence_refs=["measurement.delay.cp2"],
            now_minutes=120,
            last_prompt_at_minutes=100,
            previous_evidence_refs=["measurement.delay.cp2"],
        )

        self.assertEqual(decision.decision, "defer")
        self.assertIn("new evidence", decision.reasons[0])

    def test_new_evidence_overrides_cooldown_for_retreat_prompt(self):
        decision = load_policy("traverse.json").evaluate(
            skill_id="retreat-decision-support",
            safety_level="L2",
            route_type="traverse",
            duration_class="same_day",
            activity="moving",
            weather="clear",
            team_state="nominal",
            evidence_refs=["measurement.delay.cp2", "fact.weather.rain_start"],
            now_minutes=120,
            last_prompt_at_minutes=100,
            previous_evidence_refs=["measurement.delay.cp2"],
        )

        self.assertEqual(decision.decision, "allow")

    def test_recently_acknowledged_prompt_is_suppressed_even_with_new_evidence(self):
        decision = load_policy("traverse.json").evaluate(
            skill_id="retreat-decision-support",
            safety_level="L2",
            route_type="traverse",
            duration_class="same_day",
            activity="moving",
            weather="clear",
            team_state="nominal",
            evidence_refs=["measurement.delay.cp2", "fact.weather.rain_start"],
            now_minutes=130,
            last_prompt_at_minutes=90,
            acknowledged_prompt_at_minutes=110,
            previous_evidence_refs=["measurement.delay.cp2"],
        )

        self.assertEqual(decision.decision, "defer")
        self.assertIn("acknowledged", decision.reasons[0])

    def test_require_new_evidence_suppresses_when_all_evidence_was_acknowledged(self):
        decision = load_policy("traverse.json").evaluate(
            skill_id="retreat-decision-support",
            safety_level="L2",
            route_type="traverse",
            duration_class="same_day",
            activity="moving",
            weather="clear",
            team_state="nominal",
            evidence_refs=["measurement.delay.cp2", "fact.weather.rain_start"],
            now_minutes=200,
            last_prompt_at_minutes=120,
            previous_evidence_refs=["measurement.delay.cp2"],
            acknowledged_evidence_refs=["fact.weather.rain_start"],
        )

        self.assertEqual(decision.decision, "defer")
        self.assertIn("new evidence", decision.reasons[0])

    def test_unknown_skill_is_disallowed_and_unknown_level_is_rejected(self):
        unknown_skill = load_policy("same_day_loop.json").evaluate(
            skill_id="unlisted-skill",
            safety_level="L0",
            route_type="loop",
            duration_class="same_day",
            activity="moving",
            weather="clear",
            team_state="nominal",
            evidence_refs=[],
        )

        self.assertEqual(unknown_skill.decision, "disallow")

        with self.assertRaises(LnConstraintPolicyError):
            load_policy("same_day_loop.json").evaluate(
                skill_id="device-capability-check",
                safety_level="LX",
                route_type="loop",
                duration_class="same_day",
                activity="moving",
                weather="clear",
                team_state="nominal",
                evidence_refs=[],
            )


if __name__ == "__main__":
    unittest.main()
