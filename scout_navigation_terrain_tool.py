from __future__ import annotations

from pathlib import Path
from typing import Any

from pretrip_navigation_terrain_collection import collect_pretrip_navigation_terrain


NAVIGATION_TERRAIN_TOOL_ID = "scout.ai.navigation_terrain.assess.v0"
NAVIGATION_TERRAIN_OUTPUT_KIND = "scout_ai_navigation_terrain_tool_output"
NAVIGATION_TERRAIN_REQUIRED_FIELDS = ("project_root",)
NAVIGATION_TERRAIN_OPTIONAL_FIELDS = (
    "offline_map_downloaded",
    "gpx_loaded_on_device",
    "contour_skill_confirmed",
    "terrain_feature_skill_confirmed",
    "junction_points_known",
    "retreat_direction_understood",
    "backup_positioning_available",
    "terrain_risk_layers_understood",
    "team_map_user_count",
)


def assess_scout_navigation_terrain(
    project_root: Path | str,
    *,
    query: str = "",
    offline_map_downloaded: bool | str | None = None,
    gpx_loaded_on_device: bool | str | None = None,
    contour_skill_confirmed: bool | str | None = None,
    terrain_feature_skill_confirmed: bool | str | None = None,
    junction_points_known: bool | str | None = None,
    retreat_direction_understood: bool | str | None = None,
    backup_positioning_available: bool | str | None = None,
    terrain_risk_layers_understood: bool | str | None = None,
    team_map_user_count: int | str | None = None,
) -> dict[str, Any]:
    """Assess Sec. 11 navigation terrain readiness without writing workspace files."""

    collection = collect_pretrip_navigation_terrain(
        project_root,
        dry_run=True,
        offline_map_downloaded=offline_map_downloaded,
        gpx_loaded_on_device=gpx_loaded_on_device,
        contour_skill_confirmed=contour_skill_confirmed,
        terrain_feature_skill_confirmed=terrain_feature_skill_confirmed,
        junction_points_known=junction_points_known,
        retreat_direction_understood=retreat_direction_understood,
        backup_positioning_available=backup_positioning_available,
        terrain_risk_layers_understood=terrain_risk_layers_understood,
        team_map_user_count=team_map_user_count,
    )
    decision = str(collection.get("decision") or "DELAY")
    missing_fields = _text_list(collection.get("missing_fields"))
    required_actions = _text_list(collection.get("required_actions"))
    navigation_demand = _dict(collection.get("navigation_demand"))
    map_readiness = _dict(collection.get("map_readiness"))
    terrain_readiness = _dict(collection.get("terrain_readiness"))
    positioning_readiness = _dict(collection.get("positioning_readiness"))
    map_skill_readiness = _dict(collection.get("map_skill_readiness"))
    answerability = str(collection.get("answerability") or "navigation_terrain_unknown")
    field_answer = _field_answer(
        decision=decision,
        missing_fields=missing_fields,
        required_actions=required_actions,
        navigation_demand=navigation_demand,
    )
    decision_output = _decision_output(
        decision=decision,
        answerability=answerability,
        field_answer=field_answer,
        missing_fields=missing_fields,
        required_actions=required_actions,
        navigation_demand=navigation_demand,
    )

    return {
        "artifact_kind": NAVIGATION_TERRAIN_OUTPUT_KIND,
        "tool_id": NAVIGATION_TERRAIN_TOOL_ID,
        "status": "completed",
        "project_id": collection.get("project_id"),
        "query": query,
        "assessment_kind": "read_only_navigation_terrain_readiness",
        "answerability": answerability,
        "source_status": "candidate_only",
        "decision": decision,
        "allowed": decision in {"GO", "CONDITIONAL_GO"},
        "decision_output": decision_output,
        "field_answer": field_answer,
        "missing_fields": missing_fields,
        "navigation_terrain": {
            "role": "Navigation & Terrain Intelligence / Map Readiness",
            "candidate_only": True,
            "runtime_safety_truth": False,
            "decision": decision,
            "decision_output": decision_output,
            "navigation_demand": navigation_demand,
            "map_readiness": map_readiness,
            "terrain_readiness": terrain_readiness,
            "positioning_readiness": positioning_readiness,
            "map_skill_readiness": map_skill_readiness,
            "required_actions": required_actions,
            "next_action": decision_output["nextAction"],
        },
        "navigation_demand": navigation_demand,
        "map_readiness": map_readiness,
        "terrain_readiness": terrain_readiness,
        "positioning_readiness": positioning_readiness,
        "map_skill_readiness": map_skill_readiness,
        "required_actions": required_actions,
        "source_report": collection.get("source_report") or [],
        "result_count": 1,
        "results": [
            {
                "label": "navigation terrain readiness decision",
                "decision": decision,
                "decision_output": decision_output,
                "answerability": answerability,
                "field_answer": field_answer,
                "navigation_terrain": {
                    "role": "Navigation & Terrain Intelligence / Map Readiness",
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                },
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        ],
        "standard_alignment": [
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 11 Navigation & Terrain Intelligence",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 18.1 map and navigation required inputs",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 18.2 pre-trip required outputs",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 23 acceptance criteria",
        ],
        "boundary": _closed_boundary(),
        "debug_collection": {
            "dry_run": collection.get("dry_run"),
            "writes_performed": collection.get("writes_performed"),
            "planned_refs": collection.get("planned_refs") or [],
        },
    }


def _field_answer(
    *,
    decision: str,
    missing_fields: list[str],
    required_actions: list[str],
    navigation_demand: dict[str, Any],
) -> str:
    demand = str(navigation_demand.get("demand_level") or "unknown")
    reasons = _text_list(navigation_demand.get("reasons"))
    reason_text = "；".join(reasons[:2]) or f"navigation_demand={demand}"
    if decision == "GUIDED_ONLY":
        actions = "；".join(required_actions[:3]) or "補齊離線地圖、地形判讀與定位備援。"
        return (
            "地圖力判斷：建議 GUIDED_ONLY。"
            f"{reason_text}；{actions} "
            "不建議自主前往；可參加有嚮導活動，或先完成離線地圖、地形判讀、撤退方向與定位備援訓練。 "
            "此為 Navigation & Terrain 候選判斷，不是 departure approval 或 runtime safety truth；不得觸發 /safety、SOS、outbound send 或硬體控制。"
        )
    if decision == "CHANGE_PLAN":
        return (
            "地圖力判斷：建議 CHANGE_PLAN。"
            f"{reason_text}；缺少可支撐導航判斷的地圖、路線或地形風險材料。 "
            "先改線、補齊 reviewed map package，或改成有經驗帶領的低需求路線。 "
            "此為 Navigation & Terrain 候選判斷，不是 runtime safety truth。"
        )
    if missing_fields:
        return (
            "地圖力判斷：建議 CONDITIONAL_GO，但不得視為自主出發批准。缺少 "
            + "、".join(missing_fields)
            + "；補齊前不能把此回答當作 departure approval。"
        )
    if decision == "GO":
        return (
            "地圖力判斷：建議 GO 進入人工出發門檢。"
            f"{reason_text}；仍需每個人確認離線地圖、GPX、撤退方向與備援定位。"
        )
    return (
        f"地圖力判斷：建議 {decision}。{reason_text} "
        "此為 Navigation & Terrain 候選判斷，不是 runtime safety truth。"
    )


def _decision_output(
    *,
    decision: str,
    answerability: str,
    field_answer: str,
    missing_fields: list[str],
    required_actions: list[str],
    navigation_demand: dict[str, Any],
) -> dict[str, Any]:
    allowed = decision in {"GO", "CONDITIONAL_GO"}
    reasons = _main_reasons(
        missing_fields=missing_fields,
        required_actions=required_actions,
        navigation_demand=navigation_demand,
    )
    next_action = _next_action(decision=decision, missing_fields=missing_fields)
    first_layer = {
        "decision": _decision_phrase(decision=decision, allowed=allowed),
        "limit": _decision_limit(decision=decision),
        "reason": " / ".join(reasons[:2]),
        "nextStep": next_action,
    }
    return {
        "role": "Pre-Trip Navigation Terrain Agent",
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
        "secondLayer": {
            "details": [field_answer],
            "uncertaintyNotes": [f"Missing field: {field}" for field in missing_fields],
            "residualRisk": [
                "Navigation terrain evidence is candidate-only.",
                "Runtime safety truth, /safety, SOS, outbound send, and hardware control were not triggered.",
            ],
            "requiredConditions": required_actions,
            "alternativeActions": [
                "改成合格嚮導或經驗領隊帶領。",
                "先完成離線地圖、GPX、等高線、撤退方向與定位備援訓練。",
                "改選低地圖力需求的短版或訓練路線。",
            ],
        },
        "action": "pretrip_navigation_terrain_readiness",
        "decision": decision,
        "allowed": allowed,
        "locationConstraint": first_layer["limit"],
        "mainReasons": reasons[:3],
        "cost": {
            "navigationDemandLevel": navigation_demand.get("demand_level"),
            "mapSkillGapCount": len(required_actions),
            "autonomousDepartureAllowed": decision not in {"GUIDED_ONLY", "CHANGE_PLAN"},
        },
        "nextAction": next_action,
        "confidence": "low" if missing_fields else "medium",
        "uncertaintyNotes": [f"Missing field: {field}" for field in missing_fields],
        "residualRisk": [
            "Candidate navigation terrain readiness does not authorize runtime navigation.",
        ],
        "requiredConditions": required_actions,
        "alternativeActions": [
            "Use a guided trip or experienced leader.",
            "Complete map/terrain/navigation drills before autonomous departure.",
        ],
        "answerability": answerability,
        "runtimeSafetyTruth": False,
        "departureApprovalGranted": False,
        "standardAlignment": [
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 11 Navigation & Terrain Intelligence",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 16 required decision output format",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 18 pre-trip workflow",
        ],
    }


def _main_reasons(
    *,
    missing_fields: list[str],
    required_actions: list[str],
    navigation_demand: dict[str, Any],
) -> list[str]:
    reasons = []
    demand_level = navigation_demand.get("demand_level")
    if demand_level:
        reasons.append(f"navigation_demand_level={demand_level}")
    reasons.extend(_text_list(navigation_demand.get("reasons"))[:2])
    reasons.extend(required_actions[:3])
    if missing_fields:
        reasons.append("缺少 " + "、".join(missing_fields[:5]))
    return _dedupe(reasons) or ["Navigation terrain readiness did not expose a reason."]


def _decision_phrase(*, decision: str, allowed: bool) -> str:
    if decision == "GUIDED_ONLY":
        return "不建議自主前往。"
    if decision == "CHANGE_PLAN":
        return "必須改計畫。"
    if decision == "GO" and allowed:
        return "可進入人工出發門檢。"
    if decision == "CONDITIONAL_GO":
        return "只可有條件進入人工出發門檢。"
    if decision == "NO_GO":
        return "不建議出發。"
    return "暫緩判斷。"


def _decision_limit(*, decision: str) -> str:
    if decision == "GUIDED_ONLY":
        return "不得自主出發；只可在合格嚮導、經驗領隊或等效審核控制下重新評估。"
    if decision == "CHANGE_PLAN":
        return "不得照原計畫出發；先補齊 reviewed map package 或改低需求路線。"
    if decision == "CONDITIONAL_GO":
        return "所有 required actions 完成前，不得把此回答當成自主出發批准。"
    if decision == "GO":
        return "仍需人工 departure gate；runtime 前要重算位置、天氣、腳程與裝備。"
    return "不得把此候選判斷當成 departure approval 或 runtime safety truth。"


def _next_action(*, decision: str, missing_fields: list[str]) -> str:
    if decision == "GUIDED_ONLY":
        return "改成有合格嚮導/經驗領隊，或先完成地圖力與定位備援訓練。"
    if decision == "CHANGE_PLAN":
        return "補齊 reviewed map package 或改選低地圖力需求路線。"
    if missing_fields:
        return "補齊地圖力 readiness answers，再重新評估。"
    return "進入人工出發門檢，並保留撤退方向與定位備援。"


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item).strip() for item in value if str(item).strip()]
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


def _closed_boundary() -> dict[str, Any]:
    return {
        "read_only": True,
        "runtime_safety_truth": False,
        "live_safety_api_calls_allowed": False,
        "phase1_safety_mutation_allowed": False,
        "remote_outbound_send_allowed": False,
        "hardware_control_allowed": False,
        "raw_payloads_embedded": False,
        "model_output_is_runtime_truth": False,
    }
