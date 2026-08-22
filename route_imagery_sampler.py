from __future__ import annotations

from dataclasses import dataclass
import colorsys
from functools import lru_cache
import io
from math import cos, radians, sqrt
import warnings
from typing import Any, Iterable, Mapping

from weather_imagery_tile_cache import (
    DEFAULT_MAX_SOURCE_IMAGE_PIXELS,
    CachedImageryFrame,
    WeatherImageryTileCache,
)


EARTH_RADIUS_KM = 6371.0088
MAX_ROUTE_SIMPLIFICATION_KM = 0.025


@dataclass(frozen=True)
class RasterGrid:
    west: float
    south: float
    east: float
    north: float
    values: tuple[tuple[float | None, ...], ...]

    def __post_init__(self) -> None:
        if not self.values or not self.values[0]:
            raise ValueError("raster grid must not be empty")
        width = len(self.values[0])
        if any(len(row) != width for row in self.values):
            raise ValueError("raster grid rows must have equal width")
        if self.west >= self.east or self.south >= self.north:
            raise ValueError("invalid raster grid bounds")

    @property
    def width(self) -> int:
        return len(self.values[0])

    @property
    def height(self) -> int:
        return len(self.values)


@dataclass(frozen=True)
class RouteBuffer:
    route_points: tuple[tuple[float, float], ...]
    buffer_m: float
    bbox_wgs84: dict[str, float]

    def to_geojson(self) -> dict[str, Any]:
        lat_pad = self.buffer_m / 111_320.0
        polygons: list[list[list[list[float]]]] = []
        for (lat1, lon1), (lat2, lon2) in zip(self.route_points, self.route_points[1:]):
            center_lat = (lat1 + lat2) / 2.0
            lon_pad = self.buffer_m / max(1.0, 111_320.0 * cos(radians(center_lat)))
            west, east = min(lon1, lon2) - lon_pad, max(lon1, lon2) + lon_pad
            south, north = min(lat1, lat2) - lat_pad, max(lat1, lat2) + lat_pad
            polygons.append(
                [[[west, south], [east, south], [east, north], [west, north], [west, south]]]
            )
        return {
            "type": "Feature",
            "properties": {
                "artifactKind": "routeImageryBuffer",
                "bufferM": self.buffer_m,
                "candidateOnly": True,
                "runtimeSafetyTruth": False,
            },
            "geometry": {"type": "MultiPolygon", "coordinates": polygons},
        }


@dataclass(frozen=True)
class _RouteSegmentIndex:
    reference_lat_radians: float
    bucket_km: float
    segments: tuple[tuple[float, float, float, float], ...]
    projected_segments: tuple[tuple[float, float, float, float], ...]
    bucket_segment_ids: Mapping[tuple[int, int], tuple[int, ...]]

    def contains_within(self, lat: float, lon: float, radius_km: float) -> bool:
        scale_x = 111.320 * cos(self.reference_lat_radians)
        x_bucket = int((lon * scale_x) // self.bucket_km)
        y_bucket = int((lat * 110.574) // self.bucket_km)
        checked: set[int] = set()
        for x_offset in range(-2, 3):
            for y_offset in range(-2, 3):
                segment_ids = self.bucket_segment_ids.get(
                    (x_bucket + x_offset, y_bucket + y_offset),
                    (),
                )
                for segment_id in segment_ids:
                    if segment_id in checked:
                        continue
                    checked.add(segment_id)
                    if _point_segment_distance_xy_km(
                        lon * scale_x,
                        lat * 110.574,
                        *self.projected_segments[segment_id],
                    ) <= radius_km:
                        return True
        return False


def build_route_buffer(
    route_points: Iterable[tuple[float, float]],
    *,
    buffer_m: float = 500.0,
) -> RouteBuffer:
    points = tuple((float(lat), float(lon)) for lat, lon in route_points)
    if len(points) < 2:
        raise ValueError("route imagery buffer requires at least two points")
    if buffer_m <= 0:
        raise ValueError("route imagery buffer must be positive")
    lat_pad = buffer_m / 111_320.0
    center_lat = sum(item[0] for item in points) / len(points)
    lon_pad = buffer_m / max(1.0, 111_320.0 * cos(radians(center_lat)))
    return RouteBuffer(
        route_points=points,
        buffer_m=float(buffer_m),
        bbox_wgs84={
            "west": min(item[1] for item in points) - lon_pad,
            "south": min(item[0] for item in points) - lat_pad,
            "east": max(item[1] for item in points) + lon_pad,
            "north": max(item[0] for item in points) + lat_pad,
        },
    )


def sample_radar_grid(
    grid: RasterGrid,
    route_buffer: RouteBuffer,
    *,
    source_timestamp: str,
    fetched_at: str,
    echo_threshold_dbz: float = 20.0,
    strong_threshold_dbz: float = 40.0,
    nearby_radius_km: float = 20.0,
) -> dict[str, Any]:
    cells = _grid_cells(grid)
    route_cells = _cached_cells_within_route_radius(
        grid,
        cells,
        route_buffer,
        route_buffer.buffer_m / 1000.0,
    )
    nearby_cells = _cached_cells_within_route_radius(
        grid,
        cells,
        route_buffer,
        nearby_radius_km,
    )
    valid_route = [cell for cell in route_cells if cell[2] is not None]
    echo = [cell for cell in valid_route if float(cell[2]) >= echo_threshold_dbz]
    strong = [cell for cell in nearby_cells if cell[2] is not None and float(cell[2]) >= strong_threshold_dbz]
    max_dbz = max((float(cell[2]) for cell in nearby_cells if cell[2] is not None), default=None)
    return {
        "artifactKind": "routeRadarImagerySample",
        "sourceTimestamp": source_timestamp,
        "fetchedAt": fetched_at,
        "currentRainOnRoute": bool(echo) if valid_route else None,
        "nearbyStrongEcho": bool(strong) if nearby_cells else None,
        "routeEchoOverlapRatio": round(len(echo) / len(valid_route), 4) if valid_route else None,
        "maxReflectivityDbz": max_dbz,
        "strongEchoCentroid": _centroid(strong),
        "coverageConfidence": _coverage_confidence(grid, route_buffer, valid_route, route_cells),
        "spatialResolutionKm": round(_grid_cell_diagonal_km(grid, route_buffer) / 2.0, 4),
        "routeGeometryToleranceKm": _route_index_tolerance_km(
            route_buffer.buffer_m / 1000.0
        ),
        "candidateOnly": True,
        "runtimeSafetyTruth": False,
    }


def sample_satellite_grid(
    grid: RasterGrid,
    route_buffer: RouteBuffer,
    *,
    source_timestamp: str,
    fetched_at: str,
    convective_threshold: float = 0.75,
) -> dict[str, Any]:
    cells = _grid_cells(grid)
    route_cells = _cached_cells_within_route_radius(
        grid,
        cells,
        route_buffer,
        route_buffer.buffer_m / 1000.0,
    )
    valid = [cell for cell in route_cells if cell[2] is not None]
    convective = [cell for cell in valid if float(cell[2]) >= convective_threshold]
    score = max((float(cell[2]) for cell in valid), default=None)
    return {
        "artifactKind": "routeSatelliteImagerySample",
        "sourceTimestamp": source_timestamp,
        "fetchedAt": fetched_at,
        "satelliteConvectiveCloudScore": round(score, 4) if score is not None else None,
        "convectiveCloudCentroid": _centroid(convective),
        "coverageConfidence": _coverage_confidence(grid, route_buffer, valid, route_cells),
        "spatialResolutionKm": round(_grid_cell_diagonal_km(grid, route_buffer) / 2.0, 4),
        "routeGeometryToleranceKm": _route_index_tolerance_km(
            route_buffer.buffer_m / 1000.0
        ),
        "candidateOnly": True,
        "runtimeSafetyTruth": False,
    }


def decode_cached_frame_grid(
    frame: CachedImageryFrame,
    cache: WeatherImageryTileCache,
    *,
    max_grid_dimension: int = 160,
    sample_bbox_wgs84: dict[str, float] | None = None,
) -> RasterGrid:
    if max_grid_dimension < 16:
        raise ValueError("max_grid_dimension must be at least 16")
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - server environment preflight owns this.
        raise RuntimeError("Pillow is required for server-side CWA imagery processing") from exc
    if "fixed_grid_required" in frame.georeference_version:
        raise ValueError("fixed-grid satellite imagery must be reprojected before route sampling")
    if not frame.route_sampling_supported:
        raise ValueError("imagery product is not approved for route sampling")
    bbox = dict(frame.bbox_wgs84)
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        source = Image.open(io.BytesIO(cache.read_asset(frame.cache_ref)))
        if source.width * source.height > DEFAULT_MAX_SOURCE_IMAGE_PIXELS:
            source.close()
            raise ValueError("CWA imagery source exceeds pixel limit")
        if sample_bbox_wgs84 is not None:
            source, bbox = _crop_to_wgs84_bbox(source, bbox, sample_bbox_wgs84)
        source.thumbnail((max_grid_dimension, max_grid_dimension))
        image = source.convert("RGBA")
        source.close()
        width, height = image.size
        pixels = image.load()
        rows: list[tuple[float | None, ...]] = []
        for y in range(height):
            row: list[float | None] = []
            for x in range(width):
                red, green, blue, alpha = pixels[x, y]
                if frame.image_type.startswith("echo") or frame.image_type == "rainfall_radar":
                    row.append(_radar_dbz(red, green, blue, alpha))
                elif frame.image_type == "enhanced_color":
                    row.append(_satellite_convective_score(red, green, blue, alpha))
                else:
                    row.append(None)
            rows.append(tuple(row))
        image.close()
    return RasterGrid(
        west=float(bbox["west"]),
        south=float(bbox["south"]),
        east=float(bbox["east"]),
        north=float(bbox["north"]),
        values=tuple(rows),
    )


def distance_to_route_km(lat: float, lon: float, route_buffer: RouteBuffer) -> float:
    return min(
        _point_segment_distance_km(lat, lon, lat1, lon1, lat2, lon2)
        for (lat1, lon1), (lat2, lon2) in zip(route_buffer.route_points, route_buffer.route_points[1:])
    )


def _grid_cells(grid: RasterGrid) -> list[tuple[float, float, float | None]]:
    cells: list[tuple[float, float, float | None]] = []
    for row_index, row in enumerate(grid.values):
        lat = grid.north - ((row_index + 0.5) / grid.height) * (grid.north - grid.south)
        for column_index, value in enumerate(row):
            lon = grid.west + ((column_index + 0.5) / grid.width) * (grid.east - grid.west)
            cells.append((lat, lon, value))
    return cells


def _route_sample_cells(
    grid: RasterGrid,
    route_buffer: RouteBuffer,
) -> list[tuple[float, float, float | None]]:
    cells = _grid_cells(grid)
    return _cached_cells_within_route_radius(
        grid,
        cells,
        route_buffer,
        route_buffer.buffer_m / 1000.0,
    )


def _cached_cells_within_route_radius(
    grid: RasterGrid,
    cells: list[tuple[float, float, float | None]],
    route_buffer: RouteBuffer,
    radius_km: float,
) -> list[tuple[float, float, float | None]]:
    indices = _route_cell_indices(
        grid.west,
        grid.south,
        grid.east,
        grid.north,
        grid.width,
        grid.height,
        route_buffer.route_points,
        route_buffer.buffer_m,
        radius_km,
    )
    return [cells[index] for index in indices]


@lru_cache(maxsize=64)
def _route_cell_indices(
    west: float,
    south: float,
    east: float,
    north: float,
    width: int,
    height: int,
    route_points: tuple[tuple[float, float], ...],
    buffer_m: float,
    radius_km: float,
) -> tuple[int, ...]:
    route_buffer = build_route_buffer(route_points, buffer_m=buffer_m)
    segment_index = _build_route_segment_index(route_buffer, bucket_km=radius_km)
    matching: list[int] = []
    for row_index in range(height):
        lat = north - ((row_index + 0.5) / height) * (north - south)
        for column_index in range(width):
            lon = west + ((column_index + 0.5) / width) * (east - west)
            if segment_index.contains_within(lat, lon, radius_km):
                matching.append(row_index * width + column_index)
    return tuple(matching)


def _cells_within_route_radius(
    cells: Iterable[tuple[float, float, float | None]],
    route_buffer: RouteBuffer,
    radius_km: float,
) -> list[tuple[float, float, float | None]]:
    if radius_km <= 0:
        raise ValueError("route sampling radius must be positive")
    segment_index = _build_route_segment_index(route_buffer, bucket_km=radius_km)
    return [
        cell
        for cell in cells
        if segment_index.contains_within(cell[0], cell[1], radius_km)
    ]


def _build_route_segment_index(
    route_buffer: RouteBuffer,
    *,
    bucket_km: float,
) -> _RouteSegmentIndex:
    if bucket_km <= 0:
        raise ValueError("route segment index bucket must be positive")
    reference_lat_radians = radians(
        sum(point[0] for point in route_buffer.route_points)
        / len(route_buffer.route_points)
    )
    scale_x = 111.320 * cos(reference_lat_radians)
    sampling_points = _simplify_route_points(
        route_buffer.route_points,
        tolerance_km=_route_index_tolerance_km(bucket_km),
        scale_x=scale_x,
    )
    segments = tuple(
        (lat1, lon1, lat2, lon2)
        for (lat1, lon1), (lat2, lon2) in zip(
            sampling_points,
            sampling_points[1:],
        )
    )
    projected_segments = tuple(
        (
            lon1 * scale_x,
            lat1 * 110.574,
            lon2 * scale_x,
            lat2 * 110.574,
        )
        for lat1, lon1, lat2, lon2 in segments
    )
    buckets: dict[tuple[int, int], list[int]] = {}
    for segment_id, (lat1, lon1, lat2, lon2) in enumerate(segments):
        min_x_bucket = int((min(lon1, lon2) * scale_x) // bucket_km)
        max_x_bucket = int((max(lon1, lon2) * scale_x) // bucket_km)
        min_y_bucket = int((min(lat1, lat2) * 110.574) // bucket_km)
        max_y_bucket = int((max(lat1, lat2) * 110.574) // bucket_km)
        for x_bucket in range(min_x_bucket, max_x_bucket + 1):
            for y_bucket in range(min_y_bucket, max_y_bucket + 1):
                key = (x_bucket, y_bucket)
                buckets[key] = [*buckets.get(key, ()), segment_id]
    return _RouteSegmentIndex(
        reference_lat_radians=reference_lat_radians,
        bucket_km=bucket_km,
        segments=segments,
        projected_segments=projected_segments,
        bucket_segment_ids={
            key: tuple(segment_ids) for key, segment_ids in buckets.items()
        },
    )


def _route_index_tolerance_km(bucket_km: float) -> float:
    return round(min(MAX_ROUTE_SIMPLIFICATION_KM, bucket_km * 0.05), 6)


def _simplify_route_points(
    points: tuple[tuple[float, float], ...],
    *,
    tolerance_km: float,
    scale_x: float,
) -> tuple[tuple[float, float], ...]:
    if len(points) <= 2 or tolerance_km <= 0:
        return points
    projected = tuple((lon * scale_x, lat * 110.574) for lat, lon in points)
    keep = {0, len(points) - 1}
    pending = [(0, len(points) - 1)]
    while pending:
        start, end = pending.pop()
        farthest_index: int | None = None
        farthest_distance = -1.0
        for index in range(start + 1, end):
            distance = _point_segment_distance_xy_km(
                *projected[index],
                *projected[start],
                *projected[end],
            )
            if distance > farthest_distance:
                farthest_distance = distance
                farthest_index = index
        if farthest_index is not None and farthest_distance > tolerance_km:
            keep.add(farthest_index)
            pending.extend(((start, farthest_index), (farthest_index, end)))
    return tuple(points[index] for index in sorted(keep))


def _grid_cell_diagonal_km(grid: RasterGrid, route_buffer: RouteBuffer) -> float:
    center_lat = sum(point[0] for point in route_buffer.route_points) / len(route_buffer.route_points)
    height_km = (grid.north - grid.south) * 110.574 / grid.height
    width_km = (
        (grid.east - grid.west)
        * 111.320
        * cos(radians(center_lat))
        / grid.width
    )
    return sqrt(height_km * height_km + width_km * width_km)


def _coverage_confidence(
    grid: RasterGrid,
    route_buffer: RouteBuffer,
    valid_cells: list[tuple[float, float, float | None]],
    route_cells: list[tuple[float, float, float | None]],
) -> float:
    if not route_cells:
        return 0.0
    data_ratio = len(valid_cells) / len(route_cells)
    half_diagonal = _grid_cell_diagonal_km(grid, route_buffer) / 2.0
    resolution_ratio = min(
        1.0,
        (route_buffer.buffer_m / 1000.0) / max(0.001, half_diagonal),
    )
    return round(data_ratio * resolution_ratio, 4)


def _crop_to_wgs84_bbox(
    image: Any,
    source_bbox: dict[str, float],
    requested_bbox: dict[str, float],
) -> tuple[Any, dict[str, float]]:
    west = max(float(source_bbox["west"]), float(requested_bbox["west"]))
    south = max(float(source_bbox["south"]), float(requested_bbox["south"]))
    east = min(float(source_bbox["east"]), float(requested_bbox["east"]))
    north = min(float(source_bbox["north"]), float(requested_bbox["north"]))
    if west >= east or south >= north:
        image.close()
        raise ValueError("route sampling bbox is outside imagery coverage")
    span_lon = float(source_bbox["east"]) - float(source_bbox["west"])
    span_lat = float(source_bbox["north"]) - float(source_bbox["south"])
    left = max(0, int((west - float(source_bbox["west"])) / span_lon * image.width))
    right = min(image.width, int((east - float(source_bbox["west"])) / span_lon * image.width) + 1)
    top = max(0, int((float(source_bbox["north"]) - north) / span_lat * image.height))
    bottom = min(image.height, int((float(source_bbox["north"]) - south) / span_lat * image.height) + 1)
    cropped = image.crop((left, top, right, bottom))
    image.close()
    return cropped, {"west": west, "south": south, "east": east, "north": north}


def _centroid(cells: list[tuple[float, float, float | None]]) -> dict[str, float] | None:
    if not cells:
        return None
    weights = [max(float(cell[2] or 0.0), 0.01) for cell in cells]
    total = sum(weights)
    return {
        "lat": round(sum(cell[0] * weight for cell, weight in zip(cells, weights)) / total, 6),
        "lon": round(sum(cell[1] * weight for cell, weight in zip(cells, weights)) / total, 6),
    }


def _point_segment_distance_km(
    lat: float,
    lon: float,
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    reference_lat = radians((lat + lat1 + lat2) / 3.0)
    scale_x = 111.320 * cos(reference_lat)
    scale_y = 110.574
    px, py = lon * scale_x, lat * scale_y
    x1, y1 = lon1 * scale_x, lat1 * scale_y
    x2, y2 = lon2 * scale_x, lat2 * scale_y
    return _point_segment_distance_xy_km(px, py, x1, y1, x2, y2)


def _point_segment_distance_xy_km(
    px: float,
    py: float,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
) -> float:
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return sqrt((px - x1) ** 2 + (py - y1) ** 2)
    fraction = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    nearest_x, nearest_y = x1 + fraction * dx, y1 + fraction * dy
    return sqrt((px - nearest_x) ** 2 + (py - nearest_y) ** 2)


def _radar_dbz(red: int, green: int, blue: int, alpha: int) -> float | None:
    if alpha < 24:
        return None
    hue, saturation, value = colorsys.rgb_to_hsv(red / 255.0, green / 255.0, blue / 255.0)
    degrees = hue * 360.0
    if saturation < 0.18 or value < 0.12:
        return None
    if 180 <= degrees < 270:
        return 20.0
    if 75 <= degrees < 180:
        return 32.0
    if 45 <= degrees < 75:
        return 40.0
    if 18 <= degrees < 45:
        return 45.0
    if degrees < 18 or degrees >= 345:
        return 50.0
    if 270 <= degrees < 345:
        return 55.0
    return None


def _satellite_convective_score(red: int, green: int, blue: int, alpha: int) -> float | None:
    if alpha < 24:
        return None
    _hue, saturation, value = colorsys.rgb_to_hsv(red / 255.0, green / 255.0, blue / 255.0)
    brightness_contrast = abs(value - 0.5) * 2.0
    return round(max(0.0, min(1.0, 0.65 * saturation + 0.35 * brightness_contrast)), 4)
