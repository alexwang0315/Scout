# Scout Live Runtime Shadow Smoke

Date: 2026-05-20

Target: `scout.local`

Shadow URL: `http://scout.local:9120`

Production Step 1 URL: `http://scout.local:9099`

## Scope

這份 smoke 驗證 live runtime profile 可以在 shadow port 啟動，而不替換目前
`9099` 上的 deterministic Step 1 runtime。

中文註釋：這不是正式 cutover。`scout-pi-runtime` 仍維持 `pi-field` Step 1；
`scout-pi-runtime-live-shadow` 只跑在 `9120` 供部署前驗證。

## Telegram Provider Refs

`~/.Hermes/.env` and `~/.hermes/.env` both had:

- `OPENROUTER_API_KEY`;
- `TELEGRAM_BOT_TOKEN`;
- `TELEGRAM_HOME_CHANNEL`.

These were mapped to Scout-owned secret refs on the Scout machine:

- `SCOUT_CLOUD_MODEL_TOKEN`;
- `SCOUT_REMOTE_PROVIDER_KIND=telegram_bot`;
- `SCOUT_TELEGRAM_BOT_TOKEN`;
- `SCOUT_TELEGRAM_TARGET_CHAT_ID`.

Secret values were written only to `/data/scout/secrets/live-runtime.env`.
They were not printed, committed, or embedded in JSON evidence.

## Preflight

Evidence directory:
`/data/scout/deployments/live-preflight-telegram-20260520T092040Z`

Result:

- `status=live_enablement_ready`;
- `ready=true`;
- `blocked_gates=[]`;
- `blocker_reasons=[]`;
- `missing_secret_refs=[]`;
- `ready_gates=[hardware_provider_control, local_model_ollama_fallback, remote_provider_live_send, runtime_stream]`;
- `required_secret_refs=[env:SCOUT_CLOUD_MODEL_TOKEN, env:SCOUT_TELEGRAM_BOT_TOKEN, env:SCOUT_TELEGRAM_TARGET_CHAT_ID, file:/data/scout/secrets/hardware-provider-control-token, file:/data/scout/secrets/runtime-stream-admission-secret]`;
- `secret_values_embedded=false`;
- `network_send_performed=false`;
- `hardware_control_performed=false`.

中文註釋：這表示四個 gate 設定就緒，但 preflight 本身沒有送 Telegram、沒有控制硬體、沒有改 runtime state。

## Image Build

The live image was rebuilt on Scout machine:

- image: `scout-fusion/pi-runtime:live`;
- source directory: `/home/alexwang0315/scout-fusion-live`;
- Dockerfile: `Dockerfile.pi.live`;
- build-time import smoke: `RUN python -c "import scout_pi_runtime"`.

The import smoke caught missing packaging dependencies before runtime startup.

## Shadow Container

Shadow container:

- name: `scout-pi-runtime-live-shadow`;
- image: `scout-fusion/pi-runtime:live`;
- port: `9120 -> 9099`;
- status during smoke: running.

Production containers stayed unchanged:

- `scout-pi-runtime`: `scout-fusion/pi-runtime:local`, `9099 -> 9099`;
- `scout-pi-phase4-admin`: `scout-fusion/pi-phase4-admin:preview`, `9110 -> 9099`;
- `scout-ollama`: `ollama/ollama:latest`, `11434 -> 11434`.

## Live Shadow Probes

`GET /health` on `9120` returned:

- `status=ok`;
- `runtime_profile=pi-field-live`;
- `live_enablement.status=live_enablement_ready`;
- `runtime_stream_transport_enabled=true`;
- `remote_provider_live_send_enabled=true`;
- `hardware_provider_control_enabled=true`;
- `secret_values_embedded=false`;
- `network_send_performed=false`;
- `hardware_control_performed=false`.

`GET /assistant/status` on `9120` returned:

- `provider=pydantic_ai`;
- `startup_connection_status=connected:local`;
- `active_profile=cloud`;
- `cloud_model=google/gemma-3-27b-it`;
- `local_model=qwen2.5:0.5b`;
- `local_fallback_enabled=true`;
- `local_fallback_fixed_schema=false`;
- `token_values_exposed=false`.

中文註釋：startup 嘗試 cloud provider 後落到 Ollama local fallback。這符合「雲端通訊中斷則切換本地模型」的護欄；不代表 assistant 可改安全狀態。

`GET /runtime/streams/status-read-only` on `9120` returned:

- `transport_routes_mounted=true`;
- `observation_ingest_allowed=true`;
- `stream_control_mutation_allowed=true`;
- `live_provider_send_allowed=true`;
- `safety_mutation_allowed=false`;
- `phase2_writeback_allowed=false`;
- `raw_payloads_embedded=false`;
- route inventory includes `POST /runtime/streams/http-push/observations` and
  `WS /runtime/streams/websocket/observations`.

`GET /providers/control/status` with the operator token returned:

- `status=enabled`;
- `policy_id=hardware_control_policy.pi5_live.v0`;
- `allowed_actions=[read_provider_status]`;
- `operator_authorization_required=true`;
- `token_value_exposed=false`;
- `safety_mutation_allowed=false`;
- `outbound_send_allowed=false`.

No hardware control POST was executed in this smoke.

## Assistant Query

`POST /assistant/query` on `9120` returned:

- `model_interpretation=true`;
- `read_only=true`;
- `boundary.safety_mutation_allowed=false`;
- `boundary.phase2_writeback_allowed=false`;
- `boundary.outbound_send_allowed=false`;
- `boundary.hardware_control_allowed=false`;
- `safe_failure=false`.

The answer correctly treated the response as a read-only model interpretation.
The selected debug query did not include source refs, so the answer reported
insufficient context rather than inventing an explanation.

## Telegram CLI Blocked Smoke

Evidence directory:
`/data/scout/deployments/telegram-cli-blocked-20260520T093157Z`

The Telegram provider CLI was run without live-send flags. Result:

- `status=telegram_live_send_blocked`;
- `blocker_reasons=[provider_adapter_not_enabled, live_network_send_not_enabled, manual_send_authorization_missing]`;
- `live_network_send_attempted=false`;
- `send_performed=false`;
- `remote_notification_send_count=0`;
- `raw_secret_values_embedded=false`;
- `token_value_embedded=false`;
- `chat_id_embedded=false`.

中文註釋：Telegram-specific provider path 已存在，但預設不送。真正送出必須同時提供 reviewed intent artifact、`--enable-provider-adapter`、`--enable-live-network-send`、和 `--authorize-manual-send`。

## Boundary

Not performed:

- no production cutover from `9099`;
- no true Telegram send;
- no SOS, SMS, satellite, or emergency provider send;
- no `/safety/*` mutation from assistant;
- no hardware driver invocation;
- no Phase 2 Brain writeback;
- no ObservedFact write;
- no HumanReview or review decision mutation.

## Current State

At the end of this smoke:

- Step 1 production runtime remained on `9099`;
- live shadow runtime remained available on `9120`;
- live shadow can be stopped with `docker rm -f scout-pi-runtime-live-shadow`.
