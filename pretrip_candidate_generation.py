from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from geo_utils import haversine_m
from pretrip_models import (
    PreTripArtifactKind,
    PreTripCheckpointCandidate,
    PreTripProvenance,
    PreTripSegmentCandidate,
)
from route_matching import GpxRoute, RoutePoint, load_gpx_route


@dataclass(frozen=True)
class PreTripCandidateGenerationResult:
    checkpoint_candidates: list[PreTripCheckpointCandidate]
    segment_candidates: list[PreTripSegmentCandidate]


def generate_pretrip_candidates_from_gpx(
    gpx_path: Path | str,
    *,
    checkpoint_spacing_m: float = 1_000.0,
    source_ref: str | None = None,
) -> PreTripCandidateGenerationResult:
    if checkpoint_spacing_m <= 0:
        raise ValueError("checkpoint_spacing_m must be greater than 0")

    route = load_gpx_route(gpx_path)
    effective_source_ref = source_ref or Path(gpx_path).name
    provenance = _route_provenance(route, effective_source_ref)
    checkpoints = generate_checkpoint_candidates(
        route,
        checkpoint_spacing_m=checkpoint_spacing_m,
        source_ref=effective_source_ref,
        provenance=provenance,
    )
    segments = generate_segment_candidates(
        route,
        checkpoints,
        source_ref=effective_source_ref,
        provenance=provenance,
    )
    return PreTripCandidateGenerationResult(
        checkpoint_candidates=checkpoints,
        segment_candidates=segments,
    )


def generate_checkpoint_candidates(
    route: GpxRoute,
    *,
    checkpoint_spacing_m: float = 1_000.0,
    source_ref: str | None = None,
    provenance: PreTripProvenance | None = None,
) -> list[PreTripCheckpointCandidate]:
    if checkpoint_spacing_m <= 0:
        raise ValueError("checkpoint_spacing_m must be greater than 0")
    if not route.points:
        raise ValueError("route must contain at least one point")

    effective_source_ref = source_ref or route.source.name
    effective_provenance = provenance or _route_provenance(route, effective_source_ref)
    selected_indices = _checkpoint_route_indices(route.points, checkpoint_spacing_m)
    finish_position = len(selected_indices) - 1

    candidates: list[PreTripCheckpointCandidate] = []
    interior_number = 1
    for position, route_index in enumerate(selected_indices):
        point = route.points[route_index]
        if position == 0:
            candidate_id = "cp.start"
            label = "Start"
            checkpoint_type = "start"
        elif position == finish_position:
            candidate_id = "cp.finish"
            label = "Finish"
            checkpoint_type = "finish"
        else:
            candidate_id = f"cp.{interior_number:03d}"
            label = f"CP {interior_number:03d}"
            checkpoint_type = "route_progress"
            interior_number += 1

        candidates.append(
            PreTripCheckpointCandidate(
                candidate_id=candidate_id,
                label=label,
                source_refs=[effective_source_ref],
                provenance=[effective_provenance],
                confidence="high",
                notes="Generated from GPX route distance spacing.",
                lat=point.lat,
                lon=point.lon,
                route_point_index=route_index,
                checkpoint_type=checkpoint_type,
            )
        )

    return candidates


def generate_segment_candidates(
    route: GpxRoute,
    checkpoint_candidates: list[PreTripCheckpointCandidate],
    *,
    source_ref: str | None = None,
    provenance: PreTripProvenance | None = None,
) -> list[PreTripSegmentCandidate]:
    effective_source_ref = source_ref or route.source.name
    effective_provenance = provenance or _route_provenance(route, effective_source_ref)
    segments: list[PreTripSegmentCandidate] = []

    for index, (start, end) in enumerate(zip(checkpoint_candidates, checkpoint_candidates[1:]), start=1):
        if start.route_point_index is None or end.route_point_index is None:
            raise ValueError("checkpoint candidates must include route_point_index")
        if start.route_point_index > end.route_point_index:
            raise ValueError("checkpoint candidates must be ordered by route_point_index")

        distance_m, elevation_gain_m, elevation_loss_m = _route_range_stats(
            route.points,
            start.route_point_index,
            end.route_point_index,
        )
        segments.append(
            PreTripSegmentCandidate(
                candidate_id=f"seg.{index:03d}",
                label=f"Segment {index:03d}",
                source_refs=[effective_source_ref],
                provenance=[effective_provenance],
                confidence="high",
                notes="Generated between adjacent checkpoint candidates.",
                from_candidate_id=start.candidate_id,
                to_candidate_id=end.candidate_id,
                route_point_start_index=start.route_point_index,
                route_point_end_index=end.route_point_index,
                distance_m=distance_m,
                elevation_gain_m=elevation_gain_m,
                elevation_loss_m=elevation_loss_m,
            )
        )

    return segments


def _checkpoint_route_indices(points: list[RoutePoint], checkpoint_spacing_m: float) -> list[int]:
    if len(points) == 1:
        return [0]

    total_distance_m = points[-1].progress_m
    selected = [0]
    target_distance_m = checkpoint_spacing_m
    next_search_index = 1

    while target_distance_m < total_distance_m:
        for index in range(next_search_index, len(points) - 1):
            if points[index].progress_m >= target_distance_m:
                if index != selected[-1]:
                    selected.append(index)
                next_search_index = index + 1
                break
        target_distance_m += checkpoint_spacing_m

    finish_index = len(points) - 1
    if selected[-1] != finish_index:
        selected.append(finish_index)
    return selected


def _route_range_stats(points: list[RoutePoint], start_index: int, end_index: int) -> tuple[float, float, float]:
    distance_m = 0.0
    elevation_gain_m = 0.0
    elevation_loss_m = 0.0

    for previous, current in zip(points[start_index:end_index], points[start_index + 1 : end_index + 1]):
        distance_m += haversine_m(previous.lat, previous.lon, current.lat, current.lon)
        if previous.elevation_m is None or current.elevation_m is None:
            continue
        delta_elevation_m = current.elevation_m - previous.elevation_m
        if delta_elevation_m >= 0:
            elevation_gain_m += delta_elevation_m
        else:
            elevation_loss_m += abs(delta_elevation_m)

    return distance_m, elevation_gain_m, elevation_loss_m


def _route_provenance(route: GpxRoute, source_ref: str) -> PreTripProvenance:
    return PreTripProvenance(
        source_ref=source_ref,
        source_kind=PreTripArtifactKind.GPX,
        uri=str(route.source),
        method="pretrip_candidate_generation.generate_pretrip_candidates_from_gpx",
        notes="Deterministic distance-spaced checkpoint and adjacent segment candidate generation.",
    )
