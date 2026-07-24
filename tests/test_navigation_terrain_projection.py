from __future__ import annotations

import json
from pathlib import Path

import pytest

import navigation_terrain_projection
from navigation_terrain_projection import (
    MAX_ROUTE_TERRAIN_EVENTS,
    MAX_TERRAIN_HIERARCHY_EDGES,
    MAX_ROUTE_SAMPLE_POINTS,
    NavigationTerrainProjectionError,
    build_navigation_terrain_projection,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _workspace(tmp_path: Path, *, sample_count: int = 300) -> tuple[Path, dict]:
    project_root = tmp_path / "route-demo"
    terrain_ref = "outputs/layers/normalized/terrain_visualization.geojson"
    samples_ref = "outputs/layers/normalized/terrain_route_samples.geojson"
    risk_ref = "outputs/layers/candidates/terrain_risk_candidates.json"
    project = {
        "project_id": "route-demo",
        "terrain_visualization_ref": terrain_ref,
        "terrain_route_samples_ref": samples_ref,
        "terrain_risk_candidates_ref": risk_ref,
        "terrain_slope_shading_overlay_ref": (
            "outputs/layers/normalized/terrain_slope_shading.png"
        ),
    }
    _write_json(
        project_root / terrain_ref,
        {
            "counts": {
                "source_dtm_tile_count": 4,
                "contour_marker_count": 80,
                "slope_class_counts": {"slope-30-40": 120},
            },
            "dtm_grid": {
                "bbox_wgs84": {
                    "west": 121.1,
                    "south": 24.0,
                    "east": 121.2,
                    "north": 24.1,
                },
                "crs": "EPSG:3826-compatible",
                "cell_resolution_m": 20,
                "selected_cell_count": 320,
            },
            "features": [],
            "raster_overlays": [
                {
                    "mode": "contours",
                    "source_path": "outputs/layers/normalized/terrain_contours.png",
                    "bbox_wgs84": {
                        "west": 121.1,
                        "south": 24.0,
                        "east": 121.2,
                        "north": 24.1,
                    },
                    "pixel_width": 432,
                    "pixel_height": 169,
                    "cell_resolution_m": 20,
                    "sha256": "a" * 64,
                },
                {
                    "mode": "slope_shading",
                    "source_path": (
                        "outputs/layers/normalized/terrain_slope_shading.png"
                    ),
                    "bbox_wgs84": {
                        "west": 121.1,
                        "south": 24.0,
                        "east": 121.2,
                        "north": 24.1,
                    },
                    "pixel_width": 432,
                    "pixel_height": 169,
                    "cell_resolution_m": 20,
                    "sha256": "b" * 64,
                },
            ],
        },
    )
    _write_json(
        project_root / samples_ref,
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [121.1 + index / 10_000, 24.01],
                    },
                    "properties": {
                        "candidate_id": f"sample-{index:04d}",
                        "distance_m": index * 20,
                        "elevation_m": 2000 + index,
                        "pretrip_risk": index % 100,
                        "teii_20m": (index + 20) % 100,
                        "tri": (index + 40) % 100,
                    },
                }
                for index in range(sample_count)
            ],
        },
    )
    _write_json(
        project_root / risk_ref,
        {
            "candidates": [
                {
                    "candidate_id": "risk-1",
                    "candidate_kind": "terrain_risk_candidate",
                    "lon": 121.15,
                    "lat": 24.05,
                    "reason": "candidate pressure requires review",
                    "confidence": "medium",
                    "review_state": "candidate",
                    "risk_dimensions": {
                        "pretrip_risk": 74,
                        "teii_20m": 91,
                        "tri": 88,
                    },
                    "source_refs": ["outputs/risk/source.json#risk-1"],
                }
            ]
        },
    )
    return project_root, project


def test_projection_is_bounded_candidate_only_and_reports_structure_gaps(
    tmp_path: Path,
) -> None:
    project_root, project = _workspace(tmp_path)

    result = build_navigation_terrain_projection(
        project_root,
        project,
        project_id="route-demo",
    )

    assert result["status"] == "ready_with_structure_gaps"
    assert result["terrain_surface"]["cell_resolution_m"] == 20
    assert result["terrain_surface"]["available_overlay_modes"] == [
        "contours",
        "slope_shading",
    ]
    assert result["route_samples"]["source_count"] == 300
    assert result["route_samples"]["rendered_count"] == MAX_ROUTE_SAMPLE_POINTS
    assert result["route_samples"]["points"][0]["distance_m"] == 0
    assert result["route_samples"]["points"][-1]["distance_m"] == 5980
    assert result["risk_candidates"]["points"][0]["display_pressure"] == 91
    assert result["feature_extraction"]["ridge"]["status"] == "not_prepared"
    assert result["feature_extraction"]["valley"]["status"] == "not_prepared"
    assert result["feature_extraction"]["saddle"]["status"] == "not_prepared"
    assert result["feature_extraction"]["steep_slope"]["status"] == (
        "available_as_raster"
    )
    assert result["boundary"] == {
        "candidate_only": True,
        "runtime_safety_truth": False,
        "safe_or_walkable": "not_determined",
        "raw_dem_embedded": False,
        "raw_gpx_embedded": False,
        "phase1_runtime_mutation_allowed": False,
        "safety_api_called": False,
        "human_review_required": True,
    }


def test_projection_returns_explicit_unavailable_without_artifacts(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "empty"
    project_root.mkdir()

    result = build_navigation_terrain_projection(
        project_root,
        {},
        project_id="empty",
    )

    assert result["status"] == "unavailable"
    assert result["terrain_surface"]["overlays"] == []
    assert result["route_samples"]["points"] == []
    assert result["risk_candidates"]["points"] == []
    assert result["feature_extraction"]["ridge"]["status"] == "not_prepared"


def test_projection_rejects_artifact_reference_outside_project(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "route-demo"
    project_root.mkdir()

    with pytest.raises(
        NavigationTerrainProjectionError,
        match="unsafe navigation terrain artifact reference",
    ):
        build_navigation_terrain_projection(
            project_root,
            {"terrain_visualization_ref": "../outside.json"},
            project_id="route-demo",
        )


def test_projection_bounds_terrain_hierarchy_and_route_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, project = _workspace(tmp_path, sample_count=4)
    hierarchy_edges = [
        {
            "id": f"edge-{index:03d}",
            "kind": ("main_ridge_candidate" if index % 2 == 0 else "drainage_trunk"),
            "from": "node-a",
            "to": "node-b",
            "coordinates_wgs84": [
                [121.1 + point / 10_000, 24.01 + index / 100_000]
                for point in range(100)
            ],
            "length_m": 2000 + index,
            "source_refs": ["terrain-source"],
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
        for index in range(MAX_TERRAIN_HIERARCHY_EDGES + 10)
    ]
    hierarchy = {
        "schema_version": "scout_navigation_terrain_hierarchy.v0",
        "status": "candidate_hierarchy",
        "counts": {"edge_count": len(hierarchy_edges), "node_count": 2},
        "nodes": [
            {
                "id": "node-a",
                "kind": "ridge_divide_node",
                "lon": 121.12,
                "lat": 24.02,
                "elevation_m": 2200,
                "source_refs": ["terrain-source"],
                "candidate_only": True,
                "runtime_safety_truth": False,
            },
            {
                "id": "node-b",
                "kind": "headwater_node",
                "lon": 121.13,
                "lat": 24.03,
                "elevation_m": 2100,
                "source_refs": ["terrain-source"],
                "candidate_only": True,
                "runtime_safety_truth": False,
            },
        ],
        "edges": hierarchy_edges,
        "source_refs": ["terrain-source"],
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "safe_or_walkable": "not_determined",
        },
    }
    route_events = {
        "schema_version": "scout_navigation_route_terrain_events.v0",
        "status": "candidate_events",
        "candidate_event_count": MAX_ROUTE_TERRAIN_EVENTS + 5,
        "truncated": True,
        "events": [
            {
                "id": f"event-{index:03d}",
                "sequence": index + 1,
                "event_type": "watershed_crossing",
                "terrain_relation": "crosses_main_ridge_or_watershed",
                "terrain_feature_id": "edge-000",
                "terrain_feature_kind": "main_ridge_candidate",
                "route_distance_m": index * 100,
                "off_route_distance_m": 0,
                "crossing_angle_degrees": 80,
                "x_twd97": 250_000 + index,
                "y_twd97": 2_600_000 + index,
                "observation_prompt": "Observe the terrain turn.",
                "wrong_way_cue": "Stop if the terrain relation does not appear.",
                "recovery_prompt": "Return to the last confirmed terrain point.",
                "source_refs": ["terrain-source"],
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
            for index in range(MAX_ROUTE_TERRAIN_EVENTS + 5)
        ],
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "safe_or_walkable": "not_determined",
        },
    }
    monkeypatch.setattr(
        navigation_terrain_projection,
        "_workspace_terrain_bundle",
        lambda *_args, **_kwargs: (hierarchy, route_events),
    )

    result = build_navigation_terrain_projection(
        project_root,
        project,
        project_id="route-demo",
    )

    assert result["status"] == "ready_with_terrain_hierarchy"
    assert result["terrain_hierarchy"]["source_edge_count"] == len(hierarchy_edges)
    assert (
        result["terrain_hierarchy"]["rendered_edge_count"]
        == MAX_TERRAIN_HIERARCHY_EDGES
    )
    assert all(
        len(edge["coordinates"]) <= 64 for edge in result["terrain_hierarchy"]["edges"]
    )
    assert result["route_terrain_events"]["rendered_count"] == MAX_ROUTE_TERRAIN_EVENTS
    assert result["route_terrain_events"]["truncated"] is True
    assert all(
        event["candidate_only"] is True
        and event["runtime_safety_truth"] is False
        and event["source_refs"] == ["terrain-source"]
        for event in result["route_terrain_events"]["events"]
    )
