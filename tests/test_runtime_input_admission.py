import inspect

from runtime_input_admission import (
    RuntimeInputAdmissionStatus,
    admit_runtime_observation_input,
    empty_runtime_input_admission_state,
)
from runtime_observation_envelope import build_signed_runtime_observation_envelope
from runtime_stream_policy import build_default_runtime_stream_policy_manifest


SECRET_KEY = "test-secret"


def _payload() -> dict[str, object]:
    return {
        "timestamp": 60.0,
        "source": "apple_watch",
        "lat": 24.0,
        "lon": 121.0,
        "elevation_m": 1001.0,
        "gps_horizontal_accuracy_m": 8.0,
    }


def _envelope(sequence_no: int, observed_at: str, **overrides):
    values = {
        "payload": _payload(),
        "secret_key": SECRET_KEY,
        "envelope_id": f"runtime_observation_envelope.apple_watch.{sequence_no:04d}",
        "source_id": "runtime_source.apple_watch.v0",
        "source_kind": "apple_watch",
        "transport": "http_push",
        "device_id": "watch.alex.001",
        "sequence_no": sequence_no,
        "observed_at": observed_at,
        "received_at": observed_at,
    }
    values.update(overrides)
    return build_signed_runtime_observation_envelope(**values)


def test_runtime_input_admission_accepts_signed_allowed_source_without_forwarding():
    manifest = build_default_runtime_stream_policy_manifest()
    state = empty_runtime_input_admission_state()
    envelope = _envelope(1, "2026-05-18T10:00:01.000+08:00")

    decision = admit_runtime_observation_input(
        envelope,
        _payload(),
        secret_key=SECRET_KEY,
        policy_manifest=manifest,
        state=state,
        connected=True,
    )

    assert decision.status == RuntimeInputAdmissionStatus.ADMITTED_NOT_FORWARDED
    assert decision.signature_verified is True
    assert decision.policy_matched is True
    assert decision.transport_allowed is True
    assert decision.token_scope_allowed is True
    assert decision.queue_depth == 0
    assert decision.state_after.last_sequence_by_stream == {
        "runtime_source.apple_watch.v0:watch.alex.001": 1
    }
    assert decision.state_after.seen_dedupe_keys == [envelope.dedupe_key]
    assert decision.counts.admitted_count == 1
    assert decision.counts.safety_api_call_count == 0
    assert decision.boundary.admission_only is True
    assert decision.boundary.creates_live_endpoint is False
    assert decision.boundary.calls_safety_api is False
    assert decision.boundary.forwards_to_runtime is False
    assert decision.boundary.connects_device_stream is False
    assert decision.boundary.enables_incident_bridge is False
    assert decision.boundary.writes_phase2_brain is False

    serialized = decision.to_json()
    assert "24.0" not in serialized
    assert "121.0" not in serialized
    assert "elevation_m" not in serialized
    assert "gps_horizontal_accuracy_m" not in serialized


def test_runtime_input_admission_rejects_tampered_payload_or_unknown_source():
    manifest = build_default_runtime_stream_policy_manifest()
    envelope = _envelope(1, "2026-05-18T10:00:01.000+08:00")
    tampered_payload = dict(_payload())
    tampered_payload["lat"] = 25.0

    tampered = admit_runtime_observation_input(
        envelope,
        tampered_payload,
        secret_key=SECRET_KEY,
        policy_manifest=manifest,
        state=empty_runtime_input_admission_state(),
    )

    assert tampered.status == RuntimeInputAdmissionStatus.REJECTED_SIGNATURE
    assert tampered.signature_verified is False
    assert tampered.counts.rejected_count == 1
    assert tampered.state_after.seen_dedupe_keys == []

    unknown_source = _envelope(
        1,
        "2026-05-18T10:00:01.000+08:00",
        source_id="runtime_source.unknown.v0",
    )
    rejected = admit_runtime_observation_input(
        unknown_source,
        _payload(),
        secret_key=SECRET_KEY,
        policy_manifest=manifest,
        state=empty_runtime_input_admission_state(),
    )

    assert rejected.status == RuntimeInputAdmissionStatus.REJECTED_SOURCE_POLICY
    assert rejected.policy_matched is False
    assert rejected.counts.rejected_count == 1


def test_runtime_input_admission_rejects_duplicate_and_out_of_order_sequences():
    manifest = build_default_runtime_stream_policy_manifest()
    state = empty_runtime_input_admission_state()
    first = _envelope(2, "2026-05-18T10:00:02.000+08:00")

    accepted = admit_runtime_observation_input(
        first,
        _payload(),
        secret_key=SECRET_KEY,
        policy_manifest=manifest,
        state=state,
    )
    duplicate = admit_runtime_observation_input(
        first,
        _payload(),
        secret_key=SECRET_KEY,
        policy_manifest=manifest,
        state=accepted.state_after,
    )
    older = _envelope(1, "2026-05-18T10:00:03.000+08:00")
    out_of_order = admit_runtime_observation_input(
        older,
        _payload(),
        secret_key=SECRET_KEY,
        policy_manifest=manifest,
        state=accepted.state_after,
    )

    assert accepted.status == RuntimeInputAdmissionStatus.ADMITTED_NOT_FORWARDED
    assert duplicate.status == RuntimeInputAdmissionStatus.REJECTED_DUPLICATE
    assert out_of_order.status == RuntimeInputAdmissionStatus.REJECTED_SEQUENCE
    assert duplicate.counts.rejected_count == 1
    assert out_of_order.counts.rejected_count == 1


def test_runtime_input_admission_applies_10hz_backpressure_without_safety_call():
    manifest = build_default_runtime_stream_policy_manifest()
    first = _envelope(1, "2026-05-18T10:00:01.000+08:00")
    second = _envelope(2, "2026-05-18T10:00:01.050+08:00")

    accepted = admit_runtime_observation_input(
        first,
        _payload(),
        secret_key=SECRET_KEY,
        policy_manifest=manifest,
        state=empty_runtime_input_admission_state(),
    )
    backpressured = admit_runtime_observation_input(
        second,
        _payload(),
        secret_key=SECRET_KEY,
        policy_manifest=manifest,
        state=accepted.state_after,
    )

    assert backpressured.status == RuntimeInputAdmissionStatus.QUEUED_BACKPRESSURE
    assert backpressured.reason == "cadence_interval_below_policy_minimum"
    assert backpressured.queue_depth == 1
    assert backpressured.state_after.backpressure_queue_keys == [second.dedupe_key]
    assert backpressured.counts.queued_count == 1
    assert backpressured.counts.safety_api_call_count == 0


def test_runtime_input_admission_queues_disconnected_then_keeps_latest_after_retries():
    manifest = build_default_runtime_stream_policy_manifest()
    first = _envelope(1, "2026-05-18T10:00:01.000+08:00")
    second = _envelope(2, "2026-05-18T10:00:02.000+08:00")

    queued = admit_runtime_observation_input(
        first,
        _payload(),
        secret_key=SECRET_KEY,
        policy_manifest=manifest,
        state=empty_runtime_input_admission_state(),
        connected=False,
        retry_attempt=0,
    )
    retained = admit_runtime_observation_input(
        second,
        _payload(),
        secret_key=SECRET_KEY,
        policy_manifest=manifest,
        state=queued.state_after,
        connected=False,
        retry_attempt=manifest.buffering.retry_attempt_limit,
    )

    stream_key = "runtime_source.apple_watch.v0:watch.alex.001"
    assert queued.status == RuntimeInputAdmissionStatus.QUEUED_DISCONNECTED
    assert queued.queue_depth == 1
    assert retained.status == RuntimeInputAdmissionStatus.LATEST_POINT_RETAINED
    assert retained.state_after.latest_retained_key_by_stream == {
        stream_key: second.dedupe_key
    }
    assert retained.counts.queued_count == 1
    assert retained.counts.safety_api_call_count == 0


def test_runtime_input_admission_source_does_not_connect_network_or_runtime():
    import runtime_input_admission

    source = inspect.getsource(runtime_input_admission)

    assert "requests." not in source
    assert "httpx." not in source
    assert "FastAPI" not in source
    assert "APIRouter" not in source
    assert "from fastapi import WebSocket" not in source
    assert "import websockets" not in source
    assert "SafetyRuntimeSession(" not in source
    assert "Phase1IncidentBridge(" not in source
