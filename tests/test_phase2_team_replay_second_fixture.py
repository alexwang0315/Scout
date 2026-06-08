import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from phase2_brain_models import Mission, RemoteStatusArtifact, Route, Team
from phase2_brain_store import BrainFileStore
from phase2_team_replay_store import load_team_replay_nodes, persist_team_replay_to_brain_store


FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "phase2"
    / "team_replay"
    / "forest_traverse_two_person_team_replay.json"
)

RIDGE_LOOP_DEFAULT_IDS = {
    "mission.ridge_loop_20260513",
    "team.ridge_loop_alpha",
    "route.ridge_loop_north",
    "remote_status.ridge_loop_20260513T100800",
}


class Phase2SecondTeamReplayFixtureTests(unittest.TestCase):
    def test_second_fixture_loads_with_non_ridge_defaults(self):
        nodes = load_team_replay_nodes(FIXTURE_PATH)
        by_id = {node.id: node for node in nodes}

        self.assertFalse(RIDGE_LOOP_DEFAULT_IDS & set(by_id))

        mission = by_id["mission.forest_traverse_20260513"]
        team = by_id["team.forest_traverse_beta"]
        route = by_id["route.forest_traverse_south"]
        remote_status = by_id["remote_status.forest_traverse_20260513T082000"]

        self.assertIsInstance(mission, Mission)
        self.assertIsInstance(team, Team)
        self.assertIsInstance(route, Route)
        self.assertIsInstance(remote_status, RemoteStatusArtifact)
        self.assertEqual(mission.team_id, team.id)
        self.assertEqual(mission.route_id, route.id)
        self.assertEqual(route.route_type, "traverse")
        self.assertEqual(team.member_ids, ["person.leader_ivy", "person.member_noah"])
        self.assertEqual(remote_status.safety_level, "L1")
        self.assertEqual(remote_status.team_summary["members_total"], 2)
        self.assertEqual(remote_status.team_summary["possible_separation_member_ids"], [])
        self.assertEqual(remote_status.latest_checkpoint, "checkpoint.cedar_bridge")

    def test_second_fixture_persists_and_recovers_from_brain_store(self):
        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)
            result = persist_team_replay_to_brain_store(store, FIXTURE_PATH)

            self.assertEqual(result.fixture_path, FIXTURE_PATH)
            self.assertEqual(len(result.nodes), len(result.paths))
            self.assertEqual(len(result.nodes), len(store.list_nodes()))
            self.assertFalse(RIDGE_LOOP_DEFAULT_IDS & set(result.node_ids))

            recovered_mission = store.load_node("mission.forest_traverse_20260513")
            recovered_route = store.load_node("route.forest_traverse_south")
            recovered_remote = store.load_node("remote_status.forest_traverse_20260513T082000")

            self.assertIsInstance(recovered_mission, Mission)
            self.assertIsInstance(recovered_route, Route)
            self.assertIsInstance(recovered_remote, RemoteStatusArtifact)
            self.assertEqual(recovered_mission.name, "Synthetic forest traverse pair hike")
            self.assertEqual(recovered_route.source_artifact_refs, ["artifact.route_gpx.forest_traverse_20260513"])
            self.assertEqual(recovered_remote.artifact_refs, ["artifact.remote_status_json.forest_20260513T082000"])


if __name__ == "__main__":
    unittest.main()
