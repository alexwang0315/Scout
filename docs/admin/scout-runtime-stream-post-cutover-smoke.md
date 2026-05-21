# Scout Runtime Stream Post-Cutover Smoke

Date: 2026-05-20

Target: `scout.local`

Runtime URL: `http://scout.local:9099`

Evidence directory:
`/data/scout/deployments/runtime-stream-admission-smoke-20260520T101957Z`

## Scope

This smoke verifies that the production `pi-field-live` runtime on `9099` can
admit a signed HTTP runtime observation after cutover.

中文註釋：這是 live runtime stream admission smoke，不是 assistant 行為、
不是 remote provider send，也不是硬體控制。它會讓 runtime session 接收一筆
測試 observation；因此這份 smoke 只使用正常路線 fixture 的第一個點，並檢查
沒有 incident 檔案增加。

## Precondition

The runtime was already cut over to live mode:

- `runtime_profile=pi-field-live`;
- `live_runtime_enabled=true`;
- `runtime_stream_transport_enabled=true`;
- `remote_provider_live_send_enabled=true`;
- `hardware_provider_control_enabled=true`.

The signed admission secret existed only on the Scout machine:

- `SCOUT_SAFETY_OBSERVATION_ADMISSION_SECRET_FILE=/data/scout/secrets/runtime-stream-admission-secret`;
- `secret_value_embedded=false`.

Secret values were not printed, committed, or copied into the repo.

## HTTP Push Admission

The smoke generated a signed `runtime_observation_envelope` inside the live
runtime container and posted it to:

`POST /runtime/streams/http-push/observations`

Result:

- `artifact_kind=scout_runtime_stream_post_cutover_smoke`;
- `status=passed`;
- `runtime_profile=pi-field-live`;
- `health_sample_count=3`;
- `health_samples_all_ok=true`;
- `http_push_status_code=200`;
- `http_push_status=accepted`;
- `http_push_transport_surface=http_push`;
- `http_push_observations_accepted=1`;
- `http_push_admission_status=admitted_not_forwarded`;
- `http_push_signature_verified=true`;
- `http_push_policy_matched=true`;
- `http_push_token_scope_allowed=true`;
- `payload_sha256=f0785b81372a0318884ffa2c86ae9be9de6eadc7af3d4872bb8e5dc07ec7827c`;
- `dedupe_key_recorded=true`;
- `raw_payload_embedded=false`;
- `raw_payload_leak_detected=false`.

The raw SensorLog-style payload was not stored in this repo or in the summary
artifact. The summary keeps only hashes, counts, statuses, and boundary flags.

## Duplicate Rejection

The same signed envelope was posted a second time to prove admission dedupe.

Result:

- `duplicate_status_code=409`;
- `duplicate_admission_status=rejected_duplicate`;
- `telemetry_last_rejection_reason=dedupe_key_already_seen`.

## Telemetry Delta

The passed smoke used delta-based telemetry assertions because an earlier local
checker run had already produced one accepted test observation and one duplicate
rejection while using an overly strict leak detector.

Passed smoke telemetry:

- `telemetry_http_accepted_count_before=1`;
- `telemetry_http_accepted_count_after=2`;
- `telemetry_http_accepted_delta=1`;
- `telemetry_http_rejected_count_before=1`;
- `telemetry_http_rejected_count_after=2`;
- `telemetry_http_rejected_delta=1`;
- `telemetry_raw_payload_embedded=false`;
- `telemetry_incident_bridge_enabled=false`;
- `telemetry_phase2_writeback_count=0`;
- `stream_control_status=observing`;
- `stream_control_calls_safety_api=false`;
- `stream_control_phase2_writeback_count=0`.

中文註釋：`admitted_not_forwarded` 是 admission layer 的名稱，表示 admission
本身不把封包轉送到其他外部 runtime/provider；在 live runtime stream endpoint
內，通過 admission 後仍會由本地 `SafetyRuntimeSession` 處理該 observation。
這是本 smoke 唯一允許的 runtime state 變化。

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

- one signed HTTP runtime observation accepted by live `9099`;
- one duplicate signed HTTP observation rejected by admission dedupe;
- three health samples against `pi-field-live`;
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

## Follow-Up Status

The original follow-up slices are now complete or deliberately scoped out:

- WebSocket admission smoke: `docs/admin/scout-runtime-stream-websocket-post-cutover-smoke.md`;
- operator pause/resume/drain smoke: `docs/admin/scout-runtime-stream-control-post-cutover-smoke.md`;
- longer post-cutover soak: `docs/admin/scout-live-runtime-post-cutover-soak.md`
  and `docs/admin/scout-live-runtime-long-soak-automation.md`;
- rollback drill documentation: `docs/admin/scout-live-runtime-rollback-drill.md`.

Remaining work belongs to the next milestone: real Apple Watch/mobile
continuous stream evidence and any operator-approved rollback execution.
