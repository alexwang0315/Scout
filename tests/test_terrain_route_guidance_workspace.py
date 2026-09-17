from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import terrain_route_guidance_workspace as guidance_workspace
from admin_api import create_admin_app
from terrain_route_guidance_map_review import TerrainGuidanceMapReviewScope
from terrain_route_guidance_workspace import (
    TerrainGuidanceInterpretRequest,
    TerrainGuidanceManualAnchorRequest,
    TerrainGuidanceResolveRequest,
    TerrainGuidanceReviewRequest,
    TerrainRouteGuidanceWorkspaceService,
    build_guided_route_cache_binding,
    load_reviewed_guidance_execution_plan,
)
from terrain_route_hypothesis_models import GeoPoint


NARRATIVE = (
    "於1148鞍沿著稜線走至其開始轉為上坡後，往西邊的坡切，"
    "沿遇到的第一個溝東側的稜線續行，在寬闊的稜線上抓方向往北走。"
    "H820m轉稜，下至溪底，過溪。沿著小溪溝上大概15m之後，"
    "往西腰繞，沿著獵徑之字繞上稜，抵達異祿閣稜線。"
)

ROUTE_START = GeoPoint(x=121.204, y=23.464, crs="EPSG:4326", label="A")
ROUTE_DESTINATION = GeoPoint(
    x=121.211,
    y=23.471,
    crs="EPSG:4326",
    label="B",
)


class _FakeElevationSampler:
    backend_id = "fake_dem_elevation.v0_1"

    def sample(
        self,
        raster_path: Path,
        points_wgs84: tuple[tuple[float, float], ...],
    ) -> tuple[float | None, ...]:
        if raster_path.name == "terrain_route_top_5_percent_corridor.tif":
            return tuple(
                1.0 if longitude < 121.209 else 255.0
                for longitude, _latitude in points_wgs84
            )
        assert raster_path.name == "dem_route_bbox.tif"
        values: list[float | None] = []
        for longitude, _latitude in points_wgs84:
            if abs(longitude - 121.205) < 0.000001:
                values.append(1260.0)
            elif abs(longitude - 121.207) < 0.000001:
                values.append(1148.0)
            elif abs(longitude - 121.208) < 0.000001:
                values.append(1270.0)
            elif abs(longitude - ((121.205 + 121.207 + 121.208) / 3)) < 0.000001:
                values.append(820.0)
            else:
                values.append(900.0)
        return tuple(values)


class _FailingElevationSampler:
    backend_id = "failing_dem_elevation.v0_1"

    def sample(
        self,
        raster_path: Path,
        points_wgs84: tuple[tuple[float, float], ...],
    ) -> tuple[float | None, ...]:
        del raster_path, points_wgs84
        raise ValueError("synthetic DEM sampling failure")


class _NoDataElevationSampler:
    backend_id = "nodata_dem_elevation.v0_1"

    def sample(
        self,
        raster_path: Path,
        points_wgs84: tuple[tuple[float, float], ...],
    ) -> tuple[float | None, ...]:
        del raster_path
        return tuple(None for _point in points_wgs84)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _workspace(tmp_path: Path, project_id: str = "guidance_demo") -> Path:
    project_root = tmp_path / project_id
    feature_root = project_root / "outputs/spatial/qgis/feature-run"
    feature_root.mkdir(parents=True)
    dem_path = feature_root / "dem_route_bbox.tif"
    dem_path.write_bytes(b"synthetic-dem-fixture")
    manifest_path = feature_root / "terrain_feature_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "artifact_kind": "terrain_feature_manifest",
                "candidate_only": True,
                "runtime_safety_truth": False,
                "operational": False,
                "fixture": False,
                "synthetic": False,
                "source_resolution": {
                    "status": "reported",
                    "x_m": 20,
                    "y_m": 20,
                    "crs": "EPSG:3826",
                    "adds_source_resolution": False,
                },
                "artifacts": {"dem_route_bbox": dem_path.name},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    ridge_path = feature_root / "ridge_lines.geojson"
    ridge_path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {
                            "kind": "qgis_candidate_ridge_line",
                            "candidate_only": True,
                            "runtime_safety_truth": False,
                            "operational": False,
                            "label": "ridge candidate 1",
                        },
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [
                                [121.205, 23.465],
                                [121.207, 23.467],
                                [121.208, 23.470],
                            ],
                        },
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    valley_path = feature_root / "valley_lines.geojson"
    valley_path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {
                            "kind": "qgis_candidate_valley_line",
                            "candidate_only": True,
                            "runtime_safety_truth": False,
                            "operational": False,
                            "label": "valley candidate 1",
                        },
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [
                                [121.209, 23.464],
                                [121.210, 23.466],
                            ],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "project_id": project_id,
                "terrain_feature_manifest_ref": str(
                    manifest_path.relative_to(project_root)
                ),
                "terrain_dem_route_bbox_raster_ref": str(
                    dem_path.relative_to(project_root)
                ),
                "qgis_ridge_lines_vector_ref": str(
                    ridge_path.relative_to(project_root)
                ),
                "qgis_valley_lines_vector_ref": str(
                    valley_path.relative_to(project_root)
                ),
                "official_trail_ref": "official/trails.geojson",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return project_root


def _attach_candidate_corridor_reference(
    project_root: Path,
    *,
    project_id: str = "guidance_demo",
) -> None:
    project = json.loads((project_root / "project.json").read_text())
    ridge_ref = Path(str(project["qgis_ridge_lines_vector_ref"]))
    ridge_path = project_root / ridge_ref
    ridge_payload = json.loads(ridge_path.read_text())
    ridge_payload["features"].append(
        {
            "type": "Feature",
            "properties": {
                "kind": "qgis_candidate_ridge_line",
                "candidate_only": True,
                "runtime_safety_truth": False,
                "operational": False,
                "label": "ridge candidate outside reference corridor",
            },
            "geometry": {
                "type": "LineString",
                "coordinates": [
                    [121.2095, 23.466],
                    [121.2100, 23.468],
                    [121.2105, 23.470],
                ],
            },
        }
    )
    ridge_path.write_text(json.dumps(ridge_payload), encoding="utf-8")

    cache_key = "c" * 64
    artifact_root = Path("outputs/spatial/qgis/terrain-route-cache") / cache_key
    raster_ref = artifact_root / "terrain_route_top_5_percent_corridor.tif"
    raster_path = project_root / raster_ref
    raster_path.parent.mkdir(parents=True, exist_ok=True)
    raster_path.write_bytes(b"synthetic-candidate-corridor-mask")
    hypothesis_ref = artifact_root / "terrain_route_hypothesis.json"
    visualization_ref = artifact_root / "terrain_route_visualization.json"
    hypothesis_payload = {
        "schema_version": "scout_terrain_route_hypothesis.v0_2",
        "artifact_kind": "terrain_route_hypothesis_run",
        "status": "completed",
        "created_at": "2026-09-02T00:00:00Z",
        "hypotheses": [
            {
                "id": "synthetic-local-r1",
                "label": "Synthetic local terrain hypothesis",
                "alternative_index": 1,
                "strategy": "terrain_only_baseline",
                "drainage_penalty_multiplier": 0,
                "start": ROUTE_START.model_dump(mode="json"),
                "destination": ROUTE_DESTINATION.model_dump(mode="json"),
                "best_path": {
                    "type": "LineString",
                    "coordinates": [
                        [ROUTE_START.x, ROUTE_START.y],
                        [121.207, 23.467],
                        [ROUTE_DESTINATION.x, ROUTE_DESTINATION.y],
                    ],
                    "crs": "EPSG:4326",
                },
                "corridor": {
                    "bands": [
                        {
                            "name": "top_5_percent_corridor",
                            "percentile": 5,
                            "max_relative_corridor_cost": 1,
                            "cell_count": 100,
                            "contains_best_path": True,
                            "raster_ref": {
                                "artifact_ref": str(raster_ref),
                                "sha256": _sha(raster_path),
                                "media_type": "image/tiff",
                                "crs": "EPSG:3826",
                                "bbox_wgs84": {
                                    "west": 121.203,
                                    "south": 23.463,
                                    "east": 121.212,
                                    "north": 23.472,
                                },
                            },
                        }
                    ]
                },
                "metrics": {
                    "relative_cost": 1,
                    "distance_m": 1200,
                    "elevation_gain_m": 300,
                    "elevation_loss_m": 500,
                    "max_slope_degrees": 35,
                    "median_slope_degrees": 18,
                    "high_cost_fraction": 0.1,
                },
                "dem_resolution_m": 20,
                "resolution_class": "macro_terrain_only",
                "confidence_limits": ["microterrain_not_resolved"],
                "cost_model_version": "terrain_routing_cost.v0_2",
                "provenance": {
                    "dem_dataset_id": "synthetic-dem",
                    "dem_sha256": _sha(
                        project_root
                        / "outputs/spatial/qgis/feature-run/dem_route_bbox.tif"
                    ),
                    "dem_resolution_m": 20,
                    "dem_crs": "EPSG:3826",
                    "dem_extent": {
                        "x_min": 0,
                        "y_min": 0,
                        "x_max": 100,
                        "y_max": 100,
                    },
                    "input_endpoints": {
                        "start": ROUTE_START.model_dump(mode="json"),
                        "destination": ROUTE_DESTINATION.model_dump(mode="json"),
                    },
                    "cost_model_version": "terrain_routing_cost.v0_2",
                    "weights": {"slope_weight": 1},
                    "weights_hash": "d" * 64,
                    "grass_version": "8.5.0",
                    "qgis_version": "3.44.13",
                    "backend_id": "synthetic-test-backend",
                    "modules_executed": ["r.walk", "r.path", "r.cost"],
                    "timestamp": "2026-09-02T00:00:00Z",
                    "algorithm_version": "terrain_route_hypothesis.v0_2",
                    "processing_manifest": {
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
    hypothesis_path = project_root / hypothesis_ref
    hypothesis_path.write_text(json.dumps(hypothesis_payload), encoding="utf-8")
    visualization_path = project_root / visualization_ref
    visualization_path.write_text(
        json.dumps(
            {
                "artifact_kind": "terrain_route_hypothesis_visualization",
                "candidate_only": True,
                "runtime_safety_truth": False,
                "operational": False,
            }
        ),
        encoding="utf-8",
    )
    catalog_ref = Path("outputs/spatial/qgis/terrain-route-hypothesis-catalog.json")
    catalog_path = project_root / catalog_ref
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_text(
        json.dumps(
            {
                "schema_version": "scout_terrain_route_hypothesis_catalog.v0_1",
                "artifact_kind": "terrain_route_hypothesis_catalog",
                "project_id": project_id,
                "default_id": "local-r1",
                "entries": [
                    {
                        "id": "local-r1",
                        "label": "Local R1 terrain hypothesis",
                        "scope": "local",
                        "focus_mode": "hypothesis",
                        "start_label": "A",
                        "destination_label": "B",
                        "hypothesis_ref": str(hypothesis_ref),
                        "hypothesis_sha256": _sha(hypothesis_path),
                        "visualization_ref": str(visualization_ref),
                        "visualization_sha256": _sha(visualization_path),
                        "cache_key": cache_key,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    project.update(
        {
            "terrain_route_hypothesis_catalog_ref": str(catalog_ref),
            "terrain_route_hypothesis_catalog_sha256": _sha(catalog_path),
        }
    )
    (project_root / "project.json").write_text(
        json.dumps(project, sort_keys=True),
        encoding="utf-8",
    )


def _attach_r1_r3_path_references(project_root: Path) -> None:
    _attach_candidate_corridor_reference(project_root)
    project_path = project_root / "project.json"
    project = json.loads(project_path.read_text())
    ridge_path = project_root / project["qgis_ridge_lines_vector_ref"]
    ridge_payload = json.loads(ridge_path.read_text())
    ridge_payload["features"][-1]["geometry"]["coordinates"] = [
        [121.2095, 23.4640],
        [121.2100, 23.4645],
        [121.2105, 23.4650],
    ]
    ridge_path.write_text(json.dumps(ridge_payload), encoding="utf-8")
    catalog_path = project_root / project["terrain_route_hypothesis_catalog_ref"]
    catalog = json.loads(catalog_path.read_text())
    entry = catalog["entries"][0]
    hypothesis_path = project_root / entry["hypothesis_ref"]
    payload = json.loads(hypothesis_path.read_text())
    first_hypothesis = payload["hypotheses"][0]
    for alternative_index, (strategy, multiplier, midpoint) in enumerate(
        (
            ("balanced", 1.5, [121.2068, 23.4672]),
            ("terrain_only_baseline", 0, [121.2072, 23.4668]),
        ),
        start=2,
    ):
        hypothesis = json.loads(json.dumps(first_hypothesis))
        hypothesis.update(
            {
                "id": f"synthetic-local-r{alternative_index}",
                "label": f"Synthetic local R{alternative_index} terrain hypothesis",
                "alternative_index": alternative_index,
                "strategy": strategy,
                "drainage_penalty_multiplier": multiplier,
                "corridor": None,
            }
        )
        hypothesis["best_path"]["coordinates"] = [
            [ROUTE_START.x, ROUTE_START.y],
            midpoint,
            [ROUTE_DESTINATION.x, ROUTE_DESTINATION.y],
        ]
        payload["hypotheses"].append(hypothesis)

    hypothesis_path.write_text(json.dumps(payload), encoding="utf-8")
    entry["hypothesis_sha256"] = _sha(hypothesis_path)
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    project["terrain_route_hypothesis_catalog_sha256"] = _sha(catalog_path)
    project.update(
        {
            "terrain_route_hypothesis_ref": entry["hypothesis_ref"],
            "terrain_route_hypothesis_sha256": entry["hypothesis_sha256"],
            "terrain_route_hypothesis_cache_key": entry["cache_key"],
        }
    )
    project_path.write_text(json.dumps(project, sort_keys=True), encoding="utf-8")


def _service() -> TerrainRouteGuidanceWorkspaceService:
    return TerrainRouteGuidanceWorkspaceService(
        now_factory=lambda: datetime(2026, 9, 1, tzinfo=timezone.utc)
    )


def test_dem_sampler_adds_ranked_ridge_elevation_and_saddle_candidates(
    tmp_path: Path,
) -> None:
    project_root = _workspace(tmp_path)
    service = TerrainRouteGuidanceWorkspaceService(
        now_factory=lambda: datetime(2026, 9, 1, tzinfo=timezone.utc),
        elevation_sampler=_FakeElevationSampler(),
    )
    interpreted = service.interpret(
        project_root,
        project_id="guidance_demo",
        request=TerrainGuidanceInterpretRequest(
            narrative=NARRATIVE,
            source_id="iroko-d3",
        ),
    )

    resolved = service.resolve(
        project_root,
        project_id="guidance_demo",
        request=TerrainGuidanceResolveRequest(
            guidance_id=interpreted["guidance_plan"]["guidance_id"],
            route_start=ROUTE_START,
            route_destination=ROUTE_DESTINATION,
            search_margin_m=200,
        ),
    )

    index = resolved["feature_index"]
    assert index["elevation_sampling_status"] == "completed"
    assert index["elevation_sampling_backend"] == _FakeElevationSampler.backend_id
    assert index["derived_saddle_count"] == 1
    assert index["elevation_sample_count"] > 0
    assert index["elevation_nodata_count"] == 0
    saddle = next(item for item in index["features"] if item["landform"] == "saddle")
    assert saddle["elevation_m"] == 1148.0
    assert saddle["geometry"]["type"] == "Point"
    assert saddle["selection_source"] == "dem_derived"
    assert saddle["candidate_only"] is True
    assert saddle["runtime_safety_truth"] is False

    by_constraint = {
        item["constraint_id"]: item for item in resolved["resolution"]["constraints"]
    }
    assert by_constraint["G1"]["status"] == "resolved"
    assert by_constraint["G1"]["candidate_feature_ids"] == [saddle["feature_id"]]
    assert by_constraint["G1"]["selected_feature_id"] is None
    assert by_constraint["G6"]["status"] == "resolved"
    ridge = next(
        item
        for item in index["features"]
        if item["feature_id"] == by_constraint["G6"]["candidate_feature_ids"][0]
    )
    assert ridge["landform"] == "ridge"
    assert ridge["elevation_m"] == 820.0
    assert resolved["guided_execution_ready"] is False
    assert resolved["review"] is None


def test_hash_bound_candidate_corridor_overlap_ranks_without_filtering_or_selection(
    tmp_path: Path,
) -> None:
    project_root = _workspace(tmp_path)
    _attach_candidate_corridor_reference(project_root)
    service = TerrainRouteGuidanceWorkspaceService(
        now_factory=lambda: datetime(2026, 9, 1, tzinfo=timezone.utc),
        elevation_sampler=_FakeElevationSampler(),
    )
    interpreted = service.interpret(
        project_root,
        project_id="guidance_demo",
        request=TerrainGuidanceInterpretRequest(
            narrative=NARRATIVE,
            source_id="iroko-d3",
        ),
    )

    resolved = service.resolve(
        project_root,
        project_id="guidance_demo",
        request=TerrainGuidanceResolveRequest(
            guidance_id=interpreted["guidance_plan"]["guidance_id"],
            route_start=ROUTE_START,
            route_destination=ROUTE_DESTINATION,
            search_margin_m=200,
            reference_hypothesis_id="local-r1",
            reference_corridor_band_name="top_5_percent_corridor",
        ),
    )

    feature_index = resolved["feature_index"]
    reference = feature_index["reference_corridor"]
    assert reference["hypothesis_id"] == "local-r1"
    assert reference["band_name"] == "top_5_percent_corridor"
    assert reference["sampling_backend"] == _FakeElevationSampler.backend_id
    assert reference["feature_count"] >= 3
    assert 0 < reference["features_with_overlap"] < reference["feature_count"]
    dem_features = [
        item
        for item in feature_index["features"]
        if item["selection_source"] == "dem_derived"
    ]
    assert all(item["reference_corridor_overlap"] for item in dem_features)

    by_constraint = {
        item["constraint_id"]: item for item in resolved["resolution"]["constraints"]
    }
    terminal_ridge = by_constraint["G11"]
    assert terminal_ridge["status"] == "multiple_candidates"
    assert len(terminal_ridge["candidate_feature_ids"]) == 2
    feature_by_id = {item["feature_id"]: item for item in dem_features}
    ranked_overlaps = [
        feature_by_id[feature_id]["reference_corridor_overlap"]["overlap_fraction"]
        for feature_id in terminal_ridge["candidate_feature_ids"]
    ]
    assert ranked_overlaps == sorted(ranked_overlaps, reverse=True)
    assert terminal_ridge["selected_feature_id"] is None
    assert resolved["guided_execution_ready"] is False
    assert resolved["candidate_only"] is True
    assert resolved["runtime_safety_truth"] is False


def test_r1_r3_paths_build_review_shortlist_without_removing_candidates(
    tmp_path: Path,
) -> None:
    project_root = _workspace(tmp_path)
    _attach_r1_r3_path_references(project_root)
    service = TerrainRouteGuidanceWorkspaceService(
        now_factory=lambda: datetime(2026, 9, 1, tzinfo=timezone.utc),
        elevation_sampler=_FakeElevationSampler(),
    )
    interpreted = service.interpret(
        project_root,
        project_id="guidance_demo",
        request=TerrainGuidanceInterpretRequest(
            narrative=NARRATIVE,
            source_id="iroko-d3",
        ),
    )

    resolved = service.resolve(
        project_root,
        project_id="guidance_demo",
        request=TerrainGuidanceResolveRequest(
            guidance_id=interpreted["guidance_plan"]["guidance_id"],
            route_start=ROUTE_START,
            route_destination=ROUTE_DESTINATION,
            search_margin_m=200,
            reference_hypothesis_ids=["active-cccccccccccc"],
            reference_corridor_band_name="top_5_percent_corridor",
            reference_path_scope_m=40,
        ),
    )

    feature_index = resolved["feature_index"]
    assert [
        item["hypothesis_id"] for item in feature_index["reference_corridors"]
    ] == ["active-cccccccccccc"]
    assert [item["display_id"] for item in feature_index["reference_paths"]] == [
        "R1",
        "R2",
        "R3",
    ]
    dem_features = [
        item
        for item in feature_index["features"]
        if item["selection_source"] == "dem_derived"
    ]
    assert all(len(item["reference_path_proximities"]) == 3 for item in dem_features)
    assert all(item["reference_path_support"]["reference_count"] == 3 for item in dem_features)

    by_constraint = {
        item["constraint_id"]: item for item in resolved["resolution"]["constraints"]
    }
    terminal_ridge = by_constraint["G11"]
    assert len(terminal_ridge["candidate_feature_ids"]) == 2
    assert len(terminal_ridge["review_shortlist_feature_ids"]) == 1
    assert terminal_ridge["out_of_scope_candidate_count"] == 1
    assert terminal_ridge["review_scope_semantics"] == (
        "candidate_path_or_corridor_union_for_review_scope_only"
    )
    assert terminal_ridge["selected_feature_id"] is None
    assert resolved["candidate_only"] is True
    assert resolved["runtime_safety_truth"] is False


def test_inspect_preserves_hash_binding_for_legacy_json_without_additive_fields(
    tmp_path: Path,
) -> None:
    project_root = _workspace(tmp_path)
    service = _service()
    interpreted = service.interpret(
        project_root,
        project_id="guidance_demo",
        request=TerrainGuidanceInterpretRequest(
            narrative=NARRATIVE,
            source_id="iroko-d3",
        ),
    )
    service.resolve(
        project_root,
        project_id="guidance_demo",
        request=TerrainGuidanceResolveRequest(
            guidance_id=interpreted["guidance_plan"]["guidance_id"],
            route_start=ROUTE_START,
            route_destination=ROUTE_DESTINATION,
            search_margin_m=200,
        ),
    )
    project_path = project_root / "project.json"
    project = json.loads(project_path.read_text())
    feature_path = project_root / project["terrain_route_guidance_feature_index_ref"]
    feature_payload = json.loads(feature_path.read_text())
    feature_payload.pop("reference_corridors", None)
    feature_payload.pop("reference_paths", None)
    for feature in feature_payload["features"]:
        feature.pop("reference_corridor_overlaps", None)
        feature.pop("reference_corridor_support", None)
        feature.pop("reference_path_proximities", None)
        feature.pop("reference_path_support", None)
    feature_path.write_text(json.dumps(feature_payload), encoding="utf-8")

    resolution_path = project_root / project["terrain_route_guidance_resolution_ref"]
    resolution_payload = json.loads(resolution_path.read_text())
    for constraint in resolution_payload["constraints"]:
        constraint.pop("review_shortlist_feature_ids", None)
        constraint.pop("review_scope_semantics", None)
        constraint.pop("out_of_scope_candidate_count", None)
    resolution_path.write_text(json.dumps(resolution_payload), encoding="utf-8")

    def canonical_sha(payload: dict[str, object]) -> str:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    project["terrain_route_guidance_feature_index_sha256"] = canonical_sha(
        feature_payload
    )
    project["terrain_route_guidance_resolution_sha256"] = canonical_sha(
        resolution_payload
    )
    project_path.write_text(json.dumps(project, sort_keys=True), encoding="utf-8")

    inspected = service.inspect(project_root, project_id="guidance_demo")

    assert inspected["feature_index"]["reference_paths"] == []
    assert inspected["feature_index_sha256"] == project["terrain_route_guidance_feature_index_sha256"]
    assert inspected["resolution_sha256"] == project["terrain_route_guidance_resolution_sha256"]
    assert inspected["resolution"]["constraints"][0][
        "review_scope_semantics"
    ] == "legacy_unscoped_candidates"


def test_candidate_corridor_hash_mismatch_fails_before_writing_resolution(
    tmp_path: Path,
) -> None:
    project_root = _workspace(tmp_path)
    _attach_candidate_corridor_reference(project_root)
    service = TerrainRouteGuidanceWorkspaceService(
        now_factory=lambda: datetime(2026, 9, 1, tzinfo=timezone.utc),
        elevation_sampler=_FakeElevationSampler(),
    )
    interpreted = service.interpret(
        project_root,
        project_id="guidance_demo",
        request=TerrainGuidanceInterpretRequest(
            narrative=NARRATIVE,
            source_id="iroko-d3",
        ),
    )
    raster_path = next(
        project_root.glob(
            "outputs/spatial/qgis/terrain-route-cache/*/terrain_route_top_5_percent_corridor.tif"
        )
    )
    raster_path.write_bytes(b"tampered-candidate-corridor-mask")

    with pytest.raises(ValueError, match="candidate corridor raster hash mismatch"):
        service.resolve(
            project_root,
            project_id="guidance_demo",
            request=TerrainGuidanceResolveRequest(
                guidance_id=interpreted["guidance_plan"]["guidance_id"],
                route_start=ROUTE_START,
                route_destination=ROUTE_DESTINATION,
                search_margin_m=200,
                reference_hypothesis_id="local-r1",
            ),
        )

    inspected = service.inspect(project_root, project_id="guidance_demo")
    assert inspected["status"] == "interpreted"
    assert inspected["feature_index"] is None
    assert inspected["resolution"] is None
    assert inspected["review"] is None


def test_dem_sampling_failure_writes_no_partial_resolution(tmp_path: Path) -> None:
    project_root = _workspace(tmp_path)
    service = TerrainRouteGuidanceWorkspaceService(
        now_factory=lambda: datetime(2026, 9, 1, tzinfo=timezone.utc),
        elevation_sampler=_FailingElevationSampler(),
    )
    interpreted = service.interpret(
        project_root,
        project_id="guidance_demo",
        request=TerrainGuidanceInterpretRequest(
            narrative=NARRATIVE,
            source_id="iroko-d3",
        ),
    )

    with pytest.raises(ValueError, match="synthetic DEM sampling failure"):
        service.resolve(
            project_root,
            project_id="guidance_demo",
            request=TerrainGuidanceResolveRequest(
                guidance_id=interpreted["guidance_plan"]["guidance_id"],
                route_start=ROUTE_START,
                route_destination=ROUTE_DESTINATION,
                search_margin_m=200,
            ),
        )

    inspected = service.inspect(project_root, project_id="guidance_demo")
    assert inspected["status"] == "interpreted"
    assert inspected["feature_index"] is None
    assert inspected["resolution"] is None
    assert inspected["review"] is None
    assert inspected["guided_execution_ready"] is False


def test_dem_nodata_is_typed_and_leaves_elevation_constraints_unresolved(
    tmp_path: Path,
) -> None:
    project_root = _workspace(tmp_path)
    service = TerrainRouteGuidanceWorkspaceService(
        now_factory=lambda: datetime(2026, 9, 1, tzinfo=timezone.utc),
        elevation_sampler=_NoDataElevationSampler(),
    )
    interpreted = service.interpret(
        project_root,
        project_id="guidance_demo",
        request=TerrainGuidanceInterpretRequest(
            narrative=NARRATIVE,
            source_id="iroko-d3",
        ),
    )

    resolved = service.resolve(
        project_root,
        project_id="guidance_demo",
        request=TerrainGuidanceResolveRequest(
            guidance_id=interpreted["guidance_plan"]["guidance_id"],
            route_start=ROUTE_START,
            route_destination=ROUTE_DESTINATION,
            search_margin_m=200,
        ),
    )

    index = resolved["feature_index"]
    assert index["elevation_sampling_status"] == "no_data"
    assert index["elevation_sampling_backend"] == _NoDataElevationSampler.backend_id
    assert index["elevation_sample_count"] > 0
    assert index["elevation_nodata_count"] == index["elevation_sample_count"]
    assert index["derived_saddle_count"] == 0
    assert not [item for item in index["features"] if item["landform"] == "saddle"]
    by_constraint = {
        item["constraint_id"]: item for item in resolved["resolution"]["constraints"]
    }
    assert by_constraint["G1"]["status"] == "unresolved"
    assert by_constraint["G6"]["status"] == "unresolved"
    assert resolved["guided_execution_ready"] is False


def test_workspace_lifecycle_persists_hash_bound_candidate_artifacts(
    tmp_path: Path,
) -> None:
    project_root = _workspace(tmp_path)
    service = _service()

    interpreted = service.interpret(
        project_root,
        project_id="guidance_demo",
        request=TerrainGuidanceInterpretRequest(
            narrative=NARRATIVE,
            source_id="iroko-d3",
            source_date="2017-01-01",
            requested_by="dashboard_operator",
        ),
    )

    assert interpreted["status"] == "interpreted"
    assert interpreted["candidate_only"] is True
    assert interpreted["runtime_safety_truth"] is False
    plan = interpreted["guidance_plan"]
    root_ref = interpreted["workspace_refs"]["root_ref"]
    assert (project_root / root_ref / "narrative.txt").read_text() == NARRATIVE
    assert _sha(project_root / interpreted["workspace_refs"]["narrative_ref"]) == (
        plan["narrative_sha256"]
    )

    required = [item for item in plan["constraints"] if item["required_anchor"]]
    manual_anchors = [
        TerrainGuidanceManualAnchorRequest(
            constraint_id=item["constraint_id"],
            point=GeoPoint(
                x=121.205 + index * 0.001,
                y=23.465 + index * 0.001,
                crs="EPSG:4326",
                label=f"confirmed {item['constraint_id']}",
            ),
        )
        for index, item in enumerate(required)
    ]
    resolved = service.resolve(
        project_root,
        project_id="guidance_demo",
        request=TerrainGuidanceResolveRequest(
            guidance_id=plan["guidance_id"],
            route_start=ROUTE_START,
            route_destination=ROUTE_DESTINATION,
            search_margin_m=200,
            manual_anchors=manual_anchors,
        ),
    )

    assert resolved["status"] in {"resolved", "partially_resolved"}
    assert resolved["feature_index"]["dem_sha256"] == _sha(
        project_root / "outputs/spatial/qgis/feature-run/dem_route_bbox.tif"
    )
    assert any(
        item["selection_source"] == "human_map_annotation"
        for item in resolved["feature_index"]["features"]
    )
    manual_by_constraint = {
        constraint_id: next(
            feature["feature_id"]
            for feature in resolved["feature_index"]["features"]
            if feature["selection_source"] == "human_map_annotation"
            and constraint_id in feature["supported_constraint_ids"]
        )
        for constraint_id in (item["constraint_id"] for item in required)
    }
    selected_ids = set(manual_by_constraint)
    disabled = [
        item["constraint_id"]
        for item in resolved["resolution"]["constraints"]
        if item["constraint_id"] not in selected_ids
        and item["status"] in {"unresolved", "multiple_candidates"}
    ]
    reviewed = service.review(
        project_root,
        project_id="guidance_demo",
        request=TerrainGuidanceReviewRequest(
            guidance_id=plan["guidance_id"],
            selected_feature_ids=manual_by_constraint,
            disabled_constraint_ids=disabled,
            reviewed_by="trip_leader",
        ),
    )

    assert reviewed["status"] == "reviewed"
    assert reviewed["guided_execution_ready"] is True
    assert reviewed["review"]["guided_hypothesis_id"] == "R4"
    decisions = reviewed["review"]["review_decisions"]
    selected_decisions = [item for item in decisions if item["human_selected_feature_id"]]
    assert selected_decisions
    assert all(item["ai_selected_feature_id"] is None for item in decisions)
    assert all(
        item["selected_feature_source"] == "human_map_annotation"
        and item["decision_kind"] == "human_map_anchor_confirmed"
        for item in selected_decisions
    )
    assert {
        item["constraint_id"]
        for item in decisions
        if item["decision_kind"] == "human_disabled_constraint"
    } == set(disabled)
    binding = build_guided_route_cache_binding(
        reviewed["review"],
        dem_sha256=resolved["feature_index"]["dem_sha256"],
    )
    assert binding["guided_hypothesis_id"] == "R4"
    assert binding["guidance_review_sha256"] == reviewed["review_sha256"]

    execution = load_reviewed_guidance_execution_plan(
        project_root,
        project_id="guidance_demo",
        guidance_id=plan["guidance_id"],
        review_sha256=reviewed["review_sha256"],
    )
    assert execution.guided_hypothesis_id == "R4"
    assert execution.guidance_review_sha256 == reviewed["review_sha256"]
    assert [item.model_dump(mode="json") for item in execution.review_decisions] == (
        reviewed["review"]["review_decisions"]
    )
    assert execution.dem_sha256 == resolved["feature_index"]["dem_sha256"]
    assert [item.constraint_id for item in execution.anchors] == [
        item["constraint_id"] for item in required
    ]
    assert all(
        item.selection_source == "human_map_annotation"
        and item.point.crs == "EPSG:4326"
        for item in execution.anchors
    )
    assert execution.cost_model_version == "reviewed_local_cost_preferences.v0_1"
    assert [item.constraint_id for item in execution.cost_modifiers] == [
        item.constraint_id for item in execution.anchors
    ]
    assert all(
        0 < item.minimum_friction_multiplier <= 1
        and 0 < item.influence_radius_m <= 500
        and item.semantics
        == "reviewed_constraint_local_cost_preference_not_route_truth"
        for item in execution.cost_modifiers
    )

    inspected = service.inspect(project_root, project_id="guidance_demo")
    assert inspected["narrative"] == NARRATIVE
    assert inspected["guidance_plan"]["source_id"] == "iroko-d3"
    assert inspected["guidance_plan"]["source_date"] == "2017-01-01"

    project = json.loads((project_root / "project.json").read_text())
    assert project["terrain_route_guidance_status"] == "reviewed"
    assert project["terrain_route_guidance_candidate_only"] is True
    assert project["terrain_route_guidance_runtime_safety_truth"] is False
    assert project["official_trail_ref"] == "official/trails.geojson"


def test_guided_execution_plan_rejects_stale_review_and_non_point_selection(
    tmp_path: Path,
) -> None:
    project_root = _workspace(tmp_path)
    service = _service()
    interpreted = service.interpret(
        project_root,
        project_id="guidance_demo",
        request=TerrainGuidanceInterpretRequest(
            narrative=NARRATIVE,
            source_id="iroko-d3",
        ),
    )
    plan = interpreted["guidance_plan"]
    required = [item for item in plan["constraints"] if item["required_anchor"]]
    resolved = service.resolve(
        project_root,
        project_id="guidance_demo",
        request=TerrainGuidanceResolveRequest(
            guidance_id=plan["guidance_id"],
            route_start=ROUTE_START,
            route_destination=ROUTE_DESTINATION,
            search_margin_m=200,
            manual_anchors=[
                TerrainGuidanceManualAnchorRequest(
                    constraint_id=item["constraint_id"],
                    point=GeoPoint(
                        x=121.205 + index * 0.001,
                        y=23.465 + index * 0.001,
                        crs="EPSG:4326",
                    ),
                )
                for index, item in enumerate(required)
            ],
        ),
    )
    selected = {
        item["supported_constraint_ids"][0]: item["feature_id"]
        for item in resolved["feature_index"]["features"]
        if item["selection_source"] == "human_map_annotation"
    }
    disabled = [
        item["constraint_id"]
        for item in resolved["resolution"]["constraints"]
        if item["constraint_id"] not in selected
        and item["status"] in {"unresolved", "multiple_candidates"}
    ]
    reviewed = service.review(
        project_root,
        project_id="guidance_demo",
        request=TerrainGuidanceReviewRequest(
            guidance_id=plan["guidance_id"],
            selected_feature_ids=selected,
            disabled_constraint_ids=disabled,
            reviewed_by="trip_leader",
        ),
    )

    with pytest.raises(ValueError, match="review hash"):
        load_reviewed_guidance_execution_plan(
            project_root,
            project_id="guidance_demo",
            guidance_id=plan["guidance_id"],
            review_sha256="0" * 64,
        )

    feature_index_path = project_root / resolved["workspace_refs"]["feature_index_ref"]
    feature_index = json.loads(feature_index_path.read_text(encoding="utf-8"))
    selected_feature_id = next(iter(selected.values()))
    selected_feature = next(
        item
        for item in feature_index["features"]
        if item["feature_id"] == selected_feature_id
    )
    selected_feature["selection_source"] = "dem_derived"
    selected_feature["geometry"] = {
        "type": "LineString",
        "coordinates": [[121.205, 23.465], [121.206, 23.466]],
    }
    feature_index_path.write_text(
        json.dumps(feature_index, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    project = json.loads((project_root / "project.json").read_text())
    from terrain_route_guidance import TerrainGuidanceFeatureIndex

    project["terrain_route_guidance_feature_index_sha256"] = hashlib.sha256(
        json.dumps(
            TerrainGuidanceFeatureIndex.model_validate(feature_index).model_dump(
                mode="json"
            ),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    (project_root / "project.json").write_text(json.dumps(project))

    with pytest.raises(
        ValueError,
        match="review chain|explicit human map point",
    ):
        load_reviewed_guidance_execution_plan(
            project_root,
            project_id="guidance_demo",
            guidance_id=plan["guidance_id"],
            review_sha256=reviewed["review_sha256"],
        )


def test_resolve_invalidates_a_previous_human_review(tmp_path: Path) -> None:
    project_root = _workspace(tmp_path)
    service = _service()
    interpreted = service.interpret(
        project_root,
        project_id="guidance_demo",
        request=TerrainGuidanceInterpretRequest(
            narrative=NARRATIVE,
            source_id="iroko-d3",
        ),
    )
    plan = interpreted["guidance_plan"]
    required = [item for item in plan["constraints"] if item["required_anchor"]]
    resolved = service.resolve(
        project_root,
        project_id="guidance_demo",
        request=TerrainGuidanceResolveRequest(
            guidance_id=plan["guidance_id"],
            route_start=ROUTE_START,
            route_destination=ROUTE_DESTINATION,
            search_margin_m=200,
            manual_anchors=[
                TerrainGuidanceManualAnchorRequest(
                    constraint_id=item["constraint_id"],
                    point=GeoPoint(
                        x=121.205 + index * 0.001,
                        y=23.465 + index * 0.001,
                        crs="EPSG:4326",
                    ),
                )
                for index, item in enumerate(required)
            ],
        ),
    )
    selected = {
        item["supported_constraint_ids"][0]: item["feature_id"]
        for item in resolved["feature_index"]["features"]
        if item["selection_source"] == "human_map_annotation"
    }
    disabled = [
        item["constraint_id"]
        for item in resolved["resolution"]["constraints"]
        if item["constraint_id"] not in selected
        and item["status"] in {"unresolved", "multiple_candidates"}
    ]
    reviewed = service.review(
        project_root,
        project_id="guidance_demo",
        request=TerrainGuidanceReviewRequest(
            guidance_id=plan["guidance_id"],
            selected_feature_ids=selected,
            disabled_constraint_ids=disabled,
            reviewed_by="trip_leader",
        ),
    )
    assert reviewed["guided_execution_ready"] is True

    rerun = service.resolve(
        project_root,
        project_id="guidance_demo",
        request=TerrainGuidanceResolveRequest(
            guidance_id=plan["guidance_id"],
            route_start=ROUTE_START,
            route_destination=ROUTE_DESTINATION,
            search_margin_m=300,
        ),
    )

    assert rerun["review"] is None
    assert rerun["review_sha256"] is None
    assert rerun["guided_execution_ready"] is False
    inspected = service.inspect(project_root, project_id="guidance_demo")
    assert inspected["review"] is None
    assert inspected["review_sha256"] is None
    assert inspected["guided_execution_ready"] is False
    project = json.loads((project_root / "project.json").read_text())
    assert project["terrain_route_guidance_review_ref"] is None
    assert project["terrain_route_guidance_review_sha256"] is None
    assert project["terrain_route_guidance_guided_execution_ready"] is False


def test_workspace_resolver_fails_closed_when_parent_dem_hash_changes(
    tmp_path: Path,
) -> None:
    project_root = _workspace(tmp_path)
    service = _service()
    interpreted = service.interpret(
        project_root,
        project_id="guidance_demo",
        request=TerrainGuidanceInterpretRequest(
            narrative=NARRATIVE,
            source_id="iroko-d3",
        ),
    )
    dem_path = project_root / "outputs/spatial/qgis/feature-run/dem_route_bbox.tif"
    dem_path.write_bytes(b"changed-dem")
    project = json.loads((project_root / "project.json").read_text())
    project["terrain_route_guidance_dem_sha256"] = "0" * 64
    (project_root / "project.json").write_text(json.dumps(project))

    with pytest.raises(ValueError, match="DEM hash"):
        service.resolve(
            project_root,
            project_id="guidance_demo",
            request=TerrainGuidanceResolveRequest(
                guidance_id=interpreted["guidance_plan"]["guidance_id"],
                route_start=ROUTE_START,
                route_destination=ROUTE_DESTINATION,
                search_margin_m=200,
            ),
        )


def test_admin_api_exposes_interpret_resolve_review_and_status(tmp_path: Path) -> None:
    project_root = _workspace(tmp_path)
    del project_root
    client = TestClient(
        create_admin_app(
            pretrip_workspace_root=tmp_path,
            runtime_audit_root=tmp_path.parent / f"{tmp_path.name}-audit",
            terrain_guidance_elevation_sampler=None,
        )
    )
    base = "/admin/pretrip/projects/guidance_demo/terrain-route-guidance"

    interpreted = client.post(
        f"{base}/interpret",
        json={
            "narrative": NARRATIVE,
            "source_id": "iroko-d3",
            "source_date": "2017-01-01",
            "requested_by": "dashboard_operator",
        },
    )
    assert interpreted.status_code == 201, interpreted.text
    plan = interpreted.json()["guidance_plan"]
    status = client.get(base)
    assert status.status_code == 200
    assert status.json()["guidance_plan"]["guidance_id"] == plan["guidance_id"]
    assert status.json()["narrative"] == NARRATIVE

    required = [item for item in plan["constraints"] if item["required_anchor"]]
    resolved = client.post(
        f"{base}/resolve",
        json={
            "guidance_id": plan["guidance_id"],
            "route_start": ROUTE_START.model_dump(mode="json"),
            "route_destination": ROUTE_DESTINATION.model_dump(mode="json"),
            "search_margin_m": 200,
            "manual_anchors": [
                {
                    "constraint_id": item["constraint_id"],
                    "point": {
                        "x": 121.205 + index * 0.001,
                        "y": 23.465 + index * 0.001,
                        "crs": "EPSG:4326",
                        "label": item["constraint_id"],
                    },
                }
                for index, item in enumerate(required)
            ],
        },
    )
    assert resolved.status_code == 200, resolved.text
    payload = resolved.json()
    selected = {
        item["supported_constraint_ids"][0]: item["feature_id"]
        for item in payload["feature_index"]["features"]
        if item["selection_source"] == "human_map_annotation"
    }
    disabled = [
        item["constraint_id"]
        for item in payload["resolution"]["constraints"]
        if item["constraint_id"] not in selected
        and item["status"] in {"unresolved", "multiple_candidates"}
    ]
    reviewed = client.post(
        f"{base}/review",
        json={
            "guidance_id": plan["guidance_id"],
            "selected_feature_ids": selected,
            "disabled_constraint_ids": disabled,
            "reviewed_by": "trip_leader",
        },
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["guided_execution_ready"] is True
    assert reviewed.headers["x-scout-candidate-only"] == "true"


def test_resolver_requires_distinct_wgs84_route_window_and_clips_candidates(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="route_start and route_destination"):
        TerrainGuidanceResolveRequest(
            guidance_id="terrain-guidance-test",
            route_start=ROUTE_START,
        )
    with pytest.raises(ValueError, match="EPSG:4326"):
        TerrainGuidanceResolveRequest(
            guidance_id="terrain-guidance-test",
            route_start=GeoPoint(x=273559, y=2583344, crs="EPSG:3826"),
            route_destination=ROUTE_DESTINATION,
        )
    with pytest.raises(ValueError, match="must differ"):
        TerrainGuidanceResolveRequest(
            guidance_id="terrain-guidance-test",
            route_start=ROUTE_START,
            route_destination=ROUTE_START,
        )

    project_root = _workspace(tmp_path)
    project = json.loads((project_root / "project.json").read_text(encoding="utf-8"))
    ridge_path = project_root / project["qgis_ridge_lines_vector_ref"]
    ridge = json.loads(ridge_path.read_text(encoding="utf-8"))
    ridge["features"][0]["geometry"] = {
        "type": "MultiLineString",
        "coordinates": [
            [[121.203, 23.463], [121.207, 23.467], [121.212, 23.472]],
            [[121.300, 23.550], [121.310, 23.560]],
        ],
    }
    ridge_path.write_text(json.dumps(ridge), encoding="utf-8")

    service = _service()
    interpreted = service.interpret(
        project_root,
        project_id="guidance_demo",
        request=TerrainGuidanceInterpretRequest(
            narrative=NARRATIVE,
            source_id="iroko-d3",
        ),
    )
    resolved = service.resolve(
        project_root,
        project_id="guidance_demo",
        request=TerrainGuidanceResolveRequest(
            guidance_id=interpreted["guidance_plan"]["guidance_id"],
            route_start=ROUTE_START,
            route_destination=ROUTE_DESTINATION,
            search_margin_m=200,
        ),
    )

    index = resolved["feature_index"]
    window = index["search_window"]
    assert index["algorithm_version"] == (
        "qgis_feature_vectors_route_window_plus_human_map_annotations.v0_2"
    )
    assert window["route_start"] == ROUTE_START.model_dump(mode="json")
    assert window["route_destination"] == ROUTE_DESTINATION.model_dump(mode="json")
    assert window["margin_m"] == 200
    dem_features = [
        item for item in index["features"] if item["selection_source"] == "dem_derived"
    ]
    assert dem_features
    assert all(item["geometry"]["type"] == "LineString" for item in dem_features)
    for feature in dem_features:
        for x, y in feature["geometry"]["coordinates"]:
            assert window["west"] <= x <= window["east"]
            assert window["south"] <= y <= window["north"]
            assert x < 121.25

    with pytest.raises(ValueError, match="inside the A/B search window"):
        service.resolve(
            project_root,
            project_id="guidance_demo",
            request=TerrainGuidanceResolveRequest(
                guidance_id=interpreted["guidance_plan"]["guidance_id"],
                route_start=ROUTE_START,
                route_destination=ROUTE_DESTINATION,
                search_margin_m=200,
                manual_anchors=[
                    TerrainGuidanceManualAnchorRequest(
                        constraint_id="G1",
                        point=GeoPoint(x=121.3, y=23.55, crs="EPSG:4326"),
                    )
                ],
            ),
        )


def test_resolver_fails_closed_when_local_candidate_budget_is_exceeded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _workspace(tmp_path)
    service = _service()
    interpreted = service.interpret(
        project_root,
        project_id="guidance_demo",
        request=TerrainGuidanceInterpretRequest(
            narrative=NARRATIVE,
            source_id="iroko-d3",
        ),
    )
    monkeypatch.setattr(guidance_workspace, "MAX_GUIDANCE_LOCAL_FEATURES", 1)

    with pytest.raises(ValueError, match="local candidate budget exceeded"):
        service.resolve(
            project_root,
            project_id="guidance_demo",
            request=TerrainGuidanceResolveRequest(
                guidance_id=interpreted["guidance_plan"]["guidance_id"],
                route_start=ROUTE_START,
                route_destination=ROUTE_DESTINATION,
                search_margin_m=200,
            ),
        )


def _canonical_sha(payload: dict) -> str:
    return hashlib.sha256(json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()


def _replace_guidance_artifact(root: Path, name: str, payload: dict) -> None:
    project_path = root / "project.json"
    project = json.loads(project_path.read_text())
    (root / project[f"terrain_route_guidance_{name}_ref"]).write_text(
        json.dumps(payload), encoding="utf-8",
    )
    project[f"terrain_route_guidance_{name}_sha256"] = _canonical_sha(payload)
    project_path.write_text(json.dumps(project), encoding="utf-8")


def _replace_map_review_index(root: Path, index: dict) -> None:
    _replace_guidance_artifact(root, "feature_index", index)
    project = json.loads((root / "project.json").read_text())
    resolution = json.loads((root / project["terrain_route_guidance_resolution_ref"]).read_text())
    resolution["feature_index_sha256"] = _canonical_sha(index)
    _replace_guidance_artifact(root, "resolution", resolution)


def _different_map_review_context(root: Path) -> dict:
    index = _service().inspect(root, project_id="guidance_demo")["feature_index"]
    index["search_window"]["route_start"]["x"] += 0.0045
    _replace_map_review_index(root, index)
    return index["search_window"]


def _map_review_workspace(tmp_path: Path, *, manual: bool = False) -> Path:
    root = _workspace(tmp_path)
    _attach_r1_r3_path_references(root)
    service = TerrainRouteGuidanceWorkspaceService(elevation_sampler=_FakeElevationSampler())
    interpreted = service.interpret(
        root, project_id="guidance_demo",
        request=TerrainGuidanceInterpretRequest(narrative=NARRATIVE, source_id="iroko-d3"),
    )
    saved = service.resolve(
        root, project_id="guidance_demo",
        request=TerrainGuidanceResolveRequest(
            guidance_id=interpreted["guidance_plan"]["guidance_id"],
            route_start=ROUTE_START, route_destination=ROUTE_DESTINATION,
            search_margin_m=200,
        ),
    )
    project = json.loads((root / "project.json").read_text())
    assert saved["feature_index_sha256"] == project["terrain_route_guidance_feature_index_sha256"]
    assert saved["resolution_sha256"] == project["terrain_route_guidance_resolution_sha256"]
    index = saved["feature_index"]
    ridge = next(item for item in index["features"] if item["landform"] == "ridge")
    points = [
        (121.2085, 23.4685), (121.206, 23.466), (121.209, 23.466),
        (121.210, 23.465), (121.208, 23.469),
    ]
    index["features"] = [
        {
            **ridge, "feature_id": f"ridge-{rank}", "elevation_m": 820,
            "centroid": {"x": x, "y": y, "crs": "EPSG:4326"},
            "geometry": {
                "type": "LineString",
                "coordinates": [[x - 0.0001, y], [x + 0.0001, y]],
            },
        }
        for rank, (x, y) in enumerate(points, start=1)
    ]
    # The first line intersects the mask, but its unchanged marker does not.
    index["features"][0]["geometry"]["coordinates"] = [
        [121.207, 23.467], [121.210, 23.470],
    ]
    for feature_id, x, y in (
        ("saddle-on", 121.207, 23.467), ("saddle-off", 121.2105, 23.4645),
    ):
        index["features"].append({
            **ridge, "feature_id": feature_id, "landform": "saddle", "elevation_m": 1148,
            "centroid": {"x": x, "y": y, "crs": "EPSG:4326"},
            "geometry": {"type": "Point", "coordinates": [x, y]},
        })
    if manual:
        index["features"].append({
            **ridge, "feature_id": "manual-anchor", "selection_source": "human_map_annotation",
            "supported_constraint_ids": ["G6"],
            "centroid": {"x": 121.2072, "y": 23.4672, "crs": "EPSG:4326"},
            "geometry": {"type": "Point", "coordinates": [121.2072, 23.4672]},
        })
    for key in ("reference_corridor", "reference_corridors", "reference_paths"):
        index.pop(key, None)
    for feature in index["features"]:
        for key in tuple(feature):
            if key.startswith("reference_"):
                feature.pop(key)
    plan = guidance_workspace.TerrainNarrativeGuidancePlan.model_validate(saved["guidance_plan"])
    resolution = guidance_workspace.resolve_terrain_route_guidance(
        plan, guidance_workspace.TerrainGuidanceFeatureIndex.model_validate(index),
    ).model_dump(mode="json")
    g6 = next(item for item in resolution["constraints"] if item["constraint_id"] == "G6")
    g6["candidate_feature_ids"] = [f"ridge-{rank}" for rank in range(1, 6)]
    if manual:
        g6["candidate_feature_ids"].append("manual-anchor")
    for constraint in resolution["constraints"]:
        for key in ("review_shortlist_feature_ids", "review_scope_semantics", "out_of_scope_candidate_count"):
            constraint.pop(key, None)
    resolution["feature_index_sha256"] = _canonical_sha(index)
    _replace_guidance_artifact(root, "feature_index", index)
    _replace_guidance_artifact(root, "resolution", resolution)
    if manual:
        service.review(
            root, project_id="guidance_demo",
            request=TerrainGuidanceReviewRequest(
                guidance_id=plan.guidance_id, selected_feature_ids={"G6": "manual-anchor"},
                disabled_constraint_ids=[
                    item.constraint_id for item in plan.constraints
                    if item.required_anchor and item.constraint_id != "G6"
                ],
            ),
        )
    return root


class _MapReviewSampler:
    backend_id = "fixture_marker_mask.v0_1"

    def __init__(self, samples: dict | None = None, default: float | None = 255.0):
        self.samples = samples if samples is not None else {
            (121.206, 23.466): 1.0, (121.208, 23.469): 1.0,
            (121.207, 23.467): 1.0, (121.2105, 23.4645): 1.0,
        }
        self.default = default
        self.calls: list[tuple[Path, tuple[tuple[float, float], ...]]] = []

    def sample(self, raster_path: Path, points_wgs84: tuple) -> tuple:
        self.calls.append((raster_path, points_wgs84))
        if raster_path.name == "terrain_route_top_10_percent_corridor.tif":
            return tuple(1.0 for _point in points_wgs84)
        return tuple(self.samples.get(point, self.default) for point in points_wgs84)


def _file_snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*") if path.is_file()
    }


def _map_scope(root: Path, sampler, **kwargs) -> dict:
    return TerrainRouteGuidanceWorkspaceService(elevation_sampler=sampler).map_review_scope(
        root, project_id="guidance_demo", reference_hypothesis_id="active-cccccccccccc",
        corridor_band_name=kwargs.pop("corridor_band_name", "top_5_percent_corridor"),
        **kwargs,
    )


def _scope_constraint(scope: dict, constraint_id: str) -> dict:
    return next(item for item in scope["constraints"] if item["constraint_id"] == constraint_id)


def _candidate_run(root: Path) -> dict:
    project = json.loads((root / "project.json").read_text())
    return json.loads((root / project["terrain_route_hypothesis_ref"]).read_text())


def _replace_candidate_run(root: Path, run: dict) -> None:
    project_path = root / "project.json"
    project = json.loads(project_path.read_text())
    run_path = root / project["terrain_route_hypothesis_ref"]
    run_path.write_text(json.dumps(run), encoding="utf-8")
    catalog_path = root / project["terrain_route_hypothesis_catalog_ref"]
    catalog = json.loads(catalog_path.read_text())
    catalog["entries"][0]["hypothesis_sha256"] = _sha(run_path)
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    project["terrain_route_hypothesis_catalog_sha256"] = _sha(catalog_path)
    project["terrain_route_hypothesis_sha256"] = _sha(run_path)
    project_path.write_text(json.dumps(project), encoding="utf-8")


def test_map_review_scope_uses_legacy_marker_centroids_and_original_ranks(tmp_path: Path) -> None:
    root = _map_review_workspace(tmp_path)
    before = _file_snapshot(root)
    sampler = _MapReviewSampler()
    inspected = _service().inspect(root, project_id="guidance_demo")
    assert inspected["feature_index"]["reference_paths"] == []
    assert inspected["feature_index"]["reference_corridors"] == []
    scope = _map_scope(
        root, sampler, expected_feature_index_sha256=inspected["feature_index_sha256"],
        expected_resolution_sha256=inspected["resolution_sha256"],
    )
    assert TerrainGuidanceMapReviewScope.model_validate(scope).model_dump(mode="json") == scope
    assert scope["status"] == "ready"
    assert scope["endpoint_alignment"] == "same_ab"
    assert scope["start_difference_m"] == scope["destination_difference_m"] == 0
    assert scope["execution_eligible"] is False
    assert scope["routing_effect"] == "none"
    assert scope["source_feature_index_sha256"] == inspected["feature_index_sha256"]
    assert scope["source_resolution_sha256"] == inspected["resolution_sha256"]
    g6 = _scope_constraint(scope, "G6")
    assert [(item["feature_id"], item["rank"]) for item in g6["candidates"]] == [
        ("ridge-2", 2), ("ridge-5", 5),
    ]
    assert (g6["total_candidate_count"], g6["visible_candidate_count"], g6["excluded_candidate_count"]) == (5, 2, 3)
    assert g6["status"] == "candidates"
    assert g6["candidates"][1]["minimum_path_distance_m"] > scope["saddle_path_tolerance_m"]
    assert len(sampler.calls) == 1
    assert sampler.calls[0][0] == root / scope["corridor_reference"]["raster_ref"]
    assert sampler.calls[0][1] == tuple(
        (item["centroid"]["x"], item["centroid"]["y"])
        for item in inspected["feature_index"]["features"]
    )
    assert (121.210, 23.470) not in sampler.calls[0][1]
    assert scope["candidate_only"] is True
    assert scope["runtime_safety_truth"] is False
    assert scope["operational"] is False
    assert _map_scope(root, sampler) == scope
    assert _file_snapshot(root) == before


def test_map_review_saddle_requires_one_dem_diagonal_to_a_path(tmp_path: Path) -> None:
    root = _map_review_workspace(tmp_path)
    scope = _map_scope(root, _MapReviewSampler())
    saddle = _scope_constraint(scope, "G1")
    assert scope["saddle_path_tolerance_m"] == 20 * math.sqrt(2)
    assert [item["feature_id"] for item in saddle["candidates"]] == ["saddle-on"]
    assert saddle["candidates"][0]["minimum_path_distance_m"] == pytest.approx(0)
    assert saddle["excluded_candidate_count"] == 1
    assert [item["display_id"] for item in scope["reference_paths"]] == ["R1", "R2", "R3"]


@pytest.mark.parametrize("value", [None, 0.0, 255.0, float("nan"), float("inf")])
def test_map_review_nodata_or_outside_never_passes(tmp_path: Path, value: float | None) -> None:
    root = _map_review_workspace(tmp_path)
    before = _file_snapshot(root)
    scope = _map_scope(root, _MapReviewSampler({}, default=value))
    assert all(item["status"] == "unknown" and not item["candidates"] for item in scope["constraints"])
    assert all(item["excluded_candidate_count"] == item["total_candidate_count"] for item in scope["constraints"])
    assert _file_snapshot(root) == before


@pytest.mark.parametrize("value", [2.0, 1.0000001, -1.0, True, "1"])
def test_map_review_unexpected_mask_values_fail_closed(tmp_path: Path, value) -> None:
    root = _map_review_workspace(tmp_path)
    before = _file_snapshot(root)
    with pytest.raises(ValueError, match="unexpected value|invalid data"):
        _map_scope(root, _MapReviewSampler({}, default=value))
    assert _file_snapshot(root) == before


@pytest.mark.parametrize("key", ["feature_index", "resolution"])
def test_map_review_rejects_stale_expected_hash_before_sampling(tmp_path: Path, key: str) -> None:
    root = _map_review_workspace(tmp_path)
    before = _file_snapshot(root)
    sampler = _MapReviewSampler()
    with pytest.raises(ValueError, match="expected .* hash is stale"):
        _map_scope(root, sampler, **{f"expected_{key}_sha256": "0" * 64})
    assert sampler.calls == []
    assert _file_snapshot(root) == before


def test_map_review_unavailable_and_incomplete_sampler_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _map_review_workspace(tmp_path)
    before = _file_snapshot(root)
    with pytest.raises(ValueError, match="sampling is unavailable"):
        _map_scope(root, None)
    sampler = _MapReviewSampler()
    monkeypatch.setattr(sampler, "sample", lambda _raster, _points: (1.0,))
    with pytest.raises(ValueError, match="incomplete result"):
        _map_scope(root, sampler)
    assert _file_snapshot(root) == before


def test_map_review_omits_manual_annotations_and_preserves_review(tmp_path: Path) -> None:
    root = _map_review_workspace(tmp_path, manual=True)
    before = _file_snapshot(root)
    sampler = _MapReviewSampler()
    scope = _map_scope(root, sampler)
    g6 = _scope_constraint(scope, "G6")
    assert [(item["feature_id"], item["rank"]) for item in g6["candidates"]] == [("ridge-2", 2), ("ridge-5", 5)]
    assert g6["total_candidate_count"] == 6
    assert (121.2072, 23.4672) not in sampler.calls[0][1]
    assert _file_snapshot(root) == before
    review = _service().inspect(root, project_id="guidance_demo")["review"]
    assert review["selected_anchors"][0]["feature_id"] == "manual-anchor"


def test_map_review_uses_the_selected_source_band(tmp_path: Path) -> None:
    root = _map_review_workspace(tmp_path)
    run = _candidate_run(root)
    band = run["hypotheses"][0]["corridor"]["bands"][0]
    raster_ref = band["raster_ref"]["artifact_ref"].replace("top_5_", "top_10_")
    (root / raster_ref).write_bytes(b"synthetic-ten-percent-corridor")
    run["hypotheses"][0]["corridor"]["bands"].append({
        **band, "name": "top_10_percent_corridor", "percentile": 10,
        "raster_ref": {**band["raster_ref"], "artifact_ref": raster_ref, "sha256": _sha(root / raster_ref)},
    })
    _replace_candidate_run(root, run)
    before = _file_snapshot(root)
    sampler = _MapReviewSampler()
    narrow = _map_scope(root, sampler)
    wide = _map_scope(root, sampler, corridor_band_name="top_10_percent_corridor")
    assert narrow["scope_id"] != wide["scope_id"]
    assert _scope_constraint(narrow, "G6")["visible_candidate_count"] == 2
    assert _scope_constraint(wide, "G6")["visible_candidate_count"] == 5
    assert wide["corridor_reference"]["raster_ref"] == raster_ref
    assert sampler.calls[-1][0] == root / raster_ref
    assert _file_snapshot(root) == before


@pytest.mark.parametrize("source", ["plan", "feature_index", "resolution", "dem", "manifest", "run", "raster", "catalog"])
def test_map_review_rejects_stale_source_artifacts(tmp_path: Path, source: str) -> None:
    root = _map_review_workspace(tmp_path)
    project = json.loads((root / "project.json").read_text())
    refs = {
        **{key: project[f"terrain_route_guidance_{key}_ref"] for key in ("plan", "feature_index", "resolution")},
        "dem": project["terrain_dem_route_bbox_raster_ref"],
        "manifest": project["terrain_feature_manifest_ref"],
        "run": project["terrain_route_hypothesis_ref"],
        "catalog": project["terrain_route_hypothesis_catalog_ref"],
        "raster": _candidate_run(root)["hypotheses"][0]["corridor"]["bands"][0]["raster_ref"]["artifact_ref"],
    }
    target = root / refs[source]
    if target.suffix == ".json":
        target.write_text(json.dumps({**json.loads(target.read_text()), "changed": True}), encoding="utf-8")
    else:
        target.write_bytes(b"changed-evidence")
    before = _file_snapshot(root)
    sampler = _MapReviewSampler()
    with pytest.raises(ValueError, match="hash|binding"):
        _map_scope(root, sampler)
    assert sampler.calls == []
    assert _file_snapshot(root) == before


@pytest.mark.parametrize("change", ["ab", "cache", "dem", "parent", "crs", "path_crs", "resolution"])
def test_map_review_validates_selected_run_binding(tmp_path: Path, change: str) -> None:
    root = _map_review_workspace(tmp_path)
    run = _candidate_run(root)
    hypothesis = run["hypotheses"][0 if change == "ab" else 1]
    if change == "ab":
        hypothesis["start"]["x"] += 0.01
    elif change == "cache":
        hypothesis["provenance"]["cache_key"] = "0" * 64
    elif change == "dem":
        hypothesis["provenance"]["dem_sha256"] = "0" * 64
    elif change == "parent":
        hypothesis["provenance"]["processing_manifest"]["parent_source_hashes"] = {"unbound": "0" * 64}
    elif change == "crs":
        hypothesis["provenance"]["dem_crs"] = "EPSG:4326"
    elif change == "path_crs":
        hypothesis["best_path"]["crs"] = "EPSG:3826"
    else:
        hypothesis["provenance"]["dem_resolution_m"] = 30
    _replace_candidate_run(root, run)
    before = _file_snapshot(root)
    sampler = _MapReviewSampler()
    with pytest.raises(ValueError, match="A/B|cache|DEM|CRS|EPSG:4326"):
        _map_scope(root, sampler)
    assert sampler.calls == []
    assert _file_snapshot(root) == before


def test_map_review_preserves_full_path_vertices_for_saddle_distance(tmp_path: Path) -> None:
    root = _map_review_workspace(tmp_path)
    run = _candidate_run(root)
    points = [
        (
            ROUTE_START.x + (ROUTE_DESTINATION.x - ROUTE_START.x) * index / 1000,
            ROUTE_START.y + (ROUTE_DESTINATION.y - ROUTE_START.y) * index / 1000
            + (0.005 if 0 < index < 1000 else 0),
        )
        for index in range(1001)
    ]
    sampled_indexes = {round(index * 1000 / 799) for index in range(800)}
    omitted = next(index for index in range(450, 550) if index not in sampled_indexes)
    points[omitted] = (121.207, 23.467)
    assert guidance_workspace._wgs84_point_to_path_distance_m(
        points[omitted], guidance_workspace._bounded_reference_path_points(points),
    ) > 20 * math.sqrt(2)
    run["hypotheses"] = [run["hypotheses"][0]]
    run["hypotheses"][0]["best_path"]["coordinates"] = points
    _replace_candidate_run(root, run)
    before = _file_snapshot(root)
    scope = _map_scope(root, _MapReviewSampler())
    assert _scope_constraint(scope, "G1")["candidates"][0]["feature_id"] == "saddle-on"
    assert _scope_constraint(scope, "G1")["candidates"][0]["minimum_path_distance_m"] == pytest.approx(0)
    assert scope["reference_paths"][0]["path_point_count"] == 1001
    assert _file_snapshot(root) == before


@pytest.mark.parametrize("offset_m, visible", [(-0.001, True), (0.001, False)])
def test_map_review_saddle_cell_diagonal_boundary(tmp_path: Path, offset_m: float, visible: bool) -> None:
    root = _map_review_workspace(tmp_path)
    run = _candidate_run(root)
    run["hypotheses"] = [run["hypotheses"][0]]
    run["hypotheses"][0]["best_path"]["coordinates"] = [
        [ROUTE_START.x, ROUTE_START.y], [121.206, 23.467], [121.208, 23.467],
        [ROUTE_DESTINATION.x, ROUTE_DESTINATION.y],
    ]
    _replace_candidate_run(root, run)
    state = _service().inspect(root, project_id="guidance_demo")
    index = state["feature_index"]
    saddle = next(item for item in index["features"] if item["feature_id"] == "saddle-on")
    latitude = 23.467 + (20 * math.sqrt(2) + offset_m) / 111320
    saddle["centroid"]["y"] = latitude
    saddle["geometry"]["coordinates"][1] = latitude
    _replace_map_review_index(root, index)
    before = _file_snapshot(root)
    scope = _map_scope(root, _MapReviewSampler({}, default=1.0))
    ids = [item["feature_id"] for item in _scope_constraint(scope, "G1")["candidates"]]
    assert ("saddle-on" in ids) is visible
    assert _file_snapshot(root) == before


def test_map_review_outside_raster_extent_is_not_sampled(tmp_path: Path) -> None:
    root = _map_review_workspace(tmp_path)
    run = _candidate_run(root)
    run["hypotheses"][0]["corridor"]["bands"][0]["raster_ref"]["bbox_wgs84"] = {
        "west": 122, "east": 123, "south": 24, "north": 25,
    }
    _replace_candidate_run(root, run)
    sampler = _MapReviewSampler({}, default=1.0)
    scope = _map_scope(root, sampler)
    assert sampler.calls == []
    assert scope["corridor_reference"]["sampled_marker_count"] == 0
    assert all(item["status"] == "unknown" for item in scope["constraints"])


def test_map_review_retains_not_routing_applicable_status(tmp_path: Path) -> None:
    root = _map_review_workspace(tmp_path)
    state = _service().inspect(root, project_id="guidance_demo")
    plan = state["guidance_plan"]
    plan["constraints"][2].update(routing_applicable=False, routing_effect="context_only")
    _replace_guidance_artifact(root, "plan", plan)
    resolution = state["resolution"]
    resolution["plan_sha256"] = _canonical_sha(plan)
    resolution["constraints"][2].update(status="not_routing_applicable", candidate_feature_ids=[])
    _replace_guidance_artifact(root, "resolution", resolution)
    before = _file_snapshot(root)
    scope = _map_scope(root, _MapReviewSampler())
    assert _scope_constraint(scope, "G3") == {
        "constraint_id": "G3", "total_candidate_count": 0, "visible_candidate_count": 0,
        "excluded_candidate_count": 0, "status": "not_routing_applicable", "candidates": [],
    }
    assert _file_snapshot(root) == before


@pytest.mark.parametrize("change", ["index_chain", "plan_chain", "search_window"])
def test_map_review_rejects_rebound_but_inconsistent_sources(tmp_path: Path, change: str) -> None:
    root = _map_review_workspace(tmp_path)
    state = _service().inspect(root, project_id="guidance_demo")
    if change == "search_window":
        index = state["feature_index"]
        index["search_window"] = None
        _replace_map_review_index(root, index)
    else:
        resolution = state["resolution"]
        resolution["feature_index_sha256" if change == "index_chain" else "plan_sha256"] = "0" * 64
        _replace_guidance_artifact(root, "resolution", resolution)
    before = _file_snapshot(root)
    sampler = _MapReviewSampler()
    with pytest.raises(ValueError, match="hash chain|search window"):
        _map_scope(root, sampler)
    assert sampler.calls == []
    assert _file_snapshot(root) == before


@pytest.mark.parametrize("change", ["feature_index", "raster"])
def test_map_review_detects_concurrent_source_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str) -> None:
    root = _map_review_workspace(tmp_path)
    sampler = _MapReviewSampler()
    original_sample = sampler.sample
    changed_files: dict[str, bytes] = {}

    def sample(raster_path, points):
        values = original_sample(raster_path, points)
        if change == "feature_index":
            index = _service().inspect(root, project_id="guidance_demo")["feature_index"]
            index["algorithm_version"] += ".concurrent"
            _replace_map_review_index(root, index)
        else:
            raster_path.write_bytes(b"concurrent-raster-replacement")
        changed_files.update(_file_snapshot(root))
        return values

    monkeypatch.setattr(sampler, "sample", sample)
    with pytest.raises(ValueError, match="changed while sampling"):
        _map_scope(root, sampler)
    assert _file_snapshot(root) == changed_files


def test_map_review_different_context_preserves_ranks_without_relaxing_resolve(tmp_path: Path) -> None:
    root = _map_review_workspace(tmp_path)
    source_window = _different_map_review_context(root)
    before = _file_snapshot(root)
    scope = _map_scope(root, _MapReviewSampler())
    assert scope["endpoint_alignment"] == "different_review_context"
    assert scope["source_route_start"] == source_window["route_start"]
    assert scope["source_route_destination"] == source_window["route_destination"]
    assert scope["scope_route_start"] == ROUTE_START.model_dump(mode="json")
    assert scope["scope_route_destination"] == ROUTE_DESTINATION.model_dump(mode="json")
    assert scope["start_difference_m"] > 400
    assert scope["destination_difference_m"] == 0
    assert scope["execution_eligible"] is False
    assert scope["routing_effect"] == "none"
    assert [item["rank"] for item in _scope_constraint(scope, "G6")["candidates"]] == [2, 5]
    with pytest.raises(ValueError, match="endpoints do not match the guidance A/B"):
        TerrainRouteGuidanceWorkspaceService(elevation_sampler=_FakeElevationSampler()).resolve(
            root, project_id="guidance_demo",
            request=TerrainGuidanceResolveRequest(
                guidance_id=scope["guidance_id"],
                route_start=GeoPoint.model_validate(source_window["route_start"]),
                route_destination=GeoPoint.model_validate(source_window["route_destination"]),
                search_margin_m=source_window["margin_m"],
                reference_hypothesis_id="active-cccccccccccc",
            ),
        )
    assert _file_snapshot(root) == before


@pytest.mark.parametrize("with_hashes, different_context", [(False, False), (True, False), (True, True)])
def test_admin_api_map_review_scope_success_is_read_only(tmp_path: Path, with_hashes: bool, different_context: bool) -> None:
    root = _map_review_workspace(tmp_path, manual=True)
    if different_context:
        _different_map_review_context(root)
    client = TestClient(create_admin_app(
        pretrip_workspace_root=tmp_path,
        runtime_audit_root=tmp_path.parent / f"{tmp_path.name}-audit",
        terrain_guidance_elevation_sampler=_MapReviewSampler(),
    ))
    base = "/admin/pretrip/projects/guidance_demo/terrain-route-guidance"
    state = client.get(base).json()
    params = {
        "reference_hypothesis_id": "active-cccccccccccc",
        "corridor_band_name": "top_5_percent_corridor",
    }
    if with_hashes:
        params.update({f"expected_{key}_sha256": state[f"{key}_sha256"] for key in ("feature_index", "resolution")})
    before = _file_snapshot(root)
    response = client.get(f"{base}/map-review-scope", params=params)
    assert response.status_code == 200, response.text
    scope = response.json()
    assert scope["status"] == "ready"
    assert scope["endpoint_alignment"] == ("different_review_context" if different_context else "same_ab")
    assert scope["execution_eligible"] is False
    assert scope["routing_effect"] == "none"
    assert [item["rank"] for item in _scope_constraint(scope, "G6")["candidates"]] == [2, 5]
    assert scope["source_feature_index_sha256"] == state["feature_index_sha256"]
    assert scope["source_resolution_sha256"] == state["resolution_sha256"]
    assert response.headers["x-scout-candidate-only"] == "true"
    assert _file_snapshot(root) == before


@pytest.mark.parametrize("failure", ["sampler", "feature_index", "resolution"])
def test_admin_api_map_review_scope_failures_are_read_only(tmp_path: Path, failure: str) -> None:
    root = _map_review_workspace(tmp_path, manual=True)
    client = TestClient(create_admin_app(
        pretrip_workspace_root=tmp_path,
        runtime_audit_root=tmp_path.parent / f"{tmp_path.name}-audit",
        terrain_guidance_elevation_sampler=None if failure == "sampler" else _MapReviewSampler(),
    ))
    params = {
        "reference_hypothesis_id": "active-cccccccccccc",
        "corridor_band_name": "top_5_percent_corridor",
    }
    if failure != "sampler":
        params[f"expected_{failure}_sha256"] = "0" * 64
    before = _file_snapshot(root)
    response = client.get(
        "/admin/pretrip/projects/guidance_demo/terrain-route-guidance/map-review-scope", params=params,
    )
    assert response.status_code == 409, response.text
    assert response.json()["status"] == "unavailable"
    assert response.json()["constraints"] == []
    assert response.json()["runtime_safety_truth"] is False
    assert _file_snapshot(root) == before
