from __future__ import annotations

import math
import re
from collections import Counter
from datetime import timezone
from typing import Iterable

from spatial_imprint_models import (
    SpatialImprint,
    SpatialImprintPayload,
    SpatialImprintPredicate,
    SpatialImprintSet,
    SpatialImprintTriggerContext,
    SpatialImprintTriggerDryRunReport,
    SpatialImprintTriggerEvent,
    SpatialImprintQueuedPayload,
    SpatialPredicateEvaluation,
    parse_spatial_datetime,
)
from voice_cue_models import VoiceCue, VoiceCueRepeatPolicy


EARTH_RADIUS_M = 6_371_000.0


def evaluate_spatial_imprints(
    imprint_set: SpatialImprintSet,
    context: SpatialImprintTriggerContext,
    *,
    previous_trigger_keys: Iterable[str] = (),
) -> SpatialImprintTriggerDryRunReport:
    previous = set(previous_trigger_keys)
    events = [
        evaluate_spatial_imprint(
            imprint,
            context,
            previous_trigger_keys=previous,
            sequence=index,
        )
        for index, imprint in enumerate(imprint_set.imprints, start=1)
    ]
    counts = Counter(event.status for event in events)
    counts["event_count"] = len(events)
    return SpatialImprintTriggerDryRunReport(
        trip_id=imprint_set.trip_id,
        client_id=context.client_id,
        observed_at=context.observed_at,
        events=events,
        counts=dict(counts),
    )


def evaluate_spatial_imprint(
    imprint: SpatialImprint,
    context: SpatialImprintTriggerContext,
    *,
    previous_trigger_keys: set[str] | None = None,
    sequence: int = 1,
) -> SpatialImprintTriggerEvent:
    previous = previous_trigger_keys or set()
    event_id = f"spatial_imprint_trigger.{_safe_token(imprint.imprint_id)}.{sequence:06d}"
    inactive_status = _inactive_status(imprint, context)
    if inactive_status is not None:
        return SpatialImprintTriggerEvent(
            event_id=event_id,
            imprint_id=imprint.imprint_id,
            client_id=context.client_id,
            triggered_at=context.observed_at,
            status=inactive_status,
            suppressed=inactive_status != "not_triggered",
            suppression_reason=inactive_status,
        )

    if not _audience_matches(imprint, context):
        return SpatialImprintTriggerEvent(
            event_id=event_id,
            imprint_id=imprint.imprint_id,
            client_id=context.client_id,
            triggered_at=context.observed_at,
            status="suppressed",
            suppressed=True,
            suppression_reason="audience_mismatch",
        )

    trigger_key = trigger_dedupe_key(imprint, context)
    if imprint.trigger_policy.once_per_client and trigger_key in previous:
        return SpatialImprintTriggerEvent(
            event_id=event_id,
            imprint_id=imprint.imprint_id,
            client_id=context.client_id,
            triggered_at=context.observed_at,
            status="suppressed",
            suppressed=True,
            suppression_reason="once_per_client_already_triggered",
        )

    evaluations = [
        evaluate_predicate(predicate, imprint=imprint, context=context)
        for predicate in imprint.trigger.predicates
    ]
    matched = _combined_match(imprint.trigger.operator, evaluations)
    if not matched:
        return SpatialImprintTriggerEvent(
            event_id=event_id,
            imprint_id=imprint.imprint_id,
            client_id=context.client_id,
            triggered_at=context.observed_at,
            status="not_triggered",
            matched_predicates=[
                item.predicate_type for item in evaluations if item.matched
            ],
            failed_predicates=[item for item in evaluations if not item.matched],
        )

    queued_payload = _queued_payload(imprint.payload, imprint=imprint, event_id=event_id)
    return SpatialImprintTriggerEvent(
        event_id=event_id,
        imprint_id=imprint.imprint_id,
        client_id=context.client_id,
        triggered_at=context.observed_at,
        status="triggered",
        matched_predicates=[item.predicate_type for item in evaluations if item.matched],
        failed_predicates=[item for item in evaluations if not item.matched],
        queued_payload=queued_payload,
    )


def evaluate_predicate(
    predicate: SpatialImprintPredicate,
    *,
    imprint: SpatialImprint,
    context: SpatialImprintTriggerContext,
) -> SpatialPredicateEvaluation:
    if predicate.type == "horizontal_radius":
        return _eval_horizontal_radius(predicate, context)
    if predicate.type == "altitude_range":
        return _eval_altitude_range(predicate, context)
    if predicate.type == "vertical_delta_from_anchor":
        return _eval_vertical_delta(predicate, imprint, context)
    if predicate.type == "heading_sector":
        return _eval_heading_sector(predicate, context)
    if predicate.type == "route_progress_window":
        return _eval_route_progress_window(predicate, context)
    if predicate.type == "before_cp":
        return _eval_before_cp(predicate, context)
    if predicate.type == "inside_cp_radius":
        return _eval_inside_cp_radius(predicate, context)
    if predicate.type == "inside_segment":
        return _eval_inside_segment(predicate, context)
    if predicate.type == "inside_risk_zone":
        return _eval_inside_risk_zone(predicate, context)
    if predicate.type == "risk_score_min":
        return _eval_risk_score_min(predicate, context)
    if predicate.type == "sensor_state":
        return _eval_sensor_state(predicate, context)
    if predicate.type == "time_window":
        return _eval_time_window(predicate, context)
    if predicate.type == "client_group_match":
        return _eval_client_group_match(predicate, context)
    if predicate.type in {"all", "any"}:
        children = [
            evaluate_predicate(
                SpatialImprintPredicate.model_validate(child),
                imprint=imprint,
                context=context,
            )
            for child in predicate.predicates
        ]
        matched = _combined_match(predicate.type, children)
        return SpatialPredicateEvaluation(
            predicate_type=predicate.type,
            matched=matched,
            reason="nested predicates matched" if matched else "nested predicates did not match",
            details={"children": [child.model_dump(mode="json") for child in children]},
        )
    return SpatialPredicateEvaluation(
        predicate_type=predicate.type,
        matched=False,
        reason="unsupported predicate",
    )


def voice_cue_from_trigger_event(
    imprint: SpatialImprint,
    event: SpatialImprintTriggerEvent,
) -> VoiceCue:
    if event.status != "triggered":
        raise ValueError("voice cue can only be built from triggered imprint events")
    if imprint.payload.payload_type != "voice_cue":
        raise ValueError("spatial imprint payload is not a voice_cue")
    text = imprint.payload.text_zh
    if not text:
        raise ValueError("voice_cue payload requires text_zh")
    return VoiceCue(
        cue_id=event.queued_payload.cue_id if event.queued_payload else _voice_cue_id(imprint, event.event_id),
        priority=imprint.payload.voice_priority,
        category=imprint.payload.voice_category,
        text_zh=text,
        source_event_refs=[event.event_id, *[source.source_id for source in imprint.source_refs]],
        source_kind=imprint.payload.source_kind,
        confidence=1.0 if not event.failed_predicates else 0.75,
        expires_at=imprint.lifecycle.expires_at,
        repeat_policy=VoiceCueRepeatPolicy(
            dedupe_key=imprint.dedupe_key,
            min_interval_seconds=imprint.trigger_policy.retrigger_after_seconds or 300,
            max_repeats=1 if imprint.trigger_policy.once_per_client else None,
        ),
        require_ack=imprint.trigger_policy.suppress_if_acknowledged,
    )


def trigger_dedupe_key(imprint: SpatialImprint, context: SpatialImprintTriggerContext) -> str:
    return f"{context.client_id}:{imprint.dedupe_key}"


def _inactive_status(
    imprint: SpatialImprint,
    context: SpatialImprintTriggerContext,
) -> str | None:
    if imprint.lifecycle.state == "disabled":
        return "inactive"
    if imprint.lifecycle.state == "deleted_tombstone":
        return "inactive"
    if imprint.lifecycle.expires_at is not None:
        expires_at = parse_spatial_datetime(imprint.lifecycle.expires_at)
        observed_at = parse_spatial_datetime(context.observed_at)
        if observed_at >= expires_at:
            return "expired"
    return None


def _audience_matches(imprint: SpatialImprint, context: SpatialImprintTriggerContext) -> bool:
    audience = imprint.audience
    if context.client_id in audience.exclude_actor_refs:
        return False
    if audience.scope in {"registered_trip_clients", "all_registered_clients"}:
        if not audience.client_group_refs:
            return True
        return bool(set(audience.client_group_refs) & set(context.client_group_refs))
    if audience.scope == "specific_clients":
        return context.client_id in audience.client_refs
    if audience.scope == "leader_only":
        return "leader" in context.client_group_refs or context.client_id in audience.client_refs
    if audience.scope == "scout_centre_clients":
        return "scout_centre_clients" in context.client_group_refs
    return False


def _eval_horizontal_radius(
    predicate: SpatialImprintPredicate,
    context: SpatialImprintTriggerContext,
) -> SpatialPredicateEvaluation:
    if context.position is None:
        return _eval(predicate, False, "position unavailable")
    distance = haversine_m(
        context.position.lat,
        context.position.lon,
        predicate.lat,
        predicate.lon,
    )
    return _eval(
        predicate,
        distance <= predicate.radius_m,
        "inside horizontal radius" if distance <= predicate.radius_m else "outside horizontal radius",
        distance_m=round(distance, 2),
        radius_m=predicate.radius_m,
    )


def _eval_altitude_range(
    predicate: SpatialImprintPredicate,
    context: SpatialImprintTriggerContext,
) -> SpatialPredicateEvaluation:
    altitude = context.position.altitude_m if context.position is not None else None
    if altitude is None:
        return _eval(predicate, False, "altitude unavailable")
    matched = predicate.min_m <= altitude <= predicate.max_m
    return _eval(
        predicate,
        matched,
        "altitude in range" if matched else "altitude outside range",
        altitude_m=altitude,
        min_m=predicate.min_m,
        max_m=predicate.max_m,
    )


def _eval_vertical_delta(
    predicate: SpatialImprintPredicate,
    imprint: SpatialImprint,
    context: SpatialImprintTriggerContext,
) -> SpatialPredicateEvaluation:
    altitude = context.position.altitude_m if context.position is not None else None
    anchor_altitude = imprint.anchor.coordinate.altitude_m if imprint.anchor.coordinate else None
    if altitude is None or anchor_altitude is None:
        return _eval(predicate, False, "altitude or anchor altitude unavailable")
    delta = altitude - anchor_altitude
    matched = predicate.min_m <= delta <= predicate.max_m
    return _eval(
        predicate,
        matched,
        "vertical delta in range" if matched else "vertical delta outside range",
        delta_m=round(delta, 2),
        min_m=predicate.min_m,
        max_m=predicate.max_m,
    )


def _eval_heading_sector(
    predicate: SpatialImprintPredicate,
    context: SpatialImprintTriggerContext,
) -> SpatialPredicateEvaluation:
    heading = context.motion.heading_degrees
    if heading is None:
        return _eval(predicate, False, "heading unavailable")
    delta = angular_delta_degrees(heading, predicate.center_degrees)
    matched = delta <= predicate.half_width_degrees
    return _eval(
        predicate,
        matched,
        "heading in sector" if matched else "heading outside sector",
        heading_degrees=heading,
        center_degrees=predicate.center_degrees,
        delta_degrees=round(delta, 2),
    )


def _eval_route_progress_window(
    predicate: SpatialImprintPredicate,
    context: SpatialImprintTriggerContext,
) -> SpatialPredicateEvaluation:
    progress = context.route_progress.progress_m
    if progress is None:
        return _eval(predicate, False, "route progress unavailable")
    matched = predicate.start_distance_m <= progress <= predicate.end_distance_m
    return _eval(
        predicate,
        matched,
        "route progress in window" if matched else "route progress outside window",
        progress_m=progress,
        start_distance_m=predicate.start_distance_m,
        end_distance_m=predicate.end_distance_m,
    )


def _eval_before_cp(
    predicate: SpatialImprintPredicate,
    context: SpatialImprintTriggerContext,
) -> SpatialPredicateEvaluation:
    matched = (
        context.route_progress.nearest_cp_ref == predicate.cp_ref
        and context.route_progress.distance_to_nearest_cp_m is not None
        and context.route_progress.distance_to_nearest_cp_m <= predicate.radius_m
    )
    return _eval(
        predicate,
        matched,
        "before cp within radius" if matched else "not before cp within radius",
        nearest_cp_ref=context.route_progress.nearest_cp_ref,
        distance_to_nearest_cp_m=context.route_progress.distance_to_nearest_cp_m,
        radius_m=predicate.radius_m,
    )


def _eval_inside_cp_radius(
    predicate: SpatialImprintPredicate,
    context: SpatialImprintTriggerContext,
) -> SpatialPredicateEvaluation:
    matched = (
        context.route_progress.nearest_cp_ref == predicate.cp_ref
        and context.route_progress.distance_to_nearest_cp_m is not None
        and context.route_progress.distance_to_nearest_cp_m <= predicate.radius_m
    )
    return _eval(
        predicate,
        matched,
        "inside cp radius" if matched else "outside cp radius",
        nearest_cp_ref=context.route_progress.nearest_cp_ref,
        distance_to_nearest_cp_m=context.route_progress.distance_to_nearest_cp_m,
    )


def _eval_inside_segment(
    predicate: SpatialImprintPredicate,
    context: SpatialImprintTriggerContext,
) -> SpatialPredicateEvaluation:
    matched = context.route_progress.segment_ref == predicate.segment_ref
    return _eval(
        predicate,
        matched,
        "inside segment" if matched else "outside segment",
        segment_ref=context.route_progress.segment_ref,
    )


def _eval_inside_risk_zone(
    predicate: SpatialImprintPredicate,
    context: SpatialImprintTriggerContext,
) -> SpatialPredicateEvaluation:
    matched = predicate.risk_zone_ref in context.risk_context.risk_zone_refs
    return _eval(
        predicate,
        matched,
        "inside risk zone" if matched else "outside risk zone",
        risk_zone_refs=context.risk_context.risk_zone_refs,
    )


def _eval_risk_score_min(
    predicate: SpatialImprintPredicate,
    context: SpatialImprintTriggerContext,
) -> SpatialPredicateEvaluation:
    score = context.risk_context.risk_score
    if score is None:
        return _eval(predicate, False, "risk score unavailable")
    matched = score >= predicate.risk_score_min
    return _eval(
        predicate,
        matched,
        "risk score above threshold" if matched else "risk score below threshold",
        risk_score=score,
        risk_score_min=predicate.risk_score_min,
    )


def _eval_sensor_state(
    predicate: SpatialImprintPredicate,
    context: SpatialImprintTriggerContext,
) -> SpatialPredicateEvaluation:
    sensor = context.sensor_state
    failures: list[str] = []
    if predicate.requires_barometer and not sensor.barometer_available:
        failures.append("barometer_unavailable")
    if predicate.requires_magnetometer and not sensor.magnetometer_available:
        failures.append("magnetometer_unavailable")
    if predicate.requires_imu and not sensor.imu_available:
        failures.append("imu_unavailable")
    if (
        predicate.requires_gnss_confidence_min is not None
        and (sensor.gnss_confidence is None or sensor.gnss_confidence < predicate.requires_gnss_confidence_min)
    ):
        failures.append("gnss_confidence_low")
    if (
        predicate.requires_pdr_confidence_min is not None
        and (sensor.pdr_confidence is None or sensor.pdr_confidence < predicate.requires_pdr_confidence_min)
    ):
        failures.append("pdr_confidence_low")
    return _eval(
        predicate,
        not failures,
        "sensor state matched" if not failures else "sensor state failed",
        failures=failures,
    )


def _eval_time_window(
    predicate: SpatialImprintPredicate,
    context: SpatialImprintTriggerContext,
) -> SpatialPredicateEvaluation:
    observed = parse_spatial_datetime(context.observed_at)
    starts_at = parse_spatial_datetime(predicate.starts_at) if predicate.starts_at else None
    ends_at = parse_spatial_datetime(predicate.ends_at) if predicate.ends_at else None
    matched = (starts_at is None or observed >= starts_at) and (ends_at is None or observed <= ends_at)
    return _eval(
        predicate,
        matched,
        "time window matched" if matched else "time window failed",
        observed_at=observed.astimezone(timezone.utc).isoformat(),
    )


def _eval_client_group_match(
    predicate: SpatialImprintPredicate,
    context: SpatialImprintTriggerContext,
) -> SpatialPredicateEvaluation:
    matched = predicate.client_group_ref in context.client_group_refs
    return _eval(
        predicate,
        matched,
        "client group matched" if matched else "client group did not match",
        client_group_refs=context.client_group_refs,
    )


def _combined_match(operator: str, evaluations: list[SpatialPredicateEvaluation]) -> bool:
    if operator == "any":
        return any(item.matched for item in evaluations)
    return all(item.matched for item in evaluations)


def _queued_payload(
    payload: SpatialImprintPayload,
    *,
    imprint: SpatialImprint,
    event_id: str,
) -> SpatialImprintQueuedPayload | None:
    if payload.payload_type == "voice_cue":
        return SpatialImprintQueuedPayload(
            payload_type="voice_cue",
            cue_id=_voice_cue_id(imprint, event_id),
            text_zh=payload.text_zh,
        )
    if payload.payload_type in {"ui_cue", "leader_message", "note_append"}:
        return SpatialImprintQueuedPayload(
            payload_type=payload.payload_type,
            text_zh=payload.text_zh,
        )
    return SpatialImprintQueuedPayload(payload_type=payload.payload_type)


def _voice_cue_id(imprint: SpatialImprint, event_id: str) -> str:
    return f"voice_cue.spatial_imprint.{_safe_token(imprint.imprint_id)}.{_safe_token(event_id)}"


def _eval(
    predicate: SpatialImprintPredicate,
    matched: bool,
    reason: str,
    **details: object,
) -> SpatialPredicateEvaluation:
    return SpatialPredicateEvaluation(
        predicate_type=predicate.type,
        matched=matched,
        reason=reason,
        details={key: value for key, value in details.items() if value is not None},
    )


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def angular_delta_degrees(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


def _safe_token(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.:-]+", "_", value)
