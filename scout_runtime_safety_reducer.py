from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scout_energy_models import aggregate_sha256, sha256_file
from scout_runtime_safety_gate_models import (
    SafetyGateConfidence,
    SafetyGateSeverity,
    SafetyLnLevelCandidate,
    SafetyLnTransitionCandidate,
    ScoutRuntimeSafetyGateEvent,
    ScoutRuntimeSafetyGateEventBatch,
    build_runtime_safety_gate_event_batch,
)
from scout_wearable_validator import FORBIDDEN_RAW_KEYS


ReducerRecommendation = Literal[
    "continue_monitoring",
    "watch_and_recheck",
    "slow_down_or_rest",
    "stop_and_rest",
    "retreat_review",
    "alert_review",
]
ReducerState = Literal[
    "normal",
    "watch",
    "rest",
    "retreat_review",
    "alert_review",
]
Phase1AdapterStatus = Literal[
    "blocked_feature_flag_disabled",
    "blocked_review_required",
    "transition_request_prepared",
]

_TRANSITION_BY_SEVERITY: dict[str, SafetyLnTransitionCandidate] = {
    "none": "none",
    "watch": "candidate_watch",
    "rest": "candidate_rest",
    "retreat_review": "candidate_retreat",
    "alert_review": "candidate_alert_review",
}
_LEVEL_BY_TRANSITION: dict[str, SafetyLnLevelCandidate] = {
    "none": "L0_NORMAL",
    "candidate_watch": "L1_CAUTION",
    "candidate_rest": "L2_CONCERN",
    "candidate_retreat": "L3_RETREAT",
    "candidate_alert_review": "L4_ALERT_REVIEW",
}
_STATE_BY_TRANSITION: dict[str, ReducerState] = {
    "none": "normal",
    "candidate_watch": "watch",
    "candidate_rest": "rest",
    "candidate_retreat": "retreat_review",
    "candidate_alert_review": "alert_review",
}
_RECOMMENDATION_BY_TRANSITION: dict[str, ReducerRecommendation] = {
    "none": "continue_monitoring",
    "candidate_watch": "watch_and_recheck",
    "candidate_rest": "stop_and_rest",
    "candidate_retreat": "retreat_review",
    "candidate_alert_review": "alert_review",
}
_HARD_SINGLE_GATE_ESCALATORS = {"weather_gate", "environment_threat_gate", "darkness_gate"}


class RuntimeSafetyReducerBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_only: bool = True
    reducer_dry_run: bool = True
    runtime_safety_truth: bool = False
    phase1_runtime_safety_truth: bool = False
    phase1_runtime_mutation_allowed: bool = False
    phase1_l0_l4_state_mutated: bool = False
    safety_api_called: bool = False
    outbound_alert_sent: bool = False
    medical_diagnosis: bool = False
    raw_health_payload_shared: bool = False
    raw_track_shared: bool = False
    precise_timestamps_shared: bool = False
    home_work_trace_shared: bool = False

    @model_validator(mode="after")
    def enforce_dry_run_boundary(self) -> "RuntimeSafetyReducerBoundary":
        if not self.candidate_only or not self.reducer_dry_run:
            raise ValueError("runtime safety reducer artifact must be dry-run candidate evidence")
        if (
            self.runtime_safety_truth
            or self.phase1_runtime_safety_truth
            or self.phase1_runtime_mutation_allowed
            or self.phase1_l0_l4_state_mutated
        ):
            raise ValueError("runtime safety reducer dry-run cannot mutate Phase 1 state")
        if self.safety_api_called:
            raise ValueError("runtime safety reducer dry-run cannot call /safety/*")
        if self.outbound_alert_sent:
            raise ValueError("runtime safety reducer dry-run cannot send outbound alerts")
        if self.medical_diagnosis:
            raise ValueError("runtime safety reducer dry-run cannot be a medical diagnosis")
        if (
            self.raw_health_payload_shared
            or self.raw_track_shared
            or self.precise_timestamps_shared
            or self.home_work_trace_shared
        ):
            raise ValueError("runtime safety reducer dry-run cannot share raw private payloads")
        return self


class RuntimeSafetyReducerPrivacy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    local_only: bool = True
    aggregate_only: bool = True
    raw_health_payload_shared: bool = False
    raw_track_shared: bool = False
    precise_timestamps_shared: bool = False
    home_work_trace_shared: bool = False
    shareable_by_default: bool = False


class RuntimeSafetyReducerDataQuality(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confidence: SafetyGateConfidence = "low"
    gate_event_count: int = Field(default=0, ge=0)
    contributing_gate_count: int = Field(default=0, ge=0)
    missing_gate_ids: list[str] = Field(default_factory=list)
    stale_signal_names: list[str] = Field(default_factory=list)
    live_network_calls_made: bool = False
    limitations: list[str] = Field(default_factory=list)


class RuntimeSafetyReducerHysteresisInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    previous_ln_level: SafetyLnLevelCandidate = "L0_NORMAL"
    previous_reducer_state: ReducerState = "normal"
    clear_window_count: int = Field(default=0, ge=0)
    stable_window_count: int = Field(default=0, ge=0)


class RuntimeSafetyReducerHysteresisResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    applied: bool = True
    escalated_immediately: bool = False
    deescalation_held: bool = False
    required_clear_windows: int = 2
    previous_ln_level: SafetyLnLevelCandidate
    proposed_ln_level: SafetyLnLevelCandidate
    final_ln_level: SafetyLnLevelCandidate
    suppressed_reasons: list[str] = Field(default_factory=list)


class RuntimeSafetyReducerDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_runtime_safety_reducer_dry_run"
    artifact_version: str = "runtime_safety_reducer_dry_run.v1"
    source_provider: str = "scout_runtime_safety_reducer"
    source_path: str
    sha256: str
    gate_event_count: int = Field(ge=0)
    contributing_gate_ids: list[str] = Field(default_factory=list)
    corroborating_gate_ids: list[str] = Field(default_factory=list)
    suppressed_gate_ids: list[str] = Field(default_factory=list)
    selected_event_id: str | None = None
    selected_event_sha256: str | None = None
    selected_gate_id: str | None = None
    highest_severity: SafetyGateSeverity = "none"
    proposed_ln_transition_candidate: SafetyLnTransitionCandidate = "none"
    proposed_ln_level_candidate: SafetyLnLevelCandidate = "L0_NORMAL"
    ln_transition_candidate: SafetyLnTransitionCandidate = "none"
    ln_level_candidate: SafetyLnLevelCandidate = "L0_NORMAL"
    reducer_state: ReducerState = "normal"
    recommendation: ReducerRecommendation = "continue_monitoring"
    route_pressure_review_required: bool = False
    eta_delay_minutes: int = Field(default=0, ge=0)
    policy_trace: list[str] = Field(default_factory=list)
    suppressed_reasons: list[str] = Field(default_factory=list)
    gate_summaries: list[dict[str, Any]] = Field(default_factory=list)
    hysteresis: RuntimeSafetyReducerHysteresisResult
    data_quality: RuntimeSafetyReducerDataQuality = Field(default_factory=RuntimeSafetyReducerDataQuality)
    privacy: RuntimeSafetyReducerPrivacy = Field(default_factory=RuntimeSafetyReducerPrivacy)
    boundary: RuntimeSafetyReducerBoundary = Field(default_factory=RuntimeSafetyReducerBoundary)

    @model_validator(mode="after")
    def enforce_decision(self) -> "RuntimeSafetyReducerDecision":
        if self.gate_event_count < len(self.contributing_gate_ids):
            raise ValueError("contributing gates cannot exceed gate event count")
        if self.proposed_ln_level_candidate != _LEVEL_BY_TRANSITION[
            self.proposed_ln_transition_candidate
        ]:
            raise ValueError("proposed level must match proposed transition")
        if self.ln_level_candidate != _LEVEL_BY_TRANSITION[self.ln_transition_candidate]:
            raise ValueError("level must match transition")
        forbidden_paths = _forbidden_key_paths(self.gate_summaries)
        if forbidden_paths:
            raise ValueError(f"forbidden reducer fields present: {', '.join(forbidden_paths)}")
        if self.privacy.raw_health_payload_shared or self.privacy.precise_timestamps_shared:
            raise ValueError("reducer privacy flags are invalid")
        return self


class RuntimeSafetyPhase1AdapterBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    controlled_adapter: bool = True
    reducer_owned: bool = True
    individual_gate_owned: bool = False
    feature_flag_required: bool = True
    human_review_required: bool = True
    runtime_safety_truth: bool = False
    phase1_l0_l4_state_mutated: bool = False
    safety_api_called: bool = False
    outbound_alert_sent: bool = False
    medical_diagnosis: bool = False
    raw_health_payload_shared: bool = False
    raw_track_shared: bool = False
    precise_timestamps_shared: bool = False
    home_work_trace_shared: bool = False

    @model_validator(mode="after")
    def enforce_adapter_boundary(self) -> "RuntimeSafetyPhase1AdapterBoundary":
        if not self.controlled_adapter or not self.reducer_owned:
            raise ValueError("Phase 1 adapter must be controlled by the reducer")
        if self.individual_gate_owned:
            raise ValueError("individual gates cannot own the Phase 1 adapter")
        if self.runtime_safety_truth or self.phase1_l0_l4_state_mutated:
            raise ValueError("adapter artifact cannot claim Phase 1 mutation was performed")
        if self.safety_api_called:
            raise ValueError("adapter artifact cannot call /safety/* in this slice")
        if self.outbound_alert_sent:
            raise ValueError("adapter artifact cannot send outbound alerts")
        if self.medical_diagnosis:
            raise ValueError("adapter artifact cannot be a medical diagnosis")
        if (
            self.raw_health_payload_shared
            or self.raw_track_shared
            or self.precise_timestamps_shared
            or self.home_work_trace_shared
        ):
            raise ValueError("adapter artifact cannot share raw private payloads")
        return self


class RuntimeSafetyPhase1AdapterResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_runtime_safety_phase1_adapter_result"
    artifact_version: str = "runtime_safety_phase1_adapter_result.v1"
    source_provider: str = "scout_runtime_safety_reducer"
    source_path: str
    sha256: str
    status: Phase1AdapterStatus
    phase1_adapter_enabled: bool = False
    human_review_approved: bool = False
    transition_request_prepared: bool = False
    phase1_transition_candidate: dict[str, Any] | None = None
    selected_reducer_sha256: str
    selected_reducer_level_candidate: SafetyLnLevelCandidate
    selected_reducer_transition_candidate: SafetyLnTransitionCandidate
    boundary: RuntimeSafetyPhase1AdapterBoundary = Field(
        default_factory=RuntimeSafetyPhase1AdapterBoundary
    )

    @model_validator(mode="after")
    def enforce_adapter_result(self) -> "RuntimeSafetyPhase1AdapterResult":
        if self.transition_request_prepared != (
            self.status == "transition_request_prepared"
        ):
            raise ValueError("transition_request_prepared must match status")
        if self.status == "transition_request_prepared" and not self.phase1_transition_candidate:
            raise ValueError("prepared adapter result requires a transition candidate")
        forbidden_paths = _forbidden_key_paths(self.phase1_transition_candidate or {})
        if forbidden_paths:
            raise ValueError(f"forbidden adapter fields present: {', '.join(forbidden_paths)}")
        return self


def reduce_runtime_safety_gate_events(
    gate_events: (
        ScoutRuntimeSafetyGateEventBatch
        | list[ScoutRuntimeSafetyGateEvent | dict[str, Any]]
        | dict[str, Any]
    ),
    *,
    source_path: str = "inline:runtime-safety-gate-reducer",
    hysteresis_input: RuntimeSafetyReducerHysteresisInput | dict[str, Any] | None = None,
) -> RuntimeSafetyReducerDecision:
    batch = _event_batch(gate_events)
    events = batch.events
    contributing = [event for event in events if event.severity != "none"]
    selected = _selected_event(contributing)
    proposed_transition = selected.ln_transition_candidate if selected else "none"
    highest_severity = selected.severity if selected else "none"
    policy_trace: list[str] = []
    suppressed_reasons: list[str] = []
    suppressed_gate_ids: list[str] = []
    corroborating_gate_ids = _corroborating_gate_ids(contributing)

    proposed_transition = _apply_cross_gate_policy(
        contributing,
        proposed_transition,
        policy_trace=policy_trace,
        suppressed_reasons=suppressed_reasons,
        suppressed_gate_ids=suppressed_gate_ids,
        corroborating_gate_ids=corroborating_gate_ids,
    )
    proposed_level = _LEVEL_BY_TRANSITION[proposed_transition]
    hysteresis_model = (
        hysteresis_input
        if isinstance(hysteresis_input, RuntimeSafetyReducerHysteresisInput)
        else RuntimeSafetyReducerHysteresisInput.model_validate(hysteresis_input or {})
    )
    final_transition, hysteresis_result = _apply_hysteresis(
        proposed_transition,
        hysteresis_model,
    )
    final_level = _LEVEL_BY_TRANSITION[final_transition]
    suppressed_reasons.extend(hysteresis_result.suppressed_reasons)
    reducer_state = _STATE_BY_TRANSITION[final_transition]
    recommendation = _RECOMMENDATION_BY_TRANSITION[final_transition]
    route_pressure_review_required = any(
        event.route_pressure_review_required for event in contributing
    )
    eta_delay_minutes = max([event.eta_delay_minutes for event in events], default=0)
    gate_summaries = [_event_summary(event) for event in events]
    digest_payload = {
        "source_path": source_path,
        "batch_sha256": batch.sha256,
        "event_ids": [event.event_id for event in events],
        "proposed_transition": proposed_transition,
        "final_transition": final_transition,
        "hysteresis": hysteresis_result.model_dump(mode="json"),
    }
    digest = aggregate_sha256([digest_payload])

    return RuntimeSafetyReducerDecision(
        source_path=source_path,
        sha256=digest,
        gate_event_count=len(events),
        contributing_gate_ids=[event.gate_id for event in contributing],
        corroborating_gate_ids=_unique_string_list(corroborating_gate_ids),
        suppressed_gate_ids=_unique_string_list(suppressed_gate_ids),
        selected_event_id=selected.event_id if selected else None,
        selected_event_sha256=selected.sha256 if selected else None,
        selected_gate_id=selected.gate_id if selected else None,
        highest_severity=highest_severity,
        proposed_ln_transition_candidate=proposed_transition,
        proposed_ln_level_candidate=proposed_level,
        ln_transition_candidate=final_transition,
        ln_level_candidate=final_level,
        reducer_state=reducer_state,
        recommendation=recommendation,
        route_pressure_review_required=route_pressure_review_required,
        eta_delay_minutes=eta_delay_minutes,
        policy_trace=policy_trace,
        suppressed_reasons=_unique_string_list(suppressed_reasons),
        gate_summaries=gate_summaries,
        hysteresis=hysteresis_result,
        data_quality=RuntimeSafetyReducerDataQuality(
            confidence=_max_confidence([event.confidence for event in events]),
            gate_event_count=len(events),
            contributing_gate_count=len(contributing),
            missing_gate_ids=[
                gate_id
                for gate_id in (
                    "pace_gate",
                    "delay_gate",
                    "physiologic_gate",
                    "weather_gate",
                    "darkness_gate",
                    "environment_threat_gate",
                )
                if gate_id not in {event.gate_id for event in events}
            ],
            stale_signal_names=_unique_string_list(
                [
                    stale
                    for event in events
                    for stale in event.data_quality.stale_signal_names
                ]
            ),
            live_network_calls_made=any(
                event.data_quality.live_network_calls_made for event in events
            ),
            limitations=[
                "dry-run reducer candidate only",
                "Phase 1 adapter must be explicitly enabled and reviewed",
            ],
        ),
        privacy=RuntimeSafetyReducerPrivacy(),
        boundary=RuntimeSafetyReducerBoundary(),
    )


def build_phase1_adapter_result(
    decision: RuntimeSafetyReducerDecision | dict[str, Any],
    *,
    source_path: str = "inline:runtime-safety-phase1-adapter",
    phase1_adapter_enabled: bool = False,
    human_review_approved: bool = False,
) -> RuntimeSafetyPhase1AdapterResult:
    reducer_decision = (
        decision
        if isinstance(decision, RuntimeSafetyReducerDecision)
        else RuntimeSafetyReducerDecision.model_validate(decision)
    )
    status: Phase1AdapterStatus
    transition_request: dict[str, Any] | None = None
    if not phase1_adapter_enabled:
        status = "blocked_feature_flag_disabled"
    elif not human_review_approved:
        status = "blocked_review_required"
    else:
        status = "transition_request_prepared"
        transition_request = {
            "adapter_kind": "phase1_l0_l4_transition_candidate",
            "requested_ln_level": reducer_decision.ln_level_candidate,
            "requested_ln_transition": reducer_decision.ln_transition_candidate,
            "reducer_recommendation": reducer_decision.recommendation,
            "selected_gate_id": reducer_decision.selected_gate_id,
            "selected_event_sha256": reducer_decision.selected_event_sha256,
            "corroborating_gate_ids": reducer_decision.corroborating_gate_ids,
            "phase1_l0_l4_state_mutated": False,
            "safety_api_called": False,
        }
    digest = aggregate_sha256(
        [
            {
                "source_path": source_path,
                "decision_sha256": reducer_decision.sha256,
                "status": status,
                "phase1_adapter_enabled": phase1_adapter_enabled,
                "human_review_approved": human_review_approved,
                "transition_request": transition_request,
            }
        ]
    )
    return RuntimeSafetyPhase1AdapterResult(
        source_path=source_path,
        sha256=digest,
        status=status,
        phase1_adapter_enabled=phase1_adapter_enabled,
        human_review_approved=human_review_approved,
        transition_request_prepared=status == "transition_request_prepared",
        phase1_transition_candidate=transition_request,
        selected_reducer_sha256=reducer_decision.sha256,
        selected_reducer_level_candidate=reducer_decision.ln_level_candidate,
        selected_reducer_transition_candidate=reducer_decision.ln_transition_candidate,
        boundary=RuntimeSafetyPhase1AdapterBoundary(),
    )


def write_runtime_safety_reducer_decision(
    decision: RuntimeSafetyReducerDecision,
    output_path: Path | str,
) -> RuntimeSafetyReducerDecision:
    path = Path(output_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(decision.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return RuntimeSafetyReducerDecision.model_validate_json(path.read_text(encoding="utf-8"))


def load_runtime_safety_reducer_decision(path: Path | str) -> RuntimeSafetyReducerDecision:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    payload["source_path"] = payload.get("source_path") or str(path)
    payload["sha256"] = payload.get("sha256") or sha256_file(Path(path).expanduser())
    return RuntimeSafetyReducerDecision.model_validate(payload)


def write_phase1_adapter_result(
    result: RuntimeSafetyPhase1AdapterResult,
    output_path: Path | str,
) -> RuntimeSafetyPhase1AdapterResult:
    path = Path(output_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return RuntimeSafetyPhase1AdapterResult.model_validate_json(path.read_text(encoding="utf-8"))


def load_phase1_adapter_result(path: Path | str) -> RuntimeSafetyPhase1AdapterResult:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    payload["source_path"] = payload.get("source_path") or str(path)
    payload["sha256"] = payload.get("sha256") or sha256_file(Path(path).expanduser())
    return RuntimeSafetyPhase1AdapterResult.model_validate(payload)


def _event_batch(
    value: (
        ScoutRuntimeSafetyGateEventBatch
        | list[ScoutRuntimeSafetyGateEvent | dict[str, Any]]
        | dict[str, Any]
    ),
) -> ScoutRuntimeSafetyGateEventBatch:
    if isinstance(value, ScoutRuntimeSafetyGateEventBatch):
        return value
    if isinstance(value, list):
        return build_runtime_safety_gate_event_batch(value)
    return ScoutRuntimeSafetyGateEventBatch.model_validate(value)


def _selected_event(
    events: list[ScoutRuntimeSafetyGateEvent],
) -> ScoutRuntimeSafetyGateEvent | None:
    if not events:
        return None
    return max(
        events,
        key=lambda event: (
            _transition_rank(event.ln_transition_candidate),
            _confidence_rank(event.confidence),
            event.eta_delay_minutes,
            -events.index(event),
        ),
    )


def _apply_cross_gate_policy(
    events: list[ScoutRuntimeSafetyGateEvent],
    proposed_transition: SafetyLnTransitionCandidate,
    *,
    policy_trace: list[str],
    suppressed_reasons: list[str],
    suppressed_gate_ids: list[str],
    corroborating_gate_ids: list[str],
) -> SafetyLnTransitionCandidate:
    if not events:
        policy_trace.append("no contributing gates")
        return "none"

    gate_ids = {event.gate_id for event in events}
    physiologic = [event for event in events if event.gate_id == "physiologic_gate"]
    route_pressure_gate_ids = {
        "pace_gate",
        "delay_gate",
        "darkness_gate",
    } & gate_ids
    hard_gate_events = [
        event
        for event in events
        if event.gate_id in _HARD_SINGLE_GATE_ESCALATORS
        and event.confidence in {"medium", "high"}
    ]

    if physiologic and route_pressure_gate_ids:
        max_physio = max(
            _transition_rank(event.ln_transition_candidate) for event in physiologic
        )
        if max_physio >= _transition_rank("candidate_rest"):
            policy_trace.append("physiologic pressure corroborated by route pressure")
            corroborating_gate_ids.extend(sorted(route_pressure_gate_ids | {"physiologic_gate"}))
            proposed_transition = _max_transition(
                proposed_transition,
                "candidate_retreat",
            )

    if proposed_transition == "candidate_alert_review":
        hard_alert = any(
            event.gate_id in _HARD_SINGLE_GATE_ESCALATORS
            and event.ln_transition_candidate == "candidate_alert_review"
            and event.confidence in {"medium", "high"}
            for event in events
        )
        strong_multi_gate = len(corroborating_gate_ids) >= 2 and any(
            _transition_rank(event.ln_transition_candidate)
            >= _transition_rank("candidate_retreat")
            for event in events
        )
        if hard_alert or strong_multi_gate:
            policy_trace.append("alert review supported by hard gate or corroboration")
        else:
            proposed_transition = "candidate_retreat"
            suppressed_reasons.append("alert review requires hard current evidence or corroboration")
            suppressed_gate_ids.extend(event.gate_id for event in events if event.severity == "alert_review")

    if proposed_transition == "candidate_retreat" and len(events) == 1:
        event = events[0]
        if (
            event.gate_id not in _HARD_SINGLE_GATE_ESCALATORS
            and event.confidence == "low"
            and not event.route_pressure_review_required
        ):
            proposed_transition = "candidate_rest"
            policy_trace.append("weak single-gate retreat candidate suppressed")
            suppressed_reasons.append("single low-confidence non-hard gate cannot own retreat")
            suppressed_gate_ids.append(event.gate_id)
    elif hard_gate_events:
        policy_trace.append("hard gate evidence can escalate without physiologic corroboration")

    return proposed_transition


def _apply_hysteresis(
    proposed_transition: SafetyLnTransitionCandidate,
    hysteresis: RuntimeSafetyReducerHysteresisInput,
) -> tuple[SafetyLnTransitionCandidate, RuntimeSafetyReducerHysteresisResult]:
    previous_transition = _transition_for_level(hysteresis.previous_ln_level)
    proposed_rank = _transition_rank(proposed_transition)
    previous_rank = _transition_rank(previous_transition)
    suppressed_reasons: list[str] = []
    final_transition = proposed_transition
    escalated = proposed_rank > previous_rank
    held = False
    if proposed_rank < previous_rank:
        if hysteresis.clear_window_count < 2:
            final_transition = previous_transition
            held = True
            suppressed_reasons.append("de-escalation held until two clear windows")
        else:
            final_transition = proposed_transition
    return (
        final_transition,
        RuntimeSafetyReducerHysteresisResult(
            escalated_immediately=escalated,
            deescalation_held=held,
            previous_ln_level=hysteresis.previous_ln_level,
            proposed_ln_level=_LEVEL_BY_TRANSITION[proposed_transition],
            final_ln_level=_LEVEL_BY_TRANSITION[final_transition],
            suppressed_reasons=suppressed_reasons,
        ),
    )


def _corroborating_gate_ids(events: list[ScoutRuntimeSafetyGateEvent]) -> list[str]:
    gate_ids = {event.gate_id for event in events}
    corroborating = set()
    if "physiologic_gate" in gate_ids and (
        {"pace_gate", "delay_gate", "darkness_gate"} & gate_ids
    ):
        corroborating.update({"physiologic_gate"} | (gate_ids & {"pace_gate", "delay_gate", "darkness_gate"}))
    if "weather_gate" in gate_ids and "environment_threat_gate" in gate_ids:
        corroborating.update({"weather_gate", "environment_threat_gate"})
    return sorted(corroborating)


def _event_summary(event: ScoutRuntimeSafetyGateEvent) -> dict[str, Any]:
    return {
        "gate_id": event.gate_id,
        "event_id": event.event_id,
        "sha256": event.sha256,
        "severity": event.severity,
        "ln_transition_candidate": event.ln_transition_candidate,
        "ln_level_candidate": event.ln_level_candidate,
        "state_candidate": event.state_candidate,
        "confidence": event.confidence,
        "route_pressure_review_required": event.route_pressure_review_required,
        "eta_delay_minutes": event.eta_delay_minutes,
        "dominant_reasons": event.dominant_reasons,
        "evidence_refs": event.evidence_refs,
        "map_target_ids": event.route_context.map_target_ids,
        "source_path": event.source_path,
        "source_provider": event.source_provider,
    }


def _transition_for_level(level: SafetyLnLevelCandidate) -> SafetyLnTransitionCandidate:
    by_level = {level_value: transition for transition, level_value in _LEVEL_BY_TRANSITION.items()}
    return by_level[level]


def _max_transition(
    left: SafetyLnTransitionCandidate,
    right: SafetyLnTransitionCandidate,
) -> SafetyLnTransitionCandidate:
    return left if _transition_rank(left) >= _transition_rank(right) else right


def _transition_rank(value: str) -> int:
    order = {
        "none": 0,
        "candidate_watch": 1,
        "candidate_rest": 2,
        "candidate_retreat": 3,
        "candidate_alert_review": 4,
    }
    return order.get(value, 0)


def _confidence_rank(value: str) -> int:
    order = {"low": 0, "medium": 1, "high": 2}
    return order.get(value, 0)


def _max_confidence(values: list[Any]) -> SafetyGateConfidence:
    rank = {"low": 0, "medium": 1, "high": 2}
    valid = [str(value) for value in values if str(value) in rank]
    if not valid:
        return "low"
    return max(valid, key=lambda item: rank[item])  # type: ignore[return-value]


def _forbidden_key_paths(value: Any, prefix: str = "") -> list[str]:
    if isinstance(value, dict):
        paths: list[str] = []
        for key, child in value.items():
            child_path = f"{prefix}.{key}" if prefix else str(key)
            if str(key).lower() in FORBIDDEN_RAW_KEYS:
                paths.append(child_path)
            paths.extend(_forbidden_key_paths(child, child_path))
        return paths
    if isinstance(value, list):
        paths = []
        for index, child in enumerate(value):
            paths.extend(_forbidden_key_paths(child, f"{prefix}[{index}]"))
        return paths
    return []


def _unique_string_list(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value is None or value == "":
            continue
        item = str(value)
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
