"""SQLite-backed WorkflowStore for Scout AI OS."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from scout.schemas.workflow import WorkflowSpec


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)


@dataclass(frozen=True)
class WorkflowRecord:
    id: str
    user_id: str
    name: str
    status: str
    lifecycle: str
    runtime: str
    workflow: WorkflowSpec
    next_run_at: datetime | None
    retry_count: int
    created_at: datetime
    updated_at: datetime
    last_error: str | None


class WorkflowStore:
    """Persist workflow specs and status metadata.

    This store does not execute workflows. It only records workflow specs,
    lifecycle status, and audit-like workflow events.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def install(
        self,
        workflow: WorkflowSpec,
        user_id: str,
        status: str = "active",
    ) -> str:
        workflow_id = workflow.id or str(uuid4())
        stored_workflow = workflow.model_copy(update={"id": workflow_id})
        timestamp = _now_iso()
        self._connection.execute(
            """
            INSERT INTO workflow_instances (
                id, user_id, name, status, lifecycle, runtime, workflow_json,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                workflow_id,
                user_id,
                stored_workflow.name,
                status,
                stored_workflow.lifecycle.value,
                stored_workflow.runtime.value,
                stored_workflow.model_dump_json(),
                timestamp,
                timestamp,
            ),
        )
        self.record_event(
            workflow_id,
            "workflow.installed",
            {"status": status, "user_id": user_id},
            commit=False,
        )
        self._connection.commit()
        return workflow_id

    def save_pending(self, workflow: WorkflowSpec, user_id: str) -> str:
        return self.install(workflow, user_id=user_id, status="pending")

    def list_workflows(self, user_id: str) -> list[WorkflowRecord]:
        rows = self._connection.execute(
            """
            SELECT * FROM workflow_instances
            WHERE user_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (user_id,),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def get_workflow(self, workflow_id: str) -> WorkflowRecord | None:
        row = self._connection.execute(
            "SELECT * FROM workflow_instances WHERE id = ?",
            (workflow_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def cancel(self, workflow_id: str, reason: str) -> None:
        self._set_status(workflow_id, "cancelled", "workflow.cancelled", reason)

    def pause(self, workflow_id: str, reason: str) -> None:
        self._set_status(workflow_id, "paused", "workflow.paused", reason)

    def complete(self, workflow_id: str) -> None:
        self._set_status(workflow_id, "completed", "workflow.completed", "")

    def activate(self, workflow_id: str, reason: str = "") -> None:
        self._set_status(workflow_id, "active", "workflow.activated", reason)

    def set_next_run_at(self, workflow_id: str, next_run_at: datetime | None) -> None:
        serialized = None
        if next_run_at is not None:
            serialized = next_run_at.astimezone(UTC).isoformat()
        cursor = self._connection.execute(
            """
            UPDATE workflow_instances
            SET next_run_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (serialized, _now_iso(), workflow_id),
        )
        if cursor.rowcount == 0:
            raise KeyError(f"workflow not found: {workflow_id}")
        self._connection.commit()

    def record_failure(self, workflow_id: str, error: str) -> None:
        cursor = self._connection.execute(
            """
            UPDATE workflow_instances
            SET retry_count = retry_count + 1,
                last_error = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (error, _now_iso(), workflow_id),
        )
        if cursor.rowcount == 0:
            raise KeyError(f"workflow not found: {workflow_id}")
        self.record_event(
            workflow_id,
            "workflow.failed",
            {"error": error},
            commit=False,
        )
        self._connection.commit()

    def record_event(
        self,
        workflow_id: str,
        event_type: str,
        payload: dict[str, Any],
        *,
        commit: bool = True,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO workflow_events (
                id, workflow_id, event_type, payload_json, created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                workflow_id,
                event_type,
                json.dumps(payload, sort_keys=True),
                _now_iso(),
            ),
        )
        if commit:
            self._connection.commit()

    def list_events(self, workflow_id: str, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            """
            SELECT id, event_type, payload_json, created_at
            FROM workflow_events
            WHERE workflow_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (workflow_id, limit),
        ).fetchall()
        return [
            {
                "id": row["id"],
                "event_type": row["event_type"],
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def list_due_workflows(self, now: datetime) -> list[WorkflowRecord]:
        rows = self._connection.execute(
            """
            SELECT * FROM workflow_instances
            WHERE status = 'active'
              AND next_run_at IS NOT NULL
              AND next_run_at <= ?
            ORDER BY next_run_at ASC, id ASC
            """,
            (now.astimezone(UTC).isoformat(),),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def _set_status(
        self,
        workflow_id: str,
        status: str,
        event_type: str,
        reason: str,
    ) -> None:
        cursor = self._connection.execute(
            """
            UPDATE workflow_instances
            SET status = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, _now_iso(), workflow_id),
        )
        if cursor.rowcount == 0:
            raise KeyError(f"workflow not found: {workflow_id}")
        payload: dict[str, Any] = {"status": status}
        if reason:
            payload["reason"] = reason
        self.record_event(workflow_id, event_type, payload, commit=False)
        self._connection.commit()

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> WorkflowRecord:
        return WorkflowRecord(
            id=row["id"],
            user_id=row["user_id"],
            name=row["name"],
            status=row["status"],
            lifecycle=row["lifecycle"],
            runtime=row["runtime"],
            workflow=WorkflowSpec.model_validate_json(row["workflow_json"]),
            next_run_at=_parse_datetime(row["next_run_at"]),
            retry_count=row["retry_count"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            last_error=row["last_error"],
        )


__all__ = ["WorkflowRecord", "WorkflowStore"]
