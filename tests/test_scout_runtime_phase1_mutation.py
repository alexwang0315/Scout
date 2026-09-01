from __future__ import annotations

import json
from pathlib import Path

import pytest

from safety_models import SafetyEventType, SafetyLevel, SafetyState
from scout_runtime_phase1_mutation import (
    Phase1MutationAuditStore,
    Phase1RuntimePromotionReadinessBoundary,
    Phase1RuntimeWriterDeploymentBoundary,
    Phase1RuntimeWriterDeploymentManifest,
    Phase1RuntimeWriterInvocationBoundary,
    Phase1RuntimeWriterInvocationRequest,
    Phase1SafetyMutationService,
    Phase1TransitionRequestBoundary,
    build_phase1_mutation_projection,
    build_phase1_transition_request,
    evaluate_phase1_runtime_promotion_readiness,
    evaluate_phase1_writer_production_deployment_readiness,
    invoke_phase1_runtime_promotion_writer,
    load_phase1_runtime_writer_deployment_readiness_audit,
    load_phase1_runtime_promotion_readiness_gate,
    load_phase1_runtime_writer_invocation_receipt,
    load_phase1_transition_request,
    phase1_mutation_projection_event,
    safety_event_from_phase1_transition_request,
    write_phase1_runtime_promotion_readiness_gate,
    write_phase1_runtime_writer_deployment_readiness_audit,
    write_phase1_runtime_writer_invocation_receipt,
    write_phase1_transition_request,
)
from scout_runtime_safety_gate_adapters import (
    build_delay_gate_event,
    build_production_environment_threat_gate_event,
    build_production_weather_gate_event,
)
from scout_runtime_safety_gate_models import build_runtime_safety_gate_event
from scout_runtime_safety_reducer import (
    build_phase1_adapter_result,
    build_production_gate_residency_audit,
    build_production_live_evidence_contract_audit,
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


def _resident_event(gate_id: str, index: int):
    return build_runtime_safety_gate_event(
        gate_id=gate_id,  # type: ignore[arg-type]
        event_id=f"{gate_id}:resident:{index}",
        source_provider="resident_runtime_ingest",
        source_path=f"resident://runtime/{gate_id}/event.json",
        source_gate_artifact_kind=f"{gate_id}.resident_evidence",
        source_gate_sha256=f"{index}" * 64,
        observed_at_offset_s=300 + index,
        state_candidate="clear",
        severity="none",
        ln_transition_candidate="none",
        required_action="continue_monitoring",
        confidence="high",
        evidence_refs=[
            f"resident://runtime/{gate_id}/source",
            f"field://validation/{gate_id}/leader-attested",
        ],
        route_context={
            "route_id": "runtime.route.chilai-nanhua",
            "segment_id": "seg.001",
            "checkpoint_id": "cp.001",
        },
        data_quality={
            "confidence": "high",
            "signal_count": 3,
            "missing_signal_names": [],
            "stale_signal_names": [],
        },
    )


def _production_runtime_promotion_inputs(tmp_path: Path):
    weather = build_production_weather_gate_event(
        {
            "source_provider": "resident_weather_fusion_live",
            "source_path": "resident://weather/chilai-nanhua/latest",
            "event_id": "weather_gate:resident-live-alert",
            "observed_at_offset_s": 420,
            "warning_level": "severe",
            "warning_type": "thunderstorm",
            "rain_risk": True,
            "lightning_risk": True,
            "source_age_minutes": 18,
            "provider_dataset_ids": ["F-C0041-001"],
            "provider_evidence_ref": "cwa://opendata/F-C0041-001/fresh-qpf",
            "freshness_attestation_ref": "attestation://freshness/weather/under-180m",
            "route_scope_ref": "runtime://route/chilai-nanhua/segment/seg.001",
            "field_attestation_ref": "field://validation/weather/leader-attested",
            "route_context": {
                "route_id": "runtime.route.chilai-nanhua",
                "segment_id": "seg.001",
                "checkpoint_id": "cp.001",
            },
        }
    )
    threat = build_production_environment_threat_gate_event(
        {
            "source_provider": "resident_environment_threat_live",
            "source_path": "resident://environment-threat/chilai-nanhua/current",
            "event_id": "environment_threat_gate:resident-live-blocked",
            "observed_at_offset_s": 390,
            "threat_type": "washout",
            "passability": "blocked",
            "immediacy": "nearby",
            "route_blocked": True,
            "current_observation_ref": "device://camera/summary/route-blocked",
            "freshness_attestation_ref": (
                "attestation://freshness/environment-threat/current"
            ),
            "route_scope_ref": "runtime://route/chilai-nanhua/segment/seg.001",
            "field_attestation_ref": "operator://leader/report/route-blocked",
            "route_context": {
                "route_id": "runtime.route.chilai-nanhua",
                "segment_id": "seg.001",
                "checkpoint_id": "cp.001",
            },
        }
    )
    events = [
        _resident_event("pace_gate", 1),
        _resident_event("delay_gate", 2),
        _resident_event("physiologic_gate", 3),
        weather,
        _resident_event("darkness_gate", 4),
        threat,
    ]
    reducer = reduce_runtime_safety_gate_events(
        events,
        source_path="resident://runtime/reducer/current.json",
    )
    adapter = build_phase1_adapter_result(
        reducer,
        source_path="resident://runtime/phase1_adapter/current.json",
        phase1_adapter_enabled=True,
        human_review_approved=True,
    )
    snapshot = RuntimeSafetyStateStore(tmp_path / "runtime_safety_state_store").save_snapshot(
        reducer,
        phase1_adapter_result=adapter,
    )
    request = build_phase1_transition_request(
        reducer,
        adapter,
        state_snapshot=snapshot,
        source_path="resident://runtime/phase1_transition_request/current.json",
    )
    residency = build_production_gate_residency_audit(
        events,
        source_path="resident://runtime/production_gate_residency/current.json",
    )
    live_audit = build_production_live_evidence_contract_audit(
        [weather, threat],
        source_path="resident://runtime/live_evidence_contract/current.json",
    )
    return request, reducer, adapter, residency, live_audit


def _ready_phase1_writer_deployment_inputs(tmp_path: Path):
    request, reducer, adapter, residency, live_audit = _production_runtime_promotion_inputs(
        tmp_path
    )
    readiness = evaluate_phase1_runtime_promotion_readiness(
        request,
        reducer,
        adapter,
        residency,
        live_audit,
        runtime_authority_ref="reviewed://runtime-authority/night-001",
        runtime_authority_sha256="a" * 64,
        operator_review_ref="reviewed://operator/phase1-promotion-001",
        operator_review_sha256="b" * 64,
    )
    invocation_request = Phase1RuntimeWriterInvocationRequest(
        readiness_gate_sha256=readiness.sha256,
        transition_request_sha256=request.sha256,
        execution_mode="local_test_writer",
        idempotency_key="phase1-writer-deployment-helper",
        explicit_confirmation=True,
        operator_identity_ref="operator://leader/identity/001",
        operator_authenticated=True,
        operator_approval_phrase="APPLY PHASE 1 LOCAL WRITER",
    )
    receipt = invoke_phase1_runtime_promotion_writer(
        request,
        readiness,
        invocation_request,
        mutation_service=Phase1SafetyMutationService(),
        source_path="resident://runtime/phase1_writer_invocation/current.json",
    )
    return request, readiness, receipt


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


def test_phase1_runtime_promotion_readiness_requires_all_local_gates(
    tmp_path: Path,
) -> None:
    request, reducer, adapter, residency, live_audit = _production_runtime_promotion_inputs(
        tmp_path
    )

    gate = evaluate_phase1_runtime_promotion_readiness(
        request,
        reducer,
        adapter,
        residency,
        live_audit,
        runtime_authority_ref="reviewed://runtime-authority/night-001",
        runtime_authority_sha256="a" * 64,
        operator_review_ref="reviewed://operator/phase1-promotion-001",
        operator_review_sha256="b" * 64,
        source_path="resident://runtime/promotion_readiness/current.json",
    )
    written = write_phase1_runtime_promotion_readiness_gate(
        gate,
        tmp_path / "phase1_runtime_promotion_readiness_gate.json",
    )
    loaded = load_phase1_runtime_promotion_readiness_gate(
        tmp_path / "phase1_runtime_promotion_readiness_gate.json"
    )
    serialized = json.dumps(gate.model_dump(mode="json"), sort_keys=True)

    assert gate.status == "ready_for_deterministic_writer"
    assert gate.lineage_match is True
    assert gate.adapter_prepared is True
    assert gate.production_gate_residency_ready is True
    assert gate.live_evidence_contract_ready is True
    assert gate.runtime_authority_present is True
    assert gate.operator_review_present is True
    assert gate.deterministic_writer_preconditions_met is True
    assert gate.phase1_writer_invocation_performed is False
    assert gate.runtime_safety_truth is False
    assert gate.phase1_l0_l4_state_mutated is False
    assert gate.safety_api_called is False
    assert gate.outbound_alert_sent is False
    assert gate.network_connection_attempted is False
    assert gate.external_send_performed is False
    assert gate.hardware_control_performed is False
    assert written.sha256 == gate.sha256
    assert loaded.sha256 == gate.sha256
    assert "/safety/" not in serialized
    assert "raw_payload" not in serialized


def test_phase1_runtime_promotion_readiness_fails_closed(
    tmp_path: Path,
) -> None:
    request, reducer, adapter, residency, live_audit = _production_runtime_promotion_inputs(
        tmp_path
    )

    missing_authority = evaluate_phase1_runtime_promotion_readiness(
        request,
        reducer,
        adapter,
        residency,
        live_audit,
        operator_review_ref="reviewed://operator/phase1-promotion-001",
        operator_review_sha256="b" * 64,
    )
    missing_operator = evaluate_phase1_runtime_promotion_readiness(
        request,
        reducer,
        adapter,
        residency,
        live_audit,
        runtime_authority_ref="reviewed://runtime-authority/night-001",
        runtime_authority_sha256="a" * 64,
    )
    tampered = request.model_copy(update={"selected_event_sha256": "wrong"})
    lineage = evaluate_phase1_runtime_promotion_readiness(
        tampered,
        reducer,
        adapter,
        residency,
        live_audit,
        runtime_authority_ref="reviewed://runtime-authority/night-001",
        runtime_authority_sha256="a" * 64,
        operator_review_ref="reviewed://operator/phase1-promotion-001",
        operator_review_sha256="b" * 64,
    )

    assert missing_authority.status == "blocked_runtime_authority_missing"
    assert missing_authority.deterministic_writer_preconditions_met is False
    assert missing_operator.status == "blocked_operator_review_missing"
    assert missing_operator.deterministic_writer_preconditions_met is False
    assert lineage.status == "blocked_lineage_mismatch"
    assert lineage.lineage_match is False

    with pytest.raises(ValueError, match="cannot perform effects"):
        Phase1RuntimePromotionReadinessBoundary(phase1_l0_l4_state_mutated=True)


def test_phase1_runtime_writer_invocation_guard_dry_run_and_local_writer(
    tmp_path: Path,
) -> None:
    request, reducer, adapter, residency, live_audit = _production_runtime_promotion_inputs(
        tmp_path
    )
    readiness = evaluate_phase1_runtime_promotion_readiness(
        request,
        reducer,
        adapter,
        residency,
        live_audit,
        runtime_authority_ref="reviewed://runtime-authority/night-001",
        runtime_authority_sha256="a" * 64,
        operator_review_ref="reviewed://operator/phase1-promotion-001",
        operator_review_sha256="b" * 64,
    )
    dry_run_request = Phase1RuntimeWriterInvocationRequest(
        readiness_gate_sha256=readiness.sha256,
        transition_request_sha256=request.sha256,
        execution_mode="dry_run",
        idempotency_key="phase1-writer-dry-run-001",
        explicit_confirmation=True,
        operator_identity_ref="operator://leader/identity/001",
        operator_authenticated=True,
        operator_approval_phrase="APPLY PHASE 1 LOCAL WRITER",
    )
    dry_run = invoke_phase1_runtime_promotion_writer(
        request,
        readiness,
        dry_run_request,
    )
    live_request = dry_run_request.model_copy(
        update={
            "execution_mode": "local_test_writer",
            "idempotency_key": "phase1-writer-local-001",
        }
    )
    receipt = invoke_phase1_runtime_promotion_writer(
        request,
        readiness,
        live_request,
        mutation_service=Phase1SafetyMutationService(),
        source_path="resident://runtime/phase1_writer_invocation/current.json",
    )
    written = write_phase1_runtime_writer_invocation_receipt(
        receipt,
        tmp_path / "phase1_runtime_writer_invocation_receipt.json",
    )
    loaded = load_phase1_runtime_writer_invocation_receipt(
        tmp_path / "phase1_runtime_writer_invocation_receipt.json"
    )
    serialized = json.dumps(receipt.model_dump(mode="json"), sort_keys=True)

    assert dry_run.status == "dry_run_ready"
    assert dry_run.local_phase1_writer_invoked is False
    assert dry_run.local_phase1_l0_l4_state_mutated is False
    assert dry_run.production_runtime_write_performed is False
    assert receipt.status == "local_writer_invoked"
    assert receipt.readiness_gate_accepted is True
    assert receipt.operator_approval_recorded is True
    assert receipt.local_phase1_writer_invoked is True
    assert receipt.local_phase1_l0_l4_state_mutated is True
    assert receipt.mutation_result_sha256 is not None
    assert receipt.mutation_status == "applied_transition"
    assert receipt.previous_safety_level == SafetyLevel.NORMAL
    assert receipt.resulting_safety_level == SafetyLevel.EMERGENCY
    assert receipt.production_runtime_write_performed is False
    assert receipt.production_runtime_safety_truth_mutated is False
    assert receipt.safety_api_called is False
    assert receipt.outbound_alert_sent is False
    assert receipt.network_connection_attempted is False
    assert receipt.external_send_performed is False
    assert receipt.hardware_control_performed is False
    assert written.sha256 == receipt.sha256
    assert loaded.sha256 == receipt.sha256
    assert "/safety/" not in serialized
    assert "raw_payload" not in serialized


def test_phase1_runtime_writer_invocation_guard_fails_closed(
    tmp_path: Path,
) -> None:
    request, reducer, adapter, residency, live_audit = _production_runtime_promotion_inputs(
        tmp_path
    )
    readiness = evaluate_phase1_runtime_promotion_readiness(
        request,
        reducer,
        adapter,
        residency,
        live_audit,
        runtime_authority_ref="reviewed://runtime-authority/night-001",
        runtime_authority_sha256="a" * 64,
        operator_review_ref="reviewed://operator/phase1-promotion-001",
        operator_review_sha256="b" * 64,
    )
    base_request = {
        "readiness_gate_sha256": readiness.sha256,
        "transition_request_sha256": request.sha256,
        "execution_mode": "local_test_writer",
        "idempotency_key": "phase1-writer-local-001",
        "explicit_confirmation": True,
        "operator_identity_ref": "operator://leader/identity/001",
        "operator_authenticated": True,
        "operator_approval_phrase": "APPLY PHASE 1 LOCAL WRITER",
    }
    missing_operator = invoke_phase1_runtime_promotion_writer(
        request,
        readiness,
        {
            **base_request,
            "operator_identity_ref": None,
            "operator_authenticated": False,
        },
    )
    missing_phrase = invoke_phase1_runtime_promotion_writer(
        request,
        readiness,
        {
            **base_request,
            "operator_approval_phrase": "wrong phrase",
        },
    )
    mismatch = invoke_phase1_runtime_promotion_writer(
        request,
        readiness,
        {
            **base_request,
            "transition_request_sha256": "wrong",
        },
    )
    not_ready = evaluate_phase1_runtime_promotion_readiness(
        request,
        reducer,
        adapter,
        residency,
        live_audit,
    )
    readiness_blocked = invoke_phase1_runtime_promotion_writer(
        request,
        not_ready,
        {
            **base_request,
            "readiness_gate_sha256": not_ready.sha256,
        },
    )

    assert missing_operator.status == "blocked_requires_authenticated_operator"
    assert missing_operator.local_phase1_writer_invoked is False
    assert missing_phrase.status == "blocked_requires_explicit_confirmation"
    assert missing_phrase.local_phase1_writer_invoked is False
    assert mismatch.status == "blocked_request_mismatch"
    assert mismatch.local_phase1_writer_invoked is False
    assert readiness_blocked.status == "blocked_readiness_not_ready"
    assert readiness_blocked.local_phase1_writer_invoked is False

    with pytest.raises(ValueError, match="external effects"):
        Phase1RuntimeWriterInvocationBoundary(safety_api_called=True)


def test_phase1_writer_production_deployment_readiness_requires_reviewed_boundary(
    tmp_path: Path,
) -> None:
    request, readiness, receipt = _ready_phase1_writer_deployment_inputs(tmp_path)
    manifest = Phase1RuntimeWriterDeploymentManifest(
        readiness_gate_sha256=readiness.sha256,
        writer_invocation_receipt_sha256=receipt.sha256,
        transition_request_sha256=request.sha256,
        runtime_environment_ref="runtime://scout/phase1/prod/environment",
        runtime_deployment_ref="prod://deployment/phase1-writer/v1",
        runtime_authority_ref=readiness.runtime_authority_ref,
        runtime_authority_sha256=readiness.runtime_authority_sha256,
        writer_effect_boundary_ref="reviewed://effect-boundary/phase1-writer/v1",
        writer_effect_boundary_sha256="c" * 64,
        rollback_plan_ref="reviewed://rollback/phase1-writer/v1",
        rollback_plan_sha256="d" * 64,
        operator_review_ref=readiness.operator_review_ref,
        operator_review_sha256=readiness.operator_review_sha256,
        deployment_idempotency_key="phase1-writer-deployment-ready-001",
    )

    audit = evaluate_phase1_writer_production_deployment_readiness(
        request,
        readiness,
        receipt,
        manifest,
        source_path="resident://runtime/phase1_writer_deployment_readiness/current.json",
    )
    written = write_phase1_runtime_writer_deployment_readiness_audit(
        audit,
        tmp_path / "phase1_writer_deployment_readiness.json",
    )
    loaded = load_phase1_runtime_writer_deployment_readiness_audit(
        tmp_path / "phase1_writer_deployment_readiness.json"
    )
    serialized = json.dumps(audit.model_dump(mode="json"), sort_keys=True)

    assert audit.status == "ready_for_reviewed_production_deployment"
    assert audit.writer_invocation_ready is True
    assert audit.deployment_lineage_match is True
    assert audit.runtime_boundary_present is True
    assert audit.rollback_plan_present is True
    assert audit.operator_review_present is True
    assert audit.ready_for_reviewed_production_deployment is True
    assert audit.production_runtime_write_performed is False
    assert audit.production_runtime_safety_truth_mutated is False
    assert audit.safety_api_called is False
    assert audit.network_connection_attempted is False
    assert audit.external_send_performed is False
    assert audit.hardware_control_performed is False
    assert written.sha256 == audit.sha256
    assert loaded.sha256 == audit.sha256
    assert "/safety/" not in serialized
    assert "raw_payload" not in serialized


def test_phase1_writer_production_deployment_readiness_fails_closed(
    tmp_path: Path,
) -> None:
    request, readiness, receipt = _ready_phase1_writer_deployment_inputs(tmp_path)
    base_manifest = {
        "readiness_gate_sha256": readiness.sha256,
        "writer_invocation_receipt_sha256": receipt.sha256,
        "transition_request_sha256": request.sha256,
        "runtime_environment_ref": "runtime://scout/phase1/prod/environment",
        "runtime_deployment_ref": "prod://deployment/phase1-writer/v1",
        "runtime_authority_ref": readiness.runtime_authority_ref,
        "runtime_authority_sha256": readiness.runtime_authority_sha256,
        "writer_effect_boundary_ref": "reviewed://effect-boundary/phase1-writer/v1",
        "writer_effect_boundary_sha256": "c" * 64,
        "rollback_plan_ref": "reviewed://rollback/phase1-writer/v1",
        "rollback_plan_sha256": "d" * 64,
        "operator_review_ref": readiness.operator_review_ref,
        "operator_review_sha256": readiness.operator_review_sha256,
        "deployment_idempotency_key": "phase1-writer-deployment-ready-002",
    }
    dry_run_receipt = receipt.model_copy(
        update={
            "status": "dry_run_ready",
            "local_phase1_writer_invoked": False,
            "local_phase1_l0_l4_state_mutated": False,
            "mutation_result_sha256": None,
            "mutation_id": None,
            "mutation_status": None,
            "previous_safety_level": None,
            "resulting_safety_level": None,
        }
    )
    writer_not_ready = evaluate_phase1_writer_production_deployment_readiness(
        request,
        readiness,
        dry_run_receipt,
        Phase1RuntimeWriterDeploymentManifest(**base_manifest),
    )
    mismatch = evaluate_phase1_writer_production_deployment_readiness(
        request,
        readiness,
        receipt,
        Phase1RuntimeWriterDeploymentManifest(
            **{**base_manifest, "transition_request_sha256": "wrong"}
        ),
    )
    missing_runtime = evaluate_phase1_writer_production_deployment_readiness(
        request,
        readiness,
        receipt,
        Phase1RuntimeWriterDeploymentManifest(
            **{**base_manifest, "runtime_deployment_ref": None}
        ),
    )
    missing_rollback = evaluate_phase1_writer_production_deployment_readiness(
        request,
        readiness,
        receipt,
        Phase1RuntimeWriterDeploymentManifest(
            **{**base_manifest, "rollback_plan_ref": None}
        ),
    )
    missing_operator = evaluate_phase1_writer_production_deployment_readiness(
        request,
        readiness,
        receipt,
        Phase1RuntimeWriterDeploymentManifest(
            **{**base_manifest, "operator_review_ref": None}
        ),
    )

    assert writer_not_ready.status == "blocked_writer_invocation_not_ready"
    assert writer_not_ready.ready_for_reviewed_production_deployment is False
    assert mismatch.status == "blocked_deployment_lineage_mismatch"
    assert missing_runtime.status == "blocked_runtime_boundary_missing"
    assert missing_rollback.status == "blocked_rollback_plan_missing"
    assert missing_operator.status == "blocked_operator_review_missing"
    with pytest.raises(ValueError, match="cannot perform effects"):
        Phase1RuntimeWriterDeploymentBoundary(network_connection_attempted=True)
    with pytest.raises(ValueError, match="cannot perform effects"):
        Phase1RuntimeWriterDeploymentManifest(
            **base_manifest,
            production_runtime_write_performed=True,
        )


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
