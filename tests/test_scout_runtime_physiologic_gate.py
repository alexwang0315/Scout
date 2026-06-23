import json
from datetime import date
from pathlib import Path

import pytest

from scout_energy_baseline import build_energy_reserve_baseline
from scout_energy_field_cue import load_wearable_field_observation
from scout_energy_models import load_wearable_activity_summaries
from scout_runtime_physiologic_gate import (
    PhysiologicBaselineContext,
    PhysiologicGateInput,
    PhysiologicObservationWindowContext,
    PhysiologicGateSignals,
    PhysiologicRouteContext,
    build_runtime_physiologic_gate,
    build_runtime_physiologic_gate_from_observation,
    load_runtime_physiologic_gate_input,
)


ROOT = Path(__file__).resolve().parents[1]
WEARABLE_ROOT = ROOT / "tests" / "fixtures" / "wearables"
WEARABLE_FIXTURES = [
    WEARABLE_ROOT / "apple_health_clean_activity.json",
    WEARABLE_ROOT / "apple_health_missing_hr_interval.json",
    WEARABLE_ROOT / "garmin_body_battery_provider_values.json",
]
HIGH_HR_OBSERVATION = WEARABLE_ROOT / "field_observations" / "high_hr_drift.json"
APPLE_EFFORT_FRAME = WEARABLE_ROOT / "field_observations" / "apple_effort_difficult_runtime_frame.json"


def test_runtime_phys_gate_uses_apple_effort_as_provider_value_only():
    gate_input = load_runtime_physiologic_gate_input(APPLE_EFFORT_FRAME, root=ROOT)

    output = build_runtime_physiologic_gate(gate_input)
    payload = output.model_dump(mode="json")
    user_visible = " ".join(payload["dominant_reasons"]).lower()

    assert payload["artifact_kind"] == "scout_runtime_physiologic_gate"
    assert payload["source_provider"] == "apple_healthkit_local_summary"
    assert payload["source_path"] == (
        "tests/fixtures/wearables/field_observations/apple_effort_difficult_runtime_frame.json"
    )
    assert len(payload["sha256"]) == 64
    assert payload["state"] == "stop_and_rest"
    assert payload["required_action"] == "rest_now"
    assert payload["rest_directive"]["recommended"] is True
    assert payload["eta_delay_minutes"] == 20
    assert payload["route_pressure_effect"]["next_checkpoint_eta_revised_minutes"] == 62
    assert payload["route_pressure_effect"]["daylight_buffer_after_delay_minutes"] == 20
    assert payload["route_pressure_effect"]["route_pressure_review_required"] is True
    assert payload["threshold_policy"]["policy_id"] == "workspace_fixture_thresholds.v0"
    assert payload["threshold_policy"]["heart_rate_only_max_state"] == "watch"
    assert payload["threshold_policy"]["heart_rate_high_drift_ratio"] == 0.14
    assert payload["threshold_policy"]["oxygen_uptake_stop_ratio"] == 0.85
    assert payload["threshold_policy"]["work_output_reset_ratio"] == 1.0
    assert payload["threshold_policy"]["work_output_overdraft_ratio"] == 1.2
    assert payload["threshold_policy"]["default_work_output_reset_ratio_hint"] == 1.25
    assert payload["threshold_policy"]["observation_window_minutes"] == 15
    assert payload["observation_window"]["window_minutes"] == 15
    assert payload["observation_window"]["complete"] is True
    assert payload["observation_window"]["state_before_window_gate"] == "stop_and_rest"
    assert payload["observation_window"]["state_after_window_gate"] == "stop_and_rest"
    assert payload["state_semantics"]["semantics_id"] == "physiologic_state_semantics.v0"
    assert payload["state_semantics"]["high_heart_rate_alone_max_state"] == "watch"
    assert payload["state_semantics"]["vo2max_is_live_oxygen_uptake"] is False
    assert payload["state_semantics"]["oxygen_saturation_compared_to_vo2max"] is False
    assert payload["state_semantics"]["provider_values_are_scout_truth"] is False
    assert payload["state_semantics"]["stop_and_rest_requires_corroboration"] is True
    assert payload["state_semantics"]["retreat_suggested_requires_route_pressure_or_performance_collapse"] is True
    assert payload["data_quality"]["signal_count"] >= 7
    assert payload["data_quality"]["live_network_calls_made"] is False
    assert "provider source value only" in user_visible
    assert "oxygen uptake proxy is 0.84x" in user_visible
    assert "route altitude oxygen availability proxy" in user_visible
    assert "work output is 1.00x the personal reset cue budget" in user_visible
    assert "diagnos" not in user_visible
    assert payload["privacy"]["raw_health_payload_shared"] is False
    assert payload["privacy"]["raw_samples_embedded"] is False
    assert payload["privacy"]["raw_track_shared"] is False
    assert payload["privacy"]["exact_timestamps_shared"] is False
    assert payload["boundary"]["provider_values_are_scout_truth"] is False
    assert payload["boundary"]["medical_diagnosis"] is False
    assert payload["boundary"]["phase1_runtime_safety_truth"] is False
    assert payload["boundary"]["phase1_runtime_mutation_allowed"] is False
    assert payload["boundary"]["safety_api_called"] is False
    assert payload["boundary"]["outbound_alert_sent"] is False
    assert payload["exertion_overdraft"]["stage"] == "reset_cue"
    assert payload["exertion_overdraft"]["danger_flag"] is False
    assert payload["exertion_overdraft"]["phase1_runtime_safety_truth"] is False
    assert payload["exertion_overdraft"]["safety_api_called"] is False
    assert "/safety/" not in json.dumps(payload)


def test_runtime_phys_gate_does_not_compare_spo2_percent_to_vo2max_units():
    gate_input = PhysiologicGateInput(
        source_provider="manual_fixture",
        source_path="inline:hr_spo2_vo2max_not_live_uptake",
        sha256="8" * 64,
        observed_at_offset_s=2400,
        route_context=PhysiologicRouteContext(
            route_id="fixture.route",
            segment_id="fixture.run_loop",
            distance_to_next_checkpoint_m=900,
            estimated_minutes_to_next_checkpoint=20,
            estimated_minutes_to_planned_camp=90,
            daylight_buffer_minutes=80,
        ),
        signals=PhysiologicGateSignals(
            heart_rate_bpm=162,
            heart_rate_zone="z4",
            vo2max_estimate_ml_kg_min=28.5,
            oxygen_saturation_pct=93.0,
            oxygen_saturation_source="apple_healthkit.daily_blood_oxygen",
        ),
        baseline=PhysiologicBaselineContext(
            personal_envelope_available=True,
            reserve_band="normal",
            expected_heart_rate_bpm=140,
            expected_oxygen_uptake_ml_kg_min=28.5,
            reserve_score=58,
        ),
    )

    output = build_runtime_physiologic_gate(gate_input)
    payload = output.model_dump(mode="json")

    assert payload["state"] == "watch"
    assert payload["required_action"] == "slow_down"
    assert payload["state_semantics"]["vo2max_is_live_oxygen_uptake"] is False
    assert payload["state_semantics"]["oxygen_saturation_compared_to_vo2max"] is False
    assert payload["state_semantics"]["high_heart_rate_alone_max_state"] == "watch"
    assert "oxygen saturation percent is not compared to VO2max ml/kg/min" in payload["dominant_reasons"]
    assert "oxygen saturation percent is not compared to VO2max ml/kg/min" in payload["data_quality"][
        "limitations"
    ]
    assert payload["boundary"]["medical_diagnosis"] is False
    assert payload["boundary"]["phase1_runtime_safety_truth"] is False
    assert payload["boundary"]["safety_api_called"] is False
    assert "/safety/" not in json.dumps(payload)


def test_runtime_phys_gate_keeps_high_hr_without_oxygen_context_at_watch():
    activities = load_wearable_activity_summaries(WEARABLE_FIXTURES, root=ROOT)
    baseline = build_energy_reserve_baseline(activities, reference_date=date(2026, 5, 27))
    observation = load_wearable_field_observation(HIGH_HR_OBSERVATION, root=ROOT)

    output = build_runtime_physiologic_gate_from_observation(
        observation,
        baseline,
        route_context={
            "route_id": "fixture.chilai_nanhua.day1",
            "segment_id": "tunyuan_to_yunhai",
            "distance_to_next_checkpoint_m": 1400,
            "estimated_minutes_to_next_checkpoint": 35,
            "estimated_minutes_to_planned_camp": 130,
            "daylight_buffer_minutes": 55,
        },
    )
    payload = output.model_dump(mode="json")

    assert payload["state"] == "watch"
    assert payload["required_action"] == "slow_down"
    assert payload["rest_directive"]["recommended"] is False
    assert payload["eta_delay_minutes"] == 5
    assert payload["route_pressure_effect"]["planned_camp_eta_revised_minutes"] == 135
    assert payload["source_path"].startswith("tests/fixtures/wearables/field_observations/high_hr_drift.json+")
    assert "heart-rate load is 0.174 above expected personal baseline" in payload["dominant_reasons"]
    assert "heart-rate elevation alone is not treated as fatigue, low uptake, or danger" in payload["dominant_reasons"]
    assert "oxygen uptake or altitude oxygen-availability context is missing" in payload["dominant_reasons"]
    assert payload["data_quality"]["baseline_available"] is True
    assert payload["privacy"]["raw_health_payload_shared"] is False
    assert payload["boundary"]["medical_diagnosis"] is False
    assert payload["boundary"]["phase1_runtime_safety_truth"] is False
    assert payload["boundary"]["safety_api_called"] is False
    assert "/safety/" not in json.dumps(payload)


def test_runtime_phys_gate_high_hr_low_movement_efficiency_window_suggests_stop_rest():
    gate_input = PhysiologicGateInput(
        source_provider="manual_fixture",
        source_path="inline:great_wall_low_efficiency_window",
        sha256="c" * 64,
        observed_at_offset_s=900,
        observation_window=PhysiologicObservationWindowContext(elapsed_minutes=15),
        route_context=PhysiologicRouteContext(
            route_id="fixture.great_wall",
            segment_id="fixture.climb_window",
            distance_to_next_checkpoint_m=900,
            estimated_minutes_to_next_checkpoint=35,
            estimated_minutes_to_planned_camp=120,
            daylight_buffer_minutes=90,
        ),
        signals=PhysiologicGateSignals(
            heart_rate_bpm=162,
            heart_rate_zone="z5",
            movement_efficiency_ratio_to_personal_baseline=0.32,
            pace_mps=0.28,
            cadence_spm=25,
        ),
        baseline=PhysiologicBaselineContext(
            personal_envelope_available=True,
            reserve_band="watch",
            expected_heart_rate_bpm=134,
            expected_pace_mps=0.9,
            expected_cadence_spm=85,
            reserve_score=52,
        ),
    )

    output = build_runtime_physiologic_gate(gate_input)
    payload = output.model_dump(mode="json")

    assert payload["state"] == "stop_and_rest"
    assert payload["required_action"] == "rest_now"
    assert payload["rest_directive"]["recommended"] is True
    assert payload["observation_window"]["complete"] is True
    assert "movement efficiency is 0.32x the personal or route context" in payload["dominant_reasons"]
    assert (
        "high heart-rate pressure plus low movement efficiency indicates an exertion-cost window"
        in payload["dominant_reasons"]
    )
    assert "oxygen uptake or altitude oxygen-availability context is missing" in payload["dominant_reasons"]
    assert payload["boundary"]["medical_diagnosis"] is False
    assert payload["boundary"]["phase1_runtime_safety_truth"] is False
    assert payload["boundary"]["safety_api_called"] is False
    assert "/safety/" not in json.dumps(payload)


def test_runtime_phys_gate_low_movement_efficiency_without_hr_pressure_stays_watch():
    gate_input = PhysiologicGateInput(
        source_provider="manual_fixture",
        source_path="inline:slow_sightseeing_window",
        sha256="d" * 64,
        observed_at_offset_s=900,
        observation_window=PhysiologicObservationWindowContext(elapsed_minutes=15),
        route_context=PhysiologicRouteContext(
            route_id="fixture.route",
            segment_id="fixture.slow_window",
            distance_to_next_checkpoint_m=700,
            estimated_minutes_to_next_checkpoint=30,
            estimated_minutes_to_planned_camp=100,
            daylight_buffer_minutes=90,
        ),
        signals=PhysiologicGateSignals(
            heart_rate_bpm=122,
            movement_efficiency_ratio_to_personal_baseline=0.35,
            pace_mps=0.3,
            cadence_spm=24,
        ),
        baseline=PhysiologicBaselineContext(
            personal_envelope_available=True,
            reserve_band="normal",
            expected_heart_rate_bpm=134,
            expected_pace_mps=0.9,
            expected_cadence_spm=85,
            reserve_score=62,
        ),
    )

    output = build_runtime_physiologic_gate(gate_input)
    payload = output.model_dump(mode="json")

    assert payload["state"] == "watch"
    assert payload["required_action"] == "slow_down"
    assert "movement efficiency is 0.35x the personal or route context" in payload["dominant_reasons"]
    assert "high heart-rate pressure plus low movement efficiency" not in " ".join(payload["dominant_reasons"])
    assert payload["rest_directive"]["recommended"] is False
    assert payload["boundary"]["medical_diagnosis"] is False
    assert payload["boundary"]["safety_api_called"] is False


def test_runtime_phys_gate_companion_pace_pressure_handoffs_to_companion_pace_delay_gates():
    gate_input = PhysiologicGateInput(
        source_provider="manual_fixture",
        source_path="inline:companion_pace_pressure_overdraft",
        sha256="e" * 64,
        observed_at_offset_s=3600,
        observation_window=PhysiologicObservationWindowContext(elapsed_minutes=15),
        route_context=PhysiologicRouteContext(
            route_id="fixture.great_wall",
            segment_id="fixture.group_pace_mismatch",
            distance_to_next_checkpoint_m=1200,
            estimated_minutes_to_next_checkpoint=45,
            estimated_minutes_to_planned_camp=150,
            daylight_buffer_minutes=70,
            external_pressure_flags=["companion_pace_pressure"],
        ),
        signals=PhysiologicGateSignals(
            heart_rate_bpm=170,
            heart_rate_zone="z5",
            movement_efficiency_ratio_to_personal_baseline=0.30,
            cumulative_work_output_kj=1250,
            work_output_source="provider_active_energy_kj",
            work_output_ratio_to_reset_budget=1.25,
            rest_ratio_recent_window=0.34,
        ),
        baseline=PhysiologicBaselineContext(
            personal_envelope_available=True,
            reserve_band="watch",
            expected_heart_rate_bpm=134,
            expected_pace_mps=0.9,
            expected_cadence_spm=85,
            typical_completed_work_output_kj=800,
            work_output_reset_ratio_hint=1.25,
            reserve_score=45,
        ),
    )

    output = build_runtime_physiologic_gate(gate_input)
    payload = output.model_dump(mode="json")

    assert payload["state"] == "retreat_suggested"
    assert payload["required_action"] == "retreat_review"
    assert payload["route_pressure_effect"]["route_pressure_review_required"] is True
    assert payload["exertion_overdraft"]["stage"] == "danger_overdraft_candidate"
    assert payload["exertion_overdraft"]["danger_flag"] is True
    assert payload["exertion_overdraft"]["involuntary_forward_pressure"] is True
    assert payload["exertion_overdraft"]["external_pressure_flags"] == ["companion_pace_pressure"]
    assert payload["exertion_overdraft"]["handoff_gates"] == [
        "companion_match_gate",
        "delay_gate",
        "pace_gate",
    ]
    assert "exertion overdraft danger flag indicates likely involuntary forward progress" in payload[
        "dominant_reasons"
    ]
    assert payload["boundary"]["medical_diagnosis"] is False
    assert payload["boundary"]["phase1_runtime_safety_truth"] is False
    assert payload["boundary"]["safety_api_called"] is False
    assert payload["boundary"]["outbound_alert_sent"] is False
    assert "/safety/" not in json.dumps(payload)


def test_runtime_phys_gate_alert_candidate_requires_explicit_user_help_request():
    gate_input = PhysiologicGateInput(
        source_provider="manual_fixture",
        source_path="inline:manual_help_request",
        sha256="0" * 64,
        observed_at_offset_s=3600,
        route_context=PhysiologicRouteContext(
            route_id="fixture.route",
            segment_id="fixture.segment",
            distance_to_next_checkpoint_m=500,
            estimated_minutes_to_next_checkpoint=20,
            estimated_minutes_to_planned_camp=80,
            daylight_buffer_minutes=90,
        ),
        signals=PhysiologicGateSignals(
            heart_rate_bpm=150,
            heart_rate_zone="z3",
            user_reported_discomfort="manual_help_request",
        ),
        baseline=PhysiologicBaselineContext(
            personal_envelope_available=True,
            reserve_band="watch",
            expected_heart_rate_bpm=140,
            reserve_score=50,
        ),
    )

    output = build_runtime_physiologic_gate(gate_input)
    payload = output.model_dump(mode="json")

    assert payload["state"] == "alert_candidate"
    assert payload["required_action"] == "alert_review"
    assert payload["route_pressure_effect"]["route_pressure_review_required"] is True
    assert payload["boundary"]["outbound_alert_sent"] is False
    assert payload["boundary"]["outbound_alert_allowed"] is False
    assert payload["boundary"]["safety_api_called"] is False
    assert payload["boundary"]["phase1_runtime_safety_truth"] is False
    assert "/safety/" not in json.dumps(payload)


def test_runtime_phys_gate_high_load_without_help_request_is_not_alert_candidate():
    gate_input = PhysiologicGateInput(
        source_provider="manual_fixture",
        source_path="inline:high_load_without_help",
        sha256="1" * 64,
        observed_at_offset_s=5400,
        route_context=PhysiologicRouteContext(
            route_id="fixture.route",
            segment_id="fixture.segment",
            distance_to_next_checkpoint_m=2200,
            estimated_minutes_to_next_checkpoint=70,
            estimated_minutes_to_planned_camp=210,
            daylight_buffer_minutes=25,
        ),
        signals=PhysiologicGateSignals(
            heart_rate_bpm=171,
            heart_rate_zone="z5",
            workout_effort_score=9,
            workout_effort_score_source="apple_healthkit.workoutEffortScore",
            training_load_classification="well_above",
        ),
        baseline=PhysiologicBaselineContext(
            personal_envelope_available=True,
            reserve_band="rest_suggested",
            expected_heart_rate_bpm=135,
            reserve_score=38,
        ),
    )

    output = build_runtime_physiologic_gate(gate_input)

    assert output.state == "stop_and_rest"
    assert output.required_action == "rest_now"
    assert output.boundary.outbound_alert_sent is False
    assert output.boundary.safety_api_called is False


def test_runtime_phys_gate_fast_recovery_prefers_active_pace_down_over_stop():
    gate_input = PhysiologicGateInput(
        source_provider="manual_fixture",
        source_path="inline:fast_recovery_after_high_output",
        sha256="4" * 64,
        observed_at_offset_s=4800,
        route_context=PhysiologicRouteContext(
            route_id="fixture.route",
            segment_id="fixture.climb_step",
            distance_to_next_checkpoint_m=1500,
            estimated_minutes_to_next_checkpoint=45,
            estimated_minutes_to_planned_camp=150,
            daylight_buffer_minutes=75,
        ),
        signals=PhysiologicGateSignals(
            heart_rate_bpm=160,
            heart_rate_zone="z5",
            workout_effort_score=8,
            workout_effort_score_source="apple_healthkit.workoutEffortScore",
            heart_rate_recovery_ratio_to_personal_baseline=1.22,
            active_recovery_observed=True,
            breathing_recovery_quality="settled",
            cumulative_work_output_kj=1000,
            work_output_source="derived_running_power_integral",
        ),
        baseline=PhysiologicBaselineContext(
            personal_envelope_available=True,
            reserve_band="watch",
            expected_heart_rate_bpm=140,
            reserve_score=52,
            typical_completed_work_output_kj=800,
            work_output_reset_ratio_hint=1.25,
        ),
    )

    output = build_runtime_physiologic_gate(gate_input)
    payload = output.model_dump(mode="json")

    assert payload["state"] == "watch"
    assert payload["required_action"] == "slow_down"
    assert payload["rest_directive"]["recommended"] is False
    assert payload["eta_delay_minutes"] == 5
    assert "heart-rate recovery is faster than personal context; active pace-down recovery may be enough" in payload[
        "dominant_reasons"
    ]
    assert "breathing recovery is settled during active recovery" in payload["dominant_reasons"]
    assert "work output is 1.00x the personal reset cue budget" in payload["dominant_reasons"]
    assert payload["boundary"]["medical_diagnosis"] is False
    assert payload["boundary"]["safety_api_called"] is False


def test_runtime_phys_gate_slow_recovery_after_high_output_suggests_stop_rest():
    gate_input = PhysiologicGateInput(
        source_provider="manual_fixture",
        source_path="inline:slow_recovery_after_high_output",
        sha256="5" * 64,
        observed_at_offset_s=4800,
        route_context=PhysiologicRouteContext(
            route_id="fixture.route",
            segment_id="fixture.climb_step",
            distance_to_next_checkpoint_m=1500,
            estimated_minutes_to_next_checkpoint=45,
            estimated_minutes_to_planned_camp=150,
            daylight_buffer_minutes=75,
        ),
        signals=PhysiologicGateSignals(
            heart_rate_bpm=160,
            heart_rate_zone="z5",
            workout_effort_score=8,
            workout_effort_score_source="apple_healthkit.workoutEffortScore",
            heart_rate_recovery_ratio_to_personal_baseline=0.72,
            active_recovery_observed=True,
            breathing_recovery_quality="not_settled",
            cumulative_work_output_kj=1000,
            work_output_source="derived_running_power_integral",
        ),
        baseline=PhysiologicBaselineContext(
            personal_envelope_available=True,
            reserve_band="watch",
            expected_heart_rate_bpm=140,
            reserve_score=52,
            typical_completed_work_output_kj=800,
            work_output_reset_ratio_hint=1.25,
        ),
    )

    output = build_runtime_physiologic_gate(gate_input)
    payload = output.model_dump(mode="json")

    assert payload["state"] == "stop_and_rest"
    assert payload["required_action"] == "rest_now"
    assert payload["rest_directive"]["recommended"] is True
    assert "heart-rate recovery is slower than personal context after high output" in payload["dominant_reasons"]
    assert "breathing recovery has not settled; this is an advisory field cue, not diagnosis" in payload[
        "dominant_reasons"
    ]
    assert "work output is 1.00x the personal reset cue budget" in payload["dominant_reasons"]
    assert payload["boundary"]["medical_diagnosis"] is False
    assert payload["boundary"]["outbound_alert_sent"] is False
    assert payload["boundary"]["safety_api_called"] is False


def test_runtime_phys_gate_holds_stop_signal_at_watch_until_15_minute_window_completes():
    gate_input = PhysiologicGateInput(
        source_provider="manual_fixture",
        source_path="inline:transient_stop_before_window_complete",
        sha256="9" * 64,
        observed_at_offset_s=300,
        observation_window=PhysiologicObservationWindowContext(elapsed_minutes=5),
        route_context=PhysiologicRouteContext(
            route_id="fixture.route",
            segment_id="fixture.climb_step",
            distance_to_next_checkpoint_m=1500,
            estimated_minutes_to_next_checkpoint=45,
            estimated_minutes_to_planned_camp=150,
            daylight_buffer_minutes=90,
        ),
        signals=PhysiologicGateSignals(
            heart_rate_bpm=162,
            heart_rate_zone="z5",
            workout_effort_score=8,
            workout_effort_score_source="apple_healthkit.workoutEffortScore",
            oxygen_uptake_ratio_to_personal_baseline=0.84,
            heart_rate_recovery_ratio_to_personal_baseline=0.72,
            breathing_recovery_quality="not_settled",
            cumulative_work_output_kj=1000,
            work_output_source="derived_running_power_integral",
        ),
        baseline=PhysiologicBaselineContext(
            personal_envelope_available=True,
            reserve_band="watch",
            expected_heart_rate_bpm=140,
            reserve_score=52,
            typical_completed_work_output_kj=800,
            work_output_reset_ratio_hint=1.25,
        ),
    )

    output = build_runtime_physiologic_gate(gate_input)
    payload = output.model_dump(mode="json")

    assert payload["state"] == "watch"
    assert payload["required_action"] == "slow_down"
    assert payload["eta_delay_minutes"] == 5
    assert payload["observation_window"]["window_minutes"] == 15
    assert payload["observation_window"]["elapsed_minutes"] == 5
    assert payload["observation_window"]["complete"] is False
    assert payload["observation_window"]["noise_reduction_applied"] is True
    assert payload["observation_window"]["state_before_window_gate"] == "stop_and_rest"
    assert payload["observation_window"]["state_after_window_gate"] == "watch"
    assert "holding at watch to reduce transient noise" in " ".join(payload["dominant_reasons"])
    assert payload["boundary"]["medical_diagnosis"] is False
    assert payload["boundary"]["phase1_runtime_safety_truth"] is False
    assert payload["boundary"]["safety_api_called"] is False


def test_runtime_phys_gate_allows_stop_after_15_minute_window_completes():
    gate_input = PhysiologicGateInput(
        source_provider="manual_fixture",
        source_path="inline:confirmed_stop_after_window_complete",
        sha256="b" * 64,
        observed_at_offset_s=900,
        observation_window=PhysiologicObservationWindowContext(elapsed_minutes=15),
        route_context=PhysiologicRouteContext(
            route_id="fixture.route",
            segment_id="fixture.climb_step",
            distance_to_next_checkpoint_m=1500,
            estimated_minutes_to_next_checkpoint=45,
            estimated_minutes_to_planned_camp=150,
            daylight_buffer_minutes=90,
        ),
        signals=PhysiologicGateSignals(
            heart_rate_bpm=162,
            heart_rate_zone="z5",
            workout_effort_score=8,
            workout_effort_score_source="apple_healthkit.workoutEffortScore",
            oxygen_uptake_ratio_to_personal_baseline=0.84,
            heart_rate_recovery_ratio_to_personal_baseline=0.72,
            breathing_recovery_quality="not_settled",
            cumulative_work_output_kj=1000,
            work_output_source="derived_running_power_integral",
        ),
        baseline=PhysiologicBaselineContext(
            personal_envelope_available=True,
            reserve_band="watch",
            expected_heart_rate_bpm=140,
            reserve_score=52,
            typical_completed_work_output_kj=800,
            work_output_reset_ratio_hint=1.25,
        ),
    )

    output = build_runtime_physiologic_gate(gate_input)
    payload = output.model_dump(mode="json")

    assert payload["state"] == "stop_and_rest"
    assert payload["required_action"] == "rest_now"
    assert payload["observation_window"]["complete"] is True
    assert payload["observation_window"]["noise_reduction_applied"] is False
    assert payload["observation_window"]["state_before_window_gate"] == "stop_and_rest"
    assert payload["observation_window"]["state_after_window_gate"] == "stop_and_rest"
    assert payload["boundary"]["medical_diagnosis"] is False
    assert payload["boundary"]["safety_api_called"] is False


def test_runtime_phys_gate_work_output_reset_budget_is_advisory_not_max_capacity():
    gate_input = PhysiologicGateInput(
        source_provider="manual_fixture",
        source_path="inline:work_output_reset_budget",
        sha256="6" * 64,
        observed_at_offset_s=3600,
        route_context=PhysiologicRouteContext(
            route_id="fixture.route",
            segment_id="fixture.run_loop",
            distance_to_next_checkpoint_m=1000,
            estimated_minutes_to_next_checkpoint=12,
            estimated_minutes_to_planned_camp=60,
            daylight_buffer_minutes=90,
        ),
        signals=PhysiologicGateSignals(
            cumulative_work_output_kj=1000,
            work_output_source="derived_running_power_integral",
            heart_rate_recovery_ratio_to_personal_baseline=1.05,
            active_recovery_observed=True,
        ),
        baseline=PhysiologicBaselineContext(
            personal_envelope_available=True,
            reserve_band="normal",
            typical_completed_work_output_kj=800,
            work_output_reset_ratio_hint=1.25,
            reserve_score=62,
        ),
    )

    output = build_runtime_physiologic_gate(gate_input)
    payload = output.model_dump(mode="json")

    assert payload["state"] == "watch"
    assert payload["required_action"] == "slow_down"
    assert payload["eta_delay_minutes"] == 5
    assert payload["exertion_overdraft"]["stage"] == "reset_cue"
    assert payload["exertion_overdraft"]["danger_flag"] is False
    assert "work output is 1.00x the personal reset cue budget" in payload["dominant_reasons"]
    assert "heart-rate recovery is within the personal expected context" in payload["dominant_reasons"]
    assert "maximum capability" in " ".join(payload["data_quality"]["limitations"])
    assert payload["boundary"]["medical_diagnosis"] is False
    assert payload["boundary"]["phase1_runtime_safety_truth"] is False


def test_runtime_phys_gate_marks_overdraft_danger_when_external_pressure_forces_progress():
    gate_input = PhysiologicGateInput(
        source_provider="manual_fixture",
        source_path="inline:forced_overdraft_progress",
        sha256="7" * 64,
        observed_at_offset_s=9000,
        route_context=PhysiologicRouteContext(
            route_id="fixture.route",
            segment_id="fixture.bad_weather_escape",
            distance_to_next_checkpoint_m=2600,
            estimated_minutes_to_next_checkpoint=85,
            estimated_minutes_to_planned_camp=250,
            daylight_buffer_minutes=18,
            altitude_m=3000,
            external_pressure_flags=[
                "darkness_pressure",
                "weather_deteriorating",
                "seeking_shelter",
            ],
        ),
        signals=PhysiologicGateSignals(
            heart_rate_bpm=176,
            heart_rate_zone="z5",
            workout_effort_score=9,
            workout_effort_score_source="apple_healthkit.workoutEffortScore",
            oxygen_uptake_ratio_to_personal_baseline=0.78,
            heart_rate_recovery_ratio_to_personal_baseline=0.70,
            breathing_recovery_quality="not_settled",
            cumulative_work_output_kj=1350,
            work_output_source="derived_running_power_integral",
            posture_or_gait_quality="poor",
            rest_ratio_recent_window=0.36,
        ),
        baseline=PhysiologicBaselineContext(
            personal_envelope_available=True,
            reserve_band="rest_suggested",
            expected_heart_rate_bpm=136,
            typical_completed_work_output_kj=800,
            work_output_reset_ratio_hint=1.25,
            reserve_score=30,
        ),
    )

    output = build_runtime_physiologic_gate(gate_input)
    payload = output.model_dump(mode="json")

    assert payload["state"] == "retreat_suggested"
    assert payload["required_action"] == "retreat_review"
    assert payload["route_pressure_effect"]["route_pressure_review_required"] is True
    assert payload["exertion_overdraft"]["stage"] == "danger_overdraft_candidate"
    assert payload["exertion_overdraft"]["danger_flag"] is True
    assert payload["exertion_overdraft"]["involuntary_forward_pressure"] is True
    assert payload["exertion_overdraft"]["work_output_ratio_to_reset_budget"] == 1.35
    assert payload["exertion_overdraft"]["external_pressure_flags"] == [
        "darkness_pressure",
        "weather_deteriorating",
        "seeking_shelter",
    ]
    assert payload["exertion_overdraft"]["handoff_gates"] == [
        "darkness_gate",
        "weather_gate",
        "environment_threat_gate",
        "delay_gate",
        "pace_gate",
    ]
    assert "exertion overdraft danger flag indicates likely involuntary forward progress" in payload[
        "dominant_reasons"
    ]
    assert payload["exertion_overdraft"]["phase1_runtime_safety_truth"] is False
    assert payload["exertion_overdraft"]["safety_api_called"] is False
    assert payload["exertion_overdraft"]["outbound_alert_sent"] is False
    assert payload["boundary"]["medical_diagnosis"] is False
    assert payload["boundary"]["phase1_runtime_safety_truth"] is False
    assert payload["boundary"]["safety_api_called"] is False
    assert "/safety/" not in json.dumps(payload)


def test_runtime_phys_gate_retreat_requires_oxygen_and_performance_corroboration():
    gate_input = PhysiologicGateInput(
        source_provider="manual_fixture",
        source_path="inline:oxygen_performance_route_pressure",
        sha256="3" * 64,
        observed_at_offset_s=7200,
        route_context=PhysiologicRouteContext(
            route_id="fixture.route",
            segment_id="fixture.high_altitude_segment",
            distance_to_next_checkpoint_m=1800,
            estimated_minutes_to_next_checkpoint=75,
            estimated_minutes_to_planned_camp=230,
            daylight_buffer_minutes=20,
            altitude_m=3150,
        ),
        signals=PhysiologicGateSignals(
            heart_rate_bpm=168,
            heart_rate_zone="z5",
            workout_effort_score=8,
            workout_effort_score_source="apple_healthkit.workoutEffortScore",
            oxygen_uptake_ratio_to_personal_baseline=0.76,
            posture_or_gait_quality="poor",
            rest_ratio_recent_window=0.42,
        ),
        baseline=PhysiologicBaselineContext(
            personal_envelope_available=True,
            reserve_band="rest_suggested",
            expected_heart_rate_bpm=136,
            reserve_score=34,
        ),
    )

    output = build_runtime_physiologic_gate(gate_input)
    payload = output.model_dump(mode="json")

    assert payload["state"] == "retreat_suggested"
    assert payload["required_action"] == "retreat_review"
    assert payload["route_pressure_effect"]["route_pressure_review_required"] is True
    assert "oxygen uptake proxy is 0.76x the personal or expected context" in payload["dominant_reasons"]
    assert "posture or gait quality is poor" in payload["dominant_reasons"]
    assert payload["boundary"]["medical_diagnosis"] is False
    assert payload["boundary"]["outbound_alert_sent"] is False
    assert payload["boundary"]["safety_api_called"] is False


def test_runtime_phys_gate_route_pressure_bypasses_incomplete_observation_window_for_retreat():
    gate_input = PhysiologicGateInput(
        source_provider="manual_fixture",
        source_path="inline:route_pressure_window_bypass",
        sha256="c" * 64,
        observed_at_offset_s=300,
        observation_window=PhysiologicObservationWindowContext(elapsed_minutes=5),
        route_context=PhysiologicRouteContext(
            route_id="fixture.route",
            segment_id="fixture.high_altitude_bad_weather",
            distance_to_next_checkpoint_m=1800,
            estimated_minutes_to_next_checkpoint=75,
            estimated_minutes_to_planned_camp=230,
            daylight_buffer_minutes=18,
            altitude_m=3150,
            external_pressure_flags=["darkness_pressure", "weather_deteriorating"],
        ),
        signals=PhysiologicGateSignals(
            heart_rate_bpm=176,
            heart_rate_zone="z5",
            workout_effort_score=9,
            workout_effort_score_source="apple_healthkit.workoutEffortScore",
            oxygen_uptake_ratio_to_personal_baseline=0.76,
            heart_rate_recovery_ratio_to_personal_baseline=0.70,
            breathing_recovery_quality="not_settled",
            cumulative_work_output_kj=1350,
            work_output_source="derived_running_power_integral",
            posture_or_gait_quality="poor",
            rest_ratio_recent_window=0.42,
        ),
        baseline=PhysiologicBaselineContext(
            personal_envelope_available=True,
            reserve_band="rest_suggested",
            expected_heart_rate_bpm=136,
            typical_completed_work_output_kj=800,
            work_output_reset_ratio_hint=1.25,
            reserve_score=30,
        ),
    )

    output = build_runtime_physiologic_gate(gate_input)
    payload = output.model_dump(mode="json")

    assert payload["state"] == "retreat_suggested"
    assert payload["required_action"] == "retreat_review"
    assert payload["observation_window"]["complete"] is False
    assert payload["observation_window"]["noise_reduction_applied"] is False
    assert payload["observation_window"]["state_before_window_gate"] == "retreat_suggested"
    assert payload["observation_window"]["state_after_window_gate"] == "retreat_suggested"
    assert payload["observation_window"]["bypass_reason"] == (
        "route pressure bypasses the observation window for retreat review"
    )
    assert payload["route_pressure_effect"]["route_pressure_review_required"] is True
    assert payload["exertion_overdraft"]["danger_flag"] is True
    assert payload["boundary"]["phase1_runtime_safety_truth"] is False
    assert payload["boundary"]["safety_api_called"] is False
    assert "/safety/" not in json.dumps(payload)


def test_runtime_phys_gate_missing_signals_lower_confidence_and_are_not_safe():
    gate_input = PhysiologicGateInput(
        source_provider="manual_fixture",
        source_path="inline:sparse_frame",
        sha256="2" * 64,
        observed_at_offset_s=1200,
        route_context=PhysiologicRouteContext(
            route_id="fixture.route",
            segment_id="fixture.segment",
            distance_to_next_checkpoint_m=900,
            estimated_minutes_to_next_checkpoint=30,
            estimated_minutes_to_planned_camp=100,
            daylight_buffer_minutes=80,
        ),
        signals=PhysiologicGateSignals(),
        baseline=PhysiologicBaselineContext(personal_envelope_available=False),
    )

    output = build_runtime_physiologic_gate(gate_input)
    payload = output.model_dump(mode="json")

    assert payload["state"] == "watch"
    assert payload["confidence"] == "low"
    assert payload["data_quality"]["baseline_available"] is False
    assert "heart_rate_bpm" in payload["data_quality"]["missing_signal_names"]
    assert "missing signals lower confidence and are not interpreted as safe" in payload["dominant_reasons"]
    assert payload["privacy"]["raw_health_payload_shared"] is False
    assert payload["boundary"]["medical_diagnosis"] is False
    assert payload["boundary"]["phase1_runtime_safety_truth"] is False


def test_runtime_phys_gate_loader_rejects_raw_timestamp_payload(tmp_path):
    source = json.loads(APPLE_EFFORT_FRAME.read_text(encoding="utf-8"))
    source["timestamp"] = "2026-06-22T12:03:00+08:00"
    bad_path = tmp_path / "bad_runtime_frame.json"
    bad_path.write_text(json.dumps(source), encoding="utf-8")

    with pytest.raises(ValueError) as exc:
        load_runtime_physiologic_gate_input(bad_path, root=ROOT)

    assert "forbidden raw physiologic gate fields present" in str(exc.value)
    assert "timestamp" in str(exc.value)
