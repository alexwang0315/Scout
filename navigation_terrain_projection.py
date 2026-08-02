from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

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


NAVIGATION_TERRAIN_SCHEMA_VERSION = "scout_navigation_terrain_intelligence.v0"
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

    overlays = _normalize_overlays(terrain, project_id=project_id)
    bounded_route_samples, source_route_sample_count = _normalize_route_samples(
        route_samples
    )
    bounded_risk_candidates, source_risk_candidate_count = _normalize_risk_candidates(
        risk_candidates
    )
    workspace_structures = _workspace_structure_projection(
        project_root,
        project,
        inputs,
    )
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
    raw_hierarchy, raw_route_events = _workspace_terrain_bundle(
        project_root,
        project,
        inputs,
    )
    terrain_hierarchy = _normalize_terrain_hierarchy(raw_hierarchy)
    route_terrain_events = _normalize_route_terrain_events(raw_route_events)
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
        "feature_extraction": {
            "ridge": _structure_projection(
                terrain,
                workspace_structures,
                "ridge",
                "No reviewed ridge vector was prepared by the current bitmap fallback.",
            ),
            "valley": _structure_projection(
                terrain,
                workspace_structures,
                "valley",
                "No reviewed valley or drainage vector was prepared by the current bitmap fallback.",
            ),
            "saddle": _structure_projection(
                terrain,
                workspace_structures,
                "saddle",
                "No reviewed saddle vector was prepared by the current bitmap fallback.",
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
        "route_terrain_events": route_terrain_events,
        "source_ledger": source_ledger,
        "route_topology": route_topology,
        "missing_artifacts": missing_artifacts,
        "source_refs": [
            ref for ref in (terrain_ref, route_samples_ref, risk_candidates_ref) if ref
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
    coverage_ref = _optional_ref(project.get("dtm_coverage_summary_ref"))
    coverage = _read_json_ref(project_root, coverage_ref)
    parsed_route_points = route_sample_points(route_samples)
    projected_route_points = project_route_sample_points_twd97(
        parsed_route_points
    )
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


def _source_ref_or_none(value: Any) -> str | None:
    return _optional_ref(value)


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
    points = [
        item
        for item in workspace_structures.get("points", [])
        if isinstance(item, dict) and item.get("feature_kind") == feature_kind
    ]
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
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
    return _structure_gap(
        terrain,
        feature_kind,
        workspace_structures.get("error") or default_reason,
    )


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
