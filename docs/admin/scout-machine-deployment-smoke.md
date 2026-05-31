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

Grove LED Bar v2.0 on D5 smoke:

```bash
python3 tools/pi_grove_led_bar_smoke.py \
  --port D5 \
  --pattern status_bits \
  --bits 0x003 \
  --output-jsonl /data/scout/providers/grove_led_bar/manual-smoke.jsonl
```

中文註釋：LED Bar v2.0 使用 MY9221 protocol，不是單 GPIO high/low。已驗證 D16
mapping 為 `data=GPIO16`、`clock=GPIO17`；目前為了保留 4x4 keypad 的 8 條 GPIO，
Scout bench layout 已把 LED Bar 移到 D5，也就是 `data=GPIO5`、`clock=GPIO6`。

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
python3 tools/pi_grove_led_bar_smoke.py --dry-run --port D5 --pattern status_bits --bits 0x003
python3 tools/pi_oled_i2c_smoke.py --dry-run --driver auto --address 0x3c
python3 tools/pi_smoke_visual_feedback.py --visual-dry-run --name oled --run-hold-seconds 0 --hold-seconds 0 -- python3 tools/pi_oled_i2c_smoke.py --dry-run
```

更多開發期燈號 mapping 請見：

```text
docs/specs/scout-dev-hardware-status-indicators.md
```

4x4 matrix keypad diagnostic smoke:

```bash
python3 tools/pi_keypad_4x4_smoke.py \
  --grove-ports D16,D18,D24,D26 \
  --duration-seconds 30 \
  --active-high \
  --oled-status \
  --led-status \
  --output-jsonl /data/scout/providers/keypad/keypad-4x4-manual-smoke.jsonl
```

無實體接線時可先 dry-run：

```bash
python3 tools/pi_keypad_4x4_smoke.py \
  --dry-run \
  --simulate-keys S1,S4,S15 \
  --oled-status \
  --oled-dry-run \
  --led-status \
  --led-dry-run
```

中文註釋：4x4 matrix keypad 是 16 個開關組成的矩陣，通常不接 VCC、不接 GND，只把
`R1 R2 R3 R4 C1 C2 C3 C4` 八條線接到 GPIO。Scout 目前把 keypad 接到 Grove digital
ports `D16,D18,D24,D26`；工具會展開成 rows `16,17,18,19`、cols `24,25,26,27`。
這個配置避開 I2C、UART、LED Bar D5 以及 HAT ID pins。2026-05-28 實測時，
這組接法需要 `active-high` 才能穩定捕捉按鍵事件；`active-low` 沒有捕捉到事件。
程式會把 rows 當 output、cols 當 input 掃描；在目前 `active-high` 模式下 cols 使用
pull-down。按鍵事件只輸出 diagnostic
JSONL，OLED 顯示 `SCOUT KEY / S4 KEY A` 之類的狀態，LED Bar 閃對應段位。任何按鍵，
包含 `A` 的 `sos_arm_candidate`，都不可直接當成 SOS，也不可接 live `/safety/*`
mutation。

若 keypad 面板只標示 `S1` 到 `S16`，目前採用由左至右、由上至下的 row-major
對應。JSONL 會同時輸出 `physical_label` 與邏輯 `key`，後續功能綁定應優先看
`physical_label`，避免面板印字與傳統 4x4 keypad 字元混淆。

開發期策略：4x4 keypad 是 `scout_dev_keypad_v1` development control surface。
它用 8 條 GPIO 提供 16 個輸入自由度，暫時取代多顆 Grove Button，避免為了 8 個
獨立按鈕佔滿 GPIO 並擠掉 LED Bar、PIR 或其他 Grove sensor。Grove Button 或防水
大按鈕仍保留為未來產品化 dedicated safety input。Keypad 上的 SOS/ACK/confirm
都只是 prototype control candidates，不是 final product HMI，不可直接改 L0-L4，
也不可呼叫 live `/safety/*`。

| Physical label | Logical key | Development role | Product HMI status |
| --- | --- | --- | --- |
| `S1` | `1` | `numeric_code_candidate` | dev only |
| `S2` | `2` | `numeric_code_candidate` | dev only |
| `S3` | `3` | `numeric_code_candidate` | dev only |
| `S4` | `A` | `sos_arm_candidate` | prototype only |
| `S5` | `4` | `numeric_code_candidate` | dev only |
| `S6` | `5` | `numeric_code_candidate` | dev only |
| `S7` | `6` | `numeric_code_candidate` | dev only |
| `S8` | `B` | `ack_i_am_ok_candidate` | prototype only |
| `S9` | `7` | `numeric_code_candidate` | dev only |
| `S10` | `8` | `numeric_code_candidate` | dev only |
| `S11` | `9` | `numeric_code_candidate` | dev only |
| `S12` | `C` | `mark_event_candidate` | prototype only |
| `S13` | `*` | `back_or_silence_candidate` | prototype only |
| `S14` | `0` | `numeric_code_candidate` | dev only |
| `S15` | `#` | `confirm_candidate` | prototype only |
| `S16` | `D` | `mode_page_candidate` | dev only |

Scout agent keypad command bridge:

```bash
python3 tools/pi_scout_agent_keypad_command.py \
  --duration-seconds 30 \
  --active-high \
  --oled-status \
  --led-status \
  --output-jsonl /data/scout/providers/keypad/agent-keypad-command.jsonl
```

若要讓已確認的 local diagnostic command 多產生一筆 dispatch evidence，可明確加上：

```bash
python3 tools/pi_scout_agent_keypad_command.py \
  --duration-seconds 30 \
  --active-high \
  --dispatch-confirmed-local \
  --oled-status \
  --led-status \
  --output-jsonl /data/scout/providers/keypad/agent-keypad-command.jsonl
```

無實體按鍵或 Mac/PC 上可先 dry-run：

```bash
python3 tools/pi_scout_agent_keypad_command.py \
  --dry-run \
  --simulate-keys S1,S15,S4 \
  --dispatch-confirmed-local \
  --oled-status \
  --oled-dry-run \
  --led-status \
  --led-dry-run
```

也可以透過 Scout agent tool registry 執行 dry-run：

```bash
python3 scout_agent_cli.py tools run scout.hardware.keypad_command_bridge \
  --manifest-dir tools/scout_agent_tool_manifests \
  --input tests/fixtures/hardware/keypad-agent-command.request.example.json \
  --dry-run \
  --json
```

中文註釋：`pi_scout_agent_keypad_command.py` 會把 keypad press 轉成
`command_candidate_created|confirmed|expired|blocked` evidence。例：`S1` 產生
`gps_status` local diagnostic candidate，`S15/#` 可確認仍在 timeout 內的 candidate；
`S4/A` 會被明確記為 `safety_l4_direct_trigger` blocked，不會進入 L4。OLED 會顯示
`CREATED`、`CONFIRMED`、`EXPIRED` 或 `BLOCKED`，LED Bar 會用不同 pattern 顯示狀態。
實機掃描期間，agent bridge 會在每次 key press 被 scanner 捕捉時立即更新 OLED/LED，
不需要等 `--duration-seconds` 結束才看到目測回饋。
若加上 `--dispatch-confirmed-local`，confirmed candidate 會額外寫入
`local_diagnostic_command_dispatch` evidence；這一層目前只代表 local diagnostic dispatch
path 被記錄與目測顯示，預設不讀寫 Phase 1 runtime，也不把結果升格成 safety truth。
這仍只是 agent/skill command candidate evidence，不會執行 SOS、不會改 L0-L4、不會呼叫
live `/safety/*`，也不會送 outbound。若不用 `--dry-run` 透過 agent tool registry
執行，必須帶 `--authorized-by`，避免 agent 自動控制硬體。

Grove mini PIR motion sensor diagnostic smoke:

```bash
python3 tools/pi_grove_pir_motion_smoke.py \
  --port D22 \
  --signal-index 0 \
  --duration-seconds 45 \
  --active-high \
  --oled-status \
  --led-status \
  --led-motion-bit 2 \
  --output-jsonl /data/scout/providers/pir_motion/pir-manual-smoke.jsonl
```

無實體接線時可先 dry-run：

```bash
python3 tools/pi_grove_pir_motion_smoke.py \
  --dry-run \
  --simulate-levels 0,1,1,0 \
  --oled-status \
  --oled-dry-run \
  --led-status \
  --led-dry-run
```

中文註釋：Grove mini PIR motion sensor 先接 Grove `D22`，預設讀 `signal-index 0`
也就是 `GPIO22`，避免和 LED Bar 的 D5、keypad 的 D16/D18/D24/D26、I2C、UART
互相衝突。PIR 輸出只代表 `nearby_motion_candidate`，不是人物身份、方向、速度或
危險判斷。JSONL 會輸出 `motion_idle`、`motion_present`、`motion_start`、
`motion_end` 這類 diagnostic events；OLED 顯示 `SCOUT PIR / MOTION` 或 `IDLE`，
LED Bar 預設閃 LED2。任何 PIR event 都不可直接當成 safety decision，也不可接 live
`/safety/*` mutation。

Wio-E5 / LoRa-E5 USB serial AT diagnostic smoke:

```bash
python3 tools/pi_wio_e5_lorawan_at_smoke.py \
  --port /dev/ttyUSB0 \
  --baud 9600 \
  --commands AT,AT+VER,AT+ID \
  --oled-status \
  --led-status \
  --output-jsonl /data/scout/providers/wio_e5/wio-e5-at-smoke.jsonl
```

若 Pi 上已出現 stable by-id path，優先用它避免 `/dev/ttyUSB0` 在重插 USB 後漂移：

```bash
ls -l /dev/serial/by-id/
python3 tools/pi_wio_e5_lorawan_at_smoke.py \
  --port /dev/serial/by-id/usb-Silicon_Labs_CP2102N_USB_to_UART_Bridge_Controller_621f02193301f111a009d13e364a576b-if00-port0 \
  --baud 9600 \
  --commands AT,AT+VER,AT+ID \
  --oled-status \
  --led-status \
  --output-jsonl /data/scout/providers/wio_e5/wio-e5-at-smoke.jsonl
```

無實體接線時可先 dry-run：

```bash
python3 tools/pi_wio_e5_lorawan_at_smoke.py \
  --dry-run \
  --oled-status \
  --oled-dry-run \
  --led-status \
  --led-dry-run
```

中文註釋：2026-05-28 實機偵測到 Wio-E5 USB path 是 Silicon Labs CP210x UART Bridge，
`/dev/ttyUSB0` 存在，stable path 在 `/dev/serial/by-id/`。這支工具只做
local USB serial AT diagnostic，預設送 `AT`、`AT+VER`、`AT+ID`，把完整回應寫入
JSONL，OLED 顯示 `SCOUT LORA`、`AT OK` 或 `AT FAIL`、命令通過數、EUI 摘要與
`NO RF TX`，LED Bar 預設用 LED7 表示 AT diagnostic OK、LED10 表示失敗。

這個 slice 不做 LoRaWAN join、不送 uplink、不做 RF test TX，也不接任何遠端 outbound。
工具會在開 serial 前阻擋 `AT+JOIN`、`AT+MSG`、`AT+CMSG`、`AT+PMSG`、`AT+DTRX`、
`AT+SEND`、`AT+TEST` 以及帶 `=` 的設定/發送型 AT command。Wio-E5 目前只是
team/remote capability 的硬體存在與本機 AT response smoke，不是 Scout safety runtime 的通訊 provider，
也不可接 live `/safety/*` mutation。

判讀方式很單純：先確認終端機摘要中的通過數，再看 OLED 是否顯示通過或失敗，最後看
JSONL 裡每個回應行。若 OLED 或 LED 沒反應，但終端機已有回應，優先把顯示路徑視為
另一個診斷問題；若終端機也沒有回應，才回頭檢查 USB 線、序列埠、baud rate、裝置權限
與模組供電。這一步只證明本地序列通訊可用，不能推論山區通訊距離、網關覆蓋、團隊訊息
可靠度或任何求救能力。

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

Pi 5 + Grove HAT UART note:

```bash
python3 tools/pi_gnss_nmea_smoke.py \
  --port /dev/ttyAMA0 \
  --baud 9600 \
  --duration-seconds 20 \
  --oled-status \
  --led-status \
  --output-jsonl /data/scout/providers/gnss/manual-smoke.jsonl
```

中文註釋：2026-05-28 實機測試時，Grove GPS 的 NMEA stream 出現在
`/dev/ttyAMA0`，不是 `/dev/serial0`。`/dev/serial0 -> ttyAMA10` 可以存在且
GPIO14/GPIO15 也可以是 UART mode，但該 port 不一定是 Grove HAT UART 上實際收到
GPS TX 的 device。若 `/dev/serial0` 顯示 `NO STREAM`，先改測 `/dev/ttyAMA0`。

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

Grove IMU 9DOF I2C smoke:

```bash
python3 tools/pi_grove_imu_9dof_smoke.py \
  --bus /dev/i2c-1 \
  --imu-address 0x69 \
  --mag-address 0x0c \
  --sample-count 5 \
  --sample-interval-ms 100 \
  --output-jsonl /data/scout/providers/imu/grove-9dof-manual-smoke.jsonl
```

中文註釋：2026-05-28 實機測試時，Grove IMU 9DOF 的 ICM20600 回應
`0x69 WHOAMI=0x11`，AK09918 magnetometer 回應 `0x0c WIA=0x480c`。這支工具只讀
raw accel/gyro/mag sample，標記 `primary_truth_allowed=false`，不呼叫 live
`/safety/*` mutation，也不改 Phase 1 safety decision。

判讀時先確認 `read_status=ok`、`raw_imu_present=true`、`raw_magnetometer_present=true`。
若加速度、角速度或磁力計數值會隨著輕微轉動模組而變化，代表感測器資料路徑已通。
這些數值目前只作診斷與日後重放稽核，不作即時危險判斷。

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
  --led-port D5 \
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
JSONL 會保留 `$GPGSV` / `$GNGSV` 類 sentence 的 `satellite_signal`，stdout 也會輸出
`gnss_fix_summary` 與 `gnss_signal_summary`。開始 field proof 前，先看
`gnss_fix_summary.valid_fix_count` 是否大於 0，以及
`gnss_fix_summary.latest_valid_fix.position` 是否存在；若仍是 0，就不要開始移動。RF debug
時不要只看 fix；請直接看
`gnss_signal_summary.max_cno_dbhz`、`gps_max_cno_dbhz` 與 `nonzero_cno_count`。若
`GGA` 持續 `quality=0` 且 `GSV reported_visible_satellites=0`、`max_cno_dbhz=null`，
代表 host RX path 已通但 RF 端仍沒有看到衛星訊號。

若 GPS 接 IMU D1 且依 vendor 文件設定為 `115200` baud，可另外測：

```bash
python3 tools/pi_gnss_nmea_smoke.py \
  --port /dev/ttyUSB0 \
  --baud 115200 \
  --duration-seconds 10 \
  --output-jsonl /data/scout/providers/gnss/manual-smoke-115200.jsonl
```

中文註釋：D1 接法是 vendor fusion / integrated-navigation review path，不是 GPS
RF debug path。若 GPS 本體 direct capture 仍是 `GPGSV=0`、C/N0 全 0 或 `GGA`
fix quality 0，改接 D1 不會改善天線或 RF acquisition。RF bring-up 必須先用
GPS receiver 直接進 Scout host 的 raw NMEA/UBX/PUBX 診斷確認 `GPGSV` GPS C/N0
或 valid fix，再評估 D1 是否能提供低算力 vendor fused estimate。

Vendor fusion classification smoke:

```bash
python3 tools/pi_imu_gnss_vendor_fusion_smoke.py \
  --port /dev/serial/by-id/usb-1a86_USB_Serial-if00-port0 \
  --baud 115200 \
  --duration-seconds 15 \
  --output-jsonl /data/scout/providers/imu_gnss/vendor-fusion-classification.jsonl
```

中文註釋：`pi_imu_gnss_vendor_fusion_smoke.py` 只做觀察與分類，可能輸出
`imu_only`、`gps_raw_only`、`imu_with_gps_fields`、`vendor_fused_only`、
`imu_and_vendor_fused` 或 `unknown`。vendor fused output 不可直接取代 raw GNSS NMEA
或 raw IMU frames。這支工具若環境沒有 `pyserial`，會退回標準庫 serial reader，
所以 Scout staging venv 不需為了這個 smoke 額外安裝套件。
若同一條 serial 在 `115200` 只看到 `vendor_fusion_mode_observed=gps_raw_only`、
`raw_gnss_present=true`、`raw_imu_present=false`，代表 D1/單 USB 路徑目前只提供 raw GNSS，
沒有提供 Scout DR heading baseline；此時仍需讓 IMU 另走 USB/UART 進 Scout，或調整
IMU 模組輸出設定直到 classification 看到 `imu_with_gps_fields` 或 `imu_and_vendor_fused`。
若 `fused_navigation_present=true` 但 `raw_imu_present=false`，vendor fusion 只能保留為
comparison evidence，不能作為 primary truth。

Host-side INS/DR local validation:

```bash
python3 -m pytest \
  tests/test_ins_dr_input_adapter.py \
  tests/test_ins_dr_navigation.py \
  tests/test_ins_dr_navigation_smoke.py \
  tests/test_ins_dr_field_evidence_check.py \
  tests/test_ins_dr_field_proof_pipeline.py \
  tests/test_ins_dr_field_completion_gate.py \
  tests/test_ins_dr_diagnostic_route_scaffold.py \
  tests/test_ins_dr_field_readiness_check.py \
  tests/test_ins_dr_gnss_fix_watch.py \
  tests/test_ins_dr_field_session.py \
  tests/test_ins_dr_field_movement_drill.py \
  tests/test_ins_dr_manual_field_run.py \
  tests/test_ins_dr_live_field_proof.py \
  tests/test_ins_dr_proof_manifest_check.py \
  tests/test_ins_dr_runtime_smoke.py \
  tests/test_pi_dr_delta_smoke.py \
  tests/test_pi_wheel_odometry_delta_smoke.py \
  tests/test_pi_wheel_encoder_gpio_smoke.py \
  tests/test_route_progress.py
```

中文註釋：Scout 主控端第一版 INS/DR 核心在 `ins_dr_navigation.py`。它用 reliable
raw GNSS 做 anchor / re-anchor，用 raw IMU、pedometer 或 wheel odom 轉出的
`DeadReckoningDelta` 在 GNSS degraded gap 期間推進 route-aligned estimate。Hiwonder
vendor fused output 只能作 comparison evidence；若與 host estimate 不一致，標記
`vendor_fusion_disagreement`，不可覆蓋 raw GNSS + DR estimate。

把既有 smoke JSONL 轉成 INS/DR estimate：

```bash
python3 tools/ins_dr_navigation_smoke.py \
  --route tests/fixtures/routes/normal_climb.gpx \
  --input-jsonl /data/scout/providers/gnss/manual-smoke.jsonl \
  --input-jsonl /data/scout/providers/imu/manual-smoke.jsonl \
  --output-jsonl /data/scout/providers/ins_dr/navigation-estimates.jsonl \
  --pretty
```

中文註釋：`ins_dr_navigation_smoke.py` 是 diagnostic navigation estimate tool，
不呼叫 live `/safety/*` mutation、不送 outbound、不控制硬體 provider。Hiwonder angle
frame 只更新 heading state；真正的 DR 位移仍需要 SensorLog pedometer、wheel odometry
`distance_delta_m` 或其他明確位移來源。

操作判讀時先看輸出是否至少包含一次可靠 GNSS anchor，再看後續 DR 是否持續前進、
信心是否隨時間或距離下降、以及是否出現 degraded reason。若沒有明確位移來源，只有
姿態角或加速度 frame，不應宣稱已完成航位推算；那只能說姿態資料路徑已通。

在沒有 wheel encoder driver 前，可以先用 operator-entered / fixture-backed distance
delta 產生 DR evidence：

```bash
python3 tools/pi_dr_delta_smoke.py \
  --distance-delta-m 3.0 \
  --heading-deg 87.5 \
  --timestamp-s 11.0 \
  --source manual_odometry_delta \
  --provider operator_entered_distance_delta \
  --output-jsonl /data/scout/providers/odometry/manual-dr-delta.jsonl
```

若現場已有 wheel encoder / base odometry provider，應優先把累積 wheel distance 或
encoder ticks 轉成 DR delta，而不是讓 operator 手動輸入距離：

```bash
python3 tools/pi_wheel_encoder_gpio_smoke.py \
  --left-gpio 20 \
  --right-gpio 21 \
  --meters-per-tick 0.0042 \
  --duration-seconds 30 \
  --sample-interval-seconds 1 \
  --require-live-positive-movement \
  --output-jsonl /data/scout/providers/wheel_odometry/wheel-raw.jsonl \
  --pretty

python3 tools/pi_wheel_odometry_delta_smoke.py \
  --input-jsonl /data/scout/providers/wheel_odometry/wheel-raw.jsonl \
  --output-jsonl /data/scout/providers/odometry/wheel-dr-delta.jsonl \
  --provider scout_wheel_encoder \
  --pretty
```

若 raw provider 只有左右 encoder ticks，必須明確提供 tick 尺度：

```bash
python3 tools/pi_wheel_odometry_delta_smoke.py \
  --input-jsonl /data/scout/providers/wheel_odometry/wheel-raw.jsonl \
  --meters-per-tick 0.0042 \
  --output-jsonl /data/scout/providers/odometry/wheel-dr-delta.jsonl \
  --provider scout_wheel_encoder \
  --pretty
```

中文註釋：`pi_wheel_odometry_delta_smoke.py` 固定
`hardware_control_scope=diagnostic_wheel_odometry_delta_only`。它只讀 wheel/encoder
JSONL，接受 `cumulative_distance_m`、左右 cumulative distance，或加上
`--meters-per-tick` 的 `left_ticks` / `right_ticks`，再輸出 `source=wheel_odometry` 的
`distance_delta_m`。每筆輸出會保留 `previous_raw_evidence_ref`、
`current_raw_evidence_ref`、`odometry_delta_method` 與累積距離，方便事後追回原始
provider evidence。這條路才是正式 DR completion proof 應優先使用的來源；人工
`manual_odometry_delta` 只保留給 rehearsal。
`pi_wheel_encoder_gpio_smoke.py` 固定
`hardware_control_scope=diagnostic_gpio_wheel_encoder_capture_only`，只把兩條 GPIO input
edge count 轉成 `odometry.cumulative_distance_m`，不控制馬達、不呼叫 live `/safety/*`。
`--meters-per-tick` 必須來自輪徑、encoder PPR 與減速比校正；沒有這個尺度就不能把 ticks
當成導航距離。若用 `--dry-run` 產生模擬 ticks，payload 會標成 `dry_run=true`，field
session 不會把它當正式 wheel odometry gate。
單獨驗證 wheel wiring 時可加 `--require-live-positive-movement`；工具會在 report 中輸出
`live_positive_wheel_movement_ready`、`left_tick_delta`、`right_tick_delta` 與
`missing_reason`，並在沒有非 dry-run 正向 tick / distance 變化時以 exit code 1 結束。
同一份 report 也會輸出 `line_activity_observed`、`left_level_change_delta` 與
`right_level_change_delta`，用來分辨 GPIO 線完全沒有跳變、或有線路活動但還沒形成可用
DR distance evidence。
field session 也可以直接採集 GPIO wheel encoder：
`--wheel-encoder-gpio-capture --wheel-encoder-left-gpio 20 --wheel-encoder-right-gpio 21 --wheel-meters-per-tick 0.0042`。
它會寫出 `wheel-encoder-gpio-capture.jsonl` 並自動放進 `wheel_odometry` completion gate。
注意：這個 gate 需要正向 tick / cumulative distance 變化；車輪靜止時產生的 0 tick
JSONL 只能證明 GPIO capture path 活著，不能當正式 DR distance evidence。
若要做正式 live proof，wheel movement evidence 應該在 GNSS anchor 之後採集。這時使用
`ins_dr_live_field_proof.py --wheel-encoder-gpio-capture`，或在 field session 加
`--live-wheel-encoder-gpio-capture`；工具會先取得 anchor，再提示 operator 移動，並把
live GPIO capture 寫到 field-run 下的 `wheel-encoder-gpio-capture.jsonl`，再進入 re-anchor。
若 wheel/encoder JSONL 沒有 `heading_deg`，請把 `pi_hiwonder_imu_usb_smoke.py`
產生的 Hiwonder/WIT angle frame JSONL 放在 wheel DR delta JSONL 前面輸入 runtime；
`dead_reckoning_input.heading_deg` 會保留實際使用的 heading，field report 會用
`dr_heading_summary` 稽核這件事。

再與 raw GNSS JSONL 一起離線驗證：

```bash
python3 tools/ins_dr_navigation_smoke.py \
  --route tests/fixtures/routes/normal_climb.gpx \
  --input-jsonl /data/scout/providers/gnss/manual-smoke.jsonl \
  --input-jsonl /data/scout/providers/odometry/wheel-dr-delta.jsonl \
  --output-jsonl /data/scout/providers/ins_dr/navigation-estimates.jsonl \
  --pretty
```

如果要確認同一批 evidence 走進 runtime 後仍能產生 route progress、map evidence、
recording decision 與 safety event projection，可跑 runtime-level replay：

```bash
python3 tools/ins_dr_runtime_smoke.py \
  --mission-graph tests/fixtures/mission_graph/normal_climb_mission.json \
  --input-jsonl /data/scout/providers/gnss/manual-smoke.jsonl \
  --input-jsonl /data/scout/providers/odometry/manual-dr-delta.jsonl \
  --output-jsonl /data/scout/providers/ins_dr/runtime-updates.jsonl \
  --pretty
```

中文註釋：`ins_dr_runtime_smoke.py` 只在本機建立 `SafetyRuntimeSession` 做
diagnostic replay，不呼叫 live `/safety/*` endpoint、不控制硬體 provider、不送
outbound。判讀時看 `latest_position_estimate.source=dead_reckoning`、
`latest_route_progress_sample.estimate_source=dead_reckoning`，以及 DR-only update 的
`observation_lat=null` / `observation_lon=null` 是否成立。
這支工具固定 `hardware_control_scope=diagnostic_runtime_ingest_replay_only`，
`phase1_live_safety_decision_change_allowed=false`。它的用途是確認資料進到 runtime 後
仍保留原始定位與推算定位的分界：有 GPS 的那筆可以當 anchor，只有位移的那筆只能當
估測進度，不能被寫成新的 GPS 座標。若這裡失敗，先回頭檢查 JSONL 欄位、時間順序、
路線檔與位移量，不要直接拿 field run 當成可用導航。

最後用 field evidence gate 判斷這組 runtime updates 是否足以支持 INS/DR 可用性：

```bash
python3 tools/ins_dr_field_evidence_check.py \
  --runtime-updates-jsonl /data/scout/providers/ins_dr/runtime-updates.jsonl \
  --require-reanchor \
  --pretty
```

中文註釋：`ins_dr_field_evidence_check.py` 只讀本機 JSONL，固定
`hardware_control_scope=diagnostic_field_evidence_review_only`。它會檢查 raw GNSS
anchor、anchor 後的 `dead_reckoning`、DR-only update 沒有偽造 GPS 座標、DR route
progress 有前進、raw GNSS/DR/re-anchor 都仍在 mission map corridor 內，以及加上
`--require-reanchor` 時是否真的看到 `gnss_reanchor`。只有
`field_proof_status=passed` 才能把這組現場資料當作 INS/DR 可用性證據；若是 failed，
請看 `checks` 裡哪一項不通，不要只看終端機有輸出就宣稱導航可用。
若 `raw_gnss_checksum_valid_for_navigation` 失敗，代表 anchor 或 re-anchor 的 NMEA
checksum 無效；這類 payload 會保留為 diagnostic evidence，但會被降成
`invalid_gnss_checksum_diagnostic_only`，不可作 raw GNSS primary truth。
若 `route_corridor_inside_for_navigation` 失敗，通常代表 field run 用錯 mission graph、
測試地點不在路線附近，或 GNSS/DR 已偏離可接受 corridor；這種資料不能用來宣稱
Scout 導航可用。
若 `gnss_field_capture_not_replayed_fixture` 失敗，代表 GNSS anchor 或 re-anchor 是由
`--raw-nmea`、`raw_nmea_argument` 或其他 replay fixture 產生。這種資料只能做 parser
rehearsal 或文件演練，不可作正式 completion proof；payload 會標成
`primary_truth_scope=diagnostic_replayed_nmea_only`。

實機時建議直接跑一鍵 pipeline，把 runtime replay 和 field evidence gate 串在一起：

```bash
python3 tools/ins_dr_field_proof_pipeline.py \
  --mission-graph tests/fixtures/mission_graph/normal_climb_mission.json \
  --input-jsonl /data/scout/providers/gnss/manual-smoke.jsonl \
  --input-jsonl /data/scout/providers/odometry/manual-dr-delta.jsonl \
  --runtime-updates-jsonl /data/scout/providers/ins_dr/runtime-updates.jsonl \
  --field-report-json /data/scout/providers/ins_dr/field-report.json \
  --proof-manifest-json /data/scout/providers/ins_dr/proof-manifest.json \
  --require-reanchor \
  --pretty
```

中文註釋：`ins_dr_field_proof_pipeline.py` 固定
`hardware_control_scope=diagnostic_field_proof_pipeline_only`。它會同時寫出 runtime
updates JSONL、field report JSON 與 proof manifest JSON；只有 process exit code 為 0、
`field_proof_status=passed`，且 `proof-manifest.json` 裡 mission graph、input JSONL、
runtime updates、field report 都有 `sha256`，才把這次 field run 視為 INS/DR 可用性證據。
proof manifest 本身固定 `hardware_control_scope=diagnostic_field_proof_manifest_only`。
判讀時請先看 manifest 的結論，再看各檔案雜湊是否存在；若任一檔案缺雜湊，代表這次
證據鏈不完整，不能拿來宣稱導航功能已完成。

manifest 寫出後，再用獨立 verifier 反查檔案與雜湊：

```bash
python3 tools/ins_dr_proof_manifest_check.py \
  --proof-manifest-json /data/scout/providers/ins_dr/proof-manifest.json \
  --require-reanchor \
  --pretty
```

中文註釋：`ins_dr_proof_manifest_check.py` 固定
`hardware_control_scope=diagnostic_field_proof_manifest_verification_only`。它會重新讀取
manifest、runtime updates JSONL 與 field report JSON，確認 mission graph、input
JSONL、runtime updates、field report 的 `sha256` 都和 manifest 相符，並確認
field report / runtime updates 真的包含 `dead_reckoning` 與 `gnss_reanchor`。只有
`proof_manifest_status=passed` 且 `completion_ready=true`，才把這次 proof manifest
視為 Scout INS/DR field completion evidence。
若要 debug 哪一段失敗，再分別跑 `ins_dr_runtime_smoke.py` 與
`ins_dr_field_evidence_check.py`。

最終驗收時可直接跑 completion gate，避免漏跑 manifest verifier，也避免舊
runtime-updates JSONL append 到本次 field run：

```bash
python3 tools/ins_dr_field_completion_gate.py \
  --mission-graph tests/fixtures/mission_graph/normal_climb_mission.json \
  --input-jsonl /data/scout/providers/gnss/manual-smoke.jsonl \
  --input-jsonl /data/scout/providers/odometry/manual-dr-delta.jsonl \
  --runtime-updates-jsonl /data/scout/providers/ins_dr/runtime-updates.jsonl \
  --field-report-json /data/scout/providers/ins_dr/field-report.json \
  --proof-manifest-json /data/scout/providers/ins_dr/proof-manifest.json \
  --verification-report-json /data/scout/providers/ins_dr/verification-report.json \
  --require-reanchor \
  --pretty
```

中文註釋：`ins_dr_field_completion_gate.py` 固定
`hardware_control_scope=diagnostic_field_completion_gate_only`，並覆寫本次指定的
runtime updates、field report、proof manifest 與 verification report。只有
`scout_ins_dr_navigation_status=field_ready`、`proof_manifest_status=passed`、
`completion_ready=true` 同時成立，才可宣稱 Scout INS/DR 已有可用 field navigation
evidence。
若其中任一項失敗，請把這次結果視為未完成，而不是局部成功。常見原因包括只有 GPS
anchor、沒有明確位移量、DR 後沒有回到可靠 GNSS、路線進度沒有前進、或本次輸出的
證據檔被舊資料污染。處理順序是先修輸入資料與實機測試流程，再重跑 completion gate；
不要手動改 JSON 結論，也不要把 vendor fused output 當成 Scout primary truth。
completion gate 也會檢查 `dr_distance_source_allowed_for_navigation`；runtime update 必須
保留 `observation_dr_source_kind` 與 `observation_dr_navigation_allowed`。若 DR 來源是
`manual_operator_distance_delta`，field report 會標成 `field_rehearsal_only` 並拒絕把它當
正式 navigation evidence。正式驗收的 `distance_delta_m` 必須來自 wheel odometry、
encoder odometry、pedometer/PDR 或其他明確非人工輸入的 odometry provider。
對 `wheel_or_encoder_odometry` 來說，不能只靠 `source=wheel_odometry` 字串；runtime
update 還必須帶 `observation_provider_hardware_control_scope=diagnostic_wheel_odometry_delta_only`、
`observation_odometry_delta_method`、`observation_previous_raw_evidence_ref` 與
`observation_current_raw_evidence_ref`。缺這些 provenance 時 field report 會標成
`missing_wheel_encoder_provider_provenance`，不得當正式導航證據。
completion gate 也會檢查 `dr_heading_available_for_navigation`；DR update 必須有
`observation_dr_heading_deg`，且 position estimate 不能帶 `heading_unavailable`。若
wheel/encoder provider 只有距離或 ticks，必須在 wheel delta 前先餵入 Hiwonder/WIT
angle frame 或其他 heading evidence，讓 runtime 以 raw IMU heading 推進 DR。

若現場只想先把 GNSS hardware snapshot、GNSS diagnosis、field readiness 串成同一包證據，
請優先使用 top-level diagnostic field session wrapper：

```bash
python3 tools/ins_dr_field_session.py \
  --output-dir /data/scout/providers/ins_dr/field-session-001 \
  --mission-graph /data/scout/providers/ins_dr/manual-field-run-001/mission_graph/manual_field_run_001_mission.json \
  --gnss-baud 115200 \
  --snapshot-ab-duration-seconds 60 \
  --snapshot-probe-duration-seconds 10 \
  --gnss-watch-before-readiness \
  --gnss-watch-window-seconds 10 \
  --gnss-watch-max-wait-seconds 600 \
  --gnss-watch-stop-on valid_fix \
  --readiness-auto-select-duration-seconds 30 \
  --readiness-capture-duration-seconds 60 \
  --allow-overwrite \
  --pretty
```

若要做下一次戶外推車測試，請改用 movement drill wrapper；它把 field session 的長參數固定成
`GNSS anchor -> live GPIO wheel capture -> GNSS re-anchor`，並在 GNSS 未取得 valid fix
時只留下診斷證據，不會要求 operator 推車做無效 proof：

```bash
python3 tools/ins_dr_field_movement_drill.py \
  --output-dir /data/scout/providers/ins_dr/movement-drill-001 \
  --mission-graph /data/scout/providers/ins_dr/manual-field-run-001/mission_graph/manual_field_run_001_mission.json \
  --wheel-meters-per-tick 0.0042 \
  --gnss-baud 115200 \
  --gnss-watch-window-seconds 10 \
  --gnss-watch-max-wait-seconds 600 \
  --anchor-wait-timeout-seconds 180 \
  --reanchor-wait-timeout-seconds 180 \
  --wheel-encoder-left-gpio 20 \
  --wheel-encoder-right-gpio 21 \
  --wheel-encoder-capture-duration-seconds 30 \
  --allow-overwrite \
  --pretty
```

先用 `--dry-run-plan` 可只輸出 `field-movement-drill-report.json` 和 operator steps，
不開 serial、不讀 GPIO。正式跑時 report 會保留 `drill_profile=gnss_anchor_then_live_gpio_wheel_then_reanchor`、
`diagnostic_field_movement_drill_only` 與 field session 的 completion gates。

中文註釋：`tools/ins_dr_field_session.py` 固定
`hardware_control_scope=diagnostic_field_session_orchestration_only`，它只 orchestration
診斷流程，不呼叫 live `/safety/*` mutation、不送 outbound、不控制導航。預設會依序寫出
`gnss-hardware-snapshot.json`、`gnss-diagnosis-report.json`、
`gnss-diagnosis-report.md`、`field-readiness-report.json`、
`field-session-next-action.json`、`field-session-next-action.md` 與
`field-session-report.json`。`field_session_status=readiness_not_ready` 時必須停在 GNSS
天線/RF/定位修復；`field_session_status=ready_for_live_proof` 只代表可以進入下一步 live
proof，還不代表導航完成。只有 operator 明確加 `--run-live-proof`，且 readiness report
已經是 `ready_for_live_field_proof=true`，wrapper 才會呼叫
`ins_dr_live_field_proof.py`；live proof 完成後才會看到
`field_session_status=live_proof_completed` 與 `completion_ready=true`。若 USB hub 上有多個
serial device，這支 wrapper 仍沿用 readiness 的 auto-select-by-fix 規則，只接受看到
valid fix 的 `selected_gnss_port`，不猜 `/dev/ttyUSB0`。
若加上 `--gnss-watch-before-readiness`，wrapper 會先跑 GNSS fix/C/N0 watch；當
`gnss_watch_status=valid_fix_observed` 時，會把 watch 選到的 `selected_gnss_port` 與
`gnss-fix-watch-payloads.jsonl` 交給 readiness。若 watch 停在
`gnss_watch_status=timed_out_no_rf_signal`，field session 會標成
`field_session_status=gnss_watch_not_ready` 或 readiness failed，不會進 live proof。
這樣現場人員可以把車放到開闊處等待，不需要反覆手動抄指令；證據會連續保存，失敗時也
能看清楚是沒有資料、沒有訊號、只有訊號、還是真的取得定位。
`field-session-next-action.json` 會把失敗狀態轉成 operator action：例如
`next_action_status=collect_physical_measurements`、`repair_physical_fault`、
`fix_gnss_rf_or_antenna`、`wait_for_valid_fix`、`collect_dr_evidence_inputs` 或
`run_live_proof_next`。只要 next action
仍要求補 GNSS/physical evidence，就不能宣稱 INS/DR 已可用。
`gnss_command_path_summary` 會把硬體 snapshot 裡的 u-blox/PUBX 診斷拉到最外層：
`receiver_response_observed_count>0` 代表 Scout TX 到 receiver RX 的 command path 已看到
receiver response；若同時 `max_cno_dbhz=null`、`gps_max_cno_dbhz=null`，問題就更偏向
RF/天線/偏壓/遮蔽，而不是單純 UART TX 接錯。若 `mon_hw_seen_count=0`，代表仍拿不到
MON-HW antenna supervisor 欄位，不能用 aStatus/aPower 直接排除天線問題。
同一份 report 也會輸出 `scout_ins_dr_navigation_status`，這是最接近 completion gate 的
總結欄位：`field_ready` 才代表 live proof 已完成；`ready_for_live_proof` 只代表可以開始
驗收；`not_ready_gnss_*` 代表 GNSS anchor 尚未成立；`not_ready_dr_inputs` 代表 raw IMU
heading 或 wheel odometry 還沒準備好。
同一份 `field-session-report.json` 與 `field-session-next-action.json` 也會輸出
`ins_dr_completion_gate_summary`，把現場 completion 拆成四個 gate：
`gnss_anchor`、`raw_imu_heading`、`wheel_odometry`、`live_field_proof`。
正式判讀時可以直接看 `failed_gate_names`；只有這個清單為空、且
`completion_ready=true` / `scout_ins_dr_navigation_status=field_ready` 同時成立，才代表
Scout INS/DR 現場導航證據完成。
若狀態是 `collect_physical_measurements`，同一個 session 目錄也會自動寫出
`gnss-physical-measurements-template.json` 與 `gnss-physical-measurements-template.md`；
直接複製 JSON template、填入電表與天線檢查值後，再用
`--gnss-physical-measurements-json` 重跑 field session。
若狀態是 `collect_dr_evidence_inputs`，代表 GNSS/route readiness 可能已經成立，但
live INS/DR proof 還缺 raw IMU heading baseline 或 wheel odometry DR distance source。
這時請先用 `pi_hiwonder_imu_usb_smoke.py` 產生 raw IMU angle JSONL，並用
`pi_wheel_odometry_delta_smoke.py` 或 wheel raw JSONL 提供正距離 / cumulative distance
證據，再把 `--heading-evidence-jsonl` 和 `--wheel-odometry-jsonl` 傳給 field session。
若 IMU 已經接到 Scout，也可以讓 field session 自己 capture heading：
`--imu-heading-capture-port auto --imu-heading-baud 9600 --imu-heading-capture-duration-seconds 10`。
它會在 session 目錄寫出 `imu-heading-capture.jsonl` 與
`imu-heading-capture-report.json`，再把這份 raw IMU heading evidence 放進同一個
DR input gate。若目前像單 USB D1 路徑只看到 `gps_raw_only`，這個 capture 會保持
`raw_imu_heading_ready=false`，提醒 operator 仍需另接 IMU USB/UART 或調整 IMU 輸出。
若 Hiwonder/WIT angle frame 還沒接好，但 Grove IMU 9DOF 仍在 I2C 上，可先用
`pi_grove_imu_9dof_smoke.py` 產生包含 `mag_raw` 的 JSONL，再以
`--heading-evidence-jsonl` 提供給 field session。這會以 raw magnetometer 推導未校正
heading baseline，只適合 DR heading gate 與現場姿態 baseline；它不是 GNSS position
authority，也不能取代後續 heading calibration。
也可以讓 field session 自己讀 Grove 9DOF：
`--grove-imu-heading-capture --grove-imu-sample-count 5 --grove-imu-sample-interval-ms 100`。
它會寫出 `grove-imu-heading-capture.jsonl`，並自動放進同一個
`raw_imu_heading` completion gate。
若同時也缺 wheel odometry，field session 會寫出 `wheel-odometry-template.jsonl` 與
`wheel-odometry-template.md`。填入至少兩筆遞增 `timestamp_s` 與單調遞增的
`odometry.cumulative_distance_m`，或填左右 encoder ticks 並在轉換時加 `--meters-per-tick`。
填好的 JSONL 可直接傳給 `--wheel-odometry-jsonl`；若只想先轉成 DR delta，可用
`pi_wheel_odometry_delta_smoke.py --input-jsonl ... --output-jsonl ...`。
現場判讀請以這份下一步清單為主；它會把目前缺口整理成量測、修復、等待或驗收，而不是
讓操作員猜測下一個動作。若清單要求補量測，請先量完並重跑；若清單要求修天線或供電，
請先處理硬體；若清單要求等待定位，請移到開闊處繼續觀察。
這一層的用途是把現場判斷收斂成同一份可回放紀錄：先看接收器是否有資料，再看天線與
射頻路徑是否有訊號，最後才判斷能不能進入移動驗收。若定位尚未成立，操作員應保留
這包證據並回頭檢查天線朝向、遮蔽、供電、接頭、線材與同地點對照接收器，不應直接
開始推車或宣稱航位推算可用。

若只需要在戶外長時間等 GNSS 收斂，不想每次重跑 hardware snapshot，可用 GNSS fix/C/N0
watch：

```bash
python3 tools/ins_dr_gnss_fix_watch.py \
  --output-dir /data/scout/providers/gnss/fix-watch-001 \
  --gnss-port auto \
  --gnss-baud 115200 \
  --window-seconds 10 \
  --max-wait-seconds 600 \
  --poll-interval-seconds 2 \
  --stop-on valid_fix \
  --pretty
```

中文註釋：`tools/ins_dr_gnss_fix_watch.py` 固定
`hardware_control_scope=diagnostic_gnss_fix_watch_only`，只讀 raw NMEA，不呼叫
live `/safety/*` mutation、不送 outbound、不控制導航。它會輸出
`gnss-fix-watch-events.jsonl`、`gnss-fix-watch-payloads.jsonl` 與
`gnss-fix-watch-report.json`。`watch_status=valid_fix_observed` 且
`ready_for_live_field_proof=true` 時，才代表這條 GNSS serial path 可進 readiness/live
proof；若只是 `watch_status=gps_cno_observed_without_fix` 或
`rf_signal_observed_without_fix`，代表 RF 已看到訊號但還不能當 anchor。若
`watch_status=timed_out_no_rf_signal`，代表 NMEA 有進來但 C/N0 仍空，優先查天線/RF path。
`--stop-on gps_cno` 或 `--stop-on any_cno` 只適合 RF debug；它可能讓 process exit code 為
0，但 `ready_for_live_field_proof` 仍會是 false，不能直接啟動 INS/DR field proof。

若 GNSS watch 或 field session 長時間停在 `timed_out_no_rf_signal`，請把人工電表與天線
檢查結果也放進同一包 session：

```bash
python3 tools/pi_gnss_physical_checklist.py \
  --write-template /data/scout/providers/gnss/physical-measurements-template.json

python3 tools/pi_gnss_physical_checklist.py \
  --measurements-json /data/scout/providers/gnss/physical-measurements-filled.json \
  --output-json /data/scout/providers/gnss/gnss-physical-checklist-report.json

python3 tools/ins_dr_field_session.py \
  --output-dir /data/scout/providers/ins_dr/field-session-physical-001 \
  --mission-graph /data/scout/providers/ins_dr/manual-field-run-001/mission_graph/manual_field_run_001_mission.json \
  --gnss-baud 115200 \
  --gnss-watch-before-readiness \
  --gnss-watch-window-seconds 10 \
  --gnss-watch-max-wait-seconds 600 \
  --gnss-physical-measurements-json /data/scout/providers/gnss/physical-measurements-filled.json \
  --pretty
```

中文註釋：`pi_gnss_physical_checklist.py` 只解讀 operator 手動輸入的量測值，不控制硬體。
它的 interpretation 固定 `hardware_control_scope=operator_entered_measurement_interpretation_only`。
`--gnss-physical-measurements-json` 可接受填好的 template 或已解讀的
`gnss-physical-checklist-report.json`；field session 會把結果另存成
`gnss-physical-checklist-report.json`，再交給 GNSS diagnosis。若結果是
`physical_fault_indicated`，diagnosis 會優先標示 physical fault，例如 VCC under-load
不足、RF_IN 對地短路、天線中心到 RF_IN 斷路、active antenna bias 掉壓、天線被遮蔽，
或 known-good GPS L1 antenna 仍無 C/N0。這些都是修硬體的證據，不是 navigation proof；
修復後仍必須重新跑 watch/readiness，直到 valid fix 成立。

若 operator 要在現場一次完成 anchor、DR delta、re-anchor 與 completion gate，可用
manual field run 工具：

```bash
python3 tools/ins_dr_diagnostic_route_scaffold.py \
  --output-dir /data/scout/providers/ins_dr/manual-field-run-001 \
  --mission-id manual_field_run_001 \
  --anchor-jsonl /data/scout/providers/gnss/manual-smoke.jsonl \
  --heading-deg 87.5 \
  --distance-m 3.0 \
  --corridor-half-width-m 6.0 \
  --pretty

python3 tools/pi_gnss_ab_compare.py \
  --auto-capture \
  --auto-baud 115200 \
  --duration-seconds 60 \
  --output-json /data/scout/providers/gnss/gnss-auto-ab-compare.json

python3 tools/pi_gnss_ab_compare.py \
  --placement current_mount \
  --placement away_from_pi_usb_ssd \
  --placement outdoor_open_sky \
  --placement-port auto \
  --placement-baud 115200 \
  --placement-settle-seconds 10 \
  --duration-seconds 30 \
  --output-json /data/scout/providers/gnss/gnss-placement-sweep.json

python3 tools/pi_gnss_signal_monitor.py \
  --output-dir /data/scout/providers/gnss/signal-monitor-current \
  --port auto \
  --baud 115200 \
  --window-seconds 2 \
  --interval-seconds 1 \
  --max-window-count 60 \
  --pretty

python3 tools/pi_gnss_hardware_snapshot.py \
  --auto-targets \
  --auto-baud 115200 \
  --ab-duration-seconds 60 \
  --probe-duration-seconds 10 \
  --output-json /data/scout/providers/gnss/gnss-hardware-snapshot.json

python3 tools/ins_dr_field_readiness_check.py \
  --mission-graph /data/scout/providers/ins_dr/manual-field-run-001/mission_graph/manual_field_run_001_mission.json \
  --gnss-port auto \
  --gnss-baud 115200 \
  --auto-select-gnss-by-fix-duration-seconds 30 \
  --auto-select-gnss-evidence-dir /data/scout/providers/gnss/readiness-auto-select \
  --capture-gnss-duration-seconds 60 \
  --capture-gnss-evidence-jsonl /data/scout/providers/gnss/readiness-live-capture.jsonl \
  --gnss-hardware-snapshot-json /data/scout/providers/gnss/gnss-hardware-snapshot.json \
  --require-valid-gnss-fix \
  --output-dir /data/scout/providers/ins_dr/manual-field-run-001/field-run \
  --pretty \
  > /data/scout/providers/gnss/field-readiness-report.json

python3 tools/ins_dr_manual_field_run.py \
  --mission-graph /data/scout/providers/ins_dr/manual-field-run-001/mission_graph/manual_field_run_001_mission.json \
  --output-dir /data/scout/providers/ins_dr/manual-field-run-001/field-run \
  --gnss-port /dev/serial/by-id/usb-u-blox_GNSS-if00-port0 \
  --gnss-baud 9600 \
  --anchor-duration-seconds 10 \
  --distance-delta-m 3.0 \
  --heading-deg 87.5 \
  --source wheel_odometry \
  --provider scout_wheel_encoder \
  --movement-window-seconds 30 \
  --reanchor-duration-seconds 10 \
  --pretty
```

中文註釋：`ins_dr_diagnostic_route_scaffold.py` 固定
`hardware_control_scope=diagnostic_route_scaffold_only`。它會用目前 GNSS anchor 或手動
lat/lon 建立短距離 GPX、mission graph 與 map corridor；這只是現場驗收用診斷 route
fixture，不是正式路線規劃，也不是 primary truth。`pi_gnss_hardware_snapshot.py` 固定
`hardware_control_scope=diagnostic_read_only_plus_non_destructive_polls`，它收集 serial、
USB、UART、供電節流、NMEA A/B capture 與 UBX poll 證據，輸出硬體/RF snapshot JSON。
若 USB hub 上有多個 GNSS receiver，可先跑 `pi_gnss_ab_compare.py --auto-capture`；
它預設只掃 `/dev/serial/by-id/` 與常見 USB serial path，輸出 `auto_serial_candidates`、
`labels_with_gps_rf_signal` 與 `labels_with_any_rf_signal`，用來決定哪一條 stable path
可當 comparator，哪一條是 Scout target。若 comparator baud 不是 115200，請用
`--auto-baud 9600` 再跑一次，或重複提供多個 `--auto-baud`。只有需要把
`/dev/serial0` 這類 Pi UART 也納入比較時，才加 `--include-uart`。
若只有一顆 GNSS receiver，但懷疑天線位置、Pi/SSD/USB hub 遮蔽或供電影響，請用
`pi_gnss_ab_compare.py --placement ...` 做同一條 serial 的 sequential placement sweep。
report 會寫出 `placement_sweep.best_placement_label`、
`placements_with_gps_rf_signal`、`placements_with_any_rf_signal` 與 ranked placements；
這不是 navigation proof，而是用來決定天線應該固定在哪個位置再重跑 field session。
現場操作時請一次只改一個變數，例如先維持同一條 USB 線，只把天線從目前固定點移到遠離
Pi、SSD、電池與金屬外殼的位置，再移到真正開闊天空下。每個位置都要停住等待，不要邊走邊
量；否則 C/N0 變化會混入移動、遮蔽與線材拉扯，難以判斷是哪個因素改善或惡化。若只有
開闊天空位置有 C/N0，優先處理安裝位置與遮蔽；若所有位置都沒有 GPS C/N0，才回頭查天線、
偏壓、接頭、RF 路徑與接收器設定。
若 operator 正在手動微調天線、USB hub 或電源位置，請用 `pi_gnss_signal_monitor.py`
看短窗口回饋。它每個 window 都會在 stderr 印出 `state`、`gps_cno`、`any_cno`、
`talkers=GP:.../GL:...` 與 `fix`，並寫出 `gnss-signal-monitor-windows.jsonl` 和
`gnss-signal-monitor-report.json`。report 也會保留 `talker_signal_summary`，用來分辨
真正的 GPS `GP` C/N0 與只有 `GL`/`BD` 這類非 GPS C/N0 的狀況。若 report
出現 `valid_fix_observed_hold_position_and_run_movement_drill`，請保持位置不要再動，直接跑
movement drill；若是 `rf_is_intermittent_adjust_mounting_and_reduce_shielding`，代表 C/N0
會出現但不穩，優先處理固定方式、遮蔽物與供電/USB 線位置。
`pi_gnss_hardware_snapshot.py --auto-targets` 使用同一套 serial discovery，會對每個
USB/stable target 做 NMEA A/B capture 與 non-destructive UBX probe，並把
`auto_serial_candidates` 與 `auto_serial_candidate_count` 寫進 snapshot。若要重跑已知
target，可改回 `--target scout=/dev/serial/by-id/...:115200`。
`ins_dr_field_readiness_check.py --gnss-port auto` 在 USB hub 多 serial 時預設仍會停在
`ambiguous_serial_candidates`，避免猜錯 GNSS source；它也預設只看 USB/stable serial，
要納入 Pi UART 才加 `--include-uart`。若現場要讓 readiness 自動選出可用的 raw GNSS
source，加入 `--auto-select-gnss-by-fix-duration-seconds` 與
`--auto-select-gnss-evidence-dir`；它會對每條候選 serial 做 live NMEA capture，只有看到
`valid_fix_count > 0` 的候選才會把 `selected_gnss_port` 設成該 stable path，並輸出
`gnss_auto_selection_summary.selection_status=selected_valid_fix_candidate`，且
`gnss_auto_selection_has_valid_fix_candidate` check 必須通過。若多條 serial 都沒有 valid
fix，readiness 仍是 `not_ready`，不會把只有 C/N0 或只有 NMEA 的 port 當 field proof
anchor。
若只有 Scout 這一顆 GNSS target，verdict 會明確列出還缺 USB comparator 或 GPS L1
C/N0 對照；若同位置 comparator 已看到 GPS C/N0，而 Scout target 長時間沒有 GPS C/N0，
`verdict.gps_rf_fault_strongly_supported_labels` 才能支持 RF/天線路徑故障判斷。
`ins_dr_field_readiness_check.py` 固定
`hardware_control_scope=diagnostic_field_readiness_check_only`；它不呼叫 live `/safety/*`
mutation、不送 outbound，只檢查 mission graph / GPX route / map corridor 是否可由
`SafetyRuntimeSession` 載入、`gnss_serial_port_exists` 是否通過、output dir 是否可寫，
以及是否已有舊的 proof artifacts。若提供 `--gnss-evidence-jsonl`，它只讀既有 GNSS
evidence；若提供 `--capture-gnss-duration-seconds` 與
`--capture-gnss-evidence-jsonl`，它會先做一次 read-only live NMEA capture，寫出
`gnss-readiness-capture.jsonl` 或指定 JSONL，再把這份 evidence 放進 readiness gate。
若提供 `--gnss-hardware-snapshot-json`，readiness report 會加入
`gnss_hardware_snapshot_loaded` 與 `gnss_hardware_snapshot_summary.verdict.next_required_evidence`；
這只提供下一步硬體證據 guidance，不會取代 GNSS fix/CN0 gate。
readiness report 會檢查 `gnss_live_evidence_capture_completed`、
`gnss_evidence_has_rf_signal_or_fix` 與 `gnss_evidence_has_valid_fix`，並把
`gnss_live_capture_summary.fix.valid_fix_count`、
`gnss_evidence_summary.fix.latest_valid_fix`、`gnss_evidence_summary.signal.max_cno_dbhz` /
`gps_max_cno_dbhz` 放進 report；`gnss_readiness_diagnosis.state` 會直接標示
`valid_fix_ready`、`rf_signal_without_valid_fix`、`non_gps_rf_signal_without_valid_fix`、
`no_rf_signal_observed`、`no_nmea_payloads` 或 `nmea_without_gsv_or_fix`，並附
`next_operator_action`。若目前像 `GSV=0`、C/N0 全空，或只有 GL/BD C/N0 但
`gps_max_cno_dbhz=null` 且 `valid_fix_count=0`，就不應進入 field run。
field session 會把 GNSS watch 與 readiness capture 的 talker-level evidence 分別保留在
`gnss_watch_talker_signal_summary` 與 `readiness_gnss_talker_signal_summary`；若
`readiness_gnss_best_talker=GL` 但 `GP` 仍沒有 C/N0，代表目前只看到非 GPS 訊號，還不能當
GNSS anchor。
現場判讀重點是先確認能不能取得可靠定位，再確認衛星訊號是否來自需要的定位系統；
只有零星非定位主線訊號時，仍要回到天線位置、遮蔽、供電與同地點對照接收器檢查。
現場判讀請先停在這一關：有穩定 NMEA 只代表資料線與 baud 正確，還不能代表導航可用。
只有看到有效定位或至少看到衛星訊號強度後，才值得移動車體收集 DR 位移；否則後面的
anchor、DR、re-anchor 只會產生失敗證據。
只有
`field_run_readiness_status=ready` 才進入 manual field run。`--gnss-port auto` 只做
候選 serial path discovery；若只有一個候選，report 會給 `selected_gnss_port`，現場
manual run 應優先使用 `/dev/serial/by-id/` stable path。若 auto detect 回報
`ambiguous_serial_candidates`，代表 USB hub 上有多個 serial device，必須明確指定 GPS
那條 port，不可猜 `/dev/ttyUSB0`。若 output dir 已有
`anchor-gnss.jsonl`、`field-report.json` 或 `proof-manifest.json` 等舊證據，必須換新
output dir，除非 operator 明確用 `--allow-overwrite` 標示這次就是覆寫演練。
`ins_dr_manual_field_run.py` 固定
`hardware_control_scope=diagnostic_manual_field_run_only`。它會依序寫出
`anchor-gnss.jsonl`、`dr-delta.jsonl`、`reanchor-gnss.jsonl`，再產生
`runtime-updates.jsonl`、`field-report.json`、`proof-manifest.json` 與
`verification-report.json`。這支工具只讀 GNSS serial、記錄 operator 明確輸入的
distance delta，不控制導航、不呼叫 live `/safety/*`、不送 outbound；若 re-anchor
沒收到 valid GNSS，仍會輸出完整失敗證據，不能手動改成通過。
實測時請先在路線起點或 corridor 內等待定位穩定，再開始移動指定距離；距離可以先用
步數、量尺、輪徑或明確地標估算，但必須誠實記錄來源。完成後停在同一條 route corridor
內等待 re-anchor。若場地、任務圖、路線檔或輸入距離不可信，這次結果只能當硬體演練，
不能當正式導航驗收。
若 `--source` / `--provider` 沒有指向實際 odometry/PDR provider，預設
`manual_odometry_delta` / `operator_entered_distance_delta` 只能產生 rehearsal evidence；
不要為了通過 gate 把人工估算距離偽裝成 wheel encoder。
`--raw-anchor-nmea` / `--raw-reanchor-nmea` 只可用於 rehearsal；正式 field proof 必須
由工具直接讀 serial device，讓 GNSS payload 保持 `capture_mode=serial_device`。
若要同一個命令涵蓋「開始後移動」，請設定 `--movement-window-seconds`；report 會保存
`movement_window_seconds`，方便回看這次 operator 有多少時間完成指定距離。

若現場 operator 想少跑一個前置 GNSS capture，可以改用 one-command diagnostic live
field proof wrapper。它會先讀 GNSS anchor，再用 anchor 產生 diagnostic route/corridor，
接著寫 DR delta、讀 re-anchor，最後自動跑 completion gate：

```bash
python3 tools/ins_dr_live_field_proof.py \
  --output-dir /data/scout/providers/ins_dr/live-field-run-001 \
  --mission-id live_field_run_001 \
  --gnss-port auto \
  --readiness-report-json /data/scout/providers/gnss/field-readiness-report.json \
  --gnss-baud 115200 \
  --anchor-duration-seconds 10 \
  --anchor-wait-timeout-seconds 180 \
  --anchor-retry-interval-seconds 2 \
  --heading-evidence-jsonl /data/scout/providers/imu/hiwonder-angle.jsonl \
  --wheel-odometry-jsonl /data/scout/providers/wheel_odometry/wheel-raw.jsonl \
  --wheel-provider scout_wheel_encoder \
  --movement-window-seconds 30 \
  --reanchor-duration-seconds 10 \
  --reanchor-wait-timeout-seconds 180 \
  --reanchor-retry-interval-seconds 2 \
  --corridor-half-width-m 6.0 \
  --pretty
```

中文註釋：`ins_dr_live_field_proof.py` 固定
`hardware_control_scope=diagnostic_live_field_proof_only`，仍然不控制導航、不呼叫
live `/safety/*` mutation、不送 outbound。它會寫出 `route-scaffold-report.json`、
`live-field-proof-report.json`、`operator-events.jsonl`、diagnostic route/mission/map，以及 field-run 目錄下的
`anchor-gnss.jsonl`、`dr-delta.jsonl`、`reanchor-gnss.jsonl`、`field-report.json`、
`proof-manifest.json` 和 `verification-report.json`。正式 completion 仍必須看到
`capture_mode=serial_device`；若用 `--raw-anchor-nmea` / `--raw-reanchor-nmea` 演練，
report 會標示 `raw_nmea_rehearsal_no_serial_required`，completion gate 必須拒絕把它
當成 field proof。
若已經先跑 readiness，live proof 應加 `--readiness-report-json`；它只接受
`ready_for_live_field_proof=true` 且有 `selected_gnss_port` 的 report，並把
`serial_resolution.auto_detection_status=selected_from_readiness_report` 寫入
`live-field-proof-report.json`。若 readiness report 是 `not_ready`、沒有
`selected_gnss_port`、或 operator 另外指定的 `--gnss-port` 與 report 不一致，live proof
會拒絕開始，避免 USB hub 上重新猜錯 serial path。
正式 field proof 應使用 `--wheel-odometry-jsonl` 讀 wheel/encoder raw provider
JSONL；report 會輸出 `dr_evidence_mode=wheel_odometry_jsonl` 與
`wheel_odometry_record_count`，proof manifest 也會把 wheel raw JSONL 放入
`input_refs` checksum。`--distance-delta-m` 仍保留給 rehearsal，但不可和
`--wheel-odometry-jsonl` 混用，也不可搭配 `--source wheel_odometry` 來偽裝正式
wheel evidence。
若 wheel encoder 已直接接到 Scout GPIO，也可以讓 live proof 在 anchor 後直接採集：

```bash
python3 tools/ins_dr_live_field_proof.py \
  --output-dir /data/scout/providers/ins_dr/live-field-run-001 \
  --mission-id live_field_run_001 \
  --gnss-port auto \
  --readiness-report-json /data/scout/providers/gnss/field-readiness-report.json \
  --gnss-baud 115200 \
  --anchor-duration-seconds 10 \
  --anchor-wait-timeout-seconds 180 \
  --anchor-retry-interval-seconds 2 \
  --heading-evidence-jsonl /data/scout/providers/imu/hiwonder-angle.jsonl \
  --wheel-encoder-gpio-capture \
  --wheel-encoder-left-gpio 20 \
  --wheel-encoder-right-gpio 21 \
  --wheel-meters-per-tick 0.0042 \
  --wheel-encoder-capture-duration-seconds 30 \
  --reanchor-duration-seconds 10 \
  --reanchor-wait-timeout-seconds 180 \
  --reanchor-retry-interval-seconds 2 \
  --pretty
```

這條路的時序是 `GNSS anchor -> live wheel encoder capture -> DR delta -> GNSS re-anchor`。
`operator-events.jsonl` 會包含 `wheel_encoder_gpio_capture_start`、
`wheel_encoder_gpio_capture_complete` 與
`movement_window_consumed_by_wheel_encoder_capture`，可用來確認 wheel evidence 不是在
anchor 前偷跑出來的預錄資料。
若 wheel/encoder raw JSONL 只有距離或 ticks、沒有 heading，請加上
`--heading-evidence-jsonl` 指向 `pi_hiwonder_imu_usb_smoke.py` 產生的 raw IMU angle
JSONL。live proof 會先餵入這些 heading payload，再餵入 wheel DR delta；report 會保存
`heading_evidence_payload_count` 與 `heading_evidence_jsonl_paths`，proof manifest 也會把
raw IMU heading JSONL 放進 `input_refs` checksum。這讓 Hiwonder/WIT 的 10 軸姿態資料成為
Scout DR heading baseline，而不是把 vendor fusion 當 primary truth。
現場操作時，先把車停在起點、等待定位穩定，再啟動這支工具；工具完成 anchor 後才開始
移動指定距離。`--movement-window-seconds` 是給 operator 移動與停車的時間；若車還沒
停穩就進入 re-anchor，這次資料容易失敗。移動完成後停車等待 re-anchor，不要在還沒
重新看到可靠 GNSS 前手動宣稱通過。若結果失敗，保留整包輸出資料，優先看失敗檢查名稱，
再回頭確認天線、序列埠、移動距離、heading、route corridor 與 output 目錄是否正確。
若現場 GNSS 會間歇看到 C/N0 但還沒有 fix，請使用 `--anchor-wait-timeout-seconds`
搭配 `--anchor-retry-interval-seconds`。live proof 會在 timeout 內重複 capture anchor，
每次寫入 `anchor_capture_attempt` operator event，直到看到 valid GNSS position 才建立
route scaffold 並開始 DR movement window；若 timeout 後仍沒有 valid fix，report 會保留
`anchor_capture_summary` 與完整 `anchor-gnss.jsonl`，但 `proof_manifest_status` 仍是
`not_created`。
GNSS watch report 也會寫出 `window_stability`，其中包含
`valid_fix_window_count`、`gps_cno_window_count`、`any_cno_window_count`、
`no_rf_window_count` 與 `intermittent_rf_observed`。若 `intermittent_rf_observed=true`，
代表 RF/C/N0 曾經出現但不穩，應優先調整天線朝向、遮蔽物、USB hub/電源與外殼位置；
若 `no_rf_window_count` 等於所有 window，才回到 RF path / antenna bias 的硬體檢查。
移動後的 re-anchor 也可以用 `--reanchor-wait-timeout-seconds` 搭配
`--reanchor-retry-interval-seconds`。live proof 會寫入 `reanchor_capture_attempt` operator
event，report 會保存 `reanchor_capture_summary`；只有看到 valid re-anchor，completion
gate 才能在 `--require-reanchor` 預設開啟時通過。
若一開始 anchor capture 沒有任何 valid GNSS position，工具仍會保留
`anchor-gnss.jsonl`、`operator-events.jsonl` 與 `live-field-proof-report.json`。report
會標示 `failure_stage=anchor_capture`、`anchor_gnss_signal_summary` 與
`proof_manifest_status=not_created`；`anchor_failure_diagnosis.state` 會把
`no_rf_signal_observed` 和 `rf_signal_without_valid_fix` 分開。前者代表 NMEA 有進來但
C/N0 仍空，優先查天線/RF path；後者代表已看到衛星訊號但還沒有 valid fix，應先保持
開闊天空、調整天線位置或延長等待，不要開始 DR 移動。這只是硬體/天線診斷證據，不是
field proof，必須先修好 GNSS fix 或至少讓 readiness gate 看到 valid fix 後再重跑。
工具執行時會把 `Capturing GNSS anchor`、`Movement window started`、`Capturing GNSS re-anchor`
這類 operator guidance 印到 stderr；同一份 timeline 會寫入 `operator-events.jsonl`，
固定 `hardware_control_scope=diagnostic_live_field_proof_operator_guidance_only`，只供人工操作
與事後稽核，不是 safety decision。

中文註釋：`pi_dr_delta_smoke.py` 只產生 diagnostic odometry delta evidence，
固定 `hardware_control_scope=diagnostic_odometry_delta_only`、
`primary_truth_allowed=false`。live observation 可以用 top-level `distance_delta_m`，
也可以放在 `raw.odometry.distance_delta_m` 或 `raw.dr.distance_delta_m`；這些都不會把
原始 `lat/lon` 偽裝成 GPS。
這個步驟的目的只是確認 Scout 能吃到明確位移量，不能代表車輪編碼器、步數估算或姿態
感測器已經完成校正。若輸入距離不可信，後續航位推算也只能當作低信心診斷資料。
field report 會把 DR source 統整到 `dr_distance_source_summary`，並用
`dr_distance_source_failure_count` 清楚標出不可信的 DR 來源。正式 completion evidence
需要 `observation_dr_navigation_allowed=true`；operator-entered distance 的預設結果會是
`observation_dr_navigation_allowed=false`。

Live no-fix DR-only path 的判讀重點：如果先前已經有 reliable GNSS anchor，後續
SensorLog / wheel odometry observation 即使沒有 `lat/lon`，仍可在 `position_estimate`
看到 `source=dead_reckoning`、`primary_truth_source=raw_gnss+dead_reckoning` 與
`pdr_delta_m`。原始 observation 的 `lat/lon` 必須維持空值，避免把 DR estimate 誤標成
raw GPS。

`/safety/observations` direct ingest 也接受 GNSS/DR provider payload batch；operator
手動送入時，response 會帶 `latest_position_estimate`，可直接確認
`source=dead_reckoning`。範例 payload 形狀：

```json
{"payloads":[{"source":"pi_gnss_nmea_smoke","timestamp_s":10.0,"position":{"lat":24.1,"lon":121.2}},{"source":"wheel_odometry","timestamp_s":11.0,"odometry":{"distance_delta_m":3.0,"heading_deg":87.5}}]}
```

中文註釋：這一步仍是 live `/safety/*` mutation，只有 operator 明確開始 prototype
smoke 時才可手動呼叫；preflight、文件測試與 assistant 不得自動送出。

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

Field Wi-Fi OLED status diagnostic:

```bash
python3 tools/pi_wifi_oled_status.py \
  --interface wlan0 \
  --source nmcli \
  --timeout-seconds 10 \
  --bus /dev/i2c-1 \
  --address 0x3c \
  --driver sh1107g \
  --output-jsonl /data/scout/providers/wifi_oled/boot-status.jsonl
```

中文註釋：這支工具適合離開原本 Wi-Fi 後的 field bring-up。它會掃描 Pi 開機後可見
的 SSID，讀取目前 active SSID 與 `wlan0` IPv4 address，並把摘要顯示在 Grove OLED：
`SCOUT WIFI`、`IP ...`、`ON ...`、`AP N` 與前幾個 SSID / signal。若掃描失敗，
OLED 會顯示 `SCAN ERR`，JSONL 會保存錯誤字串。這只做 diagnostic display 與
local evidence，不呼叫 live `/safety/*` mutation、不送 outbound、不改 Phase 1 safety
decision。

若要開機後自動顯示 Wi-Fi 診斷，可在 Scout Pi 上建立 one-shot systemd service：

```ini
[Unit]
Description=Scout Wi-Fi OLED boot status
After=NetworkManager.service
Wants=NetworkManager.service

[Service]
Type=oneshot
WorkingDirectory=/home/alexwang0315/scout-fusion
ExecStart=/usr/bin/python3 tools/pi_wifi_oled_status.py --interface wlan0 --source nmcli --timeout-seconds 10 --bus /dev/i2c-1 --address 0x3c --driver sh1107g --output-jsonl /data/scout/providers/wifi_oled/boot-status.jsonl

[Install]
WantedBy=multi-user.target
```

這個 service 只顯示狀態；不會替 Pi 新增、修改或切換 Wi-Fi 連線。若要解決 field
連線問題，仍應另外設定 NetworkManager profile 或 Scout field AP fallback。

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
