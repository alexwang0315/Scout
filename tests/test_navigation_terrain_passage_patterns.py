from __future__ import annotations

from navigation_terrain_dem import WorkspaceTerrainGrid
from navigation_terrain_passage_patterns import build_terrain_passage_prior


def _sloped_grid() -> WorkspaceTerrainGrid:
    elevations = {
        (250_000 + column * 20, 2_600_000 + row * 20): 1_000 + column * 10
        for row in range(11)
        for column in range(11)
    }
    return WorkspaceTerrainGrid(
        terrain={},
        coverage={},
        elevations=elevations,
        bbox_twd97={
            "min_x": 250_000,
            "min_y": 2_600_000,
            "max_x": 250_200,
            "max_y": 2_600_200,
        },
        resolution_m=20,
        selected_tiles=(),
        tile_ids=("fixture",),
        corridor_filter_method="not_applied",
    )


def test_positive_only_prior_learns_contour_and_fall_line_patterns() -> None:
    result = build_terrain_passage_prior(
        _sloped_grid(),
        observed_paths=[
            {
                "id": "gpx-contour",
                "source_kind": "gpx_observed",
                "coordinates_twd97": [
                    [250_100, 2_600_020],
                    [250_100, 2_600_180],
                ],
                "source_refs": ["reference.gpx"],
            },
            {
                "id": "osm-fall-line",
                "source_kind": "osm_overpass_trail",
                "coordinates_twd97": [
                    [250_020, 2_600_100],
                    [250_180, 2_600_100],
                ],
                "source_refs": ["overpass.geojson"],
            },
        ],
        terrain_hierarchy={"nodes": [], "edges": []},
        source_refs=["terrain.json", "reference.gpx", "overpass.geojson"],
    )

    assert result["status"] == "observed_positive_patterns"
    assert result["learning_contract"]["learning_mode"] == (
        "positive_unlabeled_descriptive_prior"
    )
    assert result["learning_contract"]["osm_absence_semantics"] == "unknown"
    assert result["learning_contract"]["negative_labels_created"] is False
    assert result["source_profiles"]["gpx_observed"]["alignment_counts"][
        "contour_following"
    ] > 0
    assert result["source_profiles"]["osm_overpass_trail"]["alignment_counts"][
        "fall_line"
    ] > 0
    assert result["observation_count"] > 10
    assert result["boundary"]["passability_asserted"] is False
    assert result["boundary"]["trail_existence_asserted"] is False


def test_prior_skips_unsupported_dem_cells_instead_of_bridging() -> None:
    grid = _sloped_grid()
    elevations = dict(grid.elevations)
    for row in range(11):
        elevations.pop((250_100, 2_600_000 + row * 20))
    grid_with_gap = WorkspaceTerrainGrid(
        terrain=grid.terrain,
        coverage=grid.coverage,
        elevations=elevations,
        bbox_twd97=grid.bbox_twd97,
        resolution_m=grid.resolution_m,
        selected_tiles=grid.selected_tiles,
        tile_ids=grid.tile_ids,
        corridor_filter_method=grid.corridor_filter_method,
    )

    result = build_terrain_passage_prior(
        grid_with_gap,
        observed_paths=[
            {
                "id": "crosses-gap",
                "source_kind": "gpx_observed",
                "coordinates_twd97": [
                    [250_020, 2_600_100],
                    [250_180, 2_600_100],
                ],
                "source_refs": ["reference.gpx"],
            }
        ],
        terrain_hierarchy={"nodes": [], "edges": []},
        source_refs=["terrain.json"],
    )

    assert result["sampling"]["unsupported_sample_count"] > 0
    assert result["sampling"]["unsupported_gap_bridge_count"] == 0
    assert result["learning_contract"]["rudy_tw_role"] == (
        "visual_reference_only_no_label_extraction"
    )


def test_prior_deduplicates_reversed_observed_vectors_and_declares_holdouts() -> None:
    forward = [[250_020, 2_600_100], [250_180, 2_600_100]]
    result = build_terrain_passage_prior(
        _sloped_grid(),
        observed_paths=[
            {
                "id": "osm-forward",
                "source_kind": "osm_overpass_trail",
                "coordinates_twd97": forward,
                "source_refs": ["overpass.geojson"],
            },
            {
                "id": "osm-reversed-duplicate",
                "source_kind": "osm_overpass_trail",
                "coordinates_twd97": list(reversed(forward)),
                "source_refs": ["overpass.geojson"],
            },
        ],
        terrain_hierarchy={"nodes": [], "edges": []},
        source_refs=["terrain.json", "overpass.geojson"],
    )

    assert result["source_path_count"] == 1
    assert result["sampling"]["duplicate_path_count"] == 1
    assert result["learning_contract"]["osm_mapping_completeness"] == (
        "unknown_not_measured"
    )
    assert result["learning_contract"]["terrain_extraction_feedback"] == "prohibited"
    assert result["evaluation"]["classifier_holdout_status"] == (
        "not_applicable_descriptive_prior"
    )
    assert result["evaluation"]["route_level_holdout_required_before_training"] is True
    assert result["evaluation"]["region_level_holdout_required_before_training"] is True
