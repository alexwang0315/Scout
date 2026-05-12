from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from checkpoint_manager import CheckpointArrival, CheckpointManager
from go_no_go import GoNoGoEvaluation, GoNoGoEvaluator, MissionContext
from incident_package import IncidentPackageBuilder
from incident_store import IncidentStore
from mission_graph import MissionGraphRuntime, load_mission_graph
from mission_progress import MissionProgressTracker, MissionProgressUpdate
from mission_models import SegmentCapsule
from offline_map import OfflineMapContext, load_offline_map_context
from offline_map_models import CorridorEvidence
from pdr_fallback import PdrFallbackEstimator, PositionEstimate
from provider_context import (
    MissionProviderBundle,
    load_fixture_provider_bundle,
    mission_context_from_providers,
    provider_evidence,
)
from recording_policy_runtime import RecordingPolicyDecision, RecordingPolicyRuntime
from risk_rules import RiskRuleEvaluator, load_risk_rules
from route_matching import GpxRoute, RoutePoint, load_gpx_route
from route_progress import RouteProgressConfig, RouteProgressEvaluator, RouteProgressSample, load_route_progress_config
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
    recording_decisions: list[RecordingPolicyDecision]
    stored_incident_paths: list[Path]


def replay_route(
    mission_graph_path: Path | str,
    route_path: Path | str,
    map_context_path: Path | str | None = None,
    risk_rules_path: Path | str | None = None,
    mission_context_path: Path | str | None = None,
    mission_provider_bundle: MissionProviderBundle | None = None,
    route_progress_config: RouteProgressConfig | None = None,
    route_progress_config_path: Path | str | None = None,
    incident_store_path: Path | str | None = None,
) -> ReplayResult:
    mission_path = Path(mission_graph_path)
    runtime = MissionGraphRuntime(load_mission_graph(mission_path))
    planned_route_path = _resolve_route_source(mission_path, runtime.graph.route_source)
    planned_route = load_gpx_route(planned_route_path)
    route = load_gpx_route(route_path)
    offline_map_context = _load_map_context(mission_path, planned_route_path, map_context_path)
    risk_rule_evaluator = _load_risk_rule_evaluator(mission_path, planned_route_path, risk_rules_path)
    if mission_provider_bundle is None and mission_context_path is not None:
        mission_provider_bundle = load_fixture_provider_bundle(mission_context_path)
    if route_progress_config is None and route_progress_config_path is not None:
        route_progress_config = load_route_progress_config(route_progress_config_path)
    go_no_go_evaluator = GoNoGoEvaluator()
    incident_store = IncidentStore(incident_store_path) if incident_store_path is not None else None
    pdr_fallback = PdrFallbackEstimator(planned_route)
    recording_policy_runtime = RecordingPolicyRuntime(runtime)
    checkpoint_manager = CheckpointManager(runtime)
    progress_tracker = MissionProgressTracker(runtime)
    route_progress_evaluator = RouteProgressEvaluator(
        runtime,
        planned_route,
        config=route_progress_config,
        risk_rule_evaluator=risk_rule_evaluator,
    )
    safety_state_machine = SafetyStateMachine()
    incident_package_builder = IncidentPackageBuilder(raw_window_seconds=_max_raw_ring_seconds(runtime))
    checkpoint_hits: list[CheckpointArrival] = []
    progress_updates: list[MissionProgressUpdate] = []
    incident_packages: list[IncidentPackage] = []
    recording_decisions: list[RecordingPolicyDecision] = []
    stored_incident_paths: list[Path] = []

    matched_route_index: int | None = None
    go_no_go_evaluated = False
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
        go_no_go_result = _go_no_go_evaluation(
            runtime=runtime,
            mission_provider_bundle=mission_provider_bundle,
            evaluator=go_no_go_evaluator,
            timestamp=float(index),
            already_evaluated=go_no_go_evaluated,
            observation=observation,
        )
        if go_no_go_result is not None:
            go_no_go_evaluated = True
        go_no_go_evaluation = go_no_go_result.evaluation if go_no_go_result is not None else None
        observation.raw["go_no_go"] = _go_no_go_raw(go_no_go_evaluation)
        observation.raw["provider_context"] = (
            provider_evidence(go_no_go_result.mission_context) if go_no_go_result is not None else None
        )
        arrival = checkpoint_manager.observe(observation)
        if arrival is not None:
            checkpoint_hits.append(arrival)
        progress_update = progress_tracker.observe(observation)
        if progress_update is not None:
            progress_updates.append(progress_update)
        safety_event = route_progress_evaluator.observe(progress_sample, progress_tracker.expected_checkpoint_id)
        pending_events = [
            event
            for event in [
                safety_event,
                go_no_go_evaluation.safety_event if go_no_go_evaluation is not None else None,
            ]
            if event is not None
        ]
        recording_decision = recording_policy_runtime.decide(
            timestamp=float(index),
            route_index=position_estimate.route_index,
            current_safety_level=safety_state_machine.state.level,
            pending_events=pending_events,
            segment_id=_active_segment_id(runtime, progress_tracker),
        )
        recording_decisions.append(recording_decision)
        observation.raw["recording_policy"] = recording_decision.model_dump(mode="json")
        updated_incident_packages = incident_package_builder.observe(observation)
        _persist_updated_incidents(
            updated_incident_packages,
            incident_store=incident_store,
            stored_incident_paths=stored_incident_paths,
        )
        if safety_event is not None:
            _record_safety_event(
                safety_event=safety_event,
                progress_tracker=progress_tracker,
                safety_state_machine=safety_state_machine,
                incident_package_builder=incident_package_builder,
                incident_packages=incident_packages,
                raw_window_seconds=recording_decision.raw_ring_seconds,
                incident_store=incident_store,
                stored_incident_paths=stored_incident_paths,
            )
        if go_no_go_evaluation is not None and go_no_go_evaluation.safety_event is not None:
            _record_safety_event(
                safety_event=go_no_go_evaluation.safety_event,
                progress_tracker=progress_tracker,
                safety_state_machine=safety_state_machine,
                incident_package_builder=incident_package_builder,
                incident_packages=incident_packages,
                raw_window_seconds=recording_decision.raw_ring_seconds,
                incident_store=incident_store,
                stored_incident_paths=stored_incident_paths,
            )

    _persist_updated_incidents(
        incident_packages,
        incident_store=incident_store,
        stored_incident_paths=stored_incident_paths,
    )

    return ReplayResult(
        observations_processed=len(route.points),
        checkpoint_hits=checkpoint_hits,
        segment_capsules=progress_tracker.segment_capsules,
        progress_updates=progress_updates,
        safety_events=progress_tracker.safety_events,
        safety_state=safety_state_machine.state,
        incident_packages=incident_packages,
        recording_decisions=recording_decisions,
        stored_incident_paths=stored_incident_paths,
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


def _load_risk_rule_evaluator(
    mission_graph_path: Path,
    planned_route_path: Path,
    risk_rules_path: Path | str | None,
) -> RiskRuleEvaluator | None:
    if risk_rules_path is not None:
        return RiskRuleEvaluator(load_risk_rules(risk_rules_path))

    default_name = f"{planned_route_path.stem}_rules.json"
    candidates = [
        Path.cwd() / "tests" / "fixtures" / "risk_rules" / default_name,
        mission_graph_path.parent.parent / "risk_rules" / default_name,
        mission_graph_path.parent.parent.parent / "tests" / "fixtures" / "risk_rules" / default_name,
    ]
    for candidate in candidates:
        if candidate.exists():
            return RiskRuleEvaluator(load_risk_rules(candidate))
    return None


@dataclass(frozen=True)
class GoNoGoProviderResult:
    evaluation: GoNoGoEvaluation
    mission_context: MissionContext


def _go_no_go_evaluation(
    *,
    runtime: MissionGraphRuntime,
    mission_provider_bundle: MissionProviderBundle | None,
    evaluator: GoNoGoEvaluator,
    timestamp: float,
    already_evaluated: bool,
    observation: Observation | None = None,
) -> GoNoGoProviderResult | None:
    if mission_provider_bundle is None or already_evaluated:
        return None

    mission_context = mission_context_from_providers(mission_provider_bundle, observation=observation)
    segment_id = mission_context.route_context.get("current_segment_id")
    if not segment_id:
        return None

    segment = runtime.current_segment(segment_id)
    return GoNoGoProviderResult(
        evaluation=evaluator.evaluate(segment, mission_context, timestamp=timestamp),
        mission_context=mission_context,
    )


def _go_no_go_raw(evaluation: GoNoGoEvaluation | None) -> dict | None:
    if evaluation is None:
        return None

    return {
        "decision": evaluation.decision.model_dump(mode="json"),
        "safety_event": evaluation.safety_event.model_dump(mode="json") if evaluation.safety_event else None,
    }


def _record_safety_event(
    *,
    safety_event: SafetyEvent,
    progress_tracker: MissionProgressTracker,
    safety_state_machine: SafetyStateMachine,
    incident_package_builder: IncidentPackageBuilder,
    incident_packages: list[IncidentPackage],
    raw_window_seconds: int,
    incident_store: IncidentStore | None,
    stored_incident_paths: list[Path],
) -> None:
    progress_tracker.safety_events.append(safety_event)
    safety_state_machine.apply_event(safety_event)
    incident_package = incident_package_builder.build_for_event(
        safety_event,
        segment_capsules=progress_tracker.segment_capsules,
        safety_transitions=safety_state_machine.state.transitions,
        raw_window_seconds=raw_window_seconds,
    )
    if incident_package is not None:
        incident_packages.append(incident_package)
        if incident_store is not None:
            _save_incident_package(
                incident_package,
                incident_store=incident_store,
                stored_incident_paths=stored_incident_paths,
            )


def _persist_updated_incidents(
    incident_packages: list[IncidentPackage],
    *,
    incident_store: IncidentStore | None,
    stored_incident_paths: list[Path],
) -> None:
    if incident_store is None:
        return
    for incident_package in incident_packages:
        _save_incident_package(
            incident_package,
            incident_store=incident_store,
            stored_incident_paths=stored_incident_paths,
        )


def _save_incident_package(
    incident_package: IncidentPackage,
    *,
    incident_store: IncidentStore,
    stored_incident_paths: list[Path],
) -> None:
    path = incident_store.save(incident_package)
    if path not in stored_incident_paths:
        stored_incident_paths.append(path)


def _active_segment_id(runtime: MissionGraphRuntime, progress_tracker: MissionProgressTracker) -> str | None:
    current_checkpoint_id = progress_tracker.current_checkpoint_id
    expected_checkpoint_id = progress_tracker.expected_checkpoint_id
    if current_checkpoint_id is None or expected_checkpoint_id is None:
        return None

    segment = runtime.segment_between(current_checkpoint_id, expected_checkpoint_id)
    return segment.segment_id if segment is not None else None


def _max_raw_ring_seconds(runtime: MissionGraphRuntime) -> int:
    if not runtime.graph.recording_policies:
        return 300
    return max(policy.raw_ring_seconds for policy in runtime.graph.recording_policies)


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
