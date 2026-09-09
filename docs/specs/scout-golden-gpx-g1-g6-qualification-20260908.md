# 依循 Golden：G1–G6 實測紀錄（2026-09-08）

狀態：**NOT QUALIFIED；不得宣稱「依循 Golden 可用」**。
本輪已觀測 New Import、兩個 Clone 的終止結果及可到達的 Dashboard 步驟。
三個新 workspace 均未能完成候選編排鏈；受阻的後續步驟保留為未完成，沒有代填 PASS。

驗收依據是 [delivery plan §3.2](scout-golden-planned-gpx-delivery-plan.md#32-驗收矩陣)。
本輪執行現有程式的真實 Dashboard 操作與隔離故障測試，沒有修改 production code、
降低驗收條件，或以補寫 workspace JSON 取得成功畫面。

## 1. 本輪範圍與身份

- Runtime：`http://127.0.0.1:9099/admin/dashboard`；既有 PID `47541`，啟動時間
  `2026-09-08 11:32:21 Asia/Taipei`。本輪沒有啟停 server 或操作硬體。
- Git HEAD：`4ee2cfb416315461ecd2d19fb7b3213c48cb2e51`；工作樹原本已有未提交修改。
  [開始快照](../../artifacts/golden-gpx-qualification-20260908/initial-snapshot.json)保存 dirty diff 指紋。
  測試中整體指紋有變；當時檔案 mtime 顯示變動是既有 preparation runbook，
  另保存排除 `docs/specs` 的 [程式 diff 指紋](../../artifacts/golden-gpx-qualification-20260908/receipts/runtime-source-diff-fingerprint.json)。
- 真實操作只使用 Codex in-app browser 的 Dashboard 表單、按鈕、reload 與 workspace selector。
  CDP 用於觀察本地 API 回應；來源檔案用獨立解析器核對。
- 新建 `golden_g1_chilai_20260908`、`golden_g1_chilai_clone_20260908`、
  `golden_g2_dongqing_clone_20260908`。原有 workspace 只做檢視、切換、無寫入的 Preview／Generate；
  沒有對原案執行 Save、Accept 或 Rebuild。
- 故障注入使用 artifacts 內的隔離資料；沒有讀取真 `.env`、向外送訊、部署、commit 或 push。

## 2. G1–G6 驗收表

| ID | 判定 | 實際觀測 | 尚未滿足的條件 |
|---|---|---|---|
| G1 | **FAIL** | 單日原始 Golden＋24 Ref. 完成 server import；UI 180 秒 timeout 後，可從清單重開。35 CP 的來源 index/time 全符合。單日 Clone 完成但回報 `completed_with_degraded_terrain`。 | New Import 未完成 map preparation；Clone 的 QGIS worker status 三次 preflight 後仍 timeout。兩案均缺 Permission seed，無法開始 Generate／Save／Accept。 |
| G2 | **FAIL；歷史重建子項 PASS** | 多日 Clone 的來源與 219 CP 相符；原 workspace 的無寫入 Preview／Generate 產生九日，獨立原始 GPX 比對全部相符。 | 新 Clone 最終因 bounded DEM 缺件而降級完成，Permission seed 仍缺失。依 §3.2 新 ID 完整 browser 操作要求，原案重建成功不替代新案全鏈。 |
| G3 | **PARTIAL** | 隔離測試涵蓋缺時、非單調、混年、CP/source/hash 不符及反向綁定；真實多日 UI 顯示 missing ranges 與 unknown CP。 | 缺時／反向等全部異常情境的真實 UI 流程沒有完整覆蓋；隔離 PASS 不替代 Dashboard PASS。 |
| G4 | **BLOCKED** | A→B→A 與 reload 保持專案隔離；A 不帶入 B 的九日草稿。 | 新 workspace 無法建立第一個 candidate，故 Save／Accept／Rebuild 各自 reload 與保存產物的全鏈尚未執行。 |
| G5 | **FAIL** | 實際 import timeout 後表單與作業狀態消失；已完成 workspace 可由 catalog 找回。同名 Clone 重送回應 409。隔離測試確認 idempotency、no-write conflicts、失敗 receipt。 | 找回完成結果不等於可追蹤或續跑準備工作；隔離 Clone preparation failure 的同名重試只會拒絕既有 target，未證明 resume。真實雙擊 Save／Accept 受 G1 阻擋。 |
| G6 | **BLOCKED** | 新單日 import 及多日 Clone 準備後六頁皆已檢視；缺件、部分結果與 unknown 詳列於下表。原案 Permission 能指出 reviewed baseline 已更新而投影 stale。 | 沒有完成新案審查與 Rebuild，無法驗證六力共用同一分析路線、CP／segment、時間與版本。 |

**完整成功鏈：0 次。** 依既定規則，尚未開始「成功後同版本連續三次」的穩定性重跑。
重看已完成頁面、API 200、來源 hash 相同、圖層數或某個 fixture PASS 都不代替這個門檻。

## 3. 真實來源與獨立預期

### G1：單日 Golden

既有 `chilai_nanhua_day1_scoutAI` 的 Golden 實際跨兩個 local 日；本輪沒有依 workspace
名稱誤判單日。改用同區域原始 `GoLife_Run_gpx_2016-11-12.gpx`：

- SHA256：`2d57a1d949547b9f17a1c2a5470795d9d8fd0fff1de09924e40b2f5bd7bfbbaf`。
- 2016-11-12 08:40:19–16:47:41，Asia/Taipei；9,302 原始點，原檔沒有缺時或非遞增時間。
- 透過表單指定原始 GPX corpus；25 個來源檔（Golden＋24 Ref.）進入新案。
- import 後 Golden 9,290 點、35 CP／34 segments，35 個 CP index/time 全符合原來源。

[G1 匯入比對](../../artifacts/golden-gpx-qualification-20260908/sources/golden_g1_chilai_20260908.import-after-ui-timeout.json)
區分 raw 與 filtered，沒有把過濾後資料直接當作原始預期。

### G2：九日 Golden

東清八通關的原始 GPX 有嵌入的 2012 年異年點，不能直接把 11 個 calendar dates 當成
11 個行走日。獨立解析器保留 raw point identity，並檢查 import 移除與保留的點。

- Clone import：4 個 unique source files，Golden 5,768→5,649 點；119 個移除點與所有
  保留點都可追溯，主要九日為 2020-12-26–2021-01-03。
- 原 workspace 實際 UI Generate 回應 `writes_performed=false`；九日首末 point identity、
  departure、arrival、elapsed 全部吻合原始來源。
- 219 個 CP 的 clock／unknown 鏈全部吻合；218 有時間，`cp.177` 保持 unknown。
- D1、D2、D4、D8、D9 超過八小時，沒有被截斷或重新分日。
- 143 個缺時間點、8 個跨日 gap 全保留；32 個 stationary intervals 保持 inferred stops，
  未被宣稱為已確認休息；overnight gap 不等於已確認露營活動。

[逐日獨立比對](../../artifacts/golden-gpx-qualification-20260908/sources/g2-ui-oracle-comparison.md)
與 [實際 UI API response](../../artifacts/golden-gpx-qualification-20260908/receipts/g2-original-ui-generate-response.json)
只證明原案的無寫入重建能力，沒有替新 Clone 的初始化、審查與持久化背書。

本輪結束前另做 [58 個來源檔 hash 核對](../../artifacts/golden-gpx-qualification-20260908/receipts/source-preservation-final.json)，
涵蓋 29 個原始來源及原 workspace 來源副本，全部符合初始 hash。此保存證據限於 GPX；
不宣稱所有可能更新的 workspace cache 或其他任務產物均未改變。

## 4. G1／G5 真實操作中的阻擋與恢復

1. Preview 使用預設 `/data/scout/materials/country/tw` 時回報 material root 不存在。
   清空欄位後仍套回 country default。改以 UI 指向現存原始材料來源後才通過 Preview。
2. 原 material manifest 的 `scout-fusion/catographydata/DTM` 路徑已不存在。
   本輪 UI 改指仍存在的 `scout-fusion-legacy-20260823/catographydata/DTM` 原始 DEM 目錄。
   DTM 欄位是單行 input，須逗號分隔；第一次誤用換行造成路徑串接，列為測試輸入錯誤。
3. Create 的真實 POST `/admin/pretrip/projects/golden_g1_chilai_20260908/import-gpx`
   超過 180 秒，UI 顯示失敗；server 後續仍完成 import。
4. reload 清空 intake，沒有找回該作業的進度／狀態。從 Workspace catalog 選取新案並
   Open workspace 可以恢復檢視完成的 import；本輪沒有同名覆寫或重新 import 該目標。
5. 新案 Layers prepared 顯示 `--`；Permission 明確回報
   `Contextual Permission seed is missing: outputs/contextual_permission/workbench_seed.json`。
   畫面唯一的 Retry bounded projection 再次得到相同阻斷。
6. 單日 Clone 執行中，由另一個頁面重送相同**測試目標**名稱，實際回應 409
   `clone target already exists`。原先 Clone 繼續執行，拒絕重送不表示已具備續跑能力。

關鍵畫面：[import timeout](../../artifacts/golden-gpx-qualification-20260908/browser/g5-01-import-timeout-before-reload.png)、
[seed missing](../../artifacts/golden-gpx-qualification-20260908/browser/g1-19-permission-blocked-settled.png)、
[同名拒絕](../../artifacts/golden-gpx-qualification-20260908/browser/g5-08-existing-test-target-rejected.png)。

### 兩個 Clone 的最終結果

| 新案 | 完成時間（Asia/Taipei） | 終止狀態與具體原因 |
|---|---|---|
| `golden_g1_chilai_clone_20260908` | 2026-09-08 12:34:23 | `completed_with_degraded_terrain`；QGIS `MCP_UNAVAILABLE`，`QGIS worker status timed out.`，三次 preflight；Permission seed 不存在。 |
| `golden_g2_dongqing_clone_20260908` | 2026-09-08 12:26:48 | `completed_with_degraded_terrain`；QGIS 可連線，但 `SOURCE_UNAVAILABLE`，`No bounded DEM source is available for terrain_feature_stack.v1.`；Permission seed 不存在。 |

[最終 receipt 與階段摘要](../../artifacts/golden-gpx-qualification-20260908/receipts/final-clone-outcomes.json)
保存兩者原始 Clone receipt 的 ref/hash。完成時間取 Clone `completed_at`，沒有把
core preparation manifest 的 `finished_at` 當成後續 enrichments 全部結束的時間。
多日 Clone 的 UI POST 回應 HTTP 201，但 receipt 仍明確是 degraded；兩者 map preparation
summary 都為 blocked。TRH 因 `terrain_feature_stack_not_completed` unavailable，workspace
DEM 為 `terrain_parent_unavailable`，Terrain RGB 為 `awaiting_qgis_grass_processor`。

兩份 Clone receipt 的 `material_root` 都為 null。單日來源是本輪剛 import、尚未 preparation
的 workspace；這指出來源設定承接／preflight 的檢查需求，不能推斷為兩案相同的 DEM
或 worker 根因。單日案實際先卡在 worker status，多日案才取得明確的 DEM 缺件回應。
本輪沒有手動補 seed、修改來源 manifest、重啟 worker 或用已生成 terrain 替代完整準備。

準備結束後的 Permission 畫面仍分別顯示 missing seed：
[單日 Clone](../../artifacts/golden-gpx-qualification-20260908/browser/g1-clone-15-permission-confirmed.png)、
[多日 Clone](../../artifacts/golden-gpx-qualification-20260908/browser/g2-22-new-clone-permission-blocked.png)。

## 5. G6 六力觀測

### 新單日 workspace：New Import 後、尚未 preparation

以下是審查前的實際缺件觀測，**不是 G6 的 post-Rebuild PASS**。

| 面向 | 實際畫面／資料 |
|---|---|
| Route Context | Canonical briefing 未準備，顯示 unavailable。 |
| Pace Fit | 顯示 35 個 CP、來源位置與 Recorded GPX time（2016-11-12）；頁面自述為 Preview。 |
| Permission | workbench seed missing，Generate／Save／Accept 全鏈無法開始。 |
| Architecture | geometry 可讀，但 historical mobility pending，2/7 sources、0 bins。 |
| Weather | 明確 unavailable／unknown，沒有把目前預報冒充 2016 年歷史天候；沒有啟動 refresh 或 RF send。 |
| Navigation | No terrain projection has been prepared；Rudy+TW orientation basemap only，不宣稱已準備 terrain vectors／tiles。 |

### 新多日 Clone：preparation 降級完成後

| 面向 | 最後可觀測的畫面／資料 |
|---|---|
| Route Context | 已生成 briefing，呈現約 89.8 km 的來源資料與缺口；未將九個歷史行進日直接當成已確認的未來行程。另出現 `1862my/,`、`slogans` 等疑似 OCR 雜訊的 named nodes，mileage unknown；需核對來源，不能當成可用地名。 |
| Pace Fit | 顯示 219 CP 與 Recorded GPX time，檢視中的時間為 2020-12-29 08:33；使用新 Clone 的資料。 |
| Permission | preparation 已結束仍為 seed missing；無法執行候選保存、人工審查與 Rebuild。 |
| Architecture | 最終已載入，標示 PARTIAL；Golden 90.40 km、source 89.83 km、比例 1.006432；九個歷史行進日；38 日／4 份 GPX 的歷史日行進 P50 為 3h 9m。18:00 固定截止明示為假設，非實測日落。0 difficulty CP、0 selected MCP，保留 217 context MCP。 |
| Weather | 顯示目前 CWA 批次，目標 QPF 時窗為 2026-09-08 11:50–12:50，cache 12:11；`no_coverage`、route rain／arrival UNKNOWN、confidence 7%。這不是 2020 年的歷史天候。沒有按 Refresh 或 RF send。 |
| Navigation | 沒有 QGIS spatial artifact 或 terrain-risk candidate，只有 Rudy+TW orientation basemap；04:43:19Z 與 04:44:41Z 的畫面均仍顯示 `LOADING WORKSPACE TERRAIN EVIDENCE`，沒有得到可用 terrain 或明確終止的頁面狀態。 |

關鍵證據：[Architecture](../../artifacts/golden-gpx-qualification-20260908/browser/g2-28-postprep-architecture-bounded.bounded-dom.json)、
[Weather](../../artifacts/golden-gpx-qualification-20260908/browser/g2-30-postprep-weather-settled.bounded-dom.json)、
[Navigation](../../artifacts/golden-gpx-qualification-20260908/browser/g2-33-postprep-navigation-final.png)。
Architecture 的兩條里程軸有顯示比例，不能單憑數值差異判為 bug；仍須 G6 的共同分析主體
契約比對。新 Clone 的 Architecture input 指紋中，12 個存在的 inputs 均符合 hash，
另有 4 個缺件，沒有觀測到存在 inputs 的 hash mismatch。

既有奇萊案 Weather 也明確標示 08/25 舊快取為 stale_data，沒有把舊到雨時刻從現在起算。
既有東清案 source 指紋另發現 Architecture 18 個 inputs 中一個 risk source 的 bytes 已變、
原 manifest 仍留有 `fresh=true`；此為待處理的 artifact 依賴問題，不能僅憑該欄位
推斷 Dashboard 仍在使用新鮮資料。要在合法 Rebuild 後重新驗證實際 API 與六頁來源。

現有 deterministic layer verifier 三案均為 `ok=false`，各檢查 33 個 contract entries：
新 G1 import 有 13 個缺 ref／count errors，單日與多日 Clone 各 11 個（risk、MCP、boss-points
等缺件／count）。[單日 Clone 結果](../../artifacts/golden-gpx-qualification-20260908/receipts/golden_g1_chilai_clone_20260908.layer-verifier.json)
與 [多日 Clone 結果](../../artifacts/golden-gpx-qualification-20260908/receipts/golden_g2_dongqing_clone_20260908.layer-verifier.json)
是補充資料完整性檢查，不是新增的 G 驗收條件，也不能單憑全綠代替六力一致性。

## 6. 隔離測試與證據界線

56 個 cases 通過：第一組 55 項耗時 77.29 秒，另加方向綁定 1 項耗時 59.01 秒。
兩個成功執行的真 `.env` open 與 socket connect 嘗試都為 0；沒有啟動測試 runtime。

- 缺時間仍保留幾何；無法歷史重建則 409，不製造完整節奏或 candidate。
- 非單調、混年、CP／來源 hash 不符、竄改候選皆保留具體原因與 no-write 證據。
- 反向綁定案例回應 `reference_gpx_checkpoint_coordinates_mismatch:cp.000`。
  這證明不一致的 CP→Golden 綁定被拒絕，不表示自洽的反向行程應一律拒絕。
- 相同 idempotency key 的 Save／Accept 回傳相同 receipt，檔案 hashes 不變；
  Rebuild 重送回應 200 並回傳同一 `rebuild_sha256`，未擴大宣稱所有 Rebuild 產物均不變。
- Clone preparation failure 保存 `imported_preparation_failed`，同名再試拒絕既有目標。
  只證明失敗保存與防重複，未證明 preparation resume。

[完整子案例與 raw logs](../../artifacts/golden-gpx-qualification-20260908/isolated/summary.md)。
第一次 collection 的 dotenv 嘗試在讀取前被 guard 阻擋；補齊隔離 wrapper 後重跑。
該失敗是 harness isolation gap，不列為產品 FLAKY。單行欄位誤用換行、locator 名稱大小寫
等操作錯誤亦保留原始紀錄，不列為產品缺陷。

Browser 截圖、DOM 與經欄位篩選的 network events 存於
[browser evidence](../../artifacts/golden-gpx-qualification-20260908/browser)。
部分大量 map events 有 buffer truncation，部分切換後需重新啟用 Network capture；
不能宣稱所有資源請求皆完整。關鍵多日 Generate 已另錄 POST／200 與 response body。
多日 Clone 的 201 event 已保存，auto-navigation 後再取 response body 回報
`No resource with given identifier found`，所以 Clone 內容以保存的 workspace receipt 佐證。
Architecture 大量 SVG 的完整 DOM snapshot 曾逾時；改用唯讀、限定元素與長度的 DOM
讀取及截圖後成功，不能把這個觀測工具限制當成頁面不能操作的證據。

## 7. 下一輪修復與重測順序

本輪已提供 A0 的來源比較基準與 A1 的具體缺口；沿用 delivery plan 的階段名稱。

1. **A1：準備與 job 恢復。** 將 New Import 接入與 Clone 相同的 preparation 服務；
   在 Dashboard 顯示可恢復的 job ID、階段、錯誤與結果，reload 後能找回作業。
   對 material／DEM 路徑作可解釋的 server preflight，保留有效來源設定；針對 worker status
   timeout 提供可驗證的階段重試，不以同名重新 import 當作恢復。
2. **A1：合法 authoring 初始化。** 把必要的 route axis、timing 與 workbench seed 初始化
   接入準備鏈；允許從 candidate-only 狀態開始第一份 baseline，不製造人工 review。
3. **A2：以新案重測持久化與六力。** Save／reload、Quick review＋Accept／reload、
   Rebuild／reload、A→B→A；逐一核對同一分析路線、CP／segment、來源與時間版本。
   任一 stale／unknown 維持明示，再重測故障恢復與並發重送。
4. 首次完整成功後，於固定程式版本連續三次重跑關鍵編排／恢復流程，重新收集證據。
   在 G1–G6 全部通過之前，結論維持「依循 Golden 尚未通過驗收」。

本輪沒有對產品做修補，沒有宣稱 release／正式 runtime 可用，也沒有對外送出獨立審查訊息。

## 8. 證據封存與檢查範圍

- [最終 runtime 與版本](../../artifacts/golden-gpx-qualification-20260908/receipts/final-runtime-version.json)：
  PID／啟動時間與測試開始相同；排除 `docs/specs` 的 tracked source diff SHA256 仍為
  `51921231a1664e9b2569f753f971868263659065d6d64b58e7294f7ec2d876a5`，與中途快照一致。
  開始時沒有逐檔 hash，故這是中途至結束的直接比較；開始至中途另有 mtime 證據與限制。
- [Navigation freeze 最終檢查](../../artifacts/golden-gpx-qualification-20260908/receipts/navigation-freeze-final.txt)：
  `NAVIGATION_FREEZE_SUSPENDED`、report-only、130 個檔案；未改 baseline。
  這只記錄 freeze 政策與既有 drift，不是 Navigation 或 Golden 驗收 PASS。
- [機器可讀 G1–G6 結果](../../artifacts/golden-gpx-qualification-20260908/reports/g1-g6-results.json)
  保存判定、已證明子項、阻擋、0 次完整成功及未開始的重跑門檻。
- 本輪產品程式未修改，沒有為文件變更執行全 repository lint／typecheck／test。
  實際驗證範圍是 browser 操作、獨立 GPX 比對、56 個隔離 cases、三案唯讀 layer verifier，
  以及文件／證據引用完整性檢查。沒有將未執行的後續 browser 或對外獨立審查記成通過。
