import importlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


class ServerSafetyObservationAdmissionConfigTests(unittest.TestCase):
    def _reload_server(self):
        import server

        return importlib.reload(server)

    def test_admission_config_is_disabled_by_default(self):
        import server

        config = server.create_safety_observation_admission_config_from_env({})

        self.assertIsNone(config)

    def test_admission_config_can_load_secret_from_env_or_file(self):
        import server

        env_config = server.create_safety_observation_admission_config_from_env(
            {
                "SCOUT_SAFETY_OBSERVATION_ADMISSION_ENABLED": "1",
                "SCOUT_SAFETY_OBSERVATION_ADMISSION_SECRET": "0123456789abcdef",
            }
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            secret_path = Path(tmpdir) / "admission.secret"
            secret_path.write_text("fedcba9876543210\n", encoding="utf-8")
            file_config = server.create_safety_observation_admission_config_from_env(
                {
                    "SCOUT_SAFETY_OBSERVATION_ADMISSION_ENABLED": "true",
                    "SCOUT_SAFETY_OBSERVATION_ADMISSION_SECRET_FILE": str(secret_path),
                }
            )

        self.assertEqual(env_config.secret_key, "0123456789abcdef")
        self.assertEqual(file_config.secret_key, "fedcba9876543210")

    def test_enabled_admission_config_requires_strong_secret(self):
        import server

        with self.assertRaisesRegex(ValueError, "SCOUT_SAFETY_OBSERVATION_ADMISSION_SECRET"):
            server.create_safety_observation_admission_config_from_env(
                {"SCOUT_SAFETY_OBSERVATION_ADMISSION_ENABLED": "1"}
            )

        with self.assertRaisesRegex(ValueError, "at least 16 characters"):
            server.create_safety_observation_admission_config_from_env(
                {
                    "SCOUT_SAFETY_OBSERVATION_ADMISSION_ENABLED": "1",
                    "SCOUT_SAFETY_OBSERVATION_ADMISSION_SECRET": "short",
                }
            )

        with self.assertRaisesRegex(ValueError, "secret file not found"):
            server.create_safety_observation_admission_config_from_env(
                {
                    "SCOUT_SAFETY_OBSERVATION_ADMISSION_ENABLED": "1",
                    "SCOUT_SAFETY_OBSERVATION_ADMISSION_SECRET_FILE": "/missing/scout/admission.secret",
                }
            )

    def test_server_mount_uses_signed_admission_when_env_enabled(self):
        with patch.dict(
            os.environ,
            {
                "SCOUT_SAFETY_ENABLED": "true",
                "SCOUT_SAFETY_OBSERVATION_ADMISSION_ENABLED": "1",
                "SCOUT_SAFETY_OBSERVATION_ADMISSION_SECRET": "0123456789abcdef",
                "SCOUT_RUNTIME_STREAM_TRANSPORT_ENABLED": "false",
            },
            clear=False,
        ):
            server = self._reload_server()
            self.addCleanup(self._reload_server)
            client = TestClient(server.app)

            self.assertIsNotNone(server.safety_observation_admission_config)
            route_paths = {route.path for route in server.app.routes}
            self.assertIn("/safety/observations", route_paths)
            self.assertNotIn("/runtime/streams/http-push/observations", route_paths)
            self.assertNotIn("/runtime/streams/websocket/observations", route_paths)
            response = client.post(
                "/safety/observations",
                json={"payload": {"loggingTime": 1.0}},
            )

        self.assertEqual(response.status_code, 422)
        detail = response.json()["detail"]
        self.assertTrue(any(item.get("loc") == ["envelope"] for item in detail))

    def test_runtime_stream_transport_requires_explicit_launch_guard(self):
        with patch.dict(
            os.environ,
            {
                "SCOUT_SAFETY_ENABLED": "true",
                "SCOUT_SAFETY_OBSERVATION_ADMISSION_ENABLED": "1",
                "SCOUT_SAFETY_OBSERVATION_ADMISSION_SECRET": "0123456789abcdef",
                "SCOUT_RUNTIME_STREAM_TRANSPORT_ENABLED": "1",
            },
            clear=False,
        ):
            server = self._reload_server()
            self.addCleanup(self._reload_server)

        self.assertIsNotNone(server.safety_observation_admission_config)
        route_paths = {route.path for route in server.app.routes}
        self.assertIn("/runtime/streams/http-push/observations", route_paths)
        self.assertIn("/runtime/streams/websocket/observations", route_paths)

    def test_server_fails_closed_when_admission_enabled_without_secret(self):
        with patch.dict(
            os.environ,
            {
                "SCOUT_SAFETY_ENABLED": "true",
                "SCOUT_SAFETY_OBSERVATION_ADMISSION_ENABLED": "1",
            },
            clear=False,
        ):
            os.environ.pop("SCOUT_SAFETY_OBSERVATION_ADMISSION_SECRET", None)
            os.environ.pop("SCOUT_SAFETY_OBSERVATION_ADMISSION_SECRET_FILE", None)
            server = self._reload_server()
            self.addCleanup(self._reload_server)

        self.assertIsNone(server.safety_observation_admission_config)
        self.assertIsNotNone(server.safety_observation_admission_config_error)
        self.assertIsNone(server.safety_runtime_session)
        route_paths = {route.path for route in server.app.routes}
        self.assertNotIn("/safety/observations", route_paths)
        self.assertNotIn("/runtime/streams/http-push/observations", route_paths)
        self.assertNotIn("/runtime/streams/websocket/observations", route_paths)


if __name__ == "__main__":
    unittest.main()
