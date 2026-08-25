from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scout.runtime import (
    ActionExecutor,
    BackgroundScheduler,
    RuntimeExecutor,
    RuntimeTickResult,
    Scheduler,
)
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
    MemoryExternalNotificationTransport,
    CapabilityRegistry,
    DryRunNotificationProvider,
    MemoryNotificationProvider,
    NotificationGateway,
    OPERATOR_NOTIFICATION_APPROVAL_PHRASE,
    OperatorConfirmedNotificationProvider,
    OperatorNotificationApproval,
    PermissionGate,
    TelegramNotificationTransport,
    WorkflowStore,
    open_database,
)
from scout.ui_action_plan import build_scout_ui_action_plan


ROOT = Path(__file__).resolve().parents[1]


class _FakeTelegramResponse:
    status = 200

    def __enter__(self) -> "_FakeTelegramResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def make_workflow(
    *,
    lifecycle: WorkflowLifecycle = WorkflowLifecycle.ONE_SHOT,
    runtime: RuntimeTarget = RuntimeTarget.PI,
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
        runtime=runtime,
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


def test_permission_gate_allows_session_local_ui_action_plan() -> None:
    plan = build_scout_ui_action_plan(
        surface="pretrip",
        request_text="請幫我關掉所有地圖圖層，只留下 risk score 相關圖層。",
    )

    decision = PermissionGate().evaluate_ui_action_plan(plan)

    assert decision.allowed is True
    assert decision.requires_user_approval is False
    assert "session-local" in decision.reason


def test_permission_gate_requires_confirmation_for_workspace_ui_intent() -> None:
    plan = build_scout_ui_action_plan(
        surface="pretrip",
        request_text="用目前地圖點新增一個 CP。",
    )

    decision = PermissionGate().evaluate_ui_action_plan(plan)

    assert decision.allowed is True
    assert decision.requires_user_approval is True
    assert "workspace write intent" in decision.reason


def test_permission_gate_denies_forbidden_ui_action_plan() -> None:
    plan = build_scout_ui_action_plan(
        surface="debug",
        request_text="請直接觸發 Ln 並發送 SOS",
    )

    decision = PermissionGate().evaluate_ui_action_plan(plan)

    assert decision.allowed is False
    assert decision.requires_user_approval is False
    assert "forbidden_runtime_or_outbound_action" in decision.reason


def test_permission_gate_allows_low_risk_ui_action_workflow() -> None:
    workflow = make_workflow(
        lifecycle=WorkflowLifecycle.SESSION_SCOPED,
        runtime=RuntimeTarget.BROWSER,
        permissions=PermissionSpec(required=["session_local_ui"]),
        actions=[
            ActionSpec(
                type=ActionType.UI_ACTION,
                description="Plan risk-only layer visibility.",
                config={
                    "surface": "pretrip",
                    "request_text": "請幫我關掉所有地圖圖層，只留下 risk score 相關圖層。",
                },
            )
        ],
    )

    decision = PermissionGate().evaluate_workflow(workflow)

    assert decision.allowed is True
    assert decision.requires_user_approval is False
    assert decision.reason == "low-risk workflow"


def test_permission_gate_requires_confirmation_for_ui_workflow_workspace_intent() -> None:
    plan = build_scout_ui_action_plan(
        surface="pretrip",
        request_text="刪除目前選取的 CP。",
    )
    workflow = make_workflow(
        lifecycle=WorkflowLifecycle.SESSION_SCOPED,
        runtime=RuntimeTarget.BROWSER,
        permissions=PermissionSpec(required=["session_local_ui"]),
        actions=[
            ActionSpec(
                type=ActionType.UI_ACTION,
                description="Delete selected checkpoint as a workspace review intent.",
                config={"ui_action_plan": plan},
            )
        ],
    )

    decision = PermissionGate().evaluate_workflow(workflow)

    assert decision.allowed is True
    assert decision.requires_user_approval is True
    assert "workspace write intent" in decision.reason


def test_permission_gate_denies_forbidden_ui_action_workflow() -> None:
    plan = build_scout_ui_action_plan(
        surface="debug",
        request_text="請直接觸發 Ln 並發送 SOS",
    )
    workflow = make_workflow(
        lifecycle=WorkflowLifecycle.SESSION_SCOPED,
        runtime=RuntimeTarget.BROWSER,
        permissions=PermissionSpec(required=["session_local_ui"]),
        actions=[
            ActionSpec(
                type=ActionType.UI_ACTION,
                description="Plan forbidden outbound safety mutation.",
                config={"ui_action_plan": plan},
            )
        ],
    )

    decision = PermissionGate().evaluate_workflow(workflow)

    assert decision.allowed is False
    assert decision.requires_user_approval is False
    assert "UI action denied" in decision.reason


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
    assert result.provider == "stdout"
    assert "Scout: Check route." in capsys.readouterr().out
    events = workflow_store.list_events(workflow_id)
    notification_event = next(
        event for event in events if event["event_type"] == "notification.sent"
    )
    assert notification_event["payload"]["provider"] == "stdout"
    assert notification_event["payload"]["sent"] is True


def test_notification_gateway_supports_memory_provider(capsys) -> None:
    provider = MemoryNotificationProvider()
    gateway = NotificationGateway(provider=provider)

    result = gateway.send("user-1", "Scout", "Check camp.")

    assert result.provider == "memory"
    assert provider.notifications == [result]
    assert capsys.readouterr().out == ""


def test_notification_gateway_supports_external_transport_dry_run(capsys) -> None:
    provider = DryRunNotificationProvider("telegram")
    gateway = NotificationGateway(provider=provider)

    result = gateway.send("user-1", "Scout", "Dry-run message.")

    assert result.provider == "dry_run:telegram"
    assert result.sent is False
    assert result.metadata["dry_run"] is True
    assert result.metadata["transport"] == "telegram"
    assert provider.notifications == [result]
    assert capsys.readouterr().out == ""


def test_operator_confirmed_notification_provider_sends_low_risk_path() -> None:
    transport = MemoryExternalNotificationTransport()
    provider = OperatorConfirmedNotificationProvider(
        transport,
        approval=OperatorNotificationApproval(
            approved_by="operator-1",
            recipient_id="user-1",
            phrase=OPERATOR_NOTIFICATION_APPROVAL_PHRASE,
            reason="Manual low-risk smoke.",
        ),
        allowed_user_ids={"user-1"},
    )
    gateway = NotificationGateway(provider=provider)

    result = gateway.send("user-1", "Scout", "Operator-confirmed.", priority="low")

    assert result.sent is True
    assert result.provider == "operator_confirmed:external_memory"
    assert result.metadata["operator_confirmed"] is True
    assert result.metadata["transport"] == "external_memory"
    assert transport.notifications[0].sent is True


def test_telegram_notification_transport_sends_redacted_payload() -> None:
    calls: list[object] = []

    def fake_urlopen(req: object, *, timeout: float) -> _FakeTelegramResponse:
        calls.append((req, timeout))
        return _FakeTelegramResponse()

    transport = TelegramNotificationTransport(
        bot_token="secret-token",
        chat_id="12345",
        urlopen=fake_urlopen,
    )
    provider = OperatorConfirmedNotificationProvider(
        transport,
        approval=OperatorNotificationApproval(
            approved_by="operator-1",
            recipient_id="user-1",
            phrase=OPERATOR_NOTIFICATION_APPROVAL_PHRASE,
            reason="Manual low-risk Telegram proof.",
        ),
        allowed_user_ids={"user-1"},
    )
    gateway = NotificationGateway(provider=provider)

    result = gateway.send(
        "user-1",
        "Scout",
        "Telegram adapter proof.",
        priority="low",
        metadata={"api_token": "must-redact"},
    )

    req, timeout = calls[0]
    payload = json.loads(req.data.decode("utf-8"))
    assert result.sent is True
    assert result.provider == "operator_confirmed:telegram"
    assert req.full_url == "https://api.telegram.org/botsecret-token/sendMessage"
    assert timeout == 10.0
    assert payload["chat_id"] == "12345"
    assert "Telegram adapter proof." in payload["text"]
    assert result.metadata["telegram_bot_token_present"] is True
    assert result.metadata["telegram_chat_id_hash"] != "12345"
    assert provider.audit_log[0].metadata["api_token"] == "[redacted]"


def test_operator_confirmed_notification_provider_rate_limits_repeated_send() -> None:
    now = 100.0
    transport = MemoryExternalNotificationTransport()
    provider = OperatorConfirmedNotificationProvider(
        transport,
        approval=OperatorNotificationApproval(
            approved_by="operator-1",
            recipient_id="user-1",
            phrase=OPERATOR_NOTIFICATION_APPROVAL_PHRASE,
            reason="Manual low-risk smoke.",
        ),
        allowed_user_ids={"user-1"},
        min_interval_seconds=60,
        clock=lambda: now,
    )
    gateway = NotificationGateway(provider=provider)

    first = gateway.send("user-1", "Scout", "First.", priority="low")
    second = gateway.send("user-1", "Scout", "Second.", priority="low")

    assert first.sent is True
    assert second.sent is False
    assert second.metadata["blocked_reason"] == "rate_limited"
    assert len(transport.notifications) == 1
    assert provider.audit_log[-1].blocked_reason == "rate_limited"


def test_operator_confirmed_notification_provider_blocks_bad_phrase() -> None:
    transport = MemoryExternalNotificationTransport()
    provider = OperatorConfirmedNotificationProvider(
        transport,
        approval=OperatorNotificationApproval(
            approved_by="operator-1",
            recipient_id="user-1",
            phrase="send it",
        ),
        allowed_user_ids={"user-1"},
    )
    gateway = NotificationGateway(provider=provider)

    result = gateway.send("user-1", "Scout", "Should not send.", priority="low")

    assert result.sent is False
    assert result.metadata["blocked_reason"] == "approval_phrase_mismatch"
    assert transport.notifications == []


def test_operator_confirmed_notification_provider_blocks_high_priority() -> None:
    transport = MemoryExternalNotificationTransport()
    provider = OperatorConfirmedNotificationProvider(
        transport,
        approval=OperatorNotificationApproval(
            approved_by="operator-1",
            recipient_id="user-1",
            phrase=OPERATOR_NOTIFICATION_APPROVAL_PHRASE,
        ),
        allowed_user_ids={"user-1"},
    )
    gateway = NotificationGateway(provider=provider)

    result = gateway.send("user-1", "Scout", "Too risky.", priority="critical")

    assert result.sent is False
    assert result.metadata["blocked_reason"] == "priority_not_low_risk"
    assert transport.notifications == []


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


def test_runtime_tick_reschedules_daily_trigger_for_next_day(tmp_path: Path) -> None:
    workflow_store, executor = make_runtime(tmp_path)
    now = datetime(2026, 8, 25, 8, 1, tzinfo=UTC)
    first_run_at = now - timedelta(minutes=1)
    workflow_id = workflow_store.save_pending(
        make_workflow(
            lifecycle=WorkflowLifecycle.PERMANENT,
            trigger=TriggerSpec(
                type=TriggerType.TIME,
                description="Daily time trigger",
                config={
                    "run_at": first_run_at.isoformat(),
                    "recurrence": "daily",
                },
            ),
        ),
        user_id="user-1",
    )
    workflow_store.approve(
        workflow_id,
        user_id="user-1",
        approval_note="Daily reminder approved for this test.",
    )

    result = Scheduler(executor).tick(now)

    assert result.ran == 1
    assert result.results[0].status == "scheduled"
    record = workflow_store.get_workflow(workflow_id)
    assert record is not None
    assert record.next_run_at == first_run_at + timedelta(days=1)


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


def test_runtime_fails_closed_for_unsupported_action_result(tmp_path: Path) -> None:
    workflow_store, executor = make_runtime(tmp_path)
    workflow_id = workflow_store.install(
        make_workflow(
            actions=[
                ActionSpec(
                    type=ActionType.RUN_CAPABILITY,
                    description="Legacy capability dispatch without a runtime handler.",
                    config={"capability": "scout.ui.action_plan", "input": {}},
                )
            ]
        ),
        user_id="user-1",
    )
    now = datetime.now(UTC)
    workflow_store.set_next_run_at(workflow_id, now - timedelta(seconds=1))

    result = executor.tick(now)

    assert result.failed == 1
    assert result.results[0].status == "failed"
    record = workflow_store.get_workflow(workflow_id)
    assert record is not None
    assert record.retry_count == 1
    assert "unsupported action result" in (record.last_error or "")


def test_runtime_executes_ui_action_as_session_local_plan(tmp_path: Path) -> None:
    workflow_store, executor = make_runtime(tmp_path)
    workflow_id = workflow_store.install(
        make_workflow(
            lifecycle=WorkflowLifecycle.SESSION_SCOPED,
            runtime=RuntimeTarget.BROWSER,
            permissions=PermissionSpec(required=["session_local_ui"]),
            actions=[
                ActionSpec(
                    type=ActionType.UI_ACTION,
                    description="Plan risk-only layer visibility.",
                    config={
                        "surface": "pretrip",
                        "request_text": "請幫我關掉所有地圖圖層，只留下 risk score 相關圖層。",
                    },
                )
            ],
        ),
        user_id="user-1",
    )
    now = datetime.now(UTC)
    workflow_store.set_next_run_at(workflow_id, now - timedelta(seconds=1))

    result = executor.tick(now)

    assert result.ran == 1
    assert result.results[0].status == "scheduled"
    action_result = result.results[0].events[0]
    assert action_result["status"] == "planned"
    assert action_result["action_type"] == "ui_action"
    assert action_result["artifact_version"] == "scout_ui_action_plan.v0"
    assert action_result["session_only"] is True
    assert action_result["application_required"] == (
        "window.ScoutAssistantUI.applyUiActionPlan"
    )
    assert action_result["ui_action_plan"]["actions"][0]["action_kind"] == (
        "set_layer_preset"
    )


def test_background_scheduler_lifecycle_ticks_and_stops() -> None:
    class CountingScheduler:
        def __init__(self) -> None:
            self.count = 0

        def tick(self) -> RuntimeTickResult:
            self.count += 1
            return RuntimeTickResult(checked=0, ran=0, paused=0, failed=0)

    async def run_lifecycle() -> None:
        scheduler = CountingScheduler()
        background = BackgroundScheduler(scheduler, interval_seconds=0.01)

        await background.start()
        await asyncio.sleep(0.03)
        assert background.running is True
        await background.stop()

        assert background.running is False
        assert scheduler.count >= 1
        assert background.tick_count == scheduler.count
        assert background.status()["running"] is False

    asyncio.run(run_lifecycle())
