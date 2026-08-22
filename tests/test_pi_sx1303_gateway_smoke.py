from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tools.pi_sx1303_gateway_smoke import boundary_fields, parse_chip_id_output


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "pi_sx1303_gateway_smoke.py"

CHIP_ID_OUTPUT = """Resetting Pins...
Opening SPI communication interface
Note: chip version is 0x12 (v1.2)
INFO: using legacy timestamp
ARB: dual demodulation disabled for all SF
INFO: found temperature sensor on port 0x39

INFO: concentrator EUI: 0x0016c001f11f5f46

Closing SPI communication interface
"""


def test_parse_chip_id_output_extracts_gateway_eui_and_chip_version() -> None:
    parsed = parse_chip_id_output(CHIP_ID_OUTPUT)

    assert parsed["gateway_eui"] == "0x0016c001f11f5f46"
    assert parsed["chip_version"] == "0x12"
    assert parsed["temperature_sensor_detected"] is True
    assert parsed["legacy_timestamp"] is True
    assert parsed["dual_demodulation_disabled"] is True


def test_cli_parses_chip_id_output_writes_jsonl_and_visual_dry_run(tmp_path: Path) -> None:
    output_jsonl = tmp_path / "sx1303-gateway-smoke.jsonl"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--chip-id-output",
            CHIP_ID_OUTPUT,
            "--output-jsonl",
            str(output_jsonl),
            "--oled-status",
            "--oled-dry-run",
            "--led-status",
            "--led-dry-run",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    stdout_payload = json.loads(result.stdout)
    records = [json.loads(line) for line in output_jsonl.read_text(encoding="utf-8").splitlines()]
    payload = records[-1]

    assert stdout_payload["source"] == "pi_sx1303_gateway_smoke"
    assert payload["hardware_kind"] == "sx1303_lorawan_gateway_hat"
    assert payload["status"] == "ok"
    assert payload["gateway_eui"] == "0x0016c001f11f5f46"
    assert payload["chip_version"] == "0x12"
    assert payload["rf_receive_path_checked"] is True
    assert payload["rf_read_scope"] == "spi_chip_id_only"
    assert payload["packet_forwarder_started"] is False
    assert payload["rf_tx_allowed"] is False
    assert payload["lorawan_uplink_allowed"] is False
    assert payload["phase1_safety_decision_change_allowed"] is False
    assert payload["remote_outbound_allowed"] is False
    assert payload["hardware_control_scope"] == "diagnostic_gateway_evidence_only"
    assert payload["oled_status_updates"][0]["write_status"] == "dry_run"
    assert "RF OK" in payload["oled_status_updates"][0]["message"]
    assert payload["led_status_updates"][0]["write_status"] == "dry_run"
    assert payload["led_status_updates"][0]["bits"] == "0x040"
    assert payload["read_only"] == boundary_fields()["read_only"]


def test_cli_dry_run_never_requires_hardware_or_writes_when_disabled(tmp_path: Path) -> None:
    output_jsonl = tmp_path / "should-not-exist.jsonl"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--dry-run",
            "--no-output-jsonl",
            "--output-jsonl",
            str(output_jsonl),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "dry_run"
    assert payload["rf_receive_path_checked"] is False
    assert payload["rf_tx_allowed"] is False
    assert not output_jsonl.exists()


def test_cli_invalid_led_bit_fails_cleanly() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--led-ok-bit", "11"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "LED bit must be between 1 and 10" in result.stderr
