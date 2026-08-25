"""Bounded, observable background queue for candidate-only PraisonAI work."""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, Protocol
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from scout.nextgen.intelligence_gateway import (
    GatewayValidationDisposition,
    IntelligenceRequest,
    IntelligenceResponse,
    PydanticContractGateway,
    WorkspaceBinding,
)
from scout.nextgen.background_job_store import (
    BackgroundJobStoreCorrupt,
    SQLiteBackgroundIntelligenceJobStore,
)
from scout.nextgen.edge_resource_policy import (
    EdgeBackgroundResourcePolicy,
    EdgeResourceSnapshot,
)
from scout.schemas.base import NonEmptyStr, SchemaModel


class BackgroundIntelligenceJobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"


_TERMINAL_STATES = frozenset(
    {
        BackgroundIntelligenceJobState.CANCELLED,
        BackgroundIntelligenceJobState.COMPLETED,
        BackgroundIntelligenceJobState.FAILED,
    }
)


class BackgroundIntelligenceJobProgress(SchemaModel):
    schema_version: Literal["scout.praison_background_job.v0"] = (
        "scout.praison_background_job.v0"
    )
    job_id: UUID = Field(default_factory=uuid4)
    request_id: UUID
    mission_id: NonEmptyStr
    workspace_binding: WorkspaceBinding
    state: BackgroundIntelligenceJobState
    stage: NonEmptyStr
    progress_percent: int = Field(ge=0, le=100)
    queue_position: int | None = Field(default=None, ge=0)
    submitted_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cancellation_requested: bool = False
    response_available: bool = False
    error_type: str | None = None
    validation_disposition: GatewayValidationDisposition | None = None
    validation_reasons: tuple[NonEmptyStr, ...] = ()
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False

    @model_validator(mode="after")
    def validate_lifecycle(self) -> "BackgroundIntelligenceJobProgress":
        terminal = self.state in _TERMINAL_STATES
        if terminal != (self.completed_at is not None):
            raise ValueError("terminal background jobs require completed_at")
        if terminal and self.progress_percent != 100:
            raise ValueError("terminal background jobs require 100 percent progress")
        if self.response_available != (
            self.state is BackgroundIntelligenceJobState.COMPLETED
        ):
            raise ValueError("only completed background jobs expose a response")
        if (
            self.state
            in {
                BackgroundIntelligenceJobState.CANCELLING,
                BackgroundIntelligenceJobState.CANCELLED,
            }
            and not self.cancellation_requested
        ):
            raise ValueError("cancelled background jobs require a cancellation request")
        return self


class BackgroundIntelligenceQueueError(RuntimeError):
    pass


class BackgroundIntelligenceQueueClosed(BackgroundIntelligenceQueueError):
    pass


class BackgroundIntelligenceQueueFull(BackgroundIntelligenceQueueError):
    pass


class BackgroundIntelligenceJobNotFound(BackgroundIntelligenceQueueError):
    pass


class BackgroundIntelligenceJobNotReady(BackgroundIntelligenceQueueError):
    pass


class BackgroundIntelligenceJobCancelled(BackgroundIntelligenceQueueError):
    pass


class BackgroundIntelligenceJobFailed(BackgroundIntelligenceQueueError):
    pass


class BackgroundIntelligenceResultRejected(BackgroundIntelligenceQueueError):
    pass


class BackgroundIntelligenceResultStale(BackgroundIntelligenceResultRejected):
    pass


class BackgroundIntelligenceResourceUnavailable(BackgroundIntelligenceQueueError):
    pass


class _PraisonBackgroundExecutor(Protocol):
    def execute(
        self,
        request: IntelligenceRequest,
        *,
        cancellation_event: threading.Event | None = None,
        progress_callback: Callable[[str, int], None] | None = None,
    ) -> IntelligenceResponse: ...


@dataclass(frozen=True)
class _JobRecord:
    request: IntelligenceRequest
    progress: BackgroundIntelligenceJobProgress
    cancellation_event: threading.Event
    done_event: threading.Event
    response: IntelligenceResponse | None = None


class PraisonBackgroundIntelligenceQueue:
    """Run long candidate intelligence separately from safety/runtime flows."""

    def __init__(
        self,
        *,
        service: _PraisonBackgroundExecutor,
        max_queue_size: int = 16,
        job_store: SQLiteBackgroundIntelligenceJobStore | None = None,
        resource_snapshot_provider: Callable[[], EdgeResourceSnapshot] | None = None,
        resource_policy: EdgeBackgroundResourcePolicy | None = None,
    ) -> None:
        if max_queue_size < 1:
            raise ValueError("Praison background queue size must be positive")
        self._service = service
        self._job_store = job_store
        self._resource_snapshot_provider = resource_snapshot_provider
        self._resource_policy = resource_policy or EdgeBackgroundResourcePolicy()
        self._contract_gateway = PydanticContractGateway()
        self._pending: queue.Queue[UUID | None] = queue.Queue(
            maxsize=max_queue_size
        )
        self._jobs: dict[UUID, _JobRecord] = {}
        self._lock = threading.Lock()
        self._closed = False
        self._restore_jobs()
        self._worker = threading.Thread(
            target=self._run_worker,
            name="scout-praison-background",
            daemon=True,
        )
        self._worker.start()

    def __enter__(self) -> "PraisonBackgroundIntelligenceQueue":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def submit(
        self,
        request: IntelligenceRequest,
    ) -> BackgroundIntelligenceJobProgress:
        self._assert_resources_available()
        submitted_at = datetime.now(UTC)
        progress = BackgroundIntelligenceJobProgress(
            request_id=request.request_id,
            mission_id=request.mission_id,
            workspace_binding=request.workspace_binding,
            state=BackgroundIntelligenceJobState.QUEUED,
            stage="queued",
            progress_percent=0,
            queue_position=0,
            submitted_at=submitted_at,
        )
        record = _JobRecord(
            request=request,
            progress=progress,
            cancellation_event=threading.Event(),
            done_event=threading.Event(),
        )
        with self._lock:
            if self._closed:
                raise BackgroundIntelligenceQueueClosed(
                    "Praison background queue is closed"
                )
            self._jobs[progress.job_id] = record
            try:
                self._pending.put_nowait(progress.job_id)
            except queue.Full as exc:
                del self._jobs[progress.job_id]
                raise BackgroundIntelligenceQueueFull(
                    "Praison background queue is full"
                ) from exc
            self._persist(record, event_type="submitted")
        return progress

    def get_progress(self, job_id: UUID) -> BackgroundIntelligenceJobProgress:
        with self._lock:
            record = self._record(job_id)
            position = self._queue_position(job_id)
            return record.progress.model_copy(update={"queue_position": position})

    def list_progress(self) -> tuple[BackgroundIntelligenceJobProgress, ...]:
        with self._lock:
            return tuple(
                record.progress.model_copy(
                    update={"queue_position": self._queue_position(job_id)}
                )
                for job_id, record in self._jobs.items()
            )

    def cancel(self, job_id: UUID) -> BackgroundIntelligenceJobProgress:
        with self._lock:
            record = self._record(job_id)
            if record.progress.state in _TERMINAL_STATES:
                return record.progress
            record.cancellation_event.set()
            now = datetime.now(UTC)
            if record.progress.state is BackgroundIntelligenceJobState.QUEUED:
                progress = record.progress.model_copy(
                    update={
                        "state": BackgroundIntelligenceJobState.CANCELLED,
                        "stage": "cancelled",
                        "progress_percent": 100,
                        "queue_position": None,
                        "completed_at": now,
                        "cancellation_requested": True,
                    }
                )
                record.done_event.set()
            else:
                progress = record.progress.model_copy(
                    update={
                        "state": BackgroundIntelligenceJobState.CANCELLING,
                        "stage": "cancelling",
                        "queue_position": None,
                        "cancellation_requested": True,
                    }
                )
            updated = replace(record, progress=progress)
            self._jobs[job_id] = updated
            self._persist(
                updated,
                event_type=(
                    "cancelled"
                    if progress.state is BackgroundIntelligenceJobState.CANCELLED
                    else "cancelling"
                ),
            )
            return progress

    def wait(
        self,
        job_id: UUID,
        *,
        timeout_seconds: float | None = None,
    ) -> BackgroundIntelligenceJobProgress:
        with self._lock:
            done_event = self._record(job_id).done_event
        if not done_event.wait(timeout=timeout_seconds):
            raise BackgroundIntelligenceJobNotReady(
                "Praison background job did not finish before the wait timeout"
            )
        return self.get_progress(job_id)

    def result(
        self,
        job_id: UUID,
        *,
        current_binding: WorkspaceBinding,
    ) -> IntelligenceResponse:
        with self._lock:
            record = self._record(job_id)
            state = record.progress.state
            if state is BackgroundIntelligenceJobState.CANCELLED:
                raise BackgroundIntelligenceJobCancelled(
                    "Praison background candidate was cancelled and discarded"
                )
            if state is BackgroundIntelligenceJobState.FAILED:
                raise BackgroundIntelligenceJobFailed(
                    "Praison background candidate failed and was discarded"
                )
            if state is not BackgroundIntelligenceJobState.COMPLETED:
                raise BackgroundIntelligenceJobNotReady(
                    "Praison background candidate is not complete"
                )
            if record.response is None:
                raise BackgroundIntelligenceJobFailed(
                    "completed Praison background job has no response"
                )
            validation = self._contract_gateway.validate_response(
                request=record.request,
                response=record.response,
                current_binding=current_binding,
            )
            if not validation.accepted:
                self._append_event(
                    record,
                    event_type=(
                        "result_rejected_stale"
                        if validation.disposition
                        is GatewayValidationDisposition.STALE_BINDING
                        else "result_rejected"
                    ),
                )
                if validation.disposition is GatewayValidationDisposition.STALE_BINDING:
                    raise BackgroundIntelligenceResultStale(
                        "; ".join(validation.reasons)
                    )
                raise BackgroundIntelligenceResultRejected(
                    "; ".join(validation.reasons)
                )
            self._append_event(record, event_type="result_consumed")
            return record.response

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            active_ids = tuple(
                job_id
                for job_id, record in self._jobs.items()
                if record.progress.state not in _TERMINAL_STATES
            )
        for job_id in active_ids:
            self.cancel(job_id)
        self._pending.put(None)
        self._worker.join(timeout=2)

    def _run_worker(self) -> None:
        while True:
            job_id = self._pending.get()
            try:
                if job_id is None:
                    return
                try:
                    self._assert_resources_available()
                except BackgroundIntelligenceResourceUnavailable:
                    self._finish_failed(
                        job_id,
                        error_type="ResourceBackpressure",
                    )
                    continue
                record = self._start(job_id)
                if record is None:
                    continue

                def report_progress(stage: str, percent: int) -> None:
                    self._update_progress(job_id, stage=stage, percent=percent)

                try:
                    response = IntelligenceResponse.model_validate(
                        self._service.execute(
                            record.request,
                            cancellation_event=record.cancellation_event,
                            progress_callback=report_progress,
                        )
                    )
                except Exception as exc:
                    self._finish_failed(job_id, error_type=type(exc).__name__)
                else:
                    validation = self._contract_gateway.validate_response(
                        request=record.request,
                        response=response,
                        current_binding=record.request.workspace_binding,
                    )
                    if validation.accepted:
                        self._finish_response(
                            job_id,
                            response=response,
                            validation_disposition=validation.disposition,
                            validation_reasons=validation.reasons,
                        )
                    else:
                        self._finish_failed(
                            job_id,
                            error_type="ContractGatewayRejected",
                            validation_disposition=validation.disposition,
                            validation_reasons=validation.reasons,
                        )
            finally:
                self._pending.task_done()

    def _start(self, job_id: UUID) -> _JobRecord | None:
        with self._lock:
            record = self._record(job_id)
            if record.progress.state is BackgroundIntelligenceJobState.CANCELLED:
                return None
            progress = record.progress.model_copy(
                update={
                    "state": BackgroundIntelligenceJobState.RUNNING,
                    "stage": "starting",
                    "progress_percent": max(5, record.progress.progress_percent),
                    "queue_position": None,
                    "started_at": datetime.now(UTC),
                }
            )
            started = replace(record, progress=progress)
            self._jobs[job_id] = started
            self._persist(started, event_type="started")
            return started

    def _update_progress(self, job_id: UUID, *, stage: str, percent: int) -> None:
        with self._lock:
            record = self._record(job_id)
            if record.progress.state is not BackgroundIntelligenceJobState.RUNNING:
                return
            progress = record.progress.model_copy(
                update={
                    "stage": stage.strip() or "running",
                    "progress_percent": max(
                        record.progress.progress_percent,
                        min(99, max(0, percent)),
                    ),
                }
            )
            self._jobs[job_id] = replace(record, progress=progress)
            self._persist(self._jobs[job_id], event_type="progress")

    def _finish_response(
        self,
        job_id: UUID,
        *,
        response: IntelligenceResponse,
        validation_disposition: GatewayValidationDisposition,
        validation_reasons: tuple[str, ...],
    ) -> None:
        with self._lock:
            record = self._record(job_id)
            now = datetime.now(UTC)
            if record.cancellation_event.is_set():
                progress = record.progress.model_copy(
                    update={
                        "state": BackgroundIntelligenceJobState.CANCELLED,
                        "stage": "cancelled",
                        "progress_percent": 100,
                        "completed_at": now,
                        "cancellation_requested": True,
                    }
                )
                finished = replace(record, progress=progress, response=None)
            else:
                progress = record.progress.model_copy(
                    update={
                        "state": BackgroundIntelligenceJobState.COMPLETED,
                        "stage": "completed",
                        "progress_percent": 100,
                        "completed_at": now,
                        "response_available": True,
                        "validation_disposition": validation_disposition,
                        "validation_reasons": validation_reasons,
                    }
                )
                finished = replace(record, progress=progress, response=response)
            self._jobs[job_id] = finished
            self._persist(
                finished,
                event_type=(
                    "cancelled"
                    if progress.state is BackgroundIntelligenceJobState.CANCELLED
                    else "completed"
                ),
            )
            record.done_event.set()

    def _finish_failed(
        self,
        job_id: UUID,
        *,
        error_type: str,
        validation_disposition: GatewayValidationDisposition | None = None,
        validation_reasons: tuple[str, ...] = (),
    ) -> None:
        with self._lock:
            record = self._record(job_id)
            cancelled = record.cancellation_event.is_set()
            progress = record.progress.model_copy(
                update={
                    "state": (
                        BackgroundIntelligenceJobState.CANCELLED
                        if cancelled
                        else BackgroundIntelligenceJobState.FAILED
                    ),
                    "stage": "cancelled" if cancelled else "failed",
                    "progress_percent": 100,
                    "completed_at": datetime.now(UTC),
                    "cancellation_requested": cancelled,
                    "error_type": None if cancelled else error_type,
                    "validation_disposition": validation_disposition,
                    "validation_reasons": validation_reasons,
                }
            )
            self._jobs[job_id] = replace(record, progress=progress, response=None)
            self._persist(
                self._jobs[job_id],
                event_type="cancelled" if cancelled else "failed",
            )
            record.done_event.set()

    def _restore_jobs(self) -> None:
        if self._job_store is None:
            return
        for stored in self._job_store.load_jobs():
            try:
                progress = BackgroundIntelligenceJobProgress.model_validate_json(
                    stored.progress_json
                )
            except Exception as exc:
                raise BackgroundJobStoreCorrupt(
                    "background intelligence store contains invalid job progress"
                ) from exc
            done_event = threading.Event()
            if progress.state not in _TERMINAL_STATES:
                progress = progress.model_copy(
                    update={
                        "state": BackgroundIntelligenceJobState.FAILED,
                        "stage": "restart_interrupted",
                        "progress_percent": 100,
                        "queue_position": None,
                        "completed_at": datetime.now(UTC),
                        "response_available": False,
                        "error_type": "ProcessRestartInterrupted",
                    }
                )
                stored_response = None
                event_type = "restart_interrupted"
            else:
                stored_response = stored.response
                event_type = None
            done_event.set()
            record = _JobRecord(
                request=stored.request,
                progress=progress,
                cancellation_event=threading.Event(),
                done_event=done_event,
                response=stored_response,
            )
            self._jobs[progress.job_id] = record
            if event_type is not None:
                self._persist(record, event_type=event_type)

    def _assert_resources_available(self) -> None:
        if self._resource_snapshot_provider is None:
            return
        try:
            snapshot = self._resource_snapshot_provider()
        except Exception as exc:
            raise BackgroundIntelligenceResourceUnavailable(
                f"edge resource telemetry unavailable: {type(exc).__name__}"
            ) from exc
        reasons = self._resource_policy.rejection_reasons(snapshot)
        if reasons:
            raise BackgroundIntelligenceResourceUnavailable("; ".join(reasons))

    def _persist(self, record: _JobRecord, *, event_type: str) -> None:
        if self._job_store is None:
            return
        self._job_store.save_job(
            request=record.request,
            progress=record.progress,
            response=record.response,
            event_type=event_type,
        )

    def _append_event(self, record: _JobRecord, *, event_type: str) -> None:
        if self._job_store is None:
            return
        self._job_store.append_event(
            job_id=record.progress.job_id,
            event_type=event_type,
            state=record.progress.state.value,
            stage=record.progress.stage,
        )

    def _record(self, job_id: UUID) -> _JobRecord:
        try:
            return self._jobs[job_id]
        except KeyError as exc:
            raise BackgroundIntelligenceJobNotFound(
                f"unknown Praison background job: {job_id}"
            ) from exc

    def _queue_position(self, job_id: UUID) -> int | None:
        record = self._record(job_id)
        if record.progress.state is not BackgroundIntelligenceJobState.QUEUED:
            return None
        queued = [
            candidate_id
            for candidate_id, candidate in self._jobs.items()
            if candidate.progress.state is BackgroundIntelligenceJobState.QUEUED
        ]
        return queued.index(job_id)


__all__ = [
    "BackgroundIntelligenceJobCancelled",
    "BackgroundIntelligenceJobFailed",
    "BackgroundIntelligenceJobNotFound",
    "BackgroundIntelligenceJobNotReady",
    "BackgroundIntelligenceJobProgress",
    "BackgroundIntelligenceJobState",
    "BackgroundIntelligenceQueueClosed",
    "BackgroundIntelligenceQueueError",
    "BackgroundIntelligenceQueueFull",
    "BackgroundIntelligenceResourceUnavailable",
    "BackgroundIntelligenceResultRejected",
    "BackgroundIntelligenceResultStale",
    "PraisonBackgroundIntelligenceQueue",
]
