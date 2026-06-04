import unittest

from fastapi.testclient import TestClient

from debug_api import create_debug_app
from mock_outbound_transport import MockOutboundTransport
from mock_voice_transport import MockVoiceTransport
from runtime_debug_log import MemoryRuntimeDebugEventLog
from runtime_debug_models import RuntimeDebugEvent
from scout_agent_models import ScoutAgentToolResult
from scout_agent_trace import append_agent_trace
from spatial_imprint_store import plant_spatial_imprint, spatial_imprint_set_from_store
from spatial_imprint_trigger import evaluate_spatial_imprints
from tests.test_spatial_imprint_trigger import _context, _imprint
from voice_cue_models import VoiceCue


class DebugApiTests(unittest.TestCase):
    def test_debug_page_serves_no_store_html(self):
        client = TestClient(create_debug_app())

        response = client.get("/admin/debug")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertIn("Scout Phase 3.5 Runtime Debug", response.text)
        self.assertIn("function isDirectRuntimeRasterLayer", response.text)
        self.assertIn(
            'layer?.raster_tile_delivery === "direct_wmts_runtime"',
            response.text,
        )
        self.assertIn(
            '["wmts_tile", "wmts_kvp_tile", "xyz_tile"].includes(sourceKind)',
            response.text,
        )

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

    def test_debug_clear_clears_projection_only_with_explicit_confirmation(self):
        log = MemoryRuntimeDebugEventLog()
        log.append(_event(sequence=1, kind="debug_session_started"))
        log.append(_event(sequence=2, kind="observation_ingested"))
        client = TestClient(create_debug_app(debug_log=log))

        rejected = client.post("/debug/clear", json={})
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(len(client.get("/debug/events").json()["events"]), 2)

        response = client.post(
            "/debug/clear",
            json={"confirm_debug_projection_clear": True},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "cleared")
        self.assertEqual(payload["cleared_event_count"], 2)
        self.assertTrue(payload["debug_boundary"]["debug_projection_cleared"])
        self.assertFalse(payload["debug_boundary"]["runtime_state_mutation_allowed"])
        self.assertFalse(payload["debug_boundary"]["phase1_mutation_allowed"])
        self.assertFalse(payload["debug_boundary"]["phase2_writeback_allowed"])
        self.assertFalse(payload["debug_boundary"]["incident_store_mutation_allowed"])
        self.assertFalse(payload["debug_boundary"]["hardware_control_allowed"])
        self.assertEqual(client.get("/debug/events").json()["events"], [])

    def test_debug_events_support_since_sequence_and_limit_filters(self):
        log = MemoryRuntimeDebugEventLog()
        for sequence in range(1, 5):
            log.append(_event(sequence=sequence, kind="provider_status_recorded"))
        client = TestClient(create_debug_app(debug_log=log))

        response = client.get("/debug/events", params={"since_sequence": 1, "limit": 2})

        self.assertEqual(response.status_code, 200)
        self.assertEqual([event["sequence"] for event in response.json()["events"]], [3, 4])

    def test_debug_events_can_filter_voice_cue_projection(self):
        log = MemoryRuntimeDebugEventLog()
        transport = MockVoiceTransport(
            debug_log=log,
            session_id="debug_session.voice",
            mission_id="mission.normal_climb",
            timestamp_factory=lambda: "2026-05-21T10:00:00Z",
        )
        cue = VoiceCue(
            cue_id="voice_cue.route.000001",
            priority="warning",
            category="route",
            text_zh="偏離路線，請停下確認方向。",
            source_event_refs=["debug_event.route.000001"],
            confidence=0.92,
        )
        transport.queue_voice_cue(cue, engine="piper")
        client = TestClient(create_debug_app(debug_log=log))

        response = client.get("/debug/events", params={"kind": "voice_cue_queued"})

        self.assertEqual(response.status_code, 200)
        events = response.json()["events"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["kind"], "voice_cue_queued")
        self.assertEqual(events[0]["payload"]["cue_id"], cue.cue_id)
        self.assertEqual(events[0]["payload"]["boundary"]["remote_outbound_allowed"], False)

    def test_debug_api_projects_agent_tool_trace_as_read_only_event(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmpdir:
            trace_log = __import__("pathlib").Path(tmpdir) / "agent-trace.jsonl"
            append_agent_trace(
                trace_log,
                ScoutAgentToolResult(
                    tool_id="scout.cp.proposal_preview",
                    tool_version="0.1.0",
                    action_id="agent_action.debug.000001",
                    agent_run_id="agent_run.debug.000001",
                    status="completed",
                    mode="proposal_write",
                    started_at="2026-05-27T08:00:00Z",
                    ended_at="2026-05-27T08:00:01Z",
                    outputs={"artifact_refs": ["outputs/cp-proposal.preview.json"]},
                ),
            )
            log = MemoryRuntimeDebugEventLog()
            log.append(_event(sequence=1, kind="debug_session_started"))
            client = TestClient(
                create_debug_app(debug_log=log, agent_trace_log_path=trace_log)
            )

            events = client.get("/debug/events", params={"kind": "agent_tool_invocation"})
            state = client.get("/debug/state")

        self.assertEqual(events.status_code, 200)
        event_payload = events.json()["events"][0]
        self.assertEqual(event_payload["kind"], "agent_tool_invocation")
        self.assertEqual(event_payload["sequence"], 2)
        self.assertEqual(event_payload["payload"]["tool_id"], "scout.cp.proposal_preview")
        self.assertFalse(event_payload["payload"]["live_safety_api_calls_allowed"])
        self.assertFalse(event_payload["payload"]["phase1_safety_mutation_allowed"])
        self.assertEqual(state.status_code, 200)
        self.assertEqual(state.json()["agent_tool_count"], 1)
        self.assertEqual(state.json()["latest_agent_tool"]["tool_id"], "scout.cp.proposal_preview")

    def test_debug_api_projects_spatial_imprint_store_and_trigger_report(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmpdir:
            path_cls = __import__("pathlib").Path
            store_path = path_cls(tmpdir) / "runtime-spatial-imprints.json"
            report_path = path_cls(tmpdir) / "spatial-imprint-trigger-report.json"
            store = plant_spatial_imprint(
                store_path,
                _imprint(
                    imprint_id="spatial_imprint.debug.001",
                    planting_source="operator_runtime",
                ),
                trip_id="chilai_nanhua_day1",
                authorized_by="leader.alex",
                planted_at="2026-05-27T08:00:00Z",
                reason="Debug projection test.",
            )
            report = evaluate_spatial_imprints(
                spatial_imprint_set_from_store(store),
                _context(),
            )
            report_path.write_text(report.model_dump_json(), encoding="utf-8")
            log = MemoryRuntimeDebugEventLog()
            log.append(_event(sequence=1, kind="debug_session_started"))
            client = TestClient(
                create_debug_app(
                    debug_log=log,
                    spatial_imprint_store_path=store_path,
                    spatial_imprint_trigger_report_path=report_path,
                )
            )

            events = client.get("/debug/events")
            trigger_events = client.get(
                "/debug/events",
                params={"kind": "spatial_imprint_trigger_event"},
            )
            state = client.get("/debug/state")
            clear = client.post(
                "/debug/clear",
                json={"confirm_debug_projection_clear": True},
            )
            after_clear = client.get("/debug/events")

        self.assertEqual(events.status_code, 200)
        event_payloads = events.json()["events"]
        self.assertEqual(
            [event["kind"] for event in event_payloads],
            [
                "debug_session_started",
                "spatial_imprint_store_updated",
                "spatial_imprint_trigger_event",
            ],
        )
        self.assertEqual([event["sequence"] for event in event_payloads], [1, 2, 3])
        self.assertEqual(trigger_events.status_code, 200)
        trigger_payload = trigger_events.json()["events"][0]["payload"]
        self.assertEqual(trigger_payload["status"], "triggered")
        self.assertEqual(trigger_payload["imprint_id"], "spatial_imprint.debug.001")
        self.assertTrue(trigger_payload["matched_predicates"])
        self.assertFalse(trigger_payload["live_safety_api_calls_allowed"])
        self.assertFalse(trigger_payload["phase1_safety_mutation_allowed"])
        self.assertEqual(state.status_code, 200)
        self.assertEqual(state.json()["spatial_imprint_event_count"], 2)
        self.assertEqual(
            state.json()["latest_spatial_imprint"]["imprint_id"],
            "spatial_imprint.debug.001",
        )
        self.assertEqual(clear.status_code, 200)
        self.assertFalse(clear.json()["spatial_imprint_artifacts_cleared"])
        self.assertEqual(
            [event["kind"] for event in after_clear.json()["events"]],
            ["spatial_imprint_store_updated", "spatial_imprint_trigger_event"],
        )

    def test_debug_monitoring_center_summarizes_agent_hardware_voice_and_spatial(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path

        with TemporaryDirectory() as tmpdir:
            trace_log = Path(tmpdir) / "agent-trace.jsonl"
            append_agent_trace(
                trace_log,
                ScoutAgentToolResult(
                    tool_id="scout.checks.pretrip_release",
                    tool_version="0.1.0",
                    action_id="agent_action.debug.check.000001",
                    agent_run_id="agent_run.debug.monitoring",
                    status="completed",
                    mode="local_evidence_query",
                    started_at="2026-05-27T08:00:00Z",
                    ended_at="2026-05-27T08:00:01Z",
                    outputs={"returncode": 0},
                ),
            )
            append_agent_trace(
                trace_log,
                ScoutAgentToolResult(
                    tool_id="scout.map.tile_cache_plan",
                    tool_version="0.1.0",
                    action_id="agent_action.debug.map.000001",
                    agent_run_id="agent_run.debug.monitoring",
                    status="completed",
                    mode="local_evidence_query",
                    started_at="2026-05-27T08:01:00Z",
                    ended_at="2026-05-27T08:01:01Z",
                    outputs={"returncode": 0},
                ),
            )
            log = MemoryRuntimeDebugEventLog()
            log.append(
                _event(
                    sequence=1,
                    kind="provider_status_recorded",
                    payload={"provider_ref": "provider.gnss.primary", "status": "ok"},
                )
            )
            transport = MockVoiceTransport(
                debug_log=log,
                session_id="debug_session.voice",
                timestamp_factory=lambda: "2026-05-27T08:02:00Z",
            )
            transport.queue_voice_cue(
                VoiceCue(
                    cue_id="voice_cue.monitor.001",
                    priority="info",
                    category="team",
                    text_zh="監控中心測試。",
                    source_event_refs=[],
                    confidence=1.0,
                ),
                engine="mock",
            )
            outbound = _transport(log)
            outbound.queue_message(
                category="checkin",
                recipient_ref="remote_contact.primary",
                body_preview="Monitoring center mock message.",
            )
            client = TestClient(
                create_debug_app(debug_log=log, agent_trace_log_path=trace_log)
            )

            response = client.get("/debug/monitoring")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["artifact_kind"], "scout_debug_monitoring_center")
        self.assertEqual(payload["counts"]["agent_tool_count"], 2)
        self.assertEqual(payload["counts"]["release_check_count"], 1)
        self.assertEqual(payload["counts"]["map_preparation_count"], 1)
        self.assertEqual(payload["counts"]["provider_status_count"], 1)
        self.assertEqual(payload["counts"]["voice_event_count"], 1)
        self.assertEqual(payload["counts"]["mock_message_count"], 1)
        self.assertEqual(
            payload["sections"]["hardware_readiness"]["context_endpoint"],
            "/admin/hardware-readiness/context",
        )
        self.assertTrue(payload["debug_boundary"]["read_only"])
        self.assertFalse(payload["debug_boundary"]["phase1_mutation_allowed"])

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
