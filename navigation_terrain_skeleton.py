"""Continuous candidate terrain skeletons from bounded DEM elevation grids."""

from __future__ import annotations

from collections import deque
import math
from typing import Any, Iterable, Mapping, Sequence

from navigation_terrain_coordinates import twd97_to_wgs84
from navigation_terrain_dem import (
    WorkspaceTerrainEvidenceError,
    classify_structure_neighborhood,
)

Cell = tuple[float, float]
Link = tuple[Cell, Cell]

AXES: tuple[tuple[int, int], ...] = (
    (1, 0),
    (1, 1),
    (0, 1),
    (-1, 1),
)
NEIGHBOR_OFFSETS: tuple[tuple[int, int], ...] = (
    (0, 1),
    (1, 1),
    (1, 0),
    (1, -1),
    (0, -1),
    (-1, -1),
    (-1, 0),
    (-1, 1),
)


def build_terrain_hierarchy_from_grid(
    elevations: Mapping[tuple[float, float], float],
    *,
    resolution_m: float,
    source_refs: Sequence[str],
    relief_threshold_m: float = 4.0,
    analysis_scales: Sequence[int] = (1, 2),
    minimum_component_cells: int = 4,
    max_edges_per_network: int = 180,
    vertical_datum: str | None = None,
) -> dict[str, Any]:
    """Build a candidate ridge/drainage hierarchy from a regular elevation grid.

    This extracts terrain form, not trails. Cross-section extrema are linked
    along their inferred landform axis, then compressed into a reusable graph.
    """

    grid = _normalize_grid(elevations)
    resolution = _required_positive(resolution_m, "resolution_m")
    threshold = _required_positive(relief_threshold_m, "relief_threshold_m")
    scales = _normalize_scales(analysis_scales)
    refs = _normalize_refs(source_refs)
    if minimum_component_cells < 2 or minimum_component_cells > 100:
        raise WorkspaceTerrainEvidenceError(
            "minimum_component_cells must be between 2 and 100"
        )
    if max_edges_per_network < 4 or max_edges_per_network > 1000:
        raise WorkspaceTerrainEvidenceError(
            "max_edges_per_network must be between 4 and 1000"
        )
    if len(grid) < 9:
        raise WorkspaceTerrainEvidenceError(
            "terrain hierarchy requires at least nine elevation cells"
        )

    ridge_candidates = _cross_section_candidates(
        grid,
        resolution_m=resolution,
        scales=scales,
        threshold_m=threshold,
        mode="ridge",
    )
    drainage_candidates = _cross_section_candidates(
        grid,
        resolution_m=resolution,
        scales=scales,
        threshold_m=threshold,
        mode="drainage",
    )
    ridge_graph = _candidate_graph(
        ridge_candidates,
        resolution_m=resolution,
        minimum_component_cells=minimum_component_cells,
    )
    drainage_graph = _candidate_graph(
        drainage_candidates,
        resolution_m=resolution,
        minimum_component_cells=minimum_component_cells,
    )
    ridge_nodes, ridge_edges = _compress_network(
        ridge_graph,
        grid,
        network_kind="ridge",
        source_refs=refs,
        max_edges=max_edges_per_network,
    )
    drainage_nodes, drainage_edges = _compress_network(
        drainage_graph,
        grid,
        network_kind="drainage",
        source_refs=refs,
        max_edges=max_edges_per_network,
    )
    saddle_nodes = _saddle_nodes(
        grid,
        ridge_candidates,
        resolution_m=resolution,
        relief_threshold_m=threshold,
        source_refs=refs,
    )
    nodes = _renumber_nodes([*ridge_nodes, *drainage_nodes, *saddle_nodes])
    node_id_by_key = {
        (item["_network"], item["_cell"]): item["id"]
        for item in nodes
        if item.get("_cell") is not None
    }
    edges = _renumber_edges(
        [*ridge_edges, *drainage_edges],
        node_id_by_key=node_id_by_key,
    )
    public_nodes = [_public_node(item) for item in nodes]

    return {
        "schema_version": "scout_navigation_terrain_hierarchy.v0",
        "artifact_kind": "dem_terrain_hierarchy_candidates",
        "status": "candidate_hierarchy" if edges else "not_prepared",
        "grid": {
            "crs": "EPSG:3826",
            "vertical_datum": vertical_datum,
            "cell_resolution_m": resolution,
            "selected_cell_count": len(grid),
            "bbox_twd97": _grid_bbox(grid),
        },
        "method": {
            "ridge_extraction": "multi_scale_cross_section_maxima_skeleton.v0",
            "drainage_extraction": ("multi_scale_cross_section_minima_skeleton.v0"),
            "hierarchy": "component_backbone_and_branch_compression.v0",
            "analysis_scales_cells": scales,
            "relief_threshold_m": threshold,
            "minimum_component_cells": minimum_component_cells,
        },
        "ontology": {
            "terrain_edge_kinds": [
                "main_ridge_candidate",
                "spur_ridge_candidate",
                "drainage_trunk",
                "tributary",
                "watershed_boundary",
            ],
            "terrain_node_kinds": [
                "ridge_divide_node",
                "ridge_end_node",
                "saddle_node",
                "drainage_confluence_node",
                "headwater_node",
                "drainage_outlet_node",
            ],
            "contour_traverse_band_is_ridge": False,
            "terrain_bifurcation_is_route_fork": False,
        },
        "counts": {
            "ridge_candidate_cells": len(ridge_candidates),
            "drainage_candidate_cells": len(drainage_candidates),
            "node_count": len(public_nodes),
            "edge_count": len(edges),
            "main_ridge_count": _kind_count(edges, "main_ridge_candidate"),
            "spur_ridge_count": _kind_count(edges, "spur_ridge_candidate"),
            "drainage_trunk_count": _kind_count(edges, "drainage_trunk"),
            "tributary_count": _kind_count(edges, "tributary"),
            "saddle_count": _kind_count(public_nodes, "saddle_node"),
        },
        "nodes": public_nodes,
        "edges": edges,
        "source_refs": refs,
        "limitations": [
            "DEM morphology does not prove that a trail exists or is walkable.",
            (
                "Main/spur and trunk/tributary labels are graph hierarchy "
                "candidates and require expert map or field review."
            ),
            (
                "Vegetation, cliffs, erosion, stream discharge, access, and "
                "current surface condition are not resolved."
            ),
            (
                "Contour-compatible traverse bands are a separate route-search "
                "layer and are not relabeled as ridges."
            ),
        ],
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "safe_or_walkable": "not_determined",
            "raw_dem_embedded": False,
            "human_review_required": True,
            "phase1_runtime_mutation_allowed": False,
            "safety_api_called": False,
        },
    }


def _cross_section_candidates(
    grid: Mapping[Cell, float],
    *,
    resolution_m: float,
    scales: Sequence[int],
    threshold_m: float,
    mode: str,
) -> dict[Cell, dict[str, Any]]:
    candidates: dict[Cell, dict[str, Any]] = {}
    for cell, center in grid.items():
        best: tuple[float, int] | None = None
        for axis_index, axis in enumerate(AXES):
            normal = (-axis[1], axis[0])
            differences = []
            for scale in scales:
                offset_x = normal[0] * resolution_m * scale
                offset_y = normal[1] * resolution_m * scale
                side_a = grid.get(_cell(cell[0] + offset_x, cell[1] + offset_y))
                side_b = grid.get(_cell(cell[0] - offset_x, cell[1] - offset_y))
                if side_a is None or side_b is None:
                    continue
                cross_mean = (side_a + side_b) / 2.0
                differences.append(
                    center - cross_mean if mode == "ridge" else cross_mean - center
                )
            if not differences:
                continue
            score = sum(differences) / len(differences)
            if best is None or score > best[0]:
                best = (score, axis_index)
        if best is None or best[0] < threshold_m:
            continue
        candidates[cell] = {
            "axis_index": best[1],
            "score": round(best[0], 3),
        }
    return candidates


def _candidate_graph(
    candidates: Mapping[Cell, dict[str, Any]],
    *,
    resolution_m: float,
    minimum_component_cells: int,
) -> dict[Cell, set[Cell]]:
    graph = {cell: set() for cell in candidates}
    for cell, item in candidates.items():
        axis = AXES[int(item["axis_index"])]
        directed_neighbors = {
            _cell(
                cell[0] + sign * axis[0] * resolution_m,
                cell[1] + sign * axis[1] * resolution_m,
            )
            for sign in (-1, 1)
        }
        for dx, dy in NEIGHBOR_OFFSETS:
            neighbor = _cell(
                cell[0] + dx * resolution_m,
                cell[1] + dy * resolution_m,
            )
            if neighbor not in candidates:
                continue
            neighbor_axis = AXES[int(candidates[neighbor]["axis_index"])]
            neighbor_points_back = cell in {
                _cell(
                    neighbor[0] + sign * neighbor_axis[0] * resolution_m,
                    neighbor[1] + sign * neighbor_axis[1] * resolution_m,
                )
                for sign in (-1, 1)
            }
            if neighbor not in directed_neighbors and not neighbor_points_back:
                continue
            graph[cell].add(neighbor)
            graph[neighbor].add(cell)
    retained = {
        cell
        for component in _components(graph)
        if len(component) >= minimum_component_cells
        for cell in component
    }
    return {
        cell: {neighbor for neighbor in neighbors if neighbor in retained}
        for cell, neighbors in graph.items()
        if cell in retained
    }


def _compress_network(
    graph: Mapping[Cell, set[Cell]],
    grid: Mapping[Cell, float],
    *,
    network_kind: str,
    source_refs: list[str],
    max_edges: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not graph:
        return [], []
    nodes: dict[Cell, dict[str, Any]] = {}
    edge_records: list[dict[str, Any]] = []
    for component_number, component in enumerate(_components(graph), start=1):
        component_graph = {
            cell: {neighbor for neighbor in graph[cell] if neighbor in component}
            for cell in component
        }
        backbone_links = _component_backbone_links(component_graph)
        critical = {
            cell for cell, neighbors in component_graph.items() if len(neighbors) != 2
        }
        if not critical:
            critical = {min(component)}
        component_endpoints = [
            cell for cell in component if len(component_graph[cell]) <= 1
        ]
        drainage_outlet = min(
            component_endpoints or [min(component)],
            key=lambda cell: grid[cell],
        )
        for cell in critical:
            nodes[cell] = _network_node(
                cell,
                component_graph,
                grid,
                network_kind=network_kind,
                component_number=component_number,
                drainage_outlet=drainage_outlet,
                source_refs=source_refs,
            )
        visited_links: set[Link] = set()
        for start in sorted(critical):
            for neighbor in sorted(component_graph[start]):
                first_link = _link(start, neighbor)
                if first_link in visited_links:
                    continue
                path = [start, neighbor]
                visited_links.add(first_link)
                previous, current = start, neighbor
                while current not in critical:
                    next_cells = component_graph[current] - {previous}
                    if not next_cells:
                        break
                    next_cell = sorted(next_cells)[0]
                    visited_links.add(_link(current, next_cell))
                    path.append(next_cell)
                    previous, current = current, next_cell
                if path[-1] not in nodes:
                    nodes[path[-1]] = _network_node(
                        path[-1],
                        component_graph,
                        grid,
                        network_kind=network_kind,
                        component_number=component_number,
                        drainage_outlet=drainage_outlet,
                        source_refs=source_refs,
                    )
                path_links = {_link(a, b) for a, b in zip(path, path[1:])}
                backbone_ratio = (
                    len(path_links & backbone_links) / len(path_links)
                    if path_links
                    else 0.0
                )
                edge_kind = (
                    "main_ridge_candidate"
                    if network_kind == "ridge" and backbone_ratio >= 0.5
                    else "spur_ridge_candidate"
                    if network_kind == "ridge"
                    else "drainage_trunk"
                    if backbone_ratio >= 0.5
                    else "tributary"
                )
                edge_records.append(
                    _network_edge(
                        path,
                        grid,
                        edge_kind=edge_kind,
                        network_kind=network_kind,
                        component_number=component_number,
                        source_refs=source_refs,
                        start_cell=start,
                        end_cell=path[-1],
                    )
                )
    ranked = sorted(
        edge_records,
        key=lambda item: (
            -float(item["length_m"]),
            item["_start_cell"],
            item["_end_cell"],
        ),
    )[:max_edges]
    used_cells = {
        cell for item in ranked for cell in (item["_start_cell"], item["_end_cell"])
    }
    return [nodes[cell] for cell in sorted(used_cells)], ranked


def _network_node(
    cell: Cell,
    graph: Mapping[Cell, set[Cell]],
    grid: Mapping[Cell, float],
    *,
    network_kind: str,
    component_number: int,
    drainage_outlet: Cell,
    source_refs: list[str],
) -> dict[str, Any]:
    degree = len(graph.get(cell, set()))
    if network_kind == "ridge":
        kind = "ridge_divide_node" if degree >= 3 else "ridge_end_node"
    elif degree >= 3:
        kind = "drainage_confluence_node"
    else:
        kind = "drainage_outlet_node" if cell == drainage_outlet else "headwater_node"
    return {
        "_cell": cell,
        "_network": network_kind,
        "_component_number": component_number,
        "kind": kind,
        "degree": degree,
        "x_twd97": cell[0],
        "y_twd97": cell[1],
        "elevation_m": round(grid[cell], 2),
        "source_refs": source_refs,
    }


def _network_edge(
    path: Sequence[Cell],
    grid: Mapping[Cell, float],
    *,
    edge_kind: str,
    network_kind: str,
    component_number: int,
    source_refs: list[str],
    start_cell: Cell,
    end_cell: Cell,
) -> dict[str, Any]:
    coordinates_twd97 = [[cell[0], cell[1], round(grid[cell], 2)] for cell in path]
    coordinates_wgs84 = []
    for cell in path:
        lat, lon = twd97_to_wgs84(cell[0], cell[1])
        coordinates_wgs84.append([round(lon, 8), round(lat, 8)])
    return {
        "_start_cell": start_cell,
        "_end_cell": end_cell,
        "_network": network_kind,
        "_component_number": component_number,
        "kind": edge_kind,
        "coordinates_twd97": coordinates_twd97,
        "coordinates_wgs84": coordinates_wgs84,
        "length_m": round(
            sum(_distance(a, b) for a, b in zip(path, path[1:])),
            2,
        ),
        "watershed_boundary_candidate": network_kind == "ridge",
        "source_refs": source_refs,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "requires_human_review": True,
    }


def _saddle_nodes(
    grid: Mapping[Cell, float],
    ridge_candidates: Mapping[Cell, dict[str, Any]],
    *,
    resolution_m: float,
    relief_threshold_m: float,
    source_refs: list[str],
) -> list[dict[str, Any]]:
    saddles = []
    for cell, center in grid.items():
        neighbors = [
            grid.get(
                _cell(
                    cell[0] + dx * resolution_m,
                    cell[1] + dy * resolution_m,
                )
            )
            for dx, dy in NEIGHBOR_OFFSETS
        ]
        if any(value is None for value in neighbors):
            continue
        metrics = classify_structure_neighborhood(
            center,
            [float(value) for value in neighbors if value is not None],
            relief_threshold_m=relief_threshold_m,
        )
        if metrics["feature_kind"] != "saddle":
            continue
        if ridge_candidates and not any(
            _cell(
                cell[0] + dx * resolution_m,
                cell[1] + dy * resolution_m,
            )
            in ridge_candidates
            for dx in range(-2, 3)
            for dy in range(-2, 3)
        ):
            continue
        saddles.append(
            {
                "_cell": cell,
                "_network": "saddle",
                "_component_number": 0,
                "kind": "saddle_node",
                "degree": 0,
                "x_twd97": cell[0],
                "y_twd97": cell[1],
                "elevation_m": round(center, 2),
                "source_refs": source_refs,
            }
        )
    selected: list[dict[str, Any]] = []
    for item in sorted(saddles, key=lambda value: (value["_cell"],)):
        if any(
            _distance(item["_cell"], existing["_cell"]) < resolution_m * 2
            for existing in selected
        ):
            continue
        selected.append(item)
        if len(selected) >= 32:
            break
    return selected


def _renumber_nodes(nodes: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(
        nodes,
        key=lambda item: (
            str(item["kind"]),
            float(item["x_twd97"]),
            float(item["y_twd97"]),
        ),
    )
    counters: dict[str, int] = {}
    result = []
    for item in ordered:
        kind = str(item["kind"])
        counters[kind] = counters.get(kind, 0) + 1
        result.append(
            {
                **item,
                "id": f"terrain-node.{kind}.{counters[kind]:03d}",
            }
        )
    return result


def _renumber_edges(
    edges: Sequence[dict[str, Any]],
    *,
    node_id_by_key: Mapping[tuple[str, Cell], str],
) -> list[dict[str, Any]]:
    ordered = sorted(
        edges,
        key=lambda item: (
            str(item["kind"]),
            item["_start_cell"],
            item["_end_cell"],
        ),
    )
    counters: dict[str, int] = {}
    result = []
    for item in ordered:
        kind = str(item["kind"])
        counters[kind] = counters.get(kind, 0) + 1
        network = str(item["_network"])
        public = {key: value for key, value in item.items() if not key.startswith("_")}
        result.append(
            {
                "id": f"terrain-edge.{kind}.{counters[kind]:03d}",
                "from": node_id_by_key.get((network, item["_start_cell"])),
                "to": node_id_by_key.get((network, item["_end_cell"])),
                **public,
            }
        )
    return result


def _public_node(item: dict[str, Any]) -> dict[str, Any]:
    lat, lon = twd97_to_wgs84(item["x_twd97"], item["y_twd97"])
    return {key: value for key, value in item.items() if not key.startswith("_")} | {
        "lon": round(lon, 8),
        "lat": round(lat, 8),
        "candidate_only": True,
        "runtime_safety_truth": False,
        "requires_human_review": True,
    }


def _component_backbone_links(graph: Mapping[Cell, set[Cell]]) -> set[Link]:
    if not graph:
        return set()
    start = min(graph)
    endpoint, _ = _farthest_with_parent(graph, start)
    opposite, parent = _farthest_with_parent(graph, endpoint)
    links: set[Link] = set()
    current = opposite
    while current != endpoint and current in parent:
        previous = parent[current]
        links.add(_link(current, previous))
        current = previous
    return links


def _farthest_with_parent(
    graph: Mapping[Cell, set[Cell]],
    start: Cell,
) -> tuple[Cell, dict[Cell, Cell]]:
    queue = deque([start])
    distance = {start: 0}
    parent: dict[Cell, Cell] = {}
    while queue:
        cell = queue.popleft()
        for neighbor in sorted(graph[cell]):
            if neighbor in distance:
                continue
            distance[neighbor] = distance[cell] + 1
            parent[neighbor] = cell
            queue.append(neighbor)
    farthest = max(distance, key=lambda cell: (distance[cell], cell))
    return farthest, parent


def _components(graph: Mapping[Cell, set[Cell]]) -> list[set[Cell]]:
    remaining = set(graph)
    components = []
    while remaining:
        seed = min(remaining)
        component = set()
        queue = [seed]
        while queue:
            cell = queue.pop()
            if cell in component:
                continue
            component.add(cell)
            queue.extend(graph.get(cell, set()) - component)
        remaining -= component
        components.append(component)
    return components


def _normalize_grid(
    elevations: Mapping[tuple[float, float], float],
) -> dict[Cell, float]:
    if not isinstance(elevations, Mapping):
        raise WorkspaceTerrainEvidenceError("elevations must be a coordinate map")
    normalized = {}
    for coordinate, raw_elevation in elevations.items():
        if not isinstance(coordinate, tuple) or len(coordinate) != 2:
            raise WorkspaceTerrainEvidenceError(
                "elevation grid keys must be (x, y) tuples"
            )
        try:
            x = float(coordinate[0])
            y = float(coordinate[1])
            elevation = float(raw_elevation)
        except (TypeError, ValueError) as exc:
            raise WorkspaceTerrainEvidenceError(
                "elevation grid contains non-numeric values"
            ) from exc
        if not all(math.isfinite(value) for value in (x, y, elevation)):
            raise WorkspaceTerrainEvidenceError(
                "elevation grid contains non-finite values"
            )
        normalized[_cell(x, y)] = elevation
    return normalized


def _normalize_scales(value: Sequence[int]) -> list[int]:
    if not isinstance(value, Sequence):
        raise WorkspaceTerrainEvidenceError("analysis_scales must be a sequence")
    scales = sorted(
        {
            int(item)
            for item in value
            if isinstance(item, (int, float)) and 1 <= int(item) <= 8
        }
    )
    if not scales:
        raise WorkspaceTerrainEvidenceError("analysis_scales has no usable scale")
    return scales


def _normalize_refs(value: Sequence[str]) -> list[str]:
    refs = list(
        dict.fromkeys(
            item.strip()[:500]
            for item in value
            if isinstance(item, str) and item.strip()
        )
    )
    if not refs:
        raise WorkspaceTerrainEvidenceError("source_refs must be non-empty")
    return refs[:32]


def _grid_bbox(grid: Mapping[Cell, float]) -> dict[str, float]:
    xs = [cell[0] for cell in grid]
    ys = [cell[1] for cell in grid]
    return {
        "min_x": min(xs),
        "min_y": min(ys),
        "max_x": max(xs),
        "max_y": max(ys),
    }


def _kind_count(items: Iterable[dict[str, Any]], kind: str) -> int:
    return sum(item.get("kind") == kind for item in items)


def _link(a: Cell, b: Cell) -> Link:
    return (a, b) if a <= b else (b, a)


def _distance(a: Cell, b: Cell) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _cell(x: float, y: float) -> Cell:
    return round(float(x), 6), round(float(y), 6)


def _required_positive(value: Any, field_name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise WorkspaceTerrainEvidenceError(f"{field_name} must be positive") from exc
    if not math.isfinite(number) or number <= 0:
        raise WorkspaceTerrainEvidenceError(f"{field_name} must be positive")
    return number
