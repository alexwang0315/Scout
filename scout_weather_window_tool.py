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
    "planned_eta_path",
    "current_time",
    "reference_time",
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
    planned_eta_path: str | None = None,
    current_time: str | None = None,
    reference_time: str | None = None,
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
    planned_eta, planned_eta_report = _load_planned_eta(
        root,
        project,
        explicit_path=planned_eta_path,
    )

    source_report = [*route_report, *weather_report, *planned_eta_report]
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
        query=query,
        route_package=route_package,
        weather_evidence=weather_evidence,
    )
    reference_datetime = _parse_datetime(reference_time) or datetime.now(timezone.utc)
    stale_warnings = _stale_warnings(
        route_package=route_package,
        weather_evidence=weather_evidence,
        stale_after_hours=stale_hours,
        reference_time=reference_datetime,
    )
    if stale_warnings:
        missing_fields = _dedupe([*missing_fields, "fresh_route_weather_evidence"])
    daylight_buffer_status = _daylight_buffer_status(
        query=query,
        current_time=current_time,
        route_package=route_package,
        weather_evidence=weather_evidence,
        planned_eta=planned_eta,
    )
    if daylight_buffer_status:
        missing_fields = _dedupe(
            [
                *missing_fields,
                *_string_list(daylight_buffer_status.get("missing_fields")),
            ]
        )
    warnings = _warnings(
        route_package=route_package,
        weather_evidence=weather_evidence,
        missing_fields=missing_fields,
        stale_after_hours=stale_hours,
        reference_time=reference_datetime,
        stale_warnings=stale_warnings,
    )
    route_scope_available = _route_weather_scope_available(route_package)
    answerability = (
        "route_weather_risk_available"
        if route_scope_available and not missing_fields
        else "route_weather_risk_partial"
        if route_scope_available
        else "weather_placeholder_only"
        if weather_evidence
        else "weather_evidence_missing"
    )
    weather_to_decision = _weather_to_decision(
        query=query,
        answerability=answerability,
        weather_window=weather_window,
        risk_summary=risk_summary,
        wx_alerts=wx_alerts,
        segments=filtered_segments,
        missing_fields=missing_fields,
        warnings=warnings,
        daylight_buffer_status=daylight_buffer_status,
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
    field_answer_source_refs = _loaded_source_refs(source_report)

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
        "field_answer_priority": 90,
        "field_answer_source_ref": (
            field_answer_source_refs[0] if field_answer_source_refs else None
        ),
        "field_answer_source_refs": field_answer_source_refs,
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
        "daylight_buffer_status": daylight_buffer_status,
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
            "outputs/route_weather_package.reviewed.json",
            "outputs/route_weather_package.json",
            "outputs/weather/route_weather_package.json",
            "route_weather_package.json",
        ),
    )
    route_package, legacy_report = _load_first_json_object(
        candidates,
        source_kind="route_weather_package",
    )
    if route_package:
        return route_package, legacy_report
    fresh_package, fresh_report = _load_fresh_prepared_weather_package(root, project)
    if fresh_package:
        return fresh_package, [*fresh_report, *legacy_report[:1]]
    return {}, legacy_report


def _load_fresh_prepared_weather_package(
    root: Path,
    project: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    route_risk, route_risk_report = _load_first_json_object(
        _candidate_paths(
            root,
            project,
            explicit_path=None,
            ref_keys=("route_weather_risk_package_ref",),
            fallbacks=("outputs/route_weather_risk_package.json",),
        ),
        source_kind="route_weather_risk_package",
    )
    cwa_evidence, cwa_report = _load_first_json_object(
        _candidate_paths(
            root,
            project,
            explicit_path=None,
            ref_keys=("cwa_weather_evidence_ref",),
            fallbacks=(
                "outputs/environment/cwa/cwa_weather_evidence.json",
                "outputs/cwa_weather_evidence.json",
            ),
        ),
        source_kind="cwa_weather_evidence",
    )
    qpf_summary, qpf_report = _load_first_json_object(
        _candidate_paths(
            root,
            project,
            explicit_path=None,
            ref_keys=("cwa_qpf_corridor_summary_ref",),
            fallbacks=("outputs/environment/cwa/qpf_corridor_summary.json",),
        ),
        source_kind="cwa_qpf_corridor_summary",
    )
    reports = [*route_risk_report, *cwa_report, *qpf_report]
    if not any((route_risk, cwa_evidence, qpf_summary)):
        return {}, reports
    package = _normalize_fresh_prepared_weather_package(
        project=project,
        route_risk=route_risk,
        cwa_evidence=cwa_evidence,
        qpf_summary=qpf_summary,
    )
    loaded_refs = _loaded_source_refs(reports)
    reports.append(
        {
            "source_kind": "fresh_weather_decision_adapter",
            "status": "loaded",
            "source_path": loaded_refs[0] if loaded_refs else None,
            "source_paths": loaded_refs,
            "loaded_count": 1,
            "artifact_kind": package["artifact_kind"],
            "source_status": package["status"],
        }
    )
    return package, reports


def _normalize_fresh_prepared_weather_package(
    *,
    project: dict[str, Any],
    route_risk: dict[str, Any],
    cwa_evidence: dict[str, Any],
    qpf_summary: dict[str, Any],
) -> dict[str, Any]:
    issued_at = _first_present(
        cwa_evidence,
        "issued_at",
        "api_fetched_at",
        "fetched_at",
        "request_timestamp",
        "generated_at",
        default=_first_present(route_risk, "generatedAt", "generated_at"),
    )
    valid_from = _first_present(
        qpf_summary,
        "forecast_valid_from",
        "valid_from",
        default=_first_present(
            cwa_evidence,
            "forecast_valid_from",
            "valid_from",
        ),
    )
    valid_to = _first_present(
        qpf_summary,
        "forecast_valid_until",
        "valid_until",
        "valid_to",
        default=_first_present(
            cwa_evidence,
            "forecast_valid_until",
            "valid_until",
            "valid_to",
        ),
    )
    external_calls = any(
        source.get("external_api_calls_made") is True
        or source.get("api_request_attempted") is True
        for source in (cwa_evidence, qpf_summary)
    )
    return {
        "artifact_kind": "route_weather_package",
        "adapter_kind": "fresh_prepared_weather_decision_inputs",
        "status": "candidate_only",
        "routeId": str(
            route_risk.get("routeId")
            or project.get("route_id")
            or project.get("project_id")
            or ""
        ),
        "generatedAt": issued_at,
        "issued_at": issued_at,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "validUntil": valid_to,
        "ttl_s": _validity_ttl_seconds(issued_at, valid_to),
        "provider": _first_present(cwa_evidence, "provider"),
        "authoritative_weather_computed": external_calls,
        "external_api_calls_made": external_calls,
        "human_review_required": True,
        "route_corridor_assessed": bool(route_risk or qpf_summary),
        "direct_qpf_available": _direct_qpf_available(qpf_summary),
        "weather_window": _fresh_weather_window(
            route_risk=route_risk,
            cwa_evidence=cwa_evidence,
            qpf_summary=qpf_summary,
            valid_from=valid_from,
            valid_to=valid_to,
        ),
        "segments": _fresh_route_weather_segments(route_risk),
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "human_review_required": True,
            "source_mutation_allowed": False,
        },
    }


def _fresh_weather_window(
    *,
    route_risk: dict[str, Any],
    cwa_evidence: dict[str, Any],
    qpf_summary: dict[str, Any],
    valid_from: Any,
    valid_to: Any,
) -> dict[str, Any]:
    qpf = qpf_summary.get("qpf_corridor_summary")
    qpf = {**qpf_summary, **qpf} if isinstance(qpf, dict) else qpf_summary
    max_mm = _float_or_none(qpf.get("max_mm"))
    mean_mm = _float_or_none(qpf.get("mean_mm"))
    p95_mm = _float_or_none(qpf.get("p95_mm"))
    probability = _float_or_none(qpf.get("max_rain_probability"))
    if probability is None:
        probability = _max_weather_point_rain_probability(cwa_evidence)
    summary_parts: list[str] = []
    if max_mm is not None:
        qpf_values = [f"最大 {max_mm:g} mm"]
        if p95_mm is not None:
            qpf_values.append(f"p95 {p95_mm:g} mm")
        if mean_mm is not None:
            qpf_values.append(f"平均 {mean_mm:g} mm")
        summary_parts.append("路線走廊 QPF：" + "、".join(qpf_values))
    elif probability is not None:
        summary_parts.append(
            "路線走廊尚無 direct QPF 累積雨量；"
            f"預報降雨機率峰值 {probability:g}%"
        )
    else:
        summary_parts.append(
            "fresh CWA preparation 已完成，但沒有路線走廊的累積雨量或降雨機率"
        )
    peak_window = _first_present(qpf, "peak_window")
    if peak_window:
        summary_parts.append(f"高峰時間窗={peak_window}")
    features = route_risk.get("imageryFeatures")
    features = features if isinstance(features, dict) else {}
    if features.get("currentRainOnRoute") is True:
        summary_parts.append("雷達候選證據顯示路線目前有雨")
    elif features.get("rainBandApproaching") is True:
        summary_parts.append("雷達候選證據顯示雨帶接近路線")
    interactions = route_risk.get("weatherTerrainInteractions")
    interaction_rows = (
        [item for item in interactions if isinstance(item, dict)]
        if isinstance(interactions, list)
        else []
    )
    return {
        "valid_from": valid_from,
        "valid_to": valid_to,
        "summary": "; ".join(summary_parts) + ".",
        "precipitation_label": (
            f"QPF 最大 {max_mm:g} mm"
            if max_mm is not None
            else f"降雨機率峰值 {probability:g}%"
            if probability is not None
            else "降水資料不可用"
        ),
        "source_status": "server_side_fresh_preparation",
        "confidence": _float_or_none(features.get("confidence")),
        "forecast_sources": _fresh_dataset_ids(cwa_evidence, qpf),
        "notes": [
            "路線走廊／bbox 證據僅供候選審查，仍需人工確認。",
            "山區 QPF 不能精準預測單一坡面。",
        ],
        "hazard_notes": [
            str(item.get("ruleCode"))
            for item in interaction_rows
            if item.get("ruleCode")
        ][:6],
    }


def _fresh_route_weather_segments(
    route_risk: dict[str, Any],
) -> list[dict[str, Any]]:
    raw_interactions = route_risk.get("weatherTerrainInteractions")
    interactions = raw_interactions if isinstance(raw_interactions, list) else []
    features = route_risk.get("imageryFeatures")
    features = features if isinstance(features, dict) else {}
    feature_risk = max(
        (
            value
            for value in (
                _float_or_none(features.get("confidence")),
                _float_or_none(features.get("convectiveCellScore")),
                _float_or_none(features.get("satelliteConvectiveCloudScore")),
            )
            if value is not None
        ),
        default=0.0,
    )
    segments: list[dict[str, Any]] = []
    for index, raw in enumerate(interactions):
        if not isinstance(raw, dict):
            continue
        rule_code = str(raw.get("ruleCode") or "WEATHER_TERRAIN").strip()
        terrain_risk = _float_or_none(raw.get("teii_20m"))
        if terrain_risk is not None and terrain_risk > 1:
            terrain_risk = terrain_risk / 100.0
        weather_risk = _float_or_none(raw.get("weatherConfidence"))
        if weather_risk is None:
            weather_risk = feature_risk
        final_risk = _combine_risk(terrain_risk, weather_risk)
        source_refs = _string_list(raw.get("terrainSourceRefs"))
        segments.append(
            {
                "segment_id": str(
                    raw.get("segmentId") or f"route.weather.interaction.{index:04d}"
                ),
                "terrain_risk": terrain_risk,
                "weather_risk": weather_risk,
                "final_risk": final_risk,
                "risk_level": _risk_level(final_risk or 0.0),
                "factors": [
                    rule_code,
                    _weather_interaction_label(rule_code),
                ],
                "message": (
                    "Fresh server-side route weather interaction candidate: "
                    f"{rule_code}."
                ),
                "source": {
                    "source_status": "server_side_fresh_preparation",
                    "source_refs": source_refs,
                },
            }
        )
    return segments


def _weather_interaction_label(rule_code: str) -> str:
    return {
        "RAIN_DRY_CREEK": "rain and dry creek terrain interaction",
        "RAIN_SCREE_CLIFF": "rain, scree, and cliff terrain interaction",
        "THUNDER_RIDGE": "thunder ridge terrain interaction",
        "STRONG_ECHO_STEEP_DESCENT": "strong echo and steep descent terrain interaction",
    }.get(rule_code, "weather terrain interaction")


def _fresh_dataset_ids(
    cwa_evidence: dict[str, Any],
    qpf_summary: dict[str, Any],
) -> list[str]:
    datasets: list[str] = []
    for raw in (
        cwa_evidence.get("datasets"),
        qpf_summary.get("datasets"),
        qpf_summary.get("dataset_ids"),
    ):
        if not isinstance(raw, list):
            continue
        for item in raw:
            dataset_id = (
                item.get("dataset_id") or item.get("source_dataset_id")
                if isinstance(item, dict)
                else item
            )
            text = str(dataset_id or "").strip()
            if text:
                datasets.append(text)
    return _dedupe(datasets)


def _max_weather_point_rain_probability(
    cwa_evidence: dict[str, Any],
) -> float | None:
    raw_points = cwa_evidence.get("weather_points")
    points = raw_points if isinstance(raw_points, list) else []
    values = [
        value
        for item in points
        if isinstance(item, dict)
        and (
            value := _float_or_none(
                _first_present(item, "rainProbability", "rain_probability")
            )
        )
        is not None
    ]
    return max(values) if values else None


def _direct_qpf_available(qpf_summary: dict[str, Any]) -> bool:
    qpf = qpf_summary.get("qpf_corridor_summary")
    qpf = {**qpf_summary, **qpf} if isinstance(qpf, dict) else qpf_summary
    if any(
        _float_or_none(qpf.get(key)) is not None
        for key in ("max_mm", "mean_mm", "p95_mm")
    ):
        return True
    return any(
        dataset.startswith("F-C0041-")
        for dataset in _fresh_dataset_ids({}, qpf)
    )


def _validity_ttl_seconds(issued_at: Any, valid_to: Any) -> int | None:
    issued = _parse_datetime(issued_at)
    valid = _parse_datetime(valid_to)
    if issued is None or valid is None or valid <= issued:
        return None
    return max(1, int((valid - issued).total_seconds()))


def _loaded_source_refs(source_report: list[dict[str, Any]]) -> list[str]:
    priority = {
        "cwa_qpf_corridor_summary": 0,
        "cwa_weather_evidence": 1,
        "route_weather_risk_package": 2,
        "route_weather_package": 3,
        "weather_daylight_evidence": 4,
        "planned_eta": 5,
        "fresh_weather_decision_adapter": 6,
    }
    refs: list[tuple[int, str]] = []
    for item in source_report:
        if item.get("status") != "loaded":
            continue
        source_kind = str(item.get("source_kind") or "")
        item_refs = [item.get("source_path")]
        source_paths = item.get("source_paths")
        if isinstance(source_paths, list):
            item_refs.extend(source_paths)
        for ref in item_refs:
            text = str(ref or "").strip()
            path = Path(text)
            if not text or path.is_absolute() or ".." in path.parts:
                continue
            refs.append((priority.get(source_kind, 99), path.as_posix()))
    return _dedupe([ref for _, ref in sorted(refs)])


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


def _load_planned_eta(
    root: Path,
    project: dict[str, Any],
    *,
    explicit_path: str | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    candidates = _candidate_paths(
        root,
        project,
        explicit_path=explicit_path,
        ref_keys=("planned_eta_ref",),
        fallbacks=("outputs/planned_eta.json",),
    )
    return _load_first_json_object(candidates, source_kind="planned_eta")


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


def _daylight_buffer_status(
    *,
    query: str,
    current_time: str | None,
    route_package: dict[str, Any],
    weather_evidence: dict[str, Any],
    planned_eta: dict[str, Any],
) -> dict[str, Any]:
    if not _looks_like_daylight_buffer_question(query):
        return {}
    route_daylight = route_package.get("daylight")
    route_daylight = route_daylight if isinstance(route_daylight, dict) else {}
    evidence_daylight = weather_evidence.get("daylight")
    evidence_daylight = evidence_daylight if isinstance(evidence_daylight, dict) else {}
    daylight = route_daylight or evidence_daylight
    sunset = _first_present(
        daylight,
        "sunset",
        "sunset_at",
        "sunsetAt",
        "civil_twilight_end",
    )
    target_eta = _planned_target_eta(planned_eta)
    daylight_reviewed = _daylight_window_reviewed(
        route_package=route_package,
        weather_evidence=weather_evidence,
        daylight=daylight,
        sunset=sunset,
    )
    missing_fields: list[str] = []
    if not daylight_reviewed:
        missing_fields.append("reviewed_daylight_window")
    if not current_time:
        missing_fields.append("current_time")
    if not target_eta:
        missing_fields.append("planned_target_eta")
    minutes_until_sunset = (
        _minutes_between(later=sunset, earlier=current_time)
        if current_time and sunset
        else None
    )
    route_daylight_buffer_minutes = (
        _minutes_between(later=sunset, earlier=target_eta)
        if target_eta and sunset
        else None
    )
    if current_time and sunset and minutes_until_sunset is None:
        missing_fields.append("current_time")
    if target_eta and sunset and route_daylight_buffer_minutes is None:
        missing_fields.append("planned_target_eta")
    missing_fields = _dedupe(missing_fields)
    if missing_fields:
        return {
            "status": "daylight_buffer_missing_context",
            "decision": "DELAY",
            "first_layer_decision": "無法確認日照 buffer 是否下降。",
            "main_reasons": [
                "reviewed daylight window, current_time, and planned target ETA are required to evaluate daylight buffer.",
                "missing_fields=" + ",".join(missing_fields),
            ],
            "action_limit": "不得把此回答當成仍有日照 buffer、可停留或可繼續推進的授權。",
            "next_action": "先補齊 reviewed sunrise/sunset、目前時間與 planned ETA；完成前不要消耗停留或攻頂 buffer。",
            "alternatives": [
                "載入已審核日照證據後在下一 CP 重查",
                "日照 buffer 崩潰前改短版或折返",
            ],
            "missing_fields": missing_fields,
            "daylight_buffer_impact": "daylight buffer cannot be computed from incomplete evidence",
            "current_time": current_time,
            "sunset": sunset,
            "planned_target_eta": target_eta,
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
    assert minutes_until_sunset is not None
    assert route_daylight_buffer_minutes is not None
    if route_daylight_buffer_minutes < 0:
        decision = "NO_GO"
        first_layer = "不建議照原計畫進入摸黑風險。"
        action_limit = "計畫目標 ETA 晚於已審核日落；沒有已審核撤退覆寫前不得照原計畫推進。"
        next_action = "改短版或折返，並重新計算撤退、天氣與最慢者腳程。"
        impact = "daylight buffer is already negative against planned target ETA"
    elif route_daylight_buffer_minutes < 30:
        decision = "CHANGE_PLAN"
        first_layer = f"日照 buffer 只剩約 {route_daylight_buffer_minutes:.0f} 分鐘。"
        action_limit = "日照 buffer 已低於 30 分鐘，不得再增加停留、拍攝、等待或攻頂壓力。"
        next_action = "改短版、前往最近安全 CP 或折返；下一 CP 前重新計算天氣與撤退窗口。"
        impact = "daylight buffer is near collapse and unavailable for discretionary actions"
    elif route_daylight_buffer_minutes < 60:
        decision = "CONDITIONAL_GO"
        first_layer = f"日照 buffer 約 {route_daylight_buffer_minutes:.0f} 分鐘，偏低。"
        action_limit = "只能照 CP Graph 監控推進；不得消耗停留或拍攝 buffer。"
        next_action = "下一 CP 前重算日照、天氣、撤退與最慢者速度；若再下降就改短版或折返。"
        impact = "daylight buffer is low and must be reserved for CP re-check"
    else:
        decision = "GO"
        first_layer = f"日照 buffer 約 {route_daylight_buffer_minutes:.0f} 分鐘。"
        action_limit = "這不是停留授權；任何拍攝、等待、午餐或攻頂仍需 contextual permission。"
        next_action = "照 CP Graph 推進，並在下一 CP 重新檢查日照 buffer 是否下降。"
        impact = "daylight buffer currently remains available but not spendable without permission"
    return {
        "status": "daylight_buffer_available",
        "decision": decision,
        "first_layer_decision": first_layer,
        "main_reasons": [
            f"reviewed sunset={sunset}; current_time={current_time}; minutes_until_sunset={minutes_until_sunset:.1f}.",
            f"planned_target_eta={target_eta}; daylight_buffer_to_target={route_daylight_buffer_minutes:.1f} minutes.",
        ],
        "action_limit": action_limit,
        "next_action": next_action,
        "alternatives": [
            "保留日照 buffer 給 CP 複查",
            "日照 buffer 低於下一門檻時改短版",
        ],
        "missing_fields": [],
        "minutes_until_sunset": round(minutes_until_sunset, 1),
        "route_daylight_buffer_minutes": round(route_daylight_buffer_minutes, 1),
        "daylight_buffer_impact": impact,
        "current_time": current_time,
        "sunset": sunset,
        "planned_target_eta": target_eta,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _weather_to_decision(
    *,
    query: str,
    answerability: str,
    weather_window: dict[str, Any],
    risk_summary: dict[str, Any],
    wx_alerts: list[dict[str, Any]],
    segments: list[dict[str, Any]],
    missing_fields: list[str],
    warnings: list[str],
    daylight_buffer_status: dict[str, Any],
) -> dict[str, Any]:
    highest = _highest_risk_segment(segments)
    alert_codes = sorted({code for alert in wx_alerts for code in _string_list(alert.get("code"))})
    route_sensitive_delay = _route_sensitive_weather_delay(segments)
    source_disagreement = _route_sensitive_source_disagreement(
        weather_window=weather_window,
        segments=segments,
    )
    heat_change_plan = _route_sensitive_heat_change_plan(segments)
    query_stated_rule = _query_stated_weather_rule(query)
    critical_package_risk = _critical_package_weather_risk(highest)
    applied_weather_rule: dict[str, Any] | None = None
    if source_disagreement and "SOURCE_CONFLICT" not in alert_codes:
        alert_codes.append("SOURCE_CONFLICT")
    if daylight_buffer_status:
        decision = str(daylight_buffer_status.get("decision") or "DELAY")
        main_reasons = _string_list(daylight_buffer_status.get("main_reasons"))
        action_limit = str(
            daylight_buffer_status.get("action_limit")
            or "日照窗口完成審核前，不得把日照視為仍可用。"
        )
        next_action = str(
            daylight_buffer_status.get("next_action")
            or "補齊日照窗口、目前時間與 planned ETA 後重新計算。"
        )
        alternatives = _string_list(daylight_buffer_status.get("alternatives"))
    elif missing_fields:
        if query_stated_rule:
            applied_weather_rule = query_stated_rule
            decision = str(query_stated_rule["decision"])
            main_reasons = _string_list(query_stated_rule.get("main_reasons"))
            action_limit = str(query_stated_rule["action_limit"])
            next_action = str(query_stated_rule["next_action"])
            alternatives = _string_list(query_stated_rule.get("alternatives"))
            for code in _string_list(query_stated_rule.get("alert_codes")):
                if code not in alert_codes:
                    alert_codes.append(code)
        else:
            decision = "DELAY"
            window_summary = str(weather_window.get("summary") or "").strip()
            main_reasons = [
                *([window_summary] if window_summary else []),
                "缺少完整且路線化的天氣決策證據。",
                "missing_fields=" + ",".join(missing_fields),
            ][:3]
            if missing_fields == ["direct_qpf_accumulation_mm"]:
                action_limit = (
                    "不得把降雨機率當成累積雨量，也不得只靠機率授權出發、"
                    "曝露稜線或渡溪決策。"
                )
                next_action = (
                    "補齊 route-corridor direct QPF accumulation 後，"
                    "重新疊加地形與行程時間窗。"
                )
            else:
                action_limit = (
                    "不得用不完整天氣證據授權出發、紮營、攻頂、"
                    "曝露稜線或渡溪決策。"
                )
                next_action = (
                    "補齊 fresh provider、TTL、valid-time 與 route weather "
                    "evidence；完成前採保守延後。"
                )
            alternatives = ["延後到新鮮路線天氣包完成審核", "改低曝露備援路線"]
    elif route_sensitive_delay:
        applied_weather_rule = route_sensitive_delay
        decision = "DELAY"
        crossing_count = route_sensitive_delay["creek_crossing_count"]
        main_reasons = [
            (
                f"前 24 小時降雨後，路線仍包含 {crossing_count:g} 處渡溪點。"
            ),
            "隊伍缺少渡溪經驗。",
            "降雨可能放大水位、濕滑、落石、崩塌與土石鬆動風險。",
        ]
        action_limit = (
            "溪流水位、近期路況與隊伍渡溪能力完成審核前，不得照原渡溪計畫出發。"
        )
        next_action = "建議延期 48 小時或改走低風險替代路線，並重新確認溪流水位與近期路況。"
        alternatives = [
            "延期 48 小時",
            "改走沒有渡溪點的低風險路線",
            "路況審核後改成嚮導/專家陪同渡溪方案",
        ]
    elif source_disagreement:
        applied_weather_rule = source_disagreement
        decision = "DELAY"
        main_reasons = [
            "預報來源分歧，天氣可信度不足。",
            "路線化天氣決策需要先完成來源比對。",
            "不得只採用較樂觀的預報作為授權依據。",
        ]
        action_limit = (
            "來源比對完成前，不得用單一樂觀預報授權出發、攻頂、曝露稜線、渡溪或紮營。"
        )
        next_action = (
            "先比對官方預報、路線天氣包與人工審核；若來源仍不一致，延後或改低曝露替代路線。"
        )
        alternatives = [
            "延後到預報來源收斂",
            "改保守低曝露路線",
            "路線敏感決策前先做人工作業天氣審核",
        ]
    elif heat_change_plan:
        applied_weather_rule = heat_change_plan
        decision = "CHANGE_PLAN"
        main_reasons = [
            "路線有高溫曝曬，且水量或遮蔽條件不足。",
            "高溫曝曬會放大熱傷害、補水、遮蔽與時段風險。",
            "原本曝曬時段需要移動或縮短。",
        ]
        action_limit = (
            "水量餘裕、遮蔽休息點與較涼行走時段完成審核前，不得照原高溫曝曬時段推進。"
        )
        next_action = (
            "改到清晨或較涼時段、補足水量並指定遮蔽休息點；若無法滿足就改短低曝曬路線。"
        )
        alternatives = [
            "把曝露路段移到較涼時段",
            "增加水量餘裕並指定已審核遮蔽休息點",
            "改短版或低曝曬路線",
        ]
    elif query_stated_rule and not critical_package_risk:
        applied_weather_rule = query_stated_rule
        decision = str(query_stated_rule["decision"])
        main_reasons = _string_list(query_stated_rule.get("main_reasons"))
        action_limit = str(query_stated_rule["action_limit"])
        next_action = str(query_stated_rule["next_action"])
        alternatives = _string_list(query_stated_rule.get("alternatives"))
        for code in _string_list(query_stated_rule.get("alert_codes")):
            if code not in alert_codes:
                alert_codes.append(code)
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
        "route_sensitive_weather_rule": applied_weather_rule,
        "highest_risk_segment": _compact_segment(highest) if highest else None,
        "wx_alert_count": len(wx_alerts),
        "warnings": warnings[:3],
        "weather_buffer_impact": _weather_buffer_impact(
            decision,
            missing_fields=bool(missing_fields),
        ),
        "daylight_buffer_status": daylight_buffer_status,
        "daylight_buffer_impact": daylight_buffer_status.get("daylight_buffer_impact")
        if daylight_buffer_status
        else None,
        "first_layer_decision": daylight_buffer_status.get("first_layer_decision")
        if daylight_buffer_status
        else None,
    }


def _field_answer(
    *,
    decision: dict[str, Any],
    answerability: str,
    missing_fields: list[str],
) -> str:
    decision_label = str(decision.get("decision") or "DELAY")
    reasons = decision.get("main_reasons")
    reason_text = (
        "；".join(
            str(reason).strip().rstrip("。；;")
            for reason in reasons[:2]
            if str(reason).strip().rstrip("。；;")
        )
        if isinstance(reasons, list)
        else ""
    )
    rule = decision.get("route_sensitive_weather_rule")
    query_reported = isinstance(rule, dict) and rule.get("query_reported") is True
    if decision.get("daylight_buffer_status"):
        if not reason_text:
            reason_text = f"answerability={answerability}"
        next_action = str(
            decision.get("next_action") or "補齊日照與 planned ETA 後再判斷。"
        )
        return (
            f"日照 buffer 判斷：建議 {decision_label}。{reason_text} "
            f"下一步：{next_action} "
            "此為 Weather-to-Decision / daylight buffer 候選判斷，不是 runtime safety truth；不得觸發 /safety、SOS、outbound send 或硬體控制。"
        )
    if missing_fields and not query_reported:
        missing_reason = (
            f"缺少 {', '.join(missing_fields)}，"
            "不能只看降雨機率或 placeholder。"
        )
        reason_text = (
            f"{reason_text}；{missing_reason}" if reason_text else missing_reason
        )
    elif missing_fields and query_reported:
        reason_text = (
            (reason_text + "；") if reason_text else ""
        ) + f"仍缺少 {', '.join(missing_fields)}，此判斷只能作為使用者回報條件下的候選保守決策。"
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
        "decision": str(
            decision.get("first_layer_decision")
            or _decision_phrase(decision_label, allowed=allowed)
        ),
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
            "daylightBufferImpact": decision.get("daylight_buffer_impact"),
            "daylightBufferStatus": decision.get("daylight_buffer_status") or {},
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
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 13 risk budget",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 15.2 Risk Sentinel",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 16 required decision output format",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 17 ContextualPermission schema",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 19 on-route recalculation",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 23 acceptance criteria",
        ],
        "runtimeSafetyTruth": False,
    }


def _weather_required_conditions(
    *,
    decision: dict[str, Any],
    missing_fields: list[str],
) -> list[str]:
    required = [f"補齊 {field}。" for field in missing_fields]
    decision_label = str(decision.get("decision") or "")
    if decision_label in {"NO_GO", "CHANGE_PLAN"}:
        required.append("改選較低風險天氣窗口或替代路線。")
    if decision_label == "CONDITIONAL_GO":
        required.append("下一 CP 重新檢查天氣與路線風險。")
    if not required:
        required.append("保持 route weather package 新鮮且已審核。")
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


def _critical_package_weather_risk(highest: dict[str, Any] | None) -> bool:
    if not highest:
        return False
    final_risk = _float_or_none(highest.get("final_risk")) or 0.0
    level = str(highest.get("risk_level") or "").lower()
    return level in {"critical", "severe", "extreme"} or final_risk >= 0.85


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
        return "此天氣窗口下不得進入已標記路段。"
    if decision == "CHANGE_PLAN":
        if {"THUNDER", "WIND"} & set(alert_codes):
            return "標記天氣窗口內避開曝露稜線、山頂與開闊地。"
        if "HEAT" in alert_codes:
            return (
                "水量餘裕、遮蔽休息點與較涼行走時段完成審核前，避開高溫曝曬時段。"
            )
        if "RAIN" in alert_codes:
            return "標記天氣窗口內避開渡溪、崩塌敏感切坡與濕滑曝露地形。"
        return "不得依原時程通過最高風險路段。"
    if decision == "CONDITIONAL_GO":
        segment = highest.get("segment_id") if highest else "flagged segment"
        return f"只有在天氣惡化前能通過 {segment}，且下一 CP 會重新評估時，才可繼續。"
    return "只有新鮮 route_weather_package 仍有效時，才可維持原計畫。"


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
        alternatives = ["延後 24-48 小時", "改低曝露備援路線"]
        if "THUNDER" in alert_codes:
            alternatives.append("把稜線/山頂曝露移出雷雨窗口")
        if "RAIN" in alert_codes:
            alternatives.append("避開溪谷與崩塌敏感路段")
        if "HEAT" in alert_codes:
            alternatives.append("把曝露行走移到較涼時段並確認水量餘裕")
        return alternatives
    if decision == "CONDITIONAL_GO":
        return ["縮短路線", "設定更早折返 CP", "提高 CP 天氣複查頻率"]
    return ["維持排定 CP 天氣複查"]


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


def _query_stated_weather_rule(query: str) -> dict[str, Any] | None:
    normalized = str(query or "").replace(" ", "").lower()
    if not normalized:
        return None
    asks_route_decision = any(
        term in normalized
        for term in (
            "今天還能走",
            "還能走",
            "能不能走",
            "改變計畫",
            "改計畫",
            "改原計畫",
            "照原路線",
            "原計畫",
            "需要重規劃",
            "是否需要保守決策",
            "是否需要重新評估",
            "是否升高",
            "天氣決策",
            "route",
            "plan",
        )
    )
    if _mentions_previous_24h_rain(normalized) and any(
        term in normalized
        for term in (
            "溪水",
            "渡溪",
            "過溪",
            "崩塌",
            "落石",
            "濕滑",
            "土石",
            "水位",
            "倒木",
            "通行性",
            "creek",
            "stream",
            "landslide",
            "rockfall",
        )
    ):
        return {
            "rule": "query_reported_previous_24h_rain_route_reassessment",
            "decision": "CHANGE_PLAN" if asks_route_decision else "DELAY",
            "query_reported": True,
            "alert_codes": ["RAIN", "TERRAIN"],
            "main_reasons": [
                "使用者回報前 24 小時降雨，且涉及溪水、濕滑、落石或崩塌疑慮。",
                "近期降雨可能抬升水位，並放大濕滑、落石、崩塌與土石鬆動風險。",
                "恢復原計畫前仍需補齊新鮮 route_weather_package。",
            ],
            "action_limit": (
                "路線化審核完成前，不得把原路線視為已核准；先避開渡溪、崩塌、落石與濕滑路段。"
            ),
            "next_action": "改低風險替代路線或延後，並補齊近期路況、溪流水位與 route_weather_package 後再判斷。",
            "alternatives": [
                "延後到近期降雨影響完成審核",
                "改走沒有渡溪或崩塌敏感地形的路線",
                "人工審核水位與近期路況後再判斷",
            ],
        }
    if any(term in normalized for term in ("午後雷雨", "雷雨", "thunderstorm")):
        return {
            "rule": "query_reported_thunderstorm_exposure_review",
            "decision": "CHANGE_PLAN" if asks_route_decision else "DELAY",
            "query_reported": True,
            "alert_codes": ["THUNDER"],
            "main_reasons": [
                "使用者回報路線決策時段有雷雨壓力。",
                "雷雨會改變稜線、山頂、開闊地與溪谷通行決策。",
                "恢復原計畫前仍需補齊新鮮 route_weather_package。",
            ],
            "action_limit": "雷雨壓力解除前，不得進入稜線、山頂、開闊地或溪谷曝露情境。",
            "next_action": "移出曝露路段、改短版或延後到較穩定天氣窗，並在下一 CP 重新檢查天氣。",
            "alternatives": [
                "避開稜線與山頂曝露",
                "改走較避風避雷的低海拔路線",
                "延後到雷雨窗口通過後",
            ],
        }
    if any(term in normalized for term in ("強風低溫", "強風", "低溫", "失溫", "cold", "wind")):
        return {
            "rule": "query_reported_wind_cold_exposure_review",
            "decision": "CHANGE_PLAN" if asks_route_decision else "DELAY",
            "query_reported": True,
            "alert_codes": ["WIND", "COLD"],
            "main_reasons": [
                "使用者回報強風或低溫曝露，失溫風險可能升高。",
                "稜線與紮營決策需要同時審核風、溫度、裝備與撤退 buffer。",
                "恢復原計畫前仍需補齊新鮮 route_weather_package。",
            ],
            "action_limit": "強風低溫、裝備與撤退 buffer 完成審核前，不得承諾曝露稜線或紮營計畫。",
            "next_action": "改低曝露路線、縮短停留或下撤到避風點；補齊天氣包與保暖裝備檢查。",
            "alternatives": [
                "移動到避風 CP",
                "縮短曝露稜線行走",
                "強風低溫審核完成前延後紮營決策",
            ],
        }
    if _has_heat_signal(normalized, temperature_c=None, heat_index_c=None):
        return {
            "rule": "query_reported_heat_exposure_timing_review",
            "decision": "CHANGE_PLAN" if asks_route_decision else "DELAY",
            "query_reported": True,
            "alert_codes": ["HEAT"],
            "main_reasons": [
                "使用者回報高溫曝曬或補水時段壓力。",
                "高溫會提高水量、遮蔽、熱傷害與行走時段要求。",
                "恢復原計畫前仍需補齊新鮮 route_weather_package。",
            ],
            "action_limit": "水量餘裕、遮蔽點與較涼行走時段完成審核前，不得照原曝曬時段推進。",
            "next_action": "改到清晨或較涼時段、補水並指定遮蔽休息點；不滿足時改短低曝曬路線。",
            "alternatives": [
                "把曝露路段移到較涼時段",
                "增加水量餘裕與遮蔽休息點",
                "改短版低曝曬路線",
            ],
        }
    if _mentions_source_disagreement(normalized):
        return {
            "rule": "query_reported_forecast_source_disagreement_review",
            "decision": "DELAY",
            "query_reported": True,
            "alert_codes": ["SOURCE_CONFLICT"],
            "main_reasons": [
                "使用者回報預報來源不一致。",
                "路線敏感天氣決策不得只採用較樂觀來源。",
                "需要新鮮 route_weather_package 與來源比對。",
            ],
            "action_limit": "來源仍不一致時，不得用較樂觀預報授權出發、曝露稜線、渡溪、攻頂或紮營。",
            "next_action": "先比對官方預報、路線天氣包與人工審核；若來源仍不一致，延後或改低曝露替代路線。",
            "alternatives": [
                "延後到預報來源收斂",
                "改保守低曝露路線",
                "路線敏感決策前先做人工作業天氣審核",
            ],
        }
    return None


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


def _looks_like_daylight_buffer_question(query: str) -> bool:
    normalized = str(query or "").replace(" ", "").lower()
    has_daylight = any(
        term in normalized
        for term in (
            "日照",
            "日落",
            "天黑",
            "摸黑",
            "sunset",
            "daylight",
            "darkarrival",
            "nightfall",
        )
    )
    has_buffer_or_decision = any(
        term in normalized
        for term in (
            "buffer",
            "餘裕",
            "下降",
            "剩",
            "還有",
            "多久",
            "繼續",
            "能不能",
            "可以",
            "是否",
        )
    )
    return has_daylight and has_buffer_or_decision


def _planned_target_eta(planned_eta: dict[str, Any]) -> str | None:
    assumption = planned_eta.get("assumption")
    assumption = assumption if isinstance(assumption, dict) else {}
    target_eta = _first_present(
        assumption,
        "target_eta",
        "planned_target_eta",
        "arrival_eta",
    )
    if target_eta:
        return str(target_eta)
    estimates = planned_eta.get("estimates")
    if not isinstance(estimates, list):
        return None
    eta_values = [
        str(item.get("eta"))
        for item in estimates
        if isinstance(item, dict) and item.get("eta")
    ]
    return eta_values[-1] if eta_values else None


def _daylight_window_reviewed(
    *,
    route_package: dict[str, Any],
    weather_evidence: dict[str, Any],
    daylight: dict[str, Any],
    sunset: Any,
) -> bool:
    if not sunset:
        return False
    if route_package:
        return (
            str(daylight.get("source_status") or "").lower()
            in {"reviewed", "accepted", "computed", "server_side_fixture"}
            and route_package.get("human_review_required") is not True
        )
    if weather_evidence.get("human_review_required") is True:
        return False
    validation = weather_evidence.get("validation")
    validation = validation if isinstance(validation, dict) else {}
    if validation.get("validation_status") == "human_review_required":
        return False
    return str(daylight.get("source_status") or "").lower() in {
        "reviewed",
        "accepted",
        "computed",
        "server_side_fixture",
    }


def _minutes_between(*, later: Any, earlier: Any) -> float | None:
    later_dt = _parse_datetime(later)
    earlier_dt = _parse_datetime(earlier)
    if later_dt is not None and earlier_dt is not None:
        return round((later_dt - earlier_dt).total_seconds() / 60.0, 1)
    later_clock = _local_clock_minutes(later)
    earlier_clock = _local_clock_minutes(earlier)
    if later_clock is None or earlier_clock is None:
        return None
    return round(later_clock - earlier_clock, 1)


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
    query: str,
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
    if route_package and not _route_weather_scope_available(route_package):
        missing.append("route_weather_segments")
    if (
        _is_precipitation_amount_question(query)
        and route_package.get("adapter_kind")
        == "fresh_prepared_weather_decision_inputs"
        and route_package.get("direct_qpf_available") is not True
    ):
        missing.append("direct_qpf_accumulation_mm")
    return _dedupe(missing)


def _route_weather_scope_available(route_package: dict[str, Any]) -> bool:
    return bool(
        route_package
        and (
            _route_weather_segments(route_package)
            or route_package.get("route_corridor_assessed") is True
        )
    )


def _is_precipitation_amount_question(query: str) -> bool:
    normalized = str(query or "").replace(" ", "").casefold()
    return any(
        term in normalized
        for term in (
            "雨量",
            "降雨量",
            "累積雨",
            "多少雨",
            "幾毫米",
            "多少毫米",
            "rainfallamount",
            "precipitationamount",
            "qpf",
        )
    )


def _warnings(
    *,
    route_package: dict[str, Any],
    weather_evidence: dict[str, Any],
    missing_fields: list[str],
    stale_after_hours: float,
    reference_time: datetime,
    stale_warnings: list[str] | None = None,
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
    if _is_placeholder(weather_evidence) and not route_package:
        warnings.append(
            "Weather evidence is a manual placeholder and requires human review before departure-gate use."
        )
    warnings.extend(
        stale_warnings
        if stale_warnings is not None
        else _stale_warnings(
            route_package=route_package,
            weather_evidence=weather_evidence,
            stale_after_hours=stale_after_hours,
            reference_time=reference_time,
        )
    )
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


def _stale_warnings(
    *,
    route_package: dict[str, Any],
    weather_evidence: dict[str, Any],
    stale_after_hours: float,
    reference_time: datetime,
) -> list[str]:
    warnings = []
    for source in (route_package, weather_evidence):
        warning = _stale_warning(source, stale_after_hours, reference_time)
        if warning:
            warnings.append(warning)
    return _dedupe(warnings)


def _stale_warning(
    source: dict[str, Any],
    stale_after_hours: float,
    reference_time: datetime,
) -> str | None:
    if not source:
        return None
    valid_until = _first_present(source, "valid_until", "validUntil", "valid_to", "validTo")
    if valid_until:
        parsed = _parse_datetime(valid_until)
        if parsed and parsed < reference_time:
            return f"Weather source is past valid_until={valid_until}."
    generated_at = _first_present(source, "generated_at", "generatedAt", "issued_at", "issuedAt")
    parsed_generated_at = _parse_datetime(generated_at)
    if parsed_generated_at is None:
        return None
    age_hours = (
        reference_time - parsed_generated_at.astimezone(timezone.utc)
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
