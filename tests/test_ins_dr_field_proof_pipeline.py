import json
import subprocess
import sys
from pathlib import Path

from ins_dr_navigation import route_heading_deg, route_point_at_progress
from route_matching import load_gpx_route
from tools.ins_dr_field_proof_pipeline import run_field_proof_pipeline
from tools.pi_gnss_nmea_smoke import parse_raw_nmea


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "ins_dr_field_proof_pipeline.py"
MISSION_PATH = ROOT / "tests" / "fixtures" / "mission_graph" / "normal_climb_mission.json"
ROUTE_PATH = ROOT / "tests" / "fixtures" / "routes" / "normal_climb.gpx"


def test_field_proof_pipeline_passes_for_anchor_dr_and_reanchor() -> None:
    result = run_field_proof_pipeline(
        mission_graph_path=MISSION_PATH,
        payloads=_gnss_dr_payloads(include_reanchor=True),
        require_reanchor=True,
    )

    assert result["source"] == "ins_dr_field_proof_pipeline"
    assert result["field_proof_status"] == "passed"
    assert result["usable_navigation_evidence"] is True
    assert result["runtime_summary"]["latest_position_estimate"]["source"] == "gnss_reanchor"
    assert result["field_report"]["gnss_reanchor_update_count"] == 1
    assert result["hardware_control_scope"] == "diagnostic_field_proof_pipeline_only"


def test_field_proof_pipeline_cli_writes_runtime_updates_and_report(tmp_path: Path) -> None:
    input_jsonl = tmp_path / "evidence.jsonl"
    runtime_updates_jsonl = tmp_path / "runtime-updates.jsonl"
    field_report_json = tmp_path / "field-report.json"
    proof_manifest_json = tmp_path / "proof-manifest.json"
    runtime_updates_jsonl.write_text(json.dumps({"source": "stale_previous_run"}) + "\n", encoding="utf-8")
    input_jsonl.write_text(
        "\n".join(json.dumps(payload) for payload in _gnss_dr_payloads(include_reanchor=True)) + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
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
            "--require-reanchor",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    pipeline = json.loads(result.stdout)
    updates = [json.loads(line) for line in runtime_updates_jsonl.read_text(encoding="utf-8").splitlines()]
    field_report = json.loads(field_report_json.read_text(encoding="utf-8"))
    proof_manifest = json.loads(proof_manifest_json.read_text(encoding="utf-8"))
    assert pipeline["field_proof_status"] == "passed"
    assert field_report["field_proof_status"] == "passed"
    assert proof_manifest["artifact_kind"] == "ins_dr_field_proof_manifest"
    assert proof_manifest["field_proof_status"] == "passed"
    assert proof_manifest["mission_graph_ref"]["sha256"]
    assert proof_manifest["input_refs"][0]["sha256"]
    assert proof_manifest["output_refs"]["runtime_updates_jsonl"]["sha256"]
    assert proof_manifest["output_refs"]["field_report_json"]["sha256"]
    assert proof_manifest["boundary"]["hardware_control_scope"] == "diagnostic_field_proof_manifest_only"
    assert pipeline["proof_manifest"]["usable_navigation_evidence"] is True
    assert [update["position_estimate"]["source"] for update in updates] == ["gnss", "dead_reckoning", "gnss_reanchor"]
    assert all(update.get("source") != "stale_previous_run" for update in updates)


def test_field_proof_pipeline_cli_returns_nonzero_when_reanchor_required_but_missing(tmp_path: Path) -> None:
    input_jsonl = tmp_path / "evidence.jsonl"
    input_jsonl.write_text(
        "\n".join(json.dumps(payload) for payload in _gnss_dr_payloads(include_reanchor=False)) + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--mission-graph",
            str(MISSION_PATH),
            "--input-jsonl",
            str(input_jsonl),
            "--require-reanchor",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    pipeline = json.loads(result.stdout)
    assert pipeline["field_proof_status"] == "failed"
    assert pipeline["usable_navigation_evidence"] is False


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
