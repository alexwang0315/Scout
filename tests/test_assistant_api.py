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
from assistant_api import create_assistant_provider_status
from assistant_context import assistant_source_refs_from_context, create_assistant_context_resolver
from assistant_models import ScoutAssistantQuery
from admin_assistant_context import build_admin_assistant_context
from pretrip_assistant_context import build_pretrip_assistant_context
from runtime_debug_log import MemoryRuntimeDebugEventLog
from runtime_debug_models import RuntimeDebugEvent


def _review_log(source_id: str, status: str) -> dict[str, object]:
    return {
        "source_id": f"{source_id}.chilai_nanhua_day1",
        "source_path": f"tests/fixtures/pretrip/api_{source_id}.json",
        "evidence_type": f"pretrip_{source_id}",
        "status": status,
        "counts": {},
    }


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

    def test_assistant_status_is_read_only_and_does_not_expose_tokens(self):
        client = TestClient(create_assistant_app())

        response = client.get("/assistant/status")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["read_only"])
        self.assertTrue(payload["model_interpretation"])
        self.assertEqual(payload["provider_class"], "MockAssistantProvider")
        self.assertFalse(payload["token_values_exposed"])
        self.assertNotIn("api_key", json.dumps(payload).lower())
        self.assertNotIn("token-value", json.dumps(payload).lower())

    def test_assistant_query_returns_non_authoritative_observability_metadata(self):
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
        self.assertIn("observability", payload)
        self.assertEqual(payload["observability"]["provider_class"], "MockAssistantProvider")
        self.assertGreaterEqual(payload["observability"]["source_count"], 1)
        self.assertGreaterEqual(payload["observability"]["selected_source_count"], 1)
        self.assertGreaterEqual(payload["observability"]["context_size_chars"], 1)
        self.assertIn(payload["observability"]["latency_class"], {"fast", "slow", "timeout_or_error"})
        self.assertFalse(payload["observability"]["safe_failure"])
        self.assertNotIn("api_key", json.dumps(payload["observability"]).lower())
        self.assertNotIn("token", json.dumps(payload["observability"]).lower())

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
        self.assertTrue(payload["observability"]["safe_failure"])
        self.assertEqual(payload["observability"]["latency_class"], "timeout_or_error")

    def test_local_fallback_failure_is_isolated_with_provider_provenance(self):
        from assistant_pydantic_provider import FallbackPydanticAIRunner, PydanticAIAssistantProvider

        class FailingRunner:
            def __init__(self, *, model_name=None):
                self.model_name = model_name

            def run(self, prompt: str, *, timeout_seconds: int) -> str:
                raise RuntimeError("run failed")

        runner = FallbackPydanticAIRunner(
            primary_runner=FailingRunner(model_name="cloud/test"),
            fallback_runner=FailingRunner(model_name="qwen2.5:0.5b"),
            primary_profile="cloud",
            fallback_profile="local",
        )
        provider = PydanticAIAssistantProvider(runner=runner, timeout_seconds=2)
        client = TestClient(create_assistant_app(provider=provider))

        response = client.post(
            "/assistant/query",
            json={"surface": "hardware_readiness", "question": "Explain provider state."},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["read_only"])
        self.assertTrue(payload["model_interpretation"])
        self.assertIn("Assistant provider failed safely", payload["answer"])
        self.assertFalse(payload["boundary"]["phase1_mutation_allowed"])
        self.assertFalse(payload["boundary"]["hardware_control_allowed"])
        self.assertTrue(payload["observability"]["safe_failure"])
        self.assertEqual(payload["observability"]["model_profile_used"], "local")
        self.assertEqual(payload["observability"]["failover_reason"], "local_run_error:RuntimeError")
        self.assertEqual(payload["observability"]["local_model_name"], "qwen2.5:0.5b")
        self.assertNotIn("api_key", json.dumps(payload).lower())

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
                    payload={
                        "checkpoint_id": "CP2",
                        "safety_level": "L2_CONCERN",
                        "reason": "off_route",
                    },
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
        self.assertEqual(
            sources[0]["context_summary"]["selected_event"]["payload"]["reason"],
            "off_route",
        )
        self.assertIn("debug_event.api.000001", {source["source_id"] for source in sources})

    def test_assistant_api_can_use_selected_pretrip_artifact_detail(self):
        def build_view(_project_id, *, root, project_root):
            return {
                "project_id": "chilai_nanhua_day1",
                "summary": {
                    "route_name": "奇萊南華-能高越嶺步道Day1",
                    "package_id": "pretrip_package.chilai_nanhua_day1",
                    "status": "candidate",
                },
                "artifacts": {},
                "route": {
                    "source_id": "route.chilai_nanhua_day1",
                    "source_path": "tests/fixtures/pretrip/api_route.json",
                    "evidence_type": "pretrip_route_summary",
                    "route_name": "奇萊南華-能高越嶺步道Day1",
                    "bounds": [121.0, 23.9, 121.2, 24.1],
                    "point_count": 12,
                    "distance_m": 5400,
                },
                "readiness": {
                    "source_id": "readiness.chilai_nanhua_day1",
                    "source_path": "tests/fixtures/pretrip/api_readiness.json",
                    "evidence_type": "pretrip_readiness_report",
                    "status": "blocked",
                },
                "review_queue": {
                    "source_id": "review_queue.chilai_nanhua_day1",
                    "source_path": "tests/fixtures/pretrip/api_review_queue.json",
                    "evidence_type": "pretrip_review_queue_manifest",
                    "status": "needs_review",
                    "counts": {"pending": 1},
                    "boundary": {"decisions_recorded": False},
                    "items": [
                        {
                            "source_id": "candidate.cp2",
                            "source_path": "tests/fixtures/pretrip/api_candidates.json",
                            "evidence_type": "pretrip_checkpoint_candidate",
                            "category": "checkpoint",
                            "priority": "high",
                            "status": "candidate",
                            "candidate_ref": "cp2",
                            "review_focus": ["timing", "water"],
                            "map_target_ids": ["cp2"],
                        }
                    ],
                },
                "review_draft_log": _review_log("review_draft", "drafted"),
                "review_decision_log": _review_log("review_decision", "empty"),
                "review_decision_apply_plan": _review_log("review_apply", "not_applied"),
                "external_import_queue": _review_log("external_import", "empty"),
                "expert_contributions": _review_log("expert_contributions", "empty"),
                "departure_bundle": _review_log("departure_bundle", "not_approved"),
                "resources": {"status": "candidate"},
                "weather": {"status": "candidate"},
                "contours": {"status": "candidate"},
                "raw_sample_summary": {"raw_payloads_embedded": False},
                "tabs": {
                    "pre_trip_planning": {"sections": []},
                    "post_analysis": {"sections": []},
                },
            }

        def resolver(query: ScoutAssistantQuery):
            context = build_pretrip_assistant_context(
                query.project_id or query.context_ref or "chilai_nanhua_day1",
                selected_source_id=query.selected_artifact_id,
                view_builder=build_view,
            )
            return assistant_source_refs_from_context(context, query=query)

        client = TestClient(create_assistant_app(context_resolver=resolver))
        response = client.post(
            "/assistant/query",
            json={
                "surface": "pretrip",
                "question": "Why does CP2 need review?",
                "project_id": "chilai_nanhua_day1",
                "selected_artifact_id": "candidate.cp2",
            },
        )

        self.assertEqual(response.status_code, 200)
        context_summary = response.json()["sources"][0]["context_summary"]
        self.assertEqual(context_summary["selected_evidence"]["source_id"], "candidate.cp2")
        self.assertEqual(context_summary["selected_evidence"]["priority"], "high")
        self.assertEqual(context_summary["selected_evidence"]["review_focus"], ["timing", "water"])
        self.assertFalse(response.json()["boundary"]["pretrip_review_mutation_allowed"])

    def test_assistant_api_can_use_selected_admin_evidence_detail(self):
        def resolver(query: ScoutAssistantQuery):
            context = build_admin_assistant_context(
                query.context_ref or "scout_260512_field_golden",
                selected_source_id=query.selected_artifact_id,
            )
            return assistant_source_refs_from_context(context, query=query)

        client = TestClient(create_assistant_app(context_resolver=resolver))
        response = client.post(
            "/assistant/query",
            json={
                "surface": "admin",
                "question": "Why is this checkpoint evidence important?",
                "context_ref": "scout_260512_field_golden",
                "selected_artifact_id": "cp_01",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        context_summary = payload["sources"][0]["context_summary"]
        self.assertEqual(payload["sources"][0]["source_id"], "assistant_context.admin")
        self.assertEqual(context_summary["selected_evidence"]["source_id"], "cp_01")
        self.assertEqual(context_summary["selected_evidence"]["evidence_type"], "replay_checkpoint")
        self.assertIn("Checkpoint cp_01 reached", context_summary["selected_evidence"]["reason"])
        self.assertFalse(payload["boundary"]["incident_store_write_allowed"])
        self.assertFalse(payload["boundary"]["phase2_writeback_allowed"])

    def test_assistant_api_resolves_admin_after_action_ui_selection_aliases(self):
        def resolver(query: ScoutAssistantQuery):
            context = build_admin_assistant_context(
                query.context_ref or "scout_260512_field_golden",
                selected_source_id=query.selected_artifact_id,
            )
            return assistant_source_refs_from_context(context, query=query)

        client = TestClient(create_assistant_app(context_resolver=resolver))
        response = client.post(
            "/assistant/query",
            json={
                "surface": "admin",
                "question": "Why is the selected route evidence important?",
                "context_ref": "scout_260512_field_golden",
                "selected_artifact_id": "route",
            },
        )

        self.assertEqual(response.status_code, 200)
        selected_evidence = response.json()["sources"][0]["context_summary"]["selected_evidence"]
        self.assertEqual(selected_evidence["source_id"], "field_route")
        self.assertEqual(selected_evidence["evidence_type"], "field_route_summary")
        self.assertGreater(selected_evidence["point_count"], 1500)
        self.assertNotIn("raw_samples", json.dumps(selected_evidence))

    def test_assistant_api_resolves_admin_map_layer_alias_with_readable_label(self):
        def resolver(query: ScoutAssistantQuery):
            context = build_admin_assistant_context(
                query.context_ref or "scout_260512_field_golden",
                selected_source_id=query.selected_artifact_id,
            )
            return assistant_source_refs_from_context(context, query=query)

        client = TestClient(create_assistant_app(context_resolver=resolver))
        response = client.post(
            "/assistant/query",
            json={
                "surface": "admin",
                "question": "Which corridors are visible on this map layer?",
                "context_ref": "scout_260512_field_golden",
                "selected_artifact_id": "map_corridors",
            },
        )

        self.assertEqual(response.status_code, 200)
        selected_evidence = response.json()["sources"][0]["context_summary"]["selected_evidence"]
        self.assertEqual(selected_evidence["source_id"], "field_map_context")
        self.assertEqual(selected_evidence["evidence_type"], "map_layer_summary")
        self.assertEqual(selected_evidence["selected_layer_id"], "map_corridors")
        self.assertEqual(selected_evidence["label"], "Map corridors")
        self.assertGreater(selected_evidence["layer_count"], 0)
        self.assertTrue(selected_evidence["sample_labels"])
        self.assertNotIn("polygon", json.dumps(selected_evidence))
        self.assertNotIn("coordinates", json.dumps(selected_evidence))

    def test_assistant_api_can_use_fixture_backed_hardware_readiness_context(self):
        client = TestClient(
            create_assistant_app(
                context_resolver=create_assistant_context_resolver()
            )
        )
        response = client.post(
            "/assistant/query",
            json={
                "surface": "hardware_readiness",
                "question": "Why is the selected provider degraded?",
                "selected_artifact_id": "provider.gnss.primary",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        context_summary = payload["sources"][0]["context_summary"]
        self.assertEqual(payload["sources"][0]["source_id"], "assistant_context.hardware_readiness")
        self.assertEqual(context_summary["summary"]["provider_count"], 2)
        self.assertEqual(context_summary["summary"]["degraded_provider_count"], 1)
        self.assertEqual(context_summary["selected_provider"]["provider_ref"], "provider.gnss.primary")
        self.assertIn("provider.gnss.primary", {source["source_id"] for source in payload["sources"]})
        self.assertFalse(payload["boundary"]["hardware_control_allowed"])
        self.assertFalse(payload["boundary"]["outbound_send_allowed"])

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

    def test_provider_status_reports_cloud_only_config_without_token_values(self):
        class FakeRunner:
            def connect(self, *, timeout_seconds: int) -> None:
                pass

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
                        "connect_on_startup": True,
                        "fallback_to_local_on_error": False,
                    }
                ),
                encoding="utf-8",
            )
            environ = {
                "SCOUT_AI_ASSISTANT_PROVIDER": "pydantic_ai",
                "SCOUT_AI_ASSISTANT_CONFIG_PATH": str(config_path),
                "SCOUT_CLOUD_TOKEN": "token-value-that-must-not-leak",
            }
            provider = create_assistant_provider_from_env(environ, pydantic_runner=FakeRunner())

            status = create_assistant_provider_status(provider=provider, environ=environ)

        self.assertTrue(status["config_loaded"])
        self.assertTrue(status["cloud_only"])
        self.assertFalse(status["local_fallback_enabled"])
        self.assertEqual(status["cloud_model"], "cloud/test")
        self.assertEqual(status["local_model"], "local/test")
        self.assertFalse(status["token_values_exposed"])
        self.assertNotIn("token-value-that-must-not-leak", json.dumps(status))

    def test_provider_status_reports_pi_field_manual_local_fallback_boundary(self):
        class FakeProvider:
            startup_connection_status = "not_checked"

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
                            "model_name": "qwen2.5:0.5b",
                            "base_url": "http://127.0.0.1:11434/v1",
                            "token_id": "pi-local-ollama-ref",
                        },
                        "connect_on_startup": False,
                        "fallback_to_local_on_error": True,
                    }
                ),
                encoding="utf-8",
            )

            status = create_assistant_provider_status(
                provider=FakeProvider(),
                environ={
                    "SCOUT_AI_ASSISTANT_PROVIDER": "pydantic_ai",
                    "SCOUT_AI_ASSISTANT_CONFIG_PATH": str(config_path),
                    "SCOUT_RUNTIME_PROFILE": "pi-field",
                    "SCOUT_CLOUD_TOKEN": "token-value-that-must-not-leak",
                },
            )

        self.assertTrue(status["config_loaded"])
        self.assertTrue(status["local_fallback_enabled"])
        self.assertFalse(status["cloud_only"])
        self.assertEqual(status["runtime_profile"], "pi-field")
        self.assertEqual(status["local_fallback_mode"], "pi_field_manual_opt_in")
        self.assertTrue(status["manual_verification_required"])
        self.assertEqual(status["local_fallback_max_concurrency"], 1)
        self.assertFalse(status["readiness_starts_local_model"])
        self.assertFalse(status["local_model_listener_required_for_readiness"])
        self.assertFalse(status["status_model_switch_allowed"])
        self.assertEqual(status["local_model"], "qwen2.5:0.5b")
        self.assertNotIn("token-value-that-must-not-leak", json.dumps(status))

    def test_provider_status_marks_dev_local_fallback_as_configured_but_not_pi_field(self):
        class FakeProvider:
            startup_connection_status = "not_checked"

        with TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "assistant-models.json"
            config_path.write_text(
                json.dumps(
                    {
                        "cloud_model": {"profile": "cloud", "model_name": "cloud/test"},
                        "local_model": {"profile": "local", "model_name": "qwen2.5:0.5b"},
                        "fallback_to_local_on_error": True,
                    }
                ),
                encoding="utf-8",
            )

            status = create_assistant_provider_status(
                provider=FakeProvider(),
                environ={
                    "SCOUT_AI_ASSISTANT_PROVIDER": "pydantic_ai",
                    "SCOUT_AI_ASSISTANT_CONFIG_PATH": str(config_path),
                    "SCOUT_RUNTIME_PROFILE": "dev",
                },
            )

        self.assertEqual(status["runtime_profile"], "dev")
        self.assertEqual(status["local_fallback_mode"], "configured_not_pi_field")
        self.assertFalse(status["manual_verification_required"])
        self.assertFalse(status["readiness_starts_local_model"])

    def test_provider_factory_isolates_missing_external_model_config(self):
        provider = create_assistant_provider_from_env(
            {
                "SCOUT_AI_ASSISTANT_PROVIDER": "pydantic_ai",
                "SCOUT_AI_ASSISTANT_CONFIG_PATH": "/path/that/does/not/exist.json",
            }
        )

        response = provider.answer(
            ScoutAssistantQuery(surface="debug", question="Explain state."),
            sources=[],
        )

        self.assertTrue(response.read_only)
        self.assertTrue(response.model_interpretation)
        self.assertIn("startup failed safely", response.answer)
        self.assertIn("provider_startup_error_type=FileNotFoundError", response.limitations)
        self.assertFalse(response.boundary.phase1_mutation_allowed)

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
            "@router.put",
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
            self.assertNotIn("/assistant/status", {route.path for route in server.app.routes})

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
            self.assertIn("/assistant/status", {route.path for route in server.app.routes})
            self.assertEqual(client.get("/assistant/status").status_code, 200)
            self.assertEqual(client.put("/assistant/query", json={}).status_code, 405)

    def test_assistant_api_mounts_with_safe_failure_when_pydantic_config_is_missing(self):
        with patch.dict(
            os.environ,
            {
                "SCOUT_AI_ASSISTANT_ENABLED": "1",
                "SCOUT_AI_ASSISTANT_PROVIDER": "pydantic_ai",
                "SCOUT_AI_ASSISTANT_CONFIG_PATH": "/path/that/does/not/exist.json",
            },
            clear=False,
        ):
            server = self._reload_server()
            self.addCleanup(self._reload_server)

            client = TestClient(server.app)
            response = client.post(
                "/assistant/query",
                json={"surface": "debug", "question": "Explain state."},
            )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertTrue(payload["read_only"])
            self.assertIn("startup failed safely", payload["answer"])
            self.assertIn("/assistant/query", {route.path for route in server.app.routes})


if __name__ == "__main__":
    unittest.main()
