import json
import subprocess
import sys
from pathlib import Path

from ins_dr_navigation import route_heading_deg
from route_matching import load_gpx_route
from tools.ins_dr_runtime_smoke import run_ins_dr_runtime_smoke


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "ins_dr_runtime_smoke.py"
MISSION_PATH = ROOT / "tests" / "fixtures" / "mission_graph" / "normal_climb_mission.json"
ROUTE_PATH = ROOT / "tests" / "fixtures" / "routes" / "normal_climb.gpx"


def test_ins_dr_runtime_smoke_replays_gnss_and_dr_payloads_through_runtime() -> None:
    payloads = _gnss_and_dr_payloads()

    result = run_ins_dr_runtime_smoke(
        mission_graph_path=MISSION_PATH,
        payloads=payloads,
    )

    assert result["source"] == "ins_dr_runtime_smoke"
    assert result["observations_accepted"] == 2
    assert result["phase1_live_safety_decision_change_allowed"] is False
    assert result["remote_outbound_allowed"] is False
    assert result["hardware_control_scope"] == "diagnostic_runtime_ingest_replay_only"
    assert result["latest_position_estimate"]["source"] == "dead_reckoning"
    assert result["latest_position_estimate"]["primary_truth_source"] == "raw_gnss+dead_reckoning"
    assert result["latest_position_estimate"]["pdr_delta_m"] == 3.0
    assert result["latest_route_progress_sample"]["estimate_source"] == "dead_reckoning"
    assert result["updates"][1]["observation_lat"] is None
    assert result["updates"][1]["observation_lon"] is None
    assert result["updates"][1]["observation_distance_delta_m"] == 3.0
    assert result["updates"][1]["observation_dr_source"] == "wheel_odometry"
    assert result["updates"][1]["observation_dr_source_kind"] == "wheel_or_encoder_odometry"
    assert result["updates"][1]["observation_dr_navigation_allowed"] is True
    assert result["updates"][1]["observation_dr_evidence_scope"] == "navigation_odometry_source"


def test_ins_dr_runtime_smoke_uses_hiwonder_heading_for_wheel_delta_without_heading() -> None:
    payloads = _gnss_imu_heading_and_wheel_delta_payloads()

    result = run_ins_dr_runtime_smoke(
        mission_graph_path=MISSION_PATH,
        payloads=payloads,
    )

    assert result["observations_accepted"] == 3
    assert result["latest_position_estimate"]["source"] == "dead_reckoning"
    assert result["updates"][1]["observation_source"] == "pi_hiwonder_imu_usb_smoke"
    assert result["updates"][1]["position_estimate"] is None
    assert result["updates"][1]["observation_heading_deg"] == payloads[1]["parsed"]["angle_deg"][2]
    assert result["updates"][2]["observation_source"] == "wheel_odometry"
    assert result["updates"][2]["observation_dr_heading_deg"] == payloads[1]["parsed"]["angle_deg"][2]
    assert result["updates"][2]["observation_dr_source_kind"] == "wheel_or_encoder_odometry"
    assert "heading_unavailable" not in result["updates"][2]["position_estimate"]["degradation_reasons"]


def test_ins_dr_runtime_smoke_cli_writes_update_jsonl(tmp_path: Path) -> None:
    input_jsonl = tmp_path / "evidence.jsonl"
    output_jsonl = tmp_path / "runtime-updates.jsonl"
    input_jsonl.write_text(
        "\n".join(json.dumps(payload) for payload in _gnss_and_dr_payloads()) + "\n",
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
            "--output-jsonl",
            str(output_jsonl),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    updates = [json.loads(line) for line in output_jsonl.read_text(encoding="utf-8").splitlines()]
    assert payload["latest_position_estimate"]["source"] == "dead_reckoning"
    assert payload["latest_route_progress_sample"]["estimate_source"] == "dead_reckoning"
    assert [update["position_estimate"]["source"] for update in updates] == ["gnss", "dead_reckoning"]
    assert updates[1]["hardware_control_scope"] == "diagnostic_runtime_ingest_replay_only"
    assert updates[1]["observation_dr_source_kind"] == "wheel_or_encoder_odometry"


def _gnss_and_dr_payloads() -> list[dict]:
    route = load_gpx_route(ROUTE_PATH)
    anchor = route.points[100]
    heading = route_heading_deg(route, anchor.progress_m)
    return [
        {
            "source": "pi_gnss_nmea_smoke",
            "timestamp_s": 10.0,
            "sentence_type": "GPGGA",
            "checksum_valid": True,
            "position": {"lat": anchor.lat, "lon": anchor.lon},
            "fix_quality": {"quality": 1, "valid": True, "satellites": 9, "hdop": 0.8},
        },
        {
            "source": "wheel_odometry",
            "timestamp_s": 11.0,
            "odometry": {
                "distance_delta_m": 3.0,
                "heading_deg": heading,
            },
        },
    ]


def _gnss_imu_heading_and_wheel_delta_payloads() -> list[dict]:
    route = load_gpx_route(ROUTE_PATH)
    anchor = route.points[100]
    heading = route_heading_deg(route, anchor.progress_m)
    return [
        {
            "source": "pi_gnss_nmea_smoke",
            "timestamp_s": 10.0,
            "sentence_type": "GPGGA",
            "checksum_valid": True,
            "position": {"lat": anchor.lat, "lon": anchor.lon},
            "fix_quality": {"quality": 1, "valid": True, "satellites": 9, "hdop": 0.8},
        },
        {
            "source": "pi_hiwonder_imu_usb_smoke",
            "timestamp_s": 10.5,
            "frame_type": "angle",
            "checksum_valid": True,
            "parsed": {"angle_deg": [0.0, 0.0, heading]},
            "raw_bytes_hex": "55530000000000000000a8",
        },
        {
            "source": "wheel_odometry",
            "timestamp_s": 11.0,
            "odometry": {"distance_delta_m": 3.0},
        },
    ]
