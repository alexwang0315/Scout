import json
from pathlib import Path

import pytest

from tools import ins_dr_gnss_fix_watch
from tools.ins_dr_gnss_fix_watch import run_gnss_fix_watch


def test_gnss_fix_watch_stops_when_valid_fix_is_observed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port = tmp_path / "ttyUSB0"
    port.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        ins_dr_gnss_fix_watch,
        "read_serial_nmea",
        lambda *, port, baud, duration_seconds: [
            _gga_sentence(lat=25.06370833, lon=121.654085, time_value="000010.000"),
            "$GPGSV,1,1,01,03,,,38,0*7D",
        ],
    )

    report = run_gnss_fix_watch(
        output_dir=tmp_path / "watch",
        gnss_port=port,
        gnss_baud=115200,
        window_seconds=0.1,
        max_window_count=3,
        poll_interval_seconds=0.0,
        pretty=True,
    )

    assert report["source"] == "ins_dr_gnss_fix_watch"
    assert report["hardware_control_scope"] == "diagnostic_gnss_fix_watch_only"
    assert report["watch_status"] == "valid_fix_observed"
    assert report["watch_goal_satisfied"] is True
    assert report["ready_for_live_field_proof"] is True
    assert report["selected_gnss_port"] == str(port)
    assert report["valid_fix_count"] == 1
    assert report["gps_max_cno_dbhz"] == 38
    assert report["best_talker"] == "GP"
    assert report["best_talker_cno_dbhz"] == 38
    assert report["fix"]["valid_fix_count"] == 1
    assert report["signal"]["gps_max_cno_dbhz"] == 38
    assert report["signal"]["talker_signal_summary"]["GP"]["max_cno_dbhz"] == 38
    assert report["window_event_count"] == 1
    assert report["window_stability"]["valid_fix_window_count"] == 1
    assert report["window_stability"]["gps_cno_window_count"] == 1
    assert report["window_stability"]["best_talker"] == "GP"
    assert report["window_stability"]["talker_signal_summary"]["GP"]["nonzero_cno_window_count"] == 1
    assert report["intermittent_rf_observed"] is False
    assert Path(report["events_jsonl"]).exists()
    payloads = [json.loads(line) for line in Path(report["payloads_jsonl"]).read_text(encoding="utf-8").splitlines()]
    assert payloads[0]["watch_window_index"] == 0
    assert payloads[0]["watch_target_label"].startswith("watch_0_explicit_port")


def test_gnss_fix_watch_times_out_with_nmea_but_no_rf_signal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port = tmp_path / "ttyUSB0"
    port.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        ins_dr_gnss_fix_watch,
        "read_serial_nmea",
        lambda *, port, baud, duration_seconds: [
            "$GNGGA,,,,,,0,00,25.5,,,,,,*64",
            "$GPGSV,1,1,00,0*65",
        ],
    )

    report = run_gnss_fix_watch(
        output_dir=tmp_path / "watch",
        gnss_port=port,
        gnss_baud=115200,
        window_seconds=0.1,
        max_window_count=2,
        poll_interval_seconds=0.0,
    )

    assert report["watch_status"] == "timed_out_no_rf_signal"
    assert report["watch_goal_satisfied"] is False
    assert report["ready_for_live_field_proof"] is False
    assert report["selected_gnss_port"] is None
    assert report["valid_fix_count"] == 0
    assert report["max_cno_dbhz"] is None
    assert report["fix"]["valid_fix_count"] == 0
    assert report["signal"]["max_cno_dbhz"] is None
    assert report["signal"]["talker_signal_summary"]["GP"]["rf_signal_observed"] is False
    assert report["window_stability"]["talker_signal_summary"]["GP"]["nonzero_cno_window_count"] == 0
    assert report["window_stability"]["best_talker"] is None
    assert report["classification"]["state"] == "no_rf_signal_observed"
    assert report["window_event_count"] == 2
    assert report["window_stability"]["no_rf_window_count"] == 2
    assert report["window_stability"]["any_cno_window_count"] == 0
    assert report["intermittent_rf_observed"] is False


def test_gnss_fix_watch_auto_candidates_can_stop_on_gps_cno_without_fix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = tmp_path / "ttyUSB0"
    second = tmp_path / "ttyUSB1"
    first.write_text("", encoding="utf-8")
    second.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        ins_dr_gnss_fix_watch,
        "resolve_requested_gnss_port",
        lambda gnss_port, include_uart_serial_candidates=False: (
            Path("auto"),
            {
                "requested_gnss_port": "auto",
                "resolved_gnss_port": None,
                "auto_detection_status": "ambiguous_serial_candidates",
                "candidate_count": 2,
                "candidates": [
                    {"path": str(first), "kind": "linux_usb_serial", "priority": 10},
                    {"path": str(second), "kind": "linux_usb_serial", "priority": 10},
                ],
            },
        ),
    )

    def serial_lines(*, port, baud, duration_seconds):
        if port == str(second):
            return [
                "$GNGGA,,,,,,0,00,25.5,,,,,,*64",
                "$GPGSV,2,1,05,01,40,083,42,02,17,308,30,03,12,120,,04,08,044,18*7D",
            ]
        return [
            "$GNGGA,,,,,,0,00,25.5,,,,,,*64",
            "$GPGSV,1,1,00,0*65",
        ]

    monkeypatch.setattr(ins_dr_gnss_fix_watch, "read_serial_nmea", serial_lines)

    report = run_gnss_fix_watch(
        output_dir=tmp_path / "watch",
        gnss_port=Path("auto"),
        gnss_baud=115200,
        window_seconds=0.1,
        max_window_count=3,
        poll_interval_seconds=0.0,
        stop_on="gps_cno",
        min_gps_cno_dbhz=25.0,
    )

    assert report["watch_status"] == "gps_cno_observed_without_fix"
    assert report["watch_goal_satisfied"] is True
    assert report["ready_for_live_field_proof"] is False
    assert report["selected_gnss_port"] is None
    assert report["best_observed_gnss_port"] == str(second)
    assert report["gps_max_cno_dbhz"] == 42
    assert report["signal"]["gps_max_cno_dbhz"] == 42
    assert report["best_talker"] == "GP"
    assert report["talker_signal_summary"]["GP"]["max_cno_dbhz"] == 42
    assert report["target_count"] == 2
    assert report["window_event_count"] == 2
    assert report["window_stability"]["gps_cno_window_count"] == 1
    assert report["window_stability"]["no_rf_window_count"] == 1
    assert report["window_stability"]["best_talker"] == "GP"
    assert report["window_stability"]["talker_signal_summary"]["GP"]["nonzero_cno_window_count"] == 1
    assert report["intermittent_rf_observed"] is True
    windows = report["window_stability"]["windows"]
    assert windows[0]["state"] == "no_rf_signal_observed"
    assert windows[1]["gps_max_cno_dbhz"] == 42
    assert windows[1]["best_talker"] == "GP"


def test_gnss_fix_watch_rejects_existing_artifacts_without_overwrite(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "watch"
    output_dir.mkdir()
    (output_dir / "gnss-fix-watch-report.json").write_text("{}\n", encoding="utf-8")
    port = tmp_path / "ttyUSB0"
    port.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="GNSS watch artifacts"):
        run_gnss_fix_watch(
            output_dir=output_dir,
            gnss_port=port,
            window_seconds=0.1,
            max_window_count=1,
            poll_interval_seconds=0.0,
        )


def _gga_sentence(*, lat: float, lon: float, time_value: str) -> str:
    lat_value, lat_hemi = _nmea_lat(lat)
    lon_value, lon_hemi = _nmea_lon(lon)
    body = f"GPGGA,{time_value},{lat_value},{lat_hemi},{lon_value},{lon_hemi},1,09,0.8,80.0,M,20.1,M,,"
    checksum = 0
    for char in body:
        checksum ^= ord(char)
    return f"${body}*{checksum:02X}"


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
