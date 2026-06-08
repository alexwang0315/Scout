import json
import subprocess
import sys
from pathlib import Path

from ins_dr_navigation import route_heading_deg, route_point_at_progress
from route_matching import load_gpx_route
from tools.pi_gnss_nmea_smoke import parse_raw_nmea


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "ins_dr_field_completion_gate.py"
MISSION_PATH = ROOT / "tests" / "fixtures" / "mission_graph" / "normal_climb_mission.json"
ROUTE_PATH = ROOT / "tests" / "fixtures" / "routes" / "normal_climb.gpx"


def test_field_completion_gate_passes_and_writes_verified_single_run_artifacts(tmp_path: Path) -> None:
    paths = _artifact_paths(tmp_path)
    paths["input_jsonl"].write_text(
        "\n".join(json.dumps(payload) for payload in _gnss_dr_payloads(include_reanchor=True)) + "\n",
        encoding="utf-8",
    )
    paths["runtime_updates_jsonl"].write_text(json.dumps({"source": "stale_previous_run"}) + "\n", encoding="utf-8")

    result = _run_gate(paths, require_reanchor=True)

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    updates = [json.loads(line) for line in paths["runtime_updates_jsonl"].read_text(encoding="utf-8").splitlines()]
    verification = json.loads(paths["verification_report_json"].read_text(encoding="utf-8"))
    assert report["source"] == "ins_dr_field_completion_gate"
    assert report["scout_ins_dr_navigation_status"] == "field_ready"
    assert report["completion_ready"] is True
    assert report["proof_manifest_status"] == "passed"
    assert report["hardware_control_scope"] == "diagnostic_field_completion_gate_only"
    assert verification["completion_ready"] is True
    assert [update["position_estimate"]["source"] for update in updates] == ["gnss", "dead_reckoning", "gnss_reanchor"]
    assert all(update.get("source") != "stale_previous_run" for update in updates)


def test_field_completion_gate_fails_when_reanchor_is_required_but_missing(tmp_path: Path) -> None:
    paths = _artifact_paths(tmp_path)
    paths["input_jsonl"].write_text(
        "\n".join(json.dumps(payload) for payload in _gnss_dr_payloads(include_reanchor=False)) + "\n",
        encoding="utf-8",
    )

    result = _run_gate(paths, require_reanchor=True)

    assert result.returncode == 1
    report = json.loads(result.stdout)
    verification = json.loads(paths["verification_report_json"].read_text(encoding="utf-8"))
    failed = [check["name"] for check in verification["checks"] if not check["passed"]]
    assert report["scout_ins_dr_navigation_status"] == "not_field_ready"
    assert report["completion_ready"] is False
    assert report["field_proof_status"] == "failed"
    assert report["proof_manifest_status"] == "failed"
    assert "field_report_contains_gnss_reanchor" in failed
    assert "runtime_updates_contain_gnss_reanchor" in failed


def test_field_completion_gate_rejects_missing_live_gnss_capture_metadata(tmp_path: Path) -> None:
    paths = _artifact_paths(tmp_path)
    payloads = _gnss_dr_payloads(include_reanchor=True)
    payloads[0] = {
        "source": "pi_gnss_nmea_smoke",
        "timestamp_s": 10.0,
        "sentence_type": "GPGGA",
        "checksum_valid": True,
        "position": payloads[0]["position"],
        "fix_quality": payloads[0]["fix_quality"],
    }
    paths["input_jsonl"].write_text(
        "\n".join(json.dumps(payload) for payload in payloads) + "\n",
        encoding="utf-8",
    )

    result = _run_gate(paths, require_reanchor=True)

    assert result.returncode == 1
    report = json.loads(result.stdout)
    field_report = json.loads(paths["field_report_json"].read_text(encoding="utf-8"))
    failed = [check["name"] for check in field_report["checks"] if not check["passed"]]
    assert report["scout_ins_dr_navigation_status"] == "not_field_ready"
    assert "gnss_live_serial_capture_metadata_present" in failed


def _run_gate(paths: dict[str, Path], *, require_reanchor: bool) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(SCRIPT),
        "--mission-graph",
        str(MISSION_PATH),
        "--input-jsonl",
        str(paths["input_jsonl"]),
        "--runtime-updates-jsonl",
        str(paths["runtime_updates_jsonl"]),
        "--field-report-json",
        str(paths["field_report_json"]),
        "--proof-manifest-json",
        str(paths["proof_manifest_json"]),
        "--verification-report-json",
        str(paths["verification_report_json"]),
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


def _artifact_paths(tmp_path: Path) -> dict[str, Path]:
    return {
        "input_jsonl": tmp_path / "evidence.jsonl",
        "runtime_updates_jsonl": tmp_path / "runtime-updates.jsonl",
        "field_report_json": tmp_path / "field-report.json",
        "proof_manifest_json": tmp_path / "proof-manifest.json",
        "verification_report_json": tmp_path / "verification-report.json",
    }


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
    minutes = (absolute - degrees) * 60
    return f"{degrees:02d}{minutes:07.4f}", hemi


def _nmea_lon(value: float) -> tuple[str, str]:
    hemi = "E" if value >= 0 else "W"
    absolute = abs(value)
    degrees = int(absolute)
    minutes = (absolute - degrees) * 60
    return f"{degrees:03d}{minutes:07.4f}", hemi
