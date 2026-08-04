"""Conditioned MFD drainage candidates for bounded Scout DEM windows."""

from __future__ import annotations

import heapq
import math
from typing import Any, Mapping, Sequence

import numpy as np

from navigation_terrain_morphometry import (
    Cell,
    NEIGHBOR_OFFSETS,
    extract_morphometric_candidates,
    regular_grid_arrays,
    retain_large_components,
)


def extract_conditioned_mfd_drainage(
    grid: Mapping[Cell, float],
    *,
    resolution_m: float,
    scales: Sequence[int],
    threshold_m: float,
    minimum_component_cells: int,
) -> tuple[dict[Cell, dict[str, Any]], dict[Cell, set[Cell]], dict[str, Any]]:
    """Return valley-supported cells and a directed-downstream candidate graph."""

    candidates = extract_morphometric_candidates(
        grid,
        resolution_m=resolution_m,
        scales=scales,
        threshold_m=threshold_m,
        mode="valley",
    )
    array, xs, ys, cell_by_index = regular_grid_arrays(grid, resolution_m)
    index_by_cell = {cell: index for index, cell in cell_by_index.items()}
    conditioned = _priority_flood_condition(array, resolution_m=resolution_m)
    accumulation, downstream = _mfd_accumulation(
        conditioned,
        resolution_m=resolution_m,
    )
    supported: dict[Cell, dict[str, Any]] = {}
    suppressed_by_conditioning_count = 0
    maximum_supported_conditioning_delta_m = max(
        threshold_m * 2.0,
        resolution_m * 0.5,
    )
    for cell, item in candidates.items():
        index = index_by_cell.get(cell)
        if index is None:
            continue
        row, col = index
        flow_accumulation = float(accumulation[row, col])
        conditioning_delta_m = float(conditioned[row, col] - array[row, col])
        if conditioning_delta_m > maximum_supported_conditioning_delta_m:
            suppressed_by_conditioning_count += 1
            continue
        if flow_accumulation < 2.0 and float(item.get("score", 0.0)) < threshold_m * 2:
            continue
        flow_vector = _weighted_flow_vector(downstream.get(index, []))
        tangent = flow_vector or item.get("tangent")
        supported[cell] = {
            **item,
            "tangent": tangent,
            "flow_vector": flow_vector,
            "flow_accumulation": flow_accumulation,
            "conditioned_elevation_m": float(conditioned[row, col]),
            "conditioning_delta_m": conditioning_delta_m,
            "flow_supported": True,
        }

    graph = {cell: set() for cell in supported}
    downstream_by_cell: dict[Cell, Cell] = {}
    for cell, item in supported.items():
        index = index_by_cell[cell]
        target = _best_supported_downstream(
            cell,
            index,
            item,
            supported,
            index_by_cell,
            cell_by_index,
            downstream,
            resolution_m=resolution_m,
        )
        if target is None:
            continue
        downstream_by_cell[cell] = target
        graph[cell].add(target)
        graph[target].add(cell)
    graph = retain_large_components(
        graph,
        minimum_component_cells=minimum_component_cells,
    )
    downstream_by_cell = {
        cell: target
        for cell, target in downstream_by_cell.items()
        if cell in graph and target in graph
    }
    stream_order = _stream_orders(
        graph,
        downstream_by_cell,
        supported,
    )
    supported = {
        cell: {
            **supported[cell],
            "downstream_cell": downstream_by_cell.get(cell),
            **stream_order[cell],
        }
        for cell in graph
    }

    finite_delta = conditioned - array
    finite_delta = finite_delta[np.isfinite(finite_delta)]
    return supported, graph, {
        "flow_model": "multiple_flow_direction_slope_weighted.v1",
        "conditioning": "priority_flood_epsilon.v1",
        "maximum_conditioning_delta_m": (
            round(float(np.max(finite_delta)), 4) if finite_delta.size else 0.0
        ),
        "maximum_supported_conditioning_delta_m": round(
            maximum_supported_conditioning_delta_m,
            4,
        ),
        "suppressed_by_conditioning_count": suppressed_by_conditioning_count,
        "flow_supported_cell_count": len(supported),
        "maximum_strahler_order": max(
            (int(item["strahler_order"]) for item in supported.values()),
            default=0,
        ),
        "maximum_shreve_magnitude": max(
            (int(item["shreve_magnitude"]) for item in supported.values()),
            default=0,
        ),
        "drainage_graph_acyclic_by_construction": _is_strictly_downstream(
            downstream_by_cell,
            supported,
        ),
    }


def _priority_flood_condition(
    array: np.ndarray,
    *,
    resolution_m: float,
) -> np.ndarray:
    finite = np.isfinite(array)
    conditioned = np.array(array, copy=True, dtype=float)
    visited = np.zeros(array.shape, dtype=bool)
    heap: list[tuple[float, int, int]] = []
    rows, cols = array.shape
    for row in range(rows):
        for col in range(cols):
            if not finite[row, col] or not _is_boundary_cell(finite, row, col):
                continue
            visited[row, col] = True
            heapq.heappush(heap, (float(conditioned[row, col]), row, col))
    epsilon = max(1e-6, resolution_m * 1e-7)
    while heap:
        elevation, row, col = heapq.heappop(heap)
        for dr, dc in NEIGHBOR_OFFSETS:
            next_row, next_col = row + dr, col + dc
            if not (0 <= next_row < rows and 0 <= next_col < cols):
                continue
            if not finite[next_row, next_col] or visited[next_row, next_col]:
                continue
            visited[next_row, next_col] = True
            original = float(array[next_row, next_col])
            filled = original if original > elevation else elevation + epsilon
            conditioned[next_row, next_col] = filled
            heapq.heappush(heap, (filled, next_row, next_col))
    return conditioned


def _mfd_accumulation(
    conditioned: np.ndarray,
    *,
    resolution_m: float,
) -> tuple[np.ndarray, dict[tuple[int, int], list[tuple[int, int, float]]]]:
    finite_indices = [
        (row, col)
        for row in range(conditioned.shape[0])
        for col in range(conditioned.shape[1])
        if math.isfinite(float(conditioned[row, col]))
    ]
    downstream: dict[tuple[int, int], list[tuple[int, int, float]]] = {}
    for row, col in finite_indices:
        source = float(conditioned[row, col])
        weighted: list[tuple[int, int, float]] = []
        for dr, dc in NEIGHBOR_OFFSETS:
            next_row, next_col = row + dr, col + dc
            if not (
                0 <= next_row < conditioned.shape[0]
                and 0 <= next_col < conditioned.shape[1]
            ):
                continue
            target = float(conditioned[next_row, next_col])
            if not math.isfinite(target) or target >= source:
                continue
            distance = resolution_m * math.hypot(dr, dc)
            slope = (source - target) / distance
            if slope > 0:
                weighted.append((next_row, next_col, slope**1.1))
        total = sum(item[2] for item in weighted)
        downstream[(row, col)] = [
            (next_row, next_col, weight / total)
            for next_row, next_col, weight in weighted
        ] if total > 0 else []

    accumulation = np.zeros_like(conditioned, dtype=float)
    accumulation[np.isfinite(conditioned)] = 1.0
    for row, col in sorted(
        finite_indices,
        key=lambda index: (-float(conditioned[index]), index),
    ):
        for next_row, next_col, weight in downstream[(row, col)]:
            accumulation[next_row, next_col] += accumulation[row, col] * weight
    return accumulation, downstream


def _best_supported_downstream(
    cell: Cell,
    index: tuple[int, int],
    item: Mapping[str, Any],
    supported: Mapping[Cell, dict[str, Any]],
    index_by_cell: Mapping[Cell, tuple[int, int]],
    cell_by_index: Mapping[tuple[int, int], Cell],
    downstream: Mapping[tuple[int, int], list[tuple[int, int, float]]],
    *,
    resolution_m: float,
) -> Cell | None:
    direct = []
    for row, col, weight in downstream.get(index, []):
        target = cell_by_index.get((row, col))
        target_item = supported.get(target) if target is not None else None
        if target_item is None:
            continue
        if float(target_item["flow_accumulation"]) <= float(item["flow_accumulation"]):
            continue
        direct.append((weight, target))
    if direct:
        return max(direct, key=lambda value: (value[0], value[1]))[1]

    point = _point(item, cell)
    flow_vector = item.get("flow_vector")
    candidates: list[tuple[float, Cell]] = []
    for dx in range(-2, 3):
        for dy in range(-2, 3):
            if dx == 0 and dy == 0:
                continue
            target = (
                round(cell[0] + dx * resolution_m, 6),
                round(cell[1] + dy * resolution_m, 6),
            )
            target_item = supported.get(target)
            if target_item is None:
                continue
            if float(target_item["flow_accumulation"]) <= float(item["flow_accumulation"]):
                continue
            if float(target_item["conditioned_elevation_m"]) > float(
                item["conditioned_elevation_m"]
            ) + 1e-5:
                continue
            target_point = _point(target_item, target)
            vector = _unit(
                (target_point[0] - point[0], target_point[1] - point[1])
            )
            if vector is None:
                continue
            alignment = _dot(vector, flow_vector) if flow_vector is not None else 0.0
            if flow_vector is not None and alignment < 0.1:
                continue
            distance = math.dist(point, target_point)
            score = alignment - 0.12 * distance / resolution_m
            candidates.append((score, target))
    return max(candidates, default=(0.0, None), key=lambda value: (value[0], value[1]))[1]


def _stream_orders(
    graph: Mapping[Cell, set[Cell]],
    downstream_by_cell: Mapping[Cell, Cell],
    supported: Mapping[Cell, dict[str, Any]],
) -> dict[Cell, dict[str, int]]:
    incoming: dict[Cell, list[Cell]] = {cell: [] for cell in graph}
    for source, target in downstream_by_cell.items():
        incoming[target].append(source)
    result: dict[Cell, dict[str, int]] = {}
    ordered = sorted(
        graph,
        key=lambda cell: (
            float(supported[cell]["flow_accumulation"]),
            cell,
        ),
    )
    for cell in ordered:
        upstream = [source for source in incoming[cell] if source in result]
        if not upstream:
            result[cell] = {"strahler_order": 1, "shreve_magnitude": 1}
            continue
        upstream_orders = [result[source]["strahler_order"] for source in upstream]
        maximum_order = max(upstream_orders)
        strahler = maximum_order + 1 if upstream_orders.count(maximum_order) >= 2 else maximum_order
        result[cell] = {
            "strahler_order": strahler,
            "shreve_magnitude": sum(
                result[source]["shreve_magnitude"] for source in upstream
            ),
        }
    return result


def _is_strictly_downstream(
    downstream_by_cell: Mapping[Cell, Cell],
    supported: Mapping[Cell, dict[str, Any]],
) -> bool:
    return all(
        float(supported[target]["flow_accumulation"])
        > float(supported[source]["flow_accumulation"])
        and float(supported[target]["conditioned_elevation_m"])
        <= float(supported[source]["conditioned_elevation_m"]) + 1e-5
        for source, target in downstream_by_cell.items()
    )


def _weighted_flow_vector(
    values: Sequence[tuple[int, int, float]],
) -> tuple[float, float] | None:
    x = sum(dc * weight for dr, dc, weight in values)
    y = sum(dr * weight for dr, dc, weight in values)
    return _unit((x, y))


def _is_boundary_cell(finite: np.ndarray, row: int, col: int) -> bool:
    if row in {0, finite.shape[0] - 1} or col in {0, finite.shape[1] - 1}:
        return True
    return any(
        not finite[row + dr, col + dc]
        for dr, dc in NEIGHBOR_OFFSETS
        if 0 <= row + dr < finite.shape[0]
        and 0 <= col + dc < finite.shape[1]
    )


def _point(item: Mapping[str, Any], fallback: Cell) -> tuple[float, float]:
    value = item.get("point")
    if isinstance(value, (tuple, list)) and len(value) >= 2:
        return float(value[0]), float(value[1])
    return fallback


def _unit(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, (tuple, list)) or len(value) < 2:
        return None
    x, y = float(value[0]), float(value[1])
    length = math.hypot(x, y)
    if length <= 1e-12:
        return None
    return x / length, y / length


def _dot(a: tuple[float, float], b: Any) -> float:
    if not isinstance(b, (tuple, list)) or len(b) < 2:
        return 0.0
    return a[0] * float(b[0]) + a[1] * float(b[1])
