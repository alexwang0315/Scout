"""Loopback MQTT executable contract for the Alpha sandbox.

Canonical specification:
docs/specs/scout-alpha-mobile-wearable-simulation-sandbox.md
"""

from __future__ import annotations

import threading

import pytest

from scout_local_mqtt_broker_harness import LocalMqttBrokerHarness


def test_qos1_roundtrip_delivers_exact_message_and_publisher_gets_puback() -> None:
    deliveries: list[tuple[str, bytes]] = []
    delivered = threading.Event()

    def record_delivery(topic: str, payload: bytes) -> None:
        deliveries.append((topic, payload))
        delivered.set()

    with LocalMqttBrokerHarness() as broker:
        subscription = broker.subscribe(
            "sensorlogger/scout-phone",
            record_delivery,
            qos=1,
        )
        receipt = broker.publish(
            "sensorlogger/scout-phone",
            b'{"messageId":17,"source":"phone"}',
            qos=1,
        )

        assert delivered.wait(1.0)
        assert deliveries == [
            (
                "sensorlogger/scout-phone",
                b'{"messageId":17,"source":"phone"}',
            )
        ]
        assert receipt.qos == 1
        assert receipt.packet_id is not None
        assert receipt.puback_received is True
        assert receipt.broker_acknowledged is True

        status = broker.status()
        assert broker.host == "127.0.0.1"
        assert broker.port > 0
        assert status.broker_connection_verified is True
        assert status.loopback_publish_count == 1
        assert status.qos1_publish_count == 1
        assert status.puback_count == 1
        assert status.external_network_calls_made is False
        assert status.real_outbound_send_performed is False
        assert status.to_dict()["external_network_calls_made"] is False

        subscription.close()


def test_qos0_ping_and_disconnect_are_supported_without_claiming_puback() -> None:
    deliveries: list[tuple[str, bytes]] = []
    delivered = threading.Event()

    with LocalMqttBrokerHarness() as broker:
        subscription = broker.subscribe(
            "wearable/vitals",
            lambda topic, payload: (
                deliveries.append((topic, payload)),
                delivered.set(),
            ),
            qos=0,
        )

        assert broker.ping() is True
        receipt = broker.publish("wearable/vitals", b"\x00\xffexact-bytes", qos=0)

        assert delivered.wait(1.0)
        assert deliveries == [("wearable/vitals", b"\x00\xffexact-bytes")]
        assert receipt.qos == 0
        assert receipt.packet_id is None
        assert receipt.puback_received is False
        assert receipt.broker_acknowledged is False

        subscription.close()
        status = broker.status()
        assert status.loopback_publish_count == 1
        assert status.qos0_publish_count == 1
        assert status.qos1_publish_count == 0
        assert status.puback_count == 0


def test_burst_delivery_can_be_awaited_without_polling_or_message_loss() -> None:
    deliveries: list[bytes] = []

    with LocalMqttBrokerHarness() as broker:
        subscription = broker.subscribe(
            "scout/sandbox/burst/sensorlogger",
            lambda _topic, payload: deliveries.append(payload),
            qos=1,
        )
        for index in range(64):
            broker.publish(
                "scout/sandbox/burst/sensorlogger",
                f'{{"messageId":{index}}}'.encode(),
                qos=1,
            )

        assert subscription.wait_for_delivery_count(64, timeout=5.0) is True
        assert subscription.delivery_count == 64
        assert len(deliveries) == 64
        assert broker.status().loopback_publish_count == 64


@pytest.mark.parametrize(
    "host",
    [
        "0.0.0.0",
        "localhost",
        "::1",
        "192.0.2.1",
        "example.com",
    ],
)
def test_broker_rejects_every_host_except_explicit_ipv4_loopback(host: str) -> None:
    with pytest.raises(ValueError, match="127.0.0.1"):
        LocalMqttBrokerHarness(host=host)


def test_broker_rejects_fixed_port_and_retains_safety_boundary_after_stop() -> None:
    with pytest.raises(ValueError, match="port 0"):
        LocalMqttBrokerHarness(port=1883)

    broker = LocalMqttBrokerHarness()
    initial = broker.status()
    assert initial.lifecycle == "created"
    assert initial.broker_connection_verified is False
    assert initial.loopback_publish_count == 0

    broker.start()
    assert broker.status().lifecycle == "running"
    broker.stop()

    stopped = broker.status()
    assert stopped.lifecycle == "stopped"
    assert stopped.external_network_calls_made is False
    assert stopped.real_outbound_send_performed is False


def test_invalid_qos_is_rejected_before_any_connection() -> None:
    broker = LocalMqttBrokerHarness()

    with pytest.raises(ValueError, match="QoS"):
        broker.publish("sensor/topic", b"payload", qos=2)

    assert broker.status().broker_connection_verified is False
