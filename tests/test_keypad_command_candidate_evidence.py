from datetime import datetime, timezone

from tools.keypad_command_candidate_evidence import (
    CandidatePolicy,
    build_candidate_evidence_flow,
    candidate_oled_message,
    led_bits_for_candidate_status,
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


def test_candidate_flow_creates_and_confirms_local_diagnostic_command() -> None:
    created_key = _agent_event(key="1", physical_label="S1", sequence=0)
    confirm_key = _agent_event(key="#", physical_label="S15", sequence=1)

    events = build_candidate_evidence_flow([created_key, confirm_key])

    assert [event["candidate_status"] for event in events] == ["created", "confirmed"]
    assert events[0]["mapped_command"] == "gps_status"
    assert events[0]["confirmation_required"] is True
    assert events[0]["local_command_dispatch_allowed"] is False
    assert events[1]["candidate_id"] == events[0]["candidate_id"]
    assert events[1]["local_command_dispatch_allowed"] is True
    for event in events:
        assert event["phase1_safety_decision_change_allowed"] is False
        assert event["safety_level_mutation_allowed"] is False
        assert event["live_safety_api_called"] is False
        assert event["live_safety_api_mutation_allowed"] is False
        assert event["remote_outbound_allowed"] is False
        assert event["remote_outbound_send_allowed"] is False


def test_candidate_flow_expires_unconfirmed_candidate_at_end() -> None:
    events = build_candidate_evidence_flow(
        [_agent_event(key="2", physical_label="S2", sequence=0)],
        policy=CandidatePolicy(confirmation_timeout_seconds=3.0),
    )

    assert [event["candidate_status"] for event in events] == ["created", "expired"]
    assert events[0]["mapped_command"] == "wifi_status"
    assert events[1]["transition_reason"] == "confirmation_timeout"
    assert events[1]["local_command_dispatch_allowed"] is False


def test_candidate_flow_blocks_l4_safety_and_remote_outbound_commands() -> None:
    sos = _agent_event(key="A", physical_label="S4", sequence=0)
    ack = _agent_event(key="B", physical_label="S8", sequence=1)
    mark_event = _agent_event(key="C", physical_label="S12", sequence=2)

    events = build_candidate_evidence_flow([sos, ack, mark_event])

    assert [event["candidate_status"] for event in events] == ["blocked", "blocked", "blocked"]
    assert [event["block_reason"] for event in events] == [
        "l4_direct_trigger_blocked",
        "remote_outbound_blocked",
        "safety_mutation_blocked",
    ]
    assert all(event["local_diagnostic_command_allowed"] is False for event in events)
    assert all(event["local_command_dispatch_allowed"] is False for event in events)


def test_candidate_visual_helpers_are_stable() -> None:
    events = build_candidate_evidence_flow([_agent_event(key="A", physical_label="S4", sequence=0)])
    blocked = events[0]

    assert "BLOCKED" in candidate_oled_message(blocked)
    assert "L4 DIRECT" in candidate_oled_message(blocked)
    assert led_bits_for_candidate_status(blocked) == 0x2AA
