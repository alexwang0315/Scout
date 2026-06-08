# Scout Runtime Stream Control Post-Cutover Smoke

Date: 2026-05-20

Target: `scout.local`

Runtime URL: `http://scout.local:9099`

Evidence directory:
`/data/scout/deployments/runtime-stream-control-smoke-20260520T102538Z`

Latest auth-hardening deployment evidence:
`/data/scout/deployments/live-control-auth-20260521T002419Z`

Latest control auth smoke evidence:
`/data/scout/deployments/runtime-stream-control-auth-smoke-20260521T002445Z`

## Scope

This smoke verifies that production `pi-field-live` stream controls on `9099`
can pause and resume local runtime stream ingestion without ending the stream.

中文註釋：這是 local runtime stream control smoke。它會改變 stream control
狀態，但不控制硬體、不送 remote provider、不呼叫 SOS，也不寫 Phase 2。Production
上沒有執行 `end`，最後狀態必須回到 `observing`。

## Control Flow

Performed sequence:

1. `GET /runtime/streams/control/status`
2. `POST /runtime/streams/control/pause`
3. `POST /runtime/streams/http-push/observations` while paused
4. `POST /runtime/streams/control/resume`
5. `POST /runtime/streams/http-push/observations` after resume
6. `POST /runtime/streams/control/drain-queue`
7. `GET /runtime/streams/control/status`

Result:

- `artifact_kind=scout_runtime_stream_control_post_cutover_smoke`;
- `status=passed`;
- `runtime_profile=pi-field-live`;
- `health_sample_count=2`;
- `health_samples_all_ok=true`;
- `pre_control_status=observing`;
- `pause_status_code=200`;
- `pause_status_after=paused`;
- `paused_observation_status_code=409`;
- `paused_observation_rejection_reason=runtime_stream_paused`;
- `resume_status_code=200`;
- `resume_status_after=observing`;
- `accepted_observation_status_code=200`;
- `accepted_observation_status=accepted`;
- `accepted_observation_transport_surface=http_push`;
- `accepted_observation_admission_status=admitted_not_forwarded`;
- `accepted_observation_signature_verified=true`;
- `accepted_observation_policy_matched=true`;
- `drain_status_code=200`;
- `drain_queue_depth_before=0`;
- `drain_queue_depth_after=0`;
- `post_control_status=observing`;
- `post_control_record_count=3`.

## Telemetry

Passed smoke telemetry:

- `telemetry_http_accepted_count_before=2`;
- `telemetry_http_accepted_count_after=3`;
- `telemetry_http_accepted_delta=1`;
- `telemetry_http_rejected_count_before=2`;
- `telemetry_http_rejected_count_after=3`;
- `telemetry_http_rejected_delta=1`;
- `telemetry_last_rejection_reason=runtime_stream_paused`;
- `telemetry_last_admission_status=admitted_not_forwarded`;
- `telemetry_raw_payload_embedded=false`;
- `telemetry_incident_bridge_enabled=false`;
- `telemetry_phase2_writeback_count=0`.

## Control Boundary

Control snapshot after the smoke:

- `stream_control_status=observing`;
- `stream_control_calls_safety_api=false`;
- `stream_control_controls_device_hardware=false`;
- `stream_control_remote_notifications_enabled=false`;
- `stream_control_phase2_writeback_count=0`;
- `secret_value_embedded=false`;
- `raw_payload_embedded=false`;
- `raw_payload_leak_detected=false`.

## Incident Boundary

The accepted test payload was selected from the normal route fixture and did
not create an incident.

Result:

- `pre_incident_file_count=1`;
- `post_incident_file_count=1`;
- `incident_file_delta=0`;
- `incident_ids_returned_count=0`;
- `stored_incident_paths_count=0`.

## Operator Auth Hardening

After the packaged live runtime rebuild, stream control mutation routes were
hardened to require an operator bearer token. The live profile uses
`SCOUT_RUNTIME_STREAM_CONTROL_TOKEN(_FILE)` when set, otherwise it falls back to
the existing hardware provider control token ref.

Auth smoke deployment evidence:
`/data/scout/deployments/live-control-auth-20260521T002419Z`

Auth smoke evidence directory:
`/data/scout/deployments/runtime-stream-control-auth-smoke-20260521T002445Z`

Summary artifact:
`runtime-stream-control-auth-smoke-summary.json`

Result:

- `artifact_kind=scout_runtime_stream_control_auth_smoke`;
- `status=passed`;
- `repo_commit=af02ce4f`;
- `health_status=ok`;
- `runtime_profile=pi-field-live`;
- `runtime_stream_transport_enabled=true`;
- `remote_provider_live_send_enabled=true`;
- `hardware_provider_control_enabled=true`;
- `operator_authorization_required_before=true`;
- `token_value_exposed_before=false`;
- `missing_token_status_code=401`;
- `missing_token_reason=runtime_stream_control_auth_required`;
- `wrong_token_status_code=401`;
- `wrong_token_reason=runtime_stream_control_auth_required`;
- `authorized_pause_status_code=200`;
- `authorized_pause_status_after=paused`;
- `authorized_resume_status_code=200`;
- `authorized_resume_status_after=observing`;
- `post_control_status=observing`;
- `post_control_record_count=2`;
- `status_surface_control_status=observing`;
- `token_value_exposed_after=false`;
- `secret_values_embedded=false`;
- `new_observations_sent=false`;
- `stream_control_mutation_performed=true`;
- `stream_control_final_status_restored=true`;
- `remote_provider_send_performed=false`;
- `hardware_control_performed=false`;
- `phase2_writeback_performed=false`.

中文註釋：這次 auth smoke 只測 runtime stream control 的操作者認證。它有執行
一次 authorized pause/resume，但最後回到 `observing`。它沒有送新 observation、
沒有 remote provider send、沒有硬體控制，也沒有 Phase 2 writeback。

## Boundary

Performed:

- one local pause;
- one paused HTTP observation rejection;
- one local resume;
- one accepted HTTP observation after resume;
- one empty queue drain;
- one missing-token control rejection;
- one wrong-token control rejection;
- one authorized control pause/resume auth smoke with final status restored;
- read-only status/telemetry checks.

Not performed:

- no `end` control action on production;
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

The original longer-soak follow-up is complete:

- bounded post-cutover soak:
  `docs/admin/scout-live-runtime-post-cutover-soak.md`;
- completed overnight soak:
  `docs/admin/scout-live-runtime-long-soak-automation.md`;
- packaged app rebuild smoke:
  `docs/admin/scout-live-runtime-long-soak-automation.md`.

Remaining control work belongs to the next milestone only if real device
streams expose new operator workflows.
