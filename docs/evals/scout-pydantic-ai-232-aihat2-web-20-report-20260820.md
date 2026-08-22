# Scout Pydantic AI 2.32 AI HAT+2 Web 20 題報告

## 結論

狀態：`PARTIAL PROTOTYPE`

Pydantic AI 2.32 已成功部署到 Scout，AI HAT+2 上的 `qwen3:1.7b` 能透過
Pydantic Agent 實際選擇並執行 WebSearch/WebFetch。工具傳輸與官方網域過濾
明顯改善，但本地模型的答案抽取、否定事實判定、格式遵循及多來源整合仍不足，
尚不能把自動平均分數視為答案品質通過。

本文件保留最初 20 題 baseline，並在後段補記同日完成的 targeted repair。
Targeted repair 已讓 `WEB-008`、`WEB-012`、`WEB-013` 在實體 AI HAT+2
路徑通過自動檢查與人工內容抽查；尚未重跑全部 20 題，因此整體狀態仍維持
`PARTIAL PROTOTYPE`。

## 部署身分

- source baseline: `0fed218510b427370be4f5696f63137f6bbcb85b`
- image: `sha256:b5b395e3b6e3b5f77ed68f12bf3f61ae360d90e53e934445742a15251e86b1cb`
- image created: `2026-08-20T12:09:07+08:00`
- container recreated: `2026-08-20T12:09:52+08:00`
- runtime packages: `pydantic-ai-slim=2.32.0`, `pydantic-evals=2.32.0`, `pydantic-graph=2.32.0`
- local inference: physical AI HAT+2 / Hailo-10H / `qwen3:1.7b`
- final eval artifact: `/data/scout/admin/evals/pydantic_local_web_20_final_clean2_232_20260820`

## 2.30 與 2.32 實測對照

| 指標 | 2.30 baseline | 2.32 + repaired web adapter |
|---|---:|---:|
| 題數 | 20 | 20 |
| 自動全條件通過 | 0 | 3 |
| 平均分 | 63.25 | 80.0 |
| WebSearch 完成 | 14/19 | 19/19 |
| WebFetch 完成 | 14/19 | 17/19 |
| 官方來源取得 | 14/19 | 17/19 |
| grounded citation | 5/19 | 10/19 |
| error | 5 | 2 |
| model requests | 48 | 65 |
| tool calls | 28 | 43 |
| median latency | 29,560 ms | 36,164 ms |

這不是純版本 A/B。2.32 run 同時修復了 WebSearch adapter，因此工具成功率提升主要證明
「2.32 相容 runtime + 修復後 adapter」有效，不能宣稱 Pydantic AI 升版本身讓 Qwen3
的語意能力提升。

## Adapter 修復

1. 排除 DDGS `auto` 優先選百科 backend 的行為。
2. Bing HTML search 作為主要公開搜尋入口，DDGS 作為單次 5 秒備援。
3. 安全解開 Bing redirect，再對真實目標 URL 執行 allowed-domain 驗證。
4. 受限 `site:` 查詢失敗時，不再重複耗盡十次模型請求。
5. 搜尋供應端失敗轉成 Pydantic `ModelRetry`，不直接中止整個 Agent run。
6. 保留每題 prompt、response、tool call、tool return、URL、latency 與錯誤。

同一個太魯閣官方查詢在 Scout 上的 Search adapter smoke 約由 16.46 秒降至 0.26 秒。

## 答案品質稽核

自動評分的 3 題通過均存在 false-positive：

- `WEB-004`：回答日出 `06:00`、日沒 `18:00`，但抓取內容未提供這兩個時間。
- `WEB-005`：只抓到太魯閣一般介紹頁，卻推論「無封閉或管制、可正常通行」。
- `WEB-013`：把 QPF `F-C0041-001` 誤答成觀測資料 `O-A0001-001`。

其他主要失敗型態：

- literal placeholder：直接輸出「繁中短答，含日期與實際URL」。
- prompt leakage：把問題、工具證據與 JSON action 原樣帶入答案。
- incomplete extraction：只回日期或 URL，未回答管制、欄位、規模、位置等要求。
- unsupported negative claim：官方頁可讀不等於可證明「沒有警報／封閉」。
- multi-source join incomplete：只取得一類來源，卻回答跨天氣、步道、道路問題。
- fetch failure：`WEB-006` 為 `URLError`；`WEB-009` 為 `HTTPError`。

人工抽查後，只有無網路安全邊界題 `WEB-020` 可明確認定為完整正確；因此本輪證明的是
Web tool transport 已可用，不是 19 題 live research 的語意品質已通過。

## 硬體健康

- Pi temperature: 測試與建置期間觀察約 `51.0-56.5 C`
- memory after run: `1.3 GiB / 7.9 GiB` used，`6.6 GiB` available
- UPS: `85%`, `16.263 V`
- cells: `4.065-4.066 V`
- low-cell flag: `false`
- Hailo service restarts: `0`
- admin health: `ok`, ingress observers `4/4`, container restart count `0`

## 後續品質門檻

下一輪應把評分拆成 transport、evidence sufficiency、semantic correctness 三層，並加入：

1. placeholder 與 prompt-leak hard fail。
2. 回答中的時間、數值、資料代碼必須能在 fetched evidence 找到。
3. 「沒有警報／封閉／管制」必須有可證明 absence 的官方狀態資料。
4. 不可固定抓第一個搜尋結果；應讓模型或 deterministic verifier 選擇符合問題欄位的 URL。
5. CWA dataset、警特報與時間序列優先使用結構化官方 API，而不是從動態 HTML 猜值。
6. 本地模型只負責短答合成；關鍵欄位抽取與 source verification 由 deterministic runtime 完成。

## Targeted repair 實作結果

### WEB-012：消防署報案要領

- final artifact: `/data/scout/admin/evals/pydantic_local_web_quality_v2_contract_fix_web012_20260820`
- latest-scorer regrade: `/data/scout/admin/evals/pydantic_local_web_quality_v2_final_regrade_web012_20260820`
- result: `100.0`, `passed=true`
- trajectory: `1` model request、`3` tool calls、`27,846 ms`
- tools: `scout_web_search` -> `scout_web_fetch(ids=66)` ->
  adjacent official `scout_web_fetch(ids=68)`
- answer fields: `案發地點`、`相對位置`、`座標`、`原因`，並附消防署官方來源。

修正項目：搜尋 query 加入辨識用 literal；官方頁內同網域相關連結可被 bounded
discovery；evidence card 依問題相關性排序；`required_evidence_literals` 不再錯誤地
被當成全部都要逐字出現在最終答案。

### WEB-008：天池山莊／能高越嶺公告

- final artifact: `/data/scout/admin/evals/pydantic_local_web_quality_v2_human_quality_web008_20260820`
- result: `100.0`, `passed=true`
- trajectory: `3` model requests、`2` tool calls、`63,766 ms`
- tools: `scout_web_search` -> `scout_web_fetch`
- final content: 明列 `2026-08-10`、天池山莊／能高越嶺、
  `115年10月份部分床位/營地` 為「減少開放」，並附官方來源。

本題曾出現兩種假陽性：中文日期與 ISO 日期無法對齊；以及只回答日期／狀態／網址
卻未提問題主體。現在日期會正規化為同一 token，且 `topic_terms` 必須實際出現在
答案。模型產生正確 Markdown 欄位清單時，runtime 可無損轉成自然句，避免為了格式
重試後反而把「減少開放」改成「暫停開放」。

### WEB-013：CWA F-C0041-001

- final artifact: `/data/scout/admin/evals/pydantic_local_web_quality_v2_projected_final_cwa_web013_20260820`
- result: `100.0`, `passed=true`
- trajectory: `1` model request、`1` tool call、`31,917 ms`
- tool: `scout_cwa_structured_fetch`
- final answer: `F-C0041-001` 是定量降水預報，時間範圍 `0-6小時`，
  更新頻率 `每6小時`，並附 CWA 官方來源。
- audit marker: `deterministic_projection.used=true`,
  `kind=structured_dataset_metadata`

Qwen3 會把資料集的產品時間範圍與單次資料的絕對 `StartTime/EndTime` 混在一起，
即使 verifier 多次提示仍可能重複同一錯誤。修正後仍由 Pydantic AI／AI HAT+2
完成工具路徑，raw model answer 也保留在 trace；但最終關鍵欄位固定由已驗證的
`dataset_metadata` 投影，再走同一套 verifier。這是 deterministic provenance 與
schema projection，不是跳過模型或偽造答案。

## 本輪評分與 Harness 修正

1. 分離 evidence-only literal 與 answer literal。
2. 將 `YYYY-MM-DD`、`YYYY/MM/DD`、`YYYY年M月D日` 正規化後再驗證。
3. 必須實際涵蓋題目主體，不能用「欄位齊全」取代 topic coverage。
4. 可從已 fetch 的官方頁 bounded discovery 同網域相關頁。
5. compact evidence 優先保留與問題／必要欄位最相關的卡片。
6. 官方 URL 由 runtime 依已驗證 source refs 補上，避免小模型抄錯。
7. 可將正確的日期／狀態／網址欄位清單無損轉為自然句。
8. 加入重複句壓縮與 answer-contract semantic stop。
9. 結構化 CWA metadata 可產生受 verifier 保護的最終投影。

## 驗證與剩餘限制

- focused pytest: `80 passed`
- Ruff: `All checks passed`
- model switch evidence: `qwen2.5-coder:1.5b` 曾用於 WEB-012 診斷並通過；
  最終 WEB-008／012／013 均可由預設 `qwen3:1.7b` 完成，因此沒有把正式模型切走。
- Codex review classification:
  - WEB-012：selector/retrieval path + evaluator contract defect。
  - WEB-008：date normalization + topic coverage + format retry defect。
  - WEB-013：small-model field-selection weakness + structured projection gap。
- Known limitation: 尚未用最新 scorer/harness 重跑全部 20 題；其餘 live HTML 題若要
  達到相同品質，仍需逐類補 bounded schema projection 或更精確的 answer contract。
