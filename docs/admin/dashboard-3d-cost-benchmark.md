# Dashboard 額外圖層與同步成本 — 同一台 Mac 實測

2026-09-10。僅量測，未更換引擎、未修改既有 Dashboard 或啟停正式 runtime。

**WORKING PROTOTYPE：完成 18 次真實 Mac 擷取與一致性驗證。效能判讀為方向性，未達隔離系統負載的因果量測。**

建議目前保留 MapLibre，先驗證省略不必要的中心同步。三個區塊都觀察到同步造成額外繪製，並有一致的更新率下降。

**重要量測限制：** 11:55 的系統快照回報 `CPU_Speed_Limit = 38`、已使用 swap 5,117.25 MiB（約 5 GB）。仍使用 AC 電源、電量 100%；限速原因未確認，且沒有逐輪 CPU／溫度紀錄。後段基準也變慢，所以不能把所有載入／FPS／RSS 差值歸因於圖層；尤其不能把較低的 RSS 解讀成更少的記憶體配置。

擷取時間：2026-09-10 11:43:33–11:57:46（台灣時間）。以下均為三輪中位數，括號為 min–max。

| 組別 | 旋轉 FPS〔範圍〕 | 平移 FPS | 首次就緒 s | 峰值 RSS MiB |
| --- | ---: | ---: | ---: | ---: |
| 基準：DEM ＋路線 | 55.69〔43.34–59.83〕 | 59.83 | 3.506 | 881.6 |
| ＋山體陰影 | 45.70〔44.31–59.90〕 | 54.71 | 3.579 | 922.9 |
| ＋Rudy 底圖 | 44.12〔39.23–50.46〕 | 56.99 | 4.188 | 930.8 |
| ＋Dashboard 候選圖層 | 39.20〔34.08–41.56〕 | 51.74 | 4.264 | 952.4 |
| ＋固定的第二張 2D 地圖 | 40.70〔33.59–40.99〕 | 51.69 | 4.215 | 972.0 |
| ＋原有地圖同步 | 33.43〔29.35–35.75〕 | 37.52 | 5.705 | 960.1 |

各項成本以同區塊配對差值判讀，不能把上表兩個中位數直接當成配對結果：

| 新增項目 | 旋轉 FPS 配對差值：中位數〔min–max〕 | 平移 FPS 配對差值：中位數〔min–max〕 |
| --- | ---: | ---: |
| ＋山體陰影 | +0.07〔-11.38–+2.35〕 | +0.09〔-5.18–+0.43〕 |
| ＋Rudy 底圖 | -6.47〔-9.45–-0.19〕 | +0.77〔-2.07–+2.28〕 |
| ＋Dashboard 候選圖層 | -5.14〔-11.25–-2.56〕 | -5.25〔-18.33–-4.81〕 |
| ＋固定的第二張 2D 地圖 | -0.49〔-0.86–+1.78〕 | +2.89〔-0.05–+4.46〕 |
| ＋原有地圖同步 | -5.24〔-7.27–-4.24〕 | -13.98〔-14.18–-8.40〕 |

Rudy 與候選圖層的旋轉成本，以及同步的旋轉／平移成本，在三個區塊都呈現下降；山體陰影的單獨成本未能從系統波動明確分離。固定的第二張地圖並未帶來穩定的大幅下降。這些是現況觀察，不是統計顯著性或 engine replacement 的證明。

固定中心的 12 秒旋轉中，原有同步的 `2d.jumpTo` 中位數 **407 次**（357–433），第二張地圖仍有 **370 次 render**（321–396）。同步 JavaScript 累計 **469.8 ms**（361.3–469.9），其中 peer jumpTo 約 450.3 ms；兩者互有包含。平移時同步約 **497.1 ms**（420.5–696.1），peer jumpTo 454 次。非同步組 peer jumpTo 為零。主地圖每段量測只有 5 次 moveend（起始 reset ＋四段運動），沒有以測試驅動方式製造逐幀主地圖 moveend。

完整單圖的 Dashboard DOM 建立中位數 686.9 ms，QGIS 過濾 10 次共 458.2 ms；candidate collection 6 次。雙圖分別增加為 12 次過濾、7 次 collection、2 次 style 建立。這是實際啟動準備成本；不能把互有包含的函式時間相加。

下一個最小步驟：在這個獨立回放加一個「中心未改變就略過 2D jumpTo」對照，先於 CPU／記憶體負載穩定時重測並逐輪記錄系統狀態，再決定是否修改 Dashboard。引擎更換目前沒有足夠依據。

證據： [原始 18 輪紀錄](../../outputs/evals/dashboard-3d-cost/mac-measurement-2/report.json)、[重算分析](../../outputs/evals/dashboard-3d-cost/analysis.json)、[系統負載快照](../../outputs/evals/dashboard-3d-cost/mac-end-system-state.txt)、[來源完整性](../../outputs/evals/dashboard-3d-cost/source-integrity.json)。
原始擷取 SHA-256：`75ef3feb6d36e4a8e25feaebaf2075262af8895297cf3a022fc04c472a8b7622`。

18 輪 console error／warning、HTTP error、未解決的 network failure 均為零。另有 **144 次 CDP 確認的瓦片 GET 取消**，保留 URL 與事件；最後所有 map tiles／DEM 皆 ready。畫布、相機、mesh 128、初始 LOD 12–14、運動觀察 LOD 11–14、中心高程與來源 hash 的 18 輪一致性 PASS。

## 比較範圍

使用原始 `docs/admin/scout-dashboard-v0.1.html` 的實際函式與現有 MapLibre
6.2.0 vendor。實驗服務只在回應中移除正常 DOMContentLoaded 啟動流程，注入
唯讀的 Workspace 證據及量測包裝；原始檔案沒有改寫。完整 Dashboard DOM
仍實際建立，背景 API、正常 Workspace 準備、worker 與導航控制均未啟動。

六組依序增加負擔，各三輪、三個平衡區塊。區塊順序為：
base / hillshade / rudy / full / split_static / split_sync；反向順序；
rudy / split_sync / base / full / hillshade / split_static。

| 組別 | 3D 場景 | 原生 style 圖層數 | 地圖數 |
| --- | --- | ---: | ---: |
| base | DEM、路線及其 halo | 3 | 1 |
| hillshade | 再加入既有 hillshade | 4 | 1 |
| rudy | 再加入既有 Rudy 快取底圖 | 5 | 1 |
| full | 完整 Dashboard structure lens 候選圖層 | 26 | 1 |
| split_static | 相同完整 3D，加固定中心的 2D 地圖 | 26／張 | 2 |
| split_sync | 相同雙地圖，啟用原有中心同步函式 | 26／張 | 2 |

不是所有 26 層都有資料。實際完整組為一條 prepared route、43 個 QGIS
terrain feature sample；事件來源為空，其他部分線及風險圖層也未填入人工
資料。不能外推成大量事件、河網或所有 lens 的成本。

所有組別皆保留實際 Dashboard DOM、候選 collection 與 QGIS 過濾準備。
ablation 發生在 style / GeoJSON 提交邊界，因此圖層差值不包含「省掉整段
候選準備」的效益。各準備函式的呼叫數及同步執行時間另外記錄；巢狀時間
不可相加。QGIS browser state 只保留地圖所需資料，未重現無關 worker 控制。

## 真實來源與限制

資料只讀取使用者指定的
`/home/alexwang0315/workspace/dongqing_batongguan_historic_trail_newImport`。

- 使用既有 `outputs/navigation/navigation_terrain_intelligence.json`，編譯時間
  2026-09-08T05:21:36Z；SHA-256
  `d8d965f8858fa938b686a1f68b5717f257e297197f7028e624038f7ec4d2c45d`。
  目前唯讀介面回報 `not_prepared`，故明示為既有投影回放，沒有重新編譯或
  宣稱是目前有效導航狀態。
- Dashboard 自己的路線投影包含 **240 個展示取樣點**，metadata 的 source_count
  為 4,291。保留這個既有結果，不改取樣、不重算正式指標。它不是前次獨立
  引擎測試的 5,768 點 GPX 場景，兩次 FPS／載入時間不能直接相減。
- 本機 54 張 Terrain RGB PNG，Z13、256 × 256，來源 DEM 20 m；垂直基準
  `unknown`。source fingerprint：
  `5bf9edd54b7ac4fc21dbd51cb74e7af1d6b117ef4e4a788245d4a701eb30e498`。
  使用既有原生 terrain provider 和 LOD，不把 raster 冒充其他 terrain 格式。
- QGIS 既有 run：`qgis-worker-20260908T015858039770Z-0043021dd2`。
- 原生高倍率 Rudy 快取缺瓦片，預檢正確失敗並保留紀錄。最終使用既有
  `rudy-twmap` 完整 prepared cache（402 PNG、Z5–14），**只在實驗 style
  明示上限 Z14**。沒有下載補洞，沒有更改正式底圖設定，沒有降低 DEM 細節。

所有實驗結果為 visualization_only、candidate_only；runtime_safety_truth
始終為 false。GPX、CP、路線基準及 Workspace 原始資料均維持原位。

## 量測方法

同一台 MacBookPro14,1、i5-7360U／Iris Plus 640、8 GiB RAM，macOS 13.7.8，
既有 Chrome 152.0.7977.83，實際 ANGLE Metal 硬體 renderer；開始時 AC 電源。
每輪新建獨立 Chrome profile，僅關閉本工具開啟的實例，既有使用者 Chrome
不變。HTTP cache 關閉，OS／伺服器快取不清除；沒有控制機器熱狀態。

viewport 1280 × 800，DPR 1；主地圖 960 × 640，Z14、pitch 45°、相同
prepared route 中點、exaggeration 1。即使沒有第二張圖，主地圖也不放大。
第二張 2D 地圖為 320 × 640、Z12，保留 Dashboard 原有 2D／3D zoom 獨立語意。
驗證實際 mesh size、整段運動觀察到的 LOD、中心高程、來源 hash 及圖層數。
這是原生距離自適應 LOD，不宣稱整個畫面都達到 DEM 原始像素細節。

各輪先校準 90 次 idle requestAnimationFrame；旋轉與平移各暖機 4 秒後記錄
12 秒。使用原生 `easeTo` 的四段連續運動，非每幀 `jumpTo`，避免人工製造
主地圖 moveend 風暴。旋轉為四個 90°；平移為固定矩形，偏移 0.008° 經度／
0.006° 緯度。頁面必須持續在前景、尺寸不變、最後 tiles loaded 與 DEM ready。

FPS、p95 與更新缺口由真實 render 時間戳重算。整段缺口估計沿用已驗證的
whole-window refresh estimator，**不是 compositor 確認的物理螢幕掉幀率**。
同步 callback 只量同步 JavaScript 執行時間，不包含後續排程、worker／GPU
繪製；後者反映在總幀節奏。巢狀 callback 計時不得相加。

這次同步成本涵蓋原有地圖中心同步、peer moveend、相機記錄及相關 DOM
標記，未量測 sidebar 點選造成的整頁重建，亦未量測正式 runtime 的即時資料
回補。固定 DPR 1 是控制條件，不能直接外推到 Mac Retina DPR 2 的 fill rate。

首次就緒從 navigation start 起，包括實驗 HTML／共同證據經私人 SSH 傳輸、
Dashboard DOM、style、瓦片完成及 GPU finish。這不是完整正式 Dashboard
含所有 bootstrap API 的實際啟動時間。

Chrome 程序樹 RSS 每 500 ms 取樣，含 blank、ready、final 與 peak；RSS
可能重複計入共享頁，不是 dedicated VRAM。主頁 JS heap 另外記錄，未涵蓋
所有 worker／native／GPU allocation。每組只有三輪；區間是 min–max，不是
信賴區間。各額外成本以同區塊配對差值提供，避免只比較兩個孤立最佳成績。

請求限定同一私人 loopback origin，禁止所有非 GET／HEAD 及對外請求。
記錄 console、HTTP、failed requests。只有 CDP 明確標記 cancelled 的瓦片
GET `net::ERR_ABORTED`，且最終地圖完整就緒，才獨立列為視角變更期間的
取消請求；不隱藏 404／5xx、WebGL 錯誤或缺失地形。

## 重現與入口

從 Scout repo 開獨立本機服務（正式 runtime 不參與）：

```sh
./venv/bin/python tools/dashboard_3d_cost_app.py \
  --project-root /home/alexwang0315/workspace/dongqing_batongguan_historic_trail_newImport \
  --evidence-dir outputs/evals/dashboard-3d-cost --port 9129
```

透過既有 SSH 身分將 Mac loopback 19129 接至 Scout loopback 9129。
Mac 使用既有 Node、Playwright 與 Chrome：

```sh
node tools/dashboard_3d_cost_benchmark.cjs \
  --playwright /Users/alexwang0315/scout-fusion/node_modules/playwright \
  --url http://127.0.0.1:19129 --output /tmp/scout-dashboard-cost-new-capture
```

加 `--preflight` 只做六組載入預檢。完整量測後以保留的原始紀錄分析：

```sh
node tools/dashboard_3d_cost_analyze.mjs capture/report.json analysis.json system-state.txt
```

實驗入口 `/dashboard-cost?case=split_sync&projectId=dongqing_batongguan_historic_trail_newImport`。
結果頁 `/dashboard-cost/results.html`，支援切換旋轉／平移、載入與 RSS 指標。

Mac 開啟命令（本機私人 tunnel 有效時）：

```sh
open -a "Google Chrome" "http://127.0.0.1:19129/dashboard-cost/results.html"
```

## 修改與驗證

新增 `tools/dashboard_3d_cost_{app.py,benchmark.cjs,analyze.mjs}`、
`docs/admin/experiments/dashboard-3d-cost/` 與本報告。
擴充 `tests/test_scout_gpx_3d.py`，新增 `tests/dashboard_3d_cost.test.mjs`。
既有 Navigation HTML、共享 helper、MapLibre vendor 與圖層契約不變。

- Mac cached preflight 六組 PASS；完整實測 18 輪 PASS，18 輪地形／資料／相機一致性 PASS。效能因果判讀仍為 DIRECTIONAL_ONLY，見前述 CPU／swap 限制。
- Mac 結果頁瀏覽器實測：桌面 1280 × 800、手機模擬尺寸 390 × 844 均 PASS；六組與五種指標切換、無水平溢出、console／network 錯誤為零。這是結果頁的手機檢查，3D 成本量測僅限固定桌面條件，未宣稱測過實體手機 GPU。
- Python focused tests：9 passed（包含既有 GPX 測試與新增 stale replay／HTTP 唯讀／錯誤地形處理）。Node 分析測試：3 passed，涵蓋原始樣本重算、配對區塊、拒絕未完成／不一致／軟體 GPU／錯誤同步證據。
- 既有 pnpm lint、typecheck（1 passed）、test（17 passed）通過。保留既有 AnyIO BlockingPortal deprecation warning；另對新增 JavaScript 做 syntax check。
- 28 個原始來源檔、468 個回放來源、5 個擷取工具／共用模組雜湊維持一致；18 張 Mac 截圖與原始 report 的 Mac／Scout SHA-256 相同。
- Navigation freeze guard 前後均為 INVALID_BASELINE，**不是 PASS**：本 checkout 缺 guard／baseline；使用 sibling guard 指向本 repo、以 report-only 執行，未建立或變更基線。另以既有來源檔案雜湊驗證未改動。
- 32 層共享 GIS gate：NOT APPLICABLE，未更動正式圖層契約／準備流程；未跑完整 repository／production qualification suite。
- 已從 Mac 確认 HTTP 200，並自動以既有 Chrome 開啟結果頁，觀察到相符 URL 與標題。結果預覽及 Mac loopback forward 為本次獨立 transient services、8 小時期限；沒有公開部署或重啟使用者正式 runtime。

證據：[Mac 結果頁 browser report](../../outputs/evals/dashboard-3d-cost/mac-results-browser/report.json)、[桌面截圖](../../outputs/evals/dashboard-3d-cost/mac-results-browser/desktop.png)、[手機尺寸截圖](../../outputs/evals/dashboard-3d-cost/mac-results-browser/mobile.png)、[Chrome 分頁確認](../../outputs/evals/dashboard-3d-cost/mac-chrome-tab.txt)。

保留並排除的早期嘗試：實驗 Rudy endpoint 不符、原生高倍率 Rudy 缺瓦片、第一個擷取工具把取消瓦片請求視為 fatal failure。Linux 軟體 renderer 只作功能探索，其中一次 screenshot timeout，未拿來當 Mac 效能證據。所有修正都限於新增量測程式。


沒有 commit、push、merge、公開部署、付費 API、路線 promotion 或 production activation。
