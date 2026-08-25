"""SQLite persistence and append-only audit events for candidate jobs."""

from __future__ import annotations

import os
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol
from uuid import UUID

from pydantic import Field

from scout.nextgen.intelligence_gateway import IntelligenceRequest, IntelligenceResponse
from scout.schemas.base import NonEmptyStr, SchemaModel


class BackgroundJobStoreError(RuntimeError):
    pass


class BackgroundJobStoreCorrupt(BackgroundJobStoreError):
    pass


class BackgroundIntelligenceJobEvent(SchemaModel):
    schema_version: Literal["scout.background_job_event.v0"] = (
        "scout.background_job_event.v0"
    )
    sequence_id: int = Field(ge=1)
    job_id: UUID
    event_type: NonEmptyStr
    state: NonEmptyStr
    stage: NonEmptyStr
    occurred_at: datetime
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


@dataclass(frozen=True)
class StoredBackgroundIntelligenceJob:
    request: IntelligenceRequest
    progress_json: str
    response: IntelligenceResponse | None


class _PersistedJobProgress(Protocol):
    job_id: UUID
    state: object
    stage: str

    def model_dump_json(self) -> str: ...


class SQLiteBackgroundIntelligenceJobStore:
    """Small local store; it cannot promote or mutate Scout runtime state."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._create_schema()
        self._secure_database_files()

    def __enter__(self) -> "SQLiteBackgroundIntelligenceJobStore":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def save_job(
        self,
        *,
        request: IntelligenceRequest,
        progress: _PersistedJobProgress,
        response: IntelligenceResponse | None,
        event_type: str,
    ) -> None:
        now = datetime.now(UTC)
        progress_json = progress.model_dump_json()
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO background_intelligence_jobs (
                    job_id, request_json, progress_json, response_json, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    request_json=excluded.request_json,
                    progress_json=excluded.progress_json,
                    response_json=excluded.response_json,
                    updated_at=excluded.updated_at
                """,
                (
                    str(progress.job_id),
                    request.model_dump_json(),
                    progress_json,
                    response.model_dump_json() if response is not None else None,
                    now.isoformat(),
                ),
            )
            self._insert_event(
                job_id=progress.job_id,
                event_type=event_type,
                state=str(progress.state),
                stage=str(progress.stage),
                occurred_at=now,
            )
        self._secure_database_files()

    def append_event(
        self,
        *,
        job_id: UUID,
        event_type: str,
        state: str,
        stage: str,
    ) -> None:
        with self._lock, self._connection:
            self._insert_event(
                job_id=job_id,
                event_type=event_type,
                state=state,
                stage=stage,
                occurred_at=datetime.now(UTC),
            )
        self._secure_database_files()

    def load_jobs(self) -> tuple[StoredBackgroundIntelligenceJob, ...]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT request_json, progress_json, response_json
                FROM background_intelligence_jobs
                ORDER BY updated_at, job_id
                """
            ).fetchall()
        jobs: list[StoredBackgroundIntelligenceJob] = []
        try:
            for row in rows:
                jobs.append(
                    StoredBackgroundIntelligenceJob(
                        request=IntelligenceRequest.model_validate_json(
                            row["request_json"]
                        ),
                        progress_json=row["progress_json"],
                        response=(
                            IntelligenceResponse.model_validate_json(
                                row["response_json"]
                            )
                            if row["response_json"] is not None
                            else None
                        ),
                    )
                )
        except Exception as exc:
            raise BackgroundJobStoreCorrupt(
                "background intelligence store contains invalid typed data"
            ) from exc
        return tuple(jobs)

    def list_events(self, job_id: UUID) -> tuple[BackgroundIntelligenceJobEvent, ...]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT sequence_id, job_id, event_type, state, stage, occurred_at
                FROM background_intelligence_job_events
                WHERE job_id = ?
                ORDER BY sequence_id
                """,
                (str(job_id),),
            ).fetchall()
        return tuple(
            BackgroundIntelligenceJobEvent(
                sequence_id=row["sequence_id"],
                job_id=UUID(row["job_id"]),
                event_type=row["event_type"],
                state=row["state"],
                stage=row["stage"],
                occurred_at=datetime.fromisoformat(row["occurred_at"]),
            )
            for row in rows
        )

    def _create_schema(self) -> None:
        with self._connection:
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS background_intelligence_jobs (
                    job_id TEXT PRIMARY KEY,
                    request_json TEXT NOT NULL,
                    progress_json TEXT NOT NULL,
                    response_json TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS background_intelligence_job_events (
                    sequence_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    state TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    occurred_at TEXT NOT NULL
                )
                """
            )

    def _insert_event(
        self,
        *,
        job_id: UUID,
        event_type: str,
        state: str,
        stage: str,
        occurred_at: datetime,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO background_intelligence_job_events (
                job_id, event_type, state, stage, occurred_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (str(job_id), event_type, state, stage, occurred_at.isoformat()),
        )

    def _secure_database_files(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            database_file = Path(f"{self.path}{suffix}")
            if database_file.exists():
                os.chmod(database_file, 0o600)


__all__ = [
    "BackgroundIntelligenceJobEvent",
    "BackgroundJobStoreCorrupt",
    "BackgroundJobStoreError",
    "SQLiteBackgroundIntelligenceJobStore",
    "StoredBackgroundIntelligenceJob",
]
