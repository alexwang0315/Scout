# 依循 Golden：修復與 G1–G6 重驗（2026-09-09）

狀態：**NOT QUALIFIED；不得宣稱「依循 Golden 可用」**。
本文件記錄使用者指定的準備流程、作業恢復與 Permission 初始化修復，及其真實
Dashboard 重驗。驗收依據維持 [delivery plan §3.2](scout-golden-planned-gpx-delivery-plan.md#32-驗收矩陣)。
[2026-09-08 首輪失敗紀錄](scout-golden-gpx-g1-g6-qualification-20260908.md)保留不改判。

> r9 已恢復 QGIS worker 與 Dashboard 瀏覽器，完成真實 MCP 整理器、來源綁定及
> 六頁共同分析版次修復。新的完整 UI 驗收仍在執行；不可把下列試算或隔離 PASS
> 當成 G1–G6 全數通過。

## r9 整合與重驗進度

2026-09-09 14:13（Asia/Taipei）：以真實原始 GPX、OSM 與已取得公開文件試算，
G1 有 32 份合格來源、7 個 MCP（5 個有 CP 支持、2 個保留建議插入）；G2 有
14 份合格來源、47 個 MCP，均有 CP 支持。兩案 compiler gaps 為空。
這是來源與合成能力的證據，尚未包含新 workspace 的完整 preparation／Permission 操作。

- MCP producer／原有 synthesis：32 項測試通過；[來源與完整試算回執](../../artifacts/golden-gpx-repair-20260909/reports/r9-mcp-evidence-collection.md)。
- 新原始文件、package、取得回執變更，以及 Clone／真實 import 入口：6 項測試通過；[結果](../../artifacts/golden-gpx-repair-20260909/tests/run-20260909T055947869884Z/results.json)。
- MCP 先於下游分析發布、projection hash、derived 變化不冒充 raw input drift：2 項整合測試通過；[結果](../../artifacts/golden-gpx-repair-20260909/tests/run-20260909T060155639924Z/results.json)。
- QGIS 等待預設不再取消持續執行的工作，顯式故障注入 deadline 保留：11 項測試通過；[結果](../../artifacts/golden-gpx-repair-20260909/tests/run-20260909T054911390811Z/results.json)。
- analysis subject、ETA 原回執、來源漂移：9 項 API／來源案例通過。Dashboard 保存、逾時恢復與六頁失效：48 項 VM 案例通過；[實作及各輪測試](../../artifacts/golden-gpx-repair-20260909/reports/g6-six-axis-implementation.json)。
- `pnpm lint`、`pnpm typecheck`、`pnpm test`（27 項）通過，使用 env／network 隔離；[執行回執](../../artifacts/golden-gpx-repair-20260909/tests/r9-pnpm/results.json)。最後的 recovery 分支變更另由同 HTML hash 的 48 項 VM 與 syntax 驗證。
- repo layer-contract verifier：33 層契約通過；[結果](../../artifacts/golden-gpx-repair-20260909/tests/r9-repo-layer-contract.json)。真實新 workspace 的圖層結果仍須在準備完成後驗證。

新測試 ID 為 `golden_g1_chilai_20260909_r9`、`golden_g2_dongqing_20260909_r9`；
G1 Clone 由新 G1 的原始素材重建。新 material root 僅放原始公開文件及來源宣告，
沒有複製 MCP／terrain／Permission 等衍生輸出。[素材宣告](../../artifacts/golden-gpx-repair-20260909/sources/r9-materials/input-selection.json)。
完整成功次數仍為 **0**，相同版本三次核心重跑尚未開始。

Mac 無 `.git` 是目前指定的正常架構，使用 Scout Commit Gateway 留下可追蹤版本；
不再將缺少本機 `.git` 當作修復或驗收 blocker。

## r8 G1–G6 checkpoint（歷史紀錄）

截至 r8，完整瀏覽器重驗受到連線中斷阻擋；以下區分已執行的測試、既有實際操作
與尚未滿足的前置條件。**這不是六項重驗全部完成的宣告。**

| 門檻 | 目前判定 | 本輪可用證據與剩餘條件 |
|---|---|---|
| G1 單日 New Import／Clone | 未通過 | 兩條真實入口均完成 import／Permission initialization，來源與 35 CP clocks 全符；preparation 仍為 `completed_with_gaps`，MCP 缺 producer。新的完整六力操作鏈未完成。 |
| G2 九日 Golden | 未通過 | attempt 3 終止為 `completed_with_gaps`，沿用 import.1，Permission initialization 完成且未接受。準備後來源 oracle 與唯讀重建通過，保留 9 天、32 段推估停留、8 個過夜間隔、10 段未知時間；QGIS 未執行、舊版 402 張 OCR 全逾時、MCP 缺 producer，九日 Permission UI 鏈未完成。 |
| G3 異常時間／方向綁定／來源 | 隔離案例 PASS | r7 的六個 G3 fault cases 通過：缺時間、不單調、CP 對 Golden 的反向綁定、CP timestamp／axis mismatch、cached schedule source mismatch。失敗保持具體原因、沒有候選寫入；不推論能判讀未表達的使用者行進意圖。 |
| G4 保存與跨 workspace 恢復 | 部分通過 | 真實 Save／reload／A→B→A Restore 已保留同一版本且未自動接受；source stale 已阻止 review。較早 QA 的 Accept／Rebuild 有保存回執，但新案在新版本的三段 reload 鏈尚未完成。 |
| G5 中斷／逾時／重試 | 部分通過 | r7 42 個 jobs/API tests 及故障案例通過；Resume 遇斷線仍在同一 job 終止，只有原本一份 import receipt，三階段回執 hash 全符。服務重載後 53 份作業／候選／Permission 檔案未變；瀏覽器雙擊與同版本重複核心流程仍需補證。 |
| G6 六力一致性 | 未通過；新案重驗受阻 | 已接受的較早 QA 案仍有 Pace fixture／Navigation 缺口；來源稽核亦發現共同 analysis revision、ETA 舊欄位／原 hash 綁定問題。新案尚未完成 Accept／Rebuild 前置條件，不能補造 post-Rebuild PASS。 |

一次完整成功與三次同版本核心流程均尚未成立，因此整體維持 **NOT QUALIFIED**。
接續需以 r8 新 attempt 重驗 QGIS／OCR、完成 MCP 真實證據 producer，並在瀏覽器
恢復後完成 G1／G2 的 Save → Accept → Rebuild／reload 與 G4／G6。跨六力分析版次
仍需修復與實證，才能取得「依循 Golden 可用」的結論。

## 修復內容與界線

1. Import 與 Clone 共用完整 preparation 設定，保存原始 GPX、DTM、CRS sidecar、PBF
   的來源與雜湊。空白材料欄位不再暗中套回不存在的 country path；Clone 不拿已裁切
   的 DEM 或衍生 PBF extract 冒充原始輸入。舊案以可回查的原始 coverage metadata 解析。
2. Dashboard 改由持久化 job 編排 import → preparation → Permission initialization。
   每階段有不可變回執、target lease、來源驗證與明確 Resume；同名同內容重送找回同一
   作業。GET 不啟動工作；中斷後沿用完成的 import checkpoint。未能證明 import 完成、
   來源改變或舊版沒有初始 PBF/CRS 綁定時，明示拒絕續跑，不補造歷史 hash。
3. 新案自動建立未接受的 Permission authoring seed、rules、model 與必要的 ETA 缺口
   產物；保留已存在的有效資料。初始化不是 Accept，也不授予出發或 runtime safety 權限。
4. Saved candidate catalog 與 Restore 以 project、version ref/hash 核對；reload 後可找回
   候選，不自動勾選 Quick review。Save/Accept/Rebuild 使用內容導出的穩定 idempotency key；
   長寫入不再被通用 20 秒 timer 中斷。寫入完成而後續讀取失敗、結果未知與取消等待分別顯示。
5. QGIS Processing 的特定 `buildvrt` 暫存 input-list 缺檔錯誤，改以已安裝的 native
   `gdalbuildvrt` 受限呼叫恢復；來源仍受 allowlist 控制，後續 clip/slope/GRASS 維持
   QGIS 路徑，回執明示 native processor/fallback。沒有偽裝成 Python DEM 或更動安全契約。
6. 最後的 QGIS/risk enrichments 完成後重算 layer aggregate 與 validation report，避免
   四個已完成 risk layers 仍沿用 early-stage 的 blocked 統計。MCP 的真實 missing source 保留。
7. 歷史 GPX 的 stationary interval 掃描先排除不可能達到既有停留門檻的區間，之後仍
   使用原本完整判定。單日與九日真實資料的完整重建輸出與原演算法 deep equality；
   沒有縮短資料、放寬門檻或略過來源驗證來降低 Permission 讀取時間。
8. preparation 更新來源後，舊候選維持 `stale`。修正 Quick review 原先「Accept 按鈕
   已停用，勾選後卻顯示 ready」的誤導狀態；不具 `review_ready=true` 的候選，其勾選
   控制與事件皆停用，來源過期說明不被覆蓋。
9. 重啟後的 job catalog 量測發現，五筆作業會重複驗證 16 次 request JSON，包含不必要
   的遞迴 model 轉換，花費 73.75 秒。r7 改為每筆狀態驗證一次、已解碼 JSON 直接
   canonical encoding，實測降至 9.02 秒；五份既有 request 的 canonical bytes 不變。
   GET 仍核對 request hash，Resume 仍在 lease 內驗證原始來源與 import checkpoint。
   [修復前 profile](../../artifacts/golden-gpx-repair-20260909/reports/r6-job-catalog-profile.txt)、
   [修復後 profile](../../artifacts/golden-gpx-repair-20260909/reports/r7-job-catalog-profile.txt)。
10. r8 OCR 修正：單張真實圖磚在同一 pytesseract runner 花費 22.35 秒，
    原預設 10 秒不足以容納本次運算。依 Construction Mode 改為預設等待完成；
    pytesseract 使用 `0`、CLI subprocess 使用 `None`，仍支援明確指定正數逾時，
    失敗與零文字結果照實保存。16 個 OCR／adapter 測試通過，未設定覆寫的真實單張
    runner 在 19.777 秒完成。r7 G2 使用舊程式至終止；r8 尚無完整 preparation 重跑
    證據，不能把舊作業或單張零文字結果改稱 OCR 成功。

實作與根因已回寫 [preparation runbook](scout-pretrip-full-preparation-runbook.md)。
本輪沒有 commit、push、PR、部署或原始 workspace 的 Save/Accept/Rebuild；測試寫入
限於獨立 QA targets。本輪重載自己的 Dashboard，並重啟本輪隔離 profile 的 QGIS
以恢復橋接；原始使用者的 QGIS profile 與 workspace 保留，重啟證據如下。

## 程式版本與案例

最後成功核對的 Git HEAD：`4ee2cfb416315461ecd2d19fb7b3213c48cb2e51`；目前 `.git`
已不存在，無法重新取得 HEAD／dirty diff。工作樹原有大量未提交修改，
本報告不把全部 dirty diff 歸為本次修復。每輪另保存所執行來源檔的 SHA 與 diff 指紋。

| 版本 | 用途與證據 |
|---|---|
| r2 `d8349e0078f63100f…` | v2 source-bound New Import/Clone，首次 native QGIS 完成；[來源快照](../../artifacts/golden-gpx-repair-20260909/receipts/runtime-version-round-2.json)。 |
| r3b `898dc721ce331511…` | 最後的 Permission write recovery UI；[來源快照](../../artifacts/golden-gpx-repair-20260909/receipts/runtime-version-round-3b.json)。 |
| r4 `7c5c9ab5c92448f5d…` | 加入 preparation aggregate 修復並重載 Python runtime；[來源快照](../../artifacts/golden-gpx-repair-20260909/receipts/runtime-version-round-4.json)。 |
| r5 `a7a8f4741ff8e8d6c…` | 加入 Permission 精確停留掃描加速與 stale Quick review 修復；另開 `:9100` 驗證服務，保留 r4 Clone runners；[來源快照](../../artifacts/golden-gpx-repair-20260909/receipts/runtime-version-round-5.json)。 |
| r6 `a7a8f4741ff8e8d6c…` | 使用者回報記憶體不足中斷；live uptime 證明主機重啟。來源碼與 r5 相同，恢復單一 `:9099` 服務與隔離 QGIS profile；[來源／環境回執](../../artifacts/golden-gpx-repair-20260909/receipts/runtime-version-round-6.json)。 |
| r7 `18660d2c8aef644e…` | 修復 job catalog 的重複 JSON 轉換與驗證；[來源快照](../../artifacts/golden-gpx-repair-20260909/receipts/runtime-version-round-7.json)。 |
| r8 `232119c8e8977aca…` | OCR 預設等待完成，新增 OCR source hash；全部作業終止後以新 Dashboard 程序載入，尚無完整 UI／preparation 重跑；[來源快照](../../artifacts/golden-gpx-repair-20260909/receipts/runtime-version-round-8.json)、[局部 diff](../../artifacts/golden-gpx-repair-20260909/reports/r8-ocr-scoped.diff)。 |

Runtime 是 `http://127.0.0.1:9099/admin/dashboard`。瀏覽器動作經實際表單、按鈕、
reload 與 workspace selector；Network 用於旁證。獨立 Python/XML 解析核對原始來源，
没有手動補寫 workspace JSON 來取得完成畫面。

r5 的 Permission 重驗入口是 `http://127.0.0.1:9100/admin/dashboard`。原 `:9099`
仍負責已啟動的 r4 Clone preparation；不把這些 preparation 改稱 r5 執行。
`:9100` 的 browser Settings 明確保存 API base，並由 Network 確認實際請求目標。

01:43 UTC 接續檢查時，原服務與 QGIS PID 均已不存在；兩個 G1 的
`completed_with_gaps` 回執保留，G2 的磁碟 stage 停在 attempt 2 prepare。
r6 重新取得服務與橋接的當前證據，不把重啟前的 PID、port 或 running 字樣當成存活。

| 案例 | 專案與 job |
|---|---|
| G1 New Import | `golden_g1_chilai_20260909_r2`；`prep.d5ce3e3756231b0d663aa3f7c607f798`。 |
| G1 Clone | `golden_g1_chilai_clone_20260909_r2`；`prep.2c69c1928f23d8c35bc41f8589db7a16`。 |
| G2 Clone | `golden_g2_dongqing_clone_20260909_r2`；`prep.4de346e335c850626dbe2e5fa6b5bdfe`。 |

較早的 `golden_g1_chilai_20260909` 與失敗的 G2 v1 job 保留為失敗/修復證據；不與 r4
成功次數合併。前者的實際 Accept/Rebuild 曾在 UI 20 秒 timeout 後完成，正是 write
recovery 修復的觸發案例；[回執診斷](../../reports/r2-accept-timeout-g1-chilai-20260909.md)。

## 原始來源核對

- G1：`GoLife_Run_gpx_2016-11-12.gpx`，raw SHA256
  `2d57a1d949547b9f17a1c2a5470795d9d8fd0fff1de09924e40b2f5bd7bfbbaf`。
  Golden + 24 Ref.，9,302 → 9,290 點、35 CP/34 segments；2016-11-12
  08:40:19–16:47:41 Asia/Taipei，487.3667 分鐘。35 個 CP 的來源/time 全符。
- G2：raw SHA256 `5f0ff2993d561d8f3c5b108db215d312d85d703e51e1fd93743940768df916db`。
  4 個 unique sources，5,768 → 5,649 點；119 個被過濾點可追溯，包含嵌入的異年點。
  219 CP 中 218 個有時刻，`cp.177` 保持 unknown；全部 source/time/unknown 期望相符。
  正確歷史日為 2020-12-26 至 2021-01-03，143 個缺時點、8 個 overnight gaps、32 個
  inferred stationary intervals 必須保留，不能自行改稱已確認露營或休息。

[G1 import oracle](../../artifacts/golden-gpx-repair-20260909/sources/golden_g1_chilai_20260909_r2.import-complete.json)、
[G2 import oracle](../../artifacts/golden-gpx-repair-20260909/sources/golden_g2_dongqing_clone_20260909_r2.import-complete.json)。

## 中斷恢復的實際證據

r4 重載前，三案均已完成 import；G1 已有一次 preparation/initialization 回執，G2
正在 preparation，G1 Clone 等候 shared preparation slot。重載後兩個 Clone 的 GET
顯示 interrupted；G1 是已完成的 `completed_with_gaps`，均沒有自動續跑。root
由 Dashboard 分別按 Resume，再比對 stage 與磁碟產物。

[Resume proof](../../artifacts/golden-gpx-repair-20260909/reports/r4-resume-checkpoint-proof.md)
確認三案全部沿用同一 import.1 receipt/checkpoint；108 個 workspace raw/filtered GPX、
54 個 request source GPX、12 個 import-identity JSON、10 個既有 receipt 的 SHA 全符。
每案仍只有一份 import receipt。G1 Resume HTTP 202 用時 19.377 秒；兩個 Clone 約
20 秒 abort，隨後由 job catalog 找回同一作業的 queued/running。這證明接續來源身份，
不能推論後續 QGIS 或完整準備一定成功。

G1 attempt 2 在 00:52:41 UTC 終止為 `completed_with_gaps`；[終止回執](../../artifacts/golden-gpx-repair-20260909/reports/r4-g1-resume-terminal.json)
與[刷新後畫面](../../artifacts/golden-gpx-repair-20260909/browser/073-r4-g1-resume-terminal-confirmed.dom.json)相符。
最後 validation 的舊 blocker 已清除，23 個 preparation records 中 22 ready、1 missing；
這些 records 與 33 個 Dashboard layers 是不同層級，不把數量差異當成額外缺十層。
[33-layer verifier](../../artifacts/golden-gpx-repair-20260909/tests/g1-r4-layer-contract.json)
仍因 MCP ref/count FAIL。QGIS 本次 bridge 失敗另保留於 processor receipt；此前可用
地形候選的保留不等於本次 QGIS workflow 成功。

G1 Save 後的第二次相同提交使用相同 payload hash/idempotency key，reload 後仍只有
同一 candidate version；[兩次 Save 請求](../../artifacts/golden-gpx-repair-20260909/receipts/g1-r2-repeat-save-requests.json)。
本次沒有故意切斷第二個 Save 的回應，所以不把它寫成 transport-loss 注入成功。
r4 的 A→早期 QA B→A 後，由伺服器 Restore 回
`version.9bd2a934a00ee204` / `50df237cb32926a9…`，35/35 CP clocks、1 日、0 inferred stops
不變，Quick review 勾選清空且未接受；[畫面](../../artifacts/golden-gpx-repair-20260909/browser/071-r4-g1-restored-after-a-b-a.dom.json)。
該畫面仍有 Route sketch 的 20 秒 timeout，因此候選恢復與地圖讀取分開判定。
070–076 的 Network 事件未被成功保存；這組證據只支持 DOM 所見狀態，不能宣稱
捕獲後端對過期 Accept 的 HTTP 拒絕。修復後
[078](../../artifacts/golden-gpx-repair-20260909/browser/078-stale-review-disabled-confirmed.dom.json)
明示不能審查、停用控制並保留 source_stale 原因，沒有送出 Accept。

G1 Clone 於 01:25:29 UTC 終止為 `completed_with_gaps`，import 仍為 attempt 1，
prepare 與 Permission initialization 完成；[終止回執](../../artifacts/golden-gpx-repair-20260909/reports/r4-g1-clone-terminal.json)。

r7 修復後，實際 Dashboard job catalog GET 返回 200：首次刷新 10.608 秒，之後三次
為 4.205／4.103／4.795 秒，沒有再出現清單逾時。G2 Resume POST 在 22.878 秒被
瀏覽器取消等待，後端仍在 target lease 內核對 2,834 個檔案、1,710,462,169 bytes。
後續 GET 重新找回同一 job；「running」本身不代表新 preparation 已開始。
02:33:26 UTC 才留下 attempt 3 的 queued checkpoint，原 import.1 receipt 與
request hash 不變；[Network 時間](../../artifacts/golden-gpx-repair-20260909/reports/r7-job-recovery-network-summary.json)、
[來源回執核對](../../artifacts/golden-gpx-repair-20260909/reports/r7-g2-resume-source-check.json)、
[新 attempt](../../artifacts/golden-gpx-repair-20260909/reports/r7-g2-resume-attempt3.json)。

attempt 3 的 prepare 於 02:42:46 UTC 實際開始。OSM raw extract 與 feature index
於 02:53:06／02:53:56 UTC 寫出；圖磚快取於 03:09:45 UTC 保存全部 22 組回執：
14 組 `seed_complete`、7 組部分區域無覆蓋、1 組 `seed_no_coverage`，新寫入
4,191 張、沿用既有 3,075 張、下載失敗 0。這僅證明圖磚階段完成；
[圖磚回執摘要](../../artifacts/golden-gpx-repair-20260909/reports/r7-g2-raster-terminal.json)。

prepare.3 於 03:44:20 UTC 完成，Permission initialization 於 03:46:21 UTC 完成；
整個作業在 03:46:22 UTC 終止為 `completed_with_gaps`。import.1 保持原回執與
request record hash，全部三階段回執 hash 相符；
[終止核對](../../artifacts/golden-gpx-repair-20260909/reports/r7-g2-terminal.json)。
23 個 preparation records 為 18 ready、4 blocked、1 missing。當次 QGIS 沒有執行，
四個 risk layers 保持 blocked，MCP 缺來源 producer；實際 workspace 的
[33-layer verifier 仍 FAIL](../../artifacts/golden-gpx-repair-20260909/tests/g2-r7-layer-contract.json)，
缺 ref 包含 risk-score／ribbon／heatmap／delta、MCP 與 boss-points。

當次 OCR 回執的 402 張圖磚全部遇到舊版 10 秒 timeout，0 個文字結果、0 次快取寫入。
外層 `completed` 只表示迴圈已走完，不能代表 OCR 成功；
[OCR 原始終止摘要](../../artifacts/golden-gpx-repair-20260909/reports/r7-g2-ocr-terminal.json)。

Permission 初始化結果為 `authoring_ready=true`、`projection_ready=false`，
`reviewed=false`、`departure_approval=false`、`runtime_safety_truth=false`。
由於 project 未提供多日設定，bootstrap 的 `D1` 是明示缺時間的編輯起點，
**不是將九日 Golden 合併成一日已接受計畫**；仍須經 Generate from Ref. GPX 審查。
[初始化回執](../../artifacts/golden-gpx-repair-20260909/reports/r7-g2-permission-initialization.json)。

在這個新 G2 完成 preparation 後再作唯讀重建，結果是 9 天、32 段推估停留、
8 個過夜間隔、10 段未知時間，三個來源 hash 全符，仍為未接受 candidate。
[準備後來源 oracle](../../artifacts/golden-gpx-repair-20260909/sources/golden_g2_dongqing_clone_20260909_r2.r7-prepare-complete.json)、
[實際新 G2 重建](../../artifacts/golden-gpx-repair-20260909/reports/r7-g2-real-reconstruction-after-preparation.json)。
這證明後端保留九日語意，尚未證明 Permission 表單與後續六力也正確採用。

03:19:03 UTC 的 QGIS 回執為 `MCP_UNAVAILABLE / QGIS worker status timed out`，
三次 preflight 後 `actual_processor=not_run`；[原始失敗快照](../../artifacts/golden-gpx-repair-20260909/reports/r7-g2-qgis-unavailable.json)。
直接探測確認 `/capabilities` 回應 200，但 `/status` 及 QGIS `bridge.hello` 逾時；
喚醒同一視窗亦未恢復。確認 PID 2338 為本輪隔離 profile、無開啟的 QGS/QGZ 檔案、
此案無執行中的 QGIS workflow 後，以 SIGTERM 結束該測試程序，保存原 profile 再啟動。
新 PID 5214 註冊完成後，03:37 UTC 的 worker `/status` 回應 200 / available，
QGIS application、plugin bridge 與 candidate-only 邊界皆確認，耗時 18.038 秒；
同輪獨立的 10 秒 hello probe 仍逾時，表示耗時狀態尚不足以支持穩定性宣告。
[重啟前探測](../../artifacts/golden-gpx-repair-20260909/receipts/r7-qgis-live-status-probe.json)、
[重啟回執](../../artifacts/golden-gpx-repair-20260909/receipts/r7-qgis-restart-launch.json)、
[重啟後探測](../../artifacts/golden-gpx-repair-20260909/receipts/r7-qgis-live-restarted-probe.json)。
這僅修復當前連線，不會重新執行已失敗的 G2 地形階段，也不改寫該次結果。

03:10 UTC 的範圍核對確認專案 `.git` 已不存在，無法重新取得目前 HEAD／dirty diff。
18 個 r7 執行來源檔仍全部符合所保存的 SHA；[當前來源核對](../../artifacts/golden-gpx-repair-20260909/receipts/r7-latest-source-check.json)。
未重建 Git 或還原檔案；上文 HEAD 與 dirty diff 指紋是此前實測紀錄，不能冒充這次
重新執行 Git 的成功結果。未進行 Git metadata 重建；r8 以修改前的兩份原檔快照、
局部 diff 與 19 個執行來源 hash 記錄範圍。

r7 全部作業終止後，正常結束本輪 Dashboard，再啟動 r8 PID 5830／launcher 5821。
04:02 UTC 實際確認 127.0.0.1:9099 監聽；QGIS worker 3660 沿用，沒有重複啟動。
重載後核對 53 份作業紀錄、階段回執、候選版本與 Permission 檔案均未改變；
[保存核對](../../artifacts/golden-gpx-repair-20260909/receipts/r8-after-ready-persistence.json)。
此為本機服務重載證據，不能替代 G4 的 browser reload／顯示一致性驗收。

085–088 保存本次 job catalog／Resume 畫面。單日 Permission Preview 的下一個瀏覽器
操作逾時並使控制連線重設；重新連線回傳 `No browser is available`，依文件檢查的
browser list 亦為空。該次 Preview 沒有完整 Network／畫面回執，結果是未知；不得
宣稱 r7 已完成新的 Save／Accept／Rebuild 或 G6。既有原始案未被改寫。

## 較早 QA 案的 post-Rebuild 六力觀測

下表是 `golden_g1_chilai_20260909` 已完成實際 Accept/Rebuild 後，在 r4 UI 讀取的
回歸證據。它曾有 QGIS preparation failure，不能冒充新 r4 G1/G2 完整成功鏈。

| 面向 | 實際觀測與限制 |
|---|---|
| Permission | baseline GET 超過 20 秒而顯示 fail-closed/blocked；既有 reviewed receipt 並未因此消失。[062](../../artifacts/golden-gpx-repair-20260909/browser/062-r4-old-g1-permission-read-timeout.dom.json)。 |
| Architecture | 1 個歷史行進日；Golden 16.08km、source 16.07km，scale 1.000619 明示；18:00 固定截止與未扣額外休息明示。0 selected MCP，3/7 sources、61 bins，PARTIAL。[063](../../artifacts/golden-gpx-repair-20260909/browser/063-r4-old-g1-postrebuild-architecture.dom.json)。 |
| Weather | 2026-09-09 的 CWA 快取/預報時窗，stale_data/no_coverage、rain UNKNOWN，沒有當成 2016 歷史天候；沒有按更新或 RF send。[064](../../artifacts/golden-gpx-repair-20260909/browser/064-r4-old-g1-postrebuild-weather.dom.json)。 |
| Navigation | 仍顯示 loading workspace terrain evidence，0 route-corridor lines、0 morphology samples；沒有得到可驗收的 terrain 畫面。[065](../../artifacts/golden-gpx-repair-20260909/browser/065-r4-old-g1-postrebuild-navigation.dom.json)。 |
| Route Context | 正文 iframe 有正確 project/16.1km/2016 來源日期，0 可用命名點與來源缺口；沒有讀入剛接受的分日版本，仍是 preparation briefing。另有正文「7 個命名節點」與零計數不一致。[含 iframe snapshot](../../artifacts/golden-gpx-repair-20260909/browser/066-r4-old-g1-postrebuild-route-context.snapshot.txt)。 |
| Pace Fit | 35 CP、cp.016 的 Recorded GPX time 為 2016-11-12 13:18；明示空間上下文/Preview，supporting calculations 仍是 fixture，未證明採用後節奏分析。[067](../../artifacts/golden-gpx-repair-20260909/browser/067-r4-old-g1-postrebuild-pace.dom.json)。 |

這些頁面能讀取部分同一 Golden 的觀測資料，仍不等於六力共用同一已接受分析版本。
歷史資料、18:00 假設與目前天候原本就有不同時間角色，不要求把目前预報改成歷史天氣。

## 已確認的剩餘缺口

**MCP 仍缺 producer。** 真實 G1 r2 的 33-layer verifier 只剩 MCP ref/positive-count
失敗，但這不能讀作全部 preparation 通過。GPX notes 和 OSM objects 尚未經來源去重、
實體解析與 typed named-point evidence compiler；不能直接把 4,427 則筆記或 165 個
OSM 物件當成合格 MCP。現有 synthesis/alignment 可重用，新的真實來源 profile 與
證據整理能力仍待實作；[詳細診斷與最小修復範圍](../../artifacts/golden-gpx-repair-20260909/reports/mcp-preparation-gap.md)。

**六力共同版次尚未證明。** [G6 程式/產物稽核](../../artifacts/golden-gpx-repair-20260909/reports/g6-binding-audit.md)
發現 Accept/Rebuild 只失效 Permission scope、ETA 舊欄位仍可能共存、read-time ETA SHA
未與原 seed/rebuild snapshot 核對，及缺少跨六力的共同 analysis revision。這是靜態
缺口證據，不把未發生的污染宣稱為已觀測錯誤；後續須與實際 post-Rebuild 畫面合併判定。

## 驗證紀錄

測試批次與 browser 證據分開計算，不把不同程式版本的通過數合併成一個穩定版本宣告。

- r8 OCR／adapter：16 PASS，含預設無逾時、明確正數逾時、兩個 runner、失敗記錄、
  快取與 Route Context adapter；[results](../../artifacts/golden-gpx-repair-20260909/tests/run-20260909T034055039110Z/results.json)。
- r7 單張真實圖磚唯讀診斷：停用 10 秒逾時後，pytesseract runner 在 22.348 秒完成，
  5 個 raw records、0 個非空文字；此為耗時證據，不能當成有效地名或 OCR 語意成功。
  [receipt](../../artifacts/golden-gpx-repair-20260909/receipts/r7-ocr-probe-result.json)。
- r8 未設定逾時覆寫的真實單張 runner：19.777 秒完成，與上述結果 SHA 相同，
  同樣為 5 個 raw records／0 個非空文字；僅證明預設等待修復。
  [receipt](../../artifacts/golden-gpx-repair-20260909/receipts/r8-ocr-default-probe-result.json)。
- r8 repository 33-layer contract PASS，與實際 G2 workspace 的 layer FAIL 分開判定；
  [contract](../../artifacts/golden-gpx-repair-20260909/tests/r8-repo-layer-contract.json)。
  [Navigation guard](../../artifacts/golden-gpx-repair-20260909/tests/navigation-freeze-after-r8.json)
  通過 suspended/report-only 檢查，沒有更改 freeze baseline。

- 核心 jobs/API/initialization/QGIS 整合批次：114 PASS、1 SKIP（optional upstream source
  未設定）；[results](../../artifacts/golden-gpx-repair-20260909/tests/run-20260908T235146919482Z/results.json)。
- Import/Clone/raw preparation helper：59 PASS；[results](../../artifacts/golden-gpx-repair-20260909/tests/run-20260908T234025910006Z/results.json)。
- 最後 UI write recovery：27 PASS，執行實際 inline JS 函式與 mocked transport，屬 Node VM
  隔離測試；[results](../../artifacts/golden-gpx-repair-20260909/tests/run-20260909T002243910816Z/results.json)。
- 最後 aggregate/validation 修復：5 個測試入口、參數化後 12 cases PASS；[results](../../artifacts/golden-gpx-repair-20260909/tests/run-20260909T002540674484Z/results.json)。
- r5 UI write recovery／stale review：41 PASS、0 warnings；[results](../../artifacts/golden-gpx-repair-20260909/tests/run-20260909T011539889827Z/results.json)。
  測試使用實際 inline functions／handler 與隔離 transport；HTML SHA 與 r5 一致。
- G3/G5 九個隔離故障案例保留在 [evidence summary](../../artifacts/golden-gpx-repair-20260909/tests/g3-g5/evidence-summary.md)。
- 前端 `pnpm lint`、`pnpm typecheck`、`pnpm test` 通過；[results](../../artifacts/golden-gpx-repair-20260909/tests/pnpm-r3-results.json)。
- r5 前端同三項檢查通過；[results](../../artifacts/golden-gpx-repair-20260909/tests/pnpm-r5-results.json)。
- r7 準備 jobs／API：42 PASS，1 個 pytest XML metadata 格式 warning，無失敗；
  [results](../../artifacts/golden-gpx-repair-20260909/tests/run-20260909T020840554854Z/results.json)。
- r7 G3／G5 故障案例、歷史重建、Permission initialization／Restore：50 PASS；
  [results](../../artifacts/golden-gpx-repair-20260909/tests/run-20260909T022202435032Z/results.json)。
  兩批均禁止 real `.env` 與 network；沒有觸發這些存取。這 92 cases 不替代 browser gates。
- r7 額外兩個真實來源唯讀完整對照 PASS：G1 r2 的單日重建與舊掃描結果 deep equal
  （77.01 → 17.15 秒）；既有九日 QA 對照也 deep equal（7.68 → 7.44 秒），保留
  32 inferred stays、8 overnight gaps、10 unknown ranges。
  [單日對照](../../artifacts/golden-gpx-repair-20260909/tests/run-20260909T023600190279Z/golden_g1_chilai_20260909_r2.parity.json)、
  [九日對照](../../artifacts/golden-gpx-repair-20260909/tests/run-20260909T023600190279Z/golden_g2_dongqing_clone_20260908.parity.json)。
  九日對照來源明確是 `20260908` QA，不能替代新 `20260909_r2` 的 G2。
- r7 [Navigation guard](../../artifacts/golden-gpx-repair-20260909/tests/navigation-freeze-after-r7.txt)
  通過 suspended/report-only 檢查，baseline 不變。r7 只改 Python job status，HTML 仍為
  已通過前端檢查的 r5 SHA，沒有因本次 Python 修復重跑無改動的前端 suite。
- [Navigation freeze guard](../../artifacts/golden-gpx-repair-20260909/tests/navigation-freeze-after-r4.txt)
  依既有 suspended/report-only 政策執行；沒有更新 baseline 或放寬契約。

沒有進入 Productization Mode，未跑與修改無關的全 repo suite；上述任何測試數字均不
替代 G1–G6 的真實操作門檻。完整成功後同版本三次核心流程驗證尚未成立。
