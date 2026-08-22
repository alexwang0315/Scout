#!/usr/bin/env python3
"""Compile candidate historical-route hypotheses from sourced terrain evidence.

This module deliberately does not decide whether a route is safe or currently
walkable. It performs deterministic transformations and validation for a
candidate-only research artifact assembled from historical records, DEM-derived
features, and public or Scout-owned GPX evidence.
"""

from __future__ import annotations

import argparse
import heapq
import json
import math
from pathlib import Path
from typing import Any, Iterable, Sequence

Point = tuple[float, float]
Grid = Sequence[Sequence[float]]

SOURCE_TIERS = {"P0", "P1", "P2"}
ALLOWED_EDGE_KINDS = {
    "historical_trace",
    "gpx_observed",
    "dem_horizontal_band",
    "dem_valley_transfer",
    "inferred_connector",
}
TAIWAN_AFFINE_A = 0.00001549
TAIWAN_AFFINE_B = 0.000006521


class InferenceInputError(ValueError):
    """Raised when an inference package violates the candidate contract."""


def twd67_to_twd97(easting: float, northing: float) -> Point:
    """Return the common Taiwan affine approximation from TWD67 to TWD97.

    The approximation is appropriate for coarse map/30 m DEM matching. It is
    not a survey-grade coordinate transformation.
    """

    return (
        easting
        + 807.8
        + TAIWAN_AFFINE_A * easting
        + TAIWAN_AFFINE_B * northing,
        northing
        - 248.6
        + TAIWAN_AFFINE_A * northing
        + TAIWAN_AFFINE_B * easting,
    )


def polyline_length(coordinates: Sequence[Sequence[float]]) -> float:
    """Calculate planar polyline length in input coordinate units."""

    return sum(
        math.dist(coordinates[index - 1], coordinates[index])
        for index in range(1, len(coordinates))
    )


def maximum_adjacent_spacing(coordinates: Sequence[Sequence[float]]) -> float:
    """Return the largest planar step in a polyline."""

    return max(
        (
            math.dist(coordinates[index - 1], coordinates[index])
            for index in range(1, len(coordinates))
        ),
        default=0.0,
    )


def d8_flow_accumulation(
    elevations: Grid,
    *,
    cell_width: float = 1.0,
    cell_height: float = 1.0,
) -> tuple[list[list[int]], list[list[Point | None]]]:
    """Compute simple D8 downstream cells and upstream-cell accumulation.

    Sinks remain without a downstream cell. This intentionally small,
    dependency-free implementation supports deterministic tests and bounded
    DEM windows; production-size rasters should use a reviewed GIS adapter.
    """

    rows, cols = _validate_grid(elevations)
    if cell_width <= 0 or cell_height <= 0:
        raise InferenceInputError("DEM cell dimensions must be positive")

    neighbors = (
        (-1, -1),
        (-1, 0),
        (-1, 1),
        (0, -1),
        (0, 1),
        (1, -1),
        (1, 0),
        (1, 1),
    )
    downstream: list[list[Point | None]] = [
        [None for _ in range(cols)] for _ in range(rows)
    ]
    accumulation = [[1 for _ in range(cols)] for _ in range(rows)]

    for row in range(rows):
        for col in range(cols):
            best: Point | None = None
            best_gradient = 0.0
            for row_delta, col_delta in neighbors:
                next_row = row + row_delta
                next_col = col + col_delta
                if not (0 <= next_row < rows and 0 <= next_col < cols):
                    continue
                distance = math.hypot(
                    row_delta * cell_height,
                    col_delta * cell_width,
                )
                gradient = (
                    float(elevations[row][col])
                    - float(elevations[next_row][next_col])
                ) / distance
                if gradient > best_gradient:
                    best_gradient = gradient
                    best = (next_row, next_col)
            downstream[row][col] = best

    cells_high_to_low = sorted(
        (
            (float(elevations[row][col]), row, col)
            for row in range(rows)
            for col in range(cols)
        ),
        reverse=True,
    )
    for _, row, col in cells_high_to_low:
        next_cell = downstream[row][col]
        if next_cell is None:
            continue
        next_row, next_col = int(next_cell[0]), int(next_cell[1])
        accumulation[next_row][next_col] += accumulation[row][col]

    return accumulation, downstream


def trace_downstream(
    downstream: Sequence[Sequence[Point | None]],
    start: tuple[int, int],
    *,
    max_steps: int = 10_000,
) -> list[tuple[int, int]]:
    """Trace a D8 downstream line while preventing cycles."""

    rows = len(downstream)
    cols = len(downstream[0]) if rows else 0
    row, col = start
    if not (0 <= row < rows and 0 <= col < cols):
        raise InferenceInputError("flowline start is outside the DEM grid")

    result = [(row, col)]
    seen = {(row, col)}
    for _ in range(max_steps):
        next_cell = downstream[row][col]
        if next_cell is None:
            break
        row, col = int(next_cell[0]), int(next_cell[1])
        if (row, col) in seen:
            raise InferenceInputError("D8 downstream graph contains a cycle")
        result.append((row, col))
        seen.add((row, col))
    return result


def enumerate_topology_paths(
    edges: Sequence[dict[str, Any]],
    start_node: str,
    end_node: str,
    *,
    max_paths: int = 100,
) -> list[list[str]]:
    """Enumerate simple edge paths through shared route topology."""

    if max_paths < 1:
        raise InferenceInputError("max_paths must be at least 1")
    adjacency: dict[str, list[tuple[str, str]]] = {}
    for edge in edges:
        adjacency.setdefault(edge["from"], []).append((edge["to"], edge["id"]))
        if edge.get("bidirectional", True):
            adjacency.setdefault(edge["to"], []).append((edge["from"], edge["id"]))

    results: list[list[str]] = []
    stack: list[tuple[str, list[str], frozenset[str]]] = [
        (start_node, [], frozenset({start_node}))
    ]
    while stack and len(results) < max_paths:
        node, path, visited = stack.pop()
        if node == end_node:
            results.append(path)
            continue
        for next_node, edge_id in reversed(adjacency.get(node, [])):
            if next_node in visited:
                continue
            stack.append((next_node, path + [edge_id], visited | {next_node}))
    return results


def shortest_topology_path(
    edges: Sequence[dict[str, Any]],
    start_node: str,
    end_node: str,
) -> list[str]:
    """Return the lowest-cost edge sequence, if a connected path exists."""

    adjacency: dict[str, list[tuple[str, str, float]]] = {}
    for edge in edges:
        cost = float(edge.get("cost", edge.get("length_m", 1.0)))
        adjacency.setdefault(edge["from"], []).append((edge["to"], edge["id"], cost))
        if edge.get("bidirectional", True):
            adjacency.setdefault(edge["to"], []).append((edge["from"], edge["id"], cost))

    queue: list[tuple[float, str, list[str]]] = [(0.0, start_node, [])]
    best_cost: dict[str, float] = {}
    while queue:
        cost, node, path = heapq.heappop(queue)
        if cost >= best_cost.get(node, math.inf):
            continue
        best_cost[node] = cost
        if node == end_node:
            return path
        for next_node, edge_id, edge_cost in adjacency.get(node, []):
            heapq.heappush(queue, (cost + edge_cost, next_node, path + [edge_id]))
    return []


def compile_route_hypothesis(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate and compile a candidate-only route-inference artifact."""

    project_id = _required_text(payload, "project_id")
    route_name = _required_text(payload, "route_name")
    sources = _validate_sources(payload.get("sources", []))
    source_ids = {source["id"] for source in sources}
    anchors = _normalize_anchors(payload.get("anchors", []), source_ids)
    nodes = _validate_nodes(payload.get("nodes", []), source_ids)
    coordinate_context = _coordinate_context(
        payload.get("coordinate_context", {})
    )
    edges = _validate_edges(
        payload.get("edges", []),
        nodes,
        source_ids,
        geometry_crs=str(coordinate_context.get("geometry_crs") or ""),
    )
    contradictions = _validate_contradictions(
        payload.get("contradictions", []),
        source_ids,
    )

    start_node = _required_text(payload, "start_node")
    end_node = _required_text(payload, "end_node")
    node_ids = {node["id"] for node in nodes}
    if start_node not in node_ids or end_node not in node_ids:
        raise InferenceInputError("start_node and end_node must reference topology nodes")

    route_options = enumerate_topology_paths(
        edges,
        start_node,
        end_node,
        max_paths=int(payload.get("max_paths", 100)),
    )
    if not route_options:
        raise InferenceInputError("topology has no path from start_node to end_node")

    shortest = shortest_topology_path(edges, start_node, end_node)
    route_option_labels = _route_option_labels(
        route_options,
        payload.get("route_option_labels_by_edge_signature"),
    )
    source_tier_counts = {
        tier: sum(source["tier"] == tier for source in sources)
        for tier in sorted(SOURCE_TIERS)
    }
    evidence_gaps = list(payload.get("evidence_gaps", []))
    if not any(source["tier"] == "P0" for source in sources):
        evidence_gaps.append("No P0 official or baseline source is attached.")
    if not any(edge["kind"] == "gpx_observed" for edge in edges):
        evidence_gaps.append("No GPX-observed edge is attached.")
    if not any(edge["kind"].startswith("dem_") for edge in edges):
        evidence_gaps.append("No DEM-derived terrain edge is attached.")

    return {
        "schema_version": "0.1.0",
        "status": "candidate_route_hypothesis_compiled",
        "project_id": project_id,
        "route_name": route_name,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "safe_or_walkable": "not_determined",
        "coordinate_context": coordinate_context,
        "sources": sources,
        "source_tier_counts": source_tier_counts,
        "anchors": anchors,
        "topology": {
            "start_node": start_node,
            "end_node": end_node,
            "nodes": nodes,
            "edges": edges,
            "route_option_count": len(route_options),
            "route_options_edge_ids": route_options,
            "route_option_labels": route_option_labels,
            "lowest_cost_option_edge_ids": shortest,
            "shared_edge_ids": _shared_edge_ids(route_options),
        },
        "contradictions": contradictions,
        "evidence_gaps": _dedupe_text(evidence_gaps),
        "required_review": [
            "Confirm coordinate datum and transformation method.",
            "Inspect source freshness and conflicts.",
            "Review DEM artifacts, cliffs, river crossings, vegetation, and land access.",
            "Verify candidate geometry against field evidence before operational use.",
        ],
        "prohibited_interpretations": [
            "Do not treat this artifact as proof that a path exists.",
            "Do not treat this artifact as a go/no-go or solo-readiness decision.",
            "Do not write this artifact into runtime safety truth.",
        ],
    }


def _validate_grid(elevations: Grid) -> tuple[int, int]:
    rows = len(elevations)
    cols = len(elevations[0]) if rows else 0
    if rows < 1 or cols < 1:
        raise InferenceInputError("DEM grid must not be empty")
    if any(len(row) != cols for row in elevations):
        raise InferenceInputError("DEM grid rows must have equal length")
    for row in elevations:
        for value in row:
            if not math.isfinite(float(value)):
                raise InferenceInputError("DEM grid contains a non-finite value")
    return rows, cols


def _required_text(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise InferenceInputError(f"{field} must be a non-empty string")
    return value.strip()


def _unique(items: Sequence[dict[str, Any]], label: str) -> None:
    ids = [item.get("id") for item in items]
    if any(not isinstance(item_id, str) or not item_id for item_id in ids):
        raise InferenceInputError(f"every {label} must have a non-empty id")
    if len(ids) != len(set(ids)):
        raise InferenceInputError(f"{label} ids must be unique")


def _validate_sources(sources: Any) -> list[dict[str, Any]]:
    if not isinstance(sources, list) or not sources:
        raise InferenceInputError("sources must be a non-empty list")
    _unique(sources, "source")
    normalized: list[dict[str, Any]] = []
    for source in sources:
        tier = source.get("tier")
        if tier not in SOURCE_TIERS:
            raise InferenceInputError(f"source {source['id']} has invalid tier {tier!r}")
        normalized.append(
            {
                **source,
                "tier": tier,
                "claims": list(source.get("claims", [])),
                "retrieved_at": source.get("retrieved_at"),
            }
        )
    return normalized


def _normalize_anchors(
    anchors: Any,
    source_ids: set[str],
) -> list[dict[str, Any]]:
    if not isinstance(anchors, list):
        raise InferenceInputError("anchors must be a list")
    _unique(anchors, "anchor")
    normalized: list[dict[str, Any]] = []
    for anchor in anchors:
        _validate_source_refs(anchor, source_ids, f"anchor {anchor['id']}")
        crs = anchor.get("crs")
        x = float(anchor["x"])
        y = float(anchor["y"])
        converted = None
        if crs == "EPSG:3828":
            converted_x, converted_y = twd67_to_twd97(x, y)
            converted = {
                "x": converted_x,
                "y": converted_y,
                "crs": "EPSG:3826",
                "method": "taiwan_affine_approximation",
                "survey_grade": False,
            }
        normalized.append({**anchor, "x": x, "y": y, "converted": converted})
    return normalized


def _validate_nodes(nodes: Any, source_ids: set[str]) -> list[dict[str, Any]]:
    if not isinstance(nodes, list) or len(nodes) < 2:
        raise InferenceInputError("nodes must contain at least two items")
    _unique(nodes, "node")
    normalized = []
    for node in nodes:
        _validate_source_refs(node, source_ids, f"node {node['id']}")
        normalized.append({**node, "source_refs": list(node["source_refs"])})
    return normalized


def _validate_edges(
    edges: Any,
    nodes: Sequence[dict[str, Any]],
    source_ids: set[str],
    *,
    geometry_crs: str,
) -> list[dict[str, Any]]:
    if not isinstance(edges, list) or not edges:
        raise InferenceInputError("edges must be a non-empty list")
    _unique(edges, "edge")
    node_ids = {node["id"] for node in nodes}
    normalized: list[dict[str, Any]] = []
    for edge in edges:
        if edge.get("from") not in node_ids or edge.get("to") not in node_ids:
            raise InferenceInputError(f"edge {edge['id']} references an unknown node")
        if edge.get("kind") not in ALLOWED_EDGE_KINDS:
            raise InferenceInputError(f"edge {edge['id']} has an invalid kind")
        _validate_source_refs(edge, source_ids, f"edge {edge['id']}")
        coordinates = edge.get("coordinates")
        if not isinstance(coordinates, list) or len(coordinates) < 2:
            raise InferenceInputError(
                f"edge {edge['id']} must have at least two coordinates"
            )
        numeric_coordinates = [
            [float(point[0]), float(point[1])] for point in coordinates
        ]
        if geometry_crs.casefold() == "epsg:4326":
            length_m = _wgs84_polyline_length(numeric_coordinates)
            max_spacing_m = _wgs84_maximum_adjacent_spacing(
                numeric_coordinates
            )
        else:
            length_m = polyline_length(numeric_coordinates)
            max_spacing_m = maximum_adjacent_spacing(numeric_coordinates)
        normalized.append(
            {
                **edge,
                "coordinates": numeric_coordinates,
                "length_m": round(length_m, 3),
                "max_adjacent_spacing_m": round(max_spacing_m, 3),
                "status": "candidate_only",
                "runtime_safety_truth": False,
            }
        )
    return normalized


def _wgs84_polyline_length(coordinates: Sequence[Sequence[float]]) -> float:
    return sum(
        _wgs84_distance_m(point_a, point_b)
        for point_a, point_b in zip(coordinates, coordinates[1:])
    )


def _wgs84_maximum_adjacent_spacing(
    coordinates: Sequence[Sequence[float]],
) -> float:
    return max(
        (
            _wgs84_distance_m(point_a, point_b)
            for point_a, point_b in zip(coordinates, coordinates[1:])
        ),
        default=0.0,
    )


def _wgs84_distance_m(
    point_a: Sequence[float],
    point_b: Sequence[float],
) -> float:
    lon_a, lat_a = math.radians(point_a[0]), math.radians(point_a[1])
    lon_b, lat_b = math.radians(point_b[0]), math.radians(point_b[1])
    delta_lon = lon_b - lon_a
    delta_lat = lat_b - lat_a
    haversine = (
        math.sin(delta_lat / 2.0) ** 2
        + math.cos(lat_a)
        * math.cos(lat_b)
        * math.sin(delta_lon / 2.0) ** 2
    )
    return 2.0 * 6_371_000.0 * math.asin(min(1.0, math.sqrt(haversine)))


def _validate_source_refs(
    item: dict[str, Any],
    source_ids: set[str],
    label: str,
) -> None:
    refs = item.get("source_refs")
    if not isinstance(refs, list) or not refs:
        raise InferenceInputError(f"{label} must have source_refs")
    unknown = set(refs) - source_ids
    if unknown:
        raise InferenceInputError(f"{label} has unknown source_refs: {sorted(unknown)}")


def _validate_contradictions(
    contradictions: Any,
    source_ids: set[str],
) -> list[dict[str, Any]]:
    if not isinstance(contradictions, list):
        raise InferenceInputError("contradictions must be a list")
    result = []
    for contradiction in contradictions:
        _validate_source_refs(contradiction, source_ids, "contradiction")
        if not contradiction.get("claim"):
            raise InferenceInputError("contradiction must describe its claim")
        result.append(contradiction)
    return result


def _coordinate_context(context: Any) -> dict[str, Any]:
    if not isinstance(context, dict):
        raise InferenceInputError("coordinate_context must be an object")
    return {
        **context,
        "datum_review_required": True,
        "taiwan_affine_approximation_survey_grade": False,
    }


def _shared_edge_ids(paths: Sequence[Sequence[str]]) -> list[str]:
    counts: dict[str, int] = {}
    for path in paths:
        for edge_id in set(path):
            counts[edge_id] = counts.get(edge_id, 0) + 1
    return sorted(edge_id for edge_id, count in counts.items() if count > 1)


def _route_option_labels(
    paths: Sequence[Sequence[str]],
    raw_labels: Any,
) -> list[str]:
    labels = raw_labels if isinstance(raw_labels, dict) else {}
    return [
        str(labels.get("|".join(path)) or f"Historical candidate option {index + 1}")[
            :160
        ]
        for index, path in enumerate(paths)
    ]


def _dedupe_text(items: Iterable[Any]) -> list[str]:
    return list(dict.fromkeys(str(item) for item in items if str(item).strip()))


def _compile_command(input_path: Path, output_path: Path | None) -> int:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    compiled = compile_route_hypothesis(payload)
    rendered = json.dumps(compiled, ensure_ascii=False, indent=2) + "\n"
    if output_path is None:
        print(rendered, end="")
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")
        print(output_path)
    return 0


def _dem_command(input_path: Path, output_path: Path | None) -> int:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    accumulation, downstream = d8_flow_accumulation(
        payload["elevations"],
        cell_width=float(payload.get("cell_width", 1.0)),
        cell_height=float(payload.get("cell_height", 1.0)),
    )
    result = {
        "status": "dem_d8_candidate_compiled",
        "candidate_only": True,
        "runtime_safety_truth": False,
        "accumulation": accumulation,
        "downstream": downstream,
    }
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if output_path is None:
        print(rendered, end="")
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")
        print(output_path)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compile candidate-only historical/DEM/GPX route hypotheses. "
            "This tool does not determine safety or walkability."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    compile_parser = subparsers.add_parser(
        "compile",
        help="validate and compile a route-hypothesis JSON package",
    )
    compile_parser.add_argument("--input", type=Path, required=True)
    compile_parser.add_argument("--output", type=Path)

    dem_parser = subparsers.add_parser(
        "dem-d8",
        help="compute D8 accumulation for a bounded JSON elevation grid",
    )
    dem_parser.add_argument("--input", type=Path, required=True)
    dem_parser.add_argument("--output", type=Path)
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    if args.command == "compile":
        return _compile_command(args.input, args.output)
    if args.command == "dem-d8":
        return _dem_command(args.input, args.output)
    raise AssertionError(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
