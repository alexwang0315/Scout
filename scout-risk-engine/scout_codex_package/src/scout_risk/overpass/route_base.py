from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scout_risk.geo import haversine_m, local_xy_m
from scout_risk.gpx.parser import RoutePoint, load_gpx_points
from scout_risk.gpx.sampling import resample_route_points

ROUTE_BASE_SAMPLING_STRATEGY = (
    "reference_progress_projected_to_nearest_overpass_segment.v1"
)


@dataclass(frozen=True)
class OverpassRouteBase:
    route_id: str
    points: list[RoutePoint]
    metadata: dict[str, Any]
    sample_metadata: list[dict[str, Any]]


@dataclass(frozen=True)
class _TrailSegment:
    feature_id: str
    feature_index: int
    segment_index: int
    start_lat: float
    start_lon: float
    end_lat: float
    end_lon: float
    ax: float
    ay: float
    bx: float
    by: float

    @property
    def min_x(self) -> float:
        return min(self.ax, self.bx)

    @property
    def max_x(self) -> float:
        return max(self.ax, self.bx)

    @property
    def min_y(self) -> float:
        return min(self.ay, self.by)

    @property
    def max_y(self) -> float:
        return max(self.ay, self.by)


@dataclass(frozen=True)
class _SegmentProjection:
    lat: float
    lon: float
    distance_m: float
    feature_id: str
    feature_index: int
    segment_index: int


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
    ref_lat = reference_xy[0][2]
    trail_segments, trail_feature_count = _trail_segments_from_overpass(
        overpass,
        ref_lat=ref_lat,
    )
    if not trail_segments:
        raise ValueError("Overpass evidence has no trail corridor LineString geometry")

    projected: list[tuple[RoutePoint, dict[str, Any]]] = []
    projected_distances: list[float] = []
    selected_feature_ids: set[str] = set()
    projected_reference_sample_count = 0
    fallback_reference_sample_count = 0

    for reference_point in reference_points:
        projection = _nearest_trail_segment_projection(
            reference_point,
            trail_segments=trail_segments,
            corridor_m=corridor_m,
            ref_lat=ref_lat,
        )
        if projection is None:
            fallback_reference_sample_count += 1
            projected.append(
                (
                    RoutePoint(
                        lat=reference_point.lat,
                        lon=reference_point.lon,
                        elevation_m=reference_point.elevation_m,
                    ),
                    {
                        "route_base_source": "reference_gpx_gap_fallback",
                        "route_base_feature_id": None,
                        "route_base_projection_distance_m": None,
                        "reference_distance_m": float(
                            getattr(reference_point, "distance_m", 0.0)
                        ),
                    },
                )
            )
            continue
        projected_reference_sample_count += 1
        projected_distances.append(projection.distance_m)
        selected_feature_ids.add(projection.feature_id)
        projected.append(
            (
                RoutePoint(
                    lat=projection.lat,
                    lon=projection.lon,
                    elevation_m=reference_point.elevation_m,
                ),
                {
                    "route_base_source": "overpass_projection",
                    "route_base_feature_id": projection.feature_id,
                    "route_base_projection_distance_m": round(
                        projection.distance_m,
                        3,
                    ),
                    "reference_distance_m": float(
                        getattr(reference_point, "distance_m", 0.0)
                    ),
                },
            )
        )

    if not selected_feature_ids:
        raise ValueError(
            "No Overpass trail corridor geometry matched the reference GPX corridor; "
            "increase --corridor-m or verify the Overpass evidence."
        )

    points, sample_metadata = _dedupe_ordered_entries(projected)
    if len(points) < 2:
        raise ValueError("Overpass route base produced fewer than two route points")

    vector_only = fallback_reference_sample_count == 0
    metadata = {
        "route_base": "overpass_vector_evidence",
        "sampling_strategy": ROUTE_BASE_SAMPLING_STRATEGY,
        "reference_gpx_used_as": (
            "weak_alignment_prior_only"
            if vector_only
            else "weak_alignment_prior_with_gap_fallback"
        ),
        "reference_gpx_not_used_as_route_centerline": vector_only,
        "route_base_is_overpass_vector_evidence": vector_only,
        "route_base_vector_evidence_coverage": "complete" if vector_only else "partial",
        "overpass_geojson_ref": str(overpass_path),
        "reference_gpx_ref": str(reference_path),
        "corridor_m": corridor_m,
        "reference_interval_m": reference_interval_m,
        "reference_sample_count": len(reference_points),
        "trail_feature_count": trail_feature_count,
        "trail_segment_count": len(trail_segments),
        "selected_feature_count": len(selected_feature_ids),
        "selected_projection_count": projected_reference_sample_count,
        "selected_vertex_count": projected_reference_sample_count,
        "projected_reference_sample_count": projected_reference_sample_count,
        "fallback_reference_sample_count": fallback_reference_sample_count,
        "route_point_count": len(points),
        "selected_feature_ids": sorted(selected_feature_ids),
        "median_reference_distance_m": _median(projected_distances),
        "max_reference_distance_m": (
            round(max(projected_distances), 3) if projected_distances else 0.0
        ),
        "candidate_only": True,
    }
    return OverpassRouteBase(
        route_id=route_id,
        points=points,
        metadata=metadata,
        sample_metadata=sample_metadata,
    )


def _trail_segments_from_overpass(
    overpass: dict[str, Any],
    *,
    ref_lat: float,
) -> tuple[list[_TrailSegment], int]:
    segments: list[_TrailSegment] = []
    trail_feature_count = 0
    for feature_index, feature in enumerate(overpass.get("features", [])):
        properties = feature.get("properties", {})
        if properties.get("candidate_type") != "trail_corridor_candidate":
            continue
        geometry = feature.get("geometry", {})
        lines = _geometry_lines(geometry)
        if not lines:
            continue
        trail_feature_count += 1
        feature_id = str(
            properties.get("id")
            or properties.get("osm_id")
            or properties.get("@id")
            or trail_feature_count
        )
        for line in lines:
            for segment_index, (start, end) in enumerate(zip(line, line[1:])):
                segment = _trail_segment_from_coords(
                    start,
                    end,
                    feature_id=feature_id,
                    feature_index=feature_index,
                    segment_index=segment_index,
                    ref_lat=ref_lat,
                )
                if segment is not None:
                    segments.append(segment)
    return segments, trail_feature_count


def _geometry_lines(geometry: dict[str, Any]) -> list[list[Any]]:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if geometry_type == "LineString" and isinstance(coordinates, list):
        return [coordinates]
    if geometry_type == "MultiLineString" and isinstance(coordinates, list):
        return [line for line in coordinates if isinstance(line, list)]
    return []


def _trail_segment_from_coords(
    start: Any,
    end: Any,
    *,
    feature_id: str,
    feature_index: int,
    segment_index: int,
    ref_lat: float,
) -> _TrailSegment | None:
    if not (
        isinstance(start, list | tuple)
        and isinstance(end, list | tuple)
        and len(start) >= 2
        and len(end) >= 2
    ):
        return None
    try:
        start_lon, start_lat = float(start[0]), float(start[1])
        end_lon, end_lat = float(end[0]), float(end[1])
    except (TypeError, ValueError):
        return None
    ax, ay = local_xy_m(start_lat, start_lon, ref_lat)
    bx, by = local_xy_m(end_lat, end_lon, ref_lat)
    if ax == bx and ay == by:
        return None
    return _TrailSegment(
        feature_id=feature_id,
        feature_index=feature_index,
        segment_index=segment_index,
        start_lat=start_lat,
        start_lon=start_lon,
        end_lat=end_lat,
        end_lon=end_lon,
        ax=ax,
        ay=ay,
        bx=bx,
        by=by,
    )


def _nearest_trail_segment_projection(
    reference_point: RoutePoint,
    *,
    trail_segments: list[_TrailSegment],
    corridor_m: float,
    ref_lat: float,
) -> _SegmentProjection | None:
    px, py = local_xy_m(reference_point.lat, reference_point.lon, ref_lat)
    best: _SegmentProjection | None = None
    for segment in trail_segments:
        if (
            px < segment.min_x - corridor_m
            or px > segment.max_x + corridor_m
            or py < segment.min_y - corridor_m
            or py > segment.max_y + corridor_m
        ):
            continue
        projection = _project_point_to_trail_segment(px, py, segment)
        if projection.distance_m > corridor_m:
            continue
        if best is None or projection.distance_m < best.distance_m:
            best = projection
    return best


def _project_point_to_trail_segment(
    px: float,
    py: float,
    segment: _TrailSegment,
) -> _SegmentProjection:
    dx = segment.bx - segment.ax
    dy = segment.by - segment.ay
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        t = 0.0
    else:
        t = max(0.0, min(1.0, ((px - segment.ax) * dx + (py - segment.ay) * dy) / length_sq))
    proj_x = segment.ax + t * dx
    proj_y = segment.ay + t * dy
    distance_m = ((px - proj_x) ** 2 + (py - proj_y) ** 2) ** 0.5
    return _SegmentProjection(
        lat=segment.start_lat + t * (segment.end_lat - segment.start_lat),
        lon=segment.start_lon + t * (segment.end_lon - segment.start_lon),
        distance_m=distance_m,
        feature_id=segment.feature_id,
        feature_index=segment.feature_index,
        segment_index=segment.segment_index,
    )


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


def _dedupe_ordered_entries(
    entries: list[tuple[RoutePoint, dict[str, Any]]],
) -> tuple[list[RoutePoint], list[dict[str, Any]]]:
    points: list[RoutePoint] = []
    metadata: list[dict[str, Any]] = []
    seen: set[tuple[float, float]] = set()
    for point, item_metadata in entries:
        key = (round(point.lat, 7), round(point.lon, 7))
        if key in seen:
            continue
        if points and haversine_m(points[-1].lat, points[-1].lon, point.lat, point.lon) < 1.0:
            continue
        seen.add(key)
        points.append(point)
        metadata.append(item_metadata)
    return points, metadata


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    midpoint = len(sorted_values) // 2
    if len(sorted_values) % 2:
        return round(sorted_values[midpoint], 3)
    return round((sorted_values[midpoint - 1] + sorted_values[midpoint]) / 2.0, 3)
