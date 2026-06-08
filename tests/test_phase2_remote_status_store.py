import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from phase2_brain_models import Artifact, ArtifactKind, BrainNodeType
from phase2_brain_store import BrainFileStore
from remote_status import MemberStatus, generate_remote_status_artifact
from remote_status_store import persist_remote_status_artifact


class Phase2RemoteStatusStoreTests(unittest.TestCase):
    def test_persists_remote_status_brain_node_and_json_artifact(self):
        remote_status = generate_remote_status_artifact(
            mission_id="mission.hehuan_20260513",
            generated_at="2026-05-13T10:00:00+08:00",
            members=[
                MemberStatus(
                    member_id="person.leader",
                    display_name="Trip leader",
                    last_seen_at="2026-05-13T09:58:30+08:00",
                    latest_checkpoint="checkpoint.cp2",
                    next_checkpoint="checkpoint.cp3",
                ),
                MemberStatus(
                    member_id="person.member_02",
                    display_name="Member 02",
                    last_seen_at="2026-05-13T09:58:10+08:00",
                    latest_checkpoint="checkpoint.cp2",
                    next_checkpoint="checkpoint.cp3",
                ),
            ],
        )

        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)
            persisted = persist_remote_status_artifact(store, remote_status)

            loaded_status = store.load_node(remote_status.id)
            loaded_artifact = store.load_node("artifact.remote_status_json.20260513T100000")
            artifact_path = Path(tmpdir) / loaded_artifact.uri
            artifact_payload = json.loads(artifact_path.read_text(encoding="utf-8"))

            self.assertEqual(loaded_status.type, BrainNodeType.REMOTE_STATUS_ARTIFACT)
            self.assertEqual(loaded_status.artifact_refs, [loaded_artifact.id])
            self.assertEqual(persisted.remote_status_path, store.path_for_node(loaded_status))
            self.assertEqual(persisted.artifact_node_path, store.path_for_node(loaded_artifact))
            self.assertEqual(persisted.artifact_file_path, artifact_path)
            self.assertEqual(loaded_artifact.type, BrainNodeType.ARTIFACT)
            self.assertEqual(loaded_artifact.artifact_kind, ArtifactKind.REMOTE_STATUS_JSON)
            self.assertEqual(loaded_artifact.media_type, "application/json")
            self.assertEqual(loaded_artifact.captured_at, remote_status.generated_at)
            self.assertEqual(loaded_artifact.metadata["artifact_origin"], "generated")
            self.assertEqual(loaded_artifact.metadata["remote_status_ref"], remote_status.id)
            self.assertEqual(artifact_payload["id"], remote_status.id)
            self.assertEqual(artifact_payload["mission_id"], "mission.hehuan_20260513")
            self.assertEqual(artifact_payload["status"], "on_track")
            self.assertEqual(artifact_payload["safety_level"], "L0")
            self.assertEqual(artifact_payload["uncertainty"], "high")
            self.assertEqual(artifact_payload["team_summary"]["member_count"], 2)

    def test_artifact_json_is_compact_and_excludes_raw_telemetry(self):
        remote_status = generate_remote_status_artifact(
            mission_id="mission.hehuan_20260513",
            generated_at="2026-05-13T10:00:00+08:00",
            members=[
                MemberStatus(
                    member_id="person.member_03",
                    display_name="Member 03",
                    last_seen_at="2026-05-13T09:40:00+08:00",
                    latest_checkpoint="checkpoint.cp1",
                    next_checkpoint="checkpoint.cp2",
                ),
            ],
        )

        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)
            persisted = persist_remote_status_artifact(store, remote_status)
            raw_content = persisted.artifact_file_path.read_text(encoding="utf-8")
            payload = json.loads(raw_content)

            self.assertNotIn("\n  ", raw_content)
            self.assertTrue(raw_content.endswith("\n"))
            self.assertNotIn("lat", payload)
            self.assertNotIn("lon", payload)
            self.assertNotIn("raw_telemetry", payload)
            self.assertNotIn("last_seen_at", raw_content)
            self.assertEqual(payload["freshness_seconds"], 1200)
            self.assertEqual(payload["team_summary"]["freshness_state"], "stale")

    def test_preserves_existing_artifact_refs_when_linking_remote_status_artifact(self):
        remote_status = generate_remote_status_artifact(
            mission_id="mission.hehuan_20260513",
            generated_at="2026-05-13T10:00:00+08:00",
            members=[
                MemberStatus(
                    member_id="person.leader",
                    display_name="Trip leader",
                    last_seen_at="2026-05-13T09:58:00+08:00",
                ),
            ],
        ).model_copy(update={"artifact_refs": ["artifact.preexisting_context"]})

        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)
            store.write_node(
                Artifact(
                    id="artifact.preexisting_context",
                    artifact_kind=ArtifactKind.OTHER,
                    uri="artifacts/context/preexisting.json",
                )
            )

            persist_remote_status_artifact(store, remote_status)
            loaded_status = store.load_node(remote_status.id)

            self.assertEqual(
                loaded_status.artifact_refs,
                ["artifact.preexisting_context", "artifact.remote_status_json.20260513T100000"],
            )

    def test_does_not_duplicate_existing_remote_status_artifact_ref(self):
        remote_status = generate_remote_status_artifact(
            mission_id="mission.hehuan_20260513",
            generated_at="2026-05-13T10:00:00+08:00",
            members=[
                MemberStatus(
                    member_id="person.leader",
                    display_name="Trip leader",
                    last_seen_at="2026-05-13T09:58:00+08:00",
                ),
            ],
        ).model_copy(
            update={"artifact_refs": ["artifact.remote_status_json.20260513T100000"]}
        )

        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)
            persist_remote_status_artifact(store, remote_status)
            loaded_status = store.load_node(remote_status.id)

            self.assertEqual(
                loaded_status.artifact_refs,
                ["artifact.remote_status_json.20260513T100000"],
            )


if __name__ == "__main__":
    unittest.main()
