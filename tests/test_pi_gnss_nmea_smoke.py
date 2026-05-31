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
    summarize_gnss_fix,
    summarize_gnss_signal,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "pi_gnss_nmea_smoke.py"
RMC = "$GPRMC,092751.000,A,5321.6802,N,00630.3372,W,0.06,31.66,280511,,,A*46"
GGA = "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47"
GSV = "$GPGSV,2,1,05,01,40,083,42,02,17,308,30,03,12,120,,04,08,044,18*7D"
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


def test_parse_gsv_preserves_satellite_signal_and_cno_values() -> None:
    parsed = parse_nmea_sentence(GSV)

    assert parsed is not None
    assert parsed["sentence_type"] == "GPGSV"
    assert parsed["position"] == {"lat": None, "lon": None, "altitude_m": None}
    assert parsed["fix_quality"]["valid"] is False
    assert parsed["fix_quality"]["satellites"] == 5
    assert parsed["satellite_signal"]["talker"] == "GP"
    assert parsed["satellite_signal"]["reported_visible_satellites"] == 5
    assert parsed["satellite_signal"]["parsed_satellites"] == 4
    assert parsed["satellite_signal"]["nonzero_cno_count"] == 3
    assert parsed["satellite_signal"]["max_cno_dbhz"] == 42
    assert parsed["satellite_signal"]["satellites"][0] == {
        "talker": "GP",
        "svid": 1,
        "elevation_deg": 40,
        "azimuth_deg": 83,
        "cno_dbhz": 42,
    }
    assert parsed["checksum_valid"] is True


def test_gnss_payload_primary_truth_scope_is_raw_gnss_only() -> None:
    payloads = parse_raw_nmea(f"{RMC}\n{GGA}", device_port="/dev/ttyUSB0", baud=9600)

    assert len(payloads) == 2
    assert all(payload["source"] == "pi_gnss_nmea_smoke" for payload in payloads)
    assert all(payload["hardware_kind"] == "serial_gnss_nmea" for payload in payloads)
    assert all(payload["primary_truth_allowed"] is True for payload in payloads)
    assert all(payload["primary_truth_scope"] == "raw_gnss_observation_only" for payload in payloads)
    assert all(payload["capture_mode"] == "serial_device" for payload in payloads)
    assert all(payload["phase1_safety_decision_change_allowed"] is False for payload in payloads)


def test_gnss_signal_summary_rolls_up_gsv_cno_evidence() -> None:
    payloads = parse_raw_nmea(
        "\n".join(
            [
                "$GPGSV,1,1,00,0*65",
                GSV,
                "$GLGSV,1,1,01,70,,,30,0*7C",
            ]
        ),
        device_port="/dev/ttyUSB0",
        baud=115200,
    )

    summary = summarize_gnss_signal(payloads)

    assert [payload["sentence_type"] for payload in payloads] == ["GPGSV", "GPGSV", "GLGSV"]
    assert summary["gsv_sentence_count"] == 3
    assert summary["reported_visible_satellites"] == 5
    assert summary["parsed_satellites"] == 5
    assert summary["nonzero_cno_count"] == 4
    assert summary["max_cno_dbhz"] == 42
    assert summary["gps_nonzero_cno_count"] == 3
    assert summary["gps_max_cno_dbhz"] == 42
    assert summary["talker_counts"] == {"GP": 2, "GL": 1}
    assert summary["talker_signal_summary"]["GP"] == {
        "gsv_sentence_count": 2,
        "reported_visible_satellites": 5,
        "parsed_satellites": 4,
        "nonzero_cno_count": 3,
        "max_cno_dbhz": 42,
        "rf_signal_observed": True,
    }
    assert summary["talker_signal_summary"]["GL"] == {
        "gsv_sentence_count": 1,
        "reported_visible_satellites": 1,
        "parsed_satellites": 1,
        "nonzero_cno_count": 1,
        "max_cno_dbhz": 30,
        "rf_signal_observed": True,
    }
    assert summary["talkers_with_cno"] == [
        {"talker": "GP", "max_cno_dbhz": 42, "nonzero_cno_count": 3},
        {"talker": "GL", "max_cno_dbhz": 30, "nonzero_cno_count": 1},
    ]
    assert summary["best_talker"] == "GP"
    assert summary["best_talker_cno_dbhz"] == 42


def test_gnss_fix_summary_rolls_up_fix_quality_and_latest_position() -> None:
    payloads = parse_raw_nmea(
        "\n".join(
            [
                NON_FIX_GGA,
                GGA,
                RMC,
                "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*00",
                GSV,
            ]
        ),
        device_port="/dev/ttyUSB0",
        baud=115200,
    )

    summary = summarize_gnss_fix(payloads)

    assert summary["payload_count"] == 5
    assert summary["has_valid_fix"] is True
    assert summary["valid_fix_count"] == 2
    assert summary["checksum_valid_count"] == 4
    assert summary["checksum_invalid_count"] == 1
    assert summary["sentence_type_counts"] == {"GPGGA": 3, "GPRMC": 1, "GPGSV": 1}
    assert summary["quality_counts"]["0"] == 1
    assert summary["quality_counts"]["1"] == 2
    assert summary["quality_counts"]["null"] == 2
    assert summary["status_counts"]["A"] == 1
    assert summary["latest_valid_fix"]["sentence_type"] == "GPRMC"
    assert summary["latest_valid_fix"]["position"]["lat"] == 53.36133667


def test_gnss_payload_with_invalid_checksum_is_diagnostic_only() -> None:
    payload = parse_raw_nmea(
        "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*00",
        device_port="/dev/ttyUSB0",
        baud=9600,
    )[0]

    assert payload["checksum_valid"] is False
    assert payload["primary_truth_allowed"] is False
    assert payload["primary_truth_scope"] == "invalid_gnss_checksum_diagnostic_only"


def test_gnss_smoke_cli_raw_nmea_writes_jsonl(tmp_path: Path) -> None:
    output = tmp_path / "gnss.jsonl"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--raw-nmea",
            f"{RMC}\n{GGA}\n{GSV}",
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
    assert stdout_payload["sentence_count"] == 3
    assert stdout_payload["gnss_fix_summary"]["valid_fix_count"] == 2
    assert stdout_payload["gnss_fix_summary"]["has_valid_fix"] is True
    assert stdout_payload["gnss_signal_summary"]["max_cno_dbhz"] == 42
    assert [item["sentence_type"] for item in persisted] == ["GPRMC", "GPGGA", "GPGSV"]
    assert [item["capture_mode"] for item in persisted] == [
        "raw_nmea_argument",
        "raw_nmea_argument",
        "raw_nmea_argument",
    ]
    assert all(item["primary_truth_allowed"] is False for item in persisted)
    assert all(item["primary_truth_scope"] == "diagnostic_replayed_nmea_only" for item in persisted)


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
