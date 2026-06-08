from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from mission_models import (
    Checkpoint,
    CheckpointType,
    ControlZone,
    ControlZoneType,
    DiversionPoint,
    MissionGraph,
    RecordingPolicy,
    RecordingProfile,
    RouteSegment,
    SegmentRequirement,
)
from pretrip_models import CandidateReviewState, PreTripPackage


REVIEWED_STATES = {CandidateReviewState.ACCEPTED}
UNREVIEWED_STATES = {CandidateReviewState.PROPOSED, CandidateReviewState.NEEDS_REVIEW}
DEFAULT_CONTROL_ZONE_ID = "zone_pretrip_default"
DEFAULT_RECORDING_POLICY_ID = "policy_pretrip_conservative"


def compile_pretrip_mission_graph(
    package: PreTripPackage | dict[str, Any],
    *,
    allow_unreviewed: bool = False,
    diversion_points: Iterable[DiversionPoint | dict[str, Any]] | None = None,
) -> MissionGraph:
    pretrip_package = (
        package if isinstance(package, PreTripPackage) else PreTripPackage.model_validate(package)
    )
    checkpoints = _compile_checkpoints(pretrip_package, allow_unreviewed=allow_unreviewed)
    checkpoint_ids = {checkpoint.checkpoint_id for checkpoint in checkpoints}
    segments = _compile_segments(
        pretrip_package,
        checkpoint_ids=checkpoint_ids,
        allow_unreviewed=allow_unreviewed,
    )
    compiled_diversions = _compile_diversion_points(
        pretrip_package,
        checkpoints_by_id={checkpoint.checkpoint_id: checkpoint for checkpoint in checkpoints},
        explicit_diversion_points=diversion_points,
        allow_unreviewed=allow_unreviewed,
    )

    return MissionGraph(
        mission_id=f"mission.{pretrip_package.project_id}.{pretrip_package.version}",
        name=pretrip_package.route_summary.route_name,
        route_source=_route_source(pretrip_package),
        checkpoints=checkpoints,
        control_zones=[_default_control_zone()],
        recording_policies=[_default_recording_policy()],
        segments=segments,
        diversion_points=compiled_diversions,
    )


def _compile_checkpoints(
    package: PreTripPackage,
    *,
    allow_unreviewed: bool,
) -> list[Checkpoint]:
    checkpoints: list[Checkpoint] = []
    for candidate in package.checkpoint_candidates:
        _ensure_reviewed(candidate, allow_unreviewed=allow_unreviewed)
        if candidate.review_state == CandidateReviewState.REJECTED:
            continue
        checkpoints.append(
            Checkpoint(
                checkpoint_id=candidate.candidate_id,
                name=candidate.label,
                checkpoint_type=_checkpoint_type(candidate.checkpoint_type),
                lat=candidate.lat,
                lon=candidate.lon,
                arrival_radius_m=candidate.arrival_radius_m,
                compression_boundary=candidate.compression_boundary,
                must_emit_checkin=_must_emit_checkin(candidate.checkpoint_type),
                control_zone_after=DEFAULT_CONTROL_ZONE_ID,
                source=_candidate_source(candidate),
            )
        )
    if len(checkpoints) < 2:
        raise ValueError("MissionGraph compile requires at least two reviewed checkpoint candidates")
    return checkpoints


def _compile_segments(
    package: PreTripPackage,
    *,
    checkpoint_ids: set[str],
    allow_unreviewed: bool,
) -> list[RouteSegment]:
    segments: list[RouteSegment] = []
    for candidate in package.segment_candidates:
        _ensure_reviewed(candidate, allow_unreviewed=allow_unreviewed)
        if candidate.review_state == CandidateReviewState.REJECTED:
            continue
        if candidate.from_candidate_id not in checkpoint_ids or candidate.to_candidate_id not in checkpoint_ids:
            raise ValueError(
                "segment candidate references a checkpoint candidate that was not compiled: "
                f"{candidate.candidate_id}"
            )
        segments.append(
            RouteSegment(
                segment_id=candidate.candidate_id,
                from_checkpoint_id=candidate.from_candidate_id,
                to_checkpoint_id=candidate.to_candidate_id,
                control_zone_id=DEFAULT_CONTROL_ZONE_ID,
                recording_policy_id=DEFAULT_RECORDING_POLICY_ID,
                requirement=SegmentRequirement(
                    min_device_battery=0.25,
                    min_estimated_human_energy=0.40,
                    expected_duration_seconds=_expected_duration_seconds(package, candidate),
                    requires_daylight=True,
                    water_available=False,
                    camp_available=False,
                    retreat_available=_segment_has_retreat(package, candidate),
                    signal_expected=False,
                ),
                distance_m=round(candidate.distance_m, 2),
                elevation_gain_m=round(candidate.elevation_gain_m, 2),
                elevation_loss_m=round(candidate.elevation_loss_m, 2),
                route_point_start_index=candidate.route_point_start_index,
                route_point_end_index=candidate.route_point_end_index,
            )
        )
    if not segments:
        raise ValueError("MissionGraph compile requires at least one reviewed segment candidate")
    return segments


def _compile_diversion_points(
    package: PreTripPackage,
    *,
    checkpoints_by_id: dict[str, Checkpoint],
    explicit_diversion_points: Iterable[DiversionPoint | dict[str, Any]] | None,
    allow_unreviewed: bool,
) -> list[DiversionPoint]:
    diversions = [
        _coerce_diversion_point(item, allow_unreviewed=allow_unreviewed)
        for item in explicit_diversion_points or []
    ]

    for candidate in package.retreat_route_candidates:
        _ensure_reviewed(candidate, allow_unreviewed=allow_unreviewed)
        if candidate.review_state == CandidateReviewState.REJECTED:
            continue
        checkpoint = checkpoints_by_id.get(candidate.entry_checkpoint_candidate_id)
        if checkpoint is None:
            raise ValueError(
                "retreat route candidate references a checkpoint candidate that was not compiled: "
                f"{candidate.candidate_id}"
            )
        diversions.append(
            DiversionPoint(
                diversion_id=candidate.candidate_id,
                name=candidate.label,
                diversion_type=candidate.expected_use,
                lat=checkpoint.lat,
                lon=checkpoint.lon,
                distance_from_route_m=0.0,
                required_energy=0.25,
                required_daylight_seconds=1800,
                communication_available=False,
                risk_level=0.4,
            )
        )
    return diversions


def _ensure_reviewed(candidate: Any, *, allow_unreviewed: bool) -> None:
    if candidate.review_state == CandidateReviewState.REJECTED:
        return
    if candidate.review_state in REVIEWED_STATES:
        return
    if allow_unreviewed and candidate.review_state in UNREVIEWED_STATES:
        return
    raise ValueError(
        "unreviewed PreTrip candidate cannot be compiled without allow_unreviewed=True: "
        f"{candidate.candidate_id} ({candidate.review_state})"
    )


def _coerce_diversion_point(
    item: DiversionPoint | dict[str, Any],
    *,
    allow_unreviewed: bool,
) -> DiversionPoint:
    if isinstance(item, DiversionPoint):
        return item
    if "review_state" in item:
        review_state = CandidateReviewState(item["review_state"])
        if review_state == CandidateReviewState.REJECTED:
            raise ValueError(f"rejected diversion candidate cannot be compiled: {item.get('candidate_id')}")
        if review_state not in REVIEWED_STATES and not (
            allow_unreviewed and review_state in UNREVIEWED_STATES
        ):
            raise ValueError(
                "unreviewed PreTrip diversion candidate cannot be compiled without "
                f"allow_unreviewed=True: {item.get('candidate_id')} ({review_state})"
            )
    payload = {
        "diversion_id": item.get("diversion_id") or item.get("candidate_id"),
        "name": item.get("name") or item.get("label"),
        "diversion_type": item.get("diversion_type") or item.get("expected_use") or "retreat",
        "lat": item.get("lat"),
        "lon": item.get("lon"),
        "distance_from_route_m": item.get("distance_from_route_m", 0.0),
        "required_energy": item.get("required_energy", 0.0),
        "required_daylight_seconds": item.get("required_daylight_seconds", 0),
        "communication_available": item.get("communication_available", False),
        "risk_level": item.get("risk_level", 0.0),
    }
    return DiversionPoint.model_validate(payload)


def _route_source(package: PreTripPackage) -> str:
    route_artifact_id = package.route_summary.artifact_id
    for artifact in package.source_artifacts:
        if artifact.artifact_id == route_artifact_id:
            return artifact.uri
    return route_artifact_id


def _default_control_zone() -> ControlZone:
    return ControlZone(
        zone_id=DEFAULT_CONTROL_ZONE_ID,
        zone_type=ControlZoneType.UNKNOWN,
        name="PreTrip default control zone",
        expected_gps_reliability=0.6,
        expected_communication_quality=0.3,
        slope_risk=0.2,
        notes="Conservative compiler default until reviewed terrain zones are available.",
    )


def _default_recording_policy() -> RecordingPolicy:
    return RecordingPolicy(
        policy_id=DEFAULT_RECORDING_POLICY_ID,
        normal_profile=RecordingProfile.MEDIUM,
        watch_profile=RecordingProfile.HIGH,
        concern_profile=RecordingProfile.RAW_LOCK,
        raw_ring_seconds=300,
        checkpoint_seals_segment=True,
    )


def _checkpoint_type(value: str) -> CheckpointType:
    try:
        return CheckpointType(value)
    except ValueError:
        return CheckpointType.WAYPOINT


def _must_emit_checkin(checkpoint_type: str) -> bool:
    return checkpoint_type in {
        CheckpointType.START.value,
        CheckpointType.FINISH.value,
        CheckpointType.CAMP.value,
        CheckpointType.HIGH_RISK_ENTRY.value,
        CheckpointType.RETREAT_POINT.value,
        CheckpointType.RIDGE_ENTRY.value,
        CheckpointType.WATER_SOURCE.value,
    }


def _candidate_source(candidate: Any) -> str:
    if candidate.source_refs:
        return ",".join(candidate.source_refs)
    if candidate.provenance:
        return candidate.provenance[0].uri
    return "pretrip_candidate"


def _expected_duration_seconds(package: PreTripPackage, segment_candidate: Any) -> int:
    for timing in package.route_guide_timing_candidates:
        if (
            timing.segment_candidate_id == segment_candidate.candidate_id
            and timing.route_guide_segment_time_minutes is not None
        ):
            multiplier = timing.team_route_guide_multiplier or timing.personal_route_guide_multiplier or 1.0
            minutes = timing.route_guide_segment_time_minutes * multiplier
            minutes += timing.fixed_rest_minutes
            minutes *= timing.conservative_long_day_adjustment
            return int(round(minutes * 60))
    if segment_candidate.distance_m <= 0:
        return 0
    return max(120, int(round(segment_candidate.distance_m / 0.6)))


def _segment_has_retreat(package: PreTripPackage, segment_candidate: Any) -> bool:
    endpoint_ids = {segment_candidate.from_candidate_id, segment_candidate.to_candidate_id}
    return any(
        retreat.entry_checkpoint_candidate_id in endpoint_ids
        or retreat.trigger_checkpoint_candidate_id in endpoint_ids
        for retreat in package.retreat_route_candidates
    )
