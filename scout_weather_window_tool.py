from __future__ import annotations

import json
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
    if missing_fields:
        decision = "DELAY"
        main_reasons = [
            "fresh weather / route-specific weather evidence is incomplete",
            "missing_fields=" + ",".join(missing_fields),
        ]
        action_limit = "Do not authorize departure, camping, summit, exposed ridge, or creek decisions from placeholder weather."
        next_action = "補齊 fresh provider、TTL、valid-time 與 route_weather_package；完成前採保守延後。"
        alternatives = ["delay until fresh route weather package is reviewed", "choose lower-exposure fallback route"]
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
        "highest_risk_segment": _compact_segment(highest) if highest else None,
        "wx_alert_count": len(wx_alerts),
        "warnings": warnings[:3],
        "weather_buffer_impact": _weather_buffer_impact(decision),
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
        "TERRAIN": "terrain interaction",
    }.items():
        if code in alert_codes:
            conditions.append(label)
    if highest:
        for factor in _string_list(highest.get("factors")):
            if factor not in conditions:
                conditions.append(factor)
    return conditions[:6]


def _weather_buffer_impact(decision: str) -> str:
    if decision in {"NO_GO", "CHANGE_PLAN"}:
        return "weather buffer is not available for discretionary delay or exposure"
    if decision == "CONDITIONAL_GO":
        return "weather buffer must be reserved for CP re-check and retreat option"
    if decision == "DELAY":
        return "weather buffer cannot be computed from incomplete evidence"
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
