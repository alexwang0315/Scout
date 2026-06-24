import hashlib
import json
from pathlib import Path

from pretrip_reference_segment_timing import (
    build_reference_segment_timing,
    write_reference_segment_timing,
)


def _gpx(points: list[tuple[str, float, float]], waypoints: list[tuple[str, float, float]]) -> str:
    waypoint_xml = "\n".join(
        f'  <wpt lat="{lat}" lon="{lon}"><name>{name}</name></wpt>'
        for name, lat, lon in waypoints
    )
    track_xml = "\n".join(
        f'      <trkpt lat="{lat}" lon="{lon}"><time>{timestamp}</time></trkpt>'
        for timestamp, lat, lon in points
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="scout-test" xmlns="http://www.topografix.com/GPX/1/1">
{waypoint_xml}
  <trk><name>synthetic ref</name><trkseg>
{track_xml}
  </trkseg></trk>
</gpx>
"""


def test_reference_segment_timing_builder_uses_aggregate_only_contract(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    (project_root / "sources").mkdir(parents=True)
    (project_root / "candidates").mkdir()
    source_gpx = tmp_path / "synthetic-ref.gpx"
    waypoints = [
        ("屯原登山口", 24.000, 121.000),
        ("雲海保線所", 24.040, 121.000),
        ("天池山莊", 24.120, 121.000),
        ("天池岔路口", 24.129, 121.000),
        ("奇萊南峰", 24.145, 121.000),
        ("南華山", 24.129, 121.015),
    ]
    points = [
        ("2026-01-01T00:00:00+00:00", 24.000, 121.000),
        ("2026-01-01T01:40:00+00:00", 24.040, 121.000),
        ("2026-01-01T05:00:00+00:00", 24.120, 121.000),
        ("2026-01-01T05:40:00+00:00", 24.129, 121.000),
        ("2026-01-01T06:50:00+00:00", 24.145, 121.000),
        ("2026-01-01T07:50:00+00:00", 24.129, 121.000),
        ("2026-01-01T08:40:00+00:00", 24.129, 121.015),
        ("2026-01-01T09:10:00+00:00", 24.129, 121.000),
        ("2026-01-01T10:10:00+00:00", 24.120, 121.000),
        ("2026-01-01T13:40:00+00:00", 24.040, 121.000),
        ("2026-01-01T15:30:00+00:00", 24.000, 121.000),
    ]
    source_gpx.write_text(_gpx(points, waypoints), encoding="utf-8")
    source_sha = hashlib.sha256(source_gpx.read_bytes()).hexdigest()
    source_index = {
        "artifact_kind": "pretrip_historical_gpx_source_index",
        "schema_version": "historical_gpx_importer.v1",
        "project_id": "synthetic_chilai",
        "sources": [
            {
                "source_id": "gpx.source.synthetic.001",
                "original_path": str(source_gpx),
                "original_filename": source_gpx.name,
                "provider": "operator_supplied_local_file",
                "role": "reference_track",
                "route_role": "reference_track",
                "sha256": source_sha,
                "raw_payload_embedded_in_json": False,
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        ],
    }
    (project_root / "sources" / "historical_gpx_source_index.json").write_text(
        json.dumps(source_index, ensure_ascii=False),
        encoding="utf-8",
    )
    route_guide = [
        {
            "candidate_id": "timing.001",
            "from_node_name": "屯原登山口",
            "to_node_name": "雲海保線所",
            "route_guide_segment_time_minutes": 120,
            "route_guide_return_time_minutes": 100,
        },
        {
            "candidate_id": "timing.002",
            "from_node_name": "雲海保線所",
            "to_node_name": "天池山莊",
            "route_guide_segment_time_minutes": 210,
            "route_guide_return_time_minutes": 180,
        },
        {
            "candidate_id": "timing.003",
            "from_node_name": "天池山莊",
            "to_node_name": "天池岔路口",
            "route_guide_segment_time_minutes": 60,
            "route_guide_return_time_minutes": 40,
        },
        {
            "candidate_id": "timing.004",
            "from_node_name": "天池岔路口",
            "to_node_name": "奇萊南峰",
            "route_guide_segment_time_minutes": 80,
            "route_guide_return_time_minutes": 55,
        },
        {
            "candidate_id": "timing.005",
            "from_node_name": "天池岔路口",
            "to_node_name": "南華山",
            "route_guide_segment_time_minutes": 40,
            "route_guide_return_time_minutes": 30,
        },
    ]
    (project_root / "candidates" / "route_guide_timing.json").write_text(
        json.dumps(route_guide, ensure_ascii=False),
        encoding="utf-8",
    )

    payload = build_reference_segment_timing(project_root)

    assert payload["status"] == "ready"
    assert payload["counts"]["usable_segment_count"] == 8
    assert payload["counts"]["measurement_count"] == 8
    assert payload["privacy"]["raw_gpx_embedded_in_json"] is False
    assert payload["privacy"]["coordinates_embedded"] is False
    assert payload["privacy"]["precise_timestamps_embedded"] is False
    assert payload["privacy"]["source_original_paths_embedded"] is False
    assert payload["boundary"]["phase1_runtime_safety_truth"] is False
    assert payload["boundary"]["safety_api_called"] is False

    by_label = {segment["label"]: segment for segment in payload["segments"]}
    assert by_label["屯原登山口 -> 雲海保線所"]["duration_minutes"]["min"] == 100.0
    assert by_label["天池山莊 -> 屯原登山口"]["route_guide_comparison"][
        "guide_duration_minutes"
    ] == 280

    serialized = json.dumps(payload, ensure_ascii=False)
    assert str(source_gpx) not in serialized
    assert "<trkpt" not in serialized
    assert "2026-01-01T" not in serialized

    (project_root / "project.json").write_text(
        json.dumps({"project_id": "synthetic_chilai"}, ensure_ascii=False),
        encoding="utf-8",
    )
    output_path = write_reference_segment_timing(project_root)
    project = json.loads((project_root / "project.json").read_text(encoding="utf-8"))

    assert output_path == project_root / "outputs" / "reference_segment_timing.json"
    assert project["reference_segment_timing_ref"] == "outputs/reference_segment_timing.json"
    assert project["reference_segment_timing_segment_count"] == 8
    assert project["reference_segment_timing_measurement_count"] == 8


def test_chilai_reference_segment_timing_fixture_contract() -> None:
    payload = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "tests"
            / "fixtures"
            / "pretrip"
            / "projects"
            / "chilai_nanhua_day1"
            / "outputs"
            / "reference_segment_timing.json"
        ).read_text(encoding="utf-8")
    )

    assert payload["artifact_kind"] == "pretrip_reference_segment_timing"
    assert payload["counts"]["usable_segment_count"] == 8
    assert payload["counts"]["measurement_count"] == 48
    assert payload["data_quality"]["live_network_calls_made"] is False
    assert payload["privacy"]["raw_gpx_xml_embedded"] is False
    assert payload["privacy"]["coordinates_embedded"] is False
    assert payload["privacy"]["precise_timestamps_embedded"] is False
    assert payload["boundary"]["medical_diagnosis"] is False
    assert payload["boundary"]["phase1_runtime_safety_truth"] is False
    assert payload["segments"][0]["duration_minutes"]["p50"] is not None
    assert payload["segments"][0]["route_guide_comparison"]["guide_duration_minutes"] == 120

    serialized = json.dumps(payload, ensure_ascii=False)
    assert "/Users/" not in serialized
    assert "<trkpt" not in serialized
    assert "<time" not in serialized
