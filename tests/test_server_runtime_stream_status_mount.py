import importlib
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient


class ServerRuntimeStreamStatusMountTests(unittest.TestCase):
    def _reload_server(self):
        import server

        return importlib.reload(server)

    def test_runtime_stream_read_only_status_is_disabled_by_default(self):
        with patch.dict(
            os.environ,
            {
                "SCOUT_RUNTIME_STREAM_STATUS_ENABLED": "false",
                "SCOUT_SAFETY_OBSERVATION_ADMISSION_ENABLED": "false",
                "SCOUT_RUNTIME_STREAM_TRANSPORT_ENABLED": "false",
            },
            clear=False,
        ):
            server = self._reload_server()
            self.addCleanup(self._reload_server)

        route_paths = {route.path for route in server.app.routes}
        self.assertNotIn("/runtime/streams/status-read-only", route_paths)

    def test_runtime_stream_read_only_status_mount_is_get_only_and_no_transport(self):
        with patch.dict(
            os.environ,
            {
                "SCOUT_RUNTIME_STREAM_STATUS_ENABLED": "1",
                "SCOUT_SAFETY_ENABLED": "false",
                "SCOUT_SAFETY_OBSERVATION_ADMISSION_ENABLED": "false",
                "SCOUT_RUNTIME_STREAM_TRANSPORT_ENABLED": "false",
            },
            clear=False,
        ):
            server = self._reload_server()
            self.addCleanup(self._reload_server)
            client = TestClient(server.app)

            route_methods = {
                route.path: sorted(route.methods or [])
                for route in server.app.routes
                if route.path.startswith("/runtime/streams")
            }
            response = client.get("/runtime/streams/status-read-only")
            blocked_post = client.post("/runtime/streams/status-read-only", json={})

        self.assertEqual(
            route_methods,
            {"/runtime/streams/status-read-only": ["GET"]},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["artifact_kind"], "runtime_stream_status_surface")
        self.assertTrue(payload["boundary"]["read_only_surface"])
        self.assertFalse(payload["boundary"]["transport_routes_mounted"])
        self.assertFalse(payload["boundary"]["observation_ingest_allowed"])
        self.assertFalse(payload["boundary"]["stream_control_mutation_allowed"])
        self.assertFalse(payload["boundary"]["safety_mutation_allowed"])
        self.assertEqual(blocked_post.status_code, 405)

    def test_runtime_stream_read_only_status_mount_isolated_from_admission_startup_error(self):
        with patch.dict(
            os.environ,
            {
                "SCOUT_RUNTIME_STREAM_STATUS_ENABLED": "1",
                "SCOUT_SAFETY_ENABLED": "true",
                "SCOUT_SAFETY_OBSERVATION_ADMISSION_ENABLED": "1",
                "SCOUT_RUNTIME_STREAM_TRANSPORT_ENABLED": "1",
            },
            clear=False,
        ):
            os.environ.pop("SCOUT_SAFETY_OBSERVATION_ADMISSION_SECRET", None)
            os.environ.pop("SCOUT_SAFETY_OBSERVATION_ADMISSION_SECRET_FILE", None)
            server = self._reload_server()
            self.addCleanup(self._reload_server)
            client = TestClient(server.app)

            route_paths = {route.path for route in server.app.routes}
            response = client.get("/runtime/streams/status-read-only")

        self.assertIsNotNone(server.safety_observation_admission_config_error)
        self.assertIn("/runtime/streams/status-read-only", route_paths)
        self.assertNotIn("/runtime/streams/http-push/observations", route_paths)
        self.assertNotIn("/runtime/streams/websocket/observations", route_paths)
        self.assertNotIn("/runtime/streams/control/pause", route_paths)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["boundary"]["live_provider_send_allowed"])

    def test_runtime_stream_status_reports_transport_mount_when_guard_open(self):
        with patch.dict(
            os.environ,
            {
                "SCOUT_RUNTIME_STREAM_STATUS_ENABLED": "1",
                "SCOUT_SAFETY_ENABLED": "true",
                "SCOUT_SAFETY_OBSERVATION_ADMISSION_ENABLED": "1",
                "SCOUT_SAFETY_OBSERVATION_ADMISSION_SECRET": "0123456789abcdef",
                "SCOUT_RUNTIME_STREAM_TRANSPORT_ENABLED": "1",
            },
            clear=False,
        ):
            server = self._reload_server()
            self.addCleanup(self._reload_server)
            client = TestClient(server.app)

            route_paths = {route.path for route in server.app.routes}
            response = client.get("/runtime/streams/status-read-only")

        self.assertIn("/runtime/streams/http-push/observations", route_paths)
        self.assertIn("/runtime/streams/websocket/observations", route_paths)
        self.assertEqual(response.status_code, 200)
        boundary = response.json()["boundary"]
        self.assertTrue(boundary["transport_routes_mounted"])
        self.assertTrue(boundary["observation_ingest_allowed"])
        self.assertTrue(boundary["stream_control_mutation_allowed"])

    def test_runtime_stream_control_mutation_uses_operator_bearer_token(self):
        with patch.dict(
            os.environ,
            {
                "SCOUT_RUNTIME_STREAM_STATUS_ENABLED": "1",
                "SCOUT_SAFETY_ENABLED": "true",
                "SCOUT_SAFETY_OBSERVATION_ADMISSION_ENABLED": "1",
                "SCOUT_SAFETY_OBSERVATION_ADMISSION_SECRET": "0123456789abcdef",
                "SCOUT_RUNTIME_STREAM_TRANSPORT_ENABLED": "1",
                "SCOUT_RUNTIME_STREAM_CONTROL_TOKEN": "stream-control-token",
            },
            clear=False,
        ):
            server = self._reload_server()
            self.addCleanup(self._reload_server)
            client = TestClient(server.app)

            control_status = client.get("/runtime/streams/control/status")
            unauthorized = client.post(
                "/runtime/streams/control/pause",
                json={"operator_id": "operator.local", "reason": "smoke"},
            )
            authorized = client.post(
                "/runtime/streams/control/pause",
                headers={"Authorization": "Bearer stream-control-token"},
                json={"operator_id": "operator.local", "reason": "smoke"},
            )

        self.assertEqual(control_status.status_code, 200)
        self.assertTrue(control_status.json()["operator_authorization_required"])
        self.assertFalse(control_status.json()["token_value_exposed"])
        self.assertEqual(unauthorized.status_code, 401)
        self.assertEqual(
            unauthorized.json()["detail"]["reason"],
            "runtime_stream_control_auth_required",
        )
        self.assertEqual(authorized.status_code, 200)
        self.assertEqual(authorized.json()["snapshot_after"]["status"], "paused")


if __name__ == "__main__":
    unittest.main()
