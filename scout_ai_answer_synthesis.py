from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from assistant_models import AssistantSurface
from scout_ai_evidence_collection import (
    ScoutAiEvidenceCollectionOutput,
    collect_scout_ai_evidence,
)
from scout_ai_tool_contracts import ScoutAiToolBaseModel, ScoutAiToolBoundary
from scout_live_navigation_state_tool import LIVE_NAVIGATION_STATE_TOOL_ID
from scout_contextual_permission_tool import CONTEXTUAL_PERMISSION_TOOL_ID
from scout_route_context_tool import ROUTE_CONTEXT_TOOL_ID
from scout_route_architecture_tool import ROUTE_ARCHITECTURE_TOOL_ID
from scout_pace_guardian_tool import PACE_GUARDIAN_TOOL_ID
from scout_weather_window_tool import WEATHER_WINDOW_TOOL_ID


ARTIFACT_KIND = "scout_ai_answer_synthesis"
ARTIFACT_VERSION = "scout_ai_answer_synthesis.v0"


class ScoutAiAnswerSynthesisPolicy(ScoutAiToolBaseModel):
    evidence_collection_required: Literal[True] = True
    evidence_collected_before_synthesis: Literal[True] = True
    deterministic_fallback_formatter_used: Literal[True] = True
    answer_synthesis_performed: Literal[True] = True
    model_provider_used: Literal[False] = False
    model_synthesis_performed: Literal[False] = False
    workspace_file_write_allowed: Literal[False] = False
    safety_api_called: Literal[False] = False
    phase1_l0_l4_state_mutated: Literal[False] = False
    outbound_send_performed: Literal[False] = False
    hardware_control_performed: Literal[False] = False


class ScoutAiAnswerSource(ScoutAiToolBaseModel):
    source_id: str
    tool_id: str
    collection_status: str
    output_artifact_kind: str | None = None
    result_count: int | None = None
    top_result_summary: dict[str, Any] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    implementation_gap: str | None = None
    runtime_safety_truth: Literal[False] = False


class ScoutAiAnswerSynthesisOutput(ScoutAiToolBaseModel):
    artifact_kind: Literal["scout_ai_answer_synthesis"] = ARTIFACT_KIND
    artifact_version: Literal["scout_ai_answer_synthesis.v0"] = ARTIFACT_VERSION
    project_id: str
    project_root: str
    surface: str
    question: str
    answerability: str
    answer: str
    evidence_collection: dict[str, Any]
    evidence_collection_verified: Literal[True] = True
    completed_source_count: int = Field(ge=0)
    missing_evidence_count: int = Field(ge=0)
    failed_source_count: int = Field(ge=0)
    sources: list[ScoutAiAnswerSource] = Field(default_factory=list)
    missing_evidence: list[dict[str, Any]] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    synthesis_policy: ScoutAiAnswerSynthesisPolicy = Field(
        default_factory=ScoutAiAnswerSynthesisPolicy
    )
    boundary: ScoutAiToolBoundary = Field(default_factory=ScoutAiToolBoundary)


def collect_and_synthesize_scout_ai_answer(
    question: str,
    *,
    project_root: str | Path,
    project_id: str | None = None,
    surface: str | AssistantSurface = AssistantSurface.PRETRIP,
    limit: int = 6,
    include_missing_context_sources: bool = True,
    include_not_implemented_tools: bool = True,
    max_result_items_per_tool: int = 6,
) -> ScoutAiAnswerSynthesisOutput:
    evidence_collection = collect_scout_ai_evidence(
        question,
        project_root=project_root,
        project_id=project_id,
        surface=surface,
        limit=limit,
        include_missing_context_sources=include_missing_context_sources,
        include_not_implemented_tools=include_not_implemented_tools,
        max_result_items_per_tool=max_result_items_per_tool,
    )
    return synthesize_scout_ai_answer_from_evidence(evidence_collection)


def synthesize_scout_ai_answer_from_evidence(
    evidence_collection: ScoutAiEvidenceCollectionOutput | dict[str, Any],
) -> ScoutAiAnswerSynthesisOutput:
    collection = _parse_evidence_collection(evidence_collection)
    sources = [_source_from_record(record.model_dump(mode="json")) for record in collection.evidence_records]
    missing_evidence = [
        _missing_evidence_from_source(source)
        for source in sources
        if source.collection_status in {"contract_gap", "missing_input", "not_implemented"}
        or source.missing_fields
    ]
    failed_count = sum(
        1
        for source in sources
        if source.collection_status not in {
            "completed",
            "contract_gap",
            "missing_input",
            "not_implemented",
        }
    )
    completed_count = sum(1 for source in sources if source.collection_status == "completed")
    answerability = _answerability(
        completed_count=completed_count,
        missing_evidence_count=len(missing_evidence),
        failed_count=failed_count,
        selected_tool_count=collection.selected_tool_count,
    )
    limitations = _limitations(answerability)

    return ScoutAiAnswerSynthesisOutput(
        project_id=collection.project_id,
        project_root=collection.project_root,
        surface=collection.surface,
        question=collection.question,
        answerability=answerability,
        answer=_answer_text(
            collection.question,
            sources=sources,
            missing_evidence=missing_evidence,
            answerability=answerability,
        ),
        evidence_collection=collection.model_dump(mode="json"),
        completed_source_count=completed_count,
        missing_evidence_count=len(missing_evidence),
        failed_source_count=failed_count,
        sources=sources,
        missing_evidence=missing_evidence,
        limitations=limitations,
    )


def _parse_evidence_collection(
    evidence_collection: ScoutAiEvidenceCollectionOutput | dict[str, Any],
) -> ScoutAiEvidenceCollectionOutput:
    if isinstance(evidence_collection, ScoutAiEvidenceCollectionOutput):
        return evidence_collection
    payload = dict(evidence_collection)
    payload.pop("status", None)
    return ScoutAiEvidenceCollectionOutput.model_validate(payload)


def _source_from_record(record: dict[str, Any]) -> ScoutAiAnswerSource:
    result = record.get("result") if isinstance(record.get("result"), dict) else {}
    payload = result.get("payload") if isinstance(result.get("payload"), dict) else {}
    results = payload.get("results") if isinstance(payload.get("results"), list) else []
    top_summary = _top_result_summary(results[0] if results else payload)
    for key in (
        "field_answer",
        "navigation_terrain",
        "navigation_decision",
        "provided_fields",
        "quality_flags",
        "route_context",
        "route_architecture",
        "cp_graph",
        "route_decision",
        "pace_guardian",
        "team_pace_fit",
        "weather_to_decision",
        "decision",
        "answerability",
        "source_status",
    ):
        if key in payload and key not in top_summary:
            top_summary[key] = payload[key]
    return ScoutAiAnswerSource(
        source_id=str(record.get("tool_id") or ""),
        tool_id=str(record.get("tool_id") or ""),
        collection_status=str(record.get("collection_status") or ""),
        output_artifact_kind=record.get("output_artifact_kind"),
        result_count=_int_or_none(payload.get("result_count")),
        top_result_summary=top_summary,
        missing_fields=[str(field) for field in record.get("missing_fields", [])],
        implementation_gap=record.get("implementation_gap"),
    )


def _missing_evidence_from_source(source: ScoutAiAnswerSource) -> dict[str, Any]:
    return {
        "tool_id": source.tool_id,
        "collection_status": source.collection_status,
        "missing_fields": list(source.missing_fields),
        "implementation_gap": source.implementation_gap,
    }


def _answerability(
    *,
    completed_count: int,
    missing_evidence_count: int,
    failed_count: int,
    selected_tool_count: int,
) -> str:
    if failed_count:
        return "evidence_collection_failed"
    if completed_count and missing_evidence_count:
        return "partial_evidence_with_missing_context"
    if completed_count:
        return "evidence_available"
    if missing_evidence_count:
        return "missing_evidence"
    if selected_tool_count == 0:
        return "no_registry_tool_selected"
    return "insufficient_evidence"


def _answer_text(
    question: str,
    *,
    sources: list[ScoutAiAnswerSource],
    missing_evidence: list[dict[str, Any]],
    answerability: str,
) -> str:
    parts = [
        "Scout AI read-only answer draft: deterministic evidence was collected before synthesis.",
        f"Question: {question}",
    ]
    completed_sources = [source for source in sources if source.collection_status == "completed"]
    contextual_answer = _contextual_permission_answer(completed_sources)
    if contextual_answer:
        parts.append(contextual_answer)
    navigation_answer = _live_navigation_answer(completed_sources)
    if navigation_answer:
        parts.append(navigation_answer)
    route_context_answer = _route_context_answer(completed_sources)
    if route_context_answer:
        parts.append(route_context_answer)
    route_architecture_answer = _route_architecture_answer(completed_sources)
    if route_architecture_answer:
        parts.append(route_architecture_answer)
    pace_guardian_answer = _pace_guardian_answer(completed_sources)
    if pace_guardian_answer:
        parts.append(pace_guardian_answer)
    weather_decision_answer = _weather_decision_answer(completed_sources)
    if weather_decision_answer:
        parts.append(weather_decision_answer)
    if completed_sources:
        parts.append(
            "Collected evidence: "
            + "; ".join(_completed_source_text(source) for source in completed_sources)
            + "."
        )
    if missing_evidence:
        parts.append(
            "Missing evidence: "
            + "; ".join(_missing_evidence_text(item) for item in missing_evidence)
            + "."
        )
    if answerability == "no_registry_tool_selected":
        parts.append(
            "No registry-backed Scout AI tool was selected for this question; "
            "there is no deterministic evidence to support a Scout-specific answer."
        )
    if answerability == "missing_evidence":
        parts.append(
            "A field conclusion should not be inferred until the missing evidence is provided."
        )
    parts.append(
        "This is candidate/planning evidence only, not runtime safety truth; it cannot trigger Ln, /safety/*, SOS, beacon, outbound send, or hardware control."
    )
    return " ".join(parts)


def _completed_source_text(source: ScoutAiAnswerSource) -> str:
    top = source.top_result_summary
    top_text = ", ".join(f"{key}={value}" for key, value in top.items()) if top else "no top result"
    return (
        f"{source.tool_id} completed"
        f" result_count={source.result_count if source.result_count is not None else 'unknown'}"
        f" top[{top_text}]"
    )


def _missing_evidence_text(item: dict[str, Any]) -> str:
    fields = item.get("missing_fields") if isinstance(item.get("missing_fields"), list) else []
    gap = item.get("implementation_gap")
    text = f"{item.get('tool_id')} status={item.get('collection_status')} missing_fields={','.join(str(field) for field in fields) or 'none'}"
    if gap:
        text += f" implementation_gap={gap}"
    return text


def _limitations(answerability: str) -> list[str]:
    return [
        f"answerability={answerability}",
        "Deterministic Scout AI tools were used before answer synthesis.",
        "This slice used deterministic fallback formatting; no model provider was called.",
        "Candidate/planning evidence was not promoted to runtime safety truth.",
        "No /safety/* call, Phase 1 mutation, Brain/ObservedFact/HumanReview write, outbound send, or hardware control was performed.",
    ]


def _contextual_permission_answer(sources: list[ScoutAiAnswerSource]) -> str | None:
    for source in sources:
        if source.tool_id != CONTEXTUAL_PERMISSION_TOOL_ID:
            continue
        field_answer = source.top_result_summary.get("field_answer")
        if isinstance(field_answer, str) and field_answer.strip():
            return field_answer.strip()
    return None


def _live_navigation_answer(sources: list[ScoutAiAnswerSource]) -> str | None:
    for source in sources:
        if source.tool_id != LIVE_NAVIGATION_STATE_TOOL_ID:
            continue
        field_answer = source.top_result_summary.get("field_answer")
        if isinstance(field_answer, str) and field_answer.strip():
            return field_answer.strip()
    return None


def _route_context_answer(sources: list[ScoutAiAnswerSource]) -> str | None:
    for source in sources:
        if source.tool_id != ROUTE_CONTEXT_TOOL_ID:
            continue
        field_answer = source.top_result_summary.get("field_answer")
        if isinstance(field_answer, str) and field_answer.strip():
            return field_answer.strip()
    return None


def _route_architecture_answer(sources: list[ScoutAiAnswerSource]) -> str | None:
    for source in sources:
        if source.tool_id != ROUTE_ARCHITECTURE_TOOL_ID:
            continue
        field_answer = source.top_result_summary.get("field_answer")
        if isinstance(field_answer, str) and field_answer.strip():
            return field_answer.strip()
    return None


def _pace_guardian_answer(sources: list[ScoutAiAnswerSource]) -> str | None:
    for source in sources:
        if source.tool_id != PACE_GUARDIAN_TOOL_ID:
            continue
        field_answer = source.top_result_summary.get("field_answer")
        if isinstance(field_answer, str) and field_answer.strip():
            return field_answer.strip()
    return None


def _weather_decision_answer(sources: list[ScoutAiAnswerSource]) -> str | None:
    for source in sources:
        if source.tool_id != WEATHER_WINDOW_TOOL_ID:
            continue
        field_answer = source.top_result_summary.get("field_answer")
        if isinstance(field_answer, str) and field_answer.strip():
            return field_answer.strip()
    return None


def _top_result_summary(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    keys = (
        "score",
        "score_field",
        "risk_bucket",
        "risk_level",
        "distance_km",
        "lat",
        "lon",
        "candidate_id",
        "label",
        "nearest_cp_candidate_id",
        "evidence_type",
        "source_path",
        "answerability",
        "source_status",
        "risk_summary",
        "weather_window",
        "weather_to_decision",
        "decision",
        "allowed",
        "action",
        "max_duration_minutes",
        "leave_by",
        "field_answer",
        "contextual_permission",
        "risk_budget",
        "risk_budget_source",
        "navigation_terrain",
        "navigation_decision",
        "provided_fields",
        "quality_flags",
        "route_fit_status",
        "position_quality_status",
        "route_context",
        "route_architecture",
        "cp_graph",
        "route_decision",
        "pace_guardian",
        "route_type",
        "turn_back",
        "retreat_option_count",
        "hard_point_count",
        "team_pace_fit",
        "schedule_pressure",
        "team_context",
        "slowest_member",
        "fastest_member",
        "pace_gap_ratio",
        "context_kind",
        "guidance",
        "stop_guidance",
        "candidate_only",
        "confidence",
        "main_reasons",
        "next_action",
        "missing_fields",
    )
    return {key: value[key] for key in keys if key in value and value[key] is not None}


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
