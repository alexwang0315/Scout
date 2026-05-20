# Scout Runtime Stream WebSocket Post-Cutover Smoke

Date: 2026-05-20

Target: `scout.local`

Runtime URL: `http://scout.local:9099`

Evidence directory:
`/data/scout/deployments/runtime-stream-websocket-smoke-20260520T102257Z`

## Scope

This smoke verifies that the production `pi-field-live` runtime on `9099` can
accept a signed WebSocket runtime observation after cutover.

中文註釋：這是 live WebSocket admission smoke。它只驗證 runtime stream 的
WebSocket transport、HMAC admission、dedupe、telemetry summary；不送
Telegram、不送 SOS、不控制硬體。

## WebSocket Admission

The smoke generated a signed `runtime_observation_envelope` inside the live
runtime container and connected to:

`WS /runtime/streams/websocket/observations`

Result:

- `artifact_kind=scout_runtime_stream_websocket_post_cutover_smoke`;
- `status=passed`;
- `runtime_profile=pi-field-live`;
- `health_sample_count=2`;
- `health_samples_all_ok=true`;
- `websocket_url=ws://127.0.0.1:9099/runtime/streams/websocket/observations`;
- `websocket_status=accepted`;
- `websocket_transport_surface=websocket`;
- `websocket_observations_accepted=1`;
- `websocket_admission_status=admitted_not_forwarded`;
- `websocket_signature_verified=true`;
- `websocket_policy_matched=true`;
- `websocket_token_scope_allowed=true`;
- `payload_sha256=f0785b81372a0318884ffa2c86ae9be9de6eadc7af3d4872bb8e5dc07ec7827c`;
- `dedupe_key_recorded=true`;
- `secret_value_embedded=false`;
- `raw_payload_embedded=false`;
- `raw_payload_leak_detected=false`.

The raw SensorLog-style payload was used only for the live request. The repo
report and remote summary artifact keep only hashes, status fields, counts, and
boundary flags.

## Duplicate Rejection

The same signed WebSocket body was sent again over the open WebSocket
connection to verify admission dedupe.

Result:

- `duplicate_status=rejected`;
- `duplicate_code=409`;
- `duplicate_admission_status=rejected_duplicate`;
- `telemetry_last_rejection_reason=dedupe_key_already_seen`.

## Telemetry

Passed smoke telemetry:

- `telemetry_websocket_accepted_count_before=0`;
- `telemetry_websocket_accepted_count_after=1`;
- `telemetry_websocket_accepted_delta=1`;
- `telemetry_websocket_rejected_count_before=0`;
- `telemetry_websocket_rejected_count_after=1`;
- `telemetry_websocket_rejected_delta=1`;
- `telemetry_websocket_connection_status=closed`;
- `telemetry_active_websocket_connections=0`;
- `telemetry_raw_payload_embedded=false`;
- `telemetry_incident_bridge_enabled=false`;
- `telemetry_phase2_writeback_count=0`;
- `stream_control_status=observing`;
- `stream_control_calls_safety_api=false`;
- `stream_control_phase2_writeback_count=0`.

## Incident Boundary

The test payload was selected from the normal route fixture and did not create
an incident.

Result:

- `pre_incident_file_count=1`;
- `post_incident_file_count=1`;
- `incident_file_delta=0`;
- `incident_ids_returned_count=0`;
- `stored_incident_paths_count=0`.

## Boundary

Performed:

- one signed WebSocket runtime observation accepted by live `9099`;
- one duplicate signed WebSocket observation rejected by admission dedupe;
- two health samples against `pi-field-live`;
- read-only telemetry/status checks.

Not performed:

- no assistant query or assistant action;
- no remote provider send;
- no Telegram send;
- no SOS send;
- no SMS send;
- no satellite send;
- no hardware control action;
- no Phase 2 Brain writeback;
- no ObservedFact write;
- no HumanReview or review decision mutation.

## Follow-Up

The next safe runtime slice is a live stream-control smoke that pauses and
resumes the stream locally, then verifies the final control state is
`observing`. It should avoid `end` on production unless rollback or a controlled
maintenance window is intended.
