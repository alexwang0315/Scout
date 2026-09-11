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
