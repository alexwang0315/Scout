import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tools.ins_dr_sensorlog_method_matrix import build_sensorlog_method_matrix


def test_sensorlog_method_matrix_writes_summary_and_method_outputs(tmp_path: Path) -> None:
    sensorlog = tmp_path / "sensorlog.json"
    output_dir = tmp_path / "matrix"
    sensorlog.write_text(json.dumps(_sensorlog_records()), encoding="utf-8")

    summary = build_sensorlog_method_matrix(
        sensorlog_paths=[sensorlog],
        output_dir=output_dir,
        method_names=["baseline_sparse_course", "wearable_route_constrained"],
        gnss_anchor_interval_s=60.0,
        top_error_count=3,
    )

    assert summary["source_tool"] == "ins_dr_sensorlog_method_matrix"
    assert summary["wearable_first_assumption"]["scout_host_imu_required_for_default_client"] is False
    assert summary["recommended_default_method"] == "wearable_route_constrained"
    assert summary["method_count"] == 2
    assert Path(summary["outputs"]["summary_json"]).exists()
    assert Path(summary["outputs"]["summary_markdown"]).exists()
    baseline, wearable = summary["methods"]
    assert baseline["name"] == "baseline_sparse_course"
    assert baseline["pdr_resolution_mode"] == "pedometer_updates"
    assert wearable["name"] == "wearable_route_constrained"
    assert wearable["pdr_resolution_mode"] == "distributed_sensorlog"
    assert wearable["pdr_heading_policy"] == "no_heading"
    assert wearable["recommended_for_wearable_clients"] is True
    assert Path(wearable["outputs"]["html_map"]).exists()
    assert Path(wearable["outputs"]["static_png"]).exists()


def _sensorlog_records() -> list[dict[str, str]]:
    start = datetime(2026, 5, 12, tzinfo=timezone.utc)
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
