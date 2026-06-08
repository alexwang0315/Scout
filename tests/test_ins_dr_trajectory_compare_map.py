import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tools.ins_dr_trajectory_compare_map import build_trajectory_comparison


def test_trajectory_compare_writes_report_html_and_png(tmp_path: Path) -> None:
    sensorlog = tmp_path / "sensorlog.json"
    estimates = tmp_path / "estimates.jsonl"
    overpass = tmp_path / "overpass.geojson"
    output_dir = tmp_path / "out"
    sensorlog.write_text(json.dumps(_sensorlog_records()), encoding="utf-8")
    estimates.write_text(
        "\n".join(
            json.dumps(
                {
                    "source": "dead_reckoning",
                    "timestamp_s": _timestamp(index),
                    "lat": 25.0 + index * 0.0001,
                    "lon": 121.0 + 0.00002,
                    "raw_evidence_refs": [f"{sensorlog}:1:sensorlog_pedometer"],
                }
            )
            for index in range(3)
        )
        + "\n",
        encoding="utf-8",
    )
    overpass.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {},
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[121.0, 25.0], [121.0001, 25.0002]],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    report = build_trajectory_comparison(
        sensorlog_paths=[sensorlog],
        estimates_jsonl_path=estimates,
        overpass_geojson_path=overpass,
        output_dir=output_dir,
    )

    assert report["source_tool"] == "ins_dr_trajectory_compare_map"
    assert report["bundle_summary"]["dead_reckoning_sample_count"] == 3
    assert report["bundle_summary"]["dead_reckoning_error_m"]["median"] > 0
    assert Path(report["outputs"]["report_json"]).exists()
    assert Path(report["outputs"]["html_map"]).exists()
    assert Path(report["outputs"]["static_png"]).exists()
    assert "leaflet@1.9.4" in Path(report["outputs"]["html_map"]).read_text(encoding="utf-8")


def _sensorlog_records() -> list[dict[str, str]]:
    return [
        {
            "loggingTime": datetime.fromtimestamp(_timestamp(index), tz=timezone.utc).isoformat().replace("+00:00", "Z"),
            "locationLatitude": f"{25.0 + index * 0.0001:.7f}",
            "locationLongitude": "121.0000000",
            "locationHorizontalAccuracy": "5.0",
        }
        for index in range(3)
    ]


def _timestamp(index: int) -> float:
    start = datetime(2026, 5, 12, tzinfo=timezone.utc)
    return (start + timedelta(seconds=index)).timestamp()
