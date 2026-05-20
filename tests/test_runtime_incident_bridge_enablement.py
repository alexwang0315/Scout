import inspect
import unittest
from pathlib import Path

from mock_outbound_transport import MockOutboundTransport
from runtime_debug_log import MemoryRuntimeDebugEventLog
from runtime_incident_bridge_enablement import (
    RuntimeIncidentBridgeEnablementStatus,
    build_runtime_incident_bridge_enablement_dry_run,
)
from runtime_incident_bridge_opt_in import build_runtime_incident_bridge_opt_in_decision


class RuntimeIncidentBridgeEnablementTests(unittest.TestCase):
    def test_enablement_blocks_when_opt_in_guard_is_not_ready(self):
        decision = build_runtime_incident_bridge_opt_in_decision(
            operator_id="admin.alex",
            runtime_status="observing",
            operator_opt_in=False,
        )
        transport = _transport(MemoryRuntimeDebugEventLog())

        record = build_runtime_incident_bridge_enablement_dry_run(
            opt_in_decision=decision,
            operator_id="admin.alex",
            recipient_refs=["remote_contact.primary"],
            reason="operator requested remote awareness dry run",
            outbound_transport=transport,
            timestamp_factory=lambda: "2026-05-19T22:00:00Z",
        )

        self.assertEqual(record.status, RuntimeIncidentBridgeEnablementStatus.BLOCKED)
        self.assertEqual(record.blocker_reasons, ["opt_in_guard_not_ready"])
        self.assertEqual(record.mock_outbound_message_refs, [])
        self.assertEqual(transport.list_messages(), [])
        self.assertFalse(record.remote_notifications_enabled)
        self.assertFalse(record.enable_performed)
        self.assertEqual(record.counts.incident_bridge_enable_count, 0)
        self.assertEqual(record.counts.remote_notification_send_count, 0)
        self.assertEqual(record.counts.phase2_writeback_count, 0)

    def test_ready_guard_records_dry_run_and_queues_mock_outbound_only(self):
        decision = build_runtime_incident_bridge_opt_in_decision(
            operator_id="admin.alex",
            runtime_status="observing",
            operator_opt_in=True,
            remote_contact_policy_ref="remote_contact_policy.family.v0",
            noise_reduction_policy_ref="noise_reduction_policy.family_low_noise.v0",
        )
        log = MemoryRuntimeDebugEventLog()
        transport = _transport(log)

        record = build_runtime_incident_bridge_enablement_dry_run(
            opt_in_decision=decision,
            operator_id="admin.alex",
            recipient_refs=["remote_contact.primary", "remote_contact.backup"],
            reason="confirm remote awareness path before live trip",
            outbound_transport=transport,
            timestamp_factory=lambda: "2026-05-19T22:00:00Z",
        )

        self.assertEqual(
            record.status,
            RuntimeIncidentBridgeEnablementStatus.DRY_RUN_RECORDED,
        )
        self.assertEqual(record.guard_status, "ready_not_enabled")
        self.assertEqual(record.mock_outbound_message_refs, [
            "mock_message.remote_status.000001",
            "mock_message.remote_status.000002",
        ])
        self.assertEqual(record.counts.mock_outbound_message_count, 2)
        self.assertEqual(record.counts.incident_bridge_enable_count, 0)
        self.assertEqual(record.counts.remote_notification_send_count, 0)
        self.assertEqual(record.counts.phase2_writeback_count, 0)
        self.assertFalse(record.remote_notifications_enabled)
        self.assertFalse(record.enable_performed)
        self.assertTrue(record.boundary.dry_run_only)
        self.assertTrue(record.boundary.uses_mock_outbound_transport)
        self.assertFalse(record.boundary.sends_real_remote_notification)
        self.assertFalse(record.boundary.enables_phase1_incident_bridge)
        self.assertFalse(record.boundary.writes_phase2_brain)
        self.assertFalse(record.boundary.raw_payloads_embedded)

        messages = transport.list_messages()
        self.assertEqual([message.state for message in messages], ["queued", "queued"])
        self.assertEqual([message.transport for message in messages], ["mock", "mock"])
        self.assertEqual([message.category for message in messages], ["remote_status", "remote_status"])
        self.assertFalse(any(message.boundary.real_sos_sent for message in messages))
        self.assertFalse(any(message.boundary.real_sms_sent for message in messages))
        self.assertFalse(any(message.boundary.real_satellite_sent for message in messages))
        self.assertEqual(
            [event.kind for event in log.list_events()],
            ["outbound_message_queued", "outbound_message_queued"],
        )

    def test_enablement_requires_recipient_refs_before_mock_outbound(self):
        decision = build_runtime_incident_bridge_opt_in_decision(
            operator_id="admin.alex",
            runtime_status="observing",
            operator_opt_in=True,
            remote_contact_policy_ref="remote_contact_policy.family.v0",
            noise_reduction_policy_ref="noise_reduction_policy.family_low_noise.v0",
        )

        record = build_runtime_incident_bridge_enablement_dry_run(
            opt_in_decision=decision,
            operator_id="admin.alex",
            recipient_refs=[],
            reason="missing recipients",
            outbound_transport=None,
            timestamp_factory=lambda: "2026-05-19T22:00:00Z",
        )

        self.assertEqual(record.status, RuntimeIncidentBridgeEnablementStatus.BLOCKED)
        self.assertEqual(record.blocker_reasons, ["missing_recipient_refs"])
        self.assertEqual(record.mock_outbound_message_refs, [])

    def test_enablement_source_has_no_real_network_or_phase2_bridge_imports(self):
        import runtime_incident_bridge_enablement

        source = inspect.getsource(runtime_incident_bridge_enablement)
        test_source = Path("tests/test_runtime_incident_bridge_enablement.py").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("requests", source)
        self.assertNotIn("httpx", source)
        self.assertNotIn("urllib", source)
        self.assertNotIn("twilio", source)
        self.assertNotIn("Phase1IncidentBridge", source)
        self.assertNotIn("BrainFileStore", source)
        self.assertIn("MockOutboundTransport", test_source)


def _transport(log: MemoryRuntimeDebugEventLog) -> MockOutboundTransport:
    timestamps = iter(
        [
            "2026-05-19T22:00:01Z",
            "2026-05-19T22:00:02Z",
            "2026-05-19T22:00:03Z",
        ]
    )
    return MockOutboundTransport(
        session_id="runtime_session.chilai_nanhua_day1",
        mission_id="mission.chilai_nanhua_day1",
        debug_log=log,
        timestamp_factory=lambda: next(timestamps),
    )


if __name__ == "__main__":
    unittest.main()
