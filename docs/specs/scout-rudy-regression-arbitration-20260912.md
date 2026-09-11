# Rudy 回歸：待仲裁項目與續作紀錄

日期：2026-09-12（Asia/Taipei）。狀態：**未完成，未宣稱全面通過**。

指定入口：`http://127.0.0.1:9099/admin/dashboard?projectId=dongqing_batongguan_historic_trail_newImport#map`。
使用者瀏覽器為 Chrome。Dashboard 仍以 9099 為單一入口；19111 不得恢復。

## 已確認與尚不能確認的根因

- Rudy 上游有原生細節圖磚。修前同一視角的精確快取請求失敗後，原先失敗的
  同 20 張 Z20 以 native/refresh 取得，全部 HTTP 200。
- `2c3be900`（9/11 13:09 台北）恢復 max20／exact，卻保留預設 cache-only。
  `619d0680`（9/11 15:04）主要修 Weather SVG，未補主圖 MapLibre 自動載入。
- 前次 Weather 驗的是先下載過的 70 張 Z20，與本次主圖 Z20 座標交集為 0。
  該結果不能代替主圖及未預先填入快取的視角驗證。
- 8/25 的較早策略變更只能證明潛在條件；缺少能確證本次最後正常／首次故障
  的部署收據。不得把舊日期包裝成使用者此次開始故障的時間。

## 待使用者仲裁

| ID | 原標準與衝突 | 建議及影響 |
| --- | --- | --- |
| D037-A | `diagnosticWeatherRudyTileContract` 要求舊 `initialMaxZoom + ceil(log2(zoom))` 及 `nativeMaxZoom - initialZoom` 程式字串；目前 SVG 已按實際畫面尺寸與地理範圍計算。舊檢查會在真實換磚驗證前失敗。 | 改驗實際結果：Fit 後第一下 + 必須提升原生層級，放大至 Z20、平移後所需圖磚全部成功。保留嚴格結果要求，移除綁定舊實作字串的斷言。需裁決後才能修改使用中的驗收標準。 |
| D037-B | 舊 live probe 固定 SVG 與 cache-only，禁止 native／refresh；無法測一般互動地圖快取未命中時的自動補載。 | 增加選定 workspace 的 Rudy 原生 GET 測試，使用 native=1&exact=1，不強制 refresh；保留原離線快取測試。CWA 保持 cache-only，禁止準備／重建／修改行程。此測試會填入實際取得的 Rudy 圖磚快取。需使用者裁決此測試邊界。 |
| SCOPE-STATIC | Permission 每日圖原規格是 760×248 單張快取合成圖，沒有互動換磚能力；它與可放大、平移的地圖不同。 | 建議保留靜態摘要用途，另外驗證 workspace、圖片來源與清晰度；若使用者要求它也能動態放大，需明確擴充實作及驗收範圍。不能默默排除或冒稱已通過動態換磚。 |

上述項目尚無裁決。可準備候選 patch，但不得將候選接到 active Diagnostic，
也不得自動修改期待、停用檢查、改列 N/A 或通過。使用者已要求擴大全部 Rudy
地圖的檢查範圍，這項要求本身不需要再批准；尚待裁決的是衝突的標準與靜態圖用途。

## 全面驗證清單

程式盤點將 9 張主契約地圖展開為 15 個案例：Overview、LBS、Permission context、
Emergency review、Main、Weather、Architecture、Pace Fit、Navigation 2D／3D／TRH／
SVG fallback、Debug MapLibre／SVG、Permission 每日圖。全部實際案例見 Scout 清單。

- Dashboard 自有 SVG helper、Navigation MapLibre 及 Debug MapLibre 另有圖磚 URL
  產生路徑，目前沒有同步 exact 原生策略；不能以 phase4 的修正宣稱全部正常。
- Debug SVG 仍走舊 WMTS，並可能採準備時 Z14 上限，尚待實測。
- Navigation 的 camera zoom／idle／DEM 成功不等於 Rudy 原生圖磚完整。
- 使用中的 Diagnostic 037 仍保留舊公式及 cache-only probe；候選未啟用。

## 本輪部分證據與未完成工作

共用 phase4 已試作預設 Rudy 快取優先、未命中補 native 圖磚；停止更新才離線。
共用 MapLibre adapter 已試作實際 HTTP／native 層級／視野完整性追蹤；完成了
34 項相關 Node／Python 測試。這些只證明局部行為，不是全部 Dashboard 通過。
另外，`pnpm lint` 結束碼 0，`pnpm typecheck` 的 1 項與 `pnpm test` 的 27 項
斷言通過；兩個 Python 流程仍各有同一則 Starlette／AnyIO deprecation warning。
33-layer verifier 通過，Navigation guard 依既有 suspended 政策回報差異、errors=[]。
以上是續作檢查紀錄，不能代替尚未完成的逐頁、Diagnostic 與重載驗證。

Chrome 主圖已觀測 Fit Z12 30/30、第一次 + Z13 28/28，及 camera z18.7 時
原生 Z20 28/28、pending/error/unverified=0，截圖顯示清楚等高線。
本輪 Chrome 網路監聽在分頁重載後曾缺失事件，Z20 檔案中的零筆網路事件不能
當作 HTTP 層的獨立通過證據；須修正採證連線後補測。部分新分頁曾顯示初始化
timeout；原分頁後續已 ready，原因與穩定重載尚未證實，不得隱去該觀測。

仍待：全部地圖策略修正與逐頁驗證、Z20 新視角平移與恢復、穩定重載、Diagnostic
仲裁後的實作與全部相關重驗、教學 35–38 頁及 PDF 真實截圖更新。既有 1–34 頁
與舊證據不可重新標成今天的驗證。未完成這份範圍前，不能宣稱圖磚問題已解決。

所有大檔證據保存於 Scout：
`/home/alexwang0315/work/scout-pretrip-all-seven-20260910/main-rudy-zoom-20260912/`。
子目錄：`regression-history/`、`all-map-surfaces/`、`diagnostic-arbitration/`、`guide-refresh/`。
候選 `diagnostic-arbitration/proposed-dashboard.html` 不得直接提供為正式 Dashboard。
