# Rudy 回歸：仲裁決定與續作紀錄

日期：2026-09-12（Asia/Taipei）。狀態：**未完成，未宣稱全面通過**。

指定入口：`http://127.0.0.1:9099/admin/dashboard?projectId=dongqing_batongguan_historic_trail_newImport#map`。
使用者瀏覽器為 Chrome。Dashboard 仍以 9099 為單一入口；19111 不得恢復。

## 目前續作檢查點（2026-09-12 12:17 台北）

- 凍結來源整合 `integrated-verification-041315/`：720 項中 718 passed、2 failed、
  0 skipped，另有 1 則既有 Starlette／AnyIO deprecation warning。兩個失敗是下列
  古地圖 auxiliary 與標記清理字串衝突；正式測試未套用待仲裁候選。
- 五個前端來源解析、pnpm lint／typecheck／test、repository 及指定 workspace
  圖層契約、前後 report-only Navigation guard 退出碼皆為 0。測試前後來源 SHA 相同。
- D037 A／B、Permission 每日互動及補漏的程式修改已凍結。矩陣為 D037 45 組／
  450 階段、D026–029 51 組、D038 整頁 26 階段；這些數字不是 Chrome 通過數。
- Chrome 的任務分頁仍回報 `Debugger unattached`，已請使用者手動重整 9099。
  先前不完整回執保留，不能拿舊截圖、部分成功或 Node 回放宣稱全面驗收通過。
- 六項待仲裁：反向框選、古地圖身分、Planned／Legacy 用途、loading 向量要求、
  候選定位是否移動鏡頭，以及標記清理字串。各项詳情與候選證據見下文。
- 教學第 12 頁講稿已更正；第 5、35–38 頁須重拍，15 頁依用途裁決確認影響，
  PDF 仍待更新。教學文字提交為 `04146d12`，不得當成新截圖／PDF 已交付。

## 已確認與尚不能確認的根因

- Rudy 上游有原生細節圖磚。修前同一視角的精確快取請求失敗後，原先失敗的
  同 20 張 Z20 以 native/refresh 取得，全部 HTTP 200。
- `2c3be900`（9/11 13:09 台北）恢復 max20／exact，卻保留預設 cache-only。
  `619d0680`（9/11 15:04）主要修 Weather SVG，未補主圖 MapLibre 自動載入。
- 前次 Weather 驗的是先下載過的 70 張 Z20，與本次主圖 Z20 座標交集為 0。
  該結果不能代替主圖及未預先填入快取的視角驗證。
- 8/25 的較早策略變更只能證明潛在條件；缺少能確證本次最後正常／首次故障
  的部署收據。不得把舊日期包裝成使用者此次開始故障的時間。

## 使用者仲裁（2026-09-12 已核准）

使用者決定：「Ｄ037 AB都依照你的建議修改。Permission 依然需要互動地圖。漏測問題 要全面補齊」。
下表保留原衝突與提案歷史；實作與驗收依其後的正式決定執行。

| ID | 原標準與衝突 | 建議及影響 |
| --- | --- | --- |
| D037-A | `diagnosticWeatherRudyTileContract` 要求舊 `initialMaxZoom + ceil(log2(zoom))` 及 `nativeMaxZoom - initialZoom` 程式字串；目前 SVG 已按實際畫面尺寸與地理範圍計算。舊檢查會在真實換磚驗證前失敗。 | 改驗實際結果：Fit 後第一下 + 必須提升原生層級，放大至 Z20、平移後所需圖磚全部成功。保留嚴格結果要求，移除綁定舊實作字串的斷言。需裁決後才能修改使用中的驗收標準。 |
| D037-B | 舊 live probe 固定 SVG 與 cache-only，禁止 native／refresh；無法測一般互動地圖快取未命中時的自動補載。 | 增加選定 workspace 的 Rudy 原生 GET 測試，使用 native=1&exact=1，不強制 refresh；保留原離線快取測試。CWA 保持 cache-only，禁止準備／重建／修改行程。此測試會填入實際取得的 Rudy 圖磚快取。需使用者裁決此測試邊界。 |
| SCOPE-STATIC | Permission 每日圖原規格是 760×248 單張快取合成圖，沒有互動換磚能力；它與可放大、平移的地圖不同。 | 建議保留靜態摘要用途，另外驗證 workspace、圖片來源與清晰度；若使用者要求它也能動態放大，需明確擴充實作及驗收範圍。不能默默排除或冒稱已通過動態換磚。 |

正式決定：

- D037-A：移除綁定舊公式字串的驗收，改驗實際原生層級、視野完整性與真實換磚。
- D037-B：保留離線／cache-only 案例，新增同 workspace 的 Rudy 原生 GET 補載；
  一般模式使用 `native=1&exact=1`，不強制 refresh。CWA 維持 cache-only；不執行準備或行程寫入。
- SCOPE-STATIC：Permission 每日圖改為互動地圖，包含縮放、平移、原生換磚、停止更新及恢復。
  原「single-composite」斷言依此明確授權替換，不能以靜態摘要作為排除理由。
- 漏測補齊全部真實入口及 renderer；涵蓋首次載入、重載、Fit、第一次 +、Z20、平移、
  快取命中、真實未命中、停止及恢復。沒有真實未命中證據時不能將該階段列為通過。

上述授權不表示已通過。其他新發現的 Diagnostic／規格衝突仍交由使用者裁決。

## 全面驗證清單

初步 15 組盤點已展開為 D037 的 36 組固定入口／renderer／domain／lens，加上目前候選的
每一個 Permission on-trail day；每日資料缺失不可視為零個適用案例而通過。
固定案例涵蓋 Main／Weather／Debug 的 MapLibre 與 SVG、6 張 Dashboard SVG
（Architecture 再展開 7 種 lens）、Navigation observed 2D／3D 各 5 種 lens、SVG
fallback 5 種 lens，以及三個 domain 各自的 loading。每組檢查 10 階段（包括實際
最大倍率），其他控制、hover 及圖層順序另外驗證；目前九日資料共 45 組、450 階段。

- Dashboard SVG、Navigation、Debug 與 phase4 已接入 exact 原生策略，仍需全部實測。
- Navigation 的 camera zoom／idle／DEM 成功不等於 Rudy 原生圖磚完整；3D 必須核對
  renderer 實際要求的混合 native zoom cohort。
- D037 已從 9099 既有按鈕啟動首輪，但採證中斷，沒有取得完整通過證據。

## 追加衝突：框選方向（待使用者仲裁）

`docs/admin/scout-dashboard-100-item-functional-verification-checklist.md` 第 962／969 行
保留「右下往左上框選縮小」的舊 PASS 紀錄；目前共用 Dashboard SVG、操作說明與
既有 Diagnostic executable assertion 則要求任意方向框選放大、以減號縮小。
Debug 仍有反向框選縮小實作。2026-09-12 已將這個具體差异送交使用者；在裁決前
保留各側證據，不改寫歷史 PASS、不把兩種行為視為全站一致通過。

## 追加衝突：古地圖的正式圖層契約（待使用者仲裁）

擴大執行既有頁面測試時，`tests/test_pretrip_admin_page.py:914` 要求
`historical-map` 控件包含 `data-layer-contract="auxiliary"`；現行
`scout_layer_contract.py` 則已把它列為正式契約的一層，Pretrip 控件不含此舊標記。
Git 追溯顯示差異由 `2243c150`（2026-09-07 18:00:01 +08:00）就存在，修前
HEAD 同樣不滿足此斷言；不是本輪 Rudy 修補新增的變更。

建議依現行正式圖層契約更新舊測試，同時保留古地圖預設關閉、来源、候選邊界與
圖層順序檢查。已提交使用者仲裁，目前保留 FAIL，未改測試或降格古地圖契約。
候選 patch 已保存於 Scout `diagnostic-arbitration/historical-map-candidate/`，
候選單項回放 1 passed；正式測試檔維持原 SHA，這不是現行 FAIL 已解除的證據。

## 追加範圍：比較圖與示意原型（待使用者仲裁）

實際 source 反查發現 Golden／Planned 純向量比較圖共有九個可達實例：Permission
的 preview／compare、六力各頁的 analysis，以及 Body Index 子頁的 analysis。
它們共用 `scout-planned-route.js` 的 mapHtml，但各頁仍須核對實際來源與控制。
目前有 Golden／Planned 開關、縮放、拖曳與 Fit，不能拿 Rudy 每日圖的成功代替。

Dashboard Emergency 頁還能展開 Legacy desktop approval 示意原型；它的 Rudy
名稱對應 CSS 圖樣，沒有真實圖磚取得能力。不能列為 Rudy 已載入，也不能把其
示意線當成目前 workspace 的安全或路徑證據。

已提出用途式驗收供使用者裁決：向量比較圖驗完整互動、來源幾何及對位，示意
原型驗用途標示、圖層開關及既有權限邊界；若使用者要求全部統一為一般 Rudy
互動地圖，另依該明確決定修改。裁決前保留漏項，不改成 N/A 或宣稱已通過。

## 追加衝突：候選定位與鏡頭保存（待使用者仲裁）

D038 舊清單步驟 4／5 要求切換「候選點」後 center／zoom 保持不變；目前
`focusNavigationTerrainSelection` 卻明確把每個已就緒的鏡頭移到候選座標，並將
2D／3D 至少放大到 15／16（仍受實際 maxZoom 限制）。既有 deterministic
Diagnostic 也要求這條候選定位路徑。兩個要求不能同時滿足。

已送使用者裁決：保留點選候選的定位，把它列為明確鏡頭移動例外；或改成只
高亮、維持鏡頭。裁決前不修改既有候選操作或放寬正式斷言；實際 probe 若觀測
移動，保留該階段 FAIL，其他 view／lens／domain／Fit 的獨立檢查繼續執行。

## 追加衝突：標記清理的舊程式字串（待使用者仲裁）

`tests/test_scout_dashboard_page.py:2758` 要求單一
`asArray(entry.routeAnnotations).forEach(annotation => annotation.remove());`
字串。新清理路徑逐項捕捉錯誤，避免一個標記報錯便跳過其他標記及地圖釋放；
因此不再含該固定字串。正式舊測試維持 FAIL，沒有為通過字串檢查退回不完整清理。

Scout `diagnostic-arbitration/annotation-cleanup-candidate/` 已提供候選 patch，保留
其餘 22 個 known GPX／reference／candidate 斷言，改執行真正的清理函式，驗證
正常、第一個標記出錯及第二個標記出錯的情況。完整候選測試 1 passed；將清理
退回單組 forEach 的隔離故障注入如預期失敗，確實抓到後續標記未被清理。
候選未套用，等待使用者決定是否改驗這些實際結果。

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

後續 Chrome Overview 真實操作補充：Fit Z12 30/30、第一次 + Z13 60/60、Z20
35/35；停止更新後移到新視角，10 個唯一 tile path 確實 HTTP 404，恢復更新後同
10 個 path 全部 HTTP 200，35/35 complete，camera transform 不變。這一組只證明
Overview；`overview-z20-cache-hit-state.json` 是過早的 loading 快照，不能當成功。
可用的完成快照為 `chrome-ui/overview-z20-cache-confirmed.json` 與
`overview-network-confirmed-recovery.json`，並有独立網路紀錄。

另確認 `overflow:hidden` 容器在高倍率控制鈕聚焦時會發生內部捲動，使畫面與
camera 不一致；已改為 `overflow:clip`，實際 Chrome 重驗 scrollTop/Left 保持 0。

另在同一 Chrome 的補充觀測分頁確認最大倍率缺口：Main Fit camera 10.814712／
native Z12 30/30；第一次 + 到 camera 11.814712／native Z13 24/24；camera
18.814712 時 Z20 24/24 成功。但繼續按到 camera 22，仍回報 Z20 4/4 available，
畫面已將同一批來源像素放大約 8 倍。`chrome-ui/main-maximum-overzoom-observed`
JSON／JPG 保存這個 FAIL。D037 必須新增「實際最大倍率」階段，不能停在首次
取得 Z20；修復將保留 native Z20 能力，按來源 tile size／renderer scale 限制不實
的 overzoom。3D 還需核對未截斷的實際 tile cohort，不能以 2D camera cap 代替。

整合版首輪 D037 最後可讀進度為 Emergency review initial passed，之後原 Chrome
分頁持續回報 `Debugger unattached`。已保存
`diagnostic037-first-run-interruption.json`；此輪狀態為 INCOMPLETE。另已查出
隔離測試未明確釋放內層 MapLibre 的清理缺口，但尚不能據此宣稱它是瀏覽器中斷
的確定原因。正在補 cleanup、DOM report 及失敗時初始化收據。

後續 D037 第四輪在真實 Chrome 讀到 Main SVG 首次載入失敗：原生 Z12，
成功 0/15，但 generation state 為 ready。Source 已確認首次 renderRasterLayer
直接插圖後立即 mark ready，沒有走後續換磚使用的逐張 load／error tracking；
因此不能以 ready 或另外 GET 成功補成 PASS。修復須讓初始 Rudy 也走相同的
atomic generation 完成／失敗路徑。最後可讀進度為 20/420 階段、10 通過；其後
Chrome 讀取連續逾時，未取回完整第四輪報告，故此輪仍為 INCOMPLETE。這些
觀測不是瀏覽器連線中斷根因已證實的結論。

最新程式整合證據保存在 `integrated-verification-0252/`：相關 suites 423 passed、
一則既有 Starlette／AnyIO deprecation warning；pnpm lint／typecheck／test 命令
退出碼均為 0，圖層契約驗證與 suspended Navigation guard 退出碼為 0。另加跑
既有頁面／圖層順序 suites 為 70 passed、1 failed（上列古地圖契約衝突），五個
前端來源 script 解析通過。各組紀錄不可相加成正式 UI 通過數；整體仍未完成。

實際 render 呼叫反查另確認：Navigation ready 的 terrain／prior 各只有 structure
lens，沒有 Rudy，仍須各驗 2D／3D／SVG fallback 的互動；loading renderer 則
在三個 domain 都會顯示 Rudy，需各自列測，不只以 observed 代表。正在擴充
這些分支，Rudy 圖磚與純向量互動分開記錄實際結果，不相互冒充通過。

Navigation loading 明說沒有 terrain vectors；現行 D028 的 `vectorCount > 0`
要求與此狀態衝突，先保留 FAIL。建議只在 ready 要求完整向量，而 loading 要求
明示未就緒、驗證已有底圖來源、不得虛稱向量或資料齊備；此適用性調整仍待使用者
裁決。缺少 Box／B 控制則是實作缺口，不得改標成反向語意爭議而略過。

Navigation contour training 的 renderer 雖然存在，正式頁面 sourceMode 固定為
workspace；現行 UI 沒有 training 選擇鈕。D044 直接渲染 training fixture 的結果
只能標為 fixture 證據，不能據此宣稱使用者能從頁面選取該地圖。

本輪新增 D038 的 26 個真頁面操作階段，保留原 helper 回放並另外記錄實際
renderer、pane 尺寸、domain、lens、source、camera 及清理收據。隱藏、零尺寸、
缺少或完全重疊的 Split pane 不可通過；候選定位的既有衝突仍保留失敗。
正式 Chrome 尚未執行這個新矩陣，Node／DOM 回放不是其 live PASS。

也修補共用結果流程丟棄證據的缺口：D026–029 的逐圖結果、D038 helper／page
結果、D037 原生結果與 cleanup 收據在成功、警告及失敗時都應保留；折疊 JSON
提供可從實際 DOM 讀取的明細。iframe／Navigation 清理會等待初始化、取消待載
圖磚、逐項釋放並驗證 map.remove 收據。這些缺口已確認存在，但仍沒有證據
足以把它們定為 Chrome 連線中斷的唯一原因。

固定來源整合 `integrated-verification-035054/` 為 587 passed、3 failed；其中
camera-snapshot 格式使舊字串順序檢查誤判，已以保留原行為的 block arrow 修正。
下一個固定來源 `integrated-verification-035708/` 為 588 passed、2 failed，剩餘
為古地圖 auxiliary 與標記清理字串兩項待仲裁。兩輪都保留原失敗與來源 SHA；
pnpm 指令、前端解析、repository／實際 workspace 圖層契約及 report-only guard
退出碼均為 0，仍有一則既有 Starlette／AnyIO deprecation warning。

最後來源審閱另發現 D038 的 iframe 只傳 projectId，可能把遠端 API／使用者
選中候選代換成同名本機專案／預設候選。已補相同 API、候選、band、可用
projection／DEM fingerprint 的一致性檢查，以及共用 Navigation scope 的 API
來源失效規則。不同 API 在建立 iframe 前拒絕；每個階段都核對實際 corridor
圖層來源。無父頁資料時明列來源與缺失指紋，不冒充原選取已獲驗證。
此修補包含於 `integrated-verification-041315/`，來源整合結果如上，Chrome 仍待驗證。

仍待：全部地圖逐頁／重載／新視角／缺磚恢復實測，Debug 與每日圖新增 D026–029
案例的實際驗證，Planned／Legacy 用途裁決及對應補測、全部相關 Diagnostic 重驗、
教學受影響頁面及 PDF 真實截圖更新。既有
1–34 頁與舊證據不可重新標成今天的驗證。未完成範圍前，不能宣稱圖磚問題已解決。

所有大檔證據保存於 Scout：
`/home/alexwang0315/work/scout-pretrip-all-seven-20260910/main-rudy-zoom-20260912/`。
子目錄：`regression-history/`、`all-map-surfaces/`、`diagnostic-arbitration/`、`guide-refresh/`。
候選 `diagnostic-arbitration/proposed-dashboard.html` 不得直接提供為正式 Dashboard。
