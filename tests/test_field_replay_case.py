import argparse
import unittest
from pathlib import Path

from phase1_replay_demo import run_phase1_replay_demo
from replay_runner import replay_route
from route_progress import load_route_progress_config


ROOT = Path(__file__).resolve().parents[1]
FIELD_MISSION = ROOT / "tests" / "fixtures" / "mission_graph" / "scout_260512_field_mission.json"
FIELD_ROUTE = ROOT / "tests" / "fixtures" / "routes" / "scout_260512_field_route.gpx"
FIELD_MAP = ROOT / "tests" / "fixtures" / "maps" / "scout_260512_overpass_map_context.geojson"
FIELD_RULES = ROOT / "tests" / "fixtures" / "risk_rules" / "scout_260512_field_rules.json"
FIELD_CONTEXT = ROOT / "tests" / "fixtures" / "mission_context" / "scout_260512_field_normal.json"
FIELD_CONFIG = ROOT / "tests" / "fixtures" / "route_progress" / "scout_260512_field_config.json"


class FieldReplayCaseTests(unittest.TestCase):
    def test_field_replay_uses_real_map_evidence_without_false_l2(self):
        result = replay_route(
            FIELD_MISSION,
            FIELD_ROUTE,
            map_context_path=FIELD_MAP,
            risk_rules_path=FIELD_RULES,
            mission_context_path=FIELD_CONTEXT,
            route_progress_config_path=FIELD_CONFIG,
        )

        self.assertEqual(result.observations_processed, 1568)
        self.assertEqual(
            [update.checkpoint.checkpoint_id for update in result.progress_updates if update.checkpoint],
            [f"cp_{index:02d}" for index in range(1, 11)],
        )
        self.assertEqual(
            [capsule.segment_id for capsule in result.segment_capsules],
            [f"seg_{index:02d}" for index in range(1, 10)],
        )
        self.assertEqual(result.safety_events, [])
        self.assertEqual(result.safety_state.level, "L0_NORMAL")
        self.assertEqual(result.incident_packages, [])
        self.assertIn("high", {decision.profile for decision in result.recording_decisions})

    def test_field_route_progress_config_loads_as_fixture_contract(self):
        config = load_route_progress_config(FIELD_CONFIG)

        self.assertEqual(config.min_route_deviation_duration_s, 30.0)
        self.assertEqual(config.min_loop_duration_s, 240.0)
        self.assertEqual(config.min_backtrack_distance_m, 45.0)

    def test_phase1_demo_accepts_field_route_progress_config(self):
        summary = run_phase1_replay_demo(
            argparse.Namespace(
                mission=FIELD_MISSION,
                route=FIELD_ROUTE,
                map_context=FIELD_MAP,
                risk_rules=FIELD_RULES,
                mission_context=FIELD_CONTEXT,
                route_progress_config=FIELD_CONFIG,
                incident_store=None,
            )
        )

        self.assertEqual(summary["observations_processed"], 1568)
        self.assertEqual(summary["safety_level"], "L0_NORMAL")
        self.assertEqual(summary["safety_events"], [])
        self.assertEqual(summary["checkpoint_count"], 10)
        self.assertEqual(summary["segment_capsule_count"], 9)


if __name__ == "__main__":
    unittest.main()
