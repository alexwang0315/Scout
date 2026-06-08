from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from assistant_models import AssistantSourceRef, AssistantSurface, ScoutAssistantQuery
from scout_live_navigation_snapshot_adapter import live_navigation_snapshot_from_sensor_records
from scout_live_navigation_snapshot_route_match import (
    enrich_live_navigation_snapshot_with_route_match,
)
from scout_live_navigation_state_tool import LIVE_NAVIGATION_REQUIRED_FIELDS


LIVE_NAVIGATION_EVIDENCE_LOADER_ID = (
    "assistant_context.live_navigation_snapshot.evidence_loader.v0"
)
LIVE_NAVIGATION_EVIDENCE_SOURCE_ID = "assistant_context.live_navigation_snapshot.evidence"

SENSORLOGGER_RAW_JSONL = "sensorlogger_mqtt_raw.jsonl"
SENSORLOGGER_FILTER_OUTPUTS_JSONL = "sensorlogger_mqtt_filter_outputs.jsonl"
_PROJECT_ROUTE_PATH_KEYS = (
    "live_navigation_route_path",
    "runtime_route_path",
    "route_path",
    "gpx_route_path",
    "route_gpx_path",
)
_HANDOFF_ROUTE_PATH_KEYS = ("path", "local_path", "file_path", "source_path", "uri")


def augment_sources_with_live_navigation_snapshot_evidence(
    query: ScoutAssistantQuery,
    *,
    sources: list[AssistantSourceRef],
    evidence_dir: Path | str | None,
    project_root: Path | str | None = None,
    route_path: Path | str | None = None,
    limit: int = 50,
) -> list[AssistantSourceRef]:
    """Prepend a read-only live navigation snapshot source loaded from evidence files."""

    if query.surface != AssistantSurface.PRETRIP or evidence_dir is None:
        return sources
    source = build_live_navigation_snapshot_source_from_evidence_dir(
        evidence_dir,
        project_root=project_root,
        route_path=route_path,
        limit=limit,
    )
    if source is None:
        return sources
    return [source, *sources]


def build_live_navigation_snapshot_source_from_evidence_dir(
    evidence_dir: Path | str,
    *,
    project_root: Path | str | None = None,
    route_path: Path | str | None = None,
    limit: int = 50,
) -> AssistantSourceRef | None:
    root = Path(evidence_dir)
    records, source_report = _load_sensorlogger_evidence_records(root, limit=limit)
    snapshot = live_navigation_snapshot_from_sensor_records(
        records,
        default_source="sensorlogger_mqtt_evidence",
    )
    if not snapshot:
        return None
    resolved_route_path, route_path_report = _resolve_route_path(
        project_root=Path(project_root) if project_root is not None else None,
        explicit_route_path=route_path,
    )
    route_match_report = None
    if project_root is not None or route_path is not None:
        snapshot, route_match_report = enrich_live_navigation_snapshot_with_route_match(
            snapshot,
            route_path=resolved_route_path,
            project_root=project_root,
        )
    missing_fields = [
        field for field in LIVE_NAVIGATION_REQUIRED_FIELDS if _missing(snapshot.get(field))
    ]
    if route_path_report is not None:
        source_report.append(route_path_report)
    if route_match_report is not None:
        source_report.append(route_match_report)
    return AssistantSourceRef(
        source_id=LIVE_NAVIGATION_EVIDENCE_SOURCE_ID,
        source_path=str(root),
        evidence_type="live_navigation_snapshot",
        selected=True,
        context_summary={
            "resolver": LIVE_NAVIGATION_EVIDENCE_LOADER_ID,
            "live_navigation_snapshot": snapshot,
            "field_names": sorted(snapshot),
            "missing_fields": missing_fields,
            "record_count": len(records),
            "source_report": source_report,
            "read_only": True,
            "runtime_safety_truth": False,
            "raw_payloads_embedded": False,
            "boundary": _closed_boundary(),
        },
    )


def _load_sensorlogger_evidence_records(
    evidence_dir: Path,
    *,
    limit: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    source_report: list[dict[str, Any]] = []

    raw_path = evidence_dir / SENSORLOGGER_RAW_JSONL
    raw_lines = _read_jsonl_tail(raw_path, limit=limit)
    loaded_raw = 0
    for raw_record in raw_lines:
        if raw_record.get("parse_status") != "accepted":
            continue
        raw_payload_text = raw_record.get("raw_payload_text")
        if not isinstance(raw_payload_text, str):
            continue
        try:
            message = json.loads(raw_payload_text)
        except json.JSONDecodeError:
            continue
        if not isinstance(message, dict):
            continue
        records.append(
            {
                "source": "sensorlogger_mqtt_raw",
                "source_adapter": raw_record.get("source_adapter"),
                "ingress_transport": raw_record.get("ingress_transport"),
                "received_at": raw_record.get("received_at"),
                "payload": message,
            }
        )
        loaded_raw += 1
    source_report.append(_source_status(raw_path, loaded_count=loaded_raw))

    output_path = evidence_dir / SENSORLOGGER_FILTER_OUTPUTS_JSONL
    output_lines = _read_jsonl_tail(output_path, limit=limit)
    loaded_outputs = 0
    for output_record in output_lines:
        if not _is_navigation_filter_output(output_record):
            continue
        records.append(output_record)
        loaded_outputs += 1
    source_report.append(_source_status(output_path, loaded_count=loaded_outputs))

    return records, source_report


def _resolve_route_path(
    *,
    project_root: Path | None,
    explicit_route_path: Path | str | None,
) -> tuple[Path | None, dict[str, Any] | None]:
    if explicit_route_path is not None:
        path = Path(explicit_route_path)
        return (
            path,
            {
                "source_kind": "live_navigation_route_path_resolution",
                "status": "explicit_route_path",
                "source_path": str(path),
                "exists": path.exists(),
                "read_only": True,
                "runtime_safety_truth": False,
                "raw_payloads_embedded": False,
            },
        )
    if project_root is None:
        return None, None

    project_path = project_root / "project.json"
    project = _read_json_object(project_path)
    if not project:
        return (
            None,
            {
                "source_kind": "live_navigation_route_path_resolution",
                "status": "missing_project_manifest",
                "source_path": str(project_path),
                "read_only": True,
                "runtime_safety_truth": False,
                "raw_payloads_embedded": False,
            },
        )

    for key in _PROJECT_ROUTE_PATH_KEYS:
        value = project.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        path = _project_relative_path(project_root, value)
        return (
            path if path.exists() else None,
            {
                "source_kind": "live_navigation_route_path_resolution",
                "status": "project_route_path_found" if path.exists() else "project_route_path_missing",
                "source_path": str(path),
                "project_key": key,
                "exists": path.exists(),
                "read_only": True,
                "runtime_safety_truth": False,
                "raw_payloads_embedded": False,
            },
        )

    handoff_ref = project.get("runtime_handoff_metadata_ref")
    handoff_path = (
        _project_relative_path(project_root, handoff_ref)
        if isinstance(handoff_ref, str) and handoff_ref.strip()
        else None
    )
    handoff = _read_json_object(handoff_path) if handoff_path is not None else {}
    route_refs = _route_source_refs(handoff)
    for route_ref in route_refs:
        for key in _HANDOFF_ROUTE_PATH_KEYS:
            value = route_ref.get(key)
            if not isinstance(value, str) or not value.strip():
                continue
            path = _project_relative_path(project_root, value)
            if path.exists():
                return (
                    path,
                    {
                        "source_kind": "live_navigation_route_path_resolution",
                        "status": "runtime_handoff_route_path_found",
                        "source_path": str(path),
                        "handoff_path": str(handoff_path) if handoff_path is not None else None,
                        "handoff_key": key,
                        "read_only": True,
                        "runtime_safety_truth": False,
                        "raw_payloads_embedded": False,
                    },
                )

    return (
        None,
        {
            "source_kind": "live_navigation_route_path_resolution",
            "status": "missing_route_path",
            "source_path": str(handoff_path) if handoff_path is not None else str(project_path),
            "route_source_refs": route_refs,
            "read_only": True,
            "runtime_safety_truth": False,
            "raw_payloads_embedded": False,
        },
    )


def _read_jsonl_tail(path: Path, *, limit: int) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    line_limit = max(int(limit), 0)
    lines = path.read_text(encoding="utf-8").splitlines()
    if line_limit:
        lines = lines[-line_limit:]
    records: list[dict[str, Any]] = []
    for line in lines:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            records.append(payload)
    return records


def _read_json_object(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _project_relative_path(project_root: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return project_root / path


def _route_source_refs(handoff: dict[str, Any]) -> list[dict[str, Any]]:
    refs = handoff.get("route_source_refs")
    if not isinstance(refs, list):
        return []
    bounded: list[dict[str, Any]] = []
    for ref in refs[:8]:
        if not isinstance(ref, dict):
            continue
        bounded.append(
            {
                key: value
                for key, value in ref.items()
                if key
                in {
                    "artifact_id",
                    "kind",
                    "media_type",
                    "source_ref",
                    "sha256",
                    "size_bytes",
                    *_HANDOFF_ROUTE_PATH_KEYS,
                }
            }
        )
    return bounded


def _is_navigation_filter_output(record: dict[str, Any]) -> bool:
    return (
        record.get("route_target") == "navigation.ins_dr"
        or record.get("output_kind") == "navigation_estimate"
    )


def _source_status(path: Path, *, loaded_count: int) -> dict[str, Any]:
    return {
        "source_path": str(path),
        "status": "loaded" if path.exists() else "missing",
        "loaded_count": loaded_count,
        "raw_payloads_embedded": False,
    }


def _missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return not value
    return False


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
