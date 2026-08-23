"""Prepared MapLibre raster-DEM tiles for Navigation terrain review.

The preparation path emits only complete slippy-map tiles. MapLibre raster-dem
decoding does not provide a trustworthy alpha/nodata hole contract, so partial
tiles are excluded instead of encoding unsupported cells as plausible terrain.
The result remains candidate-only visualization evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from admin_local_raster_tiles import tile_bounds_wgs84


DEFAULT_TERRAIN_DEM_MANIFEST_REF = "outputs/navigation/terrain_rgb/manifest.json"
DEFAULT_TERRAIN_DEM_ZOOM = 13
DEFAULT_TERRAIN_DEM_TILE_SIZE = 256
TERRAIN_DEM_SCHEMA_VERSION = "scout_navigation_terrain_dem.v1"
TERRAIN_DEM_RESAMPLING = "bilinear_elevation"
LEGACY_TERRAIN_DEM_RESAMPLING = "nearest"
_SAFE_PROJECT_ID = re.compile(r"^[A-Za-z0-9_.-]+$")


class TerrainDemPreparationError(ValueError):
    """Raised when a trustworthy complete raster-DEM tile set cannot be built."""


def encode_mapbox_terrain_rgb(elevation_m: float) -> tuple[int, int, int]:
    """Encode metres using Mapbox Terrain RGB's decimetre representation."""

    elevation = float(elevation_m)
    if not math.isfinite(elevation):
        raise TerrainDemPreparationError("terrain elevation must be finite")
    encoded = int(round((elevation + 10_000.0) * 10.0))
    encoded = max(0, min(16_777_215, encoded))
    return encoded // 65_536, (encoded // 256) % 256, encoded % 256


def decode_mapbox_terrain_rgb(rgb: Sequence[int]) -> float:
    """Decode a three-channel Mapbox Terrain RGB value to metres."""

    if len(rgb) < 3:
        raise TerrainDemPreparationError("terrain RGB requires three channels")
    red, green, blue = (int(rgb[index]) for index in range(3))
    if any(value < 0 or value > 255 for value in (red, green, blue)):
        raise TerrainDemPreparationError("terrain RGB channels must be bytes")
    return -10_000.0 + (red * 65_536 + green * 256 + blue) * 0.1


def largest_complete_tile_block(
    complete_tiles: Iterable[tuple[int, int]],
) -> dict[str, int] | None:
    """Return the largest all-present axis-aligned tile rectangle."""

    tiles = {(int(x), int(y)) for x, y in complete_tiles}
    if not tiles:
        return None
    x_min = min(x for x, _ in tiles)
    x_max = max(x for x, _ in tiles)
    y_min = min(y for _, y in tiles)
    y_max = max(y for _, y in tiles)
    width = x_max - x_min + 1
    heights = [0] * width
    best: tuple[int, int, int, int, int, int] | None = None

    for y in range(y_min, y_max + 1):
        for offset in range(width):
            x = x_min + offset
            heights[offset] = heights[offset] + 1 if (x, y) in tiles else 0
        stack: list[tuple[int, int]] = []
        for offset in range(width + 1):
            height = heights[offset] if offset < width else 0
            start = offset
            while stack and stack[-1][1] > height:
                left, popped_height = stack.pop()
                block_width = offset - left
                area = popped_height * block_width
                candidate = (
                    area,
                    block_width,
                    -y,
                    -(x_min + left),
                    left,
                    popped_height,
                )
                if best is None or candidate[:4] > best[:4]:
                    best = candidate
                start = left
            if not stack or stack[-1][1] < height:
                stack.append((start, height))

    if best is None or best[0] <= 0:
        return None
    _, block_width, negative_bottom_y, _, left, block_height = best
    bottom_y = -negative_bottom_y
    return {
        "x_min": x_min + left,
        "x_max": x_min + left + block_width - 1,
        "y_min": bottom_y - block_height + 1,
        "y_max": bottom_y,
    }


def prepare_navigation_terrain_dem_tiles(
    project_root: Path,
    *,
    project_id: str | None = None,
    zoom: int = DEFAULT_TERRAIN_DEM_ZOOM,
    tile_size: int = DEFAULT_TERRAIN_DEM_TILE_SIZE,
    prepared_at: str | None = None,
) -> dict[str, Any]:
    """Prepare a complete Mapbox Terrain RGB tile block from workspace DTM."""

    root = Path(project_root).expanduser().resolve()
    project_path = root / "project.json"
    project = _read_json_object(project_path, "project")
    resolved_project_id = str(project_id or project.get("project_id") or "").strip()
    if not resolved_project_id or not _SAFE_PROJECT_ID.fullmatch(resolved_project_id):
        raise TerrainDemPreparationError("project_id contains unsafe characters")
    if project.get("project_id") not in (None, resolved_project_id):
        raise TerrainDemPreparationError("project_id does not match project.json")
    if zoom < 0 or zoom > 22:
        raise TerrainDemPreparationError("terrain DEM zoom must be between 0 and 22")
    if tile_size < 8 or tile_size > 512 or tile_size & (tile_size - 1):
        raise TerrainDemPreparationError(
            "terrain DEM tile_size must be a power of two between 8 and 512"
        )

    terrain_ref = _required_project_ref(project, "terrain_visualization_ref")
    coverage_ref = _required_project_ref(project, "dtm_coverage_summary_ref")
    terrain_path = _project_path(root, terrain_ref)
    coverage_path = _project_path(root, coverage_ref)
    terrain = _read_json_object(terrain_path, "terrain visualization")
    coverage = _read_json_object(coverage_path, "DTM coverage")
    dtm_grid = terrain.get("dtm_grid")
    if not isinstance(dtm_grid, Mapping):
        raise TerrainDemPreparationError("terrain visualization has no dtm_grid")
    bbox_twd97 = _normalize_bbox(
        dtm_grid.get("full_route_corridor_bbox_twd97")
        or dtm_grid.get("bbox_twd97"),
        keys=("min_x", "min_y", "max_x", "max_y"),
    )
    bbox_wgs84 = _normalize_bbox(
        dtm_grid.get("bbox_wgs84"),
        keys=("west", "south", "east", "north"),
    )
    resolution_m = _positive_number(dtm_grid.get("cell_resolution_m"))
    if bbox_twd97 is None or bbox_wgs84 is None or resolution_m is None:
        raise TerrainDemPreparationError(
            "terrain visualization has no complete DEM georeference"
        )

    width = max(
        1,
        int(round((bbox_twd97["max_x"] - bbox_twd97["min_x"]) / resolution_m)),
    )
    height = max(
        1,
        int(round((bbox_twd97["max_y"] - bbox_twd97["min_y"]) / resolution_m)),
    )
    elevations, source_tile_ids, source_fingerprint = _load_dtm_grid_image(
        coverage,
        bbox_twd97=bbox_twd97,
        resolution_m=resolution_m,
        width=width,
        height=height,
        terrain_sha256=_sha256_file(terrain_path),
        coverage_sha256=_sha256_file(coverage_path),
        zoom=zoom,
        tile_size=tile_size,
    )
    source_manifest = {
        "artifact_kind": "admin_local_raster_source_manifest",
        "source_kind": "local_geotiff",
        "project_id": resolved_project_id,
        "layer_id": "navigation_terrain_dem",
        "georeference": {
            "status": "geotiff_wgs84",
            "bbox_wgs84": bbox_wgs84,
        },
        "image": {"width_px": width, "height_px": height},
    }

    rendered_tiles: dict[tuple[int, int], bytes] = {}
    for x, y in _slippy_tile_coordinates(bbox_wgs84, zoom):
        body = _render_terrain_rgb_tile(
            elevations,
            source_manifest,
            zoom,
            x,
            y,
            tile_size=tile_size,
        )
        if _png_is_fully_supported(body):
            rendered_tiles[(x, y)] = body

    tile_block = largest_complete_tile_block(rendered_tiles)
    if tile_block is None:
        raise TerrainDemPreparationError(
            "no fully-supported terrain DEM tiles are available at the requested zoom"
        )
    selected_tiles = {
        (x, y): rendered_tiles[(x, y)]
        for y in range(tile_block["y_min"], tile_block["y_max"] + 1)
        for x in range(tile_block["x_min"], tile_block["x_max"] + 1)
    }
    artifact_version = source_fingerprint[:16]
    tiles_ref = f"outputs/navigation/terrain_rgb/{artifact_version}/tiles"
    tile_records: list[dict[str, Any]] = []
    for (x, y), body in sorted(selected_tiles.items(), key=lambda item: (item[0][1], item[0][0])):
        relative = f"{tiles_ref}/{zoom}/{x}/{y}.png"
        output_path = _project_path(root, relative)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(body)
        tile_records.append(
            {
                "z": zoom,
                "x": x,
                "y": y,
                "source_ref": relative,
                "sha256": hashlib.sha256(body).hexdigest(),
            }
        )

    block_bounds = _tile_block_bounds(tile_block, zoom)
    timestamp = prepared_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00",
        "Z",
    )
    manifest_ref = DEFAULT_TERRAIN_DEM_MANIFEST_REF
    manifest = {
        "schema_version": TERRAIN_DEM_SCHEMA_VERSION,
        "artifact_kind": "navigation_terrain_raster_dem_tiles",
        "status": "ready",
        "project_id": resolved_project_id,
        "prepared_at": timestamp,
        "encoding": "mapbox",
        "resampling": TERRAIN_DEM_RESAMPLING,
        "visual_interpolation": "bilinear",
        "interpolation_domain": "elevation_m_before_terrain_rgb_encoding",
        "adds_source_resolution": False,
        "tile_size": tile_size,
        "minzoom": zoom,
        "maxzoom": zoom,
        "tile_block": tile_block,
        "bounds_wgs84": block_bounds,
        "source_bbox_wgs84": bbox_wgs84,
        "source_bbox_twd97": bbox_twd97,
        "source_cell_resolution_m": resolution_m,
        "source_dtm_tile_count": len(source_tile_ids),
        "source_dtm_tile_ids": source_tile_ids,
        "source_supported_cell_count": int(_finite_cell_count(elevations)),
        "complete_candidate_tile_count": len(rendered_tiles),
        "tile_count": len(tile_records),
        "tiles_ref": tiles_ref,
        "tiles": tile_records,
        "tile_url_template": (
            f"/admin/pretrip/projects/{resolved_project_id}/terrain-dem/"
            "{z}/{x}/{y}.png"
        ),
        "manifest_ref": manifest_ref,
        "source_refs": [terrain_ref, coverage_ref],
        "source_fingerprint": source_fingerprint,
        "coverage_strategy": "largest_complete_slippy_tile_block",
        "nodata_policy": "exclude_incomplete_tiles",
        "alpha_nodata_supported": False,
        "limitations": [
            "Only a fully source-supported rectangular tile block is published.",
            "Areas outside the published block remain unavailable; no elevation is synthesized.",
            "The 20 m source grid is presentation evidence and is not increased in resolution.",
            "Bilinear interpolation smooths rendered elevation between supported source cells only.",
            "Visual interpolation does not add source resolution or create new spatial evidence.",
        ],
        "boundary": {
            "candidate_only": True,
            "human_review_required": True,
            "runtime_safety_truth": False,
            "safe_or_walkable": "not_determined",
            "unsupported_cells_encoded_as_terrain": False,
            "visual_interpolation_only": True,
            "raw_dem_embedded": False,
            "phase1_runtime_mutation_allowed": False,
        },
    }
    _atomic_write_json(_project_path(root, manifest_ref), manifest)
    updated_project = {
        **project,
        "navigation_terrain_dem_manifest_ref": manifest_ref,
        "navigation_terrain_dem_status": "ready",
        "navigation_terrain_dem_source_fingerprint": source_fingerprint,
    }
    _atomic_write_json(project_path, updated_project)
    return manifest


def load_navigation_terrain_dem_manifest(
    project_root: Path,
    project: Mapping[str, Any],
) -> dict[str, Any]:
    """Load and validate the prepared read-only raster-DEM manifest."""

    root = Path(project_root).expanduser().resolve()
    ref = project.get("navigation_terrain_dem_manifest_ref")
    if not isinstance(ref, str) or not ref.strip():
        raise FileNotFoundError("navigation terrain DEM is not prepared")
    manifest = _read_json_object(_project_path(root, ref.strip()), "terrain DEM manifest")
    if manifest.get("schema_version") != TERRAIN_DEM_SCHEMA_VERSION:
        raise TerrainDemPreparationError("unsupported terrain DEM manifest schema")
    if manifest.get("artifact_kind") != "navigation_terrain_raster_dem_tiles":
        raise TerrainDemPreparationError("invalid terrain DEM artifact kind")
    if manifest.get("status") != "ready":
        raise FileNotFoundError("navigation terrain DEM is not ready")
    if manifest.get("project_id") != project.get("project_id"):
        raise TerrainDemPreparationError("terrain DEM project_id mismatch")
    if manifest.get("encoding") != "mapbox":
        raise TerrainDemPreparationError("terrain DEM must use mapbox encoding")
    if manifest.get("resampling") not in {
        TERRAIN_DEM_RESAMPLING,
        LEGACY_TERRAIN_DEM_RESAMPLING,
    }:
        raise TerrainDemPreparationError(
            "terrain DEM uses an unsupported elevation resampling contract"
        )
    if manifest.get("resampling") == TERRAIN_DEM_RESAMPLING:
        if manifest.get("visual_interpolation") != "bilinear":
            raise TerrainDemPreparationError(
                "terrain DEM bilinear resampling must disclose visual interpolation"
            )
        if manifest.get("adds_source_resolution") is not False:
            raise TerrainDemPreparationError(
                "terrain DEM visual interpolation cannot add source resolution"
            )
    if manifest.get("nodata_policy") != "exclude_incomplete_tiles":
        raise TerrainDemPreparationError("terrain DEM nodata policy is unsafe")
    return manifest


def navigation_terrain_dem_tile(
    project_root: Path,
    project: Mapping[str, Any],
    *,
    z: int,
    x: int,
    y: int,
) -> tuple[dict[str, Any], Path, str]:
    """Resolve one allowlisted prepared tile without generating runtime data."""

    manifest = load_navigation_terrain_dem_manifest(project_root, project)
    if int(manifest.get("minzoom", -1)) != int(z) or int(manifest.get("maxzoom", -1)) != int(z):
        raise FileNotFoundError("terrain DEM tile zoom is unavailable")
    block = manifest.get("tile_block")
    if not isinstance(block, Mapping) or not (
        int(block.get("x_min", -1)) <= int(x) <= int(block.get("x_max", -1))
        and int(block.get("y_min", -1)) <= int(y) <= int(block.get("y_max", -1))
    ):
        raise FileNotFoundError("terrain DEM tile is outside prepared coverage")
    record = next(
        (
            item
            for item in manifest.get("tiles", [])
            if isinstance(item, Mapping)
            and int(item.get("z", -1)) == int(z)
            and int(item.get("x", -1)) == int(x)
            and int(item.get("y", -1)) == int(y)
        ),
        None,
    )
    if not isinstance(record, Mapping):
        raise FileNotFoundError("terrain DEM tile is not declared")
    source_ref = record.get("source_ref")
    if not isinstance(source_ref, str) or not source_ref:
        raise TerrainDemPreparationError("terrain DEM tile has no source_ref")
    path = _project_path(Path(project_root).resolve(), source_ref)
    if not path.is_file():
        raise FileNotFoundError("terrain DEM tile artifact is missing")
    expected_sha = str(record.get("sha256") or "")
    actual_sha = _sha256_file(path)
    if not expected_sha or actual_sha != expected_sha:
        raise TerrainDemPreparationError("terrain DEM tile hash mismatch")
    return manifest, path, actual_sha


def _load_dtm_grid_image(
    coverage: Mapping[str, Any],
    *,
    bbox_twd97: Mapping[str, float],
    resolution_m: float,
    width: int,
    height: int,
    terrain_sha256: str,
    coverage_sha256: str,
    zoom: int,
    tile_size: int,
) -> tuple[Any, list[str], str]:
    try:
        import numpy as np
    except Exception as exc:  # pragma: no cover - environment guard.
        raise RuntimeError("NumPy is required to prepare terrain DEM tiles") from exc

    source_dirs_raw = coverage.get("source_dirs")
    if not isinstance(source_dirs_raw, list):
        raise TerrainDemPreparationError("DTM coverage source_dirs must be a list")
    source_dirs = [
        Path(value).expanduser().resolve()
        for value in source_dirs_raw
        if isinstance(value, str) and value.strip()
    ]
    if not source_dirs:
        raise TerrainDemPreparationError("DTM coverage has no source directories")
    raw_tiles = coverage.get("candidate_tiles")
    if not isinstance(raw_tiles, list):
        raise TerrainDemPreparationError("DTM coverage candidate_tiles must be a list")

    elevations = np.full((height, width), np.nan, dtype=np.float32)
    tile_ids: list[str] = []
    fingerprint_parts = [
        terrain_sha256,
        coverage_sha256,
        str(zoom),
        str(tile_size),
        TERRAIN_DEM_RESAMPLING,
    ]
    for raw_tile in raw_tiles:
        if not isinstance(raw_tile, Mapping):
            continue
        tile_bbox = _normalize_bbox(
            raw_tile.get("bbox_twd97"),
            keys=("min_x", "min_y", "max_x", "max_y"),
        )
        if tile_bbox is None or not _bbox_intersects(bbox_twd97, tile_bbox):
            continue
        grid_uri = raw_tile.get("grid_uri")
        if not isinstance(grid_uri, str) or not grid_uri.strip():
            raise TerrainDemPreparationError("DTM tile has no grid_uri")
        grid_path = Path(grid_uri).expanduser().resolve()
        if grid_path.suffix.lower() != ".grd":
            raise TerrainDemPreparationError("DTM source must use .grd files")
        if not any(_is_relative_to(grid_path, directory) for directory in source_dirs):
            raise TerrainDemPreparationError("DTM source is outside declared directories")
        if not grid_path.is_file():
            raise TerrainDemPreparationError("DTM source file is missing")
        try:
            values = np.atleast_2d(np.loadtxt(grid_path, dtype=np.float32))
        except (OSError, ValueError) as exc:
            raise TerrainDemPreparationError("DTM source could not be decoded") from exc
        if values.shape[1] < 3:
            raise TerrainDemPreparationError("DTM source must contain x y elevation")
        finite = np.isfinite(values[:, 0]) & np.isfinite(values[:, 1]) & np.isfinite(values[:, 2])
        values = values[finite]
        columns = np.floor((values[:, 0] - bbox_twd97["min_x"]) / resolution_m).astype(int)
        rows = np.floor((bbox_twd97["max_y"] - values[:, 1]) / resolution_m).astype(int)
        inside = (columns >= 0) & (columns < width) & (rows >= 0) & (rows < height)
        elevations[rows[inside], columns[inside]] = values[inside, 2]
        tile_id = str(raw_tile.get("tile_id") or grid_path.stem)
        tile_ids.append(tile_id)
        stat = grid_path.stat()
        fingerprint_parts.append(f"{tile_id}:{stat.st_size}:{stat.st_mtime_ns}")

    if not tile_ids or not bool(np.isfinite(elevations).any()):
        raise TerrainDemPreparationError("DTM sources contain no supported cells")
    fingerprint = hashlib.sha256("\n".join(fingerprint_parts).encode("utf-8")).hexdigest()
    return elevations, sorted(tile_ids), fingerprint


def _terrain_rgb_image(elevations: Any) -> Any:
    try:
        import numpy as np
        from PIL import Image
    except Exception as exc:  # pragma: no cover - environment guard.
        raise RuntimeError("NumPy and Pillow are required for terrain RGB") from exc

    supported = np.isfinite(elevations)
    encoded = np.zeros(elevations.shape, dtype=np.uint32)
    encoded[supported] = np.clip(
        np.rint((elevations[supported] + 10_000.0) * 10.0),
        0,
        16_777_215,
    ).astype(np.uint32)
    rgba = np.zeros((*elevations.shape, 4), dtype=np.uint8)
    rgba[..., 0] = (encoded // 65_536).astype(np.uint8)
    rgba[..., 1] = ((encoded // 256) % 256).astype(np.uint8)
    rgba[..., 2] = (encoded % 256).astype(np.uint8)
    rgba[..., 3] = np.where(supported, 255, 0).astype(np.uint8)
    return Image.fromarray(rgba, mode="RGBA")


def _render_terrain_rgb_tile(
    elevations: Any,
    source_manifest: Mapping[str, Any],
    z: int,
    x: int,
    y: int,
    *,
    tile_size: int,
) -> bytes:
    """Interpolate scalar elevation before Terrain RGB encoding.

    All four contributing source cells must be finite. This smooths the
    presentation mesh without bridging nodata or claiming added resolution.
    """

    try:
        import numpy as np
    except Exception as exc:  # pragma: no cover - environment guard.
        raise RuntimeError("NumPy is required to render terrain DEM tiles") from exc

    source_bbox = _normalize_bbox(
        source_manifest.get("georeference", {}).get("bbox_wgs84"),
        keys=("west", "south", "east", "north"),
    )
    if source_bbox is None:
        raise TerrainDemPreparationError("terrain DEM source has no WGS84 bounds")
    source = np.asarray(elevations, dtype=np.float64)
    if source.ndim != 2 or source.shape[0] < 1 or source.shape[1] < 1:
        raise TerrainDemPreparationError("terrain DEM source grid is invalid")

    tile_bbox = tile_bounds_wgs84(z, x, y)
    pixel_columns = np.arange(tile_size, dtype=np.float64) + 0.5
    pixel_rows = np.arange(tile_size, dtype=np.float64) + 0.5
    longitudes = (
        tile_bbox["west"]
        + pixel_columns / tile_size * (tile_bbox["east"] - tile_bbox["west"])
    )
    global_y = (float(y) + pixel_rows / tile_size) / float(2**z)
    latitudes = np.degrees(np.arctan(np.sinh(np.pi * (1.0 - 2.0 * global_y))))

    source_x = (
        (longitudes - source_bbox["west"])
        / (source_bbox["east"] - source_bbox["west"])
        * max(0, source.shape[1] - 1)
    )
    source_y = (
        (source_bbox["north"] - latitudes)
        / (source_bbox["north"] - source_bbox["south"])
        * max(0, source.shape[0] - 1)
    )
    inside_x = (longitudes >= source_bbox["west"]) & (
        longitudes <= source_bbox["east"]
    )
    inside_y = (latitudes >= source_bbox["south"]) & (
        latitudes <= source_bbox["north"]
    )
    source_x = np.clip(source_x, 0, source.shape[1] - 1)
    source_y = np.clip(source_y, 0, source.shape[0] - 1)
    x0 = np.floor(source_x).astype(int)
    y0 = np.floor(source_y).astype(int)
    x1 = np.minimum(x0 + 1, source.shape[1] - 1)
    y1 = np.minimum(y0 + 1, source.shape[0] - 1)
    x_weight = source_x - x0
    y_weight = source_y - y0

    top_left = source[y0[:, None], x0[None, :]]
    top_right = source[y0[:, None], x1[None, :]]
    bottom_left = source[y1[:, None], x0[None, :]]
    bottom_right = source[y1[:, None], x1[None, :]]
    supported = (
        inside_y[:, None]
        & inside_x[None, :]
        & np.isfinite(top_left)
        & np.isfinite(top_right)
        & np.isfinite(bottom_left)
        & np.isfinite(bottom_right)
    )
    top = top_left * (1.0 - x_weight[None, :]) + top_right * x_weight[None, :]
    bottom = (
        bottom_left * (1.0 - x_weight[None, :])
        + bottom_right * x_weight[None, :]
    )
    interpolated = top * (1.0 - y_weight[:, None]) + bottom * y_weight[:, None]
    interpolated = np.where(supported, interpolated, np.nan)

    image = _terrain_rgb_image(interpolated)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _png_is_fully_supported(body: bytes) -> bool:
    try:
        from PIL import Image
    except Exception as exc:  # pragma: no cover - environment guard.
        raise RuntimeError("Pillow is required to inspect terrain tiles") from exc
    with Image.open(io.BytesIO(body)) as image:
        minimum, maximum = image.convert("RGBA").getchannel("A").getextrema()
    return minimum == 255 and maximum == 255


def _slippy_tile_coordinates(
    bbox: Mapping[str, float],
    zoom: int,
) -> list[tuple[int, int]]:
    n = 2**zoom
    west = _lon_to_tile_float(float(bbox["west"]), zoom)
    east = _lon_to_tile_float(float(bbox["east"]), zoom)
    north = _lat_to_tile_float(float(bbox["north"]), zoom)
    south = _lat_to_tile_float(float(bbox["south"]), zoom)
    x_min = max(0, min(n - 1, int(math.floor(west + 1e-10))))
    x_max = max(0, min(n - 1, int(math.ceil(east - 1e-10) - 1)))
    y_min = max(0, min(n - 1, int(math.floor(north + 1e-10))))
    y_max = max(0, min(n - 1, int(math.ceil(south - 1e-10) - 1)))
    return [
        (x, y)
        for y in range(y_min, y_max + 1)
        for x in range(x_min, x_max + 1)
    ]


def _lon_to_tile_float(lon: float, zoom: int) -> float:
    return (lon + 180.0) / 360.0 * 2**zoom


def _lat_to_tile_float(lat: float, zoom: int) -> float:
    limited = max(-85.05112878, min(85.05112878, lat))
    radians = math.radians(limited)
    return (
        1.0 - math.asinh(math.tan(radians)) / math.pi
    ) / 2.0 * 2**zoom


def _tile_block_bounds(block: Mapping[str, int], zoom: int) -> dict[str, float]:
    north_west = tile_bounds_wgs84(zoom, int(block["x_min"]), int(block["y_min"]))
    south_east = tile_bounds_wgs84(zoom, int(block["x_max"]), int(block["y_max"]))
    return {
        "west": north_west["west"],
        "south": south_east["south"],
        "east": south_east["east"],
        "north": north_west["north"],
    }


def _finite_cell_count(elevations: Any) -> int:
    try:
        import numpy as np
    except Exception as exc:  # pragma: no cover - environment guard.
        raise RuntimeError("NumPy is required to count terrain cells") from exc
    return int(np.isfinite(elevations).sum())


def _required_project_ref(project: Mapping[str, Any], key: str) -> str:
    value = project.get(key)
    if not isinstance(value, str) or not value.strip():
        raise TerrainDemPreparationError(f"project has no {key}")
    return value.strip()


def _project_path(root: Path, ref: str) -> Path:
    path = (root / ref).resolve()
    if not _is_relative_to(path, root):
        raise TerrainDemPreparationError("unsafe project artifact reference")
    return path


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except (OSError, json.JSONDecodeError) as exc:
        raise TerrainDemPreparationError(f"invalid {label}") from exc
    if not isinstance(value, dict):
        raise TerrainDemPreparationError(f"{label} must be an object")
    return value


def _normalize_bbox(
    value: Any,
    *,
    keys: tuple[str, str, str, str],
) -> dict[str, float] | None:
    if not isinstance(value, Mapping):
        return None
    normalized: dict[str, float] = {}
    for key in keys:
        try:
            number = float(value.get(key))
        except (TypeError, ValueError):
            return None
        if not math.isfinite(number):
            return None
        normalized[key] = number
    if normalized[keys[0]] >= normalized[keys[2]]:
        return None
    if normalized[keys[1]] >= normalized[keys[3]]:
        return None
    return normalized


def _positive_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def _bbox_intersects(left: Mapping[str, float], right: Mapping[str, float]) -> bool:
    return not (
        left["max_x"] < right["min_x"]
        or left["min_x"] > right["max_x"]
        or left["max_y"] < right["min_y"]
        or left["min_y"] > right["max_y"]
    )


def _is_relative_to(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
    except ValueError:
        return False
    return True


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare complete MapLibre Terrain RGB tiles for Scout Navigation review."
    )
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--zoom", type=int, default=DEFAULT_TERRAIN_DEM_ZOOM)
    parser.add_argument("--tile-size", type=int, default=DEFAULT_TERRAIN_DEM_TILE_SIZE)
    parser.add_argument("--prepared-at")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    result = prepare_navigation_terrain_dem_tiles(
        args.workspace_root / args.project_id,
        project_id=args.project_id,
        zoom=args.zoom,
        tile_size=args.tile_size,
        prepared_at=args.prepared_at,
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "project_id": result["project_id"],
                "manifest_ref": result["manifest_ref"],
                "tile_count": result["tile_count"],
                "bounds_wgs84": result["bounds_wgs84"],
                "candidate_only": result["boundary"]["candidate_only"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint.
    raise SystemExit(main())
