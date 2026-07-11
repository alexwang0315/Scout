# Scout Live Runtime Preflight Smoke

Date: 2026-05-20

Target: `scout.local`

Evidence directory on target:
`/data/scout/deployments/live-preflight-20260520T090121Z`

## Scope

這份 smoke 記錄 live runtime profile 的 preflight-only 驗證。它沒有替換現有
`scout-pi-runtime`，沒有佔用 `9099`，沒有啟動 live service，沒有送 webhook，
也沒有控制硬體 provider。

中文註釋：這是部署前檢查，不是 field mission activation。Phase 1 deterministic
safety runtime 仍維持目前 Step 1 狀態。

## Host State

SSH key login to `scout` succeeded.

Current containers remained:

- `scout-pi-runtime`: `scout-fusion/pi-runtime:local`, healthy, `9099 -> 9099`;
- `scout-pi-phase4-admin`: `scout-fusion/pi-phase4-admin:preview`, healthy,
  `9110 -> 9099`;
- `scout-ollama`: `ollama/ollama:latest`, present on `11434`.

Current Step 1 runtime stayed unchanged:

- `runtime_profile=pi-field`;
- `live_hardware_enabled=false`;
- `ai_inference_enabled=false`;
- `local_model_enabled=false`;
- provider `control_allowed=false`.

## Prepared External Files

Operator-owned files were created on the Scout machine:

- `/data/scout/config/assistant-models.json`;
- `/data/scout/config/hardware-provider-control-policy.json`;
- `/data/scout/secrets/runtime-stream-admission-secret`;
- `/data/scout/secrets/hardware-provider-control-token`;
- `/data/scout/secrets/live-runtime.env`.

The cloud model token was loaded from the operator environment into
`/data/scout/secrets/live-runtime.env`. The value was not printed, committed, or
included in JSON evidence.

The assistant config points to:

- cloud profile: OpenRouter-compatible endpoint;
- local fallback profile: `qwen2.5:0.5b` through host Ollama;
- `connect_on_startup=true`;
- `fallback_to_local_on_error=true`;
- `local_fallback_fixed_schema=false`.

Scout Ollama had both `qwen2.5:0.5b` and `qwen2.5:1.5b` available.

## Image Build

The live image was built on Scout machine:

- image: `scout-fusion/pi-runtime:live`;
- source directory: `/home/alexwang0315/scout-fusion-live`;
- Dockerfile: `Dockerfile.pi.live`.

This build did not stop or replace the existing Step 1 runtime container.

## Preflight Result

Preflight command class:

```bash
docker run --rm \
  --env-file /home/alexwang0315/scout-fusion-live/tests/fixtures/live_runtime/operator-env.example \
  --env-file /data/scout/secrets/live-runtime.env \
  --add-host host.docker.internal:host-gateway \
  -v /data/scout:/data/scout \
  scout-fusion/pi-runtime:live \
  python live_runtime_enablement_cli.py --pretty \
    --output /data/scout/deployments/live-preflight-20260520T090121Z/live-runtime-enable-preflight.json
```

Summary:

- `status=live_enablement_blocked`;
- `ready=false`;
- `ready_gates=[hardware_provider_control, local_model_ollama_fallback, runtime_stream]`;
- `blocked_gates=[remote_provider_live_send]`;
- `blocker_reasons=[missing_remote_provider_secret_refs]`;
- `secret_values_embedded=false`;
- `network_send_performed=false`;
- `hardware_control_performed=false`.

Missing remote provider refs:

- `env:SCOUT_REMOTE_WEBHOOK_URL`;
- `env:SCOUT_REMOTE_WEBHOOK_TOKEN`;
- `env:SCOUT_REMOTE_WEBHOOK_HMAC_SECRET`;
- `env:SCOUT_REMOTE_PRIMARY_TARGET_REF`;
- `env:SCOUT_REMOTE_BACKUP_TARGET_REF`.

中文註釋：這表示 live stream、local model fallback、hardware provider control 的
設定已足以進入下一步驗證；但 remote provider live send 還缺少 Scout-compatible
webhook 目標。不能用 Telegram token 或任意 URL 假裝成已驗證的 generic webhook。

## Boundary

Not performed:

- no live service startup;
- no replacement of `scout-pi-runtime`;
- no `/safety/*` mutation;
- no assistant query against live profile;
- no remote provider send;
- no hardware control POST;
- no driver invocation;
- no Phase 2 Brain writeback;
- no ObservedFact write;
- no HumanReview or review decision mutation.

## Next Operator Decision

Historical status: this preflight gate was later satisfied by the
Telegram-like provider path and recorded in
`docs/admin/scout-live-runtime-shadow-smoke.md` and
`docs/admin/scout-live-runtime-live-send-and-cutover.md`.

To complete the fourth gate, provide a Scout-compatible webhook endpoint and
secret set for:

- `SCOUT_REMOTE_WEBHOOK_URL`;
- `SCOUT_REMOTE_WEBHOOK_TOKEN`;
- `SCOUT_REMOTE_WEBHOOK_HMAC_SECRET`;
- `SCOUT_REMOTE_PRIMARY_TARGET_REF`;
- `SCOUT_REMOTE_BACKUP_TARGET_REF`.

After those refs exist in `/data/scout/secrets/live-runtime.env`, rerun the
preflight before starting `docker-compose.pi.live.yml`.
