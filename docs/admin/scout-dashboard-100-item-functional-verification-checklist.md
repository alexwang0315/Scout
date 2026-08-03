# Scout Dashboard 100 項功能驗證清單

## 目的與狀態

本文件用於一次性檢查 Scout Dashboard 各頁面的主要功能是否正常。
檢查重點不只包括「畫面有出現」，也包括資料來源、互動結果、錯誤與
空狀態、跨頁一致性，以及操作後不應發生的副作用。

- 目標：100 個可執行、可判定、可留證據的主檢查項目。
- 目前版本：36 / 100。
- 維護狀態：持續記錄中。
- 起始日期：2026-07-28。
- 維護方式：本對話串中新增或修改的檢查項目，持續追加到本文件。
- 編號規則：既有編號不重排、不重用；需求改變時保留修訂紀錄。

## 執行規則

每次完整驗證先記錄：

| 欄位 | 執行紀錄 |
|---|---|
| 執行日期與時間 |  |
| 執行人 |  |
| Git commit / 工作樹版本 |  |
| Dashboard URL |  |
| Project ID |  |
| Workspace root |  |
| 瀏覽器與版本 |  |
| 桌面視窗尺寸 |  |
| 行動視窗尺寸 |  |
| 使用的資料集或 fixture |  |

每一個主檢查項目只能使用以下結果：

- `PASS`：所有必要步驟和通過條件均成立，且證據完整。
- `FAIL`：功能缺失、結果錯誤、有未預期副作用，或證據顯示不符合契約。
- `BLOCKED`：外部服務、測試資料或執行環境不足，無法完成判定。
- `N/A`：只有該功能確實不屬於本次指定 surface 時才可使用，必須寫理由。

最低證據要求：

1. 記錄實際 URL、Project ID、時間與版本。
2. UI 功能至少保留一張結果截圖或瀏覽器自動化輸出。
3. 資料功能記錄關鍵 API 狀態、來源參照或 artifact 路徑；不得記錄密鑰。
4. 互動功能記錄操作前後狀態，不得只以「按鈕存在」判定通過。
5. 同時檢查瀏覽器 console error、失敗的必要請求與未預期的 POST。
6. 涉及外送、刪除、硬體或安全狀態的功能，只做 sandbox／preview／
   candidate 驗證，不執行真實外部副作用。

## Dashboard Diagnostic UI

Dashboard 已在 `System → Diagnostic`（位於 Settings 之後）放入目前的
`DASH-001～DASH-036`。

- 尚未測試：灰燈。
- 測試中：黃燈與 `測試中`。
- 測試通過：綠燈與 `測試通過`。
- 測試失敗：紅燈與 `測試失敗`，並顯示失敗原因。
- 每題都有獨立的 `重新測試`。
- 頁首 `Diag all` 依序執行 36 題，避免大型 project projection API
  同時被大量呼叫。

Diagnostic UI 是即時、read-only 的快速診斷層。它只使用 UI contract、
same-origin GET API 與既有 artifacts，不會自動執行 connected preparation、
workspace operation、GPX／HealthExport import、watch start、模型生成、
MQTT publish、Emergency send 或硬體控制。需要合成資料、私資料授權、
付費模型或副作用的完整流程，仍必須依本文件的人工／隔離 acceptance
步驟執行；Diagnostic 綠燈不得取代該層證據。

## 頁面功能分類索引

詳細案例依穩定編號排列；實際驗收時依下表按頁面分批執行。

| 頁面功能分類 | 已可驗收項目 |
|---|---|
| 全域與 Overview | DASH-001、DASH-002、DASH-011 |
| Plan Trip 與 Workspace | DASH-003、DASH-007、DASH-012～DASH-014 |
| Map & Evidence | DASH-004～DASH-006、DASH-016、DASH-017、DASH-026～DASH-030 |
| Exploring for Six Axis | DASH-008、DASH-018～DASH-025、DASH-031～DASH-036 |
| Assistant、System 與 Safety / Emergency | DASH-009、DASH-010、DASH-015 |

本版刻意不收錄未接線的 preview、placeholder 或未來規劃。已實作的
candidate/shadow prototype 可收錄，但必須把 no-authority 邊界當成必要
通過條件；只有具備可操作 UI、API／artifact 與明確 PASS／FAIL 證據的功能
才會成為正式檢查項目。

## 目前可驗收的 36 項功能

### DASH-001 Dashboard 啟動、入口與必要 API 可用

- 頁面／範圍：全域、Dashboard 入口。
- 優先級：P0。
- 前置條件：指定 Project ID 與 Workspace root；使用實際 Dashboard runtime。

檢查步驟：

1. 確認 `127.0.0.1:9099` 有 Dashboard 程序監聽。
2. 開啟 `/admin/dashboard?projectId={project_id}`。
3. 檢查 Dashboard、workspace catalog、目前 workspace、pre-trip project、
   admin projection、debug projection events、Weather Dashboard、Navigation
   Terrain Intelligence 與 connected-preparation status 等必要端點。
4. 以真實瀏覽器完成首次載入，檢查 console、network 與畫面 loading 狀態。
5. 重新整理一次，確認仍可載入相同專案。

通過條件：

- Dashboard 與本次完整驗證所需的必要 API 都回應成功。
- Workspace selector 顯示指定專案，resolved project root 正確。
- 所有永久 loading 狀態都在合理時間內結束；失敗時有可理解的錯誤與重試入口。
- 首次開頁沒有 JavaScript error、必要資源 4xx/5xx 或空白主畫面。
- 首次開頁只讀，不會自動送出 connected-preparation POST 或其他寫入請求。

證據／結果：

- 結果：`未執行`
- 證據：
- 缺陷編號：
- 備註：

### DASH-002 全站導覽、路由與返回狀態

- 頁面／範圍：側邊導覽列與全部 Dashboard route。
- 優先級：P0。

檢查步驟：

1. 依序開啟 Overview、Workspace、Trip Intake、Country Material Pool、
   Map、Timeline Evidence、LBS、Route Context、
   Pace Dashboard、Body Index、Permission、Architecture、Weather、
   Navigation、Safety / Emergency、Assistant、Living、Debug Surface、
   Debug Message、MQTT / Observer、Settings。
2. 每次切頁檢查 active 樣式、頁面標題、maturity、truth strip 與主要內容。
3. 使用瀏覽器上一頁／下一頁，再重新整理目前 route。
4. 在窄螢幕開關側邊選單，確認焦點與展開狀態正確。

通過條件：

- 每個導覽入口都能到正確 route，沒有空白頁、錯頁或殘留上一頁資料。
- active route、標題、truth strip 與實際內容一致。
- 返回、前進與重新整理後仍保留 Project ID 和正確 route。
- Plan Trip 不顯示 Pre-trip Surface，System 不顯示 Admin Surface；舊 hash
  會安全返回 Overview。
- preview／partial／live／sandbox 標示不會把候選功能誤標為已完成或安全真值。
- 桌面與窄螢幕都能操作所有導覽項目，沒有被遮住或水平溢出。

證據／結果：

- 結果：`未執行`
- 證據：
- 缺陷編號：
- 備註：

### DASH-003 Workspace 清單、切換與專案資料隔離

- 頁面／範圍：Plan Trip → Workspace。
- 優先級：P0。

檢查步驟：

1. 檢查 server-owned workspace catalog、workspace parent root 與目前選取項目。
2. 切換到另一個有效 workspace，核對 URL、標題、路線統計與資料來源。
3. 嘗試無效或不存在的 workspace ID。
4. 切回原 workspace，重新整理頁面。
5. 觀察切換與首次載入期間的 network requests。

通過條件：

- Catalog 只列出 server 允許範圍內的專案，不能由瀏覽器指定任意檔案路徑。
- 有效切換必須先通過 server 驗證，再更新 URL 與 local state。
- 無效切換會顯示錯誤並保留原 workspace，不得留下半切換狀態。
- 切換後所有頁面使用同一 Project ID，不得混入前一個 workspace 的資料。
- 開啟或切換 workspace 不會自動啟動外部資料更新、準備流程或 runtime 狀態變更。

證據／結果：

- 結果：`未執行`
- 證據：
- 缺陷編號：
- 備註：

### DASH-004 32 層圖層契約、來源與幾何內容

- 頁面／範圍：Map、Weather、Debug Surface。
- 優先級：P0。
- 契約基準：`scout_layer_contract.py`。

系統 canonical layer contract 共 32 層：

1. `imagery`
2. `rudy`
3. `rudy-twmap`
4. `relief`
5. `geology`
6. `topo-5k`
7. `forest`
8. `osm`
9. `terrain`
10. `corridors`
11. `overpass`
12. `route`
13. `completed-track`
14. `reference-tracks`
15. `retreat`
16. `segments`
17. `risk-ribbon`
18. `risk-heatmap`
19. `risk-delta`
20. `soil-moisture`
21. `antecedent-rain`
22. `cwa-qpf`
23. `risk-score`
24. `checkpoints`
25. `pois`
26. `hazards`
27. `route-notes`
28. `cwa-weather`
29. `mcp`
30. `boss-points`
31. `events`
32. `weather-api`

檢查步驟：

1. 先執行 deterministic layer-contract verifier，確認 ID、順序、surface 與
   render group 契約。
2. Dashboard／Pre-trip／Debug 應檢查 31 層；`completed-track` 只能出現在
   After-action，因此在這三個 surface 不得當成 pre-trip 路線真值。
3. 逐層檢查控制入口、來源狀態、artifact/source ref、資料筆數或 tile 請求。
4. 逐層開關，確認實際 render group、圖磚或約定的點／線／面幾何同步顯示與隱藏。
5. 檢查 z-order：底圖在下、terrain/context 居中、route/risk/checkpoint 等
   操作證據在上。
6. 模擬一個 raster source 或候選 evidence 缺失，確認其他向量與路線不會被清空。
7. 檢查控制權：`soil-moisture`、`antecedent-rain`、`cwa-qpf`、
   `cwa-weather`、`weather-api` 由 Weather 頁操作；Map 頁不得出現重複控制。

通過條件：

- 契約驗證為 PASS，32 個 canonical ID 無缺少、重複或錯序。
- 各 surface 的圖層數與擁有權正確；Dashboard／Pre-trip 不誤用
  `completed-track`。
- 每層都能指出真實來源與約定的圖磚／點／線／面內容；空 layer group
  不得假裝渲染成功。
- 圖層開關會改變實際可見內容，不只是 checkbox 狀態改變。
- 無資料時明確顯示 unavailable／empty 與原因，不得捏造幾何。
- 單一圖層失敗不會使路線或其他證據一起消失。

證據／結果：

- 結果：`未執行`
- 證據：
- 缺陷編號：
- 備註：

### DASH-005 地圖基本操作、鍵盤操作與圖徵選取

- 頁面／範圍：Map 與嵌入式 canonical pre-trip map。
- 優先級：P0。

檢查步驟：

1. 使用滑鼠拖曳平移、滾輪放大縮小、`+`／`-` 控制、雙擊放大。
2. 執行框選放大與框選縮小；若產品沒有提供入口，記為 `FAIL／未實作`，
   不以 `N/A` 略過。
3. 使用 fit-to-route、reset／home，確認可回到完整路線範圍。
4. 將焦點移入地圖，以方向鍵平移、`+`／`-` 鍵縮放，並確認焦點可見。
5. 點選可互動的點、線、面圖徵，檢查 hover、selected 樣式與詳細資料。
6. 操作期間切換兩個以上圖層，再繼續平移與縮放。
7. 快速連續縮放、平移至資料邊界外，再回到路線。

通過條件：

- 所有指定滑鼠、控制鈕、框選與鍵盤操作都會改變正確 viewport。
- 地圖不跳回錯誤位置、不產生無限 tile request、不出現永久空白。
- fit-to-route 能容納完整路線且有合理 padding；reset 結果可預期。
- 點、線、面只選到目前可見且可互動的圖徵，詳細資料與來源一致。
- 圖層切換不會重設非必要的 viewport 或破壞後續互動。
- 全程無 JavaScript error，且操作不會觸發寫入、安全判定或外送。

證據／結果：

- 結果：`未執行`
- 證據：
- 缺陷編號：
- 備註：

### DASH-006 Timeline Evidence 分類、分頁與地圖連動

- 頁面／範圍：Map & Evidence → Timeline Evidence。
- 優先級：P0。

檢查步驟：

1. 開啟 CP / Timeline，確認 8 個分類標題都存在且預設收合。
2. 開啟 Map / Risk，確認 31 個分類標題都存在且預設收合。
3. 展開有資料、無資料及「資料在其他頁」的分類。
4. 切換至第 2 頁及最後一頁，再切回第 1 頁。
5. 點選 evidence row，核對時間、類型、來源、provenance、地圖定位與詳情。
6. 切換 workspace 後重做一筆 evidence 選取。

通過條件：

- 分類標題不會因分頁、空資料或收合狀態而消失。
- 預設收合，不會因前幾個大型分類展開而讓後續能力看似不存在。
- 「真正無資料」與「資料在其他頁」有不同且正確的提示。
- 分頁數、目前頁、上一頁／下一頁與列數一致，沒有重複或遺失 evidence。
- Evidence 詳情、地圖位置與 source ref 指向同一筆資料。
- Workspace 切換後不殘留前一專案的 selection 或 evidence。

證據／結果：

- 結果：`未執行`
- 證據：
- 缺陷編號：
- 備註：

### DASH-007 Trip Intake 的 GPX 驗證、預覽與建立流程

- 頁面／範圍：Plan Trip → Trip Intake。
- 優先級：P0。

檢查步驟：

1. 選擇一份有效 GPX，依序執行 Validate Intake → Preview Import。
2. 核對解析後的名稱、軌跡／segment、點數、bounds、距離、警告與預覽地圖。
3. 在明確確認後執行 Create Workspace，再 Open Workspace。
4. 以 malformed GPX、空軌跡、重複 Project ID 與不合法選項測試失敗路徑。
5. 檢查 optional import parameters 的預設值與使用者修改值。
6. 觀察整個流程的檔案寫入範圍與 network requests。

通過條件：

- Validate、Preview、Create 是分離步驟；預覽前不寫入，建立前必須明確確認。
- 預覽統計與 GPX 實際內容一致，trk/trkseg 邊界不會產生人造直線。
- 建立只發生在 server-resolved workspace root 內，不能路徑穿越或覆蓋既有專案。
- 錯誤輸入有欄位層級或步驟層級說明，且不留下半成品 workspace。
- 建立完成不會自動準備圖層、抓取外部資料、載入 runtime 或改變安全真值。
- 原始格式與 provenance 被保留；不得不必要地轉換或遺失來源資訊。

證據／結果：

- 結果：`未執行`
- 證據：
- 缺陷編號：
- 備註：

### DASH-008 Weather 五圖層、CWA 控制與候選決策

- 頁面／範圍：Exploring for Six Axis → Weather。
- 優先級：P0。

檢查步驟：

1. 確認 `soil-moisture`、`antecedent-rain`、`cwa-qpf`、`cwa-weather`、
   `weather-api` 五個控制都存在並連接 canonical pre-trip map。
2. 切換 QPE／QPF、降雨格網透明度、radar／satellite product 與透明度。
3. 切換 3／6／9／12 小時視窗、影格與播放／暫停。
4. 核對 Decision / Why / Where / When、route trend、risk features、
   terrain interaction、freshness、data delay、confidence 與 source refs。
5. 模擬 stale、partial、missing cache 與單一 imagery 失敗。
6. 在 390×844 窄螢幕重做五圖層開關與主要 CWA 控制。

通過條件：

- 五個控制都可見、可操作，且實際改變 canonical map 對應圖層。
- CWA 控制與圖例、時間、透明度及顯示影格同步，播放不會失控或重複計時器。
- API、頁面數值、地圖顯示與來源時間一致。
- 缺失或過期的重要證據會明確降級並 fail closed 至 `DELAY`，不捏造 GO。
- 單一 raster／imagery 失敗不會清空路線、其他天氣資料或整頁。
- 全部輸出維持 cache-only、candidate-only、human-review-required，
  不外送也不改變 runtime safety truth。

證據／結果：

- 結果：`未執行`
- 證據：
- 缺陷編號：
- 備註：

### DASH-009 Assistant 狀態、提問、證據與錯誤復原

- 頁面／範圍：Assistant。
- 優先級：P0。

檢查步驟：

1. 開頁後檢查 `/assistant/status` 與 provider readiness。
2. 對目前 workspace 提出一題可由現有 evidence 回答的問題。
3. 核對 loading、完成、來源參照、模型／工具狀態與回答中的 Project ID。
4. 測試空白輸入、過長輸入、連續送出與安全邊界問題。
5. 模擬 timeout、provider unavailable、工具失敗與 malformed response。
6. 切換 workspace 後再提問，確認上下文更新。

通過條件：

- readiness 顯示與實際 query 能力一致，不會只因 feature flag 開啟就顯示可用。
- 有效問題得到與當前 workspace 證據一致的回答及可追溯來源。
- Loading 期間不重複送出；完成或失敗後 UI 可恢復並允許重試。
- 錯誤訊息不洩漏密鑰、完整環境變數、私人資料或內部 stack trace。
- Workspace 切換後不沿用舊專案的 evidence、回答或 selection。
- Assistant 只能提出候選分析；不得執行外送、硬體控制或變更 runtime safety truth。

證據／結果：

- 結果：`未執行`
- 證據：
- 缺陷編號：
- 備註：

### DASH-010 Debug、Observer、Emergency 與設定的安全副作用邊界

- 頁面／範圍：Debug Message、MQTT / Observer、Safety / Emergency、Settings。
- 優先級：P0。

檢查步驟：

1. 在 Debug Message 檢查事件排序、篩選、選取、payload 摘要與 source ref。
2. 在 MQTT / Observer 檢查連線狀態、最新訊息、空狀態與斷線狀態。
3. 在 Safety / Emergency 檢查 desktop iframe、候選決策、操作工具列與邊界說明。
4. 在 Settings 檢查有效設定、來源與錯誤狀態；確認敏感值已遮蔽。
5. 操作所有 preview／sandbox 按鈕，觀察 network、MQTT、檔案與 runtime 狀態。
6. 模擬無事件、Observer 離線、Emergency iframe 失敗及設定缺失。

通過條件：

- Debug 資料順序、詳情與來源一致，無資料時有明確空狀態。
- Observer 僅觀察，不會因開頁或測試操作 publish MQTT 或假裝已連線。
- Emergency 保持 `sent=false`、`external_send_performed=false`；
  不呼叫真實 `/safety/*`、不控制硬體、不外送訊息。
- Settings 不顯示 credential、token、password、private key 或完整 `.env` 值。
- 各頁失敗互相隔離，可重試或返回，不會拖垮整個 Dashboard。
- 任何候選／preview 操作都不會變更 Phase 1 或其他 runtime safety truth。

證據／結果：

- 結果：`未執行`
- 證據：
- 缺陷編號：
- 備註：

### DASH-011 Overview Current Decision Brief 與全域狀態摘要

- 頁面／範圍：Overview。
- 頁面分類：全域與 Overview。
- 優先級：P0。

檢查步驟：

1. 開啟 Overview，核對 Current Decision Brief、route context、
   weather／terrain freshness 與 evidence gaps。
2. 核對 workspace metadata、目前 Project ID、preview taxonomy 與主要導覽入口。
3. 將一個必要來源模擬為 stale、missing 或 failed，再重新載入 Overview。
4. 在桌面與 390×844 窄螢幕檢查內容順序、卡片範圍與水平溢出。

通過條件：

- Current Decision Brief 使用目前 workspace 的資料，不顯示上一專案內容。
- Route context、freshness 與 evidence gaps 能指出來源或缺口，不以靜態文案假裝 live。
- Stale／missing／failed 狀態會覆蓋原本 truth strip，不保留錯誤的 Operational 表示。
- 主要導覽入口可操作，Overview 不會因次要 metadata 過多而遮蔽目前狀態。
- 桌面與窄螢幕均無頁面級水平溢出或 JavaScript error。

證據／結果：

- 結果：`未執行`
- 證據：
- 缺陷編號：
- 備註：

### DASH-012 Workspace Operations 與非執行型操作收據

- 頁面／範圍：Plan Trip → Workspace → Workspace Operations。
- 頁面分類：Plan Trip 與 Workspace。
- 優先級：P0。

檢查步驟：

1. 檢查 Clone、Transfer、Package、Restore、Delete review、Import trip、
   Refresh evidence 與 Open workspace 控制。
2. 對 Clone、Transfer、Package、Restore 與 Delete review 各建立一筆測試請求。
3. 核對 `reviews/workspace_operation_requests.jsonl` 的 bounded intent receipt。
4. 重新整理頁面，確認最新收據與操作結果仍可辨識。
5. 核對操作前後 workspace 檔案、目前專案與 runtime 狀態。

通過條件：

- Workspace Operations 位於 Workspace 頁主要統計之前，按鈕文字不溢出。
- 每次操作都產生可追溯收據，包含正確 project、action、時間與輸入摘要。
- 收據明確標示 `execution_performed=false` 與
  `runtime_safety_truth=false`。
- Clone／Transfer／Package／Restore 不執行真實檔案操作；Delete 只建立 review request。
- 頁面重新整理後不會把 intent receipt 誤顯示為已執行結果。

證據／結果：

- 結果：`未執行`
- 證據：
- 缺陷編號：
- 備註：

### DASH-013 Connected Preparation 狀態與明確 Refresh

- 頁面／範圍：Workspace、Weather 與 connected-preparation status。
- 頁面分類：Plan Trip 與 Workspace。
- 優先級：P0。

檢查步驟：

1. 首次開啟 Dashboard，只讀取 connected-preparation status。
2. 確認首次載入與 workspace 切換沒有自動 POST。
3. 由 `Refresh evidence` 明確觸發一次 connected preparation。
4. 觀察 queued、running、completed／failed、request activity 與來源狀態。
5. 工作進行中再次按 Refresh，檢查 single-flight 行為。
6. 完成後重新載入 Weather 與 Map 相關來源狀態。

通過條件：

- 只有明確的 operator action 會送出 connected-preparation POST。
- Queued／running 不會提前顯示 false、failed 或 completed。
- 同一 workspace 的重複請求不會建立平行重複工作。
- 完成後 prepared artifacts 與 freshness 更新；失敗時保留可理解的原因與重試入口。
- Refresh 不重建未包含在 connected refresh 的 terrain、OCR、Boss 或 mileage 成果。
- 所有結果維持 candidate-only，不變更 runtime safety truth。

證據／結果：

- 結果：`未執行`
- 證據：
- 缺陷編號：
- 備註：

### DASH-014 Country Material Pool 國別資料來源與預設值

- 頁面／範圍：Plan Trip → Country Material Pool、Trip Intake。
- 頁面分類：Plan Trip 與 Workspace。
- 優先級：P1。

檢查步驟：

1. 依序切換 Taiwan、Japan 與 Global fallback。
2. 核對 material class cards、provider matrix、factory defaults 與
   map-preparation usage。
3. 在 Taiwan 檢查 route-context P0／P1 discovery references。
4. 回到 Trip Intake，核對 material root、DTM dirs、import profile 與
   OSM PBF URL 的 pool-derived defaults。
5. Taiwan → Japan → Global 來回切換，檢查舊國別 override 是否被清除。

通過條件：

- Taiwan、Japan、Global 的 provider scope 與預設值彼此隔離。
- CWA 不會被當成 Japan 或 Global 的預設天氣來源。
- Taiwan route-context references 明確標示 discovery-only，不假裝是本路線證據。
- Trip Intake 正確帶入選定 pool 的預設值，advanced override 仍可辨識。
- 切換國別不殘留上一國的 provider／路徑值。
- 此頁只讀 registry，不抓取資料、不修改 workspace、不載入 runtime package。

證據／結果：

- 結果：`未執行`
- 證據：
- 缺陷編號：
- 備註：

### DASH-015 Debug canonical surface 嵌入

- 頁面／範圍：System → Debug Surface。
- 頁面分類：Assistant、System 與 Safety / Emergency。
- 優先級：P0。

檢查步驟：

1. 開啟 Debug Surface。
2. 核對 iframe URL、標題、目前 Project ID 與 canonical page 的主要內容。
3. 等待 `Inner surface ready - content verified` 或等價的 readiness 證據。
4. 使用 `Skip embedded surface`，確認鍵盤焦點移至 frame 後方的 exit marker。
5. 切換 route 再返回，檢查 frame 是否錯誤重載、失去 Project ID 或空白。
6. 模擬 iframe 404／timeout，確認外層 Dashboard 可復原。

通過條件：

- Debug iframe 載入正確 canonical surface，而非複製或過期的靜態內容。
- 內層內容、外層 route、Project ID 與 truth strip 一致。
- Readiness 必須驗證內層主要內容，不能只以 iframe load event 判定成功。
- 鍵盤使用者可以跳過 iframe 並繼續操作 Dashboard。
- Debug Surface 失敗不會使側邊導覽或整個 Dashboard 無法使用。

證據／結果：

- 結果：`未執行`
- 證據：
- 缺陷編號：
- 備註：

### DASH-016 Map 單次 projection、漸進載入與 Retry

- 頁面／範圍：Map。
- 頁面分類：Map & Evidence。
- 優先級：P0。

檢查步驟：

1. 從其他 route 首次開啟 Map，記錄 compact project projection 請求數。
2. 觀察 Preparing route map、base ready、enhanced ready／degraded 與
   Map Evidence 出現順序。
3. 核對外層 Dashboard 從 `scoutPretripProjectBridge` 採用同一份 projection。
4. 再次開啟同一專案，核對 server cache hit 與內容一致性。
5. 以測試環境讓載入超過 timeout，按 Retry。
6. 變更 workspace artifact 後再讀取，確認 cache signature 失效。

通過條件：

- 一次 Map 開啟只建立一個 compact project projection，不由內外層重複請求。
- Base map 可用後先解除空白 loading；optional enhancements 可並行完成或誠實降級。
- Map Evidence 與地圖來自同一 in-memory projection，數量與來源一致。
- Timeout 顯示明確 degraded panel，Retry 保留目前 workspace。
- Cache hit 不改變資料內容；workspace 檔案變更會使 cache 正確失效。
- 全程無永久 loading、失敗請求風暴或 JavaScript error。

證據／結果：

- 結果：`未執行`
- 證據：
- 缺陷編號：
- 備註：

### DASH-017 Map Segment、風險覆蓋與 layer preset

- 頁面／範圍：Map。
- 頁面分類：Map & Evidence。
- 優先級：P0。

檢查步驟：

1. 核對 route、segments、checkpoints、MCP、boss-points、risk-ribbon、
   risk-heatmap 與 risk-delta 的 API／artifact 數量。
2. 檢查每個 Segment path 非空、ID 唯一，且不是複製 generic Route path。
3. 切換 default 與 Risk Review 等現有 preset。
4. 逐一選取 Segment、checkpoint 與風險圖徵，核對 Map Evidence 詳情。
5. 關閉再開啟 Segment 兩輪，確認 geometry 仍連通且樣式恢復。
6. 檢查 Weather 所屬五個圖層不會因 preset 在 Map 頁重新出現。

通過條件：

- 畫面圖徵數與目前 project projection／artifact 相符，沒有空 path 或重複 ID。
- Segment 保留自身 geometry、provenance 與可見樣式，不被 route fallback 取代。
- Preset 同步更新實際 layer visibility，且不破壞 operator 後續逐層調整。
- 圖徵選取詳情與點選的 Segment／checkpoint／risk source 一致。
- 多次 toggle 不會 detach、遺失 geometry 或產生 console error。
- Map preset 不奪回 Weather 頁擁有的五個控制。

證據／結果：

- 結果：`未執行`
- 證據：
- 缺陷編號：
- 備註：

### DASH-018 Route Context canonical briefing

- 頁面／範圍：Exploring for Six Axis → Route Context。
- 頁面分類：Exploring for Six Axis。
- 優先級：P0。

檢查步驟：

1. 開啟 Route Context，核對目前 project 對應的 briefing iframe URL。
2. 檢查 canonical briefing 標題、路線、停留點、照片、住宿、terrain、
   weather／season 與 source tier。
3. 使用 Open briefing 在獨立頁開啟相同 artifact。
4. 核對 source artifact、skill 與 collection provenance。
5. 測試 briefing artifact 缺失或 404 狀態。

通過條件：

- Dashboard 與獨立頁載入同一個目前 workspace briefing。
- 必要 route-context 章節、照片與來源參照可讀，沒有殘留其他 Project ID。
- Artifact、skill、collection 與產生來源可追溯。
- 缺失 artifact 顯示明確錯誤，不以舊簡報或靜態文案替代。
- Briefing 維持 candidate-only，不授予 departure、stop permission 或 route open/closed。

證據／結果：

- 結果：`未執行`
- 證據：
- 缺陷編號：
- 備註：

### DASH-019 Route Context 現有 variants 與 reference gate

- 頁面／範圍：Route Context → variants drawer。
- 頁面分類：Exploring for Six Axis。
- 優先級：P1。

檢查步驟：

1. 讀取目前 variants status，不觸發新的模型生成。
2. 展開 drawer，核對五個既有 variant、index、comparison 與 model audit。
3. 逐一開啟五個 canonical `?ref=` artifact URL。
4. 核對 token usage、model、output directory 與 reference similarity gate。
5. 模擬其中一個 artifact 缺失或不允許的 ref。

通過條件：

- 五個既有 variant 與 metadata 都屬於目前 project 的 active output directory。
- 所有 artifact URL 由安全 artifact endpoint 提供，不能路徑穿越。
- Reference gate 的 observed、allowed 與 pass/fail 顯示一致。
- 缺失或非法 ref 被拒絕，不回傳任意 workspace 檔案。
- 此驗收只讀現有 artifacts，不產生新的模型費用或外部副作用。

證據／結果：

- 結果：`未執行`
- 證據：
- 缺陷編號：
- 備註：

### DASH-020 Pace Dashboard 資訊與 read-only 控制

- 頁面／範圍：Exploring for Six Axis → Pace Fit → Pace Dashboard。
- 頁面分類：Exploring for Six Axis。
- 優先級：P0。

檢查步驟：

1. 核對 route、current CP、leave-by、team pace 與 boundary status。
2. 檢查 Pace Controls、Current CP Status、Next Segment Risk、
   Risk Budget Calculator、CP Timeline 與 Pace Output。
3. 核對 Pace Evidence、Artifact Metadata、Residual Risk、
   Pace Object Preview 與 synchronized map。
4. 操作現有 pace parameters，確認標示為 read-only parameter，而非假按鈕。
5. 選取 CP／segment，核對 timeline、map 與詳情同步。

通過條件：

- 三欄 dashboard 的主要資料區塊都有目前 workspace 內容或誠實空狀態。
- CP、segment、pace evidence 與 artifact metadata 可相互追溯。
- Read-only 參數不會暗示已改變 runtime 或寫入 workspace。
- Map、timeline 與選取詳情指向同一 CP／segment。
- 頁面不顯示已移除的低資訊 Decision、Confidence 或 Next action 區塊。
- 全部結果維持 advisory／dry-run，不修改安全真值或外送。

證據／結果：

- 結果：`未執行`
- 證據：
- 缺陷編號：
- 備註：

### DASH-021 Body Index sanitized overview 與空狀態

- 頁面／範圍：Pace Fit → Body Index。
- 頁面分類：Exploring for Six Axis。
- 優先級：P0。

檢查步驟：

1. 以沒有 Body Index snapshot 的乾淨測試 project 開頁。
2. 確認九個 Pace Coefficient cards、八個 Health Baseline Signals、
   pressure timeline 與 provider metrics 的空狀態。
3. 改用已有 sanitized snapshot 的測試 project。
4. 核對 coverage、numeric median／sample count、min-average-max trend
   與 route impact mapping。
5. 在桌面與行動寬度檢查卡片、drawer 與 timeline。

通過條件：

- 無資料時顯示 unavailable／pending／`--`，不顯示 sample 數值或預設健康判斷。
- 有資料時數值、coverage 與 trend 來自 sanitized aggregate snapshot。
- 九個 section 7.2 cards 始終存在，但沒有 evidence 時不得產生 coefficient。
- UI／API／snapshot 不包含 raw HealthExport rows、GPX、座標、原始檔名或精確時間。
- Provider values 明確保持 source-provider planning evidence，不是診斷或安全真值。

證據／結果：

- 結果：`未執行`
- 證據：
- 缺陷編號：
- 備註：

### DASH-022 Body Index synthetic import、merge 與 dedup

- 頁面／範圍：Body Index → Import HealthExport。
- 頁面分類：Exploring for Six Axis。
- 優先級：P0。
- 前置條件：只使用合成 HealthExport fixture 與隔離的測試 workspace。

檢查步驟：

1. 以 `confirm_import: true` 匯入一組有效 synthetic export。
2. 核對 processed、merged、skipped、errors 與 snapshot 更新。
3. 將同內容重新命名後再次匯入。
4. 加入一個新來源與一個 malformed source，再次匯入。
5. 檢查 persisted sanitized snapshot 與 Dashboard 更新。

通過條件：

- 首次匯入只合併有效來源並即時刷新 Body Index。
- 相同內容依 SHA-256 去重，不因檔名不同重複計入。
- Malformed source 被隔離並報錯，不會讓有效 snapshot 變成計算完成的假資料。
- Persisted snapshot 僅含 sanitized counters、aggregates 與 metric names。
- 不讀取真實私人 HealthExport，不呼叫 safety API、不控制硬體、不外送。

證據／結果：

- 結果：`未執行`
- 證據：
- 缺陷編號：
- 備註：

### DASH-023 Body Index synthetic directory watch lifecycle

- 頁面／範圍：Body Index → Start Watch／Stop。
- 頁面分類：Exploring for Six Axis。
- 優先級：P1。
- 前置條件：使用短期 synthetic fixture 目錄；案例結束前必須停止 watcher。

檢查步驟：

1. 開頁確認 watcher 預設為 stopped。
2. 未提供 `confirm_watch: true` 嘗試啟動，確認被拒絕。
3. 設定短測試 interval 並明確確認啟動。
4. 新增一個 synthetic zip，等待 scan、import 與 baseline refresh。
5. 按 Stop，確認狀態停止且 scan count 不再增加。
6. 重啟 Dashboard 程序，確認 watcher 不會自行恢復。

通過條件：

- Watcher 預設停止，且沒有明確確認不能啟動。
- Status 正確更新 running、interval、scan/import count 與 sanitized result。
- 新 synthetic source 只匯入一次，Dashboard 自動顯示更新後 aggregate。
- Stop 後不再掃描；程序重啟後仍為 stopped。
- Watch 輸出不洩漏原始檔名、GPX、座標、raw health rows 或精確時間。

證據／結果：

- 結果：`未執行`
- 證據：
- 缺陷編號：
- 備註：

### DASH-024 Architecture workbench 與 Segment Microscope

- 頁面／範圍：Exploring for Six Axis → Architecture。
- 頁面分類：Exploring for Six Axis。
- 優先級：P0。

檢查步驟：

1. 核對 Route Fingerprint 七條 lane、共同里程軸與目前資料 coverage。
2. 切換 Structure、Demand、Reversibility、Evidence reading mode。
3. 切換 terrain、slow passage、risk passage、reversibility、evidence map lens。
4. 選取一個 Segment，核對 fingerprint、map、legend 與 Segment Microscope。
5. 檢查 retreat-dependency view、candidate graph 與 missing architecture 狀態。
6. 在行動寬度測試 Spine／Map／Segment 切換與 sticky inspector。

通過條件：

- Fingerprint、map 與 microscope 使用相同 segment ID 與 route-distance bin。
- Lens legend 隨目前 lens 改變，顏色、unknown 與 selected marker 說明正確。
- Missing normalized architecture／reviewed mission graph 顯示 partial／unverified，
  不捏造 branch、alternative 或 reversibility。
- Retreat view 只顯示有來源的 candidate edges。
- 頁面只使用 aggregate candidate evidence，不暴露 raw GPX、私人健康資料或精確時間。

證據／結果：

- 結果：`未執行`
- 證據：
- 缺陷編號：
- 備註：

### DASH-025 Navigation Terrain Intelligence 與 Rudy+TW map

- 頁面／範圍：Exploring for Six Axis → Navigation。
- 頁面分類：Exploring for Six Axis。
- 優先級：P0。

檢查步驟：

1. 載入 Workspace evidence，核對 terrain-intelligence API、bounded route
   points、terrain hierarchy、pressure candidates 與 ordered events。
2. 檢查 Rudy+TW WMTS 為唯一 basemap，初始 tile matrix 與可見 tile 回應成功。
3. 從 Fit 狀態記錄初始 tile matrix，使用一次 `+` 後確認 dataset 與實際
   Rudy+TW request 的 `TILEMATRIX` 都立即升一級；再使用 `-`、鍵盤與
   mouse drag 核對 matrix／translation 更新。
4. 切換 Structure、Pressure、Risk、Retreat lenses。
5. 點選 hierarchy／pressure／event，核對 Inspector 與來源。
6. 切換 Training fixture，檢查八個 annotation 與 Map Literacy Checklist。
7. 在 390×844 檢查控制、map、timeline 與頁面寬度。

通過條件：

- Workspace evidence 與 Training fixture 清楚分離，不把合成 annotation 說成真實路線。
- Rudy+TW 是唯一底圖；第一次 `+` 不得只拉伸原圖磚，必須立即載入下一個
  matrix 級別；pan 不改變 zoom。
- Route、hierarchy、pressure 與 event overlays 保持 candidate-only 且可追溯。
- 未準備的 ridge／valley／saddle 明確顯示 `not_prepared`，不從 raster 猜測。
- 所有 Inspector selection 與地圖 marker／event 一致。
- 行動版無頁面級水平溢出，console 與必要請求無錯誤。

證據／結果：

- 結果：`未執行`
- 證據：
- 缺陷編號：
- 備註：

### DASH-026 所有 Dashboard 地圖 evidence hover hint 一致性

- 頁面／範圍：Overview、LBS、Permission、Map、Weather、Navigation、
  Safety / Emergency、Architecture、Pace Fit 的全部 9 個 Dashboard 地圖實例。
- 頁面分類：Map & Evidence。
- 優先級：P0。

檢查步驟：

1. 依 `DASHBOARD_MAP_SURFACES` registry 開啟全部 9 個地圖實例，等待圖層與
   evidence 完成載入。
2. 依序把滑鼠移入每張圖的一個點、線、面、圖層或事件 evidence。
3. 使用 Tab 將鍵盤焦點移到同一類 evidence。
4. 核對 hint／tooltip 的標題、摘要、來源或 candidate 邊界。
5. 移出 evidence、按 Escape 或切換頁面，確認 hint 正確關閉。

通過條件：

- Registry 內全部 9 張圖的 evidence 都能在 hover 與鍵盤 focus 時顯示
  可讀提示。
- 嵌入 Map／Weather 的樣式不得把既有 `#hoverHint` 隱藏或裁切在 iframe 外。
- Dashboard-native SVG 地圖必須使用共用 hover/focus hint contract；嵌入式
  canonical map 可保留既有 `#hoverHint`，但不得隱藏。
- Hint 內容來自目前 evidence，不洩漏 raw GPX、精確時間或私人健康資料。

證據／結果：

- 結果：`PASS`（2026-08-03，Chromium）
- 證據：9/9 地圖均找到可 focus 的 evidence target，並顯示非空 hint；
  最新 registry 已包含 Permission Map 與 Safety / Emergency Review Map。
- 缺陷編號：
- 備註：0 POST。

### DASH-027 所有 Dashboard 地圖框選縮放與鍵盤平移

- 頁面／範圍：Overview、LBS、Permission、Map、Weather、Navigation、
  Safety / Emergency、Architecture、Pace Fit 的全部 9 個 Dashboard 地圖實例。
- 頁面分類：Map & Evidence。
- 優先級：P0。

檢查步驟：

1. 在每張圖啟用 Box／矩形縮放模式。
2. 由左上往右下拖曳一個矩形，確認局部放大且選取框在拖曳時可見。
3. 由右下往左上拖曳矩形，確認支援局部縮小。
4. 聚焦地圖後依序按方向鍵，確認四個方向均能平移。
5. 使用 `B`、`P` 與 Escape 切換或取消操作，確認不影響頁面捲動與表單。
6. 在每張圖上轉動滑鼠滾輪，確認地圖 zoom 不變且頁面可正常捲動。

通過條件：

- Registry 內全部 9 張圖都能完成矩形放大與反向矩形縮小。
- 四個方向鍵都會改變地圖位置，且只有地圖取得操作焦點時攔截按鍵。
- 取消後不留下選取框、拖曳狀態或錯誤游標。
- 全部地圖使用一致的快捷鍵與操作語意。
- 全部地圖停用滑鼠滾輪縮放；縮放只由按鈕、鍵盤與 Box 操作觸發。

證據／結果：

- 結果：`PASS`（2026-08-03，Chromium）
- 證據：9/9 地圖啟用 Box 後完成真實矩形拖曳，縮放約
  `1.97x～2.25x`；ArrowRight 均改變 controller translation 或 SVG
  viewBox；wheel event 前後 zoom／viewBox 不變。
- 缺陷編號：
- 備註：選取後均以 Fit 還原並切回 Pan。

### DASH-028 所有 Dashboard 地圖圖磚、向量與單圖例外政策

- 頁面／範圍：Overview、LBS、Permission、Map、Weather、Navigation、
  Safety / Emergency、Architecture、Pace Fit 的全部 9 個 Dashboard 地圖實例。
- 頁面分類：Map & Evidence。
- 優先級：P0。

檢查步驟：

1. 檢查 registry 內全部 9 張圖的底圖、路線與一般 overlay 的 DOM／
   network 類型。
2. 確認主 Map 是唯一 `full-canonical` surface；其餘 8 張圖的唯一 basemap
   都是 Rudy+TW WMTS，路線與 evidence 為 SVG／GeoJSON 等向量圖徵。
3. 逐一列出以單一圖片顯示的 overlay，核對是否屬於明確 allowlist。
4. 從 Fit 點擊一次 `+`，確認圖磚數量／範圍重新計算，而且
   `data-dashboard-tile-zoom` 與 network request 的 `TILEMATRIX` 立即
   升級；再平移並檢查向量對位與單圖 georeference。

通過條件：

- 一般底圖與圖層使用圖磚或向量，不以任意單張圖片冒充可縮放地圖。
- 多張圖磚也不得以低 matrix 直接拉伸冒充縮放完成；第一次放大就必須要求
  足以支撐顯示比例的下一級圖磚。
- 主 Map 保留完整 canonical 圖層；Overview、LBS、Permission、
  Safety / Emergency、Weather、Navigation、Architecture、Pace Fit 只使用
  Rudy+TW 作為底圖，不得混入 OSM 或裝飾性假底圖。
- 單一圖片只允許明確標記的 satellite、radar、LiDAR、hillshade 或 thematic
  overlay，且必須具備範圍、來源與時間／版本資訊。
- 圖磚與向量在縮放、平移後保持同一座標位置，沒有漂移或錯位。
- Weather 的 radar／satellite 仍是 `cwa-weather` 子 overlay，不新增虛構的
  canonical layer ID。

證據／結果：

- 結果：`PASS`（2026-08-03，Chromium）
- 證據：9/9 地圖的 `data-map-render-policy-status` 均為 `verified`；
  registry 為 1 個 `full-canonical` 與 8 個 `rudy-twmap-only`；所有 supporting
  maps 的 basemap tile source 都只有 `rudy-twmap`，Weather 保留 CWA thematic
  overlays。
- 追加證據（2026-07-29，Navigation）：Fit 為 `1.000x`／matrix `13`／
  `24` tiles；第一次 `+` 為 `1.250x`／matrix `14`／`70` tiles，request
  含 `TILEMATRIX=14`；blocked image `0`、console error `0`。
- 缺陷編號：`DASH-MAP-REG-001`（已修正，保留回歸門檻）。
- 備註：未發現未核准的單一圖片；低解析 matrix 被拉伸也視為同類缺陷。

### DASH-029 所有 Dashboard 地圖基本 Zoom、Pan 與 Fit

- 頁面／範圍：Overview、LBS、Permission、Map、Weather、Navigation、
  Safety / Emergency、Architecture、Pace Fit 的全部 9 個 Dashboard 地圖實例。
- 頁面分類：Map & Evidence。
- 優先級：P0。

檢查步驟：

1. 在 registry 內全部 9 張圖分別操作 Zoom in、Zoom out 與允許的縮放方式。
2. 使用滑鼠拖曳平移，再使用控制按鍵與鍵盤平移。
3. 按 Fit／Reset，確認回到完整路線或預設範圍。
4. 連續重複放大、縮小、平移與 Fit，檢查狀態與圖層對位。
5. 轉動滑鼠滾輪，確認不會觸發縮放。

通過條件：

- Registry 內全部 9 張圖都支援 Zoom in、Zoom out、拖曳 Pan 與
  Fit／Reset。
- Fit 後能看到完整目標範圍，不保留前一次 translation 或 selection。
- 控制不會造成頁面級水平溢出、iframe 失焦或圖層消失。
- 全部地圖的按鈕名稱、快捷鍵與操作結果採一致語意。
- 滑鼠滾輪不屬於允許的地圖縮放方式。

證據／結果：

- 結果：`PASS`（2026-08-03，Chromium）
- 證據：9/9 地圖 Zoom in 均由 `1.00x` 到 `1.25x`，Zoom out 回到
  `1.00x`，方向鍵 Pan 均改變位置，Fit 均還原 scale，wheel event 不改變
  zoom。
- 缺陷編號：
- 備註：每張圖均具備 Zoom in、Zoom out、Fit、Pan、Box 五個控制。

### DASH-030 Evidence 是否有計數為 0 的類別

- 頁面／範圍：Timeline Evidence、Map Evidence、System → Diagnostic。
- 頁面分類：Map & Evidence。
- 優先級：P0。

檢查步驟：

1. 載入目前 workspace 的 compact project projection。
2. 建立 Dashboard 現行的 Evidence 群組清單，檢查每個群組顯示的 count。
3. 另外展開 `Evidence Timeline`，逐一檢查其中每個子類別的 evidence count。
4. 執行 `DASH-030`，比對紅燈訊息列出的類別與畫面上的 `0` 計數。

通過條件：

- 所有 Evidence 群組的 count 都大於 0。
- `Evidence Timeline` 內所有子類別的 evidence count 都大於 0。
- 若存在 count=0，Diagnostic 必須顯示紅燈，並列出可辨識的 tab／群組／
  子類別名稱；不得只顯示籠統錯誤。
- 檢測只讀取既有 projection，不觸發 preparation、import 或任何 POST。

證據／結果：

- 結果：`FAIL`（2026-08-03，`chilai_nanhua_day1_scoutAI`）
- 證據：Chromium `Diag all` 完成 36/36，`DASH-030` 紅燈；目前列出
  5 個 count=0 類別，全程 0 POST。
- 重新投影後，修正四個假 0：Overpass Hiking Routes `2`、Water Sources
  `1`、Parking `1`、Peaks `6`。
- 使用者介面不再只顯示數字 0，而是標示 `source checked · no matches`、
  `prepared · no candidates` 或 `completed GPX not imported`；Diagnostic
  保留內部零值並連同原因列出。
- 缺陷編號：
- 備註：剩餘項目是已確認的來源空集合或尚未匯入完成 GPX，不代表系統自動
  判定這些類別必須存在真實地物，也不得為了讓計數大於 0 而捏造 evidence。

### DASH-031 Contextual Permission 專案範圍與只讀 API

- 頁面／範圍：Exploring for Six Axis → Permission、Contextual Permission GET。
- 頁面分類：Exploring for Six Axis / Contextual Permission。
- 優先級：P0。

檢查步驟：

1. 以目前 Dashboard Project ID 讀取 `contextual-permission-dashboard?lens=baseline`。
2. 核對 artifact kind、`contextualPermissionDashboard.v1` schema 與回傳 Project ID。
3. 核對狀態只會是 `ready`、`degraded` 或 `blocked`。
4. 核對 candidate、runtime、Phase 1、Safety API、outbound 與 hardware authority flags。

通過條件：

- GET projection 綁定目前 Project ID，沒有任意 workspace path 輸入。
- `candidate_only=true`、`runtime_safety_truth=false`，所有 authority effect flags 為 false。
- 缺資料時回傳 typed `blocked` 與缺口，不虛構 Current Decision。
- Diagnostic 全程不送出 POST。

證據／結果：

- 結果：`PASS`（2026-08-03，Chromium，隔離 ready fixture）。
- 證據：GET projection 綁定 `chilai_nanhua_day1_scoutAI`，schema v1、status
  `ready`、`candidate_only=true`、runtime truth 與全部 authority effects=false；
  全批次 0 POST。
- 缺陷編號：

### DASH-032 Contextual Permission Workbench 與行動版檢視

- 頁面／範圍：Exploring for Six Axis → Permission。
- 頁面分類：Exploring for Six Axis / Contextual Permission。
- 優先級：P0。
- 前置條件：目前專案有 `ready` 的 reviewed baseline/rules projection。

檢查步驟：

1. 直接開啟 `#outdoor-permission`，不先開啟其他 Six Axis 頁面。
2. 檢查 Six Axis tabs 與 Baseline、Replay、Live Observer 三個 context lenses。
3. 檢查 Current Decision、Remaining Mission、Risk-Budget、Event & Evidence、
   Safety / Emergency handoff 與 Permission Map。
4. 在 390 px 檢查 `Now`、`Remaining`、`Safety`、`Evidence` 四個 mobile views。

通過條件：

- 完整 workbench 使用現有 Dashboard shell、truth strip、tabs、status 與 map primitives。
- 四個 mobile views 都存在；預設 `Now`，桌面專用工作明確標示
  `Continue on desktop`。
- 主要 Decision、Remaining、Safety 與 Evidence 不依賴 hover 或顏色才能理解。
- 缺 projection 時顯示 fail-closed blocked surface，不顯示假資料。

證據／結果：

- 結果：`PASS`（2026-08-03，Chromium，隔離 ready fixture）。
- 證據：6 個 Six Axis tabs、3 個 context lenses、4 個 mobile views，以及
  Decision、Remaining、Risk、Evidence、handoff、Permission Map 均完成渲染；
  390 px 的 `clientWidth=scrollWidth=390`，沒有頁面級水平溢出。
- 缺陷編號：

### DASH-033 Immutable Baseline、Forward Projection 與調整政策

- 頁面／範圍：Permission Baseline、Replay、Remaining Mission、Risk-Budget。
- 頁面分類：Exploring for Six Axis / Contextual Permission。
- 優先級：P0。
- 前置條件：Baseline 與 sealed Replay projection 均為 `ready`。

檢查步驟：

1. 同時讀取 Baseline 與 Replay，核對 projection/baseline SHA-256 binding。
2. 確認 Baseline 不合併 replay events，且 time debt 為 0。
3. 核對 Replay action event IDs 與 debt ledger，每個 event 只能計數一次。
4. 逐一檢查 `auto_reduce`、`protected_floor`、`review_only` remaining-plan nodes。
5. 比對所有 protected reserve 的 baseline/effective minutes。

通過條件：

- Baseline immutable、human-reviewed，Baseline 與 Replay 綁定同一 SHA-256。
- `effective_duration_minutes` 不低於 reviewed minimum。
- `review_only` 不自動變更；`protected_floor` 保持 protected；未允許取消的
  `auto_reduce` node 不會變成 0。
- 每個 node 都有 rule hash 與 source refs；protected reserves 不被 time debt 消耗。

證據／結果：

- 結果：`PASS`（2026-08-03，Chromium，隔離 ready fixture）。
- 證據：Baseline／Replay hash binding、immutable human review、唯一 event debt、
  `auto_reduce`／`protected_floor`／`review_only`、minimum floor、rule refs 與
  protected reserves 均通過 Diagnostic contract。
- 缺陷編號：

### DASH-034 Safety / Emergency 專屬決策與權限邊界

- 頁面／範圍：Permission Safety panel、Safety / Emergency handoff。
- 頁面分類：Exploring for Six Axis / Contextual Permission。
- 優先級：P0。

檢查步驟：

1. 檢查 Permission projection 的 authority boundary 與 Current Decision runtime authority。
2. 檢查 `permission_page_can_decide=false` 與 handoff route。
3. 檢查 Permission 頁只顯示 `Open in Safety / Emergency` 與 refresh。
4. 搜尋四種 Emergency review decision，不得出現在 Permission DOM。

通過條件：

- Permission 只能 inspect、比較、模擬與 handoff，不能批准 night travel。
- `approve_for_runtime_consideration`、`reject_night_travel`、
  `select_hold_or_bivy`、`escalate_emergency` 只存在專屬 Emergency review surface。
- runtime、Phase 1、Safety API、outbound、transport、external send 與 hardware effects
  全部為 false。
- blocked projection 仍顯示 fail-closed 邊界。

證據／結果：

- 結果：`PASS`（2026-08-03，Chromium，隔離 ready fixture）。
- 證據：Permission 僅渲染 Safety / Emergency handoff，未渲染四個 Emergency
  decision controls；runtime、Phase 1、Safety API、outbound、external send 與
  hardware effects 均為 false。
- 缺陷編號：

### DASH-035 Contextual Permission Evidence lineage 與隱私邊界

- 頁面／範圍：Permission Event & Evidence Ledger、Replay projection。
- 頁面分類：Exploring for Six Axis / Contextual Permission。
- 優先級：P0。
- 前置條件：Replay projection 為 `ready`。

檢查步驟：

1. 檢查每個 evidence 的 source ID、kind、bounded ref、SHA-256、freshness 與 authority。
2. 檢查每個 action cause 的 source ref、SHA-256 與 source kind。
3. 確認 `missing_inputs` 與 `conflicting_inputs` 是明確陣列。
4. 掃描 projection 是否包含 raw GPX、coordinates、health、IMU/PDR/GNSS 或本機絕對路徑。
5. 確認 Event & Evidence Ledger 可見。

通過條件：

- 所有 evidence/cause 皆可追到 bounded ref 與 hash。
- 一般 Dashboard input 不得成為 `human_operation` cause。
- projection 不含 raw private payload、`file://`、`/Users/` 或 path traversal。
- candidate/runtime truth boundary 在每個 evidence source 上均正確。

證據／結果：

- 結果：`PASS`（2026-08-03，Chromium，隔離 ready fixture）。
- 證據：Replay evidence 與 causes 均具 bounded ref／SHA-256；missing/conflict
  arrays 明確存在，Event & Evidence Ledger 可見，projection 不含 raw GPX、
  health、IMU/PDR/GNSS、精確座標或本機絕對路徑。
- 缺陷編號：

### DASH-036 Candidate Simulation 明確觸發與 no-write contract

- 頁面／範圍：Permission Candidate Simulation、System → Diagnostic。
- 頁面分類：Exploring for Six Axis / Contextual Permission。
- 優先級：P0。

檢查步驟：

1. 確認 Permission 初始資料載入只使用 bounded GET projection。
2. 改變 scenario input 後，檢查狀態顯示 `Inputs changed · not evaluated`。
3. 確認只有 `Run candidate simulation` 明確按鍵接到 simulation endpoint。
4. 核對回傳與 UI 說明包含 `writes_performed=false`，且不取代 stored Current Decision。
5. 執行 Diagnostic 時攔截 network，確認本題不送 simulation POST。

通過條件：

- 選取 node、event 或 lens 不會隱式執行 simulation。
- 修改 scenario 只進入 dirty/not-evaluated；last evaluated decision 保持可見。
- simulation 必須明確觸發、fail closed、no-write、candidate-only，且不替換 Current Decision。
- Diagnostic 只驗證 wiring，不替操作者執行 simulation。

證據／結果：

- 結果：`PASS`（2026-08-03，Chromium，隔離 ready fixture）。
- 證據：初始 projection 為 bounded GET；scenario 變更標成 dirty/not evaluated，
  只有明確 Run 按鍵接到 no-write simulation；Diag all 未執行 simulation，
  network 攔截結果為 0 POST。
- 缺陷編號：

## 後續項目收錄門檻

下一個可用編號為 `DASH-037`。新項目只有在功能已實作，且具備可操作 UI、
API／artifact、測試資料與明確 PASS／FAIL 條件時才加入。未完成、未接線、
preview placeholder 或只存在於未來規劃的能力不列入正式項目。

## 修訂紀錄

| 日期 | 變更 |
|---|---|
| 2026-08-03 | Chromium 完成 36/36 Diag all：32 PASS、4 個現況資料／服務 FAIL；DASH-031～036 全數 PASS，且 9/9 Dashboard 地圖完成真實操作回歸，全程 0 POST。 |
| 2026-08-03 | 新增 DASH-031～036，驗證 Contextual Permission read API、Workbench、Forward Projection、Safety / Emergency 邊界、Evidence lineage 與明確 no-write simulation。 |
| 2026-07-28 | 主 Map 保留完整 canonical layers；其餘 7 張 Dashboard 地圖統一為 Rudy+TW-only basemap、page-local vectors、停用 wheel zoom，並以 Chromium 驗證 8/8 操作一致。 |
| 2026-07-28 | 將 DASH-026～029 從 Map／Navigation／Weather 擴大為 registry 內全部 8 個 Dashboard 地圖實例。 |
| 2026-07-28 | 新增 DASH-030，檢查 Evidence 群組與 Evidence Timeline 子類別是否存在 count=0，紅燈時列出類別名稱。 |
| 2026-07-28 | 新增 DASH-026～029，驗證 Map／Navigation／Weather 的 hover hint、框選與鍵盤、圖磚／向量政策及基本地圖操作一致性。 |
| 2026-07-28 | 將 DASH-001～025 接入 System → Diagnostic；加入三色狀態、單題重測與 Diag all。 |
| 2026-07-28 | 依頁面功能建立分類索引；只採用現有可驗收能力，擴充至 DASH-025。 |
| 2026-07-28 | 建立文件；新增第一批 DASH-001 ～ DASH-010 必要功能檢查。 |
