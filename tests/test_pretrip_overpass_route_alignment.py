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
