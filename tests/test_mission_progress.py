import unittest
from pathlib import Path

from mission_graph import MissionGraphRuntime, load_mission_graph
from mission_progress import MissionProgressTracker
from safety_models import Observation


ROOT = Path(__file__).resolve().parents[1]
MISSION_PATH = ROOT / "tests" / "fixtures" / "mission_graph" / "normal_climb_mission.json"


class MissionProgressTrackerTests(unittest.TestCase):
    def test_advances_only_when_expected_checkpoint_arrives(self):
        runtime = MissionGraphRuntime(load_mission_graph(MISSION_PATH))
        tracker = MissionProgressTracker(runtime)
        cp1 = runtime.checkpoint("cp_01")
        cp2 = runtime.checkpoint("cp_02")

        first = tracker.observe(Observation(timestamp=10.0, source="test", lat=cp1.lat, lon=cp1.lon))
        second = tracker.observe(Observation(timestamp=20.0, source="test", lat=cp2.lat, lon=cp2.lon))

        self.assertIsNotNone(first)
        self.assertEqual(first.checkpoint.checkpoint_id, "cp_01")
        self.assertIsNotNone(second)
        self.assertEqual(second.checkpoint.checkpoint_id, "cp_02")
        self.assertIsNotNone(second.segment_capsule)
        self.assertEqual(second.segment_capsule.segment_id, "seg_01")
        self.assertEqual(tracker.current_checkpoint_id, "cp_02")
        self.assertEqual(tracker.expected_checkpoint_id, "cp_03")

    def test_future_checkpoint_before_expected_does_not_emit_safety_event(self):
        runtime = MissionGraphRuntime(load_mission_graph(MISSION_PATH))
        tracker = MissionProgressTracker(runtime)
        cp1 = runtime.checkpoint("cp_01")
        cp3 = runtime.checkpoint("cp_03")

        tracker.observe(Observation(timestamp=10.0, source="test", lat=cp1.lat, lon=cp1.lon))
        event_update = tracker.observe(Observation(timestamp=30.0, source="test", lat=cp3.lat, lon=cp3.lon))

        self.assertIsNone(event_update)
        self.assertEqual(tracker.current_checkpoint_id, "cp_01")

    def test_prior_checkpoint_revisit_does_not_emit_backtracking_event(self):
        runtime = MissionGraphRuntime(load_mission_graph(MISSION_PATH))
        tracker = MissionProgressTracker(runtime)
        cp1 = runtime.checkpoint("cp_01")
        cp2 = runtime.checkpoint("cp_02")

        tracker.observe(Observation(timestamp=10.0, source="test", lat=cp1.lat, lon=cp1.lon))
        tracker.observe(Observation(timestamp=20.0, source="test", lat=cp2.lat, lon=cp2.lon))
        event_update = tracker.observe(Observation(timestamp=30.0, source="test", lat=cp1.lat, lon=cp1.lon))

        self.assertIsNone(event_update)
        self.assertEqual(tracker.current_checkpoint_id, "cp_02")


if __name__ == "__main__":
    unittest.main()
