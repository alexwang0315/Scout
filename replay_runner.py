from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from checkpoint_manager import CheckpointArrival, CheckpointManager
from incident_package import IncidentPackageBuilder
from mission_graph import MissionGraphRuntime, load_mission_graph
from mission_progress import MissionProgressTracker, MissionProgressUpdate
from mission_models import SegmentCapsule
from offline_map import OfflineMapContext, load_offline_map_context
from offline_map_models import CorridorEvidence
from pdr_fallback import PdrFallbackEstimator, PositionEstimate
from route_matching import GpxRoute, RoutePoint, load_gpx_route
from route_progress import RouteProgressEvaluator, RouteProgressSample
from safety_models import IncidentPackage, Observation, SafetyEvent, SafetyState
from safety_state_machine import SafetyStateMachine


@dataclass(frozen=True)
class ReplayResult:
    observations_processed: int
    checkpoint_hits: list[CheckpointArrival]
    segment_capsules: list[SegmentCapsule]
    progress_updates: list[MissionProgressUpdate]
    safety_events: list[SafetyEvent]
    safety_state: SafetyState
    incident_packages: list[IncidentPackage]


def replay_route(
    mission_graph_path: Path | str,
    route_path: Path | str,
    map_context_path: Path | str | None = None,
) -> ReplayResult:
    mission_path = Path(mission_graph_path)
    runtime = MissionGraphRuntime(load_mission_graph(mission_path))
    planned_route_path = _resolve_route_source(mission_path, runtime.graph.route_source)
    planned_route = load_gpx_route(planned_route_path)
    route = load_gpx_route(route_path)
    offline_map_context = _load_map_context(mission_path, planned_route_path, map_context_path)
    pdr_fallback = PdrFallbackEstimator(planned_route)
    checkpoint_manager = CheckpointManager(runtime)
    progress_tracker = MissionProgressTracker(runtime)
    route_progress_evaluator = RouteProgressEvaluator(runtime, planned_route)
    safety_state_machine = SafetyStateMachine()
    incident_package_builder = IncidentPackageBuilder()
    checkpoint_hits: list[CheckpointArrival] = []
    progress_updates: list[MissionProgressUpdate] = []
    incident_packages: list[IncidentPackage] = []

    matched_route_index: int | None = None
    for index, point in enumerate(route.points):
        position_estimate = pdr_fallback.estimate(
            timestamp=float(index),
            point=point,
            previous_route_index=matched_route_index,
        )
        matched_route_index = position_estimate.route_index
        progress_sample = _route_progress_sample(
            timestamp=float(index),
            point=point,
            position_estimate=position_estimate,
            planned_route=planned_route,
            offline_map_context=offline_map_context,
        )
        observation = Observation(
            timestamp=float(index),
            source="gpx_replay",
            lat=point.lat,
            lon=point.lon,
            elevation_m=point.elevation_m,
            gps_horizontal_accuracy_m=point.gps_horizontal_accuracy_m,
            raw={
                "route_index": index,
                "timestamp": point.timestamp,
                "position_estimate": {
                    "source": position_estimate.source,
                    "progress_m": position_estimate.progress_m,
                    "route_index": position_estimate.route_index,
                    "confidence": position_estimate.confidence,
                    "pdr_delta_m": position_estimate.pdr_delta_m,
                    "gps_reanchor_correction_m": position_estimate.gps_reanchor_correction_m,
                },
                "map_evidence": {
                    "corridor": {
                        "inside": progress_sample.map_corridor_inside,
                        "corridor_id": progress_sample.map_corridor_id,
                        "distance_m": progress_sample.map_corridor_distance_m,
                        "allowed_distance_m": progress_sample.map_corridor_allowed_distance_m,
                        "source_metadata": progress_sample.map_source_metadata,
                    },
                    "hazards": progress_sample.map_hazards or [],
                },
            },
        )
        incident_package_builder.observe(observation)
        arrival = checkpoint_manager.observe(observation)
        if arrival is not None:
            checkpoint_hits.append(arrival)
        progress_update = progress_tracker.observe(observation)
        if progress_update is not None:
            progress_updates.append(progress_update)
        safety_event = route_progress_evaluator.observe(progress_sample, progress_tracker.expected_checkpoint_id)
        if safety_event is not None:
            progress_tracker.safety_events.append(safety_event)
            safety_state_machine.apply_event(safety_event)
            incident_package = incident_package_builder.build_for_event(
                safety_event,
                segment_capsules=progress_tracker.segment_capsules,
                safety_transitions=safety_state_machine.state.transitions,
            )
            if incident_package is not None:
                incident_packages.append(incident_package)

    return ReplayResult(
        observations_processed=len(route.points),
        checkpoint_hits=checkpoint_hits,
        segment_capsules=progress_tracker.segment_capsules,
        progress_updates=progress_updates,
        safety_events=progress_tracker.safety_events,
        safety_state=safety_state_machine.state,
        incident_packages=incident_packages,
    )


def _resolve_route_source(mission_graph_path: Path, route_source: str) -> Path:
    route_path = Path(route_source)
    if route_path.is_absolute():
        return route_path

    candidates = [
        Path.cwd() / route_path,
        mission_graph_path.parent / route_path,
        mission_graph_path.parent.parent.parent / route_path,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _load_map_context(
    mission_graph_path: Path,
    planned_route_path: Path,
    map_context_path: Path | str | None,
) -> OfflineMapContext | None:
    if map_context_path is not None:
        return load_offline_map_context(map_context_path)

    default_name = f"{planned_route_path.stem}_map_context.geojson"
    candidates = [
        Path.cwd() / "tests" / "fixtures" / "maps" / default_name,
        mission_graph_path.parent.parent / "maps" / default_name,
        mission_graph_path.parent.parent.parent / "tests" / "fixtures" / "maps" / default_name,
    ]
    for candidate in candidates:
        if candidate.exists():
            return load_offline_map_context(candidate)
    return None


def _route_progress_sample(
    *,
    timestamp: float,
    point: RoutePoint,
    position_estimate: PositionEstimate,
    planned_route: GpxRoute,
    offline_map_context: OfflineMapContext | None,
) -> RouteProgressSample:
    corridor = _corridor_evidence(
        point=point,
        position_estimate=position_estimate,
        planned_route=planned_route,
        offline_map_context=offline_map_context,
    )
    hazards = _hazard_evidence(
        point=point,
        position_estimate=position_estimate,
        planned_route=planned_route,
        offline_map_context=offline_map_context,
    )
    return RouteProgressSample(
        timestamp=timestamp,
        progress_m=position_estimate.progress_m,
        lat=point.lat,
        lon=point.lon,
        gps_horizontal_accuracy_m=point.gps_horizontal_accuracy_m,
        route_distance_m=position_estimate.route_distance_m,
        route_index=position_estimate.route_index,
        estimate_source=position_estimate.source,
        pdr_delta_m=position_estimate.pdr_delta_m,
        estimate_confidence=position_estimate.confidence,
        map_corridor_inside=corridor.inside if corridor is not None else None,
        map_corridor_id=corridor.corridor_id if corridor is not None else None,
        map_corridor_distance_m=corridor.distance_m if corridor is not None else None,
        map_corridor_allowed_distance_m=corridor.allowed_distance_m if corridor is not None else None,
        map_source_metadata=corridor.source_metadata.model_dump() if corridor and corridor.source_metadata else None,
        map_hazards=hazards,
    )


def _corridor_evidence(
    *,
    point: RoutePoint,
    position_estimate: PositionEstimate,
    planned_route: GpxRoute,
    offline_map_context: OfflineMapContext | None,
) -> CorridorEvidence | None:
    if offline_map_context is None:
        return None

    if position_estimate.source == "pdr_fallback":
        estimate_point = planned_route.points[position_estimate.route_index]
        return offline_map_context.corridor_evidence(estimate_point.lat, estimate_point.lon)

    uncertainty_m = point.gps_horizontal_accuracy_m or 0.0
    return offline_map_context.corridor_evidence(
        point.lat,
        point.lon,
        position_uncertainty_m=uncertainty_m,
    )


def _hazard_evidence(
    *,
    point: RoutePoint,
    position_estimate: PositionEstimate,
    planned_route: GpxRoute,
    offline_map_context: OfflineMapContext | None,
) -> list[dict] | None:
    if offline_map_context is None:
        return None

    if position_estimate.source == "pdr_fallback":
        estimate_point = planned_route.points[position_estimate.route_index]
        hazards = offline_map_context.hazards_at(estimate_point.lat, estimate_point.lon)
    else:
        hazards = offline_map_context.hazards_at(point.lat, point.lon)

    return [hazard.model_dump() for hazard in hazards]
