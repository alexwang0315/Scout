from __future__ import annotations

import json
from pathlib import Path

from scout.schemas import LearningArtifact, LearningArtifactType, LearningBundle
from scout.services import LearningStore, MemoryStore, open_database


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

    artifact_ids = store.save_bundle(bundle, source_workflow_id="wf-1")

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
        )
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
        )
    )

    result = store.approve(artifact_id, user_id="user-1")

    assert result["action"] == "eval_case_appended"
    eval_path = tmp_path / "evals" / "workflow_compiler.jsonl"
    lines = eval_path.read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0]) == eval_case
