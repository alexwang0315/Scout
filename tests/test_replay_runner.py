import unittest
from pathlib import Path

from replay_runner import replay_route
from safety_models import SafetyEventType


ROOT = Path(__file__).resolve().parents[1]
MISSION_PATH = ROOT / "tests" / "fixtures" / "mission_graph" / "normal_climb_mission.json"
ROUTE_PATH = ROOT / "tests" / "fixtures" / "routes" / "normal_climb.gpx"
OFF_ROUTE_PATH = ROOT / "tests" / "fixtures" / "routes" / "off_route_deviation.gpx"
BACKTRACKING_PATH = ROOT / "tests" / "fixtures" / "routes" / "backtracking_loop.gpx"
WEAK_GPS_PATH = ROOT / "tests" / "fixtures" / "routes" / "weak_gps_route.gpx"


class ReplayRunnerTests(unittest.TestCase):
    def test_replay_route_hits_checkpoints_and_seals_capsules(self):
        result = replay_route(MISSION_PATH, ROUTE_PATH)

        self.assertEqual(result.observations_processed, 3812)
        self.assertGreaterEqual(len(result.checkpoint_hits), 2)
        self.assertGreaterEqual(len(result.segment_capsules), 1)
        self.assertEqual(result.checkpoint_hits[0].checkpoint.checkpoint_id, "cp_01")
        progressed_checkpoints = [
            update.checkpoint.checkpoint_id for update in result.progress_updates if update.checkpoint is not None
        ]
        self.assertEqual(progressed_checkpoints[:3], ["cp_01", "cp_02", "cp_03"])
        self.assertEqual([capsule.segment_id for capsule in result.segment_capsules[:2]], ["seg_01", "seg_02"])
        self.assertEqual(result.safety_events, [])
        self.assertEqual(result.safety_state.level, "L0_NORMAL")
        self.assertEqual(result.incident_packages, [])

    def test_off_route_fixture_triggers_l2_incident(self):
        result = replay_route(MISSION_PATH, OFF_ROUTE_PATH)

        event_types = [event.event_type for event in result.safety_events]
        self.assertIn(SafetyEventType.ROUTE_DEVIATION, event_types)
        route_event = next(event for event in result.safety_events if event.event_type == SafetyEventType.ROUTE_DEVIATION)
        self.assertEqual(route_event.details["evidence_source"], "offline_map_corridor")
        self.assertEqual(route_event.details["corridor_id"], "corridor_normal_climb")
        self.assertEqual(route_event.details["map_source_metadata"]["source"], "synthetic_fixture")
        trigger_sample = result.incident_packages[0].raw_samples[-1]
        self.assertEqual(trigger_sample["raw"]["map_evidence"]["hazards"][0]["hazard_id"], "hazard_off_route_slope")
        self.assertEqual(result.safety_state.level, "L2_CONCERN")
        self.assertEqual(len(result.incident_packages), 1)

    def test_backtracking_loop_fixture_triggers_l2_incident(self):
        result = replay_route(MISSION_PATH, BACKTRACKING_PATH)

        event_types = [event.event_type for event in result.safety_events]
        self.assertIn(SafetyEventType.BACKTRACKING_LOOP, event_types)
        self.assertEqual(result.safety_state.level, "L2_CONCERN")
        self.assertEqual(len(result.incident_packages), 1)

    def test_weak_gps_fixture_triggers_l2_incident(self):
        result = replay_route(MISSION_PATH, WEAK_GPS_PATH)

        event_types = [event.event_type for event in result.safety_events]
        self.assertIn(SafetyEventType.WEAK_GPS, event_types)
        weak_gps_event = next(event for event in result.safety_events if event.event_type == SafetyEventType.WEAK_GPS)
        self.assertEqual(weak_gps_event.details["estimate_source"], "pdr_fallback")
        self.assertGreater(weak_gps_event.details["pdr_delta_m"], 0.0)
        self.assertEqual(result.safety_state.level, "L2_CONCERN")
        self.assertEqual(len(result.incident_packages), 1)


if __name__ == "__main__":
    unittest.main()
