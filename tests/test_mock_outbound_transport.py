import unittest
from pathlib import Path

from pydantic import ValidationError

from mock_outbound_transport import MockOutboundTransport
from runtime_debug_log import MemoryRuntimeDebugEventLog


class MockOutboundTransportTests(unittest.TestCase):
    def test_queue_message_records_mock_transport_boundaries_and_debug_event(self):
        log = MemoryRuntimeDebugEventLog()
        transport = _transport(log)

        message = transport.queue_message(
            category="incident_alert",
            recipient_ref="remote_contact.primary",
            subject_ref="incident_package.incident_abc",
            body_preview="Scout would send incident alert for L2 route deviation.",
            payload={"safety_level": "L2_CONCERN", "incident_id": "incident_abc"},
            correlation_refs=["incident_package.incident_abc"],
        )

        self.assertEqual(message.state, "queued")
        self.assertEqual(message.transport, "mock")
        self.assertFalse(message.boundary.real_sos_sent)
        self.assertFalse(message.boundary.real_sms_sent)
        self.assertFalse(message.boundary.real_satellite_sent)

        events = log.list_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].kind, "outbound_message_queued")
        self.assertEqual(events[0].subject_ref, message.message_id)
        self.assertEqual(events[0].payload["state"], "queued")
        self.assertEqual(events[0].payload["transport"], "mock")
        self.assertEqual(events[0].payload["body_preview"], message.body_preview)

    def test_message_queue_supports_sent_failed_and_mock_delivered_states(self):
        log = MemoryRuntimeDebugEventLog()
        transport = _transport(log)
        sent = transport.queue_message(
            category="remote_status",
            recipient_ref="remote_contact.primary",
            body_preview="Scout would send remote status.",
        )
        failed = transport.queue_message(
            category="provider_degraded_notice",
            recipient_ref="remote_contact.secondary",
            body_preview="Scout would report provider degradation.",
        )
        delivered = transport.queue_message(
            category="checkin",
            recipient_ref="remote_contact.primary",
            body_preview="Scout would send check-in.",
        )

        transport.mark_sent(sent.message_id)
        transport.mark_failed(failed.message_id, reason="mock provider unavailable")
        transport.mark_mock_delivered(delivered.message_id)
        transport.cancel_message(sent.message_id, reason="operator cancelled stale mock")

        states = {message.message_id: message.state for message in transport.list_messages()}
        self.assertEqual(states[sent.message_id], "cancelled")
        self.assertEqual(states[failed.message_id], "failed")
        self.assertEqual(states[delivered.message_id], "mock-delivered")

        state_events = log.list_events(kind="outbound_message_state_changed")
        self.assertEqual(
            [event.payload["state"] for event in state_events],
            ["sent", "failed", "mock-delivered", "cancelled"],
        )
        self.assertEqual(state_events[1].payload["reason"], "mock provider unavailable")
        self.assertEqual(state_events[3].payload["reason"], "operator cancelled stale mock")

    def test_every_state_transition_keeps_mock_boundaries_false(self):
        log = MemoryRuntimeDebugEventLog()
        transport = _transport(log)
        message = transport.queue_message(
            category="incident_alert",
            recipient_ref="remote_contact.primary",
            body_preview="Scout would send incident alert.",
        )

        delivered = transport.mark_mock_delivered(message.message_id)

        self.assertEqual(delivered.transport, "mock")
        self.assertFalse(delivered.boundary.real_sos_sent)
        self.assertFalse(delivered.boundary.real_sms_sent)
        self.assertFalse(delivered.boundary.real_satellite_sent)
        for event in log.list_events():
            self.assertEqual(event.payload["boundary"]["real_sos_sent"], False)
            self.assertEqual(event.payload["boundary"]["real_sms_sent"], False)
            self.assertEqual(event.payload["boundary"]["real_satellite_sent"], False)

    def test_transition_rejects_invalid_timestamp_provenance(self):
        log = MemoryRuntimeDebugEventLog()
        timestamps = iter(["2026-05-18T12:00:01Z", "not-a-time"])
        transport = MockOutboundTransport(
            session_id="debug_session.off_route_deviation.20260518T120000Z",
            mission_id="mission.normal_climb",
            debug_log=log,
            timestamp_factory=lambda: next(timestamps),
        )
        message = transport.queue_message(
            category="checkin",
            recipient_ref="remote_contact.primary",
            body_preview="Scout would send check-in.",
        )

        with self.assertRaises(ValidationError):
            transport.mark_mock_delivered(message.message_id)

    def test_module_has_no_real_network_or_provider_transport_imports(self):
        source = Path("mock_outbound_transport.py").read_text(encoding="utf-8")

        self.assertNotIn("requests", source)
        self.assertNotIn("httpx", source)
        self.assertNotIn("urllib", source)
        self.assertNotIn("twilio", source)
        self.assertNotIn("satellite", source.lower().replace("real_satellite_sent", ""))


def _transport(log: MemoryRuntimeDebugEventLog) -> MockOutboundTransport:
    timestamps = iter(
        [
            "2026-05-18T12:00:01Z",
            "2026-05-18T12:00:02Z",
            "2026-05-18T12:00:03Z",
            "2026-05-18T12:00:04Z",
            "2026-05-18T12:00:05Z",
            "2026-05-18T12:00:06Z",
            "2026-05-18T12:00:07Z",
            "2026-05-18T12:00:08Z",
        ]
    )
    return MockOutboundTransport(
        session_id="debug_session.off_route_deviation.20260518T120000Z",
        mission_id="mission.normal_climb",
        debug_log=log,
        timestamp_factory=lambda: next(timestamps),
    )


if __name__ == "__main__":
    unittest.main()
