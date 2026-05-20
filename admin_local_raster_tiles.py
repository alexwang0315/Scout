from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from admin_basemap_tiles import MAX_OSM_ZOOM, MIN_OSM_ZOOM, normalize_bbox_wgs84
from admin_tile_cache_builder import DEFAULT_TILE_CACHE_CAPACITY_BYTES
from admin_tile_proxy import validate_osm_tile_coords


DEFAULT_RASTER_TILE_CACHE_ROOT = Path("~/.cache/scout-fusion/raster-tiles")
LOCAL_RASTER_TILE_URL_TEMPLATE = (
    "/admin/tiles/imagery/{project_id}/{layer_id}/{z}/{x}/{y}.png"
)
DEFAULT_RASTER_TILE_MIN_ZOOM = 5
DEFAULT_RASTER_TILE_MAX_ZOOM = 20
DEFAULT_RASTER_TILE_SIZE = 256
DEFAULT_ESTIMATED_RASTER_TILE_BYTES = 64 * 1024
WEB_MERCATOR_MAX_LAT = 85.05112878


@dataclass(frozen=True)
class AdminRasterTilePayload:
    body: bytes
    media_type: str
    source: str
    cache_path: Path
    body_sha256: str

    def headers(self) -> dict[str, str]:
        return {
            "Cache-Control": "public, max-age=86400",
            "X-Scout-Tile-Source": self.source,
            "X-Scout-Tile-Hash": self.body_sha256,
        }


def build_raster_tile_pyramid_plan(
    source_manifest: Mapping[str, Any],
    *,
    cache_root: Path | str = DEFAULT_RASTER_TILE_CACHE_ROOT,
    min_zoom: int = DEFAULT_RASTER_TILE_MIN_ZOOM,
    max_zoom: int = DEFAULT_RASTER_TILE_MAX_ZOOM,
    capacity_limit_bytes: int = DEFAULT_TILE_CACHE_CAPACITY_BYTES,
    estimated_tile_bytes: int = DEFAULT_ESTIMATED_RASTER_TILE_BYTES,
    tile_size: int = DEFAULT_RASTER_TILE_SIZE,
) -> dict[str, Any]:
    _validate_raster_source_manifest(source_manifest)
    if min_zoom < MIN_OSM_ZOOM or max_zoom > MAX_OSM_ZOOM or min_zoom > max_zoom:
        raise ValueError(f"zoom range must be between {MIN_OSM_ZOOM} and {MAX_OSM_ZOOM}")
    if capacity_limit_bytes <= 0:
        raise ValueError("capacity_limit_bytes must be positive")
    if estimated_tile_bytes <= 0:
        raise ValueError("estimated_tile_bytes must be positive")
    if tile_size <= 0:
        raise ValueError("tile_size must be positive")

    georef = source_manifest["georeference"]
    bbox = normalize_bbox_wgs84(georef["bbox_wgs84"])
    zoom_ranges = [
        _zoom_range(bbox, zoom=z, estimated_tile_bytes=estimated_tile_bytes)
        for z in range(min_zoom, max_zoom + 1)
    ]
    total_tile_count = sum(int(item["tile_count"]) for item in zoom_ranges)
    estimated_total_bytes = total_tile_count * estimated_tile_bytes
    within_capacity = estimated_total_bytes <= capacity_limit_bytes
    project_id = _safe_identifier(source_manifest.get("project_id"), "project_id")
    layer_id = _safe_identifier(source_manifest.get("layer_id"), "layer_id")

    return {
        "artifact_kind": "admin_local_raster_tile_pyramid_plan",
        "status": "planned_capacity_ok" if within_capacity else "blocked_capacity_limit",
        "project_id": project_id,
        "layer_id": layer_id,
        "source_manifest_id": source_manifest.get("manifest_id"),
        "source_kind": source_manifest.get("source_kind"),
        "source_geotiff_path": source_manifest.get("source_file", {}).get("path"),
        "source_sha256": source_manifest.get("source_file", {}).get("sha256"),
        "cache_root": str(Path(cache_root).expanduser()),
        "runtime_tile_url_template": LOCAL_RASTER_TILE_URL_TEMPLATE,
        "cache_policy": "local_file_cache_then_transparent_fallback",
        "bbox_wgs84": bbox,
        "min_zoom": min_zoom,
        "max_zoom": max_zoom,
        "zoom_range": f"{min_zoom}-{max_zoom}",
        "zoom_ranges": zoom_ranges,
        "tile_size": tile_size,
        "capacity_limit_bytes": capacity_limit_bytes,
        "capacity_limit_gib": round(capacity_limit_bytes / 1024 / 1024 / 1024, 3),
        "estimated_tile_bytes": estimated_tile_bytes,
        "estimated_total_bytes": estimated_total_bytes,
        "estimated_total_gib": round(estimated_total_bytes / 1024 / 1024 / 1024, 3),
        "total_tile_count": total_tile_count,
        "within_capacity_limit": within_capacity,
        "external_network_required": False,
        "downloads_tiles_into_repo": False,
        "repo_fixture_write_allowed": False,
        "raw_raster_committed_to_repo_allowed": False,
        "notes_zh": [
            "這是本機 GeoTIFF 轉 PNG tile cache 的計畫，不會下載外部圖磚。",
            "輸出的 PNG tiles 應放在 ~/.cache/scout-fusion/raster-tiles 或 Scout 硬體對應 cache，不放入 repo fixtures。",
        ],
    }


def cut_raster_tile_pyramid(
    source_manifest: Mapping[str, Any],
    plan: Mapping[str, Any],
    *,
    dry_run: bool = True,
    max_tiles: int | None = None,
) -> dict[str, Any]:
    _validate_raster_source_manifest(source_manifest)
    if plan.get("within_capacity_limit") is not True:
        raise ValueError("raster tile plan exceeds capacity limit")
    if plan.get("source_geotiff_path") != source_manifest.get("source_file", {}).get("path"):
        raise ValueError("plan source_geotiff_path does not match source manifest")

    tiles_seen = 0
    tiles_written = 0
    tiles_skipped_existing = 0
    bytes_written = 0
    started_at = time.time()
    cache_root = Path(str(plan["cache_root"])).expanduser()
    capacity_limit = int(plan["capacity_limit_bytes"])

    image = None
    try:
        if not dry_run:
            from PIL import Image

            image = Image.open(str(source_manifest["source_file"]["path"])).convert("RGBA")

        for tile in iter_raster_plan_tiles(plan):
            if max_tiles is not None and tiles_seen >= max_tiles:
                break
            tiles_seen += 1
            path = raster_tile_cache_path(
                str(plan["project_id"]),
                str(plan["layer_id"]),
                tile["z"],
                tile["x"],
                tile["y"],
                cache_root=cache_root,
            )
            if path.exists():
                tiles_skipped_existing += 1
                continue
            if dry_run:
                continue
            assert image is not None
            body = render_raster_tile_png(
                image,
                source_manifest,
                tile["z"],
                tile["x"],
                tile["y"],
                tile_size=int(plan["tile_size"]),
            )
            if bytes_written + len(body) > capacity_limit:
                return _cut_summary(
                    "stopped_capacity_limit",
                    plan=plan,
                    dry_run=dry_run,
                    tiles_seen=tiles_seen,
                    tiles_written=tiles_written,
                    tiles_skipped_existing=tiles_skipped_existing,
                    bytes_written=bytes_written,
                    started_at=started_at,
                )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
            tiles_written += 1
            bytes_written += len(body)
    finally:
        if image is not None:
            image.close()

    return _cut_summary(
        "dry_run_ready" if dry_run else "seed_complete",
        plan=plan,
        dry_run=dry_run,
        tiles_seen=tiles_seen,
        tiles_written=tiles_written,
        tiles_skipped_existing=tiles_skipped_existing,
        bytes_written=bytes_written,
        started_at=started_at,
    )


def render_raster_tile_png(
    image: Any,
    source_manifest: Mapping[str, Any],
    z: int,
    x: int,
    y: int,
    *,
    tile_size: int = DEFAULT_RASTER_TILE_SIZE,
) -> bytes:
    _validate_raster_source_manifest(source_manifest)
    validate_osm_tile_coords(z, x, y)
    if tile_size <= 0:
        raise ValueError("tile_size must be positive")

    try:
        from PIL import Image
    except Exception as exc:  # pragma: no cover - environment guard
        raise RuntimeError("Pillow is required to render raster tiles") from exc

    raster_bbox = normalize_bbox_wgs84(source_manifest["georeference"]["bbox_wgs84"])
    tile_bbox = tile_bounds_wgs84(z, x, y)
    intersection = _bbox_intersection(raster_bbox, tile_bbox)
    tile_image = Image.new("RGBA", (tile_size, tile_size), (0, 0, 0, 0))
    if intersection is None:
        return _png_bytes(tile_image)

    src_box = _source_crop_box(
        intersection,
        raster_bbox=raster_bbox,
        image_width=int(source_manifest["image"]["width_px"]),
        image_height=int(source_manifest["image"]["height_px"]),
    )
    dst_box = _tile_paste_box(intersection, tile_bbox=tile_bbox, z=z, y=y, tile_size=tile_size)
    if src_box is None or dst_box is None:
        return _png_bytes(tile_image)

    crop = image.crop(src_box)
    resized = crop.resize((dst_box[2] - dst_box[0], dst_box[3] - dst_box[1]))
    tile_image.paste(resized, (dst_box[0], dst_box[1]))
    return _png_bytes(tile_image)


def iter_raster_plan_tiles(plan: Mapping[str, Any]) -> list[dict[str, int]]:
    tiles: list[dict[str, int]] = []
    for zoom_range in plan.get("zoom_ranges", []):
        z = int(zoom_range["z"])
        for y in range(int(zoom_range["y_min"]), int(zoom_range["y_max"]) + 1):
            for x in range(int(zoom_range["x_min"]), int(zoom_range["x_max"]) + 1):
                tiles.append({"z": z, "x": x, "y": y})
    return tiles


def build_local_raster_tile_proxy_contract(
    *,
    cache_root: Path | str = DEFAULT_RASTER_TILE_CACHE_ROOT,
    fallback_enabled: bool = True,
) -> dict[str, Any]:
    root = Path(cache_root).expanduser()
    return {
        "artifact_kind": "admin_local_raster_tile_proxy_contract",
        "status": "local_proxy_ready",
        "url_template": LOCAL_RASTER_TILE_URL_TEMPLATE,
        "cache_root": str(root),
        "cache_policy": "local_file_cache_then_transparent_fallback",
        "fallback_enabled": fallback_enabled,
        "external_network_fetch_allowed": False,
        "downloads_tiles_into_repo": False,
        "max_zoom": MAX_OSM_ZOOM,
        "notes_zh": [
            "這個 proxy 只服務已存在的本機 raster PNG tile。",
            "缺 tile 時可回傳透明 fallback，避免瀏覽器畫面出現破圖。",
        ],
    }


def raster_tile_cache_path(
    project_id: str,
    layer_id: str,
    z: int | str,
    x: int | str,
    y: int | str,
    *,
    cache_root: Path | str = DEFAULT_RASTER_TILE_CACHE_ROOT,
) -> Path:
    safe_project = _safe_identifier(project_id, "project_id")
    safe_layer = _safe_identifier(layer_id, "layer_id")
    tile = validate_osm_tile_coords(z, x, y)
    return (
        Path(cache_root).expanduser()
        / safe_project
        / safe_layer
        / str(tile["z"])
        / str(tile["x"])
        / f"{tile['y']}.png"
    )


def load_or_build_raster_tile_payload(
    project_id: str,
    layer_id: str,
    z: int | str,
    x: int | str,
    y: int | str,
    *,
    cache_root: Path | str = DEFAULT_RASTER_TILE_CACHE_ROOT,
    fallback_enabled: bool = True,
) -> AdminRasterTilePayload:
    cache_path = raster_tile_cache_path(
        project_id,
        layer_id,
        z,
        x,
        y,
        cache_root=cache_root,
    )
    if cache_path.exists():
        body = cache_path.read_bytes()
        return AdminRasterTilePayload(
            body=body,
            media_type="image/png",
            source="local_cache",
            cache_path=cache_path,
            body_sha256=hashlib.sha256(body).hexdigest(),
        )
    if not fallback_enabled:
        raise FileNotFoundError(str(cache_path))

    tile = validate_osm_tile_coords(z, x, y)
    body = _transparent_svg_tile(tile["z"], tile["x"], tile["y"])
    return AdminRasterTilePayload(
        body=body,
        media_type="image/svg+xml",
        source="transparent_fallback",
        cache_path=cache_path,
        body_sha256=hashlib.sha256(body).hexdigest(),
    )


def tile_bounds_wgs84(z: int, x: int, y: int) -> dict[str, float]:
    validate_osm_tile_coords(z, x, y)
    n = 2**z
    west = x / n * 360.0 - 180.0
    east = (x + 1) / n * 360.0 - 180.0
    north = _tile_y_to_lat(y, z)
    south = _tile_y_to_lat(y + 1, z)
    return {"south": south, "west": west, "north": north, "east": east}


def write_raster_tile_plan_manifest(manifest: Mapping[str, Any], path: Path | str) -> Path:
    output_path = Path(path).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(dict(manifest), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path


def _validate_raster_source_manifest(source_manifest: Mapping[str, Any]) -> None:
    if source_manifest.get("artifact_kind") != "admin_local_raster_source_manifest":
        raise ValueError("source_manifest must be an admin_local_raster_source_manifest")
    if source_manifest.get("source_kind") != "local_geotiff":
        raise ValueError("source_manifest must reference a local_geotiff")
    if source_manifest.get("georeference", {}).get("status") != "geotiff_wgs84":
        raise ValueError("only WGS84 GeoTIFF raster sources are supported")
    if not source_manifest.get("georeference", {}).get("bbox_wgs84"):
        raise ValueError("source_manifest is missing bbox_wgs84")


def _zoom_range(
    bbox: Mapping[str, Any],
    *,
    zoom: int,
    estimated_tile_bytes: int,
) -> dict[str, Any]:
    x_min, x_max, y_min, y_max = _slippy_tile_range(bbox, zoom=zoom)
    tile_count = (x_max - x_min + 1) * (y_max - y_min + 1)
    return {
        "z": zoom,
        "x_min": x_min,
        "x_max": x_max,
        "y_min": y_min,
        "y_max": y_max,
        "tile_count": tile_count,
        "estimated_bytes": tile_count * estimated_tile_bytes,
    }


def _slippy_tile_range(
    bbox: Mapping[str, Any],
    *,
    zoom: int,
) -> tuple[int, int, int, int]:
    normalized = normalize_bbox_wgs84(bbox)
    west_x = _lon_to_tile_float(normalized["west"], zoom)
    east_x = _lon_to_tile_float(normalized["east"], zoom)
    north_y = _lat_to_tile_float(normalized["north"], zoom)
    south_y = _lat_to_tile_float(normalized["south"], zoom)
    return (
        _tile_index(west_x, zoom),
        _tile_index(east_x, zoom),
        _tile_index(north_y, zoom),
        _tile_index(south_y, zoom),
    )


def _bbox_intersection(
    left: Mapping[str, float],
    right: Mapping[str, float],
) -> dict[str, float] | None:
    south = max(float(left["south"]), float(right["south"]))
    west = max(float(left["west"]), float(right["west"]))
    north = min(float(left["north"]), float(right["north"]))
    east = min(float(left["east"]), float(right["east"]))
    if south >= north or west >= east:
        return None
    return {"south": south, "west": west, "north": north, "east": east}


def _source_crop_box(
    bbox: Mapping[str, float],
    *,
    raster_bbox: Mapping[str, float],
    image_width: int,
    image_height: int,
) -> tuple[int, int, int, int] | None:
    lon_span = float(raster_bbox["east"]) - float(raster_bbox["west"])
    lat_span = float(raster_bbox["north"]) - float(raster_bbox["south"])
    if lon_span <= 0 or lat_span <= 0:
        return None
    left = math.floor((float(bbox["west"]) - float(raster_bbox["west"])) / lon_span * image_width)
    right = math.ceil((float(bbox["east"]) - float(raster_bbox["west"])) / lon_span * image_width)
    top = math.floor((float(raster_bbox["north"]) - float(bbox["north"])) / lat_span * image_height)
    bottom = math.ceil((float(raster_bbox["north"]) - float(bbox["south"])) / lat_span * image_height)
    left = max(0, min(image_width, left))
    right = max(0, min(image_width, right))
    top = max(0, min(image_height, top))
    bottom = max(0, min(image_height, bottom))
    if left >= right or top >= bottom:
        return None
    return (left, top, right, bottom)


def _tile_paste_box(
    bbox: Mapping[str, float],
    *,
    tile_bbox: Mapping[str, float],
    z: int,
    y: int,
    tile_size: int,
) -> tuple[int, int, int, int] | None:
    lon_span = float(tile_bbox["east"]) - float(tile_bbox["west"])
    if lon_span <= 0:
        return None
    left = math.floor((float(bbox["west"]) - float(tile_bbox["west"])) / lon_span * tile_size)
    right = math.ceil((float(bbox["east"]) - float(tile_bbox["west"])) / lon_span * tile_size)
    top = math.floor((_lat_to_global_pixel_y(float(bbox["north"]), z) - y * tile_size))
    bottom = math.ceil((_lat_to_global_pixel_y(float(bbox["south"]), z) - y * tile_size))
    left = max(0, min(tile_size, left))
    right = max(0, min(tile_size, right))
    top = max(0, min(tile_size, top))
    bottom = max(0, min(tile_size, bottom))
    if left >= right or top >= bottom:
        return None
    return (left, top, right, bottom)


def _png_bytes(image: Any) -> bytes:
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _cut_summary(
    status: str,
    *,
    plan: Mapping[str, Any],
    dry_run: bool,
    tiles_seen: int,
    tiles_written: int,
    tiles_skipped_existing: int,
    bytes_written: int,
    started_at: float,
) -> dict[str, Any]:
    return {
        "status": status,
        "project_id": plan.get("project_id"),
        "layer_id": plan.get("layer_id"),
        "cache_root": plan.get("cache_root"),
        "dry_run": dry_run,
        "tiles_seen": tiles_seen,
        "tiles_written": tiles_written,
        "tiles_skipped_existing": tiles_skipped_existing,
        "bytes_written": bytes_written,
        "duration_seconds": round(time.time() - started_at, 3),
        "external_network_required": False,
        "downloads_tiles_into_repo": False,
    }


def _safe_identifier(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-")
    if any(char not in allowed for char in text) or ".." in text:
        raise ValueError(f"{field_name} contains unsafe characters")
    return text


def _transparent_svg_tile(z: int, x: int, y: int) -> bytes:
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">
  <rect width="256" height="256" fill="none"/>
  <text x="128" y="238" text-anchor="middle" font-family="system-ui, -apple-system, sans-serif" font-size="14" fill="#5b6761" opacity="0.72">Raster offline {z}/{x}/{y}</text>
</svg>
"""
    return svg.encode("utf-8")


def _tile_y_to_lat(y: int, z: int) -> float:
    n = math.pi - (2.0 * math.pi * y) / (2**z)
    return math.degrees(math.atan(math.sinh(n)))


def _lon_to_tile_float(lon: float, zoom: int) -> float:
    return (lon + 180.0) / 360.0 * (2**zoom)


def _lat_to_tile_float(lat: float, zoom: int) -> float:
    clipped_lat = max(min(lat, WEB_MERCATOR_MAX_LAT), -WEB_MERCATOR_MAX_LAT)
    lat_rad = math.radians(clipped_lat)
    return (
        (1.0 - math.log(math.tan(lat_rad) + (1 / math.cos(lat_rad))) / math.pi)
        / 2.0
        * (2**zoom)
    )


def _lat_to_global_pixel_y(lat: float, zoom: int) -> float:
    return _lat_to_tile_float(lat, zoom) * DEFAULT_RASTER_TILE_SIZE


def _tile_index(value: float, zoom: int) -> int:
    max_index = (2**zoom) - 1
    return max(0, min(max_index, int(math.floor(value))))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build or seed local PNG tiles from a Scout GeoTIFF source manifest."
    )
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_RASTER_TILE_CACHE_ROOT)
    parser.add_argument("--min-zoom", type=int, default=DEFAULT_RASTER_TILE_MIN_ZOOM)
    parser.add_argument("--max-zoom", type=int, default=DEFAULT_RASTER_TILE_MAX_ZOOM)
    parser.add_argument("--capacity-gib", type=float, default=10.0)
    parser.add_argument("--write-plan", type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--max-tiles", type=int)
    args = parser.parse_args(argv)

    source_manifest = json.loads(args.source_manifest.expanduser().read_text(encoding="utf-8"))
    plan = build_raster_tile_pyramid_plan(
        source_manifest,
        cache_root=args.cache_root,
        min_zoom=args.min_zoom,
        max_zoom=args.max_zoom,
        capacity_limit_bytes=int(args.capacity_gib * 1024 * 1024 * 1024),
    )
    if args.write_plan:
        write_raster_tile_plan_manifest(plan, args.write_plan)
    summary = cut_raster_tile_pyramid(
        source_manifest,
        plan,
        dry_run=not args.execute,
        max_tiles=args.max_tiles,
    )
    print(
        json.dumps(
            {
                "plan_status": plan["status"],
                "tile_count": plan["total_tile_count"],
                "estimated_gib": plan["estimated_total_gib"],
                "seed_status": summary["status"],
                "tiles_written": summary["tiles_written"],
                "cache_root": plan["cache_root"],
                "runtime_tile_url_template": plan["runtime_tile_url_template"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
