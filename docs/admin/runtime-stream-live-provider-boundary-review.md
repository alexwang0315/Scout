# Runtime Stream and Live Provider Boundary Review

Date: 2026-05-20

這份 review 收束目前 dirty worktree 裡的 `runtime_stream_*` 與
`runtime_remote_provider_*` 草稿。它不是啟用 live stream 或 live provider 的 approval。

## Supersession Note

Status as of 2026-05-21: this review is historical boundary context. It has
been superseded by the Phase 4.5 live activation evidence index:

- `docs/admin/scout-phase4-5-live-activation-evidence-index.md`.

The live `pi-field-live` runtime is now deployed on `scout.local:9099` with
operator-approved evidence for:

- live runtime cutover;
- signed HTTP push admission;
- signed WebSocket admission;
- runtime stream pause/resume/drain controls;
- runtime stream control operator auth;
- provider control status operator auth;
- packaged signed sample client smoke;
- packaged soak checker smoke;
- completed overnight read-only soak.

中文註釋：本文件早期的「不要 live use」是當時的保護邊界，不是目前狀態。現在
live runtime 已啟用，但仍不代表自動 field mission activation，也不代表允許
incident bridge、SOS/SMS/satellite send、assistant safety mutation、硬體 driver
invocation 或 Phase 2 writeback。

## Current Status

- Runtime stream policy, telemetry, controls, and transport API are present as
  draft Phase 4.5/runtime-handoff artifacts.
- Remote provider policy, payload composer, send queue, demo harness, and live
  adapter are present as draft artifacts.
- These files are not part of the deterministic Pi Step 1 runtime-core commit.
- These files must not be bundled with assistant guardrails or hardware
  readiness commits until their live-send boundary is explicitly approved.

## Boundary Decision

For the current hardware prototype prep:

- Do not mount runtime stream transport routes into the Scout machine runtime.
- Do not enable remote provider live send by default.
- Do not couple runtime stream controls to GPIO events.
- Do not let assistant responses pause, resume, drain, or end runtime streams.
- Do not let assistant responses enqueue, approve, or send provider payloads.
- Do not call `/safety/*` mutation from runtime stream smoke.
- Do not write IncidentStore, ObservedFact, Brain, or HumanReview from stream
  telemetry.

中文註釋：runtime stream 可以先作為「邊界模型與只讀 telemetry」存在，但不能被誤認為
已經允許 live provider send、incident bridge enablement 或安全決策 mutation。

## Required Gates Before Live Use

Status: the gates below have been either satisfied by dedicated evidence or kept as explicit non-goals for this milestone.

1. Operator policy naming who may enable a stream and for how long.
2. Authentication and replay-protection test plan for every transport.
3. Backpressure/drop behavior verified with fixture load tests.
4. Explicit incident bridge enablement separate from stream acceptance.
5. Manual provider-send authorization separate from queued intent.
6. Rollback plan that leaves Phase 1 safety runtime deterministic.
7. Browser/admin UI wording that labels all stream summaries as read-only until
   live mode is approved.

## Commit Hygiene

Runtime stream/live provider files should be grouped into a dedicated commit
after the above boundary is accepted. They should not be staged with:

- hardware Docker Step 1 runtime-core;
- assistant guardrail API/UI work;
- Phase 4 pretrip planning core;
- local-only field captures;
- local model/Ollama compose.

## Historical Next Implementation Slice

The original next safe slice was a read-only stream status surface that renders
existing policy/telemetry snapshots without mounting live transport send routes.
That slice is now complete, and later live transport/operator-auth evidence is
indexed in `docs/admin/scout-phase4-5-live-activation-evidence-index.md`.

中文註釋：如果下一步要真的開 live provider send，就需要使用者明確決策；這不是可以由
cleanup 或 smoke 自動跨過的邊界。

## Read-Only Status Surface

Implemented read-only status slice:

- `runtime_stream_status_surface.py`;
- `tests/test_runtime_stream_status_surface.py`;
- `tests/test_server_runtime_stream_status_mount.py`;
- `GET /runtime/streams/status-read-only` when the status-only router is
  explicitly mounted.
- Server mount is opt-in with `SCOUT_RUNTIME_STREAM_STATUS_ENABLED=1`; the
  default server does not mount this route.
- The status-only mount is independent from signed admission startup. If signed
  admission is missing or misconfigured, the read-only status route can still
  report policy/control summaries without opening transport routes.

The status surface combines:

- `RuntimeStreamPolicyManifest`;
- `RuntimeStreamTelemetrySnapshot`;
- `RuntimeStreamControlSnapshot`;
- `RuntimeRemoteProviderPolicyContract`.

Boundary:

- `transport_routes_mounted=false`;
- `observation_ingest_allowed=false`;
- `stream_control_mutation_allowed=false`;
- `live_provider_send_allowed=false`;
- `safety_mutation_allowed=false`;
- `incident_bridge_enable_allowed=false`;
- `phase2_writeback_allowed=false`;
- `raw_payloads_embedded=false`.

中文註釋：這個 surface 只顯示政策與狀態摘要，不掛
`/runtime/streams/http-push/observations`、WebSocket ingest、pause/resume/end
control、或 remote provider send route。`SCOUT_RUNTIME_STREAM_STATUS_ENABLED=1`
只代表開啟只讀查詢面，不代表允許 runtime stream 真的接收資料。
