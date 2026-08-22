from __future__ import annotations

import json
from pathlib import Path

from scout_runtime_safety_gate_adapters import (
    build_delay_gate_event,
    build_weather_gate_event,
)
from scout_runtime_safety_gate_models import (
    build_runtime_safety_gate_event,
    build_runtime_safety_gate_event_batch,
)
from scout_runtime_safety_reducer import (
    RuntimeSafetyReducerBoundary,
    build_phase1_adapter_result,
    load_phase1_adapter_result,
    load_runtime_safety_reducer_decision,
    reduce_runtime_safety_gate_events,
    write_phase1_adapter_result,
    write_runtime_safety_reducer_decision,
)


def test_reducer_escalates_physiologic_rest_with_delay_corroboration() -> None:
    physiologic = build_runtime_safety_gate_event(
        gate_id="physiologic_gate",
        event_id="physiologic_gate:stop-and-rest",
        source_provider="sensorlogger_fixture",
        source_path="outputs/physio/physiologic_safety_gate_event.json",
        state_candidate="stop_and_rest",
        severity="rest",
        ln_transition_candidate="candidate_rest",
        required_action="stop_and_rest",
        confidence="high",
        route_pressure_review_required=True,
        eta_delay_minutes=20,
        dominant_reasons=[
            "high heart-rate pressure with low movement efficiency",
            "slow recovery across 15 minute window",
        ],
        route_context={"route_id": "fixture.route", "segment_id": "seg.002"},
    )
    delay = build_delay_gate_event(
        {
            "event_id": "delay_gate:timeline-watch",
            "source_path": "outputs/runtime/delay.json",
            "delay_minutes": 18,
            "planned_buffer_minutes": 12,
            "route_context": {"route_id": "fixture.route", "segment_id": "seg.002"},
        }
    )
    decision = reduce_runtime_safety_gate_events([physiologic, delay])

    assert decision.artifact_kind == "scout_runtime_safety_reducer_dry_run"
    assert decision.proposed_ln_transition_candidate == "candidate_retreat"
    assert decision.ln_level_candidate == "L3_RETREAT"
    assert decision.recommendation == "retreat_review"
    assert decision.corroborating_gate_ids == ["delay_gate", "physiologic_gate"]
    assert "physiologic pressure corroborated by route pressure" in decision.policy_trace
    assert decision.boundary.runtime_safety_truth is False
    assert decision.boundary.phase1_l0_l4_state_mutated is False
    assert decision.boundary.safety_api_called is False
    assert decision.boundary.medical_diagnosis is False


def test_reducer_suppresses_low_confidence_single_non_hard_retreat() -> None:
    pace = build_runtime_safety_gate_event(
        gate_id="pace_gate",
        event_id="pace_gate:weak-retreat",
        source_provider="fixture",
        source_path="outputs/runtime/pace.json",
        state_candidate="pace_collapse_review",
        severity="retreat_review",
        ln_transition_candidate="candidate_retreat",
        required_action="review_retreat",
        confidence="low",
        route_pressure_review_required=False,
    )
    decision = reduce_runtime_safety_gate_events([pace])

    assert decision.proposed_ln_transition_candidate == "candidate_rest"
    assert decision.ln_level_candidate == "L2_CONCERN"
    assert decision.recommendation == "stop_and_rest"
    assert decision.suppressed_gate_ids == ["pace_gate"]
    assert "single low-confidence non-hard gate cannot own retreat" in decision.suppressed_reasons


def test_reducer_allows_hard_weather_alert_review() -> None:
    weather = build_weather_gate_event(
        {
            "event_id": "weather_gate:severe",
            "source_path": "outputs/runtime/weather.json",
            "warning_level": "severe",
            "warning_type": "thunderstorm",
            "lightning_risk": True,
            "source_age_minutes": 15,
            "confidence": "high",
        }
    )
    decision = reduce_runtime_safety_gate_events([weather])

    assert decision.selected_gate_id == "weather_gate"
    assert decision.highest_severity == "alert_review"
    assert decision.ln_level_candidate == "L4_ALERT_REVIEW"
    assert decision.recommendation == "alert_review"
    assert "alert review supported by hard gate or corroboration" in decision.policy_trace


def test_reducer_hysteresis_holds_deescalation_until_clear_windows() -> None:
    held = reduce_runtime_safety_gate_events(
        [],
        hysteresis_input={
            "previous_ln_level": "L3_RETREAT",
            "previous_reducer_state": "retreat_review",
            "clear_window_count": 1,
        },
    )
    cleared = reduce_runtime_safety_gate_events(
        [],
        hysteresis_input={
            "previous_ln_level": "L3_RETREAT",
            "previous_reducer_state": "retreat_review",
            "clear_window_count": 2,
        },
    )

    assert held.proposed_ln_level_candidate == "L0_NORMAL"
    assert held.ln_level_candidate == "L3_RETREAT"
    assert held.hysteresis.deescalation_held is True
    assert "de-escalation held until two clear windows" in held.suppressed_reasons
    assert cleared.ln_level_candidate == "L0_NORMAL"
    assert cleared.hysteresis.deescalation_held is False


def test_reducer_writes_and_loads_sanitized_artifact(tmp_path: Path) -> None:
    weather = build_weather_gate_event(
        {
            "event_id": "weather_gate:unsafe",
            "source_path": "outputs/runtime/weather.json",
            "warning_level": "unsafe",
            "warning_type": "wind",
            "wind_risk": True,
            "source_age_minutes": 20,
        }
    )
    batch = build_runtime_safety_gate_event_batch([weather])
    decision = reduce_runtime_safety_gate_events(batch, source_path="outputs/runtime/reducer.json")
    output_path = tmp_path / "runtime_safety_reducer_dry_run.json"

    written = write_runtime_safety_reducer_decision(decision, output_path)
    loaded = load_runtime_safety_reducer_decision(output_path)
    serialized = json.dumps(loaded.model_dump(mode="json"), sort_keys=True)

    assert written == loaded
    assert loaded.selected_gate_id == "weather_gate"
    assert loaded.data_quality.live_network_calls_made is False
    assert "/safety/" not in serialized
    assert "raw_payload" not in serialized
    assert "heartRateData" not in serialized


def test_phase1_adapter_is_feature_flagged_and_reducer_owned(tmp_path: Path) -> None:
    weather = build_weather_gate_event(
        {
            "event_id": "weather_gate:unsafe",
            "source_path": "outputs/runtime/weather.json",
            "warning_level": "unsafe",
            "warning_type": "wind",
            "wind_risk": True,
            "source_age_minutes": 20,
        }
    )
    decision = reduce_runtime_safety_gate_events([weather])
    disabled = build_phase1_adapter_result(decision)
    review_blocked = build_phase1_adapter_result(
        decision,
        phase1_adapter_enabled=True,
    )
    prepared = build_phase1_adapter_result(
        decision,
        phase1_adapter_enabled=True,
        human_review_approved=True,
        source_path="outputs/runtime/phase1_adapter.json",
    )
    output_path = tmp_path / "phase1_adapter_result.json"
    write_phase1_adapter_result(prepared, output_path)
    loaded = load_phase1_adapter_result(output_path)
    serialized = json.dumps(prepared.model_dump(mode="json"), sort_keys=True)

    assert disabled.status == "blocked_feature_flag_disabled"
    assert disabled.transition_request_prepared is False
    assert review_blocked.status == "blocked_review_required"
    assert prepared.status == "transition_request_prepared"
    assert prepared.transition_request_prepared is True
    assert prepared.phase1_transition_candidate is not None
    assert prepared.phase1_transition_candidate["requested_ln_level"] == "L3_RETREAT"
    assert prepared.boundary.reducer_owned is True
    assert prepared.boundary.individual_gate_owned is False
    assert prepared.boundary.phase1_l0_l4_state_mutated is False
    assert prepared.boundary.safety_api_called is False
    assert loaded.sha256 == prepared.sha256
    assert "/safety/" not in serialized


def test_reducer_boundary_rejects_runtime_mutation_claims() -> None:
    try:
        RuntimeSafetyReducerBoundary(phase1_l0_l4_state_mutated=True)
    except ValueError as exc:
        assert "Phase 1 state" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected boundary validation failure")
