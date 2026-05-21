# Scout Live Runtime Guard Update And Signed Sample

Date: 2026-05-20

Target: `scout.local`

Production URL: `http://scout.local:9099`

## Scope

This report records the Phase 4.5 live runtime guard update deployment and the
first operator-approved signed HTTP push sample after that update.

中文註釋：這次 sample 是一筆簽章 observation 進入 live runtime 的 smoke。它不是
SOS、不是 Telegram send、不是 incident bridge 啟用，也不是 Phase 2 Brain
writeback。

## Local Commits

Applied commits:

- `003e4bf6 fix: harden phase45 live runtime demo guards`
- `5cfead95 fix: include signed sample client in live image context`

The second commit was required because the first deployment attempt exposed a
Docker build-context allowlist issue.

## First Deployment Attempt

Evidence directory:
`/data/scout/deployments/live-guard-update-20260520T110519Z`

Result:

- `status=build_failed`;
- failed before replacing production container;
- old `scout-pi-runtime-live` remained running and healthy;
- failure reason: `.dockerignore` did not allow
  `runtime_stream_signed_sample_client.py`;
- production `9099` was not replaced by this failed build.

中文註釋：這是 build 階段失敗，不是 runtime cutover 失敗。舊 live container
仍維持服務。

## Successful Deployment

Evidence directory:
`/data/scout/deployments/live-guard-update-20260520T110822Z`

Rollback image tag:
`scout-fusion/pi-runtime:rollback-before-live-guard-update-20260520T110822Z`

Deployment summary:

- `status=deployed`;
- `health_status=ok`;
- `runtime_profile=pi-field-live`;
- `runtime_stream_transport_enabled=true`;
- `remote_provider_live_send_enabled=true`;
- `hardware_provider_control_enabled=true`;
- `status_surface=read_only_status_ready`;
- `transport_routes_mounted=true`;
- `assistant_provider=pydantic_ai`;
- `assistant_token_values_exposed=false`;
- `sample_client_packaged=true`;
- `secrets_printed=false`.

## Signed HTTP Push Sample

Evidence directory:
`/data/scout/deployments/signed-http-push-sample-20260520T111146Z`

Artifacts:

- `sample-observation.json`;
- `signed-http-push.dry-run.json`;
- `signed-http-push.sent.json`;
- `signed-http-push-summary.json`;
- `runtime-stream-status.before.json`;
- `runtime-stream-status.after.json`.

Sample summary:

- `dry_run_status=dry_run_ready`;
- `send_status=sent`;
- `http_status_code=200`;
- `response_status=accepted`;
- `response_admission_status=admitted_not_forwarded`;
- `response_transport_surface=http_push`;
- `observations_accepted=1`;
- `safety_level=L0_NORMAL`;
- `network_send_attempted=true`;
- `raw_payloads_embedded=false`;
- `secret_values_embedded=false`;
- `runtime_profile=pi-field-live`;
- `health_status=ok`;
- `incident_file_count_before=1`;
- `incident_file_count_after=1`;
- `incident_file_delta=0`;
- `incident_bridge_enabled=false`;
- `phase2_writeback_count=0`.

中文註釋：`admitted_not_forwarded` 是 admission layer 的命名；在 live runtime
transport endpoint 接受後，該 observation 仍會進入 Phase 1 runtime observe path。
這次結果保持 `L0_NORMAL`，沒有新增 incident 檔案。

## Packaged Client Smoke After Rebuild

After the live image was rebuilt with the signed sample client under `/app`, a
second signed HTTP push smoke was run from the packaged client path.

Evidence directory:
`/data/scout/deployments/packaged-signed-sample-client-20260521T001534Z`

Artifacts:

- `sample-observation.json`;
- `sample-observation.validated.json`;
- `signed-http-push.dry-run.json`;
- `signed-http-push.sent.json`;
- `packaged-signed-sample-client-summary.json`;
- `runtime-stream-status.before.json`;
- `runtime-stream-status.after.json`;
- `health.after.json`.

Sample summary:

- `artifact_kind=scout_live_runtime_packaged_signed_sample_client_smoke`;
- `status=passed`;
- `client_path=/app/runtime_stream_signed_sample_client.py`;
- `dry_run_status=dry_run_ready`;
- `dry_run_network_send_attempted=false`;
- `send_status=sent`;
- `http_status_code=200`;
- `response_status=accepted`;
- `response_admission_status=admitted_not_forwarded`;
- `response_transport_surface=http_push`;
- `observations_accepted=1`;
- `safety_level=L0_NORMAL`;
- `network_send_attempted=true`;
- `send_performed=true`;
- `health_status=ok`;
- `runtime_profile=pi-field-live`;
- `runtime_stream_transport_enabled=true`;
- `remote_provider_live_send_enabled=true`;
- `hardware_provider_control_enabled=true`;
- `telemetry_http_accepted_delta=1`;
- `telemetry_http_rejected_delta=0`;
- `incident_file_delta=0`;
- `incident_bridge_enabled=false`;
- `phase2_writeback_count=0`;
- `raw_payloads_embedded=false`;
- `secret_values_embedded=false`;
- `endpoint_secret_embedded=false`;
- `new_observations_sent=true`;
- `stream_control_mutation_performed=false`;
- `remote_provider_send_performed=false`;
- `hardware_control_performed=false`;
- `phase2_writeback_performed=false`.

中文註釋：這次 smoke 是驗證 live image 內建的 packaged client 可以完成 dry-run
與 operator-approved send。它會寫入一筆正常測試 observation，但不觸發
Telegram、SOS、incident bridge、hardware control 或 Phase 2 writeback。

## Boundary

Performed:

- rebuilt and redeployed `scout-fusion/pi-runtime:live`;
- packaged `runtime_stream_signed_sample_client.py` into the live image;
- sent one operator-approved signed HTTP push observation;
- verified packaged `/app/runtime_stream_signed_sample_client.py` after rebuild;
- verified live runtime health and read-only status after deployment.

Not performed:

- no Telegram send;
- no SOS send;
- no SMS send;
- no satellite send;
- no automatic incident escalation;
- no incident bridge opt-in;
- no hardware provider action;
- no Phase 2 Brain writeback;
- no ObservedFact write;
- no HumanReview or review decision mutation;
- no raw secret value written to committed docs.
