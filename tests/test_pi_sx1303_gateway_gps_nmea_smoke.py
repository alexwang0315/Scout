import json
import subprocess
import sys
from pathlib import Path

from tools.pi_sx1303_gateway_gps_nmea_smoke import (
    DEFAULT_BAUD_RATES,
    DEFAULT_PORTS,
    analyze_raw_sample,
    build_summary,
    candidate_status,
    choose_best_candidate,
    extract_nmea_lines,
    gateway_gps_oled_message,
    led_bits_for_summary,
    parse_csv_baud_rates,
    parse_csv_ports,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "pi_sx1303_gateway_gps_nmea_smoke.py"
GGA = "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47"
RMC = "$GPRMC,092751.000,A,5321.6802,N,00630.3372,W,0.06,31.66,280511,,,A*46"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_analyze_raw_sample_detects_l76k_nmea_inside_noise() -> None:
    raw = b"\x00bad-prefix\r\n" + GGA.encode("ascii") + b"\r\n" + RMC.encode("ascii") + b"\r\n"

    candidate = analyze_raw_sample(raw=raw, port="/dev/serial0", baud=9600)

    assert candidate["status"] == "nmea_ok"
    assert candidate["bytes_read"] == len(raw)
    assert candidate["nmea_sentence_count"] == 2
    assert candidate["checksum_valid_count"] == 2
    assert candidate["nmea_sentence_types"] == ["GPGGA", "GPRMC"]
    assert candidate["first_nmea_payload"]["source"] == "pi_gnss_nmea_smoke"
    assert candidate["first_nmea_payload"]["primary_truth_scope"] == "raw_gnss_observation_only"
    assert candidate["gnss_fix_summary"]["valid_fix_count"] == 2
    assert candidate["gnss_fix_summary"]["has_valid_fix"] is True


def test_analyze_raw_sample_classifies_bad_stream_without_crashing() -> None:
    raw = bytes.fromhex("e9c26a52223a391d3131b1c9d5c1cdb9")

    candidate = analyze_raw_sample(raw=raw, port="/dev/serial0", baud=9600)

    assert candidate["status"] == "bad_stream"
    assert candidate["bytes_read"] == len(raw)
    assert candidate["nmea_sentence_count"] == 0
    assert candidate["checksum_valid_count"] == 0
    assert candidate["raw_sample_hex"] == raw.hex()
    assert "\ufffd" not in candidate["raw_sample_text"]


def test_candidate_status_matrix() -> None:
    assert candidate_status(read_status="missing_device", bytes_read=0, nmea_sentence_count=0, checksum_valid_count=0) == "missing_device"
    assert candidate_status(read_status="dry_run", bytes_read=0, nmea_sentence_count=0, checksum_valid_count=0) == "not_scanned_dry_run"
    assert candidate_status(read_status="error", bytes_read=0, nmea_sentence_count=0, checksum_valid_count=0) == "read_error"
    assert candidate_status(read_status="ok", bytes_read=0, nmea_sentence_count=0, checksum_valid_count=0) == "no_stream"
    assert candidate_status(read_status="ok", bytes_read=4, nmea_sentence_count=0, checksum_valid_count=0) == "bad_stream"
    assert candidate_status(read_status="ok", bytes_read=80, nmea_sentence_count=1, checksum_valid_count=0) == "nmea_without_valid_checksum"
    assert candidate_status(read_status="ok", bytes_read=80, nmea_sentence_count=1, checksum_valid_count=1) == "nmea_ok"


def test_choose_best_candidate_prefers_valid_nmea_over_bad_stream() -> None:
    bad = analyze_raw_sample(raw=b"\xff\xfe\x00\x01", port="/dev/serial0", baud=9600)
    good = analyze_raw_sample(raw=GGA.encode("ascii"), port="/dev/ttyAMA0", baud=9600)

    assert choose_best_candidate([bad, good]) == good


def test_summary_keeps_gateway_gps_safety_boundaries_false() -> None:
    candidate = analyze_raw_sample(raw=GGA.encode("ascii"), port="/dev/ttyAMA0", baud=9600)
    summary = build_summary(
        ports=["/dev/ttyAMA0"],
        baud_rates=[9600],
        candidates=[candidate],
        duration_seconds=4.0,
        max_bytes=2048,
        configured_gps_tty_path="/dev/ttyS0",
        dry_run=False,
        raw_sample_mode=False,
        oled_status_updates=[],
        led_status_updates=[],
    )

    assert summary["source"] == "pi_sx1303_gateway_gps_nmea_smoke"
    assert summary["hardware_kind"] == "sx1303_gateway_hat_l76k_gnss_uart"
    assert summary["status"] == "nmea_ok"
    assert summary["nmea_available"] is True
    assert summary["selected_port"] == "/dev/ttyAMA0"
    assert summary["selected_baud"] == 9600
    assert summary["suggested_gateway_conf_update"] == {"gps_tty_path": "/dev/ttyAMA0"}
    assert summary["packet_forwarder_started"] is False
    assert summary["rf_tx_allowed"] is False
    assert summary["join_allowed"] is False
    assert summary["lorawan_uplink_allowed"] is False
    assert summary["phase1_safety_decision_change_allowed"] is False
    assert summary["remote_outbound_allowed"] is False
    assert summary["hardware_control_scope"] == "diagnostic_gateway_gnss_uart_only"


def test_oled_and_led_status_helpers_reflect_gateway_nmea_result() -> None:
    candidate = analyze_raw_sample(raw=GGA.encode("ascii"), port="/dev/serial0", baud=9600)
    summary = build_summary(
        ports=["/dev/serial0"],
        baud_rates=[9600],
        candidates=[candidate],
        duration_seconds=4.0,
        max_bytes=2048,
        configured_gps_tty_path="/dev/ttyS0",
        dry_run=False,
        raw_sample_mode=False,
        oled_status_updates=[],
        led_status_updates=[],
    )

    assert "SCOUT GW GPS" in gateway_gps_oled_message(summary)
    assert "NMEA OK" in gateway_gps_oled_message(summary)
    assert "PORT SERIAL0" in gateway_gps_oled_message(summary)
    assert led_bits_for_summary(summary, ok_bit=10, fail_bit=1) == 0x200

    failed_summary = {**summary, "status": "bad_stream", "nmea_available": False, "selected_port": None, "selected_baud": None}
    assert "BAD STREAM" in gateway_gps_oled_message(failed_summary)
    assert led_bits_for_summary(failed_summary, ok_bit=10, fail_bit=1) == 0x001


def test_cli_raw_sample_writes_summary_jsonl_and_visual_dry_run(tmp_path: Path) -> None:
    output = tmp_path / "sx1303-gps.jsonl"

    result = run_cli(
        "--raw-sample-text",
        GGA,
        "--sample-port",
        "/dev/serial0",
        "--sample-baud",
        "9600",
        "--oled-status",
        "--oled-dry-run",
        "--led-status",
        "--led-dry-run",
        "--output-jsonl",
        str(output),
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    persisted = [json.loads(line) for line in output.read_text().splitlines()]
    assert persisted == [summary]
    assert summary["raw_sample_mode"] is True
    assert summary["status"] == "nmea_ok"
    assert summary["nmea_available"] is True
    assert summary["candidates"][0]["capture_mode"] == "raw_nmea_argument"
    assert summary["candidates"][0]["first_nmea_payload"]["primary_truth_allowed"] is False
    assert summary["candidates"][0]["first_nmea_payload"]["primary_truth_scope"] == "diagnostic_replayed_nmea_only"
    assert summary["oled_status_updates"][0]["source"] == "pi_sx1303_gateway_gps_nmea_oled_status"
    assert summary["oled_status_updates"][0]["write_status"] == "dry_run"
    assert summary["oled_status_updates"][0]["nmea_available"] is True
    assert summary["oled_status_updates"][0]["phase1_safety_decision_change_allowed"] is False
    assert summary["led_status_updates"][0]["source"] == "pi_sx1303_gateway_gps_nmea_led_status"
    assert summary["led_status_updates"][0]["bits"] == "0x200"
    assert summary["led_status_updates"][0]["rf_tx_allowed"] is False


def test_cli_dry_run_uses_default_ports_without_opening_devices() -> None:
    result = run_cli("--dry-run", "--duration-seconds", "0", "--max-bytes", "8")

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["ports_scanned"] == list(DEFAULT_PORTS)
    assert summary["baud_rates_scanned"] == list(DEFAULT_BAUD_RATES)
    assert summary["candidate_count"] == len(DEFAULT_PORTS) * len(DEFAULT_BAUD_RATES)
    assert {candidate["status"] for candidate in summary["candidates"]} == {"not_scanned_dry_run"}
    assert summary["packet_forwarder_started"] is False
    assert summary["rf_tx_allowed"] is False


def test_cli_raw_sample_hex_bad_stream_fails_cleanly_as_diagnostic_success() -> None:
    result = run_cli("--raw-sample-hex", "e9c26a52223a391d3131")

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["status"] == "bad_stream"
    assert summary["nmea_available"] is False
    assert summary["suggested_gateway_conf_update"] is None


def test_invalid_cli_arguments_fail_cleanly() -> None:
    assert parse_csv_ports(" /dev/serial0, /dev/ttyAMA0 ") == ["/dev/serial0", "/dev/ttyAMA0"]
    assert parse_csv_baud_rates("9600,115200") == [9600, 115200]
    assert extract_nmea_lines(f"noise {GGA}\r\n") == [GGA]

    result = run_cli("--baud-rates", "9600,abc")
    assert result.returncode == 2
    assert "invalid baud rate: abc" in result.stderr

    result = run_cli("--led-ok-bit", "11")
    assert result.returncode == 2
    assert "LED bit must be between 1 and 10" in result.stderr
