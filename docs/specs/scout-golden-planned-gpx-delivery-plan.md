# Golden 復刻驗證與 Planned GPX 交付計畫

日期：2026-09-08
狀態：Golden 首輪 Dashboard 驗證已執行，結果 NOT QUALIFIED；阻擋與未完成步驟見 §3.2。Planned 功能開發尚未執行。
依據：[Outdoor AI Standard §5.2、§18.4–§18.7](SCOUT_OUTDOOR_AI_AGENT_STANDARD.md)。

本計畫交付兩件事：先證明「依循 Golden」能從 Dashboard 完成並可靠恢復，再建立
「Permission 人工行程 → Ref. GPX 剪接／地圖尋徑 → Planned GPX 與新節奏」的完整能力。
六力共同分析選定軌跡／計畫；零 Ref. 的 AOI 起始 workspace 留在後續情境三，不是
這兩項交付的先決條件。情境二仍包含新增路段所需的 R1–R4。

## 1. 現況判定與直接證據

第一項是 **已有構件，尚未證明完整 Dashboard 流程穩定**；第二項是 **端到端生成
功能尚未完成，需要新增能力**。既有單元／API 測試與文件不能替代本次瀏覽器驗證。
下表保留計畫建立時的程式與測試閱讀結論；後續 runtime 實測結果另見 §3.2 的驗收紀錄。

| 範圍 | 目前程式行為 | 對計畫的影響 |
|---|---|---|
| New Import | [Dashboard](../admin/scout-dashboard-v0.1.html) 的 `bindImportTripControls` 中，Create Workspace 只呼叫 `import-gpx`，成功文字明示未啟動 layer preparation。 | 需補可持續操作的完整準備鏈；不能以匯入成功宣告可用。 |
| Clone | [clone_pretrip_workspace_from_inputs](../../dashboard_workspace_clone.py) 串接 `run_pretrip_import` 與 `run_layer_preparation`，含 enrichments 與 spec artifacts；準備失敗保存 `imported_preparation_failed` receipt。 | 可重用的整合基礎；長 POST 逾時、重開頁面及恢復仍須驗證／補足。 |
| Workspace Refresh | Dashboard 另呼叫 connected-preparation。 | Refresh、完整 map preparation、Permission 初始化須分別呈現，不當成同一個「準備完成」。 |
| 歷史復刻 | [build_reference_gpx_reconstruction](../../scout_reference_gpx_reconstruction.py) 與 [workbench](../../scout_contextual_permission_workbench.py) 已有來源綁定、重建、儲存、Accept、Rebuild。 | 優先驗證已有路徑；確保 Accept 後的 projection 更新也走完。 |
| Human Design | workbench 已有文字 preview 與版本化 candidate／patch；地名對位與 route admission 仍有待解欄位。 | 可沿用輸入及版本服務，需補行程意圖到路線的實質編譯。 |
| Scout patch | Dashboard 的 Preview Scout patch 目前把輸入送為 `add_assumption`。 | 「加支線」或「改休息」不會因此自動變成幾何或時間修改。 |
| 地圖候選 | [TRH](scout-terrain-route-hypothesis.md) 有 A/B 的 R1–R3 與人工錨點審查後的 R4；地圖與 Ref. 證據各有現有產物。 | 需新增候選路段到 Planned 路線的組合、來源追蹤、節奏與輸出流程。 |
| Browser smoke | [workspace smoke](../../tools/dashboard_workspace_browser_smoke.js) 有匯入／Workspace 操作，但使用測試替身，未覆蓋真實 preparation＋Permission 全鏈。 | 借用操作工具，新增本計畫的專用情境；分開報告模擬與真實 runtime 證據。 |

## 2. 交付順序與每階段出口

| 階段 | 工作 | 可檢視的交付物 | 階段完成條件 |
|---|---|---|---|
| A0：建立比較基準 | 選定單日、多日 Golden 與對應 Ref.，確認新匯入／Clone／Refresh 的路徑。 | 來源清單、獨立的預期日界／CP／時間表、流程差距清單。 | 每個預期值能回到來源；測試不自行改寫產品答案。 |
| A1：貫通 Golden 流程 | 補足 New Import 到 map preparation、Permission authoring ready 的銜接。 | 可從 Dashboard 啟動、追蹤、恢復的準備流程。 | 不需 shell bootstrap 或手改 JSON 才能開始復刻；部分失敗有可執行恢復方式。 |
| A2：Golden 穩定性驗證 | 實際操作復刻、審查、Rebuild、reload、切 workspace 與失敗恢復。 | §3 的 G1–G6 報告與 browser／artifact 證據。 | 適用案例完成，未測與不穩定項可見；建立後續改動的回歸基準。 |
| B1：Planned 最小完整切片 | 從 Permission 輸入一段支線往返與一次固定停留，使用可用 Ref. 路段。 | 可預覽、保存、重開與匯出的 Planned GPX＋行程節奏。 | 幾何與時間都真的改變，Golden 保留；不是只新增 assumption。 |
| B2：地圖補段 | 接入 Overpass／Rudy+TWMap、R1–R3、敘事 R4。 | 來源可回查的地圖／TRH 候選段與 Planned 差異。 | 無 Ref. 支段能由候選來源補入；缺口與審查狀態保留。 |
| B3：六力共同重分析 | 新路線 CP／segments、時間計畫與六力的分析主體一起改版。 | Golden／Planned 比較、完整路段軸與六力版本狀態。 | 新支線未被 Golden 軸截斷，各力使用同版計畫或明示待重算。 |
| B4：完成情境二驗收 | 驗證來源組合、時間、版本衝突、reload、GPX 匯出及 Golden 回歸。 | §5 的 P1–P9 證據與剩餘限制。 | 通過整條情境二，且 A2 已證明的 Golden 流程仍可用。 |

A0／A1／A2 先形成可信的共同基礎。B 的 schema 與路段組合器可在 A 的缺口修復時
獨立開發；B 的 Dashboard 整合與完成判定依賴 A2，避免兩條未驗證流程互相遮蔽。
B1 是第一個能力展示，B2–B4 仍是情境二完成所需工作。

## 3. 第一項：如何證明依循 Golden 可用

### 3.1 實際操作鏈與準備狀態

```text
選 Golden＋Ref. → Validate → Preview → Create／Clone
  → 完整 map preparation → Permission authoring ready
  → Generate from Ref. GPX（historical_reconstruction）→ Preview
  → Save Candidate → Quick review → Accept Reviewed Baseline
  → Rebuild projections → 檢視六力 → reload → A/B workspace 切換
```

先實測 New Import 與 Clone 各能走到哪個階段，再補缺口。重用已有 import、layer
preparation、source manifest、receipt 與狀態機；完整操作程序遵循
[preparation runbook](scout-pretrip-full-preparation-runbook.md)。

New Import 應提供清楚的下一步「準備地圖與分析資料」，Clone 使用相同準備服務。
避免為讓畫面成功而增加第二套準備演算法。準備狀態至少區分匯入完成、準備中、
部分完成、失敗與可進行行程分析；各階段有 project ID、來源 hash、工作 ID 與結果引用。

若作業超過一次 browser request，改成提交工作、查詢進度與結果；頁面重整後仍能
找回工作。重複按鈕或網路重送不能重複 import。失敗續跑以來源 hash 與階段 receipt
判斷可重用範圍；來源改變則建立新版本，不以同名覆寫掩蓋差異。

Permission 初始化須區分「缺必要資料」、「可以開始候選編排」與「尚待人工審查」。
不得要求先取得一個 reviewed baseline，才能啟動產生第一個 baseline 的入口。
若目前需要 bootstrap，將其合法的資料初始化整合到準備鏈；不自動製造人工 review。

### 3.2 驗收矩陣

| ID | 情境與操作 | 必須觀察到的結果 |
|---|---|---|
| G1 | 單日 Golden＋多份 Ref.，從 Dashboard 新建 workspace 走到六力。另測 Clone。 | 原始 Golden 選擇一致；來源、幾何、CP 與 import／preparation receipts 相符。New Import／Clone 均不需人工補檔。 |
| G2 | 真實多日 Golden，包含長日、過夜、休息與裝置 gap。 | 原來源分日、起訖點、離到時刻、CP、停留與缺口保留；不被每日八小時或 crowd pace 重新分日。 |
| G3 | 時間戳缺失、不單調、方向錯誤或來源不一致。 | 可用幾何仍可研究；無法復刻的節奏／路段有具體原因，不捏造完整行程。 |
| G4 | Save 後、Accept 後、Rebuild 後分別 reload，再從 workspace A 切 B 再切 A。 | 儲存的 candidate／review 可找回，來源與版本一致，未接受者不自動接受；不混入另一專案。 |
| G5 | 準備中斷／request timeout、同名重送、雙擊 Save／Accept、來源改變。 | 作業狀態可追蹤，重試冪等；版本衝突拒絕局部寫入；原檔與上一可用版本保留。 |
| G6 | 完成審查與 Rebuild，逐一檢視六力。 | 同一分析路線、CP／segment 與時間基準；舊 projection 不冒充新版本。歷史天候、目前預報與未知分開。 |

G1、G2 用真實來源在獨立新 ID 的 workspace 做完整 browser 操作；既有 workspace
用於讀取／reload／切換回歸。G3、G5 的破壞性與故障注入放在隔離測試資料中，
其證據不當成真實 Dashboard 操作的替代品。G4 同時檢查 browser 顯示和保存產物。

先取得一次完整成功，再於相同程式版本連續三次重跑關鍵編排／恢復流程；需使用
能實際觸發該操作的起始狀態，不能只重看已完成頁面。一次失敗後重試成功仍記為
FLAKY；修復後重新收集證據。結論限於實際測試版本、路線與案例，不外推全面可靠。

每例保存：runtime URL／身份、workspace ID、程式版本與 dirty diff 指紋、來源 hash、
操作前後截圖、browser network trace、結果 ref/hash、實際狀態、失敗原因及恢復結果。
API／fixture tests 與真實 browser 成果分開報告；HTTP 200、圖層數或按鈕存在不是完成。

2026-09-08 首輪實測紀錄見
[G1–G6 qualification report](scout-golden-gpx-g1-g6-qualification-20260908.md)。
2026-09-09 的[修復與重驗 checkpoint](scout-golden-gpx-g1-g6-qualification-20260909.md)
已記錄準備恢復、Permission 初始化、MCP／CWA 來源對齊、採用後 ETA 讀取、
重複 Clone 檔名及正式 GIS launcher 的修復。r14 程式碼 `a069a000` 搭配正式
launcher 的 r14b 已完成兩個獨立新案的完整真實操作：New Import 第一次準備
即 completed；Clone 沿同 job Resume 完成且 import.1 保留。兩者 23/23 層
ready、0 warnings，初始未接受，Save／Accept／Rebuild 各次 reload、雙擊
冪等、六頁內容／地圖與 A→B→A 原版本恢復都有證據。原始 GPX 與採用產物
稽核、兩個 workspace 的 33-layer contract 及同碼 G3/G5 故障測試通過。

G2 的 r11 真實 New Import、r13 採用全鏈及 r14 當前回歸保留九日、218/219 CP
時刻、32 停留、8 過夜間隔、10 未知與 143 缺失時間戳；未變邏輯的回歸與
新起始操作分別記錄。aux TRH 的 DEM metadata 缺口仍保留為 unavailable，
目前預報與 Golden 歷史天候未知分列。先前失敗不改判。

**仍為 NOT QUALIFIED。** Scout 已驗證封存 928.11 MiB 測試證據，Mac 空間
恢復後續跑，沒有刪除既有檔案。r14c 第二輪的返回控制逾時列 FLAKY；r14d
第三、第四輪核心操作經獨立審查曾累計為 2/3。第五輪完成採用與原版本恢復，
但表單尚未載入時的填寫操作拋錯後重試，另有後段地圖網路 trace 缺口，依原
規則列 FLAKY，計數再次重置為 0/3。r14e 已改用每輪新分頁、明確等待來源
表單與增量追蹤，開始第六個新 Clone。仍須同版本連續三輪成功；修正觀測方式
不會改判舊失敗。詳見上方 qualification checkpoint 的最新紀錄。

## 4. 第二項：人工行程如何生成 Planned GPX

### 4.1 一個明確入口，串通意圖、幾何與節奏

Permission 的 Human Design 應承接這類輸入：

> 沿 Golden 第三天路線，從營地 A 單攻山頭 B 後回 A；觀景點 C 多停 40 分鐘，
> 第四天改到營地 D，早上 6 點出發。

目標流程：

```text
Permission 原始文字＋選定 Golden／Ref.
  → 結構化行程差異與待定位地名
  → 路線／地圖定位，必要時列出歧義供確認
  → Ref. 路段選取／剪接，或地圖／TRH 候選補段
  → 組合 Planned 路線幾何並驗證連通
  → 建立新 CP／segment 對應與移動／休息／紮營時間計畫
  → 地圖與逐日差異預覽
  → Save Planned Version → 審查採用／匯出 → 六力重分析
```

AI 負責解析意圖、查詢證據、選擇工具、提出可核對的路段組合；確定性程式負責
剪接、幾何／時間檢查、版本、保存與結果回執。使用者不必手動決定每個 GPX 點。
唯一且有來源的匹配可自動提出；歧義與未定位點需可見，R4 仍依既有契約人工選錨點。

文字解析先產生 ordered itinerary intent，再組合路線與 candidate graph，最後綁回
既有 `MissionBaselineCandidate` 的驗證／審查鏈。不能要求新支線的 CP 先存在於
舊 Golden graph，也不能把未定位的新地名直接視為已驗證圖節點。
程式中的既有候選型別是 `MissionBaselineDraft`（schema `missionBaselineCandidate.v1`）；
沿用其版本生命週期，但新幾何須有實際的拓樸／來源驗證回執，不能只沿用人工設定
`confirm_route_axis` 或 source ref 字串的 graph 判定來證明剪接正確。

### 4.2 最小模組與責任

以下是建議責任切分；新增模組／schema 名稱是實作提案，不代表目前已有 API。

| 模組 | 沿用基礎與新增責任 | 產物 |
|---|---|---|
| 行程意圖編譯 | 沿用 Human Design、preview／candidate／patch 生命週期；新增支線、返回、刪段、改端點、停留、啟程及營地的 typed operations。 | `ItineraryIntent`，含原文、欄位來源、待確認項。 |
| 路段目錄與解析 | 讀取完整的 filtered Ref. 幾何與來源索引，按端點／途經順序／方向找段；不可使用 Dashboard 簡化過的顯示線做剪接。 | `RouteSegmentSelection`，含 source hash、track／trkseg、點範圍、方向與來源類型。 |
| 路線組合器 | 剪取、反向、接續、支線往返，驗證距離容差、拓樸、斷點與 NoData。 | `PlannedRouteRevision`、GPX、地圖預覽、來源鏈與缺口。 |
| 地圖／TRH adapter | 查詢可用 Overpass 山徑，對 Rudy+TWMap 圖上線索定位／描繪；讀 hash-bound R1–R3／R4 產物轉成候選路段。 | 與 Ref. 同格式、但保留各自證據性質的候選段。 |
| 節奏估計 | 沿用 [reference segment timing](../../pretrip_reference_segment_timing.py) 的可用來源；依新路段與人工限制估計移動、固定停留、啟程／離營與分日。 | `PlannedItinerary`，區分歷史觀測、計畫估計、假設與未知。 |
| 版本與分析接點 | 沿用 workbench 的 project-scoped immutable save／review；新增 Planned 與 baseline、分析輸出間的綁定。 | 版本化 plan bundle、Golden 比較、各六力的來源／新舊狀態。 |

先在 B1 內證明同路線的啟程／停留修改真的改變 timetable；再切出主線一段、接上
一條 Ref. 支線、回到主線，加入 40 分鐘停留。B1 出口須同時展示新幾何、新時間與
保存後重開，不能只證明解析出幾個地名。

B2 再分三個可驗證增量：Overpass／Rudy+TWMap 補段、R1–R3 補段、R4 敘事引導補段。
既有 [Overpass alignment](../../pretrip_overpass_route_alignment.py) 對齊／切分已排序路線，
尚不能視為任意 A/B 的山徑搜尋。先接入已有向量段，接著補分析區域內的 trail graph
連通搜尋，並驗證分岔選擇與找不到接續的結果，才能完成「直接尋找既有山徑」。
Rudy+TWMap 是圖上證據，須另取得可回查的向量／描繪結果；沒有已對位幾何時保留
待查。R4 來源文字、人工錨點及 DEM hash 變更必須使舊選段失效，不能繞過原審查。

### 4.3 路線、時間與保存規則

- **Golden 保留：** Planned 有自己的版本與來源；不能覆寫 Golden 檔案或僅將它改名。
  純節奏變更可共用幾何 hash，仍建立新的 itinerary／plan bundle 版本。
- **幾何可核對：** 支線去回分開建模；反向、交叉、同點重訪依序列定位，不能只做
  最近點吸附。跨 `trkseg` 缺口不得自動補直線；來源索引與幾何更換須使舊 preview 過期。
  [load_gpx_route](../../route_matching.py) 目前攤平 track points 並跨段累計距離；新組合器
  須使用保留 `trkseg` 的資料結構，避免將裝置 gap 當成可剪接的路段。
- **移動與休息分開：** 可用且方向相容的 Ref. 統計可作估計依據；新增、反向或未知
  路段另列方法與腳程假設。固定停留加到時間軸，不能混入移動速度，也不能把來源
  的舊日期拼成新行程。TRH 模型成本未校準前不直接換成時數。
  使用歷史 elapsed time 時須先辨識已包含的停留，避免加上新休息後重複計時；
  無法分離時明示限制，不能冒充 moving-only。跨午夜須保留時區與日期進位。
- **約束衝突可見：** 出發、最晚到達、營地、日照與固定停留不相容時回報衝突；
  不以偷偷加快腳程、縮短休息或補一段未知 ETA 來完成計畫。
- **輸出成套：** GPX 預設輸出規劃幾何；分日、停留、營地、假設與來源另存同行程
  manifest。若輸出預估時間，明示 planned；重匯入不得成為本人 Recorded。
- **保存可恢復：** 預覽無寫入；明確 Save 才新增 immutable bundle，綁 project、父版本、
  intent／路段／DEM hashes 與 idempotency key。GPX、itinerary、manifest 驗證後原子發布，
  失敗保留上一版。審查與匯出不會移除 R1–R4 的 candidate-only／non-operational 性質。
- **六力版本一致：** 新 Planned 先建立自己的 route axis／CP／segments，再重算依賴。
  新版圖與舊版時間／Permission 不得一起標為完成；六力可顯示部分結果與具體缺口。
  [Architecture 分析](../../pretrip_reference_pace_energy_analysis.py) 仍有讀取
  `primary.*.speed_filtered.gpx` 的依賴，須改由明示的 analysis subject 接入，不能
  只新增 `planned.gpx` 就認為六力已切換。新支線超出現有 map／DEM coverage 時，
  先標示需追加準備並更新受影響範圍，不能沿用舊 workspace 的 ready。

### 4.4 Dashboard 的最小操作面

在現有 Permission authoring 區增加行程差異與結果預覽，沿用既有頁面與審查操作。
使用者應能看到 Golden／Planned 疊圖、分日啟程／到達／休息／營地差異、各新增段
來源、待確認項，以及 Save Planned Version、重新開啟、版本比較與 GPX 匯出。

Navigation 負責候選生成／比較，選段結果可帶回同一份 Planned 草案；避免另存一份
沒有回綁 Permission 的計畫。日程與候選改變時，preview／review 的過期原因必須清楚。

## 5. 第二項驗收矩陣

| ID | 輸入／操作 | 完成證據 |
|---|---|---|
| P1 | Golden 同路線，只加固定停留／改啟程。 | 幾何不變，時間與版本改變，原歷史時間保存。 |
| P2 | 從 Ref. 剪出支線單攻再返回。 | 去回幾何、長度、高差、來源點範圍與新耗時可核對。 |
| P3 | 多 Ref. 拼接、反向、交叉與重訪同點。 | 保留正確行程順序；不誤接交叉路段或穿越記錄缺口。 |
| P4 | Ref. 缺少支段，使用 Overpass／Rudy+TWMap 線索。 | 地圖來源及可組合幾何可追溯；未定位部分不偽造完成。 |
| P5 | 加入 R1–R3，另做有文字與人工錨點的 R4。 | 候選來源、DEM／review hashes 保留；改 A/B／DEM 後舊選段過期。 |
| P6 | 改營地／多日節奏，含未知耗時、來源停留及跨午夜。 | 新分日與固定限制生效，不重複計入休息；未知與不可滿足的時間條件可見。 |
| P7 | Save、reload、切 workspace、舊 preview 保存、重複請求、匯出與重匯入。 | 版本與專案隔離、冪等／衝突正確，GPX 與 itinerary 同版，不能冒充 Recorded。 |
| P8 | Planned 新支線交由六力分析，另測超出原 map／DEM 範圍。 | 主路線軸與 CP／segments 包含支線；所有結果綁新版本或明示待重算／追加準備。 |
| P9 | 開啟原 Golden，重跑 G1／G2／G4 的核心操作。 | 新規劃能力不破壞復刻與歷史基準。 |

P1／P2 是首個 demo；整項完成仍須 P3–P9。模組與故障測試可用 fixtures，最後的
Permission → Planned → 地圖／節奏 → 保存／重開／匯出 → 六力 必須由真實 Dashboard
可見控制完成，不能靠後端直接寫入成果冒充 UI 可操作。

## 6. 預計修改範圍與驗證資產

| 工作 | 主要既有範圍 | 新增範圍／證據 |
|---|---|---|
| A：入口、準備與恢復 | [Dashboard](../admin/scout-dashboard-v0.1.html)、[admin API](../../admin_api.py)、[clone service](../../dashboard_workspace_clone.py)、[pretrip import](../../pretrip_import.py)、既有 layer preparation／Permission bootstrap。 | 共用準備工作接點與專用 Golden browser flow；只在證據確認缺口後修改相關構件。 |
| B：文字、幾何與保存 | [Permission workbench](../../scout_contextual_permission_workbench.py)、[workbench API](../../scout_contextual_permission_workbench_api.py)、reference timing、terrain hypothesis／guidance modules。 | 建議新增 `scout_planned_route_models.py`、`scout_planned_route.py`、`scout_planned_route_artifacts.py`；adapter 沿用既有 API 入口，名稱可依現有結構調整。 |
| B：分析整合 | 現有 CP／segment producers、六力 collectors、map／Dashboard projections。 | 以 plan revision 綁定分析主體的接點；不另建六套計畫來源。 |
| 文件 | 本計畫、Outdoor Standard、workspace layout、Permission workbench spec、preparation runbook。 | 開發時同步記錄契約與實際根因／恢復步驟；本規劃回合不先修改 runtime 或其他工作中的 runbook。 |

可重用的 focused tests：

- `tests/test_pretrip_import.py`、`tests/test_dashboard_workspace_clone.py`：匯入與準備協作。
- `tests/test_scout_reference_gpx_reconstruction.py`：歷史日界、時刻與來源檢查。
- `tests/test_scout_reference_gpx_workbench.py`：isolated API 的重建、儲存、接受與 Rebuild。
- `tests/test_scout_contextual_permission_workbench_api.py`：版本、狀態、project scope 與重建。
- `tests/test_pretrip_reference_segment_timing.py`：分段時間來源與品質。
- `tests/test_terrain_route_hypothesis.py`、`tests/test_terrain_route_guidance.py`：TRH 接點與來源限制。

新增測試只保護本計畫的路段組合、時間計畫、版本保存及 browser 操作鏈。變更到
GPX／準備／共用地圖時執行 layer contract verifier 與對應 smoke；前後執行 Navigation
guard，保留凍結基準及其他 dirty work。Construction Mode 不自動擴大成全產品 release。

每階段報告「做到了什麼、哪條入口實際跑過、測試與真實 browser 各自結果、剩餘
缺口」。若 runtime 或資料條件不足，標示未驗證，接著處理仍可進行的局部開發／測試；
不把文件、候選產物或測試替身當成已穩定可用的 Dashboard。
