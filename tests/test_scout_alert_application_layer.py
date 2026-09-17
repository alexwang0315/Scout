from __future__ import annotations

import json
from pathlib import Path

import pytest

from safety_models import SafetyLevel
from scout_alert_application_layer import (
    ALERT_APPROVAL_PHRASE,
    TRANSPORT_INVOCATION_APPROVAL_PHRASE,
    ApprovedTransportExecutor,
    ApprovedTransportExecutorSelectionRequest,
    AlertApplicationPrivacy,
    EmergencyCallOutRequest,
    ProductionDeliveryEvidenceReport,
    ProductionEmergencyApprovalRequest,
    ProductionTransportEffectReceipt,
    ProductionTransportExecutorEffectBoundaryManifest,
    ProductionTransportExecutorEffectBoundaryReadinessBoundary,
    ProductionTransportExecutorExecutionBoundary,
    ProductionTransportExecutorExecutionRequest,
    ProductionTransportExecutorExecutionResult,
    ProductionTransportEffectReceiptIntakeBoundary,
    ProductionTransportInvocationBoundary,
    ProductionTransportInvocationRequest,
    ProductionTransportReleaseRequest,
    build_alert_packet_from_phase1_mutation,
    build_delivery_evidence_from_transport_effect_receipt,
    decide_outbound_policy,
    evaluate_approved_transport_executor_selection,
    evaluate_production_emergency_approval,
    evaluate_production_emergency_workflow_completion,
    evaluate_production_transport_executor_effect_boundary_readiness,
    evaluate_production_transport_invocation_guard,
    evaluate_production_transport_release,
    execute_emergency_call_out,
    execute_production_transport_with_client,
    main,
    render_lora_compact,
    render_mqtt_json,
    render_sms_text,
    run_alert_application_dry_run,
    run_emergency_call_out_dry_run,
    verify_production_delivery_evidence,
)
from scout_runtime_phase1_mutation import (
    Phase1SafetyMutationService,
    build_phase1_transition_request,
    write_phase1_mutation_result,
)
from scout_runtime_safety_gate_adapters import build_delay_gate_event
from scout_runtime_safety_gate_models import build_runtime_safety_gate_event
from scout_runtime_safety_reducer import (
    build_phase1_adapter_result,
    reduce_runtime_safety_gate_events,
)
from scout_runtime_safety_state_store import RuntimeSafetyStateStore


def _phase1_mutation_result(tmp_path: Path):
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
    reducer = reduce_runtime_safety_gate_events(
        [physiologic, delay],
        source_path="outputs/runtime/reducer.json",
    )
    adapter = build_phase1_adapter_result(
        reducer,
        source_path="outputs/runtime/phase1_adapter.json",
        phase1_adapter_enabled=True,
        human_review_approved=True,
    )
    store = RuntimeSafetyStateStore(tmp_path / "runtime_safety_state_store")
    snapshot = store.save_snapshot(reducer, phase1_adapter_result=adapter)
    request = build_phase1_transition_request(
        reducer,
        adapter,
        state_snapshot=snapshot,
        source_path="outputs/runtime/phase1_transition_request.json",
        event_time_offset_s=900.0,
    )
    return Phase1SafetyMutationService().apply_transition_request(
        request,
        source_path="outputs/runtime/phase1_safety_mutation_result.json",
    )


def _production_approval_preflight(tmp_path: Path):
    packet = build_alert_packet_from_phase1_mutation(_phase1_mutation_result(tmp_path))
    sms = render_sms_text(packet)
    policy = decide_outbound_policy(
        packet,
        [sms, render_lora_compact(packet), render_mqtt_json(packet)],
        operator_approval_phrase=ALERT_APPROVAL_PHRASE,
    )
    callout = execute_emergency_call_out(
        packet,
        sms,
        policy,
        EmergencyCallOutRequest(
            source_packet_id=packet.packet_id,
            source_packet_sha256=packet.sha256,
            source_policy_sha256=policy.sha256,
            rendered_message_sha256=sms.sha256,
            transport_profile="sms_text",
            executor_kind="local_dry_run",
            idempotency_key="approval-callout-helper",
            explicit_confirmation=True,
        ),
    )
    approval = evaluate_production_emergency_approval(
        packet,
        sms,
        policy,
        callout,
        ProductionEmergencyApprovalRequest(
            source_packet_id=packet.packet_id,
            source_packet_sha256=packet.sha256,
            source_policy_sha256=policy.sha256,
            rendered_message_sha256=sms.sha256,
            call_out_admission_sha256=callout.admission.sha256,
            transport_profile="sms_text",
            idempotency_key="production-approval-helper",
            operator_identity_ref="operator://leader-01",
            operator_authentication_ref="auth://operator-session/leader-01",
            operator_authentication_sha256="b" * 64,
            operator_authenticated=True,
            operator_approval_phrase=ALERT_APPROVAL_PHRASE,
            explicit_confirmation=True,
        ),
    )
    return packet, sms, approval


def _production_transport_release(tmp_path: Path):
    packet, sms, approval = _production_approval_preflight(tmp_path)
    release = evaluate_production_transport_release(
        approval,
        ProductionTransportReleaseRequest(
            production_approval_sha256=approval.sha256,
            source_packet_sha256=packet.sha256,
            source_policy_sha256=approval.source_policy_sha256,
            rendered_message_sha256=sms.sha256,
            call_out_admission_sha256=approval.call_out_admission_sha256,
            transport_profile="sms_text",
            production_gate_residency_audit_sha256="d" * 64,
            production_gate_residency_status="all_resident",
            runtime_authorization_ref="reviewed://runtime-authority/safety-v1",
            runtime_authorization_sha256="e" * 64,
            effect_boundary_ref="reviewed://effect-boundary/transport-v1",
            effect_boundary_sha256="f" * 64,
            effect_boundary_reviewed=True,
            idempotency_key="transport-release-helper",
            explicit_confirmation=True,
            operator_approval_phrase=ALERT_APPROVAL_PHRASE,
        ),
    )
    return packet, sms, approval, release


def _approved_sms_executor() -> ApprovedTransportExecutor:
    return ApprovedTransportExecutor(
        executor_id="sms.executor.prod.001",
        transport_profile="sms_text",
        executor_ref="prod://transport/sms/executor-001",
        executor_sha256="c" * 64,
        approved_for_production=True,
        delivery_verification_supported=True,
        hardware_backed=False,
        network_transport_enabled=True,
        credential_ref="secret-ref://sms-prod-executor",
    )


def _authorized_transport_invocation(tmp_path: Path):
    packet, sms, approval, release = _production_transport_release(tmp_path)
    executor = _approved_sms_executor()
    selection = evaluate_approved_transport_executor_selection(
        release,
        [executor],
        ApprovedTransportExecutorSelectionRequest(
            production_approval_sha256=approval.sha256,
            transport_release_sha256=release.sha256,
            source_packet_sha256=packet.sha256,
            rendered_message_sha256=sms.sha256,
            transport_profile="sms_text",
            executor_id=executor.executor_id,
            idempotency_key="transport-selection-effect-intake-helper",
        ),
    )
    invocation = evaluate_production_transport_invocation_guard(
        release,
        selection,
        ProductionTransportInvocationRequest(
            production_approval_sha256=approval.sha256,
            transport_release_sha256=release.sha256,
            executor_selection_sha256=selection.sha256,
            source_packet_sha256=packet.sha256,
            rendered_message_sha256=sms.sha256,
            transport_profile="sms_text",
            executor_id=executor.executor_id,
            executor_sha256=executor.executor_sha256,
            execution_mode="production_effect_boundary_request",
            idempotency_key="transport-invocation-effect-intake-helper",
            explicit_confirmation=True,
            operator_identity_ref="operator://leader-01",
            operator_authenticated=True,
            operator_approval_phrase=TRANSPORT_INVOCATION_APPROVAL_PHRASE,
            reviewed_transport_effect_boundary_ref="reviewed://transport-effect/sms-v1",
            reviewed_transport_effect_boundary_sha256="5" * 64,
        ),
    )
    return packet, sms, approval, release, executor, selection, invocation


def _transport_executor_effect_boundary_manifest(tmp_path: Path):
    packet, sms, approval, release, executor, selection, invocation = (
        _authorized_transport_invocation(tmp_path)
    )
    manifest = ProductionTransportExecutorEffectBoundaryManifest(
        source_path="prod://transport/sms/executor-001/effect-boundary/readiness",
        executor_selection_sha256=selection.sha256,
        transport_invocation_sha256=invocation.sha256,
        request_sha256=invocation.request_sha256,
        production_approval_sha256=approval.sha256,
        transport_release_sha256=release.sha256,
        source_packet_sha256=packet.sha256,
        rendered_message_sha256=sms.sha256,
        transport_profile="sms_text",
        executor_id=executor.executor_id,
        executor_sha256=executor.executor_sha256,
        transport_execution_ref=invocation.transport_execution_ref or "",
        transport_execution_sha256=invocation.transport_execution_sha256 or "",
        executor_effect_boundary_ref=(
            "reviewed://transport-executor-effect/sms-v1"
        ),
        executor_effect_boundary_sha256="6" * 64,
        credential_ref=executor.credential_ref,
        delivery_verifier_ref="reviewed://delivery-verifier/sms-v1",
        delivery_verifier_sha256="4" * 64,
        fallback_plan_ref="reviewed://transport-fallback/manual-callout-v1",
        fallback_plan_sha256="7" * 64,
        idempotency_key="transport-executor-effect-boundary-readiness-001",
    )
    return packet, sms, approval, release, executor, selection, invocation, manifest


def test_alert_packet_builds_from_phase1_mutation_without_raw_payloads(
    tmp_path: Path,
) -> None:
    mutation = _phase1_mutation_result(tmp_path)

    packet = build_alert_packet_from_phase1_mutation(
        mutation,
        route_name="Fixture Route",
        party_count=3,
    )
    serialized = json.dumps(packet.model_dump(mode="json"), sort_keys=True)

    assert packet.artifact_kind == "scout_alert_application_packet"
    assert packet.phase1_mutation_id == mutation.mutation_id
    assert packet.safety_level == SafetyLevel.DISTRESS
    assert packet.event_type.value == "physiologic_pressure"
    assert packet.selected_gate_id == "physiologic_gate"
    assert packet.emergency_packet.route_id == "fixture.route"
    assert packet.emergency_packet.segment_id == "seg.002"
    assert packet.emergency_packet.party_count == 3
    assert packet.emergency_packet.emergency_contacts == ["119", "112"]
    assert packet.boundary.phase1_runtime_safety_truth_source is True
    assert packet.boundary.phase1_runtime_safety_truth_mutated is False
    assert packet.boundary.outbound_send_performed is False
    assert packet.boundary.safety_api_called is False
    assert packet.boundary.medical_diagnosis is False
    assert packet.privacy.raw_health_payload_shared is False
    assert packet.privacy.raw_gpx_shared is False
    assert packet.privacy.precise_coordinates_shared is False
    assert "/safety/" not in serialized
    assert "raw_payload" not in serialized
    assert '"lat"' not in serialized
    assert '"lon"' not in serialized


def test_sms_lora_mqtt_renderers_create_transport_profiles(tmp_path: Path) -> None:
    packet = build_alert_packet_from_phase1_mutation(_phase1_mutation_result(tmp_path))

    sms = render_sms_text(packet, max_chars=220)
    lora = render_lora_compact(packet, max_bytes=160)
    mqtt = render_mqtt_json(packet, topic_prefix="scout/test/alerts")

    assert sms.transport_profile == "sms_text"
    assert sms.sent is False
    assert sms.body_text is not None
    assert len(sms.body_text) <= 220
    assert "NOT SENT" in sms.body_text
    assert lora.transport_profile == "lora_compact"
    assert lora.sent is False
    assert lora.payload_hex
    assert lora.payload_base64
    assert lora.byte_count <= 160
    assert mqtt.transport_profile == "mqtt_json"
    assert mqtt.sent is False
    assert mqtt.mqtt_topic is not None
    assert mqtt.mqtt_topic.startswith("scout/test/alerts/")
    assert mqtt.payload_json is not None
    assert mqtt.payload_json["sent"] is False
    assert mqtt.payload_json["dry_run"] is True


def test_outbound_policy_requires_approval_and_allows_manual_copy_only(
    tmp_path: Path,
) -> None:
    packet = build_alert_packet_from_phase1_mutation(_phase1_mutation_result(tmp_path))
    rendered = [
        render_sms_text(packet),
        render_lora_compact(packet),
        render_mqtt_json(packet),
    ]

    blocked = decide_outbound_policy(packet, rendered)
    approved = decide_outbound_policy(
        packet,
        rendered,
        operator_approval_phrase=ALERT_APPROVAL_PHRASE,
    )

    assert blocked.status == "requires_human_approval"
    assert blocked.manual_copy_allowed is False
    assert blocked.external_send_allowed is False
    assert approved.status == "allowed_manual_copy"
    assert approved.manual_copy_allowed is True
    assert approved.external_send_allowed is False
    assert approved.boundary.hardware_transport_invoked is False
    assert approved.boundary.outbound_send_performed is False


def test_dry_run_writes_mac_evidence_without_sending(tmp_path: Path) -> None:
    output_dir = tmp_path / "alert_application"

    result = run_alert_application_dry_run(
        _phase1_mutation_result(tmp_path),
        output_dir=output_dir,
        route_name="Fixture Route",
        party_count=2,
        location_ref="segment:seg.002",
    )

    assert result.artifact_kind == "scout_alert_application_dry_run_result"
    assert result.policy_decision.status == "requires_human_approval"
    assert result.policy_decision.external_send_allowed is False
    assert result.evidence.sent is False
    assert result.timeline_events[0]["kind"] == "alert_application_packet_prepared"
    assert result.timeline_events[0]["map_refs"] == ["seg.002", "camp.001"]
    for artifact_ref in result.artifact_refs:
        assert (output_dir / artifact_ref).exists()
    sms_body = (output_dir / "sms_message.txt").read_text(encoding="utf-8")
    dry_run_payload = json.loads(
        (output_dir / "alert_application_dry_run_result.json").read_text(
            encoding="utf-8"
        )
    )
    serialized = json.dumps(dry_run_payload, sort_keys=True)
    assert "NOT SENT" in sms_body
    assert dry_run_payload["boundary"]["outbound_send_performed"] is False
    assert dry_run_payload["boundary"]["hardware_transport_invoked"] is False
    assert "/safety/" not in serialized
    assert "raw_payload" not in serialized
    assert '"lat"' not in serialized
    assert '"lon"' not in serialized


def test_emergency_call_out_dry_run_records_unverified_receipt(
    tmp_path: Path,
) -> None:
    alert_result = run_alert_application_dry_run(
        _phase1_mutation_result(tmp_path),
        output_dir=tmp_path / "alert_application",
        route_name="Fixture Route",
    )

    callout = run_emergency_call_out_dry_run(
        alert_result,
        output_dir=tmp_path / "callout",
        transport_profile="sms_text",
        idempotency_key="callout-dry-run-001",
        explicit_confirmation=True,
    )

    assert callout.admission.status == "admitted_local_dry_run"
    assert callout.attempt is not None
    assert callout.delivery_receipt is not None
    assert callout.delivery_receipt.outcome == "dry_run_recorded"
    assert callout.delivery_receipt.production_delivery_verified is False
    assert callout.delivery_receipt.sent is False
    assert callout.boundary.outbound_send_performed is False
    assert (tmp_path / "callout" / "emergency_call_out_admission.json").exists()
    assert (tmp_path / "callout" / "emergency_call_out_attempt.json").exists()
    assert (
        tmp_path / "callout" / "emergency_call_out_delivery_receipt.json"
    ).exists()
    assert (
        callout.timeline_events[-1]["payload"]["production_delivery_verified"]
        is False
    )


def test_manual_call_out_handoff_requires_authenticated_approval(
    tmp_path: Path,
) -> None:
    packet = build_alert_packet_from_phase1_mutation(_phase1_mutation_result(tmp_path))
    sms = render_sms_text(packet)
    policy = decide_outbound_policy(
        packet,
        [sms, render_lora_compact(packet), render_mqtt_json(packet)],
        operator_approval_phrase=ALERT_APPROVAL_PHRASE,
    )
    base = {
        "source_packet_id": packet.packet_id,
        "source_packet_sha256": packet.sha256,
        "source_policy_sha256": policy.sha256,
        "rendered_message_sha256": sms.sha256,
        "transport_profile": "sms_text",
        "executor_kind": "manual_handoff",
        "idempotency_key": "manual-handoff-001",
        "explicit_confirmation": True,
        "operator_approval_phrase": ALERT_APPROVAL_PHRASE,
    }

    blocked = execute_emergency_call_out(packet, sms, policy, base)
    admitted = execute_emergency_call_out(
        packet,
        sms,
        policy,
        EmergencyCallOutRequest(
            **base,
            operator_identity_ref="operator://leader-01",
            operator_authenticated=True,
        ),
    )

    assert blocked.admission.status == "blocked_requires_authenticated_approval"
    assert blocked.attempt is None
    assert admitted.admission.status == "admitted_manual_handoff"
    assert admitted.delivery_receipt is not None
    assert admitted.delivery_receipt.delivery_claim == "manual_handoff_unverified"
    assert admitted.delivery_receipt.production_delivery_verified is False
    assert admitted.attempt is not None
    assert admitted.attempt.external_send_performed is False


def test_production_transport_call_out_is_blocked_until_executor_and_delivery_exist(
    tmp_path: Path,
) -> None:
    packet = build_alert_packet_from_phase1_mutation(_phase1_mutation_result(tmp_path))
    sms = render_sms_text(packet)
    policy = decide_outbound_policy(
        packet,
        [sms, render_lora_compact(packet), render_mqtt_json(packet)],
        operator_approval_phrase=ALERT_APPROVAL_PHRASE,
    )
    result = execute_emergency_call_out(
        packet,
        sms,
        policy,
        {
            "source_packet_id": packet.packet_id,
            "source_packet_sha256": packet.sha256,
            "source_policy_sha256": policy.sha256,
            "rendered_message_sha256": sms.sha256,
            "transport_profile": "sms_text",
            "executor_kind": "production_transport",
            "idempotency_key": "production-send-001",
            "explicit_confirmation": True,
            "operator_identity_ref": "operator://leader-01",
            "operator_authenticated": True,
            "operator_approval_phrase": ALERT_APPROVAL_PHRASE,
        },
    )

    assert result.admission.status == "blocked_production_executor_unavailable"
    assert result.admission.production_executor_available is False
    assert result.admission.verified_delivery_possible is False
    assert result.attempt is None
    assert result.delivery_receipt is None
    assert result.timeline_events[0]["payload"]["sent"] is False
    assert (
        result.timeline_events[0]["payload"]["production_delivery_verified"]
        is False
    )


def test_production_emergency_approval_records_authenticated_preflight_only(
    tmp_path: Path,
) -> None:
    packet = build_alert_packet_from_phase1_mutation(_phase1_mutation_result(tmp_path))
    sms = render_sms_text(packet)
    policy = decide_outbound_policy(
        packet,
        [sms, render_lora_compact(packet), render_mqtt_json(packet)],
        operator_approval_phrase=ALERT_APPROVAL_PHRASE,
    )
    callout = execute_emergency_call_out(
        packet,
        sms,
        policy,
        EmergencyCallOutRequest(
            source_packet_id=packet.packet_id,
            source_packet_sha256=packet.sha256,
            source_policy_sha256=policy.sha256,
            rendered_message_sha256=sms.sha256,
            transport_profile="sms_text",
            executor_kind="local_dry_run",
            idempotency_key="approval-callout-001",
            explicit_confirmation=True,
        ),
    )

    approval = evaluate_production_emergency_approval(
        packet,
        sms,
        policy,
        callout,
        ProductionEmergencyApprovalRequest(
            source_packet_id=packet.packet_id,
            source_packet_sha256=packet.sha256,
            source_policy_sha256=policy.sha256,
            rendered_message_sha256=sms.sha256,
            call_out_admission_sha256=callout.admission.sha256,
            transport_profile="sms_text",
            idempotency_key="production-approval-001",
            operator_identity_ref="operator://leader-01",
            operator_authentication_ref="auth://operator-session/leader-01",
            operator_authentication_sha256="b" * 64,
            operator_authenticated=True,
            operator_approval_phrase=ALERT_APPROVAL_PHRASE,
            explicit_confirmation=True,
        ),
    )

    assert approval.status == "authenticated_approval_recorded_pending_transport"
    assert approval.operator_approval_recorded is True
    assert approval.operator_authenticated is True
    assert approval.production_approval_granted is False
    assert approval.transport_release_authorized is False
    assert approval.verified_delivery_required is True
    assert approval.verified_delivery_present is False
    assert approval.workflow_complete is False
    assert approval.boundary.outbound_send_performed is False
    assert approval.boundary.hardware_transport_invoked is False


def test_production_emergency_approval_requires_authenticated_operator(
    tmp_path: Path,
) -> None:
    packet = build_alert_packet_from_phase1_mutation(_phase1_mutation_result(tmp_path))
    sms = render_sms_text(packet)
    policy = decide_outbound_policy(
        packet,
        [sms, render_lora_compact(packet), render_mqtt_json(packet)],
        operator_approval_phrase=ALERT_APPROVAL_PHRASE,
    )
    callout = execute_emergency_call_out(
        packet,
        sms,
        policy,
        {
            "source_packet_id": packet.packet_id,
            "source_packet_sha256": packet.sha256,
            "source_policy_sha256": policy.sha256,
            "rendered_message_sha256": sms.sha256,
            "transport_profile": "sms_text",
            "executor_kind": "local_dry_run",
            "idempotency_key": "approval-callout-002",
            "explicit_confirmation": True,
        },
    )

    approval = evaluate_production_emergency_approval(
        packet,
        sms,
        policy,
        callout,
        {
            "source_packet_id": packet.packet_id,
            "source_packet_sha256": packet.sha256,
            "source_policy_sha256": policy.sha256,
            "rendered_message_sha256": sms.sha256,
            "call_out_admission_sha256": callout.admission.sha256,
            "transport_profile": "sms_text",
            "idempotency_key": "production-approval-002",
            "operator_approval_phrase": ALERT_APPROVAL_PHRASE,
            "explicit_confirmation": True,
        },
    )

    assert approval.status == "blocked_requires_authenticated_operator"
    assert approval.operator_approval_recorded is False
    assert approval.production_approval_granted is False
    assert approval.workflow_complete is False


def test_approved_transport_executor_selection_blocks_until_approval_complete(
    tmp_path: Path,
) -> None:
    packet, sms, approval = _production_approval_preflight(tmp_path)
    executor = _approved_sms_executor()

    decision = evaluate_approved_transport_executor_selection(
        approval,
        [executor],
        ApprovedTransportExecutorSelectionRequest(
            production_approval_sha256=approval.sha256,
            source_packet_sha256=packet.sha256,
            rendered_message_sha256=sms.sha256,
            transport_profile="sms_text",
            executor_id=executor.executor_id,
            idempotency_key="transport-selection-001",
        ),
    )

    assert decision.status == "blocked_production_approval_incomplete"
    assert decision.executor_selected is True
    assert decision.executor_approved_for_production is True
    assert decision.delivery_verification_supported is True
    assert decision.production_approval_complete is False
    assert decision.transport_invocation_permitted is False
    assert decision.network_connection_attempted is False
    assert decision.production_transport_invoked is False
    assert decision.hardware_transport_invoked is False
    assert decision.external_send_performed is False
    assert decision.sent is False
    assert decision.production_delivery_verified is False


def test_transport_release_and_delivery_closure_verify_lineage_without_sending(
    tmp_path: Path,
) -> None:
    packet, sms, approval, release = _production_transport_release(tmp_path)
    executor = _approved_sms_executor()
    selection = evaluate_approved_transport_executor_selection(
        release,
        [executor],
        ApprovedTransportExecutorSelectionRequest(
            production_approval_sha256=approval.sha256,
            transport_release_sha256=release.sha256,
            source_packet_sha256=packet.sha256,
            rendered_message_sha256=sms.sha256,
            transport_profile="sms_text",
            executor_id=executor.executor_id,
            idempotency_key="transport-selection-ready-001",
        ),
    )

    delivery = verify_production_delivery_evidence(
        selection,
        ProductionDeliveryEvidenceReport(
            source_path="prod://transport/sms/executor-001/receipts/fixture",
            executor_selection_sha256=selection.sha256,
            production_approval_sha256=approval.sha256,
            transport_release_sha256=release.sha256,
            source_packet_sha256=packet.sha256,
            rendered_message_sha256=sms.sha256,
            transport_profile="sms_text",
            executor_id=executor.executor_id,
            executor_sha256=executor.executor_sha256,
            transport_execution_ref="prod://transport-execution/sms/fixture-001",
            transport_execution_sha256="1" * 64,
            provider_delivery_evidence_ref="prod://provider/sms/delivery/fixture-001",
            provider_delivery_evidence_sha256="2" * 64,
            provider_delivery_id_hash="3" * 64,
            verification_method_ref="reviewed://delivery-verifier/sms-v1",
            verification_method_sha256="4" * 64,
            delivery_status="delivered",
            delivery_confirmation_observed=True,
        ),
    )
    completion = evaluate_production_emergency_workflow_completion(
        release,
        selection,
        delivery,
    )

    assert release.status == "released_for_approved_executor_selection"
    assert release.production_approval_complete is True
    assert release.transport_release_authorized is True
    assert release.workflow_complete is False
    assert release.boundary.external_send_performed_by_verifier is False
    assert selection.status == "ready_for_verified_transport_executor"
    assert selection.transport_invocation_permitted is True
    assert selection.network_connection_attempted is False
    assert selection.external_send_performed is False
    assert delivery.status == "verified_delivery_evidence_accepted"
    assert delivery.production_delivery_verified is True
    assert delivery.boundary.external_send_performed_by_verifier is False
    assert completion.status == "workflow_completed_verified_delivery"
    assert completion.workflow_complete is True
    assert completion.runtime_safety_truth_mutated is False
    assert completion.external_send_performed_by_verifier is False
    assert completion.hardware_transport_invoked_by_verifier is False


def test_transport_invocation_guard_authorizes_receipt_without_sending(
    tmp_path: Path,
) -> None:
    packet, sms, approval, release = _production_transport_release(tmp_path)
    executor = _approved_sms_executor()
    selection = evaluate_approved_transport_executor_selection(
        release,
        [executor],
        ApprovedTransportExecutorSelectionRequest(
            production_approval_sha256=approval.sha256,
            transport_release_sha256=release.sha256,
            source_packet_sha256=packet.sha256,
            rendered_message_sha256=sms.sha256,
            transport_profile="sms_text",
            executor_id=executor.executor_id,
            idempotency_key="transport-selection-ready-guard-001",
        ),
    )
    request = ProductionTransportInvocationRequest(
        production_approval_sha256=approval.sha256,
        transport_release_sha256=release.sha256,
        executor_selection_sha256=selection.sha256,
        source_packet_sha256=packet.sha256,
        rendered_message_sha256=sms.sha256,
        transport_profile="sms_text",
        executor_id=executor.executor_id,
        executor_sha256=executor.executor_sha256,
        execution_mode="production_effect_boundary_request",
        idempotency_key="transport-invocation-guard-001",
        explicit_confirmation=True,
        operator_identity_ref="operator://leader-01",
        operator_authenticated=True,
        operator_approval_phrase=TRANSPORT_INVOCATION_APPROVAL_PHRASE,
        reviewed_transport_effect_boundary_ref="reviewed://transport-effect/sms-v1",
        reviewed_transport_effect_boundary_sha256="5" * 64,
    )
    receipt = evaluate_production_transport_invocation_guard(
        release,
        selection,
        request,
    )
    delivery = verify_production_delivery_evidence(
        selection,
        ProductionDeliveryEvidenceReport(
            source_path="prod://transport/sms/executor-001/receipts/delivered",
            executor_selection_sha256=selection.sha256,
            production_approval_sha256=approval.sha256,
            transport_release_sha256=release.sha256,
            source_packet_sha256=packet.sha256,
            rendered_message_sha256=sms.sha256,
            transport_profile="sms_text",
            executor_id=executor.executor_id,
            executor_sha256=executor.executor_sha256,
            transport_execution_ref=receipt.transport_execution_ref,
            transport_execution_sha256=receipt.transport_execution_sha256,
            provider_delivery_evidence_ref="prod://provider/sms/delivery/fixture-001",
            provider_delivery_evidence_sha256="2" * 64,
            provider_delivery_id_hash="3" * 64,
            verification_method_ref="reviewed://delivery-verifier/sms-v1",
            verification_method_sha256="4" * 64,
            delivery_status="delivered",
            delivery_confirmation_observed=True,
        ),
        receipt,
    )

    assert receipt.status == "transport_invocation_authorized"
    assert receipt.transport_invocation_authorized is True
    assert receipt.operator_approval_recorded is True
    assert receipt.transport_effect_boundary_reviewed is True
    assert receipt.transport_execution_ref is not None
    assert receipt.transport_execution_sha256 is not None
    assert receipt.production_transport_invoked is False
    assert receipt.network_connection_attempted is False
    assert receipt.external_send_performed is False
    assert receipt.hardware_transport_invoked is False
    assert receipt.sent is False
    assert receipt.production_delivery_verified is False
    assert delivery.status == "verified_delivery_evidence_accepted"
    assert delivery.transport_invocation_sha256 == receipt.sha256
    assert delivery.production_delivery_verified is True


def test_transport_executor_effect_boundary_readiness_requires_reviewed_contract(
    tmp_path: Path,
) -> None:
    (
        _packet,
        _sms,
        _approval,
        _release,
        _executor,
        selection,
        invocation,
        manifest,
    ) = _transport_executor_effect_boundary_manifest(tmp_path)

    readiness = evaluate_production_transport_executor_effect_boundary_readiness(
        selection,
        invocation,
        manifest,
    )

    assert readiness.status == "ready_for_reviewed_transport_effect_boundary"
    assert readiness.ready_for_reviewed_transport_effect_boundary is True
    assert readiness.transport_invocation_authorized is True
    assert readiness.lineage_match is True
    assert readiness.executor_boundary_present is True
    assert readiness.credential_ref_present is True
    assert readiness.delivery_verifier_present is True
    assert readiness.fallback_plan_present is True
    assert readiness.transport_execution_ref == invocation.transport_execution_ref
    assert readiness.transport_execution_sha256 == invocation.transport_execution_sha256
    assert readiness.production_transport_executor_invoked is False
    assert readiness.network_connection_attempted is False
    assert readiness.external_send_performed is False
    assert readiness.hardware_transport_invoked is False
    assert readiness.sent is False
    assert readiness.production_delivery_verified is False
    assert readiness.safety_api_called is False
    assert readiness.runtime_safety_truth_mutated is False
    assert (
        readiness.boundary.production_transport_executor_invoked_by_readiness
        is False
    )
    assert readiness.boundary.network_connection_attempted_by_readiness is False
    assert readiness.boundary.external_send_performed_by_readiness is False
    assert readiness.boundary.hardware_transport_invoked_by_readiness is False


def test_transport_executor_effect_boundary_readiness_fails_closed(
    tmp_path: Path,
) -> None:
    (
        _packet,
        _sms,
        _approval,
        _release,
        _executor,
        selection,
        invocation,
        manifest,
    ) = _transport_executor_effect_boundary_manifest(tmp_path)
    base_manifest = manifest.model_dump(mode="json")
    dry_run_invocation = invocation.model_copy(
        update={
            "status": "dry_run_ready",
            "transport_invocation_authorized": False,
            "transport_execution_ref": None,
            "transport_execution_sha256": None,
        }
    )

    unauthorized = evaluate_production_transport_executor_effect_boundary_readiness(
        selection,
        dry_run_invocation,
        base_manifest,
    )
    mismatch = evaluate_production_transport_executor_effect_boundary_readiness(
        selection,
        invocation,
        {**base_manifest, "executor_sha256": "wrong"},
    )
    missing_boundary = (
        evaluate_production_transport_executor_effect_boundary_readiness(
            selection,
            invocation,
            {**base_manifest, "executor_effect_boundary_ref": None},
        )
    )
    missing_verifier = (
        evaluate_production_transport_executor_effect_boundary_readiness(
            selection,
            invocation,
            {**base_manifest, "delivery_verifier_ref": None},
        )
    )
    missing_fallback = (
        evaluate_production_transport_executor_effect_boundary_readiness(
            selection,
            invocation,
            {**base_manifest, "fallback_plan_ref": None},
        )
    )

    assert unauthorized.status == "blocked_transport_invocation_not_authorized"
    assert unauthorized.ready_for_reviewed_transport_effect_boundary is False
    assert mismatch.status == "blocked_effect_boundary_lineage_mismatch"
    assert missing_boundary.status == "blocked_executor_boundary_missing"
    assert missing_verifier.status == "blocked_delivery_verifier_missing"
    assert missing_fallback.status == "blocked_fallback_plan_missing"
    assert missing_fallback.production_transport_executor_invoked is False
    assert missing_fallback.external_send_performed is False
    assert missing_fallback.safety_api_called is False
    with pytest.raises(ValueError, match="cannot perform effects"):
        ProductionTransportExecutorEffectBoundaryReadinessBoundary(
            external_send_performed_by_readiness=True
        )
    with pytest.raises(ValueError, match="cannot perform effects"):
        ProductionTransportExecutorEffectBoundaryManifest(
            **{**base_manifest, "network_connection_attempted_by_readiness": True},
        )


def _transport_executor_execution_request_payload(
    readiness: object,
    invocation: object,
) -> dict[str, object]:
    return {
        "transport_executor_readiness_sha256": readiness.sha256,
        "transport_invocation_sha256": invocation.sha256,
        "manifest_sha256": readiness.manifest_sha256,
        "request_sha256": invocation.request_sha256,
        "production_approval_sha256": invocation.production_approval_sha256,
        "transport_release_sha256": invocation.transport_release_sha256,
        "executor_selection_sha256": invocation.executor_selection_sha256,
        "source_packet_sha256": invocation.source_packet_sha256,
        "rendered_message_sha256": invocation.rendered_message_sha256,
        "transport_profile": invocation.transport_profile,
        "executor_id": invocation.executor_id,
        "executor_sha256": invocation.executor_sha256,
        "transport_execution_ref": invocation.transport_execution_ref,
        "transport_execution_sha256": invocation.transport_execution_sha256,
        "executor_effect_boundary_ref": readiness.executor_effect_boundary_ref,
        "executor_effect_boundary_sha256": (
            readiness.executor_effect_boundary_sha256
        ),
        "credential_ref_present": readiness.credential_ref_present,
        "delivery_verifier_ref": readiness.delivery_verifier_ref,
        "delivery_verifier_sha256": readiness.delivery_verifier_sha256,
        "fallback_plan_ref": readiness.fallback_plan_ref,
        "fallback_plan_sha256": readiness.fallback_plan_sha256,
    }


def _fake_transport_executor_execution_result(
    request: ProductionTransportExecutorExecutionRequest,
) -> dict[str, object]:
    payload = request.model_dump(mode="json")
    assert "credential_ref" not in payload
    assert "credential_value" not in payload
    assert "body_text" not in payload
    assert "payload_json" not in payload
    assert payload["credential_ref_present"] is True
    return {
        "source_path": "prod://transport/sms/executor-001/effects/delivered",
        "transport_invocation_sha256": request.transport_invocation_sha256,
        "request_sha256": request.request_sha256,
        "production_approval_sha256": request.production_approval_sha256,
        "transport_release_sha256": request.transport_release_sha256,
        "executor_selection_sha256": request.executor_selection_sha256,
        "source_packet_sha256": request.source_packet_sha256,
        "rendered_message_sha256": request.rendered_message_sha256,
        "transport_profile": request.transport_profile,
        "executor_id": request.executor_id,
        "executor_sha256": request.executor_sha256,
        "transport_execution_ref": request.transport_execution_ref,
        "transport_execution_sha256": request.transport_execution_sha256,
        "provider_delivery_evidence_ref": "prod://provider/sms/delivery/receipt-001",
        "provider_delivery_evidence_sha256": "2" * 64,
        "provider_delivery_id_hash": "3" * 64,
        "verification_method_ref": request.delivery_verifier_ref,
        "verification_method_sha256": request.delivery_verifier_sha256,
        "delivery_status": "delivered",
        "delivery_confirmation_observed": True,
        "executor_reported_transport_invoked": True,
        "executor_reported_network_connection_attempted": True,
        "executor_reported_external_send_performed": True,
    }


def test_transport_executor_harness_emits_effect_receipt_from_injected_client(
    tmp_path: Path,
) -> None:
    (
        _packet,
        _sms,
        _approval,
        _release,
        _executor,
        selection,
        invocation,
        manifest,
    ) = _transport_executor_effect_boundary_manifest(tmp_path)
    readiness = evaluate_production_transport_executor_effect_boundary_readiness(
        selection,
        invocation,
        manifest,
    )
    seen_requests: list[ProductionTransportExecutorExecutionRequest] = []

    def transport_client(
        request: ProductionTransportExecutorExecutionRequest,
    ) -> dict[str, object]:
        seen_requests.append(request)
        return _fake_transport_executor_execution_result(request)

    execution = execute_production_transport_with_client(
        readiness,
        invocation,
        transport_client,
    )
    intake = build_delivery_evidence_from_transport_effect_receipt(
        invocation,
        execution.effect_receipt or {},
    )
    delivery = verify_production_delivery_evidence(
        selection,
        intake.delivery_report or {},
        invocation,
    )

    assert execution.status == "transport_effect_receipt_emitted"
    assert execution.transport_executor_ready is True
    assert execution.transport_invocation_authorized is True
    assert execution.transport_execution_lineage_match is True
    assert execution.transport_client_called is True
    assert execution.transport_client_result_valid is True
    assert execution.transport_client_effect_present is True
    assert execution.effect_receipt is not None
    assert execution.effect_receipt_sha256 == execution.effect_receipt.sha256
    assert execution.safety_api_called is False
    assert execution.phase1_l0_l4_state_mutated is False
    assert execution.runtime_safety_truth_mutated is False
    assert execution.production_delivery_verified is False
    assert len(seen_requests) == 1
    assert seen_requests[0].transport_invocation_sha256 == invocation.sha256
    assert seen_requests[0].rendered_message_sha256 == (
        invocation.rendered_message_sha256
    )
    assert seen_requests[0].safety_api_called is False
    assert intake.status == "delivery_report_prepared"
    assert delivery.status == "verified_delivery_evidence_accepted"
    assert delivery.production_delivery_verified is True


def test_transport_executor_harness_fails_closed_before_effect_receipt(
    tmp_path: Path,
) -> None:
    (
        _packet,
        _sms,
        _approval,
        _release,
        _executor,
        selection,
        invocation,
        manifest,
    ) = _transport_executor_effect_boundary_manifest(tmp_path)
    readiness = evaluate_production_transport_executor_effect_boundary_readiness(
        selection,
        invocation,
        manifest,
    )
    calls: list[ProductionTransportExecutorExecutionRequest] = []

    def transport_client(
        request: ProductionTransportExecutorExecutionRequest,
    ) -> dict[str, object]:
        calls.append(request)
        return _fake_transport_executor_execution_result(request)

    blocked_readiness = readiness.model_copy(
        update={
            "status": "blocked_delivery_verifier_missing",
            "ready_for_reviewed_transport_effect_boundary": False,
            "delivery_verifier_present": False,
        }
    )
    blocked_invocation = invocation.model_copy(
        update={
            "status": "dry_run_ready",
            "transport_invocation_authorized": False,
        }
    )
    mismatched_readiness = readiness.model_copy(
        update={"executor_id": "sms.executor.prod.other"}
    )

    not_ready = execute_production_transport_with_client(
        blocked_readiness,
        invocation,
        transport_client,
    )
    not_authorized = execute_production_transport_with_client(
        readiness,
        blocked_invocation,
        transport_client,
    )
    mismatch = execute_production_transport_with_client(
        mismatched_readiness,
        invocation,
        transport_client,
    )
    invalid_result = execute_production_transport_with_client(
        readiness,
        invocation,
        lambda request: {
            **_fake_transport_executor_execution_result(request),
            "raw_transport_payload_embedded": True,
        },
    )
    missing_effect = execute_production_transport_with_client(
        readiness,
        invocation,
        lambda request: {
            **_fake_transport_executor_execution_result(request),
            "executor_reported_external_send_performed": False,
        },
    )

    assert not_ready.status == "blocked_transport_executor_not_ready"
    assert not_ready.transport_client_called is False
    assert not_authorized.status == "blocked_transport_invocation_not_authorized"
    assert not_authorized.transport_client_called is False
    assert mismatch.status == "blocked_transport_execution_lineage_mismatch"
    assert mismatch.transport_client_called is False
    assert invalid_result.status == "blocked_transport_client_result_invalid"
    assert invalid_result.effect_receipt is None
    assert missing_effect.status == "blocked_transport_client_effect_missing"
    assert missing_effect.effect_receipt is None
    assert calls == []
    with pytest.raises(ValueError, match="cannot mutate safety runtime"):
        ProductionTransportExecutorExecutionBoundary(safety_api_called=True)
    with pytest.raises(ValueError, match="cannot embed credentials"):
        ProductionTransportExecutorExecutionResult(
            **{
                **_fake_transport_executor_execution_result(
                    ProductionTransportExecutorExecutionRequest(
                        **_transport_executor_execution_request_payload(
                            readiness,
                            invocation,
                        )
                    )
                ),
                "credential_material_embedded": True,
            }
        )


def test_transport_effect_receipt_intake_prepares_delivery_report_without_sending(
    tmp_path: Path,
) -> None:
    packet, sms, approval, release, executor, selection, invocation = (
        _authorized_transport_invocation(tmp_path)
    )
    effect_receipt = ProductionTransportEffectReceipt(
        source_path="prod://transport/sms/executor-001/effects/delivered",
        transport_invocation_sha256=invocation.sha256,
        request_sha256=invocation.request_sha256,
        production_approval_sha256=approval.sha256,
        transport_release_sha256=release.sha256,
        executor_selection_sha256=selection.sha256,
        source_packet_sha256=packet.sha256,
        rendered_message_sha256=sms.sha256,
        transport_profile="sms_text",
        executor_id=executor.executor_id,
        executor_sha256=executor.executor_sha256,
        transport_execution_ref=invocation.transport_execution_ref or "",
        transport_execution_sha256=invocation.transport_execution_sha256 or "",
        provider_delivery_evidence_ref="prod://provider/sms/delivery/receipt-001",
        provider_delivery_evidence_sha256="2" * 64,
        provider_delivery_id_hash="3" * 64,
        verification_method_ref="reviewed://delivery-verifier/sms-v1",
        verification_method_sha256="4" * 64,
        delivery_status="delivered",
        delivery_confirmation_observed=True,
        executor_reported_transport_invoked=True,
        executor_reported_network_connection_attempted=True,
        executor_reported_external_send_performed=True,
    )

    intake = build_delivery_evidence_from_transport_effect_receipt(
        invocation,
        effect_receipt,
    )
    delivery = verify_production_delivery_evidence(
        selection,
        intake.delivery_report or {},
        invocation,
    )

    assert intake.status == "delivery_report_prepared"
    assert intake.delivery_report_prepared is True
    assert intake.intake_verified_delivery_claim is False
    assert intake.delivery_report is not None
    assert intake.delivery_report_sha256 == intake.delivery_report.sha256
    assert intake.delivery_report.transport_execution_ref == (
        invocation.transport_execution_ref
    )
    assert intake.boundary.production_transport_executor_invoked_by_intake is False
    assert intake.boundary.network_connection_attempted_by_intake is False
    assert intake.boundary.external_send_performed_by_intake is False
    assert intake.boundary.hardware_transport_invoked_by_intake is False
    assert delivery.status == "verified_delivery_evidence_accepted"
    assert delivery.production_delivery_verified is True
    assert delivery.transport_invocation_sha256 == invocation.sha256


def test_transport_effect_receipt_intake_fails_closed_before_delivery_report(
    tmp_path: Path,
) -> None:
    packet, sms, approval, release, executor, selection, invocation = (
        _authorized_transport_invocation(tmp_path)
    )
    base_receipt = {
        "source_path": "prod://transport/sms/executor-001/effects/delivered",
        "transport_invocation_sha256": invocation.sha256,
        "request_sha256": invocation.request_sha256,
        "production_approval_sha256": approval.sha256,
        "transport_release_sha256": release.sha256,
        "executor_selection_sha256": selection.sha256,
        "source_packet_sha256": packet.sha256,
        "rendered_message_sha256": sms.sha256,
        "transport_profile": "sms_text",
        "executor_id": executor.executor_id,
        "executor_sha256": executor.executor_sha256,
        "transport_execution_ref": invocation.transport_execution_ref,
        "transport_execution_sha256": invocation.transport_execution_sha256,
        "provider_delivery_evidence_ref": "prod://provider/sms/delivery/receipt-001",
        "provider_delivery_evidence_sha256": "2" * 64,
        "provider_delivery_id_hash": "3" * 64,
        "verification_method_ref": "reviewed://delivery-verifier/sms-v1",
        "verification_method_sha256": "4" * 64,
        "delivery_status": "delivered",
        "delivery_confirmation_observed": True,
        "executor_reported_transport_invoked": True,
        "executor_reported_network_connection_attempted": True,
        "executor_reported_external_send_performed": True,
    }
    dry_run_invocation = invocation.model_copy(
        update={
            "status": "dry_run_ready",
            "transport_invocation_authorized": False,
            "transport_execution_ref": None,
            "transport_execution_sha256": None,
        }
    )
    unauthorized = build_delivery_evidence_from_transport_effect_receipt(
        dry_run_invocation,
        {**base_receipt, "transport_execution_ref": "transport-invocation://dry/run"},
    )
    mismatch = build_delivery_evidence_from_transport_effect_receipt(
        invocation,
        {**base_receipt, "executor_selection_sha256": "wrong"},
    )
    missing_evidence = build_delivery_evidence_from_transport_effect_receipt(
        invocation,
        {**base_receipt, "provider_delivery_evidence_ref": None},
    )
    not_delivered = build_delivery_evidence_from_transport_effect_receipt(
        invocation,
        {**base_receipt, "delivery_status": "accepted_by_gateway"},
    )

    assert unauthorized.status == "blocked_transport_invocation_not_authorized"
    assert unauthorized.delivery_report is None
    assert mismatch.status == "blocked_effect_receipt_lineage_mismatch"
    assert missing_evidence.status == "blocked_missing_delivery_evidence"
    assert not_delivered.status == "blocked_effect_receipt_not_delivered"
    assert not_delivered.intake_verified_delivery_claim is False
    with pytest.raises(ValueError, match="cannot perform effects"):
        ProductionTransportEffectReceiptIntakeBoundary(
            external_send_performed_by_intake=True
        )
    with pytest.raises(ValueError, match="cannot embed credentials"):
        ProductionTransportEffectReceipt(
            **base_receipt,
            credential_material_embedded=True,
        )


def test_transport_invocation_guard_fails_closed_before_effect_boundary(
    tmp_path: Path,
) -> None:
    packet, sms, approval, release = _production_transport_release(tmp_path)
    executor = _approved_sms_executor()
    selection = evaluate_approved_transport_executor_selection(
        release,
        [executor],
        {
            "production_approval_sha256": approval.sha256,
            "transport_release_sha256": release.sha256,
            "source_packet_sha256": packet.sha256,
            "rendered_message_sha256": sms.sha256,
            "transport_profile": "sms_text",
            "executor_id": executor.executor_id,
            "idempotency_key": "transport-selection-ready-guard-002",
        },
    )
    base_request = {
        "production_approval_sha256": approval.sha256,
        "transport_release_sha256": release.sha256,
        "executor_selection_sha256": selection.sha256,
        "source_packet_sha256": packet.sha256,
        "rendered_message_sha256": sms.sha256,
        "transport_profile": "sms_text",
        "executor_id": executor.executor_id,
        "executor_sha256": executor.executor_sha256,
        "execution_mode": "production_effect_boundary_request",
        "idempotency_key": "transport-invocation-guard-002",
        "explicit_confirmation": True,
        "operator_identity_ref": "operator://leader-01",
        "operator_authenticated": True,
        "operator_approval_phrase": TRANSPORT_INVOCATION_APPROVAL_PHRASE,
    }
    dry_run = evaluate_production_transport_invocation_guard(
        release,
        selection,
        {**base_request, "execution_mode": "dry_run"},
    )
    missing_boundary = evaluate_production_transport_invocation_guard(
        release,
        selection,
        base_request,
    )
    wrong_phrase = evaluate_production_transport_invocation_guard(
        release,
        selection,
        {**base_request, "operator_approval_phrase": "wrong phrase"},
    )
    mismatch = evaluate_production_transport_invocation_guard(
        release,
        selection,
        {**base_request, "executor_selection_sha256": "wrong"},
    )

    assert dry_run.status == "dry_run_ready"
    assert dry_run.transport_invocation_authorized is False
    assert missing_boundary.status == "blocked_transport_effect_boundary_missing"
    assert missing_boundary.transport_execution_sha256 is None
    assert wrong_phrase.status == "blocked_requires_explicit_confirmation"
    assert wrong_phrase.transport_invocation_authorized is False
    assert mismatch.status == "blocked_invocation_lineage_mismatch"
    assert mismatch.transport_invocation_authorized is False

    with pytest.raises(ValueError, match="cannot perform effects"):
        ProductionTransportInvocationBoundary(external_send_performed_by_guard=True)


def test_delivery_verification_rejects_invocation_receipt_mismatch(
    tmp_path: Path,
) -> None:
    packet, sms, approval, release = _production_transport_release(tmp_path)
    executor = _approved_sms_executor()
    selection = evaluate_approved_transport_executor_selection(
        release,
        [executor],
        {
            "production_approval_sha256": approval.sha256,
            "transport_release_sha256": release.sha256,
            "source_packet_sha256": packet.sha256,
            "rendered_message_sha256": sms.sha256,
            "transport_profile": "sms_text",
            "executor_id": executor.executor_id,
            "idempotency_key": "transport-selection-ready-guard-003",
        },
    )
    receipt = evaluate_production_transport_invocation_guard(
        release,
        selection,
        {
            "production_approval_sha256": approval.sha256,
            "transport_release_sha256": release.sha256,
            "executor_selection_sha256": selection.sha256,
            "source_packet_sha256": packet.sha256,
            "rendered_message_sha256": sms.sha256,
            "transport_profile": "sms_text",
            "executor_id": executor.executor_id,
            "executor_sha256": executor.executor_sha256,
            "execution_mode": "production_effect_boundary_request",
            "idempotency_key": "transport-invocation-guard-003",
            "explicit_confirmation": True,
            "operator_identity_ref": "operator://leader-01",
            "operator_authenticated": True,
            "operator_approval_phrase": TRANSPORT_INVOCATION_APPROVAL_PHRASE,
            "reviewed_transport_effect_boundary_ref": "reviewed://transport-effect/sms-v1",
            "reviewed_transport_effect_boundary_sha256": "5" * 64,
        },
    )
    delivery = verify_production_delivery_evidence(
        selection,
        {
            "source_path": "prod://transport/sms/executor-001/receipts/delivered",
            "executor_selection_sha256": selection.sha256,
            "production_approval_sha256": approval.sha256,
            "transport_release_sha256": release.sha256,
            "source_packet_sha256": packet.sha256,
            "rendered_message_sha256": sms.sha256,
            "transport_profile": "sms_text",
            "executor_id": executor.executor_id,
            "executor_sha256": executor.executor_sha256,
            "transport_execution_ref": receipt.transport_execution_ref,
            "transport_execution_sha256": "wrong",
            "provider_delivery_evidence_ref": "prod://provider/sms/delivery/fixture-001",
            "provider_delivery_evidence_sha256": "2" * 64,
            "provider_delivery_id_hash": "3" * 64,
            "verification_method_ref": "reviewed://delivery-verifier/sms-v1",
            "verification_method_sha256": "4" * 64,
            "delivery_status": "delivered",
            "delivery_confirmation_observed": True,
        },
        receipt,
    )

    assert delivery.status == "blocked_delivery_lineage_mismatch"
    assert delivery.production_delivery_verified is False


def test_transport_release_requires_all_resident_gates_and_reviewed_boundary(
    tmp_path: Path,
) -> None:
    packet, sms, approval = _production_approval_preflight(tmp_path)

    release = evaluate_production_transport_release(
        approval,
        {
            "production_approval_sha256": approval.sha256,
            "source_packet_sha256": packet.sha256,
            "source_policy_sha256": approval.source_policy_sha256,
            "rendered_message_sha256": sms.sha256,
            "call_out_admission_sha256": approval.call_out_admission_sha256,
            "transport_profile": "sms_text",
            "production_gate_residency_audit_sha256": "d" * 64,
            "production_gate_residency_status": "shadow_only",
            "idempotency_key": "transport-release-shadow-only-001",
            "explicit_confirmation": True,
            "operator_approval_phrase": ALERT_APPROVAL_PHRASE,
        },
    )

    assert release.status == "blocked_gate_residency_not_ready"
    assert release.production_approval_complete is False
    assert release.transport_release_authorized is False
    assert release.workflow_complete is False


def test_delivery_verification_blocks_gateway_only_acknowledgement(
    tmp_path: Path,
) -> None:
    packet, sms, approval, release = _production_transport_release(tmp_path)
    executor = _approved_sms_executor()
    selection = evaluate_approved_transport_executor_selection(
        release,
        [executor],
        {
            "production_approval_sha256": approval.sha256,
            "transport_release_sha256": release.sha256,
            "source_packet_sha256": packet.sha256,
            "rendered_message_sha256": sms.sha256,
            "transport_profile": "sms_text",
            "executor_id": executor.executor_id,
            "idempotency_key": "transport-selection-ready-002",
        },
    )

    delivery = verify_production_delivery_evidence(
        selection,
        {
            "source_path": "prod://transport/sms/executor-001/receipts/gateway-only",
            "executor_selection_sha256": selection.sha256,
            "production_approval_sha256": approval.sha256,
            "transport_release_sha256": release.sha256,
            "source_packet_sha256": packet.sha256,
            "rendered_message_sha256": sms.sha256,
            "transport_profile": "sms_text",
            "executor_id": executor.executor_id,
            "executor_sha256": executor.executor_sha256,
            "transport_execution_ref": "prod://transport-execution/sms/gateway-only",
            "transport_execution_sha256": "1" * 64,
            "provider_delivery_evidence_ref": "prod://provider/sms/accepted/fixture",
            "provider_delivery_evidence_sha256": "2" * 64,
            "provider_delivery_id_hash": "3" * 64,
            "verification_method_ref": "reviewed://delivery-verifier/sms-v1",
            "verification_method_sha256": "4" * 64,
            "delivery_status": "accepted_by_gateway",
            "delivery_confirmation_observed": True,
        },
    )
    completion = evaluate_production_emergency_workflow_completion(
        release,
        selection,
        delivery,
    )

    assert delivery.status == "blocked_delivery_not_verified"
    assert delivery.delivery_evidence_present is True
    assert delivery.production_delivery_verified is False
    assert completion.status == "blocked_verified_delivery_missing"
    assert completion.workflow_complete is False


def test_approved_transport_executor_selection_requires_matching_executor(
    tmp_path: Path,
) -> None:
    packet, sms, approval = _production_approval_preflight(tmp_path)

    decision = evaluate_approved_transport_executor_selection(
        approval,
        [],
        {
            "production_approval_sha256": approval.sha256,
            "source_packet_sha256": packet.sha256,
            "rendered_message_sha256": sms.sha256,
            "transport_profile": "sms_text",
            "executor_id": "sms.executor.missing",
            "idempotency_key": "transport-selection-missing-001",
        },
    )

    assert decision.status == "blocked_no_matching_executor"
    assert decision.executor_selected is False
    assert decision.transport_invocation_permitted is False
    assert decision.sent is False


def test_alert_application_dry_run_cli_writes_evidence(tmp_path: Path) -> None:
    mutation_path = tmp_path / "phase1_mutation_result.json"
    output_dir = tmp_path / "cli_alert_application"
    write_phase1_mutation_result(_phase1_mutation_result(tmp_path), mutation_path)

    exit_code = main(
        [
            "dry-run",
            "--mutation-result",
            str(mutation_path),
            "--output-dir",
            str(output_dir),
            "--route-name",
            "Fixture Route",
            "--party-count",
            "2",
        ]
    )

    assert exit_code == 0
    assert (output_dir / "alert_application_dry_run_result.json").exists()
    assert (output_dir / "sms_message.txt").exists()


def test_emergency_call_out_cli_writes_local_executor_evidence(tmp_path: Path) -> None:
    mutation_path = tmp_path / "phase1_mutation_result.json"
    alert_dir = tmp_path / "cli_alert_application"
    callout_dir = tmp_path / "cli_callout"
    write_phase1_mutation_result(_phase1_mutation_result(tmp_path), mutation_path)
    assert main(
        [
            "dry-run",
            "--mutation-result",
            str(mutation_path),
            "--output-dir",
            str(alert_dir),
            "--route-name",
            "Fixture Route",
            "--party-count",
            "2",
        ]
    ) == 0

    exit_code = main(
        [
            "call-out-dry-run",
            "--alert-dry-run-result",
            str(alert_dir / "alert_application_dry_run_result.json"),
            "--output-dir",
            str(callout_dir),
            "--transport-profile",
            "sms_text",
            "--idempotency-key",
            "callout-cli-001",
            "--explicit-confirmation",
        ]
    )

    assert exit_code == 0
    assert (callout_dir / "emergency_call_out_executor_result.json").exists()


def test_alert_application_privacy_rejects_raw_or_precise_fields() -> None:
    with pytest.raises(ValueError, match="raw private payloads"):
        AlertApplicationPrivacy(raw_health_payload_shared=True)
    with pytest.raises(ValueError, match="raw private payloads"):
        AlertApplicationPrivacy(precise_coordinates_shared=True)
