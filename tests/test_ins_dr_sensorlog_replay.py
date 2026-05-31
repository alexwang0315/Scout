import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tools.ins_dr_sensorlog_replay import run_sensorlog_replay


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "ins_dr_sensorlog_replay.py"


def test_sensorlog_replay_builds_anchor_dr_and_reanchor_summary(tmp_path: Path) -> None:
    input_path = tmp_path / "apple-watch-sensorlog.json"
    input_path.write_text(json.dumps(_sensorlog_records()), encoding="utf-8")

    report = run_sensorlog_replay(
        input_path=input_path,
        gnss_anchor_interval_s=60.0,
    )

    assert report["source_tool"] == "ins_dr_sensorlog_replay"
    assert report["offline_replay_validation_status"] == "passed_with_heading_limitation"
    assert report["live_navigation_completion_proof"] is False
    assert report["anchor_source_scope"] == "apple_watch_sensorlog_location_replay_not_raw_nmea"
    assert report["estimate_source_counts"]["gnss"] == 1
    assert report["estimate_source_counts"]["gnss_reanchor"] == 1
    assert report["dead_reckoning_estimate_count"] == 4
    assert report["dr_delta_count"] == 4
    assert report["pedometer_summary"]["distance_delta_m"] == 60.0
    assert report["heading_summary"]["absolute_heading_sample_count"] == 0
    assert report["heading_summary"]["motion_yaw_sample_count"] == 6
    assert "estimates" not in report
    assert report["estimate_samples"]["last"]["source"] == "dead_reckoning"


def test_sensorlog_replay_cli_writes_summary_and_estimates_jsonl(tmp_path: Path) -> None:
    input_path = tmp_path / "apple-watch-sensorlog.json"
    report_path = tmp_path / "report.json"
    estimates_path = tmp_path / "estimates.jsonl"
    input_path.write_text(json.dumps(_sensorlog_records()), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--input",
            str(input_path),
            "--gnss-anchor-interval-s",
            "60",
            "--output-report",
            str(report_path),
            "--output-jsonl",
            str(estimates_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    stdout_payload = json.loads(result.stdout)
    report_payload = json.loads(report_path.read_text(encoding="utf-8"))
    estimates = [json.loads(line) for line in estimates_path.read_text(encoding="utf-8").splitlines()]
    assert stdout_payload["bundle_summary"]["status_counts"] == {"passed_with_heading_limitation": 1}
    assert "estimates" not in report_payload["reports"][0]
    assert [estimate["source"] for estimate in estimates] == [
        "gnss",
        "dead_reckoning",
        "dead_reckoning",
        "gnss_reanchor",
        "dead_reckoning",
        "dead_reckoning",
    ]
    assert estimates[-1]["hardware_control_scope"] == "diagnostic_sensorlog_replay_only"


def test_sensorlog_replay_distributed_mode_raises_pdr_resolution(tmp_path: Path) -> None:
    input_path = tmp_path / "sparse-pedometer-sensorlog.json"
    input_path.write_text(json.dumps(_sparse_pedometer_records()), encoding="utf-8")

    baseline = run_sensorlog_replay(
        input_path=input_path,
        gnss_anchor_interval_s=60.0,
    )
    distributed = run_sensorlog_replay(
        input_path=input_path,
        gnss_anchor_interval_s=60.0,
        pdr_resolution_mode="distributed_sensorlog",
    )

    assert baseline["pdr_resolution_mode"] == "pedometer_updates"
    assert baseline["dead_reckoning_estimate_count"] == 1
    assert distributed["pdr_resolution_mode"] == "distributed_sensorlog"
    assert distributed["dead_reckoning_estimate_count"] == 3
    assert distributed["dr_delta_count"] == 3
    assert distributed["dr_delta_distance_m"] == 30.0
    assert distributed["distributed_pdr_summary"]["enabled"] is True
    assert distributed["distributed_pdr_summary"]["raw_imu_integrated"] is False
    assert distributed["distributed_pdr_summary"]["distributed_delta_count"] == 3


def test_sensorlog_replay_wearable_route_constrained_profile_uses_watch_safe_defaults(tmp_path: Path) -> None:
    input_path = tmp_path / "sparse-pedometer-sensorlog.json"
    input_path.write_text(json.dumps(_sparse_pedometer_records()), encoding="utf-8")

    report = run_sensorlog_replay(
        input_path=input_path,
        gnss_anchor_interval_s=60.0,
        pdr_profile="wearable_route_constrained",
    )

    assert report["pdr_profile"] == "wearable_route_constrained"
    assert report["pdr_resolution_mode"] == "distributed_sensorlog"
    assert report["pdr_heading_policy"] == "no_heading"
    assert report["offline_replay_validation_status"] == "passed_with_heading_limitation"
    assert report["dead_reckoning_estimate_count"] == 3
    assert report["distributed_pdr_summary"]["raw_imu_integrated"] is False


def test_sensorlog_replay_cli_profile_can_be_used_without_low_level_flags(tmp_path: Path) -> None:
    input_path = tmp_path / "sparse-pedometer-sensorlog.json"
    input_path.write_text(json.dumps(_sparse_pedometer_records()), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--input",
            str(input_path),
            "--gnss-anchor-interval-s",
            "60",
            "--pdr-profile",
            "wearable_route_constrained",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["pdr_profile"] == "wearable_route_constrained"
    assert payload["pdr_resolution_mode"] == "distributed_sensorlog"
    assert payload["pdr_heading_policy"] == "no_heading"


def _sensorlog_records() -> list[dict[str, str]]:
    start = datetime(2026, 5, 12, 0, 0, tzinfo=timezone.utc)
    records = []
    for index in range(6):
        ts = start + timedelta(seconds=20 * index)
        records.append(
            {
                "loggingTime": ts.isoformat().replace("+00:00", "Z"),
                "locationLatitude": f"{25.0 + index * 0.0001:.7f}",
                "locationLongitude": "121.0000000",
                "locationHorizontalAccuracy": "5.0",
                "locationAltitude": "100.0",
                "locationCourse": "-1.0",
                "pedometerDistance": f"{index * 12.0:.1f}",
                "pedometerNumberOfSteps": str(index * 16),
                "motionYaw": f"{0.01 * index:.3f}",
            }
        )
    return records


def _sparse_pedometer_records() -> list[dict[str, str]]:
    start = datetime(2026, 5, 12, 0, 0, tzinfo=timezone.utc)
    distances = [0.0, 0.0, 0.0, 30.0, 30.0, 30.0]
    records = []
    for index, distance in enumerate(distances):
        ts = start + timedelta(seconds=index)
        records.append(
            {
                "loggingTime": ts.isoformat().replace("+00:00", "Z"),
                "locationLatitude": f"{25.0 + index * 0.00001:.7f}",
                "locationLongitude": "121.0000000",
                "locationHorizontalAccuracy": "5.0",
                "locationCourse": "-1.0",
                "pedometerDistance": f"{distance:.1f}",
                "pedometerNumberOfSteps": str(index),
                "motionYaw": f"{0.01 * index:.3f}",
            }
        )
    return records
