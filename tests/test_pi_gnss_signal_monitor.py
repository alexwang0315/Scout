import json
import sys
from pathlib import Path

import pytest

from tools import pi_gnss_signal_monitor
from tools.pi_gnss_signal_monitor import run_signal_monitor


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "pi_gnss_signal_monitor.py"
VALID_GGA = None


def _nmea_sentence(body: str) -> str:
    checksum = 0
    for char in body:
        checksum ^= ord(char)
    return f"${body}*{checksum:02X}"


def _gga_sentence(*, lat: float, lon: float, time_value: str) -> str:
    lat_value, lat_hemi = _nmea_lat(lat)
    lon_value, lon_hemi = _nmea_lon(lon)
    body = f"GPGGA,{time_value},{lat_value},{lat_hemi},{lon_value},{lon_hemi},1,09,0.8,80.0,M,20.1,M,,"
    return _nmea_sentence(body)


def _nmea_lat(value: float) -> tuple[str, str]:
    hemi = "N" if value >= 0 else "S"
    absolute = abs(value)
    degrees = int(absolute)
    minutes = (absolute - degrees) * 60.0
    return f"{degrees:02d}{minutes:07.4f}", hemi


def _nmea_lon(value: float) -> tuple[str, str]:
    hemi = "E" if value >= 0 else "W"
    absolute = abs(value)
    degrees = int(absolute)
    minutes = (absolute - degrees) * 60.0
    return f"{degrees:03d}{minutes:07.4f}", hemi


NO_SIGNAL = "\n".join(
    [
        "$GNGGA,,,,,,0,00,25.5,,,,,,*64",
        "$GPGSV,1,1,00,0*65",
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
GL_SIGNAL_NO_FIX = "\n".join(
    [
        "$GNGGA,,,,,,0,00,25.5,,,,,,*64",
        _nmea_sentence("GLGSV,1,1,01,65,30,120,24"),
        "$GNRMC,,V,,,,,,,,,,M,V*34",
    ]
)
VALID_FIX = "\n".join(
    [
        _gga_sentence(lat=25.06370833, lon=121.654085, time_value="000010.000"),
        "$GPGSV,1,1,01,03,45,180,38,0*54",
    ]
)


def test_signal_monitor_tracks_best_window_and_recommendation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    port = tmp_path / "ttyUSB0"
    port.write_text("", encoding="utf-8")
    windows = iter([NO_SIGNAL.encode("ascii"), GPS_SIGNAL_NO_FIX.encode("ascii")])
    monkeypatch.setattr(
        pi_gnss_signal_monitor,
        "read_serial_bytes",
        lambda port, baud, *, duration_seconds: next(windows),
    )

    report = run_signal_monitor(
        output_dir=tmp_path / "monitor",
        port=str(port),
        baud=115200,
        window_seconds=0.1,
        max_window_count=2,
        pretty=True,
    )

    assert report["source"] == "pi_gnss_signal_monitor"
    assert report["hardware_control_scope"] == "diagnostic_gnss_signal_monitor_only"
    assert report["window_count"] == 2
    assert report["gps_cno_window_count"] == 1
    assert report["any_cno_window_count"] == 1
    assert report["no_rf_window_count"] == 1
    assert report["intermittent_rf_observed"] is True
    assert report["best_window_index"] == 1
    assert report["best_gps_max_cno_dbhz"] == 38
    assert report["best_talker"] == "GP"
    assert report["best_talker_cno_dbhz"] == 38
    assert report["talker_signal_summary"]["GP"]["nonzero_cno_window_count"] == 1
    assert report["windows"][1]["talkers_with_cno"] == [
        {"talker": "GP", "max_cno_dbhz": 38, "nonzero_cno_count": 1}
    ]
    assert report["operator_recommendation"] == "gps_cno_observed_hold_open_sky_until_valid_fix"
    assert Path(report["windows_jsonl"]).exists()
    assert Path(report["report_json"]).exists()


def test_signal_monitor_reports_non_gps_talker_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    port = tmp_path / "ttyUSB0"
    port.write_text("", encoding="utf-8")
    windows = iter([NO_SIGNAL.encode("ascii"), GL_SIGNAL_NO_FIX.encode("ascii")])
    monkeypatch.setattr(
        pi_gnss_signal_monitor,
        "read_serial_bytes",
        lambda port, baud, *, duration_seconds: next(windows),
    )

    report = run_signal_monitor(
        output_dir=tmp_path / "monitor",
        port=str(port),
        baud=115200,
        window_seconds=0.1,
        max_window_count=2,
    )

    captured = capsys.readouterr()

    assert report["gps_cno_window_count"] == 0
    assert report["any_cno_window_count"] == 1
    assert report["best_talker"] == "GL"
    assert report["best_talker_cno_dbhz"] == 24
    assert report["talker_signal_summary"]["GL"]["window_count"] == 1
    assert report["talker_signal_summary"]["GL"]["nonzero_cno_window_count"] == 1
    assert report["talker_signal_summary"]["GL"]["max_cno_dbhz"] == 24
    assert report["windows"][1]["best_talker"] == "GL"
    assert report["windows"][1]["talkers_with_cno"] == [
        {"talker": "GL", "max_cno_dbhz": 24, "nonzero_cno_count": 1}
    ]
    assert "talkers=none" in captured.err
    assert "talkers=GL:24" in captured.err
    assert report["operator_recommendation"] == "rf_is_intermittent_adjust_mounting_and_reduce_shielding"


def test_signal_monitor_recommends_movement_drill_after_valid_fix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    port = tmp_path / "ttyUSB0"
    port.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        pi_gnss_signal_monitor,
        "read_serial_bytes",
        lambda port, baud, *, duration_seconds: VALID_FIX.encode("ascii"),
    )

    report = run_signal_monitor(
        output_dir=tmp_path / "monitor",
        port=str(port),
        window_seconds=0.1,
        max_window_count=1,
    )

    assert report["fix_window_count"] == 1
    assert report["operator_recommendation"] == "valid_fix_observed_hold_position_and_run_movement_drill"


def test_signal_monitor_cli_writes_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    port = tmp_path / "ttyUSB0"
    port.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        pi_gnss_signal_monitor,
        "read_serial_bytes",
        lambda port, baud, *, duration_seconds: GPS_SIGNAL_NO_FIX.encode("ascii"),
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT),
            "--output-dir",
            str(tmp_path / "monitor"),
            "--port",
            str(port),
            "--window-seconds",
            "0.1",
            "--max-window-count",
            "1",
            "--pretty",
        ],
    )

    assert pi_gnss_signal_monitor.main() == 0
    report = json.loads((tmp_path / "monitor" / "gnss-signal-monitor-report.json").read_text())
    assert report["gps_cno_window_count"] == 1
    assert (tmp_path / "monitor" / "gnss-signal-monitor-report.json").exists()
