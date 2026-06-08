import json
import subprocess
import sys
from pathlib import Path

from ins_dr_navigation import route_heading_deg, route_point_at_progress
from route_matching import load_gpx_route
from tools.pi_gnss_nmea_smoke import parse_raw_nmea


ROOT = Path(__file__).resolve().parents[1]
PIPELINE_SCRIPT = ROOT / "tools" / "ins_dr_field_proof_pipeline.py"
CHECK_SCRIPT = ROOT / "tools" / "ins_dr_proof_manifest_check.py"
MISSION_PATH = ROOT / "tests" / "fixtures" / "mission_graph" / "normal_climb_mission.json"
ROUTE_PATH = ROOT / "tests" / "fixtures" / "routes" / "normal_climb.gpx"


def test_proof_manifest_check_passes_for_complete_reanchored_field_proof(tmp_path: Path) -> None:
    proof_manifest_json = _run_pipeline(tmp_path, include_reanchor=True, require_reanchor=True)

    result = _run_manifest_check(proof_manifest_json, require_reanchor=True)

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["source"] == "ins_dr_proof_manifest_check"
    assert report["proof_manifest_status"] == "passed"
    assert report["completion_ready"] is True
    assert report["hardware_control_scope"] == "diagnostic_field_proof_manifest_verification_only"
    assert all(check["passed"] for check in report["checks"])


def test_proof_manifest_check_fails_when_input_jsonl_is_tampered(tmp_path: Path) -> None:
    proof_manifest_json = _run_pipeline(tmp_path, include_reanchor=True, require_reanchor=True)
    input_jsonl = tmp_path / "evidence.jsonl"
    input_jsonl.write_text(
        input_jsonl.read_text(encoding="utf-8") + json.dumps({"source": "tampered"}) + "\n",
        encoding="utf-8",
    )

    result = _run_manifest_check(proof_manifest_json, require_reanchor=True)

    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["proof_manifest_status"] == "failed"
    failed = [check["name"] for check in report["checks"] if not check["passed"]]
    assert "input_ref_0_sha256_matches" in failed


def test_proof_manifest_check_can_require_reanchor_even_if_pipeline_did_not(tmp_path: Path) -> None:
    proof_manifest_json = _run_pipeline(tmp_path, include_reanchor=False, require_reanchor=False)

    result = _run_manifest_check(proof_manifest_json, require_reanchor=True)

    assert result.returncode == 1
    report = json.loads(result.stdout)
    failed = [check["name"] for check in report["checks"] if not check["passed"]]
    assert "field_report_requires_reanchor" in failed
    assert "field_report_contains_gnss_reanchor" in failed
    assert "runtime_updates_contain_gnss_reanchor" in failed


def _run_pipeline(tmp_path: Path, *, include_reanchor: bool, require_reanchor: bool) -> Path:
    input_jsonl = tmp_path / "evidence.jsonl"
    runtime_updates_jsonl = tmp_path / "runtime-updates.jsonl"
    field_report_json = tmp_path / "field-report.json"
    proof_manifest_json = tmp_path / "proof-manifest.json"
    input_jsonl.write_text(
        "\n".join(json.dumps(payload) for payload in _gnss_dr_payloads(include_reanchor=include_reanchor)) + "\n",
        encoding="utf-8",
    )
    command = [
        sys.executable,
        str(PIPELINE_SCRIPT),
        "--mission-graph",
        str(MISSION_PATH),
        "--input-jsonl",
        str(input_jsonl),
        "--runtime-updates-jsonl",
        str(runtime_updates_jsonl),
        "--field-report-json",
        str(field_report_json),
        "--proof-manifest-json",
        str(proof_manifest_json),
    ]
    if require_reanchor:
        command.append("--require-reanchor")

    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert proof_manifest_json.exists()
    return proof_manifest_json


def _run_manifest_check(proof_manifest_json: Path, *, require_reanchor: bool) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(CHECK_SCRIPT),
        "--proof-manifest-json",
        str(proof_manifest_json),
    ]
    if require_reanchor:
        command.append("--require-reanchor")
    return subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _gnss_dr_payloads(*, include_reanchor: bool) -> list[dict]:
    route = load_gpx_route(ROUTE_PATH)
    anchor = route.points[100]
    heading = route_heading_deg(route, anchor.progress_m)
    payloads = [
        _serial_gga_payload(anchor.lat, anchor.lon, timestamp_s=10.0, time_value="000010.000"),
        {
            "source": "wheel_odometry",
            "provider": "scout_wheel_encoder",
            "timestamp_s": 11.0,
            "hardware_control_scope": "diagnostic_wheel_odometry_delta_only",
            "dry_run": False,
            "previous_dry_run": False,
            "current_dry_run": False,
            "odometry_delta_method": "cumulative_distance_m",
            "previous_raw_evidence_ref": "wheel.jsonl:1",
            "current_raw_evidence_ref": "wheel.jsonl:2",
            "previous_cumulative_distance_m": 20.0,
            "current_cumulative_distance_m": 23.0,
            "odometry": {"distance_delta_m": 3.0, "heading_deg": heading},
        },
    ]
    if include_reanchor:
        reanchor = route_point_at_progress(route, anchor.progress_m + 3.0)
        payloads.append(
            _serial_gga_payload(reanchor.lat, reanchor.lon, timestamp_s=12.0, time_value="000012.000")
        )
    return payloads


def _serial_gga_payload(lat: float, lon: float, *, timestamp_s: float, time_value: str) -> dict:
    payload = parse_raw_nmea(
        _gga_sentence(lat=lat, lon=lon, time_value=time_value),
        device_port="/dev/serial/by-id/usb-scout-gnss",
        baud=115200,
        capture_mode="serial_device",
    )[0]
    payload["timestamp_s"] = timestamp_s
    return payload


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
