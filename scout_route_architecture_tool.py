from __future__ import annotations

import json
import math
import re
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean
from typing import Any


ROUTE_ARCHITECTURE_TOOL_ID = "scout.ai.route_architecture.assess.v0"
ROUTE_ARCHITECTURE_OUTPUT_KIND = "scout_ai_route_architecture_tool_output"
ROUTE_ARCHITECTURE_REQUIRED_FIELDS = ("project_root",)
ROUTE_ARCHITECTURE_OPTIONAL_FIELDS = (
    "current_cp_id",
    "current_time",
    "target_cp_id",
    "route_summary_path",
    "checkpoint_candidates_path",
    "segment_candidates_path",
    "segment_policy_candidates_path",
    "retreat_routes_path",
    "planned_eta_path",
    "risk_ribbon_metadata_path",
    "limit",
)

DEFAULT_ROUTE_ARCHITECTURE_LIMIT = 6
MAX_ROUTE_ARCHITECTURE_LIMIT = 16


def assess_scout_route_architecture(
    project_root: Path | str,
    *,
    query: str = "",
    current_cp_id: str | None = None,
    current_time: str | None = None,
    target_cp_id: str | None = None,
    route_summary_path: str | None = None,
    checkpoint_candidates_path: str | None = None,
    segment_candidates_path: str | None = None,
    segment_policy_candidates_path: str | None = None,
    retreat_routes_path: str | None = None,
    planned_eta_path: str | None = None,
    risk_ribbon_metadata_path: str | None = None,
    limit: int = DEFAULT_ROUTE_ARCHITECTURE_LIMIT,
) -> dict[str, Any]:
    """Assess CP Graph route architecture without mutating runtime state."""

    root = Path(project_root)
    project = _load_json_object(root / "project.json")
    project_id = str(project.get("project_id") or project.get("id") or root.name)
    resolved_limit = _bounded_limit(limit)
    source_report: list[dict[str, Any]] = []

    route_summary, route_summary_source = _load_project_json(
        root,
        explicit_path=route_summary_path,
        project=project,
        project_ref_key="route_summary_ref",
        default_ref="normalized/routes/route_summary.json",
        source_kind="route_summary",
        source_report=source_report,
    )
    checkpoints, checkpoint_source = _load_project_list(
        root,
        explicit_path=checkpoint_candidates_path,
        project=project,
        project_ref_key="checkpoint_candidates_ref",
        default_ref="candidates/checkpoints.json",
        source_kind="checkpoint_candidates",
        source_report=source_report,
    )
    segments, segment_source = _load_project_list(
        root,
        explicit_path=segment_candidates_path,
        project=project,
        project_ref_key="segment_candidates_ref",
        default_ref="candidates/segments.json",
        source_kind="segment_candidates",
        source_report=source_report,
    )
    segment_policies, segment_policy_source = _load_project_list(
        root,
        explicit_path=segment_policy_candidates_path,
        project=project,
        project_ref_key="segment_policy_candidates_ref",
        default_ref="outputs/segment_policy_candidates.json",
        source_kind="segment_policy_candidates",
        source_report=source_report,
    )
    retreat_routes, retreat_source = _load_project_list(
        root,
        explicit_path=retreat_routes_path,
        project=project,
        project_ref_key="retreat_routes_ref",
        default_ref="candidates/retreat_routes.json",
        source_kind="retreat_routes",
        source_report=source_report,
    )
    planned_eta, planned_eta_source = _load_project_json(
        root,
        explicit_path=planned_eta_path,
        project=project,
        project_ref_key="planned_eta_ref",
        default_ref="outputs/planned_eta.json",
        source_kind="planned_eta",
        source_report=source_report,
    )
    risk_ribbon, risk_ribbon_source = _load_project_json(
        root,
        explicit_path=risk_ribbon_metadata_path,
        project=project,
        project_ref_key="risk_ribbon_metadata_ref",
        default_ref="outputs/risk_ribbon.metadata.json",
        source_kind="risk_ribbon_metadata",
        source_report=source_report,
    )

    cp_nodes = _cp_nodes(checkpoints, planned_eta=planned_eta)
    graph_edges = _graph_edges(segments, checkpoints=cp_nodes, policies=segment_policies)
    cp_nodes = _standard_cp_nodes(
        cp_nodes,
        graph_edges=graph_edges,
        retreat_routes=retreat_routes,
        planned_eta=planned_eta,
    )
    route_architecture = _route_architecture(
        route_summary=route_summary,
        cp_nodes=cp_nodes,
        graph_edges=graph_edges,
        retreat_routes=retreat_routes,
        planned_eta=planned_eta,
        risk_ribbon=risk_ribbon,
        limit=resolved_limit,
    )
    route_decision = _route_decision(
        current_cp_id=current_cp_id,
        current_time=current_time,
        target_cp_id=target_cp_id,
        route_architecture=route_architecture,
        planned_eta=planned_eta,
        cp_nodes=cp_nodes,
        turn_back_status_label=_turn_back_status_label(query),
        requires_schedule_delta_status=_looks_like_schedule_delta_question(query),
        requires_checkpoint_deadline_status=_looks_like_checkpoint_deadline_question(query),
        external_deadline_pressure_kind=_external_deadline_pressure_kind(query),
    )
    graph_missing_fields = _missing_fields(cp_nodes=cp_nodes, graph_edges=graph_edges)
    decision_missing_fields = _string_list(route_decision.get("missing_fields"))
    missing_fields = _dedupe(graph_missing_fields + decision_missing_fields)
    if graph_missing_fields:
        answerability = "route_architecture_missing_cp_graph"
    elif decision_missing_fields:
        answerability = "route_architecture_missing_current_context"
    else:
        answerability = "route_architecture_available"
    field_answer = _field_answer(
        answerability=answerability,
        decision=route_decision,
        route_architecture=route_architecture,
        missing_fields=missing_fields,
    )
    decision_output = _decision_output(
        decision=route_decision,
        route_architecture=route_architecture,
        cp_nodes=cp_nodes,
        graph_edges=graph_edges,
        missing_fields=missing_fields,
        field_answer=field_answer,
    )

    return {
        "artifact_kind": ROUTE_ARCHITECTURE_OUTPUT_KIND,
        "tool_id": ROUTE_ARCHITECTURE_TOOL_ID,
        "status": "completed",
        "project_id": project_id,
        "query": query,
        "assessment_kind": "read_only_route_architecture",
        "answerability": answerability,
        "source_status": "candidate_only",
        "decision": route_decision["decision"],
        "decision_output": decision_output,
        "field_answer": field_answer,
        "missing_fields": missing_fields,
        "route_architecture": route_architecture,
        "cp_graph": {
            "node_count": len(cp_nodes),
            "edge_count": len(graph_edges),
            "nodes": cp_nodes[:resolved_limit],
            "edges": graph_edges[:resolved_limit],
            "candidate_only": True,
            "runtime_safety_truth": False,
            "source_paths": {
                "route_summary": route_summary_source,
                "checkpoints": checkpoint_source,
                "segments": segment_source,
                "segment_policies": segment_policy_source,
                "retreat_routes": retreat_source,
                "planned_eta": planned_eta_source,
                "risk_ribbon_metadata": risk_ribbon_source,
            },
        },
        "route_decision": route_decision,
        "source_report": source_report,
        "result_count": 1,
        "results": [
            {
                "label": "route architecture decision",
                "decision": route_decision["decision"],
                "decision_output": decision_output,
                "answerability": answerability,
                "route_type": route_architecture["route_type"],
                "turn_back": route_architecture["turn_back"],
                "retreat_option_count": route_architecture["retreat_option_count"],
                "hard_point_count": len(route_architecture["hard_points"]),
                "field_answer": field_answer,
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        ],
        "standard_alignment": [
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 9 Route Architecture Intelligence",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 12 Checkpoint Graph",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 12.1 CP Node Fields",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 18.2 CP Graph and alternatives",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 19 on-route recalculation",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 22 required development standards",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 23 acceptance criteria",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 24.1 MVP route structure requirements",
        ],
        "boundary": _closed_boundary(),
    }


def _cp_nodes(
    checkpoints: list[dict[str, Any]],
    *,
    planned_eta: dict[str, Any],
) -> list[dict[str, Any]]:
    eta_by_name = _eta_by_name(planned_eta)
    nodes = []
    for index, raw in enumerate(checkpoints):
        label = str(raw.get("label") or raw.get("candidate_id") or f"CP {index}")
        eta = eta_by_name.get(label.lower())
        nodes.append(
            {
                "cp_id": str(raw.get("candidate_id") or f"cp.{index:03d}"),
                "name": label,
                "index": index,
                "coordinates": {
                    "lat": _float_or_none(raw.get("lat")),
                    "lon": _float_or_none(raw.get("lon")),
                },
                "elevation": _first_float(
                    raw,
                    (
                        "elevation",
                        "elevation_m",
                        "elevationMeters",
                        "elevation_meter",
                        "ele",
                    ),
                ),
                "route_point_index": _int_or_none(raw.get("route_point_index")),
                "planned_arrival_time": eta.get("eta") if eta else None,
                "latest_safe_arrival_time": raw.get("latest_safe_arrival_time")
                or raw.get("latestSafeArrivalTime"),
                "latest_safe_departure_time": raw.get("latest_safe_departure_time")
                or raw.get("latestSafeDepartureTime"),
                "next_segment_estimated_minutes": eta.get("segment_duration_minutes")
                if eta
                else None,
                "checkpoint_type": raw.get("checkpoint_type"),
                "review_state": raw.get("review_state"),
                "candidate_only": bool(raw.get("candidate_only", True)),
                "runtime_safety_truth": False,
            }
        )
    return nodes


def _standard_cp_nodes(
    cp_nodes: list[dict[str, Any]],
    *,
    graph_edges: list[dict[str, Any]],
    retreat_routes: list[dict[str, Any]],
    planned_eta: dict[str, Any],
) -> list[dict[str, Any]]:
    outgoing_by_cp_id = {
        str(edge.get("from_cp_id")): edge
        for edge in graph_edges
        if isinstance(edge, dict) and edge.get("from_cp_id")
    }
    turn_back = _turn_back_summary(planned_eta)
    return [
        _standard_cp_node(
            node,
            outgoing_edge=outgoing_by_cp_id.get(str(node.get("cp_id"))),
            retreat_routes=retreat_routes,
            turn_back=turn_back,
        )
        for node in cp_nodes
    ]


def _standard_cp_node(
    node: dict[str, Any],
    *,
    outgoing_edge: dict[str, Any] | None,
    retreat_routes: list[dict[str, Any]],
    turn_back: dict[str, Any],
) -> dict[str, Any]:
    cp_id = str(node.get("cp_id") or node.get("cpId") or "")
    planned_arrival_time = node.get("planned_arrival_time")
    recommended_stop_minutes = _recommended_stop_minutes(
        node,
        outgoing_edge=outgoing_edge,
    )
    planned_departure_time = _time_plus_minutes(
        planned_arrival_time,
        recommended_stop_minutes,
    )
    latest_safe_arrival_time = _latest_safe_arrival_time(
        node,
        turn_back=turn_back,
    )
    latest_safe_departure_time = _latest_safe_departure_time(
        node,
        outgoing_edge=outgoing_edge,
        latest_safe_arrival_time=latest_safe_arrival_time,
    )
    retreat_options = _node_retreat_options(
        cp_id,
        retreat_routes=retreat_routes,
        turn_back=turn_back,
        node=node,
    )
    safe_to_stop = _safe_to_stop_candidate(node, outgoing_edge=outgoing_edge)
    enriched = dict(node)
    enriched.update(
        {
            "cpId": cp_id,
            "plannedArrivalTime": planned_arrival_time,
            "latestSafeArrivalTime": latest_safe_arrival_time,
            "plannedDepartureTime": planned_departure_time,
            "latestSafeDepartureTime": latest_safe_departure_time,
            "recommendedStopMinutes": recommended_stop_minutes,
            "maxStopMinutes": _max_stop_minutes(safe_to_stop),
            "nextSegmentEstimatedMinutes": _next_segment_estimated_minutes(
                node,
                outgoing_edge=outgoing_edge,
            ),
            "nextSegmentDifficulty": _next_segment_difficulty(outgoing_edge),
            "retreatOptions": retreat_options,
            "weatherSensitivity": _weather_sensitivity(outgoing_edge),
            "terrainRisks": _terrain_risks(outgoing_edge),
            "communicationStatus": _communication_status(outgoing_edge),
            "safeToStop": safe_to_stop,
            "photoVideoSuitability": _photo_video_suitability(safe_to_stop),
            "decisionTriggers": _cp_decision_triggers(
                node,
                outgoing_edge=outgoing_edge,
                retreat_options=retreat_options,
                latest_safe_arrival_time=latest_safe_arrival_time,
                latest_safe_departure_time=latest_safe_departure_time,
                turn_back=turn_back,
            ),
        }
    )
    return enriched


def _recommended_stop_minutes(
    node: dict[str, Any],
    *,
    outgoing_edge: dict[str, Any] | None,
) -> int:
    explicit = _int_or_none(
        node.get("recommended_stop_minutes") or node.get("recommendedStopMinutes")
    )
    if explicit is not None:
        return max(explicit, 0)
    if not _safe_to_stop_candidate(node, outgoing_edge=outgoing_edge):
        return 0
    return 3


def _max_stop_minutes(safe_to_stop: bool) -> int:
    return 5 if safe_to_stop else 0


def _safe_to_stop_candidate(
    node: dict[str, Any],
    *,
    outgoing_edge: dict[str, Any] | None,
) -> bool:
    explicit = node.get("safe_to_stop")
    if explicit is None:
        explicit = node.get("safeToStop")
    if isinstance(explicit, bool):
        return explicit
    cp_type = str(node.get("checkpoint_type") or "").strip().lower()
    low_risk_outgoing = (
        outgoing_edge is None
        or int(outgoing_edge.get("architecture_score") or 0) == 0
    )
    known_stop_type = cp_type in {"start", "finish", "trailhead", "hut", "camp", "shelter"}
    return bool(known_stop_type and low_risk_outgoing)


def _time_plus_minutes(value: Any, minutes: int) -> str | None:
    if not value:
        return None
    if minutes <= 0:
        return str(value)
    parsed = _parse_datetime(value)
    if parsed is None:
        return str(value)
    return (parsed + timedelta(minutes=minutes)).isoformat()


def _latest_safe_arrival_time(
    node: dict[str, Any],
    *,
    turn_back: dict[str, Any],
) -> Any:
    explicit = node.get("latest_safe_arrival_time") or node.get("latestSafeArrivalTime")
    if explicit:
        return explicit
    if _node_matches_turn_back(node, turn_back=turn_back):
        return turn_back.get("turn_back_eta")
    return None


def _latest_safe_departure_time(
    node: dict[str, Any],
    *,
    outgoing_edge: dict[str, Any] | None,
    latest_safe_arrival_time: Any,
) -> Any:
    explicit = node.get("latest_safe_departure_time") or node.get(
        "latestSafeDepartureTime"
    )
    if explicit:
        return explicit
    if outgoing_edge and outgoing_edge.get("latest_safe_departure_time"):
        return outgoing_edge.get("latest_safe_departure_time")
    return latest_safe_arrival_time


def _next_segment_estimated_minutes(
    node: dict[str, Any],
    *,
    outgoing_edge: dict[str, Any] | None,
) -> float | int | None:
    if outgoing_edge:
        estimated = _float_or_none(outgoing_edge.get("expected_duration_minutes"))
        if estimated is not None:
            return estimated
    return _float_or_none(node.get("next_segment_estimated_minutes"))


def _next_segment_difficulty(outgoing_edge: dict[str, Any] | None) -> str:
    if outgoing_edge is None:
        return "terminal_or_unknown"
    score = int(outgoing_edge.get("architecture_score") or 0)
    if score >= 5:
        return "high"
    if score >= 2:
        return "moderate"
    return "low"


def _node_retreat_options(
    cp_id: str,
    *,
    retreat_routes: list[dict[str, Any]],
    turn_back: dict[str, Any],
    node: dict[str, Any],
) -> list[dict[str, Any]]:
    options = []
    for route in retreat_routes:
        trigger = str(route.get("trigger_checkpoint_candidate_id") or "")
        is_triggered_here = bool(trigger and trigger == cp_id)
        is_turn_back_return_route = (
            _node_matches_turn_back(node, turn_back=turn_back)
            and (
                route.get("reversed_from_primary_route")
                or str(route.get("retreat_type") or "").lower() == "return_to_entry"
            )
        )
        if not is_triggered_here and not is_turn_back_return_route:
            continue
        option = _compact_retreat_route(route)
        option["applicability"] = (
            "turn_back_checkpoint_candidate"
            if is_turn_back_return_route and not is_triggered_here
            else "trigger_checkpoint_candidate"
        )
        options.append(option)
    return options


def _weather_sensitivity(outgoing_edge: dict[str, Any] | None) -> list[str]:
    if outgoing_edge is None:
        return ["next_segment_unknown"]
    sensitivity = []
    if outgoing_edge.get("requires_daylight"):
        sensitivity.append("daylight_required")
    if not sensitivity:
        sensitivity.append("no_weather_sensitivity_flagged")
    return sensitivity


def _terrain_risks(outgoing_edge: dict[str, Any] | None) -> list[str]:
    if outgoing_edge is None:
        return []
    return [
        reason
        for reason in _string_list(outgoing_edge.get("architecture_risk_reasons"))
        if reason != "requires_daylight"
    ]


def _communication_status(outgoing_edge: dict[str, Any] | None) -> str:
    if outgoing_edge is None:
        return "unknown"
    if outgoing_edge.get("signal_expected"):
        return "signal_expected"
    return "signal_not_expected"


def _photo_video_suitability(safe_to_stop: bool) -> str:
    if safe_to_stop:
        return "candidate_only_short_stop_requires_contextual_permission"
    return "not_recommended_requires_contextual_permission"


def _cp_decision_triggers(
    node: dict[str, Any],
    *,
    outgoing_edge: dict[str, Any] | None,
    retreat_options: list[dict[str, Any]],
    latest_safe_arrival_time: Any,
    latest_safe_departure_time: Any,
    turn_back: dict[str, Any],
) -> list[str]:
    triggers = [
        "recompute_on_arrival",
        "recompute_if_late",
        "no_stop_without_contextual_permission",
    ]
    if not latest_safe_arrival_time:
        triggers.append("latest_safe_arrival_time_missing")
    if not latest_safe_departure_time:
        triggers.append("latest_safe_departure_time_missing")
    if outgoing_edge and outgoing_edge.get("requires_daylight"):
        triggers.append("recompute_if_daylight_window_changes")
    if outgoing_edge and not outgoing_edge.get("signal_expected"):
        triggers.append("do_not_extend_stop_without_signal_review")
    if outgoing_edge and int(outgoing_edge.get("architecture_score") or 0) >= 5:
        triggers.append("preserve_buffer_before_high_difficulty_segment")
    if retreat_options:
        triggers.append("retreat_option_available_requires_review")
    if _node_matches_turn_back(node, turn_back=turn_back):
        triggers.append("turn_back_checkpoint")
    return _dedupe(triggers)


def _node_matches_turn_back(
    node: dict[str, Any],
    *,
    turn_back: dict[str, Any],
) -> bool:
    turn_back_name = str(turn_back.get("turn_back_checkpoint_name") or "").strip()
    if not turn_back_name:
        return False
    identifiers = {
        str(node.get("name") or "").strip(),
        str(node.get("cp_id") or "").strip(),
        str(node.get("cpId") or "").strip(),
    }
    return turn_back_name in identifiers


def _graph_edges(
    segments: list[dict[str, Any]],
    *,
    checkpoints: list[dict[str, Any]],
    policies: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    cp_by_id = {str(cp["cp_id"]): cp for cp in checkpoints}
    policy_by_segment_id = {
        str(policy.get("segment_candidate_id")): policy
        for policy in policies
        if isinstance(policy, dict) and policy.get("segment_candidate_id")
    }
    edges = []
    distances = [
        value
        for value in (_float_or_none(item.get("distance_m")) for item in segments)
        if value is not None
    ]
    mean_distance = mean(distances) if distances else 0.0
    for index, raw in enumerate(segments):
        segment_id = str(raw.get("candidate_id") or f"seg.{index:03d}")
        policy = policy_by_segment_id.get(segment_id, {})
        requirement = policy.get("requirement") if isinstance(policy.get("requirement"), dict) else {}
        from_cp = cp_by_id.get(str(raw.get("from_candidate_id")))
        to_cp = cp_by_id.get(str(raw.get("to_candidate_id")))
        distance_m = _float_or_none(raw.get("distance_m"))
        edge = {
            "segment_id": segment_id,
            "from_cp_id": raw.get("from_candidate_id"),
            "to_cp_id": raw.get("to_candidate_id"),
            "from_name": from_cp.get("name") if from_cp else None,
            "to_name": to_cp.get("name") if to_cp else None,
            "distance_m": distance_m,
            "elevation_gain_m": _float_or_none(raw.get("elevation_gain_m")),
            "elevation_loss_m": _float_or_none(raw.get("elevation_loss_m")),
            "expected_duration_minutes": _duration_minutes(
                requirement.get("expected_duration_seconds")
            ),
            "requires_daylight": bool(requirement.get("requires_daylight", False)),
            "retreat_available": bool(requirement.get("retreat_available", False)),
            "water_available": bool(requirement.get("water_available", False)),
            "signal_expected": bool(requirement.get("signal_expected", False)),
            "latest_safe_departure_time": requirement.get("latest_safe_departure_time")
            or requirement.get("latestSafeDepartureTime"),
            "review_state": raw.get("review_state"),
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
        edge["architecture_risk_reasons"] = _edge_risk_reasons(edge, mean_distance=mean_distance)
        edge["architecture_score"] = _edge_architecture_score(edge)
        edges.append(edge)
    return edges


def _route_architecture(
    *,
    route_summary: dict[str, Any],
    cp_nodes: list[dict[str, Any]],
    graph_edges: list[dict[str, Any]],
    retreat_routes: list[dict[str, Any]],
    planned_eta: dict[str, Any],
    risk_ribbon: dict[str, Any],
    limit: int,
) -> dict[str, Any]:
    hard_points = sorted(
        [edge for edge in graph_edges if edge["architecture_score"] > 0],
        key=lambda item: (
            -int(item.get("architecture_score") or 0),
            -float(item.get("distance_m") or 0.0),
            str(item.get("segment_id")),
        ),
    )[:limit]
    retreat_options = [_compact_retreat_route(route) for route in retreat_routes[:limit]]
    turn_back = _turn_back_summary(planned_eta)
    distance_m = _float_or_none(route_summary.get("distance_m"))
    route_type = _route_type(
        route_summary=route_summary,
        retreat_routes=retreat_routes,
        cp_nodes=cp_nodes,
    )
    return {
        "role": "Route Architecture Intelligence",
        "route_type": route_type,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "route_summary": {
            "distance_km": round(distance_m / 1000.0, 3) if distance_m else None,
            "elevation_min_m": _float_or_none(route_summary.get("elevation_min_m")),
            "elevation_max_m": _float_or_none(route_summary.get("elevation_max_m")),
            "started_at": route_summary.get("started_at"),
            "ended_at": route_summary.get("ended_at"),
        },
        "graph_completeness": {
            "has_cp_graph": bool(cp_nodes and graph_edges),
            "checkpoint_count": len(cp_nodes),
            "segment_count": len(graph_edges),
            "route_has_retreat_candidates": bool(retreat_routes),
            "has_planned_eta": bool(planned_eta.get("estimates")),
        },
        "hard_points": hard_points,
        "turn_back": turn_back,
        "retreat_options": retreat_options,
        "retreat_option_count": len(retreat_routes),
        "alternative_plan_options": _alternative_plan_options(retreat_routes=retreat_routes, turn_back=turn_back),
        "risk_ribbon_context": {
            "available": bool(risk_ribbon),
            "segment_count": risk_ribbon.get("segment_count"),
            "score_field": risk_ribbon.get("score_field"),
            "runtime_safety_truth": False,
        },
    }


def _route_decision(
    *,
    current_cp_id: str | None,
    current_time: str | None,
    target_cp_id: str | None,
    route_architecture: dict[str, Any],
    planned_eta: dict[str, Any],
    cp_nodes: list[dict[str, Any]],
    turn_back_status_label: str | None,
    requires_schedule_delta_status: bool,
    requires_checkpoint_deadline_status: bool,
    external_deadline_pressure_kind: str | None,
) -> dict[str, Any]:
    missing_graph = not route_architecture["graph_completeness"]["has_cp_graph"]
    turn_back = route_architecture.get("turn_back")
    turn_back = turn_back if isinstance(turn_back, dict) else {}
    at_turn_back_node = _matches_cp_or_label(
        current_cp_id,
        turn_back.get("turn_back_checkpoint_name"),
        cp_nodes=cp_nodes,
    )
    target_is_after_turn_back = _target_is_after_turn_back(
        target_cp_id,
        turn_back=turn_back,
        cp_nodes=cp_nodes,
    )
    reasons: list[str] = []
    if missing_graph:
        return {
            "decision": "DELAY",
            "main_reasons": ["CP Graph 缺失或不完整。"],
            "next_action": "補齊 checkpoint/segment graph 後再回答撤退、折返或替代路線問題。",
            "action_limit": "不得只依路線名稱或距離推論路線結構決策。",
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
    if turn_back_status_label and not current_cp_id and not current_time:
        if turn_back_status_label == "撤退窗口":
            reasons = [
                "判斷撤退點是否即將失去需要 current_cp_id 與 current_time。",
            ]
            if turn_back.get("turn_back_checkpoint_name"):
                reasons.append(
                    "計畫折返 checkpoint 是 "
                    + str(turn_back.get("turn_back_checkpoint_name"))
                    + f"，ETA={turn_back.get('turn_back_eta')}"
                )
            return {
                "decision": "DELAY",
                "main_reasons": reasons,
                "next_action": "先確認目前 CP、可靠定位與當前時間；確認前不要判定撤退窗口仍可用或繼續往後段推進。",
                "action_limit": "不得把此回答當成撤退窗口仍可用或可繼續推進的授權。",
                "first_layer_decision": "無法確認撤退點是否即將失去。",
                "missing_fields": ["current_cp_id", "current_time"],
                "turn_back_checkpoint": turn_back,
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        reasons = [
            "判斷現在是否為"
            + turn_back_status_label
            + "需要 current_cp_id 與 current_time。",
        ]
        if turn_back.get("turn_back_checkpoint_name"):
            reasons.append(
                "計畫折返 checkpoint 是 "
                + str(turn_back.get("turn_back_checkpoint_name"))
                + f"，ETA={turn_back.get('turn_back_eta')}"
            )
        return {
            "decision": "DELAY",
            "main_reasons": reasons,
            "next_action": "先確認目前 CP、可靠定位與當前時間；確認前不要往折返/撤退點後方推進。",
            "action_limit": "不得把此回答當成已通過折返/撤退點或可繼續推進的授權。",
            "first_layer_decision": "無法確認現在是否為" + turn_back_status_label + "。",
            "missing_fields": ["current_cp_id", "current_time"],
            "turn_back_checkpoint": turn_back,
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
    if requires_schedule_delta_status:
        missing = []
        if not current_cp_id:
            missing.append("current_cp_id")
        if not current_time:
            missing.append("current_time")
        planned_cp_eta = _planned_eta_for_cp(
            current_cp_id,
            cp_nodes=cp_nodes,
            planned_eta=planned_eta,
        )
        if current_cp_id and not planned_cp_eta:
            missing.append("planned_eta_for_current_cp")
        if missing:
            return {
                "decision": "DELAY",
                "main_reasons": [
                    "判斷與計畫 CP 通過時間差距需要 current_cp_id、current_time 與該 CP 的 planned ETA。",
                ],
                "next_action": "先確認目前 CP、可靠定位與當前時間；再與 CP Graph planned ETA 比對落後或提前分鐘。",
                "action_limit": "不得把此回答當成仍有完整時間、日照、撤退或天氣 buffer 的授權。",
                "first_layer_decision": "無法確認與計畫 CP 通過時間的差距。",
                "missing_fields": missing,
                "schedule_delta_status": {
                    "status": "missing_current_context",
                    "missing_fields": missing,
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                },
                "turn_back_checkpoint": turn_back,
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        schedule_delta = _schedule_delta_status(
            current_cp_id=current_cp_id,
            current_time=current_time,
            planned_eta=planned_cp_eta,
        )
        if schedule_delta.get("missing_fields"):
            return {
                "decision": "DELAY",
                "main_reasons": [
                    "current_time 與 planned ETA 必須可解析，才能計算 CP 時程差。",
                ],
                "next_action": "先用可解析的當前時間與 CP planned ETA 重新計算時程差。",
                "action_limit": "不得用不可解析的時間推論仍可照原計畫推進。",
                "first_layer_decision": "無法確認與計畫 CP 通過時間的差距。",
                "missing_fields": _string_list(schedule_delta.get("missing_fields")),
                "schedule_delta_status": schedule_delta,
                "turn_back_checkpoint": turn_back,
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        delta_minutes = _float_or_none(schedule_delta.get("delta_minutes"))
        if delta_minutes is None:
            decision = "DELAY"
            first_layer = "無法確認與計畫 CP 通過時間的差距。"
            next_action = "先補齊可追溯的 CP 通過時間，再重新估算 buffer。"
            action_limit = "不得把未確認進度當成可繼續推進授權。"
        elif delta_minutes >= 25:
            decision = "CHANGE_PLAN"
            first_layer = f"目前比計畫晚約 {delta_minutes:.0f} 分鐘。"
            next_action = "不要照原計畫硬推；重算腳程、日照、天氣與撤退 buffer，必要時改短版或折返。"
            action_limit = "落後已明顯壓縮時間、日照、撤退與天氣 buffer；未覆核前不建議照原計畫推進。"
        elif delta_minutes >= 15:
            decision = "CONDITIONAL_GO"
            first_layer = f"目前比計畫晚約 {delta_minutes:.0f} 分鐘。"
            next_action = "以最慢者控速前往下一 CP，下一 CP 前重新計算是否改短版或折返。"
            action_limit = "不得再消耗停留 buffer；下一 CP 前必須重算天氣、日照、撤退與隊伍速度。"
        elif delta_minutes <= -15:
            decision = "CONDITIONAL_GO"
            first_layer = f"目前比計畫快約 {abs(delta_minutes):.0f} 分鐘。"
            next_action = "放回最慢者可恢復節奏；不要把提前時間視為免費停留 buffer。"
            action_limit = "提前不是無限制 permission；仍需檢查最慢者、天氣、日照與撤退窗口。"
        else:
            decision = "GO" if abs(delta_minutes) < 0.05 else "CONDITIONAL_GO"
            if delta_minutes >= 0:
                first_layer = f"目前比計畫晚約 {delta_minutes:.0f} 分鐘。"
            else:
                first_layer = f"目前比計畫快約 {abs(delta_minutes):.0f} 分鐘。"
            next_action = "照 CP Graph 監控下一個 CP，並持續保留天氣、日照、撤退與腳程 buffer。"
            action_limit = "這只是 CP 時程差候選判斷；不得把小幅提前或落後轉成額外停留授權。"
        return {
            "decision": decision,
            "main_reasons": [
                "目前 CP "
                + str(schedule_delta.get("current_cp_id"))
                + " 的 planned ETA 是 "
                + str(schedule_delta.get("planned_eta"))
                + "，目前時間是 "
                + str(schedule_delta.get("current_time"))
                + f"，時程差約 {delta_minutes:.1f} 分鐘。",
                "CP 時程差會消耗或保留腳程、日照、天氣與撤退 buffer。",
            ],
            "next_action": next_action,
            "action_limit": action_limit,
            "first_layer_decision": first_layer,
            "schedule_delta_status": schedule_delta,
            "turn_back_checkpoint": turn_back,
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
    if requires_checkpoint_deadline_status:
        missing = []
        if not current_time:
            missing.append("current_time")
        if not target_cp_id:
            missing.append("target_cp_id")
        if missing:
            return {
                "decision": "DELAY",
                "main_reasons": [
                    "判斷是否錯過 checkpoint deadline 需要 current_time 與 target_cp_id。",
                ],
                "next_action": "先確認 deadline、目標 CP 與目前是否已抵達；確認前不要把原計畫視為仍可推進。",
                "action_limit": "不得把未抵達 checkpoint 的狀態當成可繼續推進授權。",
                "first_layer_decision": "無法確認是否已錯過 checkpoint 折返門檻。",
                "missing_fields": missing,
                "turn_back_checkpoint": turn_back,
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        return {
            "decision": "CHANGE_PLAN",
            "main_reasons": [
                f"目標 checkpoint {target_cp_id} 回報在 deadline {current_time} 前未抵達。",
                "錯過 checkpoint deadline 會消耗腳程、日照、天氣與撤退 buffer。",
            ],
            "next_action": "不要照原計畫繼續推進；在目前安全 CP 折返或改短版，並重新計算天氣、腳程與撤退路線。",
            "action_limit": "錯過 checkpoint deadline 後，沒有人工覆核 override 前不建議延續原路線。",
            "first_layer_decision": "不建議錯過 checkpoint deadline 後繼續原計畫。",
            "turn_back_checkpoint": turn_back,
            "target_checkpoint": target_cp_id,
            "checkpoint_deadline": current_time,
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
    if external_deadline_pressure_kind:
        return {
            "decision": "CHANGE_PLAN",
            "main_reasons": [
                "已回報外部 deadline 壓力："
                + _external_deadline_pressure_label(external_deadline_pressure_kind)
                + "。",
                "外部 deadline 會壓縮日照、撤退、腳程與路線 buffer。",
            ],
            "next_action": (
                "不要照原計畫硬推；改短版、直接前往最近安全 CP/山屋，"
                "並人工確認住宿、接駁或留守回報方案。"
            ),
            "action_limit": (
                "外部 deadline 壓力未解除前，不建議延續原路線。"
            ),
            "first_layer_decision": "建議改變計畫，先處理外部 deadline 壓力。",
            "turn_back_checkpoint": turn_back,
            "deadline_pressure": external_deadline_pressure_kind,
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
    if _current_time_at_or_past_turn_back(
        current_time,
        turn_back.get("turn_back_eta"),
    ):
        reasons.append(f"目前時間已到或超過折返 ETA {turn_back.get('turn_back_eta')}。")
    if at_turn_back_node:
        reasons.append("目前 CP 符合計畫折返 checkpoint。")
    if target_is_after_turn_back:
        reasons.append("目標點位於計畫折返 checkpoint 後方。")

    if reasons:
        decision = "CHANGE_PLAN"
        next_action = "不要照原計畫往更後段推進；在折返點重新確認隊伍、天氣與撤退路線。"
        action_limit = "沒有人工覆核 override 前，不建議延續原路線。"
    elif not route_architecture["retreat_options"]:
        decision = "CONDITIONAL_GO"
        reasons.append("CP Graph 已存在，但尚無已審核撤退候選路線。")
        next_action = "先補撤退路線或短版替代方案，再把行程送出發前決策。"
        action_limit = "撤退證據審核前，應視為低容錯路線。"
    elif route_architecture["hard_points"]:
        decision = "CONDITIONAL_GO"
        reasons.append("路線有需要以 CP 為單位監控的難點。")
        graph_completeness = route_architecture.get("graph_completeness")
        graph_completeness = (
            graph_completeness if isinstance(graph_completeness, dict) else {}
        )
        top_hard_point = _hard_point_summary(
            route_architecture["hard_points"][0],
            total_segments=_int_or_none(graph_completeness.get("segment_count")),
        )
        if top_hard_point:
            reasons.append("主要難點：" + top_hard_point)
        turn_back_text = _turn_back_brief(turn_back)
        if turn_back_text:
            reasons.append("折返候選：" + turn_back_text)
        next_action = "用 CP Graph 監控難點前後的時間、天氣與隊伍速度；保留折返窗口。"
        action_limit = "進入難點群前不要消耗 buffer。"
    else:
        decision = "GO"
        reasons.append("CP Graph 與撤退候選證據已可檢視。")
        next_action = "照 CP Graph 行進，並在下一個 CP 重新計算 buffer。"
        action_limit = "GO 仍只是候選判斷，必須受天氣、腳程與 runtime evidence 約束。"

    return {
        "decision": decision,
        "main_reasons": reasons[:3],
        "next_action": next_action,
        "action_limit": action_limit,
        "turn_back_checkpoint": turn_back,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _field_answer(
    *,
    answerability: str,
    decision: dict[str, Any],
    route_architecture: dict[str, Any],
    missing_fields: list[str],
) -> str:
    route_context = _route_architecture_brief(route_architecture)
    if missing_fields and answerability == "route_architecture_missing_current_context":
        first_layer_decision = str(decision.get("first_layer_decision") or "")
        if "CP 通過時間" in first_layer_decision:
            missing_context_phrase = "Scout 不能確認與計畫 CP 通過時間差距。"
        elif "撤退點是否即將失去" in first_layer_decision:
            missing_context_phrase = "Scout 不能確認撤退點是否即將失去。"
        elif "撤退點" in first_layer_decision:
            missing_context_phrase = "Scout 不能確認現在是否已到撤退點。"
        else:
            missing_context_phrase = "Scout 不能確認現在是否已到折返點。"
        return (
            "路線結構判斷：建議 DELAY。缺少 "
            + "、".join(missing_fields)
            + "，"
            + missing_context_phrase
            + (f" {route_context}" if route_context else "")
            + f" 下一步：{decision['next_action']} "
            + "此為 Route Architecture / CP Graph 候選判斷，不是 runtime safety truth；不得觸發 /safety、SOS、outbound send 或硬體控制。"
        )
    if missing_fields:
        return (
            "路線結構判斷：建議 DELAY。缺少 "
            + "、".join(missing_fields)
            + "，Scout 不能只看路線名稱、距離或爬升來回答撤退點、折返點或替代路線。"
        )
    reasons = decision.get("main_reasons")
    reason_text = "；".join(str(item) for item in reasons[:2]) if isinstance(reasons, list) else ""
    if not reason_text:
        reason_text = f"answerability={answerability}"
    return (
        f"路線結構判斷：建議 {decision['decision']}。{reason_text} "
        + (f"{route_context} " if route_context else "")
        + f"下一步：{decision['next_action']} "
        + "此為 Route Architecture / CP Graph 候選判斷，不是 runtime safety truth；不得觸發 /safety、SOS、outbound send 或硬體控制。"
    )


def _decision_output(
    *,
    decision: dict[str, Any],
    route_architecture: dict[str, Any],
    cp_nodes: list[dict[str, Any]],
    graph_edges: list[dict[str, Any]],
    missing_fields: list[str],
    field_answer: str,
) -> dict[str, Any]:
    decision_label = str(decision.get("decision") or "DELAY")
    allowed = decision_label in {"GO", "CONDITIONAL_GO"}
    reasons = _decision_reasons(decision=decision, missing_fields=missing_fields)
    uncertainty_notes = [f"Missing field: {field}" for field in missing_fields]
    required_conditions = _required_conditions(
        decision=decision,
        route_architecture=route_architecture,
        missing_fields=missing_fields,
    )
    alternatives = _string_list(route_architecture.get("alternative_plan_options"))
    first_layer = {
        "decision": str(
            decision.get("first_layer_decision")
            or _decision_phrase(decision_label, allowed=allowed)
        ),
        "limit": _decision_limit_phrase(
            decision=decision_label,
            route_decision=decision,
            route_architecture=route_architecture,
        ),
        "reason": " / ".join(reasons[:2]),
        "nextStep": str(decision.get("next_action") or "補齊 CP Graph 後重新評估。"),
    }
    second_layer = {
        "details": _decision_details(
            route_architecture=route_architecture,
            cp_nodes=cp_nodes,
            graph_edges=graph_edges,
            field_answer=field_answer,
        ),
        "uncertaintyNotes": uncertainty_notes,
        "residualRisk": [
            "CP Graph 與路線結構證據仍是 candidate-only。",
            "天氣、腳程、隊伍狀態與 runtime admission 仍是分開的 gate。",
            "本工具沒有建立 runtime safety truth。",
        ],
        "requiredConditions": required_conditions,
        "alternativeActions": alternatives,
    }
    return {
        "role": "Micro-Decision Agent",
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
        "action": "route_architecture_navigation",
        "decision": decision_label,
        "allowed": allowed,
        "locationConstraint": first_layer["limit"],
        "mainReasons": reasons[:3],
        "cost": {
            "checkpointCount": len(cp_nodes),
            "segmentCount": len(graph_edges),
            "hardPointCount": len(route_architecture.get("hard_points") or []),
            "retreatOptionCount": route_architecture.get("retreat_option_count"),
            "scheduleDeltaMinutes": _schedule_delta_minutes_from_decision(decision),
        },
        "nextAction": first_layer["nextStep"],
        "confidence": "low" if uncertainty_notes else "medium",
        "uncertaintyNotes": uncertainty_notes,
        "residualRisk": second_layer["residualRisk"],
        "requiredConditions": required_conditions,
        "alternativeActions": alternatives,
        "standardAlignment": [
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 9 Route Architecture Intelligence",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 12 Checkpoint Graph",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 16 required decision output format",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 17 ContextualPermission schema",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 19 on-route recalculation",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 23 acceptance criteria",
        ],
        "runtimeSafetyTruth": False,
    }


def _decision_reasons(
    *, decision: dict[str, Any], missing_fields: list[str]
) -> list[str]:
    reasons = _string_list(decision.get("main_reasons"))
    if missing_fields:
        reasons.append("缺少 " + "、".join(missing_fields[:5]))
    if not reasons:
        reasons.append("CP Graph and route architecture evidence are available.")
    return _dedupe(reasons)


def _schedule_delta_minutes_from_decision(decision: dict[str, Any]) -> float | None:
    status = decision.get("schedule_delta_status")
    if not isinstance(status, dict):
        return None
    return _float_or_none(status.get("delta_minutes"))


def _required_conditions(
    *,
    decision: dict[str, Any],
    route_architecture: dict[str, Any],
    missing_fields: list[str],
) -> list[str]:
    required = [f"補齊 {field}。" for field in missing_fields]
    if decision.get("decision") in {"CHANGE_PLAN", "CONDITIONAL_GO"}:
        required.append("下一個 CP 前重新檢查天氣、腳程、隊伍狀態與撤退 buffer。")
    if not route_architecture.get("retreat_options"):
        required.append("進入難點後方前，先完成撤退或短版替代路線覆核。")
    if not required:
        required.append("下一個 checkpoint 前持續使用 CP Graph 監控。")
    return _dedupe(required)


def _decision_phrase(decision: str, *, allowed: bool) -> str:
    if decision == "CHANGE_PLAN":
        return "不建議照原路線往後段推進。"
    if decision == "DELAY":
        return "暫緩路線結構判斷。"
    if decision == "CONDITIONAL_GO":
        return "可依 CP Graph 推進，但必須保留折返窗口。"
    if decision == "GO" and allowed:
        return "可依 CP Graph 行進。"
    return "暫緩判斷。"


def _decision_limit_phrase(
    *,
    decision: str,
    route_decision: dict[str, Any],
    route_architecture: dict[str, Any],
) -> str:
    if decision == "CHANGE_PLAN":
        return "未完成人工覆核前，不建議延續原路線到折返點後方或更高成本後段。"
    if decision == "DELAY":
        return str(
            route_decision.get("action_limit")
            or "不得只依路線名稱、距離或爬升做撤退、折返或替代路線判斷。"
        )
    if route_decision.get("schedule_delta_status"):
        return str(
            route_decision.get("action_limit")
            or "CP 時程差只是候選判斷，不得當成現場安全授權。"
        )
    if decision == "CONDITIONAL_GO" and route_architecture.get("hard_points"):
        return "不得在難點群前消耗 buffer；通過前後都要重新檢查時間、天氣與隊伍速度。"
    if decision == "CONDITIONAL_GO":
        return str(
            route_decision.get("action_limit")
            or "只有在撤退/短版替代方案可見時，才可視為候選通過。"
        )
    return "這不是 runtime 出發或通行授權；仍需天氣、腳程與安全 runtime gate。"


def _route_architecture_brief(route_architecture: dict[str, Any]) -> str:
    highlights: list[str] = []
    graph_completeness = route_architecture.get("graph_completeness")
    graph_completeness = (
        graph_completeness if isinstance(graph_completeness, dict) else {}
    )
    segment_count = _int_or_none(graph_completeness.get("segment_count"))

    turn_back = route_architecture.get("turn_back")
    if isinstance(turn_back, dict):
        turn_back_text = _turn_back_brief(turn_back)
        if turn_back_text:
            highlights.append("折返/撤退 checkpoint：" + turn_back_text)

    retreat_options = route_architecture.get("retreat_options")
    if isinstance(retreat_options, list) and retreat_options:
        retreat_text = _retreat_option_brief(retreat_options[0])
        if retreat_text:
            highlights.append("候選撤退路線：" + retreat_text)

    hard_points = route_architecture.get("hard_points")
    if isinstance(hard_points, list) and hard_points:
        hard_text = "；".join(
            text
            for text in (
                _hard_point_summary(item, total_segments=segment_count)
                for item in hard_points[:3]
                if isinstance(item, dict)
            )
            if text
        )
        if hard_text:
            highlights.append("主要難點：" + hard_text)

    alternatives = _string_list(route_architecture.get("alternative_plan_options"))
    if alternatives:
        highlights.append("替代方案：" + alternatives[0])

    return "結構重點：" + "；".join(highlights) + "。" if highlights else ""


def _turn_back_brief(turn_back: dict[str, Any]) -> str:
    name = turn_back.get("turn_back_checkpoint_name")
    if not name:
        return ""
    eta = turn_back.get("turn_back_eta")
    return str(name) + (f"，ETA={eta}" if eta else "")


def _retreat_option_brief(route: dict[str, Any]) -> str:
    label = _retreat_route_label(route)
    if not label:
        return ""
    details = []
    retreat_type = route.get("retreat_type")
    if retreat_type:
        details.append(_retreat_type_label(str(retreat_type)))
    distance_km = _float_or_none(route.get("distance_km"))
    if distance_km is not None:
        details.append(f"{distance_km:g} 公里")
    trigger = route.get("trigger_checkpoint_candidate_id")
    if trigger:
        details.append(f"觸發點 {trigger}")
    return label + (f" ({', '.join(details)})" if details else "")


def _retreat_route_label(route: dict[str, Any]) -> str:
    label = str(route.get("label") or "").strip()
    retreat_type = str(route.get("retreat_type") or "").strip().lower()
    if route.get("reversed_from_primary_route") or retreat_type == "return_to_entry":
        return "沿已審核或候選反向路線返回入口"
    return label or str(route.get("candidate_id") or "").strip()


def _retreat_type_label(value: str) -> str:
    labels = {
        "return_to_entry": "返回入口撤退線",
        "short_route": "短版路線",
        "alternate_exit": "替代出口",
    }
    return labels.get(value, value)


def _hard_point_summary(
    edge: dict[str, Any],
    *,
    total_segments: int | None = None,
) -> str:
    segment_id = str(edge.get("segment_id") or "").strip()
    if not segment_id:
        return ""
    from_name = str(edge.get("from_name") or edge.get("from_cp_id") or "").strip()
    to_name = str(edge.get("to_name") or edge.get("to_cp_id") or "").strip()
    phase = _hard_point_phase(edge, total_segments=total_segments)
    details = []
    duration = _float_or_none(edge.get("expected_duration_minutes"))
    if duration is not None:
        details.append(f"{duration:g} 分鐘")
    gain = _float_or_none(edge.get("elevation_gain_m"))
    if gain is not None and gain > 0:
        details.append(f"+{gain:g} m")
    reasons = _string_list(edge.get("architecture_risk_reasons"))
    if reasons:
        details.append("/".join(_architecture_risk_reason_label(item) for item in reasons[:3]))
    cp_span = f"{from_name} 到 {to_name}" if from_name or to_name else ""
    parts = [segment_id]
    if cp_span:
        parts.append(cp_span)
    if phase:
        parts.append(phase)
    if details:
        parts.append(", ".join(details))
    return " ".join(parts)


def _hard_point_phase(edge: dict[str, Any], *, total_segments: int | None) -> str:
    if not total_segments:
        return ""
    segment_id = str(edge.get("segment_id") or "")
    match = re.search(r"(\d+)", segment_id)
    if not match:
        return ""
    segment_index = int(match.group(1))
    ratio = segment_index / max(total_segments, 1)
    if ratio < 0.33:
        return "前段難點"
    if ratio < 0.66:
        return "中段難點"
    return "後段/回程難點"


def _decision_details(
    *,
    route_architecture: dict[str, Any],
    cp_nodes: list[dict[str, Any]],
    graph_edges: list[dict[str, Any]],
    field_answer: str,
) -> list[str]:
    details = [
        field_answer,
        f"路線類型={route_architecture.get('route_type')}",
        f"CP Graph={len(cp_nodes)} 個節點、{len(graph_edges)} 個路段",
    ]
    turn_back = route_architecture.get("turn_back")
    if isinstance(turn_back, dict) and turn_back.get("turn_back_checkpoint_name"):
        details.append(
            "折返點="
            + str(turn_back.get("turn_back_checkpoint_name"))
            + f"，ETA={turn_back.get('turn_back_eta')}"
        )
    hard_points = route_architecture.get("hard_points")
    if isinstance(hard_points, list) and hard_points:
        first = hard_points[0]
        if isinstance(first, dict):
            details.append(
                "主要難點="
                + str(first.get("segment_id"))
                + "，原因="
                + "、".join(
                    _architecture_risk_reason_label(item)
                    for item in _string_list(first.get("architecture_risk_reasons"))
                )
            )
    details.append(
        f"撤退候選數={route_architecture.get('retreat_option_count')}"
    )
    return details


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value]
    return []


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _edge_risk_reasons(edge: dict[str, Any], *, mean_distance: float) -> list[str]:
    reasons = []
    if edge.get("requires_daylight"):
        reasons.append("requires_daylight")
    if edge.get("retreat_available") is False:
        reasons.append("no_segment_retreat")
    if edge.get("water_available") is False:
        reasons.append("no_segment_water")
    duration = _float_or_none(edge.get("expected_duration_minutes"))
    if duration is not None and duration >= 30:
        reasons.append("long_segment_duration")
    distance = _float_or_none(edge.get("distance_m"))
    if mean_distance and distance is not None and distance >= mean_distance * 1.6:
        reasons.append("longer_than_typical_segment")
    gain = _float_or_none(edge.get("elevation_gain_m"))
    if gain is not None and gain >= 120:
        reasons.append("sustained_ascent")
    return reasons


def _architecture_risk_reason_label(reason: str) -> str:
    labels = {
        "requires_daylight": "需要日照",
        "no_segment_retreat": "路段內無撤退點",
        "no_segment_water": "路段內無補水點",
        "long_segment_duration": "路段時間長",
        "longer_than_typical_segment": "長於典型路段",
        "sustained_ascent": "持續爬升",
    }
    return labels.get(str(reason), str(reason))


def _edge_architecture_score(edge: dict[str, Any]) -> int:
    weights = {
        "requires_daylight": 2,
        "no_segment_retreat": 2,
        "no_segment_water": 1,
        "long_segment_duration": 2,
        "longer_than_typical_segment": 1,
        "sustained_ascent": 1,
    }
    return sum(weights.get(reason, 0) for reason in edge["architecture_risk_reasons"])


def _eta_by_name(planned_eta: dict[str, Any]) -> dict[str, dict[str, Any]]:
    estimates = planned_eta.get("estimates")
    if not isinstance(estimates, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for item in estimates:
        if not isinstance(item, dict):
            continue
        name = item.get("to_node_name")
        if isinstance(name, str) and name.strip():
            result[name.strip().lower()] = item
    return result


def _turn_back_summary(planned_eta: dict[str, Any]) -> dict[str, Any]:
    assumption = planned_eta.get("assumption")
    assumption = assumption if isinstance(assumption, dict) else {}
    return {
        "turn_back_checkpoint_name": assumption.get("turn_back_checkpoint_node_name"),
        "turn_back_eta": assumption.get("turn_back_checkpoint_eta"),
        "return_to_entry_eta_if_turn_back": assumption.get(
            "return_to_entry_eta_if_turn_back_at_checkpoint"
        ),
        "target_eta": assumption.get("target_eta"),
        "daylight_policy_status": assumption.get("daylight_policy_status"),
        "team_multiplier_status": assumption.get("team_multiplier_status"),
    }


def _planned_eta_for_cp(
    current_cp_id: str | None,
    *,
    cp_nodes: list[dict[str, Any]],
    planned_eta: dict[str, Any],
) -> dict[str, Any] | None:
    if not current_cp_id:
        return None
    current = str(current_cp_id).strip().lower()
    for node in cp_nodes:
        if not isinstance(node, dict):
            continue
        identifiers = (
            str(node.get("cp_id") or "").strip().lower(),
            str(node.get("name") or "").strip().lower(),
        )
        if current not in identifiers:
            continue
        eta = node.get("planned_arrival_time")
        if eta:
            return {
                "current_cp_id": node.get("cp_id"),
                "current_cp_name": node.get("name"),
                "planned_eta": eta,
            }
    eta_by_name = _eta_by_name(planned_eta)
    eta = eta_by_name.get(current)
    if eta and eta.get("eta"):
        return {
            "current_cp_id": current_cp_id,
            "current_cp_name": eta.get("to_node_name") or current_cp_id,
            "planned_eta": eta.get("eta"),
        }
    return None


def _schedule_delta_status(
    *,
    current_cp_id: str | None,
    current_time: str | None,
    planned_eta: dict[str, Any],
) -> dict[str, Any]:
    planned_time = planned_eta.get("planned_eta")
    delta = _minutes_delta(current_time, planned_time)
    missing = []
    if delta is None:
        if _local_clock_minutes(current_time) is None:
            missing.append("current_time")
        if _local_clock_minutes(planned_time) is None:
            missing.append("planned_eta_for_current_cp")
    status = "unknown"
    if delta is not None:
        if delta > 0:
            status = "behind_plan"
        elif delta < 0:
            status = "ahead_of_plan"
        else:
            status = "on_plan"
    return {
        "current_cp_id": planned_eta.get("current_cp_id") or current_cp_id,
        "current_cp_name": planned_eta.get("current_cp_name"),
        "current_time": current_time,
        "planned_eta": planned_time,
        "delta_minutes": delta,
        "status": status,
        "missing_fields": missing,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _minutes_delta(current_time: Any, planned_time: Any) -> float | None:
    current_dt = _parse_datetime(current_time)
    planned_dt = _parse_datetime(planned_time)
    if current_dt is not None and planned_dt is not None:
        return round((current_dt - planned_dt).total_seconds() / 60.0, 1)
    current_clock = _local_clock_minutes(current_time)
    planned_clock = _local_clock_minutes(planned_time)
    if current_clock is None or planned_clock is None:
        return None
    return round(current_clock - planned_clock, 1)


def _route_type(
    *,
    route_summary: dict[str, Any],
    retreat_routes: list[dict[str, Any]],
    cp_nodes: list[dict[str, Any]],
) -> str:
    if any(route.get("reversed_from_primary_route") for route in retreat_routes):
        return "primary_route_with_return_to_entry_retreat_candidate"
    if cp_nodes and cp_nodes[0].get("name") == cp_nodes[-1].get("name"):
        return "loop_or_return_route_candidate"
    if route_summary:
        return "linear_or_traverse_candidate"
    return "unknown"


def _alternative_plan_options(
    *,
    retreat_routes: list[dict[str, Any]],
    turn_back: dict[str, Any],
) -> list[str]:
    options = []
    if retreat_routes:
        options.append("通過折返點前，先使用已審核或候選撤退路線返回入口。")
    if turn_back.get("turn_back_checkpoint_name"):
        options.append(
            f"若腳程或天氣 buffer 偏弱，在 {turn_back['turn_back_checkpoint_name']} 折返。"
        )
    options.append("進入難點群前，改短版路線或拆成較低風險路段計畫。")
    return options


def _compact_retreat_route(route: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_id": route.get("candidate_id"),
        "label": route.get("label"),
        "retreat_type": route.get("retreat_type"),
        "trigger_checkpoint_candidate_id": route.get("trigger_checkpoint_candidate_id"),
        "entry_checkpoint_candidate_id": route.get("entry_checkpoint_candidate_id"),
        "distance_km": round(float(route.get("distance_m")) / 1000.0, 3)
        if _float_or_none(route.get("distance_m")) is not None
        else None,
        "review_state": route.get("review_state"),
        "candidate_only": bool(route.get("candidate_only", True)),
        "runtime_safety_truth": False,
    }


def _matches_cp_or_label(
    value: str | None,
    label: Any,
    *,
    cp_nodes: list[dict[str, Any]],
) -> bool:
    if not value:
        return False
    normalized = str(value).strip().lower()
    if label and normalized == str(label).strip().lower():
        return True
    for node in cp_nodes:
        if normalized in {
            str(node.get("cp_id") or "").lower(),
            str(node.get("name") or "").lower(),
        }:
            return bool(
                label
                and str(node.get("name") or "").lower()
                == str(label).strip().lower()
            )
    return False


def _target_is_after_turn_back(
    target_cp_id: str | None,
    *,
    turn_back: dict[str, Any],
    cp_nodes: list[dict[str, Any]],
) -> bool:
    if not target_cp_id or not turn_back.get("turn_back_checkpoint_name"):
        return False
    target_index = _node_index(target_cp_id, cp_nodes)
    turn_index = _node_index(str(turn_back["turn_back_checkpoint_name"]), cp_nodes)
    return target_index is not None and turn_index is not None and target_index > turn_index


def _node_index(value: str, cp_nodes: list[dict[str, Any]]) -> int | None:
    normalized = str(value).strip().lower()
    for node in cp_nodes:
        if normalized in {
            str(node.get("cp_id") or "").lower(),
            str(node.get("name") or "").lower(),
        }:
            return _int_or_none(node.get("index"))
    return None


def _missing_fields(
    *,
    cp_nodes: list[dict[str, Any]],
    graph_edges: list[dict[str, Any]],
) -> list[str]:
    missing = []
    if not cp_nodes:
        missing.append("checkpoint_candidates")
    if not graph_edges:
        missing.append("segment_candidates")
    return missing


def _turn_back_status_label(query: str) -> str | None:
    normalized = "".join(str(query).lower().split())
    if any(
        phrase in normalized
        for phrase in (
            "撤退點是否即將失去",
            "撤退點是不是快沒了",
            "下一個撤退點是不是快沒了",
            "撤退窗口是否即將失去",
            "撤退窗口是不是快沒了",
            "快失去撤退窗口",
            "失去撤退窗口",
            "retreatwindowclosing",
        )
    ):
        return "撤退窗口"
    if any(
        phrase in normalized
        for phrase in (
            "現在是不是撤退點",
            "目前是不是撤退點",
            "這裡是不是撤退點",
            "此處是不是撤退點",
            "是不是撤退點",
            "到撤退點了嗎",
            "已經到撤退點",
            "retreatpoint",
        )
    ):
        return "撤退點"
    if any(
        phrase in normalized
        for phrase in (
            "現在是不是折返點",
            "是不是折返點",
            "到折返點了嗎",
            "已經到折返點",
            "turn-backpoint",
            "turnbackpoint",
        )
    ):
        return "折返點"
    return None


def _looks_like_checkpoint_deadline_question(query: str) -> bool:
    normalized = "".join(str(query).lower().split())
    has_missed_checkpoint = any(
        phrase in normalized
        for phrase in (
            "未抵達",
            "未到",
            "沒抵達",
            "沒有抵達",
            "沒到",
            "未達",
            "未通過",
            "沒通過",
        )
    )
    has_turnback_intent = any(
        phrase in normalized
        for phrase in (
            "折返",
            "撤退",
            "回頭",
            "turnback",
            "turn-back",
        )
    )
    return has_missed_checkpoint and has_turnback_intent


def _looks_like_schedule_delta_question(query: str) -> bool:
    normalized = "".join(str(query).lower().split())
    return any(
        phrase in normalized
        for phrase in (
            "cp通過時間",
            "checkpoint通過時間",
            "計畫cp通過時間",
            "通過時間差",
            "時程差",
            "進度差",
            "比計畫晚",
            "比原計畫晚",
            "比預定晚",
            "比計畫落後",
            "比原計畫落後",
            "比計畫快多少",
            "落後多少",
            "晚多少",
            "plannedeta",
            "scheduledelta",
        )
    )


def _external_deadline_pressure_kind(query: str) -> str | None:
    normalized = "".join(str(query).lower().split())
    pressure_terms = (
        "快到了",
        "快到",
        "趕不上",
        "來不及",
        "逼近",
        "是否需要改計畫",
        "需要改計畫",
        "改計畫",
        "照原計畫",
        "原計畫",
        "deadline",
        "timepressure",
    )
    if not any(term in normalized for term in pressure_terms):
        return None
    if any(
        term in normalized
        for term in (
            "山屋報到",
            "報到時間",
            "山屋入住",
            "入住時間",
            "hutcheckin",
            "hutdeadline",
            "check-in",
            "checkin",
        )
    ):
        return "hut_checkin"
    if any(
        term in normalized
        for term in (
            "交通末班",
            "末班車",
            "末班",
            "接駁末班",
            "lastbus",
            "lasttransport",
            "transportdeadline",
        )
    ):
        return "transport_last_service"
    return None


def _external_deadline_pressure_label(kind: str) -> str:
    if kind == "hut_checkin":
        return "山屋報到"
    if kind == "transport_last_service":
        return "交通末班/接駁 deadline"
    return "外部 deadline"


def _load_project_json(
    root: Path,
    *,
    explicit_path: str | None,
    project: dict[str, Any],
    project_ref_key: str,
    default_ref: str,
    source_kind: str,
    source_report: list[dict[str, Any]],
) -> tuple[dict[str, Any], str | None]:
    ref = explicit_path or str(project.get(project_ref_key) or default_ref)
    path = _project_path(root, ref)
    payload = _load_json_object(path)
    source_report.append(
        {
            "source_kind": source_kind,
            "status": "loaded" if payload else "missing_or_empty",
            "source_path": ref,
            "loaded_count": 1 if payload else 0,
            "raw_payloads_embedded": False,
        }
    )
    return payload, ref if payload else None


def _load_project_list(
    root: Path,
    *,
    explicit_path: str | None,
    project: dict[str, Any],
    project_ref_key: str,
    default_ref: str,
    source_kind: str,
    source_report: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str | None]:
    ref = explicit_path or str(project.get(project_ref_key) or default_ref)
    path = _project_path(root, ref)
    payload = _load_json(path)
    rows: list[Any] = []
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        for key in ("candidates", "items", "segments", "checkpoints", "rows"):
            if isinstance(payload.get(key), list):
                rows = payload[key]
                break
    dict_rows = [item for item in rows if isinstance(item, dict)]
    source_report.append(
        {
            "source_kind": source_kind,
            "status": "loaded" if dict_rows else "missing_or_empty",
            "source_path": ref,
            "loaded_count": len(dict_rows),
            "raw_payloads_embedded": False,
        }
    )
    return dict_rows, ref if dict_rows else None


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


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(parsed):
        return None
    return parsed


def _first_float(raw: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        parsed = _float_or_none(raw.get(key))
        if parsed is not None:
            return parsed
    return None


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _duration_minutes(seconds: Any) -> float | None:
    parsed = _float_or_none(seconds)
    if parsed is None:
        return None
    return round(parsed / 60.0, 1)


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _current_time_at_or_past_turn_back(
    current_time: Any,
    turn_back_eta: Any,
) -> bool:
    current = _parse_datetime(current_time)
    turn_back = _parse_datetime(turn_back_eta)
    if current is not None and turn_back is not None:
        return current >= turn_back
    current_clock = _local_clock_minutes(current_time)
    turn_back_clock = _local_clock_minutes(turn_back_eta)
    if current_clock is None or turn_back_clock is None:
        return False
    return current_clock >= turn_back_clock


def _local_clock_minutes(value: Any) -> float | None:
    if not isinstance(value, str) or not value.strip():
        return None
    parsed = _parse_datetime(value)
    if parsed is not None:
        return parsed.hour * 60 + parsed.minute + parsed.second / 60
    match = re.search(r"(?<!\d)(\d{1,2})[:：](\d{2})(?::(\d{2}))?", value)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2))
    second = int(match.group(3) or 0)
    if hour > 23 or minute > 59 or second > 59:
        return None
    return hour * 60 + minute + second / 60


def _bounded_limit(limit: int) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = DEFAULT_ROUTE_ARCHITECTURE_LIMIT
    return max(1, min(value, MAX_ROUTE_ARCHITECTURE_LIMIT))


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
        "outbound_send_performed": False,
    }
