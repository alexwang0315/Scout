from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mock_outbound_transport import MockOutboundMessage
from runtime_debug_log import FileRuntimeDebugEventLog
from runtime_debug_models import RuntimeDebugEvent


DEFAULT_SESSION_ID = "debug_session.phase35_ui_demo.20260518T120000Z"
DEFAULT_MISSION_ID = "mission.normal_climb"


@dataclass(frozen=True)
class RuntimeDebugUiDemo:
    session_id: str
    mission_id: str
    events: list[RuntimeDebugEvent]
    messages: list[MockOutboundMessage]


def build_runtime_debug_ui_demo(
    *,
    session_id: str = DEFAULT_SESSION_ID,
    mission_id: str = DEFAULT_MISSION_ID,
) -> RuntimeDebugUiDemo:
    message_id = "mock_message.incident_alert.000001"
    incident_id = "incident_package.normal_climb.route_deviation.000001"
    body_preview = "Scout would send a mock L2 route deviation alert to the remote contact."
    events = [
        _event(
            1,
            session_id=session_id,
            mission_id=mission_id,
            kind="debug_session_started",
            source="runtime_debug_ui_demo",
            phase="phase35",
            summary="Fixture-backed UI demo session started.",
            payload={
                "runtime_profile": "phase35-ui-demo",
                "fixture_backed": True,
                "hardware_required": False,
                "live_safety_runtime_used": False,
            },
        ),
        _event(
            2,
            session_id=session_id,
            mission_id=mission_id,
            kind="provider_status_recorded",
            source="runtime_debug_ui_demo",
            phase="phase35",
            summary="GPS provider available at demo start.",
            subject_ref="provider.gps",
            payload={"provider": "gps", "status": "available", "sample_age_seconds": 1},
        ),
        _event(
            3,
            session_id=session_id,
            mission_id=mission_id,
            kind="observation_ingested",
            source="runtime_debug_ui_demo",
            phase="phase1",
            summary="Observation batch ingested from replay fixture.",
            subject_ref="observation.batch.000001",
            payload={
                "observation_count": 12,
                "input_kind": "replay_fixture",
                "route_ref": "tests/fixtures/routes/off_route_deviation.gpx",
            },
        ),
        _event(
            4,
            session_id=session_id,
            mission_id=mission_id,
            kind="route_progress_evaluated",
            source="runtime_debug_ui_demo",
            phase="phase1",
            summary="Route progress evaluated for the replay observation batch.",
            subject_ref="route_progress.segment_02",
            payload={
                "segment_id": "segment_02",
                "progress_ratio": 0.39,
                "distance_from_route_m": 18.4,
                "safety_level": "L0_NORMAL",
            },
        ),
        _event(
            5,
            session_id=session_id,
            mission_id=mission_id,
            kind="provider_status_recorded",
            source="runtime_debug_ui_demo",
            phase="phase35",
            severity="warning",
            summary="GPS provider degraded during replay.",
            subject_ref="provider.gps",
            payload={
                "provider": "gps",
                "status": "degraded",
                "reason": "sample age exceeded demo threshold",
                "sample_age_seconds": 16,
            },
        ),
        _event(
            6,
            session_id=session_id,
            mission_id=mission_id,
            kind="checkpoint_detected",
            source="runtime_debug_ui_demo",
            phase="phase1",
            summary="Checkpoint proximity detected.",
            subject_ref="checkpoint.cp_02",
            payload={
                "checkpoint_id": "cp_02",
                "distance_m": 7.8,
                "status": "nearby",
            },
        ),
        _event(
            7,
            session_id=session_id,
            mission_id=mission_id,
            kind="safety_event_emitted",
            source="runtime_debug_ui_demo",
            phase="phase1",
            severity="warning",
            summary="Route deviation safety event emitted.",
            subject_ref="safety_event.route_deviation.000001",
            payload={
                "event_type": "route_deviation",
                "safety_level": "L2_CONCERN",
                "distance_from_route_m": 42.6,
                "rule_id": "route_deviation_sustained",
            },
        ),
        _event(
            8,
            session_id=session_id,
            mission_id=mission_id,
            kind="safety_transition_recorded",
            source="runtime_debug_ui_demo",
            phase="phase1",
            severity="warning",
            summary="Safety state transitioned from L0 to L2.",
            subject_ref="safety_state.normal_climb",
            payload={
                "from_level": "L0_NORMAL",
                "to_level": "L2_CONCERN",
                "reason": "sustained route deviation",
            },
        ),
        _event(
            9,
            session_id=session_id,
            mission_id=mission_id,
            kind="incident_package_created",
            source="runtime_debug_ui_demo",
            phase="phase1",
            severity="warning",
            summary="Incident package created after L2 transition.",
            subject_ref=incident_id,
            correlation_refs=["safety_event.route_deviation.000001"],
            payload={
                "incident_id": incident_id,
                "trigger_level": "L2_CONCERN",
                "event_count": 1,
            },
        ),
        _event(
            10,
            session_id=session_id,
            mission_id=mission_id,
            kind="incident_package_persisted",
            source="runtime_debug_ui_demo",
            phase="phase1",
            severity="warning",
            summary="Incident package persisted before downstream bridge visibility.",
            subject_ref=incident_id,
            payload={
                "incident_id": incident_id,
                "path": "fixture://phase35/runtime_debug_ui_demo/incidents/incident.json",
                "post_persistence": True,
            },
        ),
        _event(
            11,
            session_id=session_id,
            mission_id=mission_id,
            kind="phase3_bridge_result",
            source="runtime_debug_ui_demo",
            phase="phase3",
            summary="Phase 3 bridge skipped while disabled.",
            subject_ref=incident_id,
            payload={
                "incident_id": incident_id,
                "status": "skipped",
                "enabled": False,
                "post_persistence": True,
                "failure_isolated": True,
            },
        ),
        _event(
            12,
            session_id=session_id,
            mission_id=mission_id,
            kind="phase3_bridge_result",
            source="runtime_debug_ui_demo",
            phase="phase3",
            summary="Phase 3 bridge import recorded in fixture-only demo mode.",
            subject_ref=incident_id,
            payload={
                "incident_id": incident_id,
                "status": "imported",
                "enabled": True,
                "post_persistence": True,
                "idempotent": True,
                "fixture_only": True,
            },
        ),
        _event(
            13,
            session_id=session_id,
            mission_id=mission_id,
            kind="ln_activation_gate_evaluated",
            source="runtime_debug_ui_demo",
            phase="phase2",
            summary="Ln gate allowed incident follow-up skill visibility.",
            subject_ref="ln_gate.incident_followup",
            correlation_refs=[incident_id],
            payload={
                "gate": "incident_followup",
                "decision": "allowed",
                "reason": "incident package exists after persistence",
            },
        ),
        _event(
            14,
            session_id=session_id,
            mission_id=mission_id,
            kind="skill_run_recorded",
            source="runtime_debug_ui_demo",
            phase="phase2",
            summary="Incident summary skill run started.",
            subject_ref="skill_run.incident_summary.000001",
            correlation_refs=[incident_id],
            payload={
                "skill_id": "incident_summary",
                "state": "started",
                "gate": "incident_followup",
            },
        ),
        _event(
            15,
            session_id=session_id,
            mission_id=mission_id,
            kind="skill_run_recorded",
            source="runtime_debug_ui_demo",
            phase="phase2",
            summary="Incident summary skill run completed.",
            subject_ref="skill_run.incident_summary.000001",
            correlation_refs=[incident_id],
            payload={
                "skill_id": "incident_summary",
                "state": "completed",
                "output_ref": "debug_only://skill_runs/incident_summary/000001",
                "observed_fact_written": False,
            },
        ),
        _event(
            16,
            session_id=session_id,
            mission_id=mission_id,
            kind="ln_activation_gate_evaluated",
            source="runtime_debug_ui_demo",
            phase="phase2",
            severity="warning",
            summary="Ln gate blocked escalation skill in debug fixture.",
            subject_ref="ln_gate.escalation_message",
            correlation_refs=[incident_id],
            payload={
                "gate": "escalation_message",
                "decision": "blocked",
                "reason": "real outbound transport disabled in Phase 3.5",
            },
        ),
        _event(
            17,
            session_id=session_id,
            mission_id=mission_id,
            kind="skill_run_recorded",
            source="runtime_debug_ui_demo",
            phase="phase2",
            severity="warning",
            summary="Escalation skill run failed safely after blocked gate.",
            subject_ref="skill_run.escalation_message.000001",
            correlation_refs=[incident_id],
            payload={
                "skill_id": "escalation_message",
                "state": "failed",
                "failure_isolated": True,
                "reason": "gate blocked",
            },
        ),
        _event(
            18,
            session_id=session_id,
            mission_id=mission_id,
            kind="outbound_message_queued",
            source="runtime_debug_ui_demo",
            phase="phase35",
            summary="Mock outbound incident alert queued.",
            subject_ref=message_id,
            correlation_refs=[incident_id],
            payload=_outbound_payload(
                message_id=message_id,
                state="queued",
                subject_ref=incident_id,
                body_preview=body_preview,
            ),
        ),
        _event(
            19,
            session_id=session_id,
            mission_id=mission_id,
            kind="outbound_message_state_changed",
            source="runtime_debug_ui_demo",
            phase="phase35",
            summary="Mock outbound incident alert marked sent.",
            subject_ref=message_id,
            correlation_refs=[incident_id],
            payload=_outbound_payload(
                message_id=message_id,
                state="sent",
                subject_ref=incident_id,
                body_preview=body_preview,
            ),
        ),
        _event(
            20,
            session_id=session_id,
            mission_id=mission_id,
            kind="outbound_message_state_changed",
            source="runtime_debug_ui_demo",
            phase="phase35",
            summary="Mock outbound incident alert marked delivered.",
            subject_ref=message_id,
            correlation_refs=[incident_id],
            payload=_outbound_payload(
                message_id=message_id,
                state="mock-delivered",
                subject_ref=incident_id,
                body_preview=body_preview,
            ),
        ),
        _event(
            21,
            session_id=session_id,
            mission_id=mission_id,
            kind="provider_status_recorded",
            source="runtime_debug_ui_demo",
            phase="phase35",
            summary="GPS provider recovered after replay window.",
            subject_ref="provider.gps",
            payload={
                "provider": "gps",
                "status": "available",
                "reason": "fresh sample received",
                "sample_age_seconds": 2,
            },
        ),
        _event(
            22,
            session_id=session_id,
            mission_id=mission_id,
            kind="debug_session_completed",
            source="runtime_debug_ui_demo",
            phase="phase35",
            summary="Fixture-backed UI demo session completed.",
            payload={
                "safety_level": "L2_CONCERN",
                "observations_processed": 12,
                "incident_count": 1,
                "stored_incident_count": 1,
                "message_count": 1,
                "phase1_mutation_by_debug": False,
                "observed_fact_written": False,
            },
        ),
    ]
    messages = [
        MockOutboundMessage(
            message_id=message_id,
            session_id=session_id,
            created_at=_timestamp(18),
            updated_at=_timestamp(20),
            category="incident_alert",
            state="mock-delivered",
            recipient_ref="remote_contact.primary",
            subject_ref=incident_id,
            body_preview=body_preview,
            payload={"safety_level": "L2_CONCERN", "incident_id": incident_id},
        )
    ]
    return RuntimeDebugUiDemo(
        session_id=session_id,
        mission_id=mission_id,
        events=events,
        messages=messages,
    )


def write_runtime_debug_ui_demo(
    debug_log_path: Path | str,
    *,
    session_id: str = DEFAULT_SESSION_ID,
    mission_id: str = DEFAULT_MISSION_ID,
    replace: bool = False,
) -> RuntimeDebugUiDemo:
    path = Path(debug_log_path)
    if path.exists() and not replace:
        raise FileExistsError(f"debug log already exists: {path}")
    if path.exists() and replace:
        path.unlink()
    demo = build_runtime_debug_ui_demo(session_id=session_id, mission_id=mission_id)
    log = FileRuntimeDebugEventLog(path)
    for event in demo.events:
        log.append(event)
    return demo


def runtime_debug_ui_demo_summary(demo: RuntimeDebugUiDemo) -> dict[str, Any]:
    final_safety = next(
        (
            event.payload.get("safety_level")
            for event in reversed(demo.events)
            if event.kind == "debug_session_completed"
        ),
        "unknown",
    )
    return {
        "session_id": demo.session_id,
        "mission_id": demo.mission_id,
        "event_count": len(demo.events),
        "message_count": len(demo.messages),
        "event_kinds": sorted({event.kind for event in demo.events}),
        "final_message_states": [message.state for message in demo.messages],
        "final_safety_level": final_safety,
        "fixture_backed": True,
        "hardware_required": False,
        "live_safety_runtime_used": False,
        "mock_transport_only": all(message.transport == "mock" for message in demo.messages),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Write a Scout Phase 3.5 debug UI demo log.")
    parser.add_argument("--debug-log", type=Path, help="JSONL path for the generated debug event log.")
    parser.add_argument("--session-id", default=DEFAULT_SESSION_ID)
    parser.add_argument("--mission-id", default=DEFAULT_MISSION_ID)
    parser.add_argument("--replace", action="store_true", help="Replace an existing demo log path.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the JSON summary.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    demo = (
        write_runtime_debug_ui_demo(
            args.debug_log,
            session_id=args.session_id,
            mission_id=args.mission_id,
            replace=args.replace,
        )
        if args.debug_log
        else build_runtime_debug_ui_demo(session_id=args.session_id, mission_id=args.mission_id)
    )
    print(json.dumps(runtime_debug_ui_demo_summary(demo), indent=2 if args.pretty else None, sort_keys=True))
    return 0


def _event(
    sequence: int,
    *,
    session_id: str,
    mission_id: str,
    kind: str,
    source: str,
    phase: str,
    summary: str,
    severity: str = "info",
    subject_ref: str | None = None,
    correlation_refs: list[str] | None = None,
    payload: dict[str, Any] | None = None,
) -> RuntimeDebugEvent:
    return RuntimeDebugEvent(
        event_id=f"debug_event.phase35_ui_demo.{sequence:06d}",
        session_id=session_id,
        mission_id=mission_id,
        timestamp=_timestamp(sequence),
        sequence=sequence,
        kind=kind,
        source=source,
        phase=phase,
        severity=severity,
        subject_ref=subject_ref,
        correlation_refs=list(correlation_refs or []),
        summary=summary,
        payload=dict(payload or {}),
    )


def _outbound_payload(
    *,
    message_id: str,
    state: str,
    subject_ref: str,
    body_preview: str,
) -> dict[str, Any]:
    return {
        "message_id": message_id,
        "category": "incident_alert",
        "transport": "mock",
        "state": state,
        "recipient_ref": "remote_contact.primary",
        "subject_ref": subject_ref,
        "body_preview": body_preview,
        "payload": {"safety_level": "L2_CONCERN", "incident_id": subject_ref},
        "boundary": {
            "real_sos_sent": False,
            "real_sms_sent": False,
            "real_satellite_sent": False,
        },
    }


def _timestamp(sequence: int) -> str:
    return f"2026-05-18T12:00:{sequence:02d}Z"


if __name__ == "__main__":
    raise SystemExit(main())
