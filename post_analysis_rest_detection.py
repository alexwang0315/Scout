from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from geo_utils import haversine_m
from post_analysis_capability_models import RestDetectionPolicy, RestInterval
from route_matching import RoutePoint


@dataclass(frozen=True)
class TimedRoutePoint:
    index: int
    point: RoutePoint
    timestamp: datetime | None
    offset_s: int | None


def parse_gpx_time(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def timed_route_points(points: list[RoutePoint]) -> list[TimedRoutePoint]:
    parsed = [parse_gpx_time(point.timestamp) for point in points]
    first_time = next((timestamp for timestamp in parsed if timestamp is not None), None)
    timed: list[TimedRoutePoint] = []
    for index, (point, timestamp) in enumerate(zip(points, parsed, strict=True)):
        offset_s = None
        if first_time is not None and timestamp is not None:
            offset_s = int(round((timestamp - first_time).total_seconds()))
        timed.append(TimedRoutePoint(index=index, point=point, timestamp=timestamp, offset_s=offset_s))
    return timed


def detect_rest_intervals(
    points: list[RoutePoint],
    *,
    policy: RestDetectionPolicy,
    source_ref: str,
) -> list[RestInterval]:
    timed = timed_route_points(points)
    rests: list[RestInterval] = []
    candidate_start: int | None = None
    max_radius_m = 0.0
    threshold_mps = policy.rest_speed_threshold_kmh * 1000.0 / 3600.0

    def close_candidate(end_index: int) -> None:
        nonlocal candidate_start, max_radius_m
        if candidate_start is None:
            return
        start = timed[candidate_start]
        end = timed[end_index]
        if start.offset_s is None or end.offset_s is None:
            candidate_start = None
            max_radius_m = 0.0
            return
        duration_s = end.offset_s - start.offset_s
        if duration_s >= policy.min_rest_duration_s:
            rest_points = timed[candidate_start : end_index + 1]
            lat = sum(point.point.lat for point in rest_points) / len(rest_points)
            lon = sum(point.point.lon for point in rest_points) / len(rest_points)
            rest_id = f"rest.{len(rests) + 1:03d}"
            rests.append(
                RestInterval(
                    rest_id=rest_id,
                    start_index=start.index,
                    end_index=end.index,
                    start_offset_s=start.offset_s,
                    end_offset_s=end.offset_s,
                    duration_s=duration_s,
                    lat=round(lat, 7),
                    lon=round(lon, 7),
                    confidence="high" if max_radius_m <= policy.rest_radius_m else "medium",
                    source_refs=[source_ref, f"track_points.{start.index}-{end.index}"],
                )
            )
        candidate_start = None
        max_radius_m = 0.0

    for index in range(1, len(timed)):
        previous = timed[index - 1]
        current = timed[index]
        if previous.timestamp is None or current.timestamp is None:
            close_candidate(index - 1)
            continue
        dt_s = (current.timestamp - previous.timestamp).total_seconds()
        if dt_s <= 0:
            close_candidate(index - 1)
            continue
        step_distance_m = haversine_m(
            previous.point.lat,
            previous.point.lon,
            current.point.lat,
            current.point.lon,
        )
        speed_mps = step_distance_m / dt_s
        if candidate_start is None:
            candidate_anchor = previous.point
        else:
            candidate_anchor = timed[candidate_start].point
        radius_m = haversine_m(
            candidate_anchor.lat,
            candidate_anchor.lon,
            current.point.lat,
            current.point.lon,
        )
        is_rest_step = speed_mps <= threshold_mps and radius_m <= policy.rest_radius_m
        if is_rest_step:
            if candidate_start is None:
                candidate_start = index - 1
                max_radius_m = 0.0
            max_radius_m = max(max_radius_m, radius_m)
            continue
        close_candidate(index - 1)

    close_candidate(len(timed) - 1)
    return rests
