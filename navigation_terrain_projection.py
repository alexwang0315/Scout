from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from pydantic import ValidationError

import navigation_terrain_projection_expert as expert_projection
from navigation_terrain_projection_expert import (
    MAX_ROUTE_TERRAIN_EVENTS,
    empty_route_terrain_events as _empty_route_terrain_events,
    empty_terrain_hierarchy as _empty_terrain_hierarchy,
    normalize_route_terrain_events as _normalize_route_terrain_events,
    normalize_terrain_hierarchy as _normalize_terrain_hierarchy,
)
from navigation_terrain_workspace import (
    WorkspaceTerrainGrid,
    WorkspaceTerrainEvidenceError,
    build_workspace_route_terrain_events,
    build_workspace_route_topology,
    build_workspace_source_ledger,
    build_workspace_terrain_hierarchy,
    extract_dem_structure_candidates,
    load_workspace_terrain_grid,
    project_route_sample_points_twd97,
    route_sample_points,
)
from navigation_terrain_validation import build_terrain_validation_receipt
from navigation_terrain_mesh import (
    build_bounded_terrain_mesh,
    empty_bounded_terrain_mesh,
)
from navigation_terrain_passage_patterns import (
    build_terrain_passage_prior,
    empty_terrain_passage_prior,
    observed_paths_from_overpass,
    observed_paths_from_projected_route,
    observed_paths_from_reference_tracks,
)
from terrain_route_hypothesis_models import (
    TERRAIN_ROUTE_BAND_MODEL,
    TERRAIN_ROUTE_BAND_SEMANTICS,
    TERRAIN_ROUTE_PATH_BAND_RELATIONSHIP,
    TERRAIN_ROUTE_PATH_MODEL,
    TERRAIN_ROUTE_PATH_SEMANTICS,
    TerrainRouteHypothesisRun,
    TerrainRouteRunStatus,
)


NAVIGATION_TERRAIN_SCHEMA_VERSION = "scout_navigation_terrain_intelligence.v1"
MAX_TERRAIN_HIERARCHY_EDGES = expert_projection.MAX_TERRAIN_HIERARCHY_EDGES
MAX_ROUTE_SAMPLE_POINTS = 240
MAX_RISK_CANDIDATES = 50
SUPPORTED_OVERLAY_MODES = (
    "contours",
    "hillshade",
    "slope_shading",
    "elevation_tint",
)
_TERRAIN_BUNDLE_CACHE: dict[
    tuple[Any, ...],
    tuple[dict[str, Any], dict[str, Any]],
] = {}
_STANDARD_GIS_PRIMARY_REASON = (
    "QGIS/GRASS standard terrain artifacts are primary. Scout local Python DEM "
    "morphology was not rebuilt for this projection."
)


class NavigationTerrainProjectionError(ValueError):
    """Raised when a workspace terrain reference is unsafe or malformed."""


@dataclass(frozen=True)
class _NavigationTerrainInputs:
    terrain: dict[str, Any]
    route_samples: dict[str, Any]
    risk_candidates: dict[str, Any]
    route_points: list[dict[str, Any]]
    projected_route_points: list[dict[str, Any]]
    workspace_grid: WorkspaceTerrainGrid | None
    workspace_grid_error: str | None


def build_navigation_terrain_projection(
    project_root: Path,
    project: dict[str, Any],
    *,
    project_id: str,
) -> dict[str, Any]:
    """Build a bounded candidate terrain projection for the Dashboard."""

    terrain_ref = _optional_ref(project.get("terrain_visualization_ref"))
    route_samples_ref = _optional_ref(project.get("terrain_route_samples_ref"))
    risk_candidates_ref = _optional_ref(project.get("terrain_risk_candidates_ref"))
    terrain_route_hypothesis = _terrain_route_hypothesis_projection(
        project_root,
        project,
        project_id=project_id,
    )

    inputs = _load_navigation_terrain_inputs(
        project_root,
        project,
        terrain_ref=terrain_ref,
        route_samples_ref=route_samples_ref,
        risk_candidates_ref=risk_candidates_ref,
    )
    terrain = inputs.terrain
    route_samples = inputs.route_samples
    risk_candidates = inputs.risk_candidates
    standard_gis_primary = _is_standard_gis_primary(project, terrain)

    overlays = _normalize_overlays(terrain, project_id=project_id)
    bounded_route_samples, source_route_sample_count = _normalize_route_samples(
        route_samples
    )
    bounded_risk_candidates, source_risk_candidate_count = _normalize_risk_candidates(
        risk_candidates
    )
    if standard_gis_primary:
        workspace_structures = _standard_gis_structure_projection(terrain)
        terrain_mesh = empty_bounded_terrain_mesh(_STANDARD_GIS_PRIMARY_REASON)
    else:
        workspace_structures = _workspace_structure_projection(
            project_root,
            project,
            inputs,
        )
        terrain_mesh = _workspace_terrain_mesh_projection(project, inputs)
    source_ledger = _workspace_source_ledger_projection(
        project_root,
        project,
    )
    route_topology = _workspace_route_topology_projection(
        project_root,
        project,
        workspace_structures,
        inputs,
    )
    if standard_gis_primary:
        raw_hierarchy = _empty_terrain_hierarchy(_STANDARD_GIS_PRIMARY_REASON)
        raw_route_events = _empty_route_terrain_events(_STANDARD_GIS_PRIMARY_REASON)
    else:
        raw_hierarchy, raw_route_events = _workspace_terrain_bundle(
            project_root,
            project,
            inputs,
        )
    terrain_hierarchy = _normalize_terrain_hierarchy(raw_hierarchy)
    route_terrain_events = _normalize_route_terrain_events(raw_route_events)
    if standard_gis_primary:
        terrain_passage_prior = empty_terrain_passage_prior(
            _STANDARD_GIS_PRIMARY_REASON
        )
    else:
        terrain_passage_prior = _workspace_terrain_passage_prior(
            project_root,
            project,
            inputs,
            raw_hierarchy,
        )
    terrain_validation = _workspace_terrain_validation(
        project_root,
        project,
        raw_hierarchy,
    )
    terrain_counts = terrain.get("counts", {}) if isinstance(terrain, dict) else {}
    dtm_grid = terrain.get("dtm_grid", {}) if isinstance(terrain, dict) else {}
    bbox_wgs84 = _normalize_bbox(dtm_grid.get("bbox_wgs84"))
    available_overlay_modes = [overlay["mode"] for overlay in overlays]

    missing_artifacts = [
        label
        for label, payload in (
            ("terrain_visualization", terrain),
            ("terrain_route_samples", route_samples),
            ("terrain_risk_candidates", risk_candidates),
            (
                "terrain_route_hypothesis",
                terrain_route_hypothesis
                if terrain_route_hypothesis.get("status") == "candidate_ready"
                else {},
            ),
        )
        if not payload
    ]
    if terrain and route_samples:
        status = (
            "ready_with_terrain_hierarchy"
            if terrain_hierarchy.get("edges")
            else "ready_with_candidate_structures"
            if workspace_structures.get("points")
            else "ready_with_structure_gaps"
            if not terrain.get("features")
            else "ready"
        )
    elif terrain or route_samples or risk_candidates:
        status = "partial"
    else:
        status = "unavailable"

    return {
        "schema_version": NAVIGATION_TERRAIN_SCHEMA_VERSION,
        "artifact_kind": "navigation_terrain_intelligence_projection",
        "project_id": project_id,
        "status": status,
        "terrain_processing": _terrain_processing_summary(
            terrain,
            standard_gis_primary=standard_gis_primary,
        ),
        "terrain_surface": {
            "bbox_wgs84": bbox_wgs84,
            "crs": dtm_grid.get("crs"),
            "cell_resolution_m": _finite_number(dtm_grid.get("cell_resolution_m")),
            "source_dtm_tile_count": _nonnegative_int(
                terrain_counts.get("source_dtm_tile_count")
            ),
            "selected_cell_count": _nonnegative_int(
                dtm_grid.get("selected_cell_count")
            ),
            "contour_marker_count": _nonnegative_int(
                terrain_counts.get("contour_marker_count")
            ),
            "slope_class_counts": _normalize_count_map(
                terrain_counts.get("slope_class_counts")
            ),
            "overlays": overlays,
            "available_overlay_modes": available_overlay_modes,
        },
        "terrain_mesh": terrain_mesh,
        "route_samples": {
            "source_count": source_route_sample_count,
            "rendered_count": len(bounded_route_samples),
            "max_rendered_count": MAX_ROUTE_SAMPLE_POINTS,
            "sampling": "deterministic_even_spacing",
            "points": bounded_route_samples,
        },
        "risk_candidates": {
            "source_count": source_risk_candidate_count,
            "rendered_count": len(bounded_risk_candidates),
            "max_rendered_count": MAX_RISK_CANDIDATES,
            "points": bounded_risk_candidates,
            "review_state": "human_review_required",
        },
        "terrain_validation": terrain_validation,
        "feature_extraction": {
            "ridge": _structure_projection(
                terrain,
                workspace_structures,
                "ridge",
                "No QGIS/GRASS ridge candidate vector is available.",
            ),
            "valley": _structure_projection(
                terrain,
                workspace_structures,
                "valley",
                "No QGIS/GRASS valley or drainage candidate vector is available.",
            ),
            "saddle": _structure_projection(
                terrain,
                workspace_structures,
                "saddle",
                "No standard GIS saddle candidate vector is available.",
            ),
            "steep_slope": {
                "status": (
                    "available_as_raster"
                    if "slope_shading" in available_overlay_modes
                    else "not_prepared"
                ),
                "source_ref": _source_ref_or_none(
                    project.get("terrain_slope_shading_overlay_ref")
                ),
                "candidate_only": True,
                "runtime_safety_truth": False,
            },
            "terrain_risk": {
                "status": (
                    "candidate_points" if bounded_risk_candidates else "not_prepared"
                ),
                "count": source_risk_candidate_count,
                "source_ref": risk_candidates_ref,
                "human_review_required": True,
                "candidate_only": True,
                "runtime_safety_truth": False,
            },
        },
        "terrain_structures": workspace_structures,
        "terrain_hierarchy": terrain_hierarchy,
        "terrain_passage_prior": terrain_passage_prior,
        "route_terrain_events": route_terrain_events,
        "source_ledger": source_ledger,
        "route_topology": route_topology,
        "terrain_route_hypothesis": terrain_route_hypothesis,
        "missing_artifacts": missing_artifacts,
        "source_refs": [
            ref
            for ref in (
                terrain_ref,
                route_samples_ref,
                risk_candidates_ref,
                *terrain_route_hypothesis.get("source_refs", []),
            )
            if ref
        ],
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "safe_or_walkable": "not_determined",
            "raw_dem_embedded": False,
            "raw_gpx_embedded": False,
            "phase1_runtime_mutation_allowed": False,
            "safety_api_called": False,
            "human_review_required": True,
        },
    }


def _terrain_route_hypothesis_projection(
    project_root: Path,
    project: dict[str, Any],
    *,
    project_id: str,
) -> dict[str, Any]:
    boundary = {
        "authority": "candidate_only",
        "source_type": "terrain_hypothesis",
        "candidate_only": True,
        "runtime_safety_truth": False,
        "operational": False,
        "safe_or_walkable": "not_determined",
        "promotion_allowed": False,
        "human_review_required": True,
    }
    hypothesis_ref = _optional_ref(project.get("terrain_route_hypothesis_ref"))
    visualization_ref = _optional_ref(
        project.get("terrain_route_hypothesis_visualization_ref")
    )
    if not hypothesis_ref or not visualization_ref:
        return {
            "status": (
                "unavailable"
                if project.get("terrain_route_hypothesis_status") == "unavailable"
                else "not_prepared"
            ),
            "reason": (
                "typed_terrain_route_hypothesis_unavailable"
                if project.get("terrain_route_hypothesis_status") == "unavailable"
                else "terrain_route_hypothesis_not_prepared"
            ),
            "display_labels": [
                "CANDIDATE",
                "TERRAIN HYPOTHESIS",
                "NOT A VERIFIED TRAIL",
            ],
            "source_refs": [],
            "boundary": boundary,
        }
    try:
        hypothesis_path = _bounded_project_ref_path(project_root, hypothesis_ref)
        visualization_path = _bounded_project_ref_path(
            project_root, visualization_ref
        )
        hypothesis_sha = _sha256_or_none(
            project.get("terrain_route_hypothesis_sha256")
        )
        visualization_sha = _sha256_or_none(
            project.get("terrain_route_hypothesis_visualization_sha256")
        )
        if (
            hypothesis_sha is None
            or visualization_sha is None
            or _file_sha256(hypothesis_path) != hypothesis_sha
            or _file_sha256(visualization_path) != visualization_sha
        ):
            raise NavigationTerrainProjectionError(
                "terrain route hypothesis artifact hash mismatch"
            )
        hypothesis_run = TerrainRouteHypothesisRun.model_validate(
            _read_json_ref(project_root, hypothesis_ref)
        )
        visualization = _read_json_ref(project_root, visualization_ref)
        if (
            hypothesis_run.status is not TerrainRouteRunStatus.COMPLETED
            or len(hypothesis_run.hypotheses) != 1
        ):
            raise NavigationTerrainProjectionError(
                "terrain route hypothesis is not one completed candidate"
            )
        hypothesis = hypothesis_run.hypotheses[0]
        if (
            project.get("terrain_route_hypothesis_cache_key")
            != hypothesis.provenance.cache_key
            or project.get("terrain_route_hypothesis_authority")
            != "candidate_only"
            or project.get("terrain_route_hypothesis_candidate_only") is not True
            or project.get("terrain_route_hypothesis_runtime_safety_truth") is not False
        ):
            raise NavigationTerrainProjectionError(
                "terrain route hypothesis project activation is inconsistent"
            )
        features = _normalized_terrain_route_features(visualization)
        overlays = _normalized_terrain_route_overlays(
            visualization,
            project_id=project_id,
            expected_bands=hypothesis.corridor.bands
            if hypothesis.corridor is not None
            else (),
        )
        if hypothesis.corridor is None or len(overlays) != len(
            hypothesis.corridor.bands
        ):
            raise NavigationTerrainProjectionError(
                "terrain route corridor overlays are incomplete"
            )
        positive_evidence = [
            item.code
            for item in hypothesis.reasons
            if item.polarity.value == "positive"
        ]
        negative_evidence = [
            item.code
            for item in hypothesis.reasons
            if item.polarity.value == "negative"
        ]
        return {
            "status": "candidate_ready",
            "candidate": hypothesis.id,
            "label": hypothesis.label,
            "display_labels": list(visualization["display_labels"]),
            "path_model": {
                "id": hypothesis.path_model,
                "semantics": hypothesis.path_semantics,
                "display_name": "minimum anisotropic model-cost trace",
            },
            "best_path": {
                "type": "FeatureCollection",
                "features": features,
                "semantics": hypothesis.path_semantics,
            },
            "corridor": {
                "relative_cost_formula": hypothesis.corridor.relative_cost_formula,
                "cost_surface_kind": hypothesis.corridor.cost_surface_kind,
                "band_model": {
                    "id": hypothesis.corridor.band_model,
                    "semantics": hypothesis.corridor.threshold_semantics,
                    "display_name": (
                        "symmetric macro-terrain detour-score percentile cells"
                    ),
                },
                "path_relationship": hypothesis.corridor.path_relationship,
                "threshold_semantics": hypothesis.corridor.threshold_semantics,
                "bands": [
                    {
                        "name": band.name,
                        "percentile": band.percentile,
                        "max_relative_corridor_cost": (
                            band.max_relative_corridor_cost
                        ),
                        "cell_count": band.cell_count,
                        "contains_best_path": band.contains_best_path,
                        "contains_minimum_model_cost_trace": (
                            band.contains_best_path
                        ),
                        "threshold_comparison_operator": (
                            band.threshold_comparison_operator
                        ),
                        "tie_handling": band.tie_handling,
                        "best_path_union_applied": band.best_path_union_applied,
                        "path_relationship": band.path_relationship,
                        "runtime_href": overlay["runtime_href"],
                        "bbox_wgs84": overlay["bbox_wgs84"],
                        "default_visible": overlay["default_visible"],
                        "opacity": overlay["opacity"],
                        "candidate_only": True,
                        "runtime_safety_truth": False,
                    }
                    for band, overlay in zip(
                        hypothesis.corridor.bands, overlays, strict=True
                    )
                ],
                "overlays": overlays,
            },
            "relative_score": hypothesis.metrics.relative_score,
            "relative_cost": hypothesis.metrics.relative_cost,
            "metrics": hypothesis.metrics.model_dump(mode="json"),
            "positive_evidence": positive_evidence,
            "negative_evidence": negative_evidence,
            "evidence": [
                item.model_dump(mode="json") for item in hypothesis.reasons
            ],
            "unknowns": [
                item.model_dump(mode="json") for item in hypothesis.unknowns
            ],
            "dem_resolution_m": hypothesis.dem_resolution_m,
            "resolution_class": hypothesis.resolution_class.value,
            "confidence_limits": list(hypothesis.confidence_limits),
            "cost_model_version": hypothesis.cost_model_version,
            "provenance": {
                "dem_dataset_id": hypothesis.provenance.dem_dataset_id,
                "dem_sha256": hypothesis.provenance.dem_sha256,
                "dem_resolution_m": hypothesis.provenance.dem_resolution_m,
                "dem_crs": hypothesis.provenance.dem_crs,
                "cost_model_version": hypothesis.provenance.cost_model_version,
                "weights": hypothesis.provenance.weights,
                "weights_hash": hypothesis.provenance.weights_hash,
                "grass_version": hypothesis.provenance.grass_version,
                "qgis_version": hypothesis.provenance.qgis_version,
                "backend_id": hypothesis.provenance.backend_id,
                "modules_executed": hypothesis.provenance.modules_executed[:32],
                "timestamp": hypothesis.provenance.timestamp,
                "algorithm_version": hypothesis.provenance.algorithm_version,
                "cache_key": hypothesis.provenance.cache_key,
                "cache_keys": hypothesis.provenance.cache_keys,
                "path_model": hypothesis.provenance.processing_manifest.get(
                    "path_model",
                    {
                        "id": TERRAIN_ROUTE_PATH_MODEL,
                        "semantics": TERRAIN_ROUTE_PATH_SEMANTICS,
                    },
                ),
                "band_model": hypothesis.provenance.processing_manifest.get(
                    "band_model",
                    {
                        "id": TERRAIN_ROUTE_BAND_MODEL,
                        "semantics": TERRAIN_ROUTE_BAND_SEMANTICS,
                    },
                ),
                "path_band_relationship": (
                    hypothesis.provenance.processing_manifest.get(
                        "path_band_relationship",
                        TERRAIN_ROUTE_PATH_BAND_RELATIONSHIP,
                    )
                ),
            },
            "uncertainty_statement": (
                "依目前 DEM 與地形證據，這個區域較像合理的候選通行 "
                "corridor；這不表示實地存在步道、可通行或安全。"
            ),
            "source_refs": [hypothesis_ref, visualization_ref],
            "boundary": boundary,
        }
    except (
        OSError,
        ValueError,
        ValidationError,
        NavigationTerrainProjectionError,
    ):
        return {
            "status": "unavailable",
            "reason": "terrain_route_hypothesis_validation_failed",
            "display_labels": [
                "CANDIDATE",
                "TERRAIN HYPOTHESIS",
                "NOT A VERIFIED TRAIL",
            ],
            "source_refs": [],
            "boundary": boundary,
        }


def _normalized_terrain_route_features(
    visualization: dict[str, Any],
) -> list[dict[str, Any]]:
    required_labels = {
        "CANDIDATE",
        "TERRAIN HYPOTHESIS",
        "NOT A VERIFIED TRAIL",
    }
    if (
        visualization.get("schema_version")
        != "scout_terrain_route_visualization.v0_2"
        or visualization.get("path_model")
        != {
            "id": TERRAIN_ROUTE_PATH_MODEL,
            "semantics": TERRAIN_ROUTE_PATH_SEMANTICS,
            "display_name": "minimum anisotropic model-cost trace",
        }
        or not isinstance(visualization.get("band_model"), dict)
        or visualization["band_model"].get("id") != TERRAIN_ROUTE_BAND_MODEL
        or visualization["band_model"].get("semantics")
        != TERRAIN_ROUTE_BAND_SEMANTICS
        or visualization.get("path_band_relationship")
        != TERRAIN_ROUTE_PATH_BAND_RELATIONSHIP
        or visualization.get("artifact_kind")
        != "terrain_route_hypothesis_visualization"
        or visualization.get("authority") != "candidate_only"
        or visualization.get("source_type") != "terrain_hypothesis"
        or visualization.get("candidate_only") is not True
        or visualization.get("runtime_safety_truth") is not False
        or visualization.get("operational") is not False
        or not required_labels.issubset(set(visualization.get("display_labels") or []))
    ):
        raise NavigationTerrainProjectionError(
            "terrain route visualization authority is invalid"
        )
    raw_features = visualization.get("features")
    if not isinstance(raw_features, list) or not 1 <= len(raw_features) <= 8:
        raise NavigationTerrainProjectionError(
            "terrain route visualization feature count is invalid"
        )
    features: list[dict[str, Any]] = []
    for feature in raw_features:
        properties = feature.get("properties") if isinstance(feature, dict) else None
        geometry = feature.get("geometry") if isinstance(feature, dict) else None
        if (
            not isinstance(properties, dict)
            or properties.get("authority") != "candidate_only"
            or properties.get("source_type") != "terrain_hypothesis"
            or properties.get("candidate_only") is not True
            or properties.get("runtime_safety_truth") is not False
            or properties.get("operational") is not False
            or not isinstance(geometry, dict)
            or geometry.get("type") not in {"LineString", "Point"}
            or (
                geometry.get("type") == "LineString"
                and (
                    properties.get("path_model") != TERRAIN_ROUTE_PATH_MODEL
                    or properties.get("path_semantics")
                    != TERRAIN_ROUTE_PATH_SEMANTICS
                    or properties.get("path_band_relationship")
                    != TERRAIN_ROUTE_PATH_BAND_RELATIONSHIP
                )
            )
        ):
            raise NavigationTerrainProjectionError(
                "terrain route visualization feature attempted promotion"
            )
        features.append(
            {
                "type": "Feature",
                "geometry": geometry,
                "properties": properties,
            }
        )
    return features


def _normalized_terrain_route_overlays(
    visualization: dict[str, Any],
    *,
    project_id: str,
    expected_bands: Any,
) -> list[dict[str, Any]]:
    raw_overlays = visualization.get("raster_overlays")
    if not isinstance(raw_overlays, list):
        return []
    by_mode = {
        item.get("mode"): item
        for item in raw_overlays
        if isinstance(item, dict) and isinstance(item.get("mode"), str)
    }
    overlays: list[dict[str, Any]] = []
    for band in expected_bands:
        item = by_mode.get(band.name)
        if (
            not isinstance(item, dict)
            or item.get("candidate_only") is not True
            or item.get("runtime_safety_truth") is not False
            or item.get("operational") is not False
            or not isinstance(item.get("contains_best_path"), bool)
            or item.get("contains_best_path") is not band.contains_best_path
            or item.get("sha256")
            != (band.overlay_ref.sha256 if band.overlay_ref else None)
        ):
            raise NavigationTerrainProjectionError(
                "terrain route corridor overlay binding is invalid"
            )
        overlays.append(
            {
                "mode": band.name,
                "runtime_href": (
                    f"/admin/pretrip/projects/{quote(project_id, safe='')}"
                    f"/terrain-route-overlays/{quote(band.name, safe='')}.png"
                ),
                "source_ref": _source_ref_or_none(item.get("source_path")),
                "bbox_wgs84": _normalize_bbox(item.get("bbox_wgs84")),
                "pixel_width": _positive_int_or_none(item.get("pixel_width")),
                "pixel_height": _positive_int_or_none(item.get("pixel_height")),
                "sha256": _sha256_or_none(item.get("sha256")),
                "percentile": _finite_number(item.get("percentile")),
                "default_visible": item.get("default_visible") is True,
                "opacity": _overlay_opacity_or_none(item.get("opacity")),
                "threshold_semantics": item.get("threshold_semantics"),
                "candidate_only": True,
                "runtime_safety_truth": False,
                "operational": False,
            }
        )
    return overlays


def _bounded_project_ref_path(project_root: Path, ref: str) -> Path:
    path = (project_root / ref).resolve()
    try:
        path.relative_to(project_root.resolve())
    except ValueError as exc:
        raise NavigationTerrainProjectionError(
            "unsafe terrain route hypothesis artifact reference"
        ) from exc
    if not path.is_file():
        raise NavigationTerrainProjectionError(
            "terrain route hypothesis artifact is unavailable"
        )
    return path


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _workspace_terrain_mesh_projection(
    project: dict[str, Any],
    inputs: _NavigationTerrainInputs,
) -> dict[str, Any]:
    if inputs.workspace_grid is None:
        return empty_bounded_terrain_mesh(
            inputs.workspace_grid_error or "Workspace DEM grid is not prepared."
        )
    refs = [
        ref
        for key in ("terrain_visualization_ref", "dtm_coverage_summary_ref")
        if (ref := _optional_ref(project.get(key))) is not None
    ]
    try:
        return build_bounded_terrain_mesh(
            inputs.workspace_grid,
            source_refs=refs,
        )
    except ValueError as exc:
        return empty_bounded_terrain_mesh(str(exc))


def _workspace_terrain_passage_prior(
    project_root: Path,
    project: dict[str, Any],
    inputs: _NavigationTerrainInputs,
    raw_hierarchy: dict[str, Any],
) -> dict[str, Any]:
    if inputs.workspace_grid is None:
        return empty_terrain_passage_prior(
            inputs.workspace_grid_error or "Workspace DEM grid is not prepared."
        )
    route_ref = _optional_ref(project.get("terrain_route_samples_ref"))
    reference_ref = _optional_ref(project.get("reference_track_display_geometry_ref"))
    overpass_ref = _optional_ref(project.get("overpass_vector_evidence_ref"))
    observed_paths = []
    source_refs = []
    if route_ref:
        source_refs.append(route_ref)
        observed_paths.extend(
            observed_paths_from_projected_route(
                inputs.projected_route_points,
                source_ref=route_ref,
            )
        )
    if reference_ref:
        source_refs.append(reference_ref)
        observed_paths.extend(
            observed_paths_from_reference_tracks(
                _read_json_ref(project_root, reference_ref),
                source_ref=reference_ref,
            )
        )
    if overpass_ref:
        source_refs.append(overpass_ref)
        observed_paths.extend(
            observed_paths_from_overpass(
                _read_json_ref(project_root, overpass_ref),
                source_ref=overpass_ref,
                bbox_twd97=inputs.workspace_grid.bbox_twd97,
            )
        )
    terrain_ref = _optional_ref(project.get("terrain_visualization_ref"))
    if terrain_ref:
        source_refs.append(terrain_ref)
    return build_terrain_passage_prior(
        inputs.workspace_grid,
        observed_paths=observed_paths,
        terrain_hierarchy=raw_hierarchy,
        source_refs=source_refs,
    )


def _workspace_terrain_bundle(
    project_root: Path,
    project: dict[str, Any],
    inputs: _NavigationTerrainInputs,
) -> tuple[dict[str, Any], dict[str, Any]]:
    cache_key = _terrain_bundle_cache_key(project_root, project)
    cached = _TERRAIN_BUNDLE_CACHE.get(cache_key)
    if cached is not None:
        return cached
    if inputs.workspace_grid is None:
        reason = inputs.workspace_grid_error or "Workspace DEM grid is not prepared."
        return _empty_terrain_hierarchy(reason), _empty_route_terrain_events(reason)
    try:
        hierarchy = build_workspace_terrain_hierarchy(
            project_root,
            project,
            workspace_grid=inputs.workspace_grid,
            relief_threshold_m=6.0,
            minimum_component_cells=5,
            max_edges_per_network=120,
        )
        route_events = build_workspace_route_terrain_events(
            project_root,
            project,
            hierarchy,
            projected_route_points=inputs.projected_route_points,
            proximity_tolerance_m=50.0,
            max_events=MAX_ROUTE_TERRAIN_EVENTS,
        )
    except WorkspaceTerrainEvidenceError as exc:
        hierarchy = _empty_terrain_hierarchy(str(exc))
        route_events = _empty_route_terrain_events(str(exc))
    if len(_TERRAIN_BUNDLE_CACHE) >= 8:
        _TERRAIN_BUNDLE_CACHE.pop(next(iter(_TERRAIN_BUNDLE_CACHE)))
    _TERRAIN_BUNDLE_CACHE[cache_key] = (hierarchy, route_events)
    return hierarchy, route_events


def _workspace_terrain_validation(
    project_root: Path,
    project: dict[str, Any],
    hierarchy: dict[str, Any],
) -> dict[str, Any]:
    raw_refs = project.get("terrain_expert_annotation_refs", [])
    if not isinstance(raw_refs, list):
        raw_refs = []
    annotation_refs = list(
        dict.fromkeys(
            ref
            for item in raw_refs
            if (ref := _optional_ref(item)) is not None
        )
    )[:32]
    reference_sets = [
        payload
        for ref in annotation_refs
        if (payload := _read_json_ref(project_root, ref))
    ]
    policy_ref = _optional_ref(project.get("terrain_acceptance_policy_ref"))
    policy = _read_json_ref(project_root, policy_ref) if policy_ref else None
    return build_terrain_validation_receipt(
        hierarchy,
        reference_sets,
        acceptance_policy=policy,
    )


def _load_navigation_terrain_inputs(
    project_root: Path,
    project: dict[str, Any],
    *,
    terrain_ref: str | None,
    route_samples_ref: str | None,
    risk_candidates_ref: str | None,
) -> _NavigationTerrainInputs:
    terrain = _read_json_ref(project_root, terrain_ref)
    route_samples = _read_json_ref(project_root, route_samples_ref)
    risk_candidates = _read_json_ref(project_root, risk_candidates_ref)
    parsed_route_points = route_sample_points(route_samples)
    projected_route_points = project_route_sample_points_twd97(
        parsed_route_points
    )
    if _is_standard_gis_primary(project, terrain):
        workspace_grid = None
        workspace_grid_error = _STANDARD_GIS_PRIMARY_REASON
    else:
        coverage_ref = _optional_ref(project.get("dtm_coverage_summary_ref"))
        coverage = _read_json_ref(project_root, coverage_ref)
        try:
            workspace_grid = load_workspace_terrain_grid(
                project_root,
                project,
                terrain_payload=terrain,
                coverage_payload=coverage,
            )
            workspace_grid_error = None
        except WorkspaceTerrainEvidenceError as exc:
            workspace_grid = None
            workspace_grid_error = str(exc)
    return _NavigationTerrainInputs(
        terrain=terrain,
        route_samples=route_samples,
        risk_candidates=risk_candidates,
        route_points=parsed_route_points,
        projected_route_points=projected_route_points,
        workspace_grid=workspace_grid,
        workspace_grid_error=workspace_grid_error,
    )


def _terrain_bundle_cache_key(
    project_root: Path,
    project: dict[str, Any],
) -> tuple[Any, ...]:
    refs = [
        _optional_ref(project.get(key))
        for key in (
            "terrain_visualization_ref",
            "dtm_coverage_summary_ref",
            "terrain_route_samples_ref",
        )
    ]
    artifact_state = []
    for ref in refs:
        if not ref:
            artifact_state.append((ref, None, None))
            continue
        path = (project_root / ref).resolve()
        try:
            path.relative_to(project_root.resolve())
            stat = path.stat()
            artifact_state.append((ref, stat.st_mtime_ns, stat.st_size))
        except (ValueError, OSError):
            artifact_state.append((ref, None, None))
    return (str(project_root.resolve()), *artifact_state)


def _read_json_ref(project_root: Path, ref: str | None) -> dict[str, Any]:
    if not ref:
        return {}
    candidate = (project_root / ref).resolve()
    try:
        candidate.relative_to(project_root.resolve())
    except ValueError as exc:
        raise NavigationTerrainProjectionError(
            "unsafe navigation terrain artifact reference"
        ) from exc
    if not candidate.exists():
        return {}
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise NavigationTerrainProjectionError(
            f"invalid navigation terrain artifact: {ref}"
        ) from exc
    if not isinstance(payload, dict):
        raise NavigationTerrainProjectionError(
            f"navigation terrain artifact must be an object: {ref}"
        )
    return payload


def _optional_ref(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _is_standard_gis_primary(
    project: dict[str, Any],
    terrain: dict[str, Any],
) -> bool:
    visualization_spec = terrain.get("visualization_spec")
    boundary = terrain.get("boundary")
    if not isinstance(visualization_spec, dict) or not isinstance(boundary, dict):
        return False
    return (
        project.get("terrain_visualization_processor") == "qgis_processing_grass"
        and visualization_spec.get("actual_processor") == "qgis_processing_grass"
        and visualization_spec.get("standard_processor_completed") is True
        and visualization_spec.get("fallback_used") is False
        and visualization_spec.get("python_dtm_processing_used") is False
        and boundary.get("candidate_only") is True
        and boundary.get("runtime_safety_truth") is False
        and boundary.get("operational") is False
    )


def _terrain_processing_summary(
    terrain: dict[str, Any],
    *,
    standard_gis_primary: bool,
) -> dict[str, Any]:
    visualization_spec = terrain.get("visualization_spec")
    if not isinstance(visualization_spec, dict):
        visualization_spec = {}
    if standard_gis_primary:
        return {
            "primary_processor": "qgis_processing_grass",
            "standard_processor_completed": True,
            "fallback_used": False,
            "python_dtm_processing_used": False,
            "local_python_comparator": "not_run",
        }
    return {
        "primary_processor": visualization_spec.get("actual_processor")
        or "scout_local_dem_analysis",
        "standard_processor_completed": (
            visualization_spec.get("standard_processor_completed") is True
        ),
        "fallback_used": visualization_spec.get("fallback_used"),
        "python_dtm_processing_used": visualization_spec.get(
            "python_dtm_processing_used"
        ),
        "local_python_comparator": "legacy_path_available",
    }


def _source_ref_or_none(value: Any) -> str | None:
    return _optional_ref(value)


def _overlay_opacity_or_none(value: Any) -> float | None:
    opacity = _finite_number(value)
    return opacity if opacity is not None and 0 <= opacity <= 1 else None


def _normalize_overlays(
    terrain: dict[str, Any],
    *,
    project_id: str,
) -> list[dict[str, Any]]:
    raw_overlays = terrain.get("raster_overlays", [])
    if not isinstance(raw_overlays, list):
        return []
    by_mode = {
        item.get("mode"): item
        for item in raw_overlays
        if isinstance(item, dict) and item.get("mode") in SUPPORTED_OVERLAY_MODES
    }
    overlays = []
    for mode in SUPPORTED_OVERLAY_MODES:
        item = by_mode.get(mode)
        if not item:
            continue
        overlays.append(
            {
                "mode": mode,
                "runtime_href": (
                    f"/admin/pretrip/projects/{quote(project_id, safe='')}"
                    f"/terrain-overlays/{mode}.png"
                ),
                "source_ref": _source_ref_or_none(item.get("source_path")),
                "bbox_wgs84": _normalize_bbox(item.get("bbox_wgs84")),
                "pixel_width": _positive_int_or_none(item.get("pixel_width")),
                "pixel_height": _positive_int_or_none(item.get("pixel_height")),
                "cell_resolution_m": _finite_number(item.get("cell_resolution_m")),
                "sha256": _sha256_or_none(item.get("sha256")),
                "alpha_channel": item.get("alpha_channel") is True,
                "opacity": _overlay_opacity_or_none(item.get("opacity")),
                "compositing": (
                    "source-over"
                    if item.get("compositing") == "source-over"
                    else None
                ),
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        )
    return overlays


def _normalize_route_samples(
    payload: dict[str, Any],
) -> tuple[list[dict[str, Any]], int]:
    features = payload.get("features", []) if isinstance(payload, dict) else []
    if not isinstance(features, list):
        return [], 0
    points = []
    for feature in features:
        if not isinstance(feature, dict):
            continue
        coordinate = _point_coordinate(feature.get("geometry"))
        properties = feature.get("properties", {})
        if coordinate is None or not isinstance(properties, dict):
            continue
        distance_m = _finite_number(properties.get("distance_m"))
        if distance_m is None:
            continue
        points.append(
            {
                "id": str(
                    properties.get("candidate_id")
                    or f"terrain-route-sample-{len(points):04d}"
                ),
                "lon": coordinate[0],
                "lat": coordinate[1],
                "distance_m": distance_m,
                "elevation_m": _finite_number(properties.get("elevation_m")),
                "pretrip_risk": _finite_number(properties.get("pretrip_risk")),
                "teii_20m": _finite_number(properties.get("teii_20m")),
                "tri": _finite_number(properties.get("tri")),
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        )
    points.sort(key=lambda item: (item["distance_m"], item["id"]))
    return _evenly_sample(points, MAX_ROUTE_SAMPLE_POINTS), len(points)


def _normalize_risk_candidates(
    payload: dict[str, Any],
) -> tuple[list[dict[str, Any]], int]:
    candidates = payload.get("candidates", []) if isinstance(payload, dict) else []
    if not isinstance(candidates, list):
        return [], 0
    normalized = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        lon = _finite_number(item.get("lon"))
        lat = _finite_number(item.get("lat"))
        if lon is None or lat is None:
            continue
        dimensions = item.get("risk_dimensions", {})
        if not isinstance(dimensions, dict):
            dimensions = {}
        normalized_dimensions = {
            key: _finite_number(dimensions.get(key))
            for key in ("pretrip_risk", "teii_20m", "tri", "lec", "sri", "scp")
        }
        pressure = max(
            (value for value in normalized_dimensions.values() if value is not None),
            default=0.0,
        )
        normalized.append(
            {
                "id": str(
                    item.get("candidate_id")
                    or f"terrain-risk-candidate-{len(normalized):03d}"
                ),
                "kind": str(item.get("candidate_kind") or "terrain_risk_candidate"),
                "lon": lon,
                "lat": lat,
                "reason": str(item.get("reason") or "Candidate requires review."),
                "confidence": str(item.get("confidence") or "unknown"),
                "review_state": str(item.get("review_state") or "candidate"),
                "risk_dimensions": normalized_dimensions,
                "display_pressure": round(pressure, 2),
                "source_refs": _normalize_string_refs(item.get("source_refs")),
                "requires_human_review": True,
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        )
    normalized.sort(key=lambda item: (-item["display_pressure"], item["id"]))
    return normalized[:MAX_RISK_CANDIDATES], len(normalized)


def _structure_gap(
    terrain: dict[str, Any],
    feature_kind: str,
    default_reason: str,
) -> dict[str, Any]:
    features = terrain.get("features", []) if isinstance(terrain, dict) else []
    matches = [
        item
        for item in features
        if isinstance(item, dict)
        and isinstance(item.get("properties"), dict)
        and item["properties"].get("feature_kind") == feature_kind
    ]
    return {
        "status": "candidate_vectors" if matches else "not_prepared",
        "count": len(matches),
        "reason": None if matches else default_reason,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _structure_projection(
    terrain: dict[str, Any],
    workspace_structures: dict[str, Any],
    feature_kind: str,
    default_reason: str,
) -> dict[str, Any]:
    qgis_vectors = _qgis_structure_vector_matches(terrain, feature_kind)
    points = [
        item
        for item in workspace_structures.get("points", [])
        if isinstance(item, dict) and item.get("feature_kind") == feature_kind
    ]
    if qgis_vectors:
        vector_count = sum(
            _line_geometry_count(item.get("geometry")) for item in qgis_vectors
        )
        return {
            "status": "candidate_vectors",
            "count": vector_count,
            "rendered_count": vector_count,
            "reason": (
                "QGIS/GRASS standard terrain morphology candidate vectors; "
                "Scout local morphology remains a non-authoritative comparator."
            ),
            "source": "qgis_processing_grass",
            "comparison_point_count": len(points),
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
    if points:
        return {
            "status": "candidate_points",
            "count": int(
                workspace_structures.get("counts", {}).get(
                    feature_kind,
                    len(points),
                )
            ),
            "rendered_count": len(points),
            "reason": (
                "Deterministic local DEM morphology candidates; map or field "
                "review is still required."
            ),
            "source": "scout_python_morphology_comparator",
            "comparison_point_count": len(points),
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
    return _structure_gap(
        terrain,
        feature_kind,
        workspace_structures.get("error") or default_reason,
    )


def _qgis_structure_vector_matches(
    terrain: dict[str, Any],
    feature_kind: str,
) -> list[dict[str, Any]]:
    qgis_kinds = {
        "ridge": "qgis_candidate_ridge_line",
        "valley": "qgis_candidate_valley_line",
    }
    qgis_kind = qgis_kinds.get(feature_kind)
    if qgis_kind is None:
        return []
    features = terrain.get("features", []) if isinstance(terrain, dict) else []
    return [
        item
        for item in features
        if isinstance(item, dict)
        and isinstance(item.get("properties"), dict)
        and item["properties"].get("kind") == qgis_kind
        and item["properties"].get("candidate_only") is True
        and item["properties"].get("runtime_safety_truth") is False
        and item["properties"].get("operational") is False
    ]


def _qgis_structure_vector_count(
    terrain: dict[str, Any],
    feature_kind: str,
) -> int:
    return sum(
        _line_geometry_count(item.get("geometry"))
        for item in _qgis_structure_vector_matches(terrain, feature_kind)
    )


def _line_geometry_count(geometry: Any) -> int:
    if not isinstance(geometry, dict):
        return 0
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if geometry_type == "LineString":
        return 1 if isinstance(coordinates, list) and len(coordinates) >= 2 else 0
    if geometry_type == "MultiLineString" and isinstance(coordinates, list):
        return sum(
            1
            for line in coordinates
            if isinstance(line, list) and len(line) >= 2
        )
    return 0


def _standard_gis_structure_projection(
    terrain: dict[str, Any],
) -> dict[str, Any]:
    counts = {
        "ridge": _qgis_structure_vector_count(terrain, "ridge"),
        "valley": _qgis_structure_vector_count(terrain, "valley"),
        "saddle": 0,
    }
    return {
        "status": "standard_gis_primary",
        "source": "qgis_processing_grass",
        "counts": counts,
        "rendered_counts": dict(counts),
        "points": [],
        "error": None,
        "local_python_comparator": "not_run",
        "reason": _STANDARD_GIS_PRIMARY_REASON,
        "boundary": _workspace_candidate_boundary(),
    }


def _workspace_structure_projection(
    project_root: Path,
    project: dict[str, Any],
    inputs: _NavigationTerrainInputs,
) -> dict[str, Any]:
    if inputs.workspace_grid is None:
        return {
            "status": "not_prepared",
            "counts": {"ridge": 0, "valley": 0, "saddle": 0},
            "rendered_counts": {"ridge": 0, "valley": 0, "saddle": 0},
            "points": [],
            "error": inputs.workspace_grid_error,
            "boundary": _workspace_candidate_boundary(),
        }
    try:
        return extract_dem_structure_candidates(
            project_root,
            project,
            workspace_grid=inputs.workspace_grid,
            route_points=inputs.route_points,
            projected_route_points=inputs.projected_route_points,
        )
    except WorkspaceTerrainEvidenceError as exc:
        return {
            "status": "not_prepared",
            "counts": {"ridge": 0, "valley": 0, "saddle": 0},
            "rendered_counts": {"ridge": 0, "valley": 0, "saddle": 0},
            "points": [],
            "error": str(exc),
            "boundary": _workspace_candidate_boundary(),
        }


def _workspace_source_ledger_projection(
    project_root: Path,
    project: dict[str, Any],
) -> dict[str, Any]:
    try:
        return build_workspace_source_ledger(project_root, project)
    except WorkspaceTerrainEvidenceError as exc:
        return {
            "status": "not_prepared",
            "sources": [],
            "source_tier_counts": {"P0": 0, "P1": 0, "P2": 0},
            "ordered_clues": [],
            "coordinate_audit": {},
            "contradictions": [],
            "evidence_gaps": [str(exc)],
            "boundary": _workspace_candidate_boundary(),
        }


def _workspace_route_topology_projection(
    project_root: Path,
    project: dict[str, Any],
    workspace_structures: dict[str, Any],
    inputs: _NavigationTerrainInputs,
) -> dict[str, Any]:
    try:
        return build_workspace_route_topology(
            project_root,
            project,
            workspace_structures,
            route_points=inputs.route_points,
        )
    except WorkspaceTerrainEvidenceError as exc:
        return {
            "status": "not_prepared",
            "nodes": [],
            "edges": [],
            "route_options": [],
            "route_option_count": 0,
            "shared_edge_ids": [],
            "prepared_historical_topology": {
                "status": "not_prepared",
                "nodes": [],
                "edges": [],
                "route_options": [],
                "route_option_count": 0,
                "shared_edge_ids": [],
                "contradictions": [],
                "evidence_gaps": [str(exc)],
                "boundary": _workspace_candidate_boundary(),
            },
            "limitations": [str(exc)],
            "boundary": _workspace_candidate_boundary(),
        }


def _workspace_candidate_boundary() -> dict[str, Any]:
    return {
        "candidate_only": True,
        "runtime_safety_truth": False,
        "safe_or_walkable": "not_determined",
        "human_review_required": True,
        "phase1_runtime_mutation_allowed": False,
    }


def _evenly_sample(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    if len(items) <= limit:
        return list(items)
    if limit <= 1:
        return [items[0]]
    indices = {round(index * (len(items) - 1) / (limit - 1)) for index in range(limit)}
    return [items[index] for index in sorted(indices)]


def _point_coordinate(geometry: Any) -> tuple[float, float] | None:
    if not isinstance(geometry, dict) or geometry.get("type") != "Point":
        return None
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list) or len(coordinates) < 2:
        return None
    lon = _finite_number(coordinates[0])
    lat = _finite_number(coordinates[1])
    if lon is None or lat is None:
        return None
    return lon, lat


def _normalize_bbox(value: Any) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None
    normalized = {
        key: _finite_number(value.get(key))
        for key in ("west", "south", "east", "north")
    }
    if any(item is None for item in normalized.values()):
        return None
    if normalized["west"] >= normalized["east"]:
        return None
    if normalized["south"] >= normalized["north"]:
        return None
    return {key: float(item) for key, item in normalized.items() if item is not None}


def _normalize_count_map(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {str(key): _nonnegative_int(count) for key, count in value.items()}


def _normalize_string_refs(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(
        dict.fromkeys(
            item.strip() for item in value if isinstance(item, str) and item.strip()
        )
    )


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _positive_int_or_none(value: Any) -> int | None:
    normalized = _nonnegative_int(value)
    return normalized if normalized > 0 else None


def _sha256_or_none(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if len(normalized) != 64:
        return None
    if any(character not in "0123456789abcdef" for character in normalized):
        return None
    return normalized
