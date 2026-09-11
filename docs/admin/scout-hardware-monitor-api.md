# Scout 硬體監控 API

可運作原型：獨立 API 讀取既有 monitor 的快照與輪替紀錄，沒有重新採樣、發通知、
改門檻或控制硬體的 HTTP 路徑。使用目前 venv 的 FastAPI／Pydantic／Uvicorn，
沒有新增依賴。API 與每分鐘採樣器各有自己的 user systemd service。

## 端點

Scout 主機 base URL：`http://127.0.0.1:9151`。

| 方法 | 路徑 | 用途 |
| --- | --- | --- |
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

`power.flow` 是 `charging / discharging / idle`。`battery_power_w` 正值充電、負值放電，
可用絕對值加方向顯示；不要從 UPS VBUS=0 就推斷 Scout 已斷電。
`power.age_seconds` 是**採樣當時**的 UPS 資料年齡；API 當下的整份快照年齡請看
`freshness.age_seconds`。`power.status=unavailable` 時電池讀值可能全為 null。
GiB = bytes / 1024³。低溫時風扇 0 RPM 不單獨代表故障。
只有 `active_throttle_bits` 表示當下限制；歷史旗標需另標為本次開機曾發生。

歷史 API 的 `items[]` 與 `data` 共用 Snapshot schema，事件為
`{captured_at, events: string[]}`。清單 envelope 提供 `status`, `summary`, `server_time`
與 `meta={limit,count,order,has_more,scan_truncated,skipped_invalid_records}`。
正常空清單回 200；損壞紀錄跳過並標記 `partial`；讀取失敗回 503／`unavailable`。
讀取目前檔及 `.1`～`.3`，每次最多掃描 8 MiB，保留狀況可能不足所要求筆數。
`has_more` 是更早紀錄存在的提示，沒有 cursor 分頁。不可把 60 筆直接標成完整一小時，
要使用採樣時間；圖表缺口保留，不自行補造數據。

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
Host allowlist、無 wildcard CORS、GET 無採樣或通知副作用。未修改採樣器或 Dashboard
既有 API／HTML／CSS／JavaScript，因此沒有跑 Dashboard 瀏覽器／GIS 圖層測試。
Navigation freeze guard 在本 Scout checkout 缺少 `tools/verify_navigation_freeze.py`，
無法執行；保留現有 policy／baseline，僅新增獨立 API，沒有補造或繞過 guard。

未產品化：目前未提供公網驗證／流量限制；請留在私有後端轉接範圍。
API 可辨識採樣停止後的過期資料，整台 Scout 離線則由 Dashboard 顯示連線失敗。
