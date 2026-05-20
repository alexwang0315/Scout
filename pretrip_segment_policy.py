from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from mission_models import RecordingPolicy, RecordingProfile, SegmentRequirement
from pretrip_models import CandidateReviewState, PreTripPackage, PreTripSegmentCandidate


class ExpectedDurationSource(StrEnum):
    ROUTE_GUIDE_TIMING_CANDIDATE = "route_guide_timing_candidate"
    ROUTE_GEOMETRY_DISTANCE_FALLBACK = "route_geometry_distance_fallback"
    HUMAN_REVIEW_REQUIRED = "human_review_required"


class SegmentPolicyCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    label: str
    segment_candidate_id: str
    from_candidate_id: str
    to_candidate_id: str
    review_state: CandidateReviewState = CandidateReviewState.PROPOSED
    candidate_only: bool = True
    human_review_required: bool = True
    source_refs: list[str] = Field(default_factory=list)
    requirement: SegmentRequirement
    expected_duration_source: Literal[
        "route_guide_timing_candidate",
        "route_geometry_distance_fallback",
        "human_review_required",
    ]
    expected_duration_source_ref: str | None = None
    requirement_rationale: list[str] = Field(default_factory=list)
    recording_policy: RecordingPolicy
    recording_policy_rationale: list[str] = Field(default_factory=list)
    compile_boundary: Literal["candidate_only_not_runtime"] = "candidate_only_not_runtime"
    notes: str = ""


class SegmentPolicyCandidateReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    artifact_kind: Literal["segment_policy_candidates"] = "segment_policy_candidates"
    project_id: str
    status: Literal["candidate_only"] = "candidate_only"
    policy_version: str = "0.1.0"
    candidates: list[SegmentPolicyCandidate]
    counts: dict[str, int]
    notes: list[str] = Field(default_factory=list)


def build_chilai_segment_policy_candidates(
    package: PreTripPackage | dict[str, Any],
) -> SegmentPolicyCandidateReport:
    pretrip_package = (
        package if isinstance(package, PreTripPackage) else PreTripPackage.model_validate(package)
    )
    candidates = [
        _build_segment_policy_candidate(pretrip_package, segment)
        for segment in pretrip_package.segment_candidates
        if segment.review_state != CandidateReviewState.REJECTED
    ]
    retreat_candidate_count = sum(
        1 for candidate in candidates if candidate.requirement.retreat_available
    )
    signal_expected_count = sum(1 for candidate in candidates if candidate.requirement.signal_expected)
    return SegmentPolicyCandidateReport(
        artifact_id=f"segment_policy_candidates.{pretrip_package.project_id}.v0",
        project_id=pretrip_package.project_id,
        candidates=candidates,
        counts={
            "segment_policy_candidate_count": len(candidates),
            "candidate_only_count": sum(1 for candidate in candidates if candidate.candidate_only),
            "human_review_required_count": sum(
                1 for candidate in candidates if candidate.human_review_required
            ),
            "requires_daylight_count": sum(
                1 for candidate in candidates if candidate.requirement.requires_daylight
            ),
            "retreat_available_count": retreat_candidate_count,
            "signal_expected_count": signal_expected_count,
        },
        notes=[
            "Candidate-only Phase 4 segment policy output; does not write MissionGraph or live Phase 1 runtime.",
            "SegmentRequirement and RecordingPolicy payloads use mission_models-compatible shapes for later reviewed compilation.",
            "Chilai Day 1 timing candidates are route-guide level and not segment-id mapped in this fixture, so segment durations fall back to route geometry distance.",
        ],
    )


def _build_segment_policy_candidate(
    package: PreTripPackage,
    segment: PreTripSegmentCandidate,
) -> SegmentPolicyCandidate:
    duration_seconds, duration_source, duration_ref = _expected_duration_seconds(package, segment)
    retreat_available = _segment_has_retreat(package, segment)
    requirement = SegmentRequirement(
        min_device_battery=0.25,
        min_estimated_human_energy=0.40,
        expected_duration_seconds=duration_seconds,
        requires_daylight=True,
        water_available=False,
        camp_available=False,
        retreat_available=retreat_available,
        signal_expected=_signal_expected(segment),
    )
    recording_policy = _recording_policy(package, segment, retreat_available=retreat_available)
    return SegmentPolicyCandidate(
        candidate_id=f"policy_candidate.{package.project_id}.{segment.candidate_id}",
        label=f"{segment.label} policy candidate",
        segment_candidate_id=segment.candidate_id,
        from_candidate_id=segment.from_candidate_id,
        to_candidate_id=segment.to_candidate_id,
        review_state=CandidateReviewState.PROPOSED,
        source_refs=segment.source_refs,
        requirement=requirement,
        expected_duration_source=duration_source,
        expected_duration_source_ref=duration_ref,
        requirement_rationale=[
            "Daylight is required for this mountain pre-trip candidate until reviewed sun-window evidence exists.",
            "Water and camp availability are false because no reviewed segment-local water/camp POI candidate is linked.",
            _retreat_rationale(retreat_available),
            _signal_rationale(segment),
        ],
        recording_policy=recording_policy,
        recording_policy_rationale=[
            "Use conservative medium/high/raw-lock profiles for mountain pre-trip candidates.",
            "Checkpoint boundaries seal segment capsules for after-action and plan-to-runtime audit.",
            "Raw ring duration remains compatible with the existing Phase 1 RecordingPolicy model.",
        ],
        notes="Human review must accept or edit this candidate before it can be used as compile input.",
    )


def _expected_duration_seconds(
    package: PreTripPackage,
    segment: PreTripSegmentCandidate,
) -> tuple[int, str, str | None]:
    for timing in package.route_guide_timing_candidates:
        if (
            timing.segment_candidate_id == segment.candidate_id
            and timing.route_guide_segment_time_minutes is not None
        ):
            multiplier = timing.team_route_guide_multiplier or timing.personal_route_guide_multiplier or 1.0
            minutes = timing.route_guide_segment_time_minutes * multiplier
            minutes += timing.fixed_rest_minutes
            minutes *= timing.conservative_long_day_adjustment
            return (
                int(round(minutes * 60)),
                ExpectedDurationSource.ROUTE_GUIDE_TIMING_CANDIDATE,
                timing.candidate_id,
            )
    if segment.distance_m > 0:
        return (
            max(120, int(round(segment.distance_m / 0.6))),
            ExpectedDurationSource.ROUTE_GEOMETRY_DISTANCE_FALLBACK,
            segment.candidate_id,
        )
    return (0, ExpectedDurationSource.HUMAN_REVIEW_REQUIRED, None)


def _recording_policy(
    package: PreTripPackage,
    segment: PreTripSegmentCandidate,
    *,
    retreat_available: bool,
) -> RecordingPolicy:
    raw_ring_seconds = 300 if retreat_available else 240
    return RecordingPolicy(
        policy_id=f"policy.{package.project_id}.{segment.candidate_id}.candidate",
        normal_profile=RecordingProfile.MEDIUM,
        watch_profile=RecordingProfile.HIGH,
        concern_profile=RecordingProfile.RAW_LOCK,
        raw_ring_seconds=raw_ring_seconds,
        checkpoint_seals_segment=True,
    )


def _segment_has_retreat(package: PreTripPackage, segment: PreTripSegmentCandidate) -> bool:
    endpoint_ids = {segment.from_candidate_id, segment.to_candidate_id}
    return any(
        retreat.entry_checkpoint_candidate_id in endpoint_ids
        or retreat.trigger_checkpoint_candidate_id in endpoint_ids
        for retreat in package.retreat_route_candidates
        if retreat.review_state != CandidateReviewState.REJECTED
    )


def _signal_expected(segment: PreTripSegmentCandidate) -> bool:
    return segment.from_candidate_id == "cp.start"


def _retreat_rationale(retreat_available: bool) -> str:
    if retreat_available:
        return "Retreat is available because a retreat route candidate is attached to one segment endpoint."
    return "Retreat is not marked available because no retreat route candidate is attached to either segment endpoint."


def _signal_rationale(segment: PreTripSegmentCandidate) -> str:
    if _signal_expected(segment):
        return "Signal is expected only at the start-adjacent segment until reviewed signal POIs exist."
    return "Signal is not expected for deep-mountain segments without reviewed signal POI evidence."
