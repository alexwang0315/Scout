from __future__ import annotations

from dataclasses import dataclass, field

from phase2_brain_models import (
    BeaconNode,
    ConfidenceLevel,
    SignalBearingMeasurement,
    TeamSeparationEvent,
)


@dataclass(frozen=True)
class TeamMemberEvidence:
    member_id: str
    observed_at: str
    evidence_ref: str
    freshness_seconds: int | None = None
    latest_checkpoint: str | None = None
    group_checkpoint: str | None = None
    estimated_distance_from_group_m: float | None = None


@dataclass(frozen=True)
class RssiTrendSample:
    measured_at: str
    rssi_dbm: int | float | None
    evidence_ref: str
    movement_hint: str | None = None


@dataclass(frozen=True)
class TeamSeparationThresholds:
    stale_after_seconds: int = 600
    separated_after_meters: float = 300.0


def detect_team_separation_event(
    *,
    team_id: str,
    detected_at: str,
    member_evidence: list[TeamMemberEvidence],
    thresholds: TeamSeparationThresholds = TeamSeparationThresholds(),
) -> TeamSeparationEvent | None:
    divergent_members: list[str] = []
    evidence_refs: list[str] = []
    reasons: list[str] = []

    for evidence in member_evidence:
        member_reasons = _separation_reasons(evidence, thresholds)
        if not member_reasons:
            continue

        divergent_members.append(evidence.member_id)
        evidence_refs.append(evidence.evidence_ref)
        reasons.extend(member_reasons)

    if not divergent_members:
        return None

    severity = _severity_for(reasons)
    return TeamSeparationEvent(
        id=f"team_separation.{_slug(team_id)}.{_timestamp_slug(detected_at)}",
        team_id=team_id,
        detected_at=detected_at,
        member_ids=divergent_members,
        evidence_refs=sorted(set(evidence_refs)),
        severity=severity,
        reason="; ".join(_dedupe(reasons)),
    )


def create_rendezvous_beacon(
    *,
    beacon_id: str,
    source_device_id: str,
    designated_at: str,
    rendezvous_ref: str | None = None,
    mission_id: str | None = None,
    artifact_refs: list[str] | None = None,
) -> BeaconNode:
    return BeaconNode(
        id=beacon_id,
        mission_id=mission_id,
        source_device_id=source_device_id,
        designated_at=designated_at,
        mode="mock",
        rendezvous_ref=rendezvous_ref,
        uncertainty=ConfidenceLevel.UNKNOWN,
        active=True,
        artifact_refs=artifact_refs or [],
    )


def generate_signal_bearing_measurement(
    *,
    measurement_id: str,
    beacon_id: str,
    observer_device_id: str,
    samples: list[RssiTrendSample],
    signal_type: str = "mock",
) -> SignalBearingMeasurement:
    if not samples:
        raise ValueError("at least one RSSI trend sample is required")

    trend = _rssi_trend(samples)
    confidence = _confidence_for_trend(samples, trend)
    movement_hint = _latest_movement_hint(samples)
    direction_hint = _direction_hint(trend, movement_hint)

    return SignalBearingMeasurement(
        id=measurement_id,
        beacon_id=beacon_id,
        observer_device_id=observer_device_id,
        measured_at=samples[-1].measured_at,
        signal_type=signal_type,
        trend=trend,
        confidence=confidence,
        evidence_refs=sorted({sample.evidence_ref for sample in samples}),
        direction_hint=direction_hint,
        exact_position_claimed=False,
    )


def _separation_reasons(
    evidence: TeamMemberEvidence, thresholds: TeamSeparationThresholds
) -> list[str]:
    reasons: list[str] = []
    if (
        evidence.freshness_seconds is not None
        and evidence.freshness_seconds >= thresholds.stale_after_seconds
    ):
        reasons.append(
            f"{evidence.member_id} freshness is stale by mock status evidence"
        )

    if (
        evidence.latest_checkpoint
        and evidence.group_checkpoint
        and evidence.latest_checkpoint != evidence.group_checkpoint
    ):
        reasons.append(
            f"{evidence.member_id} checkpoint evidence diverges from group checkpoint"
        )

    if (
        evidence.estimated_distance_from_group_m is not None
        and evidence.estimated_distance_from_group_m >= thresholds.separated_after_meters
    ):
        reasons.append(
            f"{evidence.member_id} distance estimate diverges from group envelope"
        )

    return reasons


def _severity_for(reasons: list[str]) -> str:
    reason_count = len(reasons)
    if reason_count >= 3:
        return "confirmed"
    if reason_count >= 2:
        return "likely"
    return "possible"


def _rssi_trend(samples: list[RssiTrendSample]) -> str:
    values = [sample.rssi_dbm for sample in samples if sample.rssi_dbm is not None]
    if not values:
        return "lost"
    if len(values) == 1:
        return "unknown"

    delta = values[-1] - values[0]
    if delta >= 3:
        return "improving"
    if delta <= -3:
        return "weakening"
    return "stable"


def _confidence_for_trend(samples: list[RssiTrendSample], trend: str) -> ConfidenceLevel:
    if trend in {"lost", "unknown"}:
        return ConfidenceLevel.LOW
    if len(samples) >= 3:
        return ConfidenceLevel.MEDIUM
    return ConfidenceLevel.LOW


def _latest_movement_hint(samples: list[RssiTrendSample]) -> str | None:
    for sample in reversed(samples):
        if sample.movement_hint:
            return sample.movement_hint
    return None


def _direction_hint(trend: str, movement_hint: str | None) -> str | None:
    if trend == "improving" and movement_hint:
        return f"signal improved while moving {movement_hint}"
    if trend == "weakening" and movement_hint:
        return f"signal weakened while moving {movement_hint}"
    if trend == "stable":
        return "signal stayed roughly stable; continue comparing trend samples"
    if trend == "lost":
        return "signal was not observed in mock samples"
    return None


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _slug(value: str) -> str:
    return value.replace(".", "_").replace(":", "").replace("/", "_")


def _timestamp_slug(value: str) -> str:
    return (
        value.replace("-", "")
        .replace(":", "")
        .replace("+", "")
        .replace("T", "T")
    )
