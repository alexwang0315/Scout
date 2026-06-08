import json
import subprocess
import sys
from pathlib import Path

from ins_dr_navigation import route_heading_deg, route_point_at_progress
from route_matching import load_gpx_route


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "ins_dr_manual_field_run.py"
MISSION_PATH = ROOT / "tests" / "fixtures" / "mission_graph" / "normal_climb_mission.json"
ROUTE_PATH = ROOT / "tests" / "fixtures" / "routes" / "normal_climb.gpx"


def test_manual_field_run_raw_nmea_arguments_are_rehearsal_not_completion(tmp_path: Path) -> None:
    route = load_gpx_route(ROUTE_PATH)
    anchor = route.points[100]
    reanchor = route_point_at_progress(route, anchor.progress_m + 3.0)
    heading = route_heading_deg(route, anchor.progress_m)

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--mission-graph",
            str(MISSION_PATH),
            "--output-dir",
            str(tmp_path),
            "--raw-anchor-nmea",
            _gga_sentence(lat=anchor.lat, lon=anchor.lon, time_value="000010.000"),
            "--distance-delta-m",
            "3.0",
            "--heading-deg",
            str(heading),
            "--timestamp-s",
            "11.0",
            "--movement-window-seconds",
            "0",
            "--raw-reanchor-nmea",
            _gga_sentence(lat=reanchor.lat, lon=reanchor.lon, time_value="000012.000"),
            "--pretty",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["source"] == "ins_dr_manual_field_run"
    assert report["scout_ins_dr_navigation_status"] == "not_field_ready"
    assert report["completion_ready"] is False
    assert report["anchor_payload_count"] == 1
    assert report["dr_delta_count"] == 1
    assert report["reanchor_payload_count"] == 1
    assert report["movement_window_seconds"] == 0.0
    assert report["hardware_control_scope"] == "diagnostic_manual_field_run_only"
    assert Path(report["anchor_jsonl"]).exists()
    assert Path(report["dr_jsonl"]).exists()
    assert Path(report["reanchor_jsonl"]).exists()
    assert Path(report["proof_manifest_json"]).exists()
    assert Path(report["verification_report_json"]).exists()

    field_report = json.loads(Path(report["field_report_json"]).read_text(encoding="utf-8"))
    assert field_report["field_proof_status"] == "failed"
    assert field_report["replayed_gnss_failure_count"] == 2
    assert field_report["route_corridor_failure_count"] == 0
    failed = [check["name"] for check in field_report["checks"] if not check["passed"]]
    assert "gnss_field_capture_not_replayed_fixture" in failed


def test_manual_field_run_fails_when_reanchor_capture_is_missing(tmp_path: Path) -> None:
    route = load_gpx_route(ROUTE_PATH)
    anchor = route.points[100]
    heading = route_heading_deg(route, anchor.progress_m)

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--mission-graph",
            str(MISSION_PATH),
            "--output-dir",
            str(tmp_path),
            "--raw-anchor-nmea",
            _gga_sentence(lat=anchor.lat, lon=anchor.lon, time_value="000010.000"),
            "--distance-delta-m",
            "3.0",
            "--heading-deg",
            str(heading),
            "--timestamp-s",
            "11.0",
            "--raw-reanchor-nmea",
            "",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["scout_ins_dr_navigation_status"] == "not_field_ready"
    assert report["completion_ready"] is False
    assert report["reanchor_payload_count"] == 0
    verification = json.loads(Path(report["verification_report_json"]).read_text(encoding="utf-8"))
    failed = [check["name"] for check in verification["checks"] if not check["passed"]]
    assert "field_report_contains_gnss_reanchor" in failed
    assert "runtime_updates_contain_gnss_reanchor" in failed


def test_manual_field_run_rejects_negative_movement_window(tmp_path: Path) -> None:
    route = load_gpx_route(ROUTE_PATH)
    anchor = route.points[100]
    heading = route_heading_deg(route, anchor.progress_m)

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--mission-graph",
            str(MISSION_PATH),
            "--output-dir",
            str(tmp_path),
            "--raw-anchor-nmea",
            _gga_sentence(lat=anchor.lat, lon=anchor.lon, time_value="000010.000"),
            "--distance-delta-m",
            "3.0",
            "--heading-deg",
            str(heading),
            "--raw-reanchor-nmea",
            "",
            "--movement-window-seconds",
            "-1",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "movement_window_seconds must be non-negative" in result.stderr


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
    minutes = (absolute - degrees) * 60
    return f"{degrees:02d}{minutes:07.4f}", hemi


def _nmea_lon(value: float) -> tuple[str, str]:
    hemi = "E" if value >= 0 else "W"
    absolute = abs(value)
    degrees = int(absolute)
    minutes = (absolute - degrees) * 60
    return f"{degrees:03d}{minutes:07.4f}", hemi
