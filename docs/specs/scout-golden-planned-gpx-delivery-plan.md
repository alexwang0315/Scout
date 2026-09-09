# Golden 復刻驗證與 Planned GPX 交付計畫

建立日期：2026-09-08；更新日期：2026-09-10
狀態：Golden G1–G6 的 2026-09-09 指定版本與案例維持 PASS，後續核心重驗連續 3/3；證據及限制見 §3.2。Planned 第二項已完成指定範圍的 P1–P9 驗收，為 SCOPED PASS / WORKING PROTOTYPE；操作見 §4，真實／fixture 證據及限制見[驗收報告](scout-planned-gpx-p1-p9-qualification-20260910.md)。
依據：[Outdoor AI Standard §5.2、§18.4–§18.7](SCOUT_OUTDOOR_AI_AGENT_STANDARD.md)。

本計畫交付兩件事：先證明「依循 Golden」能從 Dashboard 完成並可靠恢復，再建立
「Permission 人工行程 → Ref. GPX 剪接／地圖尋徑 → Planned GPX 與新節奏」的完整能力。
六力共同分析選定軌跡／計畫；零 Ref. 的 AOI 起始 workspace 留在後續情境三，不是
這兩項交付的先決條件。情境二仍包含新增路段所需的 R1–R4。

## 1. 計畫建立時的現況判定與直接證據

計畫建立時，第一項是 **已有構件，尚未證明完整 Dashboard 流程穩定**；第二項是 **端到端生成
功能尚未完成，需要新增能力**。既有單元／API 測試與文件不能替代本次瀏覽器驗證。
下表保留計畫建立時的程式與測試閱讀結論；後續 runtime 實測結果另見 §3.2 的驗收紀錄。
2026-09-10 的實作已新增獨立 Planned 編譯、保存、審查與分析主體接點，現況對照見
§4.2；此歷史表格中的缺口描述不再代表所有功能均未開發。

| 範圍 | 計畫建立時的程式行為 | 對計畫的影響 |
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

**最終為 SCOPED PASS / WORKING PROTOTYPE。** 首次完整操作後，第六、七、八輪
全新 Clone 在 r14 `a069a000` 上連續通過核心／恢復驗證，達成 3/3；三案皆
attempt 1 完成、23/23 層 ready、0 warnings，33-layer contract 與原始 GPX
採用稽核通過。四次真實文件 reload、同名回到同 job、雙擊 Save／Accept
各一次效果、六頁同源與 A→九日 G2→A 原候選恢復均有封存證據。

第二輪控制逾時及第五輪 disabled-field 操作拋錯後重試仍列 FLAKY，兩次皆
重置連續計數；第三、四輪只保留為較早成功。第七、八輪在開始 Clone 之前的
追蹤器設定失敗與第八輪初次狀態 predicate 過早成立也保留，不宣稱整段
自動化皆無錯。原 §3.2 判準不變，結論限於指定版本、路線與案例。

Scout 已驗證封存 928.11 MiB 既有證據，沒有刪除本機原檔；儲存回執與後續
追加封存另列。完整結果見[最終 G1–G6 報告](scout-golden-gpx-g1-g6-qualification-20260909.md)。
上述 2026-09-09 紀錄當時將第二項列為 B1 起點：Permission 人工差異 → Ref. GPX
路段組合 → Planned GPX 與新節奏。2026-09-10 已完成下節所列實作及 B4 的 P1–P9
指定案例驗證；Golden 的歷史 PASS 與本次 Planned 驗收分開記錄。

## 4. 第二項：人工行程如何生成 Planned GPX

### 4.1 一個明確入口，串通意圖、幾何與節奏

Permission 的 Human Design 要處理這類行程差異：

> 沿 Golden 第三天路線，從營地 A 單攻山頭 B 後回 A；觀景點 C 多停 40 分鐘，
> 第四天改到營地 D，早上 6 點出發。

目前入口同時提供受限文字句型與明確行程表單。上例中的日次、營地離營日期及
來源路段須拆成可核對欄位，不能假設整段自然語言已能一次自動完成；見 §4.4、§4.6。

已接入的流程：

```text
Permission 原始文字＋選定 Golden／Ref.
  → 結構化行程差異與待定位地名
  → 路線／地圖定位，必要時列出歧義供確認
  → Ref. 路段選取／剪接，或地圖／TRH 候選補段
  → 組合 Planned 路線幾何並驗證連通
  → 建立新 CP／segment 對應與移動／休息／紮營時間計畫
  → 地圖與逐日差異預覽
  → Save Planned Version → 審查／分析主體選擇／匯出 → 六力版本與待重算狀態
```

目前文字解析與路線編譯由確定性程式執行；LLM／agent 的自由文字工具規劃仍是後續
擴充方向。唯一且有來源的匹配可提出候選；歧義與未定位點列為待解，亦可在表單中
明確選來源錨點、路段及第幾次經過。R4 仍依既有契約人工選錨點。

文字與表單先產生有順序的 typed operations，再建立新 route axis、CP、segments 及
日程。Bundle 內沿用 `MissionBaselineDraft`（schema `missionBaselineCandidate.v1`）
保存候選日程表示，審查則綁定獨立 Planned manifest。這個接點不會採用或改寫
Golden 的 accepted baseline，也不會用舊 graph 接受新支線；候選中的
`golden_graph_activation` 明示 `blocked`。不能把型別相同、`confirm_route_axis`
或 source ref 字串當成新幾何已通過舊 mission graph 驗證。

### 4.2 2026-09-10 實作對照

下表列出已落地的程式入口。P1–P9 依原矩陣完成觀察，真實 Dashboard 操作、
來源讀取與 focused fixtures 的證據範圍分列於[驗收報告](scout-planned-gpx-p1-p9-qualification-20260910.md)。

| 模組 | 已實作責任 | 產物／接點 |
|---|---|---|
| Typed 輸入 | [scout_planned_route_models.py](../../scout_planned_route_models.py) 定義 `PlannedRouteRequest`、`ItineraryOperation`、`RouteSegmentSelection`、`TrailPathSelection`，拒絕未知欄位及無時區的日期。 | 原文、來源 snapshot、父版本、七種行程操作、依序選段及地名對位。 |
| 目錄與路線編譯 | [scout_planned_route.py](../../scout_planned_route.py) 的 `load_planned_catalog`、`compile_planned_route` 讀完整來源點與分段，執行剪裁、取代、反向、接續及支線往返；保留缺口與來源 hash。 | `plannedRoutePreview.v1`、Golden／Planned GeoJSON、GPX、新 route axis／CP／segments、差異與問題。 |
| 節奏編譯 | 同一編譯器分離來源可辨識的靜止時間、移動估計及新增固定停留；支援指定腳程、啟程、營地離營、最晚到達與跨日，無依據時保留未知。 | `itinerary.days`、`timeline`、`unknowns`、`conflicts`；時間角色均為計畫估計。 |
| 地圖／TRH 候選 | [scout_planned_route_sources.py](../../scout_planned_route_sources.py) 接入 Overpass 查詢與已保存向量圖的起終點／途經點連通搜尋；讀入已審查的 Rudy 描繪、具來源鏈的 R1–R3 及沿用人工錨點審查的 R4。 | 來源檔案與 hash 綁定、候選路段及不可用原因；不將 raster 圖像或 TRH 成本直接變成可通行性／耗時。 |
| 保存、審查與匯出 | [scout_planned_route_artifacts.py](../../scout_planned_route_artifacts.py) 重新編譯核對 preview，檢查父版本、來源及冪等鍵，原子發布 immutable bundle；獨立記錄四面向審查與分析選擇。 | `reviews/planned_routes` 下的版本、審查、選擇回執；GPX、manifest、ZIP bundle。 |
| HTTP 入口 | [scout_planned_route_api.py](../../scout_planned_route_api.py) 透過既有 [workbench router](../../scout_contextual_permission_workbench_api.py) 的 `project_root_for` 接入相同 workspace。 | §4.5 的 `/admin/pretrip/projects/{project_id}/planned-route` API；來源衝突回報具體 code。 |
| 分析主體 | [scout_analysis_subject.py](../../scout_analysis_subject.py) 增加 reviewed Planned bundle 選擇，提供完整新軸與分日；來源／版本無效時保留具體失效原因。 | Permission／Pace 的 Planned 日程，以及其他各力 `needs_reanalysis`／`coverage_needed`；不把舊報告標成新結果。 |
| Dashboard | [scout-planned-route.js](../admin/scout-planned-route.js) 接入 [Permission Human Design](../admin/scout-dashboard-v0.1.html)，提供差異表單、來源選段、疊圖、時間軸、版本審查及匯出。 | 下節可見操作鏈；原始逐點時間軸保留，畫面採分頁與相鄰移動摘要。 |
| 重匯入來源隔離 | [pretrip_import.py](../../pretrip_import.py)、[pretrip_gpx_corpus.py](../../pretrip_gpx_corpus.py) 保留 Planned XML provenance；[reference timing](../../pretrip_reference_segment_timing.py) 與 [daily departures](../../pretrip_historical_daily_departures.py) 排除計畫時間。 | Planned 可作規劃來源；不能藉重匯入成為本人 Recorded 或歷史觀測。 |

先在 B1 內證明同路線的啟程／停留修改真的改變 timetable；再切出主線一段、接上
一條 Ref. 支線、回到主線，加入 40 分鐘停留。B1 出口須同時展示新幾何、新時間與
保存後重開，不能只證明解析出幾個地名。

B2 分三個驗證增量：Overpass／Rudy+TWMap 補段、R1–R3 補段、R4 敘事引導補段。
既有 [Overpass alignment](../../pretrip_overpass_route_alignment.py) 對齊／切分已排序路線，
本身不是任意 A/B 山徑搜尋。新的 sources adapter 已另加向量 trail graph 連通搜尋；
目前只在目錄內可追溯的既有山徑向量上運作，分岔、途經點與找不到接續仍須依
P4 驗收。Rudy+TWMap 要先有已審查的人工描繪向量及地圖來源綁定，這次沒有新增
從 raster 自動描繪路線的能力。R4 讀取既有敘事／人工錨點審查產物；來源文字、
人工錨點或 DEM hash 改變使舊選段失效，不能用 Planned 審查繞過原審查。

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

### 4.4 Dashboard 操作方式

1. 選擇已準備的 Golden／Ref. workspace，進入 Permission → Human Design 的
   **Human Design → Planned GPX**。確認 project ID、來源數及 snapshot 已載入；
   有新來源或要恢復版本時按「重新讀取來源與版本」。
2. 填「人工行程」、計畫啟程日期時間及時區。腳程可選「可用來源節奏優先」或
   「全程使用固定腳程」；沒有可用來源又未填腳程的部分維持未知。支援句型見 §4.6。
3. 在「明確行程差異與來源選段」加入固定停留、紮營／離營、啟程、最晚到達、
   支線往返、取代主線路段或剪裁路線端點。使用錨點搜尋／來源範圍選位置，重訪
   同點時指定第幾次經過。路段操作另選 Ref.／地圖／TRH 來源、不跨缺口的來源段、
   起終點與是否返回；也可依序「以此段建立自訂主路線」。需要山徑補段時，先用
   「查詢並加入 Overpass 山徑候選」保存指定範圍來源，再選既有向量山徑連通搜尋
   的起點、終點與途經點。新增來源會使舊預覽過期。
4. 按「預覽 Planned 幾何與節奏」，檢查 Golden／Planned 疊圖、方向與返回、
   來源點範圍、分日及固定停留、未知時間與衝突。大型時間軸可切摘要／原始明細並
   分頁核對，完整記錄仍在 bundle。`blocked` 須先解決；`needs_review` 的限制會
   帶入版本審查，不能靠勾選解除幾何或時間的阻擋錯誤。
5. 按 **Save Planned Version**，保存這次 preview 的獨立版本。保存不會自動採用
   為分析主體。若回應逾時，先重新讀取版本確認保存結果；重送同一請求只回傳
   原版本。輸入、來源或父版本變更後須重新預覽。
6. 在「審查此 Planned 版本」逐一檢視**來源與選段範圍、幾何順序／往返／缺口、
   分日／腳程／固定停留、不確定性與候選來源限制**，確認完整的版本限制，再按
   「記錄此版本審查」。審查只綁定該 manifest，保留 candidate-only 性質。
7. 按「以此 Planned 分析六力」。檢查目前選擇的 `planned_gpx` 與版本 ID，以及
   各力使用的新 route axis／CP／segments 和日程狀態。Permission／Pace 顯示新計畫；
   尚未依新版本產生的分析保留待重算／追加準備原因，見 §4.6。
8. 由「匯出 Planned GPX」「匯出 行程 Manifest」「匯出 完整 Bundle」匯出同版資料。
   GPX 預設提供規劃幾何與角色 metadata；完整日程、來源、hash 與不確定性請取 ZIP bundle。
   按鈕先核對伺服器回應，顯示檔名、大小及 hash，再觸發下載；HTTP 衝突會顯示失敗。
   「產物已準備」只表示檔案已取回，是否落盤須看瀏覽器下載紀錄。
   reload 或切回 workspace 後，用 **Restore Planned Version** 重開，亦可比較
   另一保存版本，或按「切回 Golden 分析」恢復 Golden 分析主體。

### 4.5 API 與保存位置

以下路徑共用前綴 `/admin/pretrip/projects/{project_id}/planned-route`，使用既有
project workspace resolver，沒有另建另一套 project store。

| 方法與路徑 | 輸入／結果重點 |
|---|---|
| `GET /catalog` | 來源、錨點、問題及 `source_snapshot_sha256`；只讀。 |
| `POST /sources/overpass` | `bbox`（south／west／north／east）、冪等鍵與明確確認；查詢固定 Overpass 入口、保存來源檔，再回傳更新的 catalog。 |
| `POST /preview` | `PlannedRouteRequest`：原文、時區日期、腳程模式、`operations`、`route_selections`、來源 snapshot／父版本及地名對位；回傳 preview hash、幾何、日程與 `review_requirements.required_issue_ids`，不寫入。 |
| `GET /versions`、`GET /versions/{version_id}` | 列出或恢復 manifest、preview、review、來源新鮮度與目前分析選擇；只讀。 |
| `POST /versions` | `request`、`expected_preview_sha256`、`idempotency_key`、`explicit_confirmation: true`；重新編譯與核對來源，成功才發布版本。 |
| `POST /review` | 版本 ID、`expected_manifest_sha256`、審查者、四個 `accepted_dimensions`、完整 `acknowledged_issue_ids`、冪等鍵及明確確認；阻擋錯誤不能審查放行。 |
| `GET /analysis-selection`、`POST /analysis-selection` | 讀取／切換 `golden_gpx` 或已審查的 `planned_gpx`；寫入綁版本、manifest、`expected_selection_sha256`、冪等鍵及明確確認。 |
| `GET /export/{version_id}/{format}` | `format` 為 `gpx`、`manifest` 或 `bundle`；核對同版產物與 hash 後下載。 |

`GET /admin/pretrip/projects/{project_id}/analysis-subject` 回傳實際選用的共同分析主體，
包含 `subject_kind`、`selected_plan_version_id`、來源／manifest 綁定、新路線軸、
CP／segments、itinerary 及各力 dependency 狀態。重送相同冪等鍵與相同 payload
回到相同結果；同鍵不同 payload、過期來源、過期父版本或分析選擇衝突會被拒絕。

每個 project 的版本位置為
`reviews/planned_routes/versions/plan.<24 位十六進位識別碼>/`，包括：

- `planned.gpx`、`route.geojson`、`route_axis.json`、`checkpoints.json`、`segments.json`。
- `itinerary.json`、`request.json`、`preview.json`、`mission_baseline_candidate.json`。
- `manifest.json`：檔案 hash、來源 snapshot、父版本、幾何／日程 hash 與必要限制 ID。

審查位於 `reviews/planned_routes/reviews/{version_id}/`；分析選擇位於
`reviews/planned_routes/analysis_selection.json`，並保留 `selections/` 歷史回執。
Overpass 原始／向量來源存於 `normalized/map/planned-overpass/{來源內容識別碼}/`，
只追加 `project.planned_overpass_source_refs`；Golden refs 與原 accepted baseline 保留。

### 4.6 目前能力邊界與未完成重算

文字解析以換行、分號或句號分句，目前直接支援以下句型；A／B／C 必須替換成
目錄可辨識的地名或錨點。解析成功後仍須核對定位與來源路段。

| 文字例子 | 目前處理方式 |
|---|---|
| `沿 Golden`、`依循 Golden` | 保留 Golden 主線，再套用其餘差異。 |
| `在 C 停留 40 分鐘`、`C 多停 40 分鐘` | 新增固定停留；以分鐘表示，與來源可辨識停留分列。 |
| `從 A 單攻 B 後回 A` | 提出同點返回的支線；無唯一可用來源時須明確選段。 |
| `早上6點出發` | 修改已填計畫日期的出發時刻；完整日期與時區仍由欄位提供。 |
| `在 A 紮營`、`改到 A 過夜` | 新增營地事件；停留或離營日期由明確操作補足，未有依據時列未知。 |

「第三天」「第四天改營地」「隔天六點」與任意敘事沒有通用日期／意圖推論能力。
以表單選實際位置、完整啟程／離營日期時間，必要時在「此操作對應的原文句子」
填入完整待解句，保留原文並明確表達該句。多日、歧義地名及相同地點重訪不能
靠未解析文字靜默略過。

Rudy 僅接受 `project.planned_rudy_trace_refs` 中已有的人工描繪向量，且需
`human_reviewed`、審查者／時間、Rudy 圖層及地圖證據 hash；沒有此來源就保持待查。
R4 仍在既有 Navigation 敘事引導流程選人工錨點、審查並產生候選，Planned 只讀取
與該來源、A/B、DEM、審查版本一致的產物。這次沒有把一般登山日誌直接變成
免錨點審查的 R4。

切換 Planned 已更新共同分析主體。當來源與新軸有效時，Permission／Pace 的日程
dependency 為 `current_planned_candidate`；Architecture 的完整 producer 尚未依
新版本重新產生，保留 `needs_reanalysis`。Navigation、Weather、
Route Context 亦依來源與幾何範圍顯示待重算或 `coverage_needed`，目前預報不冒充
Golden 歷史天候。新幾何即使位於 Golden 外框內，DEM coverage 仍屬未驗證；這次
沒有把 Planned 選擇直接接成額外 map／DEM 自動準備作業。

來源 elapsed time 只作計畫估計，停留辨識方法與腳程假設可回查；未知移動時間
不補成完整 ETA。GPX 預設不輸出 `<time>`，日程留在同版 bundle；即使外部加入
預估時間且保留 Planned provenance，重匯入也不能進入歷史觀測樣本。所有候選、
審查、匯出與六力顯示維持 `candidate_only: true`、`runtime_safety_truth: false`。

## 5. 第二項驗收矩陣

2026-09-10 狀態：P1–P9 指定範圍 **SCOPED PASS / WORKING PROTOTYPE**。
P1／P2／P7／P8 與 P9 核心由真實 Dashboard 操作；P3–P6 與故障案例使用 focused
fixtures，另有真實 Overpass 取源與既有 R1–R3 讀取。下表維持原始完成標準；
逐例結果、版本及證據見[驗收報告](scout-planned-gpx-p1-p9-qualification-20260910.md)。
P9 的再次 Accept 經 409 後成功找回既有 review，不宣稱新 Accept 或新的 Rebuild。
P8 通過的是共同新版本與具體待重算狀態；後四力完整 producer 重算仍見 §4.6。

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

## 6. 實作範圍與驗證資產

| 工作 | 主要既有範圍 | 新增範圍／證據 |
|---|---|---|
| A：入口、準備與恢復 | [Dashboard](../admin/scout-dashboard-v0.1.html)、[admin API](../../admin_api.py)、[clone service](../../dashboard_workspace_clone.py)、[pretrip import](../../pretrip_import.py)、既有 layer preparation／Permission bootstrap。 | 共用準備工作接點與專用 Golden browser flow；只在證據確認缺口後修改相關構件。 |
| B：文字、幾何與保存 | [Permission workbench](../../scout_contextual_permission_workbench.py)、[workbench API](../../scout_contextual_permission_workbench_api.py)、reference timing、terrain hypothesis／guidance modules。 | 已新增 §4.2 的 Planned models／compiler／sources／artifacts／API 及 Dashboard 操作面。 |
| B：分析整合與重匯入 | 現有 CP／segment producers、六力 collectors、map／Dashboard projections、GPX import／歷史來源 producers。 | `scout_analysis_subject.py` 綁定新 plan revision；import／corpus 保留 Planned 角色，歷史 timing／daily departures 排除預估時間。各力未重算處仍可見。 |
| 文件 | 本計畫、Outdoor Standard、workspace layout、Permission workbench spec、preparation runbook。 | 持續記錄契約與實際根因／恢復步驟；本計畫的實作對照與操作更新不代替另行保存的 qualification 結果。 |

可重用的 focused tests：

- `tests/test_pretrip_import.py`、`tests/test_dashboard_workspace_clone.py`：匯入與準備協作。
- `tests/test_scout_reference_gpx_reconstruction.py`：歷史日界、時刻與來源檢查。
- `tests/test_scout_reference_gpx_workbench.py`：isolated API 的重建、儲存、接受與 Rebuild。
- `tests/test_scout_contextual_permission_workbench_api.py`：版本、狀態、project scope 與重建。
- `tests/test_pretrip_reference_segment_timing.py`：分段時間來源與品質。
- `tests/test_terrain_route_hypothesis.py`、`tests/test_terrain_route_guidance.py`：TRH 接點與來源限制。

已新增／擴充的 Planned focused tests：

- `tests/test_scout_planned_route.py`：文字與 typed 差異、剪接、往返、缺口、時間及來源變更。
- `tests/test_scout_planned_route_sources.py`、`tests/test_scout_planned_route_map_compilation.py`：Overpass／Rudy／R1–R4 來源、向量連通及編譯接點。
- `tests/test_scout_planned_route_artifacts.py`：實際 API 保存／重開／審查／選擇／匯出、hash／authority／來源競態與冪等。
- `tests/test_scout_analysis_subject.py`、`tests/test_dashboard_analysis_subject.py`、`tests/test_dashboard_planned_route.py`：共同分析主體、Dashboard 呈現與待重算狀態。
- `tests/test_pretrip_import_planned_provenance.py`：真實 local importer 的 GPX 重匯入、預估時間、來源角色與 Recorded 隔離；connected preparation 另行驗證。

新增測試只保護本計畫的路段組合、時間計畫、版本保存及 browser 操作鏈。變更到
GPX／準備／共用地圖時執行 layer contract verifier 與對應 smoke；前後執行 Navigation
guard，保留凍結基準及其他 dirty work。Construction Mode 不自動擴大成全產品 release。

每階段報告「做到了什麼、哪條入口實際跑過、測試與真實 browser 各自結果、剩餘
缺口」。若 runtime 或資料條件不足，標示未驗證，接著處理仍可進行的局部開發／測試；
不把文件、候選產物或測試替身當成已穩定可用的 Dashboard。
