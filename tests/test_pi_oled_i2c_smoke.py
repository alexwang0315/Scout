import json
import subprocess
import sys
from pathlib import Path

from tools.pi_oled_i2c_smoke import (
    render_message_buffer,
    write_sh1107g,
    write_ssd1327,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "pi_oled_i2c_smoke.py"


class FakeI2cDevice:
    def __init__(self) -> None:
        self.commands: list[tuple[int, ...]] = []
        self.data_writes: list[bytes] = []

    def write_command(self, *commands: int) -> None:
        self.commands.append(commands)

    def write_data(self, data: bytes) -> None:
        self.data_writes.append(data)


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_oled_dry_run_writes_boundary_payload(tmp_path: Path) -> None:
    output = tmp_path / "oled.jsonl"

    result = run_cli(
        "--dry-run",
        "--bus",
        "/dev/i2c-1",
        "--address",
        "0x3c",
        "--driver",
        "sh1107g",
        "--message",
        "SCOUT",
        "--output-jsonl",
        str(output),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    persisted = json.loads(output.read_text().splitlines()[0])
    assert payload == persisted
    assert payload["source"] == "pi_oled_i2c_smoke"
    assert payload["hardware_kind"] == "grove_oled_96x96_i2c"
    assert payload["bus"] == "/dev/i2c-1"
    assert payload["address"] == "0x3c"
    assert payload["driver_attempted"] == "sh1107g"
    assert payload["write_status"] == "dry_run"
    assert payload["message"] == "SCOUT"
    assert payload["display_width"] == 128
    assert payload["display_height"] == 128
    assert payload["phase1_safety_decision_change_allowed"] is False
    assert payload["remote_outbound_allowed"] is False
    assert payload["hardware_control_scope"] == "diagnostic_display_only"


def test_oled_auto_dry_run_preserves_auto_driver_attempt() -> None:
    result = run_cli("--dry-run", "--driver", "auto")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["driver_attempted"] == "auto"
    assert payload["address"] == "0x3c"


def test_oled_invalid_address_fails_cleanly() -> None:
    result = run_cli("--dry-run", "--address", "0x80")

    assert result.returncode == 2
    assert "I2C address must be between 0x03 and 0x77" in result.stderr


def test_oled_invalid_driver_fails_cleanly() -> None:
    result = run_cli("--dry-run", "--driver", "bad")

    assert result.returncode == 2
    assert "invalid choice" in result.stderr


def test_render_message_buffer_supports_96_and_128_geometry() -> None:
    buffer_96 = render_message_buffer("SCOUT", width=96, height=96)
    buffer_128 = render_message_buffer("SCOUT\nGPS\nLAT 25.06376\nLON 121.65877", width=128, height=128)

    assert len(buffer_96) == 96 * 12
    assert len(buffer_128) == 128 * 16
    assert any(value for value in buffer_96)
    assert any(value for value in buffer_128)


def test_sh1107g_writer_uses_128x128_page_geometry_and_seeed_init_path() -> None:
    device = FakeI2cDevice()

    write_sh1107g(device, "SCOUT\nGPS")

    assert (0xD5, 0x50) in device.commands
    assert (0xAD, 0x80) in device.commands
    assert (0xDB, 0x27) in device.commands
    assert len(device.data_writes) == 16
    assert {len(data) for data in device.data_writes} == {128}


def test_ssd1327_writer_preserves_96x96_page_geometry() -> None:
    device = FakeI2cDevice()

    write_ssd1327(device, "SCOUT")

    assert len(device.data_writes) == 12
    assert {len(data) for data in device.data_writes} == {96}
