from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

import pretrip_layer_preparation
from navigation_terrain_projection_store import inspect_navigation_terrain_projection
from qgis_spatial_backend import (
    QgisMcpHttpTransport,
    QgisSpatialBackend,
    QgisSpatialBackendError,
    QgisSpatialBackendConfig,
    _compact_json_bytes,
    _json_bytes,
    _validated_terrain_surface_manifest_bytes,
    _validated_candidate_geojson,
)
from qgis_spatial_contracts import (
    TERRAIN_FEATURE_STACK_WORKFLOW_ID,
    TERRAIN_ROUTE_HYPOTHESIS_WORKFLOW_ID,
    QgisBackendAvailability,
    SpatialAnalysisErrorCode,
    SpatialAnalysisRequest,
    SpatialWorkflowState,
    TerrainRouteEndpointSelection,
)
from pretrip_layer_preparation import LayerPreparationRequest


def _test_access_value() -> str:
    return "".join(("test-scout-", "backend-worker-", "0123456789"))


def _fixed_now() -> datetime:
    return datetime(2026, 8, 21, 4, 30, tzinfo=timezone.utc)


def _workspace(root: Path) -> tuple[Path, dict[str, Any], Path]:
    project_root = root / "qgis_worker_demo"
    (project_root / "outputs").mkdir(parents=True)
    checkpoints = [
        {"lat": 24.05, "lon": 121.21},
        {"lat": 24.04, "lon": 121.22},
    ]
    (project_root / "outputs" / "compiled_mission_graph.reviewed.json").write_text(
        json.dumps({"checkpoints": checkpoints}),
        encoding="utf-8",
    )
    project = {
        "project_id": "qgis_worker_demo",
        "route_name": "QGIS worker demo",
        "compiled_mission_graph_reviewed_ref": "outputs/compiled_mission_graph.reviewed.json",
    }
    (project_root / "project.json").write_text(json.dumps(project), encoding="utf-8")
    dem = root / "source-dem.grd"
    dem.write_bytes(b"source-dem")
    full_dem = root / "full-source-dem.tif"
    full_dem.write_bytes(b"full-source-dem")
    summary = {
        "summary_id": "dtm_coverage.qgis_worker_demo",
        "missing_grid_count": 0,
        "raster_sources": [
            {
                "path": str(full_dem),
                "role": "operator_supplied_full_extent_dem_raster",
                "sha256": hashlib.sha256(full_dem.read_bytes()).hexdigest(),
                "crs": "EPSG:3826",
                "crs_evidence": "Metadata.xml",
                "source_resolution_m": 20.0,
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        ],
        "candidate_tiles": [
            {
                "tile_id": "demo-dem",
                "grid_uri": str(dem),
                "intersects_route_bbox": True,
                "resolution_x_m": 20.0,
                "resolution_y_m": 20.0,
            }
        ],
    }
    summary_path = project_root / "normalized" / "terrain" / "dtm_coverage_summary.json"
    summary_path.parent.mkdir(parents=True)
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    return project_root, project, full_dem


def _worker_run(state: str) -> dict[str, Any]:
    base = {
        "schema_version": "scout_qgis_worker.v0_1",
        "worker_run_id": "qgis-worker-demo-run",
        "project_id": "qgis_worker_demo",
        "workflow_id": "terrain_context_preview.v1",
        "workflow_version": "0.1",
        "request_id": "request-worker-demo",
        "requested_by": "dashboard_operator",
        "state": state,
        "created_at": "2026-08-21T04:30:00Z",
        "started_at": "2026-08-21T04:30:00Z" if state != "queued" else None,
        "updated_at": "2026-08-21T04:30:01Z",
        "completed_at": "2026-08-21T04:30:01Z" if state == "completed" else None,
        "processing_status": "completed" if state == "completed" else state,
        "render_status": "completed" if state == "completed" else "pending",
        "visual_review_status": "pending",
        "human_review_status": "pending",
        "steps": [],
        "warnings": [],
        "error": None,
        "audit_trail": [{"event": f"workflow_{state}", "at": "2026-08-21T04:30:01Z"}],
        "candidate_only": True,
        "runtime_safety_truth": False,
        "operational": False,
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "operational": False,
            "phase1_runtime_mutation_allowed": False,
            "safety_api_called": False,
            "browser_direct_mcp_allowed": False,
            "arbitrary_python_allowed": False,
            "shell_execution_allowed": False,
            "unrestricted_filesystem_allowed": False,
            "human_review_required": True,
            "safe_or_walkable": "not_determined",
        },
    }
    if state != "completed":
        return {**base, "result": None}
    slope = b"real-qgis-slope-raster"
    render = b"real-qgis-render-png"
    return {
        **base,
        "result": {
            "maplibre_geojson": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[121.21, 24.05], [121.22, 24.04]],
                        },
                        "properties": {
                            "kind": "qgis_candidate_route",
                            "candidate_only": True,
                            "runtime_safety_truth": False,
                        },
                    },
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[121.2, 24.03], [121.23, 24.03], [121.23, 24.06], [121.2, 24.06], [121.2, 24.03]]],
                        },
                        "properties": {
                            "kind": "qgis_slope_candidate",
                            "candidate_only": True,
                            "runtime_safety_truth": False,
                            "visualization_only": True,
                        },
                    },
                ],
                "properties": {"candidate_only": True, "runtime_safety_truth": False},
            },
            "artifacts": [
                {
                    "artifact_id": "qgis-worker-demo-run.slope",
                    "artifact_type": "slope_raster",
                    "relative_ref": "slope.tif",
                    "media_type": "image/tiff",
                    "sha256": hashlib.sha256(slope).hexdigest(),
                    "byte_count": len(slope),
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                    "operational": False,
                    "visualization_only": False,
                    "adds_source_resolution": False,
                },
                {
                    "artifact_id": "qgis-worker-demo-run.render",
                    "artifact_type": "qgis_render_preview",
                    "relative_ref": "qgis_render_preview.png",
                    "media_type": "image/png",
                    "sha256": hashlib.sha256(render).hexdigest(),
                    "byte_count": len(render),
                    "width_px": 960,
                    "height_px": 540,
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                    "operational": False,
                    "visualization_only": True,
                    "adds_source_resolution": False,
                },
            ],
            "qgis_version": "3.44.12",
            "qgis_mcp_plugin_version": "0.4.8",
            "crs": "EPSG:3826",
            "source_resolution": {"x_m": 20.0, "y_m": 20.0, "adds_source_resolution": False},
            "output_resolution": {"render_width_px": 960, "render_height_px": 540},
            "processing_algorithms": ["gdal:slope"],
            "processing_parameters": {"slope_band": 1, "slope_scale": 1.0},
            "warnings": ["execution evidence only"],
            "candidate_only": True,
            "runtime_safety_truth": False,
            "operational": False,
            "adds_source_resolution": False,
        },
    }


class AsyncWorkerTransport:
    def __init__(self) -> None:
        self.post_calls: list[tuple[str, dict[str, Any]]] = []
        self.get_calls: list[str] = []
        self.byte_calls: list[str] = []

    def get_json(self, url: str, *, timeout_s: float) -> Any:
        self.get_calls.append(url)
        if url.endswith("/status"):
            return {
                "availability": "available",
                "mcp_reachable": True,
                "qgis_application_available": True,
                "plugin_bridge_available": True,
                "capabilities_discoverable": True,
                "qgis_version": "3.44.12",
                "qgis_mcp_plugin_version": "0.4.8",
            }
        if url.endswith("/workflows/qgis-worker-demo-run"):
            return _worker_run("completed")
        raise AssertionError(f"unexpected GET: {url}")

    def post_json(self, url: str, payload: dict[str, Any], *, timeout_s: float) -> Any:
        self.post_calls.append((url, payload))
        if url.endswith("/cancel"):
            return {**_worker_run("queued"), "state": "cancelled", "processing_status": "cancelled"}
        return _worker_run("queued")

    def get_bytes(self, url: str, *, timeout_s: float, max_bytes: int) -> bytes:
        self.byte_calls.append(url)
        if url.endswith("qgis-worker-demo-run.slope"):
            return b"real-qgis-slope-raster"
        if url.endswith("qgis-worker-demo-run.render"):
            return b"real-qgis-render-png"
        raise AssertionError(f"unexpected artifact: {url}")


_ROUTE_SAMPLE_BYTES = json.dumps(
    {
        "type": "FeatureCollection",
        "metadata": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "operational": False,
            "risk_score_applied": False,
        },
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [121.21, 24.05]},
                "properties": {
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                    "operational": False,
                    "risk_score_applied": False,
                    "slope_degrees": 35.0,
                    "geomorphon_code": 3,
                    "geomorphon_label": "ridge",
                },
            }
        ],
    },
    separators=(",", ":"),
).encode("utf-8")


def _candidate_vector_bytes(kind: str) -> bytes:
    return json.dumps(
        {
            "type": "FeatureCollection",
            "metadata": {
                "candidate_only": True,
                "runtime_safety_truth": False,
                "operational": False,
                "risk_score_applied": False,
                "crs": "EPSG:4326",
            },
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[121.21, 24.05], [121.22, 24.04]],
                    },
                    "properties": {
                        "kind": kind,
                        "candidate_only": True,
                        "runtime_safety_truth": False,
                        "operational": False,
                        "risk_score_applied": False,
                    },
                }
            ],
        },
        separators=(",", ":"),
    ).encode("utf-8")


_TERRAIN_FEATURE_BYTES = {
    "dem_route_bbox_raster": b"route-bbox-dem-raster",
    "slope_raster": b"grass-slope-raster",
    "aspect_raster": b"grass-aspect-raster",
    "hillshade_raster": b"grass-hillshade-raster",
    "elevation_tint_overlay": b"elevation-tint-png",
    "hillshade_overlay": b"hillshade-png",
    "slope_shading_overlay": b"slope-shading-png",
    "contour_lines_vector": _candidate_vector_bytes("qgis_candidate_contour_line"),
    "contours_overlay": b"contours-png",
    "terrain_surface_manifest": json.dumps(
        {
            "schema_version": "scout_qgis_terrain_surface.v0_1",
            "artifact_kind": "scout_qgis_terrain_surface_manifest",
            "status": "completed_candidate_surface",
            "coverage_scope": "full_route_extent_rectangle",
            "overlay_alpha_channel": True,
            "overlay_pixel_format": "RGBA",
            "overlay_compositing": "source-over",
            "analysis_extent": {
                "scope": "full_route_extent_rectangle",
                "crs": "EPSG:3826",
                "margin_m": 250.0,
                "resolution_m": 20.0,
                "width": 526,
                "height": 526,
                "cell_count": 276676,
                "bbox_twd97": {
                    "min_x": 259740.0,
                    "min_y": 2639740.0,
                    "max_x": 270260.0,
                    "max_y": 2650260.0,
                },
                "bbox_wgs84": {
                    "west": 121.09,
                    "south": 23.86,
                    "east": 121.20,
                    "north": 23.96,
                },
                "qgis_extent": "259740,270260,2639740,2650260",
            },
            "actual_processor": "qgis_processing_grass",
            "actual_processors": {
                "dem_crop": "gdal:cliprasterbyextent",
                "slope_aspect": "grass:r.slope.aspect",
                "hillshade": "grass:r.relief",
                "contours": "grass:r.contour",
                "contour_rasterization": "gdal:rasterize",
                "display_colorization": "gdal:colorrelief",
            },
            "fallback_used": False,
            "python_dtm_processing_used": False,
            "candidate_only": True,
            "runtime_safety_truth": False,
            "operational": False,
            "adds_source_resolution": False,
        },
        separators=(",", ":"),
    ).encode("utf-8"),
    "geomorphon_raster": b"grass-geomorphon-raster",
    "geomorphon_fine_raster": b"grass-geomorphon-fine-raster",
    "geomorphon_coarse_raster": b"grass-geomorphon-coarse-raster",
    "geomorphon_consensus_ridge_raster": b"grass-ridge-consensus-raster",
    "geomorphon_consensus_valley_raster": b"grass-valley-consensus-raster",
    "flow_accumulation_raster": b"grass-flow-accumulation-raster",
    "stream_network_raster": b"grass-stream-network-raster",
    "ridge_lines_vector": _candidate_vector_bytes("qgis_candidate_ridge_line"),
    "valley_lines_vector": _candidate_vector_bytes("qgis_candidate_valley_line"),
    "stream_network_vector": _candidate_vector_bytes(
        "qgis_candidate_stream_network"
    ),
    "terrain_feature_route_samples": _ROUTE_SAMPLE_BYTES,
    "terrain_feature_manifest": json.dumps(
        {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "operational": False,
            "fixture": False,
            "synthetic": False,
            "artifacts": {"dem_route_bbox": "dem_route_bbox.tif"},
            "source_resolution": {
                "status": "reported",
                "source_kind": "declared_full_extent_raster",
                "x_m": 20.0,
                "y_m": 20.0,
                "crs": "EPSG:3826",
                "crs_evidence": "Metadata.xml",
                "adds_source_resolution": False,
            },
            "parameters": {
                "analysis_extent": {
                    "resolution_m": 20.0,
                }
            },
        },
        separators=(",", ":"),
    ).encode("utf-8"),
    "qgis_visual_context": b'{"rendered_feature":"grass_slope_candidate"}',
    "qgis_render_preview": b"real-grass-qgis-render-png",
}


def test_qgis_surface_manifest_rejects_grid_extent_misalignment() -> None:
    payload = json.loads(_TERRAIN_FEATURE_BYTES["terrain_surface_manifest"])
    payload["analysis_extent"]["bbox_twd97"]["max_x"] += 20.0

    with pytest.raises(
        QgisSpatialBackendError,
        match="grid is not aligned",
    ):
        _validated_terrain_surface_manifest_bytes(
            json.dumps(payload, separators=(",", ":")).encode("utf-8")
        )


def _terrain_feature_worker_run(state: str) -> dict[str, Any]:
    payload = _worker_run(state)
    payload["workflow_id"] = TERRAIN_FEATURE_STACK_WORKFLOW_ID
    if state != "completed":
        return payload
    artifact_files = {
        "dem_route_bbox_raster": "dem_route_bbox.tif",
        "slope_raster": "grass_slope.tif",
        "aspect_raster": "grass_aspect.tif",
        "hillshade_raster": "grass_hillshade.tif",
        "elevation_tint_overlay": "terrain_elevation_tint.png",
        "hillshade_overlay": "terrain_hillshade.png",
        "slope_shading_overlay": "terrain_slope_shading.png",
        "contour_lines_vector": "grass_contours.geojson",
        "contours_overlay": "terrain_contours.png",
        "terrain_surface_manifest": "terrain_surface_manifest.json",
        "geomorphon_raster": "grass_geomorphon_landforms.tif",
        "geomorphon_fine_raster": "grass_geomorphon_fine.tif",
        "geomorphon_coarse_raster": "grass_geomorphon_coarse.tif",
        "geomorphon_consensus_ridge_raster": "grass_geomorphon_ridge_consensus.tif",
        "geomorphon_consensus_valley_raster": "grass_geomorphon_valley_consensus.tif",
        "flow_accumulation_raster": "grass_flow_accumulation.tif",
        "stream_network_raster": "grass_stream_network.tif",
        "ridge_lines_vector": "ridge_lines.geojson",
        "valley_lines_vector": "valley_lines.geojson",
        "stream_network_vector": "stream_network.geojson",
        "terrain_feature_route_samples": "terrain_feature_route_samples.geojson",
        "terrain_feature_manifest": "terrain_feature_manifest.json",
        "qgis_visual_context": "qgis_visual_context.json",
        "qgis_render_preview": "qgis_render_preview.png",
    }
    artifact_media = {
        "dem_route_bbox_raster": "image/tiff",
        "slope_raster": "image/tiff",
        "aspect_raster": "image/tiff",
        "hillshade_raster": "image/tiff",
        "elevation_tint_overlay": "image/png",
        "hillshade_overlay": "image/png",
        "slope_shading_overlay": "image/png",
        "contour_lines_vector": "application/geo+json",
        "contours_overlay": "image/png",
        "terrain_surface_manifest": "application/json",
        "geomorphon_raster": "image/tiff",
        "geomorphon_fine_raster": "image/tiff",
        "geomorphon_coarse_raster": "image/tiff",
        "geomorphon_consensus_ridge_raster": "image/tiff",
        "geomorphon_consensus_valley_raster": "image/tiff",
        "flow_accumulation_raster": "image/tiff",
        "stream_network_raster": "image/tiff",
        "ridge_lines_vector": "application/geo+json",
        "valley_lines_vector": "application/geo+json",
        "stream_network_vector": "application/geo+json",
        "terrain_feature_route_samples": "application/geo+json",
        "terrain_feature_manifest": "application/json",
        "qgis_visual_context": "application/json",
        "qgis_render_preview": "image/png",
    }
    artifacts = []
    for artifact_type, raw in _TERRAIN_FEATURE_BYTES.items():
        artifact = {
            "artifact_id": f"qgis-worker-demo-run.{artifact_type}",
            "artifact_type": artifact_type,
            "relative_ref": artifact_files[artifact_type],
            "media_type": artifact_media[artifact_type],
            "sha256": hashlib.sha256(raw).hexdigest(),
            "byte_count": len(raw),
            "candidate_only": True,
            "runtime_safety_truth": False,
            "operational": False,
            "visualization_only": artifact_type
            in {
                "elevation_tint_overlay",
                "hillshade_overlay",
                "slope_shading_overlay",
                "contour_lines_vector",
                "contours_overlay",
                "terrain_surface_manifest",
                "qgis_visual_context",
                "qgis_render_preview",
            },
            "adds_source_resolution": False,
        }
        if artifact_type == "qgis_render_preview":
            artifact.update({"width_px": 960, "height_px": 540})
        elif artifact_type in {
            "elevation_tint_overlay",
            "hillshade_overlay",
            "slope_shading_overlay",
        }:
            artifact.update({"width_px": 526, "height_px": 526})
        elif artifact_type == "contours_overlay":
            artifact.update({"width_px": 1052, "height_px": 1052})
        artifacts.append(artifact)
    payload["result"] = {
        **payload["result"],
        "artifacts": artifacts,
        "processing_algorithms": [
            "gdal:cliprasterbyextent",
            "gdal:colorrelief",
            "gdal:rasterize",
            "grass:r.contour",
            "grass:r.slope.aspect",
            "grass:r.relief",
            "grass:r.geomorphon",
            "grass:r.mapcalc.simple",
            "grass:r.thin",
            "grass:r.to.vect",
            "grass:r.watershed",
        ],
        "processing_parameters": {
            "analysis_extent": {
                "scope": "full_route_extent_rectangle",
                "crs": "EPSG:3826",
                "margin_m": 250.0,
                "resolution_m": 20.0,
                "width": 526,
                "height": 526,
                "cell_count": 276676,
                "bbox_twd97": {
                    "min_x": 259740.0,
                    "min_y": 2639740.0,
                    "max_x": 270260.0,
                    "max_y": 2650260.0,
                },
                "bbox_wgs84": {
                    "west": 121.09,
                    "south": 23.86,
                    "east": 121.20,
                    "north": 23.96,
                },
                "qgis_extent": "259740,270260,2639740,2650260",
            },
            "geomorphon_search_cells": {"fine": 5, "medium": 10, "coarse": 20},
            "watershed_threshold_cells": 50,
        },
        "warnings": ["candidate terrain feature execution evidence only"],
    }
    return payload


class TerrainFeatureWorkerTransport(AsyncWorkerTransport):
    def get_json(self, url: str, *, timeout_s: float) -> Any:
        self.get_calls.append(url)
        if url.endswith("/status"):
            return {
                "availability": "available",
                "mcp_reachable": True,
                "qgis_application_available": True,
                "plugin_bridge_available": True,
                "capabilities_discoverable": True,
                "qgis_version": "3.44.12",
                "qgis_mcp_plugin_version": "0.4.9",
            }
        if url.endswith("/workflows/qgis-worker-demo-run"):
            return _terrain_feature_worker_run("completed")
        raise AssertionError(f"unexpected GET: {url}")

    def post_json(self, url: str, payload: dict[str, Any], *, timeout_s: float) -> Any:
        self.post_calls.append((url, payload))
        return _terrain_feature_worker_run("queued")

    def get_bytes(self, url: str, *, timeout_s: float, max_bytes: int) -> bytes:
        self.byte_calls.append(url)
        artifact_type = url.rsplit(".", 1)[-1]
        if artifact_type in _TERRAIN_FEATURE_BYTES:
            return _TERRAIN_FEATURE_BYTES[artifact_type]
        raise AssertionError(f"unexpected artifact: {url}")


def _terrain_route_worker_evidence(
    request_payload: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, bytes]]:
    cache_keys = dict(request_payload["terrain_route_cache_keys"])
    cache_key = cache_keys["route_hypothesis"]
    coordinates = request_payload["route_geojson"]["features"][0]["geometry"][
        "coordinates"
    ]
    parent_ref = next(
        ref
        for ref in request_payload["source_refs"]
        if str(ref).endswith("terrain_feature_manifest.json")
    )
    bbox = {"west": 121.09, "south": 23.86, "east": 121.2, "north": 23.96}
    relative_refs = {
        "terrain_route_hypothesis": "terrain_route_hypothesis.json",
        "terrain_route_best_path_vector": "terrain_route_best_path.geojson",
        "terrain_route_slope_raster": "terrain_route_slope.tif",
        "terrain_route_flow_accumulation_raster": "terrain_route_flow_accumulation.tif",
        "terrain_route_drainage_pressure_raster": "terrain_route_drainage_pressure.tif",
        "terrain_route_friction_raster": "terrain_route_friction.tif",
        "terrain_route_walk_cost_raster": "terrain_route_walk_cost.tif",
        "terrain_route_walk_direction_raster": "terrain_route_walk_direction.tif",
        "terrain_route_cost_from_a_raster": "terrain_route_cost_from_a.tif",
        "terrain_route_cost_from_b_raster": "terrain_route_cost_from_b.tif",
        "terrain_route_cost_direction_a_raster": "terrain_route_cost_direction_a.tif",
        "terrain_route_cost_direction_b_raster": "terrain_route_cost_direction_b.tif",
        "terrain_route_corridor_raster": "terrain_route_corridor.tif",
        "terrain_route_quantiles": "terrain_route_quantiles.json",
        "terrain_route_processing_manifest": "terrain_route_processing_manifest.json",
    }
    bytes_by_key: dict[str, bytes] = {
        key: f"real-{key}".encode("ascii")
        for key in (
            "terrain_route_slope_raster",
            "terrain_route_flow_accumulation_raster",
            "terrain_route_drainage_pressure_raster",
            "terrain_route_friction_raster",
            "terrain_route_walk_cost_raster",
            "terrain_route_walk_direction_raster",
            "terrain_route_cost_from_a_raster",
            "terrain_route_cost_from_b_raster",
            "terrain_route_cost_direction_a_raster",
            "terrain_route_cost_direction_b_raster",
            "terrain_route_corridor_raster",
        )
    }
    bytes_by_key["terrain_route_quantiles"] = json.dumps(
        {"5": 0.5, "10": 1.0, "20": 2.0}, separators=(",", ":")
    ).encode("utf-8")
    best_path = {
        "type": "FeatureCollection",
        "metadata": {
            "schema_version": "scout_terrain_route_best_path.v0_2",
            "workflow_id": TERRAIN_ROUTE_HYPOTHESIS_WORKFLOW_ID,
            "crs": "EPSG:4326",
            "authority": "candidate_only",
            "source_type": "terrain_hypothesis",
            "candidate_only": True,
            "runtime_safety_truth": False,
            "operational": False,
            "safe_or_walkable": "not_determined",
        },
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coordinates},
                "properties": {
                    "id": "qgis-worker-demo-run.terrain_route_hypothesis.R1",
                    "kind": "terrain_route_hypothesis_best_path",
                    "feature_class": "terrain_route_hypothesis_best_path",
                    "label": "R1 minimum anisotropic model-cost trace",
                    "path_model": "anisotropic_walk",
                    "path_semantics": "minimum_anisotropic_model_cost_trace",
                    "path_band_relationship": "separate_model_not_path_confidence_band",
                    "authority": "candidate_only",
                    "source_type": "terrain_hypothesis",
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                    "operational": False,
                    "safe_or_walkable": "not_determined",
                    "observed": False,
                    "official": False,
                    "human_verified": False,
                    "not_verified_trail": True,
                },
            }
        ],
    }
    bytes_by_key["terrain_route_best_path_vector"] = json.dumps(
        best_path, separators=(",", ":")
    ).encode("utf-8")
    bands: list[dict[str, Any]] = []
    band_keys: list[tuple[str, str, str]] = []
    for percentile in (5, 10, 20):
        mode = f"top_{percentile}_percent_corridor"
        raster_key = f"terrain_route_corridor_band_raster_{percentile}"
        overlay_key = f"terrain_route_corridor_overlay_{percentile}"
        raster_ref = f"{mode}.tif"
        overlay_ref = f"{mode}.png"
        relative_refs[raster_key] = raster_ref
        relative_refs[overlay_key] = overlay_ref
        bytes_by_key[raster_key] = f"real-{raster_key}".encode("ascii")
        bytes_by_key[overlay_key] = f"real-{overlay_key}".encode("ascii")
        bands.append(
            {
                "name": mode,
                "percentile": percentile,
                "max_relative_corridor_cost": percentile / 10,
                "cell_count": percentile * 100,
                "contains_best_path": True,
                "raster_ref": {
                    "artifact_ref": raster_ref,
                    "sha256": hashlib.sha256(bytes_by_key[raster_key]).hexdigest(),
                    "media_type": "image/tiff",
                    "crs": "EPSG:3826",
                    "bbox_wgs84": bbox,
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                    "operational": False,
                },
                "overlay_ref": {
                    "artifact_ref": overlay_ref,
                    "sha256": hashlib.sha256(bytes_by_key[overlay_key]).hexdigest(),
                    "media_type": "image/png",
                    "crs": "EPSG:3826",
                    "bbox_wgs84": bbox,
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                    "operational": False,
                },
            }
        )
        band_keys.append((raster_key, overlay_key, mode))
    processing_manifest = {
        "schema_version": "scout_terrain_route_processing_manifest.v0_2",
        "workflow_id": TERRAIN_ROUTE_HYPOTHESIS_WORKFLOW_ID,
        "parent_terrain_feature_manifest_ref": parent_ref,
        "cache_keys": cache_keys,
        "corridor_semantics": (
            "finite_symmetric_macro_terrain_relative_cost_cell_percentile"
        ),
        "corridor_formula": "C_A(x,y)+C_B(x,y)-C_AB",
        "corridor_cost_symmetric": True,
        "best_path_cost_symmetric": False,
        "path_model": {
            "id": "anisotropic_walk",
            "semantics": "minimum_anisotropic_model_cost_trace",
            "recipe": "grass:r.walk.coords+grass:r.path",
        },
        "band_model": {
            "id": "symmetric_macro_terrain_cost",
            "semantics": "finite_symmetric_macro_terrain_relative_cost_cell_percentile",
            "recipe": "symmetric_grass:r.cost",
        },
        "path_band_relationship": "separate_model_not_path_confidence_band",
        "best_path_union_applied": False,
        "path_orientation": "A_TO_B",
        "search_complete": True,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "operational": False,
        "safe_or_walkable": "not_determined",
    }
    bytes_by_key["terrain_route_processing_manifest"] = json.dumps(
        processing_manifest, separators=(",", ":")
    ).encode("utf-8")
    cost_config = request_payload["terrain_routing_cost_config"]
    corridor_raw = bytes_by_key["terrain_route_corridor_raster"]
    hypothesis = {
        "schema_version": "scout_terrain_route_hypothesis.v0_2",
        "artifact_kind": "terrain_route_hypothesis_run",
        "status": "completed",
        "created_at": "2026-08-21T04:30:01Z",
        "hypotheses": [
            {
                "id": "qgis-worker-demo-run.terrain_route_hypothesis.R1",
                "label": "R1 terrain route hypothesis",
                "start": {
                    "x": coordinates[0][0],
                    "y": coordinates[0][1],
                    "crs": "EPSG:4326",
                },
                "destination": {
                    "x": coordinates[-1][0],
                    "y": coordinates[-1][1],
                    "crs": "EPSG:4326",
                },
                "best_path": {
                    "type": "LineString",
                    "coordinates": coordinates,
                    "crs": "EPSG:4326",
                },
                "path_model": "anisotropic_walk",
                "path_semantics": "minimum_anisotropic_model_cost_trace",
                "corridor": {
                    "bands": bands,
                    "raster_ref": {
                        "artifact_ref": relative_refs["terrain_route_corridor_raster"],
                        "sha256": hashlib.sha256(corridor_raw).hexdigest(),
                        "media_type": "image/tiff",
                        "crs": "EPSG:3826",
                        "bbox_wgs84": bbox,
                        "candidate_only": True,
                        "runtime_safety_truth": False,
                        "operational": False,
                    },
                },
                "metrics": {
                    "relative_score": 1.0,
                    "relative_cost": 42.0,
                    "distance_m": 1500.0,
                    "elevation_gain_m": 210.0,
                    "elevation_loss_m": 70.0,
                    "max_slope_degrees": 34.0,
                    "median_slope_degrees": 16.0,
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
                        "description": "Terrain evidence does not establish legal access.",
                    },
                    {
                        "code": "recent_landslide_unknown",
                        "description": "Recent landslide state is unknown.",
                    },
                ],
                "dem_resolution_m": 20.0,
                "resolution_class": "macro_terrain_only",
                "confidence_limits": ["microterrain_not_resolved"],
                "cost_model_version": cost_config["model_version"],
                "provenance": {
                    "dem_dataset_id": "qgis_worker_demo.dem_route_bbox",
                    "dem_sha256": next(iter(request_payload["source_hashes"].values())),
                    "dem_resolution_m": 20.0,
                    "dem_crs": "EPSG:3826",
                    "dem_extent": {
                        "x_min": 259740.0,
                        "y_min": 2639740.0,
                        "x_max": 270260.0,
                        "y_max": 2650260.0,
                    },
                    "input_endpoints": {
                        "start": {"lon": coordinates[0][0], "lat": coordinates[0][1]},
                        "destination": {"lon": coordinates[-1][0], "lat": coordinates[-1][1]},
                    },
                    "cost_model_version": cost_config["model_version"],
                    "weights": {
                        key: value
                        for key, value in cost_config.items()
                        if key.endswith("_weight")
                    },
                    "weights_hash": "e" * 64,
                    "grass_version": "8.5.0",
                    "qgis_version": "3.44.12",
                    "backend_id": "qgis_processing_grass",
                    "modules_executed": [
                        "r.slope.aspect",
                        "r.mapcalc",
                        "r.walk",
                        "r.path",
                        "r.cost",
                        "r.quantile",
                    ],
                    "timestamp": "2026-08-21T04:30:01Z",
                    "algorithm_version": cost_config["algorithm_version"],
                    "processing_manifest": {
                        "parent_terrain_feature_manifest_ref": parent_ref
                    },
                    "cache_key": cache_key,
                    "cache_keys": cache_keys,
                },
            }
        ],
    }
    midpoint_lon = (float(coordinates[0][0]) + float(coordinates[-1][0])) / 2
    midpoint_lat = (float(coordinates[0][1]) + float(coordinates[-1][1])) / 2
    route_profiles = (
        ("drainage_averse", 4.0, [midpoint_lon - 0.001, midpoint_lat + 0.001]),
        ("balanced", 1.5, [midpoint_lon, midpoint_lat]),
        ("terrain_only_baseline", 0.0, [midpoint_lon + 0.001, midpoint_lat - 0.001]),
    )
    typed_hypotheses = []
    path_features = []
    for alternative_index, (strategy, multiplier, midpoint) in enumerate(
        route_profiles,
        start=1,
    ):
        candidate_id = f"R{alternative_index}"
        profile_coordinates = [coordinates[0], midpoint, coordinates[-1]]
        route = json.loads(json.dumps(hypothesis["hypotheses"][0]))
        route.update(
            {
                "id": f"qgis-worker-demo-run.terrain_route_hypothesis.{candidate_id}",
                "label": f"{candidate_id} {strategy} terrain hypothesis",
                "alternative_index": alternative_index,
                "strategy": strategy,
                "drainage_penalty_multiplier": multiplier,
            }
        )
        route["best_path"]["coordinates"] = profile_coordinates
        if alternative_index > 1:
            route["corridor"] = None
        route["provenance"]["weights"]["drainage_penalty_multiplier"] = multiplier
        route["provenance"]["processing_manifest"]["active_profile"] = {
            "candidate_id": candidate_id,
            "strategy": strategy,
            "drainage_penalty_multiplier": multiplier,
            "corridor_profile": alternative_index == 1,
        }
        typed_hypotheses.append(route)

        feature = json.loads(json.dumps(best_path["features"][0]))
        feature["geometry"]["coordinates"] = profile_coordinates
        feature["properties"].update(
            {
                "id": route["id"],
                "candidate_id": candidate_id,
                "alternative_index": alternative_index,
                "label": route["label"],
                "strategy": strategy,
                "drainage_penalty_multiplier": multiplier,
                "relative_cost_comparison_scope": "within_profile_only",
            }
        )
        path_features.append(feature)
    hypothesis["hypotheses"] = typed_hypotheses
    best_path["features"] = path_features
    best_path["metadata"].update(
        {
            "candidate_ids": ["R1", "R2", "R3"],
            "candidate_count": 3,
            "distinct_geometry_count": 3,
        }
    )
    bytes_by_key["terrain_route_best_path_vector"] = json.dumps(
        best_path, separators=(",", ":")
    ).encode("utf-8")
    bytes_by_key["terrain_route_hypothesis"] = json.dumps(
        hypothesis, separators=(",", ":")
    ).encode("utf-8")
    artifact_types = {
        **{key: key for key in relative_refs},
        **{
            raster_key: "terrain_route_corridor_band_raster"
            for raster_key, _, _ in band_keys
        },
        **{
            overlay_key: "terrain_route_corridor_overlay"
            for _, overlay_key, _ in band_keys
        },
    }
    artifacts = []
    for key, raw in bytes_by_key.items():
        artifact_type = artifact_types[key]
        media_type = (
            "image/tiff"
            if relative_refs[key].endswith(".tif")
            else "image/png"
            if relative_refs[key].endswith(".png")
            else "application/geo+json"
            if relative_refs[key].endswith(".geojson")
            else "application/json"
        )
        artifact = {
            "artifact_id": f"qgis-worker-demo-run.{key}",
            "artifact_type": artifact_type,
            "relative_ref": relative_refs[key],
            "media_type": media_type,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "byte_count": len(raw),
            "candidate_only": True,
            "runtime_safety_truth": False,
            "operational": False,
            "visualization_only": media_type in {"image/png", "application/geo+json"},
            "adds_source_resolution": False,
        }
        if media_type == "image/png":
            artifact.update({"width_px": 526, "height_px": 526})
        artifacts.append(artifact)
    return (
        {
            "maplibre_geojson": best_path,
            "artifacts": artifacts,
            "qgis_version": "3.44.12",
            "qgis_mcp_plugin_version": "0.4.9",
            "crs": "EPSG:3826",
            "source_resolution": request_payload["source_resolution"],
            "output_resolution": {"width": 526, "height": 526},
            "processing_algorithms": [
                "grass:r.slope.aspect",
                "grass:r.mapcalc.simple",
                "grass:r.walk.coords",
                "grass:r.path",
                "grass:r.cost",
                "grass:r.quantile",
            ],
            "processing_parameters": {"cache_keys": cache_keys},
            "warnings": ["candidate terrain route execution evidence only"],
            "candidate_only": True,
            "runtime_safety_truth": False,
            "operational": False,
            "adds_source_resolution": False,
        },
        {
            f"qgis-worker-demo-run.{key}": raw
            for key, raw in bytes_by_key.items()
        },
    )


class TerrainRouteWorkerTransport(AsyncWorkerTransport):
    def __init__(self) -> None:
        super().__init__()
        self.request_payload: dict[str, Any] | None = None
        self.artifact_bytes: dict[str, bytes] = {}

    def _run(self, state: str) -> dict[str, Any]:
        request_payload = self.request_payload or {
            "request_id": "request-worker-demo",
        }
        payload = _worker_run("completed" if state == "completed" else "queued")
        payload.update(
            {
                "workflow_id": TERRAIN_ROUTE_HYPOTHESIS_WORKFLOW_ID,
                "request_id": request_payload["request_id"],
                "state": state,
                "processing_status": "completed" if state == "completed" else state,
                "render_status": "completed" if state == "completed" else "pending",
            }
        )
        if state != "completed":
            payload["result"] = None
            return payload
        result, self.artifact_bytes = _terrain_route_worker_evidence(request_payload)
        payload["result"] = result
        return payload

    def get_json(self, url: str, *, timeout_s: float) -> Any:
        self.get_calls.append(url)
        if url.endswith("/status"):
            return {
                "availability": "available",
                "mcp_reachable": True,
                "qgis_application_available": True,
                "plugin_bridge_available": True,
                "capabilities_discoverable": True,
                "qgis_version": "3.44.12",
                "qgis_mcp_plugin_version": "0.4.9",
            }
        if url.endswith("/workflows/qgis-worker-demo-run"):
            return self._run("completed")
        raise AssertionError(f"unexpected GET: {url}")

    def post_json(self, url: str, payload: dict[str, Any], *, timeout_s: float) -> Any:
        self.post_calls.append((url, payload))
        self.request_payload = payload
        return self._run("queued")

    def get_bytes(self, url: str, *, timeout_s: float, max_bytes: int) -> bytes:
        self.byte_calls.append(url)
        artifact_id = url.rsplit("/", 1)[-1]
        if artifact_id in self.artifact_bytes:
            return self.artifact_bytes[artifact_id]
        raise AssertionError(f"unexpected terrain route artifact: {url}")


def test_qgis_backend_requires_worker_token_before_network_call() -> None:
    transport = AsyncWorkerTransport()
    status = QgisSpatialBackend(
        config=QgisSpatialBackendConfig(
            enabled=True,
            worker_url="http://127.0.0.1:9876",
            worker_token=None,
        ),
        transport=transport,
        now_factory=_fixed_now,
    ).status(project_id="qgis_worker_demo")
    assert status.availability is QgisBackendAvailability.NOT_CONFIGURED
    assert status.errors[0].code.value == "BACKEND_NOT_CONFIGURED"
    assert not transport.get_calls


def test_qgis_backend_worker_flow_is_queued_polled_and_normalized(tmp_path: Path) -> None:
    project_root, project, dem = _workspace(tmp_path)
    transport = AsyncWorkerTransport()
    backend = QgisSpatialBackend(
        config=QgisSpatialBackendConfig(
            enabled=True,
            worker_url="http://127.0.0.1:9876",
            worker_token=_test_access_value(),
        ),
        transport=transport,
        now_factory=_fixed_now,
    )
    queued = backend.start_workflow(
        project_id="qgis_worker_demo",
        project_root=project_root,
        project=project,
        request=SpatialAnalysisRequest(
            project_id="qgis_worker_demo",
            request_id="request-worker-demo",
        ),
    )
    assert queued.state is SpatialWorkflowState.QUEUED
    assert queued.backend_run_id == "qgis-worker-demo-run"
    submitted = transport.post_calls[0][1]
    assert submitted["dem_refs"] == [str(dem)]
    assert submitted["source_resolution"]["x_m"] == 20.0
    assert submitted["source_resolution"]["crs"] == "EPSG:3826"
    assert submitted["source_resolution"]["source_kind"] == "declared_full_extent_raster"
    assert submitted["candidate_only"] is True
    assert submitted["runtime_safety_truth"] is False

    completed = backend.get_run(
        project_root=project_root,
        workflow_run_id=queued.workflow_run_id,
    )
    assert completed.state is SpatialWorkflowState.COMPLETED
    assert completed.processing_status == "completed"
    assert completed.render_status == "completed"
    assert completed.visual_review_status == "pending"
    assert completed.runtime_safety_truth is False
    assert completed.maplibre_geojson["features"]
    assert {artifact.artifact_type for artifact in completed.artifacts} == {
        "route_geometry",
        "slope_raster",
        "workflow_metadata",
    }
    assert completed.render_artifacts[0].artifact_type == "qgis_render_preview"
    assert completed.render_artifacts[0].fixture is False
    assert completed.render_artifacts[0].synthetic is False
    assert len(transport.byte_calls) == 2
    for artifact in [*completed.artifacts, *completed.render_artifacts]:
        assert artifact.candidate_only is True
        assert artifact.runtime_safety_truth is False
        assert artifact.operational is False


def test_qgis_backend_preserves_typed_artifact_normalization_detail(tmp_path: Path) -> None:
    class CorruptArtifactTransport(AsyncWorkerTransport):
        def get_bytes(self, url: str, *, timeout_s: float, max_bytes: int) -> bytes:
            if url.endswith("qgis-worker-demo-run.slope"):
                return b"corrupt"
            return super().get_bytes(url, timeout_s=timeout_s, max_bytes=max_bytes)

    project_root, project, _ = _workspace(tmp_path)
    backend = QgisSpatialBackend(
        config=QgisSpatialBackendConfig(
            enabled=True,
            worker_url="http://127.0.0.1:9876",
            worker_token=_test_access_value(),
        ),
        transport=CorruptArtifactTransport(),
        now_factory=_fixed_now,
    )
    queued = backend.start_workflow(
        project_id="qgis_worker_demo",
        project_root=project_root,
        project=project,
        request=SpatialAnalysisRequest(
            project_id="qgis_worker_demo",
            request_id="request-worker-demo",
        ),
    )
    failed = backend.get_run(
        project_root=project_root,
        workflow_run_id=queued.workflow_run_id,
    )

    assert failed.state is SpatialWorkflowState.FAILED
    assert failed.error is not None
    assert failed.error.code.value == "ARTIFACT_EXPORT_FAILED"
    assert failed.error.detail == "QGIS slope artifact hash mismatch"


def test_qgis_backend_grass_feature_stack_is_hashed_and_normalized(
    tmp_path: Path,
) -> None:
    project_root, project, _ = _workspace(tmp_path)
    transport = TerrainFeatureWorkerTransport()
    backend = QgisSpatialBackend(
        config=QgisSpatialBackendConfig(
            enabled=True,
            worker_url="http://127.0.0.1:9876",
            worker_token=_test_access_value(),
        ),
        transport=transport,
        now_factory=_fixed_now,
    )
    queued = backend.start_workflow(
        project_id="qgis_worker_demo",
        project_root=project_root,
        project=project,
        request=SpatialAnalysisRequest(
            project_id="qgis_worker_demo",
            workflow_id=TERRAIN_FEATURE_STACK_WORKFLOW_ID,
            request_id="request-worker-demo",
        ),
    )
    assert queued.state is SpatialWorkflowState.QUEUED
    assert transport.post_calls[0][0].endswith(
        "/workflows/terrain_feature_stack.v1"
    )
    assert transport.post_calls[0][1]["workflow_id"] == TERRAIN_FEATURE_STACK_WORKFLOW_ID

    completed = backend.get_run(
        project_root=project_root,
        workflow_run_id=queued.workflow_run_id,
    )
    assert completed.state is SpatialWorkflowState.COMPLETED
    assert completed.workflow_id == TERRAIN_FEATURE_STACK_WORKFLOW_ID
    assert completed.processing_status == "completed"
    assert completed.visual_review_status == "pending"
    assert len(transport.byte_calls) == len(_TERRAIN_FEATURE_BYTES)
    assert {artifact.artifact_type for artifact in completed.artifacts} == {
        "route_geometry",
        "dem_route_bbox_raster",
        "slope_raster",
        "aspect_raster",
        "hillshade_raster",
        "elevation_tint_overlay",
        "hillshade_overlay",
        "slope_shading_overlay",
        "contour_lines_vector",
        "contours_overlay",
        "terrain_surface_manifest",
        "geomorphon_raster",
        "geomorphon_fine_raster",
        "geomorphon_coarse_raster",
        "geomorphon_consensus_ridge_raster",
        "geomorphon_consensus_valley_raster",
        "flow_accumulation_raster",
        "stream_network_raster",
        "ridge_lines_vector",
        "valley_lines_vector",
        "stream_network_vector",
        "terrain_feature_route_samples",
        "terrain_feature_manifest",
        "qgis_visual_context",
        "maplibre_terrain_visualization",
        "workflow_metadata",
    }
    assert completed.render_artifacts[0].artifact_type == "qgis_render_preview"
    assert all(
        artifact.candidate_only
        and not artifact.runtime_safety_truth
        and not artifact.operational
        for artifact in [*completed.artifacts, *completed.render_artifacts]
    )
    assert all(
        (project_root / artifact.artifact_ref).is_file()
        for artifact in [*completed.artifacts, *completed.render_artifacts]
        if artifact.artifact_ref
    )
    persisted_project = json.loads(
        (project_root / "project.json").read_text(encoding="utf-8")
    )
    visualization_ref = persisted_project["terrain_visualization_ref"]
    assert visualization_ref == (
        f"outputs/spatial/qgis/{queued.workflow_run_id}/terrain_visualization.geojson"
    )
    assert persisted_project["terrain_visualization_processor"] == (
        "qgis_processing_grass"
    )
    assert persisted_project["terrain_visualization_workflow_run_id"] == (
        queued.workflow_run_id
    )
    visualization = json.loads(
        (project_root / visualization_ref).read_text(encoding="utf-8")
    )
    assert visualization["status"] == "ready_from_qgis_grass_route_extent_rectangle"
    assert visualization["visualization_spec"]["actual_processor"] == (
        "qgis_processing_grass"
    )
    assert visualization["visualization_spec"]["fallback_used"] is False
    assert visualization["visualization_spec"]["python_dtm_processing_used"] is False
    assert visualization["visualization_spec"]["coverage_scope"] == (
        "full_route_extent_rectangle"
    )
    assert [item["mode"] for item in visualization["raster_overlays"]] == [
        "elevation_tint",
        "hillshade",
        "slope_shading",
        "contours",
    ]
    assert all(
        item["alpha_channel"] is True
        and item["compositing"] == "source-over"
        for item in visualization["raster_overlays"]
    )
    assert {
        item["mode"]: item["opacity"]
        for item in visualization["raster_overlays"]
    } == {
        "elevation_tint": 0.62,
        "hillshade": 0.26,
        "slope_shading": 0.5,
        "contours": 0.72,
    }
    assert all(
        item["bbox_wgs84"]
        == {
            "west": 121.09,
            "south": 23.86,
            "east": 121.2,
            "north": 23.96,
        }
        for item in visualization["raster_overlays"]
    )
    assert visualization["boundary"] == {
        "candidate_only": True,
        "runtime_safety_truth": False,
        "operational": False,
        "visualization_only": True,
        "adds_source_resolution": False,
    }


def test_qgis_backend_materializes_and_reuses_candidate_terrain_route_cache(
    tmp_path: Path,
) -> None:
    project_root, project, _ = _workspace(tmp_path)
    feature_backend = QgisSpatialBackend(
        config=QgisSpatialBackendConfig(
            enabled=True,
            worker_url="http://127.0.0.1:9876",
            worker_token=_test_access_value(),
        ),
        transport=TerrainFeatureWorkerTransport(),
        now_factory=_fixed_now,
    )
    feature_queued = feature_backend.start_workflow(
        project_id="qgis_worker_demo",
        project_root=project_root,
        project=project,
        request=SpatialAnalysisRequest(
            project_id="qgis_worker_demo",
            workflow_id=TERRAIN_FEATURE_STACK_WORKFLOW_ID,
            request_id="request-worker-demo",
        ),
    )
    feature_completed = feature_backend.get_run(
        project_root=project_root,
        workflow_run_id=feature_queued.workflow_run_id,
    )
    assert feature_completed.state is SpatialWorkflowState.COMPLETED

    route_transport = TerrainRouteWorkerTransport()
    route_backend = QgisSpatialBackend(
        config=QgisSpatialBackendConfig(
            enabled=True,
            worker_url="http://127.0.0.1:9876",
            worker_token=_test_access_value(),
        ),
        transport=route_transport,
        now_factory=_fixed_now,
    )
    active_project = json.loads(
        (project_root / "project.json").read_text(encoding="utf-8")
    )
    queued = route_backend.start_workflow(
        project_id="qgis_worker_demo",
        project_root=project_root,
        project=active_project,
        request=SpatialAnalysisRequest(
            project_id="qgis_worker_demo",
            workflow_id=TERRAIN_ROUTE_HYPOTHESIS_WORKFLOW_ID,
            request_id="request-terrain-route",
        ),
    )

    assert queued.state is SpatialWorkflowState.QUEUED, queued.error
    submitted = route_transport.post_calls[0][1]
    assert submitted["workflow_id"] == TERRAIN_ROUTE_HYPOTHESIS_WORKFLOW_ID
    assert len(
        submitted["route_geojson"]["features"][0]["geometry"]["coordinates"]
    ) == 2
    assert submitted["candidate_only"] is True
    assert submitted["runtime_safety_truth"] is False
    assert submitted["operational"] is False
    assert submitted["source_resolution"] == {
        "status": "reported",
        "source_kind": "active_terrain_feature_dem",
        "x_m": 20.0,
        "y_m": 20.0,
        "crs": "EPSG:3826",
        "crs_evidence": "Metadata.xml",
        "adds_source_resolution": False,
        "parent_terrain_feature_manifest_ref": (
            active_project["terrain_feature_manifest_ref"]
        ),
    }
    assert set(submitted["terrain_route_cache_keys"]) == {
        "schema_version",
        "derived_terrain",
        "friction",
        "cost_raster",
        "route_hypothesis",
    }

    completed = route_backend.get_run(
        project_root=project_root,
        workflow_run_id=queued.workflow_run_id,
    )

    assert completed.state is SpatialWorkflowState.COMPLETED, completed.error
    assert completed.workflow_id == TERRAIN_ROUTE_HYPOTHESIS_WORKFLOW_ID
    assert completed.candidate_only is True
    assert completed.runtime_safety_truth is False
    assert completed.operational is False
    assert len(route_transport.byte_calls) == 21
    persisted = json.loads(
        (project_root / "project.json").read_text(encoding="utf-8")
    )
    cache_key = submitted["terrain_route_cache_keys"]["route_hypothesis"]
    assert persisted["terrain_route_hypothesis_cache_key"] == cache_key
    assert persisted["terrain_route_hypothesis_authority"] == "candidate_only"
    assert persisted["terrain_route_hypothesis_candidate_only"] is True
    assert persisted["terrain_route_hypothesis_runtime_safety_truth"] is False
    assert persisted["terrain_route_hypothesis_ref"].startswith(
        f"outputs/spatial/qgis/terrain-route-cache/{cache_key}/"
    )
    for ref_key in (
        "terrain_route_hypothesis_ref",
        "terrain_route_hypothesis_visualization_ref",
        "terrain_route_hypothesis_best_path_ref",
        "terrain_route_hypothesis_processing_manifest_ref",
    ):
        assert (project_root / persisted[ref_key]).is_file()
    normalized = json.loads(
        (project_root / persisted["terrain_route_hypothesis_ref"]).read_text(
            encoding="utf-8"
        )
    )
    assert len(normalized["hypotheses"]) == 3
    assert [item["strategy"] for item in normalized["hypotheses"]] == [
        "drainage_averse",
        "balanced",
        "terrain_only_baseline",
    ]
    hypothesis = normalized["hypotheses"][0]
    assert hypothesis["authority"] == "candidate_only"
    assert hypothesis["source_type"] == "terrain_hypothesis"
    assert hypothesis["runtime_safety_truth"] is False
    navigation_project = json.loads(
        (project_root / "project.json").read_text(encoding="utf-8")
    )
    navigation = inspect_navigation_terrain_projection(
        project_root,
        navigation_project,
        project_id="qgis_worker_demo",
    )
    assert navigation.payload["projection_state"] == "ready"
    assert navigation.payload["terrain_route_hypothesis"]["status"] == (
        "candidate_ready"
    )
    assert len(
        navigation.payload["terrain_route_hypothesis"]["alternatives"]
    ) == 3
    route_boundary = navigation.payload["terrain_route_hypothesis"]["boundary"]
    assert route_boundary["candidate_only"] is True
    assert route_boundary["runtime_safety_truth"] is False
    assert all(
        band["overlay_ref"]["artifact_ref"].startswith(
            f"outputs/spatial/qgis/terrain-route-cache/{cache_key}/"
        )
        for band in hypothesis["corridor"]["bands"]
    )
    visualization = json.loads(
        (
            project_root / persisted["terrain_route_hypothesis_visualization_ref"]
        ).read_text(encoding="utf-8")
    )
    assert visualization["display_labels"] == [
        "CANDIDATE",
        "TERRAIN HYPOTHESIS",
        "NOT A VERIFIED TRAIL",
    ]
    assert len(visualization["alternative_profiles"]) == 3
    assert [item["mode"] for item in visualization["raster_overlays"]] == [
        "top_5_percent_corridor",
        "top_10_percent_corridor",
        "top_20_percent_corridor",
    ]

    cached = route_backend.start_workflow(
        project_id="qgis_worker_demo",
        project_root=project_root,
        project=persisted,
        request=SpatialAnalysisRequest(
            project_id="qgis_worker_demo",
            workflow_id=TERRAIN_ROUTE_HYPOTHESIS_WORKFLOW_ID,
            request_id="request-terrain-route-cache-hit",
        ),
    )
    assert cached.state is SpatialWorkflowState.COMPLETED
    assert cached.workflow_run_id == completed.workflow_run_id
    assert len(route_transport.post_calls) == 1


def test_qgis_backend_uses_explicit_terrain_route_endpoints_instead_of_gpx(
    tmp_path: Path,
) -> None:
    project_root, project, _ = _workspace(tmp_path)
    feature_backend = QgisSpatialBackend(
        config=QgisSpatialBackendConfig(
            enabled=True,
            worker_url="http://127.0.0.1:9876",
            worker_token=_test_access_value(),
        ),
        transport=TerrainFeatureWorkerTransport(),
        now_factory=_fixed_now,
    )
    feature_queued = feature_backend.start_workflow(
        project_id="qgis_worker_demo",
        project_root=project_root,
        project=project,
        request=SpatialAnalysisRequest(
            project_id="qgis_worker_demo",
            workflow_id=TERRAIN_FEATURE_STACK_WORKFLOW_ID,
            request_id="request-worker-demo",
        ),
    )
    assert feature_backend.get_run(
        project_root=project_root,
        workflow_run_id=feature_queued.workflow_run_id,
    ).state is SpatialWorkflowState.COMPLETED

    transport = TerrainRouteWorkerTransport()
    backend = QgisSpatialBackend(
        config=QgisSpatialBackendConfig(
            enabled=True,
            worker_url="http://127.0.0.1:9876",
            worker_token=_test_access_value(),
        ),
        transport=transport,
        now_factory=_fixed_now,
    )
    active_project = json.loads(
        (project_root / "project.json").read_text(encoding="utf-8")
    )
    route_ref = active_project.pop("compiled_mission_graph_reviewed_ref", None)
    if route_ref:
        (project_root / route_ref).unlink()
    (project_root / "project.json").write_text(
        json.dumps(active_project),
        encoding="utf-8",
    )
    endpoints = TerrainRouteEndpointSelection(
        start={"x": 121.11, "y": 23.9, "crs": "EPSG:4326", "label": "A"},
        destination={"x": 121.15, "y": 23.92, "crs": "EPSG:4326", "label": "B"},
        selection_source="dashboard_map_selection",
    )
    queued = backend.start_workflow(
        project_id="qgis_worker_demo",
        project_root=project_root,
        project=active_project,
        request=SpatialAnalysisRequest(
            project_id="qgis_worker_demo",
            workflow_id=TERRAIN_ROUTE_HYPOTHESIS_WORKFLOW_ID,
            request_id="request-explicit-terrain-route",
            terrain_route_endpoints=endpoints,
        ),
    )

    assert queued.state is SpatialWorkflowState.QUEUED, queued.error
    submitted = transport.post_calls[0][1]
    assert submitted["route_geojson"]["features"][0]["geometry"]["coordinates"] == [
        [121.11, 23.9],
        [121.15, 23.92],
    ]
    assert "request://terrain-route-endpoints.v1" in submitted["source_refs"]
    assert submitted["source_hashes"]["request://terrain-route-endpoints.v1"]
    assert "outputs/compiled_mission_graph.reviewed.json" not in submitted["source_refs"]
    assert queued.audit_trail[0]["endpoint_selection_source"] == (
        "dashboard_map_selection"
    )
    assert queued.audit_trail[0]["endpoint_source_ref"] == (
        "request://terrain-route-endpoints.v1"
    )
    assert queued.candidate_only is True
    assert queued.runtime_safety_truth is False
    assert queued.operational is False

    completed = backend.get_run(
        project_root=project_root,
        workflow_run_id=queued.workflow_run_id,
    )
    assert completed.state is SpatialWorkflowState.COMPLETED, completed.error
    persisted = json.loads(
        (project_root / "project.json").read_text(encoding="utf-8")
    )
    hypothesis_run = json.loads(
        (project_root / persisted["terrain_route_hypothesis_ref"]).read_text(
            encoding="utf-8"
        )
    )
    hypothesis = hypothesis_run["hypotheses"][0]
    assert hypothesis["start"] == {
        "x": 121.11,
        "y": 23.9,
        "crs": "EPSG:4326",
        "label": None,
    }
    assert hypothesis["destination"] == {
        "x": 121.15,
        "y": 23.92,
        "crs": "EPSG:4326",
        "label": None,
    }
    assert hypothesis["authority"] == "candidate_only"
    assert hypothesis["source_type"] == "terrain_hypothesis"
    assert hypothesis["runtime_safety_truth"] is False


def test_qgis_backend_rejects_terrain_route_when_parent_dem_resolution_is_unknown(
    tmp_path: Path,
) -> None:
    project_root, project, _ = _workspace(tmp_path)
    feature_backend = QgisSpatialBackend(
        config=QgisSpatialBackendConfig(
            enabled=True,
            worker_url="http://127.0.0.1:9876",
            worker_token=_test_access_value(),
        ),
        transport=TerrainFeatureWorkerTransport(),
        now_factory=_fixed_now,
    )
    feature_queued = feature_backend.start_workflow(
        project_id="qgis_worker_demo",
        project_root=project_root,
        project=project,
        request=SpatialAnalysisRequest(
            project_id="qgis_worker_demo",
            workflow_id=TERRAIN_FEATURE_STACK_WORKFLOW_ID,
            request_id="request-worker-demo",
        ),
    )
    feature_completed = feature_backend.get_run(
        project_root=project_root,
        workflow_run_id=feature_queued.workflow_run_id,
    )
    assert feature_completed.state is SpatialWorkflowState.COMPLETED

    active_project = json.loads(
        (project_root / "project.json").read_text(encoding="utf-8")
    )
    parent_path = project_root / active_project["terrain_feature_manifest_ref"]
    parent = json.loads(parent_path.read_text(encoding="utf-8"))
    parent["source_resolution"].pop("x_m")
    parent_path.write_text(json.dumps(parent), encoding="utf-8")
    route_transport = TerrainRouteWorkerTransport()
    route_backend = QgisSpatialBackend(
        config=QgisSpatialBackendConfig(
            enabled=True,
            worker_url="http://127.0.0.1:9876",
            worker_token=_test_access_value(),
        ),
        transport=route_transport,
        now_factory=_fixed_now,
    )

    failed = route_backend.start_workflow(
        project_id="qgis_worker_demo",
        project_root=project_root,
        project=active_project,
        request=SpatialAnalysisRequest(
            project_id="qgis_worker_demo",
            workflow_id=TERRAIN_ROUTE_HYPOTHESIS_WORKFLOW_ID,
            request_id="request-terrain-route-missing-resolution",
        ),
    )

    assert failed.state is SpatialWorkflowState.FAILED
    assert failed.error is not None
    assert failed.error.code is SpatialAnalysisErrorCode.SOURCE_UNAVAILABLE
    assert route_transport.post_calls == []


def test_pretrip_terrain_route_stage_activates_and_clears_stale_refs_fail_closed(
    tmp_path: Path,
) -> None:
    project_root, project, _ = _workspace(tmp_path)
    feature_backend = QgisSpatialBackend(
        config=QgisSpatialBackendConfig(
            enabled=True,
            worker_url="http://127.0.0.1:9876",
            worker_token=_test_access_value(),
        ),
        transport=TerrainFeatureWorkerTransport(),
        now_factory=_fixed_now,
    )
    feature_queued = feature_backend.start_workflow(
        project_id="qgis_worker_demo",
        project_root=project_root,
        project=project,
        request=SpatialAnalysisRequest(
            project_id="qgis_worker_demo",
            workflow_id=TERRAIN_FEATURE_STACK_WORKFLOW_ID,
            request_id="request-worker-demo",
        ),
    )
    assert feature_backend.get_run(
        project_root=project_root,
        workflow_run_id=feature_queued.workflow_run_id,
    ).state is SpatialWorkflowState.COMPLETED
    route_backend = QgisSpatialBackend(
        config=QgisSpatialBackendConfig(
            enabled=True,
            worker_url="http://127.0.0.1:9876",
            worker_token=_test_access_value(),
        ),
        transport=TerrainRouteWorkerTransport(),
        now_factory=_fixed_now,
    )
    request = LayerPreparationRequest(
        project_id="qgis_worker_demo",
        project_root=project_root,
        layers=("terrain",),
        qgis_terrain_workflow_timeout_s=2.0,
        qgis_terrain_poll_interval_s=0.0,
    )
    parent = {
        "status": "completed",
        "workflow_id": TERRAIN_FEATURE_STACK_WORKFLOW_ID,
        "workflow_run_id": feature_queued.workflow_run_id,
    }
    result = (
        pretrip_layer_preparation._run_qgis_terrain_route_hypothesis_after_layer_preparation(
            project_root=project_root,
            manifest={
                "project_id": "qgis_worker_demo",
                "job_id": "layer_preparation.qgis_worker_demo.terrain-route",
                "normalized_layers": ["terrain"],
                "finished_at": "2026-08-28T00:00:00Z",
            },
            request=request,
            qgis_terrain_feature_stack=parent,
            backend=route_backend,
        )
    )

    assert result["status"] == "completed"
    assert result["workflow_id"] == TERRAIN_ROUTE_HYPOTHESIS_WORKFLOW_ID
    assert result["actual_processor"] == "qgis_processing_grass"
    assert result["fallback_used"] is False
    assert result["python_dtm_processing_used"] is False
    assert result["authority"] == "candidate_only"
    assert result["source_type"] == "terrain_hypothesis"
    receipt_ref = result["output_refs"]["qgis_terrain_route_preparation_ref"]
    receipt = json.loads((project_root / receipt_ref).read_text(encoding="utf-8"))
    assert receipt["artifact_kind"] == "terrain_route_hypothesis_preparation_status"
    assert receipt["boundary"]["runtime_safety_truth"] is False
    active = json.loads((project_root / "project.json").read_text(encoding="utf-8"))
    active_ref = active["terrain_route_hypothesis_ref"]
    assert active["terrain_route_hypothesis_status"] == "completed"

    unavailable = (
        pretrip_layer_preparation._run_qgis_terrain_route_hypothesis_after_layer_preparation(
            project_root=project_root,
            manifest={
                "project_id": "qgis_worker_demo",
                "job_id": "layer_preparation.qgis_worker_demo.terrain-route.retry",
                "normalized_layers": ["terrain"],
                "finished_at": "2026-08-28T00:01:00Z",
            },
            request=request,
            qgis_terrain_feature_stack=parent,
            backend=QgisSpatialBackend(
                config=QgisSpatialBackendConfig(enabled=False),
                now_factory=_fixed_now,
            ),
        )
    )
    assert unavailable["status"] == "disabled"
    assert unavailable["error"]["code"] == "BACKEND_NOT_CONFIGURED"
    cleared = json.loads((project_root / "project.json").read_text(encoding="utf-8"))
    assert "terrain_route_hypothesis_ref" not in cleared
    assert cleared["terrain_route_hypothesis_previous_ref"] == active_ref
    assert cleared["terrain_route_hypothesis_status"] == "unavailable"
    assert cleared["terrain_route_hypothesis_candidate_only"] is True
    assert cleared["terrain_route_hypothesis_runtime_safety_truth"] is False


def test_map_preparation_stage_materializes_and_activates_grass_artifacts(
    tmp_path: Path,
) -> None:
    project_root, project, _ = _workspace(tmp_path)

    class PreparationTransport(TerrainFeatureWorkerTransport):
        request_id = ""

        def post_json(
            self,
            url: str,
            payload: dict[str, Any],
            *,
            timeout_s: float,
        ) -> Any:
            self.request_id = str(payload["request_id"])
            response = super().post_json(url, payload, timeout_s=timeout_s)
            return {**response, "request_id": self.request_id}

        def get_json(self, url: str, *, timeout_s: float) -> Any:
            response = super().get_json(url, timeout_s=timeout_s)
            if url.endswith("/status"):
                return response
            return {**response, "request_id": self.request_id}

    backend = QgisSpatialBackend(
        config=QgisSpatialBackendConfig(
            enabled=True,
            worker_url="http://127.0.0.1:9876",
            worker_token=_test_access_value(),
        ),
        transport=PreparationTransport(),
        now_factory=_fixed_now,
    )
    result = (
        pretrip_layer_preparation._run_qgis_terrain_feature_stack_after_layer_preparation(
            project_root=project_root,
            manifest={
                "project_id": "qgis_worker_demo",
                "job_id": "layer_preparation.qgis_worker_demo.20260828T000000Z",
                "normalized_layers": ["terrain"],
                "finished_at": "2026-08-28T00:00:00Z",
            },
            request=LayerPreparationRequest(
                project_id="qgis_worker_demo",
                project_root=project_root,
                layers=("terrain",),
                qgis_terrain_workflow_timeout_s=2.0,
                qgis_terrain_poll_interval_s=0.0,
            ),
            backend=backend,
        )
    )

    assert result["status"] == "completed"
    assert result["workflow_id"] == TERRAIN_FEATURE_STACK_WORKFLOW_ID
    assert result["actual_processor"] == "qgis_processing_grass"
    assert result["fallback_used"] is False
    assert result["python_dtm_processing_used"] is False
    assert result["output_refs"]["terrain_visualization_ref"].endswith(
        "/terrain_visualization.geojson"
    )
    persisted_project = json.loads(
        (project_root / "project.json").read_text(encoding="utf-8")
    )
    assert persisted_project["terrain_visualization_ref"] == (
        result["output_refs"]["terrain_visualization_ref"]
    )
    assert persisted_project["terrain_visualization_processor"] == (
        "qgis_processing_grass"
    )
    assert (project_root / persisted_project["qgis_ridge_lines_vector_ref"]).is_file()
    assert (project_root / persisted_project["qgis_valley_lines_vector_ref"]).is_file()
    assert (project_root / persisted_project["qgis_stream_network_vector_ref"]).is_file()


def test_qgis_backend_prefers_imported_golden_gpx_over_checkpoint_fallback(
    tmp_path: Path,
) -> None:
    project_root, project, _ = _workspace(tmp_path)
    filtered_ref = "normalized/routes/filtered/primary.golden.speed_filtered.gpx"
    filtered_path = project_root / filtered_ref
    filtered_path.parent.mkdir(parents=True)
    filtered_path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><name>Golden route</name><trkseg>
    <trkpt lat="23.9000" lon="121.1000"><ele>1000</ele></trkpt>
    <trkpt lat="23.9010" lon="121.1010"><ele>1010</ele></trkpt>
    <trkpt lat="23.9020" lon="121.1020"><ele>1020</ele></trkpt>
  </trkseg></trk>
</gpx>
""",
        encoding="utf-8",
    )
    bundle_ref = "normalized/routes/route_evidence_bundle.json"
    bundle_path = project_root / bundle_ref
    bundle_path.write_text(
        json.dumps(
            {
                "artifact_kind": "pretrip_historical_gpx_route_evidence_bundle",
                "project_id": "qgis_worker_demo",
                "golden_route": {
                    "filtered_geometry_ref": filtered_ref,
                    "filtered_geometry_sha256": hashlib.sha256(
                        filtered_path.read_bytes()
                    ).hexdigest(),
                    "role": "golden_route_reference",
                },
                "boundary": {
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                },
            }
        ),
        encoding="utf-8",
    )
    project = {**project, "route_evidence_bundle_ref": bundle_ref}
    (project_root / "project.json").write_text(json.dumps(project), encoding="utf-8")
    transport = AsyncWorkerTransport()
    backend = QgisSpatialBackend(
        config=QgisSpatialBackendConfig(
            enabled=True,
            worker_url="http://127.0.0.1:9876",
            worker_token=_test_access_value(),
        ),
        transport=transport,
        now_factory=_fixed_now,
    )

    backend.start_workflow(
        project_id="qgis_worker_demo",
        project_root=project_root,
        project=project,
        request=SpatialAnalysisRequest(
            project_id="qgis_worker_demo",
            workflow_id=TERRAIN_FEATURE_STACK_WORKFLOW_ID,
            request_id="request-worker-demo",
        ),
    )

    submitted = transport.post_calls[0][1]
    assert submitted["route_geojson"]["features"][0]["geometry"]["coordinates"] == [
        [121.1, 23.9],
        [121.101, 23.901],
        [121.102, 23.902],
    ]
    assert filtered_ref in submitted["source_refs"]
    assert submitted["source_hashes"][filtered_ref] == hashlib.sha256(
        filtered_path.read_bytes()
    ).hexdigest()


def test_qgis_backend_fails_closed_when_imported_golden_gpx_hash_mismatches(
    tmp_path: Path,
) -> None:
    project_root, project, _ = _workspace(tmp_path)
    filtered_ref = "normalized/routes/filtered/primary.golden.speed_filtered.gpx"
    filtered_path = project_root / filtered_ref
    filtered_path.parent.mkdir(parents=True)
    filtered_path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><trkseg>
    <trkpt lat="23.9000" lon="121.1000" />
    <trkpt lat="23.9010" lon="121.1010" />
  </trkseg></trk>
</gpx>
""",
        encoding="utf-8",
    )
    bundle_ref = "normalized/routes/route_evidence_bundle.json"
    bundle_path = project_root / bundle_ref
    bundle_path.write_text(
        json.dumps(
            {
                "project_id": "qgis_worker_demo",
                "golden_route": {
                    "filtered_geometry_ref": filtered_ref,
                    "filtered_geometry_sha256": "0" * 64,
                },
                "boundary": {
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                },
            }
        ),
        encoding="utf-8",
    )
    project = {**project, "route_evidence_bundle_ref": bundle_ref}
    (project_root / "project.json").write_text(json.dumps(project), encoding="utf-8")
    transport = AsyncWorkerTransport()
    backend = QgisSpatialBackend(
        config=QgisSpatialBackendConfig(
            enabled=True,
            worker_url="http://127.0.0.1:9876",
            worker_token=_test_access_value(),
        ),
        transport=transport,
        now_factory=_fixed_now,
    )

    run = backend.start_workflow(
        project_id="qgis_worker_demo",
        project_root=project_root,
        project=project,
        request=SpatialAnalysisRequest(
            project_id="qgis_worker_demo",
            workflow_id=TERRAIN_FEATURE_STACK_WORKFLOW_ID,
            request_id="request-worker-hash-mismatch",
        ),
    )

    assert run.state is SpatialWorkflowState.FAILED
    assert run.error is not None
    assert run.error.code is SpatialAnalysisErrorCode.INVALID_INPUT
    assert transport.post_calls == []


def test_qgis_backend_fails_closed_when_filtered_golden_gpx_hash_is_missing(
    tmp_path: Path,
) -> None:
    project_root, project, _ = _workspace(tmp_path)
    filtered_ref = "normalized/routes/filtered/primary.golden.speed_filtered.gpx"
    filtered_path = project_root / filtered_ref
    filtered_path.parent.mkdir(parents=True)
    filtered_path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><trkseg>
    <trkpt lat="23.9000" lon="121.1000" />
    <trkpt lat="23.9010" lon="121.1010" />
  </trkseg></trk>
</gpx>
""",
        encoding="utf-8",
    )
    bundle_ref = "normalized/routes/route_evidence_bundle.json"
    (project_root / bundle_ref).write_text(
        json.dumps(
            {
                "project_id": "qgis_worker_demo",
                "golden_route": {"filtered_geometry_ref": filtered_ref},
                "boundary": {
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                },
            }
        ),
        encoding="utf-8",
    )
    project = {**project, "route_evidence_bundle_ref": bundle_ref}
    (project_root / "project.json").write_text(json.dumps(project), encoding="utf-8")
    transport = AsyncWorkerTransport()
    backend = QgisSpatialBackend(
        config=QgisSpatialBackendConfig(
            enabled=True,
            worker_url="http://127.0.0.1:9876",
            worker_token=_test_access_value(),
        ),
        transport=transport,
        now_factory=_fixed_now,
    )

    run = backend.start_workflow(
        project_id="qgis_worker_demo",
        project_root=project_root,
        project=project,
        request=SpatialAnalysisRequest(
            project_id="qgis_worker_demo",
            workflow_id=TERRAIN_FEATURE_STACK_WORKFLOW_ID,
            request_id="request-worker-missing-filtered-hash",
        ),
    )

    assert run.state is SpatialWorkflowState.FAILED
    assert run.error is not None
    assert run.error.code is SpatialAnalysisErrorCode.INVALID_INPUT
    assert transport.post_calls == []


def test_qgis_backend_cancellation_is_forwarded_to_worker(tmp_path: Path) -> None:
    project_root, project, _ = _workspace(tmp_path)
    transport = AsyncWorkerTransport()
    backend = QgisSpatialBackend(
        config=QgisSpatialBackendConfig(
            enabled=True,
            worker_url="http://127.0.0.1:9876",
            worker_token=_test_access_value(),
        ),
        transport=transport,
        now_factory=_fixed_now,
    )
    queued = backend.start_workflow(
        project_id="qgis_worker_demo",
        project_root=project_root,
        project=project,
        request=SpatialAnalysisRequest(project_id="qgis_worker_demo", request_id="request-worker-demo"),
    )
    cancelled = backend.cancel_workflow(
        project_root=project_root,
        workflow_run_id=queued.workflow_run_id,
    )
    assert cancelled.state is SpatialWorkflowState.CANCELLED
    assert transport.post_calls[-1][0].endswith("/workflows/qgis-worker-demo-run/cancel")


def test_http_transport_attaches_bearer_token(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}

    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_: Any) -> None:
            return None

        def read(self) -> bytes:
            return b'{"ok":true}'

    def fake_urlopen(request: Any, *, timeout: float) -> Response:
        captured["authorization"] = request.get_header("Authorization")
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("qgis_spatial_backend.urlopen", fake_urlopen)
    payload = QgisMcpHttpTransport(auth_token=_test_access_value()).get_json(
        "http://127.0.0.1:9876/status",
        timeout_s=2.5,
    )
    assert payload == {"ok": True}
    assert captured["authorization"] == f"Bearer {_test_access_value()}"
    assert captured["timeout"] == 2.5


def test_qgis_maplibre_limit_uses_canonical_compact_json_size() -> None:
    point = [121.123456, 24.123456]
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "MultiLineString",
                    "coordinates": [[point] * 230_000],
                },
                "properties": {
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                    "operational": False,
                },
            }
        ],
    }

    assert len(_compact_json_bytes(payload)) < 8 * 1024 * 1024
    assert len(_json_bytes(payload)) > 8 * 1024 * 1024
    assert _validated_candidate_geojson(payload)["features"]
