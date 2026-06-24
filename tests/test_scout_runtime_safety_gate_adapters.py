from __future__ import annotations

import json

import pytest

from scout_runtime_safety_gate_adapters import (
    EnvironmentThreatGateObservation,
    build_darkness_gate_event,
    build_delay_gate_event,
    build_environment_threat_gate_event,
    build_pace_gate_event,
    build_runtime_safety_gate_events_from_fixture,
    build_weather_gate_event,
)
from scout_runtime_safety_gate_models import build_runtime_safety_gate_event_batch


def test_gate_adapters_emit_sanitized_runtime_gate_events() -> None:
    events = build_runtime_safety_gate_events_from_fixture(
        {
            "pace": {
                "event_id": "pace_gate:slow-segment",
                "source_path": "outputs/runtime/pace.json",
                "observed_segment_minutes": 90,
                "reference_p75_segment_minutes": 50,
                "observed_pace_min_per_km": 18,
                "reference_p75_pace_min_per_km": 10,
                "route_pressure_review_required": True,
                "route_context": {
                    "route_id": "fixture.route",
                    "segment_id": "seg.001",
                    "checkpoint_id": "cp.001",
                },
                "evidence_refs": ["reference_segment_timing.json#seg.001"],
            },
            "delay": {
                "event_id": "delay_gate:buffer-used",
                "source_path": "outputs/runtime/delay.json",
                "delay_minutes": 38,
                "planned_buffer_minutes": 20,
                "route_context": {"segment_id": "seg.001"},
            },
            "darkness": {
                "event_id": "darkness_gate:negative-margin",
                "source_path": "outputs/runtime/darkness.json",
                "daylight_buffer_minutes": 25,
                "minutes_to_next_safe_objective": 70,
                "route_context": {"segment_id": "seg.001"},
            },
            "weather": {
                "event_id": "weather_gate:unsafe-wind",
                "source_path": "outputs/runtime/weather.json",
                "warning_level": "unsafe",
                "warning_type": "wind",
                "wind_risk": True,
                "source_age_minutes": 20,
                "route_context": {"segment_id": "seg.001"},
            },
            "environment_threat": {
                "event_id": "environment_threat_gate:washout",
                "source_path": "outputs/runtime/environment.json",
                "threat_type": "washout",
                "passability": "blocked",
                "route_blocked": True,
                "route_context": {"segment_id": "seg.001"},
            },
        }
    )
    batch = build_runtime_safety_gate_event_batch(events)
    serialized = json.dumps(batch.model_dump(mode="json"), sort_keys=True)

    assert [event.gate_id for event in events] == [
        "pace_gate",
        "delay_gate",
        "darkness_gate",
        "weather_gate",
        "environment_threat_gate",
    ]
    assert events[0].severity == "retreat_review"
    assert events[0].ln_level_candidate == "L3_RETREAT"
    assert events[1].severity == "rest"
    assert events[2].severity == "alert_review"
    assert events[3].severity == "retreat_review"
    assert events[4].severity == "retreat_review"
    assert batch.event_count == 5
    assert all(event.boundary.reducer_required for event in events)
    assert all(event.boundary.phase1_l0_l4_state_mutated is False for event in events)
    assert all(event.boundary.safety_api_called is False for event in events)
    assert all(event.boundary.medical_diagnosis is False for event in events)
    assert "/safety/" not in serialized
    assert "raw_payload" not in serialized
    assert "heartRateData" not in serialized


def test_pace_gate_uses_watch_for_mild_slowness() -> None:
    event = build_pace_gate_event(
        {
            "observed_segment_minutes": 58,
            "reference_p75_segment_minutes": 50,
        }
    )

    assert event.gate_id == "pace_gate"
    assert event.state_candidate == "pace_watch"
    assert event.severity == "watch"
    assert event.ln_transition_candidate == "candidate_watch"
    assert event.eta_delay_minutes == 8


def test_delay_gate_does_not_infer_physiologic_cause() -> None:
    event = build_delay_gate_event(
        {
            "delay_minutes": 75,
            "planned_buffer_minutes": -5,
            "camp_deadline_missed": True,
        }
    )

    assert event.gate_id == "delay_gate"
    assert event.severity == "retreat_review"
    assert any(
        "does not infer the reason for delay" in limitation
        for limitation in event.data_quality.limitations
    )
    assert "medical" not in " ".join(event.dominant_reasons).lower()


def test_darkness_and_weather_gate_keep_fixture_source_only() -> None:
    darkness = build_darkness_gate_event(
        {
            "daylight_buffer_minutes": 85,
            "minutes_to_next_safe_objective": 45,
        }
    )
    weather = build_weather_gate_event(
        {
            "warning_level": "severe",
            "warning_type": "thunderstorm",
            "lightning_risk": True,
            "source_age_minutes": 240,
        }
    )

    assert darkness.severity == "watch"
    assert darkness.route_context.daylight_buffer_minutes == 85
    assert weather.severity == "alert_review"
    assert weather.data_quality.live_network_calls_made is False
    assert weather.data_quality.stale_signal_names == ["weather_source"]


def test_environment_threat_observation_rejects_inconsistent_blocked_route() -> None:
    with pytest.raises(ValueError, match="route_blocked cannot be passable"):
        EnvironmentThreatGateObservation(
            threat_type="washout",
            passability="passable",
            route_blocked=True,
        )


def test_environment_threat_immediate_unknown_bypass_escalates_to_alert_review() -> None:
    event = build_environment_threat_gate_event(
        {
            "threat_type": "rockfall",
            "immediacy": "immediate",
            "passability": "unknown",
            "safe_bypass_known": False,
        }
    )

    assert event.gate_id == "environment_threat_gate"
    assert event.severity == "alert_review"
    assert event.ln_level_candidate == "L4_ALERT_REVIEW"
    assert event.boundary.outbound_alert_sent is False
