# Spec: Scout Mobile/Wearable Sensor Ecosystem v0

Date: 2026-06-04

## Objective

Scout needs a first ecosystem contract for phones, wearable devices, Scout
servers, and field gateways that can exchange live sensor, location, status, and
emergency evidence.

The v0 inbound reference path is:

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
transport path. Scout must keep transport services independent from sensor
normalization, application routing, filter/agent execution, journey-record
export, and runtime safety admission. Transport services are bidirectional:
they can receive evidence and send authorized envelopes to clients, peer Scout
server nodes, gateways, or emergency/SAR recipients.

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

## Captured Requirements from 2026-06-05 Scout Client Discussion

The immediate objective is not a polished Apple app. The immediate objective is
to prove a Scout client path that can move real iPhone/Apple Watch sensor data
into Scout while preserving evidence boundaries.

Thread-derived requirements:

- Use real device data for live testing. If a third-party app can publish live
  iPhone/Apple Watch telemetry now, prefer it over simulated data for the first
  Scout observer tests.
- Sensor Logger Pro MQTT Publishing is the current reference live tester because
  it can publish iPhone/Apple Watch motion, location, pedometer, battery,
  barometer, and heart-rate-like wearable evidence to a broker.
- Health Auto Export / Apple Health exports do not need to be live for v0.
  Health summaries may be prepared in pre-trip or admin workflows as batch JSON,
  CSV, GPX, REST, or MQTT-exported evidence. They must not block the live sensor
  ingress milestone.
- A Scout-native iOS/watchOS client remains the future target, but its first
  prototype should preserve the Sensor Logger v0 outer envelope before adding
  richer Scout-specific identity, bidirectional commands, or safety affordances.
- The Scout-native Apple client can start as a bare operational UI with connection status, broker/topic configuration, permission status, recording state, and evidence upload state. It should not begin by implementing medical diagnosis or Phase 1 safety mutation.
- Live Scout testing should focus on motion/location/PDR/vitals ingress first.
  Apple Health historical aggregates belong in pre-trip/admin preparation unless
  a later runtime requirement explicitly promotes them.
- The same source-adapter contract must be usable by future Android, Scout iOS,
  Scout watchOS, gateway, LoRa, and satellite adapters. The transport may
  change, but the normalized record and safety admission gates must remain
  transport-independent.

中文註釋：第一階段不是做漂亮的 Apple app，而是先證明真裝置資料可以 live 進
Scout。健康資料可以先做 pre-trip/admin batch evidence；真正需要 live 的是
Sensor Logger 這類 motion/location/PDR/wearable telemetry。

## Layering Model

Scout mobile/wearable sensing is split into seven layers:

1. Bidirectional transport service layer
   - Receives bytes/messages from HTTP, WebSocket, TCP streams, Bluetooth/BLE,
     MQTT, LoRa/LoRaWAN, satellite, or future transports.
   - Sends already-authorized outbound envelopes over the same transport family
     when the application/safety layers request it.
   - Preserves raw ingress evidence, egress evidence, transport metadata,
     receive/send timestamps, payload hashes, identity metadata, parse status,
     delivery state, and retry state.
   - Does not decide route semantics, safety level, or emergency content.
   - May enforce transport-level policy such as credential scope, rate limits,
     retry limits, queue durability, and destination allowlists.

2. Source adapter layer
   - Parses source-specific payloads such as Sensor Logger, Scout iOS, Scout
     Android, Garmin export, Apple Health export, BLE peripherals, LoRa beacons,
     or satellite check-ins.
   - Converts readings into provider-neutral sensor observations and routing
     hints.
   - Preserves source provenance and data-quality limitations.

3. Application router layer
   - Receives normalized observations, hardware events, forecasts, status
     messages, or already-admitted application envelopes.
   - Dispatches each message to one or more registered filters, modules,
     skills, agents, or the raw archive path.
   - Routes IMU/PDR/GPS/wheel evidence to navigation filters such as INS/DR.
   - Routes health/resource evidence to modules such as Energy Reserve.
   - Routes SOS triggers, beacon broadcasts, and last-heard relay messages to
     modules such as Beacon Tracer.
   - Routes weather forecasts or weather alerts to weather-risk agents such as
     a Pydantic AI camp/avoid-rain advisor.
   - Preserves route decisions, route-table version, match reasons, fan-out,
     and dispatch status.
   - Does not perform sensor fusion, health interpretation, incident
     declaration, or safety-level selection by itself.

4. Application filter/agent layer
   - Hosts registered filters/modules/agents such as `navigation.ins_dr`,
     `resource.energy_reserve`, `beacon.tracer`, `weather.route_advisor`, and
     `raw.archive`.
   - `navigation.ins_dr` consumes routed location + PDR/IMU/wheel evidence and
     produces INS/DR estimates, route progress, confidence, degradation reasons,
     and re-anchor corrections.
   - Each target declares input schemas, output schemas, side-effect policy,
     safety boundary, and allowed outbound envelope classes.
   - AI-backed targets use explicit Scout skills and constrained agents. They
     return typed candidates, advisories, or summaries, not direct safety
     mutations.

5. Scout Sensor/Vitals Record layer
   - Stores normalized sensor, location, PDR, battery, environment, and life
     sign observations, router decisions, and filter outputs in a Scout-owned
     record format.
   - Provides deterministic export to GPX, KML, CSV, and future formats.
   - Keeps raw private payloads separate from admin summaries.

6. Safety admission layer
   - Decides whether normalized navigation/resource evidence is eligible for
     Phase 1 runtime evaluation.
   - Applies uncertainty, persistence, map confidence, route-corridor, and
     terrain-risk gates before the L0-L4 state machine can react.

7. Admin visualization/export layer
   - Presents journey path, GPS-only path, INS/DR path, no-good-GPS coverage,
     re-anchor corrections, and export files for human review.
   - `trajectory_diff_map.html` belongs here. It is an admin view, not the
     canonical journey record.

中文註釋：MQTT、HTTP、TCP、Bluetooth、LoRa、衛星都只是 transport service。它們
可以收資料，也可以送位置、ack、緊急封包或 peer relay 封包；但 Scout 真正要穩定
的是 transport-independent 的 router、filter/agent registry、sensor/vitals record、
outbound envelope，以及進入 safety 前的 admission gate。INS/DR 只是其中一個
navigation filter，不是整個 application layer。

## Application Router And Filter Registry

The Scout application layer is not INS/DR. INS/DR is one registered filter
behind an application router.

The router consumes normalized envelopes from the source adapter layer. A single
envelope may be dispatched to multiple targets, or to no filter at all when it
should remain raw evidence only.

Required route targets for v0 planning:

- `navigation.ins_dr`: IMU, PDR, GPS/location, wheel odometry, barometer, heading,
  and route context. Output is navigation estimate evidence such as GPS-only,
  INS/DR, route-constrained DR, uncertainty, degradation reasons, and re-anchor
  metadata.
- `resource.energy_reserve`: heart rate, HRV, battery, exertion, sleep/recovery
  exports, activity summaries, and other life-sign/resource evidence. Output is
  baseline-relative resource/advisory evidence, not medical diagnosis and not
  Scout safety truth.
- `beacon.tracer`: hardware SOS, user distress triggers, beacon broadcasting,
  LoRa last-heard packets, black-box heartbeat state, and peer relay evidence.
  Output is beacon trace state, relay candidates, and emergency envelope
  candidates subject to policy/admission.
- `weather.route_advisor`: weather forecast, radar/nowcast summaries, typhoon or
  heavy-rain alerts, temperature/wind risk, and route timing context. Output is a
  typed weather-risk advisory candidate, such as camp/avoid-rain/watch-window,
  validated by Pydantic AI or an equivalent typed agent contract.
- `raw.archive`: stores normalized or unrecognized evidence without applying an
  application filter.

Router rules must be declarative and versioned, not hidden in transport adapter
code. A route rule should declare:

- `route_id` and `router_version`;
- input selectors such as observation name, event class, source adapter,
  capability tag, mission context, and safety boundary;
- target filter/module/skill/agent id;
- fan-out behavior and priority;
- idempotency/dedupe key;
- timeout and retry policy;
- allowed side effects and outbound envelope classes;
- output contract and record target;
- operator/policy gate for enabling the route.

Every dispatch should preserve a summary record with:

- `router_version`;
- `route_id`;
- `route_target`;
- `match_reason`;
- `dispatch_status`: `accepted`, `blocked`, `deferred`, `failed`, or
  `raw_archive_only`;
- `input_ref`;
- `output_ref`;
- `side_effect_policy`;
- `agent_skill_ref` when an AI skill/agent handled the message;
- `credential_value_exposed=false`.

Skill + agent extension model:

- A `ScoutApplicationSkill` is a declarative capability package: input schema,
  output schema, examples, validation rules, policy boundaries, test fixtures,
  and allowed tools/transports.
- A `ScoutApplicationAgent` executes a registered skill under router policy. It
  may use Pydantic AI or another typed runtime, but it must return validated
  Scout records or candidates.
- Runtime dispatch should remain deterministic and auditable. AI may classify or
  summarize inside a registered target, and may help propose route-table changes
  for admin review, but the live router must not become an unconstrained
  free-form planner.
- The v0 INS/DR routing selectors live in the
  `ins-dr-wearable-route-constrained` skill manifest. Its routing agent reads
  selectors such as `observation_names`, `value_keys`, `value_key_groups`, and
  `capability_tags`; for example, a payload with `acc_x`, `acc_y`, and `acc_z`
  can be routed to `navigation.ins_dr` without a transport bridge hard-coding
  accelerometer field names.
- Agent output must not directly select Ln, mutate `/safety/*`, or send outbound
  emergency packets unless a separate safety admission or operator policy
  envelope authorizes that action.

### High-Rate Pipeline Versus Skill Router

Scout should use two routing lanes:

- **High-rate pipeline lane**: deterministic, bounded, and batch-oriented. Use
  this for continuous IMU, PDR, wheel encoder, barometer, heading, and frequent
  GNSS/location updates. The pipeline may still be selected by a skill manifest,
  but per-sample processing must not call an AI agent or rewrite full status
  JSON for every sample. It should use in-memory buffers, bounded queues,
  backpressure, sample coalescing, and periodic JSONL batch evidence.
- **Flexible skill-router lane**: versioned and inspectable. Use this for
  low-rate health/resource summaries, SOS/beacon state, weather/advisory
  messages, device status, unknown future payloads, and admin-reviewed route
  table changes.

Recommended v0 split:

| Message class | Typical rate | Required lane | Notes |
| --- | ---: | --- | --- |
| Accelerometer / gyro / motion samples | 10-100 Hz | High-rate pipeline | Batch or decimate before evidence writes and admin views. |
| Wheel encoder ticks | 10-200+ Hz | High-rate pipeline | Convert to odometry deltas before router-visible records. |
| PDR / step distance | 1-5 Hz | High-rate pipeline | Safe for route-constrained DR; still avoid per-sample AI. |
| GNSS / location | 1-10 Hz | Pipeline when continuous, skill-router when sparse | Keep raw fixes, but coalesce for INS/DR when needed. |
| Heart rate / battery / resource summary | 0.1-1 Hz | Skill-router | Flexible interpretation is more valuable than raw rate. |
| SOS / beacon / last-heard / black-box heartbeat | event to 1 Hz | Skill-router plus priority queue | Must not be delayed behind IMU backlog. |
| Weather / forecast / advisory | minutes to hours | Skill-router / typed agent | Good fit for Pydantic AI or equivalent typed agent. |

The route selector can still come from a skill such as
`ins-dr-wearable-route-constrained`, but a rule whose expected input rate is
above the current benchmark budget should enqueue into a pipeline rather than
run the full skill-router dispatch path for every sample.

Benchmarking requirement:

- Run `tools/application_router_benchmark.py` on the target Scout runtime when
  pydantic and the full router dependencies are installed.
- Run `tools/application_router_microbench_standalone.py` on constrained Scout
  deployments when only stdlib Python is available.
- For live MQTT/Sensor Logger runs, record the latency chain from MQTT receive
  time and Sensor Logger package time to application routing completion. The
  observer writes this as `sensorlogger_mqtt_latency.jsonl` and exposes the
  rolling summary in `sensorlogger_mqtt_status.json`.
- Use MQTT message-id gaps, duplicate IDs, out-of-order IDs, p95 routing
  latency, and queue growth to decide when a publish rate is no longer stable.
  Package loss is not inferred from latency alone.
- Optional OLED feedback may show throttled diagnostic summaries such as latest
  message id, receive-to-route latency, sensor-to-route latency, inferred Hz,
  and loss count. OLED output is diagnostic display only and must not affect
  safety state or send outbound traffic.
- Treat the 20% throughput budget as the safe continuous operating envelope for
  high-rate planning; reserve the remaining headroom for sensor bursts, JSONL
  flushes, safety admission, UI/debug, and radio work.
- Record p50, p95, max latency, message rate, payload size, route target, and
  whether recorder/status writes were enabled. A rate is not accepted as stable
  if p95 latency exceeds the sample period or if queues grow during a soak.

中文註釋：transport 把資料送進 Scout 後，先由 source adapter 正規化，再交給
application router。router 依照可版本化的 route table 派發：IMU/PDR/GPS 給
`navigation.ins_dr`，health 給 `resource.energy_reserve`，SOS/beacon 給
`beacon.tracer`，天氣預報給 `weather.route_advisor`，也可以完全不進 filter 而
只進 `raw.archive`。AI 可以透過 skill + agent 做 typed 分析，但不能自由改安全
狀態或自行發送緊急封包。

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

## Transport Service Roles

Scout supports multiple transport roles:

- HTTP: local lab, same Wi-Fi, iPhone hotspot, gateway upload, and high-bandwidth
  debugging. It can also serve client pull endpoints for latest status, latest
  position, and admin-reviewed journey exports.
- WebSocket: local or WAN streaming when a persistent IP connection is available.
  It can send live acknowledgements, control responses, and telemetry streams
  back to a client.
- TCP stream: gateway-to-Scout or device-to-Scout stream when a controlled
  network path exists. It can be bidirectional for low-latency gateway relay.
- Bluetooth/BLE: short-range phone/watch/peripheral ingestion and local bridge
  mode. It can send local prompts, latest Scout state, or short emergency status
  back to a paired phone/watch when the client supports it.
- MQTT: WAN live path because phones and Scout field devices can both make
  outbound broker connections without public inbound IP addresses. It can also
  publish Scout status, last-known location, emergency beacon packets, and peer
  relay messages to authorized topics.
- LoRa/LoRaWAN: low-rate nearby/off-grid fallback for check-ins, last-heard
  evidence, team beacons, and sparse PDR/location summaries. It is not a
  high-rate wearable stream transport. It can transmit compact distress,
  last-known-position, and team relay packets.
- Satellite message: very low-rate future fallback for emergency check-ins,
  last-known summaries, and incident package hints. It is not a continuous
  wearable stream transport. It can send high-priority black-box summaries when
  terrestrial transport is unavailable.

Release-bound Scout deployments should use a Scout-owned or Scout-controlled
MQTT broker. Public test brokers are only for protocol smoke tests and must not
carry real location, heart-rate, or participant data.

Normative broker ownership: Scout-owned or Scout-controlled MQTT broker before
release.

Network and broker requirements captured from the 2026-06-05 discussion:

- LAN HTTP/WebSocket/TCP is acceptable for same-Wi-Fi, phone hotspot, or local
  gateway coverage.
- Public IPv4, floating public IP, router port forwarding, or dynamic DNS can
  support local lab HTTP servers, but this is not a scalable release model for
  many Scout hosts.
- WAN live testing should use MQTT because both phones and Scout devices can
  make outbound broker connections without requiring every Scout host to expose
  an inbound public IP address.
- Sensor Logger currently publishes MQTT over WebSocket/TLS in the tested setup;
  Scout must support WebSocket/TLS broker URLs for this source adapter.
- Public/free brokers are allowed only for protocol smoke tests. Release-bound
  Scout deployments require a Scout-owned or Scout-controlled MQTT broker,
  identity policy, topic policy, credential rotation, and audit logging.
- MQTT is not only an upload channel. Future Scout clients need bidirectional communication for status, command, acknowledgement, safety-reporting coordination, and cross-client interop. That bidirectional path must still preserve safety-admission boundaries.
- LoRa or LoRaWAN gateways are a nearby/off-grid option for sparse check-ins,
  last-heard evidence, and low-rate summaries. They are not a substitute for
  high-rate wearable streaming.

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

## Egress Evidence Preservation

Transport services may transmit Scout-generated envelopes, but they must
preserve egress evidence just as carefully as ingress evidence.

Outbound content is never invented by the transport service. It must come from a
signed or otherwise authorized application-layer envelope such as:

- client acknowledgement;
- stream control response;
- latest position/status response;
- peer Scout server relay packet;
- team beacon;
- last-known-position beacon;
- emergency/SAR packet;
- incident package hint or retrieval pointer;
- black-box heartbeat packet.

Required egress evidence fields:

- `egress_transport`: `lan_http`, `lan_websocket`, `lan_tcp_stream`,
  `short_range_bluetooth`, `wan_mqtt`, `lora_gateway`, `satellite_message`, or
  a later versioned value.
- `destination_class`: `client`, `peer_scout_server`, `gateway`,
  `team_member`, `sar_recipient`, `operator_console`, or a later value.
- `source_service`: transport service name.
- `message_class`: `ack`, `status`, `position_beacon`, `team_beacon`,
  `emergency_packet`, `incident_hint`, `black_box_heartbeat`, or a later value.
- `queued_at` and optional `sent_at`.
- `payload_sha256` of the exact envelope bytes/text.
- `delivery_status`: `queued`, `sent`, `acked`, `failed`, `expired`, or
  `blocked`.
- `retry_count` and retry policy id.
- `authorization_ref`: operator, safety-admission, or runtime-policy ref that
  allowed this send.
- `raw_artifact_path` or envelope artifact path.
- `credential_value_exposed`: always `false`.

Egress preservation must not embed private health values, precise full tracks,
credentials, HMAC secrets, session keys, or raw incident details in summary
status. High-priority emergency envelopes may carry location and status, but the
summary/status view should still show only bounded previews, hashes, delivery
state, and refs.

## Black-Box Beacon And Peer Relay

Scout's transport services must support a black-box style communication role for
distress search and post-incident recovery.

When the application/safety layer has admitted an emergency or black-box beacon,
transport services may repeatedly send compact packets containing:

- latest reliable or admitted estimated position;
- timestamp and sequence number;
- route/session/device refs;
- current safety level or emergency class;
- battery/signal summaries;
- incident/package refs or retrieval hints;
- short status text approved by policy;
- signature/HMAC or other authenticity proof when available.

Supported destinations include:

- paired phone/watch/client;
- nearby Scout gateway;
- another Scout server/node;
- LoRa team relay;
- MQTT broker topic;
- satellite message relay;
- SAR/operator recipient.

The transport service owns:

- queue durability;
- retry/backoff;
- dedupe and sequence tracking;
- delivery receipts when available;
- per-transport packet-size reduction;
- destination failover;
- peer relay forwarding;
- status projection for admin/debug.

The transport service does not own:

- deciding that an incident exists;
- selecting safety level Ln;
- deciding who is allowed to receive private details;
- creating raw health/location content;
- overriding safety admission or operator policy.

中文註釋：失事尋找時，Scout transport service 可以像黑盒子一樣持續發送位置與
緊急資訊封包，也可以送到另一個 Scout server/node 代為 relay。但它送的是已經由
application/safety admission 產生和授權的 envelope，不是 transport 自己判斷
墜崖、離線或 SOS。

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
- write normalized Sensor/Vitals records to
  `sensorlogger_mqtt_sensor_vitals_records.jsonl` for replay, export, and
  downstream filters;
- detect `messageId` gaps, duplicates, and out-of-order messages per
  `deviceId + sessionId`;
- expose a status JSON file for admin/debug surfaces;
- never print or persist MQTT passwords, HMAC secrets, or access tokens.

The observer should keep raw evidence and normalized status separate. The raw
JSONL file is for replay/audit. The status file is for admin surfaces and should
remain summary-only.

The live observer file
`sensorlogger_mqtt_sensor_vitals_records.jsonl` is the MQTT adapter's admin/debug
projection of Sensor/Vitals observations. In a packaged journey bundle the same
record family is normalized into `observations.jsonl`.

Operational requirements:

- The observer should run automatically in the Scout admin runtime when
  configured. Operators should not need to manually start a one-off MQTT receive
  command after the Scout server is already running.
- `/health` or an equivalent admin status endpoint should expose observer
  configured/running state, status path, evidence directory, log path, and
  credential-presence booleans without exposing credential values.
- The observer must keep watching in the background even when the debug page is
  closed. Debug UI visibility is not a prerequisite for receiving MQTT or other
  hardware/provider events.
- Debug/admin counters may be reset as projection-only operator state, but raw ingress JSONL evidence and ingress index JSONL must remain available for audit and replay.

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
  application_routes.jsonl
  filter_outputs.jsonl
  navigation_estimates.jsonl
  vitals.jsonl
  transport_ingress_index.jsonl
  transport_egress_index.jsonl
  exports/
    journey.gpx
    journey.kml
    journey.csv
    sensor_samples.csv
```

`manifest.json` should include:

- participant/device/session identifiers as redacted refs or hashes;
- source adapters and transport adapters used;
- application router version and enabled route-table refs;
- registered filter/skill/agent versions used;
- route context and map context refs;
- privacy policy and raw-payload retention policy;
- data quality summary;
- safety admission policy version;
- export checksums.
- outbound/black-box service policy refs when egress packets were produced.

`observations.jsonl` should include normalized records such as:

- `artifact_kind=scout_sensor_vitals_record` and
  `artifact_version=scout_sensor_vitals_record.v0`;
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

`application_routes.jsonl` should include router decisions such as:

- router_version and route_id;
- route_target;
- match_reason;
- dispatch_status;
- input_ref and output_ref;
- side_effect_policy;
- agent_skill_ref when an AI skill/agent handled the message;
- credential_value_exposed=false.

`filter_outputs.jsonl` should include non-navigation filter outputs such as:

- Energy Reserve resource/advisory evidence;
- Beacon Tracer state, relay candidates, and emergency envelope candidates;
- weather-risk advisory candidates from Pydantic AI or equivalent typed agents;
- raw/archive-only decisions;
- output confidence, uncertainty, policy refs, and suppression reasons.

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
