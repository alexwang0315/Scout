"""Fail-closed expectations for Scout NextGen intelligence dependencies."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import ConfigDict, model_validator

from scout.schemas.base import NonEmptyStr, SchemaModel

AUTHORITATIVE_STATE_SURFACES = (
    "mission_state",
    "reviewed_baseline",
    "route_state",
    "permission_state",
    "deterministic_safety_state",
    "emergency_authority",
    "notification_authority",
)


class FailureScenario(StrEnum):
    PRAISON_SERVICE_UNAVAILABLE = "praison_service_unavailable"
    MCP_DISCONNECTED = "mcp_disconnected"
    LOCAL_MODEL_UNAVAILABLE = "local_model_unavailable"
    AI_HAT_UNAVAILABLE = "ai_hat_unavailable"
    CLOUD_UNAVAILABLE = "cloud_unavailable"
    QGIS_UNAVAILABLE = "qgis_unavailable"
    WEB_UNAVAILABLE = "web_unavailable"
    MODEL_TIMEOUT = "model_timeout"
    INVALID_STRUCTURED_OUTPUT = "invalid_structured_output"
    AGENT_LOOP_RUNAWAY = "agent_loop_runaway"
    MODEL_BUDGET_EXCEEDED = "model_budget_exceeded"
    STALE_INTELLIGENCE_RESULT = "stale_intelligence_result"
    MISSION_CHANGED_WHILE_RUNNING = "mission_changed_while_running"


class IntelligenceFailureDisposition(StrEnum):
    DEGRADED_UNKNOWN = "degraded_unknown"
    CAPABILITY_UNAVAILABLE = "capability_unavailable"
    EXPLICIT_LOCAL_FALLBACK = "explicit_local_fallback"
    REJECTED_CANDIDATE = "rejected_candidate"
    ATTEMPT_CANCELLED = "attempt_cancelled"


class FailureRetryPolicy(StrEnum):
    BOUNDED_RETRY = "bounded_retry"
    RESTART_THEN_BOUNDED_RETRY = "restart_then_bounded_retry"
    ALTERNATE_RUNTIME_IF_GRANTED = "alternate_runtime_if_granted"
    WAIT_FOR_DEPENDENCY = "wait_for_dependency"
    REPAIR_THEN_NEW_ATTEMPT = "repair_then_new_attempt"
    NEW_BOUND_REQUEST_REQUIRED = "new_bound_request_required"


class CloudEscalationPolicy(StrEnum):
    EXPLICIT_GRANT_ONLY = "explicit_grant_only"
    NOT_AVAILABLE = "not_available"
    NOT_APPLICABLE = "not_applicable"
    PROHIBITED_FOR_STALE_REQUEST = "prohibited_for_stale_request"


class FailureQualificationCase(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario: FailureScenario
    disposition: IntelligenceFailureDisposition
    scout_operational: Literal[True] = True
    level_zero_available: Literal[True] = True
    degraded_capabilities: tuple[NonEmptyStr, ...]
    unaffected_authoritative_state: tuple[NonEmptyStr, ...] = (
        AUTHORITATIVE_STATE_SURFACES
    )
    unknown_code: NonEmptyStr
    retry_policy: FailureRetryPolicy
    cloud_escalation: CloudEscalationPolicy
    provenance_event: NonEmptyStr
    probe_node_ids: tuple[NonEmptyStr, ...]
    invariant_refs: tuple[NonEmptyStr, ...]
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False

    @model_validator(mode="after")
    def validate_case(self) -> "FailureQualificationCase":
        if self.unaffected_authoritative_state != AUTHORITATIVE_STATE_SURFACES:
            raise ValueError("failure case cannot weaken authoritative state isolation")
        if not self.degraded_capabilities:
            raise ValueError("failure case must identify degraded capabilities")
        if not self.probe_node_ids:
            raise ValueError("failure case requires an executable probe")
        if not self.invariant_refs:
            raise ValueError("failure case requires architecture invariants")
        return self


class FailureQualificationMatrix(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["scout.nextgen_failure_matrix.v0"] = (
        "scout.nextgen_failure_matrix.v0"
    )
    cases: tuple[FailureQualificationCase, ...]
    invariant_refs: tuple[NonEmptyStr, ...]
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False

    @model_validator(mode="after")
    def validate_matrix(self) -> "FailureQualificationMatrix":
        scenarios = tuple(case.scenario for case in self.cases)
        if len(scenarios) != len(set(scenarios)):
            raise ValueError("failure matrix scenarios must be unique")
        if set(scenarios) != set(FailureScenario):
            raise ValueError("failure matrix does not cover every required scenario")
        return self


def build_nextgen_failure_matrix() -> FailureQualificationMatrix:
    common = ("INT-001", "INT-002", "INT-003", "INT-005", "INT-007")
    cases = (
        _case(
            FailureScenario.PRAISON_SERVICE_UNAVAILABLE,
            IntelligenceFailureDisposition.DEGRADED_UNKNOWN,
            ("multi_agent_analysis", "candidate_synthesis"),
            "INTELLIGENCE_SERVICE_UNAVAILABLE",
            FailureRetryPolicy.RESTART_THEN_BOUNDED_RETRY,
            CloudEscalationPolicy.EXPLICIT_GRANT_ONLY,
            "intelligence.service.unavailable",
            (
                "tests/test_scout_ai_nextgen_contracts.py::"
                "test_stub_intelligence_gateway_degrades_candidate_only",
            ),
            common + ("INT-008",),
        ),
        _case(
            FailureScenario.MCP_DISCONNECTED,
            IntelligenceFailureDisposition.DEGRADED_UNKNOWN,
            ("remote_intelligence_transport",),
            "INTELLIGENCE_TRANSPORT_UNAVAILABLE",
            FailureRetryPolicy.RESTART_THEN_BOUNDED_RETRY,
            CloudEscalationPolicy.EXPLICIT_GRANT_ONLY,
            "intelligence.mcp.disconnected",
            (
                "tests/test_scout_ai_praison_mcp_slice.py::"
                "test_mcp_process_crash_degrades_without_affecting_authoritative_state",
            ),
            common + ("INT-009",),
        ),
        _case(
            FailureScenario.LOCAL_MODEL_UNAVAILABLE,
            IntelligenceFailureDisposition.CAPABILITY_UNAVAILABLE,
            ("edge_language_reasoning", "edge_tool_selection"),
            "LOCAL_MODEL_UNAVAILABLE",
            FailureRetryPolicy.ALTERNATE_RUNTIME_IF_GRANTED,
            CloudEscalationPolicy.EXPLICIT_GRANT_ONLY,
            "model.local.unavailable",
            (
                "tests/test_scout_ai_model_runtime_qualification.py::"
                "test_live_qualification_reports_unavailable_without_claiming_model_success",
            ),
            common + ("INT-008", "INT-013"),
        ),
        _case(
            FailureScenario.AI_HAT_UNAVAILABLE,
            IntelligenceFailureDisposition.EXPLICIT_LOCAL_FALLBACK,
            ("hailo_llm", "hailo_vlm", "hailo_speech", "hailo_cv"),
            "AI_HAT_UNAVAILABLE",
            FailureRetryPolicy.ALTERNATE_RUNTIME_IF_GRANTED,
            CloudEscalationPolicy.EXPLICIT_GRANT_ONLY,
            "accelerator.hailo.unavailable",
            (
                "tests/test_scout_ai_nextgen_failure_matrix.py::"
                "test_ai_hat_loss_routes_only_to_an_explicit_registered_cpu_fallback",
            ),
            common + ("INT-013", "INT-016"),
        ),
        _case(
            FailureScenario.CLOUD_UNAVAILABLE,
            IntelligenceFailureDisposition.EXPLICIT_LOCAL_FALLBACK,
            ("cloud_reasoning", "cloud_research", "large_context"),
            "CLOUD_UNAVAILABLE",
            FailureRetryPolicy.WAIT_FOR_DEPENDENCY,
            CloudEscalationPolicy.NOT_AVAILABLE,
            "model.cloud.unavailable",
            (
                "tests/test_scout_ai_nextgen_failure_matrix.py::"
                "test_cloud_loss_keeps_registered_local_path_available",
            ),
            common + ("INT-008", "INT-013"),
        ),
        _case(
            FailureScenario.QGIS_UNAVAILABLE,
            IntelligenceFailureDisposition.DEGRADED_UNKNOWN,
            ("heavy_qgis_processing", "new_gis_derivatives"),
            "QGIS_EVIDENCE_UNAVAILABLE",
            FailureRetryPolicy.WAIT_FOR_DEPENDENCY,
            CloudEscalationPolicy.EXPLICIT_GRANT_ONLY,
            "tool.qgis.unavailable",
            (
                "tests/test_scout_ai_workspace_snapshot.py::"
                "test_workspace_compiler_preserves_missing_stale_and_conflict_states",
            ),
            common + ("INT-012", "INT-018"),
        ),
        _case(
            FailureScenario.WEB_UNAVAILABLE,
            IntelligenceFailureDisposition.CAPABILITY_UNAVAILABLE,
            ("web_research", "fresh_external_context"),
            "WEB_EVIDENCE_UNAVAILABLE",
            FailureRetryPolicy.WAIT_FOR_DEPENDENCY,
            CloudEscalationPolicy.NOT_APPLICABLE,
            "tool.web.unavailable",
            (
                "tests/test_scout_ai_praison_mcp_slice.py::"
                "test_deterministic_router_skips_research_for_pure_terrain_evidence",
            ),
            common + ("INT-006", "INT-012"),
        ),
        _case(
            FailureScenario.MODEL_TIMEOUT,
            IntelligenceFailureDisposition.ATTEMPT_CANCELLED,
            ("current_model_attempt",),
            "MODEL_TIMEOUT",
            FailureRetryPolicy.BOUNDED_RETRY,
            CloudEscalationPolicy.EXPLICIT_GRANT_ONLY,
            "model.inference.timed_out",
            (
                "tests/test_scout_ai_praison_mcp_slice.py::"
                "test_mcp_timeout_cancels_service_and_degrades",
            ),
            common + ("INT-014", "INT-016"),
        ),
        _case(
            FailureScenario.INVALID_STRUCTURED_OUTPUT,
            IntelligenceFailureDisposition.REJECTED_CANDIDATE,
            ("model_candidate_output",),
            "INVALID_STRUCTURED_OUTPUT",
            FailureRetryPolicy.REPAIR_THEN_NEW_ATTEMPT,
            CloudEscalationPolicy.EXPLICIT_GRANT_ONLY,
            "model.output.schema_rejected",
            (
                "tests/test_scout_ai_model_gateway.py::"
                "test_model_gateway_rejects_malformed_structured_output_and_records_failure",
            ),
            common + ("INT-004", "INT-014"),
        ),
        _case(
            FailureScenario.AGENT_LOOP_RUNAWAY,
            IntelligenceFailureDisposition.ATTEMPT_CANCELLED,
            ("current_agent_attempt",),
            "AGENT_ATTEMPT_BUDGET_EXHAUSTED",
            FailureRetryPolicy.REPAIR_THEN_NEW_ATTEMPT,
            CloudEscalationPolicy.NOT_APPLICABLE,
            "agent.attempt.budget_exhausted",
            (
                "tests/test_scout_ai_model_gateway.py::"
                "test_model_gateway_shared_session_stops_at_ten_actual_model_requests",
            ),
            common + ("INT-014", "INT-016"),
        ),
        _case(
            FailureScenario.MODEL_BUDGET_EXCEEDED,
            IntelligenceFailureDisposition.REJECTED_CANDIDATE,
            ("current_model_attempt",),
            "MODEL_REQUEST_BUDGET_EXCEEDED",
            FailureRetryPolicy.REPAIR_THEN_NEW_ATTEMPT,
            CloudEscalationPolicy.NOT_APPLICABLE,
            "model.request_budget.exceeded",
            (
                "tests/test_scout_ai_nextgen_contracts.py::"
                "test_contract_gateway_enforces_request_level_model_budget",
            ),
            common + ("INT-014",),
        ),
        _case(
            FailureScenario.STALE_INTELLIGENCE_RESULT,
            IntelligenceFailureDisposition.REJECTED_CANDIDATE,
            ("stale_candidate_reuse",),
            "STALE_INTELLIGENCE_BINDING",
            FailureRetryPolicy.NEW_BOUND_REQUEST_REQUIRED,
            CloudEscalationPolicy.PROHIBITED_FOR_STALE_REQUEST,
            "intelligence.result.stale_rejected",
            (
                "tests/test_scout_ai_nextgen_contracts.py::"
                "test_contract_gateway_rejects_stale_workspace_binding",
            ),
            common + ("INT-010", "INT-011"),
        ),
        _case(
            FailureScenario.MISSION_CHANGED_WHILE_RUNNING,
            IntelligenceFailureDisposition.REJECTED_CANDIDATE,
            ("in_flight_intelligence_result",),
            "MISSION_BINDING_CHANGED",
            FailureRetryPolicy.NEW_BOUND_REQUEST_REQUIRED,
            CloudEscalationPolicy.PROHIBITED_FOR_STALE_REQUEST,
            "intelligence.result.mission_changed_rejected",
            (
                "tests/test_scout_ai_praison_mcp_slice.py::"
                "test_mcp_result_is_rejected_when_mission_changes_while_running",
            ),
            common + ("INT-010", "INT-011"),
        ),
    )
    return FailureQualificationMatrix(
        cases=cases,
        invariant_refs=tuple(
            f"INT-{index:03d}" for index in range(1, 19)
        ),
    )


def _case(
    scenario: FailureScenario,
    disposition: IntelligenceFailureDisposition,
    degraded_capabilities: tuple[str, ...],
    unknown_code: str,
    retry_policy: FailureRetryPolicy,
    cloud_escalation: CloudEscalationPolicy,
    provenance_event: str,
    probe_node_ids: tuple[str, ...],
    invariant_refs: tuple[str, ...],
) -> FailureQualificationCase:
    return FailureQualificationCase(
        scenario=scenario,
        disposition=disposition,
        degraded_capabilities=degraded_capabilities,
        unknown_code=unknown_code,
        retry_policy=retry_policy,
        cloud_escalation=cloud_escalation,
        provenance_event=provenance_event,
        probe_node_ids=probe_node_ids,
        invariant_refs=tuple(dict.fromkeys(invariant_refs)),
    )


__all__ = [
    "AUTHORITATIVE_STATE_SURFACES",
    "CloudEscalationPolicy",
    "FailureQualificationCase",
    "FailureQualificationMatrix",
    "FailureRetryPolicy",
    "FailureScenario",
    "IntelligenceFailureDisposition",
    "build_nextgen_failure_matrix",
]
