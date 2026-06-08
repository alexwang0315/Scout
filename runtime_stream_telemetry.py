from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from runtime_input_admission import RuntimeInputAdmissionState
from runtime_stream_policy import RuntimeStreamTransportKind


class RuntimeStreamTelemetryModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RuntimeStreamConnectionStatus(StrEnum):
    IDLE = "idle"
    CONNECTED = "connected"
    CLOSED = "closed"


class RuntimeStreamTelemetryStatus(StrEnum):
    IDLE = "idle"
    OBSERVING = "observing"


class RuntimeStreamTelemetryBoundary(RuntimeStreamTelemetryModel):
    telemetry_only: Literal[True] = True
    raw_payload_embedded: Literal[False] = False
    incident_bridge_enabled: Literal[False] = False
    remote_notifications_enabled: Literal[False] = False
    phase2_writeback_count: Literal[0] = 0
    notes: list[str] = Field(
        default_factory=lambda: [
            "Runtime Stream Telemetry / 串流狀態遙測 records status and counters only.",
            "Telemetry records admission summaries but does not embed raw observation payloads.",
            "Telemetry does not enable incident bridge notifications or write Phase 2 Brain state.",
        ]
    )


class RuntimeStreamAdmissionStateSummary(RuntimeStreamTelemetryModel):
    seen_dedupe_key_count: int = Field(ge=0)
    disconnected_queue_depth: int = Field(ge=0)
    backpressure_queue_depth: int = Field(ge=0)
    latest_retained_stream_count: int = Field(ge=0)


class RuntimeStreamTelemetryTotals(RuntimeStreamTelemetryModel):
    accepted_count: int = Field(default=0, ge=0)
    rejected_count: int = Field(default=0, ge=0)
    queued_count: int = Field(default=0, ge=0)
    active_websocket_connections: int = Field(default=0, ge=0)


class RuntimeStreamSurfaceTelemetry(RuntimeStreamTelemetryModel):
    transport: RuntimeStreamTransportKind
    connection_status: RuntimeStreamConnectionStatus = RuntimeStreamConnectionStatus.IDLE
    accepted_count: int = Field(default=0, ge=0)
    rejected_count: int = Field(default=0, ge=0)
    queued_count: int = Field(default=0, ge=0)
    last_admission_status: str | None = None
    last_rejection_reason: str | None = None
    last_sequence_no: int | None = Field(default=None, ge=0)
    last_device_id: str | None = None
    last_source_id: str | None = None
    last_payload_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    last_seen_at: str | None = None
    queue_depth: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def enforce_no_negative_counts(self) -> "RuntimeStreamSurfaceTelemetry":
        if self.rejected_count and not self.last_rejection_reason:
            raise ValueError("rejected stream telemetry requires a rejection reason")
        return self


class RuntimeStreamTelemetrySnapshot(RuntimeStreamTelemetryModel):
    artifact_kind: Literal["runtime_stream_telemetry_snapshot"] = (
        "runtime_stream_telemetry_snapshot"
    )
    status: RuntimeStreamTelemetryStatus
    transport_surfaces: dict[str, RuntimeStreamSurfaceTelemetry]
    totals: RuntimeStreamTelemetryTotals
    admission_state: RuntimeStreamAdmissionStateSummary
    boundary: RuntimeStreamTelemetryBoundary = Field(
        default_factory=RuntimeStreamTelemetryBoundary
    )

    @model_validator(mode="after")
    def enforce_telemetry_boundary(self) -> "RuntimeStreamTelemetrySnapshot":
        if self.boundary.raw_payload_embedded:
            raise ValueError("runtime stream telemetry must not embed raw payload")
        if self.boundary.incident_bridge_enabled:
            raise ValueError("runtime stream telemetry must not enable incident bridge")
        if self.boundary.phase2_writeback_count:
            raise ValueError("runtime stream telemetry must not write Phase 2")
        return self


class RuntimeStreamTelemetryStore:
    def __init__(self) -> None:
        self._surfaces: dict[RuntimeStreamTransportKind, RuntimeStreamSurfaceTelemetry] = {
            RuntimeStreamTransportKind.HTTP_PUSH: RuntimeStreamSurfaceTelemetry(
                transport=RuntimeStreamTransportKind.HTTP_PUSH
            ),
            RuntimeStreamTransportKind.WEBSOCKET: RuntimeStreamSurfaceTelemetry(
                transport=RuntimeStreamTransportKind.WEBSOCKET
            ),
        }
        self._active_websocket_connections = 0

    def record_websocket_connected(self) -> None:
        self._active_websocket_connections += 1
        self._surface(RuntimeStreamTransportKind.WEBSOCKET).connection_status = (
            RuntimeStreamConnectionStatus.CONNECTED
        )

    def record_websocket_disconnected(self) -> None:
        self._active_websocket_connections = max(
            0,
            self._active_websocket_connections - 1,
        )
        self._surface(RuntimeStreamTransportKind.WEBSOCKET).connection_status = (
            RuntimeStreamConnectionStatus.CLOSED
        )

    def record_accepted(
        self,
        transport: RuntimeStreamTransportKind | str,
        response: dict[str, Any],
    ) -> None:
        surface = self._surface(transport)
        admission = response.get("admission", {})
        surface.accepted_count += 1
        surface.last_admission_status = _admission_value(admission, "status")
        surface.last_rejection_reason = surface.last_rejection_reason
        surface.last_sequence_no = _optional_int(admission.get("sequence_no"))
        surface.last_device_id = _admission_value(admission, "device_id")
        surface.last_source_id = _admission_value(admission, "source_id")
        surface.last_payload_sha256 = _admission_value(admission, "payload_sha256")
        surface.queue_depth = _optional_int(admission.get("queue_depth")) or 0
        surface.last_seen_at = _now()

    def record_rejected(
        self,
        transport: RuntimeStreamTransportKind | str,
        *,
        status_code: int,
        detail: Any,
    ) -> None:
        surface = self._surface(transport)
        reason = _rejection_reason(detail)
        admission_status = _rejection_admission_status(detail)
        if status_code == 202 or (admission_status and admission_status.startswith("queued_")):
            surface.queued_count += 1
        else:
            surface.rejected_count += 1
        if admission_status is not None:
            surface.last_admission_status = admission_status
        surface.last_rejection_reason = reason
        surface.queue_depth = _rejection_queue_depth(detail)
        surface.last_seen_at = _now()

    def snapshot(
        self,
        *,
        admission_state: RuntimeInputAdmissionState | None = None,
    ) -> RuntimeStreamTelemetrySnapshot:
        surfaces = {
            transport.value: surface.model_copy(deep=True)
            for transport, surface in self._surfaces.items()
        }
        accepted_count = sum(surface.accepted_count for surface in surfaces.values())
        rejected_count = sum(surface.rejected_count for surface in surfaces.values())
        queued_count = sum(surface.queued_count for surface in surfaces.values())
        status = (
            RuntimeStreamTelemetryStatus.OBSERVING
            if accepted_count
            or rejected_count
            or queued_count
            or self._active_websocket_connections
            else RuntimeStreamTelemetryStatus.IDLE
        )
        return RuntimeStreamTelemetrySnapshot(
            status=status,
            transport_surfaces=surfaces,
            totals=RuntimeStreamTelemetryTotals(
                accepted_count=accepted_count,
                rejected_count=rejected_count,
                queued_count=queued_count,
                active_websocket_connections=self._active_websocket_connections,
            ),
            admission_state=_admission_state_summary(admission_state),
        )

    def _surface(
        self,
        transport: RuntimeStreamTransportKind | str,
    ) -> RuntimeStreamSurfaceTelemetry:
        return self._surfaces[RuntimeStreamTransportKind(transport)]


def _admission_state_summary(
    state: RuntimeInputAdmissionState | None,
) -> RuntimeStreamAdmissionStateSummary:
    if state is None:
        return RuntimeStreamAdmissionStateSummary(
            seen_dedupe_key_count=0,
            disconnected_queue_depth=0,
            backpressure_queue_depth=0,
            latest_retained_stream_count=0,
        )
    return RuntimeStreamAdmissionStateSummary(
        seen_dedupe_key_count=len(state.seen_dedupe_keys),
        disconnected_queue_depth=len(state.disconnected_queue_keys),
        backpressure_queue_depth=len(state.backpressure_queue_keys),
        latest_retained_stream_count=len(state.latest_retained_key_by_stream),
    )


def _admission_value(admission: dict[str, Any], key: str) -> str | None:
    value = admission.get(key)
    return value if isinstance(value, str) else None


def _rejection_reason(detail: Any) -> str:
    if isinstance(detail, dict):
        reason = detail.get("reason") or detail.get("admission_status") or detail.get("status")
        return str(reason) if reason else "runtime_stream_rejected"
    if isinstance(detail, list):
        return "runtime_stream_validation_error"
    return str(detail) if detail else "runtime_stream_rejected"


def _rejection_admission_status(detail: Any) -> str | None:
    if not isinstance(detail, dict):
        return None
    status = detail.get("admission_status") or detail.get("status")
    return status if isinstance(status, str) else None


def _rejection_queue_depth(detail: Any) -> int:
    if not isinstance(detail, dict):
        return 0
    return _optional_int(detail.get("queue_depth")) or 0


def _optional_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
