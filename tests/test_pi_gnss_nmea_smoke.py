import json
import subprocess
import sys
from pathlib import Path

from tools.pi_gnss_nmea_smoke import (
    _termios_baud_constant,
    build_gnss_stream_status_payload,
    gnss_led_bit,
    gnss_oled_message,
    parse_nmea_sentence,
    parse_raw_nmea,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "pi_gnss_nmea_smoke.py"
RMC = "$GPRMC,092751.000,A,5321.6802,N,00630.3372,W,0.06,31.66,280511,,,A*46"
GGA = "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47"
NON_FIX_GGA_BODY = "GPGGA,123520,,,,,0,00,99.9,,,,,,"
NON_FIX_GGA = f"${NON_FIX_GGA_BODY}*76"


def test_parse_rmc_minimum_gnss_position_and_time() -> None:
    parsed = parse_nmea_sentence(RMC)

    assert parsed is not None
    assert parsed["sentence_type"] == "GPRMC"
    assert parsed["gnss_time_utc"] == "2011-05-28T09:27:51.000Z"
    assert parsed["position"]["lat"] == 53.36133667
    assert parsed["position"]["lon"] == -6.50562
    assert parsed["fix_quality"]["valid"] is True
    assert parsed["checksum_valid"] is True


def test_parse_gga_minimum_fix_quality_altitude_and_hdop() -> None:
    parsed = parse_nmea_sentence(GGA)

    assert parsed is not None
    assert parsed["sentence_type"] == "GPGGA"
    assert parsed["gnss_time_utc"] == "12:35:19Z"
    assert parsed["position"]["lat"] == 48.1173
    assert parsed["position"]["lon"] == 11.51666667
    assert parsed["position"]["altitude_m"] == 545.4
    assert parsed["fix_quality"]["quality"] == 1
    assert parsed["fix_quality"]["satellites"] == 8
    assert parsed["fix_quality"]["hdop"] == 0.9


def test_gnss_payload_primary_truth_scope_is_raw_gnss_only() -> None:
    payloads = parse_raw_nmea(f"{RMC}\n{GGA}", device_port="/dev/ttyUSB0", baud=9600)

    assert len(payloads) == 2
    assert all(payload["source"] == "pi_gnss_nmea_smoke" for payload in payloads)
    assert all(payload["hardware_kind"] == "serial_gnss_nmea" for payload in payloads)
    assert all(payload["primary_truth_allowed"] is True for payload in payloads)
    assert all(payload["primary_truth_scope"] == "raw_gnss_observation_only" for payload in payloads)
    assert all(payload["phase1_safety_decision_change_allowed"] is False for payload in payloads)


def test_gnss_smoke_cli_raw_nmea_writes_jsonl(tmp_path: Path) -> None:
    output = tmp_path / "gnss.jsonl"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--raw-nmea",
            f"{RMC}\n{GGA}",
            "--output-jsonl",
            str(output),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    stdout_payload = json.loads(result.stdout)
    persisted = [json.loads(line) for line in output.read_text().splitlines()]
    assert stdout_payload["sentence_count"] == 2
    assert [item["sentence_type"] for item in persisted] == ["GPRMC", "GPGGA"]


def test_gnss_oled_message_summarizes_fix_state_and_nmea_signal() -> None:
    payload = parse_raw_nmea(GGA, device_port="/dev/ttyUSB0", baud=9600)[0]

    message = gnss_oled_message(payload, sentence_count=3)

    assert "SCOUT GPS" in message
    assert "FIX OK" in message
    assert "NMEA GGA 3" in message
    assert "SAT 8 Q1" in message
    assert "CHK OK" in message
    assert "48.1173" in message


def test_gnss_oled_message_summarizes_non_fix_state() -> None:
    payload = parse_raw_nmea(NON_FIX_GGA, device_port="/dev/ttyUSB0", baud=9600)[0]

    message = gnss_oled_message(payload, sentence_count=1)

    assert "NO FIX" in message
    assert "NMEA GGA 1" in message
    assert "SAT 0 Q0" in message
    assert "SEARCH SKY" in message


def test_gnss_oled_message_summarizes_waiting_and_no_stream() -> None:
    waiting = build_gnss_stream_status_payload(state="waiting", device_port="/dev/serial0", baud=9600)
    no_stream = build_gnss_stream_status_payload(state="no_stream", device_port="/dev/serial0", baud=9600)

    waiting_message = gnss_oled_message(waiting, sentence_count=0)
    no_stream_message = gnss_oled_message(no_stream, sentence_count=0)

    assert "WAIT UART" in waiting_message
    assert "NMEA 0" in waiting_message
    assert "9600 BAUD" in waiting_message
    assert "LISTENING" in waiting_message
    assert "NO STREAM" in no_stream_message
    assert "CHECK UART" in no_stream_message


def test_gnss_led_bit_maps_non_fix_and_fix_segments() -> None:
    nofix_payload = parse_raw_nmea(NON_FIX_GGA, device_port="/dev/ttyUSB0", baud=9600)[0]
    fix_payload = parse_raw_nmea(GGA, device_port="/dev/ttyUSB0", baud=9600)[0]

    assert gnss_led_bit(nofix_payload, fix_bit=10, nofix_bit=1) == 0x001
    assert gnss_led_bit(fix_payload, fix_bit=10, nofix_bit=1) == 0x200
    assert (
        gnss_led_bit(
            build_gnss_stream_status_payload(state="waiting", device_port="/dev/serial0", baud=9600),
            fix_bit=10,
            nofix_bit=1,
        )
        == 0x003
    )
    assert (
        gnss_led_bit(
            build_gnss_stream_status_payload(state="no_stream", device_port="/dev/serial0", baud=9600),
            fix_bit=10,
            nofix_bit=1,
        )
        == 0x001
    )


def test_gnss_smoke_cli_raw_nmea_can_dry_run_oled_status(tmp_path: Path) -> None:
    output = tmp_path / "gnss.jsonl"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--raw-nmea",
            f"{NON_FIX_GGA}\n{GGA}",
            "--oled-status",
            "--oled-dry-run",
            "--output-jsonl",
            str(output),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    stdout_payload = json.loads(result.stdout)
    assert stdout_payload["sentence_count"] == 2
    assert len(stdout_payload["oled_status_updates"]) == 2
    first_update = stdout_payload["oled_status_updates"][0]
    second_update = stdout_payload["oled_status_updates"][1]
    assert first_update["source"] == "pi_gnss_nmea_oled_status"
    assert first_update["write_status"] == "dry_run"
    assert first_update["gnss_fix_state"] == "no_fix"
    assert first_update["nmea_sentence_type"] == "GGA"
    assert first_update["phase1_safety_decision_change_allowed"] is False
    assert first_update["remote_outbound_allowed"] is False
    assert first_update["hardware_control_scope"] == "diagnostic_display_only"
    assert second_update["gnss_fix_state"] == "fix"
    persisted = [json.loads(line) for line in output.read_text().splitlines()]
    assert len(persisted) == 2


def test_gnss_smoke_cli_raw_nmea_can_dry_run_led_status() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--raw-nmea",
            f"{NON_FIX_GGA}\n{GGA}",
            "--led-status",
            "--led-dry-run",
            "--led-fix-bit",
            "10",
            "--led-nofix-bit",
            "1",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    stdout_payload = json.loads(result.stdout)
    assert len(stdout_payload["led_status_updates"]) == 2
    first_update = stdout_payload["led_status_updates"][0]
    second_update = stdout_payload["led_status_updates"][1]
    assert first_update["source"] == "pi_gnss_nmea_led_status"
    assert first_update["write_status"] == "dry_run"
    assert first_update["port"] == "D5"
    assert first_update["data_gpio"] == 5
    assert first_update["clock_gpio"] == 6
    assert first_update["gnss_fix_state"] == "no_fix"
    assert first_update["bits"] == "0x001"
    assert first_update["nofix_led_bit"] == 1
    assert first_update["phase1_safety_decision_change_allowed"] is False
    assert first_update["remote_outbound_allowed"] is False
    assert first_update["hardware_control_scope"] == "diagnostic_indicator_only"
    assert second_update["gnss_fix_state"] == "fix"
    assert second_update["bits"] == "0x200"
    assert second_update["fix_led_bit"] == 10


def test_gnss_smoke_cli_empty_raw_nmea_still_updates_oled_and_led() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--raw-nmea",
            "",
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
    assert stdout_payload["sentence_count"] == 0
    assert stdout_payload["oled_status_updates"][0]["gnss_fix_state"] == "no_stream"
    assert "NO STREAM" in stdout_payload["oled_status_updates"][0]["message"]
    assert stdout_payload["led_status_updates"][0]["gnss_fix_state"] == "no_stream"
    assert stdout_payload["led_status_updates"][0]["bits"] == "0x001"
    assert stdout_payload["led_status_updates"][0]["phase1_safety_decision_change_allowed"] is False


def test_gnss_stdlib_serial_fallback_supports_common_baud() -> None:
    assert isinstance(_termios_baud_constant(9600), int)
    assert isinstance(_termios_baud_constant(115200), int)
