# Scout Machine Phase 4 Admin Preview Smoke

Date: 2026-05-20

Target: `scout.local`

Phase 4 admin preview package: `ed1688cf`

Remote package directory:
`/home/alexwang0315/scout-fusion-phase4-admin-auth`

This report records a read-only LAN smoke for the Phase 4 admin preview service
on the Scout machine. It does not replace the deterministic field runtime and
does not approve live runtime stream, provider send, or safety mutation paths.

## Boundary

- No live `/safety/*` mutation was called.
- No outbound, SOS, SMS, satellite, webhook, or provider send was performed.
- No hardware provider was controlled.
- No local model request was made.
- No Phase 1 safety decision was changed.
- No Phase 2 Brain, ObservedFact, IncidentStore, or HumanReview write was made.
- Admin auth was required for protected `9110` routes. Token material stayed in
  `/data/scout/admin/secrets/phase4-admin-token` or a temporary local file that
  was deleted after the smoke.
- The existing `scout-ollama` container was observed only through `docker ps`;
  it was not started, stopped, queried, or configured.

## Container State

Read-only `docker ps` showed:

- `scout-pi-runtime`: healthy, host `9099 -> 9099`.
- `scout-pi-phase4-admin`: healthy, host `9110 -> 9099`.
- `scout-ollama`: present on `11434`, not touched by this smoke.

## Runtime Health Probe

`GET http://127.0.0.1:9099/health` returned:

- `status=ok`;
- `runtime_profile=pi-field`;
- `safety_runtime.enabled=true`;
- `live_hardware_enabled=false`;
- `ai_inference_enabled=false`;
- `local_model_enabled=false`;
- `event_bus=none`.
- `runtime_stream_status_enabled=true`.

`GET http://scout.local:9099/runtime/streams/status-read-only` returned HTTP
`200` after the field runtime was rebuilt with
`SCOUT_RUNTIME_STREAM_STATUS_ENABLED=true`.

Runtime stream status summary:

- `artifact_kind=runtime_stream_status_surface`;
- `status=read_only_status_ready`;
- `read_only_surface=true`;
- `transport_routes_mounted=false`;
- `observation_ingest_allowed=false`;
- `stream_control_mutation_allowed=false`;
- `live_provider_send_allowed=false`;
- `safety_mutation_allowed=false`;
- `phase2_writeback_allowed=false`;
- `raw_payloads_embedded=false`.

Evidence summary on Scout hardware:

`/data/scout/deployments/runtime-stream-status-fix-20260520T082751Z/runtime-stream-status-deployment-summary.json`

中文註釋：這次只開啟 runtime stream 的只讀查詢面；沒有開啟 observation ingest、
pause/resume/end control、provider send、incident bridge、或 Phase 2 writeback。

## Admin Preview Health Probe

`GET http://127.0.0.1:9110/health` returned:

- `status=ok`;
- `artifact_kind=phase4_admin_runtime_health`;
- `runtime_profile=pi-phase4-admin-preview`;
- `pretrip_workspace_root=/data/scout/admin/pretrip-workspaces`;
- `assistant_provider=pydantic_ai`;
- `assistant_model_config_ref=/data/scout/config/assistant-models.json`;
- `assistant_read_only=true`;
- `phase1_field_runtime_started=false`;
- `safety_api_mutation_allowed=false`;
- `phase2_writeback_allowed=false`;
- `outbound_messages_allowed=false`;
- `hardware_control_allowed=false`.
- `auth.required=true`;
- `auth.token_configured=true`;
- `auth.token_source=file`;
- `auth.token_value_exposed=false`.

`GET http://127.0.0.1:9110/phase4/admin-preview/status` returned:

- `artifact_kind=phase4_admin_hardware_preview_status`;
- `status=ready`;
- `lan_visible=true`;
- `recommended_mac_url=http://scout.local:9110/admin/pretrip`;
- `shares_runtime_port=false`;
- `repo_fixture_write_allowed=false`.
- `auth.required=true`;
- `auth.token_configured=true`;
- `auth.token_source=file`;
- `auth.token_value_exposed=false`.

## Auth Smoke

The protected admin routes were checked from the Mac with
`phase4_hardware_demo_smoke.py --admin-token-file <temporary-token-file>`.

The smoke result was:

- `status=passed`;
- `endpoint_count=6`;
- `passed=6`;
- `failed=0`;
- `admin_auth_header_sent=true`;
- `admin_auth_scheme=basic`;
- `token_value_exposed=false`;
- `runtime_auth_header_sent=false`.

Endpoint results:

- `GET http://scout.local:9110/admin/pretrip` without auth: HTTP `401`;
- `GET http://scout.local:9110/health`: HTTP `200`;
- `GET http://scout.local:9110/admin/pretrip`: HTTP `200`;
- `GET http://scout.local:9110/admin/pretrip/projects/chilai_nanhua_day1`:
  HTTP `200`;
- `GET http://scout.local:9110/assistant/status`: HTTP `200`;
- `GET http://scout.local:9110/phase4/admin-preview/status`: HTTP `200`;
- `GET http://scout.local:9099/health`: HTTP `200`, without an auth header.

The temporary Mac token file was removed after the smoke.

中文註釋：`9110` 是 LAN 上的 Phase 4 admin preview，需要登入；`9099` 是現場
field runtime health probe，這次 smoke 沒有把 admin token 傳給 runtime。

## Map Tile And Review Preview Smoke

Authenticated live probes from the Mac returned:

- `GET http://scout.local:9110/admin/tiles/osm/5/26/13.png`: HTTP `200`,
  `content_type=image/svg+xml`, fallback tile response, `718` bytes;
- `GET http://scout.local:9110/admin/tiles/imagery/chilai_nanhua_day1/imagery/5/26/13.png`:
  HTTP `200`, `content_type=image/svg+xml`, fallback imagery response,
  `313` bytes;
- `POST http://scout.local:9110/admin/pretrip/projects/chilai_nanhua_day1/review-decisions`
  with `candidate_ref=contour.g11.seg_001_003` and
  `persist_to_workspace=false`: HTTP `200`,
  `artifact_kind=pretrip_review_decision_preview`, `preview=true`.

The review preview response preserved the expected boundary:

- `admin_api_write_performed=false`;
- `fixture_file_mutation_allowed=false`;
- `phase1_runtime_mutation_allowed=false`;
- `phase2_writeback_allowed=false`;
- `runtime_mutation_allowed=false`;
- `fixture_files_mutated=false`;
- `phase1_runtime_mutated=false`;
- `phase2_writeback_performed=false`.

`POST http://scout.local:9110/admin/pretrip/projects/chilai_nanhua_day1/workspace`
was then executed once and returned HTTP `200`:

- `artifact_kind=pretrip_workspace_copy`;
- `project_id=chilai_nanhua_day1`;
- `persisted=true`;
- `workspace_root=/data/scout/admin/pretrip-workspaces/chilai_nanhua_day1`;
- workspace file count: `44`;
- workspace size: about `904KB`;
- `project.json` present in the workspace;
- `admin_api_write_performed=true`;
- `workspace_file_mutation_allowed=true`;
- `fixture_file_mutation_allowed=false`;
- `phase1_runtime_mutation_allowed=false`;
- `phase2_writeback_allowed=false`;
- `runtime_mutation_allowed=false`;
- `external_api_calls_made=false`;
- `raw_payloads_embedded=false`.

A repeat `POST /admin/pretrip/projects/chilai_nanhua_day1/workspace` returned
HTTP `409` because the workspace already exists. This confirms the current
workspace creation route is intentionally non-idempotent.

中文註釋：tile smoke 只證明硬體上的 admin service 可以提供地圖圖層 fallback；
review-decision smoke 只跑 preview，不把 admin 決定寫入 workspace。workspace
creation smoke 會寫入 `/data/scout/admin/pretrip-workspaces`，但不寫 repo
fixture、不改 Phase 1 runtime，也不寫 Phase 2 Brain。

## Admin Page Smoke

`GET http://127.0.0.1:9110/admin/pretrip` returned:

- HTTP `200` when authenticated;
- response size `95198` bytes;
- `id="map"` present in the returned HTML.

中文註釋：這只證明 LAN 上的 Phase 4 admin preview 能顯示規劃頁與地圖容器；
不代表它可以核准 departure、compile runtime handoff、或改 Phase 1 safety runtime。

## Assistant Smoke

`GET http://127.0.0.1:9110/assistant/status` returned:

- `read_only=true`;
- `model_interpretation=true`;
- `provider=mock`;
- `runtime_profile=pi-phase4-admin-preview`;
- `local_fallback_enabled=false`;
- `readiness_starts_local_model=false`;
- `status_model_switch_allowed=false`;
- `token_values_exposed=false`.

`POST http://127.0.0.1:9110/assistant/query` with surface `pretrip` and
project `chilai_nanhua_day1` returned:

- `read_only=true`;
- `model_interpretation=true`;
- `surface=pretrip`;
- source ref `tests/fixtures/pretrip/projects/chilai_nanhua_day1/project.json`;
- limitation `Mock provider only; no network or live Pydantic AI call was made.`

## Result

The Phase 4 admin preview is available on the Scout machine at:

```text
http://scout.local:9110/admin/pretrip
```

It is separate from the field runtime at:

```text
http://scout.local:9099
```

No Scout safety, Brain, review, outbound, local model, or hardware-provider state was changed by this smoke.
