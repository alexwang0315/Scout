# Scout Phase 4.5 Live Activation Evidence Index

Date: 2026-05-21

Target evidence root:
`/data/scout/deployments`

This index cross-references the Phase 4.5 planning-to-runtime artifact chain
and the live `pi-field-live` runtime deployment evidence on `scout.local`.

中文註釋：live runtime enablement is not field mission activation。這份索引證明
live runtime host、stream、provider guard、operator control、soak 與 rollback
evidence 已建立；它不代表某一次真實登山任務已經自動出發或自動啟用 SOS。

## Scope

Phase 4.5 separates four concepts:

- Runtime Activation Preflight / runtime 啟動前檢查:
  `runtime_activation_preflight_report`, `status=activation_ready`,
  `activation_performed=false`.
- Runtime Activation Request / runtime 啟動請求:
  `runtime_activation_request`, `status=requested_not_activated`,
  `requires_runtime_operator_confirmation=true`.
- Actual Runtime Activation / 實際啟動現場 runtime:
  `runtime_activation_loader`, `status=loaded_not_observing`,
  `starts_observation_processing=false`.
- Live runtime deployment/cutover:
  operational host readiness on Scout hardware, not automatic field mission
  start; it is not automatic field mission start.

## Phase 4.5 Artifact Chain

The reviewed planning chain keeps activation intent separate from runtime
observation processing:

- `runtime_activation_preflight_report`;
- `status=activation_ready`;
- `activation_performed=false`;
- `runtime_activation_request`;
- `status=requested_not_activated`;
- `requires_runtime_operator_confirmation=true`;
- `live_runtime_activation_count=0`;
- `safety_api_call_count=0`;
- `phase2_writeback_count=0`;
- `runtime_activation_loader`;
- `status=loaded_not_observing`;
- `starts_observation_processing=false`.

中文註釋：`loaded_not_observing` 可以載入 `SafetyRuntimeSession`，但不等於開始
處理現場 observation。真正 observing start 仍要有明確 operator action。

## Live Runtime Reports

- `docs/admin/scout-live-runtime-operator-runbook.md`
- `docs/admin/scout-live-runtime-preflight-smoke.md`
- `docs/admin/scout-live-runtime-shadow-smoke.md`
- `docs/admin/scout-live-runtime-live-send-and-cutover.md`
- `docs/admin/scout-runtime-stream-post-cutover-smoke.md`
- `docs/admin/scout-runtime-stream-websocket-post-cutover-smoke.md`
- `docs/admin/scout-runtime-stream-control-post-cutover-smoke.md`
- `docs/admin/scout-live-runtime-post-cutover-soak.md`
- `docs/admin/scout-live-runtime-long-soak-automation.md`
- `docs/admin/scout-live-runtime-guard-update-and-signed-sample.md`
- `docs/admin/scout-provider-control-status-auth-smoke.md`
- `docs/admin/scout-live-runtime-rollback-drill.md`

## Current Provenance Summary

Production runtime:

- target: `scout.local`;
- URL: `http://scout.local:9099`;
- container: `scout-pi-runtime-live`;
- runtime profile: `runtime_profile=pi-field-live`.

Cutover evidence:

- `/data/scout/deployments/live-cutover-20260520T100435Z`;
- rollback tag:
  `scout-fusion/pi-runtime:rollback-before-live-20260520T100435Z`.

Signed observation and stream evidence:

- `/data/scout/deployments/runtime-stream-admission-smoke-20260520T101957Z`;
- `/data/scout/deployments/runtime-stream-websocket-smoke-20260520T102257Z`;
- `/data/scout/deployments/runtime-stream-control-smoke-20260520T102538Z`;
- `/data/scout/deployments/signed-http-push-sample-20260520T111146Z`;
- `/data/scout/deployments/packaged-signed-sample-client-20260521T001534Z`;
- `/data/scout/deployments/runtime-stream-control-auth-smoke-20260521T002445Z`.
- `/data/scout/deployments/provider-control-status-auth-smoke-20260521T003406Z`.

Soak and packaged-tool evidence:

- `/data/scout/deployments/post-cutover-soak-20260520T102748Z`;
- `/data/scout/deployments/live-runtime-soak-post-guard-20260520T153214Z`;
- `/data/scout/deployments/live-runtime-soak-overnight-20260520T152647Z`;
- `/data/scout/deployments/live-head-rebuild-20260521T000120Z`;
- `/data/scout/deployments/live-runtime-soak-packaged-app-20260521T000152Z`.

Latest hardening evidence:

- `/data/scout/deployments/live-control-auth-20260521T002419Z`;
- `repo_commit=af02ce4f`;
- `operator_authorization_required_before=true`;
- `missing_token_status_code=401`;
- `wrong_token_status_code=401`;
- `authorized_pause_status_after=paused`;
- `authorized_resume_status_after=observing`;
- `stream_control_final_status_restored=true`.
- `/data/scout/deployments/live-provider-control-auth-20260521T003333Z`;
- `repo_commit=7c95fd6f`;
- `unauthorized_status_code=401`;
- `unauthorized_reason=hardware_control_auth_required`;
- `authorized_status_code=200`;
- `provider_control_allowed_actions=[read_provider_status]`;
- `operator_authorization_required=true`;
- `token_value_exposed=false`.

## Boundary Notes

- Direct signed `/safety/observations` remains a lower-level safety API after
  handoff and now reports `ingest_surface=safety_api_direct`.
- Runtime stream HTTP push and WebSocket entries report
  `ingest_surface=runtime_stream_http_push` or
  `ingest_surface=runtime_stream_websocket`.
- Continuous Apple Watch/mobile streams should use `/runtime/streams/*` when
  stream telemetry and operator pause/resume controls are required.
- no automatic SOS send;
- no SMS send;
- no satellite send;
- no assistant safety mutation;
- no incident bridge opt-in;
- no Phase 2 Brain writeback;
- no ObservedFact write;
- no HumanReview or review decision mutation;
- `secret_values_embedded=false`;
- `raw_payloads_embedded=false`;
- signed HTTP samples are allowed test observations;
- signed HTTP samples must remain explicitly operator-approved and
  non-incident-producing.

## Still Intentional

- Rollback is documented but not executed on production.
- Real Apple Watch/mobile continuous streaming is not yet evidenced.
- Hardware provider control still records authorized command records only; no physical driver invocation is part of this milestone.
- SOS/SMS/satellite and incident bridge live sends remain disabled unless a
  later explicitly approved milestone opens them.
