import json
import subprocess
import sys
from pathlib import Path

from tools.pi_wio_e5_lorawan_at_smoke import (
    DEFAULT_BAUD,
    DEFAULT_COMMANDS,
    DEFAULT_PORT,
    build_summary,
    extract_device_identity,
    led_bits_for_summary,
    parse_commands,
    response_status_from_lines,
    wio_e5_oled_message,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "pi_wio_e5_lorawan_at_smoke.py"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_wio_e5_dry_run_writes_boundary_payloads(tmp_path: Path) -> None:
    output = tmp_path / "wio-e5.jsonl"

    result = run_cli("--dry-run", "--output-jsonl", str(output))

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    persisted = [json.loads(line) for line in output.read_text().splitlines()]
    assert summary["source"] == "pi_wio_e5_lorawan_at_smoke"
    assert summary["hardware_kind"] == "wio_e5_lorawan_usb_serial_at"
    assert summary["device_port"] == DEFAULT_PORT
    assert summary["baud"] == DEFAULT_BAUD
    assert summary["commands"] == list(DEFAULT_COMMANDS)
    assert summary["command_count"] == 3
    assert summary["ok_count"] == 3
    assert summary["failed_count"] == 0
    assert persisted == summary["responses"]
    assert summary["radio_tx_allowed"] is False
    assert summary["join_allowed"] is False
    assert summary["lorawan_uplink_allowed"] is False
    assert summary["phase1_safety_decision_change_allowed"] is False
    assert summary["remote_outbound_allowed"] is False
    assert summary["hardware_control_scope"] == "diagnostic_serial_at_only"
    assert summary["device_identity"]["deveui"] == "00:00:00:00:00:00:00:00"
    for payload in persisted:
        assert payload["command_safe_for_diagnostic"] is True
        assert payload["response_status"] == "ok"
        assert payload["radio_tx_allowed"] is False
        assert payload["join_allowed"] is False
        assert payload["lorawan_uplink_allowed"] is False
        assert payload["phase1_safety_decision_change_allowed"] is False
        assert payload["remote_outbound_allowed"] is False
        assert payload["hardware_control_scope"] == "diagnostic_serial_at_only"


def test_wio_e5_custom_safe_commands_are_normalized() -> None:
    commands = parse_commands(" at , at+ver , at+id? ")

    assert commands == ["AT", "AT+VER", "AT+ID?"]


def test_wio_e5_visual_dry_run_updates_oled_and_led() -> None:
    result = run_cli(
        "--dry-run",
        "--oled-status",
        "--oled-dry-run",
        "--led-status",
        "--led-dry-run",
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["oled_status_updates"] == [
        {
            "captured_at": summary["oled_status_updates"][0]["captured_at"],
            "source": "pi_wio_e5_lorawan_oled_status",
            "hardware_kind": "grove_oled_96x96_i2c",
            "bus": "/dev/i2c-1",
            "address": "0x3c",
            "driver": "sh1107g",
            "driver_attempted": "sh1107g",
            "write_status": "dry_run",
            "dry_run": True,
            "message": "SCOUT LORA\nAT OK\nAT 3/3\nEUI 00000000\nTTYUSB0\nNO RF TX",
            "radio_tx_allowed": False,
            "join_allowed": False,
            "lorawan_uplink_allowed": False,
            "phase1_safety_decision_change_allowed": False,
            "remote_outbound_allowed": False,
            "hardware_control_scope": "diagnostic_display_only",
        }
    ]
    assert summary["led_status_updates"] == [
        {
            "captured_at": summary["led_status_updates"][0]["captured_at"],
            "source": "pi_wio_e5_lorawan_led_status",
            "hardware_kind": "grove_led_bar_v2_my9221",
            "port": "D5",
            "data_gpio": 5,
            "clock_gpio": 6,
            "bits": "0x040",
            "at_ok_count": 3,
            "at_failed_count": 0,
            "ok_led_bit": 7,
            "fail_led_bit": 10,
            "blink_count": 2,
            "blink_seconds": 0.25,
            "write_status": "dry_run",
            "dry_run": True,
            "radio_tx_allowed": False,
            "join_allowed": False,
            "lorawan_uplink_allowed": False,
            "phase1_safety_decision_change_allowed": False,
            "remote_outbound_allowed": False,
            "hardware_control_scope": "diagnostic_indicator_only",
        }
    ]


def test_wio_e5_blocks_join_and_uplink_before_serial_open() -> None:
    result = run_cli("--dry-run", "--commands", "AT,AT+JOIN")

    assert result.returncode == 2
    assert "blocked AT command 'AT+JOIN'" in result.stderr
    assert "join, uplink, send, test-TX, or RF action commands are blocked" in result.stderr


def test_wio_e5_blocks_mutating_assignment_commands() -> None:
    result = run_cli("--dry-run", "--commands", "AT+DR=5")

    assert result.returncode == 2
    assert "commands with '='" in result.stderr


def test_wio_e5_invalid_command_fails_cleanly() -> None:
    result = run_cli("--dry-run", "--commands", "PING")

    assert result.returncode == 2
    assert "AT commands must start with AT" in result.stderr


def test_wio_e5_invalid_oled_address_fails_cleanly() -> None:
    result = run_cli("--dry-run", "--oled-status", "--oled-dry-run", "--oled-address", "0x80")

    assert result.returncode == 2
    assert "I2C address must be between 0x03 and 0x77" in result.stderr


def test_wio_e5_status_and_visual_helpers() -> None:
    assert response_status_from_lines([]) == "timeout"
    assert response_status_from_lines(["+AT: OK"]) == "ok"
    assert response_status_from_lines(["+ERR: -1"]) == "error"

    responses = [
        {
            "response_status": "ok",
            "response_lines": [
                "+ID: DevAddr, 12:34:56:78",
                "+ID: DevEui, 00:11:22:33:44:55:66:77",
                "+ID: AppEui, AA:BB:CC:DD:EE:FF:00:11",
            ],
        }
    ]
    summary = build_summary(
        port="/dev/serial/by-id/usb-Silicon_Labs_CP2102N_USB_to_UART_Bridge_Controller_621f02193301f111a009d13e364a576b-if00-port0",
        baud=9600,
        commands=["AT+ID"],
        dry_run=True,
        payloads=responses,
        oled_status_updates=[],
        led_status_updates=[],
    )
    assert extract_device_identity(responses)["deveui"] == "00:11:22:33:44:55:66:77"
    assert "EUI 44556677" in wio_e5_oled_message(summary)
    assert led_bits_for_summary(summary, ok_bit=7, fail_bit=10) == 0x040

    failed_summary = {**summary, "ok_count": 0, "failed_count": 1}
    assert "AT FAIL" in wio_e5_oled_message(failed_summary)
    assert led_bits_for_summary(failed_summary, ok_bit=7, fail_bit=10) == 0x200
