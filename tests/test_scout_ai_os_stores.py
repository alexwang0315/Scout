from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scout.schemas import (
    ActionSpec,
    ActionType,
    PermissionSpec,
    RuntimeTarget,
    TriggerSpec,
    TriggerType,
    WorkflowLifecycle,
    WorkflowSpec,
)
from scout.schemas.capability import (
    CapabilityRisk,
    CapabilityRuntime,
    CapabilitySpec,
    GeneratedCapabilityPackage,
)
from scout.services import (
    REQUIRED_TABLES,
    CapabilityRegistry,
    MemoryStore,
    WorkflowStore,
    list_tables,
    open_database,
)


ROOT = Path(__file__).resolve().parents[1]


def make_workflow(name: str = "Manual reminder") -> WorkflowSpec:
    return WorkflowSpec(
        name=name,
        source_utterance="Remind me to inspect the route.",
        user_goal="Create a local reminder for the operator.",
        trigger=TriggerSpec(
            type=TriggerType.MANUAL,
            description="Operator starts the reminder manually.",
        ),
        actions=[
            ActionSpec(
                type=ActionType.NOTIFY,
                description="Create a local notification candidate.",
            )
        ],
        lifecycle=WorkflowLifecycle.SESSION_SCOPED,
        runtime=RuntimeTarget.PI,
        permissions=PermissionSpec(),
        verification_plan=["Inspect persisted workflow record"],
    )


def open_temp_database(tmp_path: Path) -> sqlite3.Connection:
    return open_database(tmp_path / "scout-ai-os.sqlite")


def test_database_initializes_required_tables_and_wal(tmp_path: Path) -> None:
    connection = open_temp_database(tmp_path)

    assert REQUIRED_TABLES <= list_tables(connection)
    journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
    assert journal_mode == "wal"


def test_workflow_store_install_list_get_cancel_and_complete(
    tmp_path: Path,
) -> None:
    connection = open_temp_database(tmp_path)
    store = WorkflowStore(connection)

    active_id = store.install(make_workflow(), user_id="user-1")
    pending_id = store.save_pending(make_workflow("Pending reminder"), user_id="user-1")

    records = store.list_workflows("user-1")
    assert [record.id for record in records] == [active_id, pending_id]
    assert records[0].status == "active"
    assert records[0].workflow.id == active_id
    assert records[1].status == "pending"

    loaded = store.get_workflow(active_id)
    assert loaded is not None
    assert loaded.workflow.name == "Manual reminder"

    store.cancel(active_id, reason="Operator cancelled setup")
    cancelled = store.get_workflow(active_id)
    assert cancelled is not None
    assert cancelled.status == "cancelled"

    store.complete(pending_id)
    completed = store.get_workflow(pending_id)
    assert completed is not None
    assert completed.status == "completed"

    event_types = [
        row["event_type"]
        for row in connection.execute(
            """
            SELECT event_type FROM workflow_events
            WHERE workflow_id IN (?, ?)
            ORDER BY created_at ASC
            """,
            (active_id, pending_id),
        ).fetchall()
    ]
    assert "workflow.installed" in event_types
    assert "workflow.cancelled" in event_types
    assert "workflow.completed" in event_types


def test_workflow_store_lists_due_active_workflows(tmp_path: Path) -> None:
    connection = open_temp_database(tmp_path)
    store = WorkflowStore(connection)
    workflow_id = store.install(make_workflow(), user_id="user-1")
    now = datetime.now(UTC)
    due_at = (now - timedelta(minutes=1)).isoformat()
    connection.execute(
        "UPDATE workflow_instances SET next_run_at = ? WHERE id = ?",
        (due_at, workflow_id),
    )
    connection.commit()

    due_records = store.list_due_workflows(now)

    assert [record.id for record in due_records] == [workflow_id]


def test_capability_registry_load_search_get_and_install(tmp_path: Path) -> None:
    connection = open_temp_database(tmp_path)
    registry = CapabilityRegistry(connection)

    registry.load_builtins(ROOT / "src/scout/capabilities/builtins")

    all_specs = registry.list_all()
    assert {spec.name for spec in all_specs} == {
        "json_transform",
        "manual_notification",
        "time_reminder",
    }
    assert registry.get("time_reminder") is not None
    assert [spec.name for spec in registry.search("notification")] == [
        "manual_notification"
    ]

    registry.install(
        CapabilitySpec(
            name="route_summary",
            description="Summarize route metadata.",
            runtime=CapabilityRuntime.PYTHON,
            risk_level=CapabilityRisk.LOW,
            input_schema={"type": "object"},
            output_schema={"type": "object"},
        ),
        source="test",
    )
    assert registry.get("route_summary") is not None


def test_capability_registry_records_generated_package_as_candidate(
    tmp_path: Path,
) -> None:
    connection = open_temp_database(tmp_path)
    registry = CapabilityRegistry(connection)

    registry.install(
        GeneratedCapabilityPackage(
            spec=CapabilitySpec(
                name="generated_candidate",
                description="Generated package metadata candidate.",
                runtime=CapabilityRuntime.PYTHON,
                risk_level=CapabilityRisk.LOW,
                input_schema={"type": "object"},
                output_schema={"type": "object"},
            ),
            files={"implementation.py": "def run(payload): return payload"},
            tests={"test_implementation.py": "def test_run(): assert True"},
            install_notes="Metadata candidate only.",
        )
    )

    row = connection.execute(
        "SELECT status, source FROM capabilities WHERE name = ?",
        ("generated_candidate",),
    ).fetchone()
    assert row["status"] == "candidate"
    assert row["source"] == "generated_candidate"


def test_memory_store_add_list_get_and_search(tmp_path: Path) -> None:
    connection = open_temp_database(tmp_path)
    store = MemoryStore(connection)

    item_id = store.add(
        user_id="user-1",
        scope="trip",
        category="operator_preference",
        content="Prefer local reminders before route inspection.",
        source="manual_review",
    )

    item = store.get(item_id)
    assert item is not None
    assert item.content.startswith("Prefer local reminders")

    assert [entry.id for entry in store.list_items("user-1", scope="trip")] == [
        item_id
    ]
    assert [entry.id for entry in store.search("user-1", "route inspection")] == [
        item_id
    ]
