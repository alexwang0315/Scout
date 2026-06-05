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
        "Transport Layer Roles",
        "HTTP: local lab",
        "WebSocket: local or WAN streaming",
        "TCP stream: gateway-to-Scout",
        "Bluetooth/BLE: short-range",
        "MQTT: WAN live path",
        "LoRa/LoRaWAN: low-rate nearby/off-grid fallback",
        "Satellite message: very low-rate future fallback",
        "Scout-owned or Scout-controlled MQTT broker",
    ):
        assert token in source


def test_mobile_wearable_spec_preserves_all_ingress_evidence_classes() -> None:
    source = read_spec()

    for token in (
        "Ingress Evidence Preservation",
        "preserve ingress evidence before deciding whether a message can be",
        "LAN HTTP, WebSocket, or TCP stream",
        "Bluetooth/BLE from a paired phone",
        "WAN MQTT",
        "LoRa or LoRaWAN gateway messages",
        "Satellite message relays",
        "`ingress_transport`: `lan_http`, `lan_websocket`, `lan_tcp_stream`,",
        "`short_range_bluetooth`",
        "`wan_mqtt`",
        "`lora_gateway`",
        "`satellite_message`",
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
        "Satellite: provider class",
        "Ingress preservation is not the same as runtime admission",
        "signed Scout observation/envelope contract",
    ):
        assert token in source


def test_mobile_wearable_spec_separates_transport_application_record_and_safety() -> None:
    source = read_spec()

    for token in (
        "Transport is not the application layer",
        "Layering Model",
        "Transport ingress layer",
        "Source adapter layer",
        "Scout Sensor/Vitals Record layer",
        "Navigation estimation layer",
        "Safety admission layer",
        "Admin visualization/export layer",
        "trajectory_diff_map.html",
        "Scout Sensor/Vitals Record",
        "artifact_kind: scout_sensor_vitals_record",
        "journey.scout-svr/",
        "observations.jsonl",
        "navigation_estimates.jsonl",
        "vitals.jsonl",
        "journey.gpx",
        "journey.kml",
        "journey.csv",
        "GPS-only position",
        "INS/DR position",
        "Do not escalate to cliff/fall/off-route Ln from a single INS/DR or GPS sample",
        "uncertainty radius overlaps the legal/safe trail corridor",
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
