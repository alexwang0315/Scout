import inspect

from pydantic import ValidationError

from runtime_observation_envelope import (
    RuntimeObservationEnvelope,
    build_signed_runtime_observation_envelope,
    verify_runtime_observation_envelope,
)


def _payload() -> dict[str, object]:
    return {
        "timestamp": 60.0,
        "source": "apple_watch",
        "lat": 24.0,
        "lon": 121.0,
        "elevation_m": 1001.0,
        "gps_horizontal_accuracy_m": 8.0,
    }


def test_runtime_observation_envelope_hashes_and_signs_without_raw_payload():
    envelope = build_signed_runtime_observation_envelope(
        _payload(),
        secret_key="test-secret",
        envelope_id="runtime_observation_envelope.apple_watch.0001",
        source_id="runtime_source.apple_watch.v0",
        source_kind="apple_watch",
        transport="http_push",
        device_id="watch.alex.001",
        sequence_no=1,
        observed_at="2026-05-18T10:00:01+08:00",
        received_at="2026-05-18T10:00:02+08:00",
    )

    assert envelope.artifact_kind == "runtime_observation_envelope"
    assert envelope.source_kind == "apple_watch"
    assert envelope.transport == "http_push"
    assert envelope.device_id == "watch.alex.001"
    assert envelope.token_scope == "runtime:observation:write"
    assert envelope.sequence_no == 1
    assert len(envelope.payload_sha256) == 64
    assert envelope.signature_algorithm == "hmac_sha256"
    assert len(envelope.signature) == 64
    assert envelope.signed_fields == [
        "device_id",
        "source_id",
        "transport",
        "sequence_no",
        "observed_at",
        "payload_sha256",
    ]
    assert envelope.dedupe_key.startswith("runtime_source.apple_watch.v0:watch.alex.001:1:")
    assert envelope.boundary.raw_payload_embedded is False
    assert envelope.boundary.calls_safety_api is False
    assert verify_runtime_observation_envelope(
        envelope,
        _payload(),
        secret_key="test-secret",
    )

    serialized = envelope.to_json()
    assert "24.0" not in serialized
    assert "121.0" not in serialized
    assert "elevation_m" not in serialized
    assert "gps_horizontal_accuracy_m" not in serialized


def test_runtime_observation_envelope_rejects_tampered_payload_or_secret():
    envelope = build_signed_runtime_observation_envelope(
        _payload(),
        secret_key="test-secret",
        envelope_id="runtime_observation_envelope.apple_watch.0001",
        source_id="runtime_source.apple_watch.v0",
        source_kind="apple_watch",
        transport="websocket",
        device_id="watch.alex.001",
        sequence_no=1,
        observed_at="2026-05-18T10:00:01+08:00",
        received_at="2026-05-18T10:00:02+08:00",
    )

    tampered = dict(_payload())
    tampered["lat"] = 25.0
    assert not verify_runtime_observation_envelope(
        envelope,
        tampered,
        secret_key="test-secret",
    )
    assert not verify_runtime_observation_envelope(
        envelope,
        _payload(),
        secret_key="wrong-secret",
    )


def test_runtime_observation_envelope_rejects_bad_dedupe_or_signed_fields():
    envelope = build_signed_runtime_observation_envelope(
        _payload(),
        secret_key="test-secret",
        envelope_id="runtime_observation_envelope.apple_watch.0001",
        source_id="runtime_source.apple_watch.v0",
        source_kind="apple_watch",
        transport="http_push",
        device_id="watch.alex.001",
        sequence_no=1,
        observed_at="2026-05-18T10:00:01+08:00",
        received_at="2026-05-18T10:00:02+08:00",
    )
    payload = envelope.model_dump(mode="json")
    payload["dedupe_key"] = "wrong"
    try:
        RuntimeObservationEnvelope.model_validate(payload)
    except ValidationError as exc:
        assert "dedupe_key mismatch" in str(exc)
    else:
        raise AssertionError("expected bad dedupe key rejection")

    payload = envelope.model_dump(mode="json")
    payload["signed_fields"] = ["device_id"]
    try:
        RuntimeObservationEnvelope.model_validate(payload)
    except ValidationError as exc:
        assert "signed_fields mismatch" in str(exc)
    else:
        raise AssertionError("expected bad signed fields rejection")


def test_runtime_observation_envelope_source_does_not_connect_network_or_runtime():
    import runtime_observation_envelope

    source = inspect.getsource(runtime_observation_envelope)

    assert "requests." not in source
    assert "httpx." not in source
    assert "FastAPI" not in source
    assert "APIRouter" not in source
    assert "SafetyRuntimeSession(" not in source
    assert "Phase1IncidentBridge(" not in source
