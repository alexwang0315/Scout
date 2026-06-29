from __future__ import annotations

from dataclasses import dataclass
from math import atan2, cos, radians, sin, sqrt

from scout_risk.gpx.parser import RoutePoint


EARTH_RADIUS_M = 6_371_000.0


@dataclass(frozen=True)
class ResampledRoutePoint(RoutePoint):
    distance_m: float = 0.0


@dataclass(frozen=True)
class XYRoutePoint:
    x: float
    y: float
    distance_m: float
    lat: float | None = None
    lon: float | None = None
    elevation_m: float | None = None
    route_base_source: str | None = None
    route_base_feature_id: str | None = None
    route_base_projection_distance_m: float | None = None


def haversine_m(a: RoutePoint, b: RoutePoint) -> float:
    lat1 = radians(a.lat)
    lat2 = radians(b.lat)
    dlat = radians(b.lat - a.lat)
    dlon = radians(b.lon - a.lon)
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return EARTH_RADIUS_M * 2 * atan2(sqrt(h), sqrt(1 - h))


def resample_route_points(
    points: list[RoutePoint],
    *,
    interval_m: float = 20.0,
) -> list[ResampledRoutePoint]:
    if not points:
        return []
    if len(points) == 1:
        point = points[0]
        return [ResampledRoutePoint(**point.__dict__, distance_m=0.0)]
    cumulative = [0.0]
    for previous, current in zip(points, points[1:]):
        cumulative.append(cumulative[-1] + haversine_m(previous, current))
    total = cumulative[-1]
    targets = list(_distance_targets(total, interval_m))
    output: list[ResampledRoutePoint] = []
    segment_index = 0
    for target in targets:
        while segment_index < len(cumulative) - 2 and cumulative[segment_index + 1] < target:
            segment_index += 1
        start = points[segment_index]
        end = points[segment_index + 1]
        d0 = cumulative[segment_index]
        d1 = cumulative[segment_index + 1]
        ratio = 0.0 if d1 == d0 else (target - d0) / (d1 - d0)
        elevation = None
        if start.elevation_m is not None and end.elevation_m is not None:
            elevation = start.elevation_m + ratio * (end.elevation_m - start.elevation_m)
        output.append(
            ResampledRoutePoint(
                lat=start.lat + ratio * (end.lat - start.lat),
                lon=start.lon + ratio * (end.lon - start.lon),
                elevation_m=elevation,
                time=None,
                name=None,
                distance_m=target,
            )
        )
    return output


def gpx_points_to_dem_xy(
    points: list[ResampledRoutePoint],
    *,
    dem_crs: str | None,
) -> list[XYRoutePoint]:
    if _is_geographic_crs(dem_crs):
        return [
            XYRoutePoint(
                x=point.lon,
                y=point.lat,
                distance_m=point.distance_m,
                lat=point.lat,
                lon=point.lon,
                elevation_m=point.elevation_m,
            )
            for point in points
        ]
    try:
        from pyproj import Transformer
    except ImportError as exc:
        raise ImportError(
            "Projected DEM + GPX sampling requires pyproj. For synthetic tests use "
            "XYRoutePoint or a DEM CRS of EPSG:4326."
        ) from exc
    transformer = Transformer.from_crs("EPSG:4326", dem_crs, always_xy=True)
    output: list[XYRoutePoint] = []
    for point in points:
        x, y = transformer.transform(point.lon, point.lat)
        output.append(
            XYRoutePoint(
                x=float(x),
                y=float(y),
                distance_m=point.distance_m,
                lat=point.lat,
                lon=point.lon,
                elevation_m=point.elevation_m,
            )
        )
    return output


def _distance_targets(total_m: float, interval_m: float) -> list[float]:
    if interval_m <= 0:
        raise ValueError("sample interval must be positive")
    values: list[float] = []
    distance = 0.0
    while distance < total_m:
        values.append(distance)
        distance += interval_m
    if not values or values[-1] < total_m:
        values.append(total_m)
    return values


def _is_geographic_crs(crs: str | None) -> bool:
    if crs is None or not crs:
        return True
    normalized = crs.upper()
    return "4326" in normalized or "WGS84" in normalized or "WGS 84" in normalized
