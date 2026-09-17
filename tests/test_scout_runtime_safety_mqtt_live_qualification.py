from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from scout_runtime_safety_mqtt_live_qualification import (
    DockerExecMqttQualificationTransport,
    MqttLiveQualificationConfig,
    MqttTransportObservation,
    build_mqtt_consumer_receipt,
    run_mqtt_live_qualification,
)


def _config(**updates: object) -> MqttLiveQualificationConfig:
    values: dict[str, object] = {
        "source_path": "prod://qualification/run-001/mqtt-live",
        "run_id": "run-001",
        "execution_host_ref": "pi://scout/runtime",
        "broker_ref": "transport://mqtt/scout/chirpstack-mosquitto",
        "topic": "scout/qualification/safety-emergency/run-001",
        "consumer_receipt_topic": (
            "scout/qualification/safety-emergency/run-001/receipt"
        ),
        "operator_identity_ref": "operator://identity/scout-owner",
        "allow_publish": True,
    }
    values.update(updates)
    return MqttLiveQualificationConfig.model_validate(values)


def _verified_transport(config, payload: str, payload_sha256: str):
    receipt = build_mqtt_consumer_receipt(
        config,
        payload=payload,
        payload_sha256=payload_sha256,
        received_at=datetime(2026, 8, 31, 4, 0, tzinfo=timezone.utc),
    )
    return MqttTransportObservation(
        publish_exit_code=0,
        broker_ack_observed=True,
        consumer_message_received=True,
        consumer_receipt_received=True,
        consumer_receipt_payload=json.dumps(receipt, sort_keys=True),
        network_connection_attempted=True,
        external_send_performed=True,
        broker_allows_anonymous=False,
        credential_ref_applied=True,
    )


def test_live_mqtt_qualification_accepts_consumer_receipt_not_puback() -> None:
    report = run_mqtt_live_qualification(
        _config(),
        transport=_verified_transport,
        now=datetime(2026, 8, 31, 3, 59, tzinfo=timezone.utc),
    )

    assert report.status == "mqtt_live_delivery_verified"
    assert report.transport_client_execution_observed is True
    assert report.transport_credential_ref_only is True
    assert report.delivery_confirmation_observed is True
    assert report.outbound_delivery_evidence_ready is True
    assert report.gateway_ack_rejected_as_sufficient is True
    assert report.consumer_receipt_sha256
    assert report.runtime_safety_truth_mutated is False
    assert report.raw_transport_payload_persisted is False


def test_live_mqtt_qualification_rejects_puback_without_consumer_receipt() -> None:
    def puback_only(_config, _payload: str, _payload_sha256: str):
        return MqttTransportObservation(
            publish_exit_code=0,
            broker_ack_observed=True,
            consumer_message_received=False,
            consumer_receipt_received=False,
            network_connection_attempted=True,
            external_send_performed=True,
            broker_allows_anonymous=False,
        )

    report = run_mqtt_live_qualification(_config(), transport=puback_only)

    assert report.status == "blocked_consumer_receipt_missing"
    assert report.outbound_delivery_evidence_ready is False
    assert report.gateway_ack_rejected_as_sufficient is True
    assert report.delivery_confirmation_observed is False


def test_live_mqtt_qualification_reports_anonymous_broker_security_gap() -> None:
    def anonymous_transport(config, payload: str, payload_sha256: str):
        observed = _verified_transport(config, payload, payload_sha256)
        return observed.model_copy(update={"broker_allows_anonymous": True})

    report = run_mqtt_live_qualification(
        _config(),
        transport=anonymous_transport,
    )

    assert report.status == "mqtt_delivery_verified_transport_auth_gap"
    assert report.outbound_delivery_evidence_ready is True
    assert report.transport_client_execution_observed is True
    assert report.transport_credential_ref_only is False
    assert report.blockers == ["broker_allows_anonymous_connections"]


def test_live_mqtt_qualification_fails_closed_when_auth_policy_is_unknown() -> None:
    def unknown_policy_transport(config, payload: str, payload_sha256: str):
        observed = _verified_transport(config, payload, payload_sha256)
        return observed.model_copy(update={"broker_allows_anonymous": None})

    report = run_mqtt_live_qualification(
        _config(),
        transport=unknown_policy_transport,
    )

    assert report.status == "mqtt_delivery_verified_transport_auth_gap"
    assert report.transport_credential_ref_only is False
    assert report.blockers == ["broker_anonymous_policy_unverified"]


def test_live_mqtt_qualification_requires_credential_ref_application() -> None:
    def no_credential_transport(config, payload: str, payload_sha256: str):
        observed = _verified_transport(config, payload, payload_sha256)
        return observed.model_copy(update={"credential_ref_applied": False})

    report = run_mqtt_live_qualification(
        _config(),
        transport=no_credential_transport,
    )

    assert report.status == "mqtt_delivery_verified_transport_auth_gap"
    assert report.transport_credential_ref_only is False
    assert report.blockers == ["transport_credential_ref_not_applied"]


def test_docker_transport_uses_only_an_opaque_container_options_path() -> None:
    transport = DockerExecMqttQualificationTransport(
        ssh_host="scout",
        credential_options_file=(
            "/mosquitto/config/qualification-client.options"
        )
    )

    assert transport.client_auth_args == [
        "-o",
        "/mosquitto/config/qualification-client.options",
    ]
    assert transport.docker_command(
        "exec", "container", "printf", '{"value":"a b"}'
    ) == [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=15",
        "scout",
        "docker exec container printf '{\"value\":\"a b\"}'",
    ]

    with pytest.raises(ValueError, match="credential options"):
        DockerExecMqttQualificationTransport(
            credential_options_file="/tmp/plaintext-credential.options"
        )
    with pytest.raises(ValueError, match="SSH host"):
        DockerExecMqttQualificationTransport(ssh_host="scout;rm")


def test_live_mqtt_qualification_requires_double_authorization() -> None:
    calls = 0

    def transport(_config, _payload: str, _payload_sha256: str):
        nonlocal calls
        calls += 1
        raise AssertionError("transport must not be called")

    report = run_mqtt_live_qualification(
        _config(allow_publish=False),
        transport=transport,
    )

    assert report.status == "blocked_publish_not_authorized"
    assert calls == 0
    assert report.external_send_performed is False


def test_mqtt_topics_are_scoped_and_non_retained() -> None:
    with pytest.raises(ValueError, match="qualification namespace"):
        _config(topic="scout/emergency/live")
    with pytest.raises(ValueError, match="wildcards"):
        _config(topic="scout/qualification/+/run-001")
    with pytest.raises(ValueError, match="retain"):
        _config(retain=True)
