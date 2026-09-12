# Dashboard production 地圖入口補漏盤點（2026-09-12）

這份盤點以目前 Mac 9099 checkout 原始碼為準，沒有操作 Chrome、服務、候選、workspace 或人審資料。它證明入口與分支存在或不可達，不能代替實際使用者 UI 驗收。來源 SHA 與讀取時間保存在 Scout `/home/alexwang0315/work/scout-pretrip-all-seven-20260910/main-rudy-zoom-20260912/all-map-surfaces/production-map-inventory-20260912.sources.json`；行號可能隨其他 agent 的並行修改移動，函式名是穩定定位點。

## 現有分母與已授權補齊

原始 DASHBOARD_MAP_SURFACES 九種：Overview、LBS、Permission preview、Emergency review、Main、Weather、Navigation、Architecture、Pace。D026–029 原本 factory 31 個 renderer/lens cases，另加 Debug SVG/MapLibre 兩個與目前 workspace 實際 on-trail 每日圖數。原始 source marker 九張與實際 DOM case 是兩種證據，不能混成全量通過。

本次已確認且 root 授權新增：Navigation terrain/prior ready 各 structure 的 2D、3D、SVG fallback 共六；terrain/prior loading 共二；Architecture time_window 一個。因此 factory 應為 40；加 Debug 2 與 N 張每日圖共 42+N。九日 workspace 暫為 51，但不能硬寫九日或宣稱 Planned/Legacy 相關用途契約已裁決。

Navigation domain case key 使用 domain:mode:lens。observed 有 structure/pressure/risk/retreat/events；terrain/prior UI 切入時強制 structure，不能創造不存在的 lens 組合。三個 domain 都有 loading shell；loading renderer 不讀 domain，orientation basemap ready、bounds、zoom 才決定 Rudy 是否出現。ready terrain/prior 明確無 Rudy；不得以 ready 規則把 loading Rudy 省略。

## 已確認可達但原矩陣遺漏

### Planned：一個 shared SVG renderer、九個實際 UI instance

- docs/admin/scout-planned-route.js:239 mapHtml 建立 900×420 vector-only 地圖；341 previewHtml 在 354 依 prefix 產生 preview 或 compare。render 的 Human Design workbench 同時有 preview 與已保存版本 compare。Dashboard:25449 由 permissionBaselineMode=human_text 掛入 ScoutPlannedRoute.render。
- 同檔:1047 renderSubject 在 1061 呼叫 mapHtml(..., analysis)。Dashboard 的 outdoorTabs → renderAnalysisSubject 約24761，讓六力頁在 planned_gpx/unresolved_selection 上呈現 analysis：outdoor-route-context、outdoor-pace-fit、outdoor-permission、outdoor-architecture、outdoor-weather、outdoor-navigation。
- Body Index 不能漏掉：Dashboard:35694 的 outdoorTabs(outdoor-pace-fit) 也會插入 analysis 地圖。六力六個 + Body Index 一個 + Human Design preview/compare 兩個，共九個 UI instances。共享 renderer 測試不代表七頁的 selection/version/source 與 handlers 都已驗證。
- JS:855 bindMaps 有 +/−/Fit、拖曳 Pan、Golden/Planned 顯隱、anchor click/Enter/Space；953 的 bindMaps(document) 發生在 workbench root 不存在即返回之前，因此 analysis 也會绑定。沒有 Box、方向鍵平移、B/P/Escape 地圖模式與共用 hover/focus tooltip；SVG title 與 selected-anchor 文字不是同一互動契約。
- tests/test_dashboard_planned_route.py 目前偏 source/geometry/version/action，沒有上述完整 control replay。先等使用者裁決用途規格，不能強套 native Rudy，也不能自行 N/A 或把缺少 Box 當通過。
- 最小補齊：每個 route+mapId 以真 render/bind 抓取該頁版本與 geometry hash，測 +/−/Fit、Pan、Golden/Planned toggles、anchor click/keyboard、缺口不補線、compare source/version 正確、rerender/restore 後狀態。一般地图全套 hover/box/key/wheel 是否適用由用途式標準決定。
- wrapHistorical（JS:1069、Dashboard renderAnalysisSubject 的周邊）把舊 Golden 工具包在 details；工廠直接render一張舊map並沒有驗頁面實際切換、details 展開或跨頁選中來源。

### Navigation：六個 ready + 兩個 loading

- renderNavigationPage（Dashboard:33596）lensOptions observed 五種，其他 domain 只有 structure；data-navigation-evidence-domain 的 click handler 會重設 structure。
- workbench 的 2D 依 DEM ready 選 MapLibre 或 SVG fallback，3D 為 MapLibre。renderNavigationWorkspaceMap 與 MapLibre style 的 observed guard 控制 GPX/Rudy/observations；ready terrain/prior 不應有 Rudy。
- renderNavigationWorkspaceLoading（33532）完全未讀 domain：orientation_basemap 條件成立即建立 Rudy layer。須各 domain 入口實際 replay，不能以一個 observed case 假設其餘已經過測。
- 新 D028 必須驗 active domain 與实际 source/vector 內容：ready terrain/prior 驗證本來的無 Rudy 邊界，不呼叫遠端、不用 observed fixture 替代；loading 與 observed 維持 exact/cache-only/source/workspace 來源政策。
- loading 畫面明示尚無 terrain vectors，與 D028 通用的 `vectorCount > 0` 斷言衝突。已送使用者裁決是否依 ready／loading 分別驗收；裁決前保留 FAIL，不自行跳過。ready terrain 的 MapLibre 仍可能有已知 GPX 參考線，不能把「無 Rudy」錯寫成「不得有 GPX」。

### Architecture：time_window 是第七個正式 lens

- renderArchitectureMap:34735–34742 的 lensButtons 包含 structure、terrain_demand、slow_passage、risk_passage、reversibility、time_window、evidence_quality，皆由同一 UI 列表生成可點按鈕。
- D024 expectedLenses 與 diagnosticArchitectureInteractions 已列七種；原 D026–029、D037、D044 各自只列六，漏掉 time_window。
- 本次加 factory time_window 並負測漏列不可 PASS；D037 由 SVG agent、D044 由 root 分工補齊。並非新增產品用途。

## Navigation 整頁狀態切換仍需要實際觀測

目前工廠一次 render 一個 host，無法證明 production workbench 2D/3D/Split 的實際 pane 尺寸、獨立鏡頭、domain/style 切換與銷毀重建沒有退化。

- D025（21428）：detached renderOutdoorPage + DOM marker/controls 查詢，沒有真實 controls 操作。
- D038（約23491）：stub map getCenter/getZoom/getPitch/getBearing 驗 remember/store/restore/sync helper，配合原始碼 marker；不是真正整頁 MapLibre/Split 切換。
- D044（24328 入口及之前 map-order probe）：三 domain 各建立 2D/3D 真 hosts 與實際 renderer，比對 layer order，再清理；也有 SVG lens、DEM mesh/training fixture。沒有按 UI View/Split/domain 按鈕或實際鏡頭保存操作。
- 最小新增場景應重用這些 preparation/dispose 而非改寫 harness：renderNavigationPage 真實頁面與 binding → 2D 平移 → 切3D並獨立平移 → Split 兩 pane 都可見且正確尺寸 → observed→terrain/prior→observed → 核對相應 sources/candidate lens/每模式鏡頭與完整 cleanup。不可把單 host 操作當整頁已測。

2026-09-12 後續實作已加入 D038 的 26-phase 真頁面 probe，透過隔離頁面的正式 render/bind 點選控制；包含實際 pane 尺寸、隱藏／重疊檢查及上述鏡頭、domain、lens、Evidence、候選與 Fit／Reset。原 helper 保留為獨立證據。正式 Chrome 尚未重跑，故仍列未驗證；source 的存在及 Node 回放不等於目前 workspace 已通過整页操作。另補 API／候選／來源 fingerprint 綁定，避免隔離頁面代用同名本機專案或預設候選。

## 可見或保留但用途/範圍不同的入口

| 入口 | 原始碼證據 | 正確證據邊界與最小方案 |
| --- | --- | --- |
| Legacy Emergency desktop 示意圖 | Dashboard:19192 iframe；admin_api.py:3271 desktop URL，另一 mobile alias 經同一 desktop transform；docs/emergency/scout-emergency-mobile-approval-v0.html:1379 data-map-surface=desktop | 固定 SVG 路徑/CSS pins + layer toggles；沒有 +/−/Fit/Pan/Box。CSS .layer-rudy 是 repeating-linear-gradient，不是真實 Rudy tiles。用途規格待使用者仲裁。兩 URL 不等於兩個 renderer，不得算 native 成功。 |
| navigation-training-map | renderNavigationTerrainMap:26779；renderNavigationPage:33600 const sourceMode=workspace；33667 training 條件分支 | 目前 UI 不可達：只有 state/handler，沒有實際 source-mode button。另一 caller 是 D044 的 fixture render。保留為 inactive retained fixture，不能當 live UI 成功，也不能直接刪除證據。 |
| DEM 2.5D mesh | renderNavigationTerrainMesh:27988；另一 caller 24274 D044 | current production 3D 用 MapLibre；mesh 是 retained diagnostic fixture，不是假設 live3D 表面。 |
| QGIS render receipt image | renderQgisRunReceipt:33486，data-qgis-render-role=static-evidence 與 audit snapshot 文案 | 靜態稽核快照，來源與 receipt/hash 要保留；不是獨立可平移地圖，不可拿來通過 native level。 |
| Historical map | phase4-pretrip-planning.html HISTORICAL_MAP 定義與 selector change/bind（約1839、2387、8903–8917） | 同 canonical camera 的 source/theme variant，不是新 engine。root 另處理 canonical/auxiliary 老檢查語意衝突；本盤點不擅改期待。 |
| Rudy 候選描線 | active Mac docs/admin 沒有另一獨立描線 renderer；scout-planned-route.js catalog/Overpass/Rudy clues；planned_rudy_trace_refs 最後成為 Planned 幾何 | 本 checkout 的 candidate 經既有 Planned preview/compare/analysis 顯示。不能拿其他 Scout branch 的舊 UI 當目前9099已覆蓋；如期待另一審查入口，應先查版本/可達性。 |
| After-action /admin | admin_api.py:258 DEFAULT_ADMIN_PAGE=phase1-after-action.html，2847 @router.get(空字串)；該HTML #map 與自身 controls | Dashboard 沒有指向此入口的 active map route，本輪也未改其 renderer。記作外部範圍。它有自己 wheel preventDefault/zoom 行為；不把它偷偷併入 Dashboard 或擅改 wheel。 |

## 驗收與未解事項

- 這份 source inventory 不是 D026–029 或 D037 的 Chrome PASS。
- 缺少 Box／B 控制仍為 FAIL；只有反向框選語意標記 pending_user_arbitration。各子觀測獨立保留，不能因 Box 缺失便漏掉 wheel、鍵盤或焦點測試；未驗證均不算 PASS。
- Planned 九 instance、Legacy用途規格、Navigation整頁狀態切換目前仍有明確缺口。即使 40 factory + Debug + 每日 focused tests 全過，也不能宣稱全部用途地圖完成。
- 新測試使用只讀既有 workspace，候選維持 candidate_only=true、runtime_safety_truth=false；不得生成新 itinerary、修改 baseline 或人審資料以製造通過。
