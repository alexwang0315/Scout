import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from phase2_brain_models import (
    Artifact,
    BrainNodeType,
    DecisionOptionSet,
    RemoteStatusArtifact,
    Route,
    SkillRunRecord,
    TeamSeparationEvent,
)
from phase2_brain_store import BrainFileStore, MissingArtifactReferenceError
from phase2_team_replay_store import (
    DEFAULT_TEAM_REPLAY_FIXTURE_PATH,
    load_team_replay_nodes,
    persist_team_replay_to_brain_store,
)


class Phase2TeamReplayStoreTests(unittest.TestCase):
    def test_fixture_nodes_validate_and_persist_to_brain_store(self):
        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)
            result = persist_team_replay_to_brain_store(store)

            self.assertEqual(result.fixture_path, DEFAULT_TEAM_REPLAY_FIXTURE_PATH)
            self.assertEqual(len(result.nodes), len(result.paths))
            self.assertEqual(len(result.nodes), len(store.list_nodes()))

            remote_status = store.load_node("remote_status.ridge_loop_20260513T100800")
            option_set = store.load_node("options.ridge_loop_hold_or_regroup.20260513T101520")
            separation = store.load_node("event.possible_separation.lin.20260513T101400")

            self.assertIsInstance(remote_status, RemoteStatusArtifact)
            self.assertIsInstance(option_set, DecisionOptionSet)
            self.assertIsInstance(separation, TeamSeparationEvent)
            self.assertEqual(remote_status.artifact_refs, ["artifact.remote_status_json.20260513T100800"])
            self.assertIn(remote_status.id, option_set.input_refs)
            self.assertIn(remote_status.id, separation.evidence_refs)

    def test_index_can_be_deleted_rebuilt_and_nodes_recovered_without_live_index(self):
        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)
            result = persist_team_replay_to_brain_store(store)
            store.index_path.unlink()

            recovered_route = store.load_node("route.ridge_loop_north")
            recovered_run = store.load_node("skill_run.decision_options.20260513T101500")

            self.assertIsInstance(recovered_route, Route)
            self.assertIsInstance(recovered_run, SkillRunRecord)
            self.assertFalse(store.index_path.exists())

            rebuilt = store.rebuild_index()

            self.assertEqual(set(rebuilt), set(result.node_ids))
            self.assertTrue(store.index_path.exists())
            self.assertEqual(
                store.load_node("signal.lin_to_maya_beacon.20260513T101900").type,
                BrainNodeType.SIGNAL_BEARING_MEASUREMENT,
            )

    def test_strict_refs_check_only_explicit_artifact_fields(self):
        nodes = load_team_replay_nodes()
        artifact_ids = {node.id for node in nodes if isinstance(node, Artifact)}
        route = next(node for node in nodes if isinstance(node, Route))
        separation = next(node for node in nodes if isinstance(node, TeamSeparationEvent))

        self.assertTrue(set(route.source_artifact_refs).issubset(artifact_ids))
        self.assertFalse(set(separation.evidence_refs).issubset(artifact_ids))

        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)
            persist_team_replay_to_brain_store(store, strict_artifact_refs=True)

            self.assertEqual(store.load_node(separation.id), separation)

    def test_loader_validates_only_artifact_classified_refs(self):
        with TemporaryDirectory() as tmpdir:
            fixture_path = Path(tmpdir) / "team_replay_mixed_refs.json"
            fixture_path.write_text(
                """{
  "nodes": [
    {
      "id": "artifact.route_gpx.loop_01",
      "type": "Artifact",
      "artifact_kind": "gpx",
      "uri": "artifacts/routes/loop_01.gpx"
    },
    {
      "id": "route.loop_01",
      "type": "Route",
      "name": "Loop 01",
      "source_artifact_refs": [
        "artifact.route_gpx.loop_01",
        "fact.route_source_note",
        "https://example.invalid/routes/loop_01.gpx"
      ]
    }
  ]
}
""",
                encoding="utf-8",
            )

            nodes = load_team_replay_nodes(fixture_path)

            self.assertEqual([node.id for node in nodes], ["artifact.route_gpx.loop_01", "route.loop_01"])

            payload = fixture_path.read_text(encoding="utf-8").replace(
                "artifact.route_gpx.loop_01",
                "artifact.route_gpx.missing",
                1,
            )
            missing_fixture_path = Path(tmpdir) / "team_replay_missing_artifact.json"
            missing_fixture_path.write_text(payload, encoding="utf-8")

            with self.assertRaisesRegex(MissingArtifactReferenceError, "artifact.route_gpx.loop_01"):
                load_team_replay_nodes(missing_fixture_path)


if __name__ == "__main__":
    unittest.main()
