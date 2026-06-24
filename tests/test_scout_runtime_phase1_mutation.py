from __future__ import annotations

import json
from pathlib import Path

import pytest

from safety_models import SafetyEventType, SafetyLevel, SafetyState
from scout_runtime_phase1_mutation import (
    Phase1MutationAuditStore,
    Phase1SafetyMutationService,
    Phase1TransitionRequestBoundary,
    build_phase1_mutation_projection,
    build_phase1_transition_request,
    load_phase1_transition_request,
    phase1_mutation_projection_event,
    safety_event_from_phase1_transition_request,
    write_phase1_transition_request,
)
from scout_runtime_safety_gate_adapters import build_delay_gate_event
from scout_runtime_safety_gate_models import build_runtime_safety_gate_event
from scout_runtime_safety_reducer import (
    build_phase1_adapter_result,
    reduce_runtime_safety_gate_events,
)
from scout_runtime_safety_state_store import RuntimeSafetyStateStore


def _physiologic_reducer():
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
        eta_delay_minutes=22,
        dominant_reasons=[
            "high heart-rate pressure with low movement efficiency",
            "slow recovery across 15 minute window",
        ],
        route_context={
            "route_id": "fixture.route",
            "segment_id": "seg.002",
            "checkpoint_id": "camp.001",
            "map_target_ids": ["seg.002", "camp.001"],
        },
        evidence_refs=["outputs/physio/physiologic_safety_gate_event.json"],
    )
    delay = build_delay_gate_event(
        {
            "event_id": "delay_gate:timeline-watch",
            "source_path": "outputs/runtime/delay.json",
            "delay_minutes": 18,
            "planned_buffer_minutes": 12,
            "route_context": {
                "route_id": "fixture.route",
                "segment_id": "seg.002",
                "checkpoint_id": "camp.001",
            },
        }
    )
    return reduce_runtime_safety_gate_events(
        [physiologic, delay],
        source_path="outputs/runtime/reducer.json",
    )


def _prepared_adapter_and_snapshot(tmp_path: Path):
    reducer = _physiologic_reducer()
    adapter = build_phase1_adapter_result(
        reducer,
        source_path="outputs/runtime/phase1_adapter.json",
        phase1_adapter_enabled=True,
        human_review_approved=True,
    )
    store = RuntimeSafetyStateStore(tmp_path / "runtime_safety_state_store")
    snapshot = store.save_snapshot(reducer, phase1_adapter_result=adapter)
    return reducer, adapter, snapshot


def test_phase1_transition_request_maps_reducer_candidate_to_safety_event(
    tmp_path: Path,
) -> None:
    reducer, adapter, snapshot = _prepared_adapter_and_snapshot(tmp_path)

    request = build_phase1_transition_request(
        reducer,
        adapter,
        state_snapshot=snapshot,
        source_path="outputs/runtime/phase1_transition_request.json",
        event_time_offset_s=900.0,
    )
    event = safety_event_from_phase1_transition_request(request)

    assert request.artifact_kind == "scout_phase1_transition_request"
    assert request.selected_gate_id == "physiologic_gate"
    assert request.requested_ln_level_candidate == "L3_RETREAT"
    assert request.target_safety_level == SafetyLevel.DISTRESS
    assert request.target_event_type == SafetyEventType.PHYSIOLOGIC_PRESSURE
    assert request.boundary.phase1_runtime_mutation_requested is True
    assert request.boundary.phase1_l0_l4_state_mutated is False
    assert request.boundary.safety_api_called is False
    assert request.boundary.outbound_alert_sent is False
    assert event.level == SafetyLevel.DISTRESS
    assert event.event_type == SafetyEventType.PHYSIOLOGIC_PRESSURE
    assert event.timestamp == 900.0
    assert event.details["selected_gate_id"] == "physiologic_gate"


def test_phase1_safety_mutation_service_applies_state_machine_and_audit(
    tmp_path: Path,
) -> None:
    reducer, adapter, snapshot = _prepared_adapter_and_snapshot(tmp_path)
    request = build_phase1_transition_request(reducer, adapter, state_snapshot=snapshot)
    request_path = tmp_path / "phase1_transition_request.json"
    request = write_phase1_transition_request(request, request_path)
    loaded_request = load_phase1_transition_request(request_path)
    service = Phase1SafetyMutationService()

    result = service.apply_transition_request(
        loaded_request,
        source_path="outputs/runtime/phase1_safety_mutation_result.json",
    )
    store = Phase1MutationAuditStore(tmp_path / "phase1_mutation_audit")
    stored = store.save_result(result)
    index = store.load_index()
    serialized = json.dumps(stored.model_dump(mode="json"), sort_keys=True)

    assert stored.status == "applied_transition"
    assert stored.previous_safety_level == SafetyLevel.NORMAL
    assert stored.resulting_safety_level == SafetyLevel.DISTRESS
    assert stored.transition_performed is True
    assert stored.transition is not None
    assert stored.safety_state.level == SafetyLevel.DISTRESS
    assert stored.boundary.phase1_l0_l4_state_mutated is True
    assert stored.boundary.safety_api_called is False
    assert stored.boundary.outbound_alert_sent is False
    assert stored.boundary.medical_diagnosis is False
    assert index.mutation_count == 1
    assert index.latest_mutation_id == stored.mutation_id
    assert index.latest_safety_level == SafetyLevel.DISTRESS
    assert "/safety/" not in serialized
    assert "raw_payload" not in serialized
    assert "heartRateData" not in serialized


def test_phase1_mutation_does_not_downgrade_existing_state(tmp_path: Path) -> None:
    reducer, adapter, snapshot = _prepared_adapter_and_snapshot(tmp_path)
    request = build_phase1_transition_request(reducer, adapter, state_snapshot=snapshot)
    service = Phase1SafetyMutationService(
        initial_state=SafetyState(level=SafetyLevel.EMERGENCY)
    )

    result = service.apply_transition_request(request)

    assert result.status == "accepted_no_transition"
    assert result.previous_safety_level == SafetyLevel.EMERGENCY
    assert result.resulting_safety_level == SafetyLevel.EMERGENCY
    assert result.transition_performed is False
    assert result.transition is None
    assert result.safety_state.active_events[-1].event_type == (
        SafetyEventType.PHYSIOLOGIC_PRESSURE
    )


def test_phase1_mutation_projection_returns_debug_event(tmp_path: Path) -> None:
    reducer, adapter, snapshot = _prepared_adapter_and_snapshot(tmp_path)
    request = build_phase1_transition_request(reducer, adapter, state_snapshot=snapshot)
    result = Phase1SafetyMutationService().apply_transition_request(request)
    store = Phase1MutationAuditStore(tmp_path / "phase1_mutation_audit")
    stored = store.save_result(result)
    event = phase1_mutation_projection_event(stored, sequence=7)
    projection = build_phase1_mutation_projection(
        "fixture.project",
        project_root=tmp_path,
        mutation_audit_index_ref="phase1_mutation_audit/phase1_safety_mutation_audit_index.json",
    )

    assert event["kind"] == "phase1_safety_mutation_result"
    assert event["payload"]["resulting_safety_level"] == "L3_DISTRESS"
    assert event["map_refs"] == ["seg.002", "camp.001"]
    assert projection.status == "ready"
    assert projection.latest_safety_level == SafetyLevel.DISTRESS
    assert projection.timeline_events[0]["kind"] == "phase1_safety_mutation_result"


def test_phase1_transition_request_rejects_blocked_adapter_and_raw_payload(
    tmp_path: Path,
) -> None:
    reducer = _physiologic_reducer()
    blocked_adapter = build_phase1_adapter_result(reducer)

    with pytest.raises(ValueError, match="prepared adapter"):
        build_phase1_transition_request(reducer, blocked_adapter)

    with pytest.raises(ValueError, match="raw private payloads"):
        Phase1TransitionRequestBoundary(raw_health_payload_shared=True)
