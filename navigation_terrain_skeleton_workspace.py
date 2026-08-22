"""Prepared-workspace adapter for the bounded terrain skeleton engine."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from navigation_terrain_dem import (
    WorkspaceTerrainGrid,
    _common_vertical_datum,
    _required_project_ref,
    load_workspace_terrain_grid,
)
from navigation_terrain_skeleton import build_terrain_hierarchy_from_grid


def build_workspace_terrain_hierarchy(
    project_root: Path,
    project: dict[str, Any],
    *,
    workspace_grid: WorkspaceTerrainGrid | None = None,
    **options: Any,
) -> dict[str, Any]:
    """Load the bounded prepared workspace DEM and build a terrain hierarchy."""

    project_root = project_root.resolve()
    terrain_ref = _required_project_ref(project, "terrain_visualization_ref")
    coverage_ref = _required_project_ref(project, "dtm_coverage_summary_ref")
    grid = workspace_grid or load_workspace_terrain_grid(project_root, project)
    return build_terrain_hierarchy_from_grid(
        grid.elevations,
        resolution_m=grid.resolution_m,
        source_refs=[coverage_ref, terrain_ref],
        vertical_datum=_common_vertical_datum(grid.selected_tiles),
        **options,
    )
