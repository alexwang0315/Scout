from __future__ import annotations

import math

from navigation_terrain_skeleton import build_terrain_hierarchy_from_grid


def _branched_terrain() -> dict[tuple[int, int], float]:
    """Synthetic north-south crest with one west spur and two drainages."""

    elevations: dict[tuple[int, int], float] = {}
    for row in range(15):
        for col in range(15):
            ridge = 80.0 - abs(col - 7) * 12.0
            spur = 42.0 - abs(row - 8) * 12.0 if col <= 7 and 4 <= row <= 12 else -100.0
            basin = (
                -28.0 + abs(col - 3) * 9.0 if col < 7 else -25.0 + abs(col - 11) * 9.0
            )
            elevations[(col * 20, row * 20)] = (
                1000.0 + row * 2.0 + max(ridge, spur, basin)
            )
    return elevations


def test_skeleton_builds_continuous_main_and_spur_ridge_hierarchy() -> None:
    result = build_terrain_hierarchy_from_grid(
        _branched_terrain(),
        resolution_m=20,
        source_refs=["synthetic-branched-dem"],
        relief_threshold_m=6,
        minimum_component_cells=3,
    )

    assert result["status"] == "candidate_hierarchy"
    assert result["schema_version"] == "scout_navigation_terrain_hierarchy.v1"
    edge_kinds = {edge["kind"] for edge in result["edges"]}
    assert "main_ridge_candidate" in edge_kinds
    assert "spur_ridge_candidate" in edge_kinds
    assert all(len(edge["coordinates_twd97"]) >= 2 for edge in result["edges"])
    assert any(node["kind"] == "ridge_divide_node" for node in result["nodes"])
    assert all(edge["candidate_only"] is True for edge in result["edges"])
    assert result["boundary"]["safe_or_walkable"] == "not_determined"
    assert result["method"]["ridge_extraction"] == (
        "multi_scale_hessian_subcell_ridge_trace.v1"
    )
    assert result["lineage"]["flow_model"] == (
        "multiple_flow_direction_slope_weighted.v1"
    )
    assert result["lineage"]["dem_resolution_m"] == 20


def test_skeleton_does_not_call_contour_traverse_bands_ridges() -> None:
    result = build_terrain_hierarchy_from_grid(
        _branched_terrain(),
        resolution_m=20,
        source_refs=["synthetic-branched-dem"],
        relief_threshold_m=6,
        minimum_component_cells=3,
    )

    assert "contour_traverse_band" not in {edge["kind"] for edge in result["edges"]}
    assert result["ontology"]["contour_traverse_band_is_ridge"] is False


def _curved_terrain(*, valley: bool) -> dict[tuple[int, int], float]:
    resolution = 20
    elevations: dict[tuple[int, int], float] = {}
    for row in range(61):
        y = row * resolution
        center_x = 600 + 180 * math.sin((y - 600) / 260)
        for col in range(61):
            x = col * resolution
            cross = x - center_x
            form = 0.010 * cross * cross
            base = 2200 - row * 3.0
            elevations[(x, y)] = base + form if valley else base - form
    return elevations


def _grid_axis_distance(angle_degrees: float) -> float:
    normalized = angle_degrees % 180
    return min(
        abs(normalized - axis)
        for axis in (0, 45, 90, 135, 180)
    )


def test_curved_ridge_trace_is_not_locked_to_four_grid_axes() -> None:
    result = build_terrain_hierarchy_from_grid(
        _curved_terrain(valley=False),
        resolution_m=20,
        source_refs=["synthetic-curved-ridge"],
        relief_threshold_m=3,
        minimum_component_cells=4,
    )

    ridge_edges = [
        edge
        for edge in result["edges"]
        if edge["kind"] in {"main_ridge_candidate", "spur_ridge_candidate"}
    ]
    assert ridge_edges
    segment_angles = []
    for edge in ridge_edges:
        points = edge["coordinates_twd97"]
        segment_angles.extend(
            math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
            for a, b in zip(points, points[1:])
            if math.hypot(b[0] - a[0], b[1] - a[1]) > 0.01
        )
    assert segment_angles
    quantized_fraction = sum(
        _grid_axis_distance(angle) <= 2 for angle in segment_angles
    ) / len(segment_angles)

    assert quantized_fraction < 0.85
    assert result["method"]["ridge_extraction"] == (
        "multi_scale_hessian_subcell_ridge_trace.v1"
    )
    assert result["method"]["geometry"] == (
        "subcell_support_constrained_topology_trace.v1"
    )


def test_drainage_edges_follow_mfd_supported_downstream_monotonicity() -> None:
    result = build_terrain_hierarchy_from_grid(
        _curved_terrain(valley=True),
        resolution_m=20,
        source_refs=["synthetic-curved-valley"],
        relief_threshold_m=3,
        minimum_component_cells=4,
    )

    drainage_edges = [
        edge
        for edge in result["edges"]
        if edge["kind"] in {"drainage_trunk", "tributary"}
    ]
    assert drainage_edges
    assert result["method"]["drainage_extraction"] == (
        "conditioned_mfd_accumulation_valley_trace.v1"
    )
    for edge in drainage_edges:
        assert edge["flow_supported"] is True
        assert edge["flow_accumulation_end"] >= edge["flow_accumulation_start"]
        conditioned = edge["conditioned_elevation_profile_m"]
        assert all(
            downstream <= upstream + 0.1
            for upstream, downstream in zip(conditioned, conditioned[1:])
        )
        assert edge["directed_downstream"] is True
        assert edge["strahler_order"] >= 1
        assert edge["shreve_magnitude"] >= 1
