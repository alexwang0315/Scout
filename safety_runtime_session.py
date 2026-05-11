from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from checkpoint_manager import CheckpointArrival, CheckpointManager
from go_no_go import GoNoGoEvaluation, GoNoGoEvaluator, MissionContext
from incident_package import IncidentPackageBuilder
from incident_store import IncidentStore
from mission_graph import MissionGraphRuntime, load_mission_graph
from mission_models import SegmentCapsule
from mission_progress import MissionProgressTracker, MissionProgressUpdate
from offline_map import OfflineMapContext
from pdr_fallback import PdrFallbackEstimator, PositionEstimate
from provider_context import (
    MissionProviderBundle,
    load_fixture_provider_bundle,
    mission_context_from_providers,
    provider_evidence,
)
from recording_policy_runtime import RecordingPolicyDecision, RecordingPolicyRuntime
from replay_runner import (
    _active_segment_id,
    _load_map_context,
    _load_risk_rule_evaluator,
    _max_raw_ring_seconds,
    _record_safety_event,
    _resolve_route_source,
    _route_progress_sample,
)
from route_matching import GpxRoute, RoutePoint, load_gpx_route
from route_progress import RouteProgressEvaluator, RouteProgressSample
from safety_models import IncidentPackage, Observation, SafetyEvent, SafetyState
from safety_state_machine import SafetyStateMachine


@dataclass(frozen=True)
class SafetyRuntimeUpdate:
    observation: Observation
    route_progress_sample: RouteProgressSample | None
    checkpoint_arrival: CheckpointArrival | None
    progress_update: MissionProgressUpdate | None
    safety_events: list[SafetyEvent]
    safety_state: SafetyState
    recording_decision: RecordingPolicyDecision
    incident_packages: list[IncidentPackage]
    stored_incident_paths: list[Path]


@dataclass(frozen=True)
class SafetyRuntimeSnapshot:
    observations_processed: int
    checkpoint_hits: list[CheckpointArrival]
    segment_capsules: list[SegmentCapsule]
    progress_updates: list[MissionProgressUpdate]
    safety_events: list[SafetyEvent]
    safety_state: SafetyState
    incident_packages: list[IncidentPackage]
    recording_decisions: list[RecordingPolicyDecision]
    stored_incident_paths: list[Path]


@dataclass(frozen=True)
class GoNoGoProviderResult:
    evaluation: GoNoGoEvaluation
    mission_context: MissionContext


class SafetyRuntimeSession:
    def __init__(
        self,
        mission_graph_path: Path | str,
        *,
        map_context_path: Path | str | None = None,
        risk_rules_path: Path | str | None = None,
        mission_context_path: Path | str | None = None,
        mission_provider_bundle: MissionProviderBundle | None = None,
        incident_store_path: Path | str | None = None,
    ):
        mission_path = Path(mission_graph_path)
        self.runtime = MissionGraphRuntime(load_mission_graph(mission_path))
        self.planned_route_path = _resolve_route_source(mission_path, self.runtime.graph.route_source)
        self.planned_route = load_gpx_route(self.planned_route_path)
        self.offline_map_context = _load_map_context(mission_path, self.planned_route_path, map_context_path)
        self.risk_rule_evaluator = _load_risk_rule_evaluator(mission_path, self.planned_route_path, risk_rules_path)
        if mission_provider_bundle is None and mission_context_path is not None:
            mission_provider_bundle = load_fixture_provider_bundle(mission_context_path)
        self.mission_provider_bundle = mission_provider_bundle
        self.go_no_go_evaluator = GoNoGoEvaluator()
        self.incident_store = IncidentStore(incident_store_path) if incident_store_path is not None else None
        self.pdr_fallback = PdrFallbackEstimator(self.planned_route)
        self.recording_policy_runtime = RecordingPolicyRuntime(self.runtime)
        self.checkpoint_manager = CheckpointManager(self.runtime)
        self.progress_tracker = MissionProgressTracker(self.runtime)
        self.route_progress_evaluator = RouteProgressEvaluator(
            self.runtime,
            self.planned_route,
            risk_rule_evaluator=self.risk_rule_evaluator,
        )
        self.safety_state_machine = SafetyStateMachine()
        self.incident_package_builder = IncidentPackageBuilder(raw_window_seconds=_max_raw_ring_seconds(self.runtime))
        self.checkpoint_hits: list[CheckpointArrival] = []
        self.progress_updates: list[MissionProgressUpdate] = []
        self.incident_packages: list[IncidentPackage] = []
        self.recording_decisions: list[RecordingPolicyDecision] = []
        self.stored_incident_paths: list[Path] = []
        self.observations_processed = 0
        self._matched_route_index: int | None = None
        self._go_no_go_evaluated = False

    def observe(self, observation: Observation) -> SafetyRuntimeUpdate:
        route_point = _route_point_from_observation(observation)
        route_progress_sample: RouteProgressSample | None = None
        checkpoint_arrival: CheckpointArrival | None = None
        progress_update: MissionProgressUpdate | None = None
        pending_events: list[SafetyEvent] = []

        if route_point is not None:
            position_estimate = self.pdr_fallback.estimate(
                timestamp=observation.timestamp,
                point=route_point,
                previous_route_index=self._matched_route_index,
            )
            self._matched_route_index = position_estimate.route_index
            route_progress_sample = _route_progress_sample(
                timestamp=observation.timestamp,
                point=route_point,
                position_estimate=position_estimate,
                planned_route=self.planned_route,
                offline_map_context=self.offline_map_context,
            )
            _attach_position_evidence(observation, position_estimate, route_progress_sample)

            checkpoint_arrival = self.checkpoint_manager.observe(observation)
            if checkpoint_arrival is not None:
                self.checkpoint_hits.append(checkpoint_arrival)
            progress_update = self.progress_tracker.observe(observation)
            if progress_update is not None:
                self.progress_updates.append(progress_update)

            safety_event = self.route_progress_evaluator.observe(
                route_progress_sample,
                self.progress_tracker.expected_checkpoint_id,
            )
            if safety_event is not None:
                pending_events.append(safety_event)

        go_no_go_result = self._go_no_go_evaluation(observation)
        go_no_go_evaluation = go_no_go_result.evaluation if go_no_go_result is not None else None
        observation.raw["go_no_go"] = _go_no_go_raw(go_no_go_evaluation)
        observation.raw["provider_context"] = (
            provider_evidence(go_no_go_result.mission_context) if go_no_go_result is not None else None
        )
        if go_no_go_evaluation is not None and go_no_go_evaluation.safety_event is not None:
            pending_events.append(go_no_go_evaluation.safety_event)

        recording_decision = self.recording_policy_runtime.decide(
            timestamp=observation.timestamp,
            route_index=self._matched_route_index or 0,
            current_safety_level=self.safety_state_machine.state.level,
            pending_events=pending_events,
            segment_id=_active_segment_id(self.runtime, self.progress_tracker),
        )
        self.recording_decisions.append(recording_decision)
        observation.raw["recording_policy"] = recording_decision.model_dump(mode="json")
        self.incident_package_builder.observe(observation)

        new_incidents: list[IncidentPackage] = []
        new_stored_paths: list[Path] = []
        for safety_event in pending_events:
            before_incidents = len(self.incident_packages)
            before_paths = len(self.stored_incident_paths)
            _record_safety_event(
                safety_event=safety_event,
                progress_tracker=self.progress_tracker,
                safety_state_machine=self.safety_state_machine,
                incident_package_builder=self.incident_package_builder,
                incident_packages=self.incident_packages,
                raw_window_seconds=recording_decision.raw_ring_seconds,
                incident_store=self.incident_store,
                stored_incident_paths=self.stored_incident_paths,
            )
            new_incidents.extend(self.incident_packages[before_incidents:])
            new_stored_paths.extend(self.stored_incident_paths[before_paths:])

        self.observations_processed += 1
        return SafetyRuntimeUpdate(
            observation=observation,
            route_progress_sample=route_progress_sample,
            checkpoint_arrival=checkpoint_arrival,
            progress_update=progress_update,
            safety_events=pending_events,
            safety_state=self.safety_state_machine.state,
            recording_decision=recording_decision,
            incident_packages=new_incidents,
            stored_incident_paths=new_stored_paths,
        )

    def snapshot(self) -> SafetyRuntimeSnapshot:
        return SafetyRuntimeSnapshot(
            observations_processed=self.observations_processed,
            checkpoint_hits=self.checkpoint_hits,
            segment_capsules=self.progress_tracker.segment_capsules,
            progress_updates=self.progress_updates,
            safety_events=self.progress_tracker.safety_events,
            safety_state=self.safety_state_machine.state,
            incident_packages=self.incident_packages,
            recording_decisions=self.recording_decisions,
            stored_incident_paths=self.stored_incident_paths,
        )

    def _go_no_go_evaluation(self, observation: Observation) -> GoNoGoProviderResult | None:
        if self.mission_provider_bundle is None or self._go_no_go_evaluated:
            return None

        mission_context = mission_context_from_providers(self.mission_provider_bundle, observation=observation)
        segment_id = mission_context.route_context.get("current_segment_id")
        if not segment_id:
            return None

        self._go_no_go_evaluated = True
        segment = self.runtime.current_segment(segment_id)
        return GoNoGoProviderResult(
            evaluation=self.go_no_go_evaluator.evaluate(segment, mission_context, timestamp=observation.timestamp),
            mission_context=mission_context,
        )


def _route_point_from_observation(observation: Observation) -> RoutePoint | None:
    if observation.lat is None or observation.lon is None:
        return None

    raw = observation.raw
    sensorlog = raw.get("sensorlog", {}) if isinstance(raw.get("sensorlog"), dict) else {}
    return RoutePoint(
        lat=observation.lat,
        lon=observation.lon,
        elevation_m=observation.elevation_m,
        timestamp=str(sensorlog.get("loggingTime") or raw.get("timestamp") or observation.timestamp),
        gps_horizontal_accuracy_m=observation.gps_horizontal_accuracy_m,
        course_deg=_float_or_none(sensorlog.get("locationCourse")),
        pedometer_distance_m=_float_or_none(sensorlog.get("pedometerDistance")),
        pedometer_steps=_int_or_none(sensorlog.get("pedometerNumberOfSteps") or sensorlog.get("pedometerNumberofSteps")),
    )


def _attach_position_evidence(
    observation: Observation,
    position_estimate: PositionEstimate,
    progress_sample: RouteProgressSample,
) -> None:
    observation.raw["position_estimate"] = {
        "source": position_estimate.source,
        "progress_m": position_estimate.progress_m,
        "route_index": position_estimate.route_index,
        "confidence": position_estimate.confidence,
        "pdr_delta_m": position_estimate.pdr_delta_m,
        "gps_reanchor_correction_m": position_estimate.gps_reanchor_correction_m,
    }
    observation.raw["map_evidence"] = {
        "corridor": {
            "inside": progress_sample.map_corridor_inside,
            "corridor_id": progress_sample.map_corridor_id,
            "distance_m": progress_sample.map_corridor_distance_m,
            "allowed_distance_m": progress_sample.map_corridor_allowed_distance_m,
            "source_metadata": progress_sample.map_source_metadata,
        },
        "hazards": progress_sample.map_hazards or [],
    }


def _go_no_go_raw(evaluation: GoNoGoEvaluation | None) -> dict | None:
    if evaluation is None:
        return None
    return {
        "decision": evaluation.decision.model_dump(mode="json"),
        "safety_event": evaluation.safety_event.model_dump(mode="json") if evaluation.safety_event else None,
    }


def _float_or_none(value: Any) -> float | None:
    if value in (None, "", "null"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    parsed = _float_or_none(value)
    return int(parsed) if parsed is not None else None
