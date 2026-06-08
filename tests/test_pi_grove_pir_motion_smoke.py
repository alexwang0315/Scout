import json
import subprocess
import sys
from pathlib import Path

from tools.pi_grove_pir_motion_smoke import (
    DEFAULT_PORT,
    DEFAULT_SIGNAL_INDEX,
    gpio_from_port,
    motion_from_level,
    observation_for_level,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "pi_grove_pir_motion_smoke.py"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_pir_dry_run_writes_boundary_payloads(tmp_path: Path) -> None:
    output = tmp_path / "pir.jsonl"

    result = run_cli(
        "--dry-run",
        "--simulate-levels",
        "0,1,1,0",
        "--output-jsonl",
        str(output),
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    persisted = [json.loads(line) for line in output.read_text().splitlines()]
    assert summary["source"] == "pi_grove_pir_motion_smoke"
    assert summary["hardware_kind"] == "grove_mini_pir_motion_sensor"
    assert summary["port"] == DEFAULT_PORT
    assert summary["signal_index"] == DEFAULT_SIGNAL_INDEX
    assert summary["gpio"] == 22
    assert summary["active_mode"] == "active_high"
    assert summary["event_count"] == 3
    assert persisted == summary["events"]
    assert [event["event"] for event in persisted] == ["motion_idle", "motion_start", "motion_end"]
    assert [event["motion_detected"] for event in persisted] == [False, True, False]
    for payload in persisted:
        assert payload["candidate_evidence_kind"] == "nearby_motion_candidate"
        assert payload["phase1_safety_decision_change_allowed"] is False
        assert payload["remote_outbound_allowed"] is False
        assert payload["hardware_control_scope"] == "diagnostic_input_only"


def test_pir_custom_port_signal_and_gpio_override_are_reflected() -> None:
    result = run_cli(
        "--dry-run",
        "--port",
        "D22",
        "--signal-index",
        "1",
        "--gpio",
        "12",
        "--simulate-levels",
        "1",
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    event = summary["events"][0]
    assert summary["port"] == "D22"
    assert summary["signal_index"] == 1
    assert summary["gpio"] == 12
    assert event["gpio"] == 12
    assert event["motion_detected"] is True


def test_pir_active_low_interprets_low_as_motion() -> None:
    result = run_cli(
        "--dry-run",
        "--active-low",
        "--simulate-levels",
        "1,0",
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["active_mode"] == "active_low"
    assert [event["event"] for event in summary["events"]] == ["motion_idle", "motion_start"]
    assert [event["motion_detected"] for event in summary["events"]] == [False, True]


def test_pir_visual_dry_run_updates_oled_and_led() -> None:
    result = run_cli(
        "--dry-run",
        "--simulate-levels",
        "1",
        "--oled-status",
        "--oled-dry-run",
        "--led-status",
        "--led-dry-run",
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    event = summary["events"][0]
    assert event["event"] == "motion_present"
    assert event["visual_updates"] == [
        {
            "target": "oled",
            "write_status": "dry_run",
            "bus": "/dev/i2c-1",
            "address": "0x3c",
            "driver": "sh1107g",
            "message": "SCOUT PIR\nMOTION\nD22 GPIO22\nMOTION_PRESENT\nDIAG ONLY",
        },
        {
            "target": "led_bar",
            "write_status": "dry_run",
            "port": "D5",
            "data_gpio": 5,
            "clock_gpio": 6,
            "bits": "0x002",
            "motion_led_bit": 2,
            "blink_seconds": 0.35,
        },
    ]


def test_pir_mapping_helpers() -> None:
    assert gpio_from_port(port="D22", signal_index=0) == 22
    assert gpio_from_port(port="D22", signal_index=1) == 23
    assert motion_from_level(1, active_low=False) is True
    assert motion_from_level(0, active_low=True) is True
    initial = observation_for_level(level=0, previous_motion=None, active_low=False)
    transition = observation_for_level(level=1, previous_motion=False, active_low=False)
    unchanged = observation_for_level(level=1, previous_motion=True, active_low=False)
    assert initial is not None
    assert initial.event == "motion_idle"
    assert transition is not None
    assert transition.event == "motion_start"
    assert unchanged is None


def test_pir_invalid_signal_index_fails_cleanly() -> None:
    result = run_cli("--dry-run", "--signal-index", "2")

    assert result.returncode == 2
    assert "signal index must be 0 or 1" in result.stderr


def test_pir_invalid_simulated_level_fails_cleanly() -> None:
    result = run_cli("--dry-run", "--simulate-levels", "0,bad,1")

    assert result.returncode == 2
    assert "unsupported simulated level" in result.stderr


def test_pir_invalid_led_bit_fails_cleanly() -> None:
    result = run_cli("--dry-run", "--led-motion-bit", "11")

    assert result.returncode == 2
    assert "LED bit must be between 1 and 10" in result.stderr
