import importlib
import os
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from phase2_brain_store import BrainFileStore
from phase2_team_replay_store import persist_team_replay_to_brain_store


class Phase2AdminApiMountTests(unittest.TestCase):
    def _reload_server(self):
        import server

        return importlib.reload(server)

    def test_phase2_admin_api_is_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SCOUT_PHASE2_ADMIN_API_ENABLED", None)
            os.environ.pop("SCOUT_PHASE2_BRAIN_STORE_ROOT", None)
            server = self._reload_server()
            self.addCleanup(self._reload_server)

            client = TestClient(server.app)
            response = client.get("/phase2/admin/preview")

            self.assertEqual(response.status_code, 404)
            routes = {route.path for route in server.app.routes}
            self.assertNotIn("/phase2/admin/preview", routes)

    def test_phase2_admin_api_mounts_when_enabled_with_fixture_brain_store_root(self):
        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)
            persist_team_replay_to_brain_store(store)

            with patch.dict(
                os.environ,
                {
                    "SCOUT_PHASE2_ADMIN_API_ENABLED": "true",
                    "SCOUT_PHASE2_BRAIN_STORE_ROOT": tmpdir,
                },
                clear=False,
            ):
                server = self._reload_server()
                self.addCleanup(self._reload_server)

                client = TestClient(server.app)
                response = client.get("/phase2/admin/preview")

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["mission_id"], "mission.ridge_loop_20260513")
            self.assertEqual(payload["remote_status"]["status"], "delayed_member_stale")
            self.assertIn("/phase2/admin/preview", {route.path for route in server.app.routes})

    def test_existing_phase1_admin_and_safety_routes_remain_registered(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SCOUT_PHASE2_ADMIN_API_ENABLED", None)
            os.environ.pop("SCOUT_PHASE2_BRAIN_STORE_ROOT", None)
            server = self._reload_server()
            self.addCleanup(self._reload_server)

            routes = {route.path for route in server.app.routes}

            self.assertIn("/admin", routes)
            self.assertIn("/admin/cases/{case_id}", routes)
            self.assertIn("/safety/observations", routes)
            self.assertIn("/safety/state", routes)
            self.assertIn("/pdr/update", routes)
            self.assertIn("/status", routes)

    def test_pretrip_workspace_root_env_enables_workspace_edit_routes(self):
        with TemporaryDirectory() as tmpdir:
            with patch.dict(
                os.environ,
                {"SCOUT_PRETRIP_WORKSPACE_ROOT": tmpdir},
                clear=False,
            ):
                server = self._reload_server()
                self.addCleanup(self._reload_server)

                client = TestClient(server.app)
                workspace_response = client.post(
                    "/admin/pretrip/projects/chilai_nanhua_day1/workspace"
                )
                edit_response = client.post(
                    "/admin/pretrip/projects/chilai_nanhua_day1/workspace-edits",
                    json={
                        "operation": "add_checkpoint",
                        "summary": "Server env workspace edit smoke.",
                        "candidate": {
                            "candidate_id": "manual.cp.server_env_smoke",
                            "label": "Server env smoke",
                            "lat": 24.05,
                            "lon": 121.22,
                            "checkpoint_type": "waypoint",
                            "review_state": "needs_human_review",
                        },
                    },
                )

            self.assertEqual(workspace_response.status_code, 200)
            self.assertEqual(edit_response.status_code, 200)
            payload = edit_response.json()
            self.assertTrue(payload["mutation"]["workspace_candidate_artifacts_mutated"])
            self.assertFalse(payload["boundary"]["phase1_runtime_mutation_allowed"])


if __name__ == "__main__":
    unittest.main()
