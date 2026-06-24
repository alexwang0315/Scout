from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scout_energy_models import aggregate_sha256, sha256_file
from scout_runtime_safety_gate_adapters import (
    build_darkness_gate_event,
    build_delay_gate_event,
    build_pace_gate_event,
)
from scout_runtime_safety_gate_models import (
    SafetyGateConfidence,
    SafetyGateDataQuality,
    ScoutRuntimeSafetyGateEvent,
    ScoutRuntimeSafetyGateEventBatch,
    build_runtime_safety_gate_event_batch,
)
from scout_wearable_validator import FORBIDDEN_RAW_KEYS


CheckpointKind = Literal["checkpoint", "camp", "safe_objective", "retreat_point"]


class RuntimeRouteGateFeedBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    local_replay_only: bool = True
    pi_hardware_required: bool = False
    runtime_safety_truth: bool = False
    phase1_runtime_safety_truth: bool = False
    phase1_runtime_mutation_allowed: bool = False
    phase1_l0_l4_state_mutated: bool = False
    safety_api_called: bool = False
    outbound_alert_sent: bool = False
    medical_diagnosis: bool = False
    raw_health_payload_shared: bool = False
    raw_track_shared: bool = False
    raw_gpx_shared: bool = False
    precise_timestamps_shared: bool = False
    home_work_trace_shared: bool = False

    @model_validator(mode="after")
    def enforce_local_replay_boundary(self) -> "RuntimeRouteGateFeedBoundary":
        if not self.local_replay_only:
            raise ValueError("route gate feed slice is local replay only")
        if self.pi_hardware_required:
            raise ValueError("route gate feed slice cannot require Pi hardware")
        if (
            self.runtime_safety_truth
            or self.phase1_runtime_safety_truth
            or self.phase1_runtime_mutation_allowed
            or self.phase1_l0_l4_state_mutated
        ):
            raise ValueError("route gate feed cannot mutate or own Phase 1 safety truth")
        if self.safety_api_called:
            raise ValueError("route gate feed cannot call safety APIs")
        if self.outbound_alert_sent:
            raise ValueError("route gate feed cannot send outbound alerts")
        if self.medical_diagnosis:
            raise ValueError("route gate feed cannot be a medical diagnosis")
        if (
            self.raw_health_payload_shared
            or self.raw_track_shared
            or self.raw_gpx_shared
            or self.precise_timestamps_shared
            or self.home_work_trace_shared
        ):
            raise ValueError("route gate feed cannot share raw private payloads")
        return self


class RuntimeRouteGateFeedPrivacy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    local_only: bool = True
    aggregate_only: bool = True
    raw_track_shared: bool = False
    raw_gpx_shared: bool = False
    precise_timestamps_shared: bool = False
    home_work_trace_shared: bool = False
    shareable_by_default: bool = False


class RuntimeRouteSegmentTiming(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: str = Field(min_length=1)
    from_checkpoint_id: str | None = None
    to_checkpoint_id: str | None = None
    distance_m: float = Field(gt=0)
    reference_p50_minutes: float | None = Field(default=None, gt=0)
    reference_p75_minutes: float = Field(gt=0)
    reference_max_minutes: float | None = Field(default=None, gt=0)
    map_target_ids: list[str] = Field(default_factory=list)
    source_ref: str | None = None

    @model_validator(mode="after")
    def normalize_map_targets(self) -> "RuntimeRouteSegmentTiming":
        self.map_target_ids = _unique_string_list(
            [
                *(self.map_target_ids or []),
                self.segment_id,
                self.from_checkpoint_id,
                self.to_checkpoint_id,
            ]
        )
        return self


class RuntimePlannedTimelineTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checkpoint_id: str = Field(min_length=1)
    checkpoint_kind: CheckpointKind = "checkpoint"
    segment_id: str | None = None
    planned_arrival_offset_min: float = Field(ge=0)
    latest_arrival_offset_min: float | None = Field(default=None, ge=0)
    map_target_ids: list[str] = Field(default_factory=list)
    source_ref: str | None = None

    @model_validator(mode="after")
    def validate_latest_after_planned(self) -> "RuntimePlannedTimelineTarget":
        if (
            self.latest_arrival_offset_min is not None
            and self.latest_arrival_offset_min < self.planned_arrival_offset_min
        ):
            raise ValueError("latest arrival must be after planned arrival")
        self.map_target_ids = _unique_string_list(
            [
                *(self.map_target_ids or []),
                self.checkpoint_id,
                self.segment_id,
            ]
        )
        return self


class RuntimeRouteProgressFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frame_id: str = Field(min_length=1)
    route_id: str = Field(min_length=1)
    observed_at_offset_s: int = Field(ge=0)
    elapsed_route_minutes: float = Field(ge=0)
    segment_id: str = Field(min_length=1)
    target_checkpoint_id: str | None = None
    elapsed_segment_minutes: float = Field(ge=0)
    observed_segment_distance_m: float = Field(default=0, ge=0)
    estimated_minutes_to_target: float | None = Field(default=None, ge=0)
    daylight_buffer_minutes: float | None = None
    minutes_to_next_safe_objective: float | None = Field(default=None, ge=0)
    emergency_bivy_candidate_distance_m: float | None = Field(default=None, ge=0)
    route_pressure_review_required: bool = False
    confidence: SafetyGateConfidence = "medium"
    evidence_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_target_for_eta(self) -> "RuntimeRouteProgressFrame":
        if self.estimated_minutes_to_target is not None and not self.target_checkpoint_id:
            raise ValueError("estimated_minutes_to_target requires target_checkpoint_id")
        return self


class RuntimeRouteGateFeedInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_runtime_route_gate_feed_input"
    artifact_version: str = "runtime_route_gate_feed_input.v1"
    source_provider: str = "scout_runtime_route_gate_feed_fixture"
    source_path: str = "inline:runtime-route-gate-feed"
    route_id: str = Field(min_length=1)
    segment_timings: list[RuntimeRouteSegmentTiming]
    planned_timeline: list[RuntimePlannedTimelineTarget] = Field(default_factory=list)
    progress_frames: list[RuntimeRouteProgressFrame]
    data_quality: SafetyGateDataQuality = Field(default_factory=SafetyGateDataQuality)
    privacy: RuntimeRouteGateFeedPrivacy = Field(default_factory=RuntimeRouteGateFeedPrivacy)
    boundary: RuntimeRouteGateFeedBoundary = Field(default_factory=RuntimeRouteGateFeedBoundary)

    @model_validator(mode="after")
    def enforce_feed_contract(self) -> "RuntimeRouteGateFeedInput":
        forbidden_paths = _forbidden_key_paths(self.model_dump(mode="json"))
        if forbidden_paths:
            raise ValueError(f"forbidden route gate feed fields present: {', '.join(forbidden_paths)}")
        if self.privacy.raw_track_shared or self.privacy.precise_timestamps_shared:
            raise ValueError("route gate feed privacy flags are invalid")
        timing_ids = {segment.segment_id for segment in self.segment_timings}
        missing_segment_ids = [
            frame.segment_id
            for frame in self.progress_frames
            if frame.segment_id not in timing_ids
        ]
        if missing_segment_ids:
            raise ValueError(f"missing segment timing for frames: {sorted(set(missing_segment_ids))}")
        target_ids = {target.checkpoint_id for target in self.planned_timeline}
        missing_targets = [
            frame.target_checkpoint_id
            for frame in self.progress_frames
            if frame.target_checkpoint_id and frame.target_checkpoint_id not in target_ids
        ]
        if missing_targets:
            raise ValueError(f"missing planned target for frames: {sorted(set(missing_targets))}")
        return self


class RuntimeRouteGateFeedResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_runtime_route_gate_feed_result"
    artifact_version: str = "runtime_route_gate_feed_result.v1"
    source_provider: str = "scout_runtime_route_gate_feeds"
    source_path: str
    sha256: str
    route_id: str
    frame_count: int = Field(ge=0)
    event_count: int = Field(ge=0)
    generated_gate_ids: list[str] = Field(default_factory=list)
    event_batch: ScoutRuntimeSafetyGateEventBatch
    events: list[ScoutRuntimeSafetyGateEvent]
    data_quality: SafetyGateDataQuality = Field(default_factory=SafetyGateDataQuality)
    privacy: RuntimeRouteGateFeedPrivacy = Field(default_factory=RuntimeRouteGateFeedPrivacy)
    boundary: RuntimeRouteGateFeedBoundary = Field(default_factory=RuntimeRouteGateFeedBoundary)

    @model_validator(mode="after")
    def enforce_result_counts(self) -> "RuntimeRouteGateFeedResult":
        if self.frame_count < 0:
            raise ValueError("frame_count cannot be negative")
        if self.event_count != len(self.events):
            raise ValueError("event_count must match events")
        if self.event_batch.event_count != len(self.events):
            raise ValueError("event_batch count must match events")
        return self


def build_route_gate_events_from_progress_feed(
    feed: RuntimeRouteGateFeedInput | dict[str, Any],
) -> RuntimeRouteGateFeedResult:
    feed_model = (
        feed
        if isinstance(feed, RuntimeRouteGateFeedInput)
        else RuntimeRouteGateFeedInput.model_validate(feed)
    )
    timing_by_id = {segment.segment_id: segment for segment in feed_model.segment_timings}
    target_by_id = {
        target.checkpoint_id: target for target in feed_model.planned_timeline
    }
    events: list[ScoutRuntimeSafetyGateEvent] = []
    missing_signal_names: list[str] = []
    for frame in feed_model.progress_frames:
        segment = timing_by_id[frame.segment_id]
        events.append(
            _pace_event_from_frame(
                frame,
                segment,
                feed_model,
            )
        )
        if frame.target_checkpoint_id:
            target = target_by_id[frame.target_checkpoint_id]
            events.append(
                _delay_event_from_frame(
                    frame,
                    target,
                    segment,
                    feed_model,
                )
            )
        else:
            missing_signal_names.append(f"{frame.frame_id}:target_checkpoint_id")
        if (
            frame.daylight_buffer_minutes is not None
            and frame.minutes_to_next_safe_objective is not None
        ):
            events.append(
                _darkness_event_from_frame(
                    frame,
                    segment,
                    feed_model,
                )
            )
        else:
            missing_signal_names.append(f"{frame.frame_id}:darkness_inputs")
    batch = build_runtime_safety_gate_event_batch(
        events,
        source_path=f"{feed_model.source_path}#runtime-route-gate-events",
    )
    digest = aggregate_sha256(
        [
            {
                "source_path": feed_model.source_path,
                "route_id": feed_model.route_id,
                "frame_ids": [frame.frame_id for frame in feed_model.progress_frames],
                "event_batch_sha256": batch.sha256,
            }
        ]
    )
    return RuntimeRouteGateFeedResult(
        source_path=feed_model.source_path,
        sha256=digest,
        route_id=feed_model.route_id,
        frame_count=len(feed_model.progress_frames),
        event_count=len(events),
        generated_gate_ids=_unique_string_list([event.gate_id for event in events]),
        event_batch=batch,
        events=events,
        data_quality=SafetyGateDataQuality(
            confidence=_max_confidence([event.confidence for event in events]),
            signal_count=sum(event.data_quality.signal_count for event in events),
            missing_signal_names=_unique_string_list(
                [
                    *missing_signal_names,
                    *feed_model.data_quality.missing_signal_names,
                ]
            ),
            stale_signal_names=feed_model.data_quality.stale_signal_names,
            live_network_calls_made=False,
            limitations=[
                "local replay route gate feed only",
                "does not require Raspberry Pi hardware",
                "does not mutate Phase 1 safety truth",
            ],
        ),
        privacy=feed_model.privacy,
        boundary=feed_model.boundary,
    )


def write_route_gate_feed_result(
    result: RuntimeRouteGateFeedResult,
    output_path: Path | str,
) -> RuntimeRouteGateFeedResult:
    path = Path(output_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return RuntimeRouteGateFeedResult.model_validate_json(path.read_text(encoding="utf-8"))


def load_route_gate_feed_result(path: Path | str) -> RuntimeRouteGateFeedResult:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    payload["source_path"] = payload.get("source_path") or str(path)
    payload["sha256"] = payload.get("sha256") or sha256_file(Path(path).expanduser())
    return RuntimeRouteGateFeedResult.model_validate(payload)


def write_route_gate_event_batch(
    result: RuntimeRouteGateFeedResult,
    output_path: Path | str,
) -> ScoutRuntimeSafetyGateEventBatch:
    path = Path(output_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result.event_batch.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return ScoutRuntimeSafetyGateEventBatch.model_validate_json(path.read_text(encoding="utf-8"))


def _pace_event_from_frame(
    frame: RuntimeRouteProgressFrame,
    segment: RuntimeRouteSegmentTiming,
    feed: RuntimeRouteGateFeedInput,
) -> ScoutRuntimeSafetyGateEvent:
    observed_distance_m = min(frame.observed_segment_distance_m, segment.distance_m)
    observed_pace = (
        frame.elapsed_segment_minutes / (observed_distance_m / 1000.0)
        if observed_distance_m > 0
        else None
    )
    reference_pace = segment.reference_p75_minutes / (segment.distance_m / 1000.0)
    progress_fraction = (
        observed_distance_m / segment.distance_m if segment.distance_m > 0 else 0.0
    )
    expected_fraction = min(1.0, frame.elapsed_segment_minutes / segment.reference_p75_minutes)
    movement_efficiency = (
        progress_fraction / expected_fraction if expected_fraction > 0 else None
    )
    route_pressure = (
        frame.route_pressure_review_required
        or _daylight_pressure(frame)
        or _estimated_target_buffer(frame, feed) < 0
    )
    return build_pace_gate_event(
        {
            "source_provider": feed.source_provider,
            "source_path": feed.source_path,
            "event_id": f"pace_gate:{frame.frame_id}",
            "observed_at_offset_s": frame.observed_at_offset_s,
            "observed_segment_minutes": frame.elapsed_segment_minutes,
            "reference_p75_segment_minutes": segment.reference_p75_minutes,
            "reference_max_segment_minutes": segment.reference_max_minutes,
            "observed_pace_min_per_km": observed_pace,
            "reference_p75_pace_min_per_km": reference_pace,
            "low_movement_efficiency_ratio": movement_efficiency,
            "route_pressure_review_required": route_pressure,
            "route_context": {
                "route_id": frame.route_id,
                "segment_id": frame.segment_id,
                "checkpoint_id": frame.target_checkpoint_id,
                "map_target_ids": segment.map_target_ids,
                "distance_to_next_checkpoint_m": _distance_to_next_checkpoint_m(
                    frame,
                    segment,
                ),
                "estimated_minutes_to_next_checkpoint": frame.estimated_minutes_to_target,
                "daylight_buffer_minutes": frame.daylight_buffer_minutes,
            },
            "evidence_refs": _unique_string_list(
                [
                    feed.source_path,
                    segment.source_ref,
                    *frame.evidence_refs,
                ]
            ),
            "confidence": frame.confidence,
        }
    )


def _delay_event_from_frame(
    frame: RuntimeRouteProgressFrame,
    target: RuntimePlannedTimelineTarget,
    segment: RuntimeRouteSegmentTiming,
    feed: RuntimeRouteGateFeedInput,
) -> ScoutRuntimeSafetyGateEvent:
    estimated_minutes_to_target = frame.estimated_minutes_to_target or 0.0
    estimated_arrival = frame.elapsed_route_minutes + estimated_minutes_to_target
    delay_minutes = estimated_arrival - target.planned_arrival_offset_min
    planned_buffer = (
        target.latest_arrival_offset_min - estimated_arrival
        if target.latest_arrival_offset_min is not None
        else None
    )
    deadline_missed = (
        target.latest_arrival_offset_min is not None
        and estimated_arrival > target.latest_arrival_offset_min
    )
    return build_delay_gate_event(
        {
            "source_provider": feed.source_provider,
            "source_path": feed.source_path,
            "event_id": f"delay_gate:{frame.frame_id}:{target.checkpoint_id}",
            "observed_at_offset_s": frame.observed_at_offset_s,
            "delay_minutes": max(0.0, delay_minutes),
            "planned_buffer_minutes": planned_buffer,
            "checkpoint_deadline_missed": (
                deadline_missed and target.checkpoint_kind != "camp"
            ),
            "camp_deadline_missed": (
                deadline_missed and target.checkpoint_kind == "camp"
            ),
            "route_pressure_review_required": (
                frame.route_pressure_review_required or deadline_missed
            ),
            "route_context": {
                "route_id": frame.route_id,
                "segment_id": frame.segment_id,
                "checkpoint_id": target.checkpoint_id,
                "map_target_ids": _unique_string_list(
                    [*segment.map_target_ids, *target.map_target_ids]
                ),
                "distance_to_next_checkpoint_m": _distance_to_next_checkpoint_m(
                    frame,
                    segment,
                ),
                "estimated_minutes_to_next_checkpoint": estimated_minutes_to_target,
                "estimated_minutes_to_planned_camp": estimated_minutes_to_target
                if target.checkpoint_kind == "camp"
                else None,
                "daylight_buffer_minutes": frame.daylight_buffer_minutes,
            },
            "evidence_refs": _unique_string_list(
                [
                    feed.source_path,
                    target.source_ref,
                    segment.source_ref,
                    *frame.evidence_refs,
                ]
            ),
            "confidence": frame.confidence,
        }
    )


def _darkness_event_from_frame(
    frame: RuntimeRouteProgressFrame,
    segment: RuntimeRouteSegmentTiming,
    feed: RuntimeRouteGateFeedInput,
) -> ScoutRuntimeSafetyGateEvent:
    return build_darkness_gate_event(
        {
            "source_provider": feed.source_provider,
            "source_path": feed.source_path,
            "event_id": f"darkness_gate:{frame.frame_id}",
            "observed_at_offset_s": frame.observed_at_offset_s,
            "daylight_buffer_minutes": frame.daylight_buffer_minutes,
            "minutes_to_next_safe_objective": frame.minutes_to_next_safe_objective,
            "emergency_bivy_candidate_distance_m": (
                frame.emergency_bivy_candidate_distance_m
            ),
            "route_pressure_review_required": True,
            "route_context": {
                "route_id": frame.route_id,
                "segment_id": frame.segment_id,
                "checkpoint_id": frame.target_checkpoint_id,
                "map_target_ids": segment.map_target_ids,
                "distance_to_next_checkpoint_m": _distance_to_next_checkpoint_m(
                    frame,
                    segment,
                ),
                "estimated_minutes_to_next_checkpoint": frame.estimated_minutes_to_target,
                "daylight_buffer_minutes": frame.daylight_buffer_minutes,
            },
            "evidence_refs": _unique_string_list(
                [
                    feed.source_path,
                    segment.source_ref,
                    *frame.evidence_refs,
                ]
            ),
            "confidence": frame.confidence,
        }
    )


def _distance_to_next_checkpoint_m(
    frame: RuntimeRouteProgressFrame,
    segment: RuntimeRouteSegmentTiming,
) -> float:
    return max(0.0, segment.distance_m - min(frame.observed_segment_distance_m, segment.distance_m))


def _estimated_target_buffer(frame: RuntimeRouteProgressFrame, feed: RuntimeRouteGateFeedInput) -> float:
    if frame.target_checkpoint_id is None or frame.estimated_minutes_to_target is None:
        return 0.0
    target = next(
        (
            item
            for item in feed.planned_timeline
            if item.checkpoint_id == frame.target_checkpoint_id
        ),
        None,
    )
    if target is None or target.latest_arrival_offset_min is None:
        return 0.0
    return target.latest_arrival_offset_min - (
        frame.elapsed_route_minutes + frame.estimated_minutes_to_target
    )


def _daylight_pressure(frame: RuntimeRouteProgressFrame) -> bool:
    if (
        frame.daylight_buffer_minutes is None
        or frame.minutes_to_next_safe_objective is None
    ):
        return False
    return frame.daylight_buffer_minutes < frame.minutes_to_next_safe_objective + 30.0


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


def _max_confidence(values: list[Any]) -> SafetyGateConfidence:
    rank = {"low": 0, "medium": 1, "high": 2}
    valid = [str(value) for value in values if str(value) in rank]
    if not valid:
        return "low"
    return max(valid, key=lambda item: rank[item])  # type: ignore[return-value]


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
