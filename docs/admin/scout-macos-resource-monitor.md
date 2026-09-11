# Scout macOS Resource Monitor

這是一個 MacBook 本機的只讀資源觀測工具，給 Scout 的 Dashboard、QGIS、模型與其他工作負載做現場診斷。它不是 Scout 的安全決策、任務控制或硬體控制面板。

## 啟動

在 Scout checkout 根目錄執行：

```bash
./tools/run_macos_resource_monitor.sh
```

然後開啟 <http://127.0.0.1:8877>。預設只監聽 loopback；若要換 port：

```bash
./tools/run_macos_resource_monitor.sh --port 9877
```

按 `Ctrl-C` 停止。也可以直接使用既有 Python：

```bash
./venv/bin/python tools/macos_resource_monitor.py --host 127.0.0.1 --port 8877
```

## Dashboard 分頁

使用 Mac Dashboard workspace runtime 時，開啟 `http://127.0.0.1:9099/admin/dashboard`，在 `System` 底下選擇 `scout monitor`。這個分頁透過 Dashboard 同源路徑讀取本機 collector，並由 Dashboard 後端唯讀代理 Scout 硬體 API；不需要另外啟動 8877。8877 仍可作為獨立 macOS monitor 頁面使用。

## Scout 硬體監控整合

`scout monitor` 內的「硬體監控」區塊使用 Dashboard 後端固定代理下列 Scout API：

- `GET /api/v1/hardware-monitor/status`
- `GET /api/v1/hardware-monitor/history?limit=60`
- `GET /api/v1/hardware-monitor/events?limit=50`

Dashboard server 在 Mac 上以 `http://127.0.0.1:9151` 作為本機 Scout upstream；瀏覽器只發送同源相對 GET，不直接連接 9151。狀態資料每 60 秒更新，離開頁面會清除輪詢並 abort 請求，手動重新讀取也只使用 GET。

已整合到既有 9099 服務，直接開啟：

```bash
open -a "Google Chrome" "http://127.0.0.1:9099/admin/dashboard#scout-monitor"
```

不需要再啟動另一個 9099 程序。2026-09-11 已確認 Dashboard 在 Mac 原生程序中執行，9151 是暫時 SSH 轉接；若以後移到容器，容器的 localhost 並非 Mac 或 Scout，必須先確認後端可達的固定 upstream。本機 Dashboard 使用既有 loopback 存取方式，沒有額外登入層。

狀態、告警門檻與告警內容分別以 `status.data`、`data.thresholds`、`data.alerts` 為準。HTTP 503 的 `status=stale` 會顯示「資料已過期」，即使回應仍帶有上一筆 `data.status=ok`；null 顯示「未知」，空的事件 items 不補造紀錄。電池功率正值標示充電、負值標示放電；同名 NVMe 感測器會以 source 分列，風扇 0 RPM 不單獨視為故障。

503 `unavailable` 會顯示斷線，保留值會標示為上次採樣。資料年齡每秒更新，超過 150 秒會在下一次 API 輪詢前先顯示過期。三個請求獨立呈現，12 秒逾時後可再次重新讀取；後端 upstream 請求逾時為 8 秒。歷史圖以真實採樣時間定位，null 或缺失採樣會斷線。單獨開啟的 8877 macOS 頁面不啟動 Scout 硬體 API 輪詢。

針對性驗證：

```bash
./venv/bin/python -m pytest -q tests/test_hardware_monitor_proxy.py tests/test_dashboard_scout_monitor.py tests/test_macos_resource_monitor.py
node tools/dashboard_scout_monitor_browser_smoke.js --base-url http://127.0.0.1:9099
node tools/dashboard_scout_monitor_state_smoke.js http://127.0.0.1:9099
```

## 顯示內容

- CPU：macOS `top` 的 user/system/idle 與 load average。
- 記憶體：`vm_stat` page counters、估算使用率，以及 `memory_pressure -Q`（若 OS 提供）。
- 系統磁碟：`/` 的 total/used/free。
- 電源與效能限制：`pmset -g batt`、`pmset -g therm`。
- Scout workload：從 `ps` 找出符合 Scout matching scope 的 process，只顯示安全化的 label、PID、CPU、記憶體、RSS 與 elapsed time，不回傳完整 command line。
- 最近 30 次 browser polling 的 CPU/記憶體趨勢；樣本只存在瀏覽器記憶體，不寫入檔案。

CPU temperature 不會由此工具收集：它不啟動通常需要 elevated privilege 的 `powermetrics`。因此 thermal 區塊呈現的是 macOS 已公開的效能限制訊號，而非溫度真值。

## Scout process matching

預設會比對 `scout-fusion`、`scout_ai_os`、Dashboard/QGIS runtime、`scout_pi_runtime` 與 `ollama`。若本機 workload 使用不同命名，可在啟動前覆寫：

```bash
SCOUT_MONITOR_PROCESS_MATCH="my-scout-worker,ollama" \
  ./tools/run_macos_resource_monitor.sh
```

這個環境變數只改變觀測範圍，不會啟動或修改任何 process。

## API

- `GET /api/health`：服務是否啟動。
- `GET /api/snapshot`：一次完整資源快照。

所有 endpoint 都是 GET。Collector 不持久化資料、不讀取 `.env`、不連接外部服務，也不會改變 Scout runtime safety truth、任務狀態、通知、硬體或資料庫。若個別 macOS command 不可用，snapshot 會保留 `status=unavailable` 的局部結果，而不是用猜測值補齊。
