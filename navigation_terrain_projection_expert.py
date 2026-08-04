"""Bounded Dashboard projection for expert terrain hierarchy and events."""

from __future__ import annotations

import math
from typing import Any

from navigation_terrain_coordinates import twd97_to_wgs84

MAX_TERRAIN_HIERARCHY_EDGES = 240
MAX_TERRAIN_HIERARCHY_NODES = 500
MAX_TERRAIN_EDGE_POINTS = 64
MAX_ROUTE_TERRAIN_EVENTS = 80
DEFAULT_UNCERTAINTY_HALF_WIDTH_M = 60.0


def normalize_terrain_hierarchy(payload: dict[str, Any]) -> dict[str, Any]:
    if not _candidate_boundary_is_valid(payload.get("boundary")):
        return empty_terrain_hierarchy(
            "Terrain hierarchy violates the candidate-only boundary."
        )
    raw_nodes = payload.get("nodes", [])
    if not isinstance(raw_nodes, list):
        raw_nodes = []
    nodes = []
    for item in raw_nodes[:MAX_TERRAIN_HIERARCHY_NODES]:
        if not isinstance(item, dict):
            continue
        lon = _finite_number(item.get("lon"))
        lat = _finite_number(item.get("lat"))
        if lon is None or lat is None:
            continue
        nodes.append(
            {
                "id": str(item.get("id") or f"terrain-node-{len(nodes):03d}"),
                "kind": str(item.get("kind") or "terrain_node"),
                "lon": lon,
                "lat": lat,
                "elevation_m": _finite_number(item.get("elevation_m")),
                "degree": _nonnegative_int(item.get("degree")),
                "source_refs": _normalize_string_refs(item.get("source_refs")),
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        )
    raw_edges = payload.get("edges", [])
    if not isinstance(raw_edges, list):
        raw_edges = []
    edges = []
    grid = payload.get("grid", {})
    if not isinstance(grid, dict):
        grid = {}
    cell_resolution_m = _finite_number(grid.get("cell_resolution_m"))
    default_half_width_m = max(
        DEFAULT_UNCERTAINTY_HALF_WIDTH_M,
        (cell_resolution_m or 20.0) * 3.0,
    )
    for item in raw_edges[:MAX_TERRAIN_HIERARCHY_EDGES]:
        if not isinstance(item, dict):
            continue
        coordinates = _normalize_coordinate_line(item.get("coordinates_wgs84"))
        if len(coordinates) < 2:
            continue
        edges.append(
            {
                "id": str(item.get("id") or f"terrain-edge-{len(edges):03d}"),
                "from": str(item.get("from") or ""),
                "to": str(item.get("to") or ""),
                "kind": str(item.get("kind") or "terrain_edge"),
                "coordinates": _evenly_sample(
                    coordinates,
                    MAX_TERRAIN_EDGE_POINTS,
                ),
                "length_m": _finite_number(item.get("length_m")),
                "watershed_boundary_candidate": bool(
                    item.get("watershed_boundary_candidate")
                ),
                "source_refs": _normalize_string_refs(item.get("source_refs")),
                "candidate_only": True,
                "runtime_safety_truth": False,
                "output_role": "uncertainty_band_visualization",
                "raw_geometry_role": "raw_debug_geometry",
                "validation_state": "unvalidated",
                "operational_authority": False,
                "presentation_scope": "planning_non_actionable",
                "effect_scope": "none",
                "event_source_mode": "prohibited",
                "centerline_visible": False,
                "uncertainty_half_width_m": max(
                    default_half_width_m,
                    _finite_number(item.get("uncertainty_half_width_m")) or 0.0,
                ),
            }
        )
    counts = payload.get("counts", {})
    if not isinstance(counts, dict):
        counts = {}
    return {
        "schema_version": "scout_navigation_terrain_hierarchy_projection.v1",
        "status": str(payload.get("status") or "not_prepared"),
        "source_node_count": _nonnegative_int(counts.get("node_count", len(raw_nodes))),
        "rendered_node_count": len(nodes),
        "source_edge_count": _nonnegative_int(counts.get("edge_count", len(raw_edges))),
        "rendered_edge_count": len(edges),
        "nodes": nodes,
        "edges": edges,
        "output_role": "uncertainty_band_visualization",
        "validation_state": "unvalidated",
        "operational_authority": False,
        "presentation_scope": "planning_non_actionable",
        "effect_scope": "none",
        "event_source_mode": "prohibited",
        "uncertainty_semantics": (
            "visual_candidate_support_not_confidence_interval"
        ),
        "source_refs": _normalize_string_refs(payload.get("source_refs")),
        "limitations": _bounded_limitations(payload.get("limitations")),
        "boundary": _candidate_boundary(),
    }


def normalize_route_terrain_events(payload: dict[str, Any]) -> dict[str, Any]:
    if not _shadow_event_payload_is_valid(payload):
        return empty_route_terrain_events(
            "Route-terrain events violate the fail-closed shadow boundary."
        )
    raw_events = payload.get("events", [])
    if not isinstance(raw_events, list):
        raw_events = []
    events = []
    for item in raw_events[:MAX_ROUTE_TERRAIN_EVENTS]:
        if not isinstance(item, dict):
            continue
        if not _shadow_event_record_is_valid(item):
            continue
        x = _finite_number(item.get("x_twd97"))
        y = _finite_number(item.get("y_twd97"))
        if x is None or y is None:
            continue
        lat, lon = twd97_to_wgs84(x, y)
        observation = str(item.get("observation_prompt") or "").strip()[:420]
        events.append(
            {
                "id": str(item.get("id") or f"route-event-{len(events):03d}"),
                "sequence": _nonnegative_int(item.get("sequence")),
                "event_type": str(item.get("event_type") or "terrain_event"),
                "terrain_relation": str(
                    item.get("terrain_relation") or "candidate_relation"
                ),
                "terrain_feature_id": str(item.get("terrain_feature_id") or ""),
                "terrain_feature_kind": str(item.get("terrain_feature_kind") or ""),
                "route_distance_m": _finite_number(item.get("route_distance_m")),
                "off_route_distance_m": _finite_number(
                    item.get("off_route_distance_m")
                ),
                "crossing_angle_degrees": _finite_number(
                    item.get("crossing_angle_degrees")
                ),
                "lon": round(lon, 8),
                "lat": round(lat, 8),
                "review_prompt": (
                    f"Shadow review hypothesis: {observation}"
                    if observation
                    else "Shadow review hypothesis: inspect the candidate relation."
                ),
                "source_refs": _normalize_string_refs(item.get("source_refs")),
                "candidate_only": True,
                "runtime_safety_truth": False,
                "output_role": "shadow_event_candidate",
                "validation_state": "blocked_pending_reference",
                "gate_mode": "shadow_only",
                "operational_authority": False,
                "presentation_scope": "developer_debug_only",
                "effect_scope": "none",
                "blocked_reason": "geometry_reference_validation_missing",
            }
        )
    candidate_count = _nonnegative_int(
        payload.get("candidate_event_count", len(raw_events))
    )
    return {
        "schema_version": "scout_navigation_route_terrain_events_projection.v1",
        "status": str(payload.get("status") or "not_prepared"),
        "output_role": "shadow_event_candidate",
        "validation_state": "blocked_pending_reference",
        "gate_mode": "shadow_only",
        "operational_authority": False,
        "presentation_scope": "developer_debug_only",
        "effect_scope": "none",
        "blocked_reason": "geometry_reference_validation_missing",
        "candidate_count": candidate_count,
        "rendered_count": len(events),
        "max_rendered_count": MAX_ROUTE_TERRAIN_EVENTS,
        "truncated": bool(payload.get("truncated")) or candidate_count > len(events),
        "events": events,
        "limitations": _bounded_limitations(payload.get("limitations")),
        "boundary": _candidate_boundary(),
    }


def empty_terrain_hierarchy(error: str) -> dict[str, Any]:
    return {
        "schema_version": "scout_navigation_terrain_hierarchy_projection.v1",
        "status": "not_prepared",
        "source_node_count": 0,
        "rendered_node_count": 0,
        "source_edge_count": 0,
        "rendered_edge_count": 0,
        "nodes": [],
        "edges": [],
        "output_role": "uncertainty_band_visualization",
        "validation_state": "unvalidated",
        "operational_authority": False,
        "presentation_scope": "planning_non_actionable",
        "effect_scope": "none",
        "event_source_mode": "prohibited",
        "uncertainty_semantics": (
            "visual_candidate_support_not_confidence_interval"
        ),
        "source_refs": [],
        "limitations": [error],
        "boundary": _candidate_boundary(),
    }


def empty_route_terrain_events(error: str) -> dict[str, Any]:
    return {
        "schema_version": "scout_navigation_route_terrain_events_projection.v1",
        "status": "not_prepared",
        "output_role": "shadow_event_candidate",
        "validation_state": "blocked_pending_reference",
        "gate_mode": "shadow_only",
        "operational_authority": False,
        "presentation_scope": "developer_debug_only",
        "effect_scope": "none",
        "blocked_reason": "geometry_reference_validation_missing",
        "candidate_count": 0,
        "rendered_count": 0,
        "max_rendered_count": MAX_ROUTE_TERRAIN_EVENTS,
        "truncated": False,
        "events": [],
        "limitations": [error],
        "boundary": _candidate_boundary(),
    }


def _normalize_coordinate_line(value: Any) -> list[dict[str, float]]:
    if not isinstance(value, list):
        return []
    coordinates = []
    for item in value:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        lon = _finite_number(item[0])
        lat = _finite_number(item[1])
        if lon is None or lat is None:
            continue
        coordinate = {"lon": lon, "lat": lat}
        if not coordinates or coordinate != coordinates[-1]:
            coordinates.append(coordinate)
    return coordinates


def _candidate_boundary_is_valid(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("candidate_only") is True
        and value.get("runtime_safety_truth") is False
    )


def _shadow_event_payload_is_valid(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and _candidate_boundary_is_valid(value.get("boundary"))
        and value.get("output_role") == "shadow_event_candidate"
        and value.get("validation_state") == "blocked_pending_reference"
        and value.get("gate_mode") == "shadow_only"
        and value.get("operational_authority") is False
        and value.get("effect_scope") == "none"
    )


def _shadow_event_record_is_valid(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("output_role") == "shadow_event_candidate"
        and value.get("validation_state") == "blocked_pending_reference"
        and value.get("gate_mode") == "shadow_only"
        and value.get("operational_authority") is False
        and value.get("effect_scope") == "none"
    )


def _candidate_boundary() -> dict[str, Any]:
    return {
        "candidate_only": True,
        "runtime_safety_truth": False,
        "safe_or_walkable": "not_determined",
        "human_review_required": True,
        "phase1_runtime_mutation_allowed": False,
        "shadow_only": True,
        "presentation_scope": "developer_debug_only",
        "effect_scope": "none",
        "event_source_mode": "shadow_only",
        "operational_authority": False,
        "validation_state": "blocked_pending_reference",
    }


def _bounded_limitations(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value[:12] if isinstance(item, str)]


def _normalize_string_refs(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(
        dict.fromkeys(
            item.strip() for item in value if isinstance(item, str) and item.strip()
        )
    )[:32]


def _evenly_sample(
    items: list[dict[str, float]],
    limit: int,
) -> list[dict[str, float]]:
    if len(items) <= limit:
        return list(items)
    indices = {round(index * (len(items) - 1) / (limit - 1)) for index in range(limit)}
    return [items[index] for index in sorted(indices)]


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
