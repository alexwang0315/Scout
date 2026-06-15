from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scout_weather_integration import build_route_weather_package, write_route_weather_package
from scout_weather_window_tool import assess_scout_weather_window


WEATHER_DECISION_COLLECTION_ARTIFACT_KIND = "pretrip_weather_decision_collection"
WEATHER_SOURCE_MANIFEST_ARTIFACT_KIND = "pretrip_weather_source_manifest"
WEATHER_DECISION_CANDIDATES_ARTIFACT_KIND = "pretrip_weather_decision_candidates"
WEATHER_DECISION_SCHEMA_VERSION = "weather_decision_collection.v1"

WEATHER_SOURCE_MANIFEST_REF = "normalized/weather/weather_source_manifest.json"
WEATHER_DECISION_CANDIDATES_REF = "candidates/weather_decision_candidates.json"
ROUTE_WEATHER_PACKAGE_REF = "outputs/route_weather_package.json"


def collect_pretrip_weather_decision(
    project_root: Path | str,
    *,
    dry_run: bool = False,
    weather_points_path: str | None = None,
    warnings_path: str | None = None,
    route_segments_path: str | None = None,
    default_township: str | None = None,
    generated_at: str | None = None,
    valid_until: str | None = None,
    provider: str = "workspace_local_weather_points",
) -> dict[str, Any]:
    root = Path(project_root)
    project_path = root / "project.json"
    project = _load_json_object(project_path)
    project_id = str(project.get("project_id") or project.get("id") or root.name)
    collected_at = generated_at or _utc_now()

    weather_points, weather_point_report = _load_weather_points(
        root,
        project,
        explicit_path=weather_points_path,
    )
    warnings, warning_report = _load_warning_records(
        root,
        project,
        explicit_path=warnings_path,
    )
    route_segments, route_segment_report = _load_route_segments(
        root,
        project,
        explicit_path=route_segments_path,
        default_township=default_township,
    )

    route_weather_package_ref = str(
        project.get("route_weather_package_ref") or ROUTE_WEATHER_PACKAGE_REF
    )
    source_manifest_ref = str(
        project.get("weather_source_manifest_ref") or WEATHER_SOURCE_MANIFEST_REF
    )
    candidates_ref = str(
        project.get("weather_decision_candidates_ref")
        or WEATHER_DECISION_CANDIDATES_REF
    )
    weather_daylight_ref = str(
        project.get("weather_daylight_evidence_ref")
        or "outputs/weather_daylight_evidence.json"
    )
    planned_refs = [source_manifest_ref, candidates_ref]

    route_weather_package: dict[str, Any] | None = None
    if weather_points and route_segments:
        route_weather_package = build_route_weather_package(
            route_id=project_id,
            route_segments=route_segments,
            weather_points=weather_points,
            warnings=warnings,
            generated_at=collected_at,
            valid_until=valid_until,
            provider=provider,
            source_run_ids=_source_run_ids(weather_points, warnings),
        )
        planned_refs.insert(0, route_weather_package_ref)

    source_report = [
        *weather_point_report,
        *warning_report,
        *route_segment_report,
        _weather_daylight_report(root, weather_daylight_ref),
        _route_weather_package_report(
            root,
            route_weather_package_ref,
            built_package=route_weather_package,
        ),
    ]
    source_manifest_payload = _source_manifest_payload(
        project_id=project_id,
        generated_at=collected_at,
        source_report=source_report,
    )

    assessment = _weather_assessment(
        root,
        project,
        route_weather_package_ref=route_weather_package_ref,
        weather_daylight_ref=weather_daylight_ref,
        route_weather_package=route_weather_package,
        dry_run=dry_run,
    )
    candidate_payload = _decision_candidates_payload(
        project_id=project_id,
        generated_at=collected_at,
        source_manifest_ref=source_manifest_ref,
        route_weather_package_ref=route_weather_package_ref
        if route_weather_package is not None or project.get("route_weather_package_ref")
        else None,
        weather_daylight_ref=weather_daylight_ref,
        assessment=assessment,
        source_report=source_report,
    )

    collection_payload = {
        "artifact_kind": WEATHER_DECISION_COLLECTION_ARTIFACT_KIND,
        "schema_version": WEATHER_DECISION_SCHEMA_VERSION,
        "status": "completed",
        "dry_run": dry_run,
        "project_id": project_id,
        "writes_performed": False,
        "route_weather_package_built": route_weather_package is not None,
        "planned_refs": planned_refs,
        "outputs": {
            "route_weather_package_ref": route_weather_package_ref
            if route_weather_package is not None or project.get("route_weather_package_ref")
            else None,
            "weather_source_manifest_ref": source_manifest_ref,
            "weather_decision_candidates_ref": candidates_ref,
        },
        "decision": assessment.get("decision"),
        "answerability": assessment.get("answerability"),
        "missing_fields": list(assessment.get("missing_fields") or []),
        "source_report": source_report,
        "standard_alignment": [
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 10 Weather-to-Decision Intelligence",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 23 acceptance criteria",
            "scout-workspace-layout Outdoor AI Agent Data Placement Sec. 10",
        ],
        "boundary": _closed_boundary(),
    }

    if not dry_run:
        if route_weather_package is not None:
            write_route_weather_package(root / route_weather_package_ref, route_weather_package)
        _write_json(root / source_manifest_ref, source_manifest_payload)
        _write_json(root / candidates_ref, candidate_payload)
        _update_project_refs(
            project_path,
            project,
            {
                **(
                    {"route_weather_package_ref": route_weather_package_ref}
                    if route_weather_package is not None
                    else {}
                ),
                "weather_source_manifest_ref": source_manifest_ref,
                "weather_decision_candidates_ref": candidates_ref,
                "weather_decision_candidate_count": len(candidate_payload["candidates"]),
                "weather_decision_collection_updated_at": collected_at,
                "weather_decision_collection_schema_version": (
                    WEATHER_DECISION_SCHEMA_VERSION
                ),
            },
        )
        collection_payload["writes_performed"] = True
        collection_payload["written_refs"] = planned_refs

    return collection_payload


def _load_weather_points(
    root: Path,
    project: dict[str, Any],
    *,
    explicit_path: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates = _candidate_paths(
        root,
        project,
        explicit_path=explicit_path,
        ref_keys=(
            "weather_points_ref",
            "forecast_snapshots_ref",
            "weather_forecast_snapshots_ref",
        ),
        fallbacks=(
            "normalized/weather/forecast_snapshots.json",
            "normalized/weather/forecast_snapshots.jsonl",
        ),
    )
    return _load_first_record_list(candidates, source_kind="weather_points")


def _load_warning_records(
    root: Path,
    project: dict[str, Any],
    *,
    explicit_path: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates = _candidate_paths(
        root,
        project,
        explicit_path=explicit_path,
        ref_keys=("weather_warning_ref", "weather_warnings_ref"),
        fallbacks=("normalized/weather/warnings.json",),
    )
    return _load_first_record_list(candidates, source_kind="weather_warnings")


def _load_route_segments(
    root: Path,
    project: dict[str, Any],
    *,
    explicit_path: str | None,
    default_township: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates = _candidate_paths(
        root,
        project,
        explicit_path=explicit_path,
        ref_keys=("compiled_mission_graph_candidate_ref", "segment_candidates_ref"),
        fallbacks=("outputs/compiled_mission_graph.candidate.json", "candidates/segments.json"),
    )
    raw_records, report = _load_first_record_list(candidates, source_kind="route_segments")
    segments = [
        _route_segment_for_weather(record, default_township=default_township)
        for record in raw_records
        if isinstance(record, dict)
    ]
    return segments, report


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
    seen: set[str] = set()
    for label, path in candidates:
        key = path.resolve().as_posix() if path.exists() else path.as_posix()
        if key in seen:
            continue
        seen.add(key)
        deduped.append((str(label), path))
    return deduped


def _load_first_record_list(
    candidates: list[tuple[str, Path]],
    *,
    source_kind: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    report: list[dict[str, Any]] = []
    for label, path in candidates:
        if not path.exists():
            report.append(_source_report(source_kind, "missing", label, 0))
            continue
        payload = _load_json_or_jsonl(path)
        records = _records_from_payload(payload)
        report.append(
            _source_report(
                source_kind,
                "loaded" if records else "loaded_empty",
                label,
                len(records),
                artifact_kind=payload.get("artifact_kind")
                if isinstance(payload, dict)
                else None,
            )
        )
        return records, report
    return [], report[:3] or [_source_report(source_kind, "missing", None, 0)]


def _load_json_or_jsonl(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    return json.loads(text)


def _records_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in (
        "weather_points",
        "forecast_snapshots",
        "records",
        "warnings",
        "segments",
        "candidates",
    ):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return [payload]


def _route_segment_for_weather(
    raw: dict[str, Any],
    *,
    default_township: str | None,
) -> dict[str, Any]:
    requirement = raw.get("requirement") if isinstance(raw.get("requirement"), dict) else {}
    distance = _float_or_none(_first_present(raw, "distance_m", "distanceM"))
    elevation_gain = _float_or_none(
        _first_present(raw, "elevation_gain_m", "elevationGainM")
    )
    terrain_risk = _float_or_none(_first_present(raw, "terrainRisk", "terrain_risk"))
    if terrain_risk is None:
        terrain_risk = _derived_terrain_interaction(raw, requirement)
    segment = {
        "segmentId": _first_present(
            raw,
            "segment_id",
            "segmentId",
            "candidate_id",
            "id",
            default="segment.unknown",
        ),
        "fromM": _float_or_none(_first_present(raw, "from_m", "fromM")),
        "toM": _float_or_none(_first_present(raw, "to_m", "toM")),
        "etaFrom": _first_present(raw, "eta_from", "etaFrom"),
        "etaTo": _first_present(raw, "eta_to", "etaTo"),
        "township": _first_present(raw, "township", "areaName", default=default_township),
        "terrainRisk": terrain_risk,
        "source": {
            "candidate_id": _first_present(raw, "candidate_id", "segment_id", "segmentId"),
            "source_refs": _string_list(raw.get("source_refs")),
            "candidate_only": bool(raw.get("candidate_only", True)),
            "runtime_safety_truth": bool(raw.get("runtime_safety_truth", False)),
        },
    }
    if segment["fromM"] is None and distance is not None:
        segment["fromM"] = 0.0
        segment["toM"] = distance
    if segment["toM"] is None and distance is not None:
        segment["toM"] = distance
    if elevation_gain is not None:
        segment["elevationGainM"] = elevation_gain
    return segment


def _derived_terrain_interaction(
    raw: dict[str, Any],
    requirement: dict[str, Any],
) -> float:
    score = 0.15
    distance = _float_or_none(_first_present(raw, "distance_m", "distanceM")) or 0.0
    elevation_gain = _float_or_none(
        _first_present(raw, "elevation_gain_m", "elevationGainM")
    ) or 0.0
    elevation_loss = _float_or_none(
        _first_present(raw, "elevation_loss_m", "elevationLossM")
    ) or 0.0
    if requirement.get("requires_daylight") is True:
        score += 0.15
    if requirement.get("retreat_available") is False:
        score += 0.10
    if requirement.get("signal_expected") is False:
        score += 0.05
    if distance >= 500:
        score += 0.05
    if elevation_gain >= 50 or elevation_loss >= 50:
        score += 0.10
    return round(min(score, 0.75), 4)


def _weather_assessment(
    root: Path,
    project: dict[str, Any],
    *,
    route_weather_package_ref: str,
    weather_daylight_ref: str,
    route_weather_package: dict[str, Any] | None,
    dry_run: bool,
) -> dict[str, Any]:
    if route_weather_package is not None:
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            (temp_root / "outputs").mkdir(parents=True)
            (temp_root / "project.json").write_text(
                json.dumps(
                    {
                        "project_id": project.get("project_id") or root.name,
                        "route_weather_package_ref": route_weather_package_ref,
                        "weather_daylight_evidence_ref": weather_daylight_ref,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            write_route_weather_package(
                temp_root / route_weather_package_ref,
                route_weather_package,
            )
            if (root / weather_daylight_ref).exists():
                _write_json(
                    temp_root / weather_daylight_ref,
                    _load_json_object(root / weather_daylight_ref),
                )
            return assess_scout_weather_window(temp_root, limit=12)
    return assess_scout_weather_window(
        root,
        weather_evidence_path=weather_daylight_ref,
        limit=12,
    )


def _source_manifest_payload(
    *,
    project_id: str,
    generated_at: str,
    source_report: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "artifact_kind": WEATHER_SOURCE_MANIFEST_ARTIFACT_KIND,
        "schema_version": WEATHER_DECISION_SCHEMA_VERSION,
        "project_id": project_id,
        "generated_at": generated_at,
        "source_report": source_report,
        "required_missing_source_kinds": [
            item["source_kind"]
            for item in source_report
            if item.get("required_by_standard_sec10") is True
            and item.get("status") not in {"loaded", "built_in_memory"}
        ],
        "optional_missing_source_kinds": [
            item["source_kind"]
            for item in source_report
            if item.get("required_by_standard_sec10") is False
            and item.get("status") == "missing"
        ],
        "cache_policy": {
            "mode": "offline_first_local_weather_evidence",
            "live_fetch_performed": False,
            "client_cwa_api_key_allowed": False,
            "refresh_required_before_runtime_truth": True,
        },
        "boundary": _closed_boundary(),
    }


def _decision_candidates_payload(
    *,
    project_id: str,
    generated_at: str,
    source_manifest_ref: str,
    route_weather_package_ref: str | None,
    weather_daylight_ref: str,
    assessment: dict[str, Any],
    source_report: list[dict[str, Any]],
) -> dict[str, Any]:
    decision = (
        assessment.get("weather_to_decision")
        if isinstance(assessment.get("weather_to_decision"), dict)
        else {}
    )
    candidate = {
        "candidate_id": f"weather_decision.{project_id}.v0",
        "project_id": project_id,
        "status": "candidate_only",
        "decision": assessment.get("decision") or decision.get("decision") or "DELAY",
        "answerability": assessment.get("answerability"),
        "field_answer": assessment.get("field_answer"),
        "main_reasons": list(decision.get("main_reasons") or []),
        "action_limit": decision.get("action_limit"),
        "next_action": decision.get("next_action"),
        "alternatives": list(decision.get("alternatives") or []),
        "route_specific_conditions": list(
            decision.get("route_specific_conditions") or []
        ),
        "highest_risk_segment": decision.get("highest_risk_segment"),
        "wx_alert_count": decision.get("wx_alert_count"),
        "weather_buffer_impact": decision.get("weather_buffer_impact"),
        "missing_fields": list(assessment.get("missing_fields") or []),
        "warnings": list(assessment.get("warnings") or []),
        "human_review_required": True,
        "source_refs": _decision_source_refs(
            source_manifest_ref,
            weather_daylight_ref,
            route_weather_package_ref,
        ),
        "candidate_only": True,
        "runtime_safety_truth": False,
        "phase1_runtime_mutation_allowed": False,
        "phase2_brain_writeback_allowed": False,
        "live_safety_api_calls_allowed": False,
        "external_api_calls_made": False,
    }
    return {
        "artifact_kind": WEATHER_DECISION_CANDIDATES_ARTIFACT_KIND,
        "schema_version": WEATHER_DECISION_SCHEMA_VERSION,
        "project_id": project_id,
        "generated_at": generated_at,
        "weather_source_manifest_ref": source_manifest_ref,
        "route_weather_package_ref": route_weather_package_ref,
        "weather_daylight_evidence_ref": weather_daylight_ref,
        "source_report": source_report,
        "counts": {
            "candidate_count": 1,
            "missing_field_count": len(candidate["missing_fields"]),
            "warning_count": len(candidate["warnings"]),
            "wx_alert_count": candidate["wx_alert_count"] or 0,
        },
        "candidates": [candidate],
        "boundary": _closed_boundary(),
    }


def _decision_source_refs(
    source_manifest_ref: str,
    weather_daylight_ref: str,
    route_weather_package_ref: str | None,
) -> list[str]:
    refs = [source_manifest_ref, weather_daylight_ref]
    if route_weather_package_ref:
        refs.append(route_weather_package_ref)
    return refs


def _weather_daylight_report(root: Path, ref: str) -> dict[str, Any]:
    path = root / ref
    if not path.exists():
        return _source_report("weather_daylight_evidence", "missing", ref, 0)
    payload = _load_json_object(path)
    return _source_report(
        "weather_daylight_evidence",
        "loaded",
        ref,
        1,
        artifact_kind=payload.get("artifact_kind") or "pretrip_weather_daylight_evidence",
        source_status=payload.get("status"),
        required=True,
    )


def _route_weather_package_report(
    root: Path,
    ref: str,
    *,
    built_package: dict[str, Any] | None,
) -> dict[str, Any]:
    if built_package is not None:
        return _source_report(
            "route_weather_package",
            "built_in_memory",
            ref,
            len(built_package.get("segments", [])),
            artifact_kind=built_package.get("artifact_kind"),
            source_status=built_package.get("status"),
            required=False,
        )
    path = root / ref
    if path.exists():
        payload = _load_json_object(path)
        return _source_report(
            "route_weather_package",
            "loaded",
            ref,
            len(payload.get("segments", [])) if isinstance(payload, dict) else 0,
            artifact_kind=payload.get("artifact_kind") if isinstance(payload, dict) else None,
            source_status=payload.get("status") if isinstance(payload, dict) else None,
            required=False,
        )
    return _source_report("route_weather_package", "missing", ref, 0, required=False)


def _source_report(
    source_kind: str,
    status: str,
    source_path: str | None,
    loaded_count: int,
    *,
    artifact_kind: str | None = None,
    source_status: str | None = None,
    required: bool | None = None,
) -> dict[str, Any]:
    required_by_sec10 = (
        source_kind in {"weather_points", "route_segments", "weather_daylight_evidence"}
        if required is None
        else required
    )
    return {
        "source_kind": source_kind,
        "status": status,
        "source_path": source_path,
        "loaded_count": loaded_count,
        "artifact_kind": artifact_kind,
        "source_status": source_status,
        "required_by_standard_sec10": required_by_sec10,
    }


def _source_run_ids(
    weather_points: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> list[str]:
    ids = []
    for item in [*weather_points, *warnings]:
        value = item.get("source_run_id")
        if value not in (None, ""):
            ids.append(str(value))
    return sorted(set(ids))


def _project_path(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _update_project_refs(
    project_path: Path,
    project: dict[str, Any],
    updates: dict[str, Any],
) -> None:
    if not project_path.exists():
        return
    _write_json(project_path, {**project, **updates})


def _closed_boundary() -> dict[str, Any]:
    return {
        "candidate_only": True,
        "runtime_safety_truth": False,
        "phase1_runtime_mutation_allowed": False,
        "phase2_brain_writeback_allowed": False,
        "live_safety_api_calls_allowed": False,
        "safety_api_called": False,
        "external_api_calls_made": False,
        "outbound_send_allowed": False,
        "hardware_control_allowed": False,
        "client_cwa_api_key_allowed": False,
        "raw_payloads_embedded": False,
    }


def _first_present(raw: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = raw.get(key)
        if value not in (None, ""):
            return value
    return default


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item not in (None, "")]
    if value in (None, ""):
        return []
    return [str(value)]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect Scout weather-to-decision candidates.")
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--weather-points", dest="weather_points_path", default=None)
    parser.add_argument("--warnings", dest="warnings_path", default=None)
    parser.add_argument("--route-segments", dest="route_segments_path", default=None)
    parser.add_argument("--default-township", default=None)
    parser.add_argument("--generated-at", default=None)
    parser.add_argument("--valid-until", default=None)
    parser.add_argument("--provider", default="workspace_local_weather_points")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    payload = collect_pretrip_weather_decision(
        args.project_root,
        dry_run=args.dry_run,
        weather_points_path=args.weather_points_path,
        warnings_path=args.warnings_path,
        route_segments_path=args.route_segments_path,
        default_township=args.default_township,
        generated_at=args.generated_at,
        valid_until=args.valid_until,
        provider=args.provider,
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(
            f"{payload['status']}: decision={payload.get('decision')} "
            f"writes={payload.get('writes_performed')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
