from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LIVE_NAVIGATION_STATE_TOOL_ID = "scout.ai.live_navigation_state.assess.v0"
LIVE_NAVIGATION_STATE_OUTPUT_KIND = "scout_ai_live_navigation_state_tool_output"
NMEA_ROUTE_RISK_PROBE_TOOL_ID = "assistant_skill.live_navigation.nmea_route_risk.v0"

LIVE_NAVIGATION_REQUIRED_FIELDS = (
    "observed_at",
    "lat",
    "lon",
    "elevation_m",
    "source",
    "hdop",
    "horizontal_accuracy_m",
    "fix_quality",
    "satellite_count",
    "max_cno_dbhz",
    "heading_deg",
    "course_deg",
    "speed_mps",
    "nearest_route_distance_m",
    "route_progress_m",
    "nearest_cp_id",
    "ins_dr_source",
    "confidence",
    "uncertainty_m",
    "last_anchor_at",
)
LIVE_NAVIGATION_OPTIONAL_FIELDS = (
    "live_navigation_snapshot_path",
    *LIVE_NAVIGATION_REQUIRED_FIELDS,
    "scenario_id",
    "travel_direction",
    "distance_to_boss_along_route_m",
    "boss_point_id",
    "boss_rank",
    "candidate_only",
    "runtime_safety_truth",
)


def assess_scout_live_navigation_state(
    project_root: Path | str,
    *,
    query: str = "",
    live_navigation_snapshot_path: str | None = None,
    observed_at: str | None = None,
    lat: float | int | str | None = None,
    lon: float | int | str | None = None,
    elevation_m: float | int | str | None = None,
    source: str | None = None,
    hdop: float | int | str | None = None,
    horizontal_accuracy_m: float | int | str | None = None,
    fix_quality: str | None = None,
    satellite_count: int | str | None = None,
    max_cno_dbhz: float | int | str | None = None,
    heading_deg: float | int | str | None = None,
    course_deg: float | int | str | None = None,
    speed_mps: float | int | str | None = None,
    nearest_route_distance_m: float | int | str | None = None,
    route_progress_m: float | int | str | None = None,
    nearest_cp_id: str | None = None,
    ins_dr_source: str | None = None,
    confidence: float | int | str | None = None,
    uncertainty_m: float | int | str | None = None,
    last_anchor_at: str | None = None,
    scenario_id: str | None = None,
    travel_direction: str | None = None,
    distance_to_boss_along_route_m: float | int | str | None = None,
    boss_point_id: str | None = None,
    boss_rank: int | str | None = None,
    candidate_only: bool | None = None,
    runtime_safety_truth: bool | None = None,
) -> dict[str, Any]:
    """Assess a caller-provided live navigation snapshot without reading runtime state."""

    root = Path(project_root)
    project = _load_project(root)
    project_id = str(project.get("project_id") or project.get("id") or root.name)
    caller_provided = {
        "observed_at": observed_at,
        "lat": lat,
        "lon": lon,
        "elevation_m": elevation_m,
        "source": source,
        "hdop": hdop,
        "horizontal_accuracy_m": horizontal_accuracy_m,
        "fix_quality": fix_quality,
        "satellite_count": satellite_count,
        "max_cno_dbhz": max_cno_dbhz,
        "heading_deg": heading_deg,
        "course_deg": course_deg,
        "speed_mps": speed_mps,
        "nearest_route_distance_m": nearest_route_distance_m,
        "route_progress_m": route_progress_m,
        "nearest_cp_id": nearest_cp_id,
        "ins_dr_source": ins_dr_source,
        "confidence": confidence,
        "uncertainty_m": uncertainty_m,
        "last_anchor_at": last_anchor_at,
    }
    scenario_context = {
        "scenario_id": scenario_id,
        "travel_direction": travel_direction,
        "distance_to_boss_along_route_m": distance_to_boss_along_route_m,
        "boss_point_id": boss_point_id,
        "boss_rank": boss_rank,
        "candidate_only": candidate_only,
        "runtime_safety_truth": runtime_safety_truth,
    }
    caller_field_count = sum(
        1 for value in caller_provided.values() if not _is_missing(value)
    )
    if live_navigation_snapshot_path or caller_field_count == 0:
        snapshot, snapshot_report = _load_live_navigation_snapshot(
            root,
            project,
            explicit_path=live_navigation_snapshot_path,
        )
    else:
        snapshot = {}
        snapshot_report = [
            {
                "source_kind": "live_navigation_snapshot",
                "status": "skipped_project_fallback_for_caller_snapshot",
                "source_path": None,
                "loaded_count": 0,
            }
        ]
    provided = {
        field: _first_non_missing(caller_provided[field], snapshot.get(field))
        for field in LIVE_NAVIGATION_REQUIRED_FIELDS
    }
    missing_fields = [
        field for field in LIVE_NAVIGATION_REQUIRED_FIELDS if _is_missing(provided[field])
    ]
    available_position = (
        not _is_missing(provided.get("lat")) and not _is_missing(provided.get("lon"))
    )
    provided_fields = {
        field: value for field, value in provided.items() if not _is_missing(value)
    }
    provided_fields = {
        **provided_fields,
        **{
            field: value
            for field, value in scenario_context.items()
            if not _is_missing(value)
        },
    }
    quality_flags = _quality_flags(
        hdop=provided.get("hdop"),
        horizontal_accuracy_m=provided.get("horizontal_accuracy_m"),
        fix_quality=provided.get("fix_quality"),
        satellite_count=provided.get("satellite_count"),
        uncertainty_m=provided.get("uncertainty_m"),
    )
    route_query_plan = _route_query_plan(
        available_position=available_position,
        missing_fields=missing_fields,
    )
    navigation_decision = _navigation_decision(
        query=query,
        missing_fields=missing_fields,
        provided=provided,
        quality_flags=quality_flags,
    )
    navigation_terrain = _navigation_terrain(
        provided=provided,
        missing_fields=missing_fields,
        quality_flags=quality_flags,
        route_query_plan=route_query_plan,
        navigation_decision=navigation_decision,
        query=query,
    )
    field_answer = _field_answer(
        decision=navigation_decision,
        missing_fields=missing_fields,
    )
    freshness_answer = _live_navigation_freshness_answer(query, provided)
    position_answer = _live_navigation_position_answer(
        query,
        provided,
        missing_fields=missing_fields,
    )
    direct_answer = freshness_answer or position_answer
    if direct_answer:
        field_answer = direct_answer
    decision_output = _decision_output(
        decision=navigation_decision,
        missing_fields=missing_fields,
    )
    return {
        "artifact_kind": LIVE_NAVIGATION_STATE_OUTPUT_KIND,
        "tool_id": LIVE_NAVIGATION_STATE_TOOL_ID,
        "status": "completed",
        "project_id": project_id,
        "query": query,
        "assessment_kind": "read_only_live_navigation_snapshot",
        "source_status": _source_status(snapshot=snapshot, provided_fields=provided_fields),
        "answerability": (
            "snapshot_evidence_available"
            if not missing_fields
            else "snapshot_missing_required_fields"
        ),
        "decision": navigation_decision["decision"],
        "field_answer": field_answer,
        "field_answer_priority": 100 if direct_answer else 0,
        "field_answer_source_ref": _loaded_snapshot_source_ref(snapshot_report),
        "decision_output": decision_output,
        "missing_fields": missing_fields,
        "provided_fields": provided_fields,
        "scenario_context": {
            field: value
            for field, value in scenario_context.items()
            if not _is_missing(value)
        },
        "navigation_terrain": navigation_terrain,
        "navigation_decision": navigation_decision,
        "route_query_plan": route_query_plan,
        "quality_flags": quality_flags,
        "result_count": 1,
        "results": [
            {
                "label": "live navigation state assessor",
                "decision": navigation_decision["decision"],
                "answerability": (
                    "snapshot_evidence_available"
                    if not missing_fields
                    else "snapshot_missing_required_fields"
                ),
                "route_fit_status": navigation_terrain["location_fit"][
                    "route_fit_status"
                ],
                "position_quality_status": navigation_terrain["location_fit"][
                    "position_quality_status"
                ],
                "field_answer": field_answer,
                "decision_output": decision_output,
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        ],
        "standard_alignment": [
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 11 Navigation & Terrain Intelligence",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 14 Micro-Decision Agent",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 18.2 on-route recalculation",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 19 navigation uncertainty questions",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 22 required development standards",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 23 acceptance criteria",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 24.1 MVP on-route route decisions",
        ],
        "source_report": [
            *snapshot_report,
            {
                "source_kind": "deterministic_live_navigation_snapshot_policy",
                "status": "loaded",
                "source_path": (
                    "scout_live_navigation_state_tool."
                    "assess_scout_live_navigation_state"
                ),
                "loaded_count": 1,
            }
        ],
        "boundary": _closed_boundary(),
    }


def _navigation_terrain(
    *,
    provided: dict[str, object],
    missing_fields: list[str],
    quality_flags: dict[str, Any],
    route_query_plan: dict[str, Any],
    navigation_decision: dict[str, Any],
    query: str,
) -> dict[str, Any]:
    distance = _float_or_none(provided.get("nearest_route_distance_m"))
    accuracy = _float_or_none(provided.get("horizontal_accuracy_m"))
    uncertainty = _float_or_none(provided.get("uncertainty_m"))
    return {
        "role": "Navigation & Terrain Intelligence",
        "basis": "caller_provided_snapshot_only",
        "candidate_only": True,
        "runtime_safety_truth": False,
        "location_fit": {
            "nearest_route_distance_m": distance,
            "route_progress_m": _float_or_none(provided.get("route_progress_m")),
            "nearest_cp_id": provided.get("nearest_cp_id"),
            "route_fit_status": _route_fit_status(
                nearest_route_distance_m=distance,
                horizontal_accuracy_m=accuracy,
                uncertainty_m=uncertainty,
            ),
            "position_quality_status": _position_quality_status(
                quality_flags=quality_flags,
                missing_fields=missing_fields,
            ),
            "quality_flags": quality_flags,
        },
        "terrain_caution_flags": _terrain_caution_flags(query),
        "guidance": navigation_decision,
        "followup_plan": route_query_plan,
        "map_boundary": {
            "offline_map_or_gpx_truth_claimed": False,
            "candidate_snapshot_only": True,
            "requires_map_or_route_followup_for_turn_confirmation": True,
        },
    }


def _navigation_decision(
    *,
    query: str,
    missing_fields: list[str],
    provided: dict[str, object],
    quality_flags: dict[str, Any],
) -> dict[str, Any]:
    distance = _float_or_none(provided.get("nearest_route_distance_m"))
    accuracy = _float_or_none(provided.get("horizontal_accuracy_m"))
    uncertainty = _float_or_none(provided.get("uncertainty_m"))
    route_fit_status = _route_fit_status(
        nearest_route_distance_m=distance,
        horizontal_accuracy_m=accuracy,
        uncertainty_m=uncertainty,
    )
    quality_status = _position_quality_status(
        quality_flags=quality_flags,
        missing_fields=missing_fields,
    )
    terrain_flags = _terrain_caution_flags(query)
    reasons: list[str] = []

    if "lat" in missing_fields or "lon" in missing_fields:
        return _decision_payload(
            decision="DELAY",
            reasons=["lat/lon are missing, so Scout cannot verify route fit."],
            next_action="先取得可靠位置，再判斷是否走對、是否偏離或是否能回主線。",
            action_limit="Do not infer turn, off-route, or down-cut decisions without position.",
            route_fit_status=route_fit_status,
            position_quality_status=quality_status,
            terrain_flags=terrain_flags,
        )

    if "downcut_or_stream_channel" in terrain_flags or "leave_main_route_request" in terrain_flags:
        reasons.append("question asks about leaving the main route or down-cutting terrain.")
        if route_fit_status in {"off_route_candidate", "route_fit_unknown"}:
            reasons.append(f"route_fit_status={route_fit_status}.")
        return _decision_payload(
            decision="NO_GO",
            reasons=reasons,
            next_action="不要下切溪谷、乾溝或離開主線；回到最近可信 CP、開闊點或原路 anchor 重新定位。",
            action_limit="Scout cannot authorize shortcut/down-cut movement from a candidate snapshot.",
            route_fit_status=route_fit_status,
            position_quality_status=quality_status,
            terrain_flags=terrain_flags,
        )

    if quality_status in {"poor_quality", "partial_quality"}:
        reasons.append(f"position_quality_status={quality_status}.")
        return _decision_payload(
            decision="GUIDED_ONLY",
            reasons=reasons,
            next_action="只能做保守引導：停止擴大偏差，核對離線地圖、GPX、地形與上一個可信 anchor。",
            action_limit="Do not confirm a branch or descent decision until GNSS/INS-DR quality improves.",
            route_fit_status=route_fit_status,
            position_quality_status=quality_status,
            terrain_flags=terrain_flags,
        )

    if route_fit_status == "off_route_candidate":
        reasons.append(f"nearest_route_distance_m={distance} exceeds route-fit threshold.")
        return _decision_payload(
            decision="CHANGE_PLAN",
            reasons=reasons,
            next_action="先停止往前推進，回到上一個可信 CP 或原路 anchor，再重新比對方向與路線走廊。",
            action_limit="Do not continue into unknown terrain while off-route candidate remains unresolved.",
            route_fit_status=route_fit_status,
            position_quality_status=quality_status,
            terrain_flags=terrain_flags,
        )

    if route_fit_status in {"near_corridor_edge", "route_fit_unknown"} or "branch_or_mainline_check" in terrain_flags:
        reasons.append(f"route_fit_status={route_fit_status}.")
        return _decision_payload(
            decision="CONDITIONAL_GO",
            reasons=reasons,
            next_action="沿主線或最近可信路線走廊前進到下一個 CP；持續核對 heading、GPX、地形線與岔路標記。",
            action_limit="Do not leave the mapped corridor; re-check at the next CP or within a few minutes.",
            route_fit_status=route_fit_status,
            position_quality_status=quality_status,
            terrain_flags=terrain_flags,
        )

    reasons.append("position quality and route-fit snapshot are usable.")
    return _decision_payload(
        decision="GO",
        reasons=reasons,
        next_action="維持在路線走廊內前進，下一個 CP 再重新計算位置、heading 與 terrain risk。",
        action_limit="GO is candidate-only and remains bounded by terrain, weather, pace, and map evidence.",
        route_fit_status=route_fit_status,
        position_quality_status=quality_status,
        terrain_flags=terrain_flags,
    )


def _decision_payload(
    *,
    decision: str,
    reasons: list[str],
    next_action: str,
    action_limit: str,
    route_fit_status: str,
    position_quality_status: str,
    terrain_flags: list[str],
) -> dict[str, Any]:
    return {
        "decision": decision,
        "main_reasons": reasons[:3],
        "next_action": next_action,
        "action_limit": action_limit,
        "route_fit_status": route_fit_status,
        "position_quality_status": position_quality_status,
        "terrain_caution_flags": terrain_flags,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _field_answer(
    *,
    decision: dict[str, Any],
    missing_fields: list[str],
) -> str:
    reasons = decision.get("main_reasons")
    reason_text = "；".join(str(item) for item in reasons[:2]) if isinstance(reasons, list) else ""
    if not reason_text and missing_fields:
        reason_text = "缺少 " + "、".join(missing_fields[:5])
    elif not reason_text:
        reason_text = f"route_fit_status={decision.get('route_fit_status')}"
    return (
        f"地形導航判斷：建議 {decision['decision']}。{reason_text} "
        f"下一步：{decision['next_action']} "
        "此為 Navigation & Terrain 候選判斷，不是 runtime safety truth；不得觸發 /safety、SOS、outbound send 或硬體控制。"
    )


def _live_navigation_freshness_answer(
    query: str,
    provided: dict[str, object],
) -> str | None:
    lowered = query.casefold()
    if not any(token in lowered for token in ("最新", "latest", "過期", "stale")):
        return None
    observed_at = provided.get("observed_at")
    if _is_missing(observed_at):
        return "Workspace 沒有可驗證的 live navigation observed_at，無法判斷 freshness。"
    parsed = _parse_timestamp(observed_at)
    if parsed is None:
        return f"最新 live navigation observed_at={observed_at}，但時間格式無法解析。"
    signed_age_seconds = (datetime.now(timezone.utc) - parsed).total_seconds()
    if signed_age_seconds < -300.0:
        return (
            f"最新 live navigation observed_at={observed_at}；時間戳在未來，"
            "存在 clock skew，freshness 不可靠。"
        )
    age_seconds = max(0.0, signed_age_seconds)
    freshness = "已過期" if age_seconds > 300.0 else "未過期"
    return (
        f"最新 live navigation observed_at={observed_at}；"
        f"距現在約 {age_seconds / 3600.0:.1f} 小時，資料{freshness}（5 分鐘門檻）。"
    )


def _live_navigation_position_answer(
    query: str,
    provided: dict[str, object],
    *,
    missing_fields: list[str],
) -> str | None:
    lowered = query.casefold()
    if not any(
        token in lowered
        for token in ("哪一個位置", "現在在哪", "目前位置", "current position")
    ):
        return None
    required = ("lat", "lon", "route_progress_m")
    if any(_is_missing(provided.get(field)) for field in required):
        missing = "、".join(field for field in required if _is_missing(provided.get(field)))
        return f"目前無法確認路線位置；缺少 {missing or '定位欄位'}，請先重新取得 GNSS 定位。"
    route_km = float(provided["route_progress_m"]) / 1000.0
    parts = [
        f"目前候選位置為 {provided['lat']},{provided['lon']}",
        f"路線累積約 {route_km:g} km",
    ]
    nearest_cp = provided.get("nearest_cp_id")
    if not _is_missing(nearest_cp):
        parts.append(f"最近 CP {nearest_cp}")
    heading = provided.get("heading_deg")
    if not _is_missing(heading):
        parts.append(f"航向 {float(heading):g} 度")
    travel_direction = provided.get("travel_direction")
    if not _is_missing(travel_direction):
        parts.append(f"行進方向 {travel_direction}")
    if missing_fields:
        parts.append("仍缺少 " + "、".join(missing_fields[:3]))
    return "；".join(parts) + "。此為定位候選證據，不是 runtime safety truth。"


def _parse_timestamp(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _loaded_snapshot_source_ref(report: list[dict[str, Any]]) -> str:
    for item in report:
        if item.get("status") == "loaded" and item.get("source_path"):
            return str(item["source_path"])
    return "project.json"


def _decision_output(
    *,
    decision: dict[str, Any],
    missing_fields: list[str],
) -> dict[str, Any]:
    decision_label = str(decision["decision"])
    allowed = decision_label in {"GO", "CONDITIONAL_GO"}
    reasons = [str(item) for item in decision.get("main_reasons", []) if str(item)]
    if not reasons and missing_fields:
        reasons = ["缺少 " + "、".join(missing_fields[:5])]
    if not reasons:
        reasons = [f"route_fit_status={decision.get('route_fit_status')}"]
    uncertainty_notes = _uncertainty_notes(
        decision=decision,
        missing_fields=missing_fields,
    )
    required_conditions = _required_conditions(
        decision=decision,
        missing_fields=missing_fields,
    )
    alternative_actions = _navigation_alternatives(decision=decision)
    details = [
        f"route_fit_status={decision.get('route_fit_status')}",
        f"position_quality_status={decision.get('position_quality_status')}",
        f"terrain_caution_flags={','.join(decision.get('terrain_caution_flags') or []) or 'none'}",
        str(decision.get("action_limit") or ""),
    ]
    return {
        "role": "Micro-Decision Agent",
        "format": "SCOUT_OUTDOOR_AI_AGENT_STANDARD.section16",
        "decisionObjectSchema": "ContextualPermission",
        "text": "\n".join(
            (
                f"[決策] {_decision_phrase(decision_label, allowed=allowed)}",
                f"[限制] {_limit_phrase(decision)}",
                f"[原因] {' / '.join(reasons[:2])}",
                f"[下一步] {decision['next_action']}",
            )
        ),
        "firstLayer": {
            "decision": _decision_phrase(decision_label, allowed=allowed),
            "limit": _limit_phrase(decision),
            "reason": " / ".join(reasons[:2]),
            "nextStep": decision["next_action"],
        },
        "secondLayer": {
            "details": [detail for detail in details if detail],
            "uncertaintyNotes": uncertainty_notes,
            "residualRisk": [
                "Caller-provided navigation snapshot is candidate evidence only.",
                "Runtime safety truth, /safety, SOS, outbound send, and hardware control were not triggered.",
            ],
            "requiredConditions": required_conditions,
            "alternativeActions": alternative_actions,
        },
        "action": _navigation_action(decision_label),
        "decision": decision_label,
        "allowed": allowed,
        "locationConstraint": _limit_phrase(decision),
        "mainReasons": reasons[:3],
        "cost": {
            "retreatImpact": "Do not consume retreat buffer by expanding off-route uncertainty.",
            "daylightImpact": "Recompute daylight and CP buffer before extending movement.",
        },
        "nextAction": decision["next_action"],
        "confidence": "low" if uncertainty_notes else "medium",
        "uncertaintyNotes": uncertainty_notes,
        "residualRisk": [
            "Candidate navigation guidance only.",
            "Live runtime admission and map evidence remain separate.",
        ],
        "requiredConditions": required_conditions,
        "alternativeActions": alternative_actions,
        "standardAlignment": [
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 16 required decision output format",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 17 ContextualPermission schema",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 19.2 required on-route output",
        ],
        "runtimeSafetyTruth": False,
    }


def _decision_phrase(decision: str, *, allowed: bool) -> str:
    if decision == "GO":
        return "可以沿路線走廊前進。"
    if decision == "CONDITIONAL_GO":
        return "可以保守前進到下一個可信 CP。"
    if decision == "GUIDED_ONLY":
        return "只能做保守引導。"
    if decision == "CHANGE_PLAN":
        return "必須先停止推進並修正路線。"
    if decision == "DELAY":
        return "暫緩判斷，先取得可靠位置。"
    if decision == "NO_GO":
        return "不建議前進或下切。"
    if decision == "ESCALATE":
        return "需要升級處理。"
    return "可以。" if allowed else "不建議。"


def _limit_phrase(decision: dict[str, Any]) -> str:
    decision_label = str(decision.get("decision") or "")
    if decision_label == "DELAY":
        return "不得判斷岔路、偏離或下切；先取得可靠位置與路線對照。"
    if decision_label == "NO_GO":
        return "不得下切、走捷徑或離開主線；回到可信 CP、開闊點或原路 anchor 重新定位。"
    if decision_label == "GUIDED_ONLY":
        return "不得確認岔路或下降決策；只做保守引導並改善定位品質。"
    if decision_label == "CHANGE_PLAN":
        return "不得繼續進入未知地形；先停止推進並回到可信 anchor。"
    if decision_label == "CONDITIONAL_GO":
        return "不得離開地圖走廊；到下一個 CP 或數分鐘內重新核對。"
    if decision_label == "GO":
        return "維持在路線走廊內；下一個 CP 重新計算位置與地形風險。"
    return "不得離開已知路線走廊；到下一個可信 CP 前持續核對。"


def _navigation_action(decision: str) -> str:
    if decision in {"NO_GO", "CHANGE_PLAN", "DELAY"}:
        return "retreat" if decision == "NO_GO" else "continue"
    return "continue"


def _uncertainty_notes(
    *,
    decision: dict[str, Any],
    missing_fields: list[str],
) -> list[str]:
    notes = []
    if missing_fields:
        notes.append("Missing fields: " + ", ".join(missing_fields[:8]))
    if decision.get("route_fit_status") == "route_fit_unknown":
        notes.append("Route fit is unknown from this snapshot.")
    if decision.get("position_quality_status") in {"poor_quality", "partial_quality"}:
        notes.append(f"Position quality is {decision.get('position_quality_status')}.")
    return notes


def _required_conditions(
    *,
    decision: dict[str, Any],
    missing_fields: list[str],
) -> list[str]:
    conditions = []
    if missing_fields:
        conditions.append("Provide complete position, quality, route-fit, and anchor fields.")
    if decision.get("position_quality_status") in {"poor_quality", "partial_quality"}:
        conditions.append("Improve GNSS/INS-DR quality before confirming branch or descent decisions.")
    if decision.get("route_fit_status") in {"route_fit_unknown", "off_route_candidate"}:
        conditions.append("Reconcile position with offline map, GPX, CP Graph, and last reliable anchor.")
    return conditions


def _navigation_alternatives(*, decision: dict[str, Any]) -> list[str]:
    decision_label = decision.get("decision")
    if decision_label == "NO_GO":
        return [
            "回到最近可信 CP 或原路 anchor。",
            "留在主線或開闊點重新定位。",
            "不要下切溪谷、乾溝或離開主線。",
        ]
    if decision_label in {"DELAY", "GUIDED_ONLY"}:
        return [
            "停止擴大偏差。",
            "核對離線地圖與 GPX。",
            "移動到開闊安全位置後重新取樣。",
        ]
    if decision_label == "CHANGE_PLAN":
        return [
            "停止往未知地形推進。",
            "回到上一個可信 anchor。",
            "重新比對路線走廊後再決策。",
        ]
    return ["在下一個 CP 重新計算位置、heading 與 terrain risk。"]


def _route_fit_status(
    *,
    nearest_route_distance_m: float | None,
    horizontal_accuracy_m: float | None,
    uncertainty_m: float | None,
) -> str:
    if nearest_route_distance_m is None:
        return "route_fit_unknown"
    margin = max(
        value for value in (horizontal_accuracy_m, uncertainty_m, 10.0) if value is not None
    )
    near_edge_threshold = max(20.0, margin * 1.5)
    off_route_threshold = max(60.0, margin * 3.0)
    if nearest_route_distance_m > off_route_threshold:
        return "off_route_candidate"
    if nearest_route_distance_m > near_edge_threshold:
        return "near_corridor_edge"
    return "on_route_corridor"


def _position_quality_status(
    *,
    quality_flags: dict[str, Any],
    missing_fields: list[str],
) -> str:
    usable_keys = (
        "hdop_usable",
        "horizontal_accuracy_usable",
        "satellite_count_usable",
        "uncertainty_usable",
        "fix_quality_usable",
    )
    for key in usable_keys:
        if quality_flags.get(key) is False:
            return "poor_quality"
    critical_missing = {
        "horizontal_accuracy_m",
        "fix_quality",
        "satellite_count",
        "uncertainty_m",
    }
    if critical_missing.intersection(missing_fields):
        return "partial_quality"
    return "usable_quality"


def _terrain_caution_flags(query: str) -> list[str]:
    normalized = str(query or "").lower().replace(" ", "")
    flags = []
    if _has_any(normalized, ("下切", "溪谷", "乾溝", "溝谷", "stream", "gully")):
        flags.append("downcut_or_stream_channel")
    if _has_any(normalized, ("離開主線", "捷徑", "切西瓜", "切路", "shortcut")):
        flags.append("leave_main_route_request")
    if _has_any(normalized, ("岔路", "走對", "轉彎", "主線", "branch", "turn")):
        flags.append("branch_or_mainline_check")
    if _has_any(normalized, ("崩壁", "落石", "碎石", "陡坡", "稜線", "terrain", "slope")):
        flags.append("terrain_risk_context")
    return flags


def _route_query_plan(
    *,
    available_position: bool,
    missing_fields: list[str],
) -> dict[str, Any]:
    if not available_position:
        return {
            "status": "insufficient_position",
            "next_tools": [],
            "missing_position_fields": [
                field for field in ("lat", "lon") if field in missing_fields
            ],
        }
    return {
        "status": "position_available_for_followup",
        "next_tools": [
            "pydantic_ai.tool.search_scout_risk_scores.v0",
            "pydantic_ai.tool.search_scout_terrain_scores.v0",
            "scout.ai.safety_boundary.explain.v0",
        ],
        "note": "Use the provided coordinate as candidate evidence only.",
    }


def _quality_flags(
    *,
    hdop: object,
    horizontal_accuracy_m: object,
    fix_quality: object,
    satellite_count: object,
    uncertainty_m: object,
) -> dict[str, Any]:
    flags: dict[str, Any] = {}
    hdop_value = _float_or_none(hdop)
    accuracy_value = _float_or_none(horizontal_accuracy_m)
    satellites_value = _int_or_none(satellite_count)
    uncertainty_value = _float_or_none(uncertainty_m)
    if hdop_value is not None:
        flags["hdop"] = hdop_value
        flags["hdop_usable"] = hdop_value <= 2.5
    if accuracy_value is not None:
        flags["horizontal_accuracy_m"] = accuracy_value
        flags["horizontal_accuracy_usable"] = accuracy_value <= 15.0
    if satellites_value is not None:
        flags["satellite_count"] = satellites_value
        flags["satellite_count_usable"] = satellites_value >= 4
    if uncertainty_value is not None:
        flags["uncertainty_m"] = uncertainty_value
        flags["uncertainty_usable"] = uncertainty_value <= 20.0
    if not _is_missing(fix_quality):
        normalized = str(fix_quality).strip().lower()
        flags["fix_quality"] = str(fix_quality)
        flags["fix_quality_usable"] = normalized not in {"0", "invalid", "none", "no_fix"}
    return flags


def _load_project(root: Path) -> dict[str, Any]:
    path = root / "project.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _load_live_navigation_snapshot(
    root: Path,
    project: dict[str, Any],
    *,
    explicit_path: str | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    candidates = _candidate_paths(
        root,
        project,
        explicit_path=explicit_path,
        ref_keys=(
            "live_navigation_snapshot_ref",
            "reviewed_live_navigation_snapshot_ref",
            "navigation_snapshot_ref",
        ),
        fallbacks=(
            "outputs/live_navigation_snapshot.reviewed.json",
            "outputs/live_navigation_snapshot.json",
            "outputs/runtime/live_navigation_snapshot.json",
        ),
    )
    report: list[dict[str, Any]] = []
    for label, path in candidates:
        if not path.exists():
            report.append(
                {
                    "source_kind": "live_navigation_snapshot",
                    "status": "missing",
                    "source_path": label,
                    "loaded_count": 0,
                }
            )
            continue
        payload = _load_json_object(path)
        snapshot = _snapshot_from_payload(payload)
        if not snapshot:
            report.append(
                {
                    "source_kind": "live_navigation_snapshot",
                    "status": "invalid_or_empty",
                    "source_path": label,
                    "loaded_count": 0,
                }
            )
            continue
        report.append(
            {
                "source_kind": "live_navigation_snapshot",
                "status": "loaded",
                "source_path": label,
                "loaded_count": 1,
                "artifact_kind": payload.get("artifact_kind"),
                "source_status": payload.get("status") or payload.get("source_status"),
            }
        )
        return snapshot, report
    return {}, report[:3]


def _candidate_paths(
    root: Path,
    project: dict[str, Any],
    *,
    explicit_path: str | None,
    ref_keys: tuple[str, ...],
    fallbacks: tuple[str, ...],
) -> list[tuple[str, Path]]:
    candidates: list[tuple[str, Path]] = []
    if explicit_path:
        candidates.append((explicit_path, _project_path(root, explicit_path)))
    for key in ref_keys:
        ref = project.get(key)
        if isinstance(ref, str) and ref.strip():
            candidates.append((ref, _project_path(root, ref)))
    for ref in fallbacks:
        candidates.append((ref, _project_path(root, ref)))
    deduped: list[tuple[str, Path]] = []
    seen: set[Path] = set()
    for label, path in candidates:
        resolved = path.resolve() if path.exists() else path
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append((label, path))
    return deduped


def _project_path(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _snapshot_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not payload:
        return {}
    nested = payload.get("live_navigation_snapshot")
    if not isinstance(nested, dict):
        nested = payload.get("navigation_snapshot")
    if not isinstance(nested, dict):
        nested = payload.get("snapshot")
    snapshot_source = nested if isinstance(nested, dict) else payload
    snapshot = {
        field: snapshot_source.get(field)
        for field in LIVE_NAVIGATION_REQUIRED_FIELDS
        if not _is_missing(snapshot_source.get(field))
    }
    if "source" not in snapshot:
        source = payload.get("source") or payload.get("provider") or payload.get("status")
        if not _is_missing(source):
            snapshot["source"] = source
    if payload.get("status") and "source_status" not in snapshot:
        snapshot["source_status"] = payload.get("status")
    return snapshot


def _source_status(
    *,
    snapshot: dict[str, Any],
    provided_fields: dict[str, Any],
) -> str:
    if snapshot:
        return str(snapshot.get("source_status") or "loaded_live_navigation_snapshot")
    if provided_fields:
        return "caller_provided_snapshot"
    return "missing_snapshot"


def _first_non_missing(*values: object) -> object:
    for value in values:
        if not _is_missing(value):
            return value
    return None


def _is_missing(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return not value
    return False


def _float_or_none(value: object) -> float | None:
    if _is_missing(value):
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _int_or_none(value: object) -> int | None:
    if _is_missing(value):
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _has_any(text: str, fragments: tuple[str, ...]) -> bool:
    return any(fragment.lower().replace(" ", "") in text for fragment in fragments)


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
        "live_hardware_read_performed": False,
    }
