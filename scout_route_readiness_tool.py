from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


ROUTE_READINESS_TOOL_ID = "scout.ai.route_readiness.assess.v0"
ROUTE_READINESS_OUTPUT_KIND = "scout_ai_route_readiness_tool_output"
ROUTE_READINESS_REQUIRED_FIELDS = ("project_root",)
ROUTE_READINESS_OPTIONAL_FIELDS = (
    "readiness_report_path",
    "planned_eta_path",
    "resource_plan_path",
    "weather_daylight_path",
    "pretrip_package_path",
    "mission_graph_path",
    "route_comparison_path",
    "user_experience_level",
    "user_goal",
    "transport_access_plan",
    "latest_return_time",
    "team_slowest_basis_confirmed",
    "departure_time_confirmed",
    "weather_reviewed",
    "daylight_reviewed",
    "equipment_confirmed",
    "remote_contact_confirmed",
)


def assess_scout_route_readiness(
    project_root: Path | str,
    *,
    query: str = "",
    readiness_report_path: str | None = None,
    planned_eta_path: str | None = None,
    resource_plan_path: str | None = None,
    weather_daylight_path: str | None = None,
    pretrip_package_path: str | None = None,
    mission_graph_path: str | None = None,
    route_comparison_path: str | None = None,
    user_experience_level: str | None = None,
    user_goal: str | None = None,
    transport_access_plan: str | None = None,
    latest_return_time: str | None = None,
    team_slowest_basis_confirmed: bool | str | None = None,
    departure_time_confirmed: bool | str | None = None,
    weather_reviewed: bool | str | None = None,
    daylight_reviewed: bool | str | None = None,
    equipment_confirmed: bool | str | None = None,
    remote_contact_confirmed: bool | str | None = None,
) -> dict[str, Any]:
    """Assess pre-trip route readiness without granting departure approval."""

    root = Path(project_root)
    project = _load_json_object(root / "project.json")
    project_id = str(project.get("project_id") or project.get("id") or root.name)
    source_report: list[dict[str, Any]] = []

    readiness_report, readiness_source = _load_optional_json(
        root,
        explicit_path=readiness_report_path,
        project=project,
        project_ref_keys=("readiness_report_ref",),
        default_refs=("outputs/readiness_report.json",),
        source_kind="readiness_report",
        source_report=source_report,
    )
    planned_eta, planned_eta_source = _load_optional_json(
        root,
        explicit_path=planned_eta_path,
        project=project,
        project_ref_keys=("planned_eta_ref",),
        default_refs=("outputs/planned_eta.json",),
        source_kind="planned_eta",
        source_report=source_report,
    )
    resource_plan, resource_plan_source = _load_optional_json(
        root,
        explicit_path=resource_plan_path,
        project=project,
        project_ref_keys=("resource_plan_ref",),
        default_refs=("outputs/resource_plan.json",),
        source_kind="resource_plan",
        source_report=source_report,
    )
    weather_daylight, weather_source = _load_optional_json(
        root,
        explicit_path=weather_daylight_path,
        project=project,
        project_ref_keys=("weather_daylight_evidence_ref",),
        default_refs=("outputs/weather_daylight_evidence.json",),
        source_kind="weather_daylight_evidence",
        source_report=source_report,
    )
    pretrip_package, package_source = _load_optional_json(
        root,
        explicit_path=pretrip_package_path,
        project=project,
        project_ref_keys=("reviewed_package_ref", "package_ref"),
        default_refs=("outputs/pretrip_package.reviewed.json", "outputs/pretrip_package.json"),
        source_kind="pretrip_package",
        source_report=source_report,
    )
    mission_graph, mission_graph_source = _load_optional_json(
        root,
        explicit_path=mission_graph_path,
        project=project,
        project_ref_keys=("compiled_mission_graph_reviewed_ref", "compiled_mission_graph_candidate_ref"),
        default_refs=(
            "outputs/compiled_mission_graph.reviewed.json",
            "outputs/compiled_mission_graph.candidate.json",
        ),
        source_kind="compiled_mission_graph",
        source_report=source_report,
    )
    route_comparison, route_comparison_source = _load_optional_json(
        root,
        explicit_path=route_comparison_path,
        project=project,
        project_ref_keys=("route_comparison_ref",),
        default_refs=("outputs/route_comparison.json",),
        source_kind="route_comparison",
        source_report=source_report,
    )

    direct = {
        "user_experience_level": user_experience_level,
        "user_goal": user_goal,
        "transport_access_plan": transport_access_plan,
        "latest_return_time": latest_return_time,
        "team_slowest_basis_confirmed": _bool_or_none(team_slowest_basis_confirmed),
        "departure_time_confirmed": _bool_or_none(departure_time_confirmed),
        "weather_reviewed": _bool_or_none(weather_reviewed),
        "daylight_reviewed": _bool_or_none(daylight_reviewed),
        "equipment_confirmed": _bool_or_none(equipment_confirmed),
        "remote_contact_confirmed": _bool_or_none(remote_contact_confirmed),
    }
    route_state = _route_state(
        project=project,
        pretrip_package=pretrip_package,
        mission_graph=mission_graph,
        planned_eta=planned_eta,
        route_comparison=route_comparison,
    )
    readiness_state = _readiness_state(readiness_report)
    resource_state = _resource_state(resource_plan)
    weather_state = _weather_daylight_state(
        weather_daylight=weather_daylight,
        direct=direct,
    )
    input_coverage = _input_coverage(
        direct=direct,
        route_state=route_state,
        resource_state=resource_state,
        weather_state=weather_state,
    )
    missing_fields = _missing_fields(input_coverage=input_coverage)
    governance = _governance(
        route_state=route_state,
        readiness_state=readiness_state,
        resource_state=resource_state,
        weather_state=weather_state,
        input_coverage=input_coverage,
        missing_fields=missing_fields,
        direct=direct,
    )
    decision = _decision(governance=governance, missing_fields=missing_fields)
    answerability = (
        "route_readiness_missing_required_fields"
        if missing_fields
        else "route_readiness_decision_available"
    )
    field_answer = _field_answer(
        decision=decision,
        governance=governance,
        missing_fields=missing_fields,
    )
    debug_sources = {
        "readiness_source": readiness_source,
        "planned_eta_source": planned_eta_source,
        "resource_plan_source": resource_plan_source,
        "weather_daylight_source": weather_source,
        "pretrip_package_source": package_source,
        "mission_graph_source": mission_graph_source,
        "route_comparison_source": route_comparison_source,
    }
    pretrip_decision_package = _pretrip_decision_package(
        decision=decision,
        answerability=answerability,
        route_state=route_state,
        readiness_state=readiness_state,
        resource_state=resource_state,
        weather_state=weather_state,
        input_coverage=input_coverage,
        missing_fields=missing_fields,
        governance=governance,
        source_report=source_report,
        debug_sources=debug_sources,
    )
    decision_output = _decision_output(
        decision=decision,
        answerability=answerability,
        route_state=route_state,
        governance=governance,
        missing_fields=missing_fields,
        pretrip_decision_package=pretrip_decision_package,
        field_answer=field_answer,
    )

    return {
        "artifact_kind": ROUTE_READINESS_OUTPUT_KIND,
        "tool_id": ROUTE_READINESS_TOOL_ID,
        "status": "completed",
        "project_id": project_id,
        "query": query,
        "assessment_kind": "read_only_pretrip_route_readiness",
        "answerability": answerability,
        "source_status": "candidate_only",
        "decision": decision,
        "allowed": decision in {"GO", "CONDITIONAL_GO"},
        "decision_output": decision_output,
        "field_answer": field_answer,
        "missing_fields": missing_fields,
        "route_demand_profile": route_state["route_demand_profile"],
        "guided_only_gate": governance["guided_only_gate"],
        "user_goal_profile": governance["user_goal_profile"],
        "route_readiness": {
            "role": "Pre-Trip Route Readiness / Departure Gate",
            "candidate_only": True,
            "runtime_safety_truth": False,
            "departure_approval_granted": False,
            "decision": decision,
            "decision_output": decision_output,
            "critical_gaps": governance["critical_gaps"],
            "warning_gaps": governance["warning_gaps"],
            "required_conditions": governance["required_conditions"],
            "alternative_actions": governance["alternative_actions"],
            "next_action": governance["next_action"],
            "guided_only_gate": governance["guided_only_gate"],
            "user_goal_profile": governance["user_goal_profile"],
        },
        "departure_gate": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "approval_granted": False,
            "operator_trigger_required": True,
            "hard_readiness_status": readiness_state["status"],
            "hard_readiness_finding_count": readiness_state["finding_count"],
            "input_coverage": input_coverage,
        },
        "route_state": route_state,
        "readiness_state": readiness_state,
        "resource_state": resource_state,
        "weather_daylight_state": weather_state,
        "readiness_governance": governance,
        "pretrip_decision_package": pretrip_decision_package,
        "source_report": source_report,
        "result_count": 1,
        "results": [
            {
                "label": "pre-trip route readiness decision",
                "decision": decision,
                "decision_output": decision_output,
                "answerability": answerability,
                "critical_gaps": governance["critical_gaps"],
                "warning_gaps": governance["warning_gaps"],
                "field_answer": field_answer,
                "candidate_only": True,
                "runtime_safety_truth": False,
                "departure_approval_granted": False,
            }
        ],
        "standard_alignment": [
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 18 pre-trip workflow",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 18.1 required inputs",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 18.2 required outputs",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 16 required decision output format",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 17 ContextualPermission schema",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 22 required development standards",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 23 acceptance criteria",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 24.1 MVP pre-trip Go/No-Go",
        ],
        "boundary": _closed_boundary(),
        "debug_sources": debug_sources,
    }


def _decision_output(
    *,
    decision: str,
    answerability: str,
    route_state: dict[str, Any],
    governance: dict[str, Any],
    missing_fields: list[str],
    pretrip_decision_package: dict[str, Any],
    field_answer: str,
) -> dict[str, Any]:
    outputs = pretrip_decision_package.get("required_outputs")
    outputs = outputs if isinstance(outputs, dict) else {}
    limits = pretrip_decision_package.get("decision_limits")
    limits = limits if isinstance(limits, dict) else {}
    traceability = pretrip_decision_package.get("traceability")
    traceability = traceability if isinstance(traceability, dict) else {}

    allowed = bool(limits.get("allowed"))
    main_reasons = _risk_reasons(outputs.get("top_risk_sources"))
    required_conditions = _text_list(outputs.get("required_conditions"))
    alternatives = _text_list(outputs.get("alternatives_or_short_routes"))
    residual_risk = _text_list(outputs.get("residual_risk"))
    uncertainty_notes = _uncertainty_notes(
        missing_fields=missing_fields,
        traceability=traceability,
    )
    limit = _decision_limit_phrase(
        decision=decision,
        allowed=allowed,
        route_state=route_state,
        limits=limits,
    )
    next_action = str(limits.get("next_action") or governance["next_action"])
    details = _decision_details(
        outputs=outputs,
        route_state=route_state,
        field_answer=field_answer,
    )
    first_layer = {
        "decision": _decision_phrase(decision=decision, allowed=allowed),
        "limit": limit,
        "reason": " / ".join((main_reasons or ["缺少前三風險摘要"])[:2]),
        "nextStep": next_action,
    }
    second_layer = {
        "details": details,
        "uncertaintyNotes": uncertainty_notes,
        "residualRisk": residual_risk,
        "requiredConditions": required_conditions,
        "alternativeActions": alternatives,
    }
    return {
        "role": "Pre-Trip Go/No-Go Agent",
        "format": "SCOUT_OUTDOOR_AI_AGENT_STANDARD.section16",
        "decisionObjectSchema": "ContextualPermission",
        "text": "\n".join(
            (
                f"[決策] {first_layer['decision']}",
                f"[限制] {first_layer['limit']}",
                f"[原因] {first_layer['reason']}",
                f"[下一步] {first_layer['nextStep']}",
            )
        ),
        "firstLayer": first_layer,
        "secondLayer": second_layer,
        "action": "pretrip_route_readiness_departure_gate",
        "decision": decision,
        "allowed": allowed,
        "locationConstraint": limit,
        "mainReasons": main_reasons
        or ["Pre-trip readiness decision package did not expose top risks."],
        "cost": {
            "timeBufferChangeMinutes": 0 if not allowed else None,
            "daylightImpact": "Departure remains gated by daylight and review evidence.",
            "retreatImpact": "Turnaround and alternatives must remain visible before runtime handoff.",
            "teamPaceImpact": "Slowest or most vulnerable member basis is required.",
            "latestTurnaroundCheckpoint": route_state.get("turn_back_checkpoint_node_name"),
            "latestReturnDeadline": governance.get("transport_deadline", {}).get(
                "resolved_deadline"
            ),
            "targetEta": route_state.get("target_eta"),
            "mustLeaveBy": limits.get("must_leave_by"),
            "bufferCostStatement": limits.get("buffer_cost_statement"),
        },
        "nextAction": next_action,
        "confidence": "low" if uncertainty_notes else "medium",
        "uncertaintyNotes": uncertainty_notes,
        "residualRisk": residual_risk,
        "requiredConditions": required_conditions,
        "alternativeActions": alternatives,
        "answerability": answerability,
        "runtimeSafetyTruth": False,
        "departureApprovalGranted": False,
        "standardAlignment": [
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 16 required decision output format",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 17 ContextualPermission schema",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 18.2 required pre-trip outputs",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 23 acceptance criteria",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 24.1 MVP Go/No-Go",
        ],
    }


def _risk_reasons(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    reasons = []
    for item in value:
        if isinstance(item, dict):
            reason = item.get("reason")
            if isinstance(reason, str) and reason.strip():
                reasons.append(reason.strip())
    return _dedupe(reasons)


def _text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _uncertainty_notes(
    *,
    missing_fields: list[str],
    traceability: dict[str, Any],
) -> list[str]:
    notes = [f"Missing field: {field}" for field in missing_fields]
    reason_records = traceability.get("reason_records")
    if isinstance(reason_records, dict):
        warning_count = _int_or_zero(reason_records.get("warning_gap_count"))
        if warning_count:
            notes.append(f"Warning gap count: {warning_count}")
        finding_count = _int_or_zero(reason_records.get("readiness_finding_count"))
        if finding_count:
            notes.append(f"Readiness finding count: {finding_count}")
    return _dedupe(notes)


def _decision_limit_phrase(
    *,
    decision: str,
    allowed: bool,
    route_state: dict[str, Any],
    limits: dict[str, Any],
) -> str:
    if decision == "NO_GO":
        return "不得照原計畫出發；先改線、延期或解除 hard blockers。"
    if decision == "DELAY":
        return "缺口補齊與人工 departure gate 通過前，不得出發或進入 runtime handoff。"
    if decision == "CHANGE_PLAN":
        return "必須改線、改日期或降低目標 CP；不得照原計畫出發。"
    if decision == "ESCALATE":
        return "交由人工領隊/留守確認；Scout 不自動批准出發、通知或報案。"
    if decision == "GUIDED_ONLY":
        return "不得自主出發；只可在合格嚮導、領隊或等效審核控制下重新進入出發門檢。"
    if decision == "CONDITIONAL_GO":
        deadline = limits.get("must_leave_by") or route_state.get("turn_back_checkpoint_eta")
        if deadline:
            return f"必須滿足 required conditions，並在 {deadline} 前離開/折返指定 checkpoint。"
        return "必須滿足 required conditions，且出發前仍需人工 departure gate。"
    if allowed:
        return "仍需人工 departure gate；每個 CP 依 CP Graph 與天氣/日照重新確認。"
    return "不得把此候選判斷當作 departure approval 或 runtime safety truth。"


def _decision_phrase(*, decision: str, allowed: bool) -> str:
    if decision == "GO" and allowed:
        return "可進入人工出發門檢。"
    if decision == "CONDITIONAL_GO":
        return "可有條件進入人工出發門檢。"
    if decision == "GUIDED_ONLY":
        return "只建議在合格帶領下進入。"
    if decision == "CHANGE_PLAN":
        return "建議改變計畫。"
    if decision == "DELAY":
        return "建議延後。"
    if decision == "NO_GO":
        return "不建議出發。"
    if decision == "ESCALATE":
        return "升級人工確認。"
    return "暫緩判斷。"


def _decision_details(
    *,
    outputs: dict[str, Any],
    route_state: dict[str, Any],
    field_answer: str,
) -> list[str]:
    latest_turnaround = outputs.get("latest_turnaround")
    latest_turnaround = latest_turnaround if isinstance(latest_turnaround, dict) else {}
    details = [
        field_answer,
        f"cp_graph_available={bool(route_state.get('mission_graph_available'))}",
        f"checkpoint_count={route_state.get('checkpoint_count')}",
        f"segment_count={route_state.get('segment_count')}",
        f"target_eta={route_state.get('target_eta')}",
        f"latest_turnaround={latest_turnaround.get('checkpoint_name')}",
        f"latest_turnaround_deadline={latest_turnaround.get('deadline')}",
    ]
    stop_points = outputs.get("not_recommended_stop_points")
    if isinstance(stop_points, list) and stop_points:
        details.append(
            "not_recommended_stop_points="
            + " / ".join(
                str(item.get("label") if isinstance(item, dict) else item)
                for item in stop_points[:2]
            )
        )
    return details


def _route_state(
    *,
    project: dict[str, Any],
    pretrip_package: dict[str, Any],
    mission_graph: dict[str, Any],
    planned_eta: dict[str, Any],
    route_comparison: dict[str, Any],
) -> dict[str, Any]:
    package_boundary = (
        pretrip_package.get("boundary")
        if isinstance(pretrip_package.get("boundary"), dict)
        else {}
    )
    package_route_summary = (
        pretrip_package.get("route_summary")
        if isinstance(pretrip_package.get("route_summary"), dict)
        else {}
    )
    assumption = (
        planned_eta.get("assumption") if isinstance(planned_eta.get("assumption"), dict) else {}
    )
    estimates = planned_eta.get("estimates") if isinstance(planned_eta.get("estimates"), list) else []
    checkpoints = (
        mission_graph.get("checkpoints")
        if isinstance(mission_graph.get("checkpoints"), list)
        else []
    )
    segments = (
        mission_graph.get("segments") if isinstance(mission_graph.get("segments"), list) else []
    )
    return {
        "candidate_only": True,
        "runtime_safety_truth": False,
        "route_name": _first_text(
            project.get("route_name"),
            package_route_summary.get("route_name"),
            pretrip_package.get("package_id"),
        ),
        "route_role": _first_text(project.get("route_role")),
        "route_available": bool(pretrip_package or mission_graph),
        "mission_graph_available": bool(mission_graph),
        "checkpoint_count": len(checkpoints),
        "segment_count": len(segments),
        "planned_eta_available": bool(planned_eta),
        "planned_start_time": _first_text(assumption.get("planned_start_time")),
        "target_eta": _first_text(assumption.get("target_eta")),
        "turn_back_checkpoint_eta": _first_text(
            assumption.get("turn_back_checkpoint_eta")
        ),
        "turn_back_checkpoint_node_name": _first_text(
            assumption.get("turn_back_checkpoint_node_name")
        ),
        "team_multiplier_status": _first_text(assumption.get("team_multiplier_status")),
        "daylight_policy_status": _first_text(assumption.get("daylight_policy_status")),
        "eta_estimate_count": len(estimates),
        "departure_approval_granted": bool(
            package_boundary.get("departure_approval_granted")
        ),
        "departure_gate_required_before_runtime": bool(
            package_boundary.get("departure_gate_required_before_runtime")
        ),
        "reviewed_package_is_not_departure_approval": bool(
            package_boundary.get("reviewed_package_is_not_departure_approval")
        ),
        "route_comparison_only": bool(route_comparison),
        "route_demand_profile": _route_demand_profile(
            project=project,
            route_summary=package_route_summary,
            mission_graph=mission_graph,
        ),
    }


def _route_demand_profile(
    *,
    project: dict[str, Any],
    route_summary: dict[str, Any],
    mission_graph: dict[str, Any],
) -> dict[str, Any]:
    route_name = " ".join(
        text
        for text in (
            _first_text(project.get("route_name")),
            _first_text(route_summary.get("route_name")),
            _first_text(mission_graph.get("name")),
            _first_text(mission_graph.get("route_source")),
        )
        if text
    )
    distance_m = _float_or_none(route_summary.get("distance_m"))
    elevation_max_m = _float_or_none(route_summary.get("elevation_max_m"))
    elevation_min_m = _float_or_none(route_summary.get("elevation_min_m"))
    elevation_range_m = (
        round(elevation_max_m - elevation_min_m, 2)
        if elevation_max_m is not None and elevation_min_m is not None
        else None
    )
    segments = _list_of_dicts(mission_graph.get("segments"))
    max_segment_gain_m = _max_float_from_dicts(segments, "elevation_gain_m")
    max_segment_loss_m = _max_float_from_dicts(segments, "elevation_loss_m")

    demand_reasons: list[str] = []
    if distance_m is not None and distance_m >= 20000:
        demand_reasons.append(f"long_route_distance_m={distance_m:g}")
    if elevation_max_m is not None and elevation_max_m >= 3000:
        demand_reasons.append(f"high_mountain_elevation_max_m={elevation_max_m:g}")
    if elevation_range_m is not None and elevation_range_m >= 1200:
        demand_reasons.append(f"large_elevation_range_m={elevation_range_m:g}")
    if max_segment_gain_m is not None and max_segment_gain_m >= 200:
        demand_reasons.append(f"steep_segment_gain_m={max_segment_gain_m:g}")
    if max_segment_loss_m is not None and max_segment_loss_m >= 250:
        demand_reasons.append(f"steep_segment_loss_m={max_segment_loss_m:g}")
    if _has_any_text(route_name, ("縱走", "高山", "曝露", "崩壁", "拉繩", "溪谷", "technical", "exposed")):
        demand_reasons.append("route_name_or_source_indicates_advanced_terrain")

    route_demand = (
        "high" if len(demand_reasons) >= 2 else "moderate" if demand_reasons else "unknown"
    )
    return {
        "route_demand": route_demand,
        "distance_m": distance_m,
        "elevation_max_m": elevation_max_m,
        "elevation_range_m": elevation_range_m,
        "max_segment_gain_m": max_segment_gain_m,
        "max_segment_loss_m": max_segment_loss_m,
        "demand_reasons": _dedupe(demand_reasons),
        "requires_guided_for_low_experience": route_demand == "high",
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _readiness_state(readiness_report: dict[str, Any]) -> dict[str, Any]:
    findings = (
        readiness_report.get("findings")
        if isinstance(readiness_report.get("findings"), list)
        else []
    )
    blocker_count = sum(
        1
        for item in findings
        if isinstance(item, dict)
        and str(item.get("severity") or "").lower() in {"blocker", "blocked"}
    )
    warning_count = sum(
        1
        for item in findings
        if isinstance(item, dict)
        and str(item.get("severity") or "").lower() == "warning"
    )
    return {
        "candidate_only": True,
        "runtime_safety_truth": False,
        "available": bool(readiness_report),
        "status": _first_text(readiness_report.get("status")) or "missing",
        "finding_count": len(findings),
        "blocker_count": blocker_count,
        "warning_count": warning_count,
        "findings": findings[:6],
    }


def _resource_state(resource_plan: dict[str, Any]) -> dict[str, Any]:
    devices = _list_of_dicts(resource_plan.get("devices"))
    equipment = _list_of_dicts(resource_plan.get("equipment"))
    team_members = _list_of_dicts(resource_plan.get("team_members"))
    remote = (
        resource_plan.get("remote_contact_plan")
        if isinstance(resource_plan.get("remote_contact_plan"), dict)
        else {}
    )
    emergency = (
        resource_plan.get("emergency_plan")
        if isinstance(resource_plan.get("emergency_plan"), dict)
        else {}
    )
    context = (
        resource_plan.get("departure_readiness_context")
        if isinstance(resource_plan.get("departure_readiness_context"), dict)
        else {}
    )
    return {
        "candidate_only": True,
        "runtime_safety_truth": False,
        "available": bool(resource_plan),
        "device_count": len(devices),
        "equipment_count": len(equipment),
        "team_member_count": len(team_members),
        "devices_need_review": _items_need_review(devices),
        "equipment_need_review": _items_need_review(equipment),
        "team_members_need_review": _items_need_review(team_members),
        "remote_contact_needs_review": _review_state(remote) == "needs_review",
        "emergency_plan_needs_review": _review_state(emergency) == "needs_review",
        "remote_contact_secret_details_included": bool(
            remote.get("secret_contact_details_included")
        ),
        "emergency_secret_details_included": bool(
            emergency.get("secret_contact_details_included")
        ),
        "blocker_candidates": _normalized_text_list(context.get("blocker_candidates")),
        "warning_candidates": _normalized_text_list(context.get("warning_candidates")),
        "blocks_existing_eta_or_readiness": bool(
            context.get("blocks_existing_eta_or_readiness")
        ),
        "hard_readiness_mutation_allowed": bool(
            context.get("hard_readiness_mutation_allowed")
        ),
    }


def _weather_daylight_state(
    *,
    weather_daylight: dict[str, Any],
    direct: dict[str, Any],
) -> dict[str, Any]:
    daylight = (
        weather_daylight.get("daylight")
        if isinstance(weather_daylight.get("daylight"), dict)
        else {}
    )
    weather_window = (
        weather_daylight.get("weather_window")
        if isinstance(weather_daylight.get("weather_window"), dict)
        else {}
    )
    validation = (
        weather_daylight.get("validation")
        if isinstance(weather_daylight.get("validation"), dict)
        else {}
    )
    human_review_required = bool(weather_daylight.get("human_review_required"))
    authoritative = bool(weather_daylight.get("authoritative_weather_computed"))
    weather_reviewed = _first_bool(
        direct.get("weather_reviewed"),
        validation.get("validation_status") in {"reviewed", "accepted"},
        authoritative and not human_review_required,
    )
    daylight_reviewed = _first_bool(
        direct.get("daylight_reviewed"),
        daylight.get("source_status") in {"reviewed", "accepted", "computed"},
        bool(daylight.get("sunrise") and daylight.get("sunset")) and not human_review_required,
    )
    return {
        "candidate_only": True,
        "runtime_safety_truth": False,
        "available": bool(weather_daylight),
        "date": _first_text(weather_daylight.get("date")),
        "timezone": _first_text(weather_daylight.get("timezone")),
        "authoritative_weather_computed": authoritative,
        "human_review_required": human_review_required,
        "weather_reviewed": bool(weather_reviewed),
        "daylight_reviewed": bool(daylight_reviewed),
        "weather_source_status": _first_text(weather_window.get("source_status")),
        "daylight_source_status": _first_text(daylight.get("source_status")),
        "validation_status": _first_text(validation.get("validation_status")),
        "hazard_notes": _normalized_text_list(weather_window.get("hazard_notes")),
    }


def _input_coverage(
    *,
    direct: dict[str, Any],
    route_state: dict[str, Any],
    resource_state: dict[str, Any],
    weather_state: dict[str, Any],
) -> dict[str, bool]:
    return {
        "route": bool(route_state.get("route_available")),
        "date": bool(weather_state.get("date") or route_state.get("planned_start_time")),
        "team": bool(resource_state.get("team_member_count")),
        "user_experience": bool(_first_text(direct.get("user_experience_level"))),
        "user_goal": bool(_goal_profile(direct.get("user_goal"))["goals"]),
        "equipment": bool(resource_state.get("equipment_count")),
        "transport_access": bool(
            _first_text(direct.get("transport_access_plan"))
            or _first_text(direct.get("latest_return_time"))
        ),
        "planned_departure_time": bool(route_state.get("planned_start_time")),
        "weather": bool(weather_state.get("available")),
        "daylight": bool(weather_state.get("available")),
        "cp_graph": bool(
            route_state.get("checkpoint_count") and route_state.get("segment_count")
        ),
        "turn_back_checkpoint": bool(route_state.get("turn_back_checkpoint_node_name")),
        "slowest_team_basis": bool(direct.get("team_slowest_basis_confirmed"))
        or route_state.get("team_multiplier_status") not in {
            None,
            "not_derived_no_human_stats",
        },
        "departure_time_confirmed": bool(direct.get("departure_time_confirmed")),
        "weather_reviewed": bool(weather_state.get("weather_reviewed")),
        "daylight_reviewed": bool(weather_state.get("daylight_reviewed")),
        "equipment_confirmed": bool(direct.get("equipment_confirmed"))
        or (
            resource_state.get("equipment_count")
            and not resource_state.get("equipment_need_review")
        ),
        "remote_contact_confirmed": bool(direct.get("remote_contact_confirmed"))
        or not resource_state.get("remote_contact_needs_review"),
    }


def _missing_fields(*, input_coverage: dict[str, bool]) -> list[str]:
    required = {
        "route": "route",
        "date": "route_date",
        "team": "team_members",
        "user_experience": "user_experience_level",
        "user_goal": "user_goal",
        "equipment": "equipment_inventory",
        "transport_access": "transport_access_plan",
        "planned_departure_time": "planned_departure_time",
        "weather": "weather_evidence",
        "daylight": "daylight_window",
        "cp_graph": "cp_graph",
        "turn_back_checkpoint": "turn_back_checkpoint",
        "slowest_team_basis": "slowest_team_basis",
        "departure_time_confirmed": "departure_time_confirmation",
        "weather_reviewed": "weather_review",
        "daylight_reviewed": "daylight_review",
        "equipment_confirmed": "equipment_review",
        "remote_contact_confirmed": "remote_contact_review",
    }
    return [label for key, label in required.items() if not input_coverage.get(key)]


def _governance(
    *,
    route_state: dict[str, Any],
    readiness_state: dict[str, Any],
    resource_state: dict[str, Any],
    weather_state: dict[str, Any],
    input_coverage: dict[str, bool],
    missing_fields: list[str],
    direct: dict[str, Any],
) -> dict[str, Any]:
    critical_gaps: list[str] = []
    warning_gaps: list[str] = []
    required_conditions: list[str] = []
    alternative_actions: list[str] = []
    user_experience = _normalized_experience_level(direct.get("user_experience_level"))
    user_goal_profile = _goal_profile(direct.get("user_goal"))
    latest_return_deadline = _latest_return_deadline(
        direct.get("latest_return_time"),
        route_state=route_state,
    )
    transport_deadline_conflict = _transport_deadline_conflict(
        latest_return_deadline=latest_return_deadline,
        route_state=route_state,
    )
    route_demand_profile = (
        route_state.get("route_demand_profile")
        if isinstance(route_state.get("route_demand_profile"), dict)
        else {}
    )
    guided_only_required = (
        bool(route_demand_profile.get("requires_guided_for_low_experience"))
        and user_experience in {"beginner", "novice", "first_time", "low"}
    )

    if readiness_state["status"] == "blocked" or readiness_state["blocker_count"]:
        critical_gaps.append("Hard readiness report contains blocker findings.")
        required_conditions.append("Resolve hard readiness blockers before departure.")
    if not route_state.get("mission_graph_available"):
        critical_gaps.append("MissionGraph / CP Graph is not available.")
    if resource_state.get("remote_contact_secret_details_included") or resource_state.get(
        "emergency_secret_details_included"
    ):
        critical_gaps.append("Resource plan contains secret contact details in Scout AI payload.")
    if resource_state.get("blocker_candidates"):
        critical_gaps.extend(resource_state["blocker_candidates"][:3])

    if transport_deadline_conflict:
        warning_gaps.append(
            "Planned target ETA is later than the latest return transport limit."
        )
        required_conditions.append(
            "Change the route, target CP, date, departure time, or transport plan before departure."
        )
        alternative_actions.append(
            "Shorten the route or set an earlier turn-back checkpoint that preserves the return transport deadline."
        )
    if readiness_state["status"] == "warning" or readiness_state["warning_count"]:
        warning_gaps.append("Hard readiness report contains warning findings.")
    if guided_only_required:
        warning_gaps.append(
            "Route demand is high for a beginner or low-experience user; autonomous departure is not recommended."
        )
        required_conditions.append(
            "Use a qualified guide, experienced leader, or equivalent reviewed controls before considering this route."
        )
        alternative_actions.append(
            "Switch to a guided trip, lower-demand route, shorter route, or training route."
        )
    if user_goal_profile["photo_or_social_goal"]:
        warning_gaps.append(
            "使用者目標包含拍攝、社交或慢行停留，需先轉成已審核 CP 停留點與停留上限。"
        )
        required_conditions.append(
            "將拍攝/社交/慢行目標限制在已審核 CP 或觀察點，並設定每次停留上限。"
        )
        alternative_actions.append(
            "把拍攝或社交目標改成低曝露 CP 內短停，或改選較短路線。"
        )
    if user_goal_profile["family_or_child_goal"]:
        warning_gaps.append(
            "親子或家庭目標需要更保守的撤退、避難與短版路線。"
        )
        required_conditions.append(
            "親子/家庭行程必須預先指定較短替代路線、避風休息點與提前撤退門檻。"
        )
        alternative_actions.append(
            "改成親子友善短線、較低海拔或有明確撤退支援的訓練路線。"
        )
    if user_goal_profile["summit_goal"] and not route_state.get(
        "turn_back_checkpoint_node_name"
    ):
        warning_gaps.append("攻頂目標缺少明確折返點，不應照原計畫推進。")
        required_conditions.append("補上攻頂前硬性折返點與山頂停留時間上限。")
        alternative_actions.append("改成不攻頂或只到已審核折返 CP 的短版路線。")
    if route_state.get("departure_gate_required_before_runtime"):
        warning_gaps.append("Reviewed planning package is not departure approval.")
        required_conditions.append("Run an explicit departure gate before runtime handoff.")
    if (
        route_state.get("team_multiplier_status") == "not_derived_no_human_stats"
        and not input_coverage.get("slowest_team_basis")
    ):
        warning_gaps.append("Team multiplier / slowest-member basis is not derived.")
        required_conditions.append("Confirm slowest team member basis before Go/No-Go.")
    if route_state.get("daylight_policy_status") == "not_evaluated_requires_sun_window":
        warning_gaps.append("Daylight policy has not been evaluated against a sun window.")
    if weather_state.get("human_review_required"):
        warning_gaps.append("Weather/daylight evidence still requires human review.")
    if resource_state.get("warning_candidates"):
        warning_gaps.extend(resource_state["warning_candidates"][:3])
    if resource_state.get("devices_need_review"):
        warning_gaps.append("Some device readiness entries still need review.")
    if resource_state.get("equipment_need_review"):
        warning_gaps.append("Some required equipment/resource entries still need review.")
    if resource_state.get("team_members_need_review"):
        warning_gaps.append("Some team member inputs still need review.")
    if resource_state.get("remote_contact_needs_review"):
        warning_gaps.append("Remote contact plan still needs review.")
    if resource_state.get("emergency_plan_needs_review"):
        warning_gaps.append("Emergency plan still needs review.")
    if missing_fields:
        required_conditions.extend(f"Provide {field}." for field in missing_fields)
    if not input_coverage.get("transport_access"):
        alternative_actions.append("Delay departure until traffic/access plan is confirmed.")
    if not input_coverage.get("weather_reviewed"):
        alternative_actions.append("Delay or change date until weather evidence is reviewed.")
    if not input_coverage.get("slowest_team_basis"):
        alternative_actions.append("Recompute ETA using the slowest/most vulnerable member.")
    alternative_actions.extend(
        [
            "Use shorter route or lower target CP if review gaps remain.",
            "Keep reviewed package as planning evidence only until departure gate passes.",
        ]
    )

    return {
        "critical_gaps": _dedupe(critical_gaps),
        "warning_gaps": _dedupe(warning_gaps)[:8],
        "required_conditions": _dedupe(required_conditions),
        "alternative_actions": _dedupe(alternative_actions),
        "next_action": _next_action(
            critical_gaps=critical_gaps,
            missing_fields=missing_fields,
            warning_gaps=warning_gaps,
            guided_only_required=guided_only_required,
        ),
        "guided_only_gate": {
            "required": guided_only_required,
            "user_experience_level": user_experience,
            "route_demand_profile": route_demand_profile,
            "autonomous_departure_allowed": False if guided_only_required else None,
        },
        "user_goal_profile": user_goal_profile,
        "transport_deadline": {
            "latest_return_time": _first_text(direct.get("latest_return_time")),
            "resolved_deadline": latest_return_deadline,
            "target_eta": route_state.get("target_eta"),
            "conflict": transport_deadline_conflict,
        },
        "plan_change_required": transport_deadline_conflict,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "departure_approval_granted": False,
    }


def _decision(*, governance: dict[str, Any], missing_fields: list[str]) -> str:
    if governance["critical_gaps"]:
        return "NO_GO"
    if governance.get("plan_change_required"):
        return "CHANGE_PLAN"
    if missing_fields:
        return "DELAY"
    if governance.get("guided_only_gate", {}).get("required"):
        return "GUIDED_ONLY"
    if governance["warning_gaps"] or governance["required_conditions"]:
        return "CONDITIONAL_GO"
    return "GO"


def _latest_return_deadline(
    value: Any,
    *,
    route_state: dict[str, Any],
) -> str | None:
    text = _first_text(value)
    if not text:
        return None
    parsed = _parse_datetime(text)
    if parsed is not None:
        return parsed.isoformat()
    if ":" not in text:
        return text
    hour_text, minute_text = text.split(":", 1)
    try:
        hour = int(hour_text)
        minute = int(minute_text[:2])
    except ValueError:
        return text
    base = _parse_datetime(route_state.get("target_eta")) or _parse_datetime(
        route_state.get("planned_start_time")
    )
    if base is None:
        return text
    return base.replace(hour=hour, minute=minute, second=0, microsecond=0).isoformat()


def _transport_deadline_conflict(
    *,
    latest_return_deadline: str | None,
    route_state: dict[str, Any],
) -> bool:
    deadline = _parse_datetime(latest_return_deadline)
    target_eta = _parse_datetime(route_state.get("target_eta"))
    if deadline is None or target_eta is None:
        return False
    return target_eta > deadline


def _pretrip_decision_package(
    *,
    decision: str,
    answerability: str,
    route_state: dict[str, Any],
    readiness_state: dict[str, Any],
    resource_state: dict[str, Any],
    weather_state: dict[str, Any],
    input_coverage: dict[str, bool],
    missing_fields: list[str],
    governance: dict[str, Any],
    source_report: list[dict[str, Any]],
    debug_sources: dict[str, str | None],
) -> dict[str, Any]:
    """Materialize the Sec. 18.2 required pre-trip outputs."""

    top_risks = _top_risk_sources(
        governance=governance,
        missing_fields=missing_fields,
        weather_state=weather_state,
        resource_state=resource_state,
    )
    required_conditions = _dedupe(
        list(governance["required_conditions"])
        or ["Pass explicit human departure gate before runtime handoff."]
    )
    residual_risk = _residual_risk(
        governance=governance,
        weather_state=weather_state,
        readiness_state=readiness_state,
    )
    stop_policy = _stop_policy(
        decision=decision,
        route_state=route_state,
        governance=governance,
        missing_fields=missing_fields,
        debug_sources=debug_sources,
    )
    return {
        "schema_version": "scout_pretrip_decision_package.v1",
        "standard_alignment": [
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 18.2 required outputs",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 23 acceptance criteria",
        ],
        "candidate_only": True,
        "runtime_safety_truth": False,
        "departure_approval_granted": False,
        "human_review_required": True,
        "answerability": answerability,
        "required_outputs": {
            "pretrip_decision": decision,
            "guided_only_gate": governance.get("guided_only_gate"),
            "user_goal_profile": governance["user_goal_profile"],
            "top_risk_sources": top_risks,
            "required_conditions": required_conditions,
            "cp_graph": {
                "available": bool(route_state.get("mission_graph_available")),
                "checkpoint_count": route_state.get("checkpoint_count"),
                "segment_count": route_state.get("segment_count"),
                "source_ref": debug_sources.get("mission_graph_source"),
            },
            "latest_turnaround": {
                "available": bool(route_state.get("turn_back_checkpoint_node_name")),
                "checkpoint_name": route_state.get("turn_back_checkpoint_node_name"),
                "deadline": route_state.get("turn_back_checkpoint_eta"),
                "source_ref": debug_sources.get("planned_eta_source"),
            },
            "suggested_stop_points": stop_policy["suggested_stop_points"],
            "not_recommended_stop_points": stop_policy["not_recommended_stop_points"],
            "alternatives_or_short_routes": list(governance["alternative_actions"]),
            "pretrip_checklist": _pretrip_checklist(
                input_coverage=input_coverage,
                resource_state=resource_state,
                weather_state=weather_state,
            ),
            "residual_risk": residual_risk,
        },
        "decision_limits": {
            "allowed": decision in {"GO", "CONDITIONAL_GO"},
            "autonomous_departure_allowed": decision not in {"GUIDED_ONLY", "NO_GO", "DELAY", "CHANGE_PLAN", "ESCALATE"},
            "must_leave_by": route_state.get("turn_back_checkpoint_eta"),
            "turnaround_checkpoint": route_state.get("turn_back_checkpoint_node_name"),
            "buffer_cost_statement": _buffer_cost_statement(
                decision=decision,
                missing_fields=missing_fields,
                governance=governance,
            ),
            "next_action": governance["next_action"],
        },
        "traceability": {
            "source_refs": {
                key: value
                for key, value in debug_sources.items()
                if value is not None
            },
            "source_kinds_loaded": [
                item["source_kind"]
                for item in source_report
                if item.get("status") == "loaded"
            ],
            "reason_records": {
                "critical_gap_count": len(governance["critical_gaps"]),
                "warning_gap_count": len(governance["warning_gaps"]),
                "missing_field_count": len(missing_fields),
                "readiness_finding_count": readiness_state.get("finding_count"),
            },
            "raw_payloads_embedded": False,
        },
        "acceptance_coverage": {
            "explicit_decision": decision
            in {"GO", "CONDITIONAL_GO", "GUIDED_ONLY", "CHANGE_PLAN", "DELAY", "NO_GO", "ESCALATE"},
            "limits_or_action_restrictions_included": True,
            "buffer_cost_included": True,
            "uncertainty_handled_conservatively": answerability.endswith(
                "missing_required_fields"
            )
            or decision in {"GUIDED_ONLY", "DELAY", "NO_GO", "CHANGE_PLAN", "ESCALATE"},
            "slowest_member_basis_required": bool(
                input_coverage.get("slowest_team_basis")
            )
            or "slowest_team_basis" in missing_fields,
            "traceable_inputs_recorded": True,
        },
        "boundary": _closed_boundary(),
    }


def _top_risk_sources(
    *,
    governance: dict[str, Any],
    missing_fields: list[str],
    weather_state: dict[str, Any],
    resource_state: dict[str, Any],
) -> list[dict[str, str]]:
    risks: list[dict[str, str]] = []
    for reason in governance["critical_gaps"]:
        risks.append(
            {
                "severity": "critical",
                "source": "readiness_governance",
                "reason": reason,
            }
        )
    transport_deadline = governance.get("transport_deadline")
    if isinstance(transport_deadline, dict) and transport_deadline.get("conflict"):
        risks.append(
            {
                "severity": "plan_change_required",
                "source": "transport_deadline",
                "reason": (
                    "Target ETA "
                    + str(transport_deadline.get("target_eta"))
                    + " is later than latest return deadline "
                    + str(transport_deadline.get("resolved_deadline"))
                    + "."
                ),
            }
        )
    for field in missing_fields:
        risks.append(
            {
                "severity": "blocking_gap",
                "source": "required_pretrip_input",
                "reason": f"Missing required pre-trip input: {field}.",
            }
        )
    for reason in governance["warning_gaps"]:
        risks.append(
            {
                "severity": "warning",
                "source": "readiness_governance",
                "reason": reason,
            }
        )
    for note in weather_state.get("hazard_notes", []):
        risks.append(
            {
                "severity": "weather_uncertainty",
                "source": "weather_daylight_evidence",
                "reason": str(note),
            }
        )
    for reason in resource_state.get("warning_candidates", []):
        risks.append(
            {
                "severity": "resource_review",
                "source": "resource_plan",
                "reason": str(reason),
            }
        )
    if not risks:
        risks.append(
            {
                "severity": "residual",
                "source": "departure_gate",
                "reason": "Outdoor conditions can change after pre-trip review; final human departure gate is still required.",
            }
        )
    ranked = []
    for index, item in enumerate(_dedupe_risk_dicts(risks)[:3], start=1):
        ranked.append({"rank": str(index), **item})
    return ranked


def _residual_risk(
    *,
    governance: dict[str, Any],
    weather_state: dict[str, Any],
    readiness_state: dict[str, Any],
) -> list[str]:
    risks = []
    if governance["warning_gaps"]:
        risks.extend(governance["warning_gaps"][:4])
    if weather_state.get("human_review_required"):
        risks.append("Weather/daylight evidence remains human-review-required.")
    if readiness_state.get("warning_count"):
        risks.append("Hard readiness warnings remain present.")
    risks.append(
        "Reviewed pre-trip evidence is not departure approval or runtime safety truth."
    )
    return _dedupe(risks)


def _stop_policy(
    *,
    decision: str,
    route_state: dict[str, Any],
    governance: dict[str, Any],
    missing_fields: list[str],
    debug_sources: dict[str, str | None],
) -> dict[str, list[dict[str, Any]]]:
    suggested = []
    turnaround = route_state.get("turn_back_checkpoint_node_name")
    if turnaround:
        suggested.append(
            {
                "label": turnaround,
                "policy": "turnaround_or_reassess",
                "latest_leave_time": route_state.get("turn_back_checkpoint_eta"),
                "rationale": "Use this checkpoint as the explicit turn-back or reassessment point.",
                "source_ref": debug_sources.get("planned_eta_source"),
            }
        )
    if decision in {"GO", "CONDITIONAL_GO"}:
        suggested.append(
            {
                "label": "Reviewed CP rest stops only",
                "policy": "short_stop_with_departure_gate_limits",
                "latest_leave_time": route_state.get("turn_back_checkpoint_eta"),
                "rationale": "Only reviewed CPs may be used for discretionary rest before runtime admission.",
                "source_ref": debug_sources.get("mission_graph_source"),
            }
        )

    not_recommended = []
    goal_profile = governance.get("user_goal_profile")
    if isinstance(goal_profile, dict):
        goal_labels = [
            str(label)
            for label in goal_profile.get("goal_labels", [])
            if str(label).strip()
        ]
        if goal_profile.get("photo_or_social_goal"):
            not_recommended.append(
                {
                    "label": "Unreviewed user-goal discretionary stops",
                    "policy": "not_recommended_until_goal_limits_reviewed",
                    "rationale": (
                        "Photo, social, or slow-travel goals must be converted "
                        "into reviewed CP stop limits before departure."
                    ),
                    "goal_labels": goal_labels,
                }
            )
        if goal_profile.get("family_or_child_goal"):
            not_recommended.append(
                {
                    "label": "Family/child trip without conservative controls",
                    "policy": "not_recommended_until_family_controls_reviewed",
                    "rationale": (
                        "Family or child trips need a reviewed short-route, "
                        "shelter, and earlier turn-back policy."
                    ),
                    "goal_labels": goal_labels,
                }
            )
    if missing_fields or governance["warning_gaps"] or decision not in {"GO"}:
        not_recommended.append(
            {
                "label": "Unplanned photo, lunch, summit, or waiting stops",
                "policy": "not_recommended_until_reviewed",
                "rationale": "Required inputs, review state, or buffer limits are not fully proven.",
            }
        )
    if decision == "GUIDED_ONLY":
        not_recommended.append(
            {
                "label": "Autonomous departure without qualified guide or reviewed controls",
                "policy": "not_recommended_guided_only",
                "rationale": "Current pre-trip decision requires guided or equivalent support.",
            }
        )
    if decision in {"NO_GO", "DELAY", "CHANGE_PLAN", "ESCALATE", "GUIDED_ONLY"}:
        not_recommended.append(
            {
                "label": "Leaving the trailhead under the original plan",
                "policy": "not_recommended",
                "rationale": f"Current pre-trip decision is {decision}.",
            }
        )
    return {
        "suggested_stop_points": suggested,
        "not_recommended_stop_points": not_recommended,
    }


def _pretrip_checklist(
    *,
    input_coverage: dict[str, bool],
    resource_state: dict[str, Any],
    weather_state: dict[str, Any],
) -> list[dict[str, str]]:
    checks = [
        ("route", "Route loaded"),
        ("date", "Trip date / departure date known"),
        ("team", "Team roster present"),
        ("user_experience", "Member experience reviewed"),
        ("user_goal", "User trip goal reviewed"),
        ("equipment", "Equipment inventory present"),
        ("transport_access", "Transport and latest return limit confirmed"),
        ("planned_departure_time", "Planned departure time confirmed"),
        ("weather_reviewed", "Weather reviewed"),
        ("daylight_reviewed", "Daylight window reviewed"),
        ("cp_graph", "CP Graph compiled"),
        ("turn_back_checkpoint", "Latest turnaround checkpoint available"),
        ("slowest_team_basis", "Slowest or most vulnerable member basis confirmed"),
        ("equipment_confirmed", "Equipment review complete"),
        ("remote_contact_confirmed", "Remote contact / emergency plan reviewed"),
    ]
    checklist = [
        {
            "item": label,
            "status": "complete" if input_coverage.get(key) else "missing_or_needs_review",
        }
        for key, label in checks
    ]
    if resource_state.get("devices_need_review"):
        checklist.append(
            {
                "item": "Device readiness review",
                "status": "needs_review",
            }
        )
    if weather_state.get("human_review_required"):
        checklist.append(
            {
                "item": "Human weather/daylight review",
                "status": "required",
            }
        )
    return checklist


def _buffer_cost_statement(
    *,
    decision: str,
    missing_fields: list[str],
    governance: dict[str, Any],
) -> str:
    if decision in {"NO_GO", "DELAY", "CHANGE_PLAN", "ESCALATE"}:
        return (
            "No discretionary stop, photo, lunch, summit, or waiting buffer is granted "
            "until required gaps are resolved and the departure gate is rerun."
        )
    if decision == "GUIDED_ONLY":
        return (
            "No autonomous route, stop, summit, photo, lunch, or waiting buffer is granted "
            "until guide support or equivalent reviewed controls are confirmed."
        )
    if missing_fields or governance["warning_gaps"]:
        return (
            "Any discretionary stop consumes route/daylight buffer and must stay within "
            "the reviewed departure-gate limit."
        )
    return "Discretionary stops still consume buffer; use CP Graph limits before extending any stop."


def _dedupe_risk_dicts(values: list[dict[str, str]]) -> list[dict[str, str]]:
    seen = set()
    result = []
    for value in values:
        key = (value.get("severity"), value.get("source"), value.get("reason"))
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _field_answer(
    *,
    decision: str,
    governance: dict[str, Any],
    missing_fields: list[str],
) -> str:
    if missing_fields and not governance["critical_gaps"]:
        return (
            "出發前判斷：建議 DELAY。缺少 "
            + "、".join(missing_fields)
            + "；Scout 不能在路線、日期、隊伍、經驗、裝備、交通、天氣/日照或最慢者基準不完整時給出出發批准。"
        )
    if decision == "GUIDED_ONLY":
        gate = governance.get("guided_only_gate", {})
        demand = gate.get("route_demand_profile") if isinstance(gate, dict) else {}
        demand_reasons = (
            demand.get("demand_reasons") if isinstance(demand, dict) else []
        )
        reason_text = "；".join(str(reason) for reason in demand_reasons[:2]) or "路線需求高於目前自主經驗。"
        return (
            "出發前判斷：建議 GUIDED_ONLY。"
            f"{reason_text} "
            "以目前使用者經驗，不建議自主出發；只能改成合格嚮導、經驗領隊或等效審核控制下的方案。 "
            f"下一步：{governance['next_action']} "
            "此為 pre-trip route readiness 候選判斷，不是 departure approval 或 runtime safety truth；不會啟動 runtime handoff、/safety、SOS、outbound send 或硬體控制。"
        )
    reasons = governance["critical_gaps"] or governance["warning_gaps"] or ["出發前資料未顯示主要阻礙。"]
    return (
        f"出發前判斷：建議 {decision}。"
        f"{'；'.join(reasons[:2])} "
        f"下一步：{governance['next_action']} "
        "此為 pre-trip route readiness 候選判斷，不是 departure approval 或 runtime safety truth；不會啟動 runtime handoff、/safety、SOS、outbound send 或硬體控制。"
    )


def _next_action(
    *,
    critical_gaps: list[str],
    missing_fields: list[str],
    warning_gaps: list[str],
    guided_only_required: bool = False,
) -> str:
    if critical_gaps:
        return "先解除 hard blocker 或重新規劃，不進入出發。"
    if missing_fields:
        return "補齊出發前必要輸入與人工 review，再重新評估。"
    if guided_only_required:
        return "改成合格嚮導/經驗領隊帶領，或改選較短、低曝露、低海拔的訓練路線。"
    if warning_gaps:
        return "通過人工 departure gate 並保留替代路線/撤退策略後才可條件式出發。"
    return "完成人工 departure gate 後，才允許進入 runtime handoff。"


def _load_optional_json(
    root: Path,
    *,
    explicit_path: str | None,
    project: dict[str, Any],
    project_ref_keys: tuple[str, ...],
    default_refs: tuple[str, ...],
    source_kind: str,
    source_report: list[dict[str, Any]],
) -> tuple[dict[str, Any], str | None]:
    refs = []
    if explicit_path:
        refs.append(explicit_path)
    refs.extend(str(project[key]) for key in project_ref_keys if project.get(key))
    refs.extend(default_refs)
    for ref in refs:
        path = _project_path(root, ref)
        payload = _load_json_object(path)
        if payload:
            source_report.append(
                {
                    "source_kind": source_kind,
                    "status": "loaded",
                    "source_path": ref,
                    "loaded_count": 1,
                    "raw_payloads_embedded": False,
                }
            )
            return payload, ref
    source_report.append(
        {
            "source_kind": source_kind,
            "status": "missing",
            "source_path": None,
            "loaded_count": 0,
            "raw_payloads_embedded": False,
        }
    )
    return {}, None


def _project_path(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _load_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = _load_json(path)
    return payload if isinstance(payload, dict) else {}


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _max_float_from_dicts(items: list[dict[str, Any]], key: str) -> float | None:
    values = [
        parsed
        for item in items
        if (parsed := _float_or_none(item.get(key))) is not None
    ]
    return round(max(values), 2) if values else None


def _items_need_review(items: list[dict[str, Any]]) -> list[str]:
    result = []
    for item in items:
        if _review_state(item) == "needs_review":
            result.append(str(item.get("device_id") or item.get("equipment_id") or item.get("member_id") or item.get("id") or "unknown"))
    return result


def _review_state(payload: dict[str, Any]) -> str | None:
    review = payload.get("review") if isinstance(payload.get("review"), dict) else {}
    return _first_text(review.get("review_state"), payload.get("review_state"))


def _normalized_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return [str(value).strip()] if str(value).strip() else []


def _first_text(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _parse_datetime(value: Any) -> datetime | None:
    text = _first_text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_bool(*values: Any) -> bool | None:
    for value in values:
        parsed = _bool_or_none(value)
        if parsed is not None:
            return parsed
    return None


def _bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y", "ok", "ready", "reviewed", "accepted"}:
        return True
    if normalized in {"0", "false", "no", "n", "missing", "unknown", "needs_review"}:
        return False
    return None


def _int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _normalized_experience_level(value: Any) -> str | None:
    text = str(value or "").strip().lower().replace(" ", "_")
    if not text:
        return None
    if text in {"beginner", "novice", "first_time", "first-timer", "low"}:
        return text.replace("-", "_")
    if any(fragment in text for fragment in ("新手", "初學", "初次", "第一次")):
        return "beginner"
    if any(fragment in text for fragment in ("低經驗", "經驗不足", "不熟")):
        return "low"
    if any(fragment in text for fragment in ("intermediate", "中級", "regular")):
        return "intermediate"
    if any(fragment in text for fragment in ("advanced", "experienced", "資深", "高經驗")):
        return "advanced"
    return text


def _goal_profile(value: Any) -> dict[str, Any]:
    raw_goal = _first_text(value)
    goals = _normalized_goals(raw_goal)
    goal_labels = [_goal_label(goal) for goal in goals]
    return {
        "candidate_only": True,
        "runtime_safety_truth": False,
        "raw_goal": raw_goal,
        "goals": goals,
        "goal_labels": goal_labels,
        "summit_goal": "summit" in goals,
        "photo_or_social_goal": bool(set(goals) & {"photo", "slow", "social"}),
        "family_or_child_goal": bool(set(goals) & {"family", "child"}),
        "training_goal": "training" in goals,
    }


def _normalized_goals(value: str | None) -> list[str]:
    text = (value or "").strip()
    if not text:
        return []
    goals: list[str] = []

    def add(goal: str) -> None:
        if goal not in goals:
            goals.append(goal)

    if _has_any_text(text, ("攻頂", "登頂", "山頂", "summit")):
        add("summit")
    if _has_any_text(
        text,
        ("拍攝", "拍照", "攝影", "photo", "photography", "film", "video"),
    ):
        add("photo")
    if _has_any_text(text, ("慢行", "慢走", "慢遊", "slow")):
        add("slow")
    if _has_any_text(text, ("訓練", "練習", "training", "train")):
        add("training")
    if _has_any_text(
        text,
        ("親子", "家庭", "小孩", "孩子", "兒童", "family", "child", "kids"),
    ):
        add("family")
    if _has_any_text(text, ("社交", "朋友", "團體", "social", "friends")):
        add("social")
    return goals


def _goal_label(goal: str) -> str:
    labels = {
        "summit": "攻頂",
        "photo": "拍攝",
        "slow": "慢行",
        "training": "訓練",
        "family": "親子/家庭",
        "child": "親子/家庭",
        "social": "社交",
    }
    return labels.get(goal, goal)


def _has_any_text(value: str, fragments: tuple[str, ...]) -> bool:
    normalized = value.lower().replace(" ", "")
    return any(fragment.lower().replace(" ", "") in normalized for fragment in fragments)


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _closed_boundary() -> dict[str, bool]:
    return {
        "read_only": True,
        "runtime_safety_truth": False,
        "live_safety_api_calls_allowed": False,
        "phase1_safety_mutation_allowed": False,
        "remote_outbound_send_allowed": False,
        "hardware_control_allowed": False,
        "raw_payloads_embedded": False,
        "model_output_is_runtime_truth": False,
        "safety_api_called": False,
        "phase1_l0_l4_state_mutated": False,
        "departure_approval_granted": False,
        "runtime_handoff_performed": False,
        "phase2_brain_write_performed": False,
    }
