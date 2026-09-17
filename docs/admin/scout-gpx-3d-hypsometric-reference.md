# Scout 3D：參考圖高程設色與圖面解析

Status: **WORKING PROTOTYPE** · 2026-09-10 · 本機實驗頁。

已依使用者提供的 Manicaland 圖片重建近似的連續高程色帶，套用至既有
GPX 3D 展示，並加入可展開的「色帶與高度分布」。重新整理已開啟的展示頁即可。
Scout 本機入口：<http://127.0.0.1:9127/?gpx=839bf9fac6f2fd73995a71ed>；
從 Mac 使用既有 SSH／localhost forwarding。沒有新增公開網址或重啟服務。

## 參考圖包含的資訊

提供的 JPEG 標題是 **MANICALAND PROVINCE, ZIMBABWE — HYPSOMETRIC
REPRESENTATION**，主體是辛巴威 Manicaland 省的地形高程圖。

| 圖面元素 | 可讀出的資訊與用途 |
| --- | --- |
| 高程設色 | 色帶由低處青綠，經亮綠、黃、橙、棕，到高處深灰；圖例端點為 313、1,843 m。是連續漸層，未標出中間級距數值。 |
| 地形明暗 | 高程設色疊加 hillshade，突顯山稜、坡面與谷地。黑暗區域也可能是背光坡，不能單憑明暗判定高度。 |
| 河網 | 淺藍色河流依 Strahler Order 1–7 分級，主要以線寬區分。這個圖例呈現河網級序，沒有提供流量、河深或即時水況。 |
| 四條剖面 | 紅色虛線 A–A1、B–B1、C–C1、D–D1，與左側四張高程剖面一一對應；橫軸距離 km、縱軸高程 m。A、C 剖面約 300 km，B 約 160 km，D 約 120 km。 |
| 行政與區域位置 | Manicaland 省邊界、周邊省份及東側 Mozambique；周邊地名包括 Mashonaland Central／West／East、Masvingo、Matabeleland South。淡色背景提供城市、道路及其他地理參考。 |
| 定位小圖 | 左上角小圖顯示 Manicaland 在辛巴威的位置，避免只見局部地形而失去區域脈絡。 |
| 地圖量測元素 | 經緯網、邊框座標標註、北箭頭與公里比例尺。可見經度刻度約 30.25–33.00、緯度刻度約 −17.60–−20.90；這些刻度不等同資料的精確外框。 |
| 製作方法 | 圖中文字說明下載、合併、裁切 SRTM DEM，在 QGIS 套用高程設色與 hillshade；數化剖面線、產生剖面圖，再編排圖面。 |
| 資料與署名 | DEM 標示 NASA SRTM／USGS Earth Explorer；水體資料標示 HydroSHEDS；Made in QGIS；作者署名 Mashford Mahute。這些是參考圖的資料來源，沒有改成 Scout 的 provenance。 |

讀圖時有三個限制：

1. A–A1 剖面明顯超過 2,000 m，但色帶上限寫 1,843 m。圖片沒有交代是否
   使用截斷色階、不同資料範圍或其他設定，不能將 1,843 m 宣稱為全區最高點。
2. 圖片沒有提供原始 QGIS 色帶、各轉折高度或拉伸／分類設定；無法確認採用
   等距、分位數、自然斷點或累積分布。下方的 20% 配置是本次重建選擇。
3. 未標示可確認的 DEM 產品解析度、取得日期、完整座標系統與垂直基準、光照
   方位／高度角。綠色不能直接解讀成植被，深灰也不能直接解讀成岩石或風險。

## 套用方式與實際高度

取圖例內部色彩轉折作近似重建；JPEG 壓縮與陰影使原始 RGB 無法精確復原。
六個色彩轉折均勻分布在**目前載入 DEM 網格的高程範圍**，轉折間使用 sRGB
插值形成連續色帶。這不是六個截然分開的級別，也不代表每種顏色各占相同面積。

`轉折高程 = DEM 最小值 + 比例 × (DEM 最大值 − DEM 最小值)`

| 比例 | 色彩 | 色碼 | 目前 DEM 對應高程 |
| ---: | --- | --- | ---: |
| 0% | 青綠 | `#00bfbf` | 228.4 m |
| 20% | 亮綠 | `#00ff00` | 961.9 m |
| 40% | 黃 | `#ffff00` | 1,695.5 m |
| 60% | 橙 | `#ff7f00` | 2,429.0 m |
| 80% | 棕 | `#bf7f3f` | 3,162.6 m |
| 100% | 深灰 | `#141414` | 3,896.1 m |

未套用參考圖的 313–1,843 m，也未改用相機當下可見範圍重新配色。換成其他
DEM 時由回傳範圍計算；均一高程只呈現一個顏色與一個高度，避免除以零。
小數位來自既有 Terrain RGB 編碼，不代表測量精度。

3D 保留既有 Lambert 坡面光照，改為白光、西北方 45°，ambient 0.15、
directional 3.0，以加強山稜明暗。這是相似視覺風格，沒有重建圖片中的原始
hillshade raster 或宣稱相同參數。渲染器與圖例共用六個轉折；色彩先在 sRGB
插值，再轉為 Three.js 光照使用的線性值。陰影影響畫面明暗，圖例保留原色。

展開圖例超出桌面高度時，實驗頁的場景區域可捲動。手機維持單欄頁面；
色彩轉折清單依空間排成 3／2／1 欄。沒有 DEM、空 GPX 或降級時不顯示正常
高程圖例；未覆蓋區域不分色。

## 來源與權限邊界

- Workspace：`/home/alexwang0315/workspace/dongqing_batongguan_historic_trail_newImport`。
- GPX：`inbox/gpx/primary.primary_hiking_20260729200546.hiking_20260729200546.gpx`，
  ID `839bf9fac6f2fd73995a71ed`；SHA-256
  `5f0ff2993d561d8f3c5b108db215d312d85d703e51e1fd93743940768df916db`。
  5,768 個有效點、1 個 segment、2 個起終點標記；來源類型 `unknown`。
  時間缺漏／不遞增，仍為等速示意回放。
- DEM：既有 `outputs/navigation/terrain_rgb/manifest.json`，54 張 Z13、256 px
  本機 Terrain RGB；來源指紋
  `5bf9edd54b7ac4fc21dbd51cb74e7af1d6b117ef4e4a788245d4a701eb30e498`。
  原始來源標示 20 m；展示仍為 stride 16、144 × 96 頂點、約 280 m 間距，
  這次沒有變更地形細節或幾何。主 GPX 5,768 點均在目前網格覆蓋內。
- GPX／本批 DEM 垂直基準均維持 `unknown`。顏色使用 DEM 網格高程，與 GPX
  原始高程、節點 DEM 取樣、12 m 純視覺抬升分開；沒有回寫原始資料。
- 保留 `visualization_only`／`candidate_only`，不是 `runtime_safety_truth`。
  沒有改 Navigation、MapLibre、CP、路線註冊、安全規則或正式 runtime。
  原本 GEV contextStore 重用與 MIT attribution 保留，沒有新增上游模組。
- 沒有外部底圖、下載、API 費用或對外 GPX／CP 傳輸。未 commit、push、部署。

## 實測

現有本機服務，Playwright Chromium 148.0.7778.0，Linux SwiftShader。
這是實際瀏覽器的功能／版面測試，不是 Mac 或實體手機效能測試。

| 驗證 | 結果 |
| --- | --- |
| 桌面 1280×900／較矮桌面 1280×720 | 六色與轉折高度一致，展開可捲動至回放按鈕，收合與旋轉／縮放／全程定位正常。 |
| 手機模擬 390×844、360×800；平板 768×1024 | 無水平溢出，圖例可展開，真實 GPX 3D／選取／回放正常。 |
| 手動選取與回放 | 五種尺寸點選起點後播放、暫停，選取仍保持起點。 |
| 均一高程、空來源 | 明確標示 synthetic test only 的 1,234.5 m DEM 探針呈現單一色高；空 GPX 顯示錯誤並隱藏上一份 DEM 圖例。 |
| 地形／renderer 失敗 | 注入 503／ERR_FAILED，顯示可見降級並隱藏圖例；錯誤保留在報告。 |
| Console／network | 正常情境 0 error、0 warning、0 HTTP error、0 failed request；外部請求與 mutation 皆 0。注入情境各產生一筆預期 console error。 |
| 原始資料與既有表面 | 27 檔 SHA-256 前後相同；10 份 GPX 另於瀏覽器檢查；54 張 DEM PNG 與 manifest 雜湊全部相符。 |
| Node 專項 | 16 passed：原 GPX／GEV／DEM 10 項及既有 benchmark helper 6 項。 |
| pnpm lint／typecheck／test | PASS；typecheck 1 passed、test 17 passed，保留既有 AnyIO deprecation warning。 |
| Navigation freeze guard | 前後皆 `INVALID_BASELINE`／report-only：本 checkout 缺 guard 與 `qualification/navigation-freeze-baseline.json`；使用 sibling checkout 的 guard 指定本 repo 唯讀檢查，未補建或更動 baseline。這不是 guard PASS。 |

首輪瀏覽器發現新圖例展開後，固定高度 scene 的 `overflow:hidden` 裁掉回放
按鈕（scene bottom 900 px，play bottom 957.47 px）。最小修正為場景超出可
捲動、非地圖面板不收縮；實際滑鼠滾動及點擊回放通過。初次並行 Node 測試
程序被 SIGTERM 結束（143，僅 TAP 起始行，原因未確認），順序重跑 16 項通過，
未修改既有測試以通過。

共 16 個瀏覽器檢查通過；截圖已實際檢視桌面、手機與展開色帶。
沒有執行正式 runtime、全域 GIS/browser qualification 或重跑 Mac benchmark。
既有 [Mac 量測](scout-gpx-3d-benchmark.md) 仍是 09-09 舊色帶的歷史結果。

本機可重現證據保留於 `outputs/evals/scout-gpx-3d/hypsometric-reference/`：

- [瀏覽器報告](../../outputs/evals/scout-gpx-3d/hypsometric-reference/browser-report.json)
  與 `browser-check.cjs`，包含各尺寸與故障注入記錄。
- [桌面畫面](../../outputs/evals/scout-gpx-3d/hypsometric-reference/desktop-elevation-full.png)、
  [手機場景](../../outputs/evals/scout-gpx-3d/hypsometric-reference/mobile-elevation-scene.png)、
  [展開色帶](../../outputs/evals/scout-gpx-3d/hypsometric-reference/desktop-distribution.png)。
- `source-integrity.json`、`terrain-integrity.json`、`freeze-after.json`。
- `node-tests.log`、`lint.log`、`typecheck.log`、`pnpm-test.log`。
- `attempt-1/` 與 `layout-probe.json` 保留原始失敗及瀏覽器修正證據。

## 修改與下一步

修改僅在 `docs/admin/experiments/gpx-3d/` 的 `terrain.mjs`、`renderer.mjs`、
`app.mjs`、`index.html`、`style.css`、`DESIGN.md`，以及本報告與兩份既有實驗
報告的版本註記。沒有新增 production 依賴、轉檔或變更網格密度。

圖片中的河網級序、四條剖面及行政圖層本次只分析，沒有假造或加到 Scout。
下一個最小步驟可用選定 GPX 的既有資料加入高程剖面，分開顯示 GPX 高程與
DEM 取樣並保留 segment 斷點；如需完全相同的原圖分類，須有原始 QGIS
樣式或數值轉折表，JPEG 本身不足以恢復。
