import json
import subprocess
import sys
from pathlib import Path

import tools.pi_scout_agent_keypad_command as bridge
from tools.pi_scout_agent_keypad_command import (
    agent_oled_message,
    build_agent_key_event,
    led_bits_for_agent_event,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "pi_scout_agent_keypad_command.py"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_agent_keypad_bridge_dry_run_writes_command_candidate_evidence(tmp_path: Path) -> None:
    output_jsonl = tmp_path / "agent-keypad.jsonl"
    output = tmp_path / "summary.json"

    result = run_cli(
        "--dry-run",
        "--simulate-keys",
        "S1,S15,S4",
        "--output-jsonl",
        str(output_jsonl),
        "--output",
        str(output),
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    persisted = [json.loads(line) for line in output_jsonl.read_text().splitlines()]
    assert json.loads(output.read_text()) == summary
    assert summary["artifact_kind"] == "scout_agent_keypad_command_bridge"
    assert summary["source"] == "pi_scout_agent_keypad_command"
    assert summary["hardware_kind"] == "matrix_keypad_4x4_agent_command_bridge"
    assert summary["event_count"] == 3
    assert summary["dry_run"] is True
    assert persisted == summary["events"]
    assert summary["candidate_evidence_model"] == "keypad_command_candidate_v1"
    assert summary["local_diagnostic_dispatch_model"] == "keypad_local_diagnostic_dispatch_v1"
    assert summary["dispatch_confirmed_local"] is False
    assert summary["dispatch_event_count"] == 0
    assert summary["dispatch_events"] == []
    assert [event["physical_label"] for event in summary["agent_key_events"]] == ["S1", "S15", "S4"]
    assert [event["candidate_status"] for event in persisted] == [
        "created",
        "confirmed",
        "blocked",
    ]
    assert [event["event"] for event in persisted] == [
        "command_candidate_created",
        "command_candidate_confirmed",
        "command_candidate_blocked",
    ]
    assert persisted[0]["candidate_id"] == persisted[1]["candidate_id"]
    assert persisted[0]["mapped_command"] == "gps_status"
    assert persisted[1]["mapped_command"] == "gps_status"
    assert persisted[1]["local_command_dispatch_allowed"] is True
    assert persisted[2]["mapped_command"] == "safety_l4_direct_trigger"
    assert persisted[2]["block_reason"] == "l4_direct_trigger_blocked"
    for event in persisted:
        assert event["agent_command_execution_allowed"] is False
        assert event["phase1_safety_decision_change_allowed"] is False
        assert event["safety_level_mutation_allowed"] is False
        assert event["live_safety_api_called"] is False
        assert event["live_safety_api_mutation_allowed"] is False
        assert event["remote_outbound_allowed"] is False
        assert event["remote_outbound_send_allowed"] is False
        assert event["hardware_control_scope"] == "agent_command_candidate_evidence_only"
    assert summary["agent_command_execution_allowed"] is False
    assert summary["phase1_safety_decision_change_allowed"] is False
    assert summary["live_safety_api_called"] is False
    assert summary["live_safety_api_mutation_allowed"] is False
    assert summary["remote_outbound_send_allowed"] is False
    assert summary["hardware_control_scope"] == "agent_command_candidate_evidence_only"


def test_agent_keypad_bridge_visual_dry_run_uses_oled_and_led_payloads() -> None:
    result = run_cli(
        "--dry-run",
        "--simulate-keys",
        "S1",
        "--oled-status",
        "--oled-dry-run",
        "--led-status",
        "--led-dry-run",
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    event = summary["events"][0]
    assert event["physical_label"] == "S1"
    assert event["mapped_command"] == "gps_status"
    assert event["candidate_status"] == "created"
    assert event["visual_updates"] == [
        {
            "target": "oled",
            "write_status": "dry_run",
            "bus": "/dev/i2c-1",
            "address": "0x3c",
            "driver": "sh1107g",
            "message": "SCOUT CMD\nGPS STATUS\nCREATED\nPRESS #\nLOCAL ONLY",
        },
        {
            "target": "led_bar",
            "write_status": "dry_run",
            "port": "D5",
            "data_gpio": 5,
            "clock_gpio": 6,
            "bits": "0x001",
            "blink_seconds": 0.25,
        },
    ]


def test_agent_keypad_bridge_dispatches_confirmed_local_command_when_enabled(tmp_path: Path) -> None:
    output_jsonl = tmp_path / "agent-keypad-dispatch.jsonl"

    result = run_cli(
        "--dry-run",
        "--simulate-keys",
        "S1,S15",
        "--dispatch-confirmed-local",
        "--oled-status",
        "--oled-dry-run",
        "--led-status",
        "--led-dry-run",
        "--output-jsonl",
        str(output_jsonl),
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    persisted = [json.loads(line) for line in output_jsonl.read_text().splitlines()]
    assert summary["dispatch_confirmed_local"] is True
    assert summary["event_count"] == 2
    assert summary["dispatch_event_count"] == 1
    assert summary["jsonl_event_count"] == 3
    assert persisted == [*summary["events"], *summary["dispatch_events"]]
    dispatch_event = summary["dispatch_events"][0]
    assert dispatch_event["event"] == "local_diagnostic_command_dispatch"
    assert dispatch_event["mapped_command"] == "gps_status"
    assert dispatch_event["dispatch_status"] == "planned"
    assert dispatch_event["dispatch_mode"] == "dry_run"
    assert dispatch_event["local_diagnostic_command_dispatched"] is False
    assert dispatch_event["phase1_safety_decision_change_allowed"] is False
    assert dispatch_event["live_safety_api_called"] is False
    assert dispatch_event["remote_outbound_send_allowed"] is False
    assert dispatch_event["hardware_control_scope"] == "local_diagnostic_command_dispatch_evidence_only"
    assert dispatch_event["visual_updates"] == [
        {
            "target": "oled",
            "write_status": "dry_run",
            "bus": "/dev/i2c-1",
            "address": "0x3c",
            "driver": "sh1107g",
            "message": "SCOUT LOCAL\nGPS STATUS\nPLANNED\nLOCAL ONLY\nNO SAFETY MUT",
        },
        {
            "target": "led_bar",
            "write_status": "dry_run",
            "port": "D5",
            "data_gpio": 5,
            "clock_gpio": 6,
            "bits": "0x1ff",
            "blink_seconds": 0.25,
        },
    ]


def test_agent_bridge_uses_scanner_callback_for_immediate_agent_visual_feedback(monkeypatch) -> None:
    callback_seen = False

    def fake_scan_keypad_events(**kwargs):
        nonlocal callback_seen
        event_callback = kwargs["event_callback"]
        callback_seen = True
        payload = {
            "captured_at": "2026-05-29T00:00:00+00:00",
            "source": "pi_keypad_4x4_smoke",
            "hardware_kind": "matrix_keypad_4x4",
            "event": "press",
            "key": "1",
            "physical_label": "S1",
            "physical_label_layout": "row_major_left_to_right_top_to_bottom_s1_s16",
            "row_index": 0,
            "col_index": 0,
            "row_gpio": 16,
            "col_gpio": 24,
            "sequence": 0,
            "suggested_control_role": "numeric_code_candidate",
        }
        event_callback(payload)
        return [payload]

    monkeypatch.setattr(bridge, "scan_keypad_events", fake_scan_keypad_events)

    summary = bridge.run_keypad_command_bridge(
        rows=[16, 17, 18, 19],
        cols=[24, 25, 26, 27],
        grove_ports=["D16", "D18", "D24", "D26"],
        active_low=False,
        duration_seconds=30.0,
        poll_interval_ms=25.0,
        debounce_ms=120.0,
        dry_run=False,
        simulated_keys=[],
        output_jsonl=None,
        visual_options={
            "oled_status": True,
            "oled_dry_run": True,
            "oled_bus": Path("/dev/i2c-1"),
            "oled_address": 0x3C,
            "oled_driver": "sh1107g",
            "led_status": True,
            "led_dry_run": True,
            "led_port": "D5",
            "led_data_gpio": 5,
            "led_clock_gpio": 6,
            "led_blink_seconds": 0.25,
        },
        candidate_policy=bridge.CandidatePolicy(expire_pending_at_end=False),
        dispatch_confirmed_local=False,
    )

    assert callback_seen is True
    assert summary["agent_key_events"][0]["captured_at"] == "2026-05-29T00:00:00+00:00"
    assert summary["events"][0]["visual_updates"][0]["message"] == (
        "SCOUT CMD\nGPS STATUS\nCREATED\nPRESS #\nLOCAL ONLY"
    )
    assert summary["events"][0]["visual_updates"][1]["bits"] == "0x001"


def test_agent_keypad_bridge_accepts_agent_tool_request_file(tmp_path: Path) -> None:
    request = tmp_path / "request.json"
    output_jsonl = tmp_path / "events.jsonl"
    request.write_text(
        json.dumps(
            {
                "dry_run": True,
                "simulate_keys": ["S8", "S12"],
                "output_jsonl": str(output_jsonl),
                "oled_status": True,
                "oled_dry_run": True,
                "led_status": True,
                "led_dry_run": True,
            }
        ),
        encoding="utf-8",
    )

    result = run_cli("--input", str(request))

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert [event["mapped_command"] for event in summary["events"]] == [
        "remote_ack_i_am_ok",
        "safety_mark_event_mutation",
    ]
    assert [event["candidate_status"] for event in summary["events"]] == ["blocked", "blocked"]
    assert output_jsonl.exists()


def test_agent_keypad_bridge_request_dry_run_forces_visual_dry_run(tmp_path: Path) -> None:
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
                "dry_run": True,
                "simulate_keys": ["S1"],
                "oled_status": True,
                "oled_dry_run": False,
                "led_status": True,
                "led_dry_run": False,
            }
        ),
        encoding="utf-8",
    )

    result = run_cli("--input", str(request))

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["dry_run"] is True
    assert [update["write_status"] for update in summary["events"][0]["visual_updates"]] == [
        "dry_run",
        "dry_run",
    ]


def test_agent_keypad_bridge_invalid_simulated_key_fails_cleanly() -> None:
    result = run_cli("--dry-run", "--simulate-keys", "X")

    assert result.returncode == 2
    assert "unsupported keypad key" in result.stderr


def test_agent_visual_helpers_are_stable() -> None:
    event = build_agent_key_event(
        keypad_event={
            "key": "D",
            "physical_label": "S16",
            "row_index": 3,
            "col_index": 3,
            "row_gpio": 19,
            "col_gpio": 27,
            "sequence": 0,
            "suggested_control_role": "mode_page_candidate",
        },
        visual_updates=[],
    )

    assert event["agent_command_id"] == "scout.keypad.mode_page_candidate"
    assert agent_oled_message(event) == "SCOUT AGENT\nS16 MODE PAGE\nKEY D\nCANDIDATE\nNO SAFETY MUT"
    assert led_bits_for_agent_event(event) == 0x020
