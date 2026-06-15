from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


EQUIPMENT_RESOURCE_TOOL_ID = "scout.ai.equipment_resource.assess.v0"
EQUIPMENT_RESOURCE_OUTPUT_KIND = "scout_ai_equipment_resource_tool_output"
EQUIPMENT_RESOURCE_REQUIRED_FIELDS = ("project_root",)
EQUIPMENT_RESOURCE_OPTIONAL_FIELDS = (
    "equipment_status_path",
    "resource_plan_path",
    "battery_percent",
    "phone_battery_percent",
    "watch_battery_percent",
    "offline_map_ready",
    "gpx_loaded",
    "headlamp_ready",
    "backup_light_ready",
    "power_bank_percent",
    "water_liters",
    "food_hours",
    "rain_shell_ready",
    "emergency_layer_ready",
    "first_aid_ready",
    "comms_ready",
    "expected_hours_remaining",
    "daylight_hours_remaining",
)

CRITICAL_PHONE_BATTERY_PCT = 10.0
LOW_PHONE_BATTERY_PCT = 25.0
MIN_WATER_LITERS = 0.5
MIN_FOOD_HOURS = 2.0


def assess_scout_equipment_resource(
    project_root: Path | str,
    *,
    query: str = "",
    equipment_status_path: str | None = None,
    resource_plan_path: str | None = None,
    battery_percent: float | int | str | None = None,
    phone_battery_percent: float | int | str | None = None,
    watch_battery_percent: float | int | str | None = None,
    offline_map_ready: bool | str | None = None,
    gpx_loaded: bool | str | None = None,
    headlamp_ready: bool | str | None = None,
    backup_light_ready: bool | str | None = None,
    power_bank_percent: float | int | str | None = None,
    water_liters: float | int | str | None = None,
    food_hours: float | int | str | None = None,
    rain_shell_ready: bool | str | None = None,
    emergency_layer_ready: bool | str | None = None,
    first_aid_ready: bool | str | None = None,
    comms_ready: bool | str | None = None,
    expected_hours_remaining: float | int | str | None = None,
    daylight_hours_remaining: float | int | str | None = None,
) -> dict[str, Any]:
    """Assess Scout equipment/resource readiness without mutating runtime state."""

    root = Path(project_root)
    project = _load_json_object(root / "project.json")
    project_id = str(project.get("project_id") or project.get("id") or root.name)
    source_report: list[dict[str, Any]] = []

    equipment_status, equipment_status_source = _load_optional_json(
        root,
        explicit_path=equipment_status_path,
        project=project,
        project_ref_keys=("equipment_status_ref", "equipment_resource_ref"),
        default_refs=("outputs/equipment_status.json", "outputs/equipment_resource.json"),
        source_kind="equipment_status",
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
    direct = {
        "battery_percent": _float_or_none(battery_percent),
        "phone_battery_percent": _float_or_none(phone_battery_percent),
        "watch_battery_percent": _float_or_none(watch_battery_percent),
        "offline_map_ready": _bool_or_none(offline_map_ready),
        "gpx_loaded": _bool_or_none(gpx_loaded),
        "headlamp_ready": _bool_or_none(headlamp_ready),
        "backup_light_ready": _bool_or_none(backup_light_ready),
        "power_bank_percent": _float_or_none(power_bank_percent),
        "water_liters": _float_or_none(water_liters),
        "food_hours": _float_or_none(food_hours),
        "rain_shell_ready": _bool_or_none(rain_shell_ready),
        "emergency_layer_ready": _bool_or_none(emergency_layer_ready),
        "first_aid_ready": _bool_or_none(first_aid_ready),
        "comms_ready": _bool_or_none(comms_ready),
        "expected_hours_remaining": _float_or_none(expected_hours_remaining),
        "daylight_hours_remaining": _float_or_none(daylight_hours_remaining),
    }
    resource_state = _resource_state(
        direct=direct,
        equipment_status=equipment_status,
        resource_plan=resource_plan,
    )
    missing_fields = _missing_fields(resource_state)
    readiness = _readiness(resource_state=resource_state, missing_fields=missing_fields)
    decision = _decision(readiness=readiness, missing_fields=missing_fields)
    answerability = (
        "equipment_resource_missing_required_fields"
        if missing_fields
        else "equipment_resource_decision_available"
    )
    field_answer = _field_answer(
        decision=decision,
        readiness=readiness,
        missing_fields=missing_fields,
    )
    decision_output = _decision_output(
        decision=decision,
        readiness=readiness,
        resource_state=resource_state,
        missing_fields=missing_fields,
        field_answer=field_answer,
    )

    return {
        "artifact_kind": EQUIPMENT_RESOURCE_OUTPUT_KIND,
        "tool_id": EQUIPMENT_RESOURCE_TOOL_ID,
        "status": "completed",
        "project_id": project_id,
        "query": query,
        "assessment_kind": "read_only_equipment_resource",
        "answerability": answerability,
        "source_status": "candidate_only",
        "decision": decision,
        "decision_output": decision_output,
        "field_answer": field_answer,
        "missing_fields": missing_fields,
        "equipment_resource": {
            "role": "Equipment / Resource Intelligence",
            "candidate_only": True,
            "runtime_safety_truth": False,
            "decision": decision,
            "decision_output": decision_output,
            "critical_gaps": readiness["critical_gaps"],
            "warning_gaps": readiness["warning_gaps"],
            "required_conditions": readiness["required_conditions"],
            "alternative_actions": readiness["alternative_actions"],
            "next_action": readiness["next_action"],
        },
        "resource_readiness": readiness,
        "resource_state": resource_state,
        "source_report": source_report,
        "result_count": 1,
        "results": [
            {
                "label": "equipment resource decision",
                "decision": decision,
                "decision_output": decision_output,
                "answerability": answerability,
                "critical_gaps": readiness["critical_gaps"],
                "warning_gaps": readiness["warning_gaps"],
                "field_answer": field_answer,
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        ],
        "standard_alignment": [
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 18.1 equipment and offline map inputs",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 18.2 pre-trip required outputs",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 19 on-route recalculation",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 22 required development standards",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 23 acceptance criteria",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 24.1 MVP required inputs and conservative missing-evidence behavior",
        ],
        "boundary": _closed_boundary(),
        "debug_sources": {
            "equipment_status_source": equipment_status_source,
            "resource_plan_source": resource_plan_source,
        },
    }


def _resource_state(
    *,
    direct: dict[str, Any],
    equipment_status: dict[str, Any],
    resource_plan: dict[str, Any],
) -> dict[str, Any]:
    devices = _device_summaries(resource_plan) + _device_summaries(equipment_status)
    equipment = _equipment_summaries(resource_plan) + _equipment_summaries(equipment_status)
    hydration = _hydration_summary(direct=direct, resource_plan=resource_plan, equipment_status=equipment_status)
    nutrition = _nutrition_summary(direct=direct, resource_plan=resource_plan, equipment_status=equipment_status)

    phone_battery = _first_float(
        direct.get("phone_battery_percent"),
        direct.get("battery_percent"),
        _device_battery(devices, device_type="phone"),
    )
    watch_battery = _first_float(
        direct.get("watch_battery_percent"),
        _device_battery(devices, device_type="watch"),
    )
    power_bank = _first_float(
        direct.get("power_bank_percent"),
        _device_battery(devices, device_type="power_bank"),
    )
    offline_map_ready = _first_bool(
        direct.get("offline_map_ready"),
        _capability_ready(devices, "offline_map"),
        _status_bool(_nested(equipment_status, "offline_map", "ready")),
    )
    gpx_loaded = _first_bool(
        direct.get("gpx_loaded"),
        _capability_ready(devices, "gpx"),
        _status_bool(_nested(equipment_status, "gpx", "loaded")),
    )
    headlamp_ready = _first_bool(
        direct.get("headlamp_ready"),
        _equipment_ready(equipment, "headlamp"),
        _status_bool(_nested(equipment_status, "headlamp", "ready")),
    )
    backup_light_ready = _first_bool(
        direct.get("backup_light_ready"),
        _equipment_ready(equipment, "backup_light"),
        _equipment_ready(equipment, "spare_headlamp"),
        _status_bool(_nested(equipment_status, "backup_light", "ready")),
    )
    rain_shell_ready = _first_bool(
        direct.get("rain_shell_ready"),
        _equipment_ready(equipment, "rain_shell"),
        _equipment_ready(equipment, "rain_jacket"),
    )
    emergency_layer_ready = _first_bool(
        direct.get("emergency_layer_ready"),
        _equipment_ready(equipment, "emergency_layer"),
        _equipment_ready(equipment, "warm_layer"),
    )
    first_aid_ready = _first_bool(
        direct.get("first_aid_ready"),
        _equipment_ready(equipment, "first_aid"),
        _equipment_ready(equipment, "first_aid_kit"),
    )
    comms_ready = _first_bool(
        direct.get("comms_ready"),
        _capability_ready(devices, "cellular_checkin"),
        _status_bool(_nested(equipment_status, "communication", "ready")),
    )

    return {
        "candidate_only": True,
        "runtime_safety_truth": False,
        "device_count": len(devices),
        "equipment_count": len(equipment),
        "devices": devices[:8],
        "equipment": equipment[:12],
        "phone_battery_percent": phone_battery,
        "watch_battery_percent": watch_battery,
        "power_bank_percent": power_bank,
        "offline_map_ready": offline_map_ready,
        "gpx_loaded": gpx_loaded,
        "headlamp_ready": headlamp_ready,
        "backup_light_ready": backup_light_ready,
        "rain_shell_ready": rain_shell_ready,
        "emergency_layer_ready": emergency_layer_ready,
        "first_aid_ready": first_aid_ready,
        "comms_ready": comms_ready,
        "water_liters": _first_float(direct.get("water_liters"), hydration.get("water_liters")),
        "food_hours": _first_float(direct.get("food_hours"), nutrition.get("food_hours")),
        "expected_hours_remaining": direct.get("expected_hours_remaining"),
        "daylight_hours_remaining": direct.get("daylight_hours_remaining"),
        "resource_plan_warnings": _resource_plan_warnings(resource_plan),
    }


def _readiness(
    *,
    resource_state: dict[str, Any],
    missing_fields: list[str],
) -> dict[str, Any]:
    critical_gaps: list[str] = []
    warning_gaps: list[str] = []
    required_conditions: list[str] = []
    alternative_actions: list[str] = []

    phone_battery = _float_or_none(resource_state.get("phone_battery_percent"))
    watch_battery = _float_or_none(resource_state.get("watch_battery_percent"))
    power_bank = _float_or_none(resource_state.get("power_bank_percent"))
    if phone_battery is not None:
        if phone_battery <= 0:
            if watch_battery is not None:
                critical_gaps.append(
                    "主要手機已無可用電量；手錶有電不能單獨取代主要離線地圖、GPX、通訊與回報能力。"
                )
            else:
                critical_gaps.append("主要手機已無可用電量。")
            required_conditions.append(
                "先恢復主要手機電量，或切換到已審核的備援導航與通訊方案。"
            )
            alternative_actions.append("原地補電、改短線、撤退或採 GUIDED_ONLY。")
        elif phone_battery <= CRITICAL_PHONE_BATTERY_PCT and not _has_usable_power_bank(power_bank):
            critical_gaps.append("手機電量過低且沒有可靠行動電源。")
            required_conditions.append("補足手機電量或確認可用行動電源。")
            alternative_actions.append("改短路線、延後出發或採 GUIDED_ONLY。")
        elif phone_battery <= CRITICAL_PHONE_BATTERY_PCT:
            warning_gaps.append("手機電量極低，即使有行動電源也需先補電再推進。")
            required_conditions.append("停下來補電並確認主要導航與通訊恢復。")
        elif phone_battery <= LOW_PHONE_BATTERY_PCT:
            warning_gaps.append("手機電量偏低，需保留導航與回報電量。")
            required_conditions.append("開啟省電模式並指定備援導航裝置。")
    elif "phone_battery_percent" not in missing_fields:
        warning_gaps.append("未取得主要手機電量。")

    if resource_state.get("offline_map_ready") is False:
        critical_gaps.append("離線地圖未就緒。")
        required_conditions.append("所有關鍵裝置下載離線地圖。")
        alternative_actions.append("不要進入低訊號路段；改由可確認地圖的人帶隊或延後。")
    if resource_state.get("gpx_loaded") is False:
        critical_gaps.append("GPX/路線檔未載入。")
        required_conditions.append("載入 GPX 或 reviewed route package。")
    if resource_state.get("headlamp_ready") is False:
        critical_gaps.append("頭燈未就緒。")
        required_conditions.append("補足頭燈與電池。")
    if resource_state.get("backup_light_ready") is False:
        warning_gaps.append("缺少備用照明。")
        required_conditions.append("補一組備用照明或縮短到不摸黑路線。")
    if resource_state.get("rain_shell_ready") is False:
        warning_gaps.append("雨具/防水層未確認。")
        required_conditions.append("補齊雨具，尤其是天氣窗口不穩時。")
    if resource_state.get("emergency_layer_ready") is False:
        warning_gaps.append("保暖/緊急層未確認。")
    if resource_state.get("first_aid_ready") is False:
        warning_gaps.append("急救包未確認。")
    if resource_state.get("comms_ready") is False:
        warning_gaps.append("通訊/回報能力未確認。")

    water_liters = _float_or_none(resource_state.get("water_liters"))
    if water_liters is not None and water_liters < MIN_WATER_LITERS:
        critical_gaps.append(f"水量約 {water_liters:g} L，低於 Scout 保守門檻。")
        required_conditions.append("補水或改到可補給/短版路線。")
        alternative_actions.append("延後出發、縮短行程或回到補給點。")
    food_hours = _float_or_none(resource_state.get("food_hours"))
    if food_hours is not None and food_hours < MIN_FOOD_HOURS:
        warning_gaps.append(f"食物/熱量只覆蓋約 {food_hours:g} 小時。")
        required_conditions.append("補足行動糧或降低行程負荷。")

    for warning in resource_state.get("resource_plan_warnings", []):
        if isinstance(warning, str) and warning not in warning_gaps:
            warning_gaps.append(warning)

    if missing_fields:
        required_conditions.extend(f"Provide {field}." for field in missing_fields)
    next_action = _next_action(
        missing_fields=missing_fields,
        critical_gaps=critical_gaps,
        warning_gaps=warning_gaps,
    )
    return {
        "critical_gaps": critical_gaps,
        "warning_gaps": warning_gaps[:6],
        "required_conditions": _dedupe(required_conditions),
        "alternative_actions": _dedupe(alternative_actions)
        or ["補齊裝備資料後再做 Go/No-Go。", "改短版或延後出發。"],
        "next_action": next_action,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _decision(*, readiness: dict[str, Any], missing_fields: list[str]) -> str:
    if readiness["critical_gaps"]:
        return "NO_GO"
    if missing_fields:
        return "DELAY"
    if readiness["warning_gaps"] or readiness["required_conditions"]:
        return "CONDITIONAL_GO"
    return "GO"


def _field_answer(
    *,
    decision: str,
    readiness: dict[str, Any],
    missing_fields: list[str],
) -> str:
    if missing_fields:
        return (
            "裝備資源判斷：建議 DELAY。缺少 "
            + "、".join(missing_fields)
            + "；Scout 不能在裝備、離線地圖、電量、水或食物不明時給出輕率 permission。"
        )
    reasons = readiness["critical_gaps"] or readiness["warning_gaps"] or ["裝備資源資料未顯示主要缺口。"]
    reason_text = "；".join(reasons[:2])
    return (
        f"裝備資源判斷：建議 {decision}。{reason_text} "
        f"下一步：{readiness['next_action']} "
        "此為 Equipment / Resource 候選判斷，不是 runtime safety truth；不得觸發 /safety、SOS、outbound send 或硬體控制。"
    )


def _decision_output(
    *,
    decision: str,
    readiness: dict[str, Any],
    resource_state: dict[str, Any],
    missing_fields: list[str],
    field_answer: str,
) -> dict[str, Any]:
    allowed = decision in {"GO", "CONDITIONAL_GO"}
    reasons = _decision_reasons(readiness=readiness, missing_fields=missing_fields)
    uncertainty_notes = [f"Missing field: {field}" for field in missing_fields]
    first_layer = {
        "decision": _decision_phrase(decision=decision, allowed=allowed),
        "limit": _decision_limit_phrase(decision=decision),
        "reason": " / ".join(reasons[:2]),
        "nextStep": readiness["next_action"],
    }
    second_layer = {
        "details": _decision_details(
            resource_state=resource_state,
            field_answer=field_answer,
        ),
        "uncertaintyNotes": uncertainty_notes,
        "residualRisk": [
            "Equipment and resource evidence is candidate-only.",
            "Runtime safety truth, /safety, SOS, outbound send, and hardware control were not triggered.",
        ],
        "requiredConditions": readiness["required_conditions"],
        "alternativeActions": readiness["alternative_actions"],
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
        "action": "equipment_resource_readiness",
        "decision": decision,
        "allowed": allowed,
        "locationConstraint": first_layer["limit"],
        "mainReasons": reasons[:3],
        "cost": {
            "phoneBatteryPercent": resource_state.get("phone_battery_percent"),
            "powerBankPercent": resource_state.get("power_bank_percent"),
            "waterLiters": resource_state.get("water_liters"),
            "foodHours": resource_state.get("food_hours"),
            "offlineMapReady": resource_state.get("offline_map_ready"),
            "gpxLoaded": resource_state.get("gpx_loaded"),
        },
        "nextAction": readiness["next_action"],
        "confidence": "low" if uncertainty_notes else "medium",
        "uncertaintyNotes": uncertainty_notes,
        "residualRisk": second_layer["residualRisk"],
        "requiredConditions": readiness["required_conditions"],
        "alternativeActions": readiness["alternative_actions"],
        "standardAlignment": [
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 18.1 equipment and offline map inputs",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 18.2 required outputs",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 16 required decision output format",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 17 ContextualPermission schema",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 24.1 MVP required inputs",
        ],
        "runtimeSafetyTruth": False,
    }


def _decision_reasons(
    *, readiness: dict[str, Any], missing_fields: list[str]
) -> list[str]:
    reasons = []
    reasons.extend(readiness["critical_gaps"])
    reasons.extend(readiness["warning_gaps"])
    if missing_fields:
        reasons.append("缺少 " + "、".join(missing_fields[:5]))
    if not reasons:
        reasons.append("裝備資源資料未顯示主要缺口。")
    return _dedupe(reasons)


def _decision_phrase(*, decision: str, allowed: bool) -> str:
    if decision == "NO_GO":
        return "不建議照原計畫出發或推進。"
    if decision == "DELAY":
        return "建議延後裝備資源判斷。"
    if decision == "CONDITIONAL_GO":
        return "可有條件進入下一步規劃。"
    if decision == "GO" and allowed:
        return "裝備資源可進入下一步。"
    return "暫緩判斷。"


def _decision_limit_phrase(*, decision: str) -> str:
    if decision == "NO_GO":
        return "補齊關鍵裝備、離線地圖、GPX、電量、水或食物前，不得照原計畫出發或推進。"
    if decision == "DELAY":
        return "資料缺口補齊前，不得把此回答當成 departure approval 或現場 permission。"
    if decision == "CONDITIONAL_GO":
        return "必須先滿足 required conditions，且仍需天氣、腳程、隊伍與 runtime gate。"
    return "這不是 runtime safety truth；下一個 CP 或出發前仍需重算資源狀態。"


def _decision_details(
    *, resource_state: dict[str, Any], field_answer: str
) -> list[str]:
    details = [
        field_answer,
        f"phone_battery_percent={resource_state.get('phone_battery_percent')}",
        f"power_bank_percent={resource_state.get('power_bank_percent')}",
        f"offline_map_ready={resource_state.get('offline_map_ready')}",
        f"gpx_loaded={resource_state.get('gpx_loaded')}",
        f"headlamp_ready={resource_state.get('headlamp_ready')}",
        f"water_liters={resource_state.get('water_liters')}",
        f"food_hours={resource_state.get('food_hours')}",
    ]
    warnings = resource_state.get("resource_plan_warnings")
    if isinstance(warnings, list) and warnings:
        details.append("resource_plan_warnings=" + " / ".join(str(item) for item in warnings[:3]))
    return details


def _missing_fields(resource_state: dict[str, Any]) -> list[str]:
    missing = []
    required = (
        "phone_battery_percent",
        "offline_map_ready",
        "gpx_loaded",
        "headlamp_ready",
        "water_liters",
        "food_hours",
    )
    for field in required:
        if resource_state.get(field) is None:
            missing.append(field)
    return missing


def _next_action(
    *,
    missing_fields: list[str],
    critical_gaps: list[str],
    warning_gaps: list[str],
) -> str:
    if missing_fields:
        return "先補齊裝備/資源資料，再做出發或現場微決策。"
    if critical_gaps:
        return "不要照原計畫出發或推進；先補裝備、改短版或延後。"
    if warning_gaps:
        return "可以進入下一步規劃，但必須先滿足 required conditions 並保留替代方案。"
    return "維持計畫，下一個 CP 或出發前再重算電量、水、食物與離線地圖狀態。"


def _device_summaries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    devices = payload.get("devices")
    if not isinstance(devices, list):
        devices = payload.get("device_status")
    if not isinstance(devices, list):
        return []
    summaries = []
    for item in devices:
        if not isinstance(item, dict):
            continue
        raw_labels = item.get("capability_labels")
        labels = raw_labels if isinstance(raw_labels, list) else []
        summaries.append(
            {
                "device_id": item.get("device_id") or item.get("id"),
                "device_type": item.get("device_type") or item.get("type"),
                "readiness": item.get("readiness") or item.get("status"),
                "estimated_start_battery_pct": _float_or_none(
                    item.get("estimated_start_battery_pct")
                    or item.get("battery_percent")
                    or item.get("battery_pct")
                ),
                "capability_labels": [str(label) for label in labels],
                "review_state": _nested(item, "review", "review_state"),
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        )
    return summaries


def _equipment_summaries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    equipment = payload.get("equipment")
    if not isinstance(equipment, list):
        equipment = payload.get("inventory")
    if not isinstance(equipment, list):
        return []
    summaries = []
    for item in equipment:
        if not isinstance(item, dict):
            continue
        summaries.append(
            {
                "item_id": item.get("item_id") or item.get("equipment_id") or item.get("id"),
                "item_type": (
                    item.get("item_type")
                    or item.get("type")
                    or item.get("category")
                    or item.get("label")
                    or item.get("name")
                ),
                "readiness": item.get("readiness") or item.get("status"),
                "quantity": item.get("quantity"),
                "review_state": _nested(item, "review", "review_state"),
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        )
    return summaries


def _hydration_summary(
    *,
    direct: dict[str, Any],
    resource_plan: dict[str, Any],
    equipment_status: dict[str, Any],
) -> dict[str, Any]:
    value = _first_float(
        direct.get("water_liters"),
        _nested(resource_plan, "hydration", "water_liters"),
        _nested(resource_plan, "water", "liters"),
        _nested(equipment_status, "hydration", "water_liters"),
    )
    return {"water_liters": value}


def _nutrition_summary(
    *,
    direct: dict[str, Any],
    resource_plan: dict[str, Any],
    equipment_status: dict[str, Any],
) -> dict[str, Any]:
    value = _first_float(
        direct.get("food_hours"),
        _nested(resource_plan, "nutrition", "food_hours"),
        _nested(resource_plan, "food", "hours"),
        _nested(equipment_status, "nutrition", "food_hours"),
    )
    return {"food_hours": value}


def _resource_plan_warnings(resource_plan: dict[str, Any]) -> list[str]:
    context = resource_plan.get("departure_readiness_context")
    if not isinstance(context, dict):
        return []
    warnings = context.get("warning_candidates")
    if not isinstance(warnings, list):
        return []
    return [str(item) for item in warnings if str(item).strip()]


def _device_battery(devices: list[dict[str, Any]], *, device_type: str) -> float | None:
    candidates = [
        _float_or_none(device.get("estimated_start_battery_pct"))
        for device in devices
        if str(device.get("device_type") or "").lower() == device_type
    ]
    candidates = [value for value in candidates if value is not None]
    return min(candidates) if candidates else None


def _capability_ready(devices: list[dict[str, Any]], capability: str) -> bool | None:
    matches = []
    for device in devices:
        labels = device.get("capability_labels")
        if not isinstance(labels, list) or capability not in {str(label) for label in labels}:
            continue
        matches.append(_readiness_bool(device.get("readiness")))
    matches = [value for value in matches if value is not None]
    if not matches:
        return None
    return any(matches)


def _equipment_ready(equipment: list[dict[str, Any]], item_type: str) -> bool | None:
    matches = []
    for item in equipment:
        raw = " ".join(
            str(part or "").lower()
            for part in (item.get("item_id"), item.get("item_type"))
        )
        if item_type.lower() not in raw:
            continue
        matches.append(_readiness_bool(item.get("readiness")))
    matches = [value for value in matches if value is not None]
    if not matches:
        return None
    return any(matches)


def _readiness_bool(value: Any) -> bool | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in {"ready", "ok", "available", "confirmed", "true", "yes"}:
        return True
    if normalized in {"missing", "not_ready", "unavailable", "false", "no", "unknown"}:
        return False
    return None


def _status_bool(value: Any) -> bool | None:
    return _bool_or_none(value) if value is not None else None


def _has_usable_power_bank(value: float | None) -> bool:
    return value is not None and value >= 30.0


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


def _nested(payload: dict[str, Any], *keys: str) -> Any:
    value: Any = payload
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _first_float(*values: Any) -> float | None:
    for value in values:
        parsed = _float_or_none(value)
        if parsed is not None:
            return parsed
    return None


def _first_bool(*values: Any) -> bool | None:
    for value in values:
        parsed = _bool_or_none(value)
        if parsed is not None:
            return parsed
    return None


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


def _bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y", "ready", "ok", "confirmed"}:
        return True
    if normalized in {"0", "false", "no", "n", "missing", "not_ready", "unknown"}:
        return False
    return None


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
        "outbound_send_performed": False,
        "live_hardware_read_performed": False,
    }
