from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import terrain_route_guidance_workspace as guidance_workspace
from admin_api import create_admin_app
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
