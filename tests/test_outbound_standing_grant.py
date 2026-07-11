from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from scout.runtime import ActionExecutor, RuntimeExecutor
from scout.schemas import (
    ActionSpec,
    ActionType,
    OutboundActionIntent,
    OutboundDataClass,
    OutboundDecisionStatus,
    OutboundGrantScope,
    OutboundPriority,
    OutboundStandingGrant,
    PermissionSpec,
    RuntimeTarget,
    TriggerSpec,
    TriggerType,
    WorkflowLifecycle,
    WorkflowSpec,
)
from scout.services import (
    CapabilityRegistry,
    MemoryExternalNotificationTransport,
    NotificationGateway,
    PermissionGate,
    StandingGrantNotificationProvider,
    WorkflowStore,
    evaluate_outbound_standing_grant,
    notification_payload_hash,
    open_database,
)


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)
PAYLOAD_HASH = notification_payload_hash(
    title="Scout status",
    body="Runtime and GNSS status are available.",
    priority="normal",
)


def make_grant(*, expires_at: datetime | None = None, max_send_count: int = 10) -> OutboundStandingGrant:
    return OutboundStandingGrant(
        grant_id="outbound-grant-trip-001",
        scope=OutboundGrantScope.TRIP,
        scope_ref="trip-001",
        approved_by="operator-1",
        issued_at=NOW - timedelta(minutes=5),
        expires_at=expires_at or NOW + timedelta(hours=8),
        allowed_provider_refs=["provider.telegram.primary", "provider.mqtt.local"],
        allowed_recipient_refs=["remote_contact.primary"],
        allowed_message_classes=["remote_status", "checkin", "device_telemetry"],
        allowed_topic_refs=["mqtt.scout.status"],
        allowed_data_classes=[
            OutboundDataClass.STATUS_SUMMARY,
            OutboundDataClass.DEVICE_TELEMETRY,
            OutboundDataClass.OPERATOR_TEXT,
        ],
        allowed_priorities=[OutboundPriority.LOW, OutboundPriority.NORMAL],
        max_send_count=max_send_count,
    )


def make_intent(**overrides: object) -> OutboundActionIntent:
    values: dict[str, object] = {
        "intent_id": "intent-001",
        "scope_ref": "trip-001",
        "provider_ref": "provider.telegram.primary",
        "recipient_ref": "remote_contact.primary",
        "message_class": "remote_status",
        "priority": OutboundPriority.NORMAL,
        "data_classes": [OutboundDataClass.STATUS_SUMMARY],
        "payload_hash": PAYLOAD_HASH,
        "idempotency_key": "trip-001:remote-status:001",
    }
    values.update(overrides)
    return OutboundActionIntent(**values)


def make_outbound_workflow(intent: OutboundActionIntent) -> WorkflowSpec:
    return WorkflowSpec(
        name="Trip remote status",
        source_utterance="Send my reviewed trip status.",
        user_goal="Send a non-safety status to a reviewed contact.",
        trigger=TriggerSpec(type=TriggerType.MANUAL, description="Manual trigger"),
        actions=[
            ActionSpec(
                type=ActionType.NOTIFY,
                description="Send a reviewed remote status message.",
                config={
                    "title": "Scout status",
                    "body": "Runtime and GNSS status are available.",
                    "priority": "normal",
                    "outbound_intent": intent.model_dump(mode="json"),
                },
            )
        ],
        lifecycle=WorkflowLifecycle.TRIP_SCOPED,
        runtime=RuntimeTarget.PI,
        permissions=PermissionSpec(required=["external_message"]),
    )


def test_valid_standing_grant_auto_allows_non_safety_outbound() -> None:
    decision = evaluate_outbound_standing_grant(
        make_intent(),
        grant=make_grant(),
        now=NOW,
        prior_send_count=0,
    )

    assert decision.status is OutboundDecisionStatus.ALLOWED
    assert decision.auto_execute_allowed is True
    assert decision.requires_user_approval is False
    assert decision.send_performed is False
    assert decision.blocker_reasons == []


def test_missing_expired_or_out_of_scope_grant_requires_approval() -> None:
    missing = evaluate_outbound_standing_grant(make_intent(), grant=None, now=NOW)
    expired = evaluate_outbound_standing_grant(
        make_intent(),
        grant=make_grant(expires_at=NOW - timedelta(seconds=1)),
        now=NOW,
    )
    wrong_recipient = evaluate_outbound_standing_grant(
        make_intent(recipient_ref="remote_contact.unreviewed"),
        grant=make_grant(),
        now=NOW,
    )

    assert missing.status is OutboundDecisionStatus.NEEDS_APPROVAL
    assert expired.status is OutboundDecisionStatus.NEEDS_APPROVAL
    assert wrong_recipient.status is OutboundDecisionStatus.NEEDS_APPROVAL
    assert "standing_grant_missing" in missing.blocker_reasons
    assert "standing_grant_expired" in expired.blocker_reasons
    assert "recipient_ref_not_granted" in wrong_recipient.blocker_reasons


def test_safety_sos_and_secret_material_are_hard_denied() -> None:
    safety = evaluate_outbound_standing_grant(
        make_intent(safety_related=True),
        grant=make_grant(),
        now=NOW,
    )
    sos = evaluate_outbound_standing_grant(
        make_intent(message_class="sos"),
        grant=make_grant(),
        now=NOW,
    )
    secret = evaluate_outbound_standing_grant(
        make_intent(contains_secret_material=True),
        grant=make_grant(),
        now=NOW,
    )

    for decision in (safety, sos, secret):
        assert decision.status is OutboundDecisionStatus.BLOCKED
        assert decision.auto_execute_allowed is False
        assert decision.requires_user_approval is False
    assert "safety_related_outbound_blocked" in safety.blocker_reasons
    assert "safety_message_class_blocked" in sos.blocker_reasons
    assert "secret_material_outbound_blocked" in secret.blocker_reasons


def test_standing_grant_contract_rejects_safety_message_class() -> None:
    grant = make_grant()
    assert isinstance(grant.allowed_recipient_refs, tuple)
    with pytest.raises(ValidationError, match="frozen"):
        grant.max_send_count = 99

    payload = grant.model_dump(mode="json")
    payload["allowed_message_classes"] = ["remote_status", "sos"]

    with pytest.raises(ValidationError, match="safety message classes"):
        OutboundStandingGrant.model_validate(payload)


def test_standing_grant_send_limit_requires_new_approval() -> None:
    decision = evaluate_outbound_standing_grant(
        make_intent(),
        grant=make_grant(max_send_count=2),
        now=NOW,
        prior_send_count=2,
    )

    assert decision.status is OutboundDecisionStatus.NEEDS_APPROVAL
    assert decision.blocker_reasons == ["standing_grant_send_limit_reached"]


def test_permission_gate_uses_typed_standing_grant_for_external_message() -> None:
    workflow = make_outbound_workflow(make_intent())

    allowed = PermissionGate(outbound_grant=make_grant(), clock=lambda: NOW).evaluate_workflow(
        workflow
    )
    needs_approval = PermissionGate(clock=lambda: NOW).evaluate_workflow(workflow)

    assert allowed.allowed is True
    assert allowed.requires_user_approval is False
    assert allowed.reason == "low-risk workflow"
    assert needs_approval.allowed is True
    assert needs_approval.requires_user_approval is True
    assert "standing_grant_missing" in needs_approval.reason


def test_permission_gate_hard_denies_safety_outbound_even_with_grant() -> None:
    workflow = make_outbound_workflow(make_intent(message_class="sos"))

    decision = PermissionGate(outbound_grant=make_grant(), clock=lambda: NOW).evaluate_workflow(
        workflow
    )

    assert decision.allowed is False
    assert decision.requires_user_approval is False
    assert "safety_message_class_blocked" in decision.reason


def test_runtime_executes_granted_outbound_without_per_send_confirmation(
    tmp_path: Path,
) -> None:
    grant = make_grant(max_send_count=1)
    intent = make_intent()
    connection = open_database(tmp_path / "runtime.sqlite")
    workflow_store = WorkflowStore(connection)
    capability_registry = CapabilityRegistry(connection)
    capability_registry.load_builtins(ROOT / "src/scout/capabilities/builtins")
    transport = MemoryExternalNotificationTransport()
    provider = StandingGrantNotificationProvider(
        transport,
        provider_ref="provider.telegram.primary",
        grant=grant,
        clock=lambda: NOW,
    )
    gateway = NotificationGateway(workflow_store, provider=provider)
    executor = RuntimeExecutor(
        workflow_store,
        PermissionGate(outbound_grant=grant, clock=lambda: NOW),
        ActionExecutor(gateway, capability_registry),
    )
    workflow_id = workflow_store.install(
        make_outbound_workflow(intent),
        user_id="remote_contact.primary",
    )
    workflow_store.set_next_run_at(workflow_id, NOW - timedelta(seconds=1))

    result = executor.tick(NOW)

    assert result.ran == 1
    assert result.results[0].status == "scheduled"
    assert result.results[0].events[0]["sent"] is True
    assert result.results[0].events[0]["standing_grant_id"] == grant.grant_id
    assert len(transport.notifications) == 1
    assert provider.audit_log[0].sent is True


def test_standing_grant_provider_stops_after_send_limit() -> None:
    grant = make_grant(max_send_count=1)
    first_intent = make_intent()
    second_intent = make_intent(
        intent_id="intent-002",
        idempotency_key="trip-001:remote-status:002",
    )
    transport = MemoryExternalNotificationTransport()
    provider = StandingGrantNotificationProvider(
        transport,
        provider_ref="provider.telegram.primary",
        grant=grant,
        clock=lambda: NOW,
    )
    gateway = NotificationGateway(provider=provider)
    first = gateway.send(
        "remote_contact.primary",
        "Scout status",
        "Runtime and GNSS status are available.",
        metadata={"outbound_intent": first_intent.model_dump(mode="json")},
    )
    second = gateway.send(
        "remote_contact.primary",
        "Scout status",
        "Runtime and GNSS status are available.",
        metadata={"outbound_intent": second_intent.model_dump(mode="json")},
    )

    assert first.sent is True
    assert second.sent is False
    assert second.metadata["blocked_reason"] == "standing_grant_send_limit_reached"
    assert len(transport.notifications) == 1
    assert provider.send_count == 1
    assert provider.audit_log[-1].blocked_reason == "standing_grant_send_limit_reached"


def test_standing_grant_provider_blocks_payload_change_and_replay() -> None:
    grant = make_grant(max_send_count=3)
    intent = make_intent()
    transport = MemoryExternalNotificationTransport()
    provider = StandingGrantNotificationProvider(
        transport,
        provider_ref="provider.telegram.primary",
        grant=grant,
        clock=lambda: NOW,
    )
    gateway = NotificationGateway(provider=provider)
    metadata = {"outbound_intent": intent.model_dump(mode="json")}

    changed = gateway.send(
        "remote_contact.primary",
        "Scout status",
        "This body was not reviewed.",
        metadata=metadata,
    )
    first = gateway.send(
        "remote_contact.primary",
        "Scout status",
        "Runtime and GNSS status are available.",
        metadata=metadata,
    )
    replay = gateway.send(
        "remote_contact.primary",
        "Scout status",
        "Runtime and GNSS status are available.",
        metadata=metadata,
    )

    assert changed.sent is False
    assert changed.metadata["blocked_reason"] == "notification_payload_hash_mismatch"
    assert first.sent is True
    assert replay.sent is False
    assert replay.metadata["blocked_reason"] == "duplicate_idempotency_key"
    assert len(transport.notifications) == 1
