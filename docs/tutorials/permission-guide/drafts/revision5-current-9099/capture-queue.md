# Permission revision5：逐頁擷取操作清單

狀態：38 頁文字與擷取腳本草稿；已重新盤點當前 Mac 的八個 UI 來源檔案，最終版本、實際畫面與功能仍待核對。未發布、未重建 PDF。

入口：http://127.0.0.1:9099/admin/dashboard?projectId=dongqing_batongguan_historic_trail_newImport#outdoor-permission
Dashboard 檔案盤點 SHA：fb17b74399b3677eeb1089b053079afd82032ebb386be091b0e71b1c03864e21

目前來源根目錄：/Users/alexwang0315/scout-fusion；盤點時間：2026-09-14T01:54:43.372935+00:00。
八個必填來源見 capture-queue.json 的 required_current_ui_source_paths，包含原本三個地圖檔案及五個 Permission 外載模組。此盤點不是擷取回執；截圖前及最終交付前仍須讀取實際來源，不能使用 TASK/repo 的舊 UI hash。

先依真實資料處理 Saved → Restore → SHA → readiness；每頁先驗 unique/visible，再取得當次 DOM rectangles。不得沿用舊座標。
第 9、12、13、19、20、23、24、28–34 頁已核對模組進入當前 source，全部保留。資料是否已存在需 root 實際讀 UI。
所有頁目前 screenshot pending；07:11 的 p3 也屬舊來源，需重拍。

主圖用 #pretripMapFrame；Weather 用 iframe[data-weather-cwa-map-frame]，都在 frame 內找 #refreshMapTiles。舊 #refreshWeatherMapTiles 已無 source。
第 5、11、17、29 頁各有四項實際操作，保留 1–4；其他頁 2–3 步，不為湊數增加無意義操作。

## 擷取順序

3, 4, 5, 6, 7, 1, 2, 8, 9, 10, 11, 12, 13, 14, 15, 16, 26, 17, 18, 19, 20, 21, 22, 23, 24, 25, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38

## 01. Permission 使用指南

狀態：PENDING_CURRENT_UI_CAPTURE；來源：SOURCE_VERIFIED_CAPTURE_PENDING。
位置：http://127.0.0.1:9099/admin/dashboard?projectId=dongqing_batongguan_historic_trail_newImport#outdoor-permission

準備：
1. 確認 URL 的 projectId 與實際 workspace 一致。
2. 在 Permission 找 Baseline Authoring Workbench，讓兩個模式按鈕及 Saved 選單同窗可見。

步驟與畫面位置：

| 數字 | 畫面實際標籤／內容 | Selector | 條件 |
| --- | --- | --- | --- |
| 1 | Human Design | [data-permission-baseline-mode="human_text"] | 依當前 DOM 核對 |
| 2 | Generate from Ref. GPX | [data-permission-baseline-mode="reference_gpx"] | 依當前 DOM 核對 |
| 3 | Saved candidate versions | [data-permission-saved-candidate] | 依當前 DOM 核對 |

資料條件：workspace_read。
缺項處置：保留實際資料缺項、disabled／錯誤與 receipt；正向教學仍待補，不能套用歷史畫面或列為通過。

## 02. 從參考紀錄產生基準草稿

狀態：PENDING_CURRENT_UI_CAPTURE；來源：SOURCE_VERIFIED_CAPTURE_PENDING。
位置：http://127.0.0.1:9099/admin/dashboard?projectId=dongqing_batongguan_historic_trail_newImport#outdoor-permission

準備：
1. 選 Generate from Ref. GPX；只拍參考來源與操作入口可先不 Generate。
2. 若要示範產生結果，另保存實際 preview receipt；不要為截圖重新 import／prepare。

步驟與畫面位置：

| 數字 | 畫面實際標籤／內容 | Selector | 條件 |
| --- | --- | --- | --- |
| 1 | Reference trip | [data-permission-baseline-ref] | 依當前 DOM 核對 |
| 2 | Preview source | [data-permission-baseline-preview] | 依當前 DOM 核對 |
| 3 | Generate typed draft | [data-permission-baseline-generate] | 依當前 DOM 核對 |

資料條件：workspace_read, golden_prepared。
缺項處置：保留實際資料缺項、disabled／錯誤與 receipt；正向教學仍待補，不能套用歷史畫面或列為通過。

## 03. 選好 Saved candidate，接著按 Restore

狀態：PENDING_CURRENT_UI_CAPTURE；來源：SOURCE_VERIFIED_CAPTURE_PENDING。
位置：http://127.0.0.1:9099/admin/dashboard?projectId=dongqing_batongguan_historic_trail_newImport#outdoor-permission

準備：
1. 按 Refresh saved versions，先核對清單。
2. 選 version.15f1d78018a8af8e（僅目前清單仍存在時），拍 Restore enabled 的選擇狀態，尚未按 Restore。

步驟與畫面位置：

| 數字 | 畫面實際標籤／內容 | Selector | 條件 |
| --- | --- | --- | --- |
| 1 | Refresh saved versions | [data-permission-candidates-refresh] | 依當前 DOM 核對 |
| 2 | Saved candidate versions | [data-permission-saved-candidate] | 依當前 DOM 核對 |
| 3 | Restore saved candidate | [data-permission-candidate-restore] | 依當前 DOM 核對 |

資料條件：saved_baseline。
缺項處置：保留實際資料缺項、disabled／錯誤與 receipt；正向教學仍待補，不能套用歷史畫面或列為通過。

## 04. 先核對版本，再決定能否審查

狀態：PENDING_CURRENT_UI_CAPTURE；來源：SOURCE_VERIFIED_CAPTURE_PENDING。
位置：http://127.0.0.1:9099/admin/dashboard?projectId=dongqing_batongguan_historic_trail_newImport#outdoor-permission

準備：
1. 由第3頁所選版本按 Restore，等待完整結果。
2. 捲到 immutable candidate / readiness，記完整 ID、SHA 與所有 gap/rebuild 提示。

步驟與畫面位置：

| 數字 | 畫面實際標籤／內容 | Selector | 條件 |
| --- | --- | --- | --- |
| 1 | Current immutable candidate | [data-permission-baseline-patch-panel] .permission-detail-row:nth-child(1) | 依當前 DOM 核對 |
| 2 | Review readiness | [data-permission-baseline-patch-panel] .permission-detail-row:nth-child(2) | 依當前 DOM 核對 |

資料條件：saved_baseline, restore_receipt。
缺項處置：保留實際資料缺項、disabled／錯誤與 receipt；正向教學仍待補，不能套用歷史畫面或列為通過。

## 05. 還原後，逐日檢查路線與時間

狀態：PENDING_CURRENT_UI_CAPTURE；來源：SOURCE_VERIFIED_CAPTURE_PENDING。
位置：http://127.0.0.1:9099/admin/dashboard?projectId=dongqing_batongguan_historic_trail_newImport#outdoor-permission

準備：
1. 延續第4頁相同版本。
2. 展開 D1，讓日標題、獨立地圖控制、圖磚狀態及證據 summary 可見。
3. 依完整地圖驗收核對 D1 操作不會移動 D2 鏡頭；其他日仍須逐一檢查。

步驟與畫面位置：

| 數字 | 畫面實際標籤／內容 | Selector | 條件 |
| --- | --- | --- | --- |
| 1 | 動態 D1 日標題、起終點與里程 | [data-permission-proposal-day="D1"] .permission-day-card-head | 依當前 DOM 核對 |
| 2 | + / − / Fit / Pan / ▣ | [data-permission-day-map="D1"] [data-dashboard-map-controls] | 依當前 DOM 核對 |
| 3 | 停止更新 或 更新圖磚；重試圖磚；實際 Rudy 圖磚狀態 | [data-permission-day-map="D1"] [data-dashboard-rudy-controls] | 依當前 DOM 核對 |
| 4 | Day route, ETA & evidence | [data-permission-proposal-day="D1"] .permission-day-details summary | 依當前 DOM 核對 |

資料條件：saved_baseline, daily_geometry, daily_map_receipts。
缺項處置：保留實際資料缺項、disabled／錯誤與 receipt；正向教學仍待補，不能套用歷史畫面或列為通過。

## 06. Quick review：逐項核對本人要採用的內容

狀態：PENDING_CURRENT_UI_CAPTURE；來源：SOURCE_VERIFIED_CAPTURE_PENDING。
位置：http://127.0.0.1:9099/admin/dashboard?projectId=dongqing_batongguan_historic_trail_newImport#outdoor-permission

準備：
1. 延續同版；展開 Quick review，不替使用者勾選。
2. 依實際 required uncertainty/handoff 決定條件欄位是否存在；缺 target 必須留下版本與 requirements 證據，不能假造 checkbox。

步驟與畫面位置：

| 數字 | 畫面實際標籤／內容 | Selector | 條件 |
| --- | --- | --- | --- |
| 1 | I adopt the reference trip’s recorded daily starts, endpoints, route and time windows shown in this immutable candidate. | label:has([data-permission-review-check="dayEnds"]) | 依當前 DOM 核對 |
| 2 | I acknowledge every disclosed recording gap and uncertainty. Stationary clusters are inferred stops; missing CP clocks and unrecorded movement remain unknown. | label:has([data-permission-review-check="timingUncertainty"]) | 僅候選列出 uncertainty IDs 時顯示 |
| 3 | I acknowledge that the listed retreat, emergency-bivy and route-reversal items remain pending separate Safety / Emergency review. This does not approve them. | label:has([data-permission-review-check="safetyHandoff"]) | 僅候選要求 handoff 時顯示 |

資料條件：saved_baseline, review_readiness。
缺項處置：保留實際資料缺項、disabled／錯誤與 receipt；正向教學仍待補，不能套用歷史畫面或列為通過。

## 07. 保存新候選，或採用已審查版本

狀態：PENDING_CURRENT_UI_CAPTURE；來源：SOURCE_VERIFIED_CAPTURE_PENDING。
位置：http://127.0.0.1:9099/admin/dashboard?projectId=dongqing_batongguan_historic_trail_newImport#outdoor-permission

準備：
1. 延續同版保存與採用按鈕；disabled 可如實拍攝。
2. 只在已有針對本版的本人審查與確認時操作 Accept；不能為教學先採用。

步驟與畫面位置：

| 數字 | 畫面實際標籤／內容 | Selector | 條件 |
| --- | --- | --- | --- |
| 1 | Save candidate version | [data-permission-baseline-save] | 依當前 DOM 核對 |
| 2 | Accept reviewed baseline | [data-permission-baseline-accept] | 依當前 DOM 核對 |

資料條件：saved_baseline, explicit_human_review_for_accept。
缺項處置：保留實際資料缺項、disabled／錯誤與 receipt；正向教學仍待補，不能套用歷史畫面或列為通過。

## 08. 把四日行程與 Golden 的差異寫清楚

狀態：PENDING_CURRENT_UI_CAPTURE；來源：SOURCE_VERIFIED_CAPTURE_PENDING。
位置：http://127.0.0.1:9099/admin/dashboard?projectId=dongqing_batongguan_historic_trail_newImport#outdoor-permission

準備：
1. 選 Human Design，等待 catalog 的真實狀態。
2. 可貼下方已授權四日原文；日期、腳程、休息分鐘未提供就保留未填。

步驟與畫面位置：

| 數字 | 畫面實際標籤／內容 | Selector | 條件 |
| --- | --- | --- | --- |
| 1 | 人工行程 | [data-planned-human-text] | 依當前 DOM 核對 |
| 2 | 計畫啟程 | [data-planned-field="departure"] | 依當前 DOM 核對 |
| 3 | 腳程估計 | [data-planned-field="paceMode"] | 依當前 DOM 核對 |

資料條件：source_catalog, user_four_day_text。
缺項處置：保留實際資料缺項、disabled／錯誤與 receipt；正向教學仍待補，不能套用歷史畫面或列為通過。

## 09. 解析後，逐句處理待定位事項

狀態：PENDING_CURRENT_UI_CAPTURE；來源：RESTORED_MODULE_INTEGRATED_CAPTURE_PENDING。
位置：http://127.0.0.1:9099/admin/dashboard?projectId=dongqing_batongguan_historic_trail_newImport#outdoor-permission

準備：
1. 展開原文解析與逐句釐清；保留模型開關原狀，拍前記是否啟用。
2. 使用實際四日原文執行一般解析，等待結果，保留 unresolved 句子與原文 SHA。
3. 若解析失敗，保留錯誤與資料缺口，不拿舊結果補上。

步驟與畫面位置：

| 數字 | 畫面實際標籤／內容 | Selector | 條件 |
| --- | --- | --- | --- |
| 1 | 使用已設定模型協助產生可核對草稿 | label:has([data-planned-intent-model]) | 依當前 DOM 核對 |
| 2 | 解析人工行程 | [data-planned-intent-action="parse"] | 依當前 DOM 核對 |
| 3 | 動態解析狀態／原文 SHA；原句／修訂句 | [data-planned-intent-result] | 解析回應後才顯示 |

資料條件：source_catalog, user_four_day_text, intent_response。
缺項處置：保留實際資料缺項、disabled／錯誤與 receipt；正向教學仍待補，不能套用歷史畫面或列為通過。

## 10. 設定停留或紮營的時間

狀態：PENDING_CURRENT_UI_CAPTURE；來源：SOURCE_VERIFIED_CAPTURE_PENDING。
位置：http://127.0.0.1:9099/admin/dashboard?projectId=dongqing_batongguan_historic_trail_newImport#outdoor-permission

準備：
1. 展開明確行程差異與來源選段，選 stop 或 camp 以顯示 duration。
2. 用真正錨點與已提供時程；原文沒給分鐘時只拍未填欄位，標資料待補。

步驟與畫面位置：

| 數字 | 畫面實際標籤／內容 | Selector | 條件 |
| --- | --- | --- | --- |
| 1 | 操作；選項 固定停留 或 紮營／離營 | [data-planned-editor="kind"] | 依當前 DOM 核對 |
| 2 | 位置／起點 | [data-planned-editor="at"] | 依當前 DOM 核對 |
| 3 | 停留／紮營分鐘 | [data-planned-editor="duration"] | kind=stop 或 camp |

資料條件：source_catalog, resolved_anchor, actual_stop_or_camp_duration。
缺項處置：保留實際資料缺項、disabled／錯誤與 receipt；正向教學仍待補，不能套用歷史畫面或列為通過。

## 11. 用來源選段描述主線與支線

狀態：PENDING_CURRENT_UI_CAPTURE；來源：SOURCE_VERIFIED_CAPTURE_PENDING。
位置：http://127.0.0.1:9099/admin/dashboard?projectId=dongqing_batongguan_historic_trail_newImport#outdoor-permission

準備：
1. kind 選支線往返（branch）或取代主線路段（replace）；展開來源選段。
2. 選實際來源及 trkseg 後才會有 sourceFrom / sourceTo 選項。
3. 阿桑來戛與異祿閣未定位／來源不完整時保持缺口；R4仍待審。

步驟與畫面位置：

| 數字 | 畫面實際標籤／內容 | Selector | 條件 |
| --- | --- | --- | --- |
| 1 | 來源 | [data-planned-editor="sourceId"] | 依當前 DOM 核對 |
| 2 | 不跨缺口的來源段 | [data-planned-editor="partIndex"] | 依當前 DOM 核對 |
| 3 | 來源起點 | [data-planned-editor="sourceFrom"] | 依當前 DOM 核對 |
| 4 | 來源終點 | [data-planned-editor="sourceTo"] | 依當前 DOM 核對 |

資料條件：source_catalog, source_segment, resolved_branch_endpoints。
缺項處置：保留實際資料缺項、disabled／錯誤與 receipt；正向教學仍待補，不能套用歷史畫面或列為通過。

## 12. 讀取地圖來源與 Rudy 向量山徑

狀態：PENDING_CURRENT_UI_CAPTURE；來源：RESTORED_MODULE_INTEGRATED_CAPTURE_PENDING。
位置：http://127.0.0.1:9099/admin/dashboard?projectId=dongqing_batongguan_historic_trail_newImport#outdoor-permission

準備：
1. 在 Permission 上方找到地圖來源與候選描線。
2. 先按重新讀取地圖來源，記 PBF 與 Mapsforge 是否 available、來源版本與 SHA。
3. 其餘兩個按鈕 enabled 由來源決定；不為拍照重建來源。

步驟與畫面位置：

| 數字 | 畫面實際標籤／內容 | Selector | 條件 |
| --- | --- | --- | --- |
| 1 | 重新讀取地圖來源 | [data-planned-map-action="refresh"] | 依當前 DOM 核對 |
| 2 | 由已登錄 PBF 重建新來源版本 | [data-planned-map-action="rebuild"] | 依當前 DOM 核對 |
| 3 | 讀取已登錄 Rudy 向量山徑 | [data-planned-map-action="mapsforge"] | 依當前 DOM 核對 |

資料條件：registered_map_sources, pbf_for_rebuild, mapsforge_for_vector_read。
缺項處置：保留實際資料缺項、disabled／錯誤與 receipt；正向教學仍待補，不能套用歷史畫面或列為通過。

## 13. 加入地形、隊伍與分日估時假設

狀態：PENDING_CURRENT_UI_CAPTURE；來源：RESTORED_MODULE_INTEGRATED_CAPTURE_PENDING。
位置：http://127.0.0.1:9099/admin/dashboard?projectId=dongqing_batongguan_historic_trail_newImport#outdoor-permission

準備：
1. 展開地形、隊伍與分日估時。
2. 只填已授權的真實假設；其他欄位維持未知，展開必要進階欄位核對。

步驟與畫面位置：

| 數字 | 畫面實際標籤／內容 | Selector | 條件 |
| --- | --- | --- | --- |
| 1 | 啟用此版的地形與隊伍估時 | label:has([data-planned-timing-enabled]) | 依當前 DOM 核對 |
| 2 | 假設平地腳程 km/h | [data-planned-timing-field="assumed_flat_speed_kmh"] | 依當前 DOM 核對 |
| 3 | 每日總耗時上限（分） | [data-planned-timing-field="max_daily_elapsed_minutes"] | 依當前 DOM 核對 |

資料條件：actual_timing_assumptions。
缺項處置：保留實際資料缺項、disabled／錯誤與 receipt；正向教學仍待補，不能套用歷史畫面或列為通過。

## 14. 先預覽，再保存確切 Planned 版本

狀態：PENDING_CURRENT_UI_CAPTURE；來源：SOURCE_VERIFIED_CAPTURE_PENDING。
位置：http://127.0.0.1:9099/admin/dashboard?projectId=dongqing_batongguan_historic_trail_newImport#outdoor-permission

準備：
1. 在真實來源及已核對操作上建立 no-save preview。
2. 只有 Save 條件成立且版本內容經確認才保存；照片可以保留 disabled，但不能代表保存成功。

步驟與畫面位置：

| 數字 | 畫面實際標籤／內容 | Selector | 條件 |
| --- | --- | --- | --- |
| 1 | 加入行程差異 | [data-planned-action="add-operation"] | 依當前 DOM 核對 |
| 2 | 預覽 Planned 幾何與節奏 | [data-planned-action="preview"] | 依當前 DOM 核對 |
| 3 | Save Planned Version | [data-planned-action="save"] | 依當前 DOM 核對 |

資料條件：source_catalog, resolved_operations, current_preview, save_eligibility。
缺項處置：保留實際資料缺項、disabled／錯誤與 receipt；正向教學仍待補，不能套用歷史畫面或列為通過。

## 15. 預覽結果：核對來源片段與缺口

狀態：PENDING_CURRENT_UI_CAPTURE；來源：SOURCE_VERIFIED_CAPTURE_PENDING。
位置：http://127.0.0.1:9099/admin/dashboard?projectId=dongqing_batongguan_historic_trail_newImport#outdoor-permission

準備：
1. 先完成第14頁的實際 preview。
2. 確認只有主 preview（非比較版）targets；如同時顯示比較版，需將 query 限定當前預覽。
3. 如僅 D4.3 來源片段，標示部分片段，四日主線與支線仍未完成。

步驟與畫面位置：

| 數字 | 畫面實際標籤／內容 | Selector | 條件 |
| --- | --- | --- | --- |
| 1 | 動態 preview status · SHA · 距離 | [data-planned-preview]:has([data-planned-map="preview"]) > p:first-of-type | 依當前 DOM 核對 |
| 2 | Golden / Planned；+ / − / Fit；拖曳平移 · 點選錨點查核 | [data-planned-map="preview"] | 依當前 DOM 核對 |

資料條件：current_preview, preview_geometry。
缺項處置：保留實際資料缺項、disabled／錯誤與 receipt；正向教學仍待補，不能套用歷史畫面或列為通過。

## 16. 核對分日表、移動與停留時間軸

狀態：PENDING_CURRENT_UI_CAPTURE；來源：SOURCE_VERIFIED_CAPTURE_PENDING。
位置：http://127.0.0.1:9099/admin/dashboard?projectId=dongqing_batongguan_historic_trail_newImport#outdoor-permission

準備：
1. 同版 preview 有 itinerary 與 events 後拍。
2. 如果沒有 events，保留尚無資料畫面；時間軸教學仍列待補，不替換成示例。

步驟與畫面位置：

| 數字 | 畫面實際標籤／內容 | Selector | 條件 |
| --- | --- | --- | --- |
| 1 | Planned 分日、移動與停留；日／啟程 → 到達／移動／停留／營地／距離／限制 | [data-planned-preview]:has([data-planned-map="preview"]) [data-planned-itinerary] > .planned-table-scroll | 依當前 DOM 核對 |
| 2 | 時間軸：移動、固定停留、離營與未知 · N 原始紀錄 | [data-planned-preview]:has([data-planned-map="preview"]) [data-planned-itinerary] > details:has([data-planned-raw-timeline]) > summary | 預覽有 events 時顯示 |

資料條件：current_preview, itinerary_events。
缺項處置：保留實際資料缺項、disabled／錯誤與 receipt；正向教學仍待補，不能套用歷史畫面或列為通過。

## 17. 審查此 Planned 版本

狀態：PENDING_CURRENT_UI_CAPTURE；來源：SOURCE_VERIFIED_CAPTURE_PENDING。
位置：http://127.0.0.1:9099/admin/dashboard?projectId=dongqing_batongguan_historic_trail_newImport#outdoor-permission

準備：
1. 讀取真實 Saved Planned，核對 manifest 與來源 current。
2. 不代勾四個人工 review checkbox；dirty 或來源改變的 disabled 狀態如實保留。

步驟與畫面位置：

| 數字 | 畫面實際標籤／內容 | Selector | 條件 |
| --- | --- | --- | --- |
| 1 | 已檢視 來源與選段範圍 | label:has([data-planned-review-check="sources"]) | 依當前 DOM 核對 |
| 2 | 已檢視 幾何順序、往返與缺口 | label:has([data-planned-review-check="geometry"]) | 依當前 DOM 核對 |
| 3 | 已檢視 分日、腳程與固定停留 | label:has([data-planned-review-check="timing"]) | 依當前 DOM 核對 |
| 4 | 已檢視 不確定性與候選來源限制 | label:has([data-planned-review-check="uncertainty"]) | 依當前 DOM 核對 |

資料條件：saved_planned, manifest_binding。
缺項處置：保留實際資料缺項、disabled／錯誤與 receipt；正向教學仍待補，不能套用歷史畫面或列為通過。

## 18. 記錄審查，再選 Planned 作為分析主體

狀態：PENDING_CURRENT_UI_CAPTURE；來源：SOURCE_VERIFIED_CAPTURE_PENDING。
位置：http://127.0.0.1:9099/admin/dashboard?projectId=dongqing_batongguan_historic_trail_newImport#outdoor-permission

準備：
1. 延續同版 Saved Planned，讀完整限制。
2. 有 actual human review 才記錄／選用，若零 issues，第1步須根據實際沒有限制的證據調整講稿及編號。

步驟與畫面位置：

| 數字 | 畫面實際標籤／內容 | Selector | 條件 |
| --- | --- | --- | --- |
| 1 | 我已檢視以上完整 N 筆限制，將全部綁定此版本確認 | label:has([data-planned-review-all-issues]) | 此版本有 review issues 時顯示 |
| 2 | 記錄此版本審查 | [data-planned-action="review"] | 依當前 DOM 核對 |
| 3 | 以此 Planned 分析六力 | [data-planned-action="select"] | 依當前 DOM 核對 |

資料條件：saved_planned, explicit_human_planned_review。
缺項處置：保留實際資料缺項、disabled／錯誤與 receipt；正向教學仍待補，不能套用歷史畫面或列為通過。

## 19. 填寫此版本的補件與審查資料

狀態：PENDING_CURRENT_UI_CAPTURE；來源：RESTORED_MODULE_INTEGRATED_CAPTURE_PENDING。
位置：http://127.0.0.1:9099/admin/dashboard?projectId=dongqing_batongguan_historic_trail_newImport#outdoor-permission

準備：
1. 先還原真實 Saved Planned，補件表只有 version_id 存在才 render。
2. 先讀已保存補件；若未有真實聲明者與隊伍資料，拍空表並列缺項。

步驟與畫面位置：

| 數字 | 畫面實際標籤／內容 | Selector | 條件 |
| --- | --- | --- | --- |
| 1 | 實際聲明者代號 | [data-planned-context-field="declaredBy"] | 依當前 DOM 核對 |
| 2 | 聲明時間（ISO 與時區） | [data-planned-context-field="declaredAt"] | 依當前 DOM 核對 |
| 3 | 隊伍人數 | [data-planned-context-field="teamSize"] | 依當前 DOM 核對 |

資料條件：saved_planned, actual_declarer_and_team。
缺項處置：保留實際資料缺項、disabled／錯誤與 receipt；正向教學仍待補，不能套用歷史畫面或列為通過。

## 20. 保存此版補件，保留未知與來源

狀態：PENDING_CURRENT_UI_CAPTURE；來源：RESTORED_MODULE_INTEGRATED_CAPTURE_PENDING。
位置：http://127.0.0.1:9099/admin/dashboard?projectId=dongqing_batongguan_historic_trail_newImport#outdoor-permission

準備：
1. 讀完所有補件；pending 保持 pending。
2. 本人完整聲明才勾確認並保存，讀回 context SHA；拍攝空表或 disabled 不能當成補件保存通過。

步驟與畫面位置：

| 數字 | 畫面實際標籤／內容 | Selector | 條件 |
| --- | --- | --- | --- |
| 1 | 我確認以上是此版本的完整人工聲明，未填項目維持未知 | label:has([data-planned-context-confirm]) | 依當前 DOM 核對 |
| 2 | 保存此版補件 | [data-planned-context-action="save"] | 依當前 DOM 核對 |

資料條件：saved_planned, actual_context_and_evidence, explicit_context_confirmation。
缺項處置：保留實際資料缺項、disabled／錯誤與 receipt；正向教學仍待補，不能套用歷史畫面或列為通過。

## 21. 追加準備並重算此版六力

狀態：PENDING_CURRENT_UI_CAPTURE；來源：SOURCE_VERIFIED_CAPTURE_PENDING。
位置：http://127.0.0.1:9099/admin/dashboard?projectId=dongqing_batongguan_historic_trail_newImport#outdoor-permission

準備：
1. 同版 review/context ready 後先讀作業列表，避免重複 start。
2. 啟動只限已授權真實工作，不用 fake plan 清空 gate；或可拍既有作業的入口與讀取。

步驟與畫面位置：

| 數字 | 畫面實際標籤／內容 | Selector | 條件 |
| --- | --- | --- | --- |
| 1 | 追加準備並重算六力 | [data-planned-run-action="start"] | 依當前 DOM 核對 |
| 2 | 此版本保存的作業 | [data-planned-analysis-run-select] | 依當前 DOM 核對 |
| 3 | 讀取作業狀態 | [data-planned-run-action="read"] | 依當前 DOM 核對 |

資料條件：reviewed_planned, current_context, same_version_run。
缺項處置：保留實際資料缺項、disabled／錯誤與 receipt；正向教學仍待補，不能套用歷史畫面或列為通過。

## 22. 逐一讀取準備與六力結果

狀態：PENDING_CURRENT_UI_CAPTURE；來源：SOURCE_VERIFIED_CAPTURE_PENDING。
位置：http://127.0.0.1:9099/admin/dashboard?projectId=dongqing_batongguan_historic_trail_newImport#outdoor-permission

準備：
1. 選同版 run 並按讀取作業狀態。
2. 等待真正 preparation/projections receipt；逐六力記錄 pass/warn/fail/unknown，不把 completed 當全通過。

步驟與畫面位置：

| 數字 | 畫面實際標籤／內容 | Selector | 條件 |
| --- | --- | --- | --- |
| 1 | 動態 version ID · run ID · status · 階段 · attempt · 執行位置 | [data-planned-analysis-run] > p:first-of-type | 依當前 DOM 核對 |
| 2 | 準備：實際狀態／原因 | [data-planned-analysis-run] > p text starts 準備： | 依當前 DOM 核對 |
| 3 | 六力／此作業結果／摘要／待補資料 | [data-planned-analysis-run] > .planned-table-scroll:nth-of-type(2) | 依當前 DOM 核對 |

資料條件：same_version_run, preparation_and_six_force_receipts。
缺項處置：保留實際資料缺項、disabled／錯誤與 receipt；正向教學仍待補，不能套用歷史畫面或列為通過。

## 23. 閱讀同版行前綜合報告

狀態：PENDING_CURRENT_UI_CAPTURE；來源：RESTORED_MODULE_INTEGRATED_CAPTURE_PENDING。
位置：http://127.0.0.1:9099/admin/dashboard?projectId=dongqing_batongguan_historic_trail_newImport#outdoor-permission

準備：
1. 同版作業必須已有 pretrip_report 且 geometry/timing/context 綁定匹配。
2. 若只有 pending 報告提示，拍真實阻擋作補充證據，正向報告頁仍待補。
3. 風險可能為空；標題後的實際 p/ul 要一同入鏡。

步驟與畫面位置：

| 數字 | 畫面實際標籤／內容 | Selector | 條件 |
| --- | --- | --- | --- |
| 1 | 候選規劃建議：decision · 完整度 status | [data-planned-report-decision] | 依當前 DOM 核對 |
| 2 | 動態 version ID · run ID · 補件 context SHA | [data-planned-pretrip-report] > p:nth-of-type(2) | 依當前 DOM 核對 |
| 3 | 前三大風險來源 | [data-planned-pretrip-report] > h4 text=前三大風險來源 | 依當前 DOM 核對 |

資料條件：same_version_run, current_context, matching_pretrip_report。
缺項處置：保留實際資料缺項、disabled／錯誤與 receipt；正向教學仍待補，不能套用歷史畫面或列為通過。

## 24. 核對來源並下載完整行前報告

狀態：PENDING_CURRENT_UI_CAPTURE；來源：RESTORED_MODULE_INTEGRATED_CAPTURE_PENDING。
位置：http://127.0.0.1:9099/admin/dashboard?projectId=dongqing_batongguan_historic_trail_newImport#outdoor-permission

準備：
1. 延續第23頁匹配的報告。
2. 拍 artifact SHA 與下載前後狀態；下載檔放 Scout，核對實際 bytes/SHA 才記完成。

步驟與畫面位置：

| 數字 | 畫面實際標籤／內容 | Selector | 條件 |
| --- | --- | --- | --- |
| 1 | 動態 artifact ref；SHA-256：完整雜湊 | [data-planned-pretrip-report] > p:has(> code) | 依當前 DOM 核對 |
| 2 | 核對並下載完整行前報告 | [data-planned-report-download] | 依當前 DOM 核對 |
| 3 | 尚未下載 或 實際下載核對結果 | [data-planned-report-download-status] | 依當前 DOM 核對 |

資料條件：matching_pretrip_report, download_receipt。
缺項處置：保留實際資料缺項、disabled／錯誤與 receipt；正向教學仍待補，不能套用歷史畫面或列為通過。

## 25. 匯出保存版本，保留完整依據

狀態：PENDING_CURRENT_UI_CAPTURE；來源：SOURCE_VERIFIED_CAPTURE_PENDING。
位置：http://127.0.0.1:9099/admin/dashboard?projectId=dongqing_batongguan_historic_trail_newImport#outdoor-permission

準備：
1. 真實 Saved Planned manifest 已還原，三匯出控制可見。
2. 實际 GPX/manifest/bundle 下載後核對內容與 SHA，沒下載只表示入口已拍。

步驟與畫面位置：

| 數字 | 畫面實際標籤／內容 | Selector | 條件 |
| --- | --- | --- | --- |
| 1 | 匯出 Planned GPX | [data-planned-export="gpx"] | 依當前 DOM 核對 |
| 2 | 匯出 行程 Manifest | [data-planned-export="manifest"] | 依當前 DOM 核對 |
| 3 | 匯出 完整 Bundle | [data-planned-export="bundle"] | 依當前 DOM 核對 |

資料條件：saved_planned, export_receipts。
缺項處置：保留實際資料缺項、disabled／錯誤與 receipt；正向教學仍待補，不能套用歷史畫面或列為通過。

## 26. 還原 Planned 版本，或切回 Golden

狀態：PENDING_CURRENT_UI_CAPTURE；來源：SOURCE_VERIFIED_CAPTURE_PENDING。
位置：http://127.0.0.1:9099/admin/dashboard?projectId=dongqing_batongguan_historic_trail_newImport#outdoor-permission

準備：
1. 先重新讀取來源與版本，列真實 version ID。
2. 選版本後按 Restore，核對 SHA。Golden 按鈕只在確定要切主體時操作。

步驟與畫面位置：

| 數字 | 畫面實際標籤／內容 | Selector | 條件 |
| --- | --- | --- | --- |
| 1 | Planned 版本 | [data-planned-version] | 依當前 DOM 核對 |
| 2 | Restore Planned Version | [data-planned-action="restore"] | 依當前 DOM 核對 |
| 3 | 切回 Golden 分析 | [data-planned-action="golden"] | 依當前 DOM 核對 |

資料條件：saved_planned, restore_receipt。
缺項處置：保留實際資料缺項、disabled／錯誤與 receipt；正向教學仍待補，不能套用歷史畫面或列為通過。

## 27. 重新找回作業，符合條件才 Resume

狀態：PENDING_CURRENT_UI_CAPTURE；來源：SOURCE_VERIFIED_CAPTURE_PENDING。
位置：http://127.0.0.1:9099/admin/dashboard?projectId=dongqing_batongguan_historic_trail_newImport#outdoor-permission

準備：
1. 選本版 run 並刷新狀態，核對 can_resume/current context。
2. 沒有真實可恢復作業時只能拍 disabled，恢復成功段落繼續待補；不可故意製造 live 故障。

步驟與畫面位置：

| 數字 | 畫面實際標籤／內容 | Selector | 條件 |
| --- | --- | --- | --- |
| 1 | 重新讀取作業列表 | [data-planned-run-action="list"] | 依當前 DOM 核對 |
| 2 | 讀取作業狀態 | [data-planned-run-action="read"] | 依當前 DOM 核對 |
| 3 | Resume 此作業 | [data-planned-run-action="resume"] | 依當前 DOM 核對 |

資料條件：same_version_run, resumable_run_for_resume。
缺項處置：保留實際資料缺項、disabled／錯誤與 receipt；正向教學仍待補，不能套用歷史畫面或列為通過。

## 28. 無 Ref. GPX：從分析區域開始

狀態：PENDING_CURRENT_UI_CAPTURE；來源：RESTORED_MODULE_INTEGRATED_CAPTURE_PENDING。
位置：http://127.0.0.1:9099/admin/dashboard?projectId=dongqing_batongguan_historic_trail_newImport#outdoor-permission

準備：
1. Permission 上方找到無 Ref. GPX：從分析區域開始。
2. 未提供實際探索名稱與 AOI 時只拍表單，不建立或切換專案。

步驟與畫面位置：

| 數字 | 畫面實際標籤／內容 | Selector | 條件 |
| --- | --- | --- | --- |
| 1 | 探索 workspace 名稱 | [data-exploration-field="projectId"] | 依當前 DOM 核對 |
| 2 | 探索目的 | [data-exploration-field="intent"] | 依當前 DOM 核對 |
| 3 | 座標系統 | [data-exploration-field="crs"] | 依當前 DOM 核對 |

資料條件：actual_exploration_name_and_intent。
缺項處置：保留實際資料缺項、disabled／錯誤與 receipt；正向教學仍待補，不能套用歷史畫面或列為通過。

## 29. 定義 AOI 邊界，先核對座標系統

狀態：PENDING_CURRENT_UI_CAPTURE；來源：RESTORED_MODULE_INTEGRATED_CAPTURE_PENDING。
位置：http://127.0.0.1:9099/admin/dashboard?projectId=dongqing_batongguan_historic_trail_newImport#outdoor-permission

準備：
1. 沿用探索表單，核對 CRS 選值。
2. 待實際 AOI 四界提供後填寫；四日行程只有 C1 一組座標，不能據此捏造完整 AOI。

步驟與畫面位置：

| 數字 | 畫面實際標籤／內容 | Selector | 條件 |
| --- | --- | --- | --- |
| 1 | AOI 最小 X／西界 | [data-exploration-field="west"] | 依當前 DOM 核對 |
| 2 | AOI 最小 Y／南界 | [data-exploration-field="south"] | 依當前 DOM 核對 |
| 3 | AOI 最大 X／東界 | [data-exploration-field="east"] | 依當前 DOM 核對 |
| 4 | AOI 最大 Y／北界 | [data-exploration-field="north"] | 依當前 DOM 核對 |

資料條件：actual_aoi_and_crs。
缺項處置：保留實際資料缺項、disabled／錯誤與 receipt；正向教學仍待補，不能套用歷史畫面或列為通過。

## 30. 建立探索資料，再準備 DEM 與 A/B 請求

狀態：PENDING_CURRENT_UI_CAPTURE；來源：RESTORED_MODULE_INTEGRATED_CAPTURE_PENDING。
位置：http://127.0.0.1:9099/admin/dashboard?projectId=dongqing_batongguan_historic_trail_newImport#outdoor-permission

準備：
1. 只能在已授權探索 workspace 及真實 AOI/DEM receipt 上示範。
2. prepare needs can_prepare，trh needs trh_request_available；建立 A/B 請求不代表已算出 R1–R3。
3. Root若測真正探索 workspace，將實際 projectId 明示為探索案例；不得把另一專案截圖標為東清。

步驟與畫面位置：

| 數字 | 畫面實際標籤／內容 | Selector | 條件 |
| --- | --- | --- | --- |
| 1 | 建立探索 workspace | [data-exploration-action="create"] | 依當前 DOM 核對 |
| 2 | 準備區域地圖與 DEM | [data-exploration-action="prepare"] | 依當前 DOM 核對 |
| 3 | 建立 A/B 地形候選請求 | [data-exploration-action="trh"] | 依當前 DOM 核對 |

資料條件：exploration_receipt, dem_preparation, actual_a_b, trh_request_receipt。
缺項處置：保留實際資料缺項、disabled／錯誤與 receipt；正向教學仍待補，不能套用歷史畫面或列為通過。

## 31. 歸來後復盤：先說明 GPX 是什麼記錄

狀態：PENDING_CURRENT_UI_CAPTURE；來源：RESTORED_MODULE_INTEGRATED_CAPTURE_PENDING。
位置：http://127.0.0.1:9099/admin/dashboard?projectId=dongqing_batongguan_historic_trail_newImport#outdoor-permission

準備：
1. 展開歸來後復盤 · Recorded / Golden / Planned。
2. 先核對資料性質選項，不用 Golden 文件冒充本次歸來記錄。

步驟與畫面位置：

| 數字 | 畫面實際標籤／內容 | Selector | 條件 |
| --- | --- | --- | --- |
| 1 | 主要隊員 | [data-recorded-field="member"] | 依當前 DOM 核對 |
| 2 | 記錄裝置 | [data-recorded-field="device"] | 依當前 DOM 核對 |
| 3 | 資料來源 | [data-recorded-field="origin"] | 依當前 DOM 核對 |

資料條件：actual_recording_metadata。
缺項處置：保留實際資料缺項、disabled／錯誤與 receipt；正向教學仍待補，不能套用歷史畫面或列為通過。

## 32. 匯入原始 GPX，再選比較的計畫

狀態：PENDING_CURRENT_UI_CAPTURE；來源：RESTORED_MODULE_INTEGRATED_CAPTURE_PENDING。
位置：http://127.0.0.1:9099/admin/dashboard?projectId=dongqing_batongguan_historic_trail_newImport#outdoor-permission

準備：
1. 需要實際授權 GPX 檔案及 observation kind。
2. 尚未提供本次 GPX 時拍空表即可，upload 後及比較結果仍列待補。

步驟與畫面位置：

| 數字 | 畫面實際標籤／內容 | Selector | 條件 |
| --- | --- | --- | --- |
| 1 | GPX 檔案 | [data-recorded-files] | 依當前 DOM 核對 |
| 2 | 匯入原始 GPX | [data-recorded-action="upload"] | 依當前 DOM 核對 |
| 3 | 比較的 Planned 版本 | [data-recorded-field="plan"] | 依當前 DOM 核對 |

資料條件：authorized_recorded_gpx, observation_kind, planned_comparison_if_any。
缺項處置：保留實際資料缺項、disabled／錯誤與 receipt；正向教學仍待補，不能套用歷史畫面或列為通過。

## 33. 保存 Recorded，再找回同一版本

狀態：PENDING_CURRENT_UI_CAPTURE；來源：RESTORED_MODULE_INTEGRATED_CAPTURE_PENDING。
位置：http://127.0.0.1:9099/admin/dashboard?projectId=dongqing_batongguan_historic_trail_newImport#outdoor-permission

準備：
1. 只有真實已上傳檔案才能 Save Recorded；先讀既有版本是否存在。
2. 從已存復盤版本下拉選 ID 再還原；原文沒有個人 Recorded 資料，存在性需實際讀取。

步驟與畫面位置：

| 數字 | 畫面實際標籤／內容 | Selector | 條件 |
| --- | --- | --- | --- |
| 1 | 建立不可覆寫的 Recorded 版本 | [data-recorded-action="save"] | 依當前 DOM 核對 |
| 2 | 讀取已存版本與作業 | [data-recorded-action="reload"] | 依當前 DOM 核對 |
| 3 | 還原版本 | [data-recorded-action="restore"] | 依當前 DOM 核對 |

資料條件：saved_recorded, recorded_manifest。
缺項處置：保留實際資料缺項、disabled／錯誤與 receipt；正向教學仍待補，不能套用歷史畫面或列為通過。

## 34. 以 Recorded 重算六力與恢復作業

狀態：PENDING_CURRENT_UI_CAPTURE；來源：RESTORED_MODULE_INTEGRATED_CAPTURE_PENDING。
位置：http://127.0.0.1:9099/admin/dashboard?projectId=dongqing_batongguan_historic_trail_newImport#outdoor-permission

準備：
1. 還原真實 Recorded 後才選分析主體／重算。
2. run.can_resume=true 才操作恢復，無資料不造 fake run。

步驟與畫面位置：

| 數字 | 畫面實際標籤／內容 | Selector | 條件 |
| --- | --- | --- | --- |
| 1 | 將此 Recorded 作為六力分析主體 | [data-recorded-action="select"] | 依當前 DOM 核對 |
| 2 | 準備此記錄並重算六力 | [data-recorded-action="analyse"] | 依當前 DOM 核對 |
| 3 | 恢復此作業 | [data-recorded-action="resume"] | 依當前 DOM 核對 |

資料條件：saved_recorded, recorded_analysis_run, resumable_recorded_run。
缺項處置：保留實際資料缺項、disabled／錯誤與 receipt；正向教學仍待補，不能套用歷史畫面或列為通過。

## 35. 主地圖：放大並核對原生細節

狀態：PENDING_CURRENT_UI_CAPTURE；來源：SOURCE_VERIFIED_CAPTURE_PENDING。
位置：http://127.0.0.1:9099/admin/dashboard?projectId=dongqing_batongguan_historic_trail_newImport#map → frame #pretripMapFrame

準備：
1. 在 #map 使用 #pretripMapFrame 內的 canonical map，不換入口或 workspace。
2. Fit 後放大、平移到實際視野，記 native zoom、圖磚清單及向量；ready 才拍正向範例。

步驟與畫面位置：

| 數字 | 畫面實際標籤／內容 | Selector | 條件 |
| --- | --- | --- | --- |
| 1 | + | #zoomIn | 依當前 DOM 核對 |
| 2 | 動態 zoom level／native tile 載入資訊 | #zoomLevel | 依當前 DOM 核對 |
| 3 | 實際 MapLibre 或 SVG 圖面，無固定文字標籤 | #mapRendererShell | 依當前 DOM 核對 |

資料條件：main_map_actual_native_tile_receipts。
缺項處置：保留實際資料缺項、disabled／錯誤與 receipt；正向教學仍待補，不能套用歷史畫面或列為通過。

## 36. 主地圖：缺圖時查看原因並恢復

狀態：PENDING_CURRENT_UI_CAPTURE；來源：SOURCE_VERIFIED_CAPTURE_PENDING。
位置：http://127.0.0.1:9099/admin/dashboard?projectId=dongqing_batongguan_historic_trail_newImport#map → frame #pretripMapFrame

準備：
1. 沿同一 Main frame 保留真實 loading/missing/error 證據。
2. 若現在全部 ready，不修改 DOM 造 missing；使用真實已記錄可重放故障，或保持此頁待拍。
3. 恢復過程前後拍獨立 receipts；不清使用者快取來湊情境。

步驟與畫面位置：

| 數字 | 畫面實際標籤／內容 | Selector | 條件 |
| --- | --- | --- | --- |
| 1 | 動態 zoom level／native tile 載入資訊 | #zoomLevel | 依當前 DOM 核對 |
| 2 | 動態實際 renderer/loading/missing/error 訊息 | #mapRendererStatus | 真實 loading / missing / error 提示可見；ready 時可能隱藏 |
| 3 | 更新圖磚 或 停止更新 | #refreshMapTiles | 依當前 DOM 核對 |

資料條件：main_map_actual_failure_receipt, main_map_actual_recovery_receipt。
缺項處置：保留實際資料缺項、disabled／錯誤與 receipt；正向教學仍待補，不能套用歷史畫面或列為通過。

## 37. Weather：核對放大後的底圖細節

狀態：PENDING_CURRENT_UI_CAPTURE；來源：SOURCE_VERIFIED_CAPTURE_PENDING。
位置：http://127.0.0.1:9099/admin/dashboard?projectId=dongqing_batongguan_historic_trail_newImport#outdoor-weather → frame iframe[data-weather-cwa-map-frame]

準備：
1. 切 #outdoor-weather，在 iframe[data-weather-cwa-map-frame] 中操作。
2. 同 Main 標準核對當前所需原生圖磚、向量及 renderer；另一頁成功不替代本頁。

步驟與畫面位置：

| 數字 | 畫面實際標籤／內容 | Selector | 條件 |
| --- | --- | --- | --- |
| 1 | + | #zoomIn | 依當前 DOM 核對 |
| 2 | 動態 zoom level／native tile 載入資訊 | #zoomLevel | 依當前 DOM 核對 |
| 3 | 實際 MapLibre 或 SVG 圖面，無固定文字標籤 | #mapRendererShell | 依當前 DOM 核對 |

資料條件：weather_map_actual_native_tile_receipts。
缺項處置：保留實際資料缺項、disabled／錯誤與 receipt；正向教學仍待補，不能套用歷史畫面或列為通過。

## 38. Weather：缺圖時查看原因並恢復

狀態：PENDING_CURRENT_UI_CAPTURE；來源：SOURCE_VERIFIED_CAPTURE_PENDING。
位置：http://127.0.0.1:9099/admin/dashboard?projectId=dongqing_batongguan_historic_trail_newImport#outdoor-weather → frame iframe[data-weather-cwa-map-frame]

準備：
1. 在 Weather canonical frame 保留實際失敗和恢復 receipt。
2. ready 時隱藏的 #mapRendererStatus 不能作有效 target；若無故障畫面本頁待拍，不能冒充目前失敗。

步驟與畫面位置：

| 數字 | 畫面實際標籤／內容 | Selector | 條件 |
| --- | --- | --- | --- |
| 1 | 動態 zoom level／native tile 載入資訊 | #zoomLevel | 依當前 DOM 核對 |
| 2 | 動態實際 renderer/loading/missing/error 訊息 | #mapRendererStatus | 真實 loading / missing / error 提示可見；ready 時可能隱藏 |
| 3 | 更新圖磚 或 停止更新 | #refreshMapTiles | 依當前 DOM 核對 |

資料條件：weather_map_actual_failure_receipt, weather_map_actual_recovery_receipt。
缺項處置：保留實際資料缺項、disabled／錯誤與 receipt；正向教學仍待補，不能套用歷史畫面或列為通過。

## 真實四日原文

D1：中平林道18K - 沛源石礦岔路 - 石礦鞍部 - 森林鞍西北側迷你鞍C1
(273689/2589087)
D2：C1 - 崩坡絕壁 - 三岔峰營地 - 玉里山 - 清八岔 - 單攻往阿桑來戛探一小段 - H1648營C2
D3：C2 - 巨石獵營 - 1148鞍 - 單攻異祿閣 - 1148鞍旁平地C3
D4：C3 - 腰繞至Nas-maya - 卓溪山岔 - 卓溪山 - 卓溪山產道

## 尚未完成

- 實際 Chrome 38頁重拍、各步驟 DOM 標記、逐頁目視驗證
- Saved Planned 的真實版本／來源與審查、補件、作業、報告／下載證據
- 四日完整主線與支線仍須對齊來源；未定位、未給日期腳程與停留不得杜撰
- 真實探索 AOI／A-B／準備 receipt 與真實 Recorded GPX／版本／作業資料
- Main／Weather 及所有受影響圖面的正式 Diagnostic 與失敗恢復證據
- 完成全部適用驗收後，重建 HTML/PDF 並驗證所交付來源與截圖同版；目前不發布
