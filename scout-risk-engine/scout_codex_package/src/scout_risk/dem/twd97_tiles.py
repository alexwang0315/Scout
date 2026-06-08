from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from scout_risk.dem.io import DEMGrid
from scout_risk.geo import wgs84_to_twd97


@dataclass(frozen=True)
class DtmMosaicBuildResult:
    dem: DEMGrid
    metadata: dict[str, Any]


def build_dem_from_dtm_coverage(
    coverage_path: str | Path,
    *,
    route_points_wgs84: list[tuple[float, float]],
    buffer_m: float = 140.0,
    pixel_size_m: float = 20.0,
) -> DtmMosaicBuildResult:
    coverage_file = Path(coverage_path)
    payload = json.loads(coverage_file.read_text(encoding="utf-8"))
    if not route_points_wgs84:
        raise ValueError("route_points_wgs84 must not be empty")

    projected = [wgs84_to_twd97(lat, lon) for lat, lon in route_points_wgs84]
    xs = [point[0] for point in projected]
    ys = [point[1] for point in projected]
    pixel_size = pixel_size_m
    min_x = _floor_to_grid(min(xs) - buffer_m, pixel_size)
    max_x = _ceil_to_grid(max(xs) + buffer_m, pixel_size)
    min_y = _floor_to_grid(min(ys) - buffer_m, pixel_size)
    max_y = _ceil_to_grid(max(ys) + buffer_m, pixel_size)

    cols = int(round((max_x - min_x) / pixel_size)) + 1
    rows = int(round((max_y - min_y) / pixel_size)) + 1
    elevation = np.full((rows, cols), np.nan, dtype=float)
    clip_bbox = {"min_x": min_x, "min_y": min_y, "max_x": max_x, "max_y": max_y}

    scanned_tiles = 0
    used_tiles: list[str] = []
    filled_cells = 0
    duplicate_cells = 0
    for tile in payload.get("candidate_tiles", []):
        tile_bbox = tile.get("bbox_twd97", {})
        if not _bbox_intersects(clip_bbox, tile_bbox):
            continue
        grid_uri = tile.get("grid_uri")
        if not grid_uri:
            continue
        grid_path = Path(grid_uri)
        if not grid_path.is_file():
            continue
        scanned_tiles += 1
        wrote_any = False
        with grid_path.open("r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                parts = line.split()
                if len(parts) < 3:
                    continue
                try:
                    x = float(parts[0])
                    y = float(parts[1])
                    z = float(parts[2])
                except ValueError:
                    continue
                if x < min_x or x > max_x or y < min_y or y > max_y:
                    continue
                col = int(round((x - min_x) / pixel_size))
                row = int(round((max_y - y) / pixel_size))
                if row < 0 or col < 0 or row >= rows or col >= cols:
                    continue
                if np.isnan(elevation[row, col]):
                    filled_cells += 1
                else:
                    duplicate_cells += 1
                elevation[row, col] = z
                wrote_any = True
        if wrote_any:
            used_tiles.append(str(grid_path))

    if filled_cells == 0:
        raise ValueError("DTM coverage did not provide any grid cells for the route corridor")

    dem = DEMGrid(
        elevation=elevation,
        x_min=min_x,
        y_max=max_y,
        pixel_size=pixel_size,
        crs="EPSG:3826",
        nodata=np.nan,
    )
    total_cells = rows * cols
    metadata = {
        "coverage_ref": str(coverage_file),
        "source_dirs": payload.get("source_dirs", []),
        "route_point_count": len(route_points_wgs84),
        "buffer_m": buffer_m,
        "clip_bbox_twd97": clip_bbox,
        "rows": rows,
        "cols": cols,
        "pixel_size_m": pixel_size,
        "candidate_tile_count": len(payload.get("candidate_tiles", [])),
        "scanned_tile_count": scanned_tiles,
        "used_tile_count": len(used_tiles),
        "used_tiles": used_tiles,
        "filled_cells": filled_cells,
        "duplicate_cells": duplicate_cells,
        "coverage_ratio": round(filled_cells / total_cells, 6),
        "raw_dtm_copied": False,
    }
    return DtmMosaicBuildResult(dem=dem, metadata=metadata)


def _bbox_intersects(a: dict[str, float], b: dict[str, float]) -> bool:
    return not (
        float(a["max_x"]) < float(b.get("min_x", math.inf))
        or float(a["min_x"]) > float(b.get("max_x", -math.inf))
        or float(a["max_y"]) < float(b.get("min_y", math.inf))
        or float(a["min_y"]) > float(b.get("max_y", -math.inf))
    )


def _floor_to_grid(value: float, grid: float) -> float:
    return math.floor(value / grid) * grid


def _ceil_to_grid(value: float, grid: float) -> float:
    return math.ceil(value / grid) * grid
