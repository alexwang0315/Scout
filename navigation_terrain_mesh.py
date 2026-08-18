"""Bounded DEM mesh projection for terrain-reading review surfaces."""

from __future__ import annotations

import math
from typing import Any, Sequence

from navigation_terrain_dem import WorkspaceTerrainGrid

DEFAULT_MAX_COLUMNS = 36
DEFAULT_MAX_ROWS = 24
MAX_MESH_VERTICES = 3_072


def build_bounded_terrain_mesh(
    workspace_grid: WorkspaceTerrainGrid,
    *,
    source_refs: Sequence[str],
    max_columns: int = DEFAULT_MAX_COLUMNS,
    max_rows: int = DEFAULT_MAX_ROWS,
) -> dict[str, Any]:
    """Project a decimated visualization mesh without filling DEM gaps.

    The result is deliberately normalized to the prepared DEM extent. It is a
    visual review aid, not a resampled elevation product and not route truth.
    """

    if max_columns < 3 or max_rows < 3:
        raise ValueError("terrain mesh requires at least three rows and columns")
    if max_columns * max_rows > MAX_MESH_VERTICES:
        raise ValueError("terrain mesh vertex budget exceeded")

    elevations = {
        (round(float(x), 6), round(float(y), 6)): float(elevation)
        for (x, y), elevation in workspace_grid.elevations.items()
        if all(math.isfinite(value) for value in (x, y, elevation))
    }
    if not elevations:
        return _empty_mesh("Workspace DEM has no supported cells.", source_refs)

    source_xs = sorted({cell[0] for cell in elevations})
    source_ys = sorted({cell[1] for cell in elevations})
    sampled_xs, stride_x = _sample_axis(source_xs, max_columns)
    sampled_ys, stride_y = _sample_axis(source_ys, max_rows)
    min_x, max_x = source_xs[0], source_xs[-1]
    min_y, max_y = source_ys[0], source_ys[-1]
    width = max(1.0, max_x - min_x)
    height = max(1.0, max_y - min_y)

    vertices: list[dict[str, Any]] = []
    vertex_id_by_position: dict[tuple[int, int], int] = {}
    supported_elevations = list(elevations.values())
    unsupported_count = 0
    for row, y in enumerate(sampled_ys):
        for column, x in enumerate(sampled_xs):
            elevation = elevations.get((x, y))
            supported = elevation is not None
            if not supported:
                unsupported_count += 1
            vertex_id = len(vertices)
            vertex_id_by_position[(column, row)] = vertex_id
            vertices.append(
                {
                    "id": vertex_id,
                    "column": column,
                    "row": row,
                    "u": round((x - min_x) / width, 6),
                    "v": round((y - min_y) / height, 6),
                    "elevation_m": round(float(elevation), 2) if supported else None,
                    "supported": supported,
                }
            )

    triangles: list[list[int]] = []
    rejected_unsupported_footprint_count = 0
    resolution_m = float(workspace_grid.resolution_m)
    for row in range(len(sampled_ys) - 1):
        for column in range(len(sampled_xs) - 1):
            northwest = vertex_id_by_position[(column, row + 1)]
            northeast = vertex_id_by_position[(column + 1, row + 1)]
            southwest = vertex_id_by_position[(column, row)]
            southeast = vertex_id_by_position[(column + 1, row)]
            quad = (northwest, northeast, southwest, southeast)
            if not all(vertices[vertex_id]["supported"] for vertex_id in quad):
                rejected_unsupported_footprint_count += 1
                continue
            if not _source_footprint_is_supported(
                elevations,
                min_x=sampled_xs[column],
                max_x=sampled_xs[column + 1],
                min_y=sampled_ys[row],
                max_y=sampled_ys[row + 1],
                resolution_m=resolution_m,
            ):
                rejected_unsupported_footprint_count += 1
                continue
            triangles.extend(
                ([northwest, southwest, southeast], [northwest, southeast, northeast])
            )

    horizontal_method = "deterministic_axis_stride_decimation"
    gap_policy = "omit_faces_with_unsupported_source_footprints"
    source_quad_count = 0
    sampled_source_quad_count = 0
    source_quads = _supported_source_quads(
        elevations,
        resolution_m=resolution_m,
    )
    source_quad_count = len(source_quads)
    if (
        source_quad_count > 200
        and len(triangles) < min(200, math.floor(source_quad_count * 0.25))
    ):
        vertices, triangles, sampled_source_quad_count = _sample_supported_source_quads(
            source_quads,
            elevations,
            min_x=min_x,
            max_x=max_x,
            min_y=min_y,
            max_y=max_y,
            resolution_m=resolution_m,
        )
        horizontal_method = "deterministic_supported_source_quad_sampling"
        gap_policy = "only_source_adjacent_supported_quads"
        unsupported_count = 0
        sampled_xs = []
        sampled_ys = []

    return {
        "schema_version": "scout_navigation_terrain_mesh.v0",
        "artifact_kind": "bounded_dem_visualization_mesh",
        "status": "visualization_mesh" if triangles else "not_prepared",
        "source_cell_resolution_m": float(workspace_grid.resolution_m),
        "source_cell_count": len(elevations),
        "sampled_column_count": len(sampled_xs),
        "sampled_row_count": len(sampled_ys),
        "vertex_count": len(vertices),
        "triangle_count": len(triangles),
        "minimum_elevation_m": round(min(supported_elevations), 2),
        "maximum_elevation_m": round(max(supported_elevations), 2),
        "vertices": vertices,
        "triangles": triangles,
        "sampling": {
            "horizontal_method": horizontal_method,
            "stride_columns": stride_x,
            "stride_rows": stride_y,
            "unsupported_vertex_count": unsupported_count,
            "gap_policy": gap_policy,
            "source_supported_quad_count": source_quad_count,
            "sampled_source_quad_count": sampled_source_quad_count,
            "rejected_unsupported_footprint_count": (
                rejected_unsupported_footprint_count
            ),
            "face_footprint_supported": True,
            "measurement_source": "prepared_dem",
            "adds_source_resolution": False,
            "default_vertical_exaggeration": 1.0,
        },
        "source_refs": _bounded_refs(source_refs),
        "limitations": [
            "The mesh is a decimated visualization of supported DEM cells.",
            "Missing DEM support remains a hole and is never bridged.",
            "Perspective and vertical exaggeration can change visual salience.",
            "The mesh does not establish a trail, passability, legality, or safety.",
        ],
        "boundary": _candidate_boundary(),
    }


def empty_bounded_terrain_mesh(reason: str) -> dict[str, Any]:
    """Public fail-closed projection used when a workspace grid is unavailable."""

    return _empty_mesh(reason, ())


def _sample_axis(values: list[float], limit: int) -> tuple[list[float], int]:
    if len(values) <= limit:
        return list(values), 1
    stride = max(1, math.ceil(len(values) / limit))
    sampled = list(values[::stride])
    if sampled[-1] != values[-1]:
        sampled.append(values[-1])
    while len(sampled) > limit:
        sampled.pop(-2)
    return sampled, stride


def _supported_source_quads(
    elevations: dict[tuple[float, float], float],
    *,
    resolution_m: float,
) -> list[tuple[float, float]]:
    cells = set(elevations)
    return sorted(
        (x, y)
        for x, y in cells
        if (x + resolution_m, y) in cells
        and (x, y + resolution_m) in cells
        and (x + resolution_m, y + resolution_m) in cells
    )


def _source_footprint_is_supported(
    elevations: dict[tuple[float, float], float],
    *,
    min_x: float,
    max_x: float,
    min_y: float,
    max_y: float,
    resolution_m: float,
) -> bool:
    """Require every source-grid vertex beneath a decimated face footprint."""

    column_count = round((max_x - min_x) / resolution_m)
    row_count = round((max_y - min_y) / resolution_m)
    if column_count < 1 or row_count < 1:
        return False
    for row in range(row_count + 1):
        y = round(min_y + row * resolution_m, 6)
        for column in range(column_count + 1):
            x = round(min_x + column * resolution_m, 6)
            if (x, y) not in elevations:
                return False
    return True


def _sample_supported_source_quads(
    source_quads: list[tuple[float, float]],
    elevations: dict[tuple[float, float], float],
    *,
    min_x: float,
    max_x: float,
    min_y: float,
    max_y: float,
    resolution_m: float,
) -> tuple[list[dict[str, Any]], list[list[int]], int]:
    maximum_quads = min(700, MAX_MESH_VERTICES // 4)
    sampled_quads = _evenly_sample(source_quads, maximum_quads)
    width = max(1.0, max_x - min_x)
    height = max(1.0, max_y - min_y)
    vertices: list[dict[str, Any]] = []
    vertex_id_by_cell: dict[tuple[float, float], int] = {}
    triangles: list[list[int]] = []

    def vertex_id(cell: tuple[float, float]) -> int:
        existing = vertex_id_by_cell.get(cell)
        if existing is not None:
            return existing
        identifier = len(vertices)
        vertex_id_by_cell[cell] = identifier
        vertices.append(
            {
                "id": identifier,
                "column": None,
                "row": None,
                "u": round((cell[0] - min_x) / width, 6),
                "v": round((cell[1] - min_y) / height, 6),
                "elevation_m": round(float(elevations[cell]), 2),
                "supported": True,
            }
        )
        return identifier

    for x, y in sampled_quads:
        southwest = vertex_id((x, y))
        southeast = vertex_id((x + resolution_m, y))
        northwest = vertex_id((x, y + resolution_m))
        northeast = vertex_id((x + resolution_m, y + resolution_m))
        triangles.extend(
            ([northwest, southwest, southeast], [northwest, southeast, northeast])
        )
    return vertices, triangles, len(sampled_quads)


def _evenly_sample(items: list[Any], limit: int) -> list[Any]:
    if len(items) <= limit:
        return list(items)
    indices = {
        round(index * (len(items) - 1) / (limit - 1))
        for index in range(limit)
    }
    return [items[index] for index in sorted(indices)]


def _empty_mesh(reason: str, source_refs: Sequence[str]) -> dict[str, Any]:
    return {
        "schema_version": "scout_navigation_terrain_mesh.v0",
        "artifact_kind": "bounded_dem_visualization_mesh",
        "status": "not_prepared",
        "source_cell_resolution_m": None,
        "source_cell_count": 0,
        "sampled_column_count": 0,
        "sampled_row_count": 0,
        "vertex_count": 0,
        "triangle_count": 0,
        "minimum_elevation_m": None,
        "maximum_elevation_m": None,
        "vertices": [],
        "triangles": [],
        "sampling": {
            "horizontal_method": "not_prepared",
            "unsupported_vertex_count": 0,
            "gap_policy": "no_surface_invented",
            "rejected_unsupported_footprint_count": 0,
            "face_footprint_supported": True,
            "measurement_source": "prepared_dem",
            "adds_source_resolution": False,
            "default_vertical_exaggeration": 1.0,
        },
        "source_refs": _bounded_refs(source_refs),
        "limitations": [reason],
        "boundary": _candidate_boundary(),
    }


def _bounded_refs(values: Sequence[str]) -> list[str]:
    return list(
        dict.fromkeys(
            value.strip()
            for value in values[:32]
            if isinstance(value, str) and value.strip()
        )
    )


def _candidate_boundary() -> dict[str, Any]:
    return {
        "candidate_only": True,
        "runtime_safety_truth": False,
        "safe_or_walkable": "not_determined",
        "raw_dem_embedded": False,
        "visualization_only": True,
        "human_review_required": True,
    }
