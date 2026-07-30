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


def test_reference_segment_timing_uses_workspace_route_nodes_without_named_waypoints(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "dongqing"
    (project_root / "sources").mkdir(parents=True)
    (project_root / "candidates").mkdir()
    (project_root / "outputs" / "mcp").mkdir(parents=True)
    source_gpx = tmp_path / "timestamped-reference.gpx"
    points = [
        ("2026-01-01T00:00:00+00:00", 23.000, 121.000),
        ("2026-01-01T00:30:00+00:00", 23.010, 121.000),
        ("2026-01-01T01:00:00+00:00", 23.020, 121.000),
    ]
    source_gpx.write_text(_gpx(points, []), encoding="utf-8")
    source_sha = hashlib.sha256(source_gpx.read_bytes()).hexdigest()
    source_index = {
        "artifact_kind": "pretrip_historical_gpx_source_index",
        "schema_version": "historical_gpx_importer.v1",
        "project_id": "dongqing",
        "sources": [
            {
                "source_id": "gpx.source.dongqing.reference.001",
                "original_path": str(source_gpx),
                "original_filename": source_gpx.name,
                "provider": "operator_supplied_local_file",
                "role": "reference_track",
                "route_role": "reference_track",
                "sha256": source_sha,
            }
        ],
    }
    (project_root / "sources" / "historical_gpx_source_index.json").write_text(
        json.dumps(source_index, ensure_ascii=False),
        encoding="utf-8",
    )
    checkpoints = [
        {
            "candidate_id": "cp.start",
            "label": "Start",
            "lat": 23.000,
            "lon": 121.000,
            "route_distance_m": 0.0,
        },
        {
            "candidate_id": "cp.middle",
            "label": "CP middle",
            "lat": 23.010,
            "lon": 121.000,
            "route_distance_m": 1112.0,
        },
        {
            "candidate_id": "cp.finish",
            "label": "Finish",
            "lat": 23.020,
            "lon": 121.000,
            "route_distance_m": 2224.0,
        },
    ]
    (project_root / "candidates" / "checkpoints.json").write_text(
        json.dumps(checkpoints, ensure_ascii=False),
        encoding="utf-8",
    )
    (project_root / "outputs" / "mcp" / "mcp_candidates.json").write_text(
        json.dumps(
            {
                "mcp_candidates": [
                    {
                        "mcp_id": "mcp.named-camp",
                        "label": "Named camp",
                        "lat": 23.010,
                        "lon": 121.000,
                        "distance_m": 1112.0,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "project_id": "dongqing",
                "checkpoint_candidates_ref": "candidates/checkpoints.json",
                "mcp_candidates_ref": "outputs/mcp/mcp_candidates.json",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    payload = build_reference_segment_timing(project_root)

    assert payload["status"] == "ready"
    assert payload["method"]["checkpoint_source"] == "workspace_route_distance_cp_mcp"
    assert payload["counts"]["timed_source_file_count"] == 1
    assert payload["counts"]["checkpoint_count"] == 3
    assert payload["counts"]["segment_count"] == 2
    assert payload["counts"]["usable_segment_count"] == 2
    assert payload["counts"]["measurement_count"] == 2
    assert [item["label"] for item in payload["segments"]] == [
        "Start -> Named camp",
        "Named camp -> Finish",
    ]
    assert "屯原登山口" not in json.dumps(payload, ensure_ascii=False)


def test_reference_segment_timing_rejects_source_with_unreliable_time_order(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    (project_root / "sources").mkdir(parents=True)
    source_gpx = tmp_path / "bad-time-order.gpx"
    source_gpx.write_text(
        _gpx(
            [
                ("2026-01-01T00:00:00+00:00", 24.000, 121.000),
                ("2026-01-01T01:00:00+00:00", 24.040, 121.000),
                ("2026-01-01T00:30:00+00:00", 24.120, 121.000),
            ],
            [
                ("屯原登山口", 24.000, 121.000),
                ("雲海保線所", 24.040, 121.000),
                ("天池山莊", 24.120, 121.000),
                ("天池岔路口", 24.129, 121.000),
                ("奇萊南峰", 24.145, 121.000),
                ("南華山", 24.129, 121.015),
            ],
        ),
        encoding="utf-8",
    )
    (project_root / "sources" / "historical_gpx_source_index.json").write_text(
        json.dumps(
            {
                "project_id": "bad_time_order",
                "sources": [
                    {
                        "source_id": "gpx.source.bad-time",
                        "original_path": str(source_gpx),
                        "original_filename": source_gpx.name,
                        "role": "reference_track",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    payload = build_reference_segment_timing(project_root)

    assert payload["counts"]["timed_source_file_count"] == 0
    assert payload["counts"]["time_quality_rejected_source_file_count"] == 1
    assert payload["source_time_quality"][0]["status"] == "rejected_non_monotonic"
    assert payload["source_time_quality"][0]["non_increasing_ratio"] == 0.5


def test_workspace_rebuild_generates_reference_timing_after_route_enrichment() -> None:
    script = (
        Path(__file__).resolve().parents[1]
        / "tools"
        / "rebuild_pretrip_workspace_on_scout.sh"
    ).read_text(encoding="utf-8")

    layer_index = script.index('echo "Running pretrip layer preparation..."')
    architecture_index = script.index(
        'echo "Preparing Route Architecture Intelligence artifacts..."'
    )
    timing_index = script.index(
        'echo "Building workspace-specific reference segment timing evidence..."'
    )
    verifier_index = script.index('echo "Running spec alignment verifier..."')

    assert layer_index < architecture_index < timing_index < verifier_index
