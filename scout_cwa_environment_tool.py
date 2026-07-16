from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CWA_ENVIRONMENT_TOOL_ID = "scout.ai.cwa_environment.assess.v0"
CWA_ENVIRONMENT_OUTPUT_KIND = "scout_ai_cwa_environment_tool_output"
CWA_ENVIRONMENT_REQUIRED_FIELDS = ("project_root",)
CWA_ENVIRONMENT_OPTIONAL_FIELDS = (
    "environment_package_path",
    "factor_matrix_path",
    "go_no_go_review_path",
    "cwa_weather_evidence_path",
    "warnings_geojson_path",
    "observations_geojson_path",
    "qpf_grid_path",
    "qpf_route_timeline_path",
    "qpf_corridor_summary_path",
    "forecast_timeline_path",
    "astronomy_timeline_path",
    "tide_marine_timeline_path",
    "radar_frames_manifest_path",
    "satellite_frames_manifest_path",
    "include_features",
    "include_timeline",
    "stale_after_hours",
    "reference_time",
)

DEFAULT_STALE_AFTER_HOURS = 12.0
DEFAULT_RESULT_LIMIT = 6
MAX_RESULT_LIMIT = 12


def assess_scout_cwa_environment(
    project_root: Path | str,
    *,
    query: str = "",
    environment_package_path: str | None = None,
    factor_matrix_path: str | None = None,
    go_no_go_review_path: str | None = None,
    cwa_weather_evidence_path: str | None = None,
    warnings_geojson_path: str | None = None,
    observations_geojson_path: str | None = None,
    qpf_grid_path: str | None = None,
    qpf_route_timeline_path: str | None = None,
    qpf_corridor_summary_path: str | None = None,
    forecast_timeline_path: str | None = None,
    astronomy_timeline_path: str | None = None,
    tide_marine_timeline_path: str | None = None,
    radar_frames_manifest_path: str | None = None,
    satellite_frames_manifest_path: str | None = None,
    include_features: bool | str | None = None,
    include_timeline: bool | str | None = None,
    stale_after_hours: float | int | str | None = None,
    reference_time: str | None = None,
    limit: int = DEFAULT_RESULT_LIMIT,
) -> dict[str, Any]:
    """Read prepared CWA environment evidence from a Scout workspace.

    This tool intentionally performs no live CWA network request. Server-side
    pretrip preparation may create these artifacts with CWA credentials, but
    Scout AI only receives redacted, candidate-only workspace evidence.
    """

    root = Path(project_root)
    project = _load_json_object(root / "project.json")
    project_id = str(project.get("project_id") or project.get("id") or root.name)
    resolved_limit = _bounded_limit(limit)
    include_feature_rows = _bool_value(include_features, default=True)
    include_timeline_rows = _bool_value(include_timeline, default=True)
    stale_hours = _float_or_default(
        stale_after_hours,
        default=DEFAULT_STALE_AFTER_HOURS,
    )
    reference_now = _reference_datetime(reference_time)

    source_report: list[dict[str, Any]] = []
    environment_package = _load_artifact(
        root,
        project,
        explicit_path=environment_package_path,
        ref_keys=("environment_evidence_package_ref",),
        fallbacks=("outputs/environment/environment_evidence_package.json",),
        source_kind="environment_evidence_package",
        source_report=source_report,
    )
    factor_matrix = _load_artifact(
        root,
        project,
        explicit_path=factor_matrix_path,
        ref_keys=("environment_factor_matrix_ref",),
        fallbacks=("outputs/environment/environment_factor_matrix.json",),
        source_kind="environment_factor_matrix",
        source_report=source_report,
    )
    go_no_go_review = _load_artifact(
        root,
        project,
        explicit_path=go_no_go_review_path,
        ref_keys=("go_no_go_review_draft_ref",),
        fallbacks=("outputs/environment/go_no_go_review_draft.json",),
        source_kind="go_no_go_review_draft",
        source_report=source_report,
    )
    cwa_weather_evidence = _load_artifact(
        root,
        project,
        explicit_path=cwa_weather_evidence_path,
        ref_keys=("cwa_weather_evidence_ref",),
        fallbacks=(
            "outputs/environment/cwa/cwa_weather_evidence.json",
            "outputs/cwa_weather_evidence.json",
            "outputs/weather_daylight_evidence.json",
        ),
        source_kind="cwa_weather_evidence",
        source_report=source_report,
    )
    warnings = _load_artifact(
        root,
        project,
        explicit_path=warnings_geojson_path,
        ref_keys=("cwa_warnings_geojson_ref",),
        fallbacks=("outputs/environment/cwa/warnings.geojson",),
        source_kind="cwa_warnings_geojson",
        source_report=source_report,
    )
    observations = _load_artifact(
        root,
        project,
        explicit_path=observations_geojson_path,
        ref_keys=("cwa_observations_geojson_ref",),
        fallbacks=("outputs/environment/cwa/observations.geojson",),
        source_kind="cwa_observations_geojson",
        source_report=source_report,
    )
    qpf_grid = _load_artifact(
        root,
        project,
        explicit_path=qpf_grid_path,
        ref_keys=("cwa_qpf_grid_ref",),
        fallbacks=("outputs/environment/cwa/qpf_grid.geojson",),
        source_kind="cwa_qpf_grid",
        source_report=source_report,
    )
    qpf_route_timeline = _load_artifact(
        root,
        project,
        explicit_path=qpf_route_timeline_path,
        ref_keys=("cwa_qpf_route_timeline_ref",),
        fallbacks=("outputs/environment/cwa/qpf_route_timeline.json",),
        source_kind="cwa_qpf_route_timeline",
        source_report=source_report,
    )
    qpf_corridor_summary = _load_artifact(
        root,
        project,
        explicit_path=qpf_corridor_summary_path,
        ref_keys=("cwa_qpf_corridor_summary_ref",),
        fallbacks=("outputs/environment/cwa/qpf_corridor_summary.json",),
        source_kind="cwa_qpf_corridor_summary",
        source_report=source_report,
    )
    forecast_timeline = _load_artifact(
        root,
        project,
        explicit_path=forecast_timeline_path,
        ref_keys=("cwa_forecast_timeline_ref",),
        fallbacks=("outputs/environment/cwa/forecast_timeline.json",),
        source_kind="cwa_forecast_timeline",
        source_report=source_report,
    )
    astronomy_timeline = _load_artifact(
        root,
        project,
        explicit_path=astronomy_timeline_path,
        ref_keys=("cwa_astronomy_timeline_ref",),
        fallbacks=("outputs/environment/cwa/astronomy_timeline.json",),
        source_kind="cwa_astronomy_timeline",
        source_report=source_report,
    )
    tide_marine_timeline = _load_artifact(
        root,
        project,
        explicit_path=tide_marine_timeline_path,
        ref_keys=("cwa_tide_marine_timeline_ref",),
        fallbacks=("outputs/environment/cwa/tide_marine_timeline.json",),
        source_kind="cwa_tide_marine_timeline",
        source_report=source_report,
    )
    radar_frames_manifest = _load_artifact(
        root,
        project,
        explicit_path=radar_frames_manifest_path,
        ref_keys=("cwa_radar_frames_manifest_ref",),
        fallbacks=("outputs/environment/cwa/imagery/radar_frames_manifest.json",),
        source_kind="cwa_radar_frames_manifest",
        source_report=source_report,
        report_missing=False,
    )
    satellite_frames_manifest = _load_artifact(
        root,
        project,
        explicit_path=satellite_frames_manifest_path,
        ref_keys=("cwa_satellite_frames_manifest_ref",),
        fallbacks=(
            "outputs/environment/cwa/imagery/satellite_frames_manifest.json",
        ),
        source_kind="cwa_satellite_frames_manifest",
        source_report=source_report,
        report_missing=False,
    )

    artifacts = {
        "environment_package": environment_package,
        "factor_matrix": factor_matrix,
        "go_no_go_review": go_no_go_review,
        "cwa_weather_evidence": cwa_weather_evidence,
        "warnings": warnings,
        "observations": observations,
        "qpf_grid": qpf_grid,
        "qpf_route_timeline": qpf_route_timeline,
        "qpf_corridor_summary": qpf_corridor_summary,
        "forecast_timeline": forecast_timeline,
        "astronomy_timeline": astronomy_timeline,
        "tide_marine_timeline": tide_marine_timeline,
        "radar_frames_manifest": radar_frames_manifest,
        "satellite_frames_manifest": satellite_frames_manifest,
    }
    missing_fields = _missing_fields(source_report)
    stale_risks = _stale_risks(
        source_report,
        stale_after_hours=stale_hours,
        reference_time=reference_now,
    )
    effective_missing_fields = [
        *missing_fields,
        *(["fresh_cwa_environment_evidence"] if stale_risks else []),
    ]
    warnings_list = _warnings(
        missing_fields=effective_missing_fields,
        stale_risks=stale_risks,
    )
    route_points, route_geometry_ref = _load_route_points(root, project)
    cwa_summary = _cwa_summary(
        artifacts,
        route_points=route_points,
        route_geometry_ref=route_geometry_ref,
        stale_after_hours=stale_hours,
        reference_time=reference_now,
    )
    decision_output = _decision_output(
        summary=cwa_summary,
        missing_fields=effective_missing_fields,
        warnings=warnings_list,
    )
    field_answer = _field_answer(decision_output, cwa_summary, query=query)
    field_answer_source_ref = _field_answer_source_ref(query)
    field_answer_source_refs = _field_answer_source_refs(query)
    results = _results(
        artifacts,
        include_features=include_feature_rows,
        include_timeline=include_timeline_rows,
        limit=resolved_limit,
    )
    answerability = (
        "cwa_environment_available"
        if cwa_summary["available_artifact_count"] >= 3
        and not effective_missing_fields
        else "cwa_environment_partial"
        if cwa_summary["available_artifact_count"]
        else "cwa_environment_missing"
    )

    return {
        "tool_id": CWA_ENVIRONMENT_TOOL_ID,
        "status": "completed",
        "project_id": project_id,
        "query": query,
        "source_ref": field_answer_source_ref,
        "assessment_kind": "read_only_cwa_environment_workspace",
        "answerability": answerability,
        "source_status": _source_status(cwa_summary["available_artifact_count"]),
        "decision": decision_output["decision"],
        "decision_output": decision_output,
        "field_answer": field_answer,
        "field_answer_priority": 100 if _is_exact_cwa_query(query) else 10,
        "field_answer_source_ref": field_answer_source_ref,
        "field_answer_source_refs": field_answer_source_refs,
        "external_api_calls_made": False,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "human_review_required": True,
        "filters": {
            "include_features": include_feature_rows,
            "include_timeline": include_timeline_rows,
            "stale_after_hours": stale_hours,
            "reference_time": reference_now.isoformat(),
        },
        "cwa_environment": {
            "role": "CWA official weather/environment workspace evidence",
            "candidate_only": True,
            "runtime_safety_truth": False,
            "human_review_required": True,
            "summary": cwa_summary,
            "decision_output": decision_output,
        },
        "cwa_summary": cwa_summary,
        "provenance_summary": _provenance_summary(source_report),
        "missing_fields": effective_missing_fields,
        "warnings": warnings_list,
        "source_report": source_report,
        "result_count": len(results),
        "results": results,
        "standard_alignment": [
            "docs/specs/scout-weather-environment-sensing.md CWA OpenData family",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 10 Weather-to-Decision Intelligence",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 28.3 Data Confidence",
        ],
        "boundary": _closed_boundary(),
    }


def _load_artifact(
    root: Path,
    project: dict[str, Any],
    *,
    explicit_path: str | None,
    ref_keys: tuple[str, ...],
    fallbacks: tuple[str, ...],
    source_kind: str,
    source_report: list[dict[str, Any]],
    report_missing: bool = True,
) -> dict[str, Any]:
    refs = _candidate_paths(
        root,
        project,
        explicit_path=explicit_path,
        ref_keys=ref_keys,
        fallbacks=fallbacks,
    )
    for ref in refs:
        path = _resolve_project_path(root, ref)
        if not path.exists() or not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            source_report.append(
                _source_report(
                    source_kind,
                    ref,
                    status="error",
                    error=str(exc),
                )
            )
            return {}
        if isinstance(payload, dict):
            source_report.append(
                _source_report(
                    source_kind,
                    ref,
                    status="loaded",
                    payload=payload,
                )
            )
            return payload
        if isinstance(payload, list):
            normalized = {"items": payload}
            source_report.append(
                _source_report(
                    source_kind,
                    ref,
                    status="loaded",
                    payload=normalized,
                )
            )
            return normalized
        source_report.append(
            _source_report(
                source_kind,
                ref,
                status="error",
                error="JSON artifact must be an object or list",
            )
        )
        return {}
    if report_missing:
        source_report.append(_source_report(source_kind, refs[0], status="missing"))
    return {}


def _candidate_paths(
    root: Path,
    project: dict[str, Any],
    *,
    explicit_path: str | None,
    ref_keys: tuple[str, ...],
    fallbacks: tuple[str, ...],
) -> list[str]:
    refs: list[str] = []
    if explicit_path:
        refs.append(explicit_path)
    for key in ref_keys:
        value = project.get(key)
        if isinstance(value, str) and value.strip():
            refs.append(value.strip())
    refs.extend(fallbacks)
    deduped: list[str] = []
    seen = set()
    for ref in refs:
        normalized = _project_ref(root, ref)
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(normalized)
    return deduped


def _project_ref(root: Path, ref: str) -> str:
    path = Path(str(ref))
    if path.is_absolute():
        try:
            return str(path.relative_to(root))
        except ValueError:
            return str(path)
    return str(path)


def _resolve_project_path(root: Path, ref: str) -> Path:
    path = Path(str(ref))
    if path.is_absolute():
        return path
    return root / path


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _source_report(
    source_kind: str,
    source_path: str,
    *,
    status: str,
    payload: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "source_kind": source_kind,
        "source_path": source_path,
        "status": status,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "human_review_required": True,
    }
    if error:
        report["error"] = error
    if payload:
        report.update(
            {
                "artifact_kind": payload.get("artifact_kind"),
                "schema_version": payload.get("schema_version"),
                "dataset_ids": _dataset_ids(payload),
                "source_refs": _source_refs(payload),
                "raw_response_hash": _raw_hash(payload),
                "stale_risk": _stale_risk(payload),
                "request_timestamp": _request_timestamp(payload),
                "normalized_artifact_ref": payload.get("normalized_artifact_ref"),
            }
        )
    return {key: value for key, value in report.items() if value not in (None, [], {})}


def _cwa_summary(
    artifacts: dict[str, dict[str, Any]],
    *,
    route_points: list[tuple[float, float]],
    route_geometry_ref: str | None,
    stale_after_hours: float,
    reference_time: datetime,
) -> dict[str, Any]:
    qpf_summary = _compact_qpf_summary(
        artifacts["qpf_corridor_summary"],
        qpf_grid=artifacts["qpf_grid"],
        qpf_timeline=artifacts["qpf_route_timeline"],
        stale_after_hours=stale_after_hours,
        reference_time=reference_time,
    )
    observation_summary = _observation_summary(
        artifacts["observations"],
        route_points=route_points,
        route_geometry_ref=route_geometry_ref,
    )
    warning_summary = _warning_layer_summary(artifacts["warnings"])
    forecast_summary = _forecast_timeline_summary(artifacts["forecast_timeline"])
    astronomy_summary = _astronomy_timeline_summary(
        artifacts["astronomy_timeline"]
    )
    tide_summary = _tide_marine_timeline_summary(
        artifacts["tide_marine_timeline"]
    )
    weather_dataset_summary = _weather_dataset_summary(
        artifacts["cwa_weather_evidence"]
    )
    imagery_summary = {
        "radar": _imagery_manifest_summary(artifacts["radar_frames_manifest"]),
        "satellite": _imagery_manifest_summary(
            artifacts["satellite_frames_manifest"]
        ),
    }
    return {
        "available_artifact_count": sum(1 for value in artifacts.values() if value),
        "warning_count": _feature_count(artifacts["warnings"]),
        "observation_count": _feature_count(artifacts["observations"]),
        "qpf_grid_feature_count": _feature_count(artifacts["qpf_grid"]),
        "qpf_route_timeline_event_count": _event_count(
            artifacts["qpf_route_timeline"]
        ),
        "qpf_summary_available": bool(qpf_summary),
        "forecast_timeline_event_count": _event_count(artifacts["forecast_timeline"]),
        "astronomy_event_count": _event_count(artifacts["astronomy_timeline"]),
        "tide_marine_event_count": _event_count(
            artifacts["tide_marine_timeline"]
        ),
        "datasets": sorted(
            {
                dataset
                for payload in artifacts.values()
                for dataset in _dataset_ids(payload)
            }
        ),
        "qpf_corridor_summary": qpf_summary,
        "observation_summary": observation_summary,
        "warning_summary": warning_summary,
        "forecast_summary": forecast_summary,
        "astronomy_summary": astronomy_summary,
        "tide_marine_summary": tide_summary,
        "weather_dataset_summary": weather_dataset_summary,
        "imagery_summary": imagery_summary,
        "environment_factor_matrix_keys": sorted(artifacts["factor_matrix"].keys())[:12],
        "go_no_go_review_available": bool(artifacts["go_no_go_review"]),
        "candidate_only": True,
        "runtime_safety_truth": False,
        "human_review_required": True,
    }


def _warning_layer_summary(payload: dict[str, Any]) -> dict[str, Any]:
    features = payload.get("features")
    rows = features if isinstance(features, list) else []
    areas: list[str] = []
    labels: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        properties = row.get("properties")
        properties = properties if isinstance(properties, dict) else {}
        for key in (
            "area_name",
            "township_name",
            "location_name",
            "county",
            "district",
        ):
            value = properties.get(key)
            if isinstance(value, str) and value.strip():
                areas.append(value.strip())
        affected = properties.get("affected_areas") or properties.get("areas")
        if isinstance(affected, list):
            areas.extend(str(item).strip() for item in affected if str(item).strip())
        label = properties.get("name") or properties.get("event")
        if isinstance(label, str) and label.strip():
            labels.append(label.strip())
    return {
        "feature_count": len(rows),
        "affected_areas": _dedupe_text(areas),
        "labels": _dedupe_text(labels),
    }


def _forecast_timeline_summary(payload: dict[str, Any]) -> dict[str, Any]:
    events = payload.get("events")
    rows = events if isinstance(events, list) else []
    areas: list[str] = []
    starts: list[str] = []
    ends: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in (
            "township_name",
            "township",
            "location_name",
            "area_name",
            "county",
            "district",
        ):
            value = row.get(key)
            if isinstance(value, str) and value.strip():
                areas.append(value.strip())
                break
        start = _first_text(row, "valid_from", "start_time", "valid_time", "time")
        end = _first_text(row, "valid_to", "end_time", "valid_time", "time")
        if start:
            starts.append(start)
        if end:
            ends.append(end)
    return {
        "event_count": len(rows),
        "areas": _dedupe_text(areas),
        "valid_from": min(starts) if starts else None,
        "valid_to": max(ends) if ends else None,
        "dataset_ids": _dataset_ids(payload),
    }


def _astronomy_timeline_summary(payload: dict[str, Any]) -> dict[str, Any]:
    events = payload.get("events")
    rows = [item for item in events if isinstance(item, dict)] if isinstance(events, list) else []
    values = {
        "sunset": None,
        "civil_twilight": None,
        "practical_darkness": None,
    }
    reason = None
    for row in rows:
        event = str(row.get("event") or row.get("type") or "").casefold()
        event_time = _first_text(row, "local_time", "time", "valid_time")
        if "sunset" in event or "日落" in event:
            values["sunset"] = event_time
        elif "civil" in event or "民用暮光" in event:
            values["civil_twilight"] = event_time
        elif "practical" in event or "darkness" in event or "天黑" in event:
            values["practical_darkness"] = event_time
        if reason is None and isinstance(row.get("reason"), str):
            reason = str(row["reason"])
    return {
        "status": payload.get("status") or ("available" if rows else "missing"),
        **values,
        "reason": reason,
        "dataset_ids": _dataset_ids(payload),
    }


def _tide_marine_timeline_summary(payload: dict[str, Any]) -> dict[str, Any]:
    events = payload.get("events")
    rows = [item for item in events if isinstance(item, dict)] if isinstance(events, list) else []
    event_names = _dedupe_text(
        str(item.get("event") or item.get("type") or "").strip()
        for item in rows
        if str(item.get("event") or item.get("type") or "").strip()
    )
    reasons = _dedupe_text(
        str(item.get("reason") or "").strip()
        for item in rows
        if str(item.get("reason") or "").strip()
    )
    status = str(payload.get("status") or "").strip() or (
        "available" if rows else "missing"
    )
    if "not_applicable_inland_route" in event_names:
        status = "not_applicable"
    return {
        "status": status,
        "applicable": status.casefold() not in {"not_applicable", "missing"}
        and "not_applicable_inland_route" not in event_names,
        "events": event_names,
        "reasons": reasons,
        "dataset_ids": _dataset_ids(payload),
    }


def _weather_dataset_summary(payload: dict[str, Any]) -> list[dict[str, str]]:
    raw = payload.get("datasets")
    rows = raw if isinstance(raw, list) else []
    summary: list[dict[str, str]] = []
    for row in rows:
        if isinstance(row, str) and row.strip():
            summary.append({"dataset_id": row.strip(), "status": "unknown"})
            continue
        if not isinstance(row, dict):
            continue
        dataset_id = str(
            row.get("dataset_id") or row.get("source_dataset_id") or ""
        ).strip()
        if dataset_id:
            summary.append(
                {
                    "dataset_id": dataset_id,
                    "status": str(row.get("status") or "unknown"),
                }
            )
    if summary:
        return summary
    return [
        {"dataset_id": dataset_id, "status": "unknown"}
        for dataset_id in _dataset_ids(payload)
    ]


def _imagery_manifest_summary(payload: dict[str, Any]) -> dict[str, Any]:
    frames = payload.get("frames")
    rows = frames if isinstance(frames, list) else []
    return {
        "available": bool(payload),
        "prepared_frame_count": len(rows),
        "latest_frame_id": payload.get("latestFrameId")
        or payload.get("latest_frame_id"),
    }


def _compact_qpf_summary(
    payload: dict[str, Any],
    *,
    qpf_grid: dict[str, Any],
    qpf_timeline: dict[str, Any],
    stale_after_hours: float,
    reference_time: datetime,
) -> dict[str, Any]:
    if not payload and not qpf_grid and not qpf_timeline:
        return {}
    summary = payload.get("qpf_corridor_summary")
    if isinstance(summary, dict):
        payload = {**payload, **summary}
    keys = (
        "max_mm",
        "mean_mm",
        "p95_mm",
        "peak_window",
        "heavy_rain_event_count",
        "update_policy",
        "qpf_update_cadence",
        "qpf_lead_time",
        "qpf_accumulation",
        "uncertainty_policy",
        "qpf_uncertainty",
        "severe_weather_intensified_operation",
        "api_fetched_at_hour",
        "fetched_at_hour",
        "forecast_valid_from_hour",
        "forecast_valid_until_hour",
        "latest_observation_at_hour",
        "valid_from_hour",
        "valid_until_hour",
        "time_precision",
    )
    compact = {key: payload[key] for key in keys if key in payload}
    direct_values = _direct_qpf_values(qpf_grid)
    datasets = _dedupe_text(
        [
            *_dataset_ids(payload),
            *_qpf_feature_dataset_ids(qpf_grid),
            *_qpf_timeline_dataset_ids(qpf_timeline),
        ]
    )
    direct_available = any(
        str(dataset).startswith("F-C0041-") for dataset in datasets
    ) or any(
        _float_or_none(payload.get(key)) is not None
        for key in ("max_mm", "mean_mm", "p95_mm")
    )
    direct_available = direct_available or bool(direct_values)
    compact.update(
        {
            "direct_qpf_available": direct_available,
            "max_mm": _float_or_none(payload.get("max_mm")),
            "mean_mm": _float_or_none(payload.get("mean_mm")),
            "p95_mm": _float_or_none(payload.get("p95_mm")),
            "peak_window": payload.get("peak_window"),
            "datasets": datasets,
        }
    )
    if direct_values:
        compact["max_mm"] = compact["max_mm"] or max(direct_values)
        compact["mean_mm"] = compact["mean_mm"] or round(
            sum(direct_values) / len(direct_values), 3
        )
        compact["p95_mm"] = compact["p95_mm"] or _percentile(
            direct_values, 0.95
        )
        compact["peak_window"] = compact["peak_window"] or _direct_qpf_peak_window(
            qpf_grid
        )
    probability_peak = _forecast_probability_peak(qpf_grid, qpf_timeline)
    compact.update(probability_peak)
    issued_at = _first_text(
        payload,
        "issued_at",
        "issue_time",
        "product_issued_at",
        "source_timestamp",
    )
    fetched_at = _first_text(
        payload,
        "api_fetched_at",
        "fetched_at",
        "request_timestamp",
    )
    valid_from = _first_text(
        payload,
        "forecast_valid_from",
        "valid_from",
        "forecast_valid_from_hour",
        "valid_from_hour",
    )
    valid_to = _first_text(
        payload,
        "forecast_valid_until",
        "valid_until",
        "valid_to",
        "forecast_valid_until_hour",
        "valid_until_hour",
        "valid_to_hour",
    )
    stale_risk, age_hours = _artifact_stale_status(
        payload,
        fallback_timestamp=fetched_at,
        stale_after_hours=stale_after_hours,
        reference_time=reference_time,
    )
    compact.update(
        {
            "issued_at": issued_at,
            "api_fetched_at": fetched_at,
            "valid_from": valid_from,
            "valid_to": valid_to,
            "stale_risk": stale_risk,
            "age_hours": age_hours,
        }
    )
    return compact


def _load_route_points(
    root: Path, project: dict[str, Any]
) -> tuple[list[tuple[float, float]], str | None]:
    refs = _candidate_paths(
        root,
        project,
        explicit_path=None,
        ref_keys=("segment_display_geometry_ref",),
        fallbacks=("outputs/segment_display_geometry.json",),
    )
    for ref in refs:
        payload = _load_json_object(_resolve_project_path(root, ref))
        segments = payload.get("segments")
        if not isinstance(segments, list):
            continue
        points: list[tuple[float, float]] = []
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            coordinates = segment.get("coordinates")
            if not isinstance(coordinates, list):
                continue
            for coordinate in coordinates:
                if not isinstance(coordinate, dict):
                    continue
                lat = _float_or_none(coordinate.get("lat"))
                lon = _float_or_none(coordinate.get("lon"))
                if lat is not None and lon is not None:
                    points.append((lat, lon))
        if points:
            return points, ref
    return [], None


def _observation_summary(
    payload: dict[str, Any],
    *,
    route_points: list[tuple[float, float]],
    route_geometry_ref: str | None,
) -> dict[str, Any]:
    if not payload:
        return {}
    time_metadata = payload.get("cwa_time_metadata")
    latest = _first_text(payload, "latest_observation_at", "latest_observation_at_hour")
    if latest is None and isinstance(time_metadata, dict):
        latest = _first_text(
            time_metadata, "latest_observation_at", "latest_observation_at_hour"
        )
    nearest: dict[str, Any] | None = None
    observed_times: list[tuple[datetime, str]] = []
    features = payload.get("features")
    if isinstance(features, list):
        for feature in features:
            if not isinstance(feature, dict):
                continue
            properties = feature.get("properties")
            geometry = feature.get("geometry")
            if not isinstance(properties, dict) or not isinstance(geometry, dict):
                continue
            observed_at = _first_text(
                properties, "obs_time", "observed_at", "observation_time"
            )
            parsed = _parse_datetime(observed_at) if observed_at else None
            if parsed is not None and observed_at is not None:
                observed_times.append((parsed, observed_at))
            coordinates = geometry.get("coordinates")
            if not route_points or not isinstance(coordinates, list) or len(coordinates) < 2:
                continue
            lon = _float_or_none(coordinates[0])
            lat = _float_or_none(coordinates[1])
            if lat is None or lon is None:
                continue
            distance_m = min(
                _haversine_m(lat, lon, route_lat, route_lon)
                for route_lat, route_lon in route_points
            )
            if nearest is not None and distance_m >= nearest["distance_to_route_m"]:
                continue
            nearest = {
                "station_name": _first_text(
                    properties, "station_name", "station", "location_name", "label"
                )
                or "unknown",
                "station_id": _first_text(properties, "station_id", "stationId"),
                "observation_at": observed_at,
                "lat": lat,
                "lon": lon,
                "distance_to_route_m": round(distance_m, 1),
            }
    if latest is None and observed_times:
        latest = max(observed_times, key=lambda item: item[0])[1]
    return {
        "latest_observation_at": latest,
        "nearest_route_station": nearest,
        "route_geometry_ref": route_geometry_ref,
    }


def _haversine_m(
    lat_a: float, lon_a: float, lat_b: float, lon_b: float
) -> float:
    lat1, lat2 = math.radians(lat_a), math.radians(lat_b)
    dlat = lat2 - lat1
    dlon = math.radians(lon_b - lon_a)
    value = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    return 6_371_000.0 * 2 * math.asin(min(1.0, math.sqrt(value)))


def _direct_qpf_values(payload: dict[str, Any]) -> list[float]:
    values: list[float] = []
    features = payload.get("features")
    if not isinstance(features, list):
        return values
    for feature in features:
        if not isinstance(feature, dict):
            continue
        properties = feature.get("properties")
        if not isinstance(properties, dict):
            continue
        source = str(properties.get("source") or properties.get("dataset_id") or "")
        is_direct = properties.get("qpf_direct_grid") is True or source.startswith(
            "F-C0041-"
        )
        value = _float_or_none(properties.get("qpf_mm"))
        if value is None and is_direct:
            value = _float_or_none(properties.get("rainfall_mm"))
        if is_direct and value is not None:
            values.append(value)
    return values


def _direct_qpf_peak_window(payload: dict[str, Any]) -> str | None:
    best: tuple[float, str] | None = None
    features = payload.get("features")
    if not isinstance(features, list):
        return None
    for feature in features:
        if not isinstance(feature, dict):
            continue
        properties = feature.get("properties")
        if not isinstance(properties, dict):
            continue
        value = _float_or_none(properties.get("qpf_mm"))
        if value is None:
            continue
        valid_from = _first_text(properties, "valid_from", "valid_time")
        valid_to = _first_text(properties, "valid_to", "valid_until")
        window = _time_window(valid_from, valid_to)
        if window and (best is None or value > best[0]):
            best = (value, window)
    return best[1] if best else None


def _forecast_probability_peak(
    qpf_grid: dict[str, Any], qpf_timeline: dict[str, Any]
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    features = qpf_grid.get("features")
    if isinstance(features, list):
        rows.extend(
            feature.get("properties", {})
            for feature in features
            if isinstance(feature, dict)
            and isinstance(feature.get("properties"), dict)
        )
    for key in ("events", "timeline", "items", "records"):
        values = qpf_timeline.get(key)
        if isinstance(values, list):
            rows.extend(item for item in values if isinstance(item, dict))
            break
    best: tuple[float, str | None] | None = None
    for row in rows:
        probability = _float_or_none(row.get("rain_probability"))
        if probability is None:
            continue
        window = _time_window(
            _first_text(row, "valid_from", "valid_time"),
            _first_text(row, "valid_to", "valid_until"),
        )
        if best is None or probability > best[0]:
            best = (probability, window)
    return {
        "forecast_derived_peak_probability_pct": best[0] if best else None,
        "forecast_derived_peak_window": best[1] if best else None,
    }


def _qpf_feature_dataset_ids(payload: dict[str, Any]) -> list[str]:
    values: list[str] = []
    features = payload.get("features")
    if isinstance(features, list):
        for feature in features:
            if not isinstance(feature, dict):
                continue
            properties = feature.get("properties")
            if not isinstance(properties, dict):
                continue
            for key in ("dataset_id", "source", "source_dataset_id"):
                value = properties.get(key)
                if isinstance(value, str) and value.strip():
                    values.append(value.strip())
    return _dedupe_text(values)


def _qpf_timeline_dataset_ids(payload: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("events", "timeline", "items", "records"):
        rows = payload.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            for dataset_key in ("dataset_id", "source", "source_dataset_id"):
                value = row.get(dataset_key)
                if isinstance(value, str) and value.strip():
                    values.append(value.strip())
        break
    return _dedupe_text(values)


def _artifact_stale_status(
    payload: dict[str, Any],
    *,
    fallback_timestamp: str | None,
    stale_after_hours: float,
    reference_time: datetime,
) -> tuple[str, float | None]:
    timestamp = _request_timestamp(payload) or fallback_timestamp
    parsed = _parse_datetime(timestamp) if timestamp else None
    age_hours = (
        round((reference_time - parsed).total_seconds() / 3600, 1)
        if parsed is not None
        else None
    )
    explicit = _stale_risk(payload)
    if age_hours is not None and age_hours > stale_after_hours:
        return "stale", age_hours
    if explicit:
        return explicit, age_hours
    return ("fresh" if age_hours is not None else "unknown"), age_hours


def _first_text(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    metadata = payload.get("cwa_time_metadata")
    if isinstance(metadata, dict):
        for key in keys:
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _time_window(valid_from: str | None, valid_to: str | None) -> str | None:
    if valid_from and valid_to:
        return f"{valid_from}/{valid_to}"
    return valid_from or valid_to


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return round(
        ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction, 3
    )


def _feature_count(payload: dict[str, Any]) -> int:
    features = payload.get("features")
    if isinstance(features, list):
        return len(features)
    items = payload.get("items")
    if isinstance(items, list):
        return len(items)
    return 1 if payload else 0


def _event_count(payload: dict[str, Any]) -> int:
    for key in ("events", "timeline", "items", "records"):
        value = payload.get(key)
        if isinstance(value, list):
            return len(value)
    return 1 if payload else 0


def _dataset_ids(payload: dict[str, Any]) -> list[str]:
    values: list[Any] = []
    for key in ("dataset_id", "source_dataset_id", "source_dataset"):
        if payload.get(key):
            values.append(payload[key])
    for key in ("dataset_ids", "source_dataset_ids", "source_datasets"):
        raw = payload.get(key)
        if isinstance(raw, list):
            values.extend(raw)
    source_report = payload.get("source_report")
    if isinstance(source_report, list):
        for item in source_report:
            if not isinstance(item, dict):
                continue
            values.extend(_dataset_ids(item))
    datasets = payload.get("datasets")
    if isinstance(datasets, list):
        for item in datasets:
            if isinstance(item, str):
                values.append(item)
            elif isinstance(item, dict):
                values.extend(_dataset_ids(item))
    return _dedupe_text(str(value) for value in values if str(value).strip())


def _source_refs(payload: dict[str, Any]) -> list[str]:
    values: list[Any] = []
    for key in ("source_ref", "source_path", "normalized_artifact_ref"):
        if payload.get(key):
            values.append(payload[key])
    raw_refs = payload.get("source_refs")
    if isinstance(raw_refs, list):
        values.extend(raw_refs)
    return _dedupe_text(str(value) for value in values if str(value).strip())


def _raw_hash(payload: dict[str, Any]) -> str | None:
    for key in ("raw_response_hash", "raw_payload_hash", "sha256", "source_sha256"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _stale_risk(payload: dict[str, Any]) -> str | None:
    for key in ("stale_risk", "staleness_risk", "freshness_status"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _request_timestamp(payload: dict[str, Any]) -> str | None:
    for key in ("request_timestamp", "requested_at", "generated_at", "updated_at"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _missing_fields(source_report: list[dict[str, Any]]) -> list[str]:
    return [
        str(item["source_kind"])
        for item in source_report
        if item.get("status") in {"missing", "error"}
    ]


def _stale_risks(
    source_report: list[dict[str, Any]],
    *,
    stale_after_hours: float,
    reference_time: datetime,
) -> list[str]:
    risks: list[str] = []
    for item in source_report:
        if item.get("stale_risk") and str(item["stale_risk"]).lower() not in {
            "low",
            "fresh",
            "none",
        }:
            risks.append(f"{item['source_kind']} stale_risk={item['stale_risk']}")
        timestamp = item.get("request_timestamp")
        if not isinstance(timestamp, str):
            continue
        parsed = _parse_datetime(timestamp)
        if parsed is None:
            continue
        age_hours = (reference_time - parsed).total_seconds() / 3600
        if age_hours > stale_after_hours:
            risks.append(
                f"{item['source_kind']} age_hours={age_hours:.1f}>{stale_after_hours:g}"
            )
    return _dedupe_text(risks)


def _reference_datetime(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    parsed = _parse_datetime(value)
    if parsed is None:
        raise ValueError("reference_time must be an ISO-8601 timestamp")
    return parsed.astimezone(timezone.utc)


def _parse_datetime(value: str) -> datetime | None:
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _warnings(
    *,
    missing_fields: list[str],
    stale_risks: list[str],
) -> list[str]:
    warnings: list[str] = []
    if missing_fields:
        warnings.append(
            "CWA environment evidence is incomplete; do not infer low weather risk."
        )
    if "cwa_qpf_corridor_summary" in missing_fields:
        warnings.append(
            "CWA QPF corridor summary is missing; route rain review has an evidence gap."
        )
    warnings.extend(stale_risks)
    return _dedupe_text(warnings)


def _decision_output(
    *,
    summary: dict[str, Any],
    missing_fields: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    qpf = summary.get("qpf_corridor_summary")
    qpf_max = _float_or_none(qpf.get("max_mm")) if isinstance(qpf, dict) else None
    heavy_events = (
        _int_or_default(qpf.get("heavy_rain_event_count"), default=0)
        if isinstance(qpf, dict)
        else 0
    )
    active_warning = summary.get("warning_count", 0) > 0
    if missing_fields:
        decision = "DELAY"
        reason = "CWA environment evidence is incomplete."
        next_step = "重新產生或補齊 CWA environment artifacts 後再做 go/no-go review。"
    elif active_warning or heavy_events or (qpf_max is not None and qpf_max >= 30):
        decision = "CHANGE_PLAN"
        reason = "CWA warning/QPF evidence indicates elevated weather review pressure."
        next_step = "把 QPF、警特報、terrain/geology/recent-rain compound evidence 交給人工複核。"
    else:
        decision = "REVIEW"
        reason = "CWA evidence is available; continue candidate-only pretrip review."
        next_step = "與 terrain、geology、SMAP/GPM、route notes 合併檢查。"
    field_answer = (
        f"CWA workspace evidence: warnings={summary['warning_count']}, "
        f"observations={summary['observation_count']}, "
        f"qpf_grid_features={summary['qpf_grid_feature_count']}, "
        f"qpf_timeline_events={summary['qpf_route_timeline_event_count']}."
    )
    return {
        "decisionObjectSchema": "ContextualPermission",
        "answerSourceToolId": CWA_ENVIRONMENT_TOOL_ID,
        "action": "review_cwa_environment_evidence",
        "decision": decision,
        "allowed": False,
        "field_answer": field_answer,
        "main_reasons": [reason, *warnings[:2]],
        "next_action": next_step,
        "firstLayer": {
            "decision": "暫緩現場授權，作為行前候選證據檢查。",
            "limit": "CWA/QPF 只能作 route corridor/bbox 層級的 candidate evidence，不可當 runtime safety truth。",
            "reason": reason,
            "nextStep": next_step,
        },
        "secondLayer": {
            "details": [field_answer],
            "uncertaintyNotes": [
                "QPF 不可解讀成單一坡面精準預報。",
                "台灣高山地形雨與短時對流會放大不確定性。",
                *warnings,
            ],
            "residualRisk": [
                "CWA-derived evidence requires human review before route decision use."
            ],
            "requiredConditions": [
                "candidate_only=true",
                "runtime_safety_truth=false",
                "human_review_required=true",
            ],
            "alternativeActions": [
                "Refresh CWA artifacts through pretrip preparation.",
                "Compare with GEE SMAP/GPM and terrain/geology evidence.",
            ],
        },
        "runtimeSafetyTruth": False,
    }


def _field_answer(
    decision_output: dict[str, Any],
    summary: dict[str, Any],
    *,
    query: str,
) -> str:
    normalized_query = query.casefold()
    qpf = summary.get("qpf_corridor_summary")
    observation = summary.get("observation_summary")
    warning = summary.get("warning_summary")
    forecast = summary.get("forecast_summary")
    astronomy = summary.get("astronomy_summary")
    tide = summary.get("tide_marine_summary")
    datasets = summary.get("weather_dataset_summary")
    imagery = summary.get("imagery_summary")
    if _is_warning_layer_query(normalized_query) and isinstance(warning, dict):
        areas = warning.get("affected_areas")
        area_text = "、".join(map(str, areas)) if isinstance(areas, list) and areas else "none"
        return (
            f"CWA warning layer feature_count={warning.get('feature_count', 0)}; "
            f"affected_areas={area_text}."
        )
    if _is_forecast_timeline_query(normalized_query) and isinstance(forecast, dict):
        areas = forecast.get("areas")
        area_text = "、".join(map(str, areas)) if isinstance(areas, list) and areas else "none"
        return (
            f"CWA forecast timeline 涵蓋區域：{area_text}；"
            f"時間窗：{forecast.get('valid_from') or 'unavailable'} 至 "
            f"{forecast.get('valid_to') or 'unavailable'}。"
        )
    if _is_qpf_intensified_query(normalized_query) and isinstance(qpf, dict):
        intensified = qpf.get("severe_weather_intensified_operation")
        datasets_text = ",".join(map(str, qpf.get("datasets") or [])) or "none"
        if intensified is True:
            return (
                "severe_weather_intensified_operation=true; this is a severe-weather "
                f"intensified QPF product; datasets={datasets_text}; "
                f"update_cadence={qpf.get('qpf_update_cadence') or qpf.get('update_policy') or 'unavailable'}."
            )
        return (
            "severe_weather_intensified_operation="
            f"{str(intensified).lower() if isinstance(intensified, bool) else 'unavailable'}; "
            "the prepared evidence does not establish a 3-hour intensified QPF operation; "
            f"datasets={datasets_text}; direct_qpf_available="
            f"{str(bool(qpf.get('direct_qpf_available'))).lower()}."
        )
    if _is_astronomy_query(normalized_query) and isinstance(astronomy, dict):
        answer = (
            f"astronomy timeline 狀態為 {astronomy.get('status') or 'missing'}；"
            f"日落時間為 {astronomy.get('sunset') or 'unavailable'}；"
            f"民用暮光時間為 {astronomy.get('civil_twilight') or 'unavailable'}；"
            f"practical darkness 時間為 "
            f"{astronomy.get('practical_darkness') or 'unavailable'}。"
        )
        if astronomy.get("reason"):
            if str(astronomy.get("status") or "").casefold() == "not_available":
                answer += " 原因：目前 CWA astronomy adapter 尚未配置。"
            else:
                answer += f" 原因：{str(astronomy['reason']).rstrip('.')}。"
        return answer
    if _is_tide_marine_query(normalized_query) and isinstance(tide, dict):
        reasons = "; ".join(map(str, tide.get("reasons") or [])) or "unavailable"
        return (
            "tide/marine timeline 對目前山區路線標示為"
            f"{'適用' if tide.get('applicable') else '不適用'}；"
            f"狀態為 {tide.get('status') or 'missing'}；"
            f"理由：{reasons.rstrip('.')}。"
        )
    if _is_dataset_id_query(normalized_query) and isinstance(datasets, list):
        rows = [
            f"{item.get('dataset_id')}={item.get('status')}"
            for item in datasets
            if isinstance(item, dict) and item.get("dataset_id")
        ]
        return f"CWA weather evidence datasets: {', '.join(rows) if rows else 'none'}."
    if _is_imagery_manifest_query(normalized_query) and isinstance(imagery, dict):
        radar = imagery.get("radar") if isinstance(imagery.get("radar"), dict) else {}
        satellite = (
            imagery.get("satellite")
            if isinstance(imagery.get("satellite"), dict)
            else {}
        )
        return (
            f"CWA radar prepared_frames={radar.get('prepared_frame_count', 0)}, "
            f"latest_frame_id={radar.get('latest_frame_id') or 'unavailable'}; "
            f"satellite prepared_frames={satellite.get('prepared_frame_count', 0)}, "
            f"latest_frame_id={satellite.get('latest_frame_id') or 'unavailable'}."
        )
    if _is_qpf_freshness_query(normalized_query) and isinstance(qpf, dict):
        return _qpf_freshness_answer(qpf)
    if _is_qpf_metric_query(normalized_query) and isinstance(qpf, dict):
        return _qpf_metric_answer(qpf)
    if _is_observation_query(normalized_query) and isinstance(observation, dict):
        return _observation_answer(observation)

    text = str(decision_output.get("field_answer") or "").strip()
    if isinstance(observation, dict) and observation:
        latest = observation.get("latest_observation_at") or "unavailable"
        nearest = observation.get("nearest_route_station")
        text += f" Latest observation={latest}."
        if isinstance(nearest, dict):
            text += (
                f" Nearest route station={nearest.get('station_name', 'unknown')} "
                f"at {nearest.get('distance_to_route_m', 'unknown')}m from route; "
                f"station observation={nearest.get('observation_at') or 'unavailable'}."
            )
        else:
            text += " Nearest route station=unavailable."
    if isinstance(qpf, dict) and qpf:
        if qpf.get("direct_qpf_available"):
            text += (
                f" QPF max={qpf.get('max_mm')}mm, mean={qpf.get('mean_mm')}mm, "
                f"p95={qpf.get('p95_mm')}mm, "
                f"peak_window={qpf.get('peak_window') or 'unavailable'}."
            )
        else:
            text += (
                " Direct QPF accumulation unavailable: max/mean/p95/peak_window "
                "cannot be derived from the prepared evidence."
            )
        probability = qpf.get("forecast_derived_peak_probability_pct")
        if probability is not None:
            text += (
                f" Forecast-derived rain probability peak={probability}% at "
                f"{qpf.get('forecast_derived_peak_window') or 'unavailable'}; "
                "this is not direct QPF millimetres."
            )
        text += (
            f" QPF issued_at={qpf.get('issued_at') or 'unavailable'}, "
            f"api_fetched_at={qpf.get('api_fetched_at') or 'unavailable'}, "
            f"valid={qpf.get('valid_from') or 'unavailable'}/"
            f"{qpf.get('valid_to') or 'unavailable'}, "
            f"stale_risk={qpf.get('stale_risk') or 'unknown'}"
            + (
                f" (age_hours={qpf['age_hours']})"
                if qpf.get("age_hours") is not None
                else ""
            )
            + "."
        )
    datasets = ", ".join(summary.get("datasets") or [])
    if datasets:
        text += f" Datasets: {datasets}."
    return text


def _field_answer_source_ref(query: str) -> str:
    normalized_query = query.casefold()
    if _is_warning_layer_query(normalized_query):
        return "outputs/environment/cwa/warnings.geojson"
    if _is_observation_query(normalized_query):
        return "outputs/environment/cwa/observations.geojson"
    if _is_forecast_timeline_query(normalized_query):
        return "outputs/environment/cwa/forecast_timeline.json"
    if _is_astronomy_query(normalized_query):
        return "outputs/environment/cwa/astronomy_timeline.json"
    if _is_tide_marine_query(normalized_query):
        return "outputs/environment/cwa/tide_marine_timeline.json"
    if _is_dataset_id_query(normalized_query):
        return "outputs/environment/cwa/cwa_weather_evidence.json"
    if _is_imagery_manifest_query(normalized_query):
        return "outputs/environment/cwa/imagery/radar_frames_manifest.json"
    if "qpf" in normalized_query:
        return "outputs/environment/cwa/qpf_corridor_summary.json"
    return "outputs/environment/environment_evidence_package.json"


def _field_answer_source_refs(query: str) -> list[str]:
    primary = _field_answer_source_ref(query)
    if _is_imagery_manifest_query(query.casefold()):
        return [
            primary,
            "outputs/environment/cwa/imagery/satellite_frames_manifest.json",
        ]
    return [primary]


def _is_warning_layer_query(query: str) -> bool:
    return "warning" in query or "警特報" in query or "警報 layer" in query


def _is_forecast_timeline_query(query: str) -> bool:
    return "forecast timeline" in query or (
        "預報" in query and any(token in query for token in ("鄉鎮", "時間窗", "timeline"))
    )


def _is_qpf_intensified_query(query: str) -> bool:
    return "qpf" in query and any(
        token in query for token in ("劇烈天氣", "3 小時", "3小時", "intensified")
    )


def _is_astronomy_query(query: str) -> bool:
    return any(token in query for token in ("astronomy", "日落", "暮光", "darkness"))


def _is_tide_marine_query(query: str) -> bool:
    return any(token in query for token in ("tide", "marine", "潮汐", "海象"))


def _is_dataset_id_query(query: str) -> bool:
    return "dataset" in query and "cwa" in query


def _is_imagery_manifest_query(query: str) -> bool:
    return any(token in query for token in ("radar", "satellite", "雷達", "衛星")) and any(
        token in query for token in ("manifest", "frame", "影像")
    )


def _is_observation_query(query: str) -> bool:
    return any(token in query for token in ("observation", "觀測", "測站"))


def _is_qpf_metric_query(query: str) -> bool:
    return "qpf" in query and any(
        token in query
        for token in ("max", "mean", "p95", "peak", "corridor summary", "毫米")
    )


def _is_qpf_freshness_query(query: str) -> bool:
    return "qpf" in query and any(
        token in query
        for token in (
            "issued",
            "valid time",
            "stale",
            "發佈時間",
            "發布時間",
            "有效時間",
            "時效",
            "過期",
        )
    )


def _is_exact_cwa_query(query: str) -> bool:
    normalized = query.casefold()
    return any(
        predicate(normalized)
        for predicate in (
            _is_warning_layer_query,
            _is_forecast_timeline_query,
            _is_qpf_intensified_query,
            _is_astronomy_query,
            _is_tide_marine_query,
            _is_dataset_id_query,
            _is_imagery_manifest_query,
            _is_observation_query,
            _is_qpf_metric_query,
            _is_qpf_freshness_query,
        )
    )


def _observation_answer(observation: dict[str, Any]) -> str:
    latest = observation.get("latest_observation_at") or "unavailable"
    nearest = observation.get("nearest_route_station")
    if not isinstance(nearest, dict):
        return f"CWA 最新觀測時間為 {latest}；最近路線測站資料 unavailable。"
    return (
        f"CWA 最新觀測時間為 {latest}；最近路線測站為 "
        f"{nearest.get('station_name') or 'unknown'}，距離路線 "
        f"{nearest.get('distance_to_route_m')} m，該站觀測時間為 "
        f"{nearest.get('observation_at') or 'unavailable'}。"
    )


def _qpf_metric_answer(qpf: dict[str, Any]) -> str:
    if qpf.get("direct_qpf_available"):
        return (
            f"Direct QPF corridor summary：max 為 {qpf.get('max_mm')} mm、"
            f"mean 為 {qpf.get('mean_mm')} mm、p95 為 {qpf.get('p95_mm')} mm、"
            f"peak window 為 {qpf.get('peak_window') or 'unavailable'}。"
        )
    return (
        "Direct QPF accumulation unavailable：max、mean、p95 與 peak window "
        "皆為 None，不可估算。現有 forecast-derived rain probability "
        "不是 direct QPF millimetres。"
    )


def _qpf_freshness_answer(qpf: dict[str, Any]) -> str:
    age_text = (
        f"，evidence age 為 {qpf['age_hours']} 小時"
        if qpf.get("age_hours") is not None
        else ""
    )
    return (
        f"QPF issued time 為 {qpf.get('issued_at') or 'unavailable'} "
        "(do not substitute observation time or API fetch time); "
        f"API fetched time 為 {qpf.get('api_fetched_at') or 'unavailable'}；"
        f"valid time 為 {qpf.get('valid_from') or 'unavailable'} 至 "
        f"{qpf.get('valid_to') or 'unavailable'}；stale risk 為 "
        f"{qpf.get('stale_risk') or 'unknown'}{age_text}。"
    )


def _results(
    artifacts: dict[str, dict[str, Any]],
    *,
    include_features: bool,
    include_timeline: bool,
    limit: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if include_features:
        rows.extend(_feature_rows("warnings", artifacts["warnings"], limit=limit))
        rows.extend(_feature_rows("observations", artifacts["observations"], limit=limit))
        rows.extend(_feature_rows("qpf_grid", artifacts["qpf_grid"], limit=limit))
    if include_timeline:
        rows.extend(_timeline_rows("qpf_route_timeline", artifacts["qpf_route_timeline"], limit=limit))
        rows.extend(_timeline_rows("forecast_timeline", artifacts["forecast_timeline"], limit=limit))
        rows.extend(_timeline_rows("astronomy_timeline", artifacts["astronomy_timeline"], limit=limit))
        rows.extend(_timeline_rows("tide_marine_timeline", artifacts["tide_marine_timeline"], limit=limit))
    return rows[:limit]


def _feature_rows(kind: str, payload: dict[str, Any], *, limit: int) -> list[dict[str, Any]]:
    features = payload.get("features")
    if not isinstance(features, list):
        return []
    rows = []
    for feature in features[:limit]:
        if not isinstance(feature, dict):
            continue
        properties = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
        geometry = feature.get("geometry") if isinstance(feature.get("geometry"), dict) else {}
        rows.append(
            {
                "result_kind": kind,
                "label": properties.get("name") or properties.get("label") or properties.get("station") or properties.get("event") or kind,
                "properties": _compact_dict(properties, max_keys=8),
                "geometry_type": geometry.get("type"),
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        )
    return rows


def _timeline_rows(kind: str, payload: dict[str, Any], *, limit: int) -> list[dict[str, Any]]:
    events: list[Any] = []
    for key in ("events", "timeline", "items", "records"):
        value = payload.get(key)
        if isinstance(value, list):
            events = value
            break
    rows = []
    for event in events[:limit]:
        if not isinstance(event, dict):
            continue
        rows.append(
            {
                "result_kind": kind,
                "label": event.get("label") or event.get("event") or event.get("type") or kind,
                "time": event.get("time") or event.get("valid_time") or event.get("valid_from"),
                "properties": _compact_dict(event, max_keys=8),
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        )
    return rows


def _compact_dict(value: dict[str, Any], *, max_keys: int) -> dict[str, Any]:
    return {key: value[key] for key in list(value)[:max_keys]}


def _provenance_summary(source_report: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "loaded_sources": [
            item["source_kind"] for item in source_report if item.get("status") == "loaded"
        ],
        "missing_or_error_sources": [
            item["source_kind"]
            for item in source_report
            if item.get("status") in {"missing", "error"}
        ],
        "raw_response_hashes": [
            item["raw_response_hash"]
            for item in source_report
            if item.get("raw_response_hash")
        ],
        "dataset_ids": sorted(
            {
                dataset
                for item in source_report
                for dataset in item.get("dataset_ids", [])
                if str(dataset).strip()
            }
        ),
        "candidate_only": True,
        "runtime_safety_truth": False,
        "human_review_required": True,
    }


def _source_status(available_artifact_count: int) -> str:
    if available_artifact_count == 0:
        return "missing"
    if available_artifact_count < 5:
        return "partial"
    return "candidate_only"


def _bounded_limit(value: int) -> int:
    return max(1, min(MAX_RESULT_LIMIT, int(value or DEFAULT_RESULT_LIMIT)))


def _bool_value(value: bool | str | None, *, default: bool) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def _float_or_default(value: float | int | str | None, *, default: float) -> float:
    parsed = _float_or_none(value)
    return default if parsed is None else parsed


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_default(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _dedupe_text(values: list[str] | Any) -> list[str]:
    seen = set()
    result = []
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
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
    }
