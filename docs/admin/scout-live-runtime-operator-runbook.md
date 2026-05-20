# Scout Live Runtime Operator Runbook

Date: 2026-05-20

Target: `scout.local`

Compose file: `docker-compose.pi.live.yml`

Image tag: `scout-fusion/pi-runtime:live`

## 目的

這份 runbook 是 live runtime enablement 的人工部署指南。它只適用於使用者已明確批准的四個 gate：

- live runtime stream transport；
- remote provider live send；
- local model / Ollama deployed fallback；
- hardware provider control。

中文註釋：這不是把 assistant 變成 safety decision maker。Phase 1 deterministic safety decision 仍是權威；assistant 回答仍是 read-only model interpretation。

操作語義：operator 是唯一能啟動 live profile 的角色；系統啟動後只根據外部設定檔與 secret ref 判斷 gate 是否 ready。任何 assistant 回答、runtime stream 摘要、remote provider queue、或 hardware control audit record 都不能被解讀成已經改變安全判斷。若現場需要切換策略，必須由 operator 先停止 live profile、確認 rollback 狀態，再重新啟動 deterministic Step 1 runtime。

## 必要外部檔案

Scout live profile 從 `/data/scout/config` 與 `/data/scout/secrets` 載入設定。這些檔案由 operator 在 Scout machine 上建立，不放進 repo。

Required config files:

- `/data/scout/config/assistant-models.json`
- `/data/scout/config/hardware-provider-control-policy.json`

Required secret files:

- `/data/scout/secrets/runtime-stream-admission-secret`
- `/data/scout/secrets/hardware-provider-control-token`
- `/data/scout/secrets/live-runtime.env`

Required environment secret refs:

- `SCOUT_CLOUD_MODEL_TOKEN`
- For `SCOUT_REMOTE_PROVIDER_KIND=telegram_bot`:
  - `SCOUT_TELEGRAM_BOT_TOKEN`
  - `SCOUT_TELEGRAM_TARGET_CHAT_ID`
- For the generic webhook provider:
  - `SCOUT_REMOTE_WEBHOOK_URL`
  - `SCOUT_REMOTE_WEBHOOK_TOKEN`
  - `SCOUT_REMOTE_WEBHOOK_HMAC_SECRET`
  - `SCOUT_REMOTE_PRIMARY_TARGET_REF`
  - `SCOUT_REMOTE_BACKUP_TARGET_REF`

範例檔案：

- `tests/fixtures/live_runtime/assistant-models.example.json`
- `tests/fixtures/live_runtime/hardware-provider-control-policy.example.json`
- `tests/fixtures/live_runtime/operator-env.example`

中文註釋：`token_id` 是 operator 可讀的 token label，不是真 token 值。真 token 只透過 env var 或 `/data/scout/secrets/*` 提供。

安全要求：設定檔可以描述「要使用哪個模型」與「token 由哪個 env var 或 secret file 供應」，但不能包含 token 內容。部署證據、測試 fixture、文件範例、JSON response 與 log 都不得出現真實 token、密碼、webhook URL、簡訊目標或衛星通訊目標。

## 模型設定語義

`assistant-models.json` 必須有兩組模型：

- `cloud_model`: 雲端模型，例如 OpenAI-compatible endpoint。
- `local_model`: 本地模型，例如 `http://scout-ollama:11434/v1`。

必須保持：

- `active_profile=cloud`
- `connect_on_startup=true`
- `fallback_to_local_on_error=true`
- `local_fallback_fixed_schema=true`

啟動時 assistant provider 會嘗試 cloud model connectivity check；如果 cloud 通訊失敗且 local model 可用，會切換到 local profile。所有回答仍會標示為 read-only model interpretation，且不得改 runtime、Brain、review、outbound 或 hardware state。

## Hardware Provider Control Policy

`hardware-provider-control-policy.json` 只允許列舉過的 provider refs 與 actions。policy 必須保持：

- `operator_authorization_required=true`
- `arbitrary_shell_allowed=false`
- `safety_mutation_allowed=false`
- `phase1_safety_decision_mutation_allowed=false`
- `outbound_send_allowed=false`
- `token_values_embedded=false`

中文註釋：hardware provider control route 只接受 bearer token 授權的 operator command record；它不允許任意 shell，不呼叫 `/safety/*` mutation，不送 outbound，也不讓 assistant 自動控制硬體。

硬體邊界：這個 slice 只開啟 provider control 的授權入口與 audit record。實際 GPIO、GNSS、IMU、BLE、cellular、battery driver invocation 仍需要獨立 driver slice、壓力測試與 rollback plan。若任何測試結果暗示 driver 已被呼叫，必須視為停止條件。

## 部署流程

1. 在 Scout machine 建立 config 與 secret 目錄。

```bash
sudo mkdir -p /data/scout/config /data/scout/secrets /data/scout/deployments
sudo chown -R alexwang0315:alexwang0315 /data/scout/config /data/scout/secrets /data/scout/deployments
chmod 700 /data/scout/secrets
```

2. 複製範例設定，然後由 operator 填入外部 secret refs。

```bash
cp tests/fixtures/live_runtime/assistant-models.example.json /data/scout/config/assistant-models.json
cp tests/fixtures/live_runtime/hardware-provider-control-policy.example.json /data/scout/config/hardware-provider-control-policy.json
printf '%s\n' '<operator-runtime-stream-secret>' > /data/scout/secrets/runtime-stream-admission-secret
printf '%s\n' '<operator-hardware-control-token>' > /data/scout/secrets/hardware-provider-control-token
chmod 600 /data/scout/secrets/runtime-stream-admission-secret /data/scout/secrets/hardware-provider-control-token
```

3. 寫入雲端模型與 remote provider secrets。

```bash
cat > /data/scout/secrets/live-runtime.env <<'EOF'
SCOUT_CLOUD_MODEL_TOKEN=<operator-cloud-model-token>
SCOUT_REMOTE_PROVIDER_KIND=telegram_bot
SCOUT_TELEGRAM_BOT_TOKEN=<operator-telegram-bot-token>
SCOUT_TELEGRAM_TARGET_CHAT_ID=<operator-telegram-target-chat-id>
EOF
chmod 600 /data/scout/secrets/live-runtime.env
```

中文註釋：`docker-compose.pi.live.yml` 會透過 `env_file` 載入這個檔案，避免把 secret 值寫進 repo 或 compose YAML。若改走 generic webhook provider，才需要 `SCOUT_REMOTE_WEBHOOK_*` 這組 refs。

4. 建置並啟動 live profile。

先跑 preflight-only CLI：

```bash
python live_runtime_enablement_cli.py \
  --env-file tests/fixtures/live_runtime/operator-env.example \
  --env-file /data/scout/secrets/live-runtime.env \
  --pretty
```

中文註釋：這個 CLI 只檢查 gate、config 與 secret ref 是否存在；不連模型、不送 webhook、不啟動 Docker、不控制硬體。

```bash
docker compose -f docker-compose.pi.live.yml build scout-live
docker compose -f docker-compose.pi.live.yml up -d scout-live
```

5. 讀取 health 與 readiness。

```bash
curl --max-time 5 http://127.0.0.1:9099/health
curl --max-time 5 http://127.0.0.1:9099/runtime/status
curl --max-time 5 http://127.0.0.1:9099/providers/status
curl --max-time 5 http://127.0.0.1:9099/runtime/streams/status-read-only
curl --max-time 5 http://127.0.0.1:9099/assistant/status
```

Expected readiness:

- `/health` has `status=ok`;
- `live_enablement.ready=true`;
- `runtime_stream` is in `ready_gates`;
- `remote_provider_live_send` is in `ready_gates`;
- `local_model_ollama_fallback` is in `ready_gates`;
- `hardware_provider_control` is in `ready_gates`;
- `/assistant/status` has `provider=pydantic_ai`;
- `startup_connection_status` is `connected:cloud` or `connected:local`;
- `token_values_exposed=false`.

## 手動驗證

Assistant query:

```bash
curl --max-time 10 -X POST http://127.0.0.1:9099/assistant/query \
  -H 'Content-Type: application/json' \
  --data '{"surface":"debug","question":"為什麼目前 runtime stream gate 是 ready？"}'
```

Hardware provider control status:

```bash
curl --max-time 5 http://127.0.0.1:9099/providers/control/status \
  -H "Authorization: Bearer $(cat /data/scout/secrets/hardware-provider-control-token)"
```

Allowed control command record:

```bash
curl --max-time 5 -X POST \
  http://127.0.0.1:9099/providers/control/provider.gnss.live.v0/actions/read_provider_status \
  -H "Authorization: Bearer $(cat /data/scout/secrets/hardware-provider-control-token)" \
  -H 'Content-Type: application/json' \
  --data '{"operator_id":"operator.local","reason":"live readiness smoke"}'
```

Expected boundary fields:

- `provider_control_authorized=true`;
- `hardware_driver_invoked=false`;
- `safety_mutation_allowed=false`;
- `outbound_send_allowed=false`.

中文註釋：目前 route 記錄 provider control command，保留 audit trail；真正 driver invocation 仍是下一個硬體 driver slice。

## Remote Provider Live Send

Remote provider live send 仍走 operator CLI 與 explicit intent，不由 assistant 自動觸發。

Required pattern:

- reviewed send-intent artifact；
- operator-provided provider config；
- explicit `--enable-live-send` 類型旗標；
- summary-only output；
- no Phase 1 incident bridge auto-enable；
- no Phase 2 Brain writeback。

中文註釋：live runtime profile 只讓 preflight gate 可以 ready；實際 send 仍是 operator-driven action。

## Rollback

Rollback to deterministic Step 1 runtime:

```bash
docker compose -f docker-compose.pi.live.yml down
docker compose -f docker-compose.pi.yml up -d scout
```

Rollback 後必須確認：

- `SCOUT_RUNTIME_PROFILE=pi-field`;
- `SCOUT_ENABLE_LIVE_HARDWARE=0`;
- `SCOUT_ENABLE_AI_INFERENCE=0`;
- `SCOUT_ENABLE_LOCAL_MODEL=0`;
- provider `control_allowed=false`;
- no live stream transport routes are mounted.

## Stop Conditions

Stop and rollback if any of these occur:

- `/health` is not `ok`;
- `live_enablement.ready=false`;
- secret value appears in any JSON response, log, or committed fixture;
- assistant returns an answer that claims it changed Scout state;
- hardware control route reports `safety_mutation_allowed=true`;
- hardware control route reports `outbound_send_allowed=true`;
- hardware control route invokes a driver before the hardware driver slice;
- remote provider sends without reviewed intent and explicit operator flag;
- local model fallback returns output that fails the fixed schema contract;
- Phase 1 safety level changes because of assistant, stream, provider send, or hardware control.

## Local Validation

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest \
  tests/test_live_runtime_docker_contract.py \
  tests/test_live_runtime_enablement.py \
  tests/test_live_runtime_enablement_cli.py \
  tests/test_scout_pi_runtime.py \
  tests/test_scout_live_runtime_operator_runbook.py
```
