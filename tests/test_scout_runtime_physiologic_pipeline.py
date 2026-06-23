import json
import zipfile
from pathlib import Path

import pytest

from scout_runtime_physiologic_gate import (
    PhysiologicBaselineContext,
    PhysiologicGateInput,
    PhysiologicGateSignals,
    PhysiologicRouteContext,
    build_runtime_physiologic_gate,
)
from scout_runtime_physiologic_pipeline import (
    apply_route_segment_context_to_windowed_replay,
    build_admin_debug_projection,
    build_companion_pace_pressure_evidence_from_windowed_replay,
    build_feature_set_from_health_auto_export,
    build_gate_inputs_from_live_physio_fixture,
    build_health_auto_export_physio_analysis,
    build_physio_review_capsule,
    build_route_pressure_handoff,
    build_gate_inputs_from_windowed_activity_replay,
    build_route_segment_reference_context,
    build_walking_hiking_baseline_from_windowed_replays,
    build_windowed_activity_replay_from_health_auto_export,
    compare_health_auto_export_physio_analyses,
    compose_route_pressure_decision,
    smooth_physio_gate_states,
)


def test_health_auto_export_pipeline_builds_sanitized_physio_features(tmp_path):
    zip_path = _write_health_auto_export_physio_zip(tmp_path / "HealthAutoExport_fixture.zip")

    feature_set = build_feature_set_from_health_auto_export(zip_path, altitude_m=2150)
    payload = feature_set.model_dump(mode="json")
    serialized = json.dumps(payload, sort_keys=True)

    assert payload["artifact_kind"] == "scout_runtime_physiologic_feature_set"
    assert payload["source_provider"] == "health_auto_export_local_zip"
    assert payload["session_count"] == 3
    assert payload["baseline"]["baseline_vo2max_ml_kg_min"] == 28.8
    assert payload["baseline"]["typical_completed_output_kj"] == 810
    assert payload["baseline"]["reset_cue_kj"] == 1012.5
    assert payload["sessions"][0]["session_index"] == 1
    assert payload["sessions"][0]["high_heart_rate_burden"]["total_minutes_at_or_above"]["165"] >= 4
    assert payload["sessions"][0]["high_heart_rate_burden"]["continuous_minutes_at_or_above"]["170"] > 1
    assert payload["sessions"][0]["oxygen_uptake"]["vo2max_estimate_ml_kg_min"] == 29.1
    assert payload["sessions"][0]["oxygen_uptake"]["altitude_oxygen_availability_ratio"] == 0.775
    assert payload["sessions"][0]["oxygen_uptake"]["provider_values_are_scout_truth"] is False
    assert payload["sessions"][0]["heart_rate_recovery"]["classification"] in {"fast", "expected", "slow"}
    assert payload["sessions"][0]["work_output"]["energy_output_source"] == "provider_active_energy_kj"
    assert payload["sessions"][0]["work_output"]["maximum_capability_claimed"] is False
    assert payload["privacy"]["raw_health_payload_shared"] is False
    assert payload["privacy"]["raw_samples_embedded"] is False
    assert payload["privacy"]["exact_timestamps_shared"] is False
    assert payload["boundary"]["medical_diagnosis"] is False
    assert payload["boundary"]["phase1_runtime_safety_truth"] is False
    assert "2026-05-01 07:" not in serialized
    assert "heartRateData" not in serialized
    assert '"route"' not in serialized
    assert "auth_token" not in serialized
    assert "/safety/" not in serialized


def test_state_smoothing_and_route_pressure_handoff_are_advisory_only():
    watch = build_runtime_physiologic_gate(
        _gate_input(
            "inline:watch",
            heart_rate_bpm=145,
            oxygen_ratio=None,
            recovery_ratio=None,
            work_kj=None,
            daylight=80,
        )
    )
    stop_1 = build_runtime_physiologic_gate(
        _gate_input(
            "inline:stop-1",
            heart_rate_bpm=162,
            oxygen_ratio=0.84,
            recovery_ratio=0.72,
            work_kj=1000,
            daylight=70,
        )
    )
    stop_2 = build_runtime_physiologic_gate(
        _gate_input(
            "inline:stop-2",
            heart_rate_bpm=164,
            oxygen_ratio=0.83,
            recovery_ratio=0.74,
            work_kj=1040,
            daylight=65,
        )
    )
    retreat = build_runtime_physiologic_gate(
        _gate_input(
            "inline:retreat",
            heart_rate_bpm=176,
            oxygen_ratio=0.76,
            recovery_ratio=0.70,
            work_kj=1350,
            daylight=18,
            external_pressure_flags=["darkness_pressure", "weather_deteriorating"],
            rest_ratio_recent_window=0.42,
            posture_or_gait_quality="poor",
        )
    )

    smoothing = smooth_physio_gate_states([watch, stop_1, stop_2, retreat])
    handoff = build_route_pressure_handoff(retreat)
    smoothing_payload = smoothing.model_dump(mode="json")
    handoff_payload = handoff.model_dump(mode="json")

    assert [frame["smoothed_state"] for frame in smoothing_payload["frames"]] == [
        "watch",
        "watch",
        "stop_and_rest",
        "retreat_suggested",
    ]
    assert smoothing_payload["boundary"]["phase1_runtime_safety_truth"] is False
    assert handoff_payload["artifact_kind"] == "scout_physiologic_route_pressure_handoff"
    assert handoff_payload["route_pressure_review_required"] is True
    assert "darkness_gate" in handoff_payload["handoff_gates"]
    assert "weather_gate" in handoff_payload["handoff_gates"]
    assert handoff_payload["advisory_only"] is True
    assert handoff_payload["phase1_runtime_safety_truth"] is False
    assert handoff_payload["safety_api_called"] is False
    assert handoff_payload["outbound_alert_sent"] is False
    assert "/safety/" not in json.dumps(handoff_payload)


def test_admin_debug_projection_shows_sanitized_timeline_without_raw_fields(tmp_path):
    zip_path = _write_health_auto_export_physio_zip(tmp_path / "HealthAutoExport_fixture.zip")
    feature_set = build_feature_set_from_health_auto_export(zip_path, altitude_m=2150)

    projection = build_admin_debug_projection(feature_set)
    payload = projection.model_dump(mode="json")
    serialized = json.dumps(payload, sort_keys=True)

    assert payload["artifact_kind"] == "scout_physiologic_admin_debug_projection"
    assert payload["surface"] == "admin_debug_physiologic_evidence"
    assert payload["cards"][0]["id"] == "session_count"
    assert len(payload["timeline_items"]) == 3
    assert payload["timeline_items"][0]["session_index"] == 1
    assert payload["timeline_items"][0]["hr_ge_165_min"] is not None
    assert payload["state_semantics"]["high_heart_rate_alone_max_state"] == "watch"
    assert payload["state_semantics"]["vo2max_is_live_oxygen_uptake"] is False
    assert payload["privacy"]["raw_health_payload_shared"] is False
    assert payload["boundary"]["phase1_runtime_safety_truth"] is False
    assert "2026-05-01" not in serialized
    assert "heartRateData" not in serialized
    assert '"frames"' not in serialized


def test_windowed_activity_replay_flags_high_hr_low_efficiency_and_rest_cost(tmp_path):
    zip_path = _write_health_auto_export_windowed_walk_zip(tmp_path / "HealthAutoExport_walk_fixture.zip")

    replay = build_windowed_activity_replay_from_health_auto_export(
        zip_path,
        activity_type="walking",
        window_minutes=15,
    )
    payload = replay.model_dump(mode="json")
    serialized = json.dumps(payload, sort_keys=True)

    assert payload["artifact_kind"] == "scout_runtime_physiologic_windowed_activity_replay"
    assert payload["source_provider"] == "health_auto_export_local_zip"
    assert payload["activity_type"] == "walking"
    assert payload["window_minutes"] == 15
    assert payload["window_count"] == 4
    assert payload["session_reference_pace_mps"] > 0.8
    assert payload["session_reference_cadence_spm"] > 90

    pressure_window = payload["windows"][0]
    rest_window = payload["windows"][1]
    assert pressure_window["heart_rate_pressure"] is True
    assert pressure_window["movement_efficiency_ratio_to_session_reference"] <= 0.35
    assert pressure_window["high_hr_low_efficiency_window"] is True
    assert pressure_window["rest_cost"]["following_rest_cost_minutes_next_60m"] >= 10
    assert pressure_window["rest_cost"]["following_rest_window_count"] >= 1
    assert pressure_window["rest_cost"]["stage"] == "recovery_debt_candidate"
    assert rest_window["heart_rate_pressure"] is False
    assert rest_window["rest_cost"]["rest_ratio_recent_window"] >= 0.9
    assert rest_window["rest_cost"]["stage"] == "watch"

    companion_pressure = build_companion_pace_pressure_evidence_from_windowed_replay(
        replay,
        companion_reference_pace_mps=1.2,
        companion_reference_source="manual_group_context:two_stronger_companions",
    )
    pressure_payload = companion_pressure.model_dump(mode="json")
    pressure_serialized = json.dumps(pressure_payload, sort_keys=True)

    assert pressure_payload["artifact_kind"] == "scout_companion_pace_pressure_evidence"
    assert pressure_payload["pressure_detected"] is True
    assert pressure_payload["pressure_window_count"] == 1
    assert pressure_payload["external_pressure_flags"] == ["companion_pace_pressure"]
    assert pressure_payload["pressure_windows"][0]["window_index"] == 1
    assert pressure_payload["pressure_windows"][0]["pressure_detected"] is True
    assert "companion_reference_above_user_sustainable_context" in pressure_payload["pressure_windows"][0][
        "reason_codes"
    ]
    assert pressure_payload["privacy"]["raw_health_payload_shared"] is False
    assert pressure_payload["boundary"]["medical_diagnosis"] is False
    assert pressure_payload["boundary"]["phase1_runtime_safety_truth"] is False
    assert "2026-06-01" not in pressure_serialized
    assert "heartRateData" not in pressure_serialized
    assert '"route"' not in pressure_serialized
    assert "/safety/" not in pressure_serialized

    gate_result = build_gate_inputs_from_windowed_activity_replay(
        replay,
        route_context={
            "route_id": "fixture.great_wall",
            "segment_id": "fixture.windowed_walk",
            "distance_to_next_checkpoint_m": 900,
            "estimated_minutes_to_next_checkpoint": 35,
            "estimated_minutes_to_planned_camp": 120,
            "daylight_buffer_minutes": 90,
        },
        baseline={
            "personal_envelope_available": True,
            "reserve_band": "watch",
            "expected_heart_rate_bpm": 135,
            "expected_pace_mps": payload["session_reference_pace_mps"],
            "expected_cadence_spm": payload["session_reference_cadence_spm"],
            "typical_completed_work_output_kj": 800,
            "work_output_reset_ratio_hint": 1.25,
            "reserve_score": 52,
        },
        companion_pressure_evidence=companion_pressure,
    )
    first_gate_output = build_runtime_physiologic_gate(
        PhysiologicGateInput.model_validate(gate_result["gate_inputs"][0])
    )
    gate_outputs = [
        build_runtime_physiologic_gate(PhysiologicGateInput.model_validate(item))
        for item in gate_result["gate_inputs"]
    ]
    composer = compose_route_pressure_decision(
        gate_outputs,
        companion_pressure_evidence=companion_pressure,
        source_path="inline:windowed_walk_composer",
    )
    composer_payload = composer.model_dump(mode="json")
    composer_serialized = json.dumps(composer_payload, sort_keys=True)

    assert gate_result["artifact_kind"] == "scout_runtime_physiologic_windowed_gate_input_result"
    assert gate_result["gate_input_count"] == 4
    assert gate_result["companion_pressure_window_count"] == 1
    assert gate_result["mutation"]["safety_api_called"] is False
    assert gate_result["gate_inputs"][0]["route_context"]["external_pressure_flags"] == [
        "companion_pace_pressure"
    ]
    assert gate_result["gate_inputs"][1]["route_context"]["external_pressure_flags"] == []
    assert first_gate_output.state == "stop_and_rest"
    assert first_gate_output.required_action == "rest_now"
    assert first_gate_output.exertion_overdraft.handoff_gates == [
        "companion_match_gate",
        "pace_gate",
        "delay_gate",
    ]
    assert composer_payload["artifact_kind"] == "scout_route_pressure_composer_result"
    assert composer_payload["required_action"] == "team_pace_reset"
    assert composer_payload["rest_now"] is True
    assert composer_payload["team_pace_reset_recommended"] is True
    assert composer_payload["route_pressure_review_required"] is True
    assert composer_payload["retreat_review_required"] is False
    assert composer_payload["alert_review_required"] is False
    assert composer_payload["companion_pressure_detected"] is True
    assert composer_payload["eta_delay_minutes"] > composer_payload["physiologic_eta_delay_minutes"]
    assert composer_payload["handoff_gates"] == [
        "companion_match_gate",
        "pace_gate",
        "delay_gate",
    ]
    assert "group-rhythm mismatch" in " ".join(composer_payload["dominant_reasons"])
    assert composer_payload["phase1_runtime_safety_truth"] is False
    assert composer_payload["safety_api_called"] is False
    assert composer_payload["outbound_alert_sent"] is False
    assert composer_payload["boundary"]["medical_diagnosis"] is False
    assert "2026-06-01" not in composer_serialized
    assert "heartRateData" not in composer_serialized
    assert '"route"' not in composer_serialized
    assert "/safety/" not in composer_serialized
    assert "high heart-rate pressure plus low movement efficiency indicates an exertion-cost window" in (
        first_gate_output.dominant_reasons
    )

    assert payload["privacy"]["raw_health_payload_shared"] is False
    assert payload["privacy"]["raw_samples_embedded"] is False
    assert payload["privacy"]["exact_timestamps_shared"] is False
    assert payload["boundary"]["medical_diagnosis"] is False
    assert payload["boundary"]["phase1_runtime_safety_truth"] is False
    assert "2026-06-01" not in serialized
    assert "heartRateData" not in serialized
    assert '"route"' not in serialized
    assert "/safety/" not in serialized


def test_walking_hiking_baseline_uses_windowed_replays_without_raw_payload(tmp_path):
    zip_path = _write_health_auto_export_windowed_walk_zip(tmp_path / "HealthAutoExport_walk_fixture.zip")
    replay = build_windowed_activity_replay_from_health_auto_export(
        zip_path,
        activity_type="walking",
        window_minutes=15,
    )

    baseline = build_walking_hiking_baseline_from_windowed_replays(
        [replay],
        source_path="inline:walking_hiking_baseline_fixture",
    )
    payload = baseline.model_dump(mode="json")
    serialized = json.dumps(payload, sort_keys=True)

    assert payload["artifact_kind"] == "scout_walking_hiking_baseline"
    assert payload["activity_types"] == ["walking"]
    assert payload["replay_count"] == 1
    assert payload["window_count"] == 4
    assert payload["sustainable_pace_mps"] == replay.session_reference_pace_mps
    assert payload["sustainable_cadence_spm"] == replay.session_reference_cadence_spm
    assert payload["typical_completed_output_kj"] == 720
    assert payload["reset_cue_kj"] == 900
    assert payload["rest_or_slowdown_frequency_per_hour"] >= 2
    assert payload["high_hr_low_efficiency_window_rate"] == 0.25
    assert payload["ascent_efficiency_m_per_hour"] is None
    assert payload["descent_conservatism_index"] is None
    assert payload["runtime_baseline_context"]["personal_envelope_available"] is True
    assert payload["runtime_baseline_context"]["expected_pace_mps"] == payload["sustainable_pace_mps"]
    assert payload["runtime_baseline_context"]["expected_cadence_spm"] == payload["sustainable_cadence_spm"]
    assert payload["runtime_baseline_context"]["reset_cue_work_output_kj"] == 900
    assert "ascent/descent efficiency is unavailable" in " ".join(payload["limitations"])
    assert payload["privacy"]["raw_health_payload_shared"] is False
    assert payload["privacy"]["raw_samples_embedded"] is False
    assert payload["privacy"]["exact_timestamps_shared"] is False
    assert payload["boundary"]["medical_diagnosis"] is False
    assert payload["boundary"]["phase1_runtime_safety_truth"] is False
    assert "2026-06-01" not in serialized
    assert "heartRateData" not in serialized
    assert '"route"' not in serialized
    assert "/safety/" not in serialized

    gate_result = build_gate_inputs_from_windowed_activity_replay(
        replay,
        route_context={
            "route_id": "fixture.great_wall",
            "segment_id": "fixture.baseline_context",
            "distance_to_next_checkpoint_m": 900,
            "estimated_minutes_to_next_checkpoint": 35,
            "estimated_minutes_to_planned_camp": 120,
            "daylight_buffer_minutes": 90,
        },
        baseline=baseline.runtime_baseline_context,
    )
    first_gate_output = build_runtime_physiologic_gate(
        PhysiologicGateInput.model_validate(gate_result["gate_inputs"][0])
    )

    assert first_gate_output.state == "stop_and_rest"
    assert first_gate_output.boundary.medical_diagnosis is False
    assert first_gate_output.boundary.safety_api_called is False


def test_route_segment_contextualized_replay_feeds_pace_gate_without_raw_gpx(tmp_path):
    zip_path = _write_health_auto_export_windowed_walk_zip(tmp_path / "HealthAutoExport_walk_fixture.zip")
    replay = build_windowed_activity_replay_from_health_auto_export(
        zip_path,
        activity_type="walking",
        window_minutes=15,
        reference_pace_mps=0.5,
    )

    segment_context = build_route_segment_reference_context(
        segment_id="fixture.tunyuan-to-yunhai",
        source_provider="reference_segment_timing_fixture",
        source_path="inline:reference-segment-timing-fixture",
        distance_m=3600,
        ascent_m=420,
        descent_m=80,
        sample_count=8,
        distance_filter_m=250,
        reference_min_minutes=45,
        reference_p50_minutes=52,
        reference_p75_minutes=60,
        reference_max_minutes=78,
        manual_guide_minutes=70,
        selected_time_source="p75",
    )
    contextualized = apply_route_segment_context_to_windowed_replay(replay, segment_context)
    payload = contextualized.model_dump(mode="json")
    serialized = json.dumps(payload, sort_keys=True)

    assert replay.windows[0].high_hr_low_efficiency_window is False
    assert payload["artifact_kind"] == "scout_route_segment_contextualized_replay"
    assert payload["source_provider"] == "scout_runtime_route_segment_contextualizer"
    assert payload["segment_context"]["source_provider"] == "reference_segment_timing_fixture"
    assert payload["segment_context"]["selected_time_source"] == "p75"
    assert payload["segment_context"]["route_expected_pace_mps"] == 1.0
    assert payload["segment_context"]["sample_count"] == 8
    assert payload["segment_context"]["distance_filter_m"] == 250
    assert payload["route_pressure_window_count"] == 1
    assert payload["windows"][0]["movement_efficiency_ratio_to_route_context"] == 0.278
    assert payload["windows"][0]["route_pressure_window"] is True
    assert payload["privacy"]["raw_health_payload_shared"] is False
    assert payload["privacy"]["raw_track_shared"] is False
    assert payload["privacy"]["exact_timestamps_shared"] is False
    assert payload["boundary"]["medical_diagnosis"] is False
    assert payload["boundary"]["phase1_runtime_safety_truth"] is False
    assert "2026-06-01" not in serialized
    assert "heartRateData" not in serialized
    assert '"route"' not in serialized
    assert "/safety/" not in serialized

    gate_result = build_gate_inputs_from_windowed_activity_replay(
        replay,
        route_context={
            "route_id": "fixture.chilai_nanhua",
            "segment_id": "fixture.tunyuan-to-yunhai",
            "distance_to_next_checkpoint_m": 3600,
            "estimated_minutes_to_next_checkpoint": 60,
            "estimated_minutes_to_planned_camp": 210,
            "daylight_buffer_minutes": 120,
        },
        baseline={
            "personal_envelope_available": True,
            "reserve_band": "watch",
            "expected_heart_rate_bpm": 135,
            "expected_pace_mps": 0.5,
            "typical_completed_work_output_kj": 720,
            "work_output_reset_ratio_hint": 1.25,
            "reserve_score": 52,
        },
        route_segment_contextualization=contextualized,
    )
    first_gate_input = PhysiologicGateInput.model_validate(gate_result["gate_inputs"][0])
    first_gate_output = build_runtime_physiologic_gate(first_gate_input)

    assert gate_result["route_segment_context_window_count"] == 4
    assert gate_result["route_pressure_window_count"] == 1
    assert gate_result["gate_inputs"][0]["signals"]["movement_efficiency_ratio_to_personal_baseline"] == 0.278
    assert gate_result["gate_inputs"][0]["route_context"]["external_pressure_flags"] == ["pace_gate_failed"]
    assert gate_result["gate_inputs"][1]["route_context"]["external_pressure_flags"] == []
    assert first_gate_output.state == "stop_and_rest"
    assert "pace_gate" in first_gate_output.exertion_overdraft.handoff_gates
    assert first_gate_output.boundary.medical_diagnosis is False
    assert first_gate_output.boundary.safety_api_called is False


def test_health_auto_export_physio_analysis_summarizes_zip_without_raw_payload(tmp_path):
    zip_path = _write_health_auto_export_analysis_zip(tmp_path / "HealthAutoExport_analysis_fixture.zip")

    analysis = build_health_auto_export_physio_analysis(
        zip_path,
        activity_type="walking",
        window_minutes=15,
    )
    payload = analysis.model_dump(mode="json")
    serialized = json.dumps(payload, sort_keys=True)
    metric_by_name = {item["metric_name"]: item for item in payload["provider_metric_summaries"]}

    assert payload["artifact_kind"] == "scout_health_auto_export_physio_analysis"
    assert payload["source_provider"] == "health_auto_export_local_zip"
    assert payload["activity_type"] == "walking"
    assert payload["session_count"] == 2
    assert payload["analysis_window_minutes"] == 15
    assert payload["baseline"]["replay_count"] == 2
    assert payload["baseline"]["confidence"] == "low"
    assert payload["overall"]["total_windows"] == 7
    assert payload["overall"]["total_high_hr_low_efficiency_windows"] == 0
    assert payload["overall"]["max_gate_state"] == "watch"
    assert payload["sessions"][0]["max_gate_state"] == "normal"
    assert payload["sessions"][1]["max_gate_state"] == "watch"
    assert payload["sessions"][1]["min_movement_efficiency_ratio"] < 0.7
    assert metric_by_name["vo2_max"]["sample_count"] == 2
    assert metric_by_name["vo2_max"]["median_value"] == 36.9
    assert metric_by_name["vo2_max"]["source_value_only"] is True
    assert metric_by_name["vo2_max"]["scout_truth"] is False
    assert "VO2max is background cardio-fitness context" in " ".join(payload["limitations"])
    assert payload["privacy"]["raw_health_payload_shared"] is False
    assert payload["privacy"]["raw_track_shared"] is False
    assert payload["privacy"]["exact_timestamps_shared"] is False
    assert payload["boundary"]["medical_diagnosis"] is False
    assert payload["boundary"]["phase1_runtime_safety_truth"] is False
    assert "2026-06-02" not in serialized
    assert "heartRateData" not in serialized
    assert '"route"' not in serialized
    assert "private-route.gpx" not in serialized
    assert "/safety/" not in serialized


def test_health_auto_export_physio_analysis_delta_marks_review_candidate_without_safety_truth(tmp_path):
    previous_zip = _write_health_auto_export_windowed_walk_zip(tmp_path / "HealthAutoExport_previous.zip")
    current_zip = _write_health_auto_export_analysis_zip(tmp_path / "HealthAutoExport_current.zip")
    previous = build_health_auto_export_physio_analysis(
        previous_zip,
        activity_type="walking",
        window_minutes=15,
    )
    current = build_health_auto_export_physio_analysis(
        current_zip,
        activity_type="walking",
        window_minutes=15,
    )

    delta = compare_health_auto_export_physio_analyses(
        previous,
        current,
        source_path="inline:physio-analysis-delta-fixture",
    )
    payload = delta.model_dump(mode="json")
    serialized = json.dumps(payload, sort_keys=True)
    metric_by_name = {item["metric_name"]: item for item in payload["provider_metric_deltas"]}

    assert payload["artifact_kind"] == "scout_health_auto_export_physio_analysis_delta"
    assert payload["previous_analysis_sha256"] == previous.sha256
    assert payload["current_analysis_sha256"] == current.sha256
    assert payload["activity_type"] == "walking"
    assert payload["previous_max_gate_state"] in {"stop_and_rest", "retreat_suggested"}
    assert payload["current_max_gate_state"] == "watch"
    assert payload["state_direction"] == "improved"
    assert payload["review_candidate_change"] is True
    assert payload["total_high_hr_low_efficiency_window_delta"] < 0
    assert "high-HR/low-efficiency windows decreased" in payload["candidate_change_reasons"]
    assert metric_by_name["vo2_max"]["source_value_only"] is True
    assert metric_by_name["vo2_max"]["scout_truth"] is False
    assert "candidate change means review-worthy physiologic trend difference" in " ".join(payload["limitations"])
    assert payload["privacy"]["raw_health_payload_shared"] is False
    assert payload["privacy"]["raw_track_shared"] is False
    assert payload["privacy"]["exact_timestamps_shared"] is False
    assert payload["boundary"]["medical_diagnosis"] is False
    assert payload["boundary"]["phase1_runtime_safety_truth"] is False
    assert "2026-06-01" not in serialized
    assert "2026-06-02" not in serialized
    assert "heartRateData" not in serialized
    assert '"route"' not in serialized
    assert "private-route.gpx" not in serialized
    assert "/safety/" not in serialized


def test_physio_review_capsule_packages_analysis_delta_without_route_approval(tmp_path):
    previous_zip = _write_health_auto_export_windowed_walk_zip(tmp_path / "HealthAutoExport_previous.zip")
    current_zip = _write_health_auto_export_analysis_zip(tmp_path / "HealthAutoExport_current.zip")
    previous = build_health_auto_export_physio_analysis(
        previous_zip,
        activity_type="walking",
        window_minutes=15,
    )
    current = build_health_auto_export_physio_analysis(
        current_zip,
        activity_type="walking",
        window_minutes=15,
    )
    delta = compare_health_auto_export_physio_analyses(
        previous,
        current,
        source_path="inline:physio-analysis-delta-fixture",
    )

    capsule = build_physio_review_capsule(
        current,
        delta=delta,
        source_path="inline:physio-review-capsule-fixture",
    )
    payload = capsule.model_dump(mode="json")
    serialized = json.dumps(payload, sort_keys=True)

    assert payload["artifact_kind"] == "scout_physio_review_capsule"
    assert payload["current_analysis_sha256"] == current.sha256
    assert payload["delta_sha256"] == delta.sha256
    assert payload["activity_type"] == "walking"
    assert payload["current_max_gate_state"] == "watch"
    assert payload["trend_direction"] == "improved"
    assert payload["review_candidate_change"] is True
    assert payload["review_priority"] == "monitor"
    assert payload["advisory_only"] is True
    assert payload["capability_truth"] is False
    assert payload["route_approval"] is False
    assert payload["safety_api_called"] is False
    assert payload["phase1_runtime_safety_truth"] is False
    assert payload["outbound_alert_sent"] is False
    assert "candidate change is a review trigger" in " ".join(payload["limitations"])
    assert "review trend before updating companion or capability matching" in payload["suggested_review_actions"]
    assert payload["privacy"]["raw_health_payload_shared"] is False
    assert payload["privacy"]["raw_track_shared"] is False
    assert payload["privacy"]["exact_timestamps_shared"] is False
    assert payload["boundary"]["medical_diagnosis"] is False
    assert payload["boundary"]["phase1_runtime_safety_truth"] is False
    assert "2026-06-01" not in serialized
    assert "2026-06-02" not in serialized
    assert "heartRateData" not in serialized
    assert '"route"' not in serialized
    assert "private-route.gpx" not in serialized
    assert "/safety/" not in serialized


def test_live_physio_fixture_adapter_builds_gate_inputs_without_provider_calls_or_tokens(tmp_path):
    fixture_path = tmp_path / "physio-live-fixture.json"
    fixture_path.write_text(
        json.dumps(
            {
                "provider": "apple_healthkit",
                "auth_token_ref": "private-live-token",
                "network_request_performed": False,
                "real_provider_api_called": False,
                "runtime_ingest_performed": False,
                "frames": [
                    {
                        "offset_s": 0,
                        "heart_rate_bpm": 142,
                        "heart_rate_zone": "z3",
                    },
                    {
                        "offset_s": 900,
                        "heart_rate_bpm": 166,
                        "heart_rate_zone": "z5",
                        "workout_effort_score": 8,
                        "workout_effort_score_source": "apple_healthkit.workoutEffortScore",
                        "oxygen_uptake_ratio_to_personal_baseline": 0.84,
                        "heart_rate_recovery_ratio_to_personal_baseline": 0.74,
                        "breathing_recovery_quality": "not_settled",
                        "cumulative_work_output_kj": 1000,
                        "work_output_source": "provider_active_energy_kj",
                        "movement_efficiency_ratio_to_personal_baseline": 0.44,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    result = build_gate_inputs_from_live_physio_fixture(
        fixture_path,
        provider="apple_healthkit_live_fixture",
        route_context={
            "route_id": "fixture.route",
            "segment_id": "fixture.segment",
            "distance_to_next_checkpoint_m": 1200,
            "estimated_minutes_to_next_checkpoint": 40,
            "estimated_minutes_to_planned_camp": 120,
            "daylight_buffer_minutes": 75,
            "altitude_m": 2150,
        },
        baseline={
            "personal_envelope_available": True,
            "reserve_band": "watch",
            "expected_heart_rate_bpm": 140,
            "typical_completed_work_output_kj": 800,
            "work_output_reset_ratio_hint": 1.25,
            "reserve_score": 52,
        },
    )
    serialized = json.dumps(result, sort_keys=True)

    assert result["artifact_kind"] == "scout_runtime_physiologic_live_adapter_result"
    assert result["gate_input_count"] == 2
    assert result["mutation"]["network_request_performed"] is False
    assert result["mutation"]["real_provider_api_called"] is False
    assert result["mutation"]["runtime_ingest_performed"] is False
    assert result["mutation"]["safety_api_called"] is False
    assert result["boundary"]["provider_values_are_scout_truth"] is False
    assert "private-live-token" not in serialized
    assert "auth_token_ref" not in serialized
    assert "/safety/" not in serialized
    assert result["gate_inputs"][1]["signals"]["movement_efficiency_ratio_to_personal_baseline"] == 0.44

    gate_output = build_runtime_physiologic_gate(
        PhysiologicGateInput.model_validate(result["gate_inputs"][1])
    )
    assert gate_output.state == "stop_and_rest"
    assert "movement efficiency is 0.44x the personal or route context" in gate_output.dominant_reasons
    assert gate_output.boundary.medical_diagnosis is False


def test_live_physio_fixture_adapter_rejects_precise_timestamps_and_network_flags(tmp_path):
    fixture_path = tmp_path / "bad-live-fixture.json"
    fixture_path.write_text(
        json.dumps(
            {
                "network_request_performed": True,
                "frames": [
                    {
                        "timestamp": "2026-05-01T07:00:00+08:00",
                        "heart_rate_bpm": 150,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError) as exc:
        build_gate_inputs_from_live_physio_fixture(
            fixture_path,
            provider="apple_healthkit_live_fixture",
            route_context={
                "route_id": "fixture.route",
                "segment_id": "fixture.segment",
                "distance_to_next_checkpoint_m": 1000,
                "estimated_minutes_to_next_checkpoint": 30,
                "estimated_minutes_to_planned_camp": 90,
                "daylight_buffer_minutes": 60,
            },
            baseline={"personal_envelope_available": False},
        )

    assert "must not perform network" in str(exc.value)


def _gate_input(
    source_path: str,
    *,
    heart_rate_bpm: int,
    oxygen_ratio: float | None,
    recovery_ratio: float | None,
    work_kj: float | None,
    daylight: int,
    external_pressure_flags: list[str] | None = None,
    rest_ratio_recent_window: float | None = None,
    posture_or_gait_quality: str | None = None,
) -> PhysiologicGateInput:
    return PhysiologicGateInput(
        source_provider="manual_fixture",
        source_path=source_path,
        sha256="a" * 64,
        observed_at_offset_s=3600,
        route_context=PhysiologicRouteContext(
            route_id="fixture.route",
            segment_id="fixture.segment",
            distance_to_next_checkpoint_m=1500,
            estimated_minutes_to_next_checkpoint=45,
            estimated_minutes_to_planned_camp=150,
            daylight_buffer_minutes=daylight,
            altitude_m=2150,
            external_pressure_flags=external_pressure_flags or [],
        ),
        signals=PhysiologicGateSignals(
            heart_rate_bpm=heart_rate_bpm,
            heart_rate_zone="z5" if heart_rate_bpm >= 160 else "z4",
            workout_effort_score=8 if heart_rate_bpm >= 160 else None,
            workout_effort_score_source="apple_healthkit.workoutEffortScore",
            oxygen_uptake_ratio_to_personal_baseline=oxygen_ratio,
            heart_rate_recovery_ratio_to_personal_baseline=recovery_ratio,
            breathing_recovery_quality="not_settled" if recovery_ratio and recovery_ratio < 0.8 else None,
            cumulative_work_output_kj=work_kj,
            work_output_source="provider_active_energy_kj" if work_kj else None,
            rest_ratio_recent_window=rest_ratio_recent_window,
            posture_or_gait_quality=posture_or_gait_quality,
        ),
        baseline=PhysiologicBaselineContext(
            personal_envelope_available=True,
            reserve_band="watch",
            expected_heart_rate_bpm=140,
            typical_completed_work_output_kj=800,
            work_output_reset_ratio_hint=1.25,
            reserve_score=52,
        ),
    )


def _write_health_auto_export_physio_zip(path: Path) -> Path:
    payload = {
        "data": {
            "workouts": [
                _run_workout(
                    "run-001",
                    start="2026-05-01 07:00:00 +0800",
                    avg_hr=154,
                    max_hr=174,
                    hrs=[142, 151, 160, 166, 171, 172, 168, 164, 158, 150],
                    recovery=[166, 155, 146, 139],
                    active_kj=805,
                    speed=7.2,
                    power=178,
                ),
                _run_workout(
                    "run-002",
                    start="2026-05-02 07:00:00 +0800",
                    avg_hr=159,
                    max_hr=178,
                    hrs=[148, 160, 166, 171, 174, 176, 170, 166, 162, 153],
                    recovery=[170, 160, 153, 146],
                    active_kj=810,
                    speed=7.5,
                    power=184,
                ),
                _run_workout(
                    "run-003",
                    start="2026-05-03 07:00:00 +0800",
                    avg_hr=151,
                    max_hr=169,
                    hrs=[136, 145, 152, 160, 166, 168, 163, 158, 150, 142],
                    recovery=[158, 145, 136, 128],
                    active_kj=840,
                    speed=7.0,
                    power=175,
                ),
            ],
            "metrics": [
                _metric("vo2_max", [29.1, 28.8, 28.4]),
                _metric("physical_effort", [4.2, 4.1, 3.8]),
                _metric("running_power", [178, 184, 175]),
                _metric("running_speed", [7.2, 7.5, 7.0]),
                _metric("blood_oxygen_saturation", [96.5, 95.8, 97.0]),
            ],
        }
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "HealthAutoExport-2026-05-01-2026-05-03.json",
            json.dumps(payload, ensure_ascii=False),
        )
        archive.writestr("private-route.gpx", "<gpx><trk><trkseg /></trk></gpx>")
    return path


def _write_health_auto_export_windowed_walk_zip(path: Path) -> Path:
    day = "2026-06-01"
    distances_km = [0.25, 0.04, 0.80, 0.85]
    step_counts = [375, 30, 1395, 1440]
    active_energy_kj = [340, 50, 170, 160]
    heart_rates = (
        [150, 158, 162, 166, 170, 172, 168, 165, 163, 161, 160, 158, 166, 170, 172]
        + [112, 110, 108, 109, 111, 115, 118, 120, 119, 116, 114, 112, 111, 110, 109]
        + [124, 126, 128, 130, 132, 134, 136, 138, 137, 136, 135, 134, 133, 132, 131]
        + [126, 128, 130, 132, 134, 136, 138, 140, 139, 137, 135, 133, 131, 129, 127]
    )

    distance_rows = []
    step_rows = []
    energy_rows = []
    hr_rows = []
    for minute in range(60):
        window = minute // 15
        row_date = f"{day} 08:{minute:02d}:00 +0800"
        distance_rows.append(
            {
                "date": row_date,
                "qty": distances_km[window] / 15.0,
                "units": "km",
                "source": "fixture.watch",
            }
        )
        step_rows.append(
            {
                "date": row_date,
                "qty": step_counts[window] / 15.0,
                "units": "count",
                "source": "fixture.watch",
            }
        )
        energy_rows.append(
            {
                "date": row_date,
                "qty": active_energy_kj[window] / 15.0,
                "units": "kJ",
                "source": "fixture.watch",
            }
        )
        hr_rows.append(
            {
                "date": row_date,
                "Avg": heart_rates[minute],
                "Max": heart_rates[minute],
                "Min": heart_rates[minute],
                "units": "bpm",
                "source": "fixture.watch",
            }
        )

    payload = {
        "data": {
            "workouts": [
                {
                    "id": "walk-windowed-001",
                    "name": "步行",
                    "start": f"{day} 08:00:00 +0800",
                    "end": f"{day} 09:00:00 +0800",
                    "duration": 3600,
                    "distance": {"qty": sum(distances_km), "units": "km"},
                    "avgHeartRate": {"qty": 135, "units": "bpm"},
                    "maxHeartRate": {"qty": 172, "units": "bpm"},
                    "activeEnergyBurned": {"qty": sum(active_energy_kj), "units": "kJ"},
                    "walkingAndRunningDistance": distance_rows,
                    "stepCount": step_rows,
                    "activeEnergy": energy_rows,
                    "heartRateData": hr_rows,
                    "route": [
                        {
                            "latitude": 40.0,
                            "longitude": 116.0,
                            "altitude": 600,
                            "timestamp": f"{day}T08:00:00+08:00",
                        }
                    ],
                }
            ],
            "metrics": [],
        }
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("HealthAutoExport-2026-06-01.json", json.dumps(payload, ensure_ascii=False))
        archive.writestr("private-route.gpx", "<gpx><trk><trkseg /></trk></gpx>")
    return path


def _write_health_auto_export_analysis_zip(path: Path) -> Path:
    payload = {
        "data": {
            "workouts": [
                _analysis_walk_workout(
                    "walk-analysis-001",
                    day="2026-06-02",
                    hour=8,
                    distances_km=[0.72, 0.89, 0.80],
                    step_counts=[1072, 1250, 1260],
                    active_energy_kj=[100, 110, 100],
                    heart_rates=[100] * 15 + [101] * 15 + [94] * 15,
                ),
                _analysis_walk_workout(
                    "walk-analysis-002",
                    day="2026-06-03",
                    hour=10,
                    distances_km=[0.54, 0.82, 0.68, 0.48],
                    step_counts=[642, 1265, 864, 520],
                    active_energy_kj=[80, 90, 80, 60],
                    heart_rates=[121] * 15 + [111] * 15 + [121] * 15 + [113] * 15,
                ),
            ],
            "metrics": [
                _metric("vo2_max", [36.9, 36.9]),
                _metric("heart_rate_variability", [42.4, 19.5, 34.1]),
                _metric("resting_heart_rate", [72]),
                _metric("walking_heart_rate_average", [106]),
            ],
        }
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("HealthAutoExport-analysis.json", json.dumps(payload, ensure_ascii=False))
        archive.writestr("private-route.gpx", "<gpx><trk><trkseg /></trk></gpx>")
    return path


def _analysis_walk_workout(
    workout_id: str,
    *,
    day: str,
    hour: int,
    distances_km: list[float],
    step_counts: list[int],
    active_energy_kj: list[int],
    heart_rates: list[int],
) -> dict:
    duration_min = len(distances_km) * 15
    end_hour = hour + duration_min // 60
    end_min = duration_min % 60
    distance_rows = []
    step_rows = []
    energy_rows = []
    hr_rows = []
    for minute in range(duration_min):
        window = minute // 15
        row_date = f"{day} {hour + minute // 60:02d}:{minute % 60:02d}:00 +0800"
        distance_rows.append(
            {
                "date": row_date,
                "qty": distances_km[window] / 15.0,
                "units": "km",
                "source": "fixture.watch",
            }
        )
        step_rows.append(
            {
                "date": row_date,
                "qty": step_counts[window] / 15.0,
                "units": "count",
                "source": "fixture.watch",
            }
        )
        energy_rows.append(
            {
                "date": row_date,
                "qty": active_energy_kj[window] / 15.0,
                "units": "kJ",
                "source": "fixture.watch",
            }
        )
        hr_rows.append(
            {
                "date": row_date,
                "Avg": heart_rates[minute],
                "Max": heart_rates[minute],
                "Min": heart_rates[minute],
                "units": "bpm",
                "source": "fixture.watch",
            }
        )
    return {
        "id": workout_id,
        "name": "步行",
        "start": f"{day} {hour:02d}:00:00 +0800",
        "end": f"{day} {end_hour:02d}:{end_min:02d}:00 +0800",
        "duration": duration_min * 60,
        "distance": {"qty": sum(distances_km), "units": "km"},
        "avgHeartRate": {"qty": round(sum(heart_rates) / len(heart_rates), 1), "units": "bpm"},
        "maxHeartRate": {"qty": max(heart_rates), "units": "bpm"},
        "activeEnergyBurned": {"qty": sum(active_energy_kj), "units": "kJ"},
        "walkingAndRunningDistance": distance_rows,
        "stepCount": step_rows,
        "activeEnergy": energy_rows,
        "heartRateData": hr_rows,
        "route": [
            {
                "latitude": 40.0,
                "longitude": 116.0,
                "altitude": 600,
                "timestamp": f"{day}T{hour:02d}:00:00+08:00",
            }
        ],
    }


def _run_workout(
    workout_id: str,
    *,
    start: str,
    avg_hr: int,
    max_hr: int,
    hrs: list[int],
    recovery: list[int],
    active_kj: int,
    speed: float,
    power: int,
) -> dict:
    day = start[:10]
    return {
        "id": workout_id,
        "name": "戶外 跑步",
        "start": start,
        "end": f"{day} 07:20:00 +0800",
        "duration": 1200,
        "distance": {"qty": 2.45, "units": "km"},
        "elevationUp": {"qty": 8, "units": "m"},
        "avgHeartRate": {"qty": avg_hr, "units": "bpm"},
        "maxHeartRate": {"qty": max_hr, "units": "bpm"},
        "avgSpeed": {"qty": speed, "units": "km/hr"},
        "activeEnergyBurned": {"qty": active_kj, "units": "kJ"},
        "heartRateData": [
            {"date": f"{day} 07:{minute:02d}:00 +0800", "Avg": bpm, "units": "bpm"}
            for minute, bpm in enumerate(hrs)
        ],
        "heartRateRecovery": [
            {"date": f"{day} 07:20:{index * 10:02d} +0800", "Avg": bpm, "units": "bpm"}
            for index, bpm in enumerate(recovery)
        ],
        "route": [
            {"lat": 25.0, "lon": 121.0, "date": f"{day} 07:00:00 +0800"},
            {"lat": 25.01, "lon": 121.01, "date": f"{day} 07:20:00 +0800"},
        ],
        "runningPower": {"qty": power, "units": "W"},
    }


def _metric(name: str, values: list[float]) -> dict:
    return {
        "name": name,
        "data": [
            {"date": f"2026-05-0{index} 00:00:00 +0800", "qty": value}
            for index, value in enumerate(values, start=1)
        ],
    }
