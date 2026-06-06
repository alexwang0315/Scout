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


def test_mobile_wearable_spec_records_current_scout_client_requirements() -> None:
    source = read_spec()

    for token in (
        "Captured Requirements from 2026-06-05 Scout Client Discussion",
        "Use real device data for live testing",
        "Sensor Logger Pro MQTT Publishing is the current reference live tester",
        "Health Auto Export / Apple Health exports do not need to be live for v0",
        "pre-trip or admin workflows as batch JSON",
        "A Scout-native iOS/watchOS client remains the future target",
        "bare operational UI",
        "connection status",
        "permission status",
        "recording state",
        "Live Scout testing should focus on motion/location/PDR/vitals ingress first",
    ):
        assert token in source


def test_mobile_wearable_spec_defines_mqtt_topics_and_transport_roles() -> None:
    source = read_spec()

    for token in (
        "scout/test/alex/sensorlogger",
        "scout/v1/mobile-wearable/sensorlogger/${deviceId}/${sessionId}/observations",
        "scout/v1/mobile-wearable/{source_adapter}/{device_id}/{session_id}/observations",
        "source_adapter=scout-android",
        "Transport Service Roles",
        "HTTP: local lab",
        "WebSocket: local or WAN streaming",
        "TCP stream: gateway-to-Scout",
        "Bluetooth/BLE: short-range",
        "MQTT: WAN live path",
        "LoRa/LoRaWAN: low-rate nearby/off-grid fallback",
        "Satellite message: very low-rate future fallback",
        "Scout-owned or Scout-controlled MQTT broker",
        "Public IPv4, floating public IP, router port forwarding, or dynamic DNS",
        "WAN live testing should use MQTT",
        "WebSocket/TLS broker URLs",
        "Public/free brokers are allowed only for protocol smoke tests",
        "bidirectional communication for status, command, acknowledgement",
        "LoRa or LoRaWAN gateways are a nearby/off-grid option",
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
        "Bidirectional transport service layer",
        "Sends already-authorized outbound envelopes",
        "Source adapter layer",
        "Application router layer",
        "Application filter/agent layer",
        "`navigation.ins_dr`",
        "`resource.energy_reserve`",
        "`beacon.tracer`",
        "`weather.route_advisor`",
        "`raw.archive`",
        "Scout Sensor/Vitals Record layer",
        "Safety admission layer",
        "Admin visualization/export layer",
        "trajectory_diff_map.html",
        "Scout Sensor/Vitals Record",
        "artifact_kind: scout_sensor_vitals_record",
        "sensorlogger_mqtt_sensor_vitals_records.jsonl",
        "journey.scout-svr/",
        "observations.jsonl",
        "application_routes.jsonl",
        "filter_outputs.jsonl",
        "navigation_estimates.jsonl",
        "vitals.jsonl",
        "transport_egress_index.jsonl",
        "journey.gpx",
        "journey.kml",
        "journey.csv",
        "GPS-only position",
        "INS/DR position",
        "Do not escalate to cliff/fall/off-route Ln from a single INS/DR or GPS sample",
        "uncertainty radius overlaps the legal/safe trail corridor",
    ):
        assert token in source


def test_mobile_wearable_spec_defines_application_router_and_filter_registry() -> None:
    source = read_spec()

    for token in (
        "Application Router And Filter Registry",
        "The Scout application layer is not INS/DR",
        "INS/DR is one registered filter",
        "behind an application router",
        "Required route targets for v0 planning",
        "`navigation.ins_dr`: IMU, PDR, GPS/location, wheel odometry",
        "`resource.energy_reserve`: heart rate, HRV, battery",
        "`beacon.tracer`: hardware SOS, user distress triggers",
        "`weather.route_advisor`: weather forecast, radar/nowcast summaries",
        "validated by Pydantic AI",
        "`raw.archive`: stores normalized or unrecognized evidence without applying an",
        "Router rules must be declarative and versioned",
        "`route_id` and `router_version`",
        "`dispatch_status`: `accepted`, `blocked`, `deferred`, `failed`, or",
        "`agent_skill_ref` when an AI skill/agent handled the message",
        "A `ScoutApplicationSkill` is a declarative capability package",
        "A `ScoutApplicationAgent` executes a registered skill under router policy",
        "live router must not become an unconstrained",
        "`ins-dr-wearable-route-constrained` skill manifest",
        "`value_key_groups`",
        "`acc_x`, `acc_y`, and `acc_z`",
        "High-Rate Pipeline Versus Skill Router",
        "High-rate pipeline lane",
        "Flexible skill-router lane",
        "Accelerometer / gyro / motion samples",
        "`tools/application_router_benchmark.py`",
        "`tools/application_router_microbench_standalone.py`",
        "`sensorlogger_mqtt_latency.jsonl`",
        "Sensor Logger package time to application routing completion",
        "Optional OLED feedback",
        "diagnostic display only",
        "20% throughput budget",
        "Agent output must not directly select Ln",
        "mutate `/safety/*`",
        "emergency packets unless",
    ):
        assert token in source


def test_mobile_wearable_spec_defines_bidirectional_egress_and_black_box_beacon() -> None:
    source = read_spec()

    for token in (
        "Egress Evidence Preservation",
        "Outbound content is never invented by the transport service",
        "`egress_transport`",
        "`destination_class`",
        "`peer_scout_server`",
        "`message_class`",
        "`position_beacon`",
        "`emergency_packet`",
        "`black_box_heartbeat`",
        "`delivery_status`",
        "`authorization_ref`",
        "Black-Box Beacon And Peer Relay",
        "latest reliable or admitted estimated position",
        "another Scout server/node",
        "peer relay forwarding",
        "The transport service does not own",
        "deciding that an incident exists",
        "selecting safety level Ln",
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
        "The observer should run automatically in the Scout admin runtime",
        "Debug UI visibility is not a prerequisite for receiving MQTT",
        "Debug/admin counters may be reset as projection-only operator state",
        "raw ingress JSONL evidence and ingress index JSONL must remain available",
        "`sensorlogger_mqtt_sensor_vitals_records.jsonl`",
        "`artifact_version=scout_sensor_vitals_record.v0`",
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
