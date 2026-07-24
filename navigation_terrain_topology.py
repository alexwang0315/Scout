"""Candidate-only observed and historical route topology projection."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Sequence

from navigation_terrain_dem import WorkspaceTerrainEvidenceError


def build_workspace_route_topology(
    project_root: Path,
    project: dict[str, Any],
    structure_candidates: dict[str, Any],
    *,
    target_node_count: int = 8,
    max_edge_points: int = 48,
) -> dict[str, Any]:
    """Build the observed baseline and project an optional compiled hypothesis."""

    if target_node_count < 2 or target_node_count > 24:
        raise WorkspaceTerrainEvidenceError(
            "target_node_count must be between 2 and 24"
        )
    if max_edge_points < 2 or max_edge_points > 200:
        raise WorkspaceTerrainEvidenceError(
            "max_edge_points must be between 2 and 200"
        )
    project_root = project_root.resolve()
    route_ref = _required_project_ref(project, "terrain_route_samples_ref")
    route_points = _route_sample_points(
        _read_project_json(project_root, route_ref)
    )
    if len(route_points) < 2:
        return _empty_route_topology(route_ref)

    node_indices = _even_indices(
        len(route_points),
        min(target_node_count, len(route_points)),
    )
    raw_structure_points = structure_candidates.get("points", [])
    structure_points = (
        [item for item in raw_structure_points if isinstance(item, dict)]
        if isinstance(raw_structure_points, list)
        else []
    )
    nodes = []
    for node_number, point_index in enumerate(node_indices):
        point = route_points[point_index]
        nodes.append(
            {
                "id": f"route-node-{node_number:02d}",
                "label": (
                    "Route start"
                    if node_number == 0
                    else "Route end"
                    if node_number == len(node_indices) - 1
                    else f"Route graph node {node_number}"
                ),
                "lon": point["lon"],
                "lat": point["lat"],
                "distance_m": point["distance_m"],
                "elevation_m": point["elevation_m"],
                "nearest_structure_candidate": _nearest_structure(
                    point,
                    structure_points,
                ),
                "source_refs": [route_ref],
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        )

    edges = []
    for edge_number, (start_index, end_index) in enumerate(
        zip(node_indices, node_indices[1:])
    ):
        source_slice = route_points[start_index : end_index + 1]
        sampled = [
            source_slice[index]
            for index in _even_indices(
                len(source_slice),
                min(max_edge_points, len(source_slice)),
            )
        ]
        edge_id = f"OBS-{edge_number:02d}-{edge_number + 1:02d}"
        edges.append(
            {
                "id": edge_id,
                "from": nodes[edge_number]["id"],
                "to": nodes[edge_number + 1]["id"],
                "kind": "gpx_observed",
                "coordinates": [
                    [point["lon"], point["lat"]] for point in sampled
                ],
                "distance_start_m": source_slice[0]["distance_m"],
                "distance_end_m": source_slice[-1]["distance_m"],
                "source_refs": [route_ref],
                "status": "candidate_only",
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        )

    route_options = [
        {
            "id": "observed-baseline",
            "label": "Prepared GPX baseline",
            "edge_ids": [edge["id"] for edge in edges],
            "evidence_kind": "gpx_observed",
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
    ]
    historical_ref = _optional_project_ref(
        project,
        "historical_route_hypothesis_ref",
    )
    historical = (
        _project_precompiled_historical_topology(
            _read_project_json(project_root, historical_ref),
            source_ref=historical_ref,
        )
        if historical_ref
        else _empty_historical_topology()
    )
    return {
        "schema_version": "scout_navigation_route_topology.v0",
        "artifact_kind": "navigation_route_topology",
        "status": "observed_baseline_topology",
        "source_ref": route_ref,
        "nodes": nodes,
        "edges": edges,
        "route_options": route_options,
        "route_option_count": 1,
        "shared_edge_ids": [],
        "prepared_historical_topology": historical,
        "limitations": [
            "Only one prepared route geometry is shown as the observed baseline.",
            (
                "Compiled alternatives are shown only when their source ledger "
                "and candidate topology are linked to the workspace."
            ),
            "Neither observed nor compiled candidates establish current walkability.",
        ],
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "safe_or_walkable": "not_determined",
            "raw_gpx_embedded": False,
            "human_review_required": True,
            "invented_detour_count": 0,
            "phase1_runtime_mutation_allowed": False,
        },
    }


def _project_precompiled_historical_topology(
    payload: dict[str, Any],
    *,
    source_ref: str,
) -> dict[str, Any]:
    if (
        payload.get("candidate_only") is not True
        or payload.get("runtime_safety_truth") is not False
    ):
        raise WorkspaceTerrainEvidenceError(
            "historical route hypothesis violates candidate boundary"
        )
    topology = payload.get("topology", {})
    if not isinstance(topology, dict):
        raise WorkspaceTerrainEvidenceError(
            "historical route hypothesis has no topology"
        )
    raw_nodes = topology.get("nodes", [])
    if not isinstance(raw_nodes, list):
        raw_nodes = []
    nodes = [
        {
            "id": str(item.get("id") or ""),
            "label": str(item.get("label") or item.get("name") or item["id"]),
            "lon": _finite_number(item.get("lon")),
            "lat": _finite_number(item.get("lat")),
            "source_refs": _bounded_string_refs(item.get("source_refs"), 16),
        }
        for item in raw_nodes[:100]
        if isinstance(item, dict) and item.get("id")
    ]
    raw_edges = topology.get("edges", [])
    if not isinstance(raw_edges, list):
        raw_edges = []
    edges = []
    for item in raw_edges[:200]:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        coordinates = item.get("coordinates", [])
        if not isinstance(coordinates, list):
            coordinates = []
        sampled_coordinates = [
            coordinates[index]
            for index in _even_indices(len(coordinates), min(100, len(coordinates)))
            if isinstance(coordinates[index], list)
            and len(coordinates[index]) >= 2
        ]
        edges.append(
            {
                "id": str(item["id"]),
                "from": str(item.get("from") or ""),
                "to": str(item.get("to") or ""),
                "kind": str(item.get("kind") or "inferred_connector"),
                "coordinates": sampled_coordinates,
                "source_refs": _bounded_string_refs(item.get("source_refs"), 16),
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        )
    option_paths = topology.get("route_options_edge_ids", [])
    if not isinstance(option_paths, list):
        option_paths = []
    route_options = [
        {
            "id": f"historical-option-{index + 1:02d}",
            "label": _option_label(payload, index, path),
            "edge_ids": _bounded_string_refs(path, 100),
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
        for index, path in enumerate(option_paths[:50])
        if isinstance(path, list)
    ]
    raw_contradictions = payload.get("contradictions", [])
    if not isinstance(raw_contradictions, list):
        raw_contradictions = []
    raw_evidence_gaps = payload.get("evidence_gaps", [])
    if not isinstance(raw_evidence_gaps, list):
        raw_evidence_gaps = []
    return {
        "status": "candidate_topology",
        "source_ref": source_ref,
        "coordinate_context": _bounded_coordinate_context(
            payload.get("coordinate_context")
        ),
        "nodes": nodes,
        "edges": edges,
        "route_options": route_options,
        "route_option_count": len(route_options),
        "shared_edge_ids": _bounded_string_refs(
            topology.get("shared_edge_ids"),
            200,
        ),
        "contradictions": [
            {
                "claim": str(item.get("claim") or ""),
                "source_refs": _bounded_string_refs(item.get("source_refs"), 16),
            }
            for item in raw_contradictions[:50]
            if isinstance(item, dict) and item.get("claim")
        ],
        "evidence_gaps": [
            str(value)
            for value in raw_evidence_gaps[:50]
            if isinstance(value, str) and value.strip()
        ],
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "safe_or_walkable": "not_determined",
            "human_review_required": True,
        },
    }


def _option_label(payload: dict[str, Any], index: int, path: Any) -> str:
    topology = payload.get("topology", {})
    labels = (
        topology.get("route_option_labels", [])
        if isinstance(topology, dict)
        else []
    )
    if isinstance(labels, list) and index < len(labels):
        label = labels[index]
        if isinstance(label, str) and label.strip():
            return label.strip()[:160]
    return f"Historical candidate option {index + 1}"


def _route_sample_points(payload: dict[str, Any]) -> list[dict[str, Any]]:
    features = payload.get("features", [])
    if not isinstance(features, list):
        return []
    points = []
    for index, feature in enumerate(features):
        if not isinstance(feature, dict):
            continue
        geometry = feature.get("geometry", {})
        properties = feature.get("properties", {})
        if (
            not isinstance(geometry, dict)
            or geometry.get("type") != "Point"
            or not isinstance(properties, dict)
        ):
            continue
        coordinates = geometry.get("coordinates")
        if not isinstance(coordinates, list) or len(coordinates) < 2:
            continue
        lon = _finite_number(coordinates[0])
        lat = _finite_number(coordinates[1])
        distance_m = _finite_number(properties.get("distance_m"))
        if lon is None or lat is None or distance_m is None:
            continue
        points.append(
            {
                "id": str(
                    properties.get("candidate_id")
                    or f"route-sample-{index:05d}"
                ),
                "lon": lon,
                "lat": lat,
                "distance_m": distance_m,
                "elevation_m": _finite_number(properties.get("elevation_m")),
            }
        )
    points.sort(key=lambda item: (item["distance_m"], item["id"]))
    return points


def _nearest_structure(
    route_point: dict[str, Any],
    structure_points: Sequence[dict[str, Any]],
) -> dict[str, Any] | None:
    candidates = []
    for item in structure_points:
        lon = _finite_number(item.get("lon"))
        lat = _finite_number(item.get("lat"))
        if lon is None or lat is None:
            continue
        distance_m = _wgs84_distance_m(
            route_point["lat"],
            route_point["lon"],
            lat,
            lon,
        )
        candidates.append((distance_m, item))
    if not candidates:
        return None
    distance_m, nearest = min(candidates, key=lambda pair: pair[0])
    if distance_m > 500.0:
        return None
    return {
        "id": str(nearest.get("id") or ""),
        "feature_kind": str(nearest.get("feature_kind") or "unknown"),
        "distance_m": round(distance_m, 1),
    }


def _wgs84_distance_m(
    lat_a: float,
    lon_a: float,
    lat_b: float,
    lon_b: float,
) -> float:
    mean_lat = math.radians((lat_a + lat_b) / 2.0)
    dx = math.radians(lon_b - lon_a) * math.cos(mean_lat)
    dy = math.radians(lat_b - lat_a)
    return math.hypot(dx, dy) * 6_371_000.0


def _empty_route_topology(source_ref: str | None) -> dict[str, Any]:
    return {
        "schema_version": "scout_navigation_route_topology.v0",
        "artifact_kind": "navigation_route_topology",
        "status": "not_prepared",
        "source_ref": source_ref,
        "nodes": [],
        "edges": [],
        "route_options": [],
        "route_option_count": 0,
        "shared_edge_ids": [],
        "prepared_historical_topology": _empty_historical_topology(),
        "limitations": ["No bounded route sample geometry is available."],
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "safe_or_walkable": "not_determined",
            "raw_gpx_embedded": False,
            "human_review_required": True,
        },
    }


def _empty_historical_topology() -> dict[str, Any]:
    return {
        "status": "not_prepared",
        "nodes": [],
        "edges": [],
        "route_options": [],
        "route_option_count": 0,
        "shared_edge_ids": [],
        "contradictions": [],
        "evidence_gaps": [
            "No compiled historical route hypothesis is linked to this workspace."
        ],
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "safe_or_walkable": "not_determined",
            "human_review_required": True,
        },
    }


def _required_project_ref(project: dict[str, Any], key: str) -> str:
    ref = _optional_project_ref(project, key)
    if ref is None:
        raise WorkspaceTerrainEvidenceError(f"{key} is required")
    return ref


def _optional_project_ref(project: dict[str, Any], key: str) -> str | None:
    value = project.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise WorkspaceTerrainEvidenceError(f"{key} must be a relative path")
    ref = value.strip()
    candidate = Path(ref)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise WorkspaceTerrainEvidenceError(f"{key} must stay inside workspace")
    return ref


def _read_project_json(project_root: Path, ref: str) -> dict[str, Any]:
    path = (project_root / ref).resolve()
    try:
        path.relative_to(project_root)
    except ValueError as exc:
        raise WorkspaceTerrainEvidenceError(
            "workspace reference escapes project root"
        ) from exc
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkspaceTerrainEvidenceError(
            f"workspace artifact could not be read: {ref}"
        ) from exc
    if not isinstance(payload, dict):
        raise WorkspaceTerrainEvidenceError(
            f"workspace artifact must be a JSON object: {ref}"
        )
    return payload


def _even_indices(item_count: int, limit: int) -> list[int]:
    if item_count <= 0 or limit <= 0:
        return []
    if item_count <= limit:
        return list(range(item_count))
    if limit == 1:
        return [0]
    return sorted(
        {
            round(index * (item_count - 1) / (limit - 1))
            for index in range(limit)
        }
    )


def _bounded_string_refs(value: Any, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(
        dict.fromkeys(
            str(item).strip()
            for item in value[:limit]
            if isinstance(item, str) and item.strip()
        )
    )


def _bounded_coordinate_context(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for raw_key, raw_value in list(value.items())[:24]:
        if not isinstance(raw_key, str) or not raw_key.strip():
            continue
        key = raw_key.strip()[:80]
        if isinstance(raw_value, str):
            result[key] = raw_value.strip()[:240]
        elif raw_value is None or isinstance(raw_value, (bool, int, float)):
            result[key] = raw_value
    return result


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None
