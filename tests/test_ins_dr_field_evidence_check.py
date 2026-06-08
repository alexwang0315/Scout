import json
import subprocess
import sys
from pathlib import Path

from ins_dr_navigation import route_heading_deg, route_point_at_progress
from route_matching import load_gpx_route
from tools.ins_dr_field_evidence_check import build_field_evidence_report
from tools.ins_dr_runtime_smoke import run_ins_dr_runtime_smoke
from tools.pi_gnss_nmea_smoke import parse_raw_nmea


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "ins_dr_field_evidence_check.py"
MISSION_PATH = ROOT / "tests" / "fixtures" / "mission_graph" / "normal_climb_mission.json"
ROUTE_PATH = ROOT / "tests" / "fixtures" / "routes" / "normal_climb.gpx"


def test_field_evidence_report_passes_for_anchor_and_dr_runtime_updates() -> None:
    runtime_result = run_ins_dr_runtime_smoke(
        mission_graph_path=MISSION_PATH,
        payloads=_gnss_dr_payloads(include_reanchor=False),
    )

    report = build_field_evidence_report(runtime_result["updates"])

    assert report["field_proof_status"] == "passed"
    assert report["usable_navigation_evidence"] is True
    assert report["gnss_anchor_update_count"] == 1
    assert report["dead_reckoning_update_count"] == 1
    assert report["dr_progress_delta_m"] >= 3.0
    assert report["replayed_gnss_failure_count"] == 0
    assert report["gnss_checksum_failure_count"] == 0
    assert report["route_corridor_failure_count"] == 0
    assert report["dr_distance_source_failure_count"] == 0
    assert report["dr_distance_source_summary"]["kind_counts"] == {"wheel_or_encoder_odometry": 1}
    assert report["dr_distance_source_summary"]["navigation_allowed_count"] == 1
    assert report["dr_distance_source_summary"]["reviews"][0]["provenance"]["odometry_delta_method"] == "cumulative_distance_m"
    assert report["dr_heading_failure_count"] == 0
    assert report["dr_heading_summary"]["navigation_allowed_count"] == 1
    assert all(check["passed"] for check in report["checks"])
    assert report["hardware_control_scope"] == "diagnostic_field_evidence_review_only"


def test_field_evidence_report_can_require_reanchor_after_dr() -> None:
    runtime_result = run_ins_dr_runtime_smoke(
        mission_graph_path=MISSION_PATH,
        payloads=_gnss_dr_payloads(include_reanchor=True),
    )

    report = build_field_evidence_report(runtime_result["updates"], require_reanchor=True)

    assert report["field_proof_status"] == "passed"
    assert report["gnss_reanchor_update_count"] == 1
    assert any(check["name"] == "gnss_reanchor_after_dr" and check["passed"] for check in report["checks"])


def test_field_evidence_report_fails_when_dr_raw_position_is_faked() -> None:
    runtime_result = run_ins_dr_runtime_smoke(
        mission_graph_path=MISSION_PATH,
        payloads=_gnss_dr_payloads(include_reanchor=False),
    )
    bad_updates = list(runtime_result["updates"])
    bad_updates[1] = {**bad_updates[1], "observation_lat": 24.0}

    report = build_field_evidence_report(bad_updates)

    assert report["field_proof_status"] == "failed"
    assert report["usable_navigation_evidence"] is False
    failed = [check["name"] for check in report["checks"] if not check["passed"]]
    assert "dr_only_observation_does_not_fake_gps" in failed


def test_field_evidence_report_fails_when_navigation_leaves_route_corridor() -> None:
    runtime_result = run_ins_dr_runtime_smoke(
        mission_graph_path=MISSION_PATH,
        payloads=_gnss_dr_payloads(include_reanchor=True),
    )
    bad_updates = list(runtime_result["updates"])
    bad_sample = dict(bad_updates[0]["route_progress_sample"])
    bad_sample.update(
        {
            "map_corridor_inside": False,
            "map_corridor_distance_m": 25.0,
            "map_corridor_allowed_distance_m": 10.0,
        }
    )
    bad_updates[0] = {**bad_updates[0], "route_progress_sample": bad_sample}

    report = build_field_evidence_report(bad_updates, require_reanchor=True)

    assert report["field_proof_status"] == "failed"
    assert report["route_corridor_failure_count"] == 1
    failed = [check["name"] for check in report["checks"] if not check["passed"]]
    assert "route_corridor_inside_for_navigation" in failed


def test_field_evidence_report_fails_when_gnss_came_from_replayed_raw_nmea() -> None:
    payloads = _gnss_dr_payloads(include_reanchor=True)
    payloads[0] = {
        **payloads[0],
        "capture_mode": "raw_nmea_argument",
        "primary_truth_allowed": False,
        "primary_truth_scope": "diagnostic_replayed_nmea_only",
    }
    payloads[2] = {
        **payloads[2],
        "capture_mode": "raw_nmea_argument",
        "primary_truth_allowed": False,
        "primary_truth_scope": "diagnostic_replayed_nmea_only",
    }
    runtime_result = run_ins_dr_runtime_smoke(
        mission_graph_path=MISSION_PATH,
        payloads=payloads,
    )

    report = build_field_evidence_report(runtime_result["updates"], require_reanchor=True)

    assert report["field_proof_status"] == "failed"
    assert report["replayed_gnss_failure_count"] == 2
    failed = [check["name"] for check in report["checks"] if not check["passed"]]
    assert "gnss_field_capture_not_replayed_fixture" in failed


def test_field_evidence_report_fails_when_raw_gnss_checksum_is_invalid() -> None:
    payloads = _gnss_dr_payloads(include_reanchor=True)
    payloads[0] = {**payloads[0], "checksum_valid": False}
    runtime_result = run_ins_dr_runtime_smoke(
        mission_graph_path=MISSION_PATH,
        payloads=payloads,
    )

    report = build_field_evidence_report(runtime_result["updates"], require_reanchor=True)

    assert report["field_proof_status"] == "failed"
    assert report["gnss_checksum_failure_count"] == 1
    failed = [check["name"] for check in report["checks"] if not check["passed"]]
    assert "raw_gnss_checksum_valid_for_navigation" in failed


def test_field_evidence_report_fails_when_gnss_lacks_live_serial_capture_metadata() -> None:
    payloads = _gnss_dr_payloads(include_reanchor=True)
    payloads[0] = {
        "source": "pi_gnss_nmea_smoke",
        "timestamp_s": 10.0,
        "sentence_type": "GPGGA",
        "checksum_valid": True,
        "position": payloads[0]["position"],
        "fix_quality": payloads[0]["fix_quality"],
    }
    runtime_result = run_ins_dr_runtime_smoke(
        mission_graph_path=MISSION_PATH,
        payloads=payloads,
    )

    report = build_field_evidence_report(runtime_result["updates"], require_reanchor=True)

    assert report["field_proof_status"] == "failed"
    assert report["live_serial_gnss_failure_count"] == 1
    failed = [check["name"] for check in report["checks"] if not check["passed"]]
    assert "gnss_live_serial_capture_metadata_present" in failed


def test_field_evidence_report_fails_when_dr_distance_is_operator_entered() -> None:
    payloads = _gnss_dr_payloads(include_reanchor=True)
    payloads[1] = {
        **payloads[1],
        "source": "manual_odometry_delta",
        "provider": "operator_entered_distance_delta",
    }
    runtime_result = run_ins_dr_runtime_smoke(
        mission_graph_path=MISSION_PATH,
        payloads=payloads,
    )

    report = build_field_evidence_report(runtime_result["updates"], require_reanchor=True)

    assert report["field_proof_status"] == "failed"
    assert report["usable_navigation_evidence"] is False
    assert report["dr_distance_source_failure_count"] == 1
    assert report["dr_distance_source_summary"]["kind_counts"] == {"manual_operator_distance_delta": 1}
    failed = [check["name"] for check in report["checks"] if not check["passed"]]
    assert "dr_distance_source_allowed_for_navigation" in failed


def test_field_evidence_report_fails_when_wheel_distance_lacks_provider_provenance() -> None:
    payloads = _gnss_dr_payloads(include_reanchor=True)
    payloads[1] = {
        "source": "wheel_odometry",
        "provider": "scout_wheel_encoder",
        "timestamp_s": payloads[1]["timestamp_s"],
        "odometry": payloads[1]["odometry"],
    }
    runtime_result = run_ins_dr_runtime_smoke(
        mission_graph_path=MISSION_PATH,
        payloads=payloads,
    )

    report = build_field_evidence_report(runtime_result["updates"], require_reanchor=True)

    assert report["field_proof_status"] == "failed"
    assert report["dr_distance_source_failure_count"] == 1
    review = report["dr_distance_source_summary"]["reviews"][0]
    assert review["kind"] == "wheel_or_encoder_odometry"
    assert review["provenance"]["evidence_scope"] == "missing_wheel_encoder_provider_provenance"
    failed = [check["name"] for check in report["checks"] if not check["passed"]]
    assert "dr_distance_source_allowed_for_navigation" in failed


def test_field_evidence_report_passes_when_hiwonder_heading_feeds_wheel_delta() -> None:
    runtime_result = run_ins_dr_runtime_smoke(
        mission_graph_path=MISSION_PATH,
        payloads=_gnss_imu_heading_wheel_payloads(include_reanchor=True),
    )

    report = build_field_evidence_report(runtime_result["updates"], require_reanchor=True)

    assert report["field_proof_status"] == "passed"
    assert report["dr_heading_failure_count"] == 0
    assert report["dr_heading_summary"]["reviews"][0]["heading_deg"] is not None
    assert any(check["name"] == "dr_heading_available_for_navigation" and check["passed"] for check in report["checks"])


def test_field_evidence_report_fails_when_hiwonder_heading_checksum_is_missing() -> None:
    payloads = _gnss_imu_heading_wheel_payloads(include_reanchor=True)
    payloads[1].pop("checksum_valid")
    payloads[1]["parsed"].pop("checksum_valid", None)
    runtime_result = run_ins_dr_runtime_smoke(
        mission_graph_path=MISSION_PATH,
        payloads=payloads,
    )

    report = build_field_evidence_report(runtime_result["updates"], require_reanchor=True)

    assert report["field_proof_status"] == "failed"
    assert report["dr_heading_failure_count"] == 1
    failed = [check["name"] for check in report["checks"] if not check["passed"]]
    assert "dr_heading_available_for_navigation" in failed


def test_field_evidence_report_fails_when_wheel_delta_is_dry_run() -> None:
    payloads = _gnss_dr_payloads(include_reanchor=True)
    payloads[1] = {**payloads[1], "dry_run": True, "previous_dry_run": True}
    runtime_result = run_ins_dr_runtime_smoke(
        mission_graph_path=MISSION_PATH,
        payloads=payloads,
    )

    report = build_field_evidence_report(runtime_result["updates"], require_reanchor=True)

    assert report["field_proof_status"] == "failed"
    assert report["dr_distance_source_failure_count"] == 1
    review = report["dr_distance_source_summary"]["reviews"][0]
    assert review["provenance"]["dry_run"] is True
    failed = [check["name"] for check in report["checks"] if not check["passed"]]
    assert "dr_distance_source_allowed_for_navigation" in failed


def test_field_evidence_report_fails_when_dr_heading_is_unavailable() -> None:
    payloads = _gnss_dr_payloads(include_reanchor=True)
    payloads[1] = {
        **payloads[1],
        "odometry": {"distance_delta_m": 3.0},
    }
    runtime_result = run_ins_dr_runtime_smoke(
        mission_graph_path=MISSION_PATH,
        payloads=payloads,
    )

    report = build_field_evidence_report(runtime_result["updates"], require_reanchor=True)

    assert report["field_proof_status"] == "failed"
    assert report["dr_heading_failure_count"] == 1
    assert report["dr_heading_summary"]["missing_heading_count"] == 1
    failed = [check["name"] for check in report["checks"] if not check["passed"]]
    assert "dr_heading_available_for_navigation" in failed


def test_field_evidence_check_cli_returns_nonzero_when_required_reanchor_missing(tmp_path: Path) -> None:
    runtime_result = run_ins_dr_runtime_smoke(
        mission_graph_path=MISSION_PATH,
        payloads=_gnss_dr_payloads(include_reanchor=False),
    )
    updates_jsonl = tmp_path / "runtime-updates.jsonl"
    updates_jsonl.write_text(
        "\n".join(json.dumps(update) for update in runtime_result["updates"]) + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--runtime-updates-jsonl",
            str(updates_jsonl),
            "--require-reanchor",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["field_proof_status"] == "failed"
    assert any(check["name"] == "gnss_reanchor_after_dr" and not check["passed"] for check in report["checks"])


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


def _gnss_imu_heading_wheel_payloads(*, include_reanchor: bool) -> list[dict]:
    payloads = _gnss_dr_payloads(include_reanchor=include_reanchor)
    route = load_gpx_route(ROUTE_PATH)
    anchor = route.points[100]
    heading = route_heading_deg(route, anchor.progress_m)
    payloads[1] = {
        "source": "pi_hiwonder_imu_usb_smoke",
        "timestamp_s": 10.5,
        "frame_type": "angle",
        "checksum_valid": True,
        "parsed": {"angle_deg": [0.0, 0.0, heading], "checksum_valid": True},
        "raw_bytes_hex": "55530000000000000000a8",
    }
    payloads.insert(
        2,
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
            "odometry": {"distance_delta_m": 3.0},
        },
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
