from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from assistant_models import AssistantSurface
from scout_ai_tool_contracts import (
    ScoutAiToolBaseModel,
    ScoutAiToolBoundary,
    default_tool_contracts,
)
from scout_ai_tool_executor import execute_scout_ai_tool
from scout_ai_workflow_discovery import build_scout_ai_workflow_discovery_plan


ARTIFACT_KIND = "scout_ai_evidence_collection"
ARTIFACT_VERSION = "scout_ai_evidence_collection.v0"


class ScoutAiEvidenceCollectionExecutionPolicy(ScoutAiToolBaseModel):
    deterministic_tools_executed: bool = False
    ready_tools_executed: bool = False
    model_synthesis_performed: Literal[False] = False
    workspace_file_write_allowed: Literal[False] = False
    safety_api_called: Literal[False] = False
    phase1_l0_l4_state_mutated: Literal[False] = False
    outbound_send_performed: Literal[False] = False
    hardware_control_performed: Literal[False] = False


class ScoutAiCollectedEvidenceRecord(ScoutAiToolBaseModel):
    tool_id: str
    planned_status: str
    collection_status: str
    implementation_status: str | None = None
    output_artifact_kind: str | None = None
    request: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    missing_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    implementation_gap: str | None = None
    boundary: ScoutAiToolBoundary = Field(default_factory=ScoutAiToolBoundary)


class ScoutAiEvidenceCollectionOutput(ScoutAiToolBaseModel):
    artifact_kind: Literal["scout_ai_evidence_collection"] = ARTIFACT_KIND
    artifact_version: Literal["scout_ai_evidence_collection.v0"] = ARTIFACT_VERSION
    project_id: str
    project_root: str
    surface: str
    question: str
    discovery_plan: dict[str, Any]
    selected_tool_count: int = Field(ge=0)
    executed_tool_count: int = Field(ge=0)
    completed_tool_count: int = Field(ge=0)
    contract_gap_count: int = Field(ge=0)
    missing_input_count: int = Field(ge=0)
    failed_tool_count: int = Field(ge=0)
    evidence_records: list[ScoutAiCollectedEvidenceRecord] = Field(default_factory=list)
    execution_policy: ScoutAiEvidenceCollectionExecutionPolicy = Field(
        default_factory=ScoutAiEvidenceCollectionExecutionPolicy
    )
    boundary: ScoutAiToolBoundary = Field(default_factory=ScoutAiToolBoundary)


def collect_scout_ai_evidence(
    question: str,
    *,
    project_root: str | Path,
    project_id: str | None = None,
    surface: str | AssistantSurface = AssistantSurface.PRETRIP,
    limit: int = 6,
    include_missing_context_sources: bool = True,
    include_not_implemented_tools: bool = True,
    max_result_items_per_tool: int = 6,
) -> ScoutAiEvidenceCollectionOutput:
    discovery = build_scout_ai_workflow_discovery_plan(
        question,
        project_root=project_root,
        project_id=project_id,
        surface=surface,
        limit=limit,
        include_missing_context_sources=include_missing_context_sources,
        include_not_implemented_tools=include_not_implemented_tools,
    )
    contracts = default_tool_contracts()
    records = [
        _collect_plan_item(
            item,
            contracts=contracts,
            max_result_items_per_tool=max_result_items_per_tool,
        )
        for item in discovery.tool_plan.get("selected_tools", [])
        if isinstance(item, dict)
    ]
    executed_count = sum(1 for record in records if record.result is not None)
    completed_count = sum(
        1 for record in records if record.collection_status == "completed"
    )
    contract_gap_count = sum(
        1 for record in records if record.collection_status == "contract_gap"
    )
    missing_input_count = sum(
        1 for record in records if record.collection_status == "missing_input"
    )
    failed_count = sum(1 for record in records if record.collection_status == "failed")

    return ScoutAiEvidenceCollectionOutput(
        project_id=discovery.project_id,
        project_root=discovery.project_root,
        surface=discovery.surface,
        question=discovery.question,
        discovery_plan=discovery.model_dump(mode="json"),
        selected_tool_count=discovery.selected_tool_count,
        executed_tool_count=executed_count,
        completed_tool_count=completed_count,
        contract_gap_count=contract_gap_count,
        missing_input_count=missing_input_count,
        failed_tool_count=failed_count,
        evidence_records=records,
        execution_policy=ScoutAiEvidenceCollectionExecutionPolicy(
            deterministic_tools_executed=executed_count > 0,
            ready_tools_executed=executed_count > 0,
        ),
    )


def _collect_plan_item(
    item: dict[str, Any],
    *,
    contracts: dict[str, Any],
    max_result_items_per_tool: int,
) -> ScoutAiCollectedEvidenceRecord:
    tool_id = str(item.get("tool_id") or "")
    planned_status = str(item.get("status") or "")
    request = item.get("request") if isinstance(item.get("request"), dict) else None
    contract = contracts.get(tool_id)
    implementation_status = str(item.get("implementation_status") or "")
    output_artifact_kind = str(item.get("output_artifact_kind") or "")

    if planned_status != "ready_to_execute" or request is None:
        collection_status = (
            "contract_gap"
            if planned_status == "contract_only_missing_evidence"
            else "missing_input"
        )
        return ScoutAiCollectedEvidenceRecord(
            tool_id=tool_id,
            planned_status=planned_status,
            collection_status=collection_status,
            implementation_status=implementation_status,
            output_artifact_kind=output_artifact_kind,
            request=None,
            result=None,
            missing_fields=list(item.get("missing_fields", [])),
            implementation_gap=contract.implementation_gap
            if contract is not None
            else None,
        )

    result = execute_scout_ai_tool(request)
    compact_result = _compact_tool_result(
        result.model_dump(mode="json"),
        max_result_items_per_tool=max_result_items_per_tool,
    )
    status = str(compact_result.get("status") or result.status.value)
    collection_status = "completed" if status == "completed" else status
    if collection_status not in {"completed", "missing_input", "not_implemented"}:
        collection_status = "failed"

    return ScoutAiCollectedEvidenceRecord(
        tool_id=result.tool_id,
        planned_status=planned_status,
        collection_status=collection_status,
        implementation_status=result.implementation_status.value
        if result.implementation_status is not None
        else implementation_status,
        output_artifact_kind=result.output_artifact_kind or output_artifact_kind,
        request=request,
        result=compact_result,
        missing_fields=list(result.missing_fields),
        warnings=list(result.warnings),
        errors=list(result.errors),
        boundary=result.boundary,
    )


def _compact_tool_result(
    result: dict[str, Any],
    *,
    max_result_items_per_tool: int,
) -> dict[str, Any]:
    payload = result.get("payload")
    compact_payload = (
        _compact_payload(payload, max_result_items_per_tool=max_result_items_per_tool)
        if isinstance(payload, dict)
        else {}
    )
    return {
        "artifact_kind": result.get("artifact_kind"),
        "artifact_version": result.get("artifact_version"),
        "tool_id": result.get("tool_id"),
        "request_id": result.get("request_id"),
        "agent_run_id": result.get("agent_run_id"),
        "status": result.get("status"),
        "implementation_status": result.get("implementation_status"),
        "output_artifact_kind": result.get("output_artifact_kind"),
        "payload": compact_payload,
        "missing_fields": result.get("missing_fields", []),
        "warnings": result.get("warnings", []),
        "errors": result.get("errors", []),
        "sources": result.get("sources", []),
        "boundary": result.get("boundary", {}),
    }


def _compact_payload(
    payload: dict[str, Any],
    *,
    max_result_items_per_tool: int,
) -> dict[str, Any]:
    keep_keys = {
        "artifact_kind",
        "tool_id",
        "status",
        "project_id",
        "query",
        "filters",
        "summaries",
        "source_report",
        "route_summary",
        "result_count",
        "matched_artifact_count",
        "matched_route_item_count",
        "matched_point_count",
        "matched_risk_count",
        "matched_terrain_count",
        "matched_evidence_count",
        "matched_context_count",
        "searched_context_count",
        "source_status",
        "navigation_terrain",
        "navigation_decision",
        "provided_fields",
        "quality_flags",
        "weather_window",
        "route_readiness",
        "departure_gate",
        "readiness_state",
        "readiness_governance",
        "pretrip_decision_package",
        "weather_daylight_state",
        "weather_to_decision",
        "media_literacy",
        "media_bias_analysis",
        "survival_incident_playbook",
        "incident_triage",
        "decision",
        "decision_object",
        "decision_output",
        "allowed",
        "action",
        "max_duration_minutes",
        "leave_by",
        "field_answer",
        "contextual_permission",
        "risk_decision",
        "terrain_decision",
        "safety_boundary",
        "risk_budget",
        "risk_budget_source",
        "route_context",
        "route_architecture",
        "cp_graph",
        "route_decision",
        "equipment_resource",
        "resource_readiness",
        "resource_state",
        "team_status_guardian",
        "team_status",
        "team_governance",
        "post_trip_review",
        "completed_trip_summary",
        "post_trip_feedback",
        "after_action_next_plan",
        "model_update_candidates",
        "post_trip_learning_package",
        "review_governance",
        "privacy_share_policy",
        "pace_guardian",
        "team_pace_fit",
        "schedule_pressure",
        "team_context",
        "standard_alignment",
        "threshold_policy",
        "risk_summary",
        "wx_alerts",
        "searched_segment_count",
        "matched_segment_count",
        "route_weather_package_schema",
        "analysis_kind",
        "assessment_kind",
        "answerability",
        "missing_fields",
        "route_query_plan",
        "boundary",
    }
    compact = {key: value for key, value in payload.items() if key in keep_keys}
    results = payload.get("results")
    if isinstance(results, list):
        max_items = max(0, int(max_result_items_per_tool))
        compact["results"] = results[:max_items]
        compact["results_truncated"] = len(results) > max_items
    return compact
