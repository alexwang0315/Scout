"""DEM extraction implementation for Navigation & Terrain Intelligence."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from navigation_terrain_coordinates import twd97_to_wgs84

STRUCTURE_KINDS = ("ridge", "valley", "saddle")
DEFAULT_MAX_PER_KIND = 24


class WorkspaceTerrainEvidenceError(ValueError):
    """Raised when workspace terrain evidence is unsafe or malformed."""


@dataclass(frozen=True)
class WorkspaceTerrainGrid:
    """One validated DEM window shared across projection stages."""

    terrain: dict[str, Any]
    coverage: dict[str, Any]
    elevations: Mapping[tuple[int, int], float]
    bbox_twd97: dict[str, float]
    resolution_m: float
    selected_tiles: tuple[dict[str, Any], ...]
    tile_ids: tuple[str, ...]
    corridor_filter_method: str


def classify_structure_neighborhood(
    center: float,
    neighbors_clockwise: Sequence[float],
    *,
    relief_threshold_m: float = 4.0,
) -> dict[str, Any]:
    """Classify one DEM cell from eight clockwise neighbors.

    The result is a geomorphology candidate, not a statement about trail
    existence or current walkability.
    """

    if len(neighbors_clockwise) != 8:
        raise WorkspaceTerrainEvidenceError(
            "terrain structure classification requires eight neighbors"
        )
    values = [float(value) for value in neighbors_clockwise]
    if not all(math.isfinite(value) for value in [float(center), *values]):
        raise WorkspaceTerrainEvidenceError(
            "terrain structure neighborhood contains non-finite elevation"
        )

    differences = [value - float(center) for value in values]
    local_mean = sum(values) / len(values)
    tpi_m = float(center) - local_mean
    higher_count = sum(value >= relief_threshold_m for value in differences)
    lower_count = sum(value <= -relief_threshold_m for value in differences)
    signs = [
        1 if value >= relief_threshold_m else -1
        for value in differences
        if abs(value) >= relief_threshold_m
    ]
    sign_changes = (
        sum(signs[index] != signs[(index + 1) % len(signs)] for index in range(len(signs)))
        if len(signs) >= 2
        else 0
    )
    relief_m = max(values) - min(values)

    feature_kind = None
    if higher_count >= 2 and lower_count >= 2 and sign_changes >= 4:
        feature_kind = "saddle"
    elif lower_count >= 6 and tpi_m >= relief_threshold_m:
        feature_kind = "ridge"
    elif higher_count >= 6 and tpi_m <= -relief_threshold_m:
        feature_kind = "valley"

    return {
        "feature_kind": feature_kind,
        "tpi_m": round(tpi_m, 3),
        "local_relief_m": round(relief_m, 3),
        "higher_neighbor_count": higher_count,
        "lower_neighbor_count": lower_count,
        "sign_changes": sign_changes,
    }


def extract_dem_structure_candidates(
    project_root: Path,
    project: dict[str, Any],
    *,
    max_per_kind: int = DEFAULT_MAX_PER_KIND,
    workspace_grid: WorkspaceTerrainGrid | None = None,
    route_points: Sequence[dict[str, Any]] | None = None,
    projected_route_points: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Extract bounded ridge, valley, and saddle candidates from workspace DTM."""

    if max_per_kind < 1 or max_per_kind > 100:
        raise WorkspaceTerrainEvidenceError("max_per_kind must be between 1 and 100")
    project_root = project_root.resolve()
    terrain_ref = _required_project_ref(project, "terrain_visualization_ref")
    coverage_ref = _required_project_ref(project, "dtm_coverage_summary_ref")
    loaded_grid = workspace_grid or load_workspace_terrain_grid(
        project_root,
        project,
    )
    terrain = loaded_grid.terrain
    dtm_grid = terrain.get("dtm_grid", {})
    bbox = loaded_grid.bbox_twd97
    resolution_m = loaded_grid.resolution_m
    tiles = list(loaded_grid.selected_tiles)
    elevation_by_xy = dict(loaded_grid.elevations)
    tile_ids = list(loaded_grid.tile_ids)

    route_ref = _optional_project_ref(project, "terrain_route_samples_ref")
    corridor_half_width_m = (
        _positive_number(dtm_grid.get("corridor_half_width_m")) or 500.0
    )
    route_distance_by_xy: dict[tuple[int, int], float] = {}
    route_points_twd97 = list(projected_route_points or ())
    corridor_filter_method = loaded_grid.corridor_filter_method
    bitmap_filtered = (
        elevation_by_xy
        if corridor_filter_method == "prepared_slope_bitmap_alpha"
        else None
    )
    if route_ref and route_points is None:
        route_payload = _read_project_json(project_root, route_ref)
        route_points = route_sample_points(route_payload)
    if route_points is not None and not route_points_twd97:
        route_points_twd97 = project_route_sample_points_twd97(route_points)
    if route_ref:
        if route_points_twd97 and bitmap_filtered is None:
            route_distance_by_xy = _route_point_distance_map(
                list(elevation_by_xy),
                route_points_twd97,
            )
            filtered: dict[tuple[int, int], float] = {}
            for (x, y), elevation in elevation_by_xy.items():
                distance_m = route_distance_by_xy.get((x, y))
                if distance_m is None or distance_m > corridor_half_width_m:
                    continue
                filtered[(x, y)] = elevation
            route_distance_by_xy = {
                key: value
                for key, value in route_distance_by_xy.items()
                if key in filtered
            }
            elevation_by_xy = filtered
            corridor_filter_method = "nearest_route_sample_numpy_chunked"

    step = int(round(resolution_m))
    raw_by_kind: dict[str, list[dict[str, Any]]] = {
        kind: [] for kind in STRUCTURE_KINDS
    }
    neighbor_offsets = (
        (0, step),
        (step, step),
        (step, 0),
        (step, -step),
        (0, -step),
        (-step, -step),
        (-step, 0),
        (-step, step),
    )
    for (x, y), center in elevation_by_xy.items():
        neighbor_values = [
            elevation_by_xy.get((x + dx, y + dy))
            for dx, dy in neighbor_offsets
        ]
        if any(value is None for value in neighbor_values):
            continue
        metrics = classify_structure_neighborhood(
            center,
            [float(value) for value in neighbor_values if value is not None],
        )
        feature_kind = metrics["feature_kind"]
        if feature_kind not in raw_by_kind:
            continue
        slope_degrees = _slope_degrees(
            center,
            east=elevation_by_xy.get((x + step, y)),
            west=elevation_by_xy.get((x - step, y)),
            north=elevation_by_xy.get((x, y + step)),
            south=elevation_by_xy.get((x, y - step)),
            resolution_m=resolution_m,
        )
        score = _structure_score(feature_kind, metrics)
        raw_by_kind[feature_kind].append(
            {
                "x": float(x),
                "y": float(y),
                "elevation_m": round(float(center), 2),
                "slope_degrees": round(slope_degrees, 2),
                "score": round(score, 3),
                "distance_to_route_m": round(
                    route_distance_by_xy.get((x, y), math.nan),
                    1,
                )
                if (x, y) in route_distance_by_xy
                else None,
                **metrics,
            }
        )

    points: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    rendered_counts: dict[str, int] = {}
    minimum_spacing_m = max(80.0, resolution_m * 3.0)
    for kind in STRUCTURE_KINDS:
        candidates = sorted(
            raw_by_kind[kind],
            key=lambda item: (-float(item["score"]), item["y"], item["x"]),
        )
        selected = _spatially_separated(
            candidates,
            limit=max_per_kind,
            minimum_spacing_m=minimum_spacing_m,
        )
        counts[kind] = len(candidates)
        rendered_counts[kind] = len(selected)
        for index, item in enumerate(selected, start=1):
            lat, lon = twd97_to_wgs84(item["x"], item["y"])
            distance_to_route_m = item["distance_to_route_m"]
            if distance_to_route_m is None and route_points_twd97:
                distance_to_route_m = round(
                    min(
                        math.hypot(
                            item["x"] - route_point["x"],
                            item["y"] - route_point["y"],
                        )
                        for route_point in route_points_twd97
                    ),
                    1,
                )
            points.append(
                {
                    "id": f"terrain-structure.{kind}.{index:03d}",
                    "feature_kind": kind,
                    "lon": round(lon, 8),
                    "lat": round(lat, 8),
                    "x_twd97": item["x"],
                    "y_twd97": item["y"],
                    "elevation_m": item["elevation_m"],
                    "slope_degrees": item["slope_degrees"],
                    "score": item["score"],
                    "distance_to_route_m": distance_to_route_m,
                    "tpi_m": item["tpi_m"],
                    "local_relief_m": item["local_relief_m"],
                    "higher_neighbor_count": item["higher_neighbor_count"],
                    "lower_neighbor_count": item["lower_neighbor_count"],
                    "sign_changes": item["sign_changes"],
                    "confidence": (
                        "medium"
                        if float(item["score"]) >= 20.0
                        else "low"
                    ),
                    "algorithm": "dtm_20m_local_morphology_candidate.v0",
                    "source_refs": [coverage_ref, terrain_ref],
                    "requires_human_review": True,
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                }
            )

    return {
        "schema_version": "scout_navigation_terrain_structure.v0",
        "artifact_kind": "dem_terrain_structure_candidates",
        "status": "candidate_points" if points else "not_prepared",
        "grid": {
            "crs": "EPSG:3826",
            "vertical_datum": _common_vertical_datum(tiles),
            "cell_resolution_m": resolution_m,
            "bbox_twd97": bbox,
            "selected_cell_count": len(elevation_by_xy),
            "source_tile_count": len(set(tile_ids)),
            "source_grid_file_count": len(tile_ids),
            "source_tile_ids": sorted(set(tile_ids)),
            "route_corridor_filter_applied": corridor_filter_method != "not_applied",
            "route_corridor_half_width_m": corridor_half_width_m,
            "route_corridor_distance_method": corridor_filter_method,
        },
        "counts": counts,
        "rendered_counts": rendered_counts,
        "max_per_kind": max_per_kind,
        "minimum_spacing_m": minimum_spacing_m,
        "points": points,
        "source_refs": [coverage_ref, terrain_ref],
        "limitations": [
            "Local DEM morphology does not prove a trail exists.",
            "Canopy, cliffs, erosion, vegetation, water, and access are not resolved.",
            "Ridge, valley, and saddle labels require map or field review.",
        ],
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "safe_or_walkable": "not_determined",
            "raw_dem_embedded": False,
            "absolute_grid_paths_exposed": False,
            "human_review_required": True,
            "phase1_runtime_mutation_allowed": False,
            "safety_api_called": False,
        },
    }


def load_workspace_terrain_grid(
    project_root: Path,
    project: dict[str, Any],
    *,
    terrain_payload: dict[str, Any] | None = None,
    coverage_payload: dict[str, Any] | None = None,
) -> WorkspaceTerrainGrid:
    """Read and validate the prepared DEM window exactly once."""

    root = project_root.resolve()
    terrain_ref = _required_project_ref(project, "terrain_visualization_ref")
    coverage_ref = _required_project_ref(project, "dtm_coverage_summary_ref")
    terrain = (
        dict(terrain_payload)
        if isinstance(terrain_payload, dict)
        else _read_project_json(root, terrain_ref)
    )
    coverage = (
        dict(coverage_payload)
        if isinstance(coverage_payload, dict)
        else _read_project_json(root, coverage_ref)
    )
    dtm_grid = terrain.get("dtm_grid", {})
    if not isinstance(dtm_grid, dict):
        raise WorkspaceTerrainEvidenceError("terrain visualization has no dtm_grid")
    bbox = _normalize_bbox_twd97(
        dtm_grid.get("full_route_corridor_bbox_twd97")
        or dtm_grid.get("bbox_twd97")
    )
    if bbox is None:
        raise WorkspaceTerrainEvidenceError(
            "terrain visualization has no usable TWD97 bounding box"
        )
    resolution_m = _positive_number(dtm_grid.get("cell_resolution_m"))
    if resolution_m is None:
        raise WorkspaceTerrainEvidenceError(
            "terrain visualization has no cell resolution"
        )
    source_dirs = _declared_source_directories(coverage)
    raw_tiles = coverage.get("candidate_tiles", [])
    if not isinstance(raw_tiles, list):
        raise WorkspaceTerrainEvidenceError(
            "DTM coverage candidate_tiles must be a list"
        )

    elevations: dict[tuple[int, int], float] = {}
    selected_tiles: list[dict[str, Any]] = []
    tile_ids: list[str] = []
    for tile in raw_tiles:
        if not isinstance(tile, dict) or not _bbox_intersects(
            bbox,
            _normalize_bbox_twd97(tile.get("bbox_twd97")),
        ):
            continue
        grid_path = _validated_grid_path(tile, source_dirs)
        _read_grid_window(grid_path, bbox, elevations)
        selected_tiles.append(dict(tile))
        tile_ids.append(str(tile.get("tile_id") or grid_path.stem))

    filtered = _filter_elevations_by_prepared_corridor_bitmap(
        root,
        terrain,
        elevations,
        bbox=bbox,
        resolution_m=resolution_m,
    )
    return WorkspaceTerrainGrid(
        terrain=terrain,
        coverage=coverage,
        elevations=filtered if filtered is not None else elevations,
        bbox_twd97=bbox,
        resolution_m=resolution_m,
        selected_tiles=tuple(selected_tiles),
        tile_ids=tuple(tile_ids),
        corridor_filter_method=(
            "prepared_slope_bitmap_alpha"
            if filtered is not None
            else "not_applied"
        ),
    )


def _required_project_ref(project: dict[str, Any], key: str) -> str:
    value = project.get(key)
    if not isinstance(value, str) or not value.strip():
        raise WorkspaceTerrainEvidenceError(f"project has no {key}")
    return value.strip()


def _optional_project_ref(project: dict[str, Any], key: str) -> str | None:
    value = project.get(key)
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _read_project_json(project_root: Path, ref: str) -> dict[str, Any]:
    path = (project_root / ref).resolve()
    try:
        path.relative_to(project_root)
    except ValueError as exc:
        raise WorkspaceTerrainEvidenceError(
            "unsafe workspace terrain artifact reference"
        ) from exc
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkspaceTerrainEvidenceError(
            f"invalid workspace terrain artifact: {ref}"
        ) from exc
    if not isinstance(payload, dict):
        raise WorkspaceTerrainEvidenceError(
            f"workspace terrain artifact must be an object: {ref}"
        )
    return payload


def _normalize_bbox_twd97(value: Any) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None
    normalized = {
        key: _finite_number(value.get(key))
        for key in ("min_x", "min_y", "max_x", "max_y")
    }
    if any(item is None for item in normalized.values()):
        return None
    if normalized["min_x"] >= normalized["max_x"]:
        return None
    if normalized["min_y"] >= normalized["max_y"]:
        return None
    return {
        key: float(item)
        for key, item in normalized.items()
        if item is not None
    }


def _declared_source_directories(payload: dict[str, Any]) -> list[Path]:
    values = payload.get("source_dirs", [])
    if not isinstance(values, list):
        raise WorkspaceTerrainEvidenceError("DTM source_dirs must be a list")
    directories = [
        Path(value).expanduser().resolve()
        for value in values
        if isinstance(value, str) and value.strip()
    ]
    if not directories:
        raise WorkspaceTerrainEvidenceError(
            "DTM coverage has no declared source directories"
        )
    return directories


def _validated_grid_path(
    tile: dict[str, Any],
    source_dirs: Sequence[Path],
) -> Path:
    value = tile.get("grid_uri")
    if not isinstance(value, str) or not value.strip():
        raise WorkspaceTerrainEvidenceError("DTM tile has no grid_uri")
    path = Path(value).expanduser().resolve()
    if path.suffix.lower() != ".grd":
        raise WorkspaceTerrainEvidenceError("DTM grid must use a .grd file")
    if not any(_is_relative_to(path, directory) for directory in source_dirs):
        raise WorkspaceTerrainEvidenceError(
            "DTM grid is outside declared DTM source directories"
        )
    if not path.is_file():
        raise WorkspaceTerrainEvidenceError("DTM grid file does not exist")
    return path


def _filter_elevations_by_prepared_corridor_bitmap(
    project_root: Path,
    terrain: dict[str, Any],
    elevation_by_xy: dict[tuple[int, int], float],
    *,
    bbox: dict[str, float],
    resolution_m: float,
) -> dict[tuple[int, int], float] | None:
    overlays = terrain.get("raster_overlays", [])
    if not isinstance(overlays, list):
        return None
    slope_overlay = next(
        (
            item
            for item in overlays
            if isinstance(item, dict)
            and item.get("mode") == "slope_shading"
            and isinstance(item.get("source_path"), str)
        ),
        None,
    )
    if slope_overlay is None:
        return None
    path = (project_root / str(slope_overlay["source_path"])).resolve()
    try:
        path.relative_to(project_root)
    except ValueError as exc:
        raise WorkspaceTerrainEvidenceError(
            "unsafe prepared terrain overlay reference"
        ) from exc
    if not path.is_file():
        return None
    try:
        from PIL import Image

        image = Image.open(path).convert("RGBA")
    except Exception as exc:
        raise WorkspaceTerrainEvidenceError(
            "prepared terrain overlay could not be read"
        ) from exc
    width, height = image.size
    pixels = image.load()
    selected: dict[tuple[int, int], float] = {}
    for (x, y), elevation in elevation_by_xy.items():
        col = int(math.floor((x - bbox["min_x"]) / resolution_m))
        row = int(math.floor((bbox["max_y"] - y) / resolution_m))
        if not (0 <= col < width and 0 <= row < height):
            continue
        if pixels[col, row][3] < 100:
            continue
        selected[(x, y)] = elevation
    return selected


def _is_relative_to(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
    except ValueError:
        return False
    return True


def _read_grid_window(
    path: Path,
    bbox: dict[str, float],
    elevation_by_xy: dict[tuple[int, int], float],
) -> None:
    try:
        handle = path.open(encoding="utf-8", errors="ignore")
    except OSError as exc:
        raise WorkspaceTerrainEvidenceError("DTM grid could not be read") from exc
    with handle:
        for line in handle:
            parts = line.split()
            if len(parts) < 3:
                continue
            x = _finite_number(parts[0])
            y = _finite_number(parts[1])
            elevation = _finite_number(parts[2])
            if x is None or y is None or elevation is None:
                continue
            if not (
                bbox["min_x"] <= x <= bbox["max_x"]
                and bbox["min_y"] <= y <= bbox["max_y"]
            ):
                continue
            elevation_by_xy[(int(round(x)), int(round(y)))] = elevation


def _bbox_intersects(
    a: dict[str, float],
    b: dict[str, float] | None,
) -> bool:
    if b is None:
        return False
    return not (
        a["max_x"] < b["min_x"]
        or a["min_x"] > b["max_x"]
        or a["max_y"] < b["min_y"]
        or a["min_y"] > b["max_y"]
    )


def _slope_degrees(
    center: float,
    *,
    east: float | None,
    west: float | None,
    north: float | None,
    south: float | None,
    resolution_m: float,
) -> float:
    dz_dx = (
        (east - west) / (2.0 * resolution_m)
        if east is not None and west is not None
        else 0.0
    )
    dz_dy = (
        (north - south) / (2.0 * resolution_m)
        if north is not None and south is not None
        else 0.0
    )
    return math.degrees(math.atan(math.hypot(dz_dx, dz_dy)))


def _structure_score(kind: str, metrics: dict[str, Any]) -> float:
    if kind == "saddle":
        return (
            float(metrics["local_relief_m"])
            + float(metrics["sign_changes"]) * 2.0
            - abs(float(metrics["tpi_m"]))
        )
    return abs(float(metrics["tpi_m"])) + float(metrics["local_relief_m"]) * 0.5


def _spatially_separated(
    candidates: Sequence[dict[str, Any]],
    *,
    limit: int,
    minimum_spacing_m: float,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    minimum_spacing_sq = minimum_spacing_m * minimum_spacing_m
    for candidate in candidates:
        if any(
            (float(candidate["x"]) - float(existing["x"])) ** 2
            + (float(candidate["y"]) - float(existing["y"])) ** 2
            < minimum_spacing_sq
            for existing in selected
        ):
            continue
        selected.append(dict(candidate))
        if len(selected) >= limit:
            break
    return selected


def _common_vertical_datum(tiles: Sequence[Any]) -> str | None:
    values = {
        str(tile.get("vertical_datum"))
        for tile in tiles
        if isinstance(tile, dict) and tile.get("vertical_datum")
    }
    return values.pop() if len(values) == 1 else None


def route_sample_points(payload: dict[str, Any]) -> list[dict[str, Any]]:
    features = payload.get("features", [])
    if not isinstance(features, list):
        return []
    points = []
    for index, feature in enumerate(features):
        if not isinstance(feature, dict):
            continue
        geometry = feature.get("geometry", {})
        properties = feature.get("properties", {})
        if (
            not isinstance(geometry, dict)
            or geometry.get("type") != "Point"
            or not isinstance(properties, dict)
        ):
            continue
        coordinates = geometry.get("coordinates")
        if not isinstance(coordinates, list) or len(coordinates) < 2:
            continue
        lon = _finite_number(coordinates[0])
        lat = _finite_number(coordinates[1])
        distance_m = _finite_number(properties.get("distance_m"))
        if lon is None or lat is None or distance_m is None:
            continue
        points.append(
            {
                "id": str(
                    properties.get("candidate_id")
                    or f"route-sample-{index:05d}"
                ),
                "lon": lon,
                "lat": lat,
                "distance_m": distance_m,
                "elevation_m": _finite_number(properties.get("elevation_m")),
            }
        )
    points.sort(key=lambda item: (item["distance_m"], item["id"]))
    return points


def project_route_sample_points_twd97(
    route_points: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    from pretrip_source_ingest import wgs84_to_twd97

    projected = []
    for point in route_points:
        x, y = wgs84_to_twd97(float(point["lat"]), float(point["lon"]))
        if projected and math.hypot(
            projected[-1]["x"] - x,
            projected[-1]["y"] - y,
        ) < 0.001:
            continue
        projected.append(
            {
                "id": str(point.get("id") or f"route-sample-{len(projected):05d}"),
                "x": x,
                "y": y,
                "x_twd97": x,
                "y_twd97": y,
                "distance_m": point.get("distance_m"),
                "elevation_m": point.get("elevation_m"),
            }
        )
    return projected


_route_sample_points = route_sample_points
_route_points_twd97 = project_route_sample_points_twd97


def _route_point_distance_map(
    cells: Sequence[tuple[int, int]],
    route_points: Sequence[dict[str, float]],
) -> dict[tuple[int, int], float]:
    """Return nearest route-sample distance using bounded NumPy chunks."""

    if not cells or not route_points:
        return {}
    try:
        import numpy as np
    except ImportError:
        route_index = _route_segment_index_twd97(
            route_points,
            corridor_half_width_m=500.0,
        )
        return {
            cell: math.sqrt(distance_sq)
            for cell in cells
            if (
                distance_sq := _nearest_route_distance_sq(
                    cell[0],
                    cell[1],
                    route_index,
                )
            )
            is not None
        }

    route_array = np.asarray(
        [[point["x"], point["y"]] for point in route_points],
        dtype=np.float64,
    )
    result: dict[tuple[int, int], float] = {}
    chunk_size = 2048
    for start in range(0, len(cells), chunk_size):
        chunk = cells[start : start + chunk_size]
        cell_array = np.asarray(chunk, dtype=np.float64)
        difference = cell_array[:, None, :] - route_array[None, :, :]
        squared = np.einsum("ijk,ijk->ij", difference, difference)
        minimum = np.sqrt(np.min(squared, axis=1))
        result.update(
            {
                cell: float(distance)
                for cell, distance in zip(chunk, minimum, strict=True)
            }
        )
    return result


def _route_segment_index_twd97(
    route_points: Sequence[dict[str, float]],
    *,
    corridor_half_width_m: float,
) -> dict[str, Any]:
    bucket_size_m = max(200.0, corridor_half_width_m)
    segments: list[dict[str, float]] = []
    buckets: dict[tuple[int, int], list[int]] = {}
    for point_a, point_b in zip(route_points, route_points[1:]):
        ax, ay = point_a["x"], point_a["y"]
        bx, by = point_b["x"], point_b["y"]
        if math.hypot(ax - bx, ay - by) < 0.001:
            continue
        segment = {
            "ax": ax,
            "ay": ay,
            "bx": bx,
            "by": by,
            "min_x": min(ax, bx) - corridor_half_width_m,
            "min_y": min(ay, by) - corridor_half_width_m,
            "max_x": max(ax, bx) + corridor_half_width_m,
            "max_y": max(ay, by) + corridor_half_width_m,
        }
        segment_id = len(segments)
        segments.append(segment)
        for bucket_x in range(
            math.floor(segment["min_x"] / bucket_size_m),
            math.floor(segment["max_x"] / bucket_size_m) + 1,
        ):
            for bucket_y in range(
                math.floor(segment["min_y"] / bucket_size_m),
                math.floor(segment["max_y"] / bucket_size_m) + 1,
            ):
                buckets.setdefault((bucket_x, bucket_y), []).append(segment_id)
    return {
        "segments": segments,
        "buckets": buckets,
        "bucket_size_m": bucket_size_m,
    }


def _nearest_route_distance_sq(
    x: float,
    y: float,
    segment_index: dict[str, Any],
) -> float | None:
    bucket_size_m = float(segment_index["bucket_size_m"])
    bucket = (
        math.floor(x / bucket_size_m),
        math.floor(y / bucket_size_m),
    )
    nearest = None
    for segment_id in segment_index["buckets"].get(bucket, []):
        segment = segment_index["segments"][segment_id]
        if not (
            segment["min_x"] <= x <= segment["max_x"]
            and segment["min_y"] <= y <= segment["max_y"]
        ):
            continue
        distance_sq = _point_segment_distance_sq(
            x,
            y,
            segment["ax"],
            segment["ay"],
            segment["bx"],
            segment["by"],
        )
        if nearest is None or distance_sq < nearest:
            nearest = distance_sq
    return nearest


def _point_segment_distance_sq(
    px: float,
    py: float,
    ax: float,
    ay: float,
    bx: float,
    by: float,
) -> float:
    vx, vy = bx - ax, by - ay
    wx, wy = px - ax, py - ay
    denominator = vx * vx + vy * vy
    if denominator <= 0:
        return (px - ax) ** 2 + (py - ay) ** 2
    ratio = max(0.0, min(1.0, (wx * vx + wy * vy) / denominator))
    qx, qy = ax + ratio * vx, ay + ratio * vy
    return (px - qx) ** 2 + (py - qy) ** 2


def _even_indices(item_count: int, limit: int) -> list[int]:
    if item_count <= 0 or limit <= 0:
        return []
    if item_count <= limit:
        return list(range(item_count))
    if limit == 1:
        return [0]
    return sorted(
        {
            round(index * (item_count - 1) / (limit - 1))
            for index in range(limit)
        }
    )


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _positive_number(value: Any) -> float | None:
    number = _finite_number(value)
    return number if number is not None and number > 0 else None
