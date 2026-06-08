import inspect

from runtime_incident_bridge_opt_in import (
    RuntimeIncidentBridgeOptInStatus,
    build_runtime_incident_bridge_opt_in_decision,
)


def test_incident_bridge_opt_in_guard_stays_disabled_by_default():
    decision = build_runtime_incident_bridge_opt_in_decision(
        operator_id="admin.alex",
        runtime_status="observing",
        operator_opt_in=False,
    )

    assert decision.status == RuntimeIncidentBridgeOptInStatus.OPT_IN_REQUIRED
    assert decision.remote_notifications_enabled is False
    assert decision.enable_performed is False
    assert decision.counts.incident_bridge_enable_count == 0
    assert decision.counts.remote_notification_send_count == 0
    assert decision.counts.phase2_writeback_count == 0
    assert decision.boundary.opt_in_guard_only is True
    assert decision.boundary.sends_remote_notification is False
    assert decision.boundary.enables_phase1_incident_bridge is False
    assert decision.boundary.writes_phase2_brain is False


def test_incident_bridge_opt_in_guard_requires_remote_contact_and_noise_policy():
    missing_contact = build_runtime_incident_bridge_opt_in_decision(
        operator_id="admin.alex",
        runtime_status="observing",
        operator_opt_in=True,
        noise_reduction_policy_ref="noise_reduction_policy.family_low_noise.v0",
    )
    missing_noise = build_runtime_incident_bridge_opt_in_decision(
        operator_id="admin.alex",
        runtime_status="observing",
        operator_opt_in=True,
        remote_contact_policy_ref="remote_contact_policy.family.v0",
    )

    assert missing_contact.status == RuntimeIncidentBridgeOptInStatus.BLOCKED
    assert missing_contact.blocker_reasons == ["missing_remote_contact_policy_ref"]
    assert missing_noise.status == RuntimeIncidentBridgeOptInStatus.BLOCKED
    assert missing_noise.blocker_reasons == ["missing_noise_reduction_policy_ref"]


def test_incident_bridge_opt_in_guard_can_mark_ready_without_enabling_bridge():
    decision = build_runtime_incident_bridge_opt_in_decision(
        operator_id="admin.alex",
        runtime_status="observing",
        operator_opt_in=True,
        remote_contact_policy_ref="remote_contact_policy.family.v0",
        noise_reduction_policy_ref="noise_reduction_policy.family_low_noise.v0",
    )

    assert decision.status == RuntimeIncidentBridgeOptInStatus.READY_NOT_ENABLED
    assert decision.operator_opt_in is True
    assert decision.remote_notifications_enabled is False
    assert decision.enable_performed is False
    assert decision.bridge_enable_allowed_after_guard is True
    assert decision.blocker_reasons == []
    assert decision.counts.incident_bridge_enable_count == 0
    assert decision.counts.remote_notification_send_count == 0


def test_incident_bridge_opt_in_guard_blocks_terminal_or_not_observing_runtime():
    decision = build_runtime_incident_bridge_opt_in_decision(
        operator_id="admin.alex",
        runtime_status="ended",
        operator_opt_in=True,
        remote_contact_policy_ref="remote_contact_policy.family.v0",
        noise_reduction_policy_ref="noise_reduction_policy.family_low_noise.v0",
    )

    assert decision.status == RuntimeIncidentBridgeOptInStatus.BLOCKED
    assert decision.blocker_reasons == ["runtime_status_not_observing_or_paused"]
    assert decision.bridge_enable_allowed_after_guard is False


def test_incident_bridge_opt_in_source_does_not_send_network_or_write_phase2():
    import runtime_incident_bridge_opt_in

    source = inspect.getsource(runtime_incident_bridge_opt_in)

    assert "requests." not in source
    assert "httpx." not in source
    assert "FastAPI" not in source
    assert "APIRouter" not in source
    assert "Phase1IncidentBridge(" not in source
    assert "SafetyRuntimeSession(" not in source
