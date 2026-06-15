from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any


WEATHER_WINDOW_TOOL_ID = "scout.ai.weather_window.assess.v0"
WEATHER_WINDOW_OUTPUT_KIND = "scout_ai_weather_window_tool_output"
WEATHER_WINDOW_REQUIRED_FIELDS = ("project_root",)
WEATHER_WINDOW_OPTIONAL_FIELDS = (
    "weather_evidence_path",
    "route_weather_package_path",
    "valid_from",
    "valid_to",
    "segment",
    "include_segments",
    "stale_after_hours",
)

FRESH_WEATHER_FIELDS = (
    "provider",
    "issued_at",
    "valid_from",
    "valid_to",
    "ttl_s",
)

DEFAULT_STALE_AFTER_HOURS = 72.0
DEFAULT_RESULT_LIMIT = 6
MAX_RESULT_LIMIT = 12

_HIGH_RISK_LEVELS = {"high", "very_high", "critical", "severe", "extreme"}


def assess_scout_weather_window(
    project_root: Path | str,
    *,
    query: str = "",
    weather_evidence_path: str | None = None,
    route_weather_package_path: str | None = None,
    valid_from: str | None = None,
    valid_to: str | None = None,
    segment: str | None = None,
    include_segments: bool | str | None = None,
    stale_after_hours: float | int | str | None = None,
    limit: int = DEFAULT_RESULT_LIMIT,
) -> dict[str, Any]:
    """Assess local route weather evidence without calling live providers.

    This tool deliberately consumes only workspace artifacts. A server-side
    CWA ingestor can generate ``route_weather_package.json`` later, but the
    assistant tool must not fetch CWA directly or expose API keys.
    """

    root = Path(project_root)
    project = _load_json_object(root / "project.json")
    project_id = str(project.get("project_id") or project.get("id") or root.name)
    resolved_limit = _bounded_limit(limit)
    include_segment_results = _bool_value(include_segments, default=True)
    stale_hours = _float_or_default(
        stale_after_hours,
        default=DEFAULT_STALE_AFTER_HOURS,
    )

    route_package, route_report = _load_route_weather_package(
        root,
        project,
        explicit_path=route_weather_package_path,
    )
    weather_evidence, weather_report = _load_weather_daylight_evidence(
        root,
        project,
        explicit_path=weather_evidence_path,
    )

    source_report = [*route_report, *weather_report]
    route_segments = _route_weather_segments(route_package)
    filtered_segments = _filter_segments(
        route_segments,
        valid_from=valid_from,
        valid_to=valid_to,
        segment=segment,
    )
    filtered_segments.sort(key=_segment_sort_key)
    top_segments = filtered_segments[:resolved_limit] if include_segment_results else []

    weather_window = _weather_window_summary(
        route_package=route_package,
        weather_evidence=weather_evidence,
    )
    risk_summary = _risk_summary(filtered_segments)
    wx_alerts = _wx_alerts(filtered_segments, limit=resolved_limit)
    missing_fields = _missing_weather_fields(
        route_package=route_package,
        weather_evidence=weather_evidence,
    )
    warnings = _warnings(
        route_package=route_package,
        weather_evidence=weather_evidence,
        missing_fields=missing_fields,
        stale_after_hours=stale_hours,
    )
    answerability = (
        "route_weather_risk_available"
        if route_segments and not missing_fields
        else "route_weather_risk_partial"
        if route_segments
        else "weather_placeholder_only"
        if weather_evidence
        else "weather_evidence_missing"
    )
    weather_to_decision = _weather_to_decision(
        answerability=answerability,
        weather_window=weather_window,
        risk_summary=risk_summary,
        wx_alerts=wx_alerts,
        segments=filtered_segments,
        missing_fields=missing_fields,
        warnings=warnings,
    )
    field_answer = _field_answer(
        decision=weather_to_decision,
        answerability=answerability,
        missing_fields=missing_fields,
    )
    decision_output = _decision_output(
        decision=weather_to_decision,
        missing_fields=missing_fields,
        field_answer=field_answer,
    )

    return {
        "tool_id": WEATHER_WINDOW_TOOL_ID,
        "status": "completed",
        "project_id": project_id,
        "query": query,
        "assessment_kind": "read_only_route_weather_window",
        "answerability": answerability,
        "source_status": _source_status(route_package, weather_evidence),
        "authoritative_weather_computed": _bool_from_sources(
            "authoritative_weather_computed",
            route_package,
            weather_evidence,
        ),
        "decision": weather_to_decision["decision"],
        "decision_output": decision_output,
        "field_answer": field_answer,
        "weather_to_decision": weather_to_decision,
        "external_api_calls_made": _bool_from_sources(
            "external_api_calls_made",
            route_package,
            weather_evidence,
        ),
        "human_review_required": _human_review_required(
            route_package,
            weather_evidence,
            missing_fields,
        ),
        "filters": {
            "valid_from": valid_from,
            "valid_to": valid_to,
            "segment": segment,
            "include_segments": include_segment_results,
            "stale_after_hours": stale_hours,
        },
        "weather_window": weather_window,
        "threshold_policy": _threshold_policy(weather_evidence),
        "risk_summary": risk_summary,
        "wx_alerts": wx_alerts,
        "missing_fields": missing_fields,
        "warnings": warnings,
        "source_report": source_report,
        "searched_segment_count": len(route_segments),
        "matched_segment_count": len(filtered_segments),
        "result_count": len(top_segments),
        "results": [_compact_segment(segment_item) for segment_item in top_segments],
        "route_weather_package_schema": _route_weather_package_schema(),
        "standard_alignment": [
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 10 Weather-to-Decision Intelligence",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 15.2 Risk Sentinel",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 19 on-route weather recalculation",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 22 required development standards",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 23 acceptance criteria",
        ],
        "boundary": _closed_boundary(),
    }


def _load_route_weather_package(
    root: Path,
    project: dict[str, Any],
    *,
    explicit_path: str | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    candidates = _candidate_paths(
        root,
        project,
        explicit_path=explicit_path,
        ref_keys=("route_weather_package_ref", "weather_route_package_ref"),
        fallbacks=(
            "outputs/route_weather_package.json",
            "outputs/weather/route_weather_package.json",
            "route_weather_package.json",
        ),
    )
    return _load_first_json_object(candidates, source_kind="route_weather_package")


def _load_weather_daylight_evidence(
    root: Path,
    project: dict[str, Any],
    *,
    explicit_path: str | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    candidates = _candidate_paths(
        root,
        project,
        explicit_path=explicit_path,
        ref_keys=("weather_daylight_evidence_ref",),
        fallbacks=("outputs/weather_daylight_evidence.json",),
    )
    return _load_first_json_object(candidates, source_kind="weather_daylight_evidence")


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
        deduped.append((str(label), path))
    return deduped


def _load_first_json_object(
    candidates: list[tuple[str, Path]],
    *,
    source_kind: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    report: list[dict[str, Any]] = []
    for label, path in candidates:
        if not path.exists():
            report.append(
                {
                    "source_kind": source_kind,
                    "status": "missing",
                    "source_path": label,
                    "loaded_count": 0,
                }
            )
            continue
        payload = _load_json_object(path)
        if not payload:
            report.append(
                {
                    "source_kind": source_kind,
                    "status": "invalid_or_empty",
                    "source_path": label,
                    "loaded_count": 0,
                }
            )
            continue
        report.append(
            {
                "source_kind": source_kind,
                "status": "loaded",
                "source_path": label,
                "loaded_count": 1,
                "artifact_kind": payload.get("artifact_kind"),
                "source_status": payload.get("status"),
            }
        )
        return payload, report
    if not report:
        report.append(
            {
                "source_kind": source_kind,
                "status": "missing",
                "source_path": None,
                "loaded_count": 0,
            }
        )
    return {}, report[:3]


def _route_weather_segments(route_package: dict[str, Any]) -> list[dict[str, Any]]:
    raw_segments = route_package.get("segments")
    if not isinstance(raw_segments, list):
        return []
    segments: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_segments):
        if not isinstance(raw, dict):
            continue
        segment_id = _first_present(
            raw,
            "segment_id",
            "segmentId",
            "id",
            default=f"segment.{index:04d}",
        )
        weather_risk = _float_or_none(
            _first_present(raw, "weather_risk", "weatherRisk")
        )
        terrain_risk = _float_or_none(
            _first_present(raw, "terrain_risk", "terrainRisk", "teii")
        )
        final_risk = _float_or_none(_first_present(raw, "final_risk", "finalRisk"))
        if final_risk is None:
            final_risk = _combine_risk(terrain_risk, weather_risk)
        risk_level = _first_present(raw, "risk_level", "riskLevel")
        if not risk_level and final_risk is not None:
            risk_level = _risk_level(final_risk)
        segment_item = {
            "segment_id": str(segment_id),
            "from_m": _float_or_none(_first_present(raw, "from_m", "fromM")),
            "to_m": _float_or_none(_first_present(raw, "to_m", "toM")),
            "eta_from": _first_present(raw, "eta_from", "etaFrom"),
            "eta_to": _first_present(raw, "eta_to", "etaTo"),
            "township": _first_present(raw, "township", "areaName", "area_name"),
            "temperature_c": _float_or_none(
                _first_present(
                    raw,
                    "temperature_c",
                    "temperatureC",
                    "max_temperature_c",
                    "maxTemperatureC",
                )
            ),
            "heat_index_c": _float_or_none(
                _first_present(raw, "heat_index_c", "heatIndexC", "heatIndex")
            ),
            "shade_status": _first_present(raw, "shade_status", "shadeStatus", "shade"),
            "water_margin_liters": _float_or_none(
                _first_present(
                    raw,
                    "water_margin_liters",
                    "waterMarginLiters",
                    "water_margin_l",
                    "waterMarginL",
                )
            ),
            "terrain_risk": terrain_risk,
            "weather_risk": weather_risk,
            "final_risk": final_risk,
            "risk_level": str(risk_level or "UNKNOWN").upper(),
            "factors": _string_list(_first_present(raw, "factors", "risk_factors", "codes")),
            "message": _first_present(raw, "message", "explanation", default=""),
            "source": raw.get("source") if isinstance(raw.get("source"), dict) else {},
        }
        segments.append(segment_item)
    return segments


def _filter_segments(
    segments: list[dict[str, Any]],
    *,
    valid_from: str | None,
    valid_to: str | None,
    segment: str | None,
) -> list[dict[str, Any]]:
    segment_filter = str(segment).strip().lower() if segment else ""
    from_filter = _parse_datetime(valid_from)
    to_filter = _parse_datetime(valid_to)
    filtered: list[dict[str, Any]] = []
    for item in segments:
        if segment_filter and segment_filter not in str(item.get("segment_id", "")).lower():
            continue
        eta_from = _parse_datetime(item.get("eta_from"))
        eta_to = _parse_datetime(item.get("eta_to"))
        if from_filter and eta_to and eta_to < from_filter:
            continue
        if to_filter and eta_from and eta_from > to_filter:
            continue
        filtered.append(item)
    return filtered


def _weather_window_summary(
    *,
    route_package: dict[str, Any],
    weather_evidence: dict[str, Any],
) -> dict[str, Any]:
    route_window = route_package.get("weather_window")
    evidence_window = weather_evidence.get("weather_window")
    if isinstance(route_window, dict):
        return _compact_weather_window(route_window)
    if isinstance(evidence_window, dict):
        return _compact_weather_window(evidence_window)
    return {}


def _compact_weather_window(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value.get(key)
        for key in (
            "window_start",
            "window_end",
            "valid_from",
            "valid_to",
            "summary",
            "precipitation_label",
            "temperature_range_c",
            "wind_summary",
            "thunderstorm_risk",
            "source_status",
            "source_consistency",
            "confidence",
            "forecast_sources",
            "notes",
            "hazard_notes",
        )
        if value.get(key) is not None
    }


def _threshold_policy(weather_evidence: dict[str, Any]) -> dict[str, Any]:
    policy = weather_evidence.get("threshold_policy")
    if not isinstance(policy, dict):
        return {}
    return {
        "policy_id": policy.get("policy_id"),
        "policy_status": policy.get("policy_status"),
        "configurable": policy.get("configurable"),
        "rainfall": policy.get("rainfall"),
        "dense_fog": policy.get("dense_fog"),
        "strong_wind": policy.get("strong_wind"),
        "daylight": policy.get("daylight"),
    }


def _risk_summary(segments: list[dict[str, Any]]) -> dict[str, Any]:
    weather_values = [
        value
        for value in (_float_or_none(item.get("weather_risk")) for item in segments)
        if value is not None
    ]
    final_values = [
        value
        for value in (_float_or_none(item.get("final_risk")) for item in segments)
        if value is not None
    ]
    levels: dict[str, int] = {}
    hazards: dict[str, int] = {}
    for item in segments:
        level = str(item.get("risk_level") or "UNKNOWN").upper()
        levels[level] = levels.get(level, 0) + 1
        for factor in _string_list(item.get("factors")):
            hazards[factor] = hazards.get(factor, 0) + 1
    return {
        "segment_count": len(segments),
        "max_weather_risk": max(weather_values) if weather_values else None,
        "mean_weather_risk": round(mean(weather_values), 4) if weather_values else None,
        "max_final_risk": max(final_values) if final_values else None,
        "mean_final_risk": round(mean(final_values), 4) if final_values else None,
        "risk_level_counts": dict(sorted(levels.items())),
        "top_hazards": [
            {"code": key, "count": count}
            for key, count in sorted(hazards.items(), key=lambda item: (-item[1], item[0]))[:6]
        ],
    }


def _wx_alerts(segments: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    for item in segments:
        weather_risk = _float_or_none(item.get("weather_risk")) or 0.0
        final_risk = _float_or_none(item.get("final_risk")) or 0.0
        level = str(item.get("risk_level") or "").lower()
        if weather_risk < 0.55 and final_risk < 0.7 and level not in _HIGH_RISK_LEVELS:
            continue
        alerts.append(
            {
                "type": "WX_ALERT",
                "seg": item.get("segment_id"),
                "risk": _mesh_risk_level(level=level, final_risk=final_risk),
                "ttlMin": _ttl_minutes(item),
                "code": _alert_codes(item),
            }
        )
    return alerts[: max(0, limit)]


def _weather_to_decision(
    *,
    answerability: str,
    weather_window: dict[str, Any],
    risk_summary: dict[str, Any],
    wx_alerts: list[dict[str, Any]],
    segments: list[dict[str, Any]],
    missing_fields: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    highest = _highest_risk_segment(segments)
    alert_codes = sorted({code for alert in wx_alerts for code in _string_list(alert.get("code"))})
    route_sensitive_delay = _route_sensitive_weather_delay(segments)
    source_disagreement = _route_sensitive_source_disagreement(
        weather_window=weather_window,
        segments=segments,
    )
    heat_change_plan = _route_sensitive_heat_change_plan(segments)
    if source_disagreement and "SOURCE_CONFLICT" not in alert_codes:
        alert_codes.append("SOURCE_CONFLICT")
    if missing_fields:
        decision = "DELAY"
        main_reasons = [
            "fresh weather / route-specific weather evidence is incomplete",
            "missing_fields=" + ",".join(missing_fields),
        ]
        action_limit = "Do not authorize departure, camping, summit, exposed ridge, or creek decisions from placeholder weather."
        next_action = "補齊 fresh provider、TTL、valid-time 與 route_weather_package；完成前採保守延後。"
        alternatives = ["delay until fresh route weather package is reviewed", "choose lower-exposure fallback route"]
    elif route_sensitive_delay:
        decision = "DELAY"
        crossing_count = route_sensitive_delay["creek_crossing_count"]
        main_reasons = [
            (
                "route contains "
                f"{crossing_count:g} creek-crossing point"
                + ("s" if crossing_count != 1 else "")
                + " after previous-24h rainfall"
            ),
            "team has no creek-crossing experience",
            "rainfall can raise creek, wet-terrain, rockfall, collapse, and loose-soil risk",
        ]
        action_limit = (
            "Do not depart on the original creek-crossing plan until water level, "
            "recent route reports, and team crossing capability are reviewed."
        )
        next_action = "建議延期 48 小時或改走低風險替代路線，並重新確認溪流水位與近期路況。"
        alternatives = [
            "delay 48 hours",
            "choose a lower-risk route without creek crossings",
            "use a guided-only creek-crossing plan after route review",
        ]
    elif source_disagreement:
        decision = "DELAY"
        main_reasons = [
            "forecast sources disagree enough to reduce weather confidence",
            "route-sensitive weather decision needs source reconciliation",
            "do not treat the favorable forecast as authoritative",
        ]
        action_limit = (
            "Do not authorize departure, summit, exposed ridge, creek, or camp "
            "decisions from a favorable forecast until sources are reconciled."
        )
        next_action = (
            "先比對官方預報、路線天氣包與人工審核；若來源仍不一致，延後或改低曝露替代路線。"
        )
        alternatives = [
            "delay until forecast sources converge",
            "choose a conservative lower-exposure route",
            "run human weather review before route-sensitive decisions",
        ]
    elif heat_change_plan:
        decision = "CHANGE_PLAN"
        main_reasons = [
            "route contains high heat / exposure with hydration or shade constraints",
            "heat exposure raises heat-illness, water, shade, and timing risk",
            "original exposed timing should be moved or shortened",
        ]
        action_limit = (
            "Do not follow the original high-heat exposed timing until water "
            "margin, shade/rest points, and a cooler travel window are reviewed."
        )
        next_action = (
            "改到清晨或較涼時段、補足水量並指定遮蔽休息點；若無法滿足就改短低曝曬路線。"
        )
        alternatives = [
            "move exposed travel to a cooler window",
            "increase water margin and reviewed shade/rest points",
            "choose a shorter or lower-exposure route",
        ]
    else:
        decision = _weather_decision_from_risk(highest=highest, risk_summary=risk_summary)
        main_reasons = _weather_decision_reasons(
            weather_window=weather_window,
            highest=highest,
            alert_codes=alert_codes,
        )
        action_limit = _weather_action_limit(decision, alert_codes=alert_codes, highest=highest)
        next_action = _weather_next_action(decision, alert_codes=alert_codes, highest=highest)
        alternatives = _weather_alternatives(decision, alert_codes=alert_codes)

    if not main_reasons:
        main_reasons = ["route weather package is present and no elevated route-weather segment was selected"]
    return {
        "role": "Risk Sentinel / Weather-to-Decision",
        "decision": decision,
        "answerability": answerability,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "main_reasons": main_reasons[:3],
        "action_limit": action_limit,
        "next_action": next_action,
        "alternatives": alternatives,
        "route_specific_conditions": _route_specific_conditions(alert_codes, highest=highest),
        "route_sensitive_weather_rule": (
            route_sensitive_delay or source_disagreement or heat_change_plan
        ),
        "highest_risk_segment": _compact_segment(highest) if highest else None,
        "wx_alert_count": len(wx_alerts),
        "warnings": warnings[:3],
        "weather_buffer_impact": _weather_buffer_impact(
            decision,
            missing_fields=bool(missing_fields),
        ),
    }


def _field_answer(
    *,
    decision: dict[str, Any],
    answerability: str,
    missing_fields: list[str],
) -> str:
    decision_label = str(decision.get("decision") or "DELAY")
    reasons = decision.get("main_reasons")
    reason_text = "；".join(str(reason) for reason in reasons[:2]) if isinstance(reasons, list) else ""
    if missing_fields:
        reason_text = f"缺少 {', '.join(missing_fields)}，不能只看降雨機率或 placeholder。"
    if not reason_text:
        reason_text = f"answerability={answerability}"
    next_action = str(decision.get("next_action") or "補齊天氣與路線交互證據後再判斷。")
    return (
        f"天氣決策：建議 {decision_label}。{reason_text} 下一步：{next_action} "
        "此為 Weather-to-Decision 候選判斷，不是 runtime safety truth；不得觸發 /safety、SOS、outbound send 或硬體控制。"
    )


def _decision_output(
    *,
    decision: dict[str, Any],
    missing_fields: list[str],
    field_answer: str,
) -> dict[str, Any]:
    decision_label = str(decision.get("decision") or "DELAY")
    allowed = decision_label in {"GO", "CONDITIONAL_GO"}
    reasons = _string_list(decision.get("main_reasons"))
    if not reasons and missing_fields:
        reasons = ["缺少 " + "、".join(missing_fields[:5])]
    if not reasons:
        reasons = ["Route weather package did not expose elevated weather risk."]
    uncertainty_notes = [f"Missing field: {field}" for field in missing_fields]
    required_conditions = _weather_required_conditions(
        decision=decision,
        missing_fields=missing_fields,
    )
    alternatives = _string_list(decision.get("alternatives"))
    first_layer = {
        "decision": _decision_phrase(decision_label, allowed=allowed),
        "limit": str(
            decision.get("action_limit")
            or "不得把 weather placeholder 當成現場授權。"
        ),
        "reason": " / ".join(reasons[:2]),
        "nextStep": str(decision.get("next_action") or "補齊天氣與路線交互證據。"),
    }
    second_layer = {
        "details": _decision_details(decision=decision, field_answer=field_answer),
        "uncertaintyNotes": uncertainty_notes,
        "residualRisk": [
            "Route weather evidence is candidate-only.",
            "Weather-to-decision output does not call /safety, SOS, outbound send, or hardware control.",
            "Runtime admission remains separate from this advisory evidence.",
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
        "action": "weather_route_decision",
        "decision": decision_label,
        "allowed": allowed,
        "locationConstraint": first_layer["limit"],
        "mainReasons": reasons[:3],
        "cost": {
            "weatherBufferImpact": decision.get("weather_buffer_impact"),
            "routeSpecificConditions": decision.get("route_specific_conditions") or [],
            "wxAlertCount": decision.get("wx_alert_count"),
        },
        "nextAction": first_layer["nextStep"],
        "confidence": "low" if uncertainty_notes else "medium",
        "uncertaintyNotes": uncertainty_notes,
        "residualRisk": second_layer["residualRisk"],
        "requiredConditions": required_conditions,
        "alternativeActions": alternatives,
        "standardAlignment": [
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 10 Weather-to-Decision Intelligence",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 15.2 Risk Sentinel",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 16 required decision output format",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 17 ContextualPermission schema",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 23 acceptance criteria",
        ],
        "runtimeSafetyTruth": False,
    }


def _weather_required_conditions(
    *,
    decision: dict[str, Any],
    missing_fields: list[str],
) -> list[str]:
    required = [f"Provide {field}." for field in missing_fields]
    decision_label = str(decision.get("decision") or "")
    if decision_label in {"NO_GO", "CHANGE_PLAN"}:
        required.append("Choose a lower-risk weather window or route alternative.")
    if decision_label == "CONDITIONAL_GO":
        required.append("Re-check weather and route risk at the next CP.")
    if not required:
        required.append("Keep route weather package fresh and reviewed.")
    return _dedupe(required)


def _decision_details(*, decision: dict[str, Any], field_answer: str) -> list[str]:
    details = [field_answer]
    conditions = _string_list(decision.get("route_specific_conditions"))
    if conditions:
        details.append("route_specific_conditions=" + ", ".join(conditions[:6]))
    highest = decision.get("highest_risk_segment")
    if isinstance(highest, dict):
        details.append(
            "highest_risk_segment="
            + str(highest.get("segment_id"))
            + f", risk_level={highest.get('risk_level')}"
            + f", final_risk={highest.get('final_risk')}"
        )
    if decision.get("weather_buffer_impact"):
        details.append("weather_buffer_impact=" + str(decision["weather_buffer_impact"]))
    return details


def _decision_phrase(decision: str, *, allowed: bool) -> str:
    if decision == "NO_GO":
        return "不建議進入受天氣影響路段。"
    if decision == "CHANGE_PLAN":
        return "不建議照原計畫通過。"
    if decision == "DELAY":
        return "建議延後天氣判斷。"
    if decision == "CONDITIONAL_GO":
        return "可有條件通過，但必須保留天氣重新檢查。"
    if decision == "GO" and allowed:
        return "可依目前天氣窗繼續。"
    return "暫緩判斷。"


def _weather_decision_from_risk(
    *,
    highest: dict[str, Any] | None,
    risk_summary: dict[str, Any],
) -> str:
    if not highest:
        return "GO"
    final_risk = _float_or_none(highest.get("final_risk")) or 0.0
    weather_risk = _float_or_none(highest.get("weather_risk")) or 0.0
    level = str(highest.get("risk_level") or "").lower()
    if level in {"critical", "severe", "extreme"} or final_risk >= 0.85:
        return "NO_GO"
    if level in {"high", "very_high"} or final_risk >= 0.7 or weather_risk >= 0.65:
        return "CHANGE_PLAN"
    if final_risk >= 0.5 or weather_risk >= 0.35:
        return "CONDITIONAL_GO"
    counts = risk_summary.get("risk_level_counts")
    if isinstance(counts, dict) and any(str(key).upper() in {"HIGH", "VERY_HIGH"} for key in counts):
        return "CHANGE_PLAN"
    return "GO"


def _weather_decision_reasons(
    *,
    weather_window: dict[str, Any],
    highest: dict[str, Any] | None,
    alert_codes: list[str],
) -> list[str]:
    reasons = []
    summary = weather_window.get("summary")
    if summary:
        reasons.append(str(summary))
    if highest:
        segment_id = highest.get("segment_id")
        level = highest.get("risk_level")
        final_risk = _float_or_none(highest.get("final_risk"))
        weather_risk = _float_or_none(highest.get("weather_risk"))
        values = []
        if final_risk is not None:
            values.append(f"final_risk={final_risk:.2f}")
        if weather_risk is not None:
            values.append(f"weather_risk={weather_risk:.2f}")
        reasons.append(
            f"route segment {segment_id} is {level}"
            + (f" ({', '.join(values)})" if values else "")
        )
        factors = _string_list(highest.get("factors"))
        if factors:
            reasons.append("route-specific factors: " + ", ".join(factors[:3]))
    if alert_codes:
        reasons.append("WX alert codes: " + ", ".join(alert_codes))
    return reasons


def _weather_action_limit(
    decision: str,
    *,
    alert_codes: list[str],
    highest: dict[str, Any] | None,
) -> str:
    if decision == "NO_GO":
        return "Do not enter the flagged segment under this weather window."
    if decision == "CHANGE_PLAN":
        if {"THUNDER", "WIND"} & set(alert_codes):
            return "Avoid exposed ridge, summit, and open terrain during the flagged window."
        if "HEAT" in alert_codes:
            return (
                "Avoid high-heat exposed timing until water margin, "
                "shade/rest points, and cooler travel window are reviewed."
            )
        if "RAIN" in alert_codes:
            return "Avoid creek crossings, landslide-prone cuts, and slippery exposed terrain during the flagged window."
        return "Do not follow the original timing through the highest-risk segment."
    if decision == "CONDITIONAL_GO":
        segment = highest.get("segment_id") if highest else "flagged segment"
        return f"Proceed only if the team can pass {segment} before conditions worsen and reassess at the next CP."
    return "Normal plan can proceed only while fresh route weather package remains valid."


def _weather_next_action(
    decision: str,
    *,
    alert_codes: list[str],
    highest: dict[str, Any] | None,
) -> str:
    if decision == "NO_GO":
        return "延期或改低暴露替代路線，並重新產生 route weather package。"
    if decision == "CHANGE_PLAN":
        if "THUNDER" in alert_codes:
            return "調整時程避開午後雷雨，優先移出稜線、山頂、裸露地與溪谷活動。"
        if "LOW_VIS" in alert_codes:
            return "改為更保守導航節奏，增加 CP 檢查，必要時延後或改短版。"
        if "HEAT" in alert_codes:
            return "改到較涼時段、補足水量、指定遮蔽休息點，或改短低曝曬路線。"
        return "改短版、提前撤退窗口，或延後到下一個較低風險天氣窗。"
    if decision == "CONDITIONAL_GO":
        return "設定下一個 CP 重新檢查點，若 weather risk 升高立即改線或撤退。"
    return "維持計畫並保留天氣重新檢查；不要把此候選判斷升級成安全保證。"


def _weather_alternatives(decision: str, *, alert_codes: list[str]) -> list[str]:
    if decision in {"NO_GO", "CHANGE_PLAN"}:
        alternatives = ["delay 24-48 hours", "choose lower-exposure fallback route"]
        if "THUNDER" in alert_codes:
            alternatives.append("move ridge/summit exposure outside thunderstorm window")
        if "RAIN" in alert_codes:
            alternatives.append("avoid creek and landslide-prone segments")
        if "HEAT" in alert_codes:
            alternatives.append("move exposed hiking to cooler hours and confirm water margin")
        return alternatives
    if decision == "CONDITIONAL_GO":
        return ["shorten route", "set earlier turn-back checkpoint", "increase CP weather checks"]
    return ["continue with scheduled CP weather re-checks"]


def _route_specific_conditions(
    alert_codes: list[str],
    *,
    highest: dict[str, Any] | None,
) -> list[str]:
    conditions = []
    for code, label in {
        "RAIN": "rain / wet terrain",
        "THUNDER": "thunderstorm exposure",
        "LOW_VIS": "low visibility / navigation demand",
        "WIND": "strong wind exposure",
        "COLD": "cold stress / hypothermia context",
        "HEAT": "heat exposure / hydration demand",
        "SOURCE_CONFLICT": "forecast source disagreement / uncertainty",
        "TERRAIN": "terrain interaction",
    }.items():
        if code in alert_codes:
            conditions.append(label)
    if highest:
        for factor in _string_list(highest.get("factors")):
            if factor not in conditions:
                conditions.append(factor)
    return conditions[:6]


def _route_sensitive_weather_delay(
    segments: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not segments:
        return None
    text = " ".join(_segment_weather_text(item) for item in segments).lower()
    if not _mentions_previous_24h_rain(text):
        return None
    if not _mentions_no_creek_crossing_experience(text):
        return None
    crossing_segments = [
        item for item in segments if _mentions_creek_crossing(_segment_weather_text(item))
    ]
    crossing_count = max(
        len(crossing_segments),
        _explicit_creek_crossing_count(text),
    )
    if crossing_count <= 0:
        return None
    return {
        "rule": "previous_24h_rain_creek_crossing_no_experience",
        "creek_crossing_count": crossing_count,
        "segment_ids": [
            str(item.get("segment_id"))
            for item in crossing_segments[:6]
            if item.get("segment_id") is not None
        ],
    }


def _route_sensitive_source_disagreement(
    *,
    weather_window: dict[str, Any],
    segments: list[dict[str, Any]],
) -> dict[str, Any] | None:
    texts = [
        str(weather_window.get("summary") or ""),
        str(weather_window.get("source_status") or ""),
        str(weather_window.get("source_consistency") or ""),
        str(weather_window.get("confidence") or ""),
        *_string_list(weather_window.get("notes")),
        *_string_list(weather_window.get("hazard_notes")),
        *(_segment_weather_text(item) for item in segments),
    ]
    joined = " ".join(text for text in texts if text)
    if not _mentions_source_disagreement(joined):
        return None
    segment_ids = [
        str(item.get("segment_id"))
        for item in segments
        if item.get("segment_id") is not None
        and _mentions_source_disagreement(_segment_weather_text(item))
    ]
    providers = _forecast_provider_names(weather_window=weather_window, segments=segments)
    return {
        "rule": "forecast_source_disagreement_conservative_review",
        "segment_ids": segment_ids[:6],
        "conflicting_sources": providers[:6],
        "source_count": len(providers) if providers else None,
        "required_reviews": [
            "compare official forecast sources",
            "apply conservative weather window",
            "human review before route-sensitive decision",
        ],
    }


def _route_sensitive_heat_change_plan(
    segments: list[dict[str, Any]],
) -> dict[str, Any] | None:
    heat_segments = []
    for item in segments:
        text = _segment_weather_text(item)
        temperature_c = _float_or_none(item.get("temperature_c"))
        heat_index_c = _float_or_none(item.get("heat_index_c"))
        water_margin = _float_or_none(item.get("water_margin_liters"))
        if not _has_heat_signal(
            text,
            temperature_c=temperature_c,
            heat_index_c=heat_index_c,
        ):
            continue
        if not (
            _mentions_heat_exposure(text, item.get("shade_status"))
            or _mentions_limited_water(text, water_margin=water_margin)
            or _mentions_hot_timing(text)
        ):
            continue
        heat_segments.append(item)
    if not heat_segments:
        return None
    temperatures = [
        value
        for item in heat_segments
        for value in (
            _float_or_none(item.get("temperature_c")),
            _float_or_none(item.get("heat_index_c")),
        )
        if value is not None
    ]
    water_margins = [
        value
        for item in heat_segments
        if (value := _float_or_none(item.get("water_margin_liters"))) is not None
    ]
    return {
        "rule": "high_heat_exposure_water_timing_review",
        "segment_ids": [
            str(item.get("segment_id"))
            for item in heat_segments[:6]
            if item.get("segment_id") is not None
        ],
        "max_temperature_or_heat_index_c": max(temperatures) if temperatures else None,
        "min_water_margin_liters": min(water_margins) if water_margins else None,
        "required_reviews": [
            "water_margin",
            "shade_or_rest_points",
            "cooler_travel_window",
        ],
    }


def _segment_weather_text(item: dict[str, Any]) -> str:
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    parts = [
        str(item.get("segment_id") or ""),
        str(item.get("message") or ""),
        str(item.get("shade_status") or ""),
        str(source.get("provider") or ""),
        str(source.get("source_status") or ""),
        str(source.get("source_consistency") or ""),
        *_string_list(item.get("factors")),
    ]
    return " ".join(part for part in parts if part)


def _mentions_source_disagreement(text: str) -> bool:
    normalized = text.replace(" ", "").lower()
    return any(
        needle in normalized
        for needle in (
            "預報來源不一致",
            "預報不一致",
            "來源不一致",
            "來源衝突",
            "預報衝突",
            "sourceconflict",
            "sourcedisagreement",
            "forecastconflict",
            "forecastdisagreement",
            "forecastmismatch",
            "providerconflict",
            "providerdisagreement",
            "inconsistentforecast",
            "conflictingforecast",
        )
    )


def _forecast_provider_names(
    *,
    weather_window: dict[str, Any],
    segments: list[dict[str, Any]],
) -> list[str]:
    providers: list[str] = []

    def add(value: Any) -> None:
        text = str(value or "").strip()
        if text and text not in providers:
            providers.append(text)

    raw_sources = weather_window.get("forecast_sources")
    if isinstance(raw_sources, list):
        for item in raw_sources:
            if isinstance(item, dict):
                add(item.get("provider") or item.get("source_id") or item.get("name"))
            else:
                add(item)
    for item in segments:
        source = item.get("source") if isinstance(item.get("source"), dict) else {}
        add(source.get("provider") or source.get("source_id") or source.get("name"))
    return providers


def _has_heat_signal(
    text: str,
    *,
    temperature_c: float | None,
    heat_index_c: float | None,
) -> bool:
    normalized = text.replace(" ", "").lower()
    if temperature_c is not None and temperature_c >= 30:
        return True
    if heat_index_c is not None and heat_index_c >= 32:
        return True
    return any(
        needle in normalized
        for needle in (
            "高溫",
            "炎熱",
            "酷熱",
            "中暑",
            "熱傷害",
            "heatexposure",
            "heatindex",
            "hightemperature",
            "hotweather",
        )
    )


def _mentions_heat_exposure(text: str, shade_status: Any) -> bool:
    normalized = text.replace(" ", "").lower()
    shade = str(shade_status or "").strip().lower().replace(" ", "")
    return shade in {"none", "limited", "unshaded", "無遮蔽", "少遮蔽"} or any(
        needle in normalized
        for needle in (
            "曝曬",
            "日曬",
            "無遮蔽",
            "少遮蔽",
            "裸露",
            "稜線",
            "exposed",
            "unshaded",
            "limitedshade",
            "opensun",
        )
    )


def _mentions_limited_water(text: str, *, water_margin: float | None) -> bool:
    normalized = text.replace(" ", "").lower()
    if water_margin is not None and water_margin < 0.75:
        return True
    return any(
        needle in normalized
        for needle in (
            "水量不足",
            "水量偏低",
            "補水",
            "缺水",
            "低水量",
            "watermarginlow",
            "lowwater",
            "hydration",
        )
    )


def _mentions_hot_timing(text: str) -> bool:
    normalized = text.replace(" ", "").lower()
    return any(
        needle in normalized
        for needle in (
            "午後",
            "正午",
            "中午",
            "炎熱時段",
            "midday",
            "noon",
            "afternoonheat",
            "hotwindow",
        )
    )


def _mentions_previous_24h_rain(text: str) -> bool:
    normalized = text.replace(" ", "")
    return any(
        needle in normalized
        for needle in (
            "前24小時",
            "過去24小時",
            "previous24h",
            "previous24hours",
            "last24h",
            "last24hours",
            "24hrain",
            "24hourrain",
        )
    ) and any(
        needle in normalized
        for needle in ("雨", "降雨", "rain", "precip")
    )


def _mentions_no_creek_crossing_experience(text: str) -> bool:
    normalized = text.replace(" ", "")
    return any(
        needle in normalized
        for needle in (
            "沒有渡溪經驗",
            "無渡溪經驗",
            "無過溪經驗",
            "沒有過溪經驗",
            "隊伍沒有渡溪經驗",
            "隊伍無渡溪經驗",
            "nocreekcrossingexperience",
            "nostreamcrossingexperience",
            "inexperiencedcreekcrossing",
            "inexperiencedstreamcrossing",
        )
    )


def _mentions_creek_crossing(text: str) -> bool:
    normalized = text.replace(" ", "")
    return any(
        needle in normalized
        for needle in (
            "渡溪",
            "過溪",
            "溪水",
            "溪谷",
            "creekcrossing",
            "streamcrossing",
            "rivercrossing",
        )
    )


def _explicit_creek_crossing_count(text: str) -> int:
    normalized = text.replace(" ", "")
    match = re.search(r"(\d+)處(?:渡溪|過溪|溪流)", normalized)
    if match:
        return int(match.group(1))
    for label, count in (("兩處", 2), ("二處", 2), ("三處", 3), ("四處", 4)):
        if label + "渡溪" in normalized or label + "過溪" in normalized:
            return count
    return 0


def _weather_buffer_impact(
    decision: str,
    *,
    missing_fields: bool,
) -> str:
    if decision in {"NO_GO", "CHANGE_PLAN"}:
        return "weather buffer is not available for discretionary delay or exposure"
    if decision == "CONDITIONAL_GO":
        return "weather buffer must be reserved for CP re-check and retreat option"
    if decision == "DELAY":
        if missing_fields:
            return "weather buffer cannot be computed from incomplete evidence"
        return "weather buffer must be preserved until route-specific weather risk is re-reviewed"
    return "weather buffer currently not consumed by a decision restriction"


def _highest_risk_segment(segments: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not segments:
        return None
    return max(
        segments,
        key=lambda item: (
            _float_or_none(item.get("final_risk")) or -1.0,
            _float_or_none(item.get("weather_risk")) or -1.0,
            str(item.get("segment_id") or ""),
        ),
    )


def _missing_weather_fields(
    *,
    route_package: dict[str, Any],
    weather_evidence: dict[str, Any],
) -> list[str]:
    source = route_package or weather_evidence
    missing = []
    for field in FRESH_WEATHER_FIELDS:
        if _first_present(source, field, _camel(field)) in (None, ""):
            missing.append(field)
    if not route_package:
        missing.append("route_weather_package")
    if route_package and not _route_weather_segments(route_package):
        missing.append("route_weather_segments")
    return _dedupe(missing)


def _warnings(
    *,
    route_package: dict[str, Any],
    weather_evidence: dict[str, Any],
    missing_fields: list[str],
    stale_after_hours: float,
) -> list[str]:
    warnings: list[str] = []
    if missing_fields:
        warnings.append(
            "Fresh provider/valid-time/TTL evidence is incomplete; do not infer a field weather conclusion."
        )
    if weather_evidence and not route_package:
        warnings.append(
            "Only weather_daylight_evidence was found; no route_weather_package segment risk layer is available."
        )
    if _is_placeholder(weather_evidence):
        warnings.append(
            "Weather evidence is a manual placeholder and requires human review before departure-gate use."
        )
    stale_warning = _stale_warning(route_package or weather_evidence, stale_after_hours)
    if stale_warning:
        warnings.append(stale_warning)
    return _dedupe(warnings)


def _source_status(
    route_package: dict[str, Any],
    weather_evidence: dict[str, Any],
) -> str:
    if route_package:
        return str(route_package.get("status") or "route_weather_package")
    if weather_evidence:
        return str(weather_evidence.get("status") or "weather_daylight_evidence")
    return "missing"


def _bool_from_sources(
    key: str,
    route_package: dict[str, Any],
    weather_evidence: dict[str, Any],
) -> bool:
    for source in (route_package, weather_evidence):
        if isinstance(source.get(key), bool):
            return bool(source[key])
    return False


def _human_review_required(
    route_package: dict[str, Any],
    weather_evidence: dict[str, Any],
    missing_fields: list[str],
) -> bool:
    for source in (route_package, weather_evidence):
        if isinstance(source.get("human_review_required"), bool):
            return bool(source["human_review_required"]) or bool(missing_fields)
    return bool(missing_fields)


def _stale_warning(source: dict[str, Any], stale_after_hours: float) -> str | None:
    if not source:
        return None
    valid_until = _first_present(source, "valid_until", "validUntil", "valid_to", "validTo")
    if valid_until:
        parsed = _parse_datetime(valid_until)
        if parsed and parsed < datetime.now(timezone.utc):
            return f"Weather source is past valid_until={valid_until}."
    generated_at = _first_present(source, "generated_at", "generatedAt", "issued_at", "issuedAt")
    parsed_generated_at = _parse_datetime(generated_at)
    if parsed_generated_at is None:
        return None
    age_hours = (
        datetime.now(timezone.utc) - parsed_generated_at.astimezone(timezone.utc)
    ).total_seconds() / 3600.0
    if age_hours > stale_after_hours:
        return f"Weather source age {age_hours:.1f}h exceeds stale_after_hours={stale_after_hours:g}."
    return None


def _is_placeholder(weather_evidence: dict[str, Any]) -> bool:
    if not weather_evidence:
        return False
    validation = weather_evidence.get("validation")
    weather_window = weather_evidence.get("weather_window")
    return (
        weather_evidence.get("status") == "candidate_only"
        and (
            (isinstance(validation, dict) and validation.get("staleness") == "placeholder")
            or (
                isinstance(weather_window, dict)
                and weather_window.get("source_status") == "manual_placeholder"
            )
        )
    )


def _compact_segment(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item.get(key)
        for key in (
            "segment_id",
            "from_m",
            "to_m",
            "eta_from",
            "eta_to",
            "township",
            "temperature_c",
            "heat_index_c",
            "shade_status",
            "water_margin_liters",
            "terrain_risk",
            "weather_risk",
            "final_risk",
            "risk_level",
            "factors",
            "message",
        )
        if item.get(key) is not None
    }


def _route_weather_package_schema() -> dict[str, Any]:
    return {
        "artifact_kind": "route_weather_package",
        "required_top_level": [
            "routeId or route_id",
            "generatedAt/generated_at",
            "validUntil/valid_until",
            "segments",
        ],
        "segment_fields": [
            "segmentId/segment_id",
            "fromM/from_m",
            "toM/to_m",
            "etaFrom/eta_from",
            "etaTo/eta_to",
            "terrainRisk/terrain_risk",
            "weatherRisk/weather_risk",
            "finalRisk/final_risk",
            "riskLevel/risk_level",
            "temperatureC/temperature_c",
            "heatIndexC/heat_index_c",
            "shadeStatus/shade_status",
            "waterMarginLiters/water_margin_liters",
            "factors",
            "message",
        ],
        "device_payload": "compact WX_ALERT objects only; raw CWA payloads stay server-side",
    }


def _combine_risk(
    terrain_risk: float | None,
    weather_risk: float | None,
) -> float | None:
    if terrain_risk is None and weather_risk is None:
        return None
    terrain = terrain_risk if terrain_risk is not None else 0.0
    weather = weather_risk if weather_risk is not None else 0.0
    interaction = terrain * weather
    return round(terrain * 0.55 + weather * 0.30 + interaction * 0.15, 4)


def _risk_level(score: float) -> str:
    if score >= 0.8:
        return "HIGH"
    if score >= 0.6:
        return "ELEVATED"
    if score >= 0.35:
        return "MODERATE"
    return "LOW"


def _mesh_risk_level(*, level: str, final_risk: float) -> int:
    if level in {"critical", "severe", "extreme"} or final_risk >= 0.85:
        return 4
    if level in {"high", "very_high"} or final_risk >= 0.7:
        return 3
    if final_risk >= 0.5:
        return 2
    return 1


def _ttl_minutes(item: dict[str, Any]) -> int | None:
    eta_to = _parse_datetime(item.get("eta_to"))
    if eta_to is None:
        return None
    delta_min = int((eta_to - datetime.now(timezone.utc)).total_seconds() // 60)
    if delta_min <= 0:
        return 0
    return min(delta_min, 24 * 60)


def _alert_codes(item: dict[str, Any]) -> list[str]:
    codes = []
    factor_text = " ".join(_string_list(item.get("factors"))).lower()
    message_text = str(item.get("message") or "").lower()
    text = f"{factor_text} {message_text}"
    for code, needles in {
        "RAIN": ("rain", "雨", "降雨", "豪雨", "大雨"),
        "THUNDER": ("thunder", "雷"),
        "LOW_VIS": ("fog", "霧", "白牆", "visibility", "能見度"),
        "WIND": ("wind", "風"),
        "COLD": ("cold", "low temperature", "低溫", "失溫"),
        "HEAT": (
            "heat",
            "hot",
            "high temperature",
            "heat index",
            "高溫",
            "炎熱",
            "酷熱",
            "中暑",
            "曝曬",
        ),
        "SOURCE_CONFLICT": (
            "source conflict",
            "source disagreement",
            "forecast conflict",
            "forecast disagreement",
            "預報來源不一致",
            "來源不一致",
            "預報衝突",
        ),
        "TERRAIN": ("cliff", "slope", "terrain", "稜線", "崩", "溪", "坡"),
    }.items():
        if any(needle in text for needle in needles):
            codes.append(code)
    return codes or ["WX"]


def _segment_sort_key(item: dict[str, Any]) -> tuple[float, float, str]:
    final_risk = _float_or_none(item.get("final_risk"))
    weather_risk = _float_or_none(item.get("weather_risk"))
    return (
        -(final_risk if final_risk is not None else -1.0),
        -(weather_risk if weather_risk is not None else -1.0),
        str(item.get("segment_id") or ""),
    )


def _bounded_limit(limit: int) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = DEFAULT_RESULT_LIMIT
    return max(1, min(value, MAX_RESULT_LIMIT))


def _first_present(
    mapping: dict[str, Any],
    *keys: str,
    default: Any = None,
) -> Any:
    for key in keys:
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    return default


def _camel(value: str) -> str:
    parts = value.split("_")
    return parts[0] + "".join(part[:1].upper() + part[1:] for part in parts[1:])


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _float_or_default(value: Any, *, default: float) -> float:
    parsed = _float_or_none(value)
    return default if parsed is None else parsed


def _bool_value(value: Any, *, default: bool) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(value)


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [part.strip() for part in value.split(",") if part.strip()]
    return []


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _project_path(root: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return root / path


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        text = str(value)
        if not text or text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    return deduped


def _closed_boundary() -> dict[str, bool]:
    return {
        "read_only": True,
        "runtime_safety_truth": False,
        "live_safety_api_calls_allowed": False,
        "phase1_l0_l4_state_mutated": False,
        "safety_api_called": False,
        "outbound_send_performed": False,
        "hardware_control_performed": False,
        "workspace_file_write_allowed": False,
        "raw_payloads_embedded": False,
        "server_side_provider_required": True,
        "client_cwa_api_key_allowed": False,
        "live_provider_fetch_performed": False,
    }
