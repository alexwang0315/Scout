import importlib
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from runtime_debug_log import FileRuntimeDebugEventLog
from runtime_debug_models import RuntimeDebugEvent


class DebugApiMountTests(unittest.TestCase):
    def _reload_server(self):
        import server

        return importlib.reload(server)

    def test_debug_api_is_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SCOUT_DEBUG_API_ENABLED", None)
            server = self._reload_server()
            self.addCleanup(self._reload_server)

            client = TestClient(server.app)

            self.assertEqual(client.get("/debug/state").status_code, 404)
            self.assertEqual(client.get("/admin/debug").status_code, 404)
            routes = {route.path for route in server.app.routes}
            self.assertNotIn("/debug/state", routes)
            self.assertNotIn("/admin/debug", routes)

    def test_debug_api_mounts_when_explicitly_enabled(self):
        with patch.dict(os.environ, {"SCOUT_DEBUG_API_ENABLED": "1"}, clear=False):
            server = self._reload_server()
            self.addCleanup(self._reload_server)

            client = TestClient(server.app)
            state = client.get("/debug/state")
            page = client.get("/admin/debug")

            self.assertEqual(state.status_code, 200)
            self.assertTrue(state.json()["debug_boundary"]["read_only"])
            self.assertEqual(page.status_code, 200)
            self.assertIn("Scout Phase 3.5 Runtime Debug", page.text)
            self.assertIn("/debug/state", {route.path for route in server.app.routes})
            self.assertIn("/admin/debug", {route.path for route in server.app.routes})
            self.assertEqual(client.post("/debug/events", json={}).status_code, 405)

    def test_debug_api_reads_file_backed_log_when_path_is_configured(self):
        with TemporaryDirectory() as tmpdir:
            debug_log_path = Path(tmpdir) / "runtime-debug-events.jsonl"
            FileRuntimeDebugEventLog(debug_log_path).append(
                RuntimeDebugEvent(
                    event_id="debug_event.mount.000001",
                    session_id="debug_session.mount",
                    mission_id="mission.normal_climb",
                    timestamp="2026-05-18T12:00:00Z",
                    sequence=1,
                    kind="debug_session_completed",
                    source="test",
                    phase="phase35",
                    summary="mounted debug log fixture",
                    payload={
                        "safety_level": "L2_CONCERN",
                        "observations_processed": 2,
                    },
                )
            )

            with patch.dict(
                os.environ,
                {
                    "SCOUT_DEBUG_API_ENABLED": "1",
                    "SCOUT_DEBUG_LOG_PATH": str(debug_log_path),
                },
                clear=False,
            ):
                server = self._reload_server()
                self.addCleanup(self._reload_server)

                client = TestClient(server.app)
                events = client.get("/debug/events")
                state = client.get("/debug/state")

        self.assertEqual(events.status_code, 200)
        self.assertEqual(events.json()["events"][0]["event_id"], "debug_event.mount.000001")
        self.assertEqual(state.status_code, 200)
        self.assertEqual(state.json()["safety_level"], "L2_CONCERN")
        self.assertEqual(state.json()["observations_processed"], 2)

    def test_existing_routes_remain_registered_when_debug_api_enabled(self):
        with patch.dict(os.environ, {"SCOUT_DEBUG_API_ENABLED": "true"}, clear=False):
            server = self._reload_server()
            self.addCleanup(self._reload_server)

            routes = {route.path for route in server.app.routes}

            self.assertIn("/admin", routes)
            self.assertIn("/safety/state", routes)
            self.assertIn("/pdr/update", routes)
            self.assertIn("/debug/messages", routes)


if __name__ == "__main__":
    unittest.main()
