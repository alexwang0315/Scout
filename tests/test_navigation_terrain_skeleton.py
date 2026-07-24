from __future__ import annotations

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


def test_skeleton_builds_continuous_ridge_and_drainage_hierarchy() -> None:
    result = build_terrain_hierarchy_from_grid(
        _branched_terrain(),
        resolution_m=20,
        source_refs=["synthetic-branched-dem"],
        relief_threshold_m=6,
        minimum_component_cells=3,
    )

    assert result["status"] == "candidate_hierarchy"
    assert result["schema_version"] == "scout_navigation_terrain_hierarchy.v0"
    edge_kinds = {edge["kind"] for edge in result["edges"]}
    assert "main_ridge_candidate" in edge_kinds
    assert "spur_ridge_candidate" in edge_kinds
    assert "drainage_trunk" in edge_kinds
    assert all(len(edge["coordinates_twd97"]) >= 2 for edge in result["edges"])
    assert any(node["kind"] == "ridge_divide_node" for node in result["nodes"])
    assert any(node["kind"] == "headwater_node" for node in result["nodes"])
    assert all(edge["candidate_only"] is True for edge in result["edges"])
    assert result["boundary"]["safe_or_walkable"] == "not_determined"
    assert result["method"]["ridge_extraction"].startswith("multi_scale_cross_section")


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
