import unittest

from fastapi.testclient import TestClient

from debug_api import create_debug_app
from mock_outbound_transport import MockOutboundTransport
from runtime_debug_log import MemoryRuntimeDebugEventLog
from runtime_debug_models import RuntimeDebugEvent


class DebugApiTests(unittest.TestCase):
    def test_debug_events_state_and_messages_are_read_only(self):
        log = MemoryRuntimeDebugEventLog()
        log.append(_event(sequence=1, kind="debug_session_started", payload={"safety_level": "L0_NORMAL"}))
        log.append(_event(sequence=2, kind="safety_event_emitted", payload={"safety_level": "L2_CONCERN"}))
        log.append(_event(sequence=3, kind="debug_session_completed", payload={"safety_level": "L2_CONCERN"}))
        transport = _transport(log)
        message = transport.queue_message(
            category="incident_alert",
            recipient_ref="remote_contact.primary",
            subject_ref="incident_package.incident_abc",
            body_preview="Scout would send incident alert.",
        )
        app = create_debug_app(debug_log=log, message_source=transport)
        client = TestClient(app)

        events = client.get("/debug/events", params={"kind": "safety_event_emitted"})
        self.assertEqual(events.status_code, 200)
        self.assertEqual([event["kind"] for event in events.json()["events"]], ["safety_event_emitted"])

        state = client.get("/debug/state")
        self.assertEqual(state.status_code, 200)
        state_payload = state.json()
        self.assertEqual(state_payload["safety_level"], "L2_CONCERN")
        self.assertTrue(state_payload["debug_boundary"]["read_only"])
        self.assertFalse(state_payload["debug_boundary"]["phase1_mutation_allowed"])
        self.assertFalse(state_payload["debug_boundary"]["phase2_writeback_allowed"])
        self.assertFalse(state_payload["debug_boundary"]["real_outbound_transport_allowed"])

        messages = client.get("/debug/messages")
        self.assertEqual(messages.status_code, 200)
        self.assertEqual(messages.json()["messages"][0]["message_id"], message.message_id)
        self.assertEqual(messages.json()["messages"][0]["transport"], "mock")

        self.assertEqual(client.post("/debug/events", json={}).status_code, 405)
        self.assertEqual(client.patch("/debug/state", json={}).status_code, 405)
        self.assertEqual(client.delete("/debug/messages").status_code, 405)

    def test_debug_events_support_since_sequence_and_limit_filters(self):
        log = MemoryRuntimeDebugEventLog()
        for sequence in range(1, 5):
            log.append(_event(sequence=sequence, kind="provider_status_recorded"))
        client = TestClient(create_debug_app(debug_log=log))

        response = client.get("/debug/events", params={"since_sequence": 1, "limit": 2})

        self.assertEqual(response.status_code, 200)
        self.assertEqual([event["sequence"] for event in response.json()["events"]], [3, 4])

    def test_debug_api_source_has_no_safety_or_brain_mutation_imports(self):
        source = __import__("pathlib").Path("debug_api.py").read_text(encoding="utf-8")

        self.assertNotIn("SafetyRuntimeSession", source)
        self.assertNotIn("safety_runtime_session", source)
        self.assertNotIn("BrainFileStore", source)
        self.assertNotIn("IncidentStore", source)


def _event(*, sequence: int, kind: str, payload: dict | None = None) -> RuntimeDebugEvent:
    return RuntimeDebugEvent(
        event_id=f"debug_event.test.{sequence:06d}",
        session_id="debug_session.test",
        mission_id="mission.normal_climb",
        timestamp=f"2026-05-18T12:00:{sequence:02d}Z",
        sequence=sequence,
        kind=kind,
        source="test",
        phase="phase35",
        summary=f"test event {sequence}",
        payload=payload or {},
    )


def _transport(log: MemoryRuntimeDebugEventLog) -> MockOutboundTransport:
    return MockOutboundTransport(
        session_id="debug_session.test",
        mission_id="mission.normal_climb",
        debug_log=log,
        timestamp_factory=lambda: "2026-05-18T12:00:10Z",
    )


if __name__ == "__main__":
    unittest.main()
