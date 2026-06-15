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
from scout_equipment_resource_tool import EQUIPMENT_RESOURCE_TOOL_ID
from scout_team_status_tool import TEAM_STATUS_TOOL_ID
from scout_post_trip_review_tool import POST_TRIP_REVIEW_TOOL_ID
from scout_route_readiness_tool import ROUTE_READINESS_TOOL_ID
from scout_weather_window_tool import WEATHER_WINDOW_TOOL_ID
from scout_media_literacy_tool import MEDIA_LITERACY_TOOL_ID
from scout_survival_incident_playbook_tool import SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID
from scout_safety_boundary_tool import SAFETY_BOUNDARY_TOOL_ID
from scout_map_perception_tool import MAP_PERCEPTION_TOOL_ID
from scout_ins_dr_trace_tool import INS_DR_TRACE_TOOL_ID


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
    decision_output: dict[str, Any] = Field(default_factory=dict)
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
    decision_output = _answer_decision_output(
        collection.question,
        sources=sources,
        missing_evidence=missing_evidence,
        answerability=answerability,
    )

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
        decision_output=decision_output,
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
        "safety_boundary",
        "map_perception",
        "ins_dr_trace",
        "metrics",
        "top_deviations",
        "gps_dropout_segments",
        "zigzag_summary",
        "estimate_cadence_summary",
        "provided_fields",
        "quality_flags",
        "route_readiness",
        "route_demand_profile",
        "guided_only_gate",
        "departure_gate",
        "readiness_state",
        "readiness_governance",
        "pretrip_decision_package",
        "weather_daylight_state",
        "route_context",
        "media_literacy",
        "media_bias_analysis",
        "survival_incident_playbook",
        "incident_triage",
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
        "weather_to_decision",
        "decision",
        "decision_object",
        "decision_output",
        "contextual_permission",
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
    safety_boundary_answer = _safety_boundary_answer(completed_sources)
    if safety_boundary_answer:
        parts.append(safety_boundary_answer)
    navigation_answer = _live_navigation_answer(completed_sources)
    if navigation_answer:
        parts.append(navigation_answer)
    map_perception_answer = _map_perception_answer(completed_sources)
    if map_perception_answer:
        parts.append(map_perception_answer)
    ins_dr_trace_answer = _ins_dr_trace_answer(completed_sources)
    if ins_dr_trace_answer:
        parts.append(ins_dr_trace_answer)
    route_readiness_answer = _route_readiness_answer(completed_sources)
    if route_readiness_answer:
        parts.append(route_readiness_answer)
    route_context_answer = _route_context_answer(completed_sources)
    if route_context_answer:
        parts.append(route_context_answer)
    media_literacy_answer = _media_literacy_answer(completed_sources)
    if media_literacy_answer:
        parts.append(media_literacy_answer)
    survival_incident_answer = _survival_incident_playbook_answer(completed_sources)
    if survival_incident_answer:
        parts.append(survival_incident_answer)
    route_architecture_answer = _route_architecture_answer(completed_sources)
    if route_architecture_answer:
        parts.append(route_architecture_answer)
    equipment_resource_answer = _equipment_resource_answer(completed_sources)
    if equipment_resource_answer:
        parts.append(equipment_resource_answer)
    team_status_answer = _team_status_answer(completed_sources)
    if team_status_answer:
        parts.append(team_status_answer)
    post_trip_review_answer = _post_trip_review_answer(completed_sources)
    if post_trip_review_answer:
        parts.append(post_trip_review_answer)
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
    top_text = (
        ", ".join(f"{key}={_summary_value_text(key, value)}" for key, value in top.items())
        if top
        else "no top result"
    )
    return (
        f"{source.tool_id} completed"
        f" result_count={source.result_count if source.result_count is not None else 'unknown'}"
        f" top[{top_text}]"
    )


def _summary_value_text(key: str, value: Any) -> str:
    if key == "pretrip_decision_package" and isinstance(value, dict):
        outputs = (
            value.get("required_outputs")
            if isinstance(value.get("required_outputs"), dict)
            else {}
        )
        traceability = (
            value.get("traceability")
            if isinstance(value.get("traceability"), dict)
            else {}
        )
        reasons = (
            traceability.get("reason_records")
            if isinstance(traceability.get("reason_records"), dict)
            else {}
        )
        return (
            "{decision="
            + str(outputs.get("pretrip_decision"))
            + f", top_risk_count={len(outputs.get('top_risk_sources') or [])}"
            + f", missing_field_count={reasons.get('missing_field_count')}}}"
        )
    if isinstance(value, dict):
        preferred_keys = (
            "role",
            "decision",
            "answerability",
            "status",
            "available",
            "checkpoint_count",
            "segment_count",
            "runtime_safety_truth",
            "candidate_only",
        )
        parts = [
            f"{item_key}={value[item_key]}"
            for item_key in preferred_keys
            if item_key in value and value[item_key] is not None
        ]
        if parts:
            return "{" + ", ".join(parts[:4]) + "}"
        return "{keys=" + ",".join(list(value)[:4]) + "}"
    if isinstance(value, list):
        if len(value) <= 3 and all(not isinstance(item, (dict, list)) for item in value):
            return "[" + ", ".join(str(item) for item in value) + "]"
        return f"list[{len(value)}]"
    text = str(value)
    if len(text) > 160:
        return text[:157] + "..."
    return text


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


def _answer_decision_output(
    question: str,
    *,
    sources: list[ScoutAiAnswerSource],
    missing_evidence: list[dict[str, Any]],
    answerability: str,
) -> dict[str, Any]:
    completed_sources = [
        source for source in sources if source.collection_status == "completed"
    ]
    decision_sources = sorted(completed_sources, key=_decision_source_priority)
    for source in decision_sources:
        native = source.top_result_summary.get("decision_output")
        if isinstance(native, dict) and native:
            return {
                **native,
                "answerSourceToolId": source.tool_id,
                "answerability": answerability,
                "runtimeSafetyTruth": False,
                "standardAlignment": _decision_output_standard_alignment(),
            }
    for source in decision_sources:
        package = source.top_result_summary.get("pretrip_decision_package")
        if isinstance(package, dict) and package:
            return _decision_output_from_pretrip_package(
                source=source,
                package=package,
                answerability=answerability,
            )
    for source in decision_sources:
        output = _generic_decision_output_from_source(
            source=source,
            question=question,
            answerability=answerability,
        )
        if output:
            return output
    return {
        "decisionObjectSchema": "ContextualPermission",
        "answerSourceToolId": None,
        "action": "continue",
        "decision": "DELAY" if missing_evidence else "ESCALATE",
        "allowed": False,
        "mainReasons": [
            "No deterministic Scout decision source was available for this answer."
        ],
        "nextAction": "補齊 deterministic Scout evidence，再重新詢問。",
        "confidence": "low",
        "uncertaintyNotes": [
            _missing_evidence_text(item) for item in missing_evidence
        ],
        "firstLayer": {
            "decision": "暫緩判斷。",
            "limit": "不得把此回答當成現場授權。",
            "reason": "缺少可追溯的 Scout 決策證據。",
            "nextStep": "補齊 deterministic Scout evidence，再重新詢問。",
        },
        "secondLayer": {
            "details": [],
            "uncertaintyNotes": [
                _missing_evidence_text(item) for item in missing_evidence
            ],
            "residualRisk": ["No runtime safety truth was created."],
            "requiredConditions": ["Provide deterministic Scout evidence."],
            "alternativeActions": ["Ask a narrower question with available workspace evidence."],
        },
        "runtimeSafetyTruth": False,
        "standardAlignment": _decision_output_standard_alignment(),
    }


def _decision_source_priority(source: ScoutAiAnswerSource) -> tuple[int, str]:
    if source.tool_id.startswith("pydantic_ai.tool.search_"):
        if source.tool_id == MAP_PERCEPTION_TOOL_ID:
            return (10, source.tool_id)
        if source.tool_id == INS_DR_TRACE_TOOL_ID:
            return (10, source.tool_id)
        return (50, source.tool_id)
    if source.tool_id in {
        SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID,
        SAFETY_BOUNDARY_TOOL_ID,
    }:
        return (0, source.tool_id)
    if source.tool_id == MEDIA_LITERACY_TOOL_ID:
        return (1, source.tool_id)
    if source.tool_id == PACE_GUARDIAN_TOOL_ID:
        schedule = source.top_result_summary.get("schedule_pressure")
        if isinstance(schedule, dict) and schedule.get("current_delay_minutes") is not None:
            return (1, source.tool_id)
    if source.tool_id == CONTEXTUAL_PERMISSION_TOOL_ID:
        return (2, source.tool_id)
    if source.tool_id == ROUTE_READINESS_TOOL_ID:
        return (5, source.tool_id)
    if source.tool_id in {
        WEATHER_WINDOW_TOOL_ID,
        LIVE_NAVIGATION_STATE_TOOL_ID,
        PACE_GUARDIAN_TOOL_ID,
        EQUIPMENT_RESOURCE_TOOL_ID,
        TEAM_STATUS_TOOL_ID,
        ROUTE_ARCHITECTURE_TOOL_ID,
        ROUTE_CONTEXT_TOOL_ID,
        POST_TRIP_REVIEW_TOOL_ID,
    }:
        return (10, source.tool_id)
    return (20, source.tool_id)


def _decision_output_from_pretrip_package(
    *,
    source: ScoutAiAnswerSource,
    package: dict[str, Any],
    answerability: str,
) -> dict[str, Any]:
    outputs = (
        package.get("required_outputs")
        if isinstance(package.get("required_outputs"), dict)
        else {}
    )
    limits = (
        package.get("decision_limits")
        if isinstance(package.get("decision_limits"), dict)
        else {}
    )
    traceability = (
        package.get("traceability")
        if isinstance(package.get("traceability"), dict)
        else {}
    )
    decision = str(outputs.get("pretrip_decision") or "DELAY")
    allowed = bool(limits.get("allowed"))
    main_reasons = _risk_reasons(outputs.get("top_risk_sources"))
    required_conditions = _text_list(outputs.get("required_conditions"))
    alternatives = _text_list(outputs.get("alternatives_or_short_routes"))
    residual_risk = _text_list(outputs.get("residual_risk"))
    latest_turnaround = (
        outputs.get("latest_turnaround")
        if isinstance(outputs.get("latest_turnaround"), dict)
        else {}
    )
    stop_limits = _stop_limit_lines(outputs.get("not_recommended_stop_points"))
    limit = _pretrip_first_layer_limit(
        decision=decision,
        allowed=allowed,
        limits=limits,
        latest_turnaround=latest_turnaround,
    )
    next_action = str(limits.get("next_action") or "補齊出發前必要條件後重新評估。")
    uncertainty_notes = _missing_field_uncertainty(traceability)
    details = [
        detail
        for detail in (
            _cp_graph_detail(outputs.get("cp_graph")),
            _turnaround_limit_text(latest_turnaround),
            *stop_limits[:2],
        )
        if detail
    ]
    return {
        "decisionObjectSchema": "ContextualPermission",
        "answerSourceToolId": source.tool_id,
        "answerability": answerability,
        "action": "continue",
        "decision": decision,
        "allowed": allowed,
        "mainReasons": main_reasons
        or ["Pre-trip readiness decision package did not expose top risks."],
        "cost": {
            "timeBufferChangeMinutes": 0 if not allowed else None,
            "daylightImpact": "Departure remains gated by daylight and review evidence.",
            "retreatImpact": "Turnaround and alternatives must remain visible before runtime handoff.",
            "teamPaceImpact": "Slowest or most vulnerable member basis is required.",
        },
        "nextAction": next_action,
        "confidence": "low" if uncertainty_notes else "medium",
        "uncertaintyNotes": uncertainty_notes,
        "residualRisk": residual_risk,
        "requiredConditions": required_conditions,
        "alternativeActions": alternatives,
        "firstLayer": {
            "decision": _decision_phrase(decision=decision, allowed=allowed),
            "limit": limit,
            "reason": " / ".join((main_reasons or ["缺少前三風險摘要"])[:2]),
            "nextStep": next_action,
        },
        "secondLayer": {
            "details": details,
            "uncertaintyNotes": uncertainty_notes,
            "residualRisk": residual_risk,
            "requiredConditions": required_conditions,
            "alternativeActions": alternatives,
        },
        "runtimeSafetyTruth": False,
        "standardAlignment": _decision_output_standard_alignment(),
    }


def _generic_decision_output_from_source(
    *,
    source: ScoutAiAnswerSource,
    question: str,
    answerability: str,
) -> dict[str, Any] | None:
    summary = source.top_result_summary
    decision = summary.get("decision")
    if not decision:
        return None
    next_action = _first_text(
        summary.get("next_action"),
        summary.get("nextAction"),
        "依照 Scout 工具輸出的下一步重新評估。",
    )
    field_answer = _first_text(summary.get("field_answer"), question) or question
    main_reasons = _text_list(summary.get("main_reasons")) or _text_list(
        summary.get("mainReasons")
    )
    if not main_reasons:
        main_reasons = [field_answer[:160]]
    allowed = bool(summary.get("allowed")) if "allowed" in summary else str(decision) in {
        "GO",
        "CONDITIONAL_GO",
    }
    return {
        "decisionObjectSchema": "ContextualPermission",
        "answerSourceToolId": source.tool_id,
        "answerability": answerability,
        "action": "continue",
        "decision": str(decision),
        "allowed": allowed,
        "mainReasons": main_reasons[:3],
        "nextAction": next_action,
        "confidence": "low" if source.missing_fields else "medium",
        "uncertaintyNotes": [
            f"Missing field: {field}" for field in source.missing_fields
        ],
        "firstLayer": {
            "decision": _decision_phrase(decision=str(decision), allowed=allowed),
            "limit": "依工具 field_answer 的限制執行；不可視為 runtime safety truth。",
            "reason": " / ".join(main_reasons[:2]),
            "nextStep": next_action,
        },
        "secondLayer": {
            "details": [field_answer],
            "uncertaintyNotes": [
                f"Missing field: {field}" for field in source.missing_fields
            ],
            "residualRisk": ["Candidate/planning evidence only."],
            "requiredConditions": [],
            "alternativeActions": [],
        },
        "runtimeSafetyTruth": False,
        "standardAlignment": _decision_output_standard_alignment(),
    }


def _decision_output_standard_alignment() -> list[str]:
    return [
        "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 16 required decision output format",
        "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 17 ContextualPermission schema",
        "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 23 acceptance criteria",
    ]


def _risk_reasons(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    reasons = []
    for item in value:
        if isinstance(item, dict) and item.get("reason"):
            reasons.append(str(item["reason"]))
    return reasons


def _text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _first_text(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _stop_limit_lines(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    lines = []
    for item in value:
        if not isinstance(item, dict):
            continue
        label = item.get("label")
        policy = item.get("policy")
        rationale = item.get("rationale")
        line = " ".join(str(part) for part in (label, policy, rationale) if part)
        if line:
            lines.append(line)
    return lines


def _missing_field_uncertainty(traceability: dict[str, Any]) -> list[str]:
    reason_records = (
        traceability.get("reason_records")
        if isinstance(traceability.get("reason_records"), dict)
        else {}
    )
    count = reason_records.get("missing_field_count")
    if not count:
        return []
    return [f"{count} required pre-trip field(s) remain missing or unreviewed."]


def _cp_graph_detail(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    if not value.get("available"):
        return "CP Graph is not available."
    return (
        "CP Graph available: "
        f"{value.get('checkpoint_count')} checkpoint(s), "
        f"{value.get('segment_count')} segment(s)."
    )


def _turnaround_limit_text(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    checkpoint = value.get("checkpoint_name")
    deadline = value.get("deadline")
    if checkpoint and deadline:
        return f"最晚折返點 {checkpoint}，deadline {deadline}。"
    if checkpoint:
        return f"最晚折返點 {checkpoint}。"
    if deadline:
        return f"最晚折返 deadline {deadline}。"
    return ""


def _pretrip_first_layer_limit(
    *,
    decision: str,
    allowed: bool,
    limits: dict[str, Any],
    latest_turnaround: dict[str, Any],
) -> str:
    turnaround = _turnaround_limit_text(latest_turnaround)
    if not allowed or decision in {"DELAY", "NO_GO", "CHANGE_PLAN", "ESCALATE"}:
        if decision == "GUIDED_ONLY":
            if turnaround:
                return f"不得自主出發；僅可改成合格帶領或等效審核控制。{turnaround}"
            return "不得自主出發；僅可改成合格帶領或等效審核控制。"
        if turnaround:
            return f"不得出發或增加停留；補齊缺口並重跑 departure gate。{turnaround}"
        return "不得出發或增加停留；補齊缺口並重跑 departure gate。"
    buffer_cost = _first_text(limits.get("buffer_cost_statement"))
    if turnaround and buffer_cost:
        return f"{turnaround}任何停留都必須保留安全 buffer。"
    if turnaround:
        return turnaround
    return "不得把此回答當成 departure approval；仍需人工出發關卡。"


def _decision_phrase(*, decision: str, allowed: bool) -> str:
    if decision == "GO":
        return "可以出發，但仍需通過人工 departure gate。"
    if decision == "CONDITIONAL_GO":
        return "可以條件式出發。"
    if decision == "GUIDED_ONLY":
        return "不建議自主前往。"
    if decision == "CHANGE_PLAN":
        return "必須改計畫。"
    if decision == "DELAY":
        return "建議延後。"
    if decision == "NO_GO":
        return "不建議出發。"
    if decision == "ESCALATE":
        return "需要升級處理。"
    return "可以。" if allowed else "不建議。"


def _contextual_permission_answer(sources: list[ScoutAiAnswerSource]) -> str | None:
    for source in sources:
        if source.tool_id != CONTEXTUAL_PERMISSION_TOOL_ID:
            continue
        field_answer = source.top_result_summary.get("field_answer")
        if isinstance(field_answer, str) and field_answer.strip():
            return field_answer.strip()
    return None


def _safety_boundary_answer(sources: list[ScoutAiAnswerSource]) -> str | None:
    for source in sources:
        if source.tool_id != SAFETY_BOUNDARY_TOOL_ID:
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


def _map_perception_answer(sources: list[ScoutAiAnswerSource]) -> str | None:
    for source in sources:
        if source.tool_id != MAP_PERCEPTION_TOOL_ID:
            continue
        field_answer = source.top_result_summary.get("field_answer")
        if isinstance(field_answer, str) and field_answer.strip():
            return field_answer.strip()
    return None


def _ins_dr_trace_answer(sources: list[ScoutAiAnswerSource]) -> str | None:
    for source in sources:
        if source.tool_id != INS_DR_TRACE_TOOL_ID:
            continue
        field_answer = source.top_result_summary.get("field_answer")
        if isinstance(field_answer, str) and field_answer.strip():
            return field_answer.strip()
    return None


def _route_readiness_answer(sources: list[ScoutAiAnswerSource]) -> str | None:
    for source in sources:
        if source.tool_id != ROUTE_READINESS_TOOL_ID:
            continue
        field_answer = source.top_result_summary.get("field_answer")
        package = source.top_result_summary.get("pretrip_decision_package")
        package_answer = (
            _pretrip_decision_package_answer(package)
            if isinstance(package, dict)
            else None
        )
        if isinstance(field_answer, str) and field_answer.strip():
            if package_answer:
                return f"{field_answer.strip()} {package_answer}"
            return field_answer.strip()
        if package_answer:
            return package_answer
    return None


def _pretrip_decision_package_answer(package: dict[str, Any]) -> str | None:
    outputs = (
        package.get("required_outputs")
        if isinstance(package.get("required_outputs"), dict)
        else {}
    )
    limits = (
        package.get("decision_limits")
        if isinstance(package.get("decision_limits"), dict)
        else {}
    )
    decision = outputs.get("pretrip_decision")
    top_risks = _summarize_risk_reasons(outputs.get("top_risk_sources"))
    required_conditions = _summarize_text_items(outputs.get("required_conditions"), limit=2)
    stop_limits = _summarize_stop_limits(
        outputs.get("not_recommended_stop_points"),
        limits=limits,
    )
    pieces = []
    if decision:
        pieces.append(f"標準出發前決策包：decision={decision}")
    if top_risks:
        pieces.append(f"前三風險={top_risks}")
    if required_conditions:
        pieces.append(f"必補條件={required_conditions}")
    latest_turnaround = (
        outputs.get("latest_turnaround")
        if isinstance(outputs.get("latest_turnaround"), dict)
        else {}
    )
    checkpoint = latest_turnaround.get("checkpoint_name")
    deadline = latest_turnaround.get("deadline")
    if checkpoint or deadline:
        pieces.append(
            "最晚折返="
            + " ".join(str(value) for value in (checkpoint, deadline) if value)
        )
    if stop_limits:
        pieces.append(f"停留限制={stop_limits}")
    if not pieces:
        return None
    return "；".join(pieces) + "。"


def _summarize_risk_reasons(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    reasons = []
    for item in value[:3]:
        if not isinstance(item, dict):
            continue
        reason = item.get("reason")
        if reason:
            reasons.append(str(reason))
    return " / ".join(reasons)


def _summarize_text_items(value: Any, *, limit: int) -> str:
    if not isinstance(value, list):
        return ""
    return " / ".join(str(item) for item in value[:limit] if str(item).strip())


def _summarize_stop_limits(value: Any, *, limits: dict[str, Any]) -> str:
    parts = []
    if isinstance(value, list):
        for item in value[:2]:
            if not isinstance(item, dict):
                continue
            label = item.get("label")
            policy = item.get("policy")
            text = " ".join(str(part) for part in (label, policy) if part)
            if text:
                parts.append(text)
    buffer_cost = limits.get("buffer_cost_statement")
    if buffer_cost:
        parts.append(str(buffer_cost))
    return " / ".join(parts)


def _route_context_answer(sources: list[ScoutAiAnswerSource]) -> str | None:
    for source in sources:
        if source.tool_id != ROUTE_CONTEXT_TOOL_ID:
            continue
        field_answer = source.top_result_summary.get("field_answer")
        if isinstance(field_answer, str) and field_answer.strip():
            return field_answer.strip()
    return None


def _media_literacy_answer(sources: list[ScoutAiAnswerSource]) -> str | None:
    for source in sources:
        if source.tool_id != MEDIA_LITERACY_TOOL_ID:
            continue
        field_answer = source.top_result_summary.get("field_answer")
        if isinstance(field_answer, str) and field_answer.strip():
            return field_answer.strip()
    return None


def _survival_incident_playbook_answer(
    sources: list[ScoutAiAnswerSource],
) -> str | None:
    for source in sources:
        if source.tool_id != SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID:
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


def _equipment_resource_answer(sources: list[ScoutAiAnswerSource]) -> str | None:
    for source in sources:
        if source.tool_id != EQUIPMENT_RESOURCE_TOOL_ID:
            continue
        field_answer = source.top_result_summary.get("field_answer")
        if isinstance(field_answer, str) and field_answer.strip():
            return field_answer.strip()
    return None


def _team_status_answer(sources: list[ScoutAiAnswerSource]) -> str | None:
    for source in sources:
        if source.tool_id != TEAM_STATUS_TOOL_ID:
            continue
        field_answer = source.top_result_summary.get("field_answer")
        if isinstance(field_answer, str) and field_answer.strip():
            return field_answer.strip()
    return None


def _post_trip_review_answer(sources: list[ScoutAiAnswerSource]) -> str | None:
    for source in sources:
        if source.tool_id != POST_TRIP_REVIEW_TOOL_ID:
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
        "decision_object",
        "decision_output",
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
        "route_readiness",
        "departure_gate",
        "readiness_state",
        "readiness_governance",
        "pretrip_decision_package",
        "weather_daylight_state",
        "route_context",
        "media_literacy",
        "media_bias_analysis",
        "survival_incident_playbook",
        "incident_triage",
        "route_architecture",
        "cp_graph",
        "route_decision",
        "pace_guardian",
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
        "critical_gaps",
        "warning_gaps",
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
