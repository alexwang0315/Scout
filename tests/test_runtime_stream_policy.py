import inspect

from pydantic import ValidationError

from runtime_stream_policy import (
    RuntimeIncidentBridgeOptInGuard,
    RuntimeStreamCadencePolicy,
    RuntimeStreamSourceKind,
    RuntimeStreamSourcePolicy,
    RuntimeStreamTransportKind,
    build_default_runtime_stream_policy_manifest,
)


def test_runtime_stream_policy_records_source_auth_buffering_and_cadence_decisions():
    manifest = build_default_runtime_stream_policy_manifest()

    assert manifest.status == "policy_ready_not_connected"
    assert [policy.source_kind for policy in manifest.source_policies] == [
        RuntimeStreamSourceKind.APPLE_WATCH,
        RuntimeStreamSourceKind.MOBILE_PHONE,
    ]
    assert manifest.counts.source_policy_count == 2
    assert manifest.counts.accepted_transport_count == 2
    assert manifest.counts.live_endpoint_count == 0
    assert manifest.counts.safety_api_call_count == 0

    for policy in manifest.source_policies:
        assert policy.accepted_transports == [
            RuntimeStreamTransportKind.HTTP_PUSH,
            RuntimeStreamTransportKind.WEBSOCKET,
        ]
        assert policy.device_id_required is True
        assert policy.scoped_token_required is True
        assert policy.hmac_signature_required is True
        assert policy.timestamp_required is True
        assert policy.sequence_number_required is True
        assert policy.payload_hash_required is True
        assert policy.recommended_auth_method == "device_id_scoped_token_hmac_signature"
        assert policy.token_scope == "runtime:observation:write"
        assert policy.rejects_device_id_only is True
        assert policy.rejects_unsigned_payload is True

    assert manifest.buffering.queue_when_disconnected is True
    assert manifest.buffering.retry_attempt_limit == 5
    assert manifest.buffering.retry_exhausted_fallback == "latest_point_only"
    assert manifest.buffering.keeps_latest_point_after_retry_exhausted is True
    assert manifest.buffering.drops_stale_queued_points_after_retry_exhausted is True

    assert manifest.cadence.max_hz == 10.0
    assert manifest.cadence.min_interval_ms == 100
    assert manifest.cadence.backpressure_enabled is True
    assert manifest.cadence.rate_limit_enabled is True
    assert (
        manifest.cadence.over_limit_action
        == "backpressure_then_drop_oldest_except_latest"
    )


def test_runtime_stream_policy_opens_safety_api_after_handoff_but_not_live_endpoint():
    manifest = build_default_runtime_stream_policy_manifest()

    assert manifest.safety_api_access.safety_api_allowed_after_phase45_handoff is True
    assert manifest.safety_api_access.endpoint_prefix == "/safety"
    assert manifest.safety_api_access.allowed_endpoint_refs == [
        "POST /safety/observations",
        "GET /safety/state",
    ]
    assert manifest.safety_api_access.requires_final_mission_graph is True
    assert manifest.safety_api_access.requires_runtime_handoff_manifest is True
    assert manifest.safety_api_access.requires_runtime_activation is True
    assert manifest.safety_api_access.requires_runtime_observing_state is True
    assert manifest.safety_api_access.requires_source_policy_match is True

    assert manifest.boundary.policy_only is True
    assert manifest.boundary.opens_safety_api_after_handoff is True
    assert manifest.boundary.creates_live_endpoint is False
    assert manifest.boundary.connects_device_stream is False
    assert manifest.boundary.starts_websocket_server is False
    assert manifest.boundary.calls_safety_api is False
    assert manifest.boundary.enables_incident_bridge is False
    assert manifest.boundary.writes_phase2_brain is False


def test_runtime_stream_policy_keeps_incident_bridge_opt_in_guard_disabled():
    manifest = build_default_runtime_stream_policy_manifest()
    guard = manifest.incident_bridge_opt_in_guard

    assert guard.guard_status == "opt_in_required_not_enabled"
    assert guard.enabled_by_default is False
    assert guard.opt_in_required is True
    assert guard.remote_notifications_enabled is False
    assert guard.stream_start_enables_bridge is False
    assert guard.requires_explicit_operator_opt_in is True
    assert guard.requires_remote_contact_policy is True
    assert guard.requires_noise_reduction_policy is True
    assert manifest.counts.incident_bridge_enable_count == 0
    assert manifest.counts.phase2_writeback_count == 0


def test_runtime_stream_policy_rejects_unsafe_auth_and_cadence():
    try:
        RuntimeStreamSourcePolicy(
            source_id="runtime_source.watch_without_websocket.v0",
            source_kind=RuntimeStreamSourceKind.APPLE_WATCH,
            accepted_transports=[RuntimeStreamTransportKind.HTTP_PUSH],
        )
    except ValidationError as exc:
        assert "must support websocket" in str(exc)
    else:
        raise AssertionError("expected missing websocket rejection")

    try:
        RuntimeStreamCadencePolicy(max_hz=20.0)
    except ValidationError as exc:
        assert "must not exceed 10 Hz" in str(exc)
    else:
        raise AssertionError("expected over-10Hz cadence rejection")

    try:
        RuntimeIncidentBridgeOptInGuard(enabled_by_default=True)
    except ValidationError as exc:
        assert "Input should be False" in str(exc)
    else:
        raise AssertionError("expected default-enabled incident bridge rejection")


def test_runtime_stream_policy_source_does_not_connect_network_or_runtime():
    import runtime_stream_policy

    source = inspect.getsource(runtime_stream_policy)

    assert "requests." not in source
    assert "httpx." not in source
    assert "FastAPI" not in source
    assert "APIRouter" not in source
    assert "from fastapi import WebSocket" not in source
    assert "import websockets" not in source
    assert "SafetyRuntimeSession(" not in source
    assert "Phase1IncidentBridge(" not in source
