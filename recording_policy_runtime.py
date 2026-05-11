from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from mission_graph import MissionGraphRuntime
from mission_models import RecordingProfile, RouteSegment
from safety_models import SafetyEvent, SafetyLevel


class RecordingPolicyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: float
    segment_id: str
    control_zone_id: str
    control_zone_type: str
    recording_policy_id: str
    profile: RecordingProfile
    raw_ring_seconds: int
    safety_level: SafetyLevel
    reason: str


class RecordingPolicyRuntime:
    def __init__(self, runtime: MissionGraphRuntime):
        self.runtime = runtime
        self._segments_by_route_index = sorted(
            runtime.graph.segments,
            key=lambda segment: segment.route_point_start_index if segment.route_point_start_index is not None else 0,
        )

    def decide(
        self,
        *,
        timestamp: float,
        route_index: int,
        current_safety_level: SafetyLevel,
        pending_events: list[SafetyEvent] | None = None,
        segment_id: str | None = None,
    ) -> RecordingPolicyDecision:
        segment = (
            self.runtime.current_segment(segment_id)
            if segment_id is not None
            else self._segment_for_route_index(route_index)
        )
        zone = self.runtime.control_zone(segment.control_zone_id)
        policy = self.runtime.recording_policy(segment.recording_policy_id)
        effective_level = _effective_safety_level(current_safety_level, pending_events or [])

        if effective_level == SafetyLevel.NORMAL:
            profile = policy.normal_profile
        elif effective_level == SafetyLevel.WATCH:
            profile = policy.watch_profile
        else:
            profile = policy.concern_profile

        return RecordingPolicyDecision(
            timestamp=timestamp,
            segment_id=segment.segment_id,
            control_zone_id=zone.zone_id,
            control_zone_type=zone.zone_type,
            recording_policy_id=policy.policy_id,
            profile=profile,
            raw_ring_seconds=policy.raw_ring_seconds,
            safety_level=effective_level,
            reason=f"{effective_level.value} uses {profile.value} for {policy.policy_id} in {zone.zone_id}",
        )

    def _segment_for_route_index(self, route_index: int) -> RouteSegment:
        previous = self._segments_by_route_index[0]
        for segment in self._segments_by_route_index:
            start_index = segment.route_point_start_index
            end_index = segment.route_point_end_index
            if start_index is None or end_index is None:
                continue
            if start_index <= route_index <= end_index:
                return segment
            if route_index < start_index:
                return previous
            previous = segment
        return previous


def _effective_safety_level(current_level: SafetyLevel, pending_events: list[SafetyEvent]) -> SafetyLevel:
    levels = [current_level, *(event.level for event in pending_events)]
    return max(levels, key=_level_rank)


def _level_rank(level: SafetyLevel) -> int:
    ranks = {
        SafetyLevel.NORMAL: 0,
        SafetyLevel.WATCH: 1,
        SafetyLevel.CONCERN: 2,
        SafetyLevel.DISTRESS: 3,
        SafetyLevel.EMERGENCY: 4,
    }
    return ranks[level]
