from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from checkpoint_manager import CheckpointArrival, CheckpointManager
from incident_package import IncidentPackageBuilder
from mission_graph import MissionGraphRuntime, load_mission_graph
from mission_progress import MissionProgressTracker, MissionProgressUpdate
from mission_models import SegmentCapsule
from pdr_fallback import PdrFallbackEstimator, PositionEstimate
from route_matching import RoutePoint, load_gpx_route
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


def replay_route(mission_graph_path: Path | str, route_path: Path | str) -> ReplayResult:
    mission_path = Path(mission_graph_path)
    runtime = MissionGraphRuntime(load_mission_graph(mission_path))
    planned_route = load_gpx_route(_resolve_route_source(mission_path, runtime.graph.route_source))
    route = load_gpx_route(route_path)
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
            },
        )
        incident_package_builder.observe(observation)
        arrival = checkpoint_manager.observe(observation)
        if arrival is not None:
            checkpoint_hits.append(arrival)
        progress_update = progress_tracker.observe(observation)
        if progress_update is not None:
            progress_updates.append(progress_update)
        progress_sample = _route_progress_sample(
            timestamp=float(index),
            point=point,
            position_estimate=position_estimate,
        )
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


def _route_progress_sample(
    *,
    timestamp: float,
    point: RoutePoint,
    position_estimate: PositionEstimate,
) -> RouteProgressSample:
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
    )
