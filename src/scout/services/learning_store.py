"""Reviewable learning artifact store for Scout AI OS."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from scout.schemas.learning import (
    LearningArtifact,
    LearningArtifactType,
    LearningBundle,
)
from scout.services.memory_store import MemoryStore


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class LearningArtifactRecord:
    id: str
    artifact: LearningArtifact
    status: str
    source_workflow_id: str | None
    created_at: datetime


class LearningStore:
    """Persist reviewable learning artifacts and explicit approvals."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        memory_store: MemoryStore,
        eval_jsonl_path: Path | None = None,
    ) -> None:
        self._connection = connection
        self._memory_store = memory_store
        self._eval_jsonl_path = eval_jsonl_path

    def save_bundle(
        self,
        bundle: LearningBundle,
        *,
        source_workflow_id: str | None = None,
    ) -> list[str]:
        ids = []
        for artifact in bundle.artifacts:
            ids.append(
                self.save_artifact(
                    artifact,
                    source_workflow_id=source_workflow_id,
                )
            )
        return ids

    def save_artifact(
        self,
        artifact: LearningArtifact,
        *,
        source_workflow_id: str | None = None,
        status: str = "pending_review",
    ) -> str:
        artifact_id = str(uuid4())
        self._connection.execute(
            """
            INSERT INTO learning_artifacts (
                id, artifact_type, source_workflow_id, content_json,
                status, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                artifact_id,
                artifact.type.value,
                source_workflow_id,
                artifact.model_dump_json(),
                status,
                _now_iso(),
            ),
        )
        self._connection.commit()
        return artifact_id

    def list_artifacts(self, status: str | None = None) -> list[LearningArtifactRecord]:
        if status is None:
            rows = self._connection.execute(
                "SELECT * FROM learning_artifacts ORDER BY created_at ASC, id ASC"
            ).fetchall()
        else:
            rows = self._connection.execute(
                """
                SELECT * FROM learning_artifacts
                WHERE status = ?
                ORDER BY created_at ASC, id ASC
                """,
                (status,),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def get_artifact(self, artifact_id: str) -> LearningArtifactRecord | None:
        row = self._connection.execute(
            "SELECT * FROM learning_artifacts WHERE id = ?",
            (artifact_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def approve(
        self,
        artifact_id: str,
        *,
        user_id: str,
        approval_note: str = "",
    ) -> dict[str, str]:
        record = self.get_artifact(artifact_id)
        if record is None:
            raise KeyError(f"learning artifact not found: {artifact_id}")
        if record.status != "pending_review":
            return {"status": record.status, "action": "already_processed"}

        action = "marked_approved"
        if record.artifact.type is LearningArtifactType.MEMORY:
            self._memory_store.add(
                user_id=user_id,
                scope=str(record.artifact.content.get("scope") or "user"),
                category=str(record.artifact.content.get("category") or "learned"),
                content=str(record.artifact.content.get("content") or record.artifact.title),
                source=f"learning_artifact:{artifact_id}",
            )
            action = "memory_inserted"
        elif record.artifact.type is LearningArtifactType.EVAL_CASE:
            self._append_eval_case(record.artifact)
            action = "eval_case_appended"

        self._connection.execute(
            """
            UPDATE learning_artifacts
            SET status = ?
            WHERE id = ?
            """,
            ("approved", artifact_id),
        )
        self._connection.commit()
        return {
            "status": "approved",
            "action": action,
            "approval_note": approval_note,
        }

    def _append_eval_case(self, artifact: LearningArtifact) -> None:
        if self._eval_jsonl_path is None:
            return
        self._eval_jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        with self._eval_jsonl_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(artifact.content, sort_keys=True) + "\n")

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> LearningArtifactRecord:
        return LearningArtifactRecord(
            id=row["id"],
            artifact=LearningArtifact.model_validate_json(row["content_json"]),
            status=row["status"],
            source_workflow_id=row["source_workflow_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )


__all__ = ["LearningArtifactRecord", "LearningStore"]
