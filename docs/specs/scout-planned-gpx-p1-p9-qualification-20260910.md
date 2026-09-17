# 人工行程 → Planned GPX：P1–P9 驗證紀錄

日期：2026-09-10（Asia/Taipei）。狀態：**SCOPED PASS / WORKING PROTOTYPE**。
依據：[交付計畫 §4–§5](scout-golden-planned-gpx-delivery-plan.md)。

本次驗證的是情境二的規劃候選能力。GPX、時間計畫、版本審查與六力分析主體
必須同版；審查不代表路線可通行、出發許可或現場安全判定。P1–P9 在下列指定
案例與證據範圍通過；不是產品化、任意自然語言理解或所有六力 producer 重算完成。

## 實作範圍

- `scout_planned_route_models.py`、`scout_planned_route.py`：文字與人工表單編成
  typed operations，使用完整來源點序列組合支線、往返、反向、替代及裁切；
  產生獨立 route axis、CP、segments、GPX、分日時間與來源差異。
- `scout_planned_route_sources.py`：Overpass 真實 node graph 尋徑、Rudy 經審查
  的向量描繪，以及綁定 A/B、DEM、原文、人工錨點與 review 的 R1–R4 adapter。
- `scout_planned_route_artifacts.py`、`scout_planned_route_api.py`：preview 無寫入；
  immutable bundle、父版本衝突、冪等保存、審查、分析選擇及成套匯出。
- `scout_analysis_subject.py` 與 Dashboard：共同選擇 Golden／Planned；Planned
  的幾何與時間可見，尚未重算的舊報告明示為 Golden 歷史內容。
- GPX 重匯入保留 planned 來源性質，不將計畫時間當作 Recorded 觀測。

## 實際使用與真實入口

在已準備的 workspace 進入 **Permission → Human Design → Human Design → Planned
GPX**，填人工行程、啟程與腳程，用來源選段表單補足支線／替代／裁切位置，按
「預覽 Planned 幾何與節奏」。核對地圖、時間與限制後 Save；審查保存版本，再選
「以此 Planned 分析六力」，或匯出 GPX／Manifest／完整 Bundle。詳細句型、欄位與
API 見[操作方式](scout-golden-planned-gpx-delivery-plan.md#44-dashboard-操作方式)。

正式 workspace launcher 啟動 `http://127.0.0.1:9100/admin/dashboard`，使用既有
QGIS Worker；原 Dashboard 9099 保留。測試專案為
`golden_g1_chilai_repeat8_20260909_r14`。來源 Golden 共 9,290 點，原始 SHA256：
`9ee8be86bd8d1f94b64311356042b68a6d29de8fd5ebbf353afd1e86e7461fab`。

最終測試 Dashboard PID 為 15424，QGIS Worker 為既有 9876。25 個來源共 133,799
點、2,034 個錨點；來源目錄與組合使用完整點序列。程式檔案及實際載入的 UI hash
見 [final-source-manifest.json](../../artifacts/planned-gpx-delivery-20260910/reports/final-source-manifest.json)。
瀏覽器最後停在原專案的 Planned 分析主體。

## P1／P2 的獨立計算與保存成果

P1 文字為「沿 Golden；在 CP 001 停留 40 分鐘」，啟程為
`2026-10-01T06:00:00+08:00`。原 GPX 在點 117 有約 1,179 m 的記錄缺口；
規劃版保留缺口及未知 ETA。相同來源點順序與相同缺口分段規則用於兩版的幾何
比較，不能把補直線當成幾何一致，也不能因原記錄缺口而捏造到達時間。

P2 選擇 Ref. `reference_004…20111127-29…` 第 4 個 `trkseg`，從 CP 032 附近
來源索引 463 到「南華山」索引 222，再依相反順序返回。獨立來源計算在操作前
記錄：單程 242 點、2,549.123 m、上升 348.712 m、下降 40.373 m；往返增加
5,098.247 m。以明示的 2 km/h 固定腳程且假設全程連續移動，初估為 152.947 分鐘。
來源接點相距約 18.63 m；接續容差保留在回執中，不生成連接直線。

該操作前預期保留未改。實作使用平均地球半徑 6,371,008.8 m，並將正向來源中
低於 0.3 km/h 的靜止區間另列；獨立重算得到往返 5,098.253879 m，與產物四捨五入
一致。去程移動 76.473810 分鐘，回程移動 75.200256 分鐘，回程來源停留 36.816667
分鐘。最初 7 mm 距離差來自半徑假設；時間差來自來源停留分列，沒有改答案來湊通過。

| 項目 | P1：只加固定停留 | P2：另加南華山支線往返 |
|---|---|---|
| 保存版本 | `plan.02858b028b677211295b0747` | `plan.0a660d68411af4df633339d2`，父版本為 P1 |
| 幾何 | 原 9,290 點順序完全相同 | 新軸 9,775 點、10 CP、5 segments，支線去回各 242 點 |
| 距離比較 | 幾何未變、增加 0 m | 增加 5,098.253 m，總長 19,984.559 m |
| 行程 | 06:00 啟程，另加固定停留 40 分鐘 | 同一啟程與固定停留；移動 593.038 分、來源停留 140.683 分 |
| 未知與準備 | 原記錄缺口保留，最終 ETA 未知 | 同一缺口保留；新增兩個支線段需 map／DEM coverage 驗證 |
| 審查／恢復 | 伺服器重啟、reload 後找回同版；3 項限制有回執 | 4 項限制有回執；A→B→A 後版本、hash、審查與來源仍一致 |

比較兩版幾何時使用相同的缺口分段規則，Golden 長度為 14,886.306 m。舊 Golden
歷史畫面約 16.1 km 的累計包含原記錄的大跨度接點；本次沒有改寫原檔，也沒有把
該缺口補成可行走直線。P1 的幾何相同由完整來源座標逐點核對，非僅比較顯示里程。

[操作前預期](../../artifacts/planned-gpx-delivery-20260910/reports/p2-independent-expectation.json)、
[12 項獨立幾何／時間核對](../../artifacts/planned-gpx-delivery-20260910/reports/p1-p2-independent-verification.json)。

## P1–P9 驗收結果

| ID | 結果與證據類型 | 實際觀察與範圍 |
|---|---|---|
| P1 | PASS · 真實 Dashboard＋逐點核對 | 文字停留改變日程，Golden 原點序列與檔案 hash 保留；preview、Save、重啟、Restore、review 均完成。 |
| P2 | PASS · 真實 Dashboard＋獨立來源計算 | Ref. 第 4 個 trkseg 的 463→222→463 去回順序、長度、高差與時間核對通過；保存為獨立 P2 版本。 |
| P3 | PASS · 3 個組合 fixture | 多 Ref.、反向、交叉、重訪及跨 trkseg 缺口依來源序列組合，不以座標接近誤接或補直線。 |
| P4 | PASS · 真實 Overpass＋10 個組合 fixture | 公開查詢取得 2 份山徑來源、261 點候選路徑；真實 OSM node graph 依序途經與合法返程。Rudy 使用附地圖 hash 與人工 review 的向量 fixture；單有 raster 不生成路段。 |
| P5 | PASS · 真實 R1–R3 來源讀取＋10 個組合 fixture | Dashboard 讀取既有 R1–R3；隔離資料跑完整 R4 原文→人工錨點→review→adapter→compiler。A/B、DEM、原文或 review 變更會使舊來源／保存請求失效。 |
| P6 | PASS · 5 個時間 fixture | 營地離營、跨午夜、來源停留與新增停留分列；最晚到達用休息前時間核對。無法滿足條件明示 conflict，未知不填 ETA。 |
| P7 | PASS · 真實 Dashboard＋API／故障／實際 importer | Save、重啟與 reload、比較 P1、A→B→A、三種匯出均完成；隔離測試覆蓋舊 preview、競態、冪等、中斷、hash 及專案隔離。真實 local importer 重匯入維持 Planned 角色。 |
| P8 | PASS · 真實六個頁面＋共同分析回應 | 六頁同一 P2 幾何／日程與 10 CP／5 segments；Permission、Pace 為本版日程，其他 producer 明示待重算或追加準備。 |
| P9 | PASS · 原 Golden 核心回歸 | 原 G1／G2 Generate、Save、既有 Accept 恢復、reload、Restore 保留原版本與歷史日程；沒有重跑完整 New Import／preparation 或新增 Rebuild。 |

P3–P6 的案例與真實來源範圍見
[gate receipt](../../artifacts/planned-gpx-delivery-20260910/reports/p3-p6-verification.json)。
P7 見[UI 生命週期](../../artifacts/planned-gpx-delivery-20260910/reports/p7-ui-lifecycle-verification.json)、
[匯出位元組核對](../../artifacts/planned-gpx-delivery-20260910/reports/p7-ui-export-verification.json)、
[重匯入驗證](../../artifacts/planned-gpx-reimport-20260910/qualification-result.json)。
P8 見[六頁核對](../../artifacts/planned-gpx-delivery-20260910/reports/p8-six-surface-verification.json)；
P9 見[Golden 核心核對](../../artifacts/planned-gpx-delivery-20260910/reports/p9-golden-core-verification.json)。

### 匯出與重新選擇的證據

三個實際按鈕均取得 HTTP 200；觀測到的原始回應位元組已另存為可取用證據：

- [Planned GPX](../../artifacts/planned-gpx-delivery-20260910/exports/plan.0a660d68411af4df633339d2.planned.gpx)：719,913 bytes。
- [行程 Manifest](../../artifacts/planned-gpx-delivery-20260910/exports/plan.0a660d68411af4df633339d2.manifest.json)：8,636 bytes。
- [完整 Bundle](../../artifacts/planned-gpx-delivery-20260910/exports/plan.0a660d68411af4df633339d2.planned-bundle.zip)：1,033,026 bytes、10 檔。

畫面 SHA256、HTTP 回應、保存版本及 ZIP 內所有檔案逐一相符。GPX 預設沒有
`<time>`，日程及候選 metadata 留在同版 bundle。Codex 內建瀏覽器沒有原生下載
落盤回執，因此不宣稱已寫入使用者 Downloads；UI 明確顯示「產物已準備，尚未確認
寫入使用者磁碟」。此驗證證明按鈕實際取回正確檔案，另存檔案也可直接取得。

P2 manifest identity 為
`fd1e71ba8f297dbc26346061cc1cf19f84ffb7fc74cea7c25dfdbd424c9457aa`；
幾何為 `69809fa61d5557574c594ecb0b64f1493374699db1905e3d2c9b151fbb328511`，
日程為 `383e29d91d472a5862098da2a0e0ff9de3a4f9deb79a582459a221110b7ed911`。
重新選擇 P2 會新增 selection receipt，因此共同 analysis revision 從 `69ead17a…`
變為 `f1ce0a23…`；上述 immutable plan hashes 不變。Manifest identity hash 與整個
manifest 檔案的 byte hash 是不同欄位，兩者均保留，不能混用。

### Golden 回歸的恢復範圍

G1 原版本 `version.a8223d6fdbaafd30` 保留單日、35／35 CP、08:40:19–16:47:41；
G2 原版本 `version.3403007055fe5cd2` 保留 9 日、218／219 CP、32 來源停留與
8 個過夜間隔，缺失時刻仍未知。兩者重送 Save 回到原版本。

對已接受的原版本再次 Accept，實際回應均為 HTTP 409
`baseline_activation_write_in_doubt`；Dashboard 讀回驗證原 review 後顯示
`Saved review recovered and verified`。後續分析主體及 Restore 仍對應原版本。
這是既有 accepted review 的恢復通過，不能寫成首次 Accept 或新的 Rebuild 成功；
原始 409 回應也保留。完整首次採用／Rebuild 的歷史證據仍見
[Golden G1–G6 報告](scout-golden-gpx-g1-g6-qualification-20260909.md)。

## 開發期間發現與修復

1. 保存清單序列化排序使來源 ref 清單比較不一致；以固定排序綁定同一來源集合。
2. 明確指定支線目的地時，原編譯器未核對選段折返點；現在會阻擋不符目的地的段。
3. 同位置的最晚到達限制曾使用休息後時間；改以實際到達時間核對，與表單加入順序無關。
4. 人工離營後可能再次計入來源原有過夜停留；明確離營取代該原位置的來源停留窗口。
5. 第一個真實 P1 預覽 POST 回傳 200，但 DOM 擷取逾時。該次保存動作未執行，
   不算通過。Network header 與 loading-finished 仍保留；回應 body 後續已無法取得，
   截圖／DOM 未生成，不補寫成功證據。改為分頁及移動摘要，保留完整原始時間軸；
   修復後 P1／P2 真實預覽、保存及操作鏈通過。
6. 山徑返程不能直接反轉單向路；改查合法返程並核對真正折返點，原始 OSM 的
   access／foot 限制不能被重新標記的向量資料移除。
7. 重匯入時從 GPX XML provenance 辨識 Planned；預估時間進入 `planned_at`，
   不進入 `observed_at`，歷史 timing／daily departure producers 也排除該來源。
8. 最初下載連結在內建瀏覽器沒有產生請求，也不能呈現 HTTP 衝突。改為按鈕先
   取得並驗證檔案、回應角色、大小及 hash，再觸發下載；HTTP 409／錯誤 header
   會明示失敗。修復後三種匯出均有完整實際回應與內容核對。

## 檢查、資源與後續工作

- 最終 [focused JUnit](../../artifacts/planned-gpx-delivery-20260910/tests/final-focused.xml)：
  **91 passed**，涵蓋 compiler、sources、artifacts/API、共同分析與 Planned UI。
  真實 importer／歷史時間隔離另有 **53 passed**。早期測試與 `pnpm test` 有重疊，
  不累加成獨立案例總數。
- `pnpm lint`、`pnpm typecheck`、`pnpm test` 通過；其中 typecheck 為專案既有
  scaffold import check，不能解讀為完整靜態型別檢查。最新 Planned JS syntax check 通過。
- [Layer contract](../../artifacts/planned-gpx-delivery-20260910/reports/layer-contract.json)：
  33 層、0 warnings。這不代表新支線已有完整 DEM／天候資料。
- [Navigation guard](../../artifacts/planned-gpx-delivery-20260910/reports/final-navigation-freeze.json)：
  `NAVIGATION_FREEZE_SUSPENDED`、report-only、34 個相對原 freeze baseline 的既有／本次
  差異；未更新 baseline，未把報告當作授權。
- 25 份完整來源的 catalog／compile／Save 約需 50–60 秒；頁面有操作狀態且不以
  短 timeout 重送。真實 Overpass 取源約 23.8 秒。大型資料效率是後續改善項，
  這次保留完整來源與原始逐點記錄。

仍需後續完成：通用自然語言日次／日期推論、Rudy raster 自動描繪、Planned 新範圍
自動準備，以及 Architecture／Navigation／Weather／Route Context 的完整 producer
重算。當前六力頁面已有新路線與版本，但後四項明示 `needs_reanalysis`／
`coverage_needed`。這符合 P8 的版本一致或具體待重算判準，不宣稱六力都已有新分析。

原始資料缺口使此 P2 最終 ETA 仍未知；不得將其當成已驗證可行走行程。測試中的
review 只確認軟體呈現的來源、幾何、時間及限制，不替使用者核准登山。

本次未執行 repository 全覆蓋、產品化壓力測試、原生下載落盤驗證、Planned 的
connected map／DEM／weather 全準備或實地通行驗證。P7 保留兩個舊 corpus 計數測試
的既有不符（6,909／2,612 點、23／24 Ref.）與早期 fixture 設定失敗；未放寬期待值
或宣稱完整 legacy corpus suite 通過。修復後通過的 focused receipts 分開保留。

原始證據位於 `artifacts/planned-gpx-delivery-20260910/`，含操作 ledger、DOM、截圖、
Network bodies、來源 hashes、獨立預期、匯出與 JUnit。原失敗證據保留；不以事後
文件補造未觀測的畫面或回應。

Scout 已封存 **841 檔、139,828,626 bytes（133.35 MiB）**，位於：

```text
/home/alexwang0315/work/scout-planned-gpx-qualification/20260910/sealed-snapshot-20260909T181139Z-cb26403f
```

包含四組驗證 artifact roots 及原 workspace 的整個 `reviews/planned_routes`，
保留版本、審查、分析選擇與選擇歷史。Receiver 與另一條 SSH 各自讀回 841／841
檔案，SHA／mode／mtime 全部一致；463 個目錄與完整 inventory 亦一致，無缺檔
或額外路徑。Manifest SHA256 為
`dbec014226b053a6594be0f01e95cc5f5299739cf6990b596ba6cbfebbc84b27`。
53 個測試 symlink 與 `.write.lock` 明確排除；沒有刪除 Mac 原檔或宣稱回收空間。

[封存回執](../../artifacts/planned-gpx-storage-20260910/sealed-snapshot-20260909T181139Z-cb26403f/final-archive-receipt.json)、
[獨立讀回](../../artifacts/planned-gpx-storage-20260910/sealed-snapshot-20260909T181139Z-cb26403f/independent-readback.json)。
封存的 `final-qualification.json` 記錄驗收完成、尚待封存／Git 提交的當時狀態；
後續封存結果以上述獨立回執為準，不回寫或改動已封存證據。
