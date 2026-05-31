import json
import subprocess
import sys
from pathlib import Path

from ins_dr_navigation import route_heading_deg
from route_matching import load_gpx_route


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "ins_dr_navigation_smoke.py"
ROUTE_PATH = ROOT / "tests" / "fixtures" / "routes" / "normal_climb.gpx"


def test_ins_dr_navigation_smoke_builds_estimates_from_jsonl(tmp_path: Path) -> None:
    route = load_gpx_route(ROUTE_PATH)
    anchor = route.points[100]
    heading = route_heading_deg(route, anchor.progress_m)
    input_jsonl = tmp_path / "evidence.jsonl"
    output_jsonl = tmp_path / "estimates.jsonl"
    payloads = [
        {
            "source": "pi_gnss_nmea_smoke",
            "timestamp_s": 0.0,
            "sentence_type": "GPGGA",
            "position": {"lat": anchor.lat, "lon": anchor.lon},
            "fix_quality": {"quality": 1, "valid": True, "satellites": 9, "hdop": 0.8},
            "raw_sentence": "$GPGGA,anchor*00",
        },
        {
            "source": "pi_hiwonder_imu_usb_smoke",
            "timestamp_s": 1.0,
            "frame_type": "angle",
            "parsed": {"angle_deg": [0.0, 0.0, heading]},
            "raw_bytes_hex": "55530000000000000000a8",
        },
        {
            "source": "sensorlog",
            "timestamp_s": 2.0,
            "sensorlog": {"pedometerDistance": 100.0},
        },
        {
            "source": "sensorlog",
            "timestamp_s": 3.0,
            "sensorlog": {"pedometerDistance": 118.0},
        },
    ]
    input_jsonl.write_text("\n".join(json.dumps(payload) for payload in payloads), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--route",
            str(ROUTE_PATH),
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
    stdout_payload = json.loads(result.stdout)
    persisted = [json.loads(line) for line in output_jsonl.read_text(encoding="utf-8").splitlines()]
    assert stdout_payload["source"] == "ins_dr_navigation_smoke"
    assert stdout_payload["estimate_count"] == 2
    assert stdout_payload["phase1_safety_decision_change_allowed"] is False
    assert [estimate["source"] for estimate in persisted] == ["gnss", "dead_reckoning"]
    assert persisted[0]["primary_truth_source"] == "raw_gnss"
    assert persisted[1]["primary_truth_source"] == "raw_gnss+dead_reckoning"
    assert persisted[1]["dr_distance_since_anchor_m"] == 18.0
    assert persisted[1]["vendor_fusion_used_as_primary_truth"] is False
    assert persisted[1]["hardware_control_scope"] == "diagnostic_navigation_estimate_only"


def test_ins_dr_navigation_smoke_marks_vendor_disagreement(tmp_path: Path) -> None:
    route = load_gpx_route(ROUTE_PATH)
    anchor = route.points[100]
    heading = route_heading_deg(route, anchor.progress_m)
    far = route.points[-1]
    input_jsonl = tmp_path / "evidence.jsonl"
    payloads = [
        {
            "source": "pi_gnss_nmea_smoke",
            "timestamp_s": 0.0,
            "sentence_type": "GPGGA",
            "position": {"lat": anchor.lat, "lon": anchor.lon},
            "fix_quality": {"quality": 1, "valid": True, "hdop": 0.8},
        },
        {
            "source": "wheel_odometry",
            "timestamp_s": 1.0,
            "distance_delta_m": 4.0,
            "heading_deg": heading,
            "vendor_fusion": True,
            "position": {"lat": far.lat, "lon": far.lon},
        },
    ]
    input_jsonl.write_text("\n".join(json.dumps(payload) for payload in payloads), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--route",
            str(ROUTE_PATH),
            "--input-jsonl",
            str(input_jsonl),
            "--vendor-disagreement-threshold-m",
            "10",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    estimates = json.loads(result.stdout)["estimates"]
    assert estimates[-1]["source"] == "dead_reckoning"
    assert estimates[-1]["degraded"] is True
    assert "vendor_fusion_disagreement" in estimates[-1]["degradation_reasons"]
    assert estimates[-1]["vendor_fusion_used_as_primary_truth"] is False
