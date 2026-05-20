from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any


DEFAULT_MOUNTAIN_ROUTE_ZOOM = 13
DEFAULT_MAX_TILES = 32
DEFAULT_VIEWPORT_WIDTH = 1000
DEFAULT_VIEWPORT_HEIGHT = 720
DEFAULT_OSM_TILE_URL_TEMPLATE = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
DEFAULT_ATTRIBUTION = "OpenStreetMap contributors"
DEFAULT_CACHE_POLICY = "browser_http_cache_or_local_proxy"
SOURCE_KIND = "openstreetmap_tile"
WEB_MERCATOR_MAX_LAT = 85.05112878
MIN_OSM_ZOOM = 0
MAX_OSM_ZOOM = 20


def normalize_bbox_wgs84(bbox: Mapping[str, Any] | object) -> dict[str, float]:
    data = _bbox_to_mapping(bbox)
    if {"south", "west", "north", "east"}.issubset(data):
        south = _coerce_float(data["south"], "south")
        west = _coerce_float(data["west"], "west")
        north = _coerce_float(data["north"], "north")
        east = _coerce_float(data["east"], "east")
    elif {"min_lat", "min_lon", "max_lat", "max_lon"}.issubset(data):
        south = _coerce_float(data["min_lat"], "min_lat")
        west = _coerce_float(data["min_lon"], "min_lon")
        north = _coerce_float(data["max_lat"], "max_lat")
        east = _coerce_float(data["max_lon"], "max_lon")
    else:
        raise ValueError(
            "bbox must contain south/west/north/east or min_lat/min_lon/max_lat/max_lon"
        )

    normalized_south, normalized_north = sorted((south, north))
    normalized_west, normalized_east = sorted((west, east))
    _validate_wgs84_bbox(
        normalized_south,
        normalized_west,
        normalized_north,
        normalized_east,
    )
    return {
        "south": normalized_south,
        "west": normalized_west,
        "north": normalized_north,
        "east": normalized_east,
    }


def build_osm_basemap_contract(
    bbox: Mapping[str, Any] | object,
    *,
    zoom: int | None = None,
    max_tiles: int = DEFAULT_MAX_TILES,
    tile_url_template: str = DEFAULT_OSM_TILE_URL_TEMPLATE,
    viewport_width: int = DEFAULT_VIEWPORT_WIDTH,
    viewport_height: int = DEFAULT_VIEWPORT_HEIGHT,
    opacity: float = 1.0,
) -> dict[str, Any]:
    normalized_bbox = normalize_bbox_wgs84(bbox)
    selected_zoom = select_zoom_for_bbox(
        normalized_bbox,
        zoom=zoom,
        max_tiles=max_tiles,
    )
    tiles = build_osm_tile_coverage(
        normalized_bbox,
        zoom=selected_zoom,
        tile_url_template=tile_url_template,
    )
    projection = build_svg_projection_contract(
        normalized_bbox,
        zoom=selected_zoom,
        viewport_width=viewport_width,
        viewport_height=viewport_height,
    )
    svg_images = build_svg_image_specs(
        tiles,
        projection=projection,
        opacity=opacity,
    )

    return {
        "source_kind": SOURCE_KIND,
        "bbox_wgs84": normalized_bbox,
        "requested_zoom": zoom,
        "zoom": selected_zoom,
        "max_tiles": max_tiles,
        "tile_count": len(tiles),
        "tile_url_template": tile_url_template,
        "attribution": DEFAULT_ATTRIBUTION,
        "external_network_required": True,
        "cache_policy": DEFAULT_CACHE_POLICY,
        "tiles": tiles,
        "svg_viewport": {
            "width": viewport_width,
            "height": viewport_height,
            "viewBox": f"0 0 {viewport_width} {viewport_height}",
        },
        "projection": projection,
        "svg_images": svg_images,
    }


def select_zoom_for_bbox(
    bbox: Mapping[str, Any] | object,
    *,
    zoom: int | None = None,
    max_tiles: int = DEFAULT_MAX_TILES,
    min_zoom: int = MIN_OSM_ZOOM,
    max_zoom: int = MAX_OSM_ZOOM,
) -> int:
    normalized_bbox = normalize_bbox_wgs84(bbox)
    if max_tiles < 1:
        raise ValueError("max_tiles must be at least 1")

    selected_zoom = DEFAULT_MOUNTAIN_ROUTE_ZOOM if zoom is None else int(zoom)
    if selected_zoom < min_zoom or selected_zoom > max_zoom:
        raise ValueError(f"zoom must be between {min_zoom} and {max_zoom}")

    while (
        tile_count_for_bbox(normalized_bbox, zoom=selected_zoom) > max_tiles
        and selected_zoom > min_zoom
    ):
        selected_zoom -= 1
    return selected_zoom


def tile_count_for_bbox(bbox: Mapping[str, Any] | object, *, zoom: int) -> int:
    x_min, x_max, y_min, y_max = slippy_tile_range(bbox, zoom=zoom)
    return (x_max - x_min + 1) * (y_max - y_min + 1)


def build_osm_tile_coverage(
    bbox: Mapping[str, Any] | object,
    *,
    zoom: int,
    tile_url_template: str = DEFAULT_OSM_TILE_URL_TEMPLATE,
) -> list[dict[str, Any]]:
    x_min, x_max, y_min, y_max = slippy_tile_range(bbox, zoom=zoom)
    tiles: list[dict[str, Any]] = []
    for y in range(y_min, y_max + 1):
        for x in range(x_min, x_max + 1):
            tiles.append(
                {
                    "z": zoom,
                    "x": x,
                    "y": y,
                    "url": tile_url_template.format(z=zoom, x=x, y=y),
                    "source_kind": SOURCE_KIND,
                    "tile_url_template": tile_url_template,
                    "attribution": DEFAULT_ATTRIBUTION,
                    "external_network_required": True,
                    "cache_policy": DEFAULT_CACHE_POLICY,
                }
            )
    return tiles


def slippy_tile_range(
    bbox: Mapping[str, Any] | object,
    *,
    zoom: int,
) -> tuple[int, int, int, int]:
    normalized_bbox = normalize_bbox_wgs84(bbox)
    _validate_zoom(zoom)
    west_x = _lon_to_tile_float(normalized_bbox["west"], zoom)
    east_x = _lon_to_tile_float(normalized_bbox["east"], zoom)
    north_y = _lat_to_tile_float(normalized_bbox["north"], zoom)
    south_y = _lat_to_tile_float(normalized_bbox["south"], zoom)
    return (
        _tile_index(west_x, zoom),
        _tile_index(east_x, zoom),
        _tile_index(north_y, zoom),
        _tile_index(south_y, zoom),
    )


def build_svg_projection_contract(
    bbox: Mapping[str, Any] | object,
    *,
    zoom: int,
    viewport_width: int = DEFAULT_VIEWPORT_WIDTH,
    viewport_height: int = DEFAULT_VIEWPORT_HEIGHT,
) -> dict[str, Any]:
    normalized_bbox = normalize_bbox_wgs84(bbox)
    _validate_zoom(zoom)
    if viewport_width <= 0 or viewport_height <= 0:
        raise ValueError("viewport width and height must be positive")

    west_x = _lon_to_tile_float(normalized_bbox["west"], zoom)
    east_x = _lon_to_tile_float(normalized_bbox["east"], zoom)
    north_y = _lat_to_tile_float(normalized_bbox["north"], zoom)
    south_y = _lat_to_tile_float(normalized_bbox["south"], zoom)
    bbox_width_tiles = max(east_x - west_x, 1e-9)
    bbox_height_tiles = max(south_y - north_y, 1e-9)
    scale = min(
        viewport_width / bbox_width_tiles,
        viewport_height / bbox_height_tiles,
    )
    content_width = bbox_width_tiles * scale
    content_height = bbox_height_tiles * scale
    offset_x = (viewport_width - content_width) / 2
    offset_y = (viewport_height - content_height) / 2

    return {
        "type": "web_mercator",
        "zoom": zoom,
        "fit": "contain",
        "tile_unit": "slippy_tile",
        "viewport": {
            "width": viewport_width,
            "height": viewport_height,
            "viewBox": f"0 0 {viewport_width} {viewport_height}",
        },
        "bbox_wgs84": normalized_bbox,
        "bbox_tile_bounds": {
            "west": west_x,
            "east": east_x,
            "north": north_y,
            "south": south_y,
        },
        "scale_svg_units_per_tile": scale,
        "offset_x": offset_x,
        "offset_y": offset_y,
    }


def build_svg_image_specs(
    tiles: list[Mapping[str, Any]],
    *,
    projection: Mapping[str, Any],
    opacity: float = 1.0,
) -> list[dict[str, Any]]:
    tile_bounds = projection["bbox_tile_bounds"]
    scale = float(projection["scale_svg_units_per_tile"])
    offset_x = float(projection["offset_x"])
    offset_y = float(projection["offset_y"])
    west = float(tile_bounds["west"])
    north = float(tile_bounds["north"])

    return [
        {
            "tag": "image",
            "x": _round_svg((int(tile["x"]) - west) * scale + offset_x),
            "y": _round_svg((int(tile["y"]) - north) * scale + offset_y),
            "width": _round_svg(scale),
            "height": _round_svg(scale),
            "href": str(tile["url"]),
            "opacity": opacity,
            "data-layer": "basemap-osm",
            "data-source-kind": str(tile["source_kind"]),
            "data-tile-z": str(tile["z"]),
            "data-tile-x": str(tile["x"]),
            "data-tile-y": str(tile["y"]),
            "data-external-network-required": str(
                tile["external_network_required"]
            ).lower(),
            "data-cache-policy": str(tile["cache_policy"]),
        }
        for tile in tiles
    ]


def project_wgs84_to_svg(
    lat: float,
    lon: float,
    *,
    projection: Mapping[str, Any],
) -> tuple[float, float]:
    zoom = int(projection["zoom"])
    tile_bounds = projection["bbox_tile_bounds"]
    scale = float(projection["scale_svg_units_per_tile"])
    x = (
        (_lon_to_tile_float(lon, zoom) - float(tile_bounds["west"])) * scale
        + float(projection["offset_x"])
    )
    y = (
        (_lat_to_tile_float(lat, zoom) - float(tile_bounds["north"])) * scale
        + float(projection["offset_y"])
    )
    return (_round_svg(x), _round_svg(y))


def _bbox_to_mapping(bbox: Mapping[str, Any] | object) -> Mapping[str, Any]:
    if isinstance(bbox, Mapping):
        return bbox
    model_dump = getattr(bbox, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        if isinstance(dumped, Mapping):
            return dumped
    return {
        key: getattr(bbox, key)
        for key in (
            "south",
            "west",
            "north",
            "east",
            "min_lat",
            "min_lon",
            "max_lat",
            "max_lon",
        )
        if hasattr(bbox, key)
    }


def _coerce_float(value: Any, field_name: str) -> float:
    try:
        coerced = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be numeric") from exc
    if not math.isfinite(coerced):
        raise ValueError(f"{field_name} must be finite")
    return coerced


def _validate_wgs84_bbox(south: float, west: float, north: float, east: float) -> None:
    if south < -90 or north > 90:
        raise ValueError("bbox latitude must be within WGS84 -90..90 degrees")
    if west < -180 or east > 180:
        raise ValueError("bbox longitude must be within WGS84 -180..180 degrees")


def _validate_zoom(zoom: int) -> None:
    if zoom < MIN_OSM_ZOOM or zoom > MAX_OSM_ZOOM:
        raise ValueError(f"zoom must be between {MIN_OSM_ZOOM} and {MAX_OSM_ZOOM}")


def _lon_to_tile_float(lon: float, zoom: int) -> float:
    return ((lon + 180.0) / 360.0) * (2**zoom)


def _lat_to_tile_float(lat: float, zoom: int) -> float:
    clamped_lat = max(min(lat, WEB_MERCATOR_MAX_LAT), -WEB_MERCATOR_MAX_LAT)
    lat_rad = math.radians(clamped_lat)
    return (
        (1.0 - math.asinh(math.tan(lat_rad)) / math.pi)
        / 2.0
        * (2**zoom)
    )


def _tile_index(tile_float: float, zoom: int) -> int:
    max_index = (2**zoom) - 1
    return max(0, min(int(math.floor(tile_float)), max_index))


def _round_svg(value: float) -> float:
    return round(value, 3)
