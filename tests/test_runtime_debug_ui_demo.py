import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from debug_api import create_debug_app
from mock_outbound_transport import MockOutboundMessage
from runtime_debug_log import FileRuntimeDebugEventLog
from runtime_debug_models import RuntimeDebugEvent
from runtime_debug_ui_demo import (
    build_runtime_debug_ui_demo,
    runtime_debug_ui_demo_summary,
    write_runtime_debug_ui_demo,
)


class RuntimeDebugUiDemoTests(unittest.TestCase):
    def test_demo_covers_phase35_ui_runtime_states_without_real_transport(self):
        demo = build_runtime_debug_ui_demo()

        event_kinds = {event.kind for event in demo.events}
        self.assertTrue(
            {
                "debug_session_started",
                "observation_ingested",
                "route_progress_evaluated",
                "checkpoint_detected",
                "safety_event_emitted",
                "safety_transition_recorded",
                "incident_package_created",
                "incident_package_persisted",
                "phase3_bridge_result",
                "provider_status_recorded",
                "ln_activation_gate_evaluated",
                "skill_run_recorded",
                "outbound_message_queued",
                "outbound_message_state_changed",
                "debug_session_completed",
            }.issubset(event_kinds)
        )

        transition = _single_payload(demo.events, "safety_transition_recorded")
        self.assertEqual(transition["from_level"], "L0_NORMAL")
        self.assertEqual(transition["to_level"], "L2_CONCERN")

        provider_statuses = [
            event.payload["status"]
            for event in demo.events
            if event.kind == "provider_status_recorded"
        ]
        self.assertIn("degraded", provider_statuses)
        self.assertIn("available", provider_statuses)

        gate_decisions = [
            event.payload["decision"]
            for event in demo.events
            if event.kind == "ln_activation_gate_evaluated"
        ]
        self.assertIn("allowed", gate_decisions)
        self.assertIn("blocked", gate_decisions)

        skill_states = [
            event.payload["state"]
            for event in demo.events
            if event.kind == "skill_run_recorded"
        ]
        self.assertEqual(skill_states, ["started", "completed", "failed"])

        message_states = [message.state for message in demo.messages]
        self.assertIn("mock-delivered", message_states)
        for message in demo.messages:
            self.assertEqual(message.transport, "mock")
            self.assertFalse(message.boundary.real_sos_sent)
            self.assertFalse(message.boundary.real_sms_sent)
            self.assertFalse(message.boundary.real_satellite_sent)

    def test_demo_writes_file_backed_log_and_debug_api_derives_messages(self):
        with TemporaryDirectory() as tmpdir:
            debug_log_path = Path(tmpdir) / "runtime-debug-ui-demo.jsonl"
            demo = write_runtime_debug_ui_demo(debug_log_path)

            persisted_events = [
                RuntimeDebugEvent.model_validate(json.loads(line))
                for line in debug_log_path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(
                [event.event_id for event in persisted_events],
                [event.event_id for event in demo.events],
            )

            client = TestClient(
                create_debug_app(debug_log=FileRuntimeDebugEventLog(debug_log_path))
            )
            messages = client.get("/debug/messages").json()["messages"]
            state = client.get("/debug/state").json()

        self.assertEqual(messages[0]["state"], "mock-delivered")
        MockOutboundMessage.model_validate(messages[0])
        self.assertEqual(state["message_count"], 1)
        self.assertEqual(state["safety_level"], "L2_CONCERN")
        self.assertEqual(state["provider_status"]["status"], "available")

    def test_demo_summary_is_compact_and_boundary_explicit(self):
        demo = build_runtime_debug_ui_demo()
        summary = runtime_debug_ui_demo_summary(demo)

        self.assertEqual(summary["session_id"], demo.session_id)
        self.assertEqual(summary["event_count"], len(demo.events))
        self.assertEqual(summary["message_count"], len(demo.messages))
        self.assertTrue(summary["mock_transport_only"])
        self.assertEqual(summary["final_message_states"], ["mock-delivered"])
        self.assertEqual(summary["final_safety_level"], "L2_CONCERN")

    def test_skill_run_demo_never_writes_model_output_as_observed_fact(self):
        demo = build_runtime_debug_ui_demo()
        skill_events = [event for event in demo.events if event.kind == "skill_run_recorded"]

        self.assertTrue(skill_events)
        for event in skill_events:
            self.assertIsNot(event.payload.get("observed_fact_written"), True)
            output_ref = event.payload.get("output_ref")
            if output_ref is not None:
                self.assertTrue(output_ref.startswith("debug_only://"))

    def test_demo_module_does_not_import_live_safety_or_brain_runtime(self):
        source = Path("runtime_debug_ui_demo.py").read_text(encoding="utf-8")

        self.assertNotIn("SafetyRuntimeSession", source)
        self.assertNotIn("safety_runtime_session", source)
        self.assertNotIn("BrainFileStore", source)
        self.assertNotIn("IncidentStore", source)


def _single_payload(events: list[RuntimeDebugEvent], kind: str) -> dict:
    matches = [event.payload for event in events if event.kind == kind]
    if len(matches) != 1:
        raise AssertionError(f"expected one {kind}, got {len(matches)}")
    return matches[0]


if __name__ == "__main__":
    unittest.main()
