"""Read-only Dashboard projection for candidate intelligence jobs."""

from __future__ import annotations

import hashlib
import os
import sqlite3
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Mapping, Protocol
from urllib.parse import quote
from uuid import UUID

from pydantic import Field

from scout.nextgen.background_job_store import BackgroundIntelligenceJobEvent
from scout.nextgen.intelligence_gateway import (
    IntelligenceRequest,
    IntelligenceResponse,
    IntelligenceTaskType,
    ModelExecutionRecord,
    WorkspaceBinding,
)
from scout.nextgen.praison_background_queue import (
    BackgroundIntelligenceJobProgress,
    BackgroundIntelligenceJobState,
)
from scout.schemas.base import NonEmptyStr, SchemaModel


TelemetryStatus = Literal["ready", "unavailable", "degraded"]
ValidationResult = Literal[
    "accepted_candidate",
    "rejected",
    "stale_binding",
    "capability_violation",
    "not_validated",
]


class IntelligenceCapabilityTelemetry(SchemaModel):
    grant_id: UUID
    allowed_capabilities: tuple[NonEmptyStr, ...]
    denied_capabilities: tuple[NonEmptyStr, ...]
    expires_at: datetime
    max_runtime_seconds: int | None = None
    max_model_requests: int = Field(ge=10)
    max_tool_calls: int = Field(ge=10)
    issued_by: NonEmptyStr
    provenance_ref: NonEmptyStr
    fail_closed: Literal[True] = True


class IntelligenceJobTelemetry(SchemaModel):
    schema_version: Literal["scout.intelligence_job_telemetry.v0"] = (
        "scout.intelligence_job_telemetry.v0"
    )
    job_id: UUID
    request_id: UUID
    mission_id: NonEmptyStr
    task_type: IntelligenceTaskType
    question_hash: NonEmptyStr
    workspace_binding: WorkspaceBinding
    capability: IntelligenceCapabilityTelemetry
    state: BackgroundIntelligenceJobState
    stage: NonEmptyStr
    progress_percent: int = Field(ge=0, le=100)
    queue_position: int | None = Field(default=None, ge=0)
    submitted_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime
    cancellation_requested: bool = False
    error_type: str | None = None
    validation_result: ValidationResult = "not_validated"
    validation_reason_codes: tuple[NonEmptyStr, ...] = ()
    service_name: str | None = None
    service_version: str | None = None
    agent_path: tuple[NonEmptyStr, ...] = ()
    tools_called: tuple[NonEmptyStr, ...] = ()
    model_runtimes: tuple[NonEmptyStr, ...] = ()
    model_execution_records: tuple[ModelExecutionRecord, ...] = ()
    request_evidence_refs: tuple[NonEmptyStr, ...] = ()
    evidence_source_refs: tuple[NonEmptyStr, ...] = ()
    artifact_refs: tuple[NonEmptyStr, ...] = ()
    output_hash: str | None = None
    finding_count: int = Field(default=0, ge=0)
    evidence_count: int = Field(default=0, ge=0)
    uncertainty_count: int = Field(default=0, ge=0)
    conflict_count: int = Field(default=0, ge=0)
    events: tuple[BackgroundIntelligenceJobEvent, ...] = ()
    promotion_result: Literal["not_promoted"] = "not_promoted"
    read_only: Literal[True] = True
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


class IntelligenceTelemetrySummary(SchemaModel):
    available_job_count: int = Field(default=0, ge=0)
    total_jobs: int = Field(default=0, ge=0)
    queued_jobs: int = Field(default=0, ge=0)
    running_jobs: int = Field(default=0, ge=0)
    completed_jobs: int = Field(default=0, ge=0)
    failed_jobs: int = Field(default=0, ge=0)
    cancelled_jobs: int = Field(default=0, ge=0)
    truncated: bool = False


class IntelligenceTelemetrySnapshot(SchemaModel):
    schema_version: Literal["scout.intelligence_telemetry.v0"] = (
        "scout.intelligence_telemetry.v0"
    )
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    status: TelemetryStatus
    status_reason: NonEmptyStr
    store_configured: bool
    store_available: bool
    summary: IntelligenceTelemetrySummary = Field(
        default_factory=IntelligenceTelemetrySummary
    )
    jobs: tuple[IntelligenceJobTelemetry, ...] = ()
    promotion_result: Literal["not_promoted"] = "not_promoted"
    read_only: Literal[True] = True
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


class IntelligenceTelemetryReader(Protocol):
    def snapshot(self) -> IntelligenceTelemetrySnapshot: ...


class SQLiteBackgroundIntelligenceTelemetryReader:
    """Project persisted jobs without opening a writable SQLite connection."""

    def __init__(
        self,
        path: Path | str | None,
        *,
        max_jobs: int = 50,
        max_events_per_job: int = 20,
    ) -> None:
        if max_jobs < 1 or max_jobs > 500:
            raise ValueError("max_jobs must be between 1 and 500")
        if max_events_per_job < 1 or max_events_per_job > 200:
            raise ValueError("max_events_per_job must be between 1 and 200")
        self.path = Path(path).expanduser() if path is not None else None
        self.max_jobs = max_jobs
        self.max_events_per_job = max_events_per_job

    @classmethod
    def from_environ(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        max_jobs: int = 50,
        max_events_per_job: int = 20,
    ) -> "SQLiteBackgroundIntelligenceTelemetryReader":
        values = os.environ if environ is None else environ
        configured = values.get("SCOUT_AI_BACKGROUND_JOB_STORE_PATH", "").strip()
        return cls(
            configured or None,
            max_jobs=max_jobs,
            max_events_per_job=max_events_per_job,
        )

    def snapshot(self) -> IntelligenceTelemetrySnapshot:
        if self.path is None:
            return unavailable_telemetry_snapshot(
                status="unavailable",
                reason="store_not_configured",
                configured=False,
            )
        if not self.path.is_file():
            return unavailable_telemetry_snapshot(
                status="unavailable",
                reason="store_not_found",
                configured=True,
            )
        try:
            with self._connect() as connection:
                self._validate_schema(connection)
                available_count = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM background_intelligence_jobs"
                    ).fetchone()[0]
                )
                rows = connection.execute(
                    """
                    SELECT job_id, request_json, progress_json, response_json,
                           updated_at
                    FROM background_intelligence_jobs
                    ORDER BY updated_at DESC, job_id DESC
                    LIMIT ?
                    """,
                    (self.max_jobs,),
                ).fetchall()
                jobs = tuple(self._project_job(connection, row) for row in rows)
        except (sqlite3.Error, OSError):
            return unavailable_telemetry_snapshot(
                status="degraded",
                reason="store_unreadable",
                configured=True,
                available=True,
            )
        except (KeyError, TypeError, ValueError):
            return unavailable_telemetry_snapshot(
                status="degraded",
                reason="invalid_typed_store",
                configured=True,
                available=True,
            )
        counts = Counter(job.state.value for job in jobs)
        return IntelligenceTelemetrySnapshot(
            status="ready",
            status_reason="typed_read_only_projection",
            store_configured=True,
            store_available=True,
            summary=IntelligenceTelemetrySummary(
                available_job_count=available_count,
                total_jobs=len(jobs),
                queued_jobs=counts[BackgroundIntelligenceJobState.QUEUED.value],
                running_jobs=(
                    counts[BackgroundIntelligenceJobState.RUNNING.value]
                    + counts[BackgroundIntelligenceJobState.CANCELLING.value]
                ),
                completed_jobs=counts[BackgroundIntelligenceJobState.COMPLETED.value],
                failed_jobs=counts[BackgroundIntelligenceJobState.FAILED.value],
                cancelled_jobs=counts[BackgroundIntelligenceJobState.CANCELLED.value],
                truncated=available_count > len(jobs),
            ),
            jobs=jobs,
        )

    def _connect(self) -> sqlite3.Connection:
        assert self.path is not None
        encoded_path = quote(str(self.path.resolve()), safe="/")
        connection = sqlite3.connect(
            f"file:{encoded_path}?mode=ro",
            uri=True,
            timeout=1,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        return connection

    @staticmethod
    def _validate_schema(connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type = 'table' AND name IN (
                'background_intelligence_jobs',
                'background_intelligence_job_events'
            )
            """
        ).fetchall()
        if {row["name"] for row in rows} != {
            "background_intelligence_jobs",
            "background_intelligence_job_events",
        }:
            raise ValueError("background intelligence telemetry schema is incomplete")

    def _project_job(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> IntelligenceJobTelemetry:
        request = IntelligenceRequest.model_validate_json(row["request_json"])
        progress = BackgroundIntelligenceJobProgress.model_validate_json(
            row["progress_json"]
        )
        response = (
            IntelligenceResponse.model_validate_json(row["response_json"])
            if row["response_json"] is not None
            else None
        )
        self._validate_bindings(row, request, progress, response)
        events = self._load_events(connection, progress.job_id)
        provenance = response.provenance if response is not None else None
        source_refs = (
            tuple(dict.fromkeys(item.source_ref for item in response.evidence))
            if response is not None
            else ()
        )
        artifact_refs = (
            tuple(
                dict.fromkeys(
                    item.source_ref
                    for item in response.evidence
                    if item.source_ref.startswith("artifact:")
                    or "artifact" in item.source_type.casefold()
                    or item.source_type.casefold().startswith("qgis_")
                )
            )
            if response is not None
            else ()
        )
        grant = request.capability_grant
        validation_result: ValidationResult = (
            progress.validation_disposition.value
            if progress.validation_disposition is not None
            else "not_validated"
        )
        return IntelligenceJobTelemetry(
            job_id=progress.job_id,
            request_id=request.request_id,
            mission_id=request.mission_id,
            task_type=request.task_type,
            question_hash=hashlib.sha256(request.question.encode("utf-8")).hexdigest(),
            workspace_binding=request.workspace_binding,
            capability=IntelligenceCapabilityTelemetry(
                grant_id=grant.grant_id,
                allowed_capabilities=tuple(sorted(grant.allowed_capabilities)),
                denied_capabilities=tuple(sorted(grant.denied_capabilities)),
                expires_at=grant.expires_at,
                max_runtime_seconds=grant.max_runtime_seconds,
                max_model_requests=grant.max_model_requests,
                max_tool_calls=grant.max_tool_calls,
                issued_by=grant.issued_by,
                provenance_ref=grant.provenance_ref,
            ),
            state=progress.state,
            stage=progress.stage,
            progress_percent=progress.progress_percent,
            queue_position=progress.queue_position,
            submitted_at=progress.submitted_at,
            started_at=progress.started_at,
            completed_at=progress.completed_at,
            updated_at=datetime.fromisoformat(row["updated_at"]),
            cancellation_requested=progress.cancellation_requested,
            error_type=progress.error_type,
            validation_result=validation_result,
            validation_reason_codes=tuple(
                dict.fromkeys(
                    _validation_reason_code(reason)
                    for reason in progress.validation_reasons
                )
            ),
            service_name=provenance.service_name if provenance is not None else None,
            service_version=(
                provenance.service_version if provenance is not None else None
            ),
            agent_path=provenance.agent_path if provenance is not None else (),
            tools_called=provenance.tools_called if provenance is not None else (),
            model_runtimes=(
                provenance.model_runtimes if provenance is not None else ()
            ),
            model_execution_records=(
                provenance.model_execution_records if provenance is not None else ()
            ),
            request_evidence_refs=request.evidence_refs,
            evidence_source_refs=source_refs,
            artifact_refs=artifact_refs,
            output_hash=provenance.output_hash if provenance is not None else None,
            finding_count=len(response.findings) if response is not None else 0,
            evidence_count=len(response.evidence) if response is not None else 0,
            uncertainty_count=(
                len(response.uncertainties) if response is not None else 0
            ),
            conflict_count=len(response.conflicts) if response is not None else 0,
            events=events,
        )

    @staticmethod
    def _validate_bindings(
        row: sqlite3.Row,
        request: IntelligenceRequest,
        progress: BackgroundIntelligenceJobProgress,
        response: IntelligenceResponse | None,
    ) -> None:
        if str(progress.job_id) != row["job_id"]:
            raise ValueError("persisted job id does not match typed progress")
        if progress.request_id != request.request_id:
            raise ValueError("persisted progress is bound to another request")
        if progress.mission_id != request.mission_id:
            raise ValueError("persisted progress is bound to another mission")
        if progress.workspace_binding != request.workspace_binding:
            raise ValueError("persisted progress has a stale workspace binding")
        if progress.response_available != (response is not None):
            raise ValueError("persisted response availability is inconsistent")
        if response is None:
            return
        if response.request_id != request.request_id:
            raise ValueError("persisted response is bound to another request")
        if response.provenance.workspace_binding != request.workspace_binding:
            raise ValueError("persisted response has a stale workspace binding")
        if response.provenance.capability_grant_id != request.capability_grant.grant_id:
            raise ValueError("persisted response has an unknown capability grant")

    def _load_events(
        self,
        connection: sqlite3.Connection,
        job_id: UUID,
    ) -> tuple[BackgroundIntelligenceJobEvent, ...]:
        rows = connection.execute(
            """
            SELECT sequence_id, job_id, event_type, state, stage, occurred_at
            FROM background_intelligence_job_events
            WHERE job_id = ?
            ORDER BY sequence_id DESC
            LIMIT ?
            """,
            (str(job_id), self.max_events_per_job),
        ).fetchall()
        events = tuple(
            BackgroundIntelligenceJobEvent(
                sequence_id=row["sequence_id"],
                job_id=UUID(row["job_id"]),
                event_type=row["event_type"],
                state=row["state"],
                stage=row["stage"],
                occurred_at=datetime.fromisoformat(row["occurred_at"]),
            )
            for row in reversed(rows)
        )
        if any(event.job_id != job_id for event in events):
            raise ValueError("persisted event is bound to another job")
        return events


def unavailable_telemetry_snapshot(
    *,
    status: Literal["unavailable", "degraded"],
    reason: str,
    configured: bool,
    available: bool = False,
) -> IntelligenceTelemetrySnapshot:
    return IntelligenceTelemetrySnapshot(
        status=status,
        status_reason=reason,
        store_configured=configured,
        store_available=available,
    )


def _validation_reason_code(reason: str) -> str:
    normalized = reason.casefold()
    if "expired" in normalized:
        return "capability_expired"
    if "stale" in normalized or "binding" in normalized:
        return "binding_rejected"
    if "budget" in normalized or "exceeded" in normalized:
        return "budget_exceeded"
    if "request id" in normalized or "request_id" in normalized:
        return "request_mismatch"
    if "malformed" in normalized or "validation" in normalized:
        return "malformed_response"
    if "capability" in normalized or "permission" in normalized:
        return "capability_violation"
    return "validation_rejected"


__all__ = [
    "IntelligenceCapabilityTelemetry",
    "IntelligenceJobTelemetry",
    "IntelligenceTelemetryReader",
    "IntelligenceTelemetrySnapshot",
    "IntelligenceTelemetrySummary",
    "SQLiteBackgroundIntelligenceTelemetryReader",
    "unavailable_telemetry_snapshot",
]
