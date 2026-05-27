from __future__ import annotations

from spatial_imprint_models import (
    SpatialImprint,
    SpatialImprintSet,
    SpatialImprintTriggerContext,
)
from spatial_imprint_trigger import (
    evaluate_spatial_imprint,
    evaluate_spatial_imprints,
    trigger_dedupe_key,
    voice_cue_from_trigger_event,
)


def test_trigger_matches_route_altitude_heading_and_risk_context() -> None:
    imprint = _imprint()
    context = _context()

    event = evaluate_spatial_imprint(imprint, context)
    cue = voice_cue_from_trigger_event(imprint, event)

    assert event.status == "triggered"
    assert event.suppressed is False
    assert set(event.matched_predicates) == {
        "route_progress_window",
        "horizontal_radius",
        "altitude_range",
        "heading_sector",
        "inside_risk_zone",
        "risk_score_min",
        "inside_segment",
        "client_group_match",
    }
    assert event.queued_payload is not None
    assert event.queued_payload.payload_type == "voice_cue"
    assert cue.priority == "warning"
    assert cue.category == "environment"
    assert cue.boundary.phase1_safety_runtime_mutation_allowed is False
    assert cue.boundary.remote_outbound_allowed is False


def test_trigger_records_failed_predicate_reasons() -> None:
    context = _context()
    context = context.model_copy(
        update={
            "position": context.position.model_copy(update={"altitude_m": 2700.0}),
            "motion": context.motion.model_copy(update={"heading_degrees": 120.0}),
        }
    )

    event = evaluate_spatial_imprint(_imprint(), context)

    assert event.status == "not_triggered"
    failures = {item.predicate_type: item.reason for item in event.failed_predicates}
    assert failures["altitude_range"] == "altitude outside range"
    assert failures["heading_sector"] == "heading outside sector"


def test_trigger_suppresses_once_per_client_previous_key() -> None:
    imprint = _imprint()
    context = _context()

    event = evaluate_spatial_imprint(
        imprint,
        context,
        previous_trigger_keys={trigger_dedupe_key(imprint, context)},
    )

    assert event.status == "suppressed"
    assert event.suppression_reason == "once_per_client_already_triggered"


def test_dry_run_report_counts_triggered_and_expired_imprints() -> None:
    active = _imprint()
    expired = _imprint(
        imprint_id="spatial_imprint.chilai.expired",
            lifecycle={
                "state": "active",
                "scope": "ttl_scoped",
                "expires_at": "2026-05-26T09:00:00+08:00",
            },
        )

    report = evaluate_spatial_imprints(
        SpatialImprintSet(trip_id="chilai_nanhua_day1", imprints=[active, expired]),
        _context(),
    )

    assert report.counts["event_count"] == 2
    assert report.counts["triggered"] == 1
    assert report.counts["expired"] == 1
    assert report.boundary.live_safety_api_calls_allowed is False


def _imprint(**overrides) -> SpatialImprint:
    payload = {
        "imprint_id": "spatial_imprint.chilai.00042",
        "label": "前方大崩壁",
        "kind": "route_warning",
        "severity": "warning",
        "planting_source": "pretrip_reviewed",
        "created_at": "2026-05-26T10:00:00+08:00",
        "created_by": {"actor_type": "operator", "actor_ref": "trip_leader"},
        "anchor": {
            "anchor_type": "route_progress",
            "route_id": "chilai_nanhua_day1",
            "segment_ref": "segment_017",
            "cp_ref": "cp_018",
            "distance_m": 8420.0,
            "trigger_before_m": 50.0,
            "coordinate": {
                "lat": 24.0301,
                "lon": 121.2842,
                "altitude_m": 2890.0,
            },
        },
        "trigger": {
            "operator": "all",
            "predicates": [
                {
                    "type": "route_progress_window",
                    "start_distance_m": 8370.0,
                    "end_distance_m": 8420.0,
                },
                {
                    "type": "horizontal_radius",
                    "lat": 24.0301,
                    "lon": 121.2842,
                    "radius_m": 45.0,
                },
                {"type": "altitude_range", "min_m": 2860.0, "max_m": 2920.0},
                {
                    "type": "heading_sector",
                    "center_degrees": 315.0,
                    "half_width_degrees": 60.0,
                },
                {"type": "inside_risk_zone", "risk_zone_ref": "risk_zone.collapse_wall.017"},
                {"type": "risk_score_min", "risk_score_min": 0.72},
                {"type": "inside_segment", "segment_ref": "segment_017"},
                {"type": "client_group_match", "client_group_ref": "current_trip_party"},
            ],
        },
        "payload": {
            "payload_type": "voice_cue",
            "text_zh": "前方約五十公尺有大崩壁，請靠內側通行並縮短隊伍間距。",
            "voice_priority": "warning",
            "voice_category": "environment",
        },
        "audience": {
            "scope": "registered_trip_clients",
            "client_group_refs": ["current_trip_party"],
        },
        "trigger_policy": {"dedupe_key": "collapse.wall.017"},
        "source_refs": [
            {
                "source_id": "route_note.reviewed.018",
                "source_path": "reviews/route_note_reviewed_assumptions.json",
            }
        ],
    }
    payload.update(overrides)
    return SpatialImprint.model_validate(payload)


def _context() -> SpatialImprintTriggerContext:
    return SpatialImprintTriggerContext.model_validate(
        {
            "client_id": "client.alex.watch",
            "scout_machine_id": "scout.pi5.alpha01",
            "trip_id": "chilai_nanhua_day1",
            "observed_at": "2026-05-26T10:03:00+08:00",
            "client_group_refs": ["current_trip_party"],
            "position": {
                "lat": 24.0300,
                "lon": 121.2840,
                "altitude_m": 2888.0,
                "horizontal_accuracy_m": 18.0,
                "vertical_accuracy_m": 12.0,
                "source": "gnss_pdr_fused",
            },
            "motion": {
                "heading_degrees": 318.0,
                "heading_source": "compass",
                "speed_mps": 0.8,
                "stationary": False,
            },
            "route_progress": {
                "route_id": "chilai_nanhua_day1",
                "segment_ref": "segment_017",
                "progress_m": 8395.0,
                "nearest_cp_ref": "cp_018",
                "distance_to_nearest_cp_m": 42.0,
            },
            "risk_context": {
                "risk_score": 0.78,
                "risk_zone_refs": ["risk_zone.collapse_wall.017"],
            },
            "sensor_state": {
                "barometer_available": True,
                "magnetometer_available": True,
                "imu_available": True,
                "gnss_confidence": 0.62,
                "pdr_confidence": 0.55,
            },
        }
    )
