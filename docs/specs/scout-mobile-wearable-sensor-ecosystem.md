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

Transport is not the application layer. MQTT is only the first proven WAN
ingress path. Scout must keep transport adapters independent from sensor
normalization, INS/DR navigation, journey-record export, and runtime safety
admission.

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

## Layering Model

Scout mobile/wearable sensing is split into six layers:

1. Transport ingress layer
   - Receives bytes/messages from HTTP, WebSocket, TCP streams, Bluetooth/BLE,
     MQTT, LoRa/LoRaWAN, satellite, or future transports.
   - Preserves raw evidence, transport metadata, receive timestamp, payload
     hash, identity metadata, and parse status.
   - Does not know Scout route semantics and does not make safety decisions.

2. Source adapter layer
   - Parses source-specific payloads such as Sensor Logger, Scout iOS, Scout
     Android, Garmin export, Apple Health export, BLE peripherals, LoRa beacons,
     or satellite check-ins.
   - Converts readings into provider-neutral sensor observations.
   - Preserves source provenance and data-quality limitations.

3. Scout Sensor/Vitals Record layer
   - Stores normalized sensor, location, PDR, battery, environment, and life
     sign observations in a Scout-owned record format.
   - Provides deterministic export to GPX, KML, CSV, and future formats.
   - Keeps raw private payloads separate from admin summaries.

4. Navigation estimation layer
   - Consumes normalized location + PDR/IMU/wheel evidence.
   - Produces INS/DR estimates, route progress, confidence, degradation reasons,
     and re-anchor corrections.

5. Safety admission layer
   - Decides whether normalized navigation/resource evidence is eligible for
     Phase 1 runtime evaluation.
   - Applies uncertainty, persistence, map confidence, route-corridor, and
     terrain-risk gates before the L0-L4 state machine can react.

6. Admin visualization/export layer
   - Presents journey path, GPS-only path, INS/DR path, no-good-GPS coverage,
     re-anchor corrections, and export files for human review.
   - `trajectory_diff_map.html` belongs here. It is an admin view, not the
     canonical journey record.

中文註釋：MQTT、HTTP、TCP、Bluetooth、LoRa、衛星都只是 transport。Scout 真正要
穩定的是 transport-independent 的 sensor/vitals record、INS/DR navigation estimate，
以及進入 safety 前的 admission gate。

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

## Transport Layer Roles

Scout supports multiple transport roles:

- HTTP: local lab, same Wi-Fi, iPhone hotspot, gateway upload, and high-bandwidth
  debugging.
- WebSocket: local or WAN streaming when a persistent IP connection is available.
- TCP stream: gateway-to-Scout or device-to-Scout stream when a controlled
  network path exists.
- Bluetooth/BLE: short-range phone/watch/peripheral ingestion and local bridge
  mode.
- MQTT: WAN live path because phones and Scout field devices can both make
  outbound broker connections without public inbound IP addresses.
- LoRa/LoRaWAN: low-rate nearby/off-grid fallback for check-ins, last-heard
  evidence, team beacons, and sparse PDR/location summaries. It is not a
  high-rate wearable stream transport.
- Satellite message: very low-rate future fallback for emergency check-ins,
  last-known summaries, and incident package hints. It is not a continuous
  wearable stream transport.

Release-bound Scout deployments should use a Scout-owned or Scout-controlled
MQTT broker. Public test brokers are only for protocol smoke tests and must not
carry real location, heart-rate, or participant data.

Normative broker ownership: Scout-owned or Scout-controlled MQTT broker before
release.

## Ingress Evidence Preservation

Scout must preserve ingress evidence before deciding whether a message can be
normalized, admitted, replayed, or promoted.

This rule applies to every mobile/wearable ingress path:

- LAN HTTP, WebSocket, or TCP stream from a nearby phone, tablet, laptop, or
  local gateway.
- Bluetooth/BLE from a paired phone, watch, or peripheral.
- WAN MQTT from Sensor Logger, Scout-native clients, broker bridges, or cloud
  relays.
- LoRa or LoRaWAN gateway messages, including low-rate check-ins, last-heard
  beacons, team beacons, and radio metadata.
- Satellite message relays, including sparse emergency or last-known summaries.

Required ingress evidence fields:

- `ingress_transport`: `lan_http`, `lan_websocket`, `lan_tcp_stream`,
  `short_range_bluetooth`, `wan_mqtt`, `lora_gateway`, `satellite_message`, or
  a later versioned value.
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
- TCP stream: peer address class, TLS status, framing mode, keepalive status,
  and stream sequence.
- Bluetooth/BLE: local device id, service UUID, characteristic UUID, pairing
  state, RSSI, and bridge device id.
- WAN MQTT: broker host, port, topic, QoS, TLS status, and subscription pattern.
- LoRa/LoRaWAN: gateway id, radio band/region, RSSI, SNR, spreading factor,
  packet counter, gateway timestamp, and last-heard location metadata when
  available.
- Satellite: provider class, message id, received-at timestamp, message length,
  retry/delay metadata, and whether the content is a full observation or a
  summary.

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

## Scout Sensor/Vitals Record

Scout needs a dedicated journey sensor record, analogous in role to Garmin FIT
but owned by Scout and shaped around wilderness safety evidence. This record is
not `trajectory_diff_map.html`; the HTML map is an admin visualization generated
from the record.

Working name:

```text
Scout Sensor/Vitals Record
file family: .scout-svr
artifact_kind: scout_sensor_vitals_record
artifact_version: scout_sensor_vitals_record.v0
```

The preferred v0 storage shape is a bundle directory or archive:

```text
journey.scout-svr/
  manifest.json
  observations.jsonl
  navigation_estimates.jsonl
  vitals.jsonl
  transport_ingress_index.jsonl
  exports/
    journey.gpx
    journey.kml
    journey.csv
    sensor_samples.csv
```

`manifest.json` should include:

- participant/device/session identifiers as redacted refs or hashes;
- source adapters and transport adapters used;
- route context and map context refs;
- privacy policy and raw-payload retention policy;
- data quality summary;
- safety admission policy version;
- export checksums.

`observations.jsonl` should include normalized records such as:

- timestamp and monotonic sequence;
- source timestamp and receive timestamp;
- location lat/lon/altitude/horizontal accuracy;
- PDR distance, step count, cadence, and source confidence;
- accelerometer, gyroscope, barometer, magnetometer, heading, battery, and
  environment samples when available;
- heart rate, HRV, SpO2, respiration, temperature, or other life signs when
  available;
- provenance fields: source_provider, source_adapter, ingress_transport,
  raw_evidence_refs, payload_sha256;
- data-quality fields and calibration flags.

`navigation_estimates.jsonl` should include:

- GPS-only position sample when available;
- INS/DR route-constrained estimate;
- confidence and uncertainty;
- `degraded` and `degradation_reasons`;
- `gps_reanchor_correction_m`;
- route index/progress;
- comparison fields between GPS-only and INS/DR when both are available.

Export rules:

- GPX export: journey path and optional track extensions for confidence,
  source, and accuracy.
- KML export: admin/map visualization layers, including GPS-only and INS/DR
  overlays.
- CSV export: analysis-friendly tables for location, INS/DR, vitals, and sensor
  samples.
- HTML map export: admin user view only; it should read from record/export data
  and show GPS-only and INS/DR lines overlaid for accuracy comparison.

The record should support multiple tracks in one journey:

- `gps_only_track`
- `ins_dr_track`
- `weak_gps_pdr_track`
- `route_constrained_track`
- `admin_reference_track`

This allows Scout to show exactly where INS/DR improved the path, where it
diverged from GPS, and where evidence quality is too low for runtime safety use.

## INS/DR Safety Admission

INS/DR + GPS estimates may eventually feed Scout safety. This is important
because narrow mountain trails, cliffs, river crossings, landslide edges, and
steep terrain can make a small localization error look like a serious route or
fall hazard.

However, raw INS/DR output must not directly trigger Ln by itself. The safety
admission layer must evaluate whether an estimate is eligible for route-risk
and hazard-risk decisions.

Required gates before INS/DR can influence Ln:

- active mission route and map context are loaded;
- source is not only raw transport ingress;
- estimate is anchored or recently re-anchored to reliable location;
- horizontal accuracy / uncertainty is within the policy threshold for the
  terrain class;
- DR elapsed time and DR distance since anchor are below policy limits;
- route/map matching distance and confidence are available;
- degradation reasons are understood and not safety-blocking;
- the signal persists across multiple samples or a minimum duration;
- the hazard decision includes hysteresis to avoid single-sample flips;
- narrow-trail margin policy is applied before cliff/off-route escalation.

Recommended narrow-trail safety rule:

```text
Do not escalate to cliff/fall/off-route Ln from a single INS/DR or GPS sample
when the estimated uncertainty radius overlaps the legal/safe trail corridor.
Escalate only after persistent deviation, high-confidence map hazard overlap,
or corroborating evidence such as sustained heading/progress conflict,
barometric drop, accelerometer impact, user distress signal, or missed
checkpoint.
```

Safety event details must preserve:

- GPS-only position;
- INS/DR position;
- uncertainty radius;
- route corridor distance;
- map/hazard overlap;
- number of consecutive samples;
- duration of the condition;
- source track refs from the Scout Sensor/Vitals Record;
- reason why the event was admitted or suppressed.

中文註釋：INS + GPS 的結果未來可以觸發 Scout safety，但不能裸奔進 L0-L4。窄小
登山徑上，單點 GPS/INS 偏移可能誤判成墜崖或離線，所以要先經過 uncertainty、
持續時間、地圖可信度、corridor overlap、re-anchor freshness、barometer/IMU 等
多重 admission gate。

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
