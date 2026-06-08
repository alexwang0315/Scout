import json
import unittest
from tempfile import TemporaryDirectory

from phase2_brain_models import ArtifactKind, BrainNodeType
from phase2_brain_store import BrainFileStore
from phase2_remote_status_replay import persist_team_replay_remote_status


class Phase2RemoteStatusReplayPersistenceTests(unittest.TestCase):
    def test_persists_team_replay_remote_status_into_brain(self):
        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)
            result = persist_team_replay_remote_status(store)

            loaded_status = store.load_node(result.remote_status.id)
            loaded_artifact = store.load_node(result.persisted.artifact.id)

            self.assertEqual(loaded_status.type, BrainNodeType.REMOTE_STATUS_ARTIFACT)
            self.assertEqual(loaded_artifact.type, BrainNodeType.ARTIFACT)
            self.assertEqual(loaded_artifact.artifact_kind, ArtifactKind.REMOTE_STATUS_JSON)
            self.assertEqual(loaded_artifact.metadata["remote_status_ref"], result.remote_status.id)
            self.assertEqual(result.persisted.remote_status_path, store.path_for_node(loaded_status))
            self.assertEqual(result.persisted.artifact_node_path, store.path_for_node(loaded_artifact))
            self.assertTrue(result.persisted.artifact_file_path.exists())

    def test_persisted_json_artifact_is_compact_and_redacted(self):
        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)
            result = persist_team_replay_remote_status(store)

            raw_content = result.persisted.artifact_file_path.read_text(encoding="utf-8")
            payload = json.loads(raw_content)

            self.assertTrue(raw_content.endswith("\n"))
            self.assertNotIn("\n  ", raw_content)
            self.assertEqual(payload["id"], "remote_status.ridge_loop_20260513T100800")
            self.assertEqual(payload["mission_id"], "mission.ridge_loop_20260513")
            self.assertEqual(payload["status"], "delayed_member_stale")
            self.assertEqual(payload["safety_level"], "L2")
            self.assertNotIn("raw_telemetry", payload)
            self.assertNotIn("last_seen_at", raw_content)
            self.assertNotIn('"lat"', raw_content)
            self.assertNotIn('"lon"', raw_content)

    def test_fixture_artifact_refs_remain_consistent_after_persistence(self):
        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)
            result = persist_team_replay_remote_status(store)

            loaded_status = store.load_node(result.remote_status.id)
            seeded_artifact_ids = [artifact.id for artifact in result.seeded_artifacts]

            self.assertEqual(seeded_artifact_ids, ["artifact.remote_status_json.20260513T100800"])
            self.assertTrue(set(result.remote_status.artifact_refs).issubset(loaded_status.artifact_refs))
            self.assertIn(result.persisted.artifact.id, loaded_status.artifact_refs)
            for artifact_ref in loaded_status.artifact_refs:
                artifact = store.load_node(artifact_ref)
                self.assertEqual(artifact.type, BrainNodeType.ARTIFACT)

            self.assertEqual(
                result.persisted.artifact_file_path.relative_to(store.root).as_posix(),
                store.load_node(result.persisted.artifact.id).uri,
            )


if __name__ == "__main__":
    unittest.main()
