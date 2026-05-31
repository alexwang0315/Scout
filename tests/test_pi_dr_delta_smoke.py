import json
import subprocess
import sys
from pathlib import Path

from ins_dr_navigation import route_heading_deg
from route_matching import load_gpx_route
from tools.pi_dr_delta_smoke import build_dr_delta_payload


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "pi_dr_delta_smoke.py"
INS_DR_SCRIPT = ROOT / "tools" / "ins_dr_navigation_smoke.py"
ROUTE_PATH = ROOT / "tests" / "fixtures" / "routes" / "normal_climb.gpx"


def test_build_dr_delta_payload_preserves_diagnostic_boundary() -> None:
    payload = build_dr_delta_payload(
        distance_delta_m=2.5,
        heading_deg=91.0,
        timestamp_s=11.0,
        source="wheel_odometry",
    )

    assert payload["source"] == "wheel_odometry"
    assert payload["hardware_kind"] == "dead_reckoning_delta_evidence"
    assert payload["distance_delta_m"] == 2.5
    assert payload["heading_deg"] == 91.0
    assert payload["phase1_safety_decision_change_allowed"] is False
    assert payload["remote_outbound_allowed"] is False
    assert payload["primary_truth_allowed"] is False
    assert payload["hardware_control_scope"] == "diagnostic_odometry_delta_only"


def test_pi_dr_delta_smoke_writes_jsonl_usable_by_ins_dr_navigation(tmp_path: Path) -> None:
    route = load_gpx_route(ROUTE_PATH)
    anchor = route.points[100]
    heading = route_heading_deg(route, anchor.progress_m)
    gnss_jsonl = tmp_path / "gnss.jsonl"
    dr_jsonl = tmp_path / "dr.jsonl"
    gnss_jsonl.write_text(
        json.dumps(
            {
                "source": "pi_gnss_nmea_smoke",
                "timestamp_s": 10.0,
                "sentence_type": "GPGGA",
                "position": {"lat": anchor.lat, "lon": anchor.lon},
                "fix_quality": {"quality": 1, "valid": True, "satellites": 9, "hdop": 0.8},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--distance-delta-m",
            "4.5",
            "--heading-deg",
            str(heading),
            "--timestamp-s",
            "11.0",
            "--source",
            "wheel_odometry",
            "--output-jsonl",
            str(dr_jsonl),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    persisted = [json.loads(line) for line in dr_jsonl.read_text(encoding="utf-8").splitlines()]
    assert summary["source"] == "pi_dr_delta_smoke"
    assert summary["hardware_control_scope"] == "diagnostic_odometry_delta_only"
    assert persisted[0]["source"] == "wheel_odometry"
    assert persisted[0]["distance_delta_m"] == 4.5
    assert persisted[0]["phase1_safety_decision_change_allowed"] is False

    ins_dr_result = subprocess.run(
        [
            sys.executable,
            str(INS_DR_SCRIPT),
            "--route",
            str(ROUTE_PATH),
            "--input-jsonl",
            str(gnss_jsonl),
            "--input-jsonl",
            str(dr_jsonl),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert ins_dr_result.returncode == 0, ins_dr_result.stderr
    estimates = json.loads(ins_dr_result.stdout)["estimates"]
    assert [estimate["source"] for estimate in estimates] == ["gnss", "dead_reckoning"]
    assert estimates[-1]["primary_truth_source"] == "raw_gnss+dead_reckoning"
    assert estimates[-1]["dr_distance_since_anchor_m"] == 4.5
