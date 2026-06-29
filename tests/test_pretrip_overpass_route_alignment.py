from __future__ import annotations

import json
from pathlib import Path

from pretrip_overpass_route_alignment import align_workspace_route_to_overpass


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_overpass_route_alignment_uses_50m_gpx_normal_corridor_before_gpx_fallback(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "workspace" / "route"
    _write_json(
        project_root / "project.json",
        {
            "project_id": "route",
            "checkpoint_candidates_ref": "candidates/checkpoints.json",
            "segment_candidates_ref": "candidates/segments.json",
            "segment_display_geometry_ref": "outputs/segment_display_geometry.json",
            "mcp_candidates_ref": "outputs/mcp/mcp_candidates.json",
            "risk_ribbon_ref": "outputs/risk/risk_ribbon.geojson",
        },
    )
    _write_json(
        project_root / "outputs/risk/risk_ribbon.geojson",
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "segment_id": "overpass.segment.001",
                        "start_distance_m": 0.0,
                        "end_distance_m": 1000.0,
                    },
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [121.0, 24.0],
                            [121.0025, 24.0],
                            [121.01, 24.0],
                        ],
                    },
                }
            ],
        },
    )
    _write_json(
        project_root / "candidates/checkpoints.json",
        {
            "candidates": [
                {"candidate_id": "cp.near", "lat": 24.00002, "lon": 121.001},
                {"candidate_id": "cp.end", "lat": 24.00002, "lon": 121.004},
                {"candidate_id": "cp.normal-start", "lat": 24.001, "lon": 121.0045},
                {"candidate_id": "cp.normal-end", "lat": 24.001, "lon": 121.007},
                {"candidate_id": "cp.far", "lat": 24.001, "lon": 121.002},
            ],
            "boundary": {"candidate_only": True, "runtime_safety_truth": False},
        },
    )
    _write_json(
        project_root / "candidates/segments.json",
        {
            "candidates": [
                {
                    "candidate_id": "seg.001",
                    "from_candidate_id": "cp.near",
                    "to_candidate_id": "cp.end",
                    "distance_m": 250.0,
                },
                {
                    "candidate_id": "seg.normal",
                    "from_candidate_id": "cp.normal-start",
                    "to_candidate_id": "cp.normal-end",
                    "distance_m": 50.0,
                }
            ],
            "boundary": {"candidate_only": True},
        },
    )
    _write_json(
        project_root / "outputs/segment_display_geometry.json",
        {
            "segments": [
                {
                    "segment_candidate_id": "seg.001",
                    "coordinates": [
                        {"lat": 24.00002, "lon": 121.001},
                        {"lat": 24.00002, "lon": 121.004},
                    ],
                    "coordinate_segments": [
                        [
                            {"lat": 24.00002, "lon": 121.001},
                            {"lat": 24.00002, "lon": 121.004},
                        ]
                    ],
                },
                {
                    "segment_candidate_id": "seg.normal",
                    "coordinates": [
                        {"lat": 24.001, "lon": 121.0045},
                        {"lat": 24.00035, "lon": 121.005},
                        {"lat": 24.00035, "lon": 121.006},
                        {"lat": 24.001, "lon": 121.007},
                    ],
                    "coordinate_segments": [
                        [
                            {"lat": 24.001, "lon": 121.0045},
                            {"lat": 24.00035, "lon": 121.005},
                            {"lat": 24.00035, "lon": 121.006},
                            {"lat": 24.001, "lon": 121.007},
                        ]
                    ],
                }
            ],
            "boundary": {"candidate_only": True, "runtime_safety_truth": False},
        },
    )
    _write_json(
        project_root / "outputs/mcp/mcp_candidates.json",
        {"mcp_candidates": [], "boundary": {"candidate_only": True}},
    )

    result = align_workspace_route_to_overpass(
        project_root,
        generated_at="2026-06-20T00:00:00+00:00",
    )

    assert result["status"] == "completed"
    project = _load(project_root / "project.json")
    assert (
        project["overpass_aligned_segment_display_geometry_ref"]
        == "outputs/overpass_aligned_segment_display_geometry.json"
    )

    checkpoints = _load(project_root / "outputs/overpass_aligned_checkpoints.json")
    near, end, normal_start, normal_end, far = checkpoints["candidates"]
    assert near["overpass_projection"]["status"] == "snapped_to_overpass"
    assert near["lat"] == 24.0
    assert near["gpx_lat"] == 24.00002
    assert end["overpass_projection"]["status"] == "snapped_to_overpass"
    assert normal_start["overpass_projection"]["status"] == "kept_gpx_outside_overpass_tolerance"
    assert normal_end["overpass_projection"]["status"] == "kept_gpx_outside_overpass_tolerance"
    assert far["overpass_projection"]["status"] == "kept_gpx_outside_overpass_tolerance"
    assert far["lat"] == 24.001

    segments = _load(project_root / "outputs/overpass_aligned_segments.json")
    aligned_segment = segments["candidates"][0]
    assert aligned_segment["overpass_projection"]["status"] == "segment_endpoints_snapped_to_overpass"
    assert aligned_segment["gpx_distance_m"] == 250.0
    assert aligned_segment["distance_m"] > aligned_segment["gpx_distance_m"]
    assert aligned_segment["route_basis"] == "overpass_risk_ribbon_centerline"
    assert aligned_segment["golden_gpx_role_after_alignment"] == "reference_track_evidence"
    assert aligned_segment["overpass_display_point_count"] > 2
    normal_segment = segments["candidates"][1]
    assert normal_segment["overpass_projection"]["status"] == (
        "segment_gpx_normal_corridor_snapped_to_overpass"
    )
    assert normal_segment["gpx_distance_m"] == 50.0
    assert normal_segment["distance_m"] > normal_segment["gpx_distance_m"]
    assert normal_segment["overpass_projection"]["snapped_display_point_count"] == 2
    assert normal_segment["route_basis"] == "overpass_risk_ribbon_centerline"

    display = _load(project_root / "outputs/overpass_aligned_segment_display_geometry.json")
    segment = display["segments"][0]
    assert segment["overpass_alignment"]["route_basis"] == "overpass_risk_ribbon_centerline"
    assert segment["coordinates"][0]["lat"] == 24.0
    assert segment["coordinates"][-1]["lat"] == 24.0
    assert segment["display_point_count"] > 2
    normal_display = display["segments"][1]
    assert normal_display["overpass_alignment"]["route_basis"] == "overpass_risk_ribbon_centerline"
    assert normal_display["coordinates"][0]["lat"] == 24.0
    assert normal_display["coordinates"][-1]["lat"] == 24.0
    assert normal_display["display_point_count"] >= 2
    assert display["boundary"]["runtime_safety_truth"] is False


def test_overpass_route_alignment_uses_checkpoint_route_order_for_foldback_routes(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "workspace" / "foldback"
    _write_json(
        project_root / "project.json",
        {
            "project_id": "foldback",
            "checkpoint_candidates_ref": "candidates/checkpoints.json",
            "segment_candidates_ref": "candidates/segments.json",
            "risk_ribbon_ref": "outputs/risk/risk_ribbon.geojson",
        },
    )
    _write_json(
        project_root / "outputs/risk/risk_ribbon.geojson",
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "segment_id": "overpass.early",
                        "start_distance_m": 0.0,
                        "end_distance_m": 100.0,
                    },
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[121.0, 24.0], [121.001, 24.0]],
                    },
                },
                {
                    "type": "Feature",
                    "properties": {
                        "segment_id": "overpass.foldback",
                        "start_distance_m": 9000.0,
                        "end_distance_m": 9100.0,
                    },
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [121.00054, 24.00039],
                            [121.00056, 24.00039],
                        ],
                    },
                },
            ],
        },
    )
    _write_json(
        project_root / "candidates/checkpoints.json",
        {
            "candidates": [
                {"candidate_id": "cp.start", "lat": 24.0004, "lon": 121.00055},
                {"candidate_id": "cp.001", "lat": 24.00002, "lon": 121.00095},
            ],
            "boundary": {"candidate_only": True, "runtime_safety_truth": False},
        },
    )
    _write_json(
        project_root / "candidates/segments.json",
        {
            "candidates": [
                {
                    "candidate_id": "seg.001",
                    "from_candidate_id": "cp.start",
                    "to_candidate_id": "cp.001",
                    "distance_m": 100.0,
                    "route_point_start_index": 0,
                    "route_point_end_index": 10,
                }
            ],
            "boundary": {"candidate_only": True},
        },
    )

    result = align_workspace_route_to_overpass(
        project_root,
        max_projection_distance_m=100.0,
        generated_at="2026-06-20T00:00:00+00:00",
    )

    assert result["status"] == "completed"
    checkpoints = _load(project_root / "outputs/overpass_aligned_checkpoints.json")
    start = checkpoints["candidates"][0]
    assert start["overpass_projection"]["status"] == "snapped_to_overpass"
    assert start["overpass_projection"]["route_distance_hint_m"] == 0.0
    assert start["route_distance_m"] < 100.0
    assert start["overpass_projection"]["route_distance_m"] < 100.0


def test_overpass_route_alignment_keeps_gpx_when_spatial_nearest_conflicts_with_route_hint(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "workspace" / "spatial"
    _write_json(
        project_root / "project.json",
        {
            "project_id": "spatial",
            "checkpoint_candidates_ref": "candidates/checkpoints.json",
            "segment_candidates_ref": "candidates/segments.json",
            "risk_ribbon_ref": "outputs/risk/risk_ribbon.geojson",
        },
    )
    _write_json(
        project_root / "outputs/risk/risk_ribbon.geojson",
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "segment_id": "overpass.hinted-but-far",
                        "start_distance_m": 0.0,
                        "end_distance_m": 100.0,
                    },
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[121.0, 24.002], [121.001, 24.002]],
                    },
                },
                {
                    "type": "Feature",
                    "properties": {
                        "segment_id": "overpass.nearby",
                        "start_distance_m": 5000.0,
                        "end_distance_m": 5100.0,
                    },
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[121.0, 24.00001], [121.001, 24.00001]],
                    },
                },
            ],
        },
    )
    _write_json(
        project_root / "candidates/checkpoints.json",
        {
            "candidates": [
                {"candidate_id": "cp.start", "lat": 24.0, "lon": 121.0005},
                {"candidate_id": "cp.001", "lat": 24.0, "lon": 121.0009},
            ],
            "boundary": {"candidate_only": True, "runtime_safety_truth": False},
        },
    )
    _write_json(
        project_root / "candidates/segments.json",
        {
            "candidates": [
                {
                    "candidate_id": "seg.001",
                    "from_candidate_id": "cp.start",
                    "to_candidate_id": "cp.001",
                    "distance_m": 100.0,
                    "route_point_start_index": 0,
                    "route_point_end_index": 10,
                }
            ],
            "boundary": {"candidate_only": True},
        },
    )

    result = align_workspace_route_to_overpass(
        project_root,
        max_projection_distance_m=500.0,
        generated_at="2026-06-20T00:00:00+00:00",
    )

    assert result["status"] == "completed"
    checkpoints = _load(project_root / "outputs/overpass_aligned_checkpoints.json")
    start = checkpoints["candidates"][0]
    assert start["overpass_projection"]["status"] == "kept_gpx_route_distance_hint_mismatch"
    assert start["overpass_projection"]["route_distance_hint_m"] == 0.0
    assert start["overpass_projection"]["route_distance_m"] > 4000.0
    assert start["overpass_projection"]["route_distance_delta_m"] > 4000.0
    assert start["overpass_projection"]["offset_m"] < 2.0


def test_overpass_route_alignment_rejects_compressed_segment_display_path(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "workspace" / "compressed"
    _write_json(
        project_root / "project.json",
        {
            "project_id": "compressed",
            "checkpoint_candidates_ref": "candidates/checkpoints.json",
            "segment_candidates_ref": "candidates/segments.json",
            "segment_display_geometry_ref": "outputs/segment_display_geometry.json",
            "risk_ribbon_ref": "outputs/risk/risk_ribbon.geojson",
        },
    )
    _write_json(
        project_root / "outputs/risk/risk_ribbon.geojson",
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "segment_id": "overpass.short.001",
                        "start_distance_m": 0.0,
                        "end_distance_m": 20.0,
                    },
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[121.0, 24.0], [121.0002, 24.0]],
                    },
                }
            ],
        },
    )
    _write_json(
        project_root / "candidates/checkpoints.json",
        {
            "candidates": [
                {"candidate_id": "cp.short-start", "lat": 24.00001, "lon": 121.0},
                {"candidate_id": "cp.short-end", "lat": 24.00001, "lon": 121.0002},
            ],
            "boundary": {"candidate_only": True, "runtime_safety_truth": False},
        },
    )
    _write_json(
        project_root / "candidates/segments.json",
        {
            "candidates": [
                {
                    "candidate_id": "seg.001",
                    "from_candidate_id": "cp.short-start",
                    "to_candidate_id": "cp.short-end",
                    "distance_m": 500.0,
                }
            ],
            "boundary": {"candidate_only": True},
        },
    )
    _write_json(
        project_root / "outputs/segment_display_geometry.json",
        {
            "segments": [
                {
                    "segment_candidate_id": "seg.001",
                    "from_candidate_id": "cp.short-start",
                    "to_candidate_id": "cp.short-end",
                    "distance_m": 500.0,
                    "coordinates": [
                        {"lat": 24.00001, "lon": 121.0},
                        {"lat": 24.00001, "lon": 121.0002},
                    ],
                    "coordinate_segments": [
                        [
                            {"lat": 24.00001, "lon": 121.0},
                            {"lat": 24.00001, "lon": 121.0002},
                        ]
                    ],
                }
            ],
            "boundary": {"candidate_only": True, "runtime_safety_truth": False},
        },
    )

    result = align_workspace_route_to_overpass(
        project_root,
        generated_at="2026-06-20T00:00:00+00:00",
    )

    assert result["status"] == "completed"
    assert result["counts"]["rejected_segment_alignment_count"] >= 1
    segments = _load(project_root / "outputs/overpass_aligned_segments.json")
    aligned_segment = segments["candidates"][0]
    assert aligned_segment["overpass_projection"]["status"] == (
        "rejected_overpass_segment_path_compression_kept_gpx"
    )
    assert "overpass_display_coordinate_segments" not in aligned_segment

    display = _load(project_root / "outputs/overpass_aligned_segment_display_geometry.json")
    display_segment = display["segments"][0]
    assert display_segment["overpass_alignment"]["route_basis"] == (
        "original_gpx_display_geometry"
    )
    assert display_segment["overpass_alignment"]["status"] == (
        "kept_gpx_no_display_points_snapped_to_overpass"
    )


def test_overpass_route_alignment_rejects_inflated_segment_display_path(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "workspace" / "inflated"
    _write_json(
        project_root / "project.json",
        {
            "project_id": "inflated",
            "checkpoint_candidates_ref": "candidates/checkpoints.json",
            "segment_candidates_ref": "candidates/segments.json",
            "segment_display_geometry_ref": "outputs/segment_display_geometry.json",
            "risk_ribbon_ref": "outputs/risk/risk_ribbon.geojson",
        },
    )
    _write_json(
        project_root / "outputs/risk/risk_ribbon.geojson",
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "segment_id": "overpass.long.001",
                        "start_distance_m": 0.0,
                        "end_distance_m": 10_000.0,
                    },
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[121.0, 24.0], [121.1, 24.0]],
                    },
                }
            ],
        },
    )
    _write_json(
        project_root / "candidates/checkpoints.json",
        {
            "candidates": [
                {"candidate_id": "cp.long-start", "lat": 24.00001, "lon": 121.001},
                {"candidate_id": "cp.long-end", "lat": 24.00001, "lon": 121.099},
            ],
            "boundary": {"candidate_only": True, "runtime_safety_truth": False},
        },
    )
    _write_json(
        project_root / "candidates/segments.json",
        {
            "candidates": [
                {
                    "candidate_id": "seg.001",
                    "from_candidate_id": "cp.long-start",
                    "to_candidate_id": "cp.long-end",
                    "distance_m": 100.0,
                }
            ],
            "boundary": {"candidate_only": True},
        },
    )
    _write_json(
        project_root / "outputs/segment_display_geometry.json",
        {
            "segments": [
                {
                    "segment_candidate_id": "seg.001",
                    "distance_m": 100.0,
                    "coordinates": [
                        {"lat": 24.00001, "lon": 121.001},
                        {"lat": 24.00002, "lon": 121.0018},
                    ],
                    "coordinate_segments": [
                        [
                            {"lat": 24.00001, "lon": 121.001},
                            {"lat": 24.00002, "lon": 121.0018},
                        ]
                    ],
                }
            ],
            "boundary": {"candidate_only": True, "runtime_safety_truth": False},
        },
    )

    result = align_workspace_route_to_overpass(
        project_root,
        generated_at="2026-06-20T00:00:00+00:00",
    )

    assert result["status"] == "completed"
    assert result["counts"]["rejected_segment_alignment_count"] >= 1
    segments = _load(project_root / "outputs/overpass_aligned_segments.json")
    aligned_segment = segments["candidates"][0]
    assert aligned_segment["overpass_projection"]["status"] == (
        "rejected_overpass_segment_path_inflation_kept_gpx"
    )
    assert aligned_segment["overpass_projection"]["aligned_distance_m"] == 9800.0
    assert "overpass_display_coordinate_segments" not in aligned_segment

    display = _load(project_root / "outputs/overpass_aligned_segment_display_geometry.json")
    display_segment = display["segments"][0]
    assert display_segment["display_point_count"] < 10
    assert display_segment["coordinates"][0]["lon"] < 121.01
    assert display_segment["coordinates"][-1]["lon"] < 121.01
