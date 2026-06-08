from __future__ import annotations

from pathlib import Path

from runtime_debug_log import FileRuntimeDebugEventLog
from scout_sos_playbook import run_mock_sos_playbook


def test_sos_playbook_dry_run_plans_steps_without_writing_logs(tmp_path: Path) -> None:
    debug_log = tmp_path / "runtime-debug.jsonl"

    result = run_mock_sos_playbook(
        sos_event=_sos_event(),
        debug_log_path=debug_log,
        dry_run=True,
    )

    assert result.status == "completed"
    assert result.dry_run is True
    assert [step.step_id for step in result.steps] == [
        "validate_sos_activation",
        "compose_emergency_packet",
        "queue_local_voice_cue",
        "queue_mock_outbound_messages",
        "record_receipts",
    ]
    assert result.counts["mock_outbound_message_count"] == 0
    assert result.boundary.live_safety_api_calls_allowed is False
    assert result.boundary.real_sos_sent is False
    assert not debug_log.exists()


def test_sos_playbook_authorized_mock_run_records_debug_receipts(tmp_path: Path) -> None:
    debug_log = tmp_path / "runtime-debug.jsonl"
    voice_log = tmp_path / "voice.jsonl"

    result = run_mock_sos_playbook(
        sos_event=_sos_event(),
        debug_log_path=debug_log,
        voice_log_path=voice_log,
        recipient_refs=["remote_contact.primary", "remote_contact.backup"],
        dry_run=False,
        mock_deliver=True,
    )

    assert result.status == "completed"
    assert result.dry_run is False
    assert result.counts["mock_outbound_message_count"] == 2
    assert result.counts["voice_cue_count"] == 1
    assert result.counts["real_outbound_send_count"] == 0
    assert result.counts["hardware_action_count"] == 0
    assert all(receipt["transport"] == "mock" for receipt in result.outbound_receipts)
    assert all(receipt["boundary"]["real_sos_sent"] is False for receipt in result.outbound_receipts)
    assert result.voice_receipts[0]["state"] == "rendered"
    assert result.voice_receipts[0]["boundary"]["remote_outbound_allowed"] is False
    events = FileRuntimeDebugEventLog(debug_log).list_events()
    assert any(event.kind == "sos_playbook_step_recorded" for event in events)
    assert any(event.kind == "outbound_message_queued" for event in events)
    assert any(event.kind == "voice_cue_queued" for event in events)
    assert voice_log.exists()


def test_sos_playbook_blocks_operator_test_activation() -> None:
    payload = _sos_event()
    payload["activation_source"] = "operator_test"

    result = run_mock_sos_playbook(sos_event=payload, dry_run=True)

    assert result.status == "blocked"
    assert result.counts["real_outbound_send_count"] == 0
    assert result.steps[0].status == "blocked"


def _sos_event() -> dict[str, object]:
    return {
        "sos_event_id": "sos_event.test.0001",
        "activation_source": "explicit_sos_command",
        "activated_at": "2026-05-27T10:00:00+08:00",
        "trip_id": "chilai_nanhua_day1",
        "client_id": "client.alex.watch",
        "scout_machine_id": "scout.pi5.alpha01",
        "position": {
            "lat": 24.0300,
            "lon": 121.2840,
            "source": "fixture_position",
        },
        "message_zh": "測試 SOS 訊息，不做真實傳送。",
        "source_refs": ["fixture.sos.manual"],
    }
