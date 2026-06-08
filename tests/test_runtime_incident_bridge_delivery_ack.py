import json
import unittest

from mock_outbound_transport import MockOutboundTransport
from runtime_debug_log import MemoryRuntimeDebugEventLog
from runtime_incident_bridge_delivery_ack import (
    RuntimeIncidentBridgeDeliveryAction,
    RuntimeIncidentBridgeDeliveryAckStatus,
    build_runtime_incident_bridge_delivery_ack,
)
from runtime_incident_bridge_enablement import (
    build_runtime_incident_bridge_enablement_dry_run,
)
from runtime_incident_bridge_opt_in import build_runtime_incident_bridge_opt_in_decision


class RuntimeIncidentBridgeDeliveryAckTests(unittest.TestCase):
    def test_confirm_mock_delivery_marks_messages_mock_delivered_only(self):
        log = MemoryRuntimeDebugEventLog()
        transport = _transport(log)
        enablement = _ready_enablement(transport)

        record = build_runtime_incident_bridge_delivery_ack(
            enablement_record=enablement,
            action=RuntimeIncidentBridgeDeliveryAction.CONFIRM_MOCK_DELIVERED,
            operator_id="admin.alex",
            reason="operator verified mock delivery path",
            outbound_transport=transport,
            timestamp_factory=lambda: "2026-05-19T23:10:00Z",
        )

        self.assertEqual(record.status, RuntimeIncidentBridgeDeliveryAckStatus.ACK_RECORDED)
        self.assertEqual(record.message_refs, enablement.mock_outbound_message_refs)
        self.assertEqual(record.counts.mock_delivered_count, 2)
        self.assertEqual(record.counts.cancelled_count, 0)
        self.assertEqual(record.counts.rerun_message_count, 0)
        self.assertEqual(record.counts.remote_notification_send_count, 0)
        self.assertEqual(record.counts.incident_bridge_enable_count, 0)
        self.assertEqual(record.counts.phase2_writeback_count, 0)
        self.assertFalse(record.remote_notifications_enabled)
        self.assertFalse(record.enable_performed)
        self.assertTrue(record.boundary.mock_ack_only)
        self.assertFalse(record.boundary.sends_real_remote_notification)
        self.assertFalse(record.boundary.enables_phase1_incident_bridge)
        self.assertFalse(record.boundary.writes_phase2_brain)

        states = [message.state for message in transport.list_messages()]
        self.assertEqual(states, ["mock-delivered", "mock-delivered"])
        self.assertEqual(
            [event.payload["state"] for event in log.list_events(kind="outbound_message_state_changed")],
            ["mock-delivered", "mock-delivered"],
        )

    def test_cancel_mock_delivery_marks_messages_cancelled_only(self):
        log = MemoryRuntimeDebugEventLog()
        transport = _transport(log)
        enablement = _ready_enablement(transport)

        record = build_runtime_incident_bridge_delivery_ack(
            enablement_record=enablement,
            action=RuntimeIncidentBridgeDeliveryAction.CANCEL_MOCK_DELIVERY,
            operator_id="admin.alex",
            reason="operator cancelled before live provider enablement",
            outbound_transport=transport,
            timestamp_factory=lambda: "2026-05-19T23:11:00Z",
        )

        self.assertEqual(record.status, RuntimeIncidentBridgeDeliveryAckStatus.CANCEL_RECORDED)
        self.assertEqual(record.counts.mock_delivered_count, 0)
        self.assertEqual(record.counts.cancelled_count, 2)
        self.assertEqual(record.counts.remote_notification_send_count, 0)
        self.assertEqual(record.counts.incident_bridge_enable_count, 0)
        self.assertEqual([message.state for message in transport.list_messages()], ["cancelled", "cancelled"])

    def test_rerun_records_result_refs_without_queueing_messages_itself(self):
        log = MemoryRuntimeDebugEventLog()
        transport = _transport(log)
        enablement = _ready_enablement(transport)

        record = build_runtime_incident_bridge_delivery_ack(
            enablement_record=enablement,
            action=RuntimeIncidentBridgeDeliveryAction.RERUN_DRY_RUN,
            operator_id="admin.alex",
            reason="rerun after wording review",
            outbound_transport=transport,
            rerun_message_refs=[
                "mock_message.remote_status.000003",
                "mock_message.remote_status.000004",
            ],
            timestamp_factory=lambda: "2026-05-19T23:12:00Z",
        )

        self.assertEqual(record.status, RuntimeIncidentBridgeDeliveryAckStatus.RERUN_RECORDED)
        self.assertEqual(record.message_refs, enablement.mock_outbound_message_refs)
        self.assertEqual(record.rerun_message_refs, [
            "mock_message.remote_status.000003",
            "mock_message.remote_status.000004",
        ])
        self.assertEqual(record.counts.rerun_message_count, 2)
        self.assertEqual(record.counts.remote_notification_send_count, 0)
        self.assertEqual(record.counts.incident_bridge_enable_count, 0)
        self.assertEqual([message.state for message in transport.list_messages()], ["queued", "queued"])

    def test_ack_blocks_non_dry_run_enablement_records(self):
        decision = build_runtime_incident_bridge_opt_in_decision(
            operator_id="admin.alex",
            runtime_status="observing",
            operator_opt_in=False,
        )
        transport = _transport(MemoryRuntimeDebugEventLog())
        blocked_enablement = build_runtime_incident_bridge_enablement_dry_run(
            opt_in_decision=decision,
            operator_id="admin.alex",
            recipient_refs=["remote_contact.primary"],
            reason="blocked",
            outbound_transport=transport,
            timestamp_factory=lambda: "2026-05-19T23:00:00Z",
        )

        record = build_runtime_incident_bridge_delivery_ack(
            enablement_record=blocked_enablement,
            action=RuntimeIncidentBridgeDeliveryAction.CONFIRM_MOCK_DELIVERED,
            operator_id="admin.alex",
            reason="invalid ack",
            outbound_transport=transport,
            timestamp_factory=lambda: "2026-05-19T23:13:00Z",
        )

        self.assertEqual(record.status, RuntimeIncidentBridgeDeliveryAckStatus.BLOCKED)
        self.assertEqual(record.blocker_reasons, ["enablement_record_not_dry_run"])
        self.assertEqual(record.counts.mock_delivered_count, 0)

    def test_ack_records_are_summary_only(self):
        log = MemoryRuntimeDebugEventLog()
        transport = _transport(log)
        enablement = _ready_enablement(transport)

        record = build_runtime_incident_bridge_delivery_ack(
            enablement_record=enablement,
            action=RuntimeIncidentBridgeDeliveryAction.CONFIRM_MOCK_DELIVERED,
            operator_id="admin.alex",
            reason="summary-only check",
            outbound_transport=transport,
            timestamp_factory=lambda: "2026-05-19T23:14:00Z",
        )

        serialized = json.dumps(record.model_dump(mode="json"), sort_keys=True)
        self.assertNotIn("locationLatitude", serialized)
        self.assertNotIn("accelerometerAccelerationX", serialized)
        self.assertNotIn('"payload":', serialized)
        self.assertFalse(record.boundary.raw_payloads_embedded)


def _ready_enablement(transport: MockOutboundTransport):
    decision = build_runtime_incident_bridge_opt_in_decision(
        operator_id="admin.alex",
        runtime_status="observing",
        operator_opt_in=True,
        remote_contact_policy_ref="remote_contact_policy.family.v0",
        noise_reduction_policy_ref="noise_reduction_policy.family_low_noise.v0",
    )
    return build_runtime_incident_bridge_enablement_dry_run(
        opt_in_decision=decision,
        operator_id="admin.alex",
        recipient_refs=["remote_contact.primary", "remote_contact.backup"],
        reason="ready dry run",
        outbound_transport=transport,
        timestamp_factory=lambda: "2026-05-19T23:00:00Z",
    )


def _transport(log: MemoryRuntimeDebugEventLog) -> MockOutboundTransport:
    counter = {"value": 0}

    def timestamp() -> str:
        counter["value"] += 1
        return f"2026-05-19T23:00:{counter['value']:02d}Z"

    return MockOutboundTransport(
        session_id="runtime_session.chilai_nanhua_day1",
        mission_id="mission.chilai_nanhua_day1",
        debug_log=log,
        timestamp_factory=timestamp,
    )


if __name__ == "__main__":
    unittest.main()
