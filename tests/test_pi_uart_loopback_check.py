import json
import subprocess
import sys
from pathlib import Path

from tools.pi_uart_loopback_check import DEFAULT_PAYLOAD, evaluate_loopback


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "pi_uart_loopback_check.py"


def test_evaluate_loopback_passes_when_expected_payload_is_observed() -> None:
    payload = evaluate_loopback(
        port="/dev/ttyAMA0",
        baud=9600,
        expected=DEFAULT_PAYLOAD,
        observed=b"noise" + DEFAULT_PAYLOAD + b"tail",
        duration_seconds=2.0,
    )

    assert payload["loopback_passed"] is True
    assert payload["summary"]["likely_state"] == "uart_tx_rx_loopback_passed"
    assert payload["summary"]["scout_uart_tx_rx_proven"] is True
    assert payload["hardware_control_scope"] == "diagnostic_uart_loopback_requires_gnss_disconnected"


def test_evaluate_loopback_fails_when_payload_is_missing() -> None:
    payload = evaluate_loopback(
        port="/dev/ttyAMA0",
        baud=9600,
        expected=DEFAULT_PAYLOAD,
        observed=b"",
        duration_seconds=2.0,
    )

    assert payload["loopback_passed"] is False
    assert payload["summary"]["likely_state"] == "uart_tx_rx_loopback_failed"
    assert "GPIO14" in payload["summary"]["next_step"]


def test_cli_requires_explicit_loopback_confirmation_before_writing() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--port", "/dev/null"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "i-confirm-gnss-disconnected" in result.stderr


def test_cli_raw_observed_hex_does_not_require_hardware(tmp_path: Path) -> None:
    output = tmp_path / "loopback.json"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--raw-observed-hex",
            DEFAULT_PAYLOAD.hex(),
            "--output-json",
            str(output),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    stdout_payload = json.loads(result.stdout)
    persisted = json.loads(output.read_text())
    assert stdout_payload["loopback_passed"] is True
    assert persisted["loopback_passed"] is True
