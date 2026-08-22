"""Continuous morphometric terrain candidates from a regular DEM grid.

The routines in this module locate ridge/valley extrema at sub-cell positions.
They deliberately keep raw grid support separate from the display geometry so
small smoothing operations cannot invent branches or move a trace outside its
candidate support.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

import numpy as np

Cell = tuple[float, float]

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


def extract_morphometric_candidates(
    grid: Mapping[Cell, float],
    *,
    resolution_m: float,
    scales: Sequence[int],
    threshold_m: float,
    mode: str,
) -> dict[Cell, dict[str, Any]]:
    """Return multi-scale ridge or valley extrema with sub-cell localization."""

    if mode not in {"ridge", "valley"}:
        raise ValueError("mode must be ridge or valley")
    array, xs, ys, cell_by_index = regular_grid_arrays(grid, resolution_m)
    aggregate: dict[Cell, dict[str, Any]] = {}
    persistence: dict[Cell, int] = {}
    for scale in scales:
        smoothed = gaussian_smooth_nan(array, sigma_cells=max(0.65, float(scale)))
        for cell, item in _scale_candidates(
            smoothed,
            array,
            xs,
            ys,
            cell_by_index,
            resolution_m=resolution_m,
            threshold_m=threshold_m,
            scale_cells=int(scale),
            mode=mode,
        ).items():
            persistence[cell] = persistence.get(cell, 0) + 1
            current = aggregate.get(cell)
            if current is None or float(item["score"]) > float(current["score"]):
                aggregate[cell] = item
    for cell, item in aggregate.items():
        item["scale_persistence"] = persistence.get(cell, 1)
        item["score"] = round(
            float(item["score"]) * (1.0 + 0.12 * (persistence.get(cell, 1) - 1)),
            4,
        )
    return _subcell_nonmaximum_suppression(
        aggregate,
        resolution_m=resolution_m,
    )


def build_tangent_candidate_graph(
    candidates: Mapping[Cell, dict[str, Any]],
    *,
    resolution_m: float,
    minimum_component_cells: int,
    elevations: Mapping[Cell, float] | None = None,
    maximum_bridge_cells: float = 5.25,
) -> dict[Cell, set[Cell]]:
    """Connect candidates by tangent agreement plus bounded crest bridges.

    The bridge pass only joins different candidate components from an existing
    endpoint whose tangent points at a stronger support cell. Every intervening
    DEM sample must remain close to the lower endpoint elevation. This recovers
    T/Y junctions where ridge curvature vanishes at a broad merge without
    allowing unconstrained line-of-sight connections.
    """

    potentials: dict[Cell, list[tuple[float, int, Cell]]] = {
        cell: [] for cell in candidates
    }
    for cell, item in candidates.items():
        point = _point(item, cell)
        tangent = _unit(item.get("tangent"))
        if tangent is None:
            continue
        for dx, dy in NEIGHBOR_OFFSETS:
            neighbor = _cell(
                cell[0] + dx * resolution_m,
                cell[1] + dy * resolution_m,
            )
            if neighbor not in candidates or neighbor <= cell:
                continue
            neighbor_item = candidates[neighbor]
            neighbor_point = _point(neighbor_item, neighbor)
            vector = _unit(
                (
                    neighbor_point[0] - point[0],
                    neighbor_point[1] - point[1],
                )
            )
            neighbor_tangent = _unit(neighbor_item.get("tangent"))
            if vector is None or neighbor_tangent is None:
                continue
            align_a = abs(_dot(vector, tangent))
            align_b = abs(_dot(vector, neighbor_tangent))
            tangent_agreement = abs(_dot(tangent, neighbor_tangent))
            if min(align_a, align_b) < 0.38 or tangent_agreement < 0.28:
                continue
            distance = math.dist(point, neighbor_point)
            cost = (
                1.0 - (align_a + align_b) / 2.0
                + 0.20 * (1.0 - tangent_agreement)
                + 0.03 * distance / resolution_m
            )
            sign_a = 1 if _dot(vector, tangent) >= 0 else -1
            reverse = (-vector[0], -vector[1])
            sign_b = 1 if _dot(reverse, neighbor_tangent) >= 0 else -1
            potentials[cell].append((cost, sign_a, neighbor))
            potentials[neighbor].append((cost, sign_b, cell))

    selected_links: set[tuple[Cell, Cell]] = set()
    for cell, options in potentials.items():
        for sign in (-1, 1):
            direction_options = sorted(
                (item for item in options if item[1] == sign),
                key=lambda item: (item[0], item[2]),
            )
            if not direction_options:
                continue
            _cost, _sign, neighbor = direction_options[0]
            selected_links.add(_link(cell, neighbor))

    graph = {cell: set() for cell in candidates}
    for a, b in selected_links:
        graph[a].add(b)
        graph[b].add(a)
    if elevations:
        _connect_supported_branch_gaps(
            graph,
            candidates,
            elevations,
            resolution_m=resolution_m,
            maximum_bridge_cells=maximum_bridge_cells,
        )
    return retain_large_components(
        graph,
        minimum_component_cells=minimum_component_cells,
    )


def _connect_supported_branch_gaps(
    graph: dict[Cell, set[Cell]],
    candidates: Mapping[Cell, dict[str, Any]],
    elevations: Mapping[Cell, float],
    *,
    resolution_m: float,
    maximum_bridge_cells: float,
) -> None:
    component_by_cell = _component_labels(graph)
    proposals: list[tuple[float, Cell, Cell]] = []
    maximum_distance = resolution_m * maximum_bridge_cells
    search_radius = int(math.ceil(maximum_bridge_cells))
    origin_x = min(cell[0] for cell in elevations)
    origin_y = min(cell[1] for cell in elevations)
    for cell, neighbors in graph.items():
        if len(neighbors) > 1:
            continue
        item = candidates[cell]
        point = _point(item, cell)
        tangent = _unit(item.get("tangent"))
        if tangent is None:
            continue
        nearby_targets = {
            _cell(
                cell[0] + dx * resolution_m,
                cell[1] + dy * resolution_m,
            )
            for dx in range(-search_radius, search_radius + 1)
            for dy in range(-search_radius, search_radius + 1)
            if dx or dy
        }
        for target in nearby_targets:
            target_item = candidates.get(target)
            if target_item is None:
                continue
            if target == cell or component_by_cell.get(target) == component_by_cell.get(cell):
                continue
            target_point = _point(target_item, target)
            distance = math.dist(point, target_point)
            if distance <= resolution_m * 1.45 or distance > maximum_distance:
                continue
            vector = _unit((target_point[0] - point[0], target_point[1] - point[1]))
            if vector is None:
                continue
            alignment = abs(_dot(vector, tangent))
            if alignment < 0.82:
                continue
            if float(target_item.get("score", 0.0)) < float(item.get("score", 0.0)) * 0.8:
                continue
            if not _ridge_bridge_has_dem_support(
                cell,
                target,
                elevations,
                resolution_m=resolution_m,
                origin_x=origin_x,
                origin_y=origin_y,
            ):
                continue
            cost = distance / resolution_m + 3.0 * (1.0 - alignment)
            proposals.append((cost, cell, target))

    used_endpoints: set[Cell] = set()
    parents = {component: component for component in set(component_by_cell.values())}

    def find(component: int) -> int:
        root = component
        while parents[root] != root:
            root = parents[root]
        while parents[component] != component:
            parent = parents[component]
            parents[component] = root
            component = parent
        return root

    for _cost, cell, target in sorted(proposals):
        source_component = find(component_by_cell[cell])
        target_component = find(component_by_cell[target])
        if cell in used_endpoints or source_component == target_component:
            continue
        graph[cell].add(target)
        graph[target].add(cell)
        used_endpoints.add(cell)
        parents[source_component] = target_component


def _component_labels(graph: Mapping[Cell, set[Cell]]) -> dict[Cell, int]:
    result: dict[Cell, int] = {}
    for component_number, seed in enumerate(sorted(graph), start=1):
        if seed in result:
            continue
        stack = [seed]
        while stack:
            cell = stack.pop()
            if cell in result:
                continue
            result[cell] = component_number
            stack.extend(graph.get(cell, set()) - result.keys())
    return result


def _ridge_bridge_has_dem_support(
    start: Cell,
    end: Cell,
    elevations: Mapping[Cell, float],
    *,
    resolution_m: float,
    origin_x: float,
    origin_y: float,
) -> bool:
    distance = math.dist(start, end)
    steps = max(2, int(math.ceil(distance / resolution_m)))
    samples: list[float] = []
    for index in range(steps + 1):
        ratio = index / steps
        x = start[0] + (end[0] - start[0]) * ratio
        y = start[1] + (end[1] - start[1]) * ratio
        cell = _cell(
            origin_x + round((x - origin_x) / resolution_m) * resolution_m,
            origin_y + round((y - origin_y) / resolution_m) * resolution_m,
        )
        elevation = elevations.get(cell)
        if elevation is None:
            return False
        samples.append(float(elevation))
    endpoint_floor = min(samples[0], samples[-1])
    maximum_sag_m = max(4.0, resolution_m * 0.5)
    return min(samples) >= endpoint_floor - maximum_sag_m


def constrained_smooth_path(
    points: Sequence[tuple[float, float]],
    *,
    resolution_m: float,
    iterations: int = 2,
    maximum_shift_cells: float = 0.35,
) -> list[tuple[float, float]]:
    """Smooth a trace without changing endpoints, point count, or support cells."""

    raw = [(float(x), float(y)) for x, y in points]
    if len(raw) < 3:
        return raw
    maximum_shift = resolution_m * maximum_shift_cells
    current = list(raw)
    for _ in range(max(0, iterations)):
        updated = [current[0]]
        for index in range(1, len(current) - 1):
            target = (
                0.25 * current[index - 1][0]
                + 0.5 * current[index][0]
                + 0.25 * current[index + 1][0],
                0.25 * current[index - 1][1]
                + 0.5 * current[index][1]
                + 0.25 * current[index + 1][1],
            )
            origin = raw[index]
            shift = (target[0] - origin[0], target[1] - origin[1])
            distance = math.hypot(*shift)
            if distance > maximum_shift and distance > 0:
                factor = maximum_shift / distance
                target = (
                    origin[0] + shift[0] * factor,
                    origin[1] + shift[1] * factor,
                )
            updated.append(target)
        updated.append(current[-1])
        current = updated
    return current


def regular_grid_arrays(
    grid: Mapping[Cell, float],
    resolution_m: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[tuple[int, int], Cell]]:
    xs = np.array(sorted({float(cell[0]) for cell in grid}), dtype=float)
    ys = np.array(sorted({float(cell[1]) for cell in grid}), dtype=float)
    if len(xs) < 3 or len(ys) < 3:
        raise ValueError("terrain grid requires at least three rows and columns")
    x_index = {round(float(value), 6): index for index, value in enumerate(xs)}
    y_index = {round(float(value), 6): index for index, value in enumerate(ys)}
    array = np.full((len(ys), len(xs)), np.nan, dtype=float)
    cell_by_index: dict[tuple[int, int], Cell] = {}
    for cell, elevation in grid.items():
        col = x_index.get(round(float(cell[0]), 6))
        row = y_index.get(round(float(cell[1]), 6))
        if row is None or col is None:
            continue
        array[row, col] = float(elevation)
        cell_by_index[(row, col)] = _cell(cell[0], cell[1])
    if len(xs) > 1 and not np.allclose(np.diff(xs), resolution_m, atol=1e-4):
        raise ValueError("terrain grid x spacing does not match resolution")
    if len(ys) > 1 and not np.allclose(np.diff(ys), resolution_m, atol=1e-4):
        raise ValueError("terrain grid y spacing does not match resolution")
    return array, xs, ys, cell_by_index


def gaussian_smooth_nan(array: np.ndarray, *, sigma_cells: float) -> np.ndarray:
    radius = max(1, int(math.ceil(2.0 * sigma_cells)))
    offsets = range(-radius, radius + 1)
    one_dimensional = {
        offset: math.exp(-0.5 * (offset / sigma_cells) ** 2)
        for offset in offsets
    }
    weighted = np.zeros_like(array, dtype=float)
    weights = np.zeros_like(array, dtype=float)
    for dy in offsets:
        for dx in offsets:
            shifted = _shift_nan(array, dy, dx)
            finite = np.isfinite(shifted)
            weight = one_dimensional[dy] * one_dimensional[dx]
            weighted[finite] += shifted[finite] * weight
            weights[finite] += weight
    result = np.full_like(array, np.nan, dtype=float)
    valid = weights > 0
    result[valid] = weighted[valid] / weights[valid]
    result[~np.isfinite(array)] = np.nan
    return result


def retain_large_components(
    graph: Mapping[Cell, set[Cell]],
    *,
    minimum_component_cells: int,
) -> dict[Cell, set[Cell]]:
    retained: set[Cell] = set()
    remaining = set(graph)
    while remaining:
        seed = min(remaining)
        component: set[Cell] = set()
        stack = [seed]
        while stack:
            cell = stack.pop()
            if cell in component:
                continue
            component.add(cell)
            stack.extend(graph.get(cell, set()) - component)
        remaining -= component
        if len(component) >= minimum_component_cells:
            retained.update(component)
    return {
        cell: {neighbor for neighbor in graph.get(cell, set()) if neighbor in retained}
        for cell in retained
    }


def _scale_candidates(
    smoothed: np.ndarray,
    raw: np.ndarray,
    xs: np.ndarray,
    ys: np.ndarray,
    cell_by_index: Mapping[tuple[int, int], Cell],
    *,
    resolution_m: float,
    threshold_m: float,
    scale_cells: int,
    mode: str,
) -> dict[Cell, dict[str, Any]]:
    result: dict[Cell, dict[str, Any]] = {}
    rows, cols = smoothed.shape
    margin = max(2, int(math.ceil(2.0 * max(0.65, float(scale_cells)))))
    for row in range(margin, rows - margin):
        for col in range(margin, cols - margin):
            cell = cell_by_index.get((row, col))
            window = smoothed[row - 1 : row + 2, col - 1 : col + 2]
            if cell is None or not np.isfinite(window).all():
                continue
            center = float(smoothed[row, col])
            dzdx = float(smoothed[row, col + 1] - smoothed[row, col - 1]) / (
                2.0 * resolution_m
            )
            dzdy = float(smoothed[row + 1, col] - smoothed[row - 1, col]) / (
                2.0 * resolution_m
            )
            dxx = float(
                smoothed[row, col + 1] - 2.0 * center + smoothed[row, col - 1]
            ) / (resolution_m * resolution_m)
            dyy = float(
                smoothed[row + 1, col] - 2.0 * center + smoothed[row - 1, col]
            ) / (resolution_m * resolution_m)
            dxy = float(
                smoothed[row + 1, col + 1]
                - smoothed[row + 1, col - 1]
                - smoothed[row - 1, col + 1]
                + smoothed[row - 1, col - 1]
            ) / (4.0 * resolution_m * resolution_m)
            half_trace = (dxx + dyy) / 2.0
            radius = math.hypot((dxx - dyy) / 2.0, dxy)
            lambda_min = half_trace - radius
            lambda_max = half_trace + radius
            theta_max = 0.5 * math.atan2(2.0 * dxy, dxx - dyy)
            if mode == "ridge":
                normal_angle = theta_max + math.pi / 2.0
                normal_curvature = lambda_min
                response = -lambda_min * resolution_m * resolution_m
                if normal_curvature >= -1e-9:
                    continue
            else:
                normal_angle = theta_max
                normal_curvature = lambda_max
                response = lambda_max * resolution_m * resolution_m
                if normal_curvature <= 1e-9:
                    continue
            if response < threshold_m:
                continue
            normal = (math.cos(normal_angle), math.sin(normal_angle))
            tangent = (-normal[1], normal[0])
            first_derivative = dzdx * normal[0] + dzdy * normal[1]
            offset_m = -first_derivative / normal_curvature
            if not math.isfinite(offset_m) or abs(offset_m) > resolution_m * 0.72:
                continue
            point = (
                float(xs[col]) + offset_m * normal[0],
                float(ys[row]) + offset_m * normal[1],
            )
            raw_elevation = float(raw[row, col])
            result[cell] = {
                "point": point,
                "elevation_m": raw_elevation,
                "normal": normal,
                "tangent": tangent,
                "normal_offset_m": offset_m,
                "normal_curvature": normal_curvature,
                "score": response,
                "scale_cells": scale_cells,
                "support_radius_m": resolution_m * max(1, scale_cells),
                "morphometry_mode": mode,
            }
    return result


def _subcell_nonmaximum_suppression(
    candidates: Mapping[Cell, dict[str, Any]],
    *,
    resolution_m: float,
) -> dict[Cell, dict[str, Any]]:
    selected: dict[Cell, dict[str, Any]] = {}
    buckets: dict[tuple[int, int], list[Cell]] = {}
    minimum_distance = resolution_m * 0.55
    for cell, item in sorted(
        candidates.items(),
        key=lambda pair: (-float(pair[1]["score"]), pair[0]),
    ):
        point = _point(item, cell)
        bucket = (
            math.floor(point[0] / resolution_m),
            math.floor(point[1] / resolution_m),
        )
        neighbors = [
            other
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
            for other in buckets.get((bucket[0] + dx, bucket[1] + dy), [])
        ]
        if any(
            math.dist(point, _point(selected[other], other)) < minimum_distance
            for other in neighbors
        ):
            continue
        selected[cell] = dict(item)
        buckets.setdefault(bucket, []).append(cell)
    return selected


def _shift_nan(array: np.ndarray, dy: int, dx: int) -> np.ndarray:
    result = np.full_like(array, np.nan, dtype=float)
    source_y_start = max(0, -dy)
    source_y_end = array.shape[0] - max(0, dy)
    source_x_start = max(0, -dx)
    source_x_end = array.shape[1] - max(0, dx)
    target_y_start = max(0, dy)
    target_y_end = target_y_start + max(0, source_y_end - source_y_start)
    target_x_start = max(0, dx)
    target_x_end = target_x_start + max(0, source_x_end - source_x_start)
    if source_y_end > source_y_start and source_x_end > source_x_start:
        result[target_y_start:target_y_end, target_x_start:target_x_end] = array[
            source_y_start:source_y_end,
            source_x_start:source_x_end,
        ]
    return result


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


def _dot(a: tuple[float, float], b: tuple[float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1]


def _cell(x: float, y: float) -> Cell:
    return round(float(x), 6), round(float(y), 6)


def _link(a: Cell, b: Cell) -> tuple[Cell, Cell]:
    return (a, b) if a <= b else (b, a)
