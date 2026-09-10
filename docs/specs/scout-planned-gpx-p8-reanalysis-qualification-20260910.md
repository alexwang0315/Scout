# Planned P8 追加準備與六力重算驗收

狀態：**SCOPED PASS / WORKING PROTOTYPE**。真實 P2 追加準備、六力實算、
同作業 Resume 重現、完整頁面重載及六頁版本／產物綁定驗收通過。
六力均保留實際缺資料的 `partial`；不代表完整資料、出發許可或產品化。

本輪延續 `scout-golden-planned-gpx-delivery-plan` 第二項。原 P8 證明六頁
識別同一 Planned 版本並明示尚未重算；本輪要證明版本專屬地圖／DEM
準備及六個確定性評估器實際執行，並讓使用者看到新結果與具體資料缺口。
這是 Construction Mode 能力驗證，沒有進行產品化升格。

## 真實資料與執行位置

- 來源專案：`golden_g1_chilai_repeat8_20260909_r14`。
- Scout 工作區：`/home/alexwang0315/workspace/golden_g1_chilai_repeat8_20260909_r14`。
- Planned：`plan.0a660d68411af4df633339d2`。
- Manifest：`fd1e71ba8f297dbc26346061cc1cf19f84ffb7fc74cea7c25dfdbd424c9457aa`。
- Canonical 軸：9,775 點、10 CP、5 geometry parts。點 117 前保留
  1,179.089 m 的原始缺口，不補路線或未知時間。
- 專用工具與證據根：`/home/alexwang0315/work/scout-planned-p8-reanalysis-20260910`。
- 大型準備、測試暫存、GIS 與分析產物在 Scout 生成；Mac 不建立完整
  工作區副本或壓縮包，不刪除使用者檔案。

起跑盤點已在 Scout 驗證 32／32 Planned source hashes、25／25 inbox
GPX、保存版九項 payload、preview、review、selection。這僅是來源驗證，
不是 P8 重算通過證據。

## 本輪通過條件

| 項目 | 必須觀測的結果 | 目前 |
|---|---|---|
| P8-A 作業生命週期 | Dashboard 提交版本/hash，持久 run 回報進度；同 key 不重複；中斷可明確恢復 | PASS：真實 POST 202、服務重啟、Resume attempt 2、執行中完整 Document reload；中斷／冪等 fixture 通過 |
| P8-B 新地圖／DEM | 五個分段保留完整點序；真正 QGIS/GRASS 原生地形產物與 DEM 點取樣覆蓋 Planned；所有缺口保留 | PASS：5/5 processing/render completed，9,775/9,775 原生取樣 |
| P8-C 六力實算 | 六力都執行對應評估器；Ref/Golden 歷史通過時間重匹配，新 CP 邊／ETA／DEM／脈絡投影可追溯 | PASS：六個 producer 實算，六個 partial，無 blocked |
| P8-D 同版呈現 | 六頁都綁同 run、version、manifest、geometry、itinerary；舊 Golden 內容保持明示歷史 | PASS：六頁真實畫面／DOM／API artifact SHA 一致；舊 Golden 區收合並標歷史 |
| P8-E 不足與過期 | 缺預報時空範圍、個人體能、安全餘裕等必須保留原因；來源或產物變更不可冒充 current | PASS：真實六力缺口可見；來源／產物／producer 過期與 race 由 focused fixtures 驗證 |
| P8-F 原資料與儲存 | 原 Golden、accepted baseline、Planned bundle bytes 不變；重產物確實在 Scout | PASS：原 774 檔全部不變；259 outputs／40 owner sources／28 RAW sources 驗證成功 |

允許明示 `partial`／待重算，但必須是實際執行後的具體缺資料或已記錄
失敗。不能用固定「尚未實作／尚未匹配」代替已有來源可完成的計算，
也不能將候選 review 當作已接受 MissionGraph 或出發許可。

## 實作契約

- `scout_planned_preparation.py`：immutable 四件組的精確副本、分段對映、
  新 Planned corridor 的地圖證據與逐 part QGIS/GRASS 準備。
- `scout_planned_analysis_inputs.py`：由 canonical CP 與軸建立分析用
  CP-edge graph／ETA；不跨 geometry break，不改保存版。
- `scout_planned_analysis_evidence.py`：實際 Ref/Golden 歷史通過時間匹配，
  原生 DEM 樣本對回每個 Planned 訪次與 CP 邊。
- `scout_planned_analysis_producers.py`：六力評估器與可追溯的完整結果。
- `scout_planned_analysis.py`：持久 state、OS lease、獨立 attempts、
  source/producer/output hashes 與明確 Resume。
- `scout_planned_analysis_remote.py`：可設定的 SSH／串流 snapshot adapter；
  只複製明示分析來源與指定保存版，排除 UI selection、cache 與其他版本。
- `/planned-route/analysis-runs`：GET 只讀；POST 202 啟動。指定 run 的
  GET／Resume／artifact 只接受已綁定的版本與列記產物。
- 六頁共用 `analysis_subject.planned_analysis`。新分析不會自動取代
  Golden，也不會產生 Recorded GPX 或 runtime safety truth。

## 已觀測驗證

- Scout 首次 integration 因測試暫存父目錄未建立而在 setup 失敗，
  已保留結果，修正測試啟動程序。
- Scout 第二輪：45 passed，含真正 GDAL GeoTIFF 原生點取樣，無 skip。
- Scout 整合回歸：102 passed，無 skip，22.05 s。保存於
  `reports/full-focused-before-live.xml`；之後新增精簡回應仍需綁完整 artifact
  中 owner 來源的兩種 race／stale 回歸，作業測試 12 passed。
- 最終來源可攜與來源綁定修復後，Scout 整合回歸 **119 passed**，
  無 skip，23.95 s；`reports/final-focused.xml`。
- 後續來源清單與共享鎖修正：Mac focused 16 passed。
- Dashboard focused 18 passed；`pnpm lint`、`pnpm typecheck`、
  `pnpm test`（27 tests）通過。
- 地圖契約 verifier：33 layers 通過。Navigation guard 保持 suspended／
  report-only；未修改 baseline。
- 專用 GIS 容器的 synthetic workflow 曾遇到小裁切窗不夠 coarse
  geomorphon 及視窗尺寸不夠 render gate，保留失敗回執。只調整輸入
  覆蓋／專用 QGIS 視窗，不縮減演算法或驗收門檻。
- Synthetic v4 已完成原生 QGIS／GRASS 與 map rendering：
  `qgis-worker-20260909T235006467353Z-6f76ce9423`，2026-09-09 23:50:34Z
  完成，回執 `receipts/synthetic-smoke-v4.json`。這是環境前置驗證，
  尚未代替真實 P2 五分段與 Dashboard 通過證據。

## 真實 P2 第一次執行

- Run：`analysis.51645da345e5e32184ae12c472aada79`，attempt 1。
- 2026-09-10 00:00:33Z 完成：`completed_with_gaps`；準備階段
  `completed`，六力階段 `completed_with_gaps`，無 producer exception。
- Report file SHA：`e3070cd47c7ec2cc29321ed7165125bf1782252499937c48405beee5234e7326`。
- Run 根：`/home/alexwang0315/workspace/golden_g1_chilai_repeat8_20260909_r14/outputs/planned_analysis/runs/analysis.51645da345e5e32184ae12c472aada79/`。
- 獨立驗證回執：工具根的 `reports/p2-first-real-audit.json`，SHA
  `b9900cdc824852ac4406ecd13718691cc941b4304698506ba65b8279e96a5d02`。

地圖 bbox 取到 63 項來源，按 Planned 各分段 500 m corridor 保留 52 項；
沒有改變 Planned 幾何。五個 QGIS／GRASS workflow 全部 processing、render
completed；9,775 點的原生 20 m DEM 覆蓋已驗證，四個來源 join 均保留。
其中三個為非零幾何缺口，另一個是同座標折返訪次。地形覆蓋不代表可通行或安全。
直接讀取舊 Golden DEM（392×115 cells）確認 **322 個 Planned 點超出其範圍**；
新準備的 verified 點集合已覆蓋這 322 點。證據是工具根
`reports/p2-outside-prior-dem-verified.json`，SHA
`7b285065f680f629c231cdcb864fd31f30db6b29829f11e64136b037b948d4d1`。

| 六力 | 實際新結果 | 保留的必要缺口 |
|---|---|---|
| Permission | 評估新計畫的 40 分鐘停留，移動時間未挪作 safety buffer | 剩餘安全餘裕、天候／日照／撤退審查 |
| Pace Fit | 評估 5 條非零 CP 邊與完整 Planned 日程 | 個人／隊伍能力、未知路段耗時 |
| Architecture | 10 CP、6 CP 邊；25 個歷史來源中實際匹配 3/5 非零邊，2 邊未匹配 | 幾何缺口、路段政策證據、2 邊歷史樣本 |
| Navigation | 9,775/9,775 DEM 點、逐邊高差與縱坡，以及新路線地圖需求 | 裝置離線圖／GPX、定位備援及人工能力確認等 8 項 |
| Weather | 實際按新位置與完整 ETA 檢查預報；0 段匹配 | 10 月 1 日有效預報、未知 ETA、日照與地形天候作用；歷史天候仍未知 |
| Route Context | 重新收集並投影 94 個有來源的脈絡點 | 新敘事 briefing 的審查 |

六力的 `partial` 均有完整 assessor artifact 與逐項原因，沒有直接套用
舊 Golden 報告。既有 assessor 的現場式 `field_answer` 保存在原產物，
Planned 預設頁面顯示計畫摘要、評估結果與待補資料，不直接顯示現場行進指令。

首次原生 Dashboard 的 catalog 因保存報告內的 Mac 絕對 GPX 路徑回 409。
新增局部可攜解析：只接受相同 project ID 的 `normalized/routes/filtered/`
檔案且須有正確 SHA；任意外部路徑、跨專案、缺 SHA、錯 SHA 均拒絕。
30 個 catalog／編譯 focused tests 通過，原報告及 bundle 不改寫。

瀏覽器最初 Restore 恰逢本任務服務重載，留下 connection reset；再次從
相同控制項操作成功。之後 POST、進度與 terminal 顯示都已觀測，
沒有把初次 connection reset 隱藏成第一次全程成功。

初次同 URL 的 browser goto 沒有 Document request，不能算完整 reload；
已從網路回執撤回該判定。服務重啟後使用新的 query 實際載入 Document、
JS 與 API，找回同一 completed run／report。接著以實際 Resume 驗證執行中重載。

完整 catalog GET 已 200，25 個 GPX、2,034 錨點；觀測耗時 102.72 s，
先前 45 s client timeout 保留。既有 map-candidate loader 仍拒絕 hash
不符的舊 Overpass 來源，Rudy／TRH 未就緒；這些既有候選未被偽造為可用。
本 P8 的 52 項新 corridor 地圖來源另由版本專屬 prepare 真實取得。

本次未執行全站產品化、所有地圖圖層 browser gate、外部發布或硬體測試；
沒有將原 G1–G6 的既有通過範圍冒充本輪重新全測。

## 同作業 Resume 重現

真實 UI 的 Resume POST 202 產生相同 run 的 attempt 2，並未另建 run。
執行中以不同 query 載入完整 Document、JS 與 API，看到相同 P2／run／
attempt 2／terrain 進度；此時前次 projection 沒有被顯示為 current。
第二次於 2026-09-10 00:17:30Z 完成，仍為 `completed_with_gaps`。

- 第二份 report SHA：`3900df64666a975a6b6712fab7032f302d1d31588eaaec4ddda9ba5c8fd52107`。
- 兩次各 5/5 地形 processing/render 完成；各 9,775/9,775 DEM 點。
- 六力的 status、summary、missing_inputs 均一致。
- 第一次 259 個 output hashes 全部保持不變，第二次 259 個產物全部驗證；
  40 個 owner sources、28 個 RAW sources 及原 774 檔未變。
- 作業兩次共 523 檔、203,586,798 bytes（約 194.2 MiB），全部在 Scout。
- 最終重現回執：工具根 `reports/p2-repeat-final-audit.json`，SHA
  `55d6066999511b2e4741d4320c5407d7c134498f9c8d24eee2be8be3817b5cb9`。

Browser receipts `24-resume-same-run-attempt2`、
`27-true-document-reload-running-attempt2` 與
`28-running-attempt2-restored-with-progress` 分別保存操作、Document/API
與可見進度。初次同址 goto 的無 Document 情況保留，未納入此通過證據。

## 最終六頁與操作證據

Browser 目錄：`browser-live-2026-09-09T23-51-22-688Z`。每頁均有 screenshot、
完整 DOM、網路事件與可見欄位 observation；`46-six-page-final.json` 對六頁
的 run、版本、manifest、geometry、itinerary、attempt 2 artifact ref／SHA
逐項比對實際收到的 `/analysis-subject` HTTP 回應，結果六頁全 PASS。
實際操作只有一個 Start POST 與一個 Resume POST，兩者均 202。

| 頁面 | 最終證據前綴 |
|---|---|
| Permission | `31-final2-permission` |
| Pace Fit | `33-final2-pace-fit` |
| Architecture | `35-final2-architecture` |
| Navigation | `37-final2-navigation` |
| Weather | `39-final2-weather` |
| Route Context | `41-final2-route-context` |

`43-final2-metadata-summary` 與 `45-final2-full-receipt-read` 證明列表摘要
明示「結果尚未讀取」，按 Read 才顯示完整六力；沒有把摘要缺欄位當成重算未完成。
六頁 screenshot 均實際檢視。修復深色主題中淺色表頭／限制區／分頁的文字
對比，並移除預設表格的現場式 `field_answer`；原始內容仍保留在完整產物。
最終實際下載 JS SHA：`6b80b5fd45f3063996fdf6ccf7b08bafdd529acb3658a1ea36becad99de301ec`。

最終 Python 整合 119 passed；最後三個 UI 回歸檢查通過，包含 4.5:1 對比、
摘要到明確 Read、六力綁定與現場文字隔離。前輪 Dashboard 18 tests、
`pnpm lint/typecheck/test` 亦通過。Layer contract 33 layers PASS；
Navigation guard report-only、131 paths、34 個既有 drift、errors=[]，
baseline 未修改。Ruff 未安裝也未設定，未另行安裝。

## Scout 儲存與交付

- 目前本機 tunnel 入口：
  `http://127.0.0.1:19100/admin/dashboard?projectId=golden_g1_chilai_repeat8_20260909_r14#outdoor-permission`。
  這是本輪專用測試服務，沒有安裝常駐自動啟動或發布到正式環境。
- GIS／測試／RAW mapping／驗證回執：
  `/home/alexwang0315/work/scout-planned-p8-reanalysis-20260910/`。
- 完整瀏覽器及環境證據封存：上述目錄的 `evidence/local-receipts/`。
  共 250 檔、96,314,914 bytes；獨立 SSH 讀回全部 SHA／bytes 相同。
  Archive manifest SHA：
  `286942135898782ccabef07e2e4169d5f94ca9ae7e4c33f45c0e17abcc9448f4`。
- 重產物都在 Scout。Mac 僅保留程式與瀏覽器／環境驗收副本，沒有重建
  原 workspace、複製 DEM 資料集或建立大型壓縮包，也沒有刪除使用者資料。
- 仍需後續處理：個人／隊伍與許可審查資料、未知路段／ETA、有效預報、
  敘事 briefing，以及既有 catalog 的 stale map candidates 與載入耗時。
  任意自然語言多日推論、無人工錨點的日誌轉 R4、正式部署及全面產品化
  仍維持原能力邊界。

本文件與實作由同一個 Scout commit gateway snapshot 交付；提交識別記錄
於本輪最終回覆及工具根的交付回執，未推送 GitHub。
