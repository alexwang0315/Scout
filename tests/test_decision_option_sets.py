import unittest
from pathlib import Path

from decision_options import (
    OptionGenerationBlockedError,
    build_decision_option_set,
    generate_option_set_with_ln_gate,
    option_candidate,
)
from ln_constraints import LnConstraintContext, LnConstraintEvaluator
from phase2_brain_models import BrainNodeType, ConfidenceLevel


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "phase2" / "policies"


def load_policy(name: str) -> LnConstraintEvaluator:
    return LnConstraintEvaluator.from_file(FIXTURE_DIR / name)


def normal_options():
    return [
        option_candidate(
            id="option.rest_reassess",
            label="Rest and reassess",
            action="rest",
            estimated_time_minutes=20,
            resource_cost="low",
            daylight_risk="medium",
            communication_chance="medium",
            team_impact="Gives the team time to hydrate and compare observations.",
            reversibility="high",
            failure_modes=("weather may worsen", "arrival delay increases"),
            confidence=ConfidenceLevel.MEDIUM,
        ),
        option_candidate(
            id="option.return_to_cp2",
            label="Return to CP2",
            action="turn_back",
            estimated_time_minutes=35,
            resource_cost="medium",
            daylight_risk="low",
            communication_chance="high",
            team_impact="Keeps the team together on a known segment.",
            reversibility="medium",
            failure_modes=("extra fatigue",),
            confidence=ConfidenceLevel.HIGH,
        ),
    ]


def degraded_options():
    return [
        option_candidate(
            id="option.local_hold_position",
            label="Hold position locally",
            action="hold",
            estimated_time_minutes=15,
            resource_cost="low",
            daylight_risk="medium",
            communication_chance="low",
            team_impact="Avoids pushing the team into worse visibility.",
            reversibility="high",
            failure_modes=("status may not reach remote contact",),
            confidence=ConfidenceLevel.MEDIUM,
        )
    ]


def option_set_kwargs():
    return {
        "id": "options.retreat_or_wait.20260513T103000",
        "mission_id": "mission.hehuan_20260513",
        "generated_at": "2026-05-13T10:30:00+08:00",
        "current_safety_level": "L2",
        "pilot_in_command": "person.leader",
        "input_refs": ["measurement.delay.cp2"],
    }


class DecisionOptionSetTests(unittest.TestCase):
    def test_builds_deterministic_option_set_with_complete_option_fields(self):
        option_set = build_decision_option_set(
            **option_set_kwargs(),
            options=normal_options(),
        )

        self.assertEqual(option_set.type, BrainNodeType.DECISION_OPTION_SET)
        self.assertEqual([option.id for option in option_set.options], ["option.rest_reassess", "option.return_to_cp2"])
        self.assertEqual(option_set.options[0].resource_cost, "low")
        self.assertEqual(option_set.options[0].estimated_time_minutes, 20)
        self.assertEqual(option_set.options[0].daylight_risk, "medium")
        self.assertEqual(option_set.options[0].communication_chance, "medium")
        self.assertEqual(option_set.options[0].team_impact, "Gives the team time to hydrate and compare observations.")
        self.assertEqual(option_set.options[0].reversibility, "high")
        self.assertEqual(option_set.options[0].failure_modes, ["weather may worsen", "arrival delay increases"])
        self.assertEqual(option_set.options[0].confidence, ConfidenceLevel.MEDIUM)
        self.assertEqual(option_set.scout_preference["preferred_option_id"], "option.return_to_cp2")
        self.assertEqual(
            option_set.scout_preference["ranking"],
            ["option.return_to_cp2", "option.rest_reassess"],
        )

    def test_allow_gate_generates_normal_intrusive_option_set(self):
        context = LnConstraintContext(
            skill_id="retreat-decision-support",
            safety_level="L2",
            route_type="traverse",
            duration_class="same_day",
            activity="moving",
            weather="clear",
            team_state="nominal",
            evidence_refs=("measurement.delay.cp2", "fact.weather.rain_start"),
            previous_evidence_refs=("measurement.delay.cp2",),
        )

        option_set = generate_option_set_with_ln_gate(
            evaluator=load_policy("traverse.json"),
            context=context,
            options=normal_options(),
            degraded_options=degraded_options(),
            **option_set_kwargs(),
        )

        self.assertEqual([option.id for option in option_set.options], ["option.rest_reassess", "option.return_to_cp2"])
        self.assertEqual(option_set.scout_preference["generation_mode"], "normal")
        self.assertEqual(option_set.scout_preference["ln_gate"]["decision"], "allow")

    def test_degrade_gate_generates_degraded_option_set(self):
        context = LnConstraintContext(
            skill_id="retreat-decision-support",
            safety_level="L1",
            route_type="expedition",
            duration_class="multi_day",
            activity="moving",
            weather="severe",
            team_state="nominal",
            evidence_refs=("fact.weather.severe", "measurement.margin.low"),
        )

        option_set = generate_option_set_with_ln_gate(
            evaluator=load_policy("multi_day_expedition.json"),
            context=context,
            options=normal_options(),
            degraded_options=degraded_options(),
            **option_set_kwargs(),
        )

        self.assertEqual([option.id for option in option_set.options], ["option.local_hold_position"])
        self.assertEqual(option_set.scout_preference["generation_mode"], "degraded")
        self.assertEqual(option_set.scout_preference["ln_gate"]["decision"], "degrade")

    def test_disallow_gate_blocks_intrusive_option_generation(self):
        context = LnConstraintContext(
            skill_id="retreat-decision-support",
            safety_level="L1",
            route_type="loop",
            duration_class="same_day",
            activity="moving",
            weather="clear",
            team_state="nominal",
            evidence_refs=("measurement.delay.cp2",),
        )

        with self.assertRaises(OptionGenerationBlockedError) as raised:
            generate_option_set_with_ln_gate(
                evaluator=load_policy("same_day_loop.json"),
                context=context,
                options=normal_options(),
                **option_set_kwargs(),
            )

        self.assertEqual(raised.exception.gate_decision.decision, "disallow")

    def test_defer_gate_blocks_intrusive_option_generation(self):
        context = LnConstraintContext(
            skill_id="retreat-decision-support",
            safety_level="L2",
            route_type="loop",
            duration_class="same_day",
            activity="resting",
            weather="clear",
            team_state="nominal",
            evidence_refs=("measurement.delay.cp2",),
        )

        with self.assertRaises(OptionGenerationBlockedError) as raised:
            generate_option_set_with_ln_gate(
                evaluator=load_policy("same_day_loop.json"),
                context=context,
                options=normal_options(),
                **option_set_kwargs(),
            )

        self.assertEqual(raised.exception.gate_decision.decision, "defer")


if __name__ == "__main__":
    unittest.main()
