import unittest
from pathlib import Path

from checkpoint_manager import CheckpointManager
from mission_graph import MissionGraphRuntime, load_mission_graph
from safety_models import Observation


ROOT = Path(__file__).resolve().parents[1]
MISSION_PATH = ROOT / "tests" / "fixtures" / "mission_graph" / "normal_climb_mission.json"


class CheckpointManagerTests(unittest.TestCase):
    def test_detects_checkpoint_arrival(self):
        runtime = MissionGraphRuntime(load_mission_graph(MISSION_PATH))
        manager = CheckpointManager(runtime)
        checkpoint = runtime.checkpoint("cp_02")
        observation = Observation(
            timestamp=100.0,
            source="test",
            lat=checkpoint.lat,
            lon=checkpoint.lon,
            elevation_m=checkpoint.elevation_m,
        )

        event = manager.observe(observation)

        self.assertIsNotNone(event)
        self.assertEqual(event.checkpoint.checkpoint_id, "cp_02")
        self.assertEqual(manager.last_checkpoint_id, "cp_02")

    def test_seals_segment_when_next_checkpoint_arrives(self):
        runtime = MissionGraphRuntime(load_mission_graph(MISSION_PATH))
        manager = CheckpointManager(runtime)

        cp1 = runtime.checkpoint("cp_01")
        cp2 = runtime.checkpoint("cp_02")
        manager.observe(Observation(timestamp=10.0, source="test", lat=cp1.lat, lon=cp1.lon))
        event = manager.observe(Observation(timestamp=20.0, source="test", lat=cp2.lat, lon=cp2.lon))

        self.assertIsNotNone(event)
        self.assertIsNotNone(event.segment_capsule)
        self.assertEqual(event.segment_capsule.segment_id, "seg_01")
        self.assertEqual(event.segment_capsule.start_checkpoint_id, "cp_01")
        self.assertEqual(event.segment_capsule.end_checkpoint_id, "cp_02")

    def test_ignores_same_checkpoint_reentry(self):
        runtime = MissionGraphRuntime(load_mission_graph(MISSION_PATH))
        manager = CheckpointManager(runtime)
        cp1 = runtime.checkpoint("cp_01")

        first = manager.observe(Observation(timestamp=10.0, source="test", lat=cp1.lat, lon=cp1.lon))
        second = manager.observe(Observation(timestamp=11.0, source="test", lat=cp1.lat, lon=cp1.lon))

        self.assertIsNotNone(first)
        self.assertIsNone(second)


if __name__ == "__main__":
    unittest.main()
