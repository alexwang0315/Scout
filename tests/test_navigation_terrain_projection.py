from __future__ import annotations

import hashlib
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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
                    "alpha_channel": True,
                    "opacity": 0.72,
                    "compositing": "source-over",
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


def _attach_terrain_route_hypothesis(
    project_root: Path,
    project: dict,
    *,
    cache_key: str = "cache-1",
    candidate_id: str = "route-demo.terrain-route.R1",
    label: str = "R1 terrain route hypothesis",
    path_coordinates: list[list[float]] | None = None,
    activate: bool = True,
) -> tuple[str, str]:
    hypothesis_ref = (
        f"outputs/spatial/qgis/terrain-route-cache/{cache_key}/hypothesis.json"
    )
    visualization_ref = (
        f"outputs/spatial/qgis/terrain-route-cache/{cache_key}/visualization.json"
    )
    path_coordinates = path_coordinates or [
        [121.11, 24.01],
        [121.15, 24.05],
        [121.19, 24.09],
    ]
    overlay_hashes = {
        "top_5_percent_corridor": "5" * 64,
        "top_10_percent_corridor": "a" * 64,
        "top_20_percent_corridor": "f" * 64,
    }
    bands = []
    overlays = []
    for percentile in (5, 10, 20):
        mode = f"top_{percentile}_percent_corridor"
        overlay_ref = (
            f"outputs/spatial/qgis/terrain-route-cache/{cache_key}/{mode}.png"
        )
        bands.append(
            {
                "name": mode,
                "percentile": percentile,
                "max_relative_corridor_cost": percentile / 10,
                "cell_count": percentile * 10,
                "contains_best_path": percentile != 5,
                "overlay_ref": {
                    "artifact_ref": overlay_ref,
                    "sha256": overlay_hashes[mode],
                    "media_type": "image/png",
                    "crs": "EPSG:3826",
                    "bbox_wgs84": {
                        "west": 121.1,
                        "south": 24.0,
                        "east": 121.2,
                        "north": 24.1,
                    },
                },
            }
        )
        overlays.append(
            {
                "mode": mode,
                "source_path": overlay_ref,
                "sha256": overlay_hashes[mode],
                "bbox_wgs84": {
                    "west": 121.1,
                    "south": 24.0,
                    "east": 121.2,
                    "north": 24.1,
                },
                "pixel_width": 64,
                "pixel_height": 64,
                "percentile": percentile,
                "default_visible": percentile == 10,
                "opacity": {5: 0.58, 10: 0.44, 20: 0.3}[percentile],
                "threshold_semantics": (
                    "finite_symmetric_macro_terrain_relative_cost_cell_percentile"
                ),
                "contains_best_path": percentile != 5,
                "candidate_only": True,
                "runtime_safety_truth": False,
                "operational": False,
            }
        )
    hypothesis = {
        "schema_version": "scout_terrain_route_hypothesis.v0_2",
        "artifact_kind": "terrain_route_hypothesis_run",
        "status": "completed",
        "created_at": "2026-08-28T00:00:00Z",
        "hypotheses": [
            {
                "id": candidate_id,
                "label": label,
                "start": {
                    "x": path_coordinates[0][0],
                    "y": path_coordinates[0][1],
                    "crs": "EPSG:4326",
                },
                "destination": {
                    "x": path_coordinates[-1][0],
                    "y": path_coordinates[-1][1],
                    "crs": "EPSG:4326",
                },
                "best_path": {
                    "type": "LineString",
                    "coordinates": path_coordinates,
                    "crs": "EPSG:4326",
                },
                "path_model": "anisotropic_walk",
                "path_semantics": "minimum_anisotropic_model_cost_trace",
                "corridor": {"bands": bands},
                "metrics": {
                    "relative_score": 0.69,
                    "relative_cost": 0.31,
                    "distance_m": 1234,
                    "elevation_gain_m": 240,
                    "elevation_loss_m": 80,
                    "max_slope_degrees": 31,
                    "median_slope_degrees": 16,
                    "high_cost_fraction": 0.08,
                },
                "reasons": [
                    {
                        "code": "moderate_slope",
                        "polarity": "positive",
                        "description": "Most sampled cells have moderate modeled slope cost.",
                    },
                    {
                        "code": "short_high_slope_section",
                        "polarity": "negative",
                        "description": "A short section has high modeled slope cost.",
                    },
                ],
                "unknowns": [
                    {
                        "code": "legal_access_unknown",
                        "description": "Terrain data does not establish legal access.",
                    }
                ],
                "dem_resolution_m": 20,
                "resolution_class": "macro_terrain_only",
                "confidence_limits": ["microterrain_not_resolved"],
                "cost_model_version": "terrain_routing_cost.v0_1",
                "provenance": {
                    "dem_dataset_id": "dem-demo",
                    "dem_sha256": "d" * 64,
                    "dem_resolution_m": 20,
                    "dem_crs": "EPSG:3826",
                    "dem_extent": {
                        "x_min": 0,
                        "y_min": 0,
                        "x_max": 1000,
                        "y_max": 1000,
                    },
                    "input_endpoints": {
                        "start": {
                            "x": path_coordinates[0][0],
                            "y": path_coordinates[0][1],
                        },
                        "destination": {
                            "x": path_coordinates[-1][0],
                            "y": path_coordinates[-1][1],
                        },
                    },
                    "cost_model_version": "terrain_routing_cost.v0_1",
                    "weights": {"slope_weight": 1.0},
                    "weights_hash": "e" * 64,
                    "grass_version": "8.5.0",
                    "qgis_version": "3.44.13",
                    "backend_id": "grass-qgis-worker",
                    "modules_executed": ["r.slope.aspect", "r.walk", "r.path", "r.cost"],
                    "timestamp": "2026-08-28T00:00:00Z",
                    "algorithm_version": "terrain_route_hypothesis.v0_2",
                    "processing_manifest": {
                        "workflow": "terrain_route_hypothesis.v0_2",
                        "path_model": {
                            "id": "anisotropic_walk",
                            "semantics": "minimum_anisotropic_model_cost_trace",
                        },
                        "band_model": {
                            "id": "symmetric_macro_terrain_cost",
                            "semantics": "finite_symmetric_macro_terrain_relative_cost_cell_percentile",
                        },
                        "path_band_relationship": "separate_model_not_path_confidence_band",
                    },
                    "cache_key": cache_key,
                    "cache_keys": {"route_hypothesis": cache_key},
                },
            }
        ],
    }
    visualization = {
        "schema_version": "scout_terrain_route_visualization.v0_2",
        "artifact_kind": "terrain_route_hypothesis_visualization",
        "authority": "candidate_only",
        "source_type": "terrain_hypothesis",
        "candidate_only": True,
        "runtime_safety_truth": False,
        "operational": False,
        "display_labels": [
            "CANDIDATE",
            "TERRAIN HYPOTHESIS",
            "NOT A VERIFIED TRAIL",
        ],
        "path_model": {
            "id": "anisotropic_walk",
            "semantics": "minimum_anisotropic_model_cost_trace",
            "display_name": "minimum anisotropic model-cost trace",
        },
        "band_model": {
            "id": "symmetric_macro_terrain_cost",
            "semantics": "finite_symmetric_macro_terrain_relative_cost_cell_percentile",
            "display_name": "symmetric macro-terrain detour-score percentile cells",
        },
        "path_band_relationship": "separate_model_not_path_confidence_band",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": path_coordinates},
                "properties": {
                    "id": candidate_id,
                    "kind": "terrain_route_hypothesis_best_path",
                    "feature_class": "terrain_route_hypothesis_best_path",
                    "path_model": "anisotropic_walk",
                    "path_semantics": "minimum_anisotropic_model_cost_trace",
                    "path_band_relationship": "separate_model_not_path_confidence_band",
                    "authority": "candidate_only",
                    "source_type": "terrain_hypothesis",
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                    "operational": False,
                    "observed": False,
                    "official": False,
                    "human_verified": False,
                },
            }
        ],
        "raster_overlays": overlays,
        "boundary": {
            "promotion_allowed": False,
            "candidate_only": True,
            "runtime_safety_truth": False,
            "operational": False,
        },
    }
    _write_json(project_root / hypothesis_ref, hypothesis)
    _write_json(project_root / visualization_ref, visualization)
    if activate:
        project.update(
            {
                "terrain_route_hypothesis_ref": hypothesis_ref,
                "terrain_route_hypothesis_sha256": _sha256(
                    project_root / hypothesis_ref
                ),
                "terrain_route_hypothesis_visualization_ref": visualization_ref,
                "terrain_route_hypothesis_visualization_sha256": _sha256(
                    project_root / visualization_ref
                ),
                "terrain_route_hypothesis_cache_key": cache_key,
                "terrain_route_hypothesis_status": "completed",
                "terrain_route_hypothesis_authority": "candidate_only",
                "terrain_route_hypothesis_candidate_only": True,
                "terrain_route_hypothesis_runtime_safety_truth": False,
            }
        )
    return hypothesis_ref, visualization_ref


def _attach_terrain_route_hypothesis_catalog(
    project_root: Path,
    project: dict,
) -> tuple[str, str]:
    full_key = "1" * 64
    local_key = "2" * 64
    full_refs = _attach_terrain_route_hypothesis(
        project_root,
        project,
        cache_key=full_key,
    )
    local_refs = _attach_terrain_route_hypothesis(
        project_root,
        project,
        cache_key=local_key,
        candidate_id="route-demo.terrain-route.R2",
        label="1148 saddle to Iroko station terrain hypothesis",
        path_coordinates=[
            [121.256226, 23.34452],
            [121.244, 23.348],
            [121.230419, 23.352571],
        ],
        activate=False,
    )
    catalog_ref = "outputs/spatial/qgis/terrain-route-hypothesis-catalog.json"
    catalog = {
        "schema_version": "scout_terrain_route_hypothesis_catalog.v0_1",
        "artifact_kind": "terrain_route_hypothesis_catalog",
        "project_id": "route-demo",
        "default_id": "full-route-r1",
        "entries": [
            {
                "id": "full-route-r1",
                "label": "Full route R1",
                "scope": "full_route",
                "focus_mode": "route_union",
                "start_label": "A",
                "destination_label": "B",
                "hypothesis_ref": full_refs[0],
                "hypothesis_sha256": _sha256(project_root / full_refs[0]),
                "visualization_ref": full_refs[1],
                "visualization_sha256": _sha256(project_root / full_refs[1]),
                "cache_key": full_key,
            },
            {
                "id": "iroko-1148-to-station",
                "label": "1148 saddle to Iroko station",
                "scope": "local",
                "focus_mode": "hypothesis",
                "start_label": "1148 saddle",
                "destination_label": "Iroko station",
                "hypothesis_ref": local_refs[0],
                "hypothesis_sha256": _sha256(project_root / local_refs[0]),
                "visualization_ref": local_refs[1],
                "visualization_sha256": _sha256(project_root / local_refs[1]),
                "cache_key": local_key,
            },
        ],
        "candidate_only": True,
        "runtime_safety_truth": False,
        "operational": False,
    }
    _write_json(project_root / catalog_ref, catalog)
    project.update(
        {
            "terrain_route_hypothesis_catalog_ref": catalog_ref,
            "terrain_route_hypothesis_catalog_sha256": _sha256(
                project_root / catalog_ref
            ),
        }
    )
    return full_refs[0], local_refs[0]


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
    contour_overlay = result["terrain_surface"]["overlays"][0]
    assert contour_overlay["alpha_channel"] is True
    assert contour_overlay["opacity"] == 0.72
    assert contour_overlay["compositing"] == "source-over"
    assert result["terrain_mesh"]["status"] == "not_prepared"
    assert result["terrain_mesh"]["boundary"]["visualization_only"] is True
    assert result["terrain_passage_prior"]["status"] == "not_prepared"
    assert result["terrain_passage_prior"]["learning_contract"][
        "osm_absence_semantics"
    ] == "unknown"
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
    assert result["terrain_validation"]["validation_state"] == (
        "blocked_pending_reference"
    )
    assert result["terrain_validation"]["event_source_mode"] == "prohibited"
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
    assert result["terrain_mesh"]["status"] == "not_prepared"
    assert result["terrain_passage_prior"]["status"] == "not_prepared"
    assert result["route_samples"]["points"] == []
    assert result["risk_candidates"]["points"] == []
    assert result["feature_extraction"]["ridge"]["status"] == "not_prepared"
    assert result["terrain_validation"]["validation_state"] == (
        "blocked_pending_reference"
    )


def test_projection_exposes_hash_bound_candidate_only_terrain_route_hypothesis(
    tmp_path: Path,
) -> None:
    project_root, project = _workspace(tmp_path, sample_count=4)
    hypothesis_ref, visualization_ref = _attach_terrain_route_hypothesis(
        project_root,
        project,
    )

    result = build_navigation_terrain_projection(
        project_root,
        project,
        project_id="route-demo",
    )

    candidate = result["terrain_route_hypothesis"]
    assert candidate["status"] == "candidate_ready"
    assert candidate["candidate"] == "route-demo.terrain-route.R1"
    assert candidate["display_labels"] == [
        "CANDIDATE",
        "TERRAIN HYPOTHESIS",
        "NOT A VERIFIED TRAIL",
    ]
    assert candidate["boundary"] == {
        "authority": "candidate_only",
        "source_type": "terrain_hypothesis",
        "candidate_only": True,
        "runtime_safety_truth": False,
        "operational": False,
        "safe_or_walkable": "not_determined",
        "promotion_allowed": False,
        "human_review_required": True,
    }
    assert candidate["positive_evidence"] == ["moderate_slope"]
    assert candidate["negative_evidence"] == ["short_high_slope_section"]
    assert candidate["unknowns"][0]["code"] == "legal_access_unknown"
    assert candidate["resolution_class"] == "macro_terrain_only"
    assert candidate["path_model"] == {
        "id": "anisotropic_walk",
        "semantics": "minimum_anisotropic_model_cost_trace",
        "display_name": "minimum anisotropic model-cost trace",
    }
    assert candidate["corridor"]["band_model"]["id"] == (
        "symmetric_macro_terrain_cost"
    )
    assert candidate["corridor"]["path_relationship"] == (
        "separate_model_not_path_confidence_band"
    )
    assert [band["percentile"] for band in candidate["corridor"]["bands"]] == [
        5.0,
        10.0,
        20.0,
    ]
    assert all(
        band["runtime_href"].startswith(
            "/admin/pretrip/projects/route-demo/terrain-route-overlays/"
        )
        for band in candidate["corridor"]["bands"]
    )
    assert candidate["corridor"]["bands"][0]["contains_best_path"] is False
    assert all(
        band["best_path_union_applied"] is False
        for band in candidate["corridor"]["bands"]
    )
    assert hypothesis_ref in result["source_refs"]
    assert visualization_ref in result["source_refs"]
    assert "不表示實地存在步道、可通行或安全" in candidate[
        "uncertainty_statement"
    ]


def test_projection_exposes_three_drainage_strategy_alternatives(
    tmp_path: Path,
) -> None:
    project_root, project = _workspace(tmp_path, sample_count=4)
    hypothesis_ref, visualization_ref = _attach_terrain_route_hypothesis(
        project_root,
        project,
    )
    hypothesis_path = project_root / hypothesis_ref
    visualization_path = project_root / visualization_ref
    hypothesis_run = json.loads(hypothesis_path.read_text(encoding="utf-8"))
    visualization = json.loads(visualization_path.read_text(encoding="utf-8"))
    base = hypothesis_run["hypotheses"][0]
    base.update(
        {
            "alternative_index": 1,
            "strategy": "drainage_averse",
            "drainage_penalty_multiplier": 4.0,
        }
    )
    profiles = []
    features = []
    for index, (strategy, multiplier, midpoint) in enumerate(
        (
            ("drainage_averse", 4.0, [121.145, 24.058]),
            ("balanced", 1.5, [121.15, 24.05]),
            ("terrain_only_baseline", 0.0, [121.158, 24.043]),
        ),
        start=1,
    ):
        route = json.loads(json.dumps(base))
        route.update(
            {
                "id": f"route-demo.terrain-route.R{index}",
                "label": f"R{index} {strategy} terrain hypothesis",
                "alternative_index": index,
                "strategy": strategy,
                "drainage_penalty_multiplier": multiplier,
            }
        )
        coordinates = [[121.11, 24.01], midpoint, [121.19, 24.09]]
        route["best_path"]["coordinates"] = coordinates
        if index > 1:
            route["corridor"] = None
        profiles.append(route)
        feature = json.loads(json.dumps(visualization["features"][0]))
        feature["geometry"]["coordinates"] = coordinates
        feature["properties"].update(
            {
                "id": route["id"],
                "candidate_id": f"R{index}",
                "alternative_index": index,
                "strategy": strategy,
                "drainage_penalty_multiplier": multiplier,
            }
        )
        features.append(feature)
    hypothesis_run["hypotheses"] = profiles
    visualization["features"] = features
    _write_json(hypothesis_path, hypothesis_run)
    _write_json(visualization_path, visualization)
    project["terrain_route_hypothesis_sha256"] = _sha256(hypothesis_path)
    project["terrain_route_hypothesis_visualization_sha256"] = _sha256(
        visualization_path
    )

    result = build_navigation_terrain_projection(
        project_root,
        project,
        project_id="route-demo",
    )

    candidate = result["terrain_route_hypothesis"]
    assert candidate["status"] == "candidate_ready"
    assert [item["strategy"] for item in candidate["alternatives"]] == [
        "drainage_averse",
        "balanced",
        "terrain_only_baseline",
    ]
    assert [
        item["drainage_penalty_multiplier"]
        for item in candidate["alternatives"]
    ] == [4.0, 1.5, 0.0]
    assert len(candidate["best_path"]["features"]) == 3
    assert sum(item["corridor_profile"] for item in candidate["alternatives"]) == 1


def test_projection_exposes_hash_bound_candidate_only_hypothesis_catalog(
    tmp_path: Path,
) -> None:
    project_root, project = _workspace(tmp_path, sample_count=4)
    full_ref, local_ref = _attach_terrain_route_hypothesis_catalog(
        project_root,
        project,
    )

    result = build_navigation_terrain_projection(
        project_root,
        project,
        project_id="route-demo",
    )

    candidate = result["terrain_route_hypothesis"]
    selection = candidate["selection"]
    assert selection["status"] == "candidate_ready"
    assert selection["default_id"] == "full-route-r1"
    assert [option["selection_id"] for option in selection["options"]] == [
        "full-route-r1",
        "iroko-1148-to-station",
    ]
    local = selection["options"][1]
    assert local["status"] == "candidate_ready"
    assert local["selection_label"] == "1148 saddle to Iroko station"
    assert local["selection_scope"] == "local"
    assert local["focus_mode"] == "hypothesis"
    assert local["endpoint_labels"] == {
        "start": "1148 saddle",
        "destination": "Iroko station",
    }
    assert local["start"] == {
        "x": 121.256226,
        "y": 23.34452,
        "crs": "EPSG:4326",
        "label": None,
    }
    assert local["destination"] == {
        "x": 121.230419,
        "y": 23.352571,
        "crs": "EPSG:4326",
        "label": None,
    }
    assert local["boundary"]["authority"] == "candidate_only"
    assert local["boundary"]["promotion_allowed"] is False
    assert all(
        "hypothesis_id=iroko-1148-to-station" in band["runtime_href"]
        for band in local["corridor"]["bands"]
    )
    assert full_ref in result["source_refs"]
    assert local_ref in result["source_refs"]
    assert project["terrain_route_hypothesis_catalog_ref"] in result["source_refs"]


def test_projection_selects_new_active_hypothesis_not_yet_in_catalog(
    tmp_path: Path,
) -> None:
    project_root, project = _workspace(tmp_path, sample_count=4)
    _attach_terrain_route_hypothesis_catalog(project_root, project)
    active_key = "3" * 64
    active_ref, _ = _attach_terrain_route_hypothesis(
        project_root,
        project,
        cache_key=active_key,
        candidate_id="route-demo.terrain-route.R3",
        label="Latest A to B terrain route hypothesis",
        path_coordinates=[
            [121.22, 23.31],
            [121.23, 23.32],
            [121.24, 23.33],
        ],
    )

    result = build_navigation_terrain_projection(
        project_root,
        project,
        project_id="route-demo",
    )

    candidate = result["terrain_route_hypothesis"]
    selection = candidate["selection"]
    active_id = f"active-{active_key[:12]}"
    assert candidate["candidate"] == "route-demo.terrain-route.R3"
    assert selection["default_id"] == active_id
    assert [option["selection_id"] for option in selection["options"]] == [
        active_id,
        "full-route-r1",
        "iroko-1148-to-station",
    ]
    active = selection["options"][0]
    assert active["selection_label"] == "Latest A to B terrain route hypothesis"
    assert active["selection_scope"] == "active_request"
    assert active["focus_mode"] == "hypothesis"
    assert active["endpoint_labels"] == {"start": "A", "destination": "B"}
    assert active["start"]["x"] == 121.22
    assert active["start"]["y"] == 23.31
    assert active["destination"]["x"] == 121.24
    assert active["destination"]["y"] == 23.33
    assert active["boundary"]["candidate_only"] is True
    assert active["boundary"]["runtime_safety_truth"] is False
    assert active_ref in result["source_refs"]


def test_projection_fails_closed_for_hash_drifted_catalog_entry(
    tmp_path: Path,
) -> None:
    project_root, project = _workspace(tmp_path, sample_count=4)
    _, local_ref = _attach_terrain_route_hypothesis_catalog(project_root, project)
    (project_root / local_ref).write_text("{}", encoding="utf-8")

    result = build_navigation_terrain_projection(
        project_root,
        project,
        project_id="route-demo",
    )

    candidate = result["terrain_route_hypothesis"]
    selection = candidate["selection"]
    assert selection["status"] == "partially_available"
    local = selection["options"][1]
    assert local["selection_id"] == "iroko-1148-to-station"
    assert local["status"] == "unavailable"
    assert local["reason"] == "terrain_route_hypothesis_validation_failed"
    assert local["source_refs"] == []
    assert local["boundary"]["authority"] == "candidate_only"
    assert local["boundary"]["promotion_allowed"] is False


def test_projection_fails_closed_when_terrain_route_visualization_hash_drifts(
    tmp_path: Path,
) -> None:
    project_root, project = _workspace(tmp_path, sample_count=4)
    _, visualization_ref = _attach_terrain_route_hypothesis(project_root, project)
    visualization_path = project_root / visualization_ref
    visualization_path.write_text("{}", encoding="utf-8")

    result = build_navigation_terrain_projection(
        project_root,
        project,
        project_id="route-demo",
    )

    candidate = result["terrain_route_hypothesis"]
    assert candidate["status"] == "unavailable"
    assert candidate["reason"] == "terrain_route_hypothesis_validation_failed"
    assert candidate["source_refs"] == []
    assert candidate["boundary"]["authority"] == "candidate_only"
    assert candidate["boundary"]["promotion_allowed"] is False


def test_projection_prefers_qgis_grass_vectors_over_local_morphology_comparator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, project = _workspace(tmp_path, sample_count=4)
    terrain_path = project_root / project["terrain_visualization_ref"]
    terrain = json.loads(terrain_path.read_text(encoding="utf-8"))
    terrain["features"] = [
        {
            "type": "Feature",
            "geometry": {
                "type": "MultiLineString",
                "coordinates": [[[121.11, 24.01], [121.12, 24.02]]],
            },
            "properties": {
                "kind": "qgis_candidate_ridge_line",
                "candidate_only": True,
                "runtime_safety_truth": False,
                "operational": False,
            },
        }
    ]
    _write_json(terrain_path, terrain)
    monkeypatch.setattr(
        navigation_terrain_projection,
        "_workspace_structure_projection",
        lambda *_args, **_kwargs: {
            "status": "ready",
            "counts": {"ridge": 4, "valley": 0, "saddle": 0},
            "rendered_counts": {"ridge": 1, "valley": 0, "saddle": 0},
            "points": [{"id": "local-ridge", "feature_kind": "ridge"}],
            "error": None,
            "boundary": {},
        },
    )

    result = build_navigation_terrain_projection(
        project_root,
        project,
        project_id="route-demo",
    )

    ridge = result["feature_extraction"]["ridge"]
    assert ridge["status"] == "candidate_vectors"
    assert ridge["source"] == "qgis_processing_grass"
    assert ridge["count"] == 1
    assert ridge["comparison_point_count"] == 1
    assert ridge["runtime_safety_truth"] is False


def test_standard_grass_projection_does_not_rebuild_python_dtm_analysis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, project = _workspace(tmp_path, sample_count=4)
    project["terrain_visualization_processor"] = "qgis_processing_grass"
    terrain_path = project_root / project["terrain_visualization_ref"]
    terrain = json.loads(terrain_path.read_text(encoding="utf-8"))
    terrain["visualization_spec"] = {
        "actual_processor": "qgis_processing_grass",
        "standard_processor_completed": True,
        "fallback_used": False,
        "python_dtm_processing_used": False,
    }
    terrain["boundary"] = {
        "candidate_only": True,
        "runtime_safety_truth": False,
        "operational": False,
        "visualization_only": True,
    }
    terrain["features"] = [
        {
            "type": "Feature",
            "geometry": {
                "type": "MultiLineString",
                "coordinates": [[[121.11, 24.01], [121.12, 24.02]]],
            },
            "properties": {
                "kind": "qgis_candidate_ridge_line",
                "candidate_only": True,
                "runtime_safety_truth": False,
                "operational": False,
            },
        }
    ]
    _write_json(terrain_path, terrain)

    def fail_python_dtm(*_args: object, **_kwargs: object) -> object:
        pytest.fail("standard GRASS projection must not rebuild Python DTM analysis")

    monkeypatch.setattr(
        navigation_terrain_projection,
        "load_workspace_terrain_grid",
        fail_python_dtm,
    )
    monkeypatch.setattr(
        navigation_terrain_projection,
        "_workspace_structure_projection",
        fail_python_dtm,
    )
    monkeypatch.setattr(
        navigation_terrain_projection,
        "_workspace_terrain_mesh_projection",
        fail_python_dtm,
    )
    monkeypatch.setattr(
        navigation_terrain_projection,
        "_workspace_terrain_bundle",
        fail_python_dtm,
    )
    monkeypatch.setattr(
        navigation_terrain_projection,
        "_workspace_terrain_passage_prior",
        fail_python_dtm,
    )

    result = build_navigation_terrain_projection(
        project_root,
        project,
        project_id="route-demo",
    )

    assert result["terrain_processing"] == {
        "primary_processor": "qgis_processing_grass",
        "standard_processor_completed": True,
        "fallback_used": False,
        "python_dtm_processing_used": False,
        "local_python_comparator": "not_run",
    }
    assert result["terrain_structures"]["status"] == "standard_gis_primary"
    assert result["terrain_structures"]["counts"]["ridge"] == 1
    assert result["terrain_mesh"]["status"] == "not_prepared"
    assert result["terrain_passage_prior"]["status"] == "not_prepared"
    assert result["feature_extraction"]["ridge"]["source"] == (
        "qgis_processing_grass"
    )
    assert result["boundary"]["candidate_only"] is True
    assert result["boundary"]["runtime_safety_truth"] is False


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
            "backbone_support_ratio": 0.72,
            "classification_basis": (
                "component_weighted_geodesic_backbone_overlap"
            ),
            "geometry_method": "subcell_support_constrained_topology_trace.v1",
            "maximum_lateral_adjustment_m": 7,
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
        "saddle_relations": [
            {
                "id": "terrain-relation.saddle-ridge.001",
                "relation_kind": "saddle_near_ridge_candidate",
                "saddle_node_id": "node-a",
                "ridge_edge_id": "edge-000",
                "distance_m": 18,
                "support_radius_m": 80,
                "source_refs": ["terrain-source"],
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        ],
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
        "output_role": "shadow_event_candidate",
        "validation_state": "blocked_pending_reference",
        "gate_mode": "shadow_only",
        "operational_authority": False,
        "presentation_scope": "developer_debug_only",
        "effect_scope": "none",
        "event_source_mode": "shadow_only",
        "blocked_reason": "geometry_reference_validation_missing",
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
                "output_role": "shadow_event_candidate",
                "validation_state": "blocked_pending_reference",
                "gate_mode": "shadow_only",
                "operational_authority": False,
                "presentation_scope": "developer_debug_only",
                "effect_scope": "none",
            }
            for index in range(MAX_ROUTE_TERRAIN_EVENTS + 5)
        ],
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "safe_or_walkable": "not_determined",
            "shadow_only": True,
            "effect_scope": "none",
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
    assert result["route_terrain_events"]["gate_mode"] == "shadow_only"
    assert result["route_terrain_events"]["operational_authority"] is False
    assert result["route_terrain_events"]["presentation_scope"] == (
        "developer_debug_only"
    )
    assert all(
        event["candidate_only"] is True
        and event["runtime_safety_truth"] is False
        and event["source_refs"] == ["terrain-source"]
        and event["output_role"] == "shadow_event_candidate"
        and event["operational_authority"] is False
        and "wrong_way_cue" not in event
        and "recovery_prompt" not in event
        and event["review_prompt"].startswith("Shadow review hypothesis")
        for event in result["route_terrain_events"]["events"]
    )
    assert all(
        edge["output_role"] == "uncertainty_band_visualization"
        and edge["centerline_visible"] is False
        and edge["operational_authority"] is False
        and edge["event_source_mode"] == "prohibited"
        and edge["uncertainty_half_width_m"] >= 60
        for edge in result["terrain_hierarchy"]["edges"]
    )
    assert result["terrain_hierarchy"]["saddle_relations"] == [
        {
            "id": "terrain-relation.saddle-ridge.001",
            "relation_kind": "saddle_near_ridge_candidate",
            "saddle_node_id": "node-a",
            "ridge_edge_id": "edge-000",
            "distance_m": 18.0,
            "support_radius_m": 80.0,
            "source_refs": ["terrain-source"],
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
    ]
    assert result["terrain_hierarchy"]["edges"][0]["classification_basis"] == (
        "component_weighted_geodesic_backbone_overlap"
    )
    assert result["terrain_hierarchy"]["edges"][0]["backbone_support_ratio"] == 0.72
