"""Small, in-memory display mesh from Scout's prepared Terrain RGB.

This is not a Cesium terrain provider or a new DEM product. Pixels are sampled
only for a visual mesh, after the existing tile/hash/coverage validation. The
same prepared pixels can be sampled separately without the mesh decimation.
"""

from __future__ import annotations

import io
import math

from scout_gpx_3d import Gpx3DWorkspace

EARTH_CIRCUMFERENCE_M = 2 * math.pi * 6378137


def decoded_tile(workspace: Gpx3DWorkspace, z: int, x: int, y: int):
    import numpy as np
    from PIL import Image

    body, sha = workspace.tile(z, x, y)
    with Image.open(io.BytesIO(body)) as image:
        rgba = np.array(image.convert("RGBA"))
    if not np.all(rgba[:, :, 3] == 255):
        raise ValueError("Terrain tile has unsupported pixels; no zero-filled mesh is allowed")
    rgb = rgba[:, :, :3].astype(np.int32)
    heights = -10000 + (rgb[:, :, 0] * 65536 + rgb[:, :, 1] * 256 + rgb[:, :, 2]) * 0.1
    return heights, sha


def build_display_mesh(workspace: Gpx3DWorkspace, stride: int = 16) -> dict:
    import numpy as np

    manifest = workspace.terrain()
    if manifest["status"] != "ready":
        return manifest
    block = manifest["tile_block"]
    tile_size = manifest["tile_size"]
    if stride < 1 or tile_size % stride:
        raise ValueError("Mesh stride must divide prepared tile size")
    per_tile = tile_size // stride
    width = (block["x_max"] - block["x_min"] + 1) * per_tile
    height = (block["y_max"] - block["y_min"] + 1) * per_tile
    elevations = np.full((height, width), np.nan)
    for tile in manifest["tiles"]:
        values, _ = decoded_tile(workspace, tile["z"], tile["x"], tile["y"])
        if values.shape != (tile_size, tile_size):
            raise ValueError("Terrain image size differs from manifest")
        x, y = (tile["x"] - block["x_min"]) * per_tile, (tile["y"] - block["y_min"]) * per_tile
        elevations[y:y + per_tile, x:x + per_tile] = values[::stride, ::stride]
    if not np.all(np.isfinite(elevations)):
        raise ValueError("Prepared tile block has missing support; refusing to fill holes")
    pixel_m = EARTH_CIRCUMFERENCE_M / (2 ** manifest["minzoom"] * tile_size)
    return {
        "status": "ready",
        "source": manifest,
        "artifact_kind": "bounded_dem_visualization_mesh",
        "horizontal_crs": "EPSG:3857; local display scaled by cos(route center latitude)",
        "vertical_datum": manifest["vertical_datum"],
        "width": width, "height": height,
        "x0": (block["x_min"] * tile_size + 0.5) * pixel_m - EARTH_CIRCUMFERENCE_M / 2,
        "y0": EARTH_CIRCUMFERENCE_M / 2 - (block["y_min"] * tile_size + 0.5) * pixel_m,
        "step_m": pixel_m * stride,
        "elevations": np.round(elevations.ravel(), 1).tolist(),
        "minimum_elevation_m": float(elevations.min()),
        "maximum_elevation_m": float(elevations.max()),
        "sampling": {"method": "nearest_prepared_terrain_rgb_pixel", "stride_pixels": stride,
                     "source_cell_resolution_m": manifest["source_cell_resolution_m"],
                     "adds_source_resolution": False, "visualization_only": True,
                     "gap_policy": "no_faces_outside_supported_rectangle",
                     "vertical_exaggeration": 1},
        "authority": manifest["authority"],
    }


def sample_prepared_elevation(workspace: Gpx3DWorkspace, lon: float, lat: float) -> dict:
    if not math.isfinite(lon) or not math.isfinite(lat) or not (-180 <= lon <= 180 and -85.051129 < lat < 85.051129):
        raise ValueError("Invalid longitude / latitude")
    manifest = workspace.terrain()
    if manifest["status"] != "ready":
        return {"status": "unavailable", "elevation_m": None, "source_ref": None}
    z = manifest["minzoom"]
    scale = 2 ** z
    tx = (lon + 180) / 360 * scale
    ty = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * scale
    x, y = math.floor(tx), math.floor(ty)
    block = manifest["tile_block"]
    if not (block["x_min"] <= x <= block["x_max"] and block["y_min"] <= y <= block["y_max"]):
        return {"status": "outside_coverage", "elevation_m": None, "source_ref": None}
    values, sha = decoded_tile(workspace, z, x, y)
    pixel_x = min(values.shape[1] - 1, math.floor((tx - x) * values.shape[1]))
    pixel_y = min(values.shape[0] - 1, math.floor((ty - y) * values.shape[0]))
    record = next(t for t in manifest["tiles"] if (t["x"], t["y"], t["z"]) == (x, y, z))
    return {"status": "ready", "elevation_m": round(float(values[pixel_y, pixel_x]), 1),
            "source_ref": record["source_ref"], "sha256": sha,
            "method": "nearest pixel in prepared Terrain RGB; source bilinear resampling and 0.1 m encoding",
            "vertical_datum": manifest["vertical_datum"]}
