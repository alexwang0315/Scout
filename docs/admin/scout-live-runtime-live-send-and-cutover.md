# Scout Live Runtime Live Send And Cutover

Date: 2026-05-20

Target: `scout.local`

Production URL after cutover: `http://scout.local:9099`

Previous shadow URL: `http://scout.local:9120`

## Scope

This report records the first operator-approved Telegram provider live-send
smoke and the follow-up cutover from the shadow live runtime to production
port `9099`.

中文註釋：這份紀錄代表 Scout Pi runtime 已由 `pi-field` Step 1 container
切到 `pi-field-live` live runtime container。這不是 SOS、簡訊、衛星或事件橋
啟用；Telegram send 僅限 `remote_status` smoke message。

## Telegram Live Send Smoke

Evidence directory:
`/data/scout/deployments/telegram-live-send-20260520T100157Z`

Intent artifact:
`telegram-send-intent.json`

Result artifact:
`telegram-send-result.live.json`

Intent summary:

- `artifact_kind=telegram_provider_send_intent`;
- `intent_id=telegram_provider_send_intent.live_shadow.remote_status.v1`;
- `message_class=remote_status`;
- `manual_send_authorization_required=true`;
- `send_intent_queued=true`;
- `sends_network_request=false`;
- `status=queued_not_sent`;
- `summary_only=true`;
- `raw_payloads_embedded=false`;
- `token_value_embedded=false`;
- `chat_id_embedded=false`.

Live-send result:

- `artifact_kind=telegram_provider_live_send_result`;
- `status=sent`;
- `http_status_code=200`;
- `blocker_count=0`;
- `blocker_reasons=[]`;
- `live_network_send_attempted=true`;
- `send_performed=true`;
- `remote_notification_send_count=1`;
- `message_class=remote_status`;
- `summary_only=true`;
- `raw_payloads_embedded=false`;
- `raw_secret_values_embedded=false`;
- `token_value_embedded=false`;
- `chat_id_embedded=false`;
- `endpoint_url_embedded=false`;
- `incident_bridge_enable_count=0`;
- `phase2_writeback_count=0`;
- `provider_error=null`.

Not recorded in this repo:

- raw Telegram bot token;
- raw Telegram chat id;
- raw provider endpoint URL;
- full provider response body.

中文註釋：這次送出的訊息是 remote status smoke，用於驗證 provider path 可用。
它不代表 Scout 可以自動對外求救，也不會讓 assistant、runtime stream、或
hardware provider control 取得修改安全決策的能力。

## Cutover

Cutover evidence directory:
`/data/scout/deployments/live-cutover-20260520T100435Z`

Rollback image tag:
`scout-fusion/pi-runtime:rollback-before-live-20260520T100435Z`

Before cutover:

- `scout-pi-runtime`: `scout-fusion/pi-runtime:local`, `9099 -> 9099`;
- `scout-pi-runtime-live-shadow`: live runtime on `9120 -> 9099`;
- `scout-pi-phase4-admin`: `9110 -> 9099`;
- `scout-ollama`: `11434 -> 11434`.

Cutover actions:

- captured `9099` and `9120` pre-state under the cutover evidence directory;
- tagged the previous local image for rollback;
- stopped `scout-pi-runtime-live-shadow`;
- stopped the old `scout-pi-runtime` Step 1 container;
- started `scout-pi-runtime-live` from `docker-compose.pi.live.yml`;
- verified production `9099` health before declaring `cutover_ready`.

After cutover:

- `scout-pi-runtime-live`: `scout-fusion/pi-runtime:live`, `9099 -> 9099`;
- `scout-pi-phase4-admin`: still running on `9110 -> 9099`;
- `scout-ollama`: still running on `11434 -> 11434`;
- `9120` no longer accepts connections.

Cutover summary:

- `status=cutover_ready`;
- `runtime_profile=pi-field-live`;
- `live_runtime_enabled=true`;
- `runtime_stream_transport_enabled=true`;
- `remote_provider_live_send_enabled=true`;
- `hardware_provider_control_enabled=true`;
- `assistant_provider=pydantic_ai`;
- `assistant_startup_connection_status=connected:cloud`;
- `assistant_token_values_exposed=false`;
- `stream_transport_routes_mounted=true`;
- `stream_safety_mutation_allowed=false`;
- `stream_phase2_writeback_allowed=false`.

## Post-Cutover Runtime Status

`GET /health` on `9099` returned:

- `status=ok`;
- `runtime_profile=pi-field-live`;
- `live_enablement.status=live_enablement_ready`;
- `live_enablement.ready=true`;
- `ready_gates=[hardware_provider_control, local_model_ollama_fallback, remote_provider_live_send, runtime_stream]`;
- `missing_secret_refs=[]`;
- `live_runtime_enabled=true`;
- `runtime_stream_transport_enabled=true`;
- `remote_provider_live_send_enabled=true`;
- `hardware_provider_control_enabled=true`;
- `live_enablement.boundary.network_send_performed=false`;
- `live_enablement.boundary.hardware_control_performed=false`;
- `live_enablement.boundary.phase1_safety_decision_mutated=false`;
- `live_enablement.boundary.phase2_writeback_performed=false`.

`GET /assistant/status` on `9099` returned:

- `read_only=true`;
- `model_interpretation=true`;
- `provider=pydantic_ai`;
- `runtime_profile=pi-field-live`;
- `startup_connection_status=connected:cloud`;
- `active_profile=cloud`;
- `cloud_model=google/gemma-3-27b-it`;
- `local_model=qwen2.5:0.5b`;
- `local_fallback_enabled=true`;
- `local_fallback_fixed_schema=false`;
- `token_values_exposed=false`.

`GET /runtime/streams/status-read-only` on `9099` returned:

- `status=read_only_status_ready`;
- `transport_routes_mounted=true`;
- `observation_ingest_allowed=true`;
- `stream_control_mutation_allowed=true`;
- `live_provider_send_allowed=true`;
- `safety_mutation_allowed=false`;
- `incident_bridge_enable_allowed=false`;
- `phase2_writeback_allowed=false`;
- `raw_payloads_embedded=false`;
- route inventory includes `POST /runtime/streams/http-push/observations`;
- route inventory includes `WS /runtime/streams/websocket/observations`.

`GET /providers/control/status` with the operator token returned:

- `status=enabled`;
- `policy_id=hardware_control_policy.pi5_live.v0`;
- `allowed_actions=[read_provider_status]`;
- `operator_authorization_required=true`;
- `token_value_exposed=false`;
- `safety_mutation_allowed=false`;
- `outbound_send_allowed=false`.

No hardware control action POST was executed in this cutover smoke.

## Boundary

Performed:

- one operator-approved Telegram `remote_status` smoke send;
- one runtime container cutover from shadow live to production `9099`;
- read-only health/status probes after cutover.

Not performed:

- no SOS send;
- no real SMS send;
- no real satellite send;
- no automatic incident escalation;
- no `/safety/*` mutation from assistant;
- no Phase 1 safety decision change;
- no IncidentStore mutation from assistant or provider smoke;
- no Phase 2 Brain writeback;
- no ObservedFact write;
- no HumanReview or review decision mutation;
- no hardware provider action beyond read-only status.

## Rollback

Rollback evidence is available under:
`/data/scout/deployments/live-cutover-20260520T100435Z`

Rollback image tag:
`scout-fusion/pi-runtime:rollback-before-live-20260520T100435Z`

Rollback plan if production `9099` fails:

1. Stop the live compose service in `/home/alexwang0315/scout-fusion-live`.
2. Start the previous Step 1 compose service in `/home/alexwang0315/scout-fusion-runtime`.
3. Verify `GET /health` on `9099` returns `runtime_profile=pi-field`.
4. Record the rollback evidence directory before retrying live runtime.
