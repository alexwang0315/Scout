import json
import subprocess
import sys
from pathlib import Path

from tools.pi_grove_led_bar_smoke import DEFAULT_PORT, bit_values_from_10bit, write_led_bar_bits


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "pi_grove_led_bar_smoke.py"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_led_bar_d5_default_dry_run_writes_boundary_payload(tmp_path: Path) -> None:
    output = tmp_path / "led.jsonl"

    result = run_cli(
        "--dry-run",
        "--pattern",
        "status_bits",
        "--bits",
        "0x155",
        "--output-jsonl",
        str(output),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    persisted = json.loads(output.read_text().splitlines()[0])
    assert payload == persisted
    assert payload["source"] == "pi_grove_led_bar_smoke"
    assert payload["hardware_kind"] == "grove_led_bar_v2_my9221"
    assert payload["port"] == DEFAULT_PORT
    assert payload["data_gpio"] == 5
    assert payload["clock_gpio"] == 6
    assert payload["pattern"] == "status_bits"
    assert payload["bits"] == "0x155"
    assert payload["write_status"] == "dry_run"
    assert payload["phase1_safety_decision_change_allowed"] is False
    assert payload["remote_outbound_allowed"] is False
    assert payload["hardware_control_scope"] == "diagnostic_indicator_only"


def test_led_bar_d5_mapping_and_pattern_bits() -> None:
    result = run_cli("--dry-run", "--port", "D5", "--pattern", "even")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["port"] == "D5"
    assert payload["data_gpio"] == 5
    assert payload["clock_gpio"] == 6
    assert payload["bits"] == "0x2aa"


def test_led_bar_d16_mapping_remains_available() -> None:
    result = run_cli("--dry-run", "--port", "D16", "--pattern", "first_half")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["port"] == "D16"
    assert payload["data_gpio"] == 16
    assert payload["clock_gpio"] == 17
    assert payload["bits"] == "0x01f"


def test_led_bar_custom_gpio_overrides_port_defaults() -> None:
    result = run_cli("--dry-run", "--port", "D16", "--data-gpio", "20", "--clock-gpio", "21")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["data_gpio"] == 20
    assert payload["clock_gpio"] == 21


def test_led_bar_status_bits_requires_bits() -> None:
    result = run_cli("--dry-run", "--pattern", "status_bits")

    assert result.returncode == 2
    assert "--bits is required for status_bits" in result.stderr


def test_led_bar_invalid_pattern_fails_cleanly() -> None:
    result = run_cli("--dry-run", "--pattern", "bad")

    assert result.returncode == 2
    assert "invalid choice" in result.stderr


def test_led_bar_10_bits_are_padded_to_12_my9221_channels() -> None:
    values = bit_values_from_10bit(0x3FF)

    assert values == [0x00FF] * 10 + [0x0000, 0x0000]


def test_led_bar_writer_uses_seeed_like_command_channels_and_latch() -> None:
    class FakeWriter:
        def __init__(self) -> None:
            self.events: list[tuple[str, int, int]] = []

        def setup_output(self, gpio: int) -> None:
            self.events.append(("setup", gpio, 0))

        def write(self, gpio: int, value: int) -> None:
            self.events.append(("write", gpio, value))

        def close(self) -> None:
            pass

    writer = FakeWriter()
    write_led_bar_bits(writer, data_gpio=16, clock_gpio=17, bits=0x001)

    writes = [event for event in writer.events if event[0] == "write"]
    clock_writes = [event for event in writes if event[1] == 17]
    data_writes = [event for event in writes if event[1] == 16]

    assert len(bit_values_from_10bit(0x001)) == 12
    assert len(clock_writes) == 16 * 13 + 6
    assert clock_writes[:4] == [
        ("write", 17, 0),
        ("write", 17, 1),
        ("write", 17, 0),
        ("write", 17, 1),
    ]
    assert data_writes[-8:] == [
        ("write", 16, 1),
        ("write", 16, 0),
        ("write", 16, 1),
        ("write", 16, 0),
        ("write", 16, 1),
        ("write", 16, 0),
        ("write", 16, 1),
        ("write", 16, 0),
    ]
