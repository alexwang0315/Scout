from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from assistant_models import AssistantSourceRef, AssistantSurface, ScoutAssistantQuery


TOTAL_INFO_SOURCE_ID = "assistant_context.total_info_entry"
TOTAL_INFO_EVIDENCE_TYPE = "assistant_workspace_total_info"

_MAX_SOURCE_REPORT_ITEMS = 16
_LIVE_NAVIGATION_FIELDS = (
    "observed_at",
    "updated_at",
    "lat",
    "lon",
    "elevation_m",
    "source",
    "snapshot_status",
    "fix_quality",
    "hdop",
    "horizontal_accuracy_m",
    "satellite_count",
    "max_cno_dbhz",
    "nearest_route_distance_m",
    "route_progress_m",
    "nearest_cp_id",
    "confidence",
    "uncertainty_m",
    "last_anchor_at",
)


def build_workspace_total_info_source_ref(
    query: ScoutAssistantQuery,
    *,
    project_root: Path | str | None,
    data_root: Path | str | None = None,
    reference_time: str | None = None,
) -> AssistantSourceRef | None:
    if query.surface != AssistantSurface.PRETRIP or project_root is None:
        return None
    root = Path(project_root).expanduser().resolve()
    manifest_path = _project_manifest_path(root)
    project = _load_json_object(manifest_path)
    if not project:
        return None

    resolved_data_root = _resolve_data_root(data_root)
    summary = {
        "artifact_kind": "assistant_workspace_total_info_context",
        "artifact_version": "assistant_workspace_total_info_context.v0",
        "project_id": str(project.get("project_id") or query.project_id or root.name),
        "query_project_id": query.project_id or query.context_ref,
        "read_only": True,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "raw_payloads_embedded": False,
        "route_context": _route_context(root, project),
        "location_context": _location_context(query, data_root=resolved_data_root),
        "body_resource_context": _body_resource_context(root, project),
        "weather_environment_context": _weather_environment_context(
            root,
            project,
            reference_time=_parse_datetime(reference_time) or datetime.now(timezone.utc),
        ),
        "terrain_risk_context": _terrain_risk_context(root, project),
        "sensor_snapshot_context": _sensor_snapshot_context(resolved_data_root),
        "workspace_ref_context": _workspace_ref_context(root, project),
        "missing_or_partial_context": [],
        "boundary": _closed_boundary(),
    }
    summary["missing_or_partial_context"] = _missing_or_partial_context(summary)
    return AssistantSourceRef(
        source_id=TOTAL_INFO_SOURCE_ID,
        source_path="workspace.total_info_entry",
        evidence_type=TOTAL_INFO_EVIDENCE_TYPE,
        selected=True,
        context_summary=summary,
    )


def public_workspace_total_info_summary(
    summary: dict[str, Any],
) -> dict[str, Any]:
    """Project total-info evidence to metadata safe for API consumers."""

    context_statuses = {
        str(key): str(value.get("status") or "unknown")
        for key, value in summary.items()
        if str(key).endswith("_context") and isinstance(value, dict)
    }
    missing = summary.get("missing_or_partial_context")
    return {
        "artifact_kind": str(
            summary.get("artifact_kind")
            or "assistant_workspace_total_info_context"
        ),
        "artifact_version": str(summary.get("artifact_version") or "unknown"),
        "project_id": str(summary.get("project_id") or "unknown"),
        "context_statuses": dict(sorted(context_statuses.items())),
        "missing_or_partial_context_count": (
            len(missing) if isinstance(missing, list) else 0
        ),
        "read_only": True,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "raw_payloads_embedded": False,
    }


def _route_context(root: Path, project: dict[str, Any]) -> dict[str, Any]:
    route = _load_json_object(_project_path(root, project.get("route_summary_ref")))
    source_path = _project_ref_label(root, project.get("route_summary_ref"))
    return _drop_none(
        {
            "status": "available" if route else "missing",
            "source_path": source_path,
            "route_name": route.get("route_name") or project.get("route_name"),
            "route_kind": project.get("route_kind"),
            "route_role": project.get("route_role"),
            "route_days": project.get("route_days"),
            "distance_m": _number(route.get("distance_m")),
            "distance_km": _km(route.get("distance_m")),
            "point_count": route.get("point_count"),
            "elevation_min_m": _number(route.get("elevation_min_m")),
            "elevation_max_m": _number(route.get("elevation_max_m")),
            "started_at": route.get("started_at"),
            "ended_at": route.get("ended_at"),
            "bbox_wgs84": route.get("bbox_wgs84"),
            "checkpoint_candidate_count": project.get("checkpoint_candidate_count"),
            "segment_candidate_count": project.get("segment_candidate_count"),
            "mcp_candidate_count": project.get("mcp_candidate_count"),
            "boss_point_count": project.get("boss_point_count"),
            "mileage_tag_alignment_count": project.get("mileage_tag_alignment_count"),
            "route_mileage_k_anchor_count": project.get("route_mileage_k_anchor_count"),
            "reference_track_count": project.get("reference_track_count"),
        }
    )


def _location_context(
    query: ScoutAssistantQuery,
    *,
    data_root: Path | None,
) -> dict[str, Any]:
    query_snapshot = _bounded_live_navigation_snapshot(query.live_navigation_snapshot)
    hardware_snapshot = _load_hardware_live_navigation_snapshot(data_root)
    selected = query_snapshot or hardware_snapshot
    return {
        "status": "available" if selected else "missing_current_location",
        "source": "assistant_query.live_navigation_snapshot"
        if query_snapshot
        else ("gnss_hardware.live_navigation_snapshot" if hardware_snapshot else None),
        "live_navigation_snapshot": selected,
        "query_snapshot_available": bool(query_snapshot),
        "hardware_snapshot_available": bool(hardware_snapshot),
        "route_match_available": any(
            key in selected
            for key in ("nearest_route_distance_m", "route_progress_m", "nearest_cp_id")
        )
        if selected
        else False,
        "raw_payloads_embedded": False,
        "runtime_safety_truth": False,
    }


def _body_resource_context(root: Path, project: dict[str, Any]) -> dict[str, Any]:
    boss = _load_json_object(_project_path(root, project.get("boss_points_ref")))
    energy_snapshot_ref = _project_ref_label(
        root,
        project.get("energy_vitals_snapshot_ref"),
    )
    energy_snapshot = _load_json_object(_project_path(root, energy_snapshot_ref))
    mission_graph = _load_json_object(root / "outputs" / "compiled_mission_graph.reviewed.json")
    thresholds = _mission_graph_thresholds(mission_graph)
    metadata = boss.get("metadata") if isinstance(boss.get("metadata"), dict) else {}
    return _drop_none(
        {
            "status": "available" if boss or energy_snapshot or thresholds else "missing_live_body_resource",
            "boss_points_ref": _project_ref_label(root, project.get("boss_points_ref")),
            "boss_point_count": project.get("boss_point_count"),
            "energy_vitals_snapshot_ref": energy_snapshot_ref,
            "energy_vitals_snapshot_available": bool(energy_snapshot),
            "raw_health_payload_embedded": metadata.get("raw_health_payload_embedded")
            if metadata
            else None,
            "energy_basis": metadata.get("basis") if metadata else None,
            "energy_reserve_band": metadata.get("energy_reserve_band") if metadata else None,
            "mission_graph_thresholds": thresholds or None,
            "limitations": [
                "Workspace body resource data is pretrip/candidate evidence unless a live wearable snapshot is supplied.",
                "No medical diagnosis or raw health payload is embedded.",
            ],
            "runtime_safety_truth": False,
        }
    )


def _weather_environment_context(
    root: Path,
    project: dict[str, Any],
    *,
    reference_time: datetime,
) -> dict[str, Any]:
    cwa = _load_json_object(_project_path(root, project.get("cwa_weather_evidence_ref")))
    qpf = _load_json_object(_project_path(root, project.get("cwa_qpf_corridor_summary_ref")))
    smap = _load_json_object(_project_path(root, project.get("smap_l4_corridor_summary_ref")))
    gpm = _load_json_object(_project_path(root, project.get("gpm_imerg_corridor_summary_ref")))
    derived = _load_json_object(_project_path(root, project.get("environment_risk_derivatives_ref")))
    artifacts = {"cwa_weather": cwa, "cwa_qpf": qpf, "gee_smap": smap, "gee_gpm": gpm}
    freshness = {
        name: _environment_artifact_freshness(payload, reference_time=reference_time)
        for name, payload in artifacts.items()
        if payload
    }
    stale_sources = sorted(
        name for name, status in freshness.items() if status == "stale"
    )
    available = any((cwa, qpf, smap, gpm, derived))
    return {
        "status": (
            "partial_stale_environment"
            if stale_sources
            else "available"
            if available
            else "missing_weather_environment"
        ),
        "freshness": freshness,
        "stale_sources": stale_sources,
        "cwa_weather": _compact_artifact(
            cwa,
            source_path=_project_ref_label(root, project.get("cwa_weather_evidence_ref")),
            keys=(
                "artifact_kind",
                "generated_at",
                "fetched_at",
                "forecast_valid_from",
                "forecast_valid_until",
                "counts",
                "external_api_calls_made",
                "source_family",
            ),
        ),
        "cwa_qpf": _compact_artifact(
            qpf,
            source_path=_project_ref_label(
                root,
                project.get("cwa_qpf_corridor_summary_ref"),
            ),
            keys=(
                "artifact_kind",
                "generated_at",
                "fetched_at",
                "forecast_valid_from",
                "forecast_valid_until",
                "counts",
                "max_observed_24h_mm",
                "mean_observed_24h_mm",
                "max_rain_probability",
                "candidate_only",
                "runtime_safety_truth",
            ),
        ),
        "gee_smap": _compact_environment_values(
            smap,
            source_path=_project_ref_label(
                root,
                project.get("smap_l4_corridor_summary_ref"),
            ),
        ),
        "gee_gpm": _compact_environment_values(
            gpm,
            source_path=_project_ref_label(
                root,
                project.get("gpm_imerg_corridor_summary_ref"),
            ),
        ),
        "environment_risk_derivatives": _compact_artifact(
            derived,
            source_path=_project_ref_label(
                root,
                project.get("environment_risk_derivatives_ref"),
            ),
            keys=("artifact_kind", "generated_at", "status", "headline", "counts", "route_buffer_m"),
        ),
        "runtime_safety_truth": False,
    }


def _environment_artifact_freshness(
    payload: dict[str, Any],
    *,
    reference_time: datetime,
    stale_after_hours: float = 72.0,
) -> str:
    valid_until = _parse_datetime(
        payload.get("forecast_valid_until")
        or payload.get("valid_until")
        or payload.get("validUntil")
        or payload.get("valid_to")
    )
    if valid_until is not None:
        return "fresh" if valid_until >= reference_time else "stale"
    generated_at = _parse_datetime(
        payload.get("generated_at")
        or payload.get("generatedAt")
        or payload.get("fetched_at")
        or payload.get("issued_at")
    )
    if generated_at is None:
        return "unknown"
    age_hours = (reference_time - generated_at).total_seconds() / 3600.0
    return "fresh" if age_hours <= stale_after_hours else "stale"


def _terrain_risk_context(root: Path, project: dict[str, Any]) -> dict[str, Any]:
    risk_meta = _load_json_object(_project_path(root, project.get("risk_route_profile_metadata_ref")))
    risk_diag = _load_json_object(_project_path(root, project.get("risk_attribution_diagnostic_ref")))
    terrain_dtm = _load_json_object(root / "normalized" / "terrain" / "dtm_coverage_summary.json")
    return {
        "status": "available" if any((risk_meta, risk_diag, terrain_dtm)) else "missing_terrain_risk",
        "risk_route_profile": _compact_artifact(
            risk_meta,
            source_path=_project_ref_label(
                root,
                project.get("risk_route_profile_metadata_ref"),
            ),
            keys=("artifact_kind", "generated_at", "segment_count", "score_summary", "score_fields"),
        ),
        "risk_attribution": _compact_artifact(
            risk_diag,
            source_path=_project_ref_label(
                root,
                project.get("risk_attribution_diagnostic_ref"),
            ),
            keys=("artifact_kind", "status", "counts", "route_dimension_stats"),
        ),
        "terrain_dtm_coverage": _compact_artifact(
            terrain_dtm,
            source_path="normalized/terrain/dtm_coverage_summary.json",
            keys=("artifact_kind", "status", "counts", "coverage", "bbox_wgs84"),
        ),
        "risk_score_point_count": project.get("risk_score_point_count"),
        "risk_ribbon_segment_count": project.get("risk_ribbon_segment_count"),
        "terrain_risk_candidate_ref": _project_ref_label(
            root,
            project.get("terrain_risk_candidates_ref"),
        ),
        "runtime_safety_truth": False,
    }


def _sensor_snapshot_context(data_root: Path | None) -> dict[str, Any]:
    if data_root is None:
        return {"status": "not_configured", "runtime_safety_truth": False}
    sensorlogger_status = _load_json_object(
        data_root / "admin" / "ingress" / "sensorlogger_mqtt" / "sensorlogger_mqtt_status.json"
    )
    imu_status = _load_json_object(
        data_root / "admin" / "ingress" / "imu_pdr" / "imu_pdr_observer_status.json"
    )
    gnss_status = _load_json_object(
        data_root / "admin" / "ingress" / "gnss_hardware" / "gnss_hardware_observer_status.json"
    )
    latest_sensor_record = _read_jsonl_tail_object(
        data_root
        / "admin"
        / "ingress"
        / "sensorlogger_mqtt"
        / "sensorlogger_mqtt_sensor_vitals_records.jsonl"
    )
    return {
        "status": "available"
        if any((sensorlogger_status, imu_status, gnss_status, latest_sensor_record))
        else "missing_live_sensor_snapshot",
        "gnss": _compact_artifact(
            gnss_status,
            source_path="admin/ingress/gnss_hardware/gnss_hardware_observer_status.json",
            keys=(
                "artifact_kind",
                "answerability",
                "decision",
                "active_listening_source_count",
                "listening_source_count",
                "latest_snapshot_at",
                "runtime_safety_truth",
            ),
        ),
        "imu_pdr": _compact_artifact(
            imu_status,
            source_path="admin/ingress/imu_pdr/imu_pdr_observer_status.json",
            keys=(
                "artifact_kind",
                "observer_state",
                "last_sample_at",
                "evidence_bucket",
                "sample_count",
                "raw_payload_count",
                "latest_pdr_estimate",
                "provider_errors",
            ),
        ),
        "sensorlogger_mqtt": _sensorlogger_status_summary(sensorlogger_status),
        "latest_sensor_vitals_record": _compact_sensor_vitals_record(latest_sensor_record),
        "runtime_safety_truth": False,
        "raw_payloads_embedded": False,
    }


def _workspace_ref_context(root: Path, project: dict[str, Any]) -> dict[str, Any]:
    refs: list[dict[str, Any]] = []
    for key, value in sorted(project.items()):
        if not key.endswith("_ref") or not isinstance(value, str):
            continue
        if not any(
            token in key
            for token in (
                "route",
                "checkpoint",
                "weather",
                "cwa",
                "gee",
                "smap",
                "gpm",
                "qpf",
                "risk",
                "terrain",
                "mileage",
                "energy",
                "boss",
                "mcp",
            )
        ):
            continue
        path = _project_path(root, value)
        if path is None:
            refs.append(
                {
                    "ref_key": key,
                    "status": "invalid_workspace_ref",
                    "exists": False,
                }
            )
            continue
        refs.append(
            {
                "ref_key": key,
                "source_path": _project_ref_label(root, value),
                "status": "available" if path.exists() else "missing",
                "exists": path.exists(),
            }
        )
    return {
        "status": "available" if refs else "missing_workspace_refs",
        "ref_count": len(refs),
        "refs": refs[:_MAX_SOURCE_REPORT_ITEMS],
        "truncated": len(refs) > _MAX_SOURCE_REPORT_ITEMS,
    }


def _missing_or_partial_context(summary: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    if summary["location_context"].get("status") != "available":
        missing.append("current_position")
    elif not summary["location_context"].get("route_match_available"):
        missing.append("current_position_route_match")
    if summary["body_resource_context"].get("status") != "available":
        missing.append("body_resource_or_wearable_vitals")
    if summary["weather_environment_context"].get("status") != "available":
        missing.append("weather_environment")
    if summary["route_context"].get("status") != "available":
        missing.append("route_summary")
    if summary["sensor_snapshot_context"].get("status") not in {"available", "not_configured"}:
        missing.append("live_sensor_snapshot")
    return missing


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _compact_artifact(
    payload: dict[str, Any],
    *,
    source_path: object,
    keys: tuple[str, ...],
) -> dict[str, Any]:
    if not payload:
        return {"status": "missing", "source_path": source_path}
    compact = {key: payload.get(key) for key in keys if key in payload}
    compact["status"] = payload.get("status") or "available"
    compact["source_path"] = source_path
    compact["candidate_only"] = payload.get("candidate_only", True)
    compact["runtime_safety_truth"] = payload.get("runtime_safety_truth", False)
    return _drop_none(compact)


def _compact_environment_values(
    payload: dict[str, Any],
    *,
    source_path: object,
) -> dict[str, Any]:
    compact = _compact_artifact(
        payload,
        source_path=source_path,
        keys=("artifact_kind", "generated_at", "status", "gee_runtime_status"),
    )
    values = payload.get("values") if isinstance(payload, dict) else None
    if isinstance(values, dict):
        compact["values"] = {
            key: value
            for key, value in values.items()
            if key
            in {
                "sm_surface",
                "sm_rootzone",
                "sm_profile",
                "sm_surface_wetness",
                "sm_rootzone_wetness",
                "surface_temp",
                "precipitation_mm",
                "precipitation_rate_mm_hr",
                "latest",
                "mean",
                "max",
                "p95",
                "trend",
            }
        }
    return compact


def _sensorlogger_status_summary(payload: dict[str, Any]) -> dict[str, Any]:
    if not payload:
        return {"status": "missing", "source_path": "admin/ingress/sensorlogger_mqtt/sensorlogger_mqtt_status.json"}
    ingress = payload.get("ingress") if isinstance(payload.get("ingress"), dict) else {}
    mqtt = payload.get("mqtt") if isinstance(payload.get("mqtt"), dict) else {}
    application_router = (
        payload.get("application_router")
        if isinstance(payload.get("application_router"), dict)
        else {}
    )
    return _drop_none(
        {
            "status": payload.get("status") or "available",
            "source_path": "admin/ingress/sensorlogger_mqtt/sensorlogger_mqtt_status.json",
            "mqtt_connected": mqtt.get("mqtt_connected") or payload.get("mqtt_connected"),
            "mqtt_subscribed": mqtt.get("mqtt_subscribed") or payload.get("mqtt_subscribed"),
            "accepted_count": ingress.get("accepted_count"),
            "latest_received_at": ingress.get("latest_received_at"),
            "registered_targets": application_router.get("registered_targets"),
            "dispatch_count": application_router.get("dispatch_count"),
            "runtime_safety_truth": False,
        }
    )


def _compact_sensor_vitals_record(record: dict[str, Any]) -> dict[str, Any]:
    if not record:
        return {"status": "missing"}
    return _drop_none(
        {
            "status": "available",
            "artifact_kind": record.get("artifact_kind"),
            "observed_at": record.get("observed_at"),
            "received_at": record.get("received_at"),
            "observation_name": record.get("observation_name"),
            "capability_tags": record.get("capability_tags"),
            "privacy_class": record.get("privacy_class"),
            "quality": record.get("quality"),
            "raw_payload_embedded": False,
            "runtime_safety_truth": False,
        }
    )


def _mission_graph_thresholds(payload: dict[str, Any]) -> dict[str, Any]:
    if not payload:
        return {}
    thresholds: dict[str, Any] = {}
    _collect_thresholds(payload, thresholds)
    return thresholds


def _collect_thresholds(value: Any, thresholds: dict[str, Any]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"min_device_battery", "min_estimated_human_energy"}:
                thresholds.setdefault(key, item)
            elif len(thresholds) < 8:
                _collect_thresholds(item, thresholds)
    elif isinstance(value, list):
        for item in value[:80]:
            if len(thresholds) >= 8:
                break
            _collect_thresholds(item, thresholds)


def _bounded_live_navigation_snapshot(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        field: value.get(field)
        for field in _LIVE_NAVIGATION_FIELDS
        if not _missing(value.get(field))
    }


def _load_hardware_live_navigation_snapshot(data_root: Path | None) -> dict[str, Any]:
    if data_root is None:
        return {}
    snapshot = _load_json_object(
        data_root / "admin" / "ingress" / "gnss_hardware" / "live_navigation_snapshot.json"
    )
    return _bounded_live_navigation_snapshot(snapshot)


def _resolve_data_root(data_root: Path | str | None) -> Path | None:
    raw = data_root or os.environ.get("SCOUT_DATA_ROOT")
    if raw is None:
        default = Path("/data/scout")
        return default if default.exists() else None
    path = Path(raw).expanduser()
    return path if path.exists() else None


def _read_jsonl_tail_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            end = fh.tell()
            fh.seek(max(end - 65536, 0), os.SEEK_SET)
            text = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return {}
    for line in reversed([item for item in text.splitlines() if item.strip()]):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return {}


def _load_json_object(path: Path | None) -> dict[str, Any]:
    if path is None or path.is_symlink():
        return {}
    descriptor: int | None = None
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            return {}
        with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
            descriptor = None
            value = json.load(stream)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return value if isinstance(value, dict) else {}


def _project_manifest_path(root: Path) -> Path | None:
    manifest = root / "project.json"
    if manifest.is_symlink():
        return None
    try:
        resolved = manifest.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError):
        return None
    return resolved if resolved.is_file() else None


def _project_path(root: Path, ref: object) -> Path | None:
    if not isinstance(ref, str) or not ref.strip():
        return None
    root_resolved = root.expanduser().resolve()
    path = Path(ref).expanduser()
    candidate = (path if path.is_absolute() else root_resolved / path).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError:
        return None
    return candidate


def _project_ref_label(root: Path, ref: object) -> str | None:
    path = _project_path(root, ref)
    if path is None:
        return None
    return path.relative_to(root.expanduser().resolve()).as_posix()


def _number(value: object) -> float | None:
    try:
        if value is None:
            return None
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None


def _km(value: object) -> float | None:
    number = _number(value)
    if number is None:
        return None
    return round(number / 1000.0, 3)


def _missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict)):
        return not value
    return False


def _drop_none(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item is not None}


def _closed_boundary() -> dict[str, bool]:
    return {
        "read_only": True,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "live_safety_api_calls_allowed": False,
        "phase1_safety_mutation_allowed": False,
        "phase2_brain_writeback_allowed": False,
        "observed_fact_write_allowed": False,
        "remote_outbound_send_allowed": False,
        "hardware_control_allowed": False,
        "raw_payloads_embedded": False,
    }
