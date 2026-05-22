import inspect
import json

from pydantic import ValidationError

from runtime_observation_envelope import build_signed_runtime_observation_envelope
from runtime_stream_device_identity import (
    RuntimeStreamDeviceCredentialRef,
    RuntimeStreamDeviceIdentity,
    RuntimeStreamDeviceIdentityStatus,
    RuntimeStreamDeviceRegistry,
    check_runtime_stream_device_identity,
)


def _payload() -> dict[str, object]:
    return {
        "timestamp": 60.0,
        "source": "apple_watch",
        "lat": 24.0,
        "lon": 121.0,
    }


def _envelope(device_id: str = "watch.alex.001"):
    return build_signed_runtime_observation_envelope(
        _payload(),
        secret_key="test-secret",
        envelope_id="runtime_observation_envelope.apple_watch.0001",
        source_id="runtime_source.apple_watch.v0",
        source_kind="apple_watch",
        transport="http_push",
        device_id=device_id,
        sequence_no=1,
        observed_at="2026-05-21T10:00:01+08:00",
        received_at="2026-05-21T10:00:02+08:00",
    )


def _registry(status: RuntimeStreamDeviceIdentityStatus = RuntimeStreamDeviceIdentityStatus.ENABLED):
    return RuntimeStreamDeviceRegistry(
        registry_id="runtime_stream_device_registry.phase46.test",
        identities=[
            RuntimeStreamDeviceIdentity(
                source_id="runtime_source.apple_watch.v0",
                source_kind="apple_watch",
                device_id="watch.alex.001",
                display_name="Alex Apple Watch",
                status=status,
                credential=RuntimeStreamDeviceCredentialRef(
                    credential_ref="credential:watch.alex.001.runtime-observation",
                    hmac_secret_ref="env:SCOUT_RUNTIME_STREAM_DEVICE_WATCH_SECRET",
                ),
            )
        ],
    )


def test_device_identity_registry_matches_source_device_and_credential_metadata():
    decision = check_runtime_stream_device_identity(_registry(), _envelope())

    assert decision.matched is True
    assert decision.reason == "device_identity_matched"
    assert decision.credential_ref == "credential:watch.alex.001.runtime-observation"
    assert decision.token_scope == "runtime:observation:write"
    assert decision.signature_algorithm == "hmac_sha256"
    assert decision.secret_value_exposed is False

    serialized = _registry().model_dump(mode="json")
    text = json.dumps(serialized, ensure_ascii=False, sort_keys=True)
    assert "test-secret" not in text
    assert "locationLatitude" not in text
    assert '"lat"' not in text
    assert '"lon"' not in text


def test_device_identity_registry_rejects_unknown_or_disabled_device():
    unknown = check_runtime_stream_device_identity(
        _registry(),
        _envelope(device_id="watch.unknown.001"),
    )
    disabled = check_runtime_stream_device_identity(
        _registry(status=RuntimeStreamDeviceIdentityStatus.DISABLED),
        _envelope(),
    )

    assert unknown.matched is False
    assert unknown.reason == "device_identity_not_registered"
    assert disabled.matched is False
    assert disabled.reason == "device_identity_disabled"
    assert disabled.credential_ref == "credential:watch.alex.001.runtime-observation"


def test_device_identity_rejects_embedded_secret_values():
    try:
        RuntimeStreamDeviceCredentialRef(
            credential_ref="credential:bad",
            hmac_secret_ref="secret:raw-secret-value",
        )
    except ValidationError as exc:
        assert "secret reference" in str(exc)
    else:
        raise AssertionError("expected embedded secret value rejection")


def test_device_identity_source_does_not_connect_network_or_runtime():
    import runtime_stream_device_identity

    source = inspect.getsource(runtime_stream_device_identity)

    assert "requests." not in source
    assert "httpx." not in source
    assert "FastAPI" not in source
    assert "APIRouter" not in source
    assert "from fastapi import WebSocket" not in source
    assert "SafetyRuntimeSession(" not in source
    assert "Phase1IncidentBridge(" not in source
