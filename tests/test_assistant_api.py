import importlib
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from assistant_api import create_assistant_app
from assistant_api import create_assistant_provider_from_env
from assistant_context import create_assistant_context_resolver
from assistant_models import ScoutAssistantQuery
from runtime_debug_log import MemoryRuntimeDebugEventLog
from runtime_debug_models import RuntimeDebugEvent


class AssistantApiTests(unittest.TestCase):
    def test_assistant_query_is_read_only_post_body_endpoint(self):
        client = TestClient(create_assistant_app())

        response = client.post(
            "/assistant/query",
            json={
                "surface": "debug",
                "question": "Why did Scout enter L2?",
                "selected_event_id": "debug_event.test.000002",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["read_only"])
        self.assertTrue(payload["model_interpretation"])
        self.assertEqual(payload["surface"], "debug")
        self.assertEqual(payload["boundary"]["surface"], "debug")
        self.assertFalse(payload["boundary"]["phase1_mutation_allowed"])
        self.assertFalse(payload["boundary"]["phase2_writeback_allowed"])
        self.assertFalse(payload["boundary"]["outbound_send_allowed"])
        self.assertIn("read-only model interpretation", payload["answer"])
        self.assertEqual(payload["sources"][0]["source_id"], "debug_event.test.000002")

        self.assertEqual(client.get("/assistant/query").status_code, 405)
        self.assertEqual(client.put("/assistant/query", json={}).status_code, 405)
        self.assertEqual(client.patch("/assistant/query", json={}).status_code, 405)
        self.assertEqual(client.delete("/assistant/query").status_code, 405)

    def test_assistant_query_rejects_action_like_fields(self):
        client = TestClient(create_assistant_app())

        response = client.post(
            "/assistant/query",
            json={
                "surface": "pretrip",
                "question": "Accept this candidate",
                "approve": True,
            },
        )

        self.assertEqual(response.status_code, 422)

    def test_provider_failure_is_isolated_as_safe_response(self):
        class FailingProvider:
            def answer(self, query: ScoutAssistantQuery, *, sources=None):
                raise RuntimeError("provider unavailable")

        client = TestClient(create_assistant_app(provider=FailingProvider()))

        response = client.post(
            "/assistant/query",
            json={"surface": "admin", "question": "What happened?"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["read_only"])
        self.assertTrue(payload["model_interpretation"])
        self.assertEqual(payload["surface"], "admin")
        self.assertIn("Assistant provider failed safely", payload["answer"])
        self.assertFalse(payload["boundary"]["incident_store_write_allowed"])
        self.assertFalse(payload["boundary"]["human_review_mutation_allowed"])

    def test_assistant_api_can_use_bounded_debug_context_sources(self):
        log = MemoryRuntimeDebugEventLog(
            [
                RuntimeDebugEvent(
                    event_id="debug_event.api.000001",
                    session_id="debug_session.api",
                    timestamp="2026-05-18T00:00:00Z",
                    sequence=1,
                    kind="safety_event_emitted",
                    source="test",
                    phase="phase35",
                    summary="CP2 emitted L2 concern.",
                    payload={"checkpoint_id": "CP2", "safety_level": "L2_CONCERN"},
                )
            ]
        )
        client = TestClient(
            create_assistant_app(
                context_resolver=create_assistant_context_resolver(debug_event_log=log)
            )
        )

        response = client.post(
            "/assistant/query",
            json={
                "surface": "debug",
                "question": "Why did CP2 become L2?",
                "selected_event_id": "debug_event.api.000001",
            },
        )

        self.assertEqual(response.status_code, 200)
        sources = response.json()["sources"]
        self.assertEqual(sources[0]["source_id"], "assistant_context.debug")
        self.assertEqual(sources[0]["evidence_type"], "assistant_context_summary")
        self.assertEqual(sources[0]["context_summary"]["summary"]["latest_safety_level"], "L2_CONCERN")
        self.assertIn("debug_event.api.000001", {source["source_id"] for source in sources})

    def test_provider_factory_enables_pydantic_ai_only_by_env(self):
        class FakeRunner:
            def run(self, prompt: str, *, timeout_seconds: int) -> str:
                return "safe pydantic response"

        mock_provider = create_assistant_provider_from_env({"SCOUT_AI_ASSISTANT_PROVIDER": "mock"})
        pydantic_provider = create_assistant_provider_from_env(
            {
                "SCOUT_AI_ASSISTANT_PROVIDER": "pydantic_ai",
                "SCOUT_AI_ASSISTANT_TIMEOUT_SECONDS": "2",
                "SCOUT_AI_ASSISTANT_MAX_CONTEXT_CHARS": "500",
            },
            pydantic_runner=FakeRunner(),
        )

        self.assertEqual(type(mock_provider).__name__, "MockAssistantProvider")
        response = pydantic_provider.answer(
            ScoutAssistantQuery(surface="debug", question="Explain state."),
            sources=[],
        )
        self.assertIn("safe pydantic response", response.answer)
        self.assertTrue(response.read_only)

    def test_provider_factory_loads_external_model_config_and_connects_on_startup(self):
        class FakeRunner:
            def __init__(self):
                self.connect_calls = []

            def connect(self, *, timeout_seconds: int) -> None:
                self.connect_calls.append(timeout_seconds)

            def run(self, prompt: str, *, timeout_seconds: int) -> str:
                return "configured response"

        with TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "assistant-models.json"
            config_path.write_text(
                json.dumps(
                    {
                        "active_profile": "cloud",
                        "cloud_model": {
                            "profile": "cloud",
                            "model_name": "cloud/test",
                            "base_url": "https://cloud.example/v1",
                            "token_id": "cloud-token-ref",
                            "token_env_var": "SCOUT_CLOUD_TOKEN",
                        },
                        "local_model": {
                            "profile": "local",
                            "model_name": "local/test",
                            "base_url": "http://127.0.0.1:11434/v1",
                            "token_id": "local-token-ref",
                        },
                        "timeout_seconds": 3,
                        "max_context_chars": 7000,
                        "connect_on_startup": True,
                        "fallback_to_local_on_error": True,
                    }
                ),
                encoding="utf-8",
            )
            runner = FakeRunner()

            provider = create_assistant_provider_from_env(
                {
                    "SCOUT_AI_ASSISTANT_PROVIDER": "pydantic_ai",
                    "SCOUT_AI_ASSISTANT_CONFIG_PATH": str(config_path),
                    "SCOUT_CLOUD_TOKEN": "test-token-value",
                },
                pydantic_runner=runner,
            )

        self.assertEqual(runner.connect_calls, [3])
        response = provider.answer(
            ScoutAssistantQuery(surface="debug", question="Explain state."),
            sources=[],
        )
        self.assertIn("configured response", response.answer)

    def test_assistant_api_source_has_no_mutation_imports_or_methods(self):
        source = __import__("pathlib").Path("assistant_api.py").read_text(encoding="utf-8")

        for forbidden_fragment in (
            "SafetyRuntimeSession",
            "BrainFileStore",
            "IncidentStore",
            "append_review_decision",
            "append_route_note_disposition",
            "@router.put",
            "@router.patch",
            "@router.delete",
            "/safety/",
        ):
            self.assertNotIn(forbidden_fragment, source)


class AssistantApiMountTests(unittest.TestCase):
    def _reload_server(self):
        import server

        return importlib.reload(server)

    def test_assistant_api_is_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SCOUT_AI_ASSISTANT_ENABLED", None)
            server = self._reload_server()
            self.addCleanup(self._reload_server)

            client = TestClient(server.app)

            self.assertEqual(client.post("/assistant/query", json={}).status_code, 404)
            self.assertNotIn("/assistant/query", {route.path for route in server.app.routes})

    def test_assistant_api_mounts_when_explicitly_enabled(self):
        with patch.dict(os.environ, {"SCOUT_AI_ASSISTANT_ENABLED": "1"}, clear=False):
            server = self._reload_server()
            self.addCleanup(self._reload_server)

            client = TestClient(server.app)
            response = client.post(
                "/assistant/query",
                json={"surface": "hardware_readiness", "question": "Provider status?"},
            )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["surface"], "hardware_readiness")
            self.assertIn("/assistant/query", {route.path for route in server.app.routes})
            self.assertEqual(client.put("/assistant/query", json={}).status_code, 405)


if __name__ == "__main__":
    unittest.main()
