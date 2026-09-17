# Scout 真實 GPX × God’s Eye View 3D 展示

Status: **WORKING PROTOTYPE** · Aggressive Construction Mode · 2026-09-07.

2026-09-10 更新：依使用者提供的 Manicaland 圖例改為青綠、亮綠、黃、橙、棕、
深灰的連續色帶，使用目前 DEM 的六個 20% 高程轉折，新增可展開高度清單。
目前配色、圖面解析與五種尺寸實測見 [參考圖設色報告](scout-gpx-3d-hypsometric-reference.md)。
以下 09-09 高度分色段落保留為歷史記錄。

2026-09-09 更新：已加入 DEM 高程色帶；目前 Workspace 的準備地形為 54 張
Z13 瓦片，普通展示仍使用 stride 16，約 280 m 顯示網格。本文下方的 506 張
瓦片／約 70 m 網格數字是 09-07 原始驗證批次，不能當成目前效能條件。
同一台 Mac 的完整密度 Three.js／MapLibre 對照另見
[量測方法與結果](scout-gpx-3d-benchmark.md)。

獨立本機實驗頁已用指定 Workspace 的真實 GPX 完成 3D 地形、全程定位、
旋轉縮放、來源節點選取、側欄同步與回放。展示為 `visualization_only=true`、
`candidate_only=true`、`runtime_safety_truth=false`。未進入 Productization Mode。

## 開啟與操作

本次本機入口：

- 選擇 GPX：<http://127.0.0.1:9127/>
- 已核對的 Workspace 原始主 GPX：<http://127.0.0.1:9127/?gpx=839bf9fac6f2fd73995a71ed>
- 篩選版主 GPX／既有 CP：<http://127.0.0.1:9127/?gpx=be3cae8e246b7836daf6e5d9>

入口綁定 loopback；必須從這台主機或既有 localhost forwarding 開啟。
沒有建立公開站台或改動既有正式 runtime。

需要重開時，在 repo 執行：

```sh
./venv/bin/python tools/scout_gpx_3d_app.py \
  --project-root /home/alexwang0315/workspace/dongqing_batongguan_historic_trail_newImport \
  --port 9127
```

新環境可用 `python3 -m venv venv` 與
`./venv/bin/pip install -r requirements.gpx3d-demo.txt` 準備獨立依賴。
本次使用 Python 3.13.5。前端已內附固定版本，執行展示不需要 npm、API key
或 CDN。不要用正式 runtime 的 port 啟動；服務拒絕常見的 8000/8080/9099。

1. 下拉選擇既有 GPX，或「開啟本機 GPX」。後者只在瀏覽器記憶體讀取，沒有
   upload POST，也不寫入 Workspace。沒有來源時顯示選檔入口，不載入 fixture。
2. 滑鼠拖曳旋轉、右鍵平移、滾輪縮放；手機單指旋轉、雙指縮放／平移。
   上方提供全程定位、放大縮小、旋轉及俯視按鈕；canvas 也支援方向鍵、+/-、F。
3. 點選地圖節點或左欄清單，查看同一筆名稱、座標、高程、時間、來源與 SHA-256。
   搜尋可縮小節點清單。播放游標不會取得手動選取狀態，也不自動移動相機。
4. 播放或拖曳進度。有效且完整、嚴格遞增的時間依記錄時間回放；跨 segment
   缺口期間不顯示插值位置。其餘標示「等速示意回放」，不提供真實速度或 ETA。
5. 來源類型預設 `unknown`。可在這次瀏覽中聲明規劃路線／歷史 GPS 記錄，
   聲明不寫回來源。Workspace 的 `golden_route_reference` 用途另行呈現。

### 高度分色更新 · 2026-09-09

地形改為低處深綠、草綠、土黃、沙色至高處米白的連續色帶，保留山稜陰影。
色彩依載入的 DEM 網格原始高程範圍決定，不使用 GPX 高程或視覺抬升值。
地圖下方圖例顯示最小、中間、最大高度（m）及該批資料的垂直基準；陰影會
影響明暗。沒有 DEM 的區域不分色；載入中、空 GPX、地形及 WebGL 降級時
隱藏圖例。重新整理頁面即可使用。

本次 Workspace 載入的網格範圍為 228.4–3,896.1 m，垂直基準回傳 `unknown`，
圖例如實呈現；不沿用下方較早驗證批次的基準宣告。色帶只表示高度，不表示
植被、積雪、地表類型或風險。此更新只涉及獨立展示的前端與設計文件。

Chromium 實測桌面 1280×900、手機模擬 390×844、平板 768×1024 通過：
色帶數值與該次 DEM 回應一致、無水平溢出、選取／回放保留；地形 503 與
renderer module 失敗均明確降級並隱藏圖例。正常 console／network 錯誤 0，
外部請求及 mutation 0；10 份原始 GPX 雜湊前後一致。另有既有 Node 專項
10 passed、pnpm lint／typecheck／test 通過（1／17 passed；既有 AnyIO
deprecation warning）。未做 Mac Safari 實測。

本機記錄與桌面／手機／平板截圖：
`outputs/evals/scout-gpx-3d/elevation-colors/browser-report.json` 及同目錄 PNG。

## 真實資料與缺漏

指定 Workspace：`/home/alexwang0315/workspace/dongqing_batongguan_historic_trail_newImport`。

| 來源 | 本次實證 |
| --- | --- |
| `inbox/gpx/primary.primary_hiking_20260729200546.hiking_20260729200546.gpx` | 主展示：5,768 點、1 個 segment、0 waypoint；SHA-256 `5f0ff2993d561d8f3c5b108db215d312d85d703e51e1fd93743940768df916db` 與 `inbox/source_manifest.json` 相符。 |
| `inbox/gpx/reference_002.reference_002_20210101-阿桑來嘎駐在所-惠琳_p.20210101-阿桑來嘎駐在所-惠琳_p.gpx` | 補充真實斷點／節點實測：1,027 點、3 個 segment、67 個 waypoint；可依記錄時間回放。 |
| `normalized/routes/filtered/primary.primary_hiking_20260729200546.speed_filtered.gpx` | 既有匯入流程產物，與原始檔分開列出。5,649 點；經既有篩選報告輸出 SHA-256 對應 legacy URI，關聯 181 個既有 CP。38 個 CP 未確認來源關聯，未顯示。 |

原始主 GPX 的所有點都有高程，但缺少 143 個時間戳，另有 12 對相鄰有效時間
不遞增，因此使用**等速示意回放**。沒有把這份檔案稱為使用者實際完成行程；
`project.json` 的 `actual_user_track_available=false` 與來源類型 unknown 相容。

主 GPX 沒有 waypoint；起終點只是來源首尾點標記。其正式 CP provenance 指向
另一份篩選版 GPX，故不將這些 CP 偷套到原始主 GPX。篩選版的 CP 仍保留
`proposed`／candidate 狀態、原有座標及出處；沒有生成新 CP，也不把 CP 候選
提升為 runtime 導航節點。UI 中缺少的時間與高程皆呈現 unknown。

## DEM 與座標

- 沿用 `load_navigation_terrain_dem_manifest()`、`navigation_terrain_dem_tile()`
  的既有唯讀契約，逐瓦片驗證 allowlist 與 SHA-256。
- 實際來源：`outputs/navigation/terrain_rgb/manifest.json`，準備時間
  `2026-08-25T04:41:33.436682+00:00`。506 張 Z15、256 px Terrain RGB。
  `source_cell_resolution_m=20`；來源指紋
  `e14cd56fe14a8d435fec45ec702486e748b079517e9c466a71f7e04b95dc80df`。
- 原 DEM coverage metadata：水平 `TWD97[2010]`／EPSG:3826-compatible，
  垂直 `TWVD2001`。已準備瓦片為 EPSG:3857，bounds 為 WGS84。
  GPX 為 WGS84；GPX 的垂直基準 unknown，沒有用 GPX 高程和 DEM 做差或校準。
- 新的唯讀適配器在記憶體解碼現有瓦片，每 16 像素抽樣，建立 368 × 352
  頂點的有限矩形網格。此區約 70 m 的顯示間距；**這不是 20 m 的展示解析度**，
  也不是新的 DEM 產品。沒有大型轉檔、下載 DEM、啟動新地形服務或外部 API。
- 網格只覆蓋已驗證的完整資料區域。主 GPX 的 4,349／5,768 點在網格內（75.4%）；
  其餘呈現黃色虛線及平面位置，畫面的格網是座標示意，沒有假設海拔 0 m。
  抽樣後最外側不足一個 stride 的邊緣也不外插。缺失／透明瓦片不建立假地形。
- Three.js 的局部 X/Z 由 EPSG:3857 相對路線中心座標乘中心緯度 cos 校正，
  Y 使用 DEM 網格相對展示基面，垂直誇張 1×。這是局部視覺展示，不宣稱測量
  級的水平／垂直一致性，沒有建立 geoid／橢球高轉換模型。

高程分成三條資料：GPX 原值；點選時獨立解碼原 Terrain RGB 像素的 DEM
取樣（保留來源瓦片與雜湊）；顯示網格的三角形插值＋12 m 純視覺抬升。
後者只避免線被地形遮住，不覆寫前兩者。CP 自己記載的高程另外列出。
Terrain RGB 的 0.1 m 編碼不等於資料精度。顯示可能增加線段內貼地用頂點，
原始有效 GPX 點沒有簡化，沒有重新計算／回寫正式距離、速度、ETA 或風險。

## 整合邊界與上游重用

既有的 `route_matching.load_gpx_route()` 會跨全部 `trkpt` 攤平。
展示使用獨立 `gpx.mjs` 保留 GPX 原始 segment，並在無效座標、極區限制或
跨日期變更線處中斷可視線段；不修改正式 parser。CP 沿用既有 project ref
優先順序：`overpass_aligned_checkpoint_candidates_ref`、`checkpoint_candidates_ref`。
UI 尚不嵌入 Dashboard，因其狀態在大頁面的私有 `state` 內，直接耦合會跨越
Navigation freeze；獨立頁避免改動原本相機、選取與控制流程。

`DisplayAuthority` 擴充現有 `SpatialAuthorityBoundary`，保留其固定權限值；
`SourceIdentity` 負責來源 SHA／角色／類型，兩者分開。沒有 promotion、runtime
route 註冊、安全規則寫入、外送、持久記憶或 production activation。

God’s Eye View 固定 commit `759652207fd1279ece97f0f19af566feb9a82146`。
實際逐位元重用 `src/data/contextStore.js`，本機改副檔名為 `.mjs`。呼叫
`registerEntityContext`／`selectEntityContext`／`getSelectedEntityContext`／
`removeEntityContextsForLayer`，以 `gev:entity-selected` 同步地圖及側欄。
保留 © 2026 Bilawal Sidhu 與完整 MIT 授權。詳細來源和 Three.js r180
歸屬見 `experiments/gpx-3d/THIRD_PARTY.md`。沒有完整移植上游 Cesium globe，
也沒有使用舊公開 demo 的程式碼或人工軌跡。

| 面向 | 既有 Navigation 3D | 本次獨立展示 |
| --- | --- | --- |
| 引擎 | MapLibre GL JS 6.2.0 raster-dem terrain；另有 bounded mesh/SVG 路徑 | Three.js r180 有限地形網格＋GEV contextStore |
| 路線 | `navigation_terrain_projection`／terrain route samples、QGIS analysis route 與既有候選上下文 | 明確選擇的 GPX 原始各 segment 與 waypoint；CP 需核對來源 |
| 視角 | 3D camera floor 是來源 zoom + 1（此 Workspace 為 Z16），局部細節；2D 保留全程視角 | 相機可全程定位、旋轉、縮放與俯視，不受瓦片 zoom floor 限制 |
| 高程 | Prepared Mapbox Terrain RGB；經緯度以 `[lon, lat]` 入圖，垂直誇張用既有狀態值 | 同批本機 Terrain RGB 的抽樣網格，三種高程分開，明示未覆蓋區 |
| 選取 | Dashboard 私有 navigation selection state 與多個 evidence lens | 獨立 GEV store，回放另有游標，不影響原本選取 |
| 用途 | Navigation／Terrain Intelligence 的候選證據工作台 | 評估全程空間關係、來源節點與時間回放的展示價值 |

## 驗證與證據

使用 repo 既有 pytest、Node test、Playwright，未啟停正式 runtime。
本機 browser smoke 限定獨立 loopback port，攔截所有 mutation／外部請求。

| 檢查 | 結果 |
| --- | --- |
| 新增 Python 專項 | 6 passed：唯讀目錄、來源身份、CP 關聯、authority literal、DEM 缺漏／雜湊／透明洞、HTTP 權限與不寫入 |
| 新增 Node 專項 | 10 passed：軸序、segment、起終點、缺失高程、無效時間／座標、空 GPX、12000 點不簡化、GEV 選取與回放隔離、DEM 插值洞 |
| 實際瀏覽器 | Chromium 148.0.7778.0；桌面 1440×1000、手機模擬 390×844、平板 768×1024；真實 GPX、3D、節點同步、播放、滑桿實拖、相機與觸控操作通過，沒有水平溢出 |
| 正常頁面 console／network | 0 console error、0 HTTP error、0 外部請求、0 mutation |
| 人工故障注入 | 地形 503：可見平面降級；renderer module `ERR_FAILED`：可見 SVG 降級。上述預期錯誤完整保留於 browser report，沒有隱藏為正常成功 |
| 底圖失敗 | NOT APPLICABLE：此版不啟用外部或本機圖像底圖，介面始終標示沒有底圖 |
| 原始資料／凍結表面 | 18 檔 SHA-256 前後相同，包含 10 GPX、CP、project、terrain manifest、Navigation、共享 MapLibre、layer contract 及 boundary freeze |
| 32-layer 靜態 contract | PASS，32 層、0 errors；不是全域正式 runtime/browser qualification |
| pnpm lint／typecheck／test | PASS；typecheck 1 passed、test 17 passed。初次測試環境缺 pydantic_ai；補齊專案已聲明依賴後通過，未修改既有功能。 |

三項既有 Navigation 聚焦回歸另驗證相機保留、全程 2D fit 與無 terrain RGB 的
vector fallback。原始 Navigation 頁面與後端程式未修改；沒有重新啟動或執行
使用者正式 runtime 的操作。本次手機是 Chromium 觸控／尺寸模擬，非實體手機。

本機證據（ignored，不嵌入真實 GPX 到 tracked fixtures）：

- `outputs/evals/scout-gpx-3d/browser-report.json`：完整實測記錄、正常與注入錯誤。
- `desktop-real.png`、`mobile-real-full.png`、`mobile-real-scene.png`、
  `tablet-real.png`、`desktop-real-reference.png`、`mobile-terrain-failure.png`：同目錄截圖。
- `source-integrity.json`、`layer-contract-report.json`、`resource-trajectory.json`。
- `python-tests.log`、`typecheck.log`、`pnpm-test.log`。

可重跑的主要命令：

```sh
./venv/bin/python -m pytest tests/test_scout_gpx_3d.py -q
node --test tests/scout_gpx_3d.test.mjs
node tools/scout_gpx_3d_browser_smoke.js \
  --url http://127.0.0.1:9127 \
  --project-root /home/alexwang0315/workspace/dongqing_batongguan_historic_trail_newImport \
  --output outputs/evals/scout-gpx-3d
```

Browser smoke 中的時間缺口、缺失高程、空檔探針都明確標示 SYNTHETIC TEST ONLY，
不計入真實路線證明。依賴使用 repo 的 Playwright／jsdom；若要跑測試，另需
pytest、httpx，Node 22.14+ 與 `npm ci`、`npx playwright install chromium`。

本次資源軌跡：解碼 506 張既有本機瓦片，129,536 頂點、257,634 個三角形；
一次地形請求約 4.1 秒，gzip 約 354 KB。瀏覽器閒置不持續重繪，播放時才逐幀
更新游標。展示沒有 model requests、付費 API 或外部資料下載；指標是本次
觀測值，不是產品 SLO。

## 新增檔案與下一步

- `scout_gpx_3d.py`：typed authority／來源、指定 Workspace 目錄、來源關聯與唯讀 terrain。
- `scout_gpx_3d_terrain.py`：本機 Terrain RGB 解碼、顯示網格、獨立高程取樣。
- `tools/scout_gpx_3d_app.py`：只讀、限本機、同源、防越界實驗服務。
- `docs/admin/experiments/gpx-3d/`：HTML／CSS、解析與回放、Three.js renderer、GEV 選取適配器、固定第三方模組與 attribution。
- `tests/test_scout_gpx_3d.py`、`tests/scout_gpx_3d.test.mjs`、`tools/scout_gpx_3d_browser_smoke.js`：聚焦測試。
- `requirements.gpx3d-demo.txt` 與本文件：可重現入口與交付紀錄。

限制：部分 DEM 覆蓋、來源時間不完整、GPX 垂直基準不明；展示網格約 70 m，
不是貼圖寫實地球；無跨日期變更線連續回放、無極區 3D、僅 UTF-8 GPX；
本機高程請求會重新驗證瓦片，尚未實作快取、LOD 或長軌跡吞吐 SLO。
密集 waypoint／CP 不做自動風險整理或節點升格。

下一個最小步驟：針對目前原始主 GPX 缺 DEM 的區段，核對現有本機 DEM 來源是否
完整可讀，再只在獨立實驗輸出中擴充覆蓋範圍；不先重做正式 import／Navigation。
若需要額外大型地形轉檔、下載或付費供應商，先提出具體範圍／費用供使用者決定。
本次沒有執行 repository-wide coverage、全套 browser/GIS qualification、實體手機
效能或正式 runtime 重啟驗證，尚未產品化；沒有 commit、push、PR 或部署。
