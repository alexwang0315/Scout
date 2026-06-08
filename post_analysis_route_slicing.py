from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from geo_utils import haversine_m
from route_matching import GpxRoute, RoutePoint


@dataclass(frozen=True)
class CapabilityCheckpoint:
    checkpoint_id: str
    name: str
    lat: float
    lon: float
    source_ref: str
    arrival_radius_m: float = 30.0


@dataclass(frozen=True)
class CapabilitySegmentDefinition:
    segment_id: str
    from_checkpoint_id: str
    to_checkpoint_id: str
    source_ref: str
    direction: str = "outbound"
    distance_m: float | None = None
    ascent_m: float | None = None
    descent_m: float | None = None
    guide_time_min: int | None = None
    terrain_context: dict[str, Any] | None = None
    risk_context: dict[str, Any] | None = None


@dataclass(frozen=True)
class MatchedCheckpoint:
    checkpoint: CapabilityCheckpoint
    route_index: int
    distance_m: float
    confidence: str
    candidate_count: int = 0
    candidate_cluster_count: int = 0


@dataclass(frozen=True)
class RouteSlice:
    segment: CapabilitySegmentDefinition
    from_match: MatchedCheckpoint
    to_match: MatchedCheckpoint
    start_index: int
    end_index: int
    points: list[RoutePoint]
    distance_m: float
    expected_distance_m: float | None
    distance_deviation_ratio: float | None
    ascent_m: float | None
    descent_m: float | None
    confidence: str
    limitations: list[str]
    traversal_status: str = "traversed"


def load_checkpoint_definitions(payload: dict[str, Any]) -> tuple[list[CapabilityCheckpoint], list[CapabilitySegmentDefinition]]:
    checkpoints_payload = payload.get("checkpoints") or payload.get("checkpoint_candidates") or []
    checkpoints = [
        CapabilityCheckpoint(
            checkpoint_id=str(raw.get("checkpoint_id") or raw.get("candidate_id")),
            name=str(raw.get("name") or raw.get("label") or raw.get("checkpoint_id") or raw.get("candidate_id")),
            lat=float(raw["lat"]),
            lon=float(raw["lon"]),
            arrival_radius_m=float(raw.get("arrival_radius_m") or 30.0),
            source_ref=str(raw.get("source_ref") or raw.get("source_id") or raw.get("source") or raw.get("candidate_id") or raw.get("checkpoint_id")),
        )
        for raw in checkpoints_payload
    ]
    segments_payload = payload.get("segments") or payload.get("segment_candidates") or []
    if not segments_payload and len(checkpoints) >= 2:
        segments_payload = [
            {
                "segment_id": f"{checkpoints[index].checkpoint_id}_to_{checkpoints[index + 1].checkpoint_id}",
                "from_checkpoint_id": checkpoints[index].checkpoint_id,
                "to_checkpoint_id": checkpoints[index + 1].checkpoint_id,
                "source_ref": f"derived.segment.{index + 1:03d}",
            }
            for index in range(len(checkpoints) - 1)
        ]
    segments = [
        CapabilitySegmentDefinition(
            segment_id=str(raw.get("segment_id") or raw.get("candidate_id")),
            from_checkpoint_id=str(raw.get("from_checkpoint_id") or raw.get("from_candidate_id")),
            to_checkpoint_id=str(raw.get("to_checkpoint_id") or raw.get("to_candidate_id")),
            source_ref=str(raw.get("source_ref") or raw.get("source_id") or raw.get("candidate_id") or raw.get("segment_id")),
            direction=str(raw.get("direction") or "outbound"),
            distance_m=_optional_float(raw.get("distance_m")),
            ascent_m=_optional_float(raw.get("ascent_m", raw.get("elevation_gain_m"))),
            descent_m=_optional_float(raw.get("descent_m", raw.get("elevation_loss_m"))),
            guide_time_min=_optional_int(
                raw.get("guide_time_min", raw.get("route_guide_segment_time_minutes"))
            ),
            terrain_context=dict(raw.get("terrain_context") or {}),
            risk_context=dict(raw.get("risk_context") or {}),
        )
        for raw in segments_payload
    ]
    return checkpoints, segments


def slice_route_by_checkpoints(
    route: GpxRoute,
    checkpoints: list[CapabilityCheckpoint],
    segments: list[CapabilitySegmentDefinition],
) -> list[RouteSlice]:
    checkpoints_by_id = {checkpoint.checkpoint_id: checkpoint for checkpoint in checkpoints}
    if segments:
        checkpoint_sequence = [segments[0].from_checkpoint_id] + [
            segment.to_checkpoint_id for segment in segments
        ]
    else:
        checkpoint_sequence = [checkpoint.checkpoint_id for checkpoint in checkpoints]
    sequence_matches = _match_checkpoint_sequence_monotonic(
        route,
        [checkpoints_by_id[checkpoint_id] for checkpoint_id in checkpoint_sequence],
    )
    matches_by_id = {
        match.checkpoint.checkpoint_id: match
        for match in sequence_matches
    }
    slices: list[RouteSlice] = []
    for index, segment in enumerate(segments):
        if index + 1 < len(sequence_matches):
            from_match = sequence_matches[index]
            to_match = sequence_matches[index + 1]
        else:
            from_match = matches_by_id[segment.from_checkpoint_id]
            to_match = matches_by_id[segment.to_checkpoint_id]
        start_index = min(from_match.route_index, to_match.route_index)
        end_index = max(from_match.route_index, to_match.route_index)
        points = route.points[start_index : end_index + 1]
        computed_distance_m = _slice_distance(points)
        distance_deviation_ratio = _distance_deviation_ratio(
            computed_distance_m,
            segment.distance_m,
        )
        computed_ascent_m, computed_descent_m = _slice_elevation(points)
        resolved_ascent_m = (
            segment.ascent_m if segment.ascent_m is not None else computed_ascent_m
        )
        resolved_descent_m = (
            segment.descent_m if segment.descent_m is not None else computed_descent_m
        )
        confidence, limitations = _slice_confidence(
            from_match,
            to_match,
            points,
            distance_deviation_ratio,
        )
        slices.append(
            RouteSlice(
                segment=segment,
                from_match=from_match,
                to_match=to_match,
                start_index=start_index,
                end_index=end_index,
                points=points,
                distance_m=round(computed_distance_m, 2),
                expected_distance_m=segment.distance_m,
                distance_deviation_ratio=distance_deviation_ratio,
                ascent_m=round(resolved_ascent_m, 2) if resolved_ascent_m is not None else None,
                descent_m=round(resolved_descent_m, 2) if resolved_descent_m is not None else None,
                confidence=confidence,
                limitations=limitations,
            )
        )
    return _mark_traversal_statuses(slices)


def _mark_traversal_statuses(route_slices: list[RouteSlice]) -> list[RouteSlice]:
    if not route_slices:
        return route_slices
    failed = [_unreached_candidate(route_slice) for route_slice in route_slices]
    run = _first_sustained_failure_run(failed, min_run_length=8)
    if run is None:
        return route_slices
    start, _end = run
    turnaround_index = max(0, start - 1)
    marked: list[RouteSlice] = []
    for index, route_slice in enumerate(route_slices):
        if index < turnaround_index:
            marked.append(route_slice)
        elif index == turnaround_index:
            limitations = sorted(
                set(
                    [
                        *route_slice.limitations,
                        "completed track appears to turn around before the next planned checkpoint",
                    ]
                )
            )
            marked.append(
                replace(route_slice, traversal_status="partial", limitations=limitations)
            )
        else:
            limitations = sorted(
                set(
                    [
                        *route_slice.limitations,
                        "planned segment was not reached by the completed track",
                    ]
                )
            )
            marked.append(
                replace(route_slice, traversal_status="unreached", limitations=limitations)
            )
    return marked


def _unreached_candidate(route_slice: RouteSlice) -> bool:
    expected = route_slice.expected_distance_m or 0.0
    if expected <= 150:
        return False
    index_span = route_slice.end_index - route_slice.start_index
    if index_span <= 1:
        return True
    if route_slice.distance_m < expected * 0.2:
        return True
    if route_slice.from_match.distance_m > 1000 and route_slice.to_match.distance_m > 1000:
        return True
    return False


def _first_sustained_failure_run(
    failed: list[bool],
    *,
    min_run_length: int,
) -> tuple[int, int] | None:
    index = 0
    while index < len(failed):
        if not failed[index]:
            index += 1
            continue
        end = index
        while end < len(failed) and failed[end]:
            end += 1
        if end - index >= min_run_length:
            return index, end - 1
        index = end
    return None


def _match_checkpoint_sequence_monotonic(
    route: GpxRoute,
    checkpoints: list[CapabilityCheckpoint],
) -> list[MatchedCheckpoint]:
    matches: list[MatchedCheckpoint] = []
    start_index = 0
    for checkpoint in checkpoints:
        best_index = start_index
        best_distance = float("inf")
        candidate_indices: list[int] = []
        for index in range(start_index, len(route.points)):
            point = route.points[index]
            distance = haversine_m(checkpoint.lat, checkpoint.lon, point.lat, point.lon)
            if distance < best_distance:
                best_index = index
                best_distance = distance
            if distance <= checkpoint.arrival_radius_m:
                candidate_indices.append(index)
        candidate_cluster_count = _cluster_count(candidate_indices)
        confidence = "high" if best_distance <= checkpoint.arrival_radius_m else "medium"
        if candidate_cluster_count > 1:
            confidence = "medium"
        if best_distance > checkpoint.arrival_radius_m * 2:
            confidence = "low"
        matches.append(
            MatchedCheckpoint(
                checkpoint=checkpoint,
                route_index=best_index,
                distance_m=round(best_distance, 2),
                confidence=confidence,
                candidate_count=len(candidate_indices),
                candidate_cluster_count=candidate_cluster_count,
            )
        )
        start_index = best_index
    return matches


def _match_checkpoints_monotonic(
    route: GpxRoute,
    checkpoints: list[CapabilityCheckpoint],
) -> list[MatchedCheckpoint]:
    return _match_checkpoint_sequence_monotonic(route, checkpoints)


def _slice_distance(points: list[RoutePoint]) -> float:
    if len(points) < 2:
        return 0.0
    return sum(
        haversine_m(previous.lat, previous.lon, current.lat, current.lon)
        for previous, current in zip(points, points[1:], strict=False)
    )


def _slice_elevation(points: list[RoutePoint]) -> tuple[float | None, float | None]:
    ascent = 0.0
    descent = 0.0
    saw_elevation = False
    for previous, current in zip(points, points[1:], strict=False):
        if previous.elevation_m is None or current.elevation_m is None:
            continue
        saw_elevation = True
        delta = current.elevation_m - previous.elevation_m
        if delta >= 0:
            ascent += delta
        else:
            descent += abs(delta)
    if not saw_elevation:
        return None, None
    return ascent, descent


def _slice_confidence(
    from_match: MatchedCheckpoint,
    to_match: MatchedCheckpoint,
    points: list[RoutePoint],
    distance_deviation_ratio: float | None,
) -> tuple[str, list[str]]:
    limitations: list[str] = []
    if len(points) < 2:
        limitations.append("segment has fewer than two completed track points")
    if "low" in {from_match.confidence, to_match.confidence}:
        limitations.append("checkpoint match is outside confidence radius")
    if from_match.candidate_cluster_count > 1 or to_match.candidate_cluster_count > 1:
        limitations.append("checkpoint match has multiple plausible completed-track clusters")
    if any(point.timestamp is None for point in points):
        limitations.append("segment contains missing timestamps")
    if distance_deviation_ratio is not None and distance_deviation_ratio > 0.35:
        limitations.append("completed segment distance deviates from segment definition")
    if len(points) < 2 or "low" in {from_match.confidence, to_match.confidence}:
        return "low", limitations
    if distance_deviation_ratio is not None and distance_deviation_ratio > 0.75:
        return "low", limitations
    if (
        "medium" in {from_match.confidence, to_match.confidence}
        or from_match.candidate_cluster_count > 1
        or to_match.candidate_cluster_count > 1
        or any(point.timestamp is None for point in points)
        or (distance_deviation_ratio is not None and distance_deviation_ratio > 0.35)
    ):
        return "medium", limitations
    return "high", limitations


def _distance_deviation_ratio(
    computed_distance_m: float,
    expected_distance_m: float | None,
) -> float | None:
    if expected_distance_m is None or expected_distance_m <= 0:
        return None
    return round(abs(computed_distance_m - expected_distance_m) / expected_distance_m, 3)


def _cluster_count(indices: list[int]) -> int:
    if not indices:
        return 0
    clusters = 1
    previous = indices[0]
    for index in indices[1:]:
        if index - previous > 1:
            clusters += 1
        previous = index
    return clusters


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)
