from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from assistant_models import (
    AssistantBoundary,
    AssistantSourceRef,
    AssistantSurface,
    ScoutAssistantQuery,
    ScoutAssistantResponse,
)
from scout_ai_context_registry import discover_scout_ai_context_sources
from scout_ai_tool_contracts import ScoutAiToolStatus, default_tool_contracts
from scout_ai_tool_executor import execute_scout_ai_tool
from scout_ai_tool_planner import (
    ENERGY_VITALS_TOOL_ID,
    LIVE_NAVIGATION_STATE_TOOL_ID,
    ScoutAiToolPlan,
    ScoutAiToolPlanItem,
    ScoutAiToolPlanItemStatus,
    plan_scout_ai_tools,
)
from scout_weather_window_tool import WEATHER_WINDOW_TOOL_ID


PRETRIP_PLACE_TO_CP_SKILL_ID = "assistant_skill.pretrip.place_to_cp.v0"
PRETRIP_CP_COUNT_SKILL_ID = "assistant_skill.pretrip.cp_count.v0"
PRETRIP_LOCAL_EVIDENCE_SEARCH_SKILL_ID = (
    "assistant_skill.pretrip.local_evidence_search.v0"
)
PRETRIP_CONTEXT_REGISTRY_SOURCE_ID = "assistant_context.context_registry"
PRETRIP_TOOL_PLANNER_SKILL_ID = "assistant_skill.pretrip.tool_planner.v0"
PRETRIP_FULL_WORKFLOW_SOURCE_ID = "assistant_skill.pretrip.full_workflow.v0"
PRETRIP_ENERGY_VITALS_SNAPSHOT_SOURCE_ID = (
    "assistant_context.energy_vitals_sensor_records"
)
LIVE_NAV_NMEA_SCENARIO_SKILL_ID = "assistant_skill.live_navigation.nmea_route_risk.v0"


def augment_pretrip_sources_with_local_evidence_search(
    query: ScoutAssistantQuery,
    *,
    sources: list[AssistantSourceRef],
    project_root: Path | None,
    limit: int = 5,
) -> list[AssistantSourceRef]:
    if query.surface != AssistantSurface.PRETRIP or project_root is None:
        return sources
    registry_sources = build_pretrip_context_registry_sources(project_root=project_root)
    base_sources = _dedupe_sources([*registry_sources, *sources])
    if resolve_assistant_query_with_skill(query, sources=base_sources) is not None:
        return base_sources

    energy_sources = build_pretrip_energy_vitals_snapshot_sources(
        project_root=project_root,
        question=query.question,
    )
    evidence_sources = [*energy_sources, *base_sources]
    planner_sources = build_pretrip_tool_plan_sources(
        query,
        project_root=project_root,
        limit=limit,
        evidence_sources=evidence_sources,
    )
    full_workflow_source = build_pretrip_full_workflow_source(
        query,
        project_root=project_root,
        limit=limit,
    )
    search_source = build_pretrip_local_evidence_search_source(
        query,
        project_root=project_root,
        limit=limit,
    )
    if search_source is None:
        return _dedupe_sources(
            [
                *base_sources,
                *planner_sources,
                *_optional_source(full_workflow_source),
                *energy_sources,
            ]
        )
    return _dedupe_sources(
        [
            *base_sources,
            *planner_sources,
            *_optional_source(full_workflow_source),
            *energy_sources,
            search_source,
        ]
    )


def augment_pretrip_sources_with_tool_plan(
    query: ScoutAssistantQuery,
    *,
    sources: list[AssistantSourceRef],
    project_root: Path | None,
    limit: int = 5,
) -> list[AssistantSourceRef]:
    if query.surface != AssistantSurface.PRETRIP or project_root is None:
        return sources
    registry_sources = build_pretrip_context_registry_sources(project_root=project_root)
    base_sources = _dedupe_sources([*registry_sources, *sources])
    if resolve_assistant_query_with_skill(query, sources=base_sources) is not None:
        return base_sources
    energy_sources = build_pretrip_energy_vitals_snapshot_sources(
        project_root=project_root,
        question=query.question,
    )
    evidence_sources = [*energy_sources, *base_sources]
    planner_sources = build_pretrip_tool_plan_sources(
        query,
        project_root=project_root,
        limit=limit,
        evidence_sources=evidence_sources,
    )
    if not planner_sources:
        return _dedupe_sources([*base_sources, *energy_sources])
    full_workflow_source = build_pretrip_full_workflow_source(
        query,
        project_root=project_root,
        limit=limit,
    )
    return _dedupe_sources(
        [
            *base_sources,
            *planner_sources,
            *_optional_source(full_workflow_source),
            *energy_sources,
        ]
    )


def build_pretrip_context_registry_sources(
    *,
    project_root: Path,
) -> list[AssistantSourceRef]:
    try:
        registry = discover_scout_ai_context_sources(project_root)
    except Exception:
        return []
    payload = registry.model_dump(mode="json")
    return [
        AssistantSourceRef(
            source_id=PRETRIP_CONTEXT_REGISTRY_SOURCE_ID,
            source_path="scout_ai_context_registry.discover_scout_ai_context_sources",
            evidence_type="assistant_context_registry",
            selected=True,
            context_summary={
                "resolver": PRETRIP_CONTEXT_REGISTRY_SOURCE_ID,
                "registry": payload,
                "artifact_kind": payload["artifact_kind"],
                "artifact_version": payload["artifact_version"],
                "project_id": payload["project_id"],
                "source_count": payload["source_count"],
                "available_source_count": payload["available_source_count"],
                "partial_source_count": payload["partial_source_count"],
                "missing_source_count": payload["missing_source_count"],
                "source_ids_by_domain": payload["source_ids_by_domain"],
                "sources": [
                    _compact_context_registry_source(source)
                    for source in payload["sources"]
                ],
                "boundary": payload["boundary"],
                "read_only": True,
                "runtime_safety_truth": False,
                "raw_payloads_embedded": False,
            },
        )
    ]


def _compact_context_registry_source(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": source.get("source_id"),
        "domain": source.get("domain"),
        "label": source.get("label"),
        "status": source.get("status"),
        "source_paths": source.get("source_paths", []),
        "missing_paths": source.get("missing_paths", []),
        "counts": source.get("counts", {}),
        "tool_ids": source.get("tool_ids", []),
        "implementation_status_by_tool": source.get(
            "implementation_status_by_tool",
            {},
        ),
        "missing_fields": source.get("missing_fields", []),
        "limitations": source.get("limitations", []),
        "candidate_only": source.get("candidate_only", True),
        "runtime_safety_truth": False,
    }


def _dedupe_sources(sources: list[AssistantSourceRef]) -> list[AssistantSourceRef]:
    deduped: list[AssistantSourceRef] = []
    seen: set[str] = set()
    for source in sources:
        if source.source_id in seen:
            continue
        seen.add(source.source_id)
        deduped.append(source)
    return deduped


def _optional_source(source: AssistantSourceRef | None) -> list[AssistantSourceRef]:
    return [source] if source is not None else []


def build_pretrip_energy_vitals_snapshot_sources(
    *,
    project_root: Path,
    question: str = "",
) -> list[AssistantSourceRef]:
    try:
        from scout_sensor_vitals_record import (
            energy_vitals_snapshot_from_sensor_vitals_records,
            load_project_sensor_vitals_records,
        )

        records, record_path = load_project_sensor_vitals_records(project_root)
        if not records or record_path is None:
            return []
        window_config = _energy_vitals_window_config_from_question(question)
        payload = energy_vitals_snapshot_from_sensor_vitals_records(
            records,
            **window_config,
        )
    except Exception:
        return []
    snapshot = payload.get("energy_vitals_snapshot")
    if not isinstance(snapshot, dict) or not snapshot:
        return []
    return [
        AssistantSourceRef(
            source_id=PRETRIP_ENERGY_VITALS_SNAPSHOT_SOURCE_ID,
            source_path=str(record_path),
            evidence_type="energy_vitals_snapshot",
            selected=True,
            context_summary={
                "energy_vitals_snapshot": snapshot,
                "record_count": payload.get("record_count", 0),
                "selected_record_count": payload.get("selected_record_count", 0),
                "field_sources": payload.get("field_sources", {}),
                "time_window": payload.get("time_window", {}),
                "window_config": window_config,
                "source_record_refs": payload.get("source_record_refs", []),
                "boundary": payload.get("boundary", {}),
                "read_only": True,
                "runtime_safety_truth": False,
                "raw_payloads_embedded": False,
            },
        )
    ]


def _energy_vitals_window_config_from_question(question: str) -> dict[str, Any]:
    text = str(question or "").strip().lower()
    compact = text.replace(" ", "")
    config: dict[str, Any] = {}

    record_match = re.search(r"最近(\d+)(筆|筆資料|個樣本|筆樣本)", compact)
    if record_match is None:
        record_match = re.search(r"(?:last|recent)(\d+)(?:records|samples)", compact)
    if record_match is not None:
        config["max_records"] = int(record_match.group(1))
        return config

    time_match = re.search(r"最近(\d+)(秒|分鐘|分|小時|時)", compact)
    if time_match is not None:
        value = int(time_match.group(1))
        unit = time_match.group(2)
        multiplier = 1 if unit == "秒" else 3600 if unit in {"小時", "時"} else 60
        config["window_s"] = float(value * multiplier)
        return config

    english_time_match = re.search(
        r"(?:last|recent)(\d+)(seconds?|secs?|minutes?|mins?|hours?|hrs?)",
        compact,
    )
    if english_time_match is not None:
        value = int(english_time_match.group(1))
        unit = english_time_match.group(2)
        if unit.startswith(("hour", "hr")):
            multiplier = 3600
        elif unit.startswith(("minute", "min")):
            multiplier = 60
        else:
            multiplier = 1
        config["window_s"] = float(value * multiplier)
    return config


def build_pretrip_tool_plan_sources(
    query: ScoutAssistantQuery,
    *,
    project_root: Path,
    limit: int = 5,
    evidence_sources: list[AssistantSourceRef] | None = None,
) -> list[AssistantSourceRef]:
    if query.surface != AssistantSurface.PRETRIP:
        return []
    plan = plan_scout_ai_tools(query, project_root=project_root, limit=limit)
    if not plan.selected_tools:
        return []

    sources = [_pretrip_tool_plan_source(plan)]
    for item in plan.selected_tools:
        sources.append(
            _pretrip_tool_result_source(
                item,
                project_root=project_root,
                evidence_sources=evidence_sources or [],
            )
        )
    return sources


def build_pretrip_full_workflow_source(
    query: ScoutAssistantQuery,
    *,
    project_root: Path,
    limit: int = 5,
) -> AssistantSourceRef | None:
    if query.surface != AssistantSurface.PRETRIP:
        return None
    if not query.question.strip():
        return None
    try:
        from scout_ai_full_workflow import run_scout_ai_full_workflow

        workflow = run_scout_ai_full_workflow(
            query.question,
            project_root=project_root,
            project_id=query.project_id or query.context_ref,
            surface=query.surface,
            limit=limit,
            max_result_items_per_tool=limit,
        )
    except Exception:
        return None

    payload = workflow.model_dump(mode="json")
    return AssistantSourceRef(
        source_id=PRETRIP_FULL_WORKFLOW_SOURCE_ID,
        source_path="scout_ai_full_workflow.run_scout_ai_full_workflow",
        evidence_type="assistant_full_workflow_summary",
        selected=True,
        context_summary=_compact_full_workflow_summary(payload),
    )


def _compact_full_workflow_summary(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "resolver": PRETRIP_FULL_WORKFLOW_SOURCE_ID,
        "artifact_kind": payload.get("artifact_kind"),
        "artifact_version": payload.get("artifact_version"),
        "project_id": payload.get("project_id"),
        "surface": payload.get("surface"),
        "question": payload.get("question"),
        "answerability": payload.get("answerability"),
        "answer": payload.get("answer"),
        "workflow_steps": [
            _compact_full_workflow_step(step)
            for step in payload.get("workflow_steps", [])
            if isinstance(step, dict)
        ],
        "selected_tool_count": payload.get("selected_tool_count", 0),
        "executed_tool_count": payload.get("executed_tool_count", 0),
        "completed_tool_count": payload.get("completed_tool_count", 0),
        "contract_gap_count": payload.get("contract_gap_count", 0),
        "missing_input_count": payload.get("missing_input_count", 0),
        "failed_tool_count": payload.get("failed_tool_count", 0),
        "missing_evidence_count": payload.get("missing_evidence_count", 0),
        "sources": [
            _compact_full_workflow_answer_source(source)
            for source in payload.get("sources", [])
            if isinstance(source, dict)
        ][:8],
        "missing_evidence": payload.get("missing_evidence", [])[:8]
        if isinstance(payload.get("missing_evidence"), list)
        else [],
        "limitations": payload.get("limitations", [])[:8]
        if isinstance(payload.get("limitations"), list)
        else [],
        "workflow_policy": payload.get("workflow_policy", {}),
        "boundary": payload.get("boundary", {}),
        "read_only": True,
        "runtime_safety_truth": False,
        "raw_payloads_embedded": False,
    }


def _compact_full_workflow_step(step: dict[str, Any]) -> dict[str, Any]:
    return {
        "step_id": step.get("step_id"),
        "artifact_kind": step.get("artifact_kind"),
        "artifact_version": step.get("artifact_version"),
        "status": step.get("status"),
        "summary": step.get("summary", {}),
    }


def _compact_full_workflow_answer_source(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "tool_id": source.get("tool_id"),
        "collection_status": source.get("collection_status"),
        "output_artifact_kind": source.get("output_artifact_kind"),
        "result_count": source.get("result_count"),
        "top_result_summary": source.get("top_result_summary", {}),
        "missing_fields": source.get("missing_fields", []),
        "implementation_gap": source.get("implementation_gap"),
        "runtime_safety_truth": False,
    }


def build_pretrip_full_workflow_fallback_response(
    query: ScoutAssistantQuery,
    *,
    sources: list[AssistantSourceRef],
    provider_error_type: str,
) -> ScoutAssistantResponse | None:
    if _has_completed_pretrip_registry_tool_source(sources):
        return None
    workflow_source = _pretrip_full_workflow_source_from_sources(sources)
    if workflow_source is None:
        return None
    summary = (
        workflow_source.context_summary
        if isinstance(workflow_source.context_summary, dict)
        else {}
    )
    answer_draft = str(summary.get("answer") or "").strip()
    if not answer_draft:
        return None

    answer = (
        "Scout AI registry planner fallback: Pydantic AI provider was unavailable, "
        "so this read-only full workflow fallback reports deterministic workflow evidence. "
        f"Question: {query.question}. "
        f"Workflow answer draft: {answer_draft}"
    )
    return ScoutAssistantResponse(
        surface=query.surface,
        answer=answer,
        sources=sources,
        boundary=AssistantBoundary(surface=query.surface),
        limitations=[
            f"provider_error_type={provider_error_type}",
            f"resolved_by={PRETRIP_FULL_WORKFLOW_SOURCE_ID}",
            f"resolved_by={PRETRIP_TOOL_PLANNER_SKILL_ID}",
            "Full workflow ran context discovery, registry-backed tool planning, evidence collection, and answer synthesis before fallback formatting.",
            "Candidate-only workflow evidence was not promoted to runtime safety truth.",
            "No runtime, Brain, review, outbound, or hardware state was changed.",
        ],
    )


def _has_completed_pretrip_registry_tool_source(
    sources: list[AssistantSourceRef],
) -> bool:
    for source in sources:
        summary = source.context_summary if isinstance(source.context_summary, dict) else {}
        if summary.get("resolver") != PRETRIP_TOOL_PLANNER_SKILL_ID:
            continue
        if source.source_id == PRETRIP_TOOL_PLANNER_SKILL_ID:
            continue
        status = summary.get("status")
        latest = summary.get("latest") if isinstance(summary.get("latest"), dict) else {}
        missing_fields = latest.get("missing_fields")
        has_missing_fields = isinstance(missing_fields, list) and bool(missing_fields)
        completed = status == "completed" or latest.get("status") == "completed"
        if completed and source.source_id != WEATHER_WINDOW_TOOL_ID:
            return True
        if completed and not has_missing_fields:
            return True
    return False


def build_pretrip_tool_plan_fallback_response(
    query: ScoutAssistantQuery,
    *,
    sources: list[AssistantSourceRef],
    provider_error_type: str,
) -> ScoutAssistantResponse | None:
    planner_source = _pretrip_tool_plan_source_from_sources(sources)
    if planner_source is None:
        return None
    tool_sources = _pretrip_tool_result_sources(sources)
    if not tool_sources:
        return None

    energy_response = _pretrip_energy_vitals_fallback_response(
        query,
        sources=sources,
        tool_sources=tool_sources,
        provider_error_type=provider_error_type,
    )
    if energy_response is not None:
        return energy_response

    evidence_lines = [_tool_source_fallback_line(source) for source in tool_sources[:5]]
    evidence_lines = [line for line in evidence_lines if line]
    if not evidence_lines:
        return None

    answer = (
        "Scout AI registry planner fallback: Pydantic AI provider was unavailable, "
        "so this read-only answer reports deterministic tool evidence and contract gaps. "
        f"Question: {query.question}. "
        f"Planner evidence: {'; '.join(evidence_lines)}. "
        "These are candidate/planning evidence, not runtime safety truth."
    )
    return ScoutAssistantResponse(
        surface=query.surface,
        answer=answer,
        sources=sources,
        boundary=AssistantBoundary(surface=query.surface),
        limitations=[
            f"provider_error_type={provider_error_type}",
            f"resolved_by={PRETRIP_TOOL_PLANNER_SKILL_ID}",
            "Registry-backed planner selected tools before model synthesis.",
            "Ready current tools were executed read-only; contract-only tools reported missing evidence fields.",
            "Candidate-only planning evidence was not promoted to runtime safety truth.",
            "No runtime, Brain, review, outbound, or hardware state was changed.",
        ],
    )


def _pretrip_energy_vitals_fallback_response(
    query: ScoutAssistantQuery,
    *,
    sources: list[AssistantSourceRef],
    tool_sources: list[AssistantSourceRef],
    provider_error_type: str,
) -> ScoutAssistantResponse | None:
    energy_source = next(
        (
            source
            for source in tool_sources
            if source.source_id == ENERGY_VITALS_TOOL_ID
            and source.evidence_type == "assistant_registry_tool_result"
        ),
        None,
    )
    if energy_source is None:
        return None
    summary = energy_source.context_summary if isinstance(energy_source.context_summary, dict) else {}
    latest = summary.get("latest") if isinstance(summary.get("latest"), dict) else {}
    if latest.get("status") != "completed":
        return None

    provided = latest.get("provided_fields") if isinstance(latest.get("provided_fields"), dict) else {}
    advisory = latest.get("advisory") if isinstance(latest.get("advisory"), dict) else {}
    time_window = latest.get("time_window") if isinstance(latest.get("time_window"), dict) else {}
    heart_rate_trend = (
        time_window.get("heart_rate_trend")
        if isinstance(time_window.get("heart_rate_trend"), dict)
        else {}
    )
    missing_fields = latest.get("missing_fields")
    if not isinstance(missing_fields, list):
        missing_fields = []

    heart_rate = provided.get("heart_rate_bpm")
    reserve_score = provided.get("reserve_score")
    reserve_band = provided.get("reserve_band")
    cue_band = advisory.get("cue_band")
    message_zh = advisory.get("message_zh")
    trend_text = _energy_vitals_trend_text(heart_rate_trend)
    missing_text = (
        "missing_fields=none"
        if not missing_fields
        else "missing_fields=" + ",".join(str(field) for field in missing_fields)
    )
    answer_parts = [
        "Scout AI read-only energy/vitals fallback: Pydantic AI provider was unavailable, so this answer uses deterministic Sensor/Vitals evidence.",
        f"問題：{query.question}",
    ]
    if trend_text:
        answer_parts.append(trend_text)
    if heart_rate is not None:
        answer_parts.append(f"最新心率={heart_rate} bpm。")
    if reserve_score is not None or reserve_band is not None or cue_band is not None:
        answer_parts.append(
            "體能儲備摘要："
            f"reserve_score={reserve_score if reserve_score is not None else 'unknown'}, "
            f"reserve_band={reserve_band or 'unknown'}, "
            f"cue_band={cue_band or 'unknown'}。"
        )
    if message_zh:
        answer_parts.append(str(message_zh))
    answer_parts.append(missing_text + "。")
    answer_parts.append(
        "這是 baseline-relative advisory evidence，不是醫療診斷，不是 runtime safety truth，也不會觸發 /safety、SOS、beacon 或 outbound send。"
    )

    return ScoutAssistantResponse(
        surface=query.surface,
        answer=" ".join(answer_parts),
        sources=sources,
        boundary=AssistantBoundary(surface=query.surface),
        limitations=[
            f"provider_error_type={provider_error_type}",
            f"resolved_by={PRETRIP_TOOL_PLANNER_SKILL_ID}",
            f"resolved_tool={ENERGY_VITALS_TOOL_ID}",
            "Energy/vitals fallback summarized deterministic Sensor/Vitals evidence after provider failure.",
            "Candidate-only wearable evidence was not promoted to runtime safety truth.",
            "No medical diagnosis was made.",
            "No runtime, Brain, review, outbound, or hardware state was changed.",
        ],
    )


def _energy_vitals_trend_text(heart_rate_trend: dict[str, Any]) -> str | None:
    trend = heart_rate_trend.get("trend")
    sample_count = heart_rate_trend.get("sample_count")
    first = heart_rate_trend.get("first")
    last = heart_rate_trend.get("last")
    delta = heart_rate_trend.get("delta")
    if trend in {None, "", "missing"}:
        return None
    trend_label = {
        "increasing": "持續升高",
        "decreasing": "不是持續升高，最近資料呈下降",
        "flat": "大致持平",
        "single_sample": "只有單筆樣本，不能判斷趨勢",
    }.get(str(trend), str(trend))
    parts = [f"心率趨勢：{trend_label}"]
    if sample_count is not None:
        parts.append(f"sample_count={sample_count}")
    if first is not None and last is not None:
        parts.append(f"{first} -> {last} bpm")
    if delta is not None:
        parts.append(f"delta={delta}")
    return "；".join(parts) + "。"


def _pretrip_tool_plan_source(plan: ScoutAiToolPlan) -> AssistantSourceRef:
    selected_tools = [
        {
            "tool_id": item.tool_id,
            "label": item.label,
            "reason": item.reason,
            "status": item.status.value,
            "implementation_status": item.implementation_status.value,
            "required_fields": item.required_fields,
            "missing_fields": item.missing_fields,
            "output_artifact_kind": item.output_artifact_kind,
        }
        for item in plan.selected_tools
    ]
    return AssistantSourceRef(
        source_id=PRETRIP_TOOL_PLANNER_SKILL_ID,
        source_path="scout_ai_tool_planner.plan_scout_ai_tools",
        evidence_type="assistant_registry_tool_plan",
        selected=True,
        context_summary={
            "resolver": PRETRIP_TOOL_PLANNER_SKILL_ID,
            "plan": plan.model_dump(mode="json"),
            "selected_tools": selected_tools,
            "read_only": True,
            "runtime_safety_truth": False,
            "raw_payloads_embedded": False,
        },
    )


def _pretrip_tool_result_source(
    item: ScoutAiToolPlanItem,
    *,
    project_root: Path,
    evidence_sources: list[AssistantSourceRef],
) -> AssistantSourceRef:
    if item.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE and item.request:
        request, hydration = _hydrate_tool_request(
            item,
            evidence_sources=evidence_sources,
        )
        result = execute_scout_ai_tool(request)
        context_summary = {
            "resolver": PRETRIP_TOOL_PLANNER_SKILL_ID,
            "tool_id": item.tool_id,
            "plan_item": item.model_dump(mode="json"),
            "hydration": hydration,
            "status": result.status.value,
            "latest": result.payload
            if result.status == ScoutAiToolStatus.COMPLETED
            else _compact_tool_result(result.model_dump(mode="json")),
            "tool_result": _compact_tool_result(result.model_dump(mode="json")),
            "boundary": result.boundary.model_dump(mode="json"),
            "read_only": True,
            "runtime_safety_truth": False,
            "raw_payloads_embedded": False,
        }
        return AssistantSourceRef(
            source_id=result.tool_id,
            source_path="scout_ai_tool_executor.execute_scout_ai_tool",
            evidence_type="assistant_registry_tool_result",
            selected=True,
            context_summary=context_summary,
        )

    contract = default_tool_contracts().get(item.tool_id)
    implementation_gap = contract.implementation_gap if contract is not None else None
    return AssistantSourceRef(
        source_id=item.tool_id,
        source_path="scout_ai_tool_planner.plan_scout_ai_tools",
        evidence_type="assistant_registry_tool_contract_gap",
        selected=True,
        context_summary={
            "resolver": PRETRIP_TOOL_PLANNER_SKILL_ID,
            "tool_id": item.tool_id,
            "plan_item": item.model_dump(mode="json"),
            "status": item.status.value,
            "implementation_status": item.implementation_status.value,
            "missing_fields": item.missing_fields,
            "implementation_gap": implementation_gap,
            "latest": {
                "status": item.status.value,
                "implementation_status": item.implementation_status.value,
                "missing_fields": item.missing_fields,
                "implementation_gap": implementation_gap,
            },
            "read_only": True,
            "runtime_safety_truth": False,
            "raw_payloads_embedded": False,
        },
        )


def _hydrate_tool_request(
    item: ScoutAiToolPlanItem,
    *,
    evidence_sources: list[AssistantSourceRef],
) -> tuple[dict[str, Any], dict[str, Any]]:
    request = dict(item.request or {})
    hydration: dict[str, Any] = {
        "status": "not_applicable",
        "source_id": None,
        "field_names": [],
    }
    if item.tool_id != LIVE_NAVIGATION_STATE_TOOL_ID:
        if item.tool_id != ENERGY_VITALS_TOOL_ID:
            return request, hydration
        snapshot, source = _energy_vitals_snapshot_from_sources(evidence_sources)
        if not snapshot:
            return (
                request,
                {
                    "status": "no_energy_vitals_snapshot_source",
                    "source_id": None,
                    "field_names": [],
                },
            )
        arguments = request.get("arguments")
        if not isinstance(arguments, dict):
            arguments = {}
        request["arguments"] = {**arguments, **snapshot}
        return (
            request,
            {
                "status": "hydrated",
                "source_id": source.source_id if source is not None else None,
                "field_names": sorted(snapshot),
            },
        )

    snapshot, source = _live_navigation_snapshot_from_sources(evidence_sources)
    if not snapshot:
        return (
            request,
            {
                "status": "no_live_navigation_snapshot_source",
                "source_id": None,
                "field_names": [],
            },
        )
    arguments = request.get("arguments")
    if not isinstance(arguments, dict):
        arguments = {}
    request["arguments"] = {**arguments, **snapshot}
    return (
        request,
        {
            "status": "hydrated",
            "source_id": source.source_id if source is not None else None,
            "field_names": sorted(snapshot),
        },
    )


def _live_navigation_snapshot_from_sources(
    sources: list[AssistantSourceRef],
) -> tuple[dict[str, Any], AssistantSourceRef | None]:
    for source in sources:
        summary = source.context_summary if isinstance(source.context_summary, dict) else {}
        snapshot = _extract_live_navigation_snapshot(summary)
        if not snapshot:
            continue
        snapshot.setdefault("source", source.evidence_type or source.source_id)
        return snapshot, source
    return {}, None


def _energy_vitals_snapshot_from_sources(
    sources: list[AssistantSourceRef],
) -> tuple[dict[str, Any], AssistantSourceRef | None]:
    for source in sources:
        summary = source.context_summary if isinstance(source.context_summary, dict) else {}
        snapshot = _extract_energy_vitals_snapshot(summary)
        if not snapshot:
            continue
        return snapshot, source
    return {}, None


def _extract_energy_vitals_snapshot(summary: dict[str, Any]) -> dict[str, Any]:
    snapshot: dict[str, Any] = {}
    explicit = _dict_or_empty(summary.get("energy_vitals_snapshot"))
    explicit = explicit or _dict_or_empty(summary.get("vitals_snapshot"))
    explicit = explicit or _dict_or_empty(summary.get("wearable_vitals"))
    explicit = explicit or _dict_or_empty(summary.get("snapshot"))
    latest = _dict_or_empty(summary.get("latest"))
    record = _dict_or_empty(summary.get("sensor_vitals_record"))
    values = _dict_or_empty(record.get("values"))
    values = values or _dict_or_empty(summary.get("values"))

    _copy_first(snapshot, "subject_id", explicit, latest, record, summary, keys=("subject_id", "user_profile_ref"))
    _copy_first(snapshot, "observed_at", explicit, latest, record, summary, keys=("observed_at", "timestamp", "captured_at"))
    _copy_first(snapshot, "heart_rate_bpm", explicit, latest, values, keys=("heart_rate_bpm", "heart_rate", "heartrate", "hr"))
    _copy_first(snapshot, "hrv_ms", explicit, latest, values, keys=("hrv_ms", "hrv", "heart_rate_variability_ms"))
    _copy_first(snapshot, "body_battery_or_provider_energy", explicit, latest, values, keys=("body_battery_or_provider_energy", "body_battery", "provider_energy", "energy"))
    _copy_first(snapshot, "pace_mps", explicit, latest, values, keys=("pace_mps", "speed_mps", "pace"))
    _copy_first(snapshot, "cadence", explicit, latest, values, keys=("cadence", "step_cadence"))
    _copy_first(snapshot, "activity_load", explicit, latest, values, keys=("activity_load", "load_sum", "load"))
    _copy_first(snapshot, "baseline_window_days", explicit, latest, keys=("baseline_window_days", "window_days"))
    _copy_first(snapshot, "reserve_score", explicit, latest, values, keys=("reserve_score", "energy_reserve_score"))
    _copy_first(snapshot, "reserve_band", explicit, latest, values, keys=("reserve_band", "energy_reserve_band"))
    _copy_first(snapshot, "heart_rate_drift_ratio", explicit, latest, values, keys=("heart_rate_drift_ratio", "hr_drift_ratio"))
    _copy_first(snapshot, "heart_rate_trend", explicit, latest, values, keys=("heart_rate_trend", "heartRateTrend"))
    _copy_first(snapshot, "hrv_trend", explicit, latest, values, keys=("hrv_trend", "hrvTrend"))
    _copy_first(snapshot, "record_gap_count", explicit, latest, values, keys=("record_gap_count", "recordGapCount"))
    _copy_first(snapshot, "staleness_s", explicit, latest, values, keys=("staleness_s", "stalenessS"))
    _copy_first(snapshot, "privacy_scope", explicit, latest, record, summary, keys=("privacy_scope", "privacy_class"))
    _copy_first(snapshot, "source_provider", explicit, latest, record, summary, keys=("source_provider", "source_adapter", "provider"))
    _copy_first(snapshot, "baseline_path", explicit, latest, summary, keys=("baseline_path", "energy_baseline_path"))
    _copy_first(snapshot, "observation_path", explicit, latest, summary, keys=("observation_path", "field_observation_path"))
    return {key: value for key, value in snapshot.items() if not _missing_value(value)}


def _extract_live_navigation_snapshot(summary: dict[str, Any]) -> dict[str, Any]:
    snapshot: dict[str, Any] = {}
    explicit = _dict_or_empty(summary.get("live_navigation_snapshot"))
    explicit = explicit or _dict_or_empty(summary.get("navigation_snapshot"))
    explicit = explicit or _dict_or_empty(summary.get("snapshot"))
    gnss_fix = _dict_or_empty(summary.get("gnss_fix"))
    route_match = _dict_or_empty(summary.get("route_match"))
    source_sample = _dict_or_empty(summary.get("source_sample"))
    ins_dr = _dict_or_empty(summary.get("ins_dr_snapshot"))
    ins_dr = ins_dr or _dict_or_empty(summary.get("ins_dr"))

    _copy_first(snapshot, "observed_at", explicit, summary, gnss_fix, keys=("observed_at", "timestamp", "captured_at", "gnss_time_utc"))
    _copy_first(snapshot, "lat", explicit, summary, gnss_fix, keys=("lat", "latitude"))
    _copy_first(snapshot, "lon", explicit, summary, gnss_fix, keys=("lon", "longitude"))
    _copy_first(snapshot, "elevation_m", explicit, summary, gnss_fix, keys=("elevation_m", "altitude_m", "altitude"))
    _copy_first(snapshot, "source", explicit, summary, keys=("source", "capture_source"))
    _copy_first(snapshot, "hdop", explicit, summary, gnss_fix, keys=("hdop",))
    _copy_first(snapshot, "horizontal_accuracy_m", explicit, summary, gnss_fix, keys=("horizontal_accuracy_m", "accuracy_m", "h_acc_m"))
    _copy_first(snapshot, "fix_quality", explicit, summary, gnss_fix, keys=("fix_quality", "quality"))
    _copy_first(snapshot, "satellite_count", explicit, summary, gnss_fix, keys=("satellite_count", "satellites"))
    _copy_first(snapshot, "max_cno_dbhz", explicit, summary, gnss_fix, keys=("max_cno_dbhz", "max_cno", "cno"))
    _copy_first(snapshot, "heading_deg", explicit, summary, gnss_fix, ins_dr, keys=("heading_deg", "heading"))
    _copy_first(snapshot, "course_deg", explicit, summary, gnss_fix, keys=("course_deg", "course"))
    _copy_first(snapshot, "speed_mps", explicit, summary, gnss_fix, keys=("speed_mps", "speed"))
    _copy_first(snapshot, "nearest_route_distance_m", explicit, summary, route_match, keys=("nearest_route_distance_m", "distance_m"))
    _copy_first(snapshot, "route_progress_m", explicit, summary, route_match, source_sample, keys=("route_progress_m", "distance_m"))
    _copy_first(snapshot, "nearest_cp_id", explicit, summary, route_match, keys=("nearest_cp_id", "nearest_cp_candidate_id"))
    _copy_first(snapshot, "ins_dr_source", explicit, summary, ins_dr, keys=("ins_dr_source", "source"))
    _copy_first(snapshot, "confidence", explicit, summary, ins_dr, keys=("confidence",))
    _copy_first(snapshot, "uncertainty_m", explicit, summary, gnss_fix, ins_dr, keys=("uncertainty_m", "estimated_error_m"))
    _copy_first(snapshot, "last_anchor_at", explicit, summary, ins_dr, keys=("last_anchor_at",))

    if "fix_quality" not in snapshot and gnss_fix.get("valid") is not None:
        snapshot["fix_quality"] = "valid" if bool(gnss_fix["valid"]) else "invalid"
    return {key: value for key, value in snapshot.items() if not _missing_value(value)}


def _copy_first(
    target: dict[str, Any],
    target_key: str,
    *sources: dict[str, Any],
    keys: tuple[str, ...],
) -> None:
    for source in sources:
        for key in keys:
            value = source.get(key)
            if not _missing_value(value):
                target[target_key] = value
                return


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _missing_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return not value
    return False


def build_pretrip_local_evidence_search_source(
    query: ScoutAssistantQuery,
    *,
    project_root: Path,
    limit: int = 5,
) -> AssistantSourceRef | None:
    search_text = query.question.strip()
    if not search_text:
        return None

    try:
        from scout_agent_kb import query_project_local_evidence

        result = query_project_local_evidence(
            project_root,
            query=search_text,
            limit=limit,
        )
        context_summary = {
            "resolver": PRETRIP_LOCAL_EVIDENCE_SEARCH_SKILL_ID,
            "query": result.query,
            "project_id": result.project_id,
            "retrieval_engine": result.retrieval_engine,
            "result_count": result.result_count,
            "searched_record_count": result.searched_record_count,
            "results": [_compact_kb_result(item) for item in result.results],
            "boundary": result.boundary.model_dump(mode="json"),
            "read_only": True,
            "runtime_safety_truth": False,
            "raw_payloads_embedded": False,
        }
    except Exception as exc:  # Defensive: search failures must not break assistant.
        context_summary = {
            "resolver": PRETRIP_LOCAL_EVIDENCE_SEARCH_SKILL_ID,
            "query": search_text,
            "project_root_available": project_root.is_dir(),
            "status": "failed",
            "error_type": type(exc).__name__,
            "read_only": True,
            "runtime_safety_truth": False,
            "raw_payloads_embedded": False,
        }

    return AssistantSourceRef(
        source_id=PRETRIP_LOCAL_EVIDENCE_SEARCH_SKILL_ID,
        source_path="scout_agent_kb.query_project_local_evidence",
        evidence_type="assistant_local_evidence_search_results",
        selected=True,
        context_summary=context_summary,
    )


def build_local_evidence_search_fallback_response(
    query: ScoutAssistantQuery,
    *,
    sources: list[AssistantSourceRef],
    provider_error_type: str,
) -> ScoutAssistantResponse | None:
    search_source = _local_evidence_search_source(sources)
    if search_source is None:
        return None
    summary = search_source.context_summary or {}
    results = summary.get("results")
    if not isinstance(results, list) or not results:
        return None

    top_results = [item for item in results[:3] if isinstance(item, dict)]
    if not top_results:
        return None

    evidence_lines = []
    for item in top_results:
        evidence_lines.append(
            " | ".join(
                str(part)
                for part in (
                    item.get("evidence_type"),
                    item.get("record_id"),
                    item.get("snippet"),
                )
                if part
            )
        )
    answer = (
        "Scout AI local evidence fallback: Pydantic AI provider was unavailable, "
        "so this read-only answer shows local workspace evidence search results. "
        f"Question: {query.question}. "
        f"Top evidence: {'; '.join(evidence_lines)}. "
        "These are candidate/planning evidence snippets, not runtime safety truth."
    )
    return ScoutAssistantResponse(
        surface=query.surface,
        answer=answer,
        sources=sources,
        boundary=AssistantBoundary(surface=query.surface),
        limitations=[
            f"provider_error_type={provider_error_type}",
            f"resolved_by={PRETRIP_LOCAL_EVIDENCE_SEARCH_SKILL_ID}",
            "Local evidence fallback summarized bounded search snippets after provider failure.",
            "Candidate-only planning evidence was not promoted to runtime safety truth.",
            "No runtime, Brain, review, outbound, or hardware state was changed.",
        ],
    )


def _local_evidence_search_source(
    sources: list[AssistantSourceRef],
) -> AssistantSourceRef | None:
    for source in sources:
        if source.source_id == PRETRIP_LOCAL_EVIDENCE_SEARCH_SKILL_ID:
            return source
    return None


def _pretrip_tool_plan_source_from_sources(
    sources: list[AssistantSourceRef],
) -> AssistantSourceRef | None:
    for source in sources:
        if source.source_id == PRETRIP_TOOL_PLANNER_SKILL_ID:
            return source
    return None


def _pretrip_full_workflow_source_from_sources(
    sources: list[AssistantSourceRef],
) -> AssistantSourceRef | None:
    for source in sources:
        if source.source_id == PRETRIP_FULL_WORKFLOW_SOURCE_ID:
            return source
    return None


def _pretrip_tool_result_sources(
    sources: list[AssistantSourceRef],
) -> list[AssistantSourceRef]:
    return [
        source
        for source in sources
        if (source.context_summary or {}).get("resolver") == PRETRIP_TOOL_PLANNER_SKILL_ID
        and source.source_id != PRETRIP_TOOL_PLANNER_SKILL_ID
    ]


def _compact_tool_result(result: dict[str, Any]) -> dict[str, Any]:
    payload = result.get("payload") if isinstance(result.get("payload"), dict) else {}
    return {
        "tool_id": result.get("tool_id"),
        "status": result.get("status"),
        "implementation_status": result.get("implementation_status"),
        "output_artifact_kind": result.get("output_artifact_kind"),
        "result_count": _result_count(payload),
        "missing_fields": result.get("missing_fields") or [],
        "warnings": (result.get("warnings") or [])[:3]
        if isinstance(result.get("warnings"), list)
        else [],
        "errors": (result.get("errors") or [])[:3]
        if isinstance(result.get("errors"), list)
        else [],
        "sources": (result.get("sources") or [])[:5]
        if isinstance(result.get("sources"), list)
        else [],
        "payload_preview": _payload_preview(payload),
    }


def _tool_source_fallback_line(source: AssistantSourceRef) -> str | None:
    summary = source.context_summary or {}
    plan_item = (
        summary.get("plan_item") if isinstance(summary.get("plan_item"), dict) else {}
    )
    label = str(plan_item.get("label") or summary.get("tool_id") or source.source_id)
    status = str(summary.get("status") or "unknown")
    missing_fields = summary.get("missing_fields")
    if not isinstance(missing_fields, list):
        missing_fields = []

    if source.evidence_type == "assistant_registry_tool_contract_gap":
        gap = summary.get("implementation_gap")
        parts = [
            f"{label}: status={status}",
            f"missing_fields={','.join(str(field) for field in missing_fields) or 'none'}",
        ]
        if gap:
            parts.append(f"implementation_gap={gap}")
        return ", ".join(parts)

    latest = summary.get("latest") if isinstance(summary.get("latest"), dict) else {}
    result_count = _result_count(latest)
    top_hint = _top_payload_hint(latest)
    parts = [f"{label}: status={status}", f"result_count={result_count}"]
    latest_missing_fields = latest.get("missing_fields")
    if isinstance(latest_missing_fields, list) and latest_missing_fields:
        parts.append(
            "missing_fields="
            + ",".join(str(field) for field in latest_missing_fields)
        )
    if top_hint:
        parts.append(f"top={top_hint}")
    return ", ".join(parts)


def _result_count(payload: dict[str, Any]) -> int:
    value = payload.get("result_count")
    if isinstance(value, int):
        return value
    for key in ("results", "summaries", "matches", "items"):
        items = payload.get(key)
        if isinstance(items, list):
            return len(items)
    return 0


def _payload_preview(payload: dict[str, Any]) -> dict[str, Any]:
    preview: dict[str, Any] = {}
    for key in (
        "artifact_kind",
        "project_id",
        "query",
        "result_count",
        "searched_record_count",
        "answerability",
        "source_status",
        "missing_fields",
        "risk_summary",
        "weather_window",
        "matched_segment_count",
        "status",
    ):
        if payload.get(key) is not None:
            preview[key] = payload.get(key)
    for key in ("results", "summaries", "matches", "items"):
        value = payload.get(key)
        if isinstance(value, list) and value:
            preview[key] = value[:3]
            break
    return preview


def _top_payload_hint(payload: dict[str, Any]) -> str | None:
    for key in ("results", "summaries", "matches", "items"):
        value = payload.get(key)
        if isinstance(value, list) and value:
            first = value[0]
            if isinstance(first, dict):
                return " | ".join(
                    str(part)
                    for part in (
                        first.get("label"),
                        first.get("title"),
                        first.get("segment_id"),
                        first.get("risk_level"),
                        first.get("weather_risk"),
                        first.get("final_risk"),
                        first.get("risk_bucket"),
                        first.get("score"),
                        first.get("cp"),
                        first.get("snippet"),
                    )
                    if part is not None and part != ""
                )[:180]
            return str(first)[:180]
    return None


def _compact_kb_result(item: dict[str, Any]) -> dict[str, Any]:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return {
        "score": item.get("score"),
        "record_id": item.get("record_id"),
        "evidence_type": item.get("evidence_type"),
        "source_path": item.get("source_path"),
        "title": item.get("title"),
        "snippet": item.get("snippet"),
        "tags": item.get("tags", [])[:6] if isinstance(item.get("tags"), list) else [],
        "metadata": {
            key: metadata.get(key)
            for key in (
                "candidate_id",
                "note_category",
                "severity",
                "category",
                "lat",
                "lon",
                "ele_m",
                "cp_ref",
                "segment_ref",
                "mcp_id",
                "named_point_id",
                "nearest_cp_candidate_id",
                "nearest_cp_distance_m",
                "support_status",
                "review_required",
                "confidence",
                "review_state",
                "candidate_only",
            )
            if metadata.get(key) is not None
        },
        "runtime_safety_truth": False,
    }


def resolve_assistant_query_with_skill(
    query: ScoutAssistantQuery,
    *,
    sources: list[AssistantSourceRef],
) -> ScoutAssistantResponse | None:
    live_navigation_response = _resolve_live_navigation_nmea_scenario(
        query,
        sources=sources,
    )
    if live_navigation_response is not None:
        return live_navigation_response
    if query.surface == AssistantSurface.PRETRIP:
        cp_count_response = _resolve_pretrip_cp_count(query, sources=sources)
        if cp_count_response is not None:
            return cp_count_response
        return _resolve_pretrip_place_to_cp(query, sources=sources)
    return None


def _resolve_live_navigation_nmea_scenario(
    query: ScoutAssistantQuery,
    *,
    sources: list[AssistantSourceRef],
) -> ScoutAssistantResponse | None:
    if not _looks_like_live_navigation_danger_question(query.question):
        return None
    scenario_source = _live_navigation_nmea_scenario_source(sources)
    if scenario_source is None:
        return None
    summary = scenario_source.context_summary or {}
    evaluation = summary.get("evaluation")
    if not isinstance(evaluation, dict):
        return None
    route_match = summary.get("route_match") if isinstance(summary.get("route_match"), dict) else {}
    risk_context = summary.get("risk_context") if isinstance(summary.get("risk_context"), dict) else {}
    gnss_fix = summary.get("gnss_fix") if isinstance(summary.get("gnss_fix"), dict) else {}
    scenario_id = str(summary.get("scenario_id") or scenario_source.source_id)
    classification = str(evaluation.get("classification") or "unknown")
    distance_m = _format_distance_m(route_match.get("distance_m"))
    allowed_m = _format_distance_m(route_match.get("allowed_corridor_m"))
    risk_score = risk_context.get("score")
    risk_bucket = risk_context.get("risk_bucket")
    hdop = gnss_fix.get("hdop")
    satellites = gnss_fix.get("satellites")

    if classification == "normal_inside_corridor_low_risk":
        verdict = (
            "目前不像是站在危險邊緣：這組 NMEA fix 落在 route corridor 內，"
            "且附近 candidate risk 不是高風險。"
        )
    elif classification == "off_route_high_risk_candidate":
        verdict = (
            "是，這組 NMEA fix 支持「已偏離主路且靠近高風險邊緣」的候選判斷。"
        )
    elif classification == "inside_corridor_high_risk_candidate":
        verdict = (
            "需要警覺：這組 NMEA fix 仍在 route corridor 內，但附近 candidate risk 偏高，"
            "不能只因為接近主路就視為安全。"
        )
    elif classification == "off_route_without_high_risk":
        verdict = (
            "目前支持偏離 route corridor，但附近未匹配到高風險候選；需要更多地形或 INS/DR evidence。"
        )
    else:
        verdict = "目前 evidence 不足，無法可靠判斷是否站在危險邊緣。"

    answer = (
        f"{verdict} Scenario={scenario_id}; route_distance={distance_m or 'unknown'}; "
        f"allowed_corridor={allowed_m or 'unknown'}; "
        f"inside_corridor={str(evaluation.get('inside_corridor')).lower()}; "
        f"risk_score={risk_score if risk_score is not None else 'unknown'}; "
        f"risk_bucket={risk_bucket or 'unknown'}; hdop={hdop if hdop is not None else 'unknown'}; "
        f"satellites={satellites if satellites is not None else 'unknown'}。"
        "這是 read-only NMEA scenario probe：candidate-only，不是 runtime safety truth，"
        "沒有呼叫 /safety/*、沒有改 Phase 1 L0-L4、沒有發送 outbound。"
    )
    return ScoutAssistantResponse(
        surface=query.surface,
        answer=f"Scout AI read-only deterministic skill result: {answer}",
        sources=_skill_sources(
            sources,
            skill_id=LIVE_NAV_NMEA_SCENARIO_SKILL_ID,
            source_id=scenario_source.source_id,
        ),
        boundary=AssistantBoundary(surface=query.surface),
        limitations=[
            f"resolved_by={LIVE_NAV_NMEA_SCENARIO_SKILL_ID}",
            "Deterministic resolver used parsed NMEA route/risk context before invoking a model.",
            "NMEA scenario evidence is fixture/probe data unless captured live by hardware.",
            "Candidate-only planning evidence was not promoted to runtime safety truth.",
            "No runtime, Brain, review, outbound, or hardware state was changed.",
        ],
    )


def _live_navigation_nmea_scenario_source(
    sources: list[AssistantSourceRef],
) -> AssistantSourceRef | None:
    for source in sources:
        if source.evidence_type == "live_navigation_nmea_scenario":
            return source
        if source.source_id == "assistant_context.live_navigation_nmea_scenario":
            return source
    return None


def _looks_like_live_navigation_danger_question(question: str) -> bool:
    normalized = question.lower().replace(" ", "")
    position_terms = ("我現在", "目前", "前方", "這裡")
    route_terms = ("主路", "主線", "路線", "route", "corridor", "偏離")
    danger_terms = ("危險", "邊緣", "崩壁", "碎石", "墜崖", "風險")
    return (
        any(term in normalized for term in position_terms)
        and any(term in normalized for term in route_terms)
        and any(term in normalized for term in danger_terms)
    )


def _resolve_pretrip_cp_count(
    query: ScoutAssistantQuery,
    *,
    sources: list[AssistantSourceRef],
) -> ScoutAssistantResponse | None:
    if not _looks_like_cp_count_question(query.question):
        return None

    summary = _pretrip_context_summary(sources)
    cp_count = summary.get("cp_count") or summary.get("checkpoint_candidate_count")
    if not isinstance(cp_count, int):
        return None

    source_id = "assistant_context.pretrip"
    answer = (
        f"目前 pretrip context 有 {cp_count} 個 CP "
        "(checkpoint candidates)。這個數字使用 cp_count / "
        "checkpoint_candidate_count；它是行前候選/規劃 evidence，"
        "不是 runtime safety truth。Source: assistant_context.pretrip."
    )
    return ScoutAssistantResponse(
        surface=query.surface,
        answer=f"Scout AI read-only deterministic skill result: {answer}",
        sources=_skill_sources(
            sources,
            skill_id=PRETRIP_CP_COUNT_SKILL_ID,
            source_id=source_id,
        ),
        boundary=AssistantBoundary(surface=query.surface),
        limitations=[
            f"resolved_by={PRETRIP_CP_COUNT_SKILL_ID}",
            "Deterministic resolver used structured pretrip context before invoking a model.",
            "Candidate-only planning evidence was not promoted to runtime safety truth.",
            "No runtime, Brain, review, outbound, or hardware state was changed.",
        ],
    )


def _resolve_pretrip_place_to_cp(
    query: ScoutAssistantQuery,
    *,
    sources: list[AssistantSourceRef],
) -> ScoutAssistantResponse | None:
    if not _looks_like_place_to_cp_question(query.question):
        return None

    links = _pretrip_place_cp_links(sources)
    link = _match_place_link(query.question, links)
    if link is None:
        return None

    nearest_cp = link.get("nearest_cp_label") or link.get("nearest_cp_candidate_id")
    if not nearest_cp:
        return None

    label = str(link.get("label") or "requested place")
    distance = _format_distance_m(link.get("nearest_cp_distance_m"))
    source_id = str(link.get("mcp_id") or "assistant_context.pretrip")
    candidate_only = bool(link.get("candidate_only"))
    runtime_truth = bool(link.get("runtime_safety_truth"))
    support_status = link.get("support_status")

    answer = (
        f"{label} 在 {nearest_cp} 附近"
        f"{f'，與最近 CP 距離約 {distance}' if distance else ''}。"
        "這是 pretrip MCP-to-CP candidate evidence；"
        f"candidate_only={str(candidate_only).lower()}，"
        f"runtime_safety_truth={str(runtime_truth).lower()}。"
        f"Source: {source_id}, assistant_context.pretrip."
    )
    if support_status:
        answer += f" support_status={support_status}."

    return ScoutAssistantResponse(
        surface=query.surface,
        answer=f"Scout AI read-only deterministic skill result: {answer}",
        sources=_skill_sources(sources, source_id=source_id),
        boundary=AssistantBoundary(surface=query.surface),
        limitations=[
            f"resolved_by={PRETRIP_PLACE_TO_CP_SKILL_ID}",
            "Deterministic resolver used structured pretrip context before invoking a model.",
            "Candidate-only planning evidence was not promoted to runtime safety truth.",
            "No runtime, Brain, review, outbound, or hardware state was changed.",
        ],
    )


def _looks_like_place_to_cp_question(question: str) -> bool:
    normalized = question.lower().replace(" ", "")
    cp_terms = ("cp", "checkpoint", "檢查點")
    place_terms = ("附近", "靠近", "第幾", "哪個", "接近")
    return any(term in normalized for term in cp_terms) and any(
        term in normalized for term in place_terms
    )


def _looks_like_cp_count_question(question: str) -> bool:
    normalized = question.lower().replace(" ", "")
    cp_terms = ("cp", "checkpoint", "檢查點")
    count_terms = ("多少", "幾個", "幾個", "總數", "count", "number")
    place_to_cp_terms = ("第幾", "附近", "靠近", "哪個", "接近")
    return (
        any(term in normalized for term in cp_terms)
        and any(term in normalized for term in count_terms)
        and not any(term in normalized for term in place_to_cp_terms)
    )


def _pretrip_place_cp_links(sources: list[AssistantSourceRef]) -> list[dict[str, Any]]:
    summary = _pretrip_context_summary(sources)
    links = summary.get("major_critical_point_cp_links")
    if isinstance(links, list):
        return [link for link in links if isinstance(link, dict)]
    return []


def _pretrip_context_summary(sources: list[AssistantSourceRef]) -> dict[str, Any]:
    for source in sources:
        if source.source_id != "assistant_context.pretrip":
            continue
        context = source.context_summary or {}
        summary = context.get("summary")
        if not isinstance(summary, dict):
            continue
        return summary
    return {}


def _match_place_link(
    question: str,
    links: list[dict[str, Any]],
) -> dict[str, Any] | None:
    candidates: list[tuple[int, dict[str, Any]]] = []
    for link in links:
        for name in _place_names(link):
            if name and name in question:
                candidates.append((len(name), link))
                break
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _place_names(link: dict[str, Any]) -> list[str]:
    names: list[str] = []
    label = link.get("label")
    if isinstance(label, str):
        names.append(label)
    aliases = link.get("aliases")
    if isinstance(aliases, list):
        names.extend(alias for alias in aliases if isinstance(alias, str))
    return names


def _format_distance_m(value: Any) -> str | None:
    if not isinstance(value, (int, float)):
        return None
    if abs(float(value) - round(float(value))) < 0.001:
        return f"{float(value):.1f} m"
    return f"{float(value):.3f} m"


def _skill_sources(
    sources: list[AssistantSourceRef],
    *,
    skill_id: str = PRETRIP_PLACE_TO_CP_SKILL_ID,
    source_id: str,
) -> list[AssistantSourceRef]:
    skill_source = AssistantSourceRef(
        source_id=skill_id,
        source_path="assistant_skill_router",
        evidence_type="assistant_deterministic_skill",
        selected=True,
        context_summary={
            "resolver": skill_id,
            "source_id": source_id,
            "read_only": True,
            "runtime_safety_truth": False,
        },
    )
    return [skill_source, *sources]
