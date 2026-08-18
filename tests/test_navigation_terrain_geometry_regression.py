from __future__ import annotations

import math

from navigation_terrain_skeleton import build_terrain_hierarchy_from_grid


def _linear_landform(
    angle_degrees: float,
    *,
    resolution_m: int = 20,
    size: int = 41,
    ridge: bool = True,
    curvature: float = 0.018,
) -> tuple[dict[tuple[float, float], float], tuple[float, float], tuple[float, float]]:
    half_extent = (size - 1) * resolution_m / 2
    angle = math.radians(angle_degrees)
    tangent = (math.cos(angle), math.sin(angle))
    normal = (-math.sin(angle), math.cos(angle))
    center = (250_000 + half_extent, 2_600_000 + half_extent)
    elevations = {}
    for row in range(size):
        for col in range(size):
            x = 250_000 + col * resolution_m
            y = 2_600_000 + row * resolution_m
            dx, dy = x - center[0], y - center[1]
            cross = dx * normal[0] + dy * normal[1]
            along = dx * tangent[0] + dy * tangent[1]
            form = curvature * cross * cross
            elevations[(x, y)] = 1800 + (form if not ridge else -form) - 0.02 * along
    return elevations, center, normal


def _hierarchy(
    elevations: dict[tuple[float, float], float],
    *,
    resolution_m: int,
    threshold_m: float = 2,
) -> dict:
    return build_terrain_hierarchy_from_grid(
        elevations,
        resolution_m=resolution_m,
        source_refs=["analytic-dem-fixture"],
        relief_threshold_m=threshold_m,
        minimum_component_cells=4,
    )


def _longest_ridge(result: dict) -> dict:
    return max(
        (
            edge
            for edge in result["edges"]
            if edge["kind"] in {"main_ridge_candidate", "spur_ridge_candidate"}
        ),
        key=lambda edge: edge["length_m"],
    )


def _lateral_rmse(
    edge: dict,
    center: tuple[float, float],
    normal: tuple[float, float],
) -> float:
    offsets = [
        abs(
            (point[0] - center[0]) * normal[0]
            + (point[1] - center[1]) * normal[1]
        )
        for point in edge["coordinates_twd97"]
    ]
    return math.sqrt(sum(value * value for value in offsets) / len(offsets))


def _quantized_fraction(edge: dict) -> float:
    angles = [
        math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 180
        for a, b in zip(
            edge["coordinates_twd97"],
            edge["coordinates_twd97"][1:],
        )
        if math.dist(a[:2], b[:2]) > 0.01
    ]
    quantized = sum(
        min(abs(angle - axis) for axis in (0, 45, 90, 135, 180)) <= 2
        for angle in angles
    )
    return quantized / len(angles)


def test_arbitrarily_rotated_ridges_remain_subcell_and_non_quantized() -> None:
    for angle in (17, 73, 127):
        elevations, center, normal = _linear_landform(angle)
        result = _hierarchy(elevations, resolution_m=20)
        edge = _longest_ridge(result)

        assert result["counts"]["main_ridge_count"] == 1
        assert _lateral_rmse(edge, center, normal) < 4
        assert _quantized_fraction(edge) < 0.25
        assert edge["classification_basis"] == (
            "component_weighted_geodesic_backbone_overlap"
        )
        assert 0 <= edge["backbone_support_ratio"] <= 1
        audit = edge["source_support_audit"]
        assert audit["audit_method"] == "ridge_edge_support_audit.v1"
        assert audit["source_chain_cell_count"] >= 2
        assert audit["total_length_m"] > 0
        assert audit["supported_length_m"] == audit["total_length_m"]
        assert audit["unsupported_length_m"] == 0
        assert audit["longest_unsupported_run_m"] == 0
        assert audit["support_ratio_denominator"] == "raw_source_chain_length_m"
        assert audit["render_geometry_within_support_envelope"] is True
        assert edge["hierarchy_presentation"] in {
            "contextual_candidate",
            "suppressed_boundary_censored",
        }


def test_ridge_localization_is_stable_across_dem_resolutions() -> None:
    normalized_errors = []
    for resolution_m, size in ((10, 81), (20, 41), (40, 21)):
        elevations, center, normal = _linear_landform(
            31,
            resolution_m=resolution_m,
            size=size,
        )
        result = _hierarchy(elevations, resolution_m=resolution_m)
        edge = _longest_ridge(result)
        normalized_errors.append(
            _lateral_rmse(edge, center, normal) / resolution_m
        )
        assert result["counts"]["main_ridge_count"] == 1
        assert result["counts"]["drainage_trunk_count"] == 0

    assert max(normalized_errors) < 0.1
    assert max(normalized_errors) - min(normalized_errors) < 0.08


def test_s_curve_and_y_junction_preserve_curvature_and_branch_topology() -> None:
    resolution_m = 20
    size = 61
    midpoint = (size - 1) * resolution_m / 2
    s_curve = {}
    for row in range(size):
        y_local = row * resolution_m
        center_x = midpoint + 150 * math.sin((y_local - midpoint) / 240)
        for col in range(size):
            x_local = col * resolution_m
            cross = x_local - center_x
            s_curve[(250_000 + x_local, 2_600_000 + y_local)] = (
                2200 - 0.010 * cross * cross - row * 2.0
            )
    s_result = _hierarchy(s_curve, resolution_m=resolution_m, threshold_m=3)
    s_edge = _longest_ridge(s_result)
    assert len(s_edge["coordinates_twd97"]) >= 20
    assert _quantized_fraction(s_edge) < 0.85

    branched = {}
    for row in range(15):
        for col in range(15):
            ridge = 80.0 - abs(col - 7) * 12.0
            spur = (
                42.0 - abs(row - 8) * 12.0
                if col <= 7 and 4 <= row <= 12
                else -100.0
            )
            basin = (
                -28.0 + abs(col - 3) * 9.0
                if col < 7
                else -25.0 + abs(col - 11) * 9.0
            )
            branched[(250_000 + col * 20, 2_600_000 + row * 20)] = (
                1000.0 + row * 2.0 + max(ridge, spur, basin)
            )
    branch_result = _hierarchy(branched, resolution_m=20, threshold_m=6)
    ridge_edges = [
        edge
        for edge in branch_result["edges"]
        if edge["kind"] in {"main_ridge_candidate", "spur_ridge_candidate"}
    ]
    assert len(ridge_edges) == 3
    assert any(edge["kind"] == "spur_ridge_candidate" for edge in ridge_edges)
    assert any(
        node["kind"] == "ridge_divide_node" and node["degree"] >= 3
        for node in branch_result["nodes"]
    )


def test_saddle_broad_sharp_flat_and_depression_regressions() -> None:
    for curvature in (0.006, 0.024):
        crest, _center, _normal = _linear_landform(
            22,
            curvature=curvature,
        )
        result = _hierarchy(crest, resolution_m=20, threshold_m=2)
        assert result["counts"]["main_ridge_count"] == 1

    size = 31
    resolution_m = 20
    midpoint = (size - 1) * resolution_m / 2
    saddle = {}
    depression = {}
    flat = {}
    for row in range(size):
        for col in range(size):
            x = 250_000 + col * resolution_m
            y = 2_600_000 + row * resolution_m
            dx, dy = col * resolution_m - midpoint, row * resolution_m - midpoint
            saddle[(x, y)] = 1500 + 0.01 * dx * dx - 0.01 * dy * dy
            depression[(x, y)] = 1500 + 0.004 * (dx * dx + dy * dy)
            flat[(x, y)] = 1500

    saddle_result = _hierarchy(saddle, resolution_m=20, threshold_m=2)
    assert saddle_result["counts"]["saddle_count"] == 1
    assert saddle_result["counts"]["saddle_relation_count"] >= 1
    assert saddle_result["saddle_relations"]
    assert all(
        relation["relation_kind"] == "saddle_near_ridge_candidate"
        and relation["candidate_only"] is True
        and relation["runtime_safety_truth"] is False
        and relation["distance_m"] <= relation["support_radius_m"]
        for relation in saddle_result["saddle_relations"]
    )

    flat_result = _hierarchy(flat, resolution_m=20, threshold_m=2)
    assert flat_result["status"] == "not_prepared"
    assert flat_result["counts"]["edge_count"] == 0

    depression_result = _hierarchy(depression, resolution_m=20, threshold_m=2)
    hydrology = depression_result["method"]["hydrology"]
    assert hydrology["maximum_conditioning_delta_m"] > 0
    assert hydrology["suppressed_by_conditioning_count"] > 0
    assert depression_result["counts"]["drainage_trunk_count"] == 0
