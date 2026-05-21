# Scout Runtime Ingest Surface Smoke

Date: 2026-05-21

Target: `scout.local`

Runtime URL: `http://scout.local:9099`

Deployment evidence:
`/data/scout/deployments/live-ingest-surface-20260521T004406Z`

Smoke evidence:
`/data/scout/deployments/ingest-surface-smoke-20260521T004438Z`

## Scope

This smoke verifies that accepted runtime observation responses identify which
server surface admitted the observation.

中文註釋：`/runtime/streams/*` 是現場串流入口，會接 stream telemetry/control；
direct `/safety/observations` 是 lower-level safety API。兩者都可以在 signed
admission 後進入 `SafetyRuntimeSession.observe()`，但 evidence 必須能看出入口
不同，避免把 stream control coverage 誤套到 direct `/safety`。

## Result

- `artifact_kind=scout_runtime_ingest_surface_smoke`;
- `status=passed`;
- `repo_commit=b95c3353`;
- `health_status=ok`;
- `runtime_profile=pi-field-live`;
- `runtime_stream_transport_enabled=true`;
- `remote_provider_live_send_enabled=true`;
- `hardware_provider_control_enabled=true`;
- `stream_send_status=sent`;
- `stream_http_status_code=200`;
- `stream_response_status=accepted`;
- `stream_response_admission_status=admitted_not_forwarded`;
- `stream_response_transport_surface=http_push`;
- `stream_response_ingest_surface=runtime_stream_http_push`;
- `stream_observations_accepted=1`;
- `direct_status_code=200`;
- `direct_response_status=accepted`;
- `direct_ingest_surface=safety_api_direct`;
- `direct_admission_transport=http_push`;
- `direct_admission_status=admitted_not_forwarded`;
- `direct_observations_accepted=1`;
- `incident_file_count_before=1`;
- `incident_file_count_after=1`;
- `incident_file_delta=0`;
- `stream_control_status=observing`;
- `secret_values_embedded=false`;
- `raw_payloads_embedded=false`;
- `new_observations_sent=true`;
- `stream_control_mutation_performed=false`;
- `remote_provider_send_performed=false`;
- `hardware_control_performed=false`;
- `phase2_writeback_performed=false`.

## Boundary

Performed:

- one signed HTTP push observation through `/runtime/streams/http-push/observations`;
- one direct signed observation through `/safety/observations`;
- one health check;
- one read-only stream status check.

Not performed:

- no stream control mutation;
- no remote provider send;
- no Telegram send;
- no SOS send;
- no SMS send;
- no satellite send;
- no hardware control action;
- no Phase 2 Brain writeback;
- no ObservedFact write;
- no HumanReview or review decision mutation;
- no raw secret value written to committed docs.
