import hashlib
import json
import unittest
from tempfile import TemporaryDirectory

from phase2_artifact_manifest_store import (
    MANIFEST_ARTIFACT_ID,
    MANIFEST_ARTIFACT_URI,
    MANIFEST_METADATA_ROLE,
    persist_phase2_artifact_manifest,
)
from phase2_brain_models import Artifact, ArtifactKind
from phase2_brain_store import BrainFileStore
from phase2_team_replay_demo import run_phase2_team_replay_demo


class Phase2ArtifactManifestStoreTests(unittest.TestCase):
    def test_persists_compact_manifest_file_and_artifact_node(self):
        with TemporaryDirectory() as tmpdir:
            run_phase2_team_replay_demo(store_root=tmpdir)
            store = BrainFileStore(tmpdir)

            persisted = persist_phase2_artifact_manifest(store)

            content = persisted.artifact_file_path.read_text(encoding="utf-8")
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            payload = json.loads(content)
            loaded_artifact = store.load_node(MANIFEST_ARTIFACT_ID)

            self.assertEqual(persisted.artifact.uri, MANIFEST_ARTIFACT_URI)
            self.assertEqual(persisted.artifact.sha256, digest)
            self.assertEqual(payload, persisted.manifest.to_dict())
            self.assertNotIn("\n  ", content)
            self.assertTrue(content.endswith("\n"))
            self.assertIsInstance(loaded_artifact, Artifact)
            self.assertEqual(loaded_artifact.artifact_kind, ArtifactKind.OTHER)
            self.assertEqual(loaded_artifact.uri, MANIFEST_ARTIFACT_URI)
            self.assertEqual(loaded_artifact.sha256, digest)
            self.assertEqual(loaded_artifact.metadata["role"], MANIFEST_METADATA_ROLE)
            self.assertFalse(loaded_artifact.metadata["source_of_truth"])
            self.assertTrue(loaded_artifact.metadata["rebuildable"])

    def test_regenerates_same_manifest_after_deleting_index(self):
        with TemporaryDirectory() as tmpdir:
            run_phase2_team_replay_demo(store_root=tmpdir)
            store = BrainFileStore(tmpdir)
            first = persist_phase2_artifact_manifest(store)
            first_content = first.artifact_file_path.read_text(encoding="utf-8")

            store.index_path.unlink()
            regenerated = persist_phase2_artifact_manifest(store)
            regenerated_content = regenerated.artifact_file_path.read_text(encoding="utf-8")

            self.assertEqual(regenerated_content, first_content)
            self.assertEqual(regenerated.artifact.sha256, first.artifact.sha256)
            self.assertEqual(regenerated.artifact.uri, MANIFEST_ARTIFACT_URI)
            self.assertEqual(json.loads(regenerated_content), first.manifest.to_dict())

    def test_manifest_artifact_is_rebuildable_not_semantic_source_of_truth(self):
        with TemporaryDirectory() as tmpdir:
            run_phase2_team_replay_demo(store_root=tmpdir)
            store = BrainFileStore(tmpdir)

            before = persist_phase2_artifact_manifest(store)
            after = persist_phase2_artifact_manifest(store)
            artifact_ids = [artifact["id"] for artifact in after.manifest.artifacts]

            self.assertEqual(after.manifest.to_dict(), before.manifest.to_dict())
            self.assertNotIn(MANIFEST_ARTIFACT_ID, artifact_ids)
            self.assertEqual(after.artifact.metadata["source_of_truth"], False)


if __name__ == "__main__":
    unittest.main()
