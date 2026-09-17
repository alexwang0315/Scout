# Scout 硬體監控 API

可運作原型：獨立 API 讀取既有 monitor 的快照與輪替紀錄，沒有重新採樣、發通知、
改門檻或控制硬體的 HTTP 路徑。使用目前 venv 的 FastAPI／Pydantic／Uvicorn，
沒有新增依賴。API 與每分鐘採樣器各有自己的 user systemd service。

## 端點

Scout 主機 base URL：`http://127.0.0.1:9151`。

| 方法 | 路徑 | 用途 |
| --- | --- | --- |
| GET | `/` 或 `/monitor` | 獨立硬體總覽 UI，與 API 使用同一個 9151 埠 |
| GET | `/api/v1/hardware-monitor/status` | 最新快照與查詢當下重新計算的資料年齡 |
| GET | `/api/v1/hardware-monitor/history?limit=60` | 最近 N 筆採樣，回傳由舊到新；預設 60，最多 1440 |
| GET | `/api/v1/hardware-monitor/events?limit=50` | 最近 N 批狀態變更事件，由舊到新；預設 50，最多 200 |
| GET | `/healthz` | API 程序存活，不代表硬體正常或採樣器仍在運作 |
| GET | `/openapi.json` | 完整可機器讀取的欄位／型別／HTTP 回應契約 |
| GET | `/docs` | 可在瀏覽器操作的 OpenAPI 文件 |

```bash
curl --fail-with-body http://127.0.0.1:9151/api/v1/hardware-monitor/status
curl --fail-with-body 'http://127.0.0.1:9151/api/v1/hardware-monitor/history?limit=60'
```

## 最新狀態契約

`schema_version` 固定為 `scout.hardware-monitor.api.v1`。欄位型別以 `/openapi.json`
與 `scout_hardware_monitor_api.py` 的 Pydantic models 為準。

| 欄位 | 意義 |
| --- | --- |
| `status` | `ok / warning / critical / stale / unavailable`，UI 主要狀態 |
| `server_time` | 此次 API 回應的 UTC 時間 |
| `summary` | 精簡的狀態摘要 |
| `freshness.state` | `fresh / stale / missing / invalid / unreadable` |
| `freshness.captured_at` | 監控器採樣時間 |
| `freshness.age_seconds` | 查詢當下的快照年齡；不可用時為 null |
| `freshness.sample_interval_seconds` | 60，刷新 API 不會加速採樣 |
| `freshness.stale_after_seconds` | 150，逾時表示採樣可能停止 |
| `data` | 最後有效的已驗證快照；不存在或格式錯誤時為 null |
| `next_steps` | 硬體告警或監控失聯時的操作建議 |
| `read_only` | true |

資料過期回 HTTP **503**，仍保留 `data` 供顯示最後讀值；UI 必須先處理頂層
`status` 與 `freshness`，不可把 `data.status=ok` 的舊資料畫成現在正常。
找不到／無法讀取／格式錯誤／超前超過 5 秒的快照，也回具相同 envelope 的 503，
但 `data=null`。HTTP 503 附 `Retry-After: 60`，UI 應讀取 JSON body。
硬體 `warning` 或 `critical` 仍回 HTTP **200**：API 與採樣本身正常，硬體有告警。

所有監控結果回 `Cache-Control: no-store`。錯誤回應不暴露檔案路徑或 traceback。
缺失的讀值使用 null；前端不可用 `value || 0` 將未知改成零。

## 快照的 UI 欄位

| 區塊 | `data` 下的欄位 |
| --- | --- |
| 電池 | `power.status`, `battery_percent`, `flow`, `battery_power_w`, `battery_voltage_mv`, `battery_current_ma`, `cell_voltage_mv`（後六者均位於 `power`） |
| 供電 | `power.ext5v_v`, `power.ups_vbus_power_mw`, `power.active_throttle_bits`, `power.historical_throttle_bits` |
| 記憶體 | `memory.used_bytes`, `total_bytes`, `available_bytes`, `used_percent`, `swap_used_bytes`, `swap_total_bytes`（均位於 `memory`） |
| 磁碟 | `disks[]` 的 `mount`, `device`, `used_percent`, `available_bytes`, `total_bytes`, `inode_used_percent`, `read_only` |
| 溫度／風扇 | `sensors[]` 的 `name`, `source`, `temperature_c`, `rpm`；以 `source` 作穩定識別，不能只按 `name` 合併 NVMe 感測器 |
| CPU／系統 | `cpu_used_percent`, `cpu_count`, `load_average[1/5/15 分鐘]`, `uptime_seconds`, `host` |
| 告警／門檻 | `alerts` 是 `{key: {severity, message}}`；另有 `thresholds` 與 `errors` |
| 連線／裝置 | `inventory.sections` 包含 `network`, `bluetooth`, `usb`, `pcie`, `i2c`, `gpio`, `serial`；舊採樣為 null |

`power.flow` 是 `charging / discharging / idle`。`battery_power_w` 正值充電、負值放電，
可用絕對值加方向顯示；不要從 UPS VBUS=0 就推斷 Scout 已斷電。
`power.age_seconds` 是**採樣當時**的 UPS 資料年齡；API 當下的整份快照年齡請看
`freshness.age_seconds`。`power.status=unavailable` 時電池讀值可能全為 null。

### 電池與主機供電分離（2026-09-13）

`power.status` 保留既有 `ok / unavailable`：只有完整電源資料均可讀才是 ok。
新增選填 `ups_status`、`supply_status`，值為 `ok / unavailable`；null 代表舊採樣，
呼叫端可回到舊 `power.status` 判讀 UPS 可讀性；舊紀錄若仍有有限的主機電壓／旗標，
應保留為觀測值，不因缺少新狀態欄位而隱藏，也不可因此宣稱整體正常。
UPS I²C 與主機 PMIC／欠壓旗標獨立驗證。

- UPS 失敗：電池、充放電、電池功率／電壓與 UPS VBUS 維持 null；有效的
  `ext5v_v`、`active_throttle_bits`、`historical_throttle_bits` 仍保留。
- 主機供電失敗：有效 UPS 電池讀值與低電量告警不受影響。PMIC 電壓與降頻旗標
  也各自保留有效值；`supply_status=unavailable` 可能仍有部分有效讀值。
- `ups_error_code`、`supply_error_code` 為 null 或固定代碼：
  `communication_error / invalid_telemetry / stale / missing / unreadable`。
  不公開原始 exception、指令或檔案路徑。UPS communication_error 顯示
  「UPS 通訊失敗（I²C），電池讀值未知」，不能推論接線或 UPS 本體故障。
- 所有值只來自同一筆既有採樣，不查找舊成功數值填補；來源過期／時間無效時
  兩組都不可用。整份快照 stale 503 仍保留最後 data，必須明確標示過期。
- 頂層告警仍使用 `data.alerts`；部分失敗保留 `power_telemetry` 警告，
  可讀的欠壓／低電量等告警各自生效。5V 可讀不代表 UPS 通訊恢復。
- I²C `telemetry_device` 與電池歷史曲線以 `ups_status` 判斷，不因主機供電
  單獨失敗而隱藏有效的 UPS 觀測；舊紀錄維持原判讀。

GiB = bytes / 1024³。低溫時風扇 0 RPM 不單獨代表故障。
只有 `active_throttle_bits` 表示當下限制；歷史旗標需另標為本次開機曾發生。

歷史 API 的 `items[]` 與 `data` 共用 Snapshot schema，事件為
`{captured_at, events: string[]}`。清單 envelope 提供 `status`, `summary`, `server_time`
與 `meta={limit,count,order,has_more,scan_truncated,skipped_invalid_records}`。
正常空清單回 200；損壞紀錄跳過並標記 `partial`；讀取失敗回 503／`unavailable`。
讀取目前檔及 `.1`～`.3`，每次最多掃描 8 MiB，保留狀況可能不足所要求筆數。
`has_more` 是更早紀錄存在的提示，沒有 cursor 分頁。不可把 60 筆直接標成完整一小時，
要使用採樣時間；圖表缺口保留，不自行補造數據。

### 裝置清單契約

`data.inventory` 的共同欄位為 `captured_at`, `status=ok/partial`, `sections`,
`read_only=true`, `active_scan_performed=false`, `gpio_value_sampling_performed=false`。
這是 v1 的新增選填欄位，既有資料和呼叫端仍相容。

每個 section 回傳 `status=ok/partial/unavailable`, `summary`, `items[]`, `notes[]`, `errors[]`。
section 的 `ok` 表示資訊讀取成功，**不等於每個裝置功能正常**。每個 item 為：

```text
{id, name, state, driver, properties: {欄位: 純量或字串陣列}, lines: GPIO 線路陣列}
```

`state` 可為 `present`, `connected`, `disconnected`, `blocked`, `powered_on`,
`powered_off`, `observed`, `unknown`。GPIO `lines[]` 含 `offset`, `name`, `direction`,
`consumer`, `active_low`, `value=null`，不會要求線路或讀取／設定高低電位。

| Section | 主要內容 |
| --- | --- |
| network | 只列實體介面；properties 包含 kind=wifi/ethernet、operstate、ipv4/ipv6；Wi-Fi 另有 ssid、signal_dbm、frequency_mhz、tx_bitrate_mbps、soft_blocked、hard_blocked |
| bluetooth | kind=controller 的電源／配對／探索旗標，以及 kind=connected_device 的目前連線；不列周邊探索快取 |
| usb | idVendor、idProduct、manufacturer、speed、root_hub、interface_drivers；區分根集線器與外接裝置 |
| pcie | vendor、device、class、device_class、vendor_name、current_link_speed、current_link_width，加上 driver |
| i2c | kind=adapter / registered_device / telemetry_device；UPS 0x2d 來自既有有效電源資料，不另執行 I²C 交易或位址掃描 |
| gpio | 控制器／線路數、方向與 consumer；使用 gpiodetect/gpioinfo，沒有 gpioget/gpioset 或 export/unexport |
| serial | UART／USB serial 的 device_node；不開啟裝置或讀取位置資料 |

資料未讀到要顯示未知。I²C 沒被系統登錄的裝置可能仍已接上；GPIO direction 並非電位。
UI 將裝置名稱、SSID、consumer 等值當作純文字處理，不能插入 `innerHTML`。

## 接到 Dashboard

建議 UI 使用**同源相對路徑** `/api/v1/hardware-monitor/...`，由 Dashboard 後端
轉接固定 upstream。API 只綁 Scout loopback，未對 LAN／公網公開，也沒有開 wildcard
CORS。後端轉接應沿用 Dashboard 的登入／權限，固定上游與 route allowlist，設短 timeout，
保留 HTTP 503 的 JSON，不讓用戶輸入任意 upstream URL 或檔案路徑。

- Dashboard 後端直接在 Scout 主機：upstream `http://127.0.0.1:9151`。
- Dashboard 後端在 Mac：用已建立的 Mac loopback SSH forward，upstream 同樣是
  `http://127.0.0.1:9151`；此 forward 目前為暫時連線，斷線後要重建。
- Dashboard 後端在容器：容器的 `127.0.0.1` 不是 Scout 主機。先確認部署方式，
  使用私有的代理／SSH forward，或把下列 router 放進有授權唯讀掛載資料的 backend；
  不要以把此無驗證 API 公開到 `0.0.0.0` 解決連線問題。

同一主機上的 FastAPI Dashboard，也可直接掛載獨立 router：

```python
from pathlib import Path
from scout_hardware_monitor_api import create_hardware_monitor_router

app.include_router(create_hardware_monitor_router(
    state_dir=Path("/home/alexwang0315/.local/state/scout-hardware-monitor"),
))
```

此函式不 import Dashboard／Scout runtime、不載入 `.env`、不啟動採樣器。
資料目錄為擁有者私有，其他執行帳戶不能任意讀取；不要把權限放寬為全機可讀。

## 安裝／操作

```bash
/home/alexwang0315/work/scout-fusion/venv/bin/python \
  /home/alexwang0315/work/scout-fusion/scripts/install-scout-hardware-monitor-api.py
systemctl --user status scout-hardware-monitor-api.service
# 暫停 API；每分鐘採樣器仍繼續
systemctl --user disable --now scout-hardware-monitor-api.service
```

安裝副本：`~/.local/lib/scout-hardware-monitor/api.py`。API 使用安裝當下的 venv Python；
清除此 venv 前須重新指定執行環境。安裝器拒絕覆蓋同名 service 或副本。
總覽頁資產複製到相同目錄的 `static/`，以 `--static-dir` 指定。
API unit 的 `Wants` 包含採樣 service 與 timer，`After` 先等初次採樣完成。
兩個可啟用 unit 均已 enabled，且 Scout `Linger=yes`；開機會自動帶起，不需要登入 shell。

Mac 文件：`http://127.0.0.1:9151/docs`。若暫時 forward 已斷，Mac 可自行開啟：

```bash
ssh -N -L 127.0.0.1:9151:127.0.0.1:9151 \
  -o BatchMode=yes -o StrictHostKeyChecking=yes -o ExitOnForwardFailure=yes \
  alexwang0315@scout.local
# 另開一個 Mac 終端機
open -a "Google Chrome" 'http://127.0.0.1:9151/docs'
```

## 驗證紀錄

2026-09-11：API 與 monitor 合計 **28 項測試通過**。涵蓋唯讀、過期／缺失／損壞資料、
503 body、資料欄位過濾、輪替歷史、查詢上限、無寫入方法、Host 檢查及 router 掛載。
既有 Starlette/AnyIO 有一項 deprecation warning，未改無關依賴。
systemd unit 驗證通過。真實 HTTP 的 status／history／events／OpenAPI 均回 200，
首次驗證取得 47 筆真實採樣。Mac 經 SSH forward 讀取 `/healthz` 與 `/docs` 成功，
已成功送出 Google Chrome 開啟文件請求。
09:41 再驗證時可讀 52 筆歷史，API 記憶體約 36.9 MiB，採樣 timer 仍為 active；
安裝副本與 repo 來源 SHA-256 一致。收據存於
`~/.local/state/scout-hardware-monitor/api-verification.json`。

安全檢視：固定檔名、只讀目錄、Pydantic 白名單欄位、有限檔案讀取、loopback 綁定、
Host allowlist、無 wildcard CORS、GET 無採樣或通知副作用。既有 Dashboard／Navigation／GIS
檔案未更動；新增獨立總覽 UI 的瀏覽器檢查另列如下。
Navigation freeze guard 在本 Scout checkout 缺少 `tools/verify_navigation_freeze.py`，
無法執行；保留現有 policy／baseline，僅新增獨立 API，沒有補造或繞過 guard。

未產品化：目前未提供公網驗證／流量限制；請留在私有後端轉接範圍。
API 可辨識採樣停止後的過期資料，整台 Scout 離線則由 Dashboard 顯示連線失敗。

## 硬體清單與總覽頁擴充（2026-09-11）

- 真實裝置清單耗時約 0.07 秒；讀到 2 個實體網路介面、1 個藍牙控制器、
  4 個 USB 根集線器／0 個外接 USB、10 個 PCIe 裝置／橋接器（含 Hailo 與 NVMe）、
  3 條 I²C、5 個 GPIO 控制器／111 線路、3 個 UART／序列節點。
- `36` 項針對性 Python 測試通過；涵蓋被動偵測、錯誤隔離、舊快照相容及啟動 unit 依賴。
- 真實 Chromium／Playwright 在預覽與常駐 9151 都通過：1440/1024/768/320px、
  GPIO 展開後刷新維持展開、鍵盤操作、warning/critical/stale/unavailable/unknown/offline/empty，
  以及將 API 文字當作純文字的 XSS fixture；無 pageerror、無橫向頁面溢出。
- pnpm 入口的既有快取缺少 pnpm.cjs；直接執行 package.json 同一組 lint/typecheck/test 腳本
  全部通過（typecheck 1 項、test 17 項），並另外檢查新增 JS 語法。沒有更動套件或工具鏈。
- systemd unit 驗證通過，已驗證 API service 重啟、啟動依賴及其後每分鐘自動採樣。
  沒有重開整台 Scout，避免中斷其他正在運作的任務。
- 11:36 真實採樣結果為 ok；採樣器記憶體峰值約 17.4 MiB、CPU 時間約 229 ms。
  API 當時記憶體約 36.9 MiB。Mac 讀取 `/monitor` 回 200，已送出 Chrome 開啟請求。
- 更新前備份：`~/.local/state/scout-hardware-monitor/backups/20260911T033515Z/`。
  瀏覽器收據與圖：`/tmp/scout-hardware-monitor-browser-live/`。

Navigation guard 在擴充前後仍因本 checkout 缺檔無法執行，沒有修改或建立替代 guard。
API GET 只讀快照；背景採樣只做本機 metadata 查詢，不掃描 Wi-Fi／藍牙／I²C，不做配對、
GPIO line request、硬體寫入或網路設定變更。
