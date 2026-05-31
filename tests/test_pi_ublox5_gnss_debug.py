import json
import subprocess
import sys
from pathlib import Path

from tools.pi_ublox5_gnss_debug import (
    build_debug_payload,
    parse_cfg_ant,
    parse_mon_hw,
    parse_nav_svinfo,
    parse_nmea_pubx,
    parse_nmea_txt,
    parse_rxm_svsi,
    parse_nmea_gsv,
    ubx_checksum,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "pi_ublox5_gnss_debug.py"


def test_parse_mon_hw_extracts_antenna_supervisor_fields() -> None:
    payload = bytearray(68)
    payload[16:18] = (42).to_bytes(2, "little")
    payload[18:20] = (320).to_bytes(2, "little")
    payload[20] = 2
    payload[21] = 1

    parsed = parse_mon_hw(bytes(payload))

    assert parsed["noise_per_ms"] == 42
    assert parsed["agc_count"] == 320
    assert parsed["antenna_status_label"] == "OK"
    assert parsed["antenna_power_label"] == "ON"


def test_parse_cfg_ant_extracts_antenna_control_flags() -> None:
    payload = (0x001B).to_bytes(2, "little") + (0x1234).to_bytes(2, "little")

    parsed = parse_cfg_ant(payload)

    assert parsed["flags"] == 0x001B
    assert parsed["pins"] == 0x1234
    assert parsed["flags_decoded"] == {
        "svcs": True,
        "scd": True,
        "ocd": False,
        "pdwn_on_scd": True,
        "recovery": True,
    }


def test_parse_nav_svinfo_extracts_cno_per_channel() -> None:
    payload = bytearray(8 + 24)
    payload[0:4] = (123456).to_bytes(4, "little")
    payload[4] = 2
    payload[8:20] = _svinfo_channel(channel=0, svid=3, cno=42, elevation=51, azimuth=135)
    payload[20:32] = _svinfo_channel(channel=1, svid=7, cno=0, elevation=0, azimuth=0)

    parsed = parse_nav_svinfo(bytes(payload))

    assert parsed["num_channels"] == 2
    assert parsed["parsed_channels"] == 2
    assert parsed["nonzero_cno_count"] == 1
    assert parsed["max_cno_dbhz"] == 42
    assert parsed["channels"][0]["svid"] == 3


def test_parse_rxm_svsi_extracts_visible_satellite_header_and_records() -> None:
    payload = bytearray(8 + 6)
    payload[0:4] = (123456).to_bytes(4, "little")
    payload[4:6] = (2212).to_bytes(2, "little", signed=True)
    payload[6] = 1
    payload[7] = 1
    payload[8] = 3
    payload[9] = 0x5A
    payload[10:12] = (135).to_bytes(2, "little", signed=True)
    payload[12] = 45
    payload[13] = 9

    parsed = parse_rxm_svsi(bytes(payload))

    assert parsed["itow_ms"] == 123456
    assert parsed["week"] == 2212
    assert parsed["num_visible_sats"] == 1
    assert parsed["num_svs"] == 1
    assert parsed["satellites"][0]["svid"] == 3
    assert parsed["satellites"][0]["elevation_deg"] == 45


def test_parse_nmea_gsv_extracts_satellite_cno_values() -> None:
    raw = "$GPGSV,2,1,05,01,40,083,42,02,17,308,30,03,12,120,,04,08,044,18*70\n"

    parsed = parse_nmea_gsv(raw)

    assert parsed["sentence_count"] == 1
    assert parsed["reported_visible_satellites"] == 5
    assert parsed["parsed_satellites"] == 4
    assert parsed["nonzero_cno_count"] == 3
    assert parsed["max_cno_dbhz"] == 42


def test_parse_pubx_and_txt_fallback_sentences() -> None:
    raw = "\n".join(
        [
            "$PUBX,00,000000.00,,,,,NF,0,0,99.99,,,,,,0,0,0*00",
            "$PUBX,03,00*00",
            "$GPTXT,01,01,01,ANTENNA OK*35",
        ]
    )

    pubx = parse_nmea_pubx(raw)
    txt = parse_nmea_txt(raw)

    assert pubx["pubx00_seen"] is True
    assert pubx["pubx03_seen"] is True
    assert pubx["by_message"] == {"00": 1, "03": 1}
    assert txt["antenna_text_status"] == "OK"


def test_debug_payload_summarizes_ok_antenna_and_rf_signal() -> None:
    data = _ubx_frame(0x0A, 0x09, _mon_hw_payload(status=2, power=1)) + _ubx_frame(
        0x01,
        0x30,
        _nav_svinfo_payload(cno=38),
    )

    payload = build_debug_payload(data=data, device_port="/dev/ttyAMA0", baud=9600)

    assert payload["ubx_supported_observed"] is True
    assert payload["summary"]["antenna_status_label"] == "OK"
    assert payload["summary"]["antenna_power_label"] == "ON"
    assert payload["summary"]["max_cno_dbhz"] == 38
    assert payload["summary"]["likely_state"] == "rf_signal_observed"
    assert payload["hardware_control_scope"] == "diagnostic_poll_only"


def test_debug_payload_summarizes_cfg_ant_and_ack_nak_command_response() -> None:
    data = (
        _ubx_frame(0x06, 0x13, (0x001B).to_bytes(2, "little") + (0).to_bytes(2, "little"))
        + _ubx_frame(0x05, 0x00, bytes([0x0A, 0x09]))
        + b"$GPTXT,01,01,01,ANTENNA OK*35\r\n"
    )

    payload = build_debug_payload(data=data, device_port="/dev/ttyUSB0", baud=115200)

    assert payload["summary"]["ubx_cfg_ant_seen"] is True
    assert payload["summary"]["antenna_config_flags_decoded"]["svcs"] is True
    assert payload["summary"]["antenna_text_status"] == "OK"
    assert payload["summary"]["ubx_ack_nak_count"] == 1
    assert payload["summary"]["command_path_state"] == "receiver_response_observed"
    assert payload["ubx_frames"]["ACK-NAK"][0]["parsed"]["target_key"] == "MON-HW"


def test_debug_payload_summarizes_antenna_short_before_cno() -> None:
    data = _ubx_frame(0x0A, 0x09, _mon_hw_payload(status=3, power=0))

    payload = build_debug_payload(data=data, device_port="/dev/ttyAMA0", baud=9600)

    assert payload["summary"]["likely_state"] == "antenna_bias_short"


def test_cli_raw_hex_writes_jsonl(tmp_path: Path) -> None:
    output = tmp_path / "ublox.jsonl"
    raw = _ubx_frame(0x0A, 0x09, _mon_hw_payload(status=4, power=2)).hex()

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--raw-hex",
            raw,
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
    assert stdout_payload["summary"]["likely_state"] == "antenna_open_or_not_connected"
    assert persisted[0]["summary"]["antenna_status_label"] == "OPEN"


def _ubx_frame(msg_class: int, msg_id: int, payload: bytes) -> bytes:
    length = len(payload).to_bytes(2, "little")
    body = bytes([msg_class, msg_id]) + length + payload
    return b"\xb5\x62" + body + bytes(ubx_checksum(body))


def _mon_hw_payload(*, status: int, power: int) -> bytes:
    payload = bytearray(68)
    payload[16:18] = (42).to_bytes(2, "little")
    payload[18:20] = (320).to_bytes(2, "little")
    payload[20] = status
    payload[21] = power
    return bytes(payload)


def _nav_svinfo_payload(*, cno: int) -> bytes:
    payload = bytearray(20)
    payload[4] = 1
    payload[8:20] = _svinfo_channel(channel=0, svid=3, cno=cno, elevation=51, azimuth=135)
    return bytes(payload)


def _svinfo_channel(*, channel: int, svid: int, cno: int, elevation: int, azimuth: int) -> bytes:
    raw = bytearray(12)
    raw[0] = channel
    raw[1] = svid
    raw[2] = 1
    raw[3] = 7
    raw[4] = cno
    raw[5] = elevation
    raw[6:8] = azimuth.to_bytes(2, "little", signed=True)
    raw[8:12] = (0).to_bytes(4, "little", signed=True)
    return bytes(raw)
