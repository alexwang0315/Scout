# Spec: Scout Mobile/Wearable Sensor Ecosystem v0

Date: 2026-06-04

## Objective

Scout needs a first ecosystem contract for phones and wearable devices that can
send live sensor evidence into Scout.

The v0 reference path is:

```text
iPhone + Apple Watch
  -> Sensor Logger MQTT Publishing
  -> Scout-owned or Scout-approved MQTT broker
  -> Scout Sensor Logger MQTT observer
  -> evidence-only storage and status
```

This is the first Scout mobile/wearable interop spec. It starts with the
iPhone/Apple Watch combination because that is the available test hardware, but
the contract is intentionally not Apple-only. Future Android and Scout-native
mobile clients should emit the same message/session/device/payload shape unless
a later versioned contract explicitly replaces it.

Normative v0 client scope: Future Android and Scout-native mobile clients are
compatible when they preserve the Sensor Logger v0 outer message shape.

## Product Position

Sensor Logger is a third-party test client. It is not the long-term Scout
client, broker, identity authority, or safety decision engine.

Scout v0 uses Sensor Logger because it provides a working iPhone/Apple Watch
publisher with real motion, location, pedometer, battery, barometer, and
heart-rate evidence. Scout then fixes the Sensor Logger MQTT shape as the
canonical v0 mobile/wearable wire format so that future clients can be tested
against a known contract.

中文註釋：Sensor Logger 是第一個可用的真裝置資料來源，不是 Scout 生態系的
最終 client。Scout 會把它的 MQTT payload shape 固定成 v0 參考格式，未來
Android app 或 Scout 官方 iOS/watchOS app 先照這個格式送資料，再逐步演進。

## Canonical v0 Wire Format

The canonical v0 MQTT payload is the Sensor Logger message body:

```json
{
  "messageId": 42,
  "sessionId": "sensor-logger-recording-session",
  "deviceId": "sensor-logger-device-id",
  "payload": [
    {
      "name": "accelerometer",
      "time": 1780555780517000000,
      "values": {
        "x": 0.1,
        "y": 0.2,
        "z": 0.3
      }
    },
    {
      "name": "location",
      "time": 1780555781517000000,
      "values": {
        "latitude": 24.12,
        "longitude": 121.28,
        "horizontalAccuracy": 8.0
      }
    }
  ]
}
```

Required v0 fields:

- `messageId`: monotonic integer per Sensor Logger recording session.
- `sessionId`: stable id for one recording session.
- `deviceId`: stable id for one publishing device.
- `payload`: non-empty list of sensor readings.
- `payload[].name`: sensor name such as `accelerometer`, `gyroscope`,
  `location`, `pedometer`, `barometer`, `battery`, `heart_rate`, or
  watch-specific names emitted by Sensor Logger.
- `payload[].time`: UTC epoch nanoseconds.
- `payload[].values`: scalar, array, or object containing the sensor-specific
  reading.

Sensor Logger `Test Publish` messages may be a bare reading such as
`{"time": 0, "name": "test", "values": []}`. Scout may accept these only as
connectivity smoke evidence. They must not be treated as a real device session.

## Topic Contract

The lab topic currently used for the iPhone/Apple Watch smoke test is:

```text
scout/test/alex/sensorlogger
```

Production Scout topics should be device/session scoped. Sensor Logger supports
topic templates, so the preferred v0 topic is:

```text
scout/v1/mobile-wearable/sensorlogger/${deviceId}/${sessionId}/observations
```

Future Scout-native clients should use the same topic contract with a different
source segment only when the payload remains wire-compatible:

```text
scout/v1/mobile-wearable/{source_adapter}/{device_id}/{session_id}/observations
```

Examples:

- `source_adapter=sensorlogger`
- `source_adapter=scout-ios`
- `source_adapter=scout-android`
- `source_adapter=scout-watchos`

## Transport Roles

Scout supports three transport roles:

- HTTP: local lab, same Wi-Fi, iPhone hotspot, and high-bandwidth debugging.
- MQTT: default WAN live path because phones and Scout field devices can both
  make outbound broker connections without public inbound IP addresses.
- LoRa/LoRaWAN: low-rate nearby/off-grid fallback for check-ins, last-heard
  evidence, and team beacons. It is not a high-rate wearable stream transport.

Release-bound Scout deployments should use a Scout-owned or Scout-controlled
MQTT broker. Public test brokers are only for protocol smoke tests and must not
carry real location, heart-rate, or participant data.

Normative broker ownership: Scout-owned or Scout-controlled MQTT broker before
release.

## Ingress Evidence Preservation

Scout must preserve ingress evidence before deciding whether a message can be
normalized, admitted, replayed, or promoted.

This rule applies to every mobile/wearable ingress path:

- LAN HTTP or WebSocket from a nearby phone, tablet, laptop, or local gateway.
- WAN MQTT from Sensor Logger, Scout-native clients, broker bridges, or cloud
  relays.
- LoRa or LoRaWAN gateway messages, including low-rate check-ins, last-heard
  beacons, team beacons, and radio metadata.

Required ingress evidence fields:

- `ingress_transport`: `lan_http`, `lan_websocket`, `wan_mqtt`,
  `lora_gateway`, or a later versioned value.
- `source_adapter`: adapter name such as `sensorlogger`, `scout-ios`,
  `scout-android`, `lora-gateway`, or `manual-lab-tool`.
- `received_at`: Scout receiver timestamp.
- `payload_sha256`: hash of the exact received payload bytes or decoded text.
- `parse_status`: `accepted`, `rejected`, or `unrecognized`.
- `raw_artifact_path`: path to the retained raw evidence record.
- `credential_value_exposed`: always `false`.

Implementation anchor: Scout v0 uses shared `IngressEvidenceRecord` and
`IngressEvidenceIndex` artifacts for LAN, WAN/MQTT, and LoRa/LoRaWAN adapters.
Individual adapters may add transport-specific metadata, but they must not
invent incompatible summary/index shapes for raw ingress preservation.

Transport-specific metadata should be preserved when available:

- LAN: endpoint path, peer address class, TLS status, and local interface.
- WAN MQTT: broker host, port, topic, QoS, TLS status, and subscription pattern.
- LoRa/LoRaWAN: gateway id, radio band/region, RSSI, SNR, spreading factor,
  packet counter, gateway timestamp, and last-heard location metadata when
  available.

Ingress preservation is not the same as runtime admission. A preserved message
may remain raw evidence forever if its format is unknown, malformed, too stale,
too large, unsigned, or outside the active Scout mission context. Promotion to
Scout runtime observation requires a later adapter decision and, for live runtime
use, the signed Scout observation/envelope contract.

Status/admin surfaces should show ingress summaries and artifact paths, but must
not embed raw payload values, health values, location traces, MQTT passwords,
LoRa session keys, HMAC secrets, access tokens, or private broker credentials.

## Scout Observer v0

The first Scout receiver is a Sensor Logger MQTT observer, not a safety
ingester.

Observer responsibilities:

- connect to the configured MQTT broker using TLS when crossing WAN;
- subscribe to one or more Sensor Logger-compatible topics;
- parse JSON message bodies;
- preserve every accepted raw message as JSONL evidence;
- compute a payload SHA-256 for each raw message;
- summarize `messageId`, `sessionId`, `deviceId`, topic, payload size, sensor
  names, and received time;
- detect `messageId` gaps, duplicates, and out-of-order messages per
  `deviceId + sessionId`;
- expose a status JSON file for admin/debug surfaces;
- never print or persist MQTT passwords, HMAC secrets, or access tokens.

The observer should keep raw evidence and normalized status separate. The raw
JSONL file is for replay/audit. The status file is for admin surfaces and should
remain summary-only.

## Android and Future Clients

Android support should not start by inventing a new Scout-only payload. The
first Android client should publish the same v0 message body:

```json
{
  "messageId": 1,
  "sessionId": "android-session",
  "deviceId": "android-device",
  "payload": [
    {
      "name": "accelerometer",
      "time": 1780555780517000000,
      "values": {"x": 0.1, "y": 0.2, "z": 0.3}
    }
  ]
}
```

Platform-specific differences belong inside `payload[].name` and
`payload[].values`, not in the outer Scout session envelope. If a platform
needs additional identity, permission, or quality metadata, it should add a
versioned `metadata` object while preserving the required v0 fields.

## Boundary

This spec is evidence-only until a later, explicit runtime/safety bridge is
approved.

The MQTT observer must not:

- call `/safety/*`;
- send SOS, SMS, satellite, e-mail, webhook, or incident notifications;
- mutate Phase 1 L0-L4 safety state;
- write Phase 2 Brain facts;
- claim medical diagnosis or medical-grade monitoring;
- treat provider values as Scout truth;
- expose raw payloads or credentials in status/admin summaries.

Boundary fields in observer status should include:

```json
{
  "evidence_only": true,
  "medical_diagnosis": false,
  "phase1_runtime_safety_truth": false,
  "phase1_l0_l4_state_mutated": false,
  "safety_api_called": false,
  "phase2_brain_writeback": false,
  "assistant_safety_mutation_allowed": false
}
```

## Acceptance Criteria

Scout mobile/wearable v0 is accepted when:

- the spec exists and names Sensor Logger MQTT as the canonical v0 reference
  format;
- shared `IngressEvidenceRecord` and `IngressEvidenceIndex` models preserve LAN,
  WAN/MQTT, and LoRa/LoRaWAN ingress before runtime admission;
- the observer can parse Sensor Logger MQTT message bodies;
- raw accepted messages are written to an evidence JSONL file;
- status JSON records message counts, active devices, sessions, sensor names,
  message gaps, duplicates, and out-of-order counts;
- the observer has focused tests for valid messages, test-publish messages,
  invalid JSON, gap detection, and boundary fields;
- no observer code imports or calls `/safety/*`;
- no MQTT credential is committed into docs, tests, or status artifacts.
