from __future__ import annotations

from navigation_terrain_dem import WorkspaceTerrainGrid
from navigation_terrain_mesh import build_bounded_terrain_mesh


def _workspace_grid(*, missing: set[tuple[int, int]] | None = None) -> WorkspaceTerrainGrid:
    missing = missing or set()
    elevations = {
        (250_000 + column * 20, 2_600_000 + row * 20): (
            1_200 + row * 18 + column * 7
        )
        for row in range(6)
        for column in range(8)
        if (column, row) not in missing
    }
    return WorkspaceTerrainGrid(
        terrain={},
        coverage={},
        elevations=elevations,
        bbox_twd97={
            "min_x": 250_000,
            "min_y": 2_600_000,
            "max_x": 250_140,
            "max_y": 2_600_100,
        },
        resolution_m=20,
        selected_tiles=(),
        tile_ids=("fixture",),
        corridor_filter_method="not_applied",
    )


def test_bounded_mesh_is_deterministic_decimated_and_candidate_only() -> None:
    result = build_bounded_terrain_mesh(
        _workspace_grid(),
        source_refs=["terrain.json", "coverage.json"],
        max_columns=5,
        max_rows=4,
    )

    assert result["status"] == "visualization_mesh"
    assert result["source_cell_resolution_m"] == 20
    assert result["sampled_column_count"] <= 5
    assert result["sampled_row_count"] <= 4
    assert result["vertex_count"] == len(result["vertices"])
    assert result["triangle_count"] == len(result["triangles"])
    assert result["triangle_count"] > 0
    assert result["sampling"]["adds_source_resolution"] is False
    assert result["sampling"]["horizontal_method"] == (
        "deterministic_axis_stride_decimation"
    )
    assert result["boundary"] == {
        "candidate_only": True,
        "runtime_safety_truth": False,
        "safe_or_walkable": "not_determined",
        "raw_dem_embedded": False,
        "visualization_only": True,
        "human_review_required": True,
    }
    assert all(0 <= vertex["u"] <= 1 for vertex in result["vertices"])
    assert all(0 <= vertex["v"] <= 1 for vertex in result["vertices"])


def test_mesh_does_not_bridge_across_missing_dem_support() -> None:
    result = build_bounded_terrain_mesh(
        _workspace_grid(missing={(3, 2)}),
        source_refs=["terrain.json"],
        max_columns=8,
        max_rows=6,
    )

    missing_vertex = next(
        vertex["id"]
        for vertex in result["vertices"]
        if vertex["column"] == 3 and vertex["row"] == 2
    )
    assert result["vertices"][missing_vertex]["supported"] is False
    assert all(missing_vertex not in triangle for triangle in result["triangles"])
    assert result["sampling"]["unsupported_vertex_count"] == 1


def test_decimated_face_footprint_cannot_span_an_unsampled_dem_hole() -> None:
    complete = build_bounded_terrain_mesh(
        _workspace_grid(),
        source_refs=["terrain.json"],
        max_columns=4,
        max_rows=3,
    )
    with_interior_hole = build_bounded_terrain_mesh(
        _workspace_grid(missing={(1, 1)}),
        source_refs=["terrain.json"],
        max_columns=4,
        max_rows=3,
    )

    assert complete["sampling"]["horizontal_method"] == (
        "deterministic_axis_stride_decimation"
    )
    assert with_interior_hole["sampling"]["horizontal_method"] == (
        "deterministic_axis_stride_decimation"
    )
    assert with_interior_hole["triangle_count"] == complete["triangle_count"] - 2
    assert with_interior_hole["sampling"]["face_footprint_supported"] is True
    assert with_interior_hole["sampling"]["rejected_unsupported_footprint_count"] >= 1
    assert with_interior_hole["sampling"]["measurement_source"] == "prepared_dem"


def test_empty_mesh_fails_closed_without_inventing_surface() -> None:
    grid = _workspace_grid()
    empty_grid = WorkspaceTerrainGrid(
        terrain=grid.terrain,
        coverage=grid.coverage,
        elevations={},
        bbox_twd97=grid.bbox_twd97,
        resolution_m=grid.resolution_m,
        selected_tiles=grid.selected_tiles,
        tile_ids=grid.tile_ids,
        corridor_filter_method=grid.corridor_filter_method,
    )

    result = build_bounded_terrain_mesh(empty_grid, source_refs=[])

    assert result["status"] == "not_prepared"
    assert result["vertices"] == []
    assert result["triangles"] == []
    assert result["boundary"]["raw_dem_embedded"] is False


def test_sparse_route_corridor_uses_supported_source_quads_not_global_chords() -> None:
    elevations = {}
    for column in range(120):
        center_row = round(column * 0.4)
        for row in range(max(0, center_row - 3), min(60, center_row + 4)):
            elevations[(250_000 + column * 20, 2_600_000 + row * 20)] = (
                900 + column * 2 + row * 5
            )
    grid = WorkspaceTerrainGrid(
        terrain={},
        coverage={},
        elevations=elevations,
        bbox_twd97={
            "min_x": 250_000,
            "min_y": 2_600_000,
            "max_x": 252_380,
            "max_y": 2_601_180,
        },
        resolution_m=20,
        selected_tiles=(),
        tile_ids=("sparse-corridor",),
        corridor_filter_method="prepared_slope_bitmap_alpha",
    )

    result = build_bounded_terrain_mesh(
        grid,
        source_refs=["terrain.json"],
        max_columns=12,
        max_rows=8,
    )

    assert result["sampling"]["horizontal_method"] == (
        "deterministic_supported_source_quad_sampling"
    )
    assert result["triangle_count"] > 100
    assert result["vertex_count"] <= 3_072
    assert all(vertex["supported"] is True for vertex in result["vertices"])
    assert result["sampling"]["gap_policy"] == (
        "only_source_adjacent_supported_quads"
    )
    assert result["sampling"]["face_footprint_supported"] is True
