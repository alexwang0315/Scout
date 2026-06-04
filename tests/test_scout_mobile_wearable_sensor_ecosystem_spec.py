from __future__ import annotations

from pathlib import Path


SPEC_PATH = Path("docs/specs/scout-mobile-wearable-sensor-ecosystem.md")
PHASE46_PATH = Path("docs/specs/phase-4-6-real-device-continuous-stream.md")


def read_spec() -> str:
    return SPEC_PATH.read_text(encoding="utf-8")


def test_mobile_wearable_spec_names_sensor_logger_as_canonical_v0_reference() -> None:
    source = read_spec()

    for token in (
        "Scout Mobile/Wearable Sensor Ecosystem v0",
        "Sensor Logger MQTT Publishing",
        "canonical v0 mobile/wearable wire format",
        "iPhone/Apple Watch combination",
        "Future Android and Scout-native mobile clients",
        "messageId",
        "sessionId",
        "deviceId",
        "payload[].name",
        "payload[].time",
        "UTC epoch nanoseconds",
        "payload[].values",
    ):
        assert token in source


def test_mobile_wearable_spec_defines_mqtt_topics_and_transport_roles() -> None:
    source = read_spec()

    for token in (
        "scout/test/alex/sensorlogger",
        "scout/v1/mobile-wearable/sensorlogger/${deviceId}/${sessionId}/observations",
        "scout/v1/mobile-wearable/{source_adapter}/{device_id}/{session_id}/observations",
        "source_adapter=scout-android",
        "HTTP: local lab",
        "MQTT: default WAN live path",
        "LoRa/LoRaWAN: low-rate nearby/off-grid fallback",
        "Scout-owned or Scout-controlled MQTT broker",
    ):
        assert token in source


def test_mobile_wearable_spec_preserves_all_ingress_evidence_classes() -> None:
    source = read_spec()

    for token in (
        "Ingress Evidence Preservation",
        "preserve ingress evidence before deciding whether a message can be",
        "LAN HTTP or WebSocket",
        "WAN MQTT",
        "LoRa or LoRaWAN gateway messages",
        "`ingress_transport`: `lan_http`, `lan_websocket`, `wan_mqtt`,",
        "`lora_gateway`",
        "`payload_sha256`",
        "`parse_status`: `accepted`, `rejected`, or `unrecognized`",
        "`raw_artifact_path`",
        "`credential_value_exposed`: always `false`",
        "shared `IngressEvidenceRecord` and",
        "`IngressEvidenceIndex` artifacts",
        "LAN, WAN/MQTT, and LoRa/LoRaWAN adapters",
        "RSSI",
        "SNR",
        "spreading factor",
        "Ingress preservation is not the same as runtime admission",
        "signed Scout observation/envelope contract",
    ):
        assert token in source


def test_mobile_wearable_spec_keeps_observer_evidence_only() -> None:
    source = read_spec()

    for token in (
        "The first Scout receiver is a Sensor Logger MQTT observer, not a safety",
        "preserve every accepted raw message as JSONL evidence",
        "detect `messageId` gaps, duplicates, and out-of-order messages",
        "never print or persist MQTT passwords",
        "call `/safety/*`",
        "mutate Phase 1 L0-L4 safety state",
        "write Phase 2 Brain facts",
        '"evidence_only": true',
        '"phase1_runtime_safety_truth": false',
        '"safety_api_called": false',
        '"phase2_brain_writeback": false',
    ):
        assert token in source


def test_phase46_links_to_mobile_wearable_ecosystem_spec() -> None:
    source = PHASE46_PATH.read_text(encoding="utf-8")

    for token in (
        "docs/specs/scout-mobile-wearable-sensor-ecosystem.md",
        "canonical v0 reference wire format",
        "future Android",
        "Scout-native clients",
    ):
        assert token in source
