import unittest
from tempfile import TemporaryDirectory

from fastapi import FastAPI
from fastapi.testclient import TestClient

from phase2_admin_api import create_phase2_admin_app, create_phase2_admin_router
from phase2_brain_store import BrainFileStore
from phase2_case_replay_integration import DEFAULT_OPTION_SET_REF, DEFAULT_REMOTE_STATUS_REF
from phase2_team_replay_store import persist_team_replay_to_brain_store


class Phase2AdminApiTests(unittest.TestCase):
    def test_preview_endpoint_returns_read_only_phase2_payload_from_store_root(self):
        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)
            persist_team_replay_to_brain_store(store)
            before_node_ids = [node.id for node in store.list_nodes()]

            client = TestClient(create_phase2_admin_app(brain_store_root=tmpdir))
            response = client.get("/phase2/admin/preview")

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["mission_id"], "mission.ridge_loop_20260513")
            self.assertEqual(payload["remote_status"]["id"], DEFAULT_REMOTE_STATUS_REF)
            self.assertEqual(payload["remote_status"]["status"], "delayed_member_stale")
            self.assertIn(DEFAULT_OPTION_SET_REF, payload["option_set_ids"])
            self.assertEqual(payload["option_sets"][0]["current_safety_level"], "L2")
            self.assertEqual(
                payload["option_sets"][0]["option_count"],
                len(payload["option_sets"][0]["option_ids"]),
            )
            self.assertGreaterEqual(payload["option_sets"][0]["option_count"], 2)
            self.assertEqual(
                set(payload["skill_run_audit_ids"]),
                {
                    "skill_run.team_checkin_summary.20260513T100800",
                    "skill_run.decision_options.20260513T101500",
                },
            )
            self.assertEqual(payload["case_verdict_level"], "decision_window_created")
            self.assertIn("artifact.remote_status_json.20260513T100800", payload["artifact_refs"])
            evidence_refs = {ref["ref"]: ref for ref in payload["evidence_refs"]}
            self.assertEqual(
                evidence_refs[DEFAULT_REMOTE_STATUS_REF]["node_type"],
                "RemoteStatusArtifact",
            )
            self.assertTrue(evidence_refs[DEFAULT_REMOTE_STATUS_REF]["resolved"])
            self.assertIn(
                "preview.remote_status",
                evidence_refs[DEFAULT_REMOTE_STATUS_REF]["source_ids"],
            )
            self.assertEqual(
                evidence_refs[DEFAULT_OPTION_SET_REF]["node_type"],
                "DecisionOptionSet",
            )
            artifact_previews = {artifact["id"]: artifact for artifact in payload["artifact_previews"]}
            self.assertIn("artifact.remote_status_json.20260513T100800", artifact_previews)
            artifact_preview = artifact_previews["artifact.remote_status_json.20260513T100800"]
            self.assertEqual(artifact_preview["artifact_kind"], "remote_status_json")
            self.assertEqual(
                artifact_preview["uri"],
                "fixtures/phase2/team_replay/artifacts/remote_status_20260513T100800.json",
            )
            self.assertEqual(artifact_preview["media_type"], "application/json")
            self.assertEqual(artifact_preview["captured_at"], "2026-05-13T10:08:00+08:00")
            self.assertTrue(
                {"redacted_raw_telemetry", "synthetic"}.issubset(
                    artifact_preview["metadata_keys"]
                )
            )
            self.assertTrue(
                {
                    DEFAULT_REMOTE_STATUS_REF,
                    "case.timeline.T-120",
                    "case.timeline.T-60",
                    "case.timeline.T-30",
                    "case.timeline.T-0",
                    "post.ridge_loop.persisted_brain_refs",
                }.issubset(artifact_preview["source_ids"])
            )
            self.assertTrue(payload["safety_guardrails"])
            self.assertTrue(
                all("guaranteed" not in note.lower() for note in payload["safety_guardrails"])
            )
            self.assertTrue(
                all("assured" not in note.lower() for note in payload["safety_guardrails"])
            )
            self.assertEqual({node.id for node in store.list_nodes()}, set(before_node_ids))

    def test_preview_router_can_be_tested_directly(self):
        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)
            persist_team_replay_to_brain_store(store)

            app = FastAPI()
            app.include_router(create_phase2_admin_router(brain_store_root=tmpdir))
            client = TestClient(app)
            response = client.get("/phase2/admin/preview")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["mission_id"], "mission.ridge_loop_20260513")

    def test_preview_endpoint_fails_cleanly_for_missing_brain_ref(self):
        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)
            persist_team_replay_to_brain_store(store)
            remote_status = store.load_node(DEFAULT_REMOTE_STATUS_REF)
            store.path_for_node(remote_status).unlink()
            store.index_path.unlink()

            client = TestClient(create_phase2_admin_app(brain_store_root=tmpdir))
            response = client.get("/phase2/admin/preview")

            self.assertEqual(response.status_code, 404)
            self.assertEqual(
                response.json(),
                {
                    "detail": f"required Brain ref is missing: {DEFAULT_REMOTE_STATUS_REF}",
                },
            )


if __name__ == "__main__":
    unittest.main()
