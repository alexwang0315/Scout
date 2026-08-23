from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from assistant_api import create_assistant_app
from assistant_pydantic_provider import PydanticAIAssistantProvider
from scout.nextgen.model_runtime import (
    ModelRuntimeCapability,
    ModelRuntimeRequest,
    ModelRuntimeTier,
    ScoutModelRuntimeRouter,
    default_runtime_profiles,
)
from scout.nextgen.runtime_shadow import (
    RUNTIME_SHADOW_ENV,
    RuntimeShadowStatus,
    maybe_build_assistant_runtime_shadow_trace,
)


class RecordingRunner:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def run(self, prompt: str, *, timeout_seconds: int | None) -> str:
        del timeout_seconds
        self.prompts.append(prompt)
        return "fixture provider answer"


def test_runtime_router_can_exclude_non_answer_runtime_tiers() -> None:
    request = ModelRuntimeRequest(
        request_id=uuid4(),
        task="assistant.debug",
        required_capabilities=frozenset(
            {
                ModelRuntimeCapability.CHAT,
                ModelRuntimeCapability.STRUCTURED_OUTPUT,
                ModelRuntimeCapability.OFFLINE,
            }
        ),
        allowed_tiers=frozenset({ModelRuntimeTier.HAILO_LOCAL}),
        requires_offline=True,
    )

    selection = ScoutModelRuntimeRouter(default_runtime_profiles()).select(request)

    assert selection.selected_runtime is not None
    assert selection.selected_runtime.runtime_id == "edge.hailo.local"
    assert (
        selection.rejected_reasons["local.fast.function"]
        == "runtime tier is outside the request allowlist"
    )


def test_assistant_runtime_shadow_routes_by_preference_and_context() -> None:
    enabled = {RUNTIME_SHADOW_ENV: "1"}

    edge = maybe_build_assistant_runtime_shadow_trace(
        task="assistant.debug",
        runtime_preference=None,
        estimated_context_tokens=2_000,
        environ=enabled,
    )
    max_server = maybe_build_assistant_runtime_shadow_trace(
        task="assistant.pretrip",
        runtime_preference=None,
        estimated_context_tokens=10_000,
        environ=enabled,
    )
    cloud = maybe_build_assistant_runtime_shadow_trace(
        task="assistant.debug",
        runtime_preference="cloud",
        estimated_context_tokens=2_000,
        environ=enabled,
    )

    assert edge is not None
    assert edge.status is RuntimeShadowStatus.SELECTED
    assert edge.selected_runtime_id == "edge.hailo.local"
    assert max_server is not None
    assert max_server.selected_runtime_id == "server.max.openai_compatible"
    assert cloud is not None
    assert cloud.selected_runtime_id == "cloud.reasoning"
    assert all(
        trace.availability_verified is False
        and trace.execution_changed is False
        and trace.candidate_only is True
        and trace.runtime_safety_truth is False
        for trace in (edge, max_server, cloud)
    )


def test_assistant_api_exposes_shadow_trace_without_changing_provider_execution(
    monkeypatch,
) -> None:
    monkeypatch.setenv(RUNTIME_SHADOW_ENV, "true")
    runner = RecordingRunner()
    provider = PydanticAIAssistantProvider(runner=runner)
    app = create_assistant_app(
        provider=provider,
        context_resolver=lambda _query: [],
    )

    response = TestClient(app).post(
        "/assistant/query",
        json={
            "surface": "debug",
            "question": "Summarize the supplied route context.",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert "fixture provider answer" in payload["answer"]
    assert len(runner.prompts) == 1
    shadow = payload["observability"]["runtime_shadow"]
    assert shadow["status"] == "selected"
    assert shadow["selected_runtime_id"] == "edge.hailo.local"
    assert shadow["availability_verified"] is False
    assert shadow["execution_changed"] is False
    assert shadow["candidate_only"] is True
    assert shadow["runtime_safety_truth"] is False


def test_assistant_runtime_shadow_is_off_by_default() -> None:
    trace = maybe_build_assistant_runtime_shadow_trace(
        task="assistant.debug",
        runtime_preference=None,
        estimated_context_tokens=1_000,
        environ={},
    )

    assert trace is None
