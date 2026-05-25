from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scout_risk.geo import haversine_m, local_xy_m
from scout_risk.gpx.parser import RoutePoint, load_gpx_points
from scout_risk.gpx.sampling import resample_route_points


@dataclass(frozen=True)
class OverpassRouteBase:
    route_id: str
    points: list[RoutePoint]
    metadata: dict[str, Any]


def build_overpass_route_base(
    *,
    overpass_geojson_path: str | Path,
    reference_gpx_path: str | Path,
    route_id: str = "overpass_aligned_route",
    corridor_m: float = 35.0,
    reference_interval_m: float = 20.0,
) -> OverpassRouteBase:
    """Build an OSM route base using GPX only as a weak alignment prior."""

    overpass_path = Path(overpass_geojson_path)
    reference_path = Path(reference_gpx_path)
    overpass = json.loads(overpass_path.read_text(encoding="utf-8"))
    reference_points = resample_route_points(
        load_gpx_points(reference_path),
        interval_m=reference_interval_m,
    )
    reference_xy = _reference_xy(reference_points)
    selected: list[tuple[float, int, RoutePoint, str, float]] = []
    trail_feature_count = 0
    selected_feature_ids: set[str] = set()

    for feature in overpass.get("features", []):
        properties = feature.get("properties", {})
        if properties.get("candidate_type") != "trail_corridor_candidate":
            continue
        geometry = feature.get("geometry", {})
        if geometry.get("type") != "LineString":
            continue
        coords = geometry.get("coordinates", [])
        if len(coords) < 2:
            continue
        trail_feature_count += 1
        feature_id = str(properties.get("id") or properties.get("osm_id") or trail_feature_count)
        for coord_index, coordinate in enumerate(coords):
            if len(coordinate) < 2:
                continue
            lon, lat = float(coordinate[0]), float(coordinate[1])
            progress_m, distance_m = _nearest_reference_progress(lat, lon, reference_xy)
            if distance_m <= corridor_m:
                selected.append(
                    (
                        progress_m,
                        coord_index,
                        RoutePoint(lat=lat, lon=lon),
                        feature_id,
                        distance_m,
                    )
                )
                selected_feature_ids.add(feature_id)

    if not selected:
        raise ValueError(
            "No Overpass trail corridor geometry matched the reference GPX corridor; "
            "increase --corridor-m or verify the Overpass evidence."
        )

    selected.sort(key=lambda item: (item[0], item[1]))
    points = _dedupe_ordered_points([item[2] for item in selected])
    metadata = {
        "route_base": "overpass_vector_evidence",
        "reference_gpx_used_as": "weak_alignment_prior_only",
        "reference_gpx_not_used_as_route_centerline": True,
        "overpass_geojson_ref": str(overpass_path),
        "reference_gpx_ref": str(reference_path),
        "corridor_m": corridor_m,
        "reference_interval_m": reference_interval_m,
        "trail_feature_count": trail_feature_count,
        "selected_feature_count": len(selected_feature_ids),
        "selected_vertex_count": len(selected),
        "route_point_count": len(points),
        "selected_feature_ids": sorted(selected_feature_ids),
        "median_reference_distance_m": _median([item[4] for item in selected]),
        "max_reference_distance_m": round(max(item[4] for item in selected), 3),
        "candidate_only": True,
    }
    return OverpassRouteBase(route_id=route_id, points=points, metadata=metadata)


def _reference_xy(points: list[RoutePoint]) -> list[tuple[float, float, float, float, float]]:
    if not points:
        raise ValueError("reference GPX has no usable points")
    ref_lat = points[0].lat
    output: list[tuple[float, float, float, float, float]] = []
    for point in points:
        x, y = local_xy_m(point.lat, point.lon, ref_lat)
        distance_m = float(getattr(point, "distance_m", 0.0))
        output.append((x, y, point.lat, point.lon, distance_m))
    return output


def _nearest_reference_progress(
    lat: float,
    lon: float,
    reference_xy: list[tuple[float, float, float, float, float]],
) -> tuple[float, float]:
    ref_lat = reference_xy[0][2]
    px, py = local_xy_m(lat, lon, ref_lat)
    best_distance = float("inf")
    best_progress = 0.0
    for index, current in enumerate(reference_xy[:-1]):
        nxt = reference_xy[index + 1]
        progress, distance = _point_segment_progress_distance(px, py, current, nxt)
        if distance < best_distance:
            best_distance = distance
            best_progress = progress
    return best_progress, best_distance


def _point_segment_progress_distance(
    px: float,
    py: float,
    start: tuple[float, float, float, float, float],
    end: tuple[float, float, float, float, float],
) -> tuple[float, float]:
    ax, ay, _, _, start_progress = start
    bx, by, _, _, end_progress = end
    dx = bx - ax
    dy = by - ay
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return start_progress, ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    proj_x = ax + t * dx
    proj_y = ay + t * dy
    distance = ((px - proj_x) ** 2 + (py - proj_y) ** 2) ** 0.5
    return start_progress + t * (end_progress - start_progress), distance


def _dedupe_ordered_points(points: list[RoutePoint]) -> list[RoutePoint]:
    output: list[RoutePoint] = []
    seen: set[tuple[float, float]] = set()
    for point in points:
        key = (round(point.lat, 7), round(point.lon, 7))
        if key in seen:
            continue
        if output and haversine_m(output[-1].lat, output[-1].lon, point.lat, point.lon) < 1.0:
            continue
        seen.add(key)
        output.append(point)
    return output


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    midpoint = len(sorted_values) // 2
    if len(sorted_values) % 2:
        return round(sorted_values[midpoint], 3)
    return round((sorted_values[midpoint - 1] + sorted_values[midpoint]) / 2.0, 3)
