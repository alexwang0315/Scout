from __future__ import annotations

import json
from pathlib import Path

import pytest

from scout_runtime_physiologic_integration import PhysiologicSafetyGateEvent
from scout_runtime_safety_gate_models import (
    PRIMARY_SAFETY_GATE_IDS,
    SafetyGateBoundary,
    build_runtime_safety_gate_event,
    build_runtime_safety_gate_event_batch,
    runtime_safety_gate_event_from_physiologic,
    write_runtime_safety_gate_event,
)


def test_build_runtime_safety_gate_event_supports_primary_gate_ids() -> None:
    events = [
        build_runtime_safety_gate_event(
            gate_id=gate_id,
            event_id=f"{gate_id}:fixture",
            source_provider="fixture",
            source_path=f"outputs/{gate_id}.json",
            state_candidate="watch",
            severity="watch",
            ln_transition_candidate="candidate_watch",
            required_action="review",
            confidence="medium",
            route_context={
                "route_id": "fixture.route",
                "segment_id": "seg.001",
                "checkpoint_id": "cp.001",
            },
            evidence_refs=[f"fixture:{gate_id}"],
        )
        for gate_id in PRIMARY_SAFETY_GATE_IDS
    ]
    batch = build_runtime_safety_gate_event_batch(events)

    assert [event.gate_id for event in events] == list(PRIMARY_SAFETY_GATE_IDS)
    assert all(event.artifact_kind == "scout_runtime_safety_gate_event" for event in events)
    assert all(event.ln_level_candidate == "L1_CAUTION" for event in events)
    assert all(event.boundary.reducer_required is True for event in events)
    assert all(event.boundary.phase1_l0_l4_state_mutated is False for event in events)
    assert all("seg.001" in event.route_context.map_target_ids for event in events)
    assert batch.artifact_kind == "scout_runtime_safety_gate_event_batch"
    assert batch.event_count == len(PRIMARY_SAFETY_GATE_IDS)
    assert batch.boundary.runtime_safety_truth is False


def test_physio_safety_gate_event_converts_to_generic_runtime_event(tmp_path: Path) -> None:
    physiologic_event = PhysiologicSafetyGateEvent(
        event_id="physiologic_gate_event:fixture",
        source_provider="sensorlogger_mqtt_local_jsonl",
        source_path="outputs/physio/physiologic_safety_gate_event.json",
        sha256="a" * 64,
        source_gate_sha256="b" * 64,
        observed_at_offset_s=900,
        state_candidate="stop_and_rest",
        required_action="stop_and_rest",
        severity="rest",
        ln_transition_candidate="candidate_rest",
        eta_delay_minutes=20,
        route_pressure_review_required=True,
        dominant_reasons=["high heart-rate pressure with low movement efficiency"],
        safety_reducer_required=True,
        data_quality={
            "heart_rate_confidence": "high",
            "gps_confidence": "medium",
            "provider_value_confidence": "low",
        },
    )

    event = runtime_safety_gate_event_from_physiologic(
        physiologic_event,
        route_context={
            "route_id": "fixture.route",
            "segment_id": "seg.physio",
            "estimated_minutes_to_planned_camp": 140,
            "daylight_buffer_minutes": 50,
        },
        evidence_refs=["outputs/physio/physiologic_gate_evidence.jsonl"],
    )
    output_path = tmp_path / "runtime_safety_gate_event.json"
    written = write_runtime_safety_gate_event(event, output_path)
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    serialized = json.dumps(payload, sort_keys=True)

    assert event.gate_id == "physiologic_gate"
    assert event.source_gate_artifact_kind == "scout_physiologic_safety_gate_event"
    assert event.source_gate_sha256 == "b" * 64
    assert event.severity == "rest"
    assert event.ln_transition_candidate == "candidate_rest"
    assert event.ln_level_candidate == "L2_CONCERN"
    assert event.reducer_required is True
    assert event.boundary.direct_phase1_mutation_performed is False
    assert event.boundary.safety_api_called is False
    assert event.boundary.medical_diagnosis is False
    assert event.route_pressure_review_required is True
    assert event.eta_delay_minutes == 20
    assert event.route_context.segment_id == "seg.physio"
    assert "seg.physio" in event.route_context.map_target_ids
    assert "outputs/physio/physiologic_gate_evidence.jsonl" in event.evidence_refs
    assert written == event
    assert "/safety/" not in serialized
    assert "raw_payload" not in serialized
    assert "heartRateData" not in serialized


def test_runtime_safety_gate_event_rejects_direct_mutation_and_safety_calls() -> None:
    with pytest.raises(ValueError, match="Phase 1 safety truth"):
        SafetyGateBoundary(phase1_l0_l4_state_mutated=True)

    with pytest.raises(ValueError, match="safety APIs"):
        SafetyGateBoundary(safety_api_called=True)

    with pytest.raises(ValueError, match="medical diagnoses"):
        SafetyGateBoundary(medical_diagnosis=True)


def test_runtime_safety_gate_event_rejects_raw_payload_fields() -> None:
    with pytest.raises(ValueError, match="forbidden raw safety gate fields"):
        build_runtime_safety_gate_event(
            gate_id="physiologic_gate",
            event_id="physiologic_gate:raw",
            source_provider="fixture",
            source_path="outputs/physio/event.json",
            state_candidate="watch",
            severity="watch",
            ln_transition_candidate="candidate_watch",
            required_action="review",
            gate_payload={"raw_payload": {"heartRateData": []}},
        )


def test_runtime_safety_gate_event_requires_transition_not_weaker_than_severity() -> None:
    with pytest.raises(ValueError, match="weaker than severity"):
        build_runtime_safety_gate_event(
            gate_id="darkness_gate",
            event_id="darkness_gate:bad-transition",
            source_provider="fixture",
            source_path="outputs/darkness/event.json",
            state_candidate="darkness_retreat",
            severity="retreat_review",
            ln_transition_candidate="candidate_watch",
            required_action="retreat_review",
        )
