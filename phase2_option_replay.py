from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from decision_options import generate_option_set_with_ln_gate
from ln_constraints import LnConstraintContext, LnConstraintDecision, LnConstraintEvaluator
from phase2_brain_ingest import ingest_brain_node
from phase2_brain_models import (
    DecisionOptionSet,
    DerivedMeasurement,
    Mission,
    RemoteStatusArtifact,
    Route,
    TeamSeparationEvent,
)
from phase2_brain_store import BrainFileStore
from phase2_demo_defaults import (
    DEFAULT_DELAY_MEASUREMENT_REF,
    DEFAULT_MISSION_REF,
    DEFAULT_OPTION_SET_REF,
    DEFAULT_POLICY_PATH,
    DEFAULT_REMOTE_STATUS_REF,
    DEFAULT_REPLAY_OPTION_SET_REF,
    DEFAULT_ROUTE_REF,
    DEFAULT_SEPARATION_EVENT_REF,
    DEFAULT_TEAM_REPLAY_FIXTURE_PATH,
)
from phase2_team_replay_store import TeamReplayStoreResult, persist_team_replay_to_brain_store


DEFAULT_FIXTURE_OPTION_SET_ID = DEFAULT_OPTION_SET_REF
DEFAULT_REPLAY_OPTION_SET_ID = DEFAULT_REPLAY_OPTION_SET_REF


@dataclass(frozen=True)
class TeamReplayOptionResult:
    team_replay: TeamReplayStoreResult
    option_set: DecisionOptionSet
    option_set_path: Path
    gate_decision: LnConstraintDecision
    evidence_refs: tuple[str, ...]


def persist_team_replay_option_set(
    store: BrainFileStore,
    *,
    fixture_path: Path | str = DEFAULT_TEAM_REPLAY_FIXTURE_PATH,
    evaluator: LnConstraintEvaluator | None = None,
    fixture_option_set_ref: str = DEFAULT_FIXTURE_OPTION_SET_ID,
    option_set_id: str = DEFAULT_REPLAY_OPTION_SET_ID,
    mission_ref: str = DEFAULT_MISSION_REF,
    route_ref: str = DEFAULT_ROUTE_REF,
    remote_status_ref: str = DEFAULT_REMOTE_STATUS_REF,
    delay_measurement_ref: str = DEFAULT_DELAY_MEASUREMENT_REF,
    separation_event_ref: str = DEFAULT_SEPARATION_EVENT_REF,
    generated_at: str = "2026-05-13T10:15:20+08:00",
    safety_level: str | None = None,
    activity: str = "moving",
    weather: str = "rain",
    team_state: str = "communication_degraded",
    intrusive: bool = True,
) -> TeamReplayOptionResult:
    team_replay = persist_team_replay_to_brain_store(store, fixture_path)
    evaluator = evaluator or LnConstraintEvaluator.from_file(DEFAULT_POLICY_PATH)

    context = build_team_replay_ln_context(
        store,
        route_ref=route_ref,
        remote_status_ref=remote_status_ref,
        delay_measurement_ref=delay_measurement_ref,
        separation_event_ref=separation_event_ref,
        safety_level=safety_level,
        activity=activity,
        weather=weather,
        team_state=team_state,
    )
    fixture_options = _load_fixture_option_set(store, fixture_option_set_ref)
    gate_decision = evaluator.evaluate_context(context)
    mission = _mission(store, mission_ref)

    option_set = generate_option_set_with_ln_gate(
        evaluator=evaluator,
        context=context,
        id=option_set_id,
        generated_at=generated_at,
        current_safety_level=context.safety_level,
        pilot_in_command=mission.mission_owner,
        mission_id=mission.id,
        options=fixture_options.options,
        degraded_options=fixture_options.options[:1],
        input_refs=_option_input_refs(context.evidence_refs),
        intrusive=intrusive,
    )
    option_set_path = _explicitly_ingest_option_set(store, option_set)

    return TeamReplayOptionResult(
        team_replay=team_replay,
        option_set=option_set,
        option_set_path=option_set_path,
        gate_decision=gate_decision,
        evidence_refs=context.evidence_refs,
    )


def build_team_replay_ln_context(
    store: BrainFileStore,
    *,
    route_ref: str = DEFAULT_ROUTE_REF,
    remote_status_ref: str = DEFAULT_REMOTE_STATUS_REF,
    delay_measurement_ref: str = DEFAULT_DELAY_MEASUREMENT_REF,
    separation_event_ref: str = DEFAULT_SEPARATION_EVENT_REF,
    safety_level: str | None = None,
    activity: str = "moving",
    weather: str = "rain",
    team_state: str = "communication_degraded",
) -> LnConstraintContext:
    route = _route(store, route_ref)
    remote_status = _remote_status(store, remote_status_ref)
    evidence_refs = _delay_and_separation_evidence_refs(
        store,
        delay_measurement_ref=delay_measurement_ref,
        separation_event_ref=separation_event_ref,
    )

    return LnConstraintContext(
        skill_id="retreat-decision-support",
        safety_level=safety_level or remote_status.safety_level,
        route_type=route.route_type,
        duration_class="same_day",
        activity=activity,
        weather=weather,
        team_state=team_state,
        evidence_refs=evidence_refs,
    )


def _delay_and_separation_evidence_refs(
    store: BrainFileStore,
    *,
    delay_measurement_ref: str,
    separation_event_ref: str,
) -> tuple[str, ...]:
    delay = _delay_measurement(store, delay_measurement_ref)
    separation = _separation_event(store, separation_event_ref)
    return _dedupe_refs([delay.id, separation.id, *separation.evidence_refs])


def _option_input_refs(evidence_refs: tuple[str, ...]) -> list[str]:
    return list(evidence_refs)


def _explicitly_ingest_option_set(store: BrainFileStore, option_set: DecisionOptionSet) -> Path:
    return ingest_brain_node(store, option_set, automatic=False, manual_write=True)


def _load_fixture_option_set(store: BrainFileStore, option_set_ref: str) -> DecisionOptionSet:
    node = store.load_node(option_set_ref)
    if not isinstance(node, DecisionOptionSet):
        raise TypeError(f"{option_set_ref} is not a DecisionOptionSet")
    return node


def _mission(store: BrainFileStore, mission_ref: str) -> Mission:
    node = store.load_node(mission_ref)
    if not isinstance(node, Mission):
        raise TypeError(f"{mission_ref} is not a Mission")
    return node


def _route(store: BrainFileStore, route_ref: str) -> Route:
    node = store.load_node(route_ref)
    if not isinstance(node, Route):
        raise TypeError(f"{route_ref} is not a Route")
    return node


def _remote_status(store: BrainFileStore, remote_status_ref: str) -> RemoteStatusArtifact:
    node = store.load_node(remote_status_ref)
    if not isinstance(node, RemoteStatusArtifact):
        raise TypeError(f"{remote_status_ref} is not a RemoteStatusArtifact")
    return node


def _delay_measurement(store: BrainFileStore, delay_measurement_ref: str) -> DerivedMeasurement:
    node = store.load_node(delay_measurement_ref)
    if not isinstance(node, DerivedMeasurement):
        raise TypeError(f"{delay_measurement_ref} is not a DerivedMeasurement")
    return node


def _separation_event(store: BrainFileStore, separation_event_ref: str) -> TeamSeparationEvent:
    node = store.load_node(separation_event_ref)
    if not isinstance(node, TeamSeparationEvent):
        raise TypeError(f"{separation_event_ref} is not a TeamSeparationEvent")
    return node


def _dedupe_refs(refs: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(refs))
