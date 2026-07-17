from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import scout_emergency_mobile_closed_loop_sandbox as sandbox_module
import scout_runtime_shadow_replay
from admin_api import create_admin_app
from scout_emergency_mobile_closed_loop_api import (
    create_emergency_mobile_closed_loop_router,
)
from scout_emergency_mobile_closed_loop_sandbox import (
    ClosedLoopSandboxConflict,
    ClosedLoopSandboxStore,
    SandboxApprovalRequest,
    SandboxRunRequest,
    SandboxTransportSimulationRequest,
)


def _run_request() -> SandboxRunRequest:
    return SandboxRunRequest(
        scenario_id="sandbox-ridge-distress-v0",
        run_id="run-001",
        project_id="chilai_nanhua_day1_scoutAI",
        confirm_sandbox_run=True,
    )


def test_sandbox_run_exercises_sensorlogger_reducer_and_candidate_boundaries(
    tmp_path: Path,
) -> None:
    store = ClosedLoopSandboxStore(tmp_path / "living")

    projection = store.run_scenario(_run_request())
    serialized = json.dumps(projection.model_dump(mode="json"), sort_keys=True)

    assert projection.artifact_kind == (
        "scout_emergency_mobile_closed_loop_living_projection"
    )
    assert projection.schema_version == "scout.emergency_mobile_closed_loop.living.v0"
    assert projection.status == "pending_approval"
    assert projection.scenario.source_mode == "synthetic_replay"
    assert projection.scenario.scenario_id == "sandbox-ridge-distress-v0"
    assert projection.ingress.adapter == "SensorLoggerMqttObserver.handle_message"
    assert projection.ingress.mode == "synthetic_direct_feed"
    assert projection.ingress.accepted_message_count == 2
    assert projection.ingress.device_count == 2
    assert set(projection.ingress.sensor_names) >= {
        "accelerometer",
        "heartRate",
        "location",
    }
    assert projection.ingress.network_mqtt_publish_performed is False
    assert len(projection.evaluation_snapshot.input_records) == 2
    assert projection.evaluation_snapshot.seal_reason == (
        "expected_synthetic_inputs_accepted"
    )
    assert projection.safety.evaluation_snapshot_sha256 == (
        projection.evaluation_snapshot.sha256
    )
    assert projection.safety.input_set_hash == (
        projection.evaluation_snapshot.input_set_hash
    )
    assert projection.route.route_progress_m == 1850
    assert projection.route.location_ref == "segment:seg.001"
    assert projection.safety.selected_gate_id == "physiologic_gate"
    assert projection.safety.ln_level_candidate == "L3_RETREAT"
    assert projection.safety.phase1_adapter_status == "blocked_feature_flag_disabled"
    assert {gate.gate_id for gate in projection.safety.gates} == {
        "pace_gate",
        "delay_gate",
        "physiologic_gate",
        "weather_gate",
        "darkness_gate",
        "environment_threat_gate",
    }
    assert projection.alert_packet is not None
    assert projection.alert_packet.status == "pending_approval"
    assert projection.alert_packet.sent is False
    assert projection.alert_packet.source_evaluation_snapshot_sha256 == (
        projection.evaluation_snapshot.sha256
    )
    assert projection.approval is None
    assert projection.transport_attempt is None
    assert projection.transport_receipt is None
    assert projection.boundary.candidate_only is True
    assert projection.boundary.runtime_safety_truth is False
    assert projection.boundary.phase1_l0_l4_state_mutated is False
    assert projection.boundary.safety_api_called is False
    assert projection.boundary.real_outbound_send_performed is False
    assert projection.boundary.hardware_control_invoked is False
    assert projection.boundary.synthetic_scenario is True
    assert "/safety/" not in serialized
    assert '"sent": true' not in serialized
    assert "precise_coordinates" not in serialized
    assert len(projection.timeline) >= 5

    run_dir = tmp_path / "living" / "runs" / "run-001"
    for relative in (
        "scenario_fixture.json",
        "ingress/sensorlogger_mqtt_status.json",
        "evaluation_snapshot.json",
        "shadow_replay/runtime_shadow_replay_result.json",
        "alert_packet_candidate.json",
        "living_projection.json",
    ):
        assert (run_dir / relative).exists(), relative
    assert (tmp_path / "living" / "current.json").exists()


def test_sandbox_approval_attempt_and_simulator_receipt_keep_effects_false(
    tmp_path: Path,
) -> None:
    store = ClosedLoopSandboxStore(tmp_path / "living")
    initial = store.run_scenario(_run_request())
    packet = initial.alert_packet
    assert packet is not None

    approval_request = SandboxApprovalRequest(
        scenario_id=initial.scenario.scenario_id,
        packet_id=packet.packet_id,
        packet_sha256=packet.sha256,
        decision="agree_send",
        idempotency_key="approve-001",
        confirm_sandbox_action=True,
    )
    approved = store.record_approval(approval_request)
    repeated = store.record_approval(approval_request)

    assert approved.approval is not None
    assert repeated.approval == approved.approval
    assert approved.status == "approved_sandbox_attempt_recorded"
    assert approved.approval.external_send_requested is True
    assert approved.approval.external_send_performed is False
    assert approved.approval.phase1_mutation_requested is False
    assert approved.transport_attempt is not None
    assert approved.transport_attempt.network_connection_attempted is False
    assert approved.transport_attempt.production_transport_invoked is False
    approval_events = [
        event for event in repeated.timeline if event.kind == "approval_action_recorded"
    ]
    assert len(approval_events) == 1
    attempt_events = [
        event
        for event in repeated.timeline
        if event.kind == "sandbox_transport_attempt_recorded"
    ]
    assert len(attempt_events) == 1

    attempt = approved.transport_attempt
    assert attempt is not None
    completed = store.record_transport_simulation(
        SandboxTransportSimulationRequest(
            scenario_id=initial.scenario.scenario_id,
            attempt_id=attempt.attempt_id,
            attempt_sha256=attempt.sha256,
            packet_id=packet.packet_id,
            packet_sha256=packet.sha256,
            outcome="simulated_receipt_recorded",
            idempotency_key="simulation-001",
            confirm_simulated_transport=True,
        )
    )
    repeated_completed = store.record_transport_simulation(
        SandboxTransportSimulationRequest(
            scenario_id=initial.scenario.scenario_id,
            attempt_id=attempt.attempt_id,
            attempt_sha256=attempt.sha256,
            packet_id=packet.packet_id,
            packet_sha256=packet.sha256,
            outcome="simulated_receipt_recorded",
            idempotency_key="simulation-001",
            confirm_simulated_transport=True,
        )
    )

    assert completed == repeated_completed
    assert completed.status == "simulated_receipt_recorded"
    assert completed.transport_attempt is not None
    assert completed.transport_simulation is not None
    assert completed.transport_receipt is not None
    assert completed.transport_attempt.source_approval_id == approved.approval.approval_id
    assert completed.transport_attempt.source_packet_id == packet.packet_id
    assert completed.transport_attempt.source_packet_sha256 == packet.sha256
    assert completed.transport_attempt.network_connection_attempted is False
    assert completed.transport_attempt.production_transport_invoked is False
    assert completed.transport_attempt.sent is False
    assert (
        completed.transport_receipt.source_attempt_id
        == completed.transport_attempt.attempt_id
    )
    assert (
        completed.transport_receipt.source_attempt_sha256
        == completed.transport_attempt.sha256
    )
    assert completed.transport_receipt.source_packet_id == packet.packet_id
    assert completed.transport_receipt.source_packet_sha256 == packet.sha256
    assert completed.transport_receipt.simulated_receipt_correlated is True
    assert completed.transport_receipt.production_delivery_verified is False
    assert completed.transport_receipt.production_send_performed is False
    assert completed.transport_receipt.sent is False
    assert completed.alert_packet is not None
    assert completed.alert_packet.sent is False
    assert completed.boundary.real_outbound_send_performed is False
    run_dir = tmp_path / "living" / "runs" / "run-001"
    assert (run_dir / "transport_attempts" / "approve-001.json").exists()
    assert (run_dir / "simulations" / "simulation-001.json").exists()
    assert (run_dir / "receipts" / "simulation-001.json").exists()
    assert [event.kind for event in completed.timeline[-2:]] == [
        "sandbox_transport_attempt_recorded",
        "sandbox_transport_receipt_recorded",
    ]


def test_sandbox_rejects_stale_packet_and_receipt_without_send_approval(
    tmp_path: Path,
) -> None:
    store = ClosedLoopSandboxStore(tmp_path / "living")
    initial = store.run_scenario(_run_request())
    packet = initial.alert_packet
    assert packet is not None

    with pytest.raises(ClosedLoopSandboxConflict, match="packet hash"):
        store.record_approval(
            SandboxApprovalRequest(
                scenario_id=initial.scenario.scenario_id,
                packet_id=packet.packet_id,
                packet_sha256="stale-packet-hash",
                decision="agree_send",
                idempotency_key="stale-approval",
                confirm_sandbox_action=True,
            )
        )

    denied = store.record_approval(
        SandboxApprovalRequest(
            scenario_id=initial.scenario.scenario_id,
            packet_id=packet.packet_id,
            packet_sha256=packet.sha256,
            decision="do_not_send",
            idempotency_key="deny-001",
            confirm_sandbox_action=True,
        )
    )
    assert denied.approval is not None
    assert denied.transport_attempt is None

    with pytest.raises(ClosedLoopSandboxConflict, match="agree_send"):
        store.record_transport_simulation(
            SandboxTransportSimulationRequest(
                scenario_id=initial.scenario.scenario_id,
                attempt_id="attempt:missing",
                attempt_sha256="missing",
                packet_id=packet.packet_id,
                packet_sha256=packet.sha256,
                outcome="simulated_receipt_recorded",
                idempotency_key="simulation-denied",
                confirm_simulated_transport=True,
            )
        )


def test_sandbox_rejects_duplicate_approval_and_forged_simulator_outcomes(
    tmp_path: Path,
) -> None:
    store = ClosedLoopSandboxStore(tmp_path / "living")
    initial = store.run_scenario(_run_request())
    packet = initial.alert_packet
    assert packet is not None

    with pytest.raises(ClosedLoopSandboxConflict, match="agree_send approval"):
        store.record_transport_simulation(
            SandboxTransportSimulationRequest(
                scenario_id=initial.scenario.scenario_id,
                attempt_id="attempt:orphan",
                attempt_sha256="orphan-hash",
                packet_id=packet.packet_id,
                packet_sha256=packet.sha256,
                outcome="simulated_receipt_recorded",
                idempotency_key="orphan-simulation",
                confirm_simulated_transport=True,
            )
        )

    approved = store.record_approval(
        SandboxApprovalRequest(
            scenario_id=initial.scenario.scenario_id,
            packet_id=packet.packet_id,
            packet_sha256=packet.sha256,
            decision="agree_send",
            idempotency_key="approve-once",
            confirm_sandbox_action=True,
        )
    )
    attempt = approved.transport_attempt
    assert attempt is not None

    with pytest.raises(ClosedLoopSandboxConflict, match="already recorded"):
        store.record_approval(
            SandboxApprovalRequest(
                scenario_id=initial.scenario.scenario_id,
                packet_id=packet.packet_id,
                packet_sha256=packet.sha256,
                decision="agree_send",
                idempotency_key="approve-twice",
                confirm_sandbox_action=True,
            )
        )

    for field, value, message in (
        ("attempt_id", "attempt:orphan", "attempt_id"),
        ("attempt_sha256", "wrong-attempt-hash", "attempt hash"),
        ("packet_sha256", "wrong-packet-hash", "packet hash"),
    ):
        payload = {
            "scenario_id": initial.scenario.scenario_id,
            "attempt_id": attempt.attempt_id,
            "attempt_sha256": attempt.sha256,
            "packet_id": packet.packet_id,
            "packet_sha256": packet.sha256,
            "outcome": "simulated_receipt_recorded",
            "idempotency_key": f"forged-{field}",
            "confirm_simulated_transport": True,
        }
        payload[field] = value
        with pytest.raises(ClosedLoopSandboxConflict, match=message):
            store.record_transport_simulation(payload)

    unchanged = store.load_current()
    assert unchanged is not None
    assert unchanged.revision == 2
    assert unchanged.transport_simulation is None
    assert unchanged.transport_receipt is None


def test_sandbox_timeout_records_no_receipt_and_is_idempotent(tmp_path: Path) -> None:
    store = ClosedLoopSandboxStore(tmp_path / "living")
    initial = store.run_scenario(_run_request())
    packet = initial.alert_packet
    assert packet is not None
    approved = store.record_approval(
        SandboxApprovalRequest(
            scenario_id=initial.scenario.scenario_id,
            packet_id=packet.packet_id,
            packet_sha256=packet.sha256,
            decision="agree_send",
            idempotency_key="approve-timeout",
            confirm_sandbox_action=True,
        )
    )
    attempt = approved.transport_attempt
    assert attempt is not None
    request = SandboxTransportSimulationRequest(
        scenario_id=initial.scenario.scenario_id,
        attempt_id=attempt.attempt_id,
        attempt_sha256=attempt.sha256,
        packet_id=packet.packet_id,
        packet_sha256=packet.sha256,
        outcome="simulated_timeout",
        idempotency_key="simulation-timeout",
        confirm_simulated_transport=True,
    )

    timed_out = store.record_transport_simulation(request)
    repeated = store.record_transport_simulation(request)

    assert repeated == timed_out
    assert timed_out.status == "simulated_timeout"
    assert timed_out.transport_simulation is not None
    assert timed_out.transport_simulation.receipt_recorded is False
    assert timed_out.transport_receipt is None
    assert timed_out.boundary.real_outbound_send_performed is False
    assert timed_out.boundary.runtime_safety_truth is False
    assert timed_out.boundary.phase1_l0_l4_state_mutated is False
    assert len(
        [
            event
            for event in timed_out.timeline
            if event.kind == "sandbox_transport_simulation_incomplete"
        ]
    ) == 1
    run_dir = tmp_path / "living" / "runs" / "run-001"
    assert not (run_dir / "receipts" / "simulation-timeout.json").exists()


def test_evaluation_snapshot_and_semantic_packet_are_input_order_invariant(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = ClosedLoopSandboxStore(tmp_path / "first").run_scenario(_run_request())
    original_messages = sandbox_module._sensorlogger_messages

    def reversed_messages(request: SandboxRunRequest, base_time: float) -> list[dict]:
        return list(reversed(original_messages(request, base_time)))

    monkeypatch.setattr(sandbox_module, "_sensorlogger_messages", reversed_messages)
    second = ClosedLoopSandboxStore(tmp_path / "second").run_scenario(
        SandboxRunRequest(
            scenario_id="sandbox-ridge-distress-v0",
            run_id="run-002",
            project_id="chilai_nanhua_day1_scoutAI",
            confirm_sandbox_run=True,
        )
    )

    assert first.evaluation_snapshot.input_set_hash == (
        second.evaluation_snapshot.input_set_hash
    )
    assert first.evaluation_snapshot.sha256 == second.evaluation_snapshot.sha256
    assert first.safety.reducer_sha256 == second.safety.reducer_sha256
    assert [gate.model_dump() for gate in first.safety.gates] == [
        gate.model_dump() for gate in second.safety.gates
    ]
    assert first.alert_packet is not None
    assert second.alert_packet is not None
    assert first.alert_packet.content_sha256 == second.alert_packet.content_sha256
    assert first.alert_packet.sha256 != second.alert_packet.sha256


def test_complete_loop_cannot_resolve_phase1_writer_or_network_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ForbiddenPhase1Writer:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise AssertionError("Phase 1 writer must be unreachable from sandbox")

    def forbidden_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("network transport must be unreachable from sandbox")

    monkeypatch.setattr(
        scout_runtime_shadow_replay,
        "Phase1SafetyMutationService",
        ForbiddenPhase1Writer,
    )
    monkeypatch.setattr(
        sandbox_module.SensorLoggerMqttObserver,
        "run_forever",
        forbidden_network,
    )

    store = ClosedLoopSandboxStore(tmp_path / "living")
    initial = store.run_scenario(_run_request())
    packet = initial.alert_packet
    assert packet is not None
    approved = store.record_approval(
        SandboxApprovalRequest(
            scenario_id=initial.scenario.scenario_id,
            packet_id=packet.packet_id,
            packet_sha256=packet.sha256,
            decision="agree_send",
            idempotency_key="sentinel-approval",
            confirm_sandbox_action=True,
        )
    )
    attempt = approved.transport_attempt
    assert attempt is not None
    completed = store.record_transport_simulation(
        SandboxTransportSimulationRequest(
            scenario_id=initial.scenario.scenario_id,
            attempt_id=attempt.attempt_id,
            attempt_sha256=attempt.sha256,
            packet_id=packet.packet_id,
            packet_sha256=packet.sha256,
            outcome="simulated_receipt_recorded",
            idempotency_key="sentinel-simulation",
            confirm_simulated_transport=True,
        )
    )

    assert completed.status == "simulated_receipt_recorded"
    assert completed.boundary.phase1_l0_l4_state_mutated is False
    assert completed.boundary.network_mqtt_publish_performed is False
    assert completed.boundary.production_transport_invoked is False


def test_closed_loop_api_exposes_run_approval_simulation_and_events(
    tmp_path: Path,
) -> None:
    app = FastAPI()
    app.include_router(
        create_emergency_mobile_closed_loop_router(store_root=tmp_path / "living")
    )
    client = TestClient(app)

    empty = client.get("/admin/dashboard/living")
    assert empty.status_code == 200
    assert empty.json()["status"] == "unavailable"
    assert empty.json()["boundary"]["runtime_safety_truth"] is False

    missing_confirmation = client.post(
        "/admin/dashboard/living/scenarios/run",
        json={"scenario_id": "sandbox-ridge-distress-v0", "run_id": "run-001"},
    )
    assert missing_confirmation.status_code == 400

    run = client.post(
        "/admin/dashboard/living/scenarios/run",
        json=_run_request().model_dump(mode="json"),
    )
    assert run.status_code == 200
    run_payload = run.json()
    assert run_payload["status"] == "pending_approval"
    packet = run_payload["alert_packet"]

    approval = client.post(
        "/admin/dashboard/living/approvals",
        json={
            "scenario_id": run_payload["scenario"]["scenario_id"],
            "packet_id": packet["packet_id"],
            "packet_sha256": packet["sha256"],
            "decision": "agree_send",
            "idempotency_key": "api-approve-001",
            "confirm_sandbox_action": True,
        },
    )
    assert approval.status_code == 200
    approval_payload = approval.json()
    assert approval_payload["status"] == "approved_sandbox_attempt_recorded"
    attempt = approval_payload["transport_attempt"]

    simulation = client.post(
        "/admin/dashboard/living/transport/simulations",
        json={
            "scenario_id": run_payload["scenario"]["scenario_id"],
            "attempt_id": attempt["attempt_id"],
            "attempt_sha256": attempt["sha256"],
            "packet_id": packet["packet_id"],
            "packet_sha256": packet["sha256"],
            "outcome": "simulated_receipt_recorded",
            "idempotency_key": "api-simulation-001",
            "confirm_simulated_transport": True,
        },
    )
    assert simulation.status_code == 200
    assert simulation.json()["status"] == "simulated_receipt_recorded"

    events = client.get("/admin/dashboard/living/events")
    assert events.status_code == 200
    assert events.json()["scenario_id"] == "sandbox-ridge-distress-v0"
    assert events.json()["event_count"] == len(events.json()["events"])
    assert events.json()["boundary"]["real_outbound_send_performed"] is False


def test_admin_app_mounts_living_projection_at_dashboard_boundary(
    tmp_path: Path,
) -> None:
    client = TestClient(
        create_admin_app(living_sandbox_store_root=tmp_path / "living")
    )

    response = client.get("/admin/dashboard/living")

    assert response.status_code == 200
    assert response.json()["status"] == "unavailable"
    assert response.json()["boundary"]["runtime_safety_truth"] is False


def test_admin_app_serves_independent_emergency_mobile_surface(tmp_path: Path) -> None:
    client = TestClient(
        create_admin_app(living_sandbox_store_root=tmp_path / "living")
    )

    response = client.get("/emergency/mobile-approval-v0")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert 'data-emergency-surface="mobile"' in response.text
    assert 'LIVING_ENDPOINT = "/admin/dashboard/living"' in response.text
    assert "runtime_safety_truth: false" in response.text
