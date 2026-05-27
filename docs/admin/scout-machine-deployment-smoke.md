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

## 4.1 Pi 5 + Grove HAT Manual Hardware Bring-Up

以下命令只供 operator 在 Pi host 上手動執行。這些工具是 host-side
diagnostic evidence tools，不呼叫 live `/safety/*` mutation、不送 outbound、不寫
IncidentStore、不改 Phase 1 safety decision。

Hot-plug warning:

```text
Do not hot-plug the Grove HAT / 40-pin HAT body.
Power off the Pi before attaching or removing the HAT or ribbon connection.
```

中文註釋：之前在排線另一端熱插拔 Grove HAT 曾導致 Pi reboot。Grove HAT 本體與
40-pin HAT 連線要視為不可熱插拔。

Power / throttling check:

```bash
vcgencmd get_throttled
```

預期結果：`throttled=0x0`。若不是 `0x0`，先處理電源、溫度或供電線材，不要繼續
做硬體 smoke。

I2C scan:

```bash
i2cdetect -y 1
```

預期結果：Grove OLED Display 1.12 inch 在 I2C port 上可看到 `0x3c`。

Grove LED Bar v2.0 on D16 smoke:

```bash
python3 tools/pi_grove_led_bar_smoke.py \
  --port D16 \
  --pattern status_bits \
  --bits 0x003 \
  --output-jsonl /data/scout/providers/grove_led_bar/manual-smoke.jsonl
```

中文註釋：LED Bar v2.0 使用 MY9221 protocol，不是單 GPIO high/low。已驗證 D16
mapping 為 `data=GPIO16`、`clock=GPIO17`。

OLED I2C smoke:

```bash
python3 tools/pi_oled_i2c_smoke.py \
  --bus /dev/i2c-1 \
  --address 0x3c \
  --driver sh1107g \
  --message "SCOUT\nI2C OK\n0x3C" \
  --output-jsonl /data/scout/providers/oled_i2c/manual-smoke.jsonl
```

Visual feedback wrapper:

```bash
python3 tools/pi_smoke_visual_feedback.py \
  --name oled \
  --run-hold-seconds 1 \
  --hold-seconds 3 \
  --output-jsonl /data/scout/providers/visual_feedback/manual-smoke.jsonl \
  -- \
  python3 tools/pi_oled_i2c_smoke.py \
    --bus /dev/i2c-1 \
    --address 0x3c \
    --driver sh1107g \
    --message "SCOUT\nI2C OK\n0x3C" \
    --output-jsonl /data/scout/providers/oled_i2c/manual-smoke.jsonl
```

中文註釋：`pi_smoke_visual_feedback.py` 是任意 Pi hardware smoke command 的外層
目測確認工具。開始時 OLED 會顯示 `RUN`、LED Bar 亮前半段；`--run-hold-seconds`
可讓 RUN 狀態先停留，方便肉眼確認。child smoke 成功時 OLED 顯示 `OK`、
LED Bar 全亮；child smoke 失敗時 OLED 顯示 `FAIL`、LED Bar 顯示交錯燈號。
它只做 diagnostic visual feedback，不呼叫 live `/safety/*` mutation、不送 outbound、
不改 Phase 1 safety decision。若某個顯示元件故障，預設只會在 JSONL 記錄錯誤並保留
child smoke 的 return code；若要把 OLED/LED 顯示也視為必測項，才加 `--require-visual`。

這個外層工具的用途是讓操作者在接線、供電、匯流排、序列埠或感測器資料流測試時，
不用只盯著終端機輸出，也能從機身上的顯示與燈號立刻知道測試正在執行、已經通過或
已經失敗。它不是產品介面，也不是使用者警示語意；開發期可以用它快速排除接錯線、
接觸不良、匯流排無回應、序列埠選錯、權限不足或測試命令本身失敗等問題。若顯示與
燈號結果和終端機結果不一致，以終端機和寫入的紀錄檔為準，並先把顯示路徑當作另一個
需要檢查的診斷項目處理，不可把燈號結果當成安全層級來源。

範例：用同一個 wrapper 包 GNSS smoke：

```bash
python3 tools/pi_smoke_visual_feedback.py \
  --name gnss \
  --run-hold-seconds 1 \
  --hold-seconds 3 \
  --output-jsonl /data/scout/providers/visual_feedback/gnss-smoke.jsonl \
  -- \
  python3 tools/pi_gnss_nmea_smoke.py \
    --port /dev/ttyUSB0 \
    --baud 9600 \
    --duration-seconds 10 \
    --output-jsonl /data/scout/providers/gnss/manual-smoke.jsonl
```

如需在 Mac/PC 或無硬體環境先驗證 payload schema，可加 `--dry-run`：

```bash
python3 tools/pi_grove_led_bar_smoke.py --dry-run --port D16 --pattern status_bits --bits 0x003
python3 tools/pi_oled_i2c_smoke.py --dry-run --driver auto --address 0x3c
python3 tools/pi_smoke_visual_feedback.py --visual-dry-run --name oled --run-hold-seconds 0 --hold-seconds 0 -- python3 tools/pi_oled_i2c_smoke.py --dry-run
```

更多開發期燈號 mapping 請見：

```text
docs/specs/scout-dev-hardware-status-indicators.md
```

## 4.2 IMU / GNSS Manual Hardware Bring-Up

以下命令只供 operator 在 Pi host 上手動執行。這些工具把 Hiwonder/WIT 類 IM10A、
Grove GPS、Grove IMU 9DOF 視為 diagnostic evidence producers，不呼叫 live
`/safety/*` mutation、不送 outbound、不寫 IncidentStore、不改 Phase 1 safety decision。

Device discovery:

```bash
lsusb
ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null
python3 -m serial.tools.list_ports
```

若 `python3 -m serial.tools.list_ports` 不存在，先安裝 pyserial：

```bash
python3 -m pip install pyserial
```

Power / throttling check:

```bash
vcgencmd get_throttled
```

預期結果：`throttled=0x0`。若不是 `0x0`，先處理電源、溫度或供電線材，不要繼續
做 IMU/GNSS smoke。

Hiwonder/WIT IMU USB smoke:

```bash
python3 tools/pi_hiwonder_imu_usb_smoke.py \
  --port /dev/ttyUSB0 \
  --baud 9600 \
  --duration-seconds 10 \
  --output-jsonl /data/scout/providers/imu/manual-smoke.jsonl
```

GNSS NMEA smoke for raw timestamp/position evidence:

```bash
python3 tools/pi_gnss_nmea_smoke.py \
  --port /dev/ttyUSB0 \
  --baud 9600 \
  --duration-seconds 10 \
  --output-jsonl /data/scout/providers/gnss/manual-smoke.jsonl
```

GNSS NMEA smoke with OLED status:

```bash
python3 tools/pi_gnss_nmea_smoke.py \
  --port /dev/ttyUSB0 \
  --baud 9600 \
  --duration-seconds 60 \
  --oled-status \
  --oled-bus /dev/i2c-1 \
  --oled-address 0x3c \
  --oled-driver sh1107g \
  --oled-update-seconds 2 \
  --output-jsonl /data/scout/providers/gnss/manual-smoke.jsonl
```

GNSS NMEA smoke with OLED + LED Bar status:

```bash
python3 tools/pi_gnss_nmea_smoke.py \
  --port /dev/ttyUSB0 \
  --baud 9600 \
  --duration-seconds 60 \
  --oled-status \
  --oled-update-seconds 2 \
  --led-status \
  --led-port D16 \
  --led-nofix-bit 1 \
  --led-fix-bit 10 \
  --led-update-seconds 2 \
  --led-blink-count 2 \
  --led-blink-seconds 0.25 \
  --output-jsonl /data/scout/providers/gnss/manual-smoke.jsonl
```

中文註釋：Grove LED Bar v2.0 不是 RGB LED，單一燈段不能從紅色切成綠色。這裡的
做法是把固定顏色的段位當狀態燈：預設 `NO FIX` 閃 LED1，`FIX OK` 閃 LED10。若實物
方向和預期相反，直接對調 `--led-nofix-bit 10 --led-fix-bit 1`。LED 狀態仍只是
diagnostic indicator，不可作為 safety decision source。

中文註釋：OLED 會顯示 `SCOUT GPS`、`FIX OK` 或 `NO FIX`、最近的 NMEA sentence
type/count、satellite/fix quality、checksum，以及有 fix 時的座標摘要。96x96 OLED 不適合
顯示完整 `$GPGGA,...` 或 `$GPRMC,...` 原文，所以這裡顯示的是 NMEA signal summary。
這仍是 diagnostic display，不呼叫 live `/safety/*` mutation、不送 outbound、不改
Phase 1 safety decision。

判讀時先看是否有 NMEA count 持續增加；若 count 增加但顯示 `NO FIX`，代表序列資料路徑
已通，只是衛星定位尚未完成。若長時間沒有 count 增加，才優先檢查接線、序列埠、baud
rate、天線位置與供電。

若 GPS 接 IMU D1 且依 vendor 文件設定為 `115200` baud，可另外測：

```bash
python3 tools/pi_gnss_nmea_smoke.py \
  --port /dev/ttyUSB0 \
  --baud 115200 \
  --duration-seconds 10 \
  --output-jsonl /data/scout/providers/gnss/manual-smoke-115200.jsonl
```

Vendor fusion classification smoke:

```bash
python3 tools/pi_imu_gnss_vendor_fusion_smoke.py \
  --port /dev/ttyUSB0 \
  --baud 9600 \
  --duration-seconds 15 \
  --output-jsonl /data/scout/providers/imu_gnss/vendor-fusion-classification.jsonl
```

中文註釋：`pi_imu_gnss_vendor_fusion_smoke.py` 只做觀察與分類，可能輸出
`imu_only`、`gps_raw_only`、`imu_with_gps_fields`、`vendor_fused_only`、
`imu_and_vendor_fused` 或 `unknown`。vendor fused output 不可直接取代 raw GNSS NMEA
或 raw IMU frames。

更多 IMU/GNSS provider boundary 請見：

```text
docs/specs/scout-imu-gnss-provider-bringup.md
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

Scout repo also includes a local voice cue TTS dry-run tool:

```bash
python3 tools/pi_voice_tts_smoke.py \
  "請停下確認方向。" \
  --engine piper \
  --output-jsonl /data/scout/providers/voice_cue/manual-smoke.jsonl
```

中文註釋：`pi_voice_tts_smoke.py` 預設只輸出 Piper/eSpeak NG/aplay command plan
和 JSONL 記錄，不播放真音訊、不呼叫 `/safety/*`、不送 remote outbound、不控制硬體。
只有加上 `--execute` 才會真的執行本機 TTS 與播放命令。

Scout repo also includes a fixture-backed voice cue debug demo:

```bash
python3 tools/voice_cue_debug_demo.py \
  --output-jsonl /data/scout/providers/voice_cue/debug-demo.jsonl
```

預期結果：固定 fixture 的 `VoiceCue` 會 dry-run 經過 `VoiceCuePolicy`、mock transport，
並輸出 mock transport state 與 read-only `RuntimeDebugEvent` JSONL。這個 demo 只驗證
VoiceCue -> policy -> mock transport -> RuntimeDebugEvent/JSONL 的觀察路徑，不呼叫
`/safety/*`、不播放音訊、不送 remote outbound、不控制硬體，也不改 Phase 1 safety
decision。

中文註釋：`voice_cue_debug_demo.py` 是 debug projection demo，不是 TTS 播放測試、
不是 real-device smoke、不是遠端告警測試，也不是 hardware control drill。

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
