import unittest
from pathlib import Path

from mission_graph import load_mission_graph, MissionGraphRuntime


ROOT = Path(__file__).resolve().parents[1]
MISSION_PATH = ROOT / "tests" / "fixtures" / "mission_graph" / "normal_climb_mission.json"


class MissionGraphRuntimeTests(unittest.TestCase):
    def test_loads_graph_and_indexes_runtime_objects(self):
        runtime = MissionGraphRuntime(load_mission_graph(MISSION_PATH))

        first_segment = runtime.current_segment("seg_01")
        next_checkpoint = runtime.next_checkpoint("seg_01")
        policy = runtime.recording_policy(first_segment.recording_policy_id)
        zone = runtime.control_zone(first_segment.control_zone_id)

        self.assertEqual(first_segment.segment_id, "seg_01")
        self.assertEqual(next_checkpoint.checkpoint_id, first_segment.to_checkpoint_id)
        self.assertTrue(policy.checkpoint_seals_segment)
        self.assertEqual(zone.zone_id, first_segment.control_zone_id)

    def test_checkpoint_lookup_raises_for_unknown_id(self):
        runtime = MissionGraphRuntime(load_mission_graph(MISSION_PATH))

        with self.assertRaises(KeyError):
            runtime.checkpoint("missing")


if __name__ == "__main__":
    unittest.main()
