# Spec: Phase 4.6 Real Device Continuous Stream

Date: 2026-05-21

## Objective

Phase 4.6 moves Scout from signed sample stream admission to real Apple Watch /
mobile continuous stream readiness.

This is one input surface for the on-trip safe-device loop defined in
`docs/specs/scout-closed-loop-operating-cycle.md`. Real device streams can feed
plan-node check-ins, hardware/software state, wearable/body-load cues, and
communication readiness evidence, but they do not by themselves approve
departure, send SOS/incident reports, or mutate Phase 2 Brain facts.

The mobile/wearable ecosystem contract that fixes Sensor Logger MQTT as Scout's
canonical v0 reference wire format is owned by
`docs/specs/scout-mobile-wearable-sensor-ecosystem.md`. This Phase 4.6 spec
keeps the Apple Watch/iPhone runtime semantics, while the ecosystem spec owns
the cross-client MQTT payload and topic contract that future Android and
Scout-native clients should follow.

中文註釋：這個 milestone 的目標是讓真裝置連續串流有明確身份、簽章、排序、
重送、限流與 operator control 語意。它不是 field mission 自動出發，也不是
SOS / SMS / satellite / incident bridge live send 的啟用。

Success means a real Apple Watch or mobile client can use the existing
`/runtime/streams/*` surface with a versioned contract that is testable before
any long field run:

- device identity is explicit and bound to `source_id`, `source_kind`,
  `device_id`, token scope, and HMAC secret ref;
- each payload is signed with HMAC-SHA256 and verified before runtime
  processing;
- sequence and dedupe behavior is deterministic per `source_id + device_id`;
- cadence above 10 Hz is backpressured before `SafetyRuntimeSession.observe`;
- offline retry keeps bounded queue state and falls back to latest point after
  retry exhaustion;
- operator pause/resume applies to Scout server-side admission, not device
  hardware;
- status and evidence artifacts remain summary-only and do not expose secrets
  or raw payloads.

## Apple Scout Client v0

The first Apple platform milestone is an Apple Scout Client, not a safety
notification feature.

Client topology:

- Apple Watch is the primary live sensor collector.
- iPhone is the Scout network bridge, signer, queue owner, and operator-visible
  control surface.
- Scout receives the stream as an evidence-only Apple client observation channel
  before any runtime/safety bridge is enabled.
- Future Scout interoperability can map accepted Apple observations into
  `/runtime/streams/*` or `/safety/*` only after an operator-controlled runtime
  handoff and source-policy match.

Initial Scout endpoint candidate:

- `POST /clients/apple/observations`
- `GET /clients/apple/status`

The endpoint pair is intentionally separate from `/safety/*`. It lets the
client prove real Watch/iPhone capture, authentication, buffering, and Scout
receipt before the safety reporting path is reopened.

中文註釋：第一步是 Apple Scout Client 能把 Apple Watch 端的健康與感測資訊即
時送回 Scout，Scout 先把它當 evidence stream。Safety 通報、SOS、SMS、衛星或
incident bridge 都是之後的互通層，不在 v0 自動啟用。

### Source Placement

Apple health exports and Apple sensor streams have different timing contracts:

- Health Auto Export is an admin/pre-trip batch source. It prepares Apple Health
  metrics, workouts, and GPX route evidence before departure or during admin
  review.
- Health Auto Export REST API / MQTT automations are useful for true Apple
  Health provenance, but they are not the live motion stream for Phase 4.6.
- SensorLog and Sensor Logger are the live Apple Watch/iPhone evidence sources
  for Phase 4.6 because they can emit motion, location, pedometer, battery,
  barometer, and heart-rate frames during the trip.
- Third-party live streams are first admitted as local-network
  `operator_live_evidence` unless they can supply the Scout
  `device_id_scoped_token_hmac_signature` envelope.

The first live Scout endpoint should therefore target SensorLog/Sensor Logger
payloads, not Health Auto Export health-metric batches:

- `POST /clients/apple/sensorlog/observations`
- `GET /clients/apple/sensorlog/status`

This endpoint remains evidence-only. It may write an evidence directory and
normalized summary, but it must not call `/safety/*`, change Phase 1 L0-L4
state, send SOS/SMS/satellite messages, or write Phase 2 Brain facts.

Expected live payload shapes:

- SensorLog snapshot rows, as seen in `SensorLogFiles_*`, where each JSON row
  contains fields such as `loggingTime`, `heartRateBPM`,
  `accelerometerAccelerationX`, `motionQuaternionW`, `locationLatitude`,
  `locationLongitude`, `pedometerDistance`, and `batteryLevel`.
- Sensor Logger event rows, as seen in `_62_*.json`, where each JSON row has a
  `sensor` discriminator such as `Gyroscope`, `Accelerometer`,
  `WatchLocation`, `WatchBarometer`, `WristMotion`, or `HeartRate`.

SensorLog snapshot rows can flow through existing SensorLog normalization more
directly. Sensor Logger event rows need a small live frame assembler because
gyro/accelerometer/location/heart-rate events arrive as separate rows.

### Watch Collection

The Watch target should sample only fields that are available through Apple
frameworks and user-granted permissions:

- HealthKit live workout data: heart rate, active energy, distance, workout
  state, workout activity, elapsed time, and available step/cadence summaries.
- Core Motion data: accelerometer, gyroscope, gravity, user acceleration,
  rotation rate, attitude/quaternion, compass/magnetometer when available.
- Barometer data: pressure and relative altitude when `CMAltimeter` is
  available.
- Location route data: latitude, longitude, altitude, speed, course, and
  accuracy only when location permission is granted and the operator enables
  route capture.

The Watch should send compact frames to the iPhone companion using
WatchConnectivity. It must not own Scout credentials, send `/safety/*` requests,
or decide incident reporting.

### iPhone Bridge

The iPhone companion owns Scout-facing behavior:

- binds Watch frames to `source_id`, `source_kind`, `device_id`, `session_id`,
  and monotonic `sequence_no`;
- computes `payload_sha256`;
- signs the envelope with `device_id_scoped_token_hmac_signature`;
- queues frames when Scout is offline;
- enforces the 10 Hz client-side send cap before Scout-side backpressure;
- retains the latest point after retry exhaustion;
- displays Scout reachability, queue depth, last accepted sequence, and whether
  the stream is paused by Scout.

Operator pause/resume from Scout remains server-side admission state. The
iPhone may continue local buffering while paused, but it must display that Scout
is not admitting live observations.

### Observation Envelope

`POST /clients/apple/observations` accepts a signed envelope, not raw HealthKit
exports:

```json
{
  "artifact_kind": "scout_apple_client_observation_envelope",
  "artifact_version": "apple_client_observation_envelope.v0",
  "source_id": "runtime_source.apple_watch.v0",
  "source_kind": "apple_watch",
  "device_id": "apple-watch-local-device-id",
  "session_id": "apple-session-20260604-am",
  "sequence_no": 42,
  "observed_at": "2026-06-04T08:15:30+08:00",
  "monotonic_ms": 1234567,
  "transport": "http_push",
  "payload_sha256": "sha256-of-payload",
  "token_scope": "runtime:observation:write",
  "signature_algorithm": "hmac_sha256",
  "signature": "base64-hmac-signature",
  "payload": {
    "health": {
      "heart_rate_bpm": 142,
      "active_energy_kj": 12.4,
      "distance_m": 85.2,
      "workout_state": "running"
    },
    "motion": {
      "accelerometer_g": {"x": 0.01, "y": 0.02, "z": 0.98},
      "gyroscope_rad_s": {"x": 0.03, "y": 0.01, "z": 0.00},
      "quaternion": {"w": 0.99, "x": 0.01, "y": 0.02, "z": 0.03}
    },
    "location": {
      "latitude": 24.1201,
      "longitude": 121.2841,
      "horizontal_accuracy_m": 8.0,
      "speed_mps": 1.2
    }
  },
  "quality": {
    "sample_cadence_ms": 1000,
    "permissions": ["healthkit", "motion", "location"],
    "missing_fields": []
  },
  "privacy": {
    "raw_health_payload_shared": false,
    "raw_track_shared_to_status": false,
    "status_surfaces_summary_only": true
  },
  "boundary": {
    "evidence_only": true,
    "medical_diagnosis": false,
    "phase1_runtime_safety_truth": false,
    "safety_api_called": false,
    "assistant_safety_mutation_allowed": false
  }
}
```

Scout response summaries may include accepted/rejected counts, last admitted
sequence, queue state, and advisory data-quality notes. They must not echo raw
health payloads, raw tracks, tokens, signatures, or HMAC secrets.

## Non-Goals

- no automatic SOS send;
- no SMS send;
- no satellite send;
- no incident bridge opt-in or remote notification send;
- no assistant safety mutation;
- no Phase 2 Brain writeback;
- no hardware driver invocation;
- no raw Apple Watch/mobile payload storage in committed docs or summary
  artifacts;
- no broad rewrite of Phase 1 route-progress or safety state behavior.

## Device Identity

`RuntimeStreamDeviceIdentity` / 串流裝置身份 is the durable identity Scout uses
to decide whether an envelope belongs to an allowed real source.

Minimum fields:

- `source_id`: versioned stream source, such as
  `runtime_source.apple_watch.v0`;
- `source_kind`: `apple_watch` or `mobile_phone`;
- `device_id`: stable per-device id chosen by the client provisioning flow;
- `display_name`: operator-readable name, not a secret;
- `credential_ref`: metadata-only reference to the scoped token/HMAC material;
- `token_scope`: must be `runtime:observation:write`;
- `hmac_secret_ref`: secret reference such as env/file/keychain path, never the
  secret value;
- `enabled`: disabled identities reject admission before runtime processing.

中文註釋：`device_id` 只能當識別，不能單獨當信任來源。Scout 必須同時檢查
device identity、限定用途 token scope、payload hash 與 HMAC signature。

## Token / HMAC

The first real-device trust model remains
`device_id_scoped_token_hmac_signature`.

- token scope is fixed to `runtime:observation:write`;
- the HMAC secret is resolved outside committed artifacts;
- HMAC-SHA256 signs device id, source id, transport, sequence number,
  observed timestamp, and payload SHA-256;
- signature verification happens before sequence, dedupe, cadence, or runtime
  observation conversion;
- summary responses may expose `credential_ref`, `token_scope`, and
  `signature_algorithm`, but never token or secret values.

## Sequence / Dedupe

Ordering is per `source_id + device_id`.

- sequence numbers must be monotonic for that stream;
- dedupe key is `source_id + device_id + sequence_no + payload_sha256`;
- duplicate dedupe keys reject with `rejected_duplicate`;
- older or equal sequence numbers reject with `rejected_sequence`;
- rejected duplicate/out-of-order payloads do not call
  `SafetyRuntimeSession.observe`.

## 10 Hz Backpressure

The maximum accepted cadence is 10 Hz.

- `max_hz=10.0`;
- `min_interval_ms=100`;
- observations below the interval are marked `queued_backpressure`;
- backpressured observations update queue summaries only and are not forwarded
  into Phase 1 processing in that request;
- status surfaces expose queue depth and counters without raw payloads.

## Offline Retry

Real clients may temporarily lose connectivity.

- disconnected submissions are recorded as `queued_disconnected`;
- retry attempts are bounded by the policy limit, currently five attempts;
- retry metadata is summary-only;
- the device client owns local raw-payload buffering until it reconnects;
- Scout server summaries must not persist raw queued payloads.

## Latest-Point Fallback

After retry exhaustion, Scout retains only the latest point reference for the
stream.

- status becomes `latest_point_retained`;
- stale queued keys for the same `source_id + device_id` are dropped;
- the retained record is a dedupe key / hash reference, not lat/lon payload;
- the fallback is meant to restore situational continuity, not reconstruct the
  full missed track.

## Operator Pause / Resume

Operator controls are server-side admission controls.

- `pause` rejects new HTTP push/WebSocket observations with
  `runtime_stream_paused`;
- `resume` allows new observations after the control state returns to
  `observing`;
- `end` is terminal for the server-side stream;
- `drain-queue` clears disconnected/backpressure/latest-retained summaries but
  preserves dedupe history;
- none of these commands stop Apple Watch/mobile sensor collection or command
  hardware drivers.

中文註釋：`pause` 不是遙控手錶停止感測。它只表示 Scout server 暫停接收進
safety runtime 的路徑；真裝置可以繼續本機收集、排隊，等 operator resume 後再依
retry/backpressure policy 嘗試送出。

## Risk Boundary

- All live action requires an evidence directory.
- All new hardware/live behavior requires focused tests.
- Secret values and raw payloads must not be written to repo docs, status
  summaries, or telemetry snapshots.
- Assistant output cannot pause, resume, drain, end, or mutate safety state.
- Continuous stream work must stay on `/runtime/streams/*`; direct
  `/safety/observations` remains lower-level signed admission after handoff.
- Incident bridge remains opt-in-required and disabled.

## Parallel Slices

- Slice A: device identity registry and admission binding
  - Files: `runtime_stream_device_identity.py`, `runtime_input_admission.py`,
    focused tests.
  - Boundary: metadata-only, no secret loading, no network.
- Slice B: real-device client harness
  - Files: a Watch/mobile HTTP-push test client or fixture harness.
  - Boundary: dry-run by default; live send only with explicit operator flag.
- Slice C: cadence/offline soak evidence
  - Files: admin smoke doc and bounded runner.
  - Boundary: evidence directory required; no remote notifications.
- Slice D: operator pause/resume real-device smoke
  - Files: admin smoke doc and focused test helper.
  - Boundary: final status must be restored to `observing`.
- Slice E: load/thermal report
  - Files: admin evidence doc.
  - Boundary: read-only status sampling plus explicit test observations only.

## Minimal Slice

The first implementation slice is Slice A plus one response-contract hardening:

- add a metadata-only device identity registry;
- make runtime input admission optionally check identity binding after source
  policy and before sequence/dedupe/cadence;
- include identity match metadata in admission summaries;
- enrich pause/end rejection details with server-side device semantics;
- verify with focused unit/API tests.
