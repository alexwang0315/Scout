"""Backend boundaries for terrain route hypothesis generation."""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass
from typing import Any, Protocol

from terrain_route_hypothesis_models import (
    TerrainDemRaster,
    TerrainRouteFailureCode,
    TerrainRoutingCostConfig,
)


GridCell = tuple[int, int]
CostGrid = tuple[tuple[float, ...], ...]


@dataclass(frozen=True)
class TerrainBackendRequest:
    dem: TerrainDemRaster
    start_cell: GridCell
    destination_cell: GridCell
    slope_degrees: CostGrid
    friction: CostGrid
    cost_config: TerrainRoutingCostConfig
    cache_key: str


@dataclass(frozen=True)
class TerrainBackendResult:
    path_cells: tuple[GridCell, ...]
    accumulated_cost: float
    cost_from_start: CostGrid | None
    cost_from_destination: CostGrid | None
    backend_id: str
    grass_version: str
    modules_executed: tuple[str, ...]
    processing_manifest: dict[str, Any]


class TerrainBackendFailure(RuntimeError):
    def __init__(
        self,
        code: TerrainRouteFailureCode,
        message: str,
        *,
        detail: str | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.detail = detail
        self.retryable = retryable


class TerrainBackend(Protocol):
    backend_id: str

    def generate_best_path(self, request: TerrainBackendRequest) -> TerrainBackendResult:
        ...


class GrassCommandRunner(Protocol):
    def generate_best_path(self, request: TerrainBackendRequest) -> TerrainBackendResult:
        ...


class GrassTerrainBackend:
    """GRASS adapter boundary for r.walk/r.path based route hypotheses."""

    backend_id = "grass_terrain_backend.v0_1"

    def __init__(self, runner: GrassCommandRunner | None = None) -> None:
        self.runner = runner

    def generate_best_path(self, request: TerrainBackendRequest) -> TerrainBackendResult:
        if self.runner is None:
            raise TerrainBackendFailure(
                TerrainRouteFailureCode.GRASS_UNAVAILABLE,
                "GRASS terrain backend is not configured.",
                retryable=True,
            )
        return self.runner.generate_best_path(request)


class FakeTerrainBackend:
    """Deterministic test backend that approximates r.walk/r.path on a grid."""

    backend_id = "fake_rwalk_rpath_backend.v0_1"

    def __init__(
        self,
        *,
        blocked_cells: set[GridCell] | None = None,
        failure_code: TerrainRouteFailureCode | None = None,
    ) -> None:
        self.blocked_cells = set(blocked_cells or set())
        self.failure_code = failure_code

    def generate_best_path(self, request: TerrainBackendRequest) -> TerrainBackendResult:
        if self.failure_code is not None:
            raise TerrainBackendFailure(
                self.failure_code,
                f"Fake terrain backend forced {self.failure_code.value}.",
            )
        cost_from_start, previous = _dijkstra(
            request.friction,
            request.start_cell,
            request.dem.resolution_m,
            blocked_cells=self.blocked_cells,
        )
        cost_from_destination, _ = _dijkstra(
            request.friction,
            request.destination_cell,
            request.dem.resolution_m,
            blocked_cells=self.blocked_cells,
        )
        path = _reconstruct_path(
            previous,
            request.start_cell,
            request.destination_cell,
        )
        accumulated = grid_value(cost_from_start, request.destination_cell)
        return TerrainBackendResult(
            path_cells=tuple(path),
            accumulated_cost=float(accumulated),
            cost_from_start=cost_from_start,
            cost_from_destination=cost_from_destination,
            backend_id=self.backend_id,
            grass_version="fake-grass-not-executed",
            modules_executed=("grass:r.walk", "grass:r.path"),
            processing_manifest={
                "backend": self.backend_id,
                "movement_model": "deterministic_8_neighbor_least_cost.v0_1",
                "blocked_cell_count": len(self.blocked_cells),
            },
        )


def finite_grid_cell(grid: CostGrid, cell: GridCell) -> bool:
    row, col = cell
    return math.isfinite(float(grid[row][col]))


def grid_value(grid: CostGrid, cell: GridCell) -> float:
    row, col = cell
    return float(grid[row][col])


def _dijkstra(
    friction: CostGrid,
    start: GridCell,
    resolution_m: float,
    *,
    blocked_cells: set[GridCell],
) -> tuple[CostGrid, dict[GridCell, GridCell]]:
    rows = len(friction)
    cols = len(friction[0]) if rows else 0
    distances = [[math.inf for _ in range(cols)] for _ in range(rows)]
    previous: dict[GridCell, GridCell] = {}
    if start in blocked_cells or not finite_grid_cell(friction, start):
        return tuple(tuple(row) for row in distances), previous

    start_row, start_col = start
    distances[start_row][start_col] = 0.0
    queue: list[tuple[float, int, int]] = [(0.0, start_row, start_col)]
    offsets = (
        (-1, 0),
        (0, -1),
        (0, 1),
        (1, 0),
        (-1, -1),
        (-1, 1),
        (1, -1),
        (1, 1),
    )
    while queue:
        cost, row, col = heapq.heappop(queue)
        if cost > distances[row][col]:
            continue
        for dr, dc in offsets:
            next_row = row + dr
            next_col = col + dc
            next_cell = (next_row, next_col)
            if not (0 <= next_row < rows and 0 <= next_col < cols):
                continue
            if next_cell in blocked_cells or not finite_grid_cell(
                friction,
                next_cell,
            ):
                continue
            distance = resolution_m * math.hypot(dr, dc)
            step_cost = distance * (
                float(friction[row][col]) + float(friction[next_row][next_col])
            ) / 2.0
            candidate = cost + step_cost
            if candidate < distances[next_row][next_col]:
                distances[next_row][next_col] = candidate
                previous[next_cell] = (row, col)
                heapq.heappush(queue, (candidate, next_row, next_col))
    return tuple(tuple(row) for row in distances), previous


def _reconstruct_path(
    previous: dict[GridCell, GridCell],
    start: GridCell,
    destination: GridCell,
) -> list[GridCell]:
    if start == destination:
        return [start]
    if destination not in previous:
        return []
    path = [destination]
    current = destination
    while current != start:
        current = previous[current]
        path.append(current)
    path.reverse()
    return path
