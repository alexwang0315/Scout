from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from runtime_debug_models import RuntimeDebugEvent
from spatial_imprint_models import SpatialImprintTriggerDryRunReport
from spatial_imprint_store import SpatialImprintStoreDocument, load_spatial_imprint_store


def load_spatial_imprint_debug_events(
    *,
    store_path: str | Path | None = None,
    trigger_report_path: str | Path | None = None,
    sequence_offset: int = 0,
    limit: int | None = None,
) -> list[RuntimeDebugEvent]:
    events: list[RuntimeDebugEvent] = []
    events.extend(
        _load_store_events(
            store_path,
            sequence_offset=sequence_offset,
        )
    )
    events.extend(
        _load_trigger_report_events(
            trigger_report_path,
            sequence_offset=sequence_offset + len(events),
        )
    )
    if limit is not None and limit >= 0:
        events = events[-limit:]
    return events


def _load_store_events(
    store_path: str | Path | None,
    *,
    sequence_offset: int,
) -> list[RuntimeDebugEvent]:
    if store_path is None:
        return []
    path = Path(store_path)
    if not path.exists():
        return []
    try:
        store = load_spatial_imprint_store(path)
    except Exception as exc:  # pragma: no cover - exercised through API behavior only.
        return [
            _projection_error_event(
                sequence=sequence_offset + 1,
                source_path=str(path),
                summary="Spatial imprint store projection failed.",
                error=exc,
            )
        ]
    return spatial_imprint_store_to_debug_events(
        store,
        source_path=str(path),
        sequence_offset=sequence_offset,
    )


def _load_trigger_report_events(
    trigger_report_path: str | Path | None,
    *,
    sequence_offset: int,
) -> list[RuntimeDebugEvent]:
    if trigger_report_path is None:
        return []
    path = Path(trigger_report_path)
    if not path.exists():
        return []
    try:
        report = SpatialImprintTriggerDryRunReport.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except Exception as exc:  # pragma: no cover - exercised through API behavior only.
        return [
            _projection_error_event(
                sequence=sequence_offset + 1,
                source_path=str(path),
                summary="Spatial imprint trigger report projection failed.",
                error=exc,
            )
        ]
    return spatial_imprint_trigger_report_to_debug_events(
        report,
        source_path=str(path),
        sequence_offset=sequence_offset,
    )


def spatial_imprint_store_to_debug_events(
    store: SpatialImprintStoreDocument,
    *,
    source_path: str = "spatial_imprint_store",
    sequence_offset: int = 0,
) -> list[RuntimeDebugEvent]:
    imprints_by_id = {imprint.imprint_id: imprint for imprint in store.imprints}
    events: list[RuntimeDebugEvent] = []
    for index, record in enumerate(store.audit_log, start=1):
        imprint = imprints_by_id.get(record.imprint_id)
        events.append(
            RuntimeDebugEvent(
                event_id=f"debug_event.spatial_imprint_store.{_safe_token(record.audit_id)}",
                session_id=f"spatial_imprint_store.{_safe_token(store.trip_id)}",
                mission_id=store.trip_id,
                timestamp=record.acted_at,
                sequence=sequence_offset + index,
                kind="spatial_imprint_store_updated",
                source="spatial_imprint_store",
                phase="phase35",
                severity="info",
                subject_ref=record.imprint_id,
                correlation_refs=[record.audit_id],
                summary=f"Spatial imprint {record.action}: {record.imprint_id}",
                payload={
                    "artifact_kind": "spatial_imprint_store_audit",
                    "trip_id": store.trip_id,
                    "action": record.action,
                    "imprint_id": record.imprint_id,
                    "imprint_label": imprint.label if imprint else None,
                    "imprint_kind": str(imprint.kind) if imprint else None,
                    "imprint_severity": str(imprint.severity) if imprint else None,
                    "actor_ref": record.actor_ref,
                    "acted_at": record.acted_at,
                    "reason": record.reason,
                    "previous_lifecycle": record.previous_lifecycle,
                    "new_lifecycle": record.new_lifecycle,
                    "store_counts": store.counts.model_dump(mode="json"),
                    "boundary": record.boundary.model_dump(mode="json"),
                    "source_path": source_path,
                    "evidence_type": "spatial_imprint_store_audit",
                    "runtime_safety_truth": False,
                    "phase1_safety_mutation_allowed": False,
                    "live_safety_api_calls_allowed": False,
                    "remote_outbound_send_allowed": False,
                    "hardware_control_allowed": False,
                },
            )
        )
    return events


def spatial_imprint_trigger_report_to_debug_events(
    report: SpatialImprintTriggerDryRunReport,
    *,
    source_path: str = "spatial_imprint_trigger_dry_run",
    sequence_offset: int = 0,
) -> list[RuntimeDebugEvent]:
    events: list[RuntimeDebugEvent] = []
    for index, trigger_event in enumerate(report.events, start=1):
        events.append(
            RuntimeDebugEvent(
                event_id=f"debug_event.spatial_imprint_trigger.{_safe_token(trigger_event.event_id)}",
                session_id=(
                    f"spatial_imprint_trigger.{_safe_token(report.trip_id)}."
                    f"{_safe_token(report.client_id)}"
                ),
                mission_id=report.trip_id,
                timestamp=trigger_event.triggered_at,
                sequence=sequence_offset + index,
                kind="spatial_imprint_trigger_event",
                source="spatial_imprint_trigger",
                phase="phase35",
                severity="warning" if trigger_event.status == "triggered" else "info",
                subject_ref=trigger_event.imprint_id,
                correlation_refs=[trigger_event.event_id],
                summary=f"Spatial imprint {trigger_event.status}: {trigger_event.imprint_id}",
                payload={
                    "artifact_kind": "spatial_imprint_trigger_event",
                    "trip_id": report.trip_id,
                    "client_id": report.client_id,
                    "observed_at": report.observed_at,
                    "imprint_id": trigger_event.imprint_id,
                    "status": trigger_event.status,
                    "suppressed": trigger_event.suppressed,
                    "suppression_reason": trigger_event.suppression_reason,
                    "matched_predicates": trigger_event.matched_predicates,
                    "failed_predicates": [
                        item.model_dump(mode="json")
                        for item in trigger_event.failed_predicates
                    ],
                    "queued_payload": (
                        trigger_event.queued_payload.model_dump(mode="json")
                        if trigger_event.queued_payload
                        else None
                    ),
                    "report_counts": dict(report.counts),
                    "boundary": trigger_event.boundary.model_dump(mode="json"),
                    "source_path": source_path,
                    "evidence_type": "spatial_imprint_trigger_dry_run",
                    "runtime_safety_truth": False,
                    "phase1_safety_mutation_allowed": False,
                    "live_safety_api_calls_allowed": False,
                    "remote_outbound_send_allowed": False,
                    "hardware_control_allowed": False,
                },
            )
        )
    return events


def _projection_error_event(
    *,
    sequence: int,
    source_path: str,
    summary: str,
    error: Exception,
) -> RuntimeDebugEvent:
    return RuntimeDebugEvent(
        event_id=f"debug_event.spatial_imprint_projection_error.{sequence:06d}",
        session_id="spatial_imprint_projection.error",
        mission_id=None,
        timestamp="1970-01-01T00:00:00Z",
        sequence=sequence,
        kind="spatial_imprint_projection_error",
        source="spatial_imprint_debug_projection",
        phase="phase35",
        severity="error",
        summary=summary,
        payload={
            "source_path": source_path,
            "error_type": type(error).__name__,
            "error": str(error),
            "runtime_safety_truth": False,
            "phase1_safety_mutation_allowed": False,
            "live_safety_api_calls_allowed": False,
            "remote_outbound_send_allowed": False,
            "hardware_control_allowed": False,
        },
    )


def _safe_token(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9_.:-]+", "_", str(value))
