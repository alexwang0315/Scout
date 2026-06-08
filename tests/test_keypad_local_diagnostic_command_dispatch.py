from datetime import datetime, timezone

from tools.keypad_command_candidate_evidence import build_candidate_evidence_flow
from tools.keypad_local_diagnostic_command_dispatch import (
    build_local_diagnostic_dispatch_events,
    dispatch_oled_message,
    led_bits_for_dispatch_status,
)
from tools.pi_scout_agent_keypad_command import build_agent_key_event


def _agent_event(*, key: str, physical_label: str, sequence: int):
    return build_agent_key_event(
        keypad_event={
            "captured_at": datetime(2026, 5, 29, 0, 0, sequence, tzinfo=timezone.utc).isoformat(),
            "key": key,
            "physical_label": physical_label,
            "row_index": sequence % 4,
            "col_index": sequence % 4,
            "row_gpio": 16 + sequence,
            "col_gpio": 24 + sequence,
            "sequence": sequence,
            "suggested_control_role": "numeric_code_candidate",
        },
        visual_updates=[],
    )


def test_dispatch_events_are_opt_in_for_confirmed_local_command() -> None:
    candidate_events = build_candidate_evidence_flow(
        [
            _agent_event(key="1", physical_label="S1", sequence=0),
            _agent_event(key="#", physical_label="S15", sequence=1),
        ]
    )

    assert build_local_diagnostic_dispatch_events(candidate_events, dispatch_enabled=False, dry_run=True) == []

    dispatch_events = build_local_diagnostic_dispatch_events(candidate_events, dispatch_enabled=True, dry_run=True)

    assert len(dispatch_events) == 1
    event = dispatch_events[0]
    assert event["event"] == "local_diagnostic_command_dispatch"
    assert event["candidate_id"] == candidate_events[0]["candidate_id"]
    assert event["mapped_command"] == "gps_status"
    assert event["dispatch_status"] == "planned"
    assert event["dispatch_mode"] == "dry_run"
    assert event["local_diagnostic_command_dispatch_requested"] is True
    assert event["local_diagnostic_command_dispatched"] is False
    assert event["agent_command_execution_allowed"] is False
    assert event["phase1_safety_decision_change_allowed"] is False
    assert event["safety_level_mutation_allowed"] is False
    assert event["live_safety_api_called"] is False
    assert event["live_safety_api_mutation_allowed"] is False
    assert event["remote_outbound_allowed"] is False
    assert event["remote_outbound_send_allowed"] is False
    assert event["hardware_control_scope"] == "local_diagnostic_command_dispatch_evidence_only"


def test_dispatch_ignores_blocked_and_unconfirmed_candidates() -> None:
    candidate_events = build_candidate_evidence_flow(
        [
            _agent_event(key="A", physical_label="S4", sequence=0),
            _agent_event(key="2", physical_label="S2", sequence=1),
        ]
    )

    dispatch_events = build_local_diagnostic_dispatch_events(candidate_events, dispatch_enabled=True, dry_run=True)

    assert dispatch_events == []


def test_dispatch_status_provider_can_record_local_result() -> None:
    candidate_events = build_candidate_evidence_flow(
        [
            _agent_event(key="D", physical_label="S16", sequence=0),
            _agent_event(key="#", physical_label="S15", sequence=1),
        ]
    )

    dispatch_events = build_local_diagnostic_dispatch_events(
        candidate_events,
        dispatch_enabled=True,
        dry_run=False,
        status_provider=lambda command, dry_run: {
            "status": "completed",
            "command": command,
            "dry_run": dry_run,
        },
    )

    assert len(dispatch_events) == 1
    event = dispatch_events[0]
    assert event["mapped_command"] == "runtime_health"
    assert event["dispatch_status"] == "completed"
    assert event["dispatch_mode"] == "local_only"
    assert event["dispatch_result"] == {
        "status": "completed",
        "command": "runtime_health",
        "dry_run": False,
    }
    assert event["local_diagnostic_command_dispatched"] is True


def test_dispatch_visual_helpers_are_stable() -> None:
    event = {
        "mapped_command": "wifi_status",
        "dispatch_status": "planned",
    }

    assert dispatch_oled_message(event) == "SCOUT LOCAL\nWIFI STATUS\nPLANNED\nLOCAL ONLY\nNO SAFETY MUT"
    assert led_bits_for_dispatch_status(event) == 0x1FF
