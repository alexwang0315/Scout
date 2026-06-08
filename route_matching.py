from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from geo_utils import haversine_m
from safety_models import Observation


@dataclass(frozen=True)
class RoutePoint:
    lat: float
    lon: float
    elevation_m: float | None = None
    timestamp: str | None = None
    progress_m: float = 0.0
    gps_horizontal_accuracy_m: float | None = None
    course_deg: float | None = None
    pedometer_distance_m: float | None = None
    pedometer_steps: int | None = None


@dataclass(frozen=True)
class GpxRoute:
    source: Path
    points: list[RoutePoint]


@dataclass(frozen=True)
class RouteMatch:
    route_index: int
    distance_m: float
    confidence: float
    point: RoutePoint


def _namespace(root: ET.Element) -> dict[str, str]:
    if root.tag.startswith("{"):
        return {"g": root.tag[1:].split("}", 1)[0]}
    return {"g": "http://www.topografix.com/GPX/1/1"}


def _float_or_none(value: str | None) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _extension_float(trkpt: ET.Element, local_name: str) -> float | None:
    for element in trkpt.iter():
        if element.tag.rsplit("}", 1)[-1] == local_name:
            return _float_or_none(element.text)
    return None


def load_gpx_route(path: Path | str) -> GpxRoute:
    source = Path(path)
    root = ET.parse(source).getroot()
    ns = _namespace(root)
    points: list[RoutePoint] = []
    previous_point: RoutePoint | None = None
    progress_m = 0.0
    for trkpt in root.findall(".//g:trkpt", ns):
        lat = float(trkpt.attrib["lat"])
        lon = float(trkpt.attrib["lon"])
        elevation = _float_or_none(trkpt.findtext("g:ele", namespaces=ns))
        timestamp = trkpt.findtext("g:time", namespaces=ns)
        gps_horizontal_accuracy = _extension_float(trkpt, "locationHorizontalAccuracy")
        course = _extension_float(trkpt, "locationCourse")
        pedometer_distance = _extension_float(trkpt, "pedometerDistance")
        pedometer_steps = _extension_float(trkpt, "pedometerNumberOfSteps")
        if previous_point is not None:
            progress_m += haversine_m(previous_point.lat, previous_point.lon, lat, lon)
        point = RoutePoint(
            lat=lat,
            lon=lon,
            elevation_m=elevation,
            timestamp=timestamp,
            progress_m=progress_m,
            gps_horizontal_accuracy_m=gps_horizontal_accuracy,
            course_deg=course if course is not None and course >= 0 else None,
            pedometer_distance_m=pedometer_distance,
            pedometer_steps=int(pedometer_steps) if pedometer_steps is not None else None,
        )
        points.append(point)
        previous_point = point
    if not points:
        raise ValueError(f"No GPX track points found: {source}")
    return GpxRoute(source=source, points=points)


def confidence_from_distance(distance_m: float, threshold_m: float = 50.0) -> float:
    return max(0.0, min(1.0, 1.0 - (distance_m / threshold_m)))


def match_observation_to_route(observation: Observation, route: GpxRoute) -> RouteMatch:
    if observation.lat is None or observation.lon is None:
        raise ValueError("Observation must include lat/lon for route matching")

    return match_point_to_route(observation.lat, observation.lon, route)


def match_point_to_route(
    lat: float,
    lon: float,
    route: GpxRoute,
    *,
    center_index: int | None = None,
    search_radius: int = 60,
) -> RouteMatch:
    best_index = 0
    best_distance = float("inf")
    if center_index is None:
        start = 0
        end = len(route.points)
    else:
        start = max(0, center_index - search_radius)
        end = min(len(route.points), center_index + search_radius + 1)

    for index in range(start, end):
        point = route.points[index]
        distance = haversine_m(lat, lon, point.lat, point.lon)
        if distance < best_distance:
            best_distance = distance
            best_index = index

    return RouteMatch(
        route_index=best_index,
        distance_m=best_distance,
        confidence=confidence_from_distance(best_distance),
        point=route.points[best_index],
    )
