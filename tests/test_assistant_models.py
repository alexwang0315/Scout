import pytest
from pydantic import ValidationError

from assistant_models import (
    ASSISTANT_SURFACE_CONSTRAINTS,
    AssistantBoundary,
    AssistantObservability,
    AssistantSourceRef,
    AssistantSurface,
    AssistantSurfaceConstraint,
    ScoutAssistantQuery,
    ScoutAssistantResponse,
)


def test_query_schema_is_strict_and_surface_bound():
    query = ScoutAssistantQuery(
        surface="debug",
        question="Why did Scout enter L2?",
        selected_event_id="debug_event.test.000002",
    )

    assert query.surface == AssistantSurface.DEBUG
    assert query.selected_event_id == "debug_event.test.000002"

    with pytest.raises(ValidationError):
        ScoutAssistantQuery(surface="debug", question="Explain state", approve=True)

    with pytest.raises(ValidationError):
        ScoutAssistantQuery(surface="unknown", question="Explain state")


def test_query_rejects_action_like_body_fields():
    for forbidden_field in (
        "action",
        "approve",
        "send",
        "write_fact",
        "mutate",
        "control_provider",
    ):
        with pytest.raises(ValidationError):
            ScoutAssistantQuery.model_validate(
                {
                    "surface": "pretrip",
                    "question": "What is still waiting for review?",
                    forbidden_field: True,
                }
            )


def test_response_is_always_read_only_model_interpretation():
    response = ScoutAssistantResponse(
        surface="pretrip",
        answer="Readiness is ready, but this is only a read-only model interpretation.",
        sources=[
            AssistantSourceRef(
                source_id="readiness.chilai_nanhua_day1",
                source_path="outputs/readiness_report.json",
                evidence_type="pretrip_readiness_report",
            )
        ],
        boundary=AssistantBoundary(surface="pretrip"),
        limitations=["No review decision was created."],
    )

    assert response.read_only is True
    assert response.model_interpretation is True
    assert response.boundary.phase1_mutation_allowed is False
    assert response.boundary.phase2_writeback_allowed is False
    assert response.boundary.observed_fact_write_allowed is False
    assert response.boundary.pretrip_review_mutation_allowed is False
    assert response.boundary.outbound_send_allowed is False
    assert response.boundary.hardware_control_allowed is False

    payload = response.model_dump(mode="json")
    for forbidden_key in (
        "runtime_command",
        "review_decision",
        "writeback_instruction",
        "outbound_send_request",
        "hardware_control_request",
    ):
        assert forbidden_key not in payload

    with pytest.raises(ValidationError):
        ScoutAssistantResponse(
            surface="debug",
            answer="unsafe",
            read_only=False,
            sources=[],
            boundary=AssistantBoundary(surface="debug"),
        )


def test_response_observability_is_non_authoritative_metadata():
    response = ScoutAssistantResponse(
        surface="debug",
        answer="Read-only model interpretation.",
        sources=[],
        boundary=AssistantBoundary(surface="debug"),
        observability=AssistantObservability(
            provider_class="MockAssistantProvider",
            source_count=0,
            selected_source_count=0,
            context_size_chars=2,
            latency_ms=1,
            latency_class="fast",
            safe_failure=False,
            model_profile_used="local",
            failover_reason="primary_run_error:TimeoutError",
            local_model_name="qwen2.5:0.5b",
        ),
    )

    payload = response.model_dump(mode="json")
    assert payload["observability"]["provider_class"] == "MockAssistantProvider"
    assert payload["observability"]["safe_failure"] is False
    assert payload["observability"]["model_profile_used"] == "local"
    assert payload["observability"]["failover_reason"] == "primary_run_error:TimeoutError"
    assert payload["observability"]["local_model_name"] == "qwen2.5:0.5b"
    assert "api_key" not in str(payload).lower()
    assert "token" not in str(payload).lower()

    with pytest.raises(ValidationError):
        AssistantObservability(
            provider_class="MockAssistantProvider",
            source_count=0,
            selected_source_count=0,
            context_size_chars=2,
            latency_ms=1,
            latency_class="fast",
            writeback=True,
        )

    with pytest.raises(ValidationError):
        ScoutAssistantResponse(
            surface="debug",
            answer="unsafe",
            model_interpretation=False,
            sources=[],
            boundary=AssistantBoundary(surface="debug"),
        )


def test_surface_constraints_are_explicit_for_all_surfaces():
    assert set(ASSISTANT_SURFACE_CONSTRAINTS) == set(AssistantSurface)

    debug = ASSISTANT_SURFACE_CONSTRAINTS[AssistantSurface.DEBUG]
    assert debug.constraint == AssistantSurfaceConstraint.DEBUG_READ_ONLY
    assert "debug events" in debug.allowed_reads
    assert "call /safety/*" in debug.forbidden_actions

    pretrip = ASSISTANT_SURFACE_CONSTRAINTS[AssistantSurface.PRETRIP]
    assert pretrip.constraint == AssistantSurfaceConstraint.PRETRIP_READ_ONLY
    assert "review queue" in pretrip.allowed_reads
    assert "accept/reject candidates" in pretrip.forbidden_actions

    hardware = ASSISTANT_SURFACE_CONSTRAINTS[AssistantSurface.HARDWARE_READINESS]
    assert hardware.constraint == AssistantSurfaceConstraint.HARDWARE_READINESS_READ_ONLY
    assert "control hardware" in hardware.forbidden_actions
