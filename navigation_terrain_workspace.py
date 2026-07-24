"""Compatibility facade for Navigation & Terrain Intelligence workspace logic."""

from navigation_route_terrain_events import (
    build_route_terrain_events,
    build_workspace_route_terrain_events,
)
from navigation_terrain_annotations import normalize_expert_terrain_annotations
from navigation_terrain_dem import (
    WorkspaceTerrainEvidenceError,
    classify_structure_neighborhood,
    extract_dem_structure_candidates,
)
from navigation_terrain_skeleton import build_terrain_hierarchy_from_grid
from navigation_terrain_skeleton_workspace import (
    build_workspace_terrain_hierarchy,
)
from navigation_terrain_sources import build_workspace_source_ledger
from navigation_terrain_topology import build_workspace_route_topology

__all__ = [
    "WorkspaceTerrainEvidenceError",
    "build_route_terrain_events",
    "build_workspace_route_topology",
    "build_workspace_route_terrain_events",
    "build_workspace_source_ledger",
    "build_workspace_terrain_hierarchy",
    "build_terrain_hierarchy_from_grid",
    "classify_structure_neighborhood",
    "extract_dem_structure_candidates",
    "normalize_expert_terrain_annotations",
]
