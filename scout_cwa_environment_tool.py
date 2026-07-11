from __future__ import annotations

import json
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
    cwa_summary = _cwa_summary(artifacts)
    decision_output = _decision_output(
        summary=cwa_summary,
        missing_fields=effective_missing_fields,
        warnings=warnings_list,
    )
    field_answer = _field_answer(decision_output, cwa_summary)
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
        "assessment_kind": "read_only_cwa_environment_workspace",
        "answerability": answerability,
        "source_status": _source_status(cwa_summary["available_artifact_count"]),
        "decision": decision_output["decision"],
        "decision_output": decision_output,
        "field_answer": field_answer,
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


def _cwa_summary(artifacts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    qpf_summary = _compact_qpf_summary(artifacts["qpf_corridor_summary"])
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
        "environment_factor_matrix_keys": sorted(artifacts["factor_matrix"].keys())[:12],
        "go_no_go_review_available": bool(artifacts["go_no_go_review"]),
        "candidate_only": True,
        "runtime_safety_truth": False,
        "human_review_required": True,
    }


def _compact_qpf_summary(payload: dict[str, Any]) -> dict[str, Any]:
    if not payload:
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
    if "datasets" not in compact:
        compact["datasets"] = _dataset_ids(payload)
    return compact


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
    if isinstance(qpf, dict) and qpf:
        field_answer += (
            f" QPF max={qpf.get('max_mm', 'n/a')}mm, "
            f"p95={qpf.get('p95_mm', 'n/a')}mm, "
            f"peak_window={qpf.get('peak_window', 'n/a')}."
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


def _field_answer(decision_output: dict[str, Any], summary: dict[str, Any]) -> str:
    text = str(decision_output.get("field_answer") or "").strip()
    datasets = ", ".join(summary.get("datasets") or [])
    if datasets:
        text += f" Datasets: {datasets}."
    return text


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
