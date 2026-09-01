from __future__ import annotations

import json
from pathlib import Path

from scout_runtime_safety_gate_adapters import (
    build_delay_gate_event,
    build_runtime_safety_gate_events_from_fixture,
    build_weather_gate_event,
)
from scout_runtime_safety_gate_models import (
    PRIMARY_SAFETY_GATE_IDS,
    build_runtime_safety_gate_event,
    build_runtime_safety_gate_event_batch,
)
from scout_runtime_safety_reducer import (
    RuntimeSafetyReducerBoundary,
    build_phase1_adapter_result,
    build_production_gate_residency_audit,
    build_production_live_evidence_contract_audit,
    load_phase1_adapter_result,
    load_production_gate_residency_audit,
    load_production_live_evidence_contract_audit,
    load_runtime_safety_reducer_decision,
    reduce_runtime_safety_gate_events,
    write_production_gate_residency_audit,
    write_production_live_evidence_contract_audit,
    write_phase1_adapter_result,
    write_runtime_safety_reducer_decision,
)


def _resident_gate_event(gate_id: str):
    return build_runtime_safety_gate_event(
        gate_id=gate_id,  # type: ignore[arg-type]
        event_id=f"{gate_id}:resident-ready",
        source_provider="scout_runtime_resident_ingest",
        source_path=f"runtime://resident/{gate_id}/event.json",
        source_gate_artifact_kind=f"{gate_id}.production_evidence",
        source_gate_sha256="a" * 64,
        observed_at_offset_s=300,
        state_candidate="clear",
        severity="none",
        ln_transition_candidate="none",
        required_action="continue_monitoring",
        confidence="high",
        evidence_refs=[
            f"runtime://resident/{gate_id}/source",
            f"field://validation/{gate_id}/leader-attested",
        ],
        route_context={
            "route_id": "runtime.route.production",
            "segment_id": "seg.production.001",
            "checkpoint_id": "cp.production.001",
        },
        data_quality={
            "confidence": "high",
            "signal_count": 3,
            "missing_signal_names": [],
            "stale_signal_names": [],
        },
    )


def _production_weather_event():
    return build_runtime_safety_gate_event(
        gate_id="weather_gate",
        event_id="weather_gate:resident-live",
        source_provider="resident_weather_observer",
        source_path="runtime://weather/gate-event.json",
        source_gate_artifact_kind="weather_gate.production_evidence",
        source_gate_sha256="b" * 64,
        observed_at_offset_s=420,
        state_candidate="weather_retreat_review",
        severity="retreat_review",
        ln_transition_candidate="candidate_retreat",
        required_action="review_retreat_or_hold",
        confidence="high",
        route_pressure_review_required=True,
        evidence_refs=[
            "runtime://weather/provider-fusion/source",
            "cwa://opendata/F-C0041-001/fresh-qpf",
            "attestation://freshness/weather/under-180m",
            "field://validation/weather/leader-attested",
        ],
        route_context={
            "route_id": "runtime.route.production",
            "segment_id": "seg.production.001",
            "checkpoint_id": "cp.production.001",
        },
        data_quality={
            "confidence": "high",
            "signal_count": 4,
            "missing_signal_names": [],
            "stale_signal_names": [],
            "live_network_calls_made": True,
        },
        gate_payload={
            "warning_level": "unsafe",
            "warning_type": "heavy_rain",
            "source_age_minutes": 24,
            "provider_dataset_ids": ["F-C0041-001"],
        },
    )


def _production_environment_threat_event():
    return build_runtime_safety_gate_event(
        gate_id="environment_threat_gate",
        event_id="environment_threat_gate:resident-live",
        source_provider="resident_environment_threat_observer",
        source_path="runtime://environment-threat/gate-event.json",
        source_gate_artifact_kind="environment_threat_gate.production_evidence",
        source_gate_sha256="c" * 64,
        observed_at_offset_s=450,
        state_candidate="environment_route_blocked_review",
        severity="retreat_review",
        ln_transition_candidate="candidate_retreat",
        required_action="review_retreat_or_safe_bypass",
        confidence="high",
        route_pressure_review_required=True,
        evidence_refs=[
            "runtime://environment-threat/provider-fusion/source",
            "device://camera/summary/route-blocked",
            "operator://leader/report/route-blocked",
            "attestation://freshness/environment-threat/current",
            "field://validation/environment-threat/leader-attested",
        ],
        route_context={
            "route_id": "runtime.route.production",
            "segment_id": "seg.production.001",
            "checkpoint_id": "cp.production.001",
        },
        data_quality={
            "confidence": "high",
            "signal_count": 4,
            "missing_signal_names": [],
            "stale_signal_names": [],
        },
        gate_payload={
            "threat_type": "washout",
            "passability": "blocked",
            "immediacy": "immediate",
            "route_blocked": True,
            "safe_bypass_known": False,
        },
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


def test_production_gate_residency_audit_accepts_all_six_ready_gates(
    tmp_path: Path,
) -> None:
    events = [_resident_gate_event(gate_id) for gate_id in PRIMARY_SAFETY_GATE_IDS]

    audit = build_production_gate_residency_audit(
        events,
        source_path="runtime://resident/audit/all-six",
    )
    written = write_production_gate_residency_audit(
        audit,
        tmp_path / "production_gate_residency_audit.json",
    )
    loaded = load_production_gate_residency_audit(
        tmp_path / "production_gate_residency_audit.json"
    )

    assert audit.status == "all_resident"
    assert audit.gate_count == 6
    assert audit.resident_ready_count == 6
    assert audit.shadow_only_count == 0
    assert audit.not_resident_count == 0
    assert audit.missing_gate_ids == []
    assert audit.reducer_candidate_allowed is True
    assert all(row.status == "resident_ready" for row in audit.rows)
    assert all(row.field_validation_present for row in audit.rows)
    assert audit.production_runtime_enabled is False
    assert audit.runtime_safety_truth is False
    assert audit.safety_api_called is False
    assert audit.outbound_alert_sent is False
    assert audit.hardware_control_performed is False
    assert written.sha256 == audit.sha256
    assert loaded.sha256 == audit.sha256


def test_production_gate_residency_audit_keeps_fixture_gates_shadow_only() -> None:
    events = build_runtime_safety_gate_events_from_fixture(
        {
            "pace": {
                "observed_segment_minutes": 80,
                "reference_p75_segment_minutes": 60,
                "route_context": {"route_id": "fixture.route", "segment_id": "seg.001"},
            },
            "delay": {
                "delay_minutes": 12,
                "route_context": {"route_id": "fixture.route", "segment_id": "seg.001"},
            },
            "darkness": {
                "daylight_buffer_minutes": 90,
                "minutes_to_next_safe_objective": 60,
                "route_context": {"route_id": "fixture.route", "segment_id": "seg.001"},
            },
            "weather": {
                "warning_level": "watch",
                "source_age_minutes": 30,
                "route_context": {"route_id": "fixture.route", "segment_id": "seg.001"},
            },
            "environment_threat": {
                "threat_type": "washout",
                "passability": "limited",
                "route_context": {"route_id": "fixture.route", "segment_id": "seg.001"},
            },
        }
    )

    audit = build_production_gate_residency_audit(events)
    by_id = {row.gate_id: row for row in audit.rows}

    assert audit.status == "partial_residency"
    assert audit.resident_ready_count == 0
    assert audit.shadow_only_count == 5
    assert audit.not_resident_count == 1
    assert audit.reducer_candidate_allowed is False
    assert by_id["physiologic_gate"].status == "not_resident"
    assert by_id["pace_gate"].status == "shadow_only"
    assert "fixture_or_inline_source" in by_id["pace_gate"].blockers
    assert "production_resident_evidence_missing" in by_id["pace_gate"].blockers
    assert "field_validation_missing" in by_id["weather_gate"].blockers
    assert audit.runtime_safety_truth is False
    assert audit.phase1_l0_l4_state_mutated is False


def test_production_live_evidence_contract_audit_accepts_weather_and_threat(
    tmp_path: Path,
) -> None:
    weather = _production_weather_event()
    threat = _production_environment_threat_event()

    audit = build_production_live_evidence_contract_audit(
        [weather, threat],
        source_path="runtime://resident/live-evidence-contract/audit",
    )
    written = write_production_live_evidence_contract_audit(
        audit,
        tmp_path / "production_live_evidence_contract_audit.json",
    )
    loaded = load_production_live_evidence_contract_audit(
        tmp_path / "production_live_evidence_contract_audit.json"
    )
    by_id = {row.gate_id: row for row in audit.rows}

    assert audit.status == "all_live_contracts_ready"
    assert audit.live_contract_ready_count == 2
    assert audit.contract_gap_count == 0
    assert audit.not_present_count == 0
    assert audit.production_weather_environment_ready is True
    assert by_id["weather_gate"].live_source_present is True
    assert by_id["weather_gate"].freshness_contract_present is True
    assert by_id["weather_gate"].provider_or_field_attestation_present is True
    assert by_id["environment_threat_gate"].current_observation_present is True
    assert by_id["environment_threat_gate"].route_scope_present is True
    assert audit.runtime_safety_truth is False
    assert audit.safety_api_called is False
    assert audit.outbound_alert_sent is False
    assert audit.hardware_control_performed is False
    assert written.sha256 == audit.sha256
    assert loaded.sha256 == audit.sha256


def test_production_live_evidence_contract_audit_blocks_fixture_or_missing_gates() -> None:
    weather = build_weather_gate_event(
        {
            "event_id": "weather_gate:fixture-watch",
            "source_provider": "scout_runtime_fixture",
            "source_path": "inline:weather-gate-observation",
            "warning_level": "watch",
            "source_age_minutes": 30,
            "route_context": {
                "route_id": "fixture.route",
                "segment_id": "seg.001",
            },
        }
    )

    audit = build_production_live_evidence_contract_audit([weather])
    by_id = {row.gate_id: row for row in audit.rows}

    assert audit.status == "partial_live_contracts"
    assert audit.live_contract_ready_count == 0
    assert audit.contract_gap_count == 1
    assert audit.not_present_count == 1
    assert audit.production_weather_environment_ready is False
    assert by_id["weather_gate"].status == "contract_gap"
    assert "fixture_or_inline_source" in by_id["weather_gate"].blockers
    assert "source_gate_hash_missing" in by_id["weather_gate"].blockers
    assert by_id["environment_threat_gate"].status == "not_present"
    assert "gate_event_missing" in by_id["environment_threat_gate"].blockers
    assert audit.runtime_safety_truth is False


def test_reducer_boundary_rejects_runtime_mutation_claims() -> None:
    try:
        RuntimeSafetyReducerBoundary(phase1_l0_l4_state_mutated=True)
    except ValueError as exc:
        assert "Phase 1 state" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected boundary validation failure")
