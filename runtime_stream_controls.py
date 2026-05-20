from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from runtime_input_admission import RuntimeInputAdmissionState


class RuntimeStreamControlModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RuntimeStreamControlStatus(StrEnum):
    OBSERVING = "observing"
    PAUSED = "paused"
    ENDED = "ended"


class RuntimeStreamControlAction(StrEnum):
    PAUSE = "pause"
    RESUME = "resume"
    END = "end"
    DRAIN_QUEUE = "drain_queue"


class RuntimeStreamControlRequest(RuntimeStreamControlModel):
    operator_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class RuntimeStreamControlBoundary(RuntimeStreamControlModel):
    local_control_only: Literal[True] = True
    raw_payload_embedded: Literal[False] = False
    controls_device_hardware: Literal[False] = False
    calls_safety_api: Literal[False] = False
    incident_bridge_enabled: Literal[False] = False
    remote_notifications_enabled: Literal[False] = False
    phase2_writeback_count: Literal[0] = 0
    notes: list[str] = Field(
        default_factory=lambda: [
            "Runtime Stream Controls / 串流操作控制 are local operator controls only.",
            "Controls do not stop device hardware streams or send remote notifications.",
            "Controls store action summaries and never embed raw observation payloads.",
        ]
    )


class RuntimeStreamControlRecord(RuntimeStreamControlModel):
    artifact_kind: Literal["runtime_stream_control_record"] = (
        "runtime_stream_control_record"
    )
    action: RuntimeStreamControlAction
    status_before: RuntimeStreamControlStatus
    status_after: RuntimeStreamControlStatus
    operator_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    recorded_at: str = Field(min_length=1)
    queue_depth_before: int = Field(default=0, ge=0)
    queue_depth_after: int = Field(default=0, ge=0)
    boundary: RuntimeStreamControlBoundary = Field(
        default_factory=RuntimeStreamControlBoundary
    )

    @model_validator(mode="after")
    def enforce_control_boundary(self) -> "RuntimeStreamControlRecord":
        if self.boundary.raw_payload_embedded:
            raise ValueError("runtime stream controls must not embed raw payload")
        if self.boundary.controls_device_hardware:
            raise ValueError("runtime stream controls must not control hardware")
        if self.boundary.incident_bridge_enabled:
            raise ValueError("runtime stream controls must not enable incident bridge")
        if self.boundary.phase2_writeback_count:
            raise ValueError("runtime stream controls must not write Phase 2")
        return self


class RuntimeStreamControlSnapshot(RuntimeStreamControlModel):
    artifact_kind: Literal["runtime_stream_control_snapshot"] = (
        "runtime_stream_control_snapshot"
    )
    status: RuntimeStreamControlStatus
    record_count: int = Field(ge=0)
    records: list[RuntimeStreamControlRecord]
    boundary: RuntimeStreamControlBoundary = Field(
        default_factory=RuntimeStreamControlBoundary
    )


class RuntimeStreamControlResult(RuntimeStreamControlModel):
    status: Literal["accepted"] = "accepted"
    action: RuntimeStreamControlAction
    snapshot_after: RuntimeStreamControlSnapshot
    record: RuntimeStreamControlRecord


class RuntimeStreamControlStore:
    def __init__(self) -> None:
        self._status = RuntimeStreamControlStatus.OBSERVING
        self._records: list[RuntimeStreamControlRecord] = []

    @property
    def status(self) -> RuntimeStreamControlStatus:
        return self._status

    def pause(self, *, operator_id: str, reason: str) -> RuntimeStreamControlResult:
        self._require_status(RuntimeStreamControlStatus.OBSERVING, action="pause")
        return self._transition(
            RuntimeStreamControlAction.PAUSE,
            RuntimeStreamControlStatus.PAUSED,
            operator_id=operator_id,
            reason=reason,
        )

    def resume(self, *, operator_id: str, reason: str) -> RuntimeStreamControlResult:
        self._require_status(RuntimeStreamControlStatus.PAUSED, action="resume")
        return self._transition(
            RuntimeStreamControlAction.RESUME,
            RuntimeStreamControlStatus.OBSERVING,
            operator_id=operator_id,
            reason=reason,
        )

    def end(self, *, operator_id: str, reason: str) -> RuntimeStreamControlResult:
        if self._status == RuntimeStreamControlStatus.ENDED:
            raise ValueError("runtime stream is terminal")
        return self._transition(
            RuntimeStreamControlAction.END,
            RuntimeStreamControlStatus.ENDED,
            operator_id=operator_id,
            reason=reason,
        )

    def drain_queue(
        self,
        state: RuntimeInputAdmissionState,
        *,
        operator_id: str,
        reason: str,
    ) -> RuntimeStreamControlRecord:
        self._reject_terminal()
        queue_depth_before = _queue_depth(state)
        state.disconnected_queue_keys.clear()
        state.backpressure_queue_keys.clear()
        state.latest_retained_key_by_stream.clear()
        record = RuntimeStreamControlRecord(
            action=RuntimeStreamControlAction.DRAIN_QUEUE,
            status_before=self._status,
            status_after=self._status,
            operator_id=operator_id,
            reason=reason,
            recorded_at=_now(),
            queue_depth_before=queue_depth_before,
            queue_depth_after=_queue_depth(state),
        )
        self._records.append(record)
        return record

    def snapshot(self) -> RuntimeStreamControlSnapshot:
        return RuntimeStreamControlSnapshot(
            status=self._status,
            record_count=len(self._records),
            records=[record.model_copy(deep=True) for record in self._records],
        )

    def reject_reason_for_observation(self) -> str | None:
        if self._status == RuntimeStreamControlStatus.PAUSED:
            return "runtime_stream_paused"
        if self._status == RuntimeStreamControlStatus.ENDED:
            return "runtime_stream_ended"
        return None

    def _transition(
        self,
        action: RuntimeStreamControlAction,
        next_status: RuntimeStreamControlStatus,
        *,
        operator_id: str,
        reason: str,
    ) -> RuntimeStreamControlResult:
        self._reject_terminal(allow_end=action == RuntimeStreamControlAction.END)
        status_before = self._status
        self._status = next_status
        record = RuntimeStreamControlRecord(
            action=action,
            status_before=status_before,
            status_after=next_status,
            operator_id=operator_id,
            reason=reason,
            recorded_at=_now(),
        )
        self._records.append(record)
        return RuntimeStreamControlResult(
            action=action,
            snapshot_after=self.snapshot(),
            record=record,
        )

    def _require_status(
        self,
        expected: RuntimeStreamControlStatus,
        *,
        action: str,
    ) -> None:
        self._reject_terminal()
        if self._status != expected:
            raise ValueError(
                f"runtime stream {action} requires {expected.value} status"
            )

    def _reject_terminal(self, *, allow_end: bool = False) -> None:
        if self._status == RuntimeStreamControlStatus.ENDED and not allow_end:
            raise ValueError("runtime stream is terminal")


def _queue_depth(state: RuntimeInputAdmissionState) -> int:
    return len(state.disconnected_queue_keys) + len(state.backpressure_queue_keys)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
