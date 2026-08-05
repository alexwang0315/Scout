from __future__ import annotations

import hashlib
import io
import json
import math
from dataclasses import dataclass
from pathlib import Path

from admin_local_raster_tiles import load_or_build_raster_tile_payload
from scout_contextual_permission_workbench import BaselineMapContextProjection


RUDY_SOURCE_ID = "happyman_rudy_twmap"
RUDY_LAYER_ID = "imagery"
RUDY_BACKGROUND_WIDTH = 760
RUDY_BACKGROUND_HEIGHT = 248
RUDY_MAX_SOURCE_TILES = 24
WEB_MERCATOR_MAX_LAT = 85.05112878


@dataclass(frozen=True)
class DailyRudyBackground:
    body: bytes
    zoom: int
    source_tile_count: int
    body_sha256: str

    def headers(self) -> dict[str, str]:
        return {
            "Cache-Control": "private, max-age=300",
            "Content-Disposition": 'inline; filename="rudy-day-background.png"',
            "X-Scout-Rudy-Background": "single-composite-image",
            "X-Scout-Imagery-Source-Id": RUDY_SOURCE_ID,
            "X-Scout-Rudy-Zoom": str(self.zoom),
            "X-Scout-Source-Tile-Count": str(self.source_tile_count),
            "X-Scout-Image-Hash": self.body_sha256,
            "X-Scout-Writes-Performed": "false",
            "X-Scout-Candidate-Only": "true",
            "X-Scout-Runtime-Safety-Truth": "false",
        }


@dataclass(frozen=True)
class RudyCacheSettings:
    cache_root: Path
    min_zoom: int
    max_zoom: int


def rudy_cache_settings(project_root: Path) -> RudyCacheSettings:
    try:
        project = json.loads((project_root / "project.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"project.json is invalid: {exc}") from exc
    if project.get("imagery_tile_cache_source_id") != RUDY_SOURCE_ID:
        raise ValueError("Rudy+TW is not the reviewed imagery cache source for this project.")
    raw_cache_root = project.get("imagery_tile_cache_root")
    if not isinstance(raw_cache_root, str) or not raw_cache_root.strip():
        raise FileNotFoundError("The project has no prepared Rudy+TW tile cache root.")
    cache_root = Path(raw_cache_root).expanduser()
    if not cache_root.is_absolute():
        cache_root = project_root / cache_root
    cache_root = cache_root.resolve()
    if not cache_root.is_dir():
        raise FileNotFoundError(f"Prepared Rudy+TW tile cache is unavailable: {cache_root}")
    min_zoom = _bounded_zoom(project.get("imagery_tile_cache_min_zoom"), default=5)
    max_zoom = _bounded_zoom(project.get("imagery_tile_cache_max_zoom"), default=14)
    if min_zoom > max_zoom:
        raise ValueError("Rudy+TW cache zoom range is invalid.")
    return RudyCacheSettings(
        cache_root=cache_root,
        min_zoom=min_zoom,
        max_zoom=max_zoom,
    )


def render_daily_rudy_background(
    *,
    project_id: str,
    context: BaselineMapContextProjection,
    cache_settings: RudyCacheSettings,
    west: float,
    south: float,
    east: float,
    north: float,
    width: int = RUDY_BACKGROUND_WIDTH,
    height: int = RUDY_BACKGROUND_HEIGHT,
) -> DailyRudyBackground:
    bounds = _validate_bounds(
        context,
        west=west,
        south=south,
        east=east,
        north=north,
    )
    if width != RUDY_BACKGROUND_WIDTH or height != RUDY_BACKGROUND_HEIGHT:
        raise ValueError("Daily Rudy backgrounds use the fixed 760 by 248 contract.")
    try:
        from PIL import Image
    except Exception as exc:  # pragma: no cover - runtime dependency guard
        raise RuntimeError("Pillow is required to compose Rudy backgrounds.") from exc

    zoom, tile_range = _select_zoom(
        bounds,
        min_zoom=cache_settings.min_zoom,
        max_zoom=cache_settings.max_zoom,
    )
    x_min, x_max, y_min, y_max = tile_range
    tile_size = 256
    mosaic = Image.new(
        "RGBA",
        ((x_max - x_min + 1) * tile_size, (y_max - y_min + 1) * tile_size),
        (6, 16, 12, 255),
    )
    source_tile_count = 0
    for y in range(y_min, y_max + 1):
        for x in range(x_min, x_max + 1):
            payload = load_or_build_raster_tile_payload(
                project_id,
                RUDY_LAYER_ID,
                zoom,
                x,
                y,
                cache_root=cache_settings.cache_root,
                fallback_enabled=False,
                imagery_source=None,
                allow_remote_fetch=False,
            )
            with Image.open(io.BytesIO(payload.body)) as source:
                tile = source.convert("RGBA")
                if tile.size != (tile_size, tile_size):
                    resample = getattr(getattr(Image, "Resampling", Image), "BILINEAR")
                    tile = tile.resize((tile_size, tile_size), resample=resample)
                mosaic.alpha_composite(
                    tile,
                    dest=((x - x_min) * tile_size, (y - y_min) * tile_size),
                )
            source_tile_count += 1

    world_size = (2**zoom) * tile_size
    left = (_mercator_x(bounds["west"]) * world_size) - (x_min * tile_size)
    right = (_mercator_x(bounds["east"]) * world_size) - (x_min * tile_size)
    upper = (_mercator_y(bounds["north"]) * world_size) - (y_min * tile_size)
    lower = (_mercator_y(bounds["south"]) * world_size) - (y_min * tile_size)
    transform = getattr(getattr(Image, "Transform", Image), "EXTENT")
    resample = getattr(getattr(Image, "Resampling", Image), "BILINEAR")
    rendered = mosaic.transform(
        (width, height),
        transform,
        (left, upper, right, lower),
        resample=resample,
    ).convert("RGB")
    output = io.BytesIO()
    rendered.save(output, format="PNG", optimize=True)
    body = output.getvalue()
    return DailyRudyBackground(
        body=body,
        zoom=zoom,
        source_tile_count=source_tile_count,
        body_sha256=hashlib.sha256(body).hexdigest(),
    )


def _bounded_zoom(value: object, *, default: int) -> int:
    try:
        zoom = int(value) if value is not None else default
    except (TypeError, ValueError) as exc:
        raise ValueError("Rudy+TW cache zoom must be an integer.") from exc
    if not 0 <= zoom <= 20:
        raise ValueError("Rudy+TW cache zoom must be between 0 and 20.")
    return zoom


def _validate_bounds(
    context: BaselineMapContextProjection,
    *,
    west: float,
    south: float,
    east: float,
    north: float,
) -> dict[str, float]:
    values = (west, south, east, north)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("Daily Rudy bounds must be finite numbers.")
    if not -180 <= west < east <= 180 or not -90 <= south < north <= 90:
        raise ValueError("Daily Rudy bounds are invalid.")
    if east - west > 2 or north - south > 2:
        raise ValueError("Daily Rudy bounds exceed the bounded route context.")
    route_points = context.route_points
    if not any(
        west <= point.lon <= east and south <= point.lat <= north
        for point in route_points
    ):
        raise ValueError("Daily Rudy bounds do not contain prepared route geometry.")
    return {"west": west, "south": south, "east": east, "north": north}


def _select_zoom(
    bounds: dict[str, float],
    *,
    min_zoom: int,
    max_zoom: int,
) -> tuple[int, tuple[int, int, int, int]]:
    for zoom in range(max_zoom, min_zoom - 1, -1):
        tile_range = _tile_range(bounds, zoom)
        x_min, x_max, y_min, y_max = tile_range
        count = (x_max - x_min + 1) * (y_max - y_min + 1)
        if count <= RUDY_MAX_SOURCE_TILES:
            return zoom, tile_range
    return min_zoom, _tile_range(bounds, min_zoom)


def _tile_range(
    bounds: dict[str, float], zoom: int
) -> tuple[int, int, int, int]:
    scale = 2**zoom
    epsilon = 1e-12
    x_min = max(0, min(scale - 1, math.floor(_mercator_x(bounds["west"]) * scale)))
    x_max = max(
        0,
        min(scale - 1, math.floor((_mercator_x(bounds["east"]) - epsilon) * scale)),
    )
    y_min = max(0, min(scale - 1, math.floor(_mercator_y(bounds["north"]) * scale)))
    y_max = max(
        0,
        min(scale - 1, math.floor((_mercator_y(bounds["south"]) - epsilon) * scale)),
    )
    return x_min, x_max, y_min, y_max


def _mercator_x(lon: float) -> float:
    return (lon + 180.0) / 360.0


def _mercator_y(lat: float) -> float:
    bounded_lat = max(-WEB_MERCATOR_MAX_LAT, min(WEB_MERCATOR_MAX_LAT, lat))
    radians = math.radians(bounded_lat)
    return (1.0 - math.asinh(math.tan(radians)) / math.pi) / 2.0
