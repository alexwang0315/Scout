from __future__ import annotations

import json
from pathlib import Path

import pytest

from scout.schemas import LearningArtifact, LearningArtifactType, LearningBundle
from scout.services import (
    LearningStore,
    MemoryStore,
    connect_database,
    initialize_database,
    open_database,
)


def make_learning_store(tmp_path: Path) -> LearningStore:
    connection = open_database(tmp_path / "learning.sqlite")
    memory_store = MemoryStore(connection)
    return LearningStore(
        connection,
        memory_store,
        eval_jsonl_path=tmp_path / "evals" / "workflow_compiler.jsonl",
    )


def test_learning_store_saves_reviewable_bundle(tmp_path: Path) -> None:
    store = make_learning_store(tmp_path)
    bundle = LearningBundle(
        artifacts=[
            LearningArtifact(
                type=LearningArtifactType.WORKFLOW_TEMPLATE,
                title="Reminder template",
                reason="Reusable reminder pattern.",
                content={"trigger_type": "time"},
            )
        ],
        summary="One artifact.",
    )

    artifact_ids = store.save_bundle(
        bundle,
        source_workflow_id="wf-1",
        user_id="user-1",
    )

    records = store.list_artifacts("pending_review")
    assert [record.id for record in records] == artifact_ids
    assert records[0].source_workflow_id == "wf-1"
    assert records[0].artifact.requires_review is True


def test_learning_approval_inserts_memory_only_when_explicit(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "learning.sqlite")
    memory_store = MemoryStore(connection)
    store = LearningStore(connection, memory_store)
    artifact_id = store.save_artifact(
        LearningArtifact(
            type=LearningArtifactType.MEMORY,
            title="Early reminders",
            reason="User corrected reminder timing.",
            content={
                "scope": "user",
                "category": "operator_preference",
                "content": "Prefer early reminders.",
            },
        ),
        user_id="user-1",
    )

    result = store.approve(artifact_id, user_id="user-1")

    assert result["action"] == "memory_inserted"
    assert store.get_artifact(artifact_id).status == "approved"  # type: ignore[union-attr]
    memories = memory_store.search("user-1", "early reminders")
    assert len(memories) == 1


def test_learning_approval_appends_eval_case_jsonl(tmp_path: Path) -> None:
    store = make_learning_store(tmp_path)
    eval_case = {
        "id": "case_manual_001",
        "user_utterance": "Remind me to check camp.",
        "expected": {"trigger_type": "manual", "action_types": ["notify"]},
    }
    artifact_id = store.save_artifact(
        LearningArtifact(
            type=LearningArtifactType.EVAL_CASE,
            title="Manual reminder eval",
            reason="Regression coverage for reminders.",
            content=eval_case,
        ),
        user_id="user-1",
    )

    result = store.approve(artifact_id, user_id="user-1")

    assert result["action"] == "eval_case_appended"
    eval_path = tmp_path / "evals" / "workflow_compiler.jsonl"
    lines = eval_path.read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0]) == eval_case


def test_processed_learning_artifact_still_enforces_owner(tmp_path: Path) -> None:
    store = make_learning_store(tmp_path)
    artifact_id = store.save_artifact(
        LearningArtifact(
            type=LearningArtifactType.WORKFLOW_TEMPLATE,
            title="Owned template",
            reason="Ownership regression coverage.",
            content={"trigger_type": "time"},
        ),
        user_id="user-1",
    )
    store.approve(artifact_id, user_id="user-1")

    with pytest.raises(PermissionError, match="another user"):
        store.approve(artifact_id, user_id="user-2")


def test_learning_migration_backfills_owner_from_source_workflow(
    tmp_path: Path,
) -> None:
    connection = connect_database(tmp_path / "legacy-learning.sqlite")
    connection.executescript(
        """
        CREATE TABLE workflow_instances (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL
        );
        CREATE TABLE learning_artifacts (
            id TEXT PRIMARY KEY,
            artifact_type TEXT NOT NULL,
            source_workflow_id TEXT,
            content_json TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        INSERT INTO workflow_instances (id, user_id)
        VALUES ('wf-legacy', 'original-user');
        INSERT INTO learning_artifacts (
            id, artifact_type, source_workflow_id, content_json, status, created_at
        ) VALUES (
            'artifact-legacy',
            'workflow_template',
            'wf-legacy',
            '{}',
            'pending_review',
            '2026-08-25T00:00:00+00:00'
        );
        """
    )
    unresolved_artifact = LearningArtifact(
        type=LearningArtifactType.WORKFLOW_TEMPLATE,
        title="Unbound legacy artifact",
        reason="Migration quarantine coverage.",
        content={"trigger_type": "manual"},
    )
    connection.execute(
        """
        INSERT INTO learning_artifacts (
            id, artifact_type, source_workflow_id, content_json, status, created_at
        ) VALUES (?, ?, NULL, ?, 'pending_review', ?)
        """,
        (
            "artifact-unbound",
            unresolved_artifact.type.value,
            unresolved_artifact.model_dump_json(),
            "2026-08-25T00:00:00+00:00",
        ),
    )

    initialize_database(connection)

    row = connection.execute(
        "SELECT user_id FROM learning_artifacts WHERE id = 'artifact-legacy'"
    ).fetchone()
    assert row["user_id"] == "original-user"

    unresolved = connection.execute(
        "SELECT user_id, status FROM learning_artifacts WHERE id = 'artifact-unbound'"
    ).fetchone()
    assert unresolved["user_id"] == "legacy"
    assert unresolved["status"] == "quarantined"

    store = LearningStore(connection, MemoryStore(connection))
    assert store.list_artifacts(user_id="legacy") == []
    with pytest.raises(PermissionError, match="authority binding"):
        store.approve("artifact-unbound", user_id="legacy")
