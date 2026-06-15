from __future__ import annotations

import json
import math
from datetime import datetime
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
        requires_turn_back_status=_looks_like_turn_back_status_question(query),
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
                "route_point_index": _int_or_none(raw.get("route_point_index")),
                "planned_arrival_time": eta.get("eta") if eta else None,
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
    requires_turn_back_status: bool,
) -> dict[str, Any]:
    missing_graph = not route_architecture["graph_completeness"]["has_cp_graph"]
    turn_back = route_architecture.get("turn_back")
    turn_back = turn_back if isinstance(turn_back, dict) else {}
    now = _parse_datetime(current_time)
    turn_back_time = _parse_datetime(turn_back.get("turn_back_eta"))
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
            "main_reasons": ["CP Graph is missing or incomplete."],
            "next_action": "補齊 checkpoint/segment graph 後再回答撤退、折返或替代路線問題。",
            "action_limit": "Do not infer route architecture decisions from route name or distance only.",
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
    if requires_turn_back_status and not current_cp_id and not current_time:
        reasons = [
            "current_cp_id and current_time are required to determine whether this is the turn-back point.",
        ]
        if turn_back.get("turn_back_checkpoint_name"):
            reasons.append(
                "planned turn-back checkpoint is "
                + str(turn_back.get("turn_back_checkpoint_name"))
                + f" at {turn_back.get('turn_back_eta')}"
            )
        return {
            "decision": "DELAY",
            "main_reasons": reasons,
            "next_action": "先確認目前 CP、可靠定位與當前時間；確認前不要往折返點後方推進。",
            "action_limit": "不得把此回答當成已通過折返點或可繼續推進的授權。",
            "first_layer_decision": "無法確認現在是否為折返點。",
            "missing_fields": ["current_cp_id", "current_time"],
            "turn_back_checkpoint": turn_back,
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
    if turn_back_time and now and now >= turn_back_time:
        reasons.append(f"current_time is at or past turn-back ETA {turn_back.get('turn_back_eta')}")
    if at_turn_back_node:
        reasons.append("current CP matches the planned turn-back checkpoint.")
    if target_is_after_turn_back:
        reasons.append("target is beyond the planned turn-back checkpoint.")

    if reasons:
        decision = "CHANGE_PLAN"
        next_action = "不要照原計畫往更後段推進；在折返點重新確認隊伍、天氣與撤退路線。"
        action_limit = "Original route continuation is not recommended without reviewed override."
    elif not route_architecture["retreat_options"]:
        decision = "CONDITIONAL_GO"
        reasons.append("CP Graph exists but no reviewed retreat candidate is available.")
        next_action = "先補撤退路線或短版替代方案，再把行程送出發前決策。"
        action_limit = "Treat route as low-forgiveness until retreat evidence is reviewed."
    elif route_architecture["hard_points"]:
        decision = "CONDITIONAL_GO"
        reasons.append("Route has hard points that require CP-based monitoring.")
        next_action = "用 CP Graph 監控難點前後的時間、天氣與隊伍速度；保留折返窗口。"
        action_limit = "Do not spend buffer before the hard-point cluster."
    else:
        decision = "GO"
        reasons.append("CP Graph and retreat candidate evidence are available.")
        next_action = "照 CP Graph 行進，並在下一個 CP 重新計算 buffer。"
        action_limit = "GO is candidate-only and remains bounded by weather, pace, and runtime evidence."

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
    missing_fields: list[str],
) -> str:
    if missing_fields and answerability == "route_architecture_missing_current_context":
        return (
            "路線結構判斷：建議 DELAY。缺少 "
            + "、".join(missing_fields)
            + "，Scout 不能確認現在是否已到折返點。"
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
        f"下一步：{decision['next_action']} "
        "此為 Route Architecture / CP Graph 候選判斷，不是 runtime safety truth；不得觸發 /safety、SOS、outbound send 或硬體控制。"
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
            "CP Graph and route architecture evidence are candidate-only.",
            "Weather, pace, team status, and runtime admission remain separate gates.",
            "No runtime safety truth was created.",
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


def _required_conditions(
    *,
    decision: dict[str, Any],
    route_architecture: dict[str, Any],
    missing_fields: list[str],
) -> list[str]:
    required = [f"Provide {field}." for field in missing_fields]
    if decision.get("decision") in {"CHANGE_PLAN", "CONDITIONAL_GO"}:
        required.append("Re-check weather, pace, team status, and retreat buffer at the next CP.")
    if not route_architecture.get("retreat_options"):
        required.append("Review retreat or short-route alternatives before committing beyond hard points.")
    if not required:
        required.append("Keep CP Graph monitoring active through the next checkpoint.")
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
    if decision == "CONDITIONAL_GO" and route_architecture.get("hard_points"):
        return "不得在難點群前消耗 buffer；通過前後都要重新檢查時間、天氣與隊伍速度。"
    if decision == "CONDITIONAL_GO":
        return str(
            route_decision.get("action_limit")
            or "只有在撤退/短版替代方案可見時，才可視為候選通過。"
        )
    return "這不是 runtime 出發或通行授權；仍需天氣、腳程與安全 runtime gate。"


def _decision_details(
    *,
    route_architecture: dict[str, Any],
    cp_nodes: list[dict[str, Any]],
    graph_edges: list[dict[str, Any]],
    field_answer: str,
) -> list[str]:
    details = [
        field_answer,
        f"route_type={route_architecture.get('route_type')}",
        f"cp_graph={len(cp_nodes)} node(s), {len(graph_edges)} edge(s)",
    ]
    turn_back = route_architecture.get("turn_back")
    if isinstance(turn_back, dict) and turn_back.get("turn_back_checkpoint_name"):
        details.append(
            "turn_back="
            + str(turn_back.get("turn_back_checkpoint_name"))
            + f", eta={turn_back.get('turn_back_eta')}"
        )
    hard_points = route_architecture.get("hard_points")
    if isinstance(hard_points, list) and hard_points:
        first = hard_points[0]
        if isinstance(first, dict):
            details.append(
                "top_hard_point="
                + str(first.get("segment_id"))
                + f", reasons={','.join(_string_list(first.get('architecture_risk_reasons')))}"
            )
    details.append(
        f"retreat_option_count={route_architecture.get('retreat_option_count')}"
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
        for key in ("to_node_name", "from_node_name"):
            name = item.get(key)
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
        options.append("return to entry using reviewed/candidate retreat route before committing beyond turn-back point")
    if turn_back.get("turn_back_checkpoint_name"):
        options.append(f"turn back at {turn_back['turn_back_checkpoint_name']} if pace/weather buffer is weak")
    options.append("shorten route or split into lower-risk segment plan before hard-point cluster")
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


def _looks_like_turn_back_status_question(query: str) -> bool:
    normalized = "".join(str(query).lower().split())
    return any(
        phrase in normalized
        for phrase in (
            "現在是不是折返點",
            "是不是折返點",
            "到折返點了嗎",
            "已經到折返點",
            "turn-backpoint",
            "turnbackpoint",
        )
    )


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
