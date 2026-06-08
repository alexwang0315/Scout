from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from scout.runtime import ActionExecutor, RuntimeExecutor, Scheduler
from scout.schemas import (
    ActionSpec,
    ActionType,
    CapabilityRisk,
    CapabilityRuntime,
    CapabilitySpec,
    GeneratedCapabilityPackage,
    PermissionSpec,
    RuntimeTarget,
    TriggerSpec,
    TriggerType,
    WorkflowLifecycle,
    WorkflowSpec,
)
from scout.services import (
    CapabilityRegistry,
    NotificationGateway,
    PermissionGate,
    WorkflowStore,
    open_database,
)


ROOT = Path(__file__).resolve().parents[1]


def make_workflow(
    *,
    lifecycle: WorkflowLifecycle = WorkflowLifecycle.ONE_SHOT,
    trigger: TriggerSpec | None = None,
    permissions: PermissionSpec | None = None,
    actions: list[ActionSpec] | None = None,
) -> WorkflowSpec:
    return WorkflowSpec(
        name="Runtime reminder",
        source_utterance="Remind me to check camp.",
        user_goal="Notify the user locally.",
        trigger=trigger
        or TriggerSpec(type=TriggerType.MANUAL, description="Manual trigger"),
        actions=actions
        or [
            ActionSpec(
                type=ActionType.NOTIFY,
                description="Send a local notification.",
                config={"title": "Camp check", "body": "Check camp."},
            )
        ],
        lifecycle=lifecycle,
        runtime=RuntimeTarget.PI,
        permissions=permissions or PermissionSpec(),
    )


def make_runtime(tmp_path: Path) -> tuple[WorkflowStore, RuntimeExecutor]:
    connection = open_database(tmp_path / "runtime.sqlite")
    workflow_store = WorkflowStore(connection)
    capability_registry = CapabilityRegistry(connection)
    capability_registry.load_builtins(ROOT / "src/scout/capabilities/builtins")
    notification_gateway = NotificationGateway(workflow_store)
    action_executor = ActionExecutor(notification_gateway, capability_registry)
    executor = RuntimeExecutor(
        workflow_store,
        PermissionGate(),
        action_executor,
    )
    return workflow_store, executor


def test_permission_gate_allows_low_risk_workflow() -> None:
    decision = PermissionGate().evaluate_workflow(make_workflow())

    assert decision.allowed is True
    assert decision.requires_user_approval is False


def test_permission_gate_requires_approval_for_location_workflow() -> None:
    workflow = make_workflow(
        trigger=TriggerSpec(
            type=TriggerType.LOCATION,
            description="Near campsite",
        ),
        permissions=PermissionSpec(required=["location.read"]),
    )

    decision = PermissionGate().evaluate_workflow(workflow)

    assert decision.allowed is True
    assert decision.requires_user_approval is True
    assert "location" in decision.reason


def test_permission_gate_denies_high_risk_generated_capability() -> None:
    package = GeneratedCapabilityPackage(
        spec=CapabilitySpec(
            name="payment_tool",
            description="Attempt payment automation.",
            runtime=CapabilityRuntime.PYTHON,
            risk_level=CapabilityRisk.HIGH,
            input_schema={"type": "object"},
            output_schema={"type": "object"},
        ),
        files={"implementation.py": "def run(payload): return payload"},
        tests={"test_implementation.py": "def test_run(): assert True"},
        install_notes="High risk candidate.",
    )

    decision = PermissionGate().evaluate_capability_install(package)

    assert decision.allowed is False
    assert decision.requires_user_approval is False


def test_notification_gateway_logs_and_records_event(tmp_path: Path, capsys) -> None:
    workflow_store, _executor = make_runtime(tmp_path)
    workflow_id = workflow_store.install(make_workflow(), user_id="user-1")
    gateway = NotificationGateway(workflow_store)

    result = gateway.send(
        "user-1",
        "Scout",
        "Check route.",
        metadata={"workflow_id": workflow_id},
    )

    assert result.sent is True
    assert "Scout: Check route." in capsys.readouterr().out
    events = workflow_store._connection.execute(  # noqa: SLF001
        "SELECT event_type FROM workflow_events WHERE workflow_id = ?",
        (workflow_id,),
    ).fetchall()
    assert "notification.sent" in [row["event_type"] for row in events]


def test_runtime_tick_executes_due_one_shot_notification(tmp_path: Path) -> None:
    workflow_store, executor = make_runtime(tmp_path)
    workflow_id = workflow_store.install(make_workflow(), user_id="user-1")
    now = datetime.now(UTC)
    workflow_store.set_next_run_at(workflow_id, now - timedelta(seconds=1))

    result = Scheduler(executor).tick(now)

    assert result.checked == 1
    assert result.ran == 1
    assert result.results[0].status == "completed"
    record = workflow_store.get_workflow(workflow_id)
    assert record is not None
    assert record.status == "completed"


def test_runtime_tick_pauses_workflow_requiring_approval(tmp_path: Path) -> None:
    workflow_store, executor = make_runtime(tmp_path)
    workflow_id = workflow_store.install(
        make_workflow(
            trigger=TriggerSpec(
                type=TriggerType.LOCATION,
                description="Near campsite",
            ),
            permissions=PermissionSpec(required=["location.read"]),
        ),
        user_id="user-1",
    )
    now = datetime.now(UTC)
    workflow_store.set_next_run_at(workflow_id, now - timedelta(seconds=1))

    result = Scheduler(executor).tick(now)

    assert result.paused == 1
    record = workflow_store.get_workflow(workflow_id)
    assert record is not None
    assert record.status == "paused"


def test_runtime_executes_low_risk_builtin_capability(tmp_path: Path) -> None:
    workflow_store, executor = make_runtime(tmp_path)
    workflow_id = workflow_store.install(
        make_workflow(
            actions=[
                ActionSpec(
                    type=ActionType.RUN_CAPABILITY,
                    description="Run JSON transform.",
                    config={
                        "capability": "json_transform",
                        "input": {"payload": {"ok": True}},
                    },
                )
            ]
        ),
        user_id="user-1",
    )
    now = datetime.now(UTC)
    workflow_store.set_next_run_at(workflow_id, now - timedelta(seconds=1))

    result = executor.tick(now)

    assert result.results[0].events[0]["payload"] == {"ok": True}
