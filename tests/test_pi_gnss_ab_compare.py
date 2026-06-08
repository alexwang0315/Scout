import json
import subprocess
import sys
from pathlib import Path

from tools.pi_gnss_ab_compare import (
    build_ab_payload,
    build_auto_capture_targets,
    capture_auto_serial_candidates,
    capture_placement_sweep,
    discover_serial_candidates,
    nmea_checksum_valid,
    parse_nmea_capture,
)
from tools import pi_gnss_ab_compare


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "pi_gnss_ab_compare.py"
GROVE_NO_SIGNAL = "\n".join(
    [
        "$GPGGA,003100.799,,,,,0,0,,,M,,M,,*4D",
        "$GPGSA,A,1,,,,,,,,,,,,,,,*1E",
        "$GPGSV,1,1,00*79",
        "$GPRMC,003100.799,V,,,,,0.00,0.00,060180,,,N*47",
    ]
)
USB_GLONASS_ONLY = "\n".join(
    [
        "$GNGGA,,,,,,0,00,25.5,,,,,,*64",
        "$GPGSV,1,1,00,0*65",
        "$BDGSV,1,1,00,0*74",
        "$GLGSV,1,1,01,70,,,30,0*7C",
        "$GPTXT,01,01,01,ANTENNA OK*35",
        "$GNRMC,,V,,,,,,,,,,M,V*34",
    ]
)
GPS_SIGNAL_NO_FIX = "\n".join(
    [
        "$GNGGA,,,,,,0,00,25.5,,,,,,*64",
        "$GPGSV,1,1,01,03,45,180,38,0*54",
        "$GNRMC,,V,,,,,,,,,,M,V*34",
    ]
)


def test_nmea_checksum_validates_sentence_checksum() -> None:
    assert nmea_checksum_valid("$GPGSV,1,1,00*79") is True
    assert nmea_checksum_valid("$GPGSV,1,1,00*00") is False
    assert nmea_checksum_valid("not nmea") is None


def test_parse_grove_no_signal_capture() -> None:
    parsed = parse_nmea_capture(GROVE_NO_SIGNAL, label="grove", device_port="/dev/ttyAMA0", baud=9600)

    assert parsed["valid_checksum_lines"] == 4
    assert parsed["valid_GGA_count"] == 0
    assert parsed["valid_RMC_count"] == 0
    assert parsed["gsv_by_talker"]["GP"]["visible_max"] == 0
    assert parsed["summary"]["likely_state"] == "no_rf_signal_observed"


def test_parse_usb_non_gps_signal_and_antenna_text() -> None:
    parsed = parse_nmea_capture(USB_GLONASS_ONLY, label="usb")

    assert parsed["antenna_text_status"] == "OK"
    assert parsed["gsv_by_talker"]["GP"]["nonzero_cno_count"] == 0
    assert parsed["gsv_by_talker"]["GL"]["cno_max"] == 30
    assert parsed["summary"]["gps_rf_signal_observed"] is False
    assert parsed["summary"]["non_gps_rf_signal_observed"] is True
    assert parsed["summary"]["likely_state"] == "non_gps_rf_signal_observed_no_fix"


def test_comparison_requires_gps_rf_for_gps_only_hardware_discrimination() -> None:
    payload = build_ab_payload(
        [
            parse_nmea_capture(GROVE_NO_SIGNAL, label="grove"),
            parse_nmea_capture(USB_GLONASS_ONLY, label="usb"),
        ]
    )

    assert payload["comparison"]["labels_with_any_rf_signal"] == ["usb"]
    assert payload["comparison"]["labels_with_gps_rf_signal"] == []
    assert payload["comparison"]["gps_ab_discriminates_hardware"] is False
    assert payload["comparison"]["interpretation"] == "non_gps_rf_observed_but_gps_l1_not_available_for_gps_only_ab"


def test_comparison_marks_position_as_discriminating_when_gps_cno_exists() -> None:
    payload = build_ab_payload(
        [
            parse_nmea_capture(GROVE_NO_SIGNAL, label="grove"),
            parse_nmea_capture(GPS_SIGNAL_NO_FIX, label="usb"),
        ]
    )

    assert payload["comparison"]["labels_with_gps_rf_signal"] == ["usb"]
    assert payload["comparison"]["gps_ab_discriminates_hardware"] is True
    assert payload["captures"]["usb"]["summary"]["gps_max_cno_dbhz"] == 38


def test_discover_serial_candidates_prefers_stable_paths_and_deduplicates_real_device(tmp_path: Path) -> None:
    dev_dir = tmp_path / "dev"
    by_id_dir = dev_dir / "serial" / "by-id"
    by_id_dir.mkdir(parents=True)
    real_port = dev_dir / "ttyUSB0"
    real_port.write_text("", encoding="utf-8")
    stable_link = by_id_dir / "usb-1a86_USB_Serial-if00-port0"
    stable_link.symlink_to(real_port)

    candidates = discover_serial_candidates(
        serial_glob_patterns=[
            ("stable_by_id", str(by_id_dir / "*"), 0),
            ("linux_usb_serial", str(dev_dir / "ttyUSB*"), 10),
        ]
    )

    assert candidates == [
        {
            "path": str(stable_link),
            "real_path": str(real_port),
            "kind": "stable_by_id",
            "priority": 0,
            "stable_path_preferred": True,
        }
    ]


def test_build_auto_capture_targets_uses_stable_label_and_requested_baud(tmp_path: Path) -> None:
    candidate = {
        "path": str(tmp_path / "usb-1a86_USB Serial-if00-port0"),
        "real_path": str(tmp_path / "ttyUSB0"),
        "kind": "stable_by_id",
        "priority": 0,
        "stable_path_preferred": True,
    }

    targets = build_auto_capture_targets(baud=115200, serial_candidates=[candidate])

    assert targets[0].device_port == candidate["path"]
    assert targets[0].baud == 115200
    assert targets[0].label == "auto_0_stable_by_id_usb_1a86_USB_Serial_if00_port0_115200"


def test_capture_auto_serial_candidates_records_all_discovered_candidates(tmp_path: Path, monkeypatch) -> None:
    dev_dir = tmp_path / "dev"
    by_id_dir = dev_dir / "serial" / "by-id"
    by_id_dir.mkdir(parents=True)
    real_port = dev_dir / "ttyUSB0"
    real_port.write_text("", encoding="utf-8")
    stable_link = by_id_dir / "usb-1a86_USB_Serial-if00-port0"
    stable_link.symlink_to(real_port)

    monkeypatch.setattr(
        pi_gnss_ab_compare,
        "read_serial_bytes",
        lambda port, baud, *, duration_seconds: GPS_SIGNAL_NO_FIX.encode("ascii"),
    )

    captures, candidates = capture_auto_serial_candidates(
        bauds=[115200],
        duration_seconds=0.1,
        serial_glob_patterns=[("stable_by_id", str(by_id_dir / "*"), 0)],
    )

    assert candidates[0]["path"] == str(stable_link)
    assert captures[0]["device_port"] == str(stable_link)
    assert captures[0]["baud"] == 115200
    assert captures[0]["summary"]["gps_rf_signal_observed"] is True


def test_capture_auto_serial_candidates_skips_uart_by_default(tmp_path: Path, monkeypatch) -> None:
    dev_dir = tmp_path / "dev"
    by_id_dir = dev_dir / "serial" / "by-id"
    by_id_dir.mkdir(parents=True)
    real_port = dev_dir / "ttyUSB0"
    real_port.write_text("", encoding="utf-8")
    stable_link = by_id_dir / "usb-1a86_USB_Serial-if00-port0"
    stable_link.symlink_to(real_port)
    serial0 = dev_dir / "serial0"
    serial0.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        pi_gnss_ab_compare,
        "read_serial_bytes",
        lambda port, baud, *, duration_seconds: GPS_SIGNAL_NO_FIX.encode("ascii"),
    )

    captures, candidates = capture_auto_serial_candidates(
        bauds=[115200],
        duration_seconds=0.1,
        serial_glob_patterns=[
            ("stable_by_id", str(by_id_dir / "*"), 0),
            ("linux_uart_alias", str(serial0), 30),
        ],
    )

    assert [candidate["path"] for candidate in candidates] == [str(stable_link)]
    assert [capture["device_port"] for capture in captures] == [str(stable_link)]


def test_capture_auto_serial_candidates_can_include_uart_when_requested(tmp_path: Path, monkeypatch) -> None:
    dev_dir = tmp_path / "dev"
    by_id_dir = dev_dir / "serial" / "by-id"
    by_id_dir.mkdir(parents=True)
    real_port = dev_dir / "ttyUSB0"
    real_port.write_text("", encoding="utf-8")
    stable_link = by_id_dir / "usb-1a86_USB_Serial-if00-port0"
    stable_link.symlink_to(real_port)
    serial0 = dev_dir / "serial0"
    serial0.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        pi_gnss_ab_compare,
        "read_serial_bytes",
        lambda port, baud, *, duration_seconds: GPS_SIGNAL_NO_FIX.encode("ascii"),
    )

    captures, candidates = capture_auto_serial_candidates(
        bauds=[115200],
        duration_seconds=0.1,
        include_uart=True,
        serial_glob_patterns=[
            ("stable_by_id", str(by_id_dir / "*"), 0),
            ("linux_uart_alias", str(serial0), 30),
        ],
    )

    assert [candidate["path"] for candidate in candidates] == [str(stable_link), str(serial0)]
    assert [capture["device_port"] for capture in captures] == [str(stable_link), str(serial0)]


def test_capture_placement_sweep_ranks_same_receiver_positions(tmp_path: Path, monkeypatch) -> None:
    port = tmp_path / "ttyUSB0"
    port.write_text("", encoding="utf-8")
    captures = iter([GROVE_NO_SIGNAL.encode("ascii"), GPS_SIGNAL_NO_FIX.encode("ascii")])

    monkeypatch.setattr(
        pi_gnss_ab_compare,
        "read_serial_bytes",
        lambda port, baud, *, duration_seconds: next(captures),
    )

    placement_captures, resolution = capture_placement_sweep(
        placements=["current", "open_sky"],
        port=str(port),
        baud=115200,
        duration_seconds=0.1,
    )
    payload = build_ab_payload(placement_captures, duration_seconds=0.1)
    payload["placement_sweep"] = pi_gnss_ab_compare._placement_sweep_summary(placement_captures)

    assert resolution["resolution_status"] == "explicit_port"
    assert [capture["placement_label"] for capture in placement_captures] == ["current", "open_sky"]
    assert payload["placement_sweep"]["best_placement_label"] == "open_sky"
    assert payload["placement_sweep"]["placements_with_gps_rf_signal"] == ["open_sky"]
    assert payload["placement_sweep"]["ranked_placements"][0]["gps_max_cno_dbhz"] == 38


def test_capture_placement_sweep_auto_selects_first_serial_candidate(tmp_path: Path, monkeypatch) -> None:
    port = tmp_path / "ttyUSB0"
    port.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        pi_gnss_ab_compare,
        "read_serial_bytes",
        lambda port, baud, *, duration_seconds: GPS_SIGNAL_NO_FIX.encode("ascii"),
    )

    placement_captures, resolution = capture_placement_sweep(
        placements=["open_sky"],
        port="auto",
        baud=115200,
        duration_seconds=0.1,
        serial_candidates=[
            {
                "path": str(port),
                "real_path": str(port),
                "kind": "stable_by_id",
                "priority": 0,
                "stable_path_preferred": True,
            }
        ],
    )

    assert resolution["resolution_status"] == "selected_first_serial_candidate"
    assert resolution["resolved_port"] == str(port)
    assert resolution["candidates"][0]["path"] == str(port)
    assert placement_captures[0]["device_port"] == str(port)
    assert placement_captures[0]["summary"]["gps_max_cno_dbhz"] == 38


def test_cli_raw_files_write_comparison_json(tmp_path: Path) -> None:
    grove = tmp_path / "grove.nmea"
    usb = tmp_path / "usb.nmea"
    output = tmp_path / "ab.json"
    grove.write_text(GROVE_NO_SIGNAL)
    usb.write_text(USB_GLONASS_ONLY)

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--raw-file",
            f"grove={grove}",
            "--raw-file",
            f"usb={usb}",
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
    assert stdout_payload["capture_count"] == 2
    assert persisted["captures"]["usb"]["antenna_text_status"] == "OK"


def test_cli_placement_sweep_writes_summary(tmp_path: Path, monkeypatch) -> None:
    port = tmp_path / "ttyUSB0"
    port.write_text("", encoding="utf-8")
    output = tmp_path / "placement.json"
    captures = iter([GROVE_NO_SIGNAL.encode("ascii"), GPS_SIGNAL_NO_FIX.encode("ascii")])

    monkeypatch.setattr(
        pi_gnss_ab_compare,
        "read_serial_bytes",
        lambda port, baud, *, duration_seconds: next(captures),
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT),
            "--placement",
            "current",
            "--placement",
            "open_sky",
            "--placement-port",
            str(port),
            "--duration-seconds",
            "0.1",
            "--output-json",
            str(output),
        ],
    )

    assert pi_gnss_ab_compare.main() == 0
    payload = json.loads(output.read_text())
    assert payload["placement_sweep"]["best_placement_label"] == "open_sky"
