# Scout Machine Deployment Smoke

這份 runbook 是 hardware prototype prep 的人工 smoke 測試指南。它把第一台
Scout machine 的驗證拆成兩段：本機 `offline preflight` 只檢查 target profile 與
邊界；真正對 Pi 或 Scout machine 發出 `curl` 的步驟必須由 operator 手動執行。

中文註釋：這不是自動部署腳本，不會幫你連 Pi，不會啟動 Docker，不會啟動 Ollama，
不會啟動本地模型，也不會把 prototype smoke 納入 assistant readiness gate。
人工測試前請先確認目標機、網路與資料根。

## 1. Prep Boundary

本 runbook 的預設範圍：

- 不連 Pi。
- 不啟動 Docker。
- 不啟動 Ollama。
- 不啟動本地模型。
- 不啟動 k3s、MQTT、NATS、Coral、Jetson。
- 不呼叫 live `/safety/*` mutation。
- 不送 outbound。
- 不送 SOS、SMS、satellite。
- 不控制 hardware provider。
- 不寫 ObservedFact、Brain、IncidentStore 或 review decision。
- 不改 Phase 1 safety decision。

`offline preflight` 可以產生 manual-only checklist，但 checklist 裡的 curl command
不會被測試自動執行。若要真的跑 Scout machine smoke，需要 operator 先明確決定目標機、
網路、資料根與啟動方式。

## 2. Step 1 Target Profile

Step 1 只驗證 Pi 5 + Docker + SSD 的 deterministic runtime baseline。建議設定：

```text
SCOUT_DATA_ROOT=/data/scout
SCOUT_RUNTIME_PROFILE=pi-field
SCOUT_ENABLE_LIVE_HARDWARE=0
SCOUT_ENABLE_AI_INFERENCE=0
SCOUT_EVENT_BUS=none
```

中文註釋：這些值代表 Scout 可以在沒有真硬體、沒有 event bus、沒有本地模型、沒有
雲端 token 的情況下做第一輪 smoke 準備。AI fallback 或 Pi/Ollama 只能用既有
manual artifact chain 記錄，不是這個 smoke 的啟動條件。

範例 target profile：

```text
tests/fixtures/hardware/scout_machine_target_profile.example.json
```

Docker runtime-core contract 也只能先做離線檢查，不啟動 Docker daemon：

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_scout_pi_docker_contract.py
```

預期結果：`Dockerfile.pi` 與 `docker-compose.pi.yml` 固定在 `linux/arm64`、`/data/scout`、
`pi-field`、live hardware off、AI inference off、event bus none；`.dockerignore` 不把
`docker-compose.pi.ai.yml` 或 dirty worktree 的非 runtime-core 檔案放進 build context。

## 3. Local Offline Validation

在 repo root 先跑離線檢查：

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_scout_hardware_prototype_prep.py tests/test_scout_machine_deployment_smoke_runbook.py
```

預期結果：

- target profile 不含 secret-like token value。
- `live_hardware_enabled` 是 `false`。
- `ai_inference_enabled` 是 `false`。
- `event_bus` 是 `none`。
- local model service 沒有被啟用。
- 產生的 smoke checklist 全部標示為 manual-only。

## 3.5 Local Admin / Assistant Prototype Gate

在真正對 Scout machine 或 Pi 發出任何命令前，可以先跑本機 host-side gate。這一步只在
`127.0.0.1` 啟動臨時 Scout server，使用 mock assistant，不連 `scout.local`、不啟動
Ollama、不啟動本地模型、不呼叫 `/safety/*` mutation，也不控制硬體 provider。

```bash
SCOUT_BROWSER_NODE=/Users/alexwang0315/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node \
SCOUT_BROWSER_NODE_PATH=/Users/alexwang0315/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules \
/Users/alexwang0315/scout-fusion/venv/bin/python admin_hardware_prototype_smoke_check.py \
  --browser-mode required \
  --pretty
```

這個 gate 會自動執行：

- `GET /assistant/status`，確認 provider 是 `mock`、`read_only=true`、
  `model_interpretation=true`、`token_values_exposed=false`；
- `assistant_ui_smoke_check.py --pretty`；
- `assistant_readiness_check.py --pretty`；
- `assistant_browser_smoke_check.py --base-url http://127.0.0.1:9111 --pretty`。

中文註釋：這是部署前的 admin/debug/pretrip/hardware-readiness UI guardrail，
不是 real-device smoke，也不是 assistant readiness gate 的替代品。若 operator 沒有
Node/Playwright，可先用 `--browser-mode skip` 只跑 server/status/static/readiness；
真部署前建議使用 `--browser-mode required`。

## 4. Manual Smoke Ladder

以下命令只供 operator 手動執行。測試與 preflight 不會執行它們。
本機可以先用 `scout_pi_fixture_smoke.py` 產生 manual-only plan；它只讀 target
profile 與 fixture，不會開網路連線。

確認 runtime health：

```bash
curl --max-time 5 http://scout.local:9099/health
```

確認 runtime status：

```bash
curl --max-time 5 http://scout.local:9099/runtime/status
```

確認 provider status 仍是 Step 1 fixture/degraded projection：

```bash
curl --max-time 5 http://scout.local:9099/providers/status
```

Scout repo includes a unified host-side radio scan smoke tool:

```bash
sudo python3 tools/pi_radio_scan_smoke.py \
  --wifi-interface wlan0 \
  --ble-controller hci0 \
  --ble-duration-seconds 10 \
  --output-jsonl /data/scout/providers/radio_scan/manual-smoke.jsonl
```

中文註釋：`pi_radio_scan_smoke.py` 會整合 Wi-Fi RSSI 與 BLE RSSI 成單一
`radio_environment_scan` JSON。payload 會帶 fixed read-only `boundary` block，並在寫入
JSONL 前驗證 `radio_counts` 與 Wi-Fi/BLE payload 一致。它是 Pi host-side evidence tool，
不呼叫 `/safety/observations`，不寫 IncidentStore、不寫 ObservedFact、不寫 Phase 2 Brain，
不送 outbound、不控制 hardware provider、不控制 Phase 1 safety decision；若某個 provider
失敗，只會在 `provider_errors` 裡記錄。

確認 Pi host 可以產生 Wi-Fi RSSI evidence。`nmcli` 只能提供 signal percentage；
若要真正 dBm RSSI，優先用 `iw`：

```bash
ssh alexwang0315@scout.local \
  'sudo /sbin/iw dev wlan0 scan | egrep "^BSS |signal:|freq:|SSID:" | sed -n "1,120p"'
```

預期結果：每個 AP block 至少包含 BSSID、frequency、`signal: -NN.NN dBm`、SSID。
這個 smoke 只讀取 radio scan evidence，不寫 `/safety/observations`，也不改 Phase 1
safety decision。

確認 Pi host 可以產生 BLE RSSI evidence。BLE scan 適合 proximity / team beacon
證據，不應被視為穩定身份或精準定位，尤其是 LE Random address：

```bash
ssh alexwang0315@scout.local \
  'timeout 10s sudo btmgmt find'
```

預期結果：`dev_found` records 會包含 BLE address、address type、`rssi -NN`、
advertising flags。這個 smoke 只確認藍牙 proximity evidence 可取得，不寫
`/safety/observations`，也不改 Phase 1 safety decision。

若 operator 已明確開始 hardware prototype smoke，才可用 fixture payload 手動測
`/safety/observations`。這一步是 mutation，所以不得由 preflight、自動測試或
assistant 執行：

```bash
curl --max-time 5 -X POST http://scout.local:9099/safety/observations \
  -H 'Content-Type: application/json' \
  --data @tests/fixtures/hardware/manual_observation_smoke.example.json
```

中文註釋：`/safety/observations` 是 Phase 1 runtime ingest。只有在 operator 決定
真的開始硬體 prototype smoke 時才可以手動呼叫；assistant 與 preflight 不可以替你呼叫。

## 5. Stop Conditions

任一條成立就停止，不要繼續部署：

- `/health` 回傳 degraded 且原因不是已知的 optional provider unavailable。
- data root 不是 `/data/scout`。
- runtime profile 不是 `pi-field`。
- live hardware 或 AI inference 被預設啟用。
- 需要 token value 才能啟動 runtime。
- provider 狀態看起來像真硬體控制台，而不是 fixture/degraded projection。
- 任一流程嘗試自動發送 outbound、SOS、SMS 或 satellite。

下一步若要真的部署到 Scout machine，請先明確指定 target host、port、資料根、啟動方式，
以及是否允許 operator 手動執行 `/safety/observations` fixture smoke。
