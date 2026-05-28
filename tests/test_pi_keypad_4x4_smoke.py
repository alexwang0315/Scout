import json
import subprocess
import sys
from pathlib import Path

from tools.pi_keypad_4x4_smoke import (
    DEFAULT_GROVE_PORTS,
    DEFAULT_COLS,
    DEFAULT_ROWS,
    key_press_for_key,
    keypad_oled_message,
    led_bits_for_key,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "pi_keypad_4x4_smoke.py"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_keypad_dry_run_writes_boundary_payloads(tmp_path: Path) -> None:
    output = tmp_path / "keypad.jsonl"

    result = run_cli(
        "--dry-run",
        "--simulate-keys",
        "1,A,#",
        "--output-jsonl",
        str(output),
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    persisted = [json.loads(line) for line in output.read_text().splitlines()]
    assert summary["source"] == "pi_keypad_4x4_smoke"
    assert summary["hardware_kind"] == "matrix_keypad_4x4"
    assert summary["rows"] == DEFAULT_ROWS
    assert summary["cols"] == DEFAULT_COLS
    assert summary["grove_ports"] == DEFAULT_GROVE_PORTS
    assert summary["active_mode"] == "active_high"
    assert summary["event_count"] == 3
    assert persisted == summary["events"]
    first, second, third = persisted
    assert first["key"] == "1"
    assert first["row_index"] == 0
    assert first["col_index"] == 0
    assert first["row_gpio"] == 16
    assert first["col_gpio"] == 24
    assert first["suggested_control_role"] == "numeric_code_candidate"
    assert second["key"] == "A"
    assert second["suggested_control_role"] == "sos_arm_candidate"
    assert third["key"] == "#"
    assert third["suggested_control_role"] == "confirm_candidate"
    for payload in persisted:
        assert payload["phase1_safety_decision_change_allowed"] is False
        assert payload["remote_outbound_allowed"] is False
        assert payload["hardware_control_scope"] == "diagnostic_input_only"
        assert payload["sos_gesture_detected"] is False
        assert payload["grove_ports"] == DEFAULT_GROVE_PORTS


def test_keypad_custom_pins_and_active_high_are_reflected() -> None:
    result = run_cli(
        "--dry-run",
        "--rows",
        "18,23,24,25",
        "--cols",
        "4,22,27,26",
        "--active-high",
        "--simulate-keys",
        "D",
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    event = summary["events"][0]
    assert summary["rows"] == [18, 23, 24, 25]
    assert summary["cols"] == [4, 22, 27, 26]
    assert summary["grove_ports"] is None
    assert summary["active_mode"] == "active_high"
    assert event["key"] == "D"
    assert event["row_gpio"] == 25
    assert event["col_gpio"] == 26


def test_keypad_can_opt_into_active_low() -> None:
    result = run_cli(
        "--dry-run",
        "--active-low",
        "--simulate-keys",
        "1",
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["active_mode"] == "active_low"
    assert summary["events"][0]["active_mode"] == "active_low"


def test_keypad_visual_dry_run_updates_oled_and_led() -> None:
    result = run_cli(
        "--dry-run",
        "--simulate-keys",
        "A",
        "--oled-status",
        "--oled-dry-run",
        "--led-status",
        "--led-dry-run",
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    event = summary["events"][0]
    assert event["key"] == "A"
    assert event["visual_updates"] == [
        {
            "target": "oled",
            "write_status": "dry_run",
            "bus": "/dev/i2c-1",
            "address": "0x3c",
            "driver": "sh1107g",
            "message": "SCOUT KEY\nKEY A\nR1 C4\nDIAG ONLY",
        },
        {
            "target": "led_bar",
            "write_status": "dry_run",
            "port": "D5",
            "data_gpio": 5,
            "clock_gpio": 6,
            "bits": "0x008",
            "blink_seconds": 0.25,
        },
    ]


def test_keypad_mapping_helpers() -> None:
    key_press = key_press_for_key("D", rows=DEFAULT_ROWS, cols=DEFAULT_COLS)

    assert key_press.row_index == 3
    assert key_press.col_index == 3
    assert key_press.row_gpio == 19
    assert key_press.col_gpio == 27
    assert keypad_oled_message(key_press) == "SCOUT KEY\nKEY D\nR4 C4\nDIAG ONLY"
    assert led_bits_for_key(key_press) == 0x020


def test_keypad_invalid_pin_list_fails_cleanly() -> None:
    result = run_cli("--dry-run", "--rows", "5,6,13", "--simulate-keys", "1")

    assert result.returncode == 2
    assert "GPIO list must contain exactly 4 pins" in result.stderr


def test_keypad_requires_rows_and_cols_together() -> None:
    result = run_cli("--dry-run", "--rows", "5,6,13,19", "--simulate-keys", "1")

    assert result.returncode == 2
    assert "--rows and --cols must be provided together" in result.stderr


def test_keypad_invalid_grove_port_fails_cleanly() -> None:
    result = run_cli("--dry-run", "--grove-ports", "D16,D18,D24,D99", "--simulate-keys", "1")

    assert result.returncode == 2
    assert "unsupported Grove digital port" in result.stderr


def test_keypad_invalid_simulated_key_fails_cleanly() -> None:
    result = run_cli("--dry-run", "--simulate-keys", "X")

    assert result.returncode == 2
    assert "unsupported keypad key" in result.stderr
