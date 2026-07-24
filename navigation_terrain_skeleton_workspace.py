"""Prepared-workspace adapter for the bounded terrain skeleton engine."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from navigation_terrain_dem import (
    WorkspaceTerrainEvidenceError,
    _bbox_intersects,
    _common_vertical_datum,
    _declared_source_directories,
    _filter_elevations_by_prepared_corridor_bitmap,
    _normalize_bbox_twd97,
    _positive_number,
    _read_grid_window,
    _read_project_json,
    _required_project_ref,
    _validated_grid_path,
)
from navigation_terrain_skeleton import build_terrain_hierarchy_from_grid


def build_workspace_terrain_hierarchy(
    project_root: Path,
    project: dict[str, Any],
    **options: Any,
) -> dict[str, Any]:
    """Load the bounded prepared workspace DEM and build a terrain hierarchy."""

    project_root = project_root.resolve()
    terrain_ref = _required_project_ref(project, "terrain_visualization_ref")
    coverage_ref = _required_project_ref(project, "dtm_coverage_summary_ref")
    terrain = _read_project_json(project_root, terrain_ref)
    coverage = _read_project_json(project_root, coverage_ref)
    dtm_grid = terrain.get("dtm_grid", {})
    if not isinstance(dtm_grid, dict):
        raise WorkspaceTerrainEvidenceError("terrain visualization has no dtm_grid")
    bbox = _normalize_bbox_twd97(
        dtm_grid.get("full_route_corridor_bbox_twd97") or dtm_grid.get("bbox_twd97")
    )
    resolution_m = _positive_number(dtm_grid.get("cell_resolution_m"))
    if bbox is None or resolution_m is None:
        raise WorkspaceTerrainEvidenceError(
            "terrain visualization has no usable grid bounds"
        )
    source_dirs = _declared_source_directories(coverage)
    raw_tiles = coverage.get("candidate_tiles", [])
    if not isinstance(raw_tiles, list):
        raise WorkspaceTerrainEvidenceError("DTM candidate_tiles must be a list")

    elevations: dict[tuple[int, int], float] = {}
    selected_tiles: list[dict[str, Any]] = []
    for tile in raw_tiles:
        if not isinstance(tile, dict):
            continue
        tile_bbox = _normalize_bbox_twd97(tile.get("bbox_twd97"))
        if not _bbox_intersects(bbox, tile_bbox):
            continue
        _read_grid_window(
            _validated_grid_path(tile, source_dirs),
            bbox,
            elevations,
        )
        selected_tiles.append(tile)
    filtered = _filter_elevations_by_prepared_corridor_bitmap(
        project_root,
        terrain,
        elevations,
        bbox=bbox,
        resolution_m=resolution_m,
    )
    return build_terrain_hierarchy_from_grid(
        filtered if filtered is not None else elevations,
        resolution_m=resolution_m,
        source_refs=[coverage_ref, terrain_ref],
        vertical_datum=_common_vertical_datum(selected_tiles),
        **options,
    )
