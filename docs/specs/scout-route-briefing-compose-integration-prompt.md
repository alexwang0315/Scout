# Scout Route Briefing Compose Integration Prompt

請在 `/Users/alexwang0315/scout-fusion` 繼續整合「route briefing compose」能力到 Scout AI。這是 pretrip / route-context 層的 candidate-only 能力，不是 deploy/runtime 修復，也不要混入新功能大改。

## 先讀這些檔案

1. `pretrip_route_briefing_compose.py`
2. `skills/scout/route-briefing-compose.yaml`
3. `tools/scout_agent_tool_manifests/scout.pretrip.route_briefing_compose.json`
4. `tests/test_pretrip_route_briefing_compose.py`
5. `tests/fixtures/pretrip/route_briefing/chilai_nanhua_research.json`
6. `docs/admin/qilai-nanhua-hiking-briefing.zh-Hant.html`
7. `pretrip_route_context_collection.py`
8. `scout_agent_tools.py`
9. `scout_agent_cli.py`

## 目前已完成

- 新增 `scout.pretrip.route_briefing_compose` tool manifest。
- 新增 `route-briefing-compose` Scout skill YAML。
- 新增可執行 composer：讀 operator-reviewed route research JSON，輸出 HTML briefing。
- 新增奇萊南華 fixture，保留歷史層、文化層、自然層、地形層、季節層、觀察點、行程版本與來源 refs。
- 新增 focused tests，覆蓋 dry-run、未授權阻擋、授權寫檔與 candidate-only boundary。

## 重要邊界

- 不要讓 Scout runtime 自動 live web search。
- live network research 必須是 operator 明確核准的前置步驟，或未來接到有審核/快取/來源 manifest 的 connector。
- briefing 輸出只能是 candidate-only pretrip artifact。
- 不得寫入 `phase1.runtime`、`phase1.safety`、`phase2.brain.observed_facts`、`live.safety_api`、`hardware.controls`。
- 不得把模型文字、網頁摘要或簡報內容升級成 runtime safety truth。
- 出發前公告、天氣、道路、入園/山屋名額仍必須由 operator 重新查核。

## 建議整合 slices

### Slice 1: Registry and CLI visibility

- 確認 `scout.pretrip.route_briefing_compose` 出現在 `scout_agent_cli tools list`。
- 不要改大架構，只補必要 coverage。
- 驗證：
  - `python3 -m pytest tests/test_pretrip_route_briefing_compose.py -q`
  - `python3 -m pytest tests/test_scout_agent_tools.py tests/test_scout_agent_builtin_manifests.py -q`，若既有 dirty work 造成非本 slice 失敗，記錄並隔離。

### Slice 2: Pretrip workspace artifact integration

- 把 route briefing output 接到既有 pretrip workspace convention。
- 優先沿用 `outputs/briefings/`、`normalized/context/route_context/`、`candidates/route_context*` 的命名與 manifest refs。
- 若要讓 artifact manifest 看見它，擴充 manifest refs 時保持 additive，不破壞既有 `route_context_briefing`。

### Slice 3: Scout AI query / evidence / answer path

- 讓 Scout AI 可以回答「這條路線有哪些值得停 3 分鐘的點？」、「奇萊南華建議幾天？」、「沿線有哪些歷史/自然/地形觀察？」。
- 不要只新增 tool；要檢查 planner trigger、evidence collection compact payload、answer synthesis 三段是否會讓 briefing 內容在最終回答可見。
- 回答文字必須說明它是行前候選資料，並引用 source refs。

### Slice 4: UI/admin visibility

- 若要展示在 admin/pretrip UI，做小 slice。
- 用 fixture-backed data，不依賴 live network。
- 若做 browser smoke，用 GET 請求或實際 browser 畫面，不用 HEAD 當 HTML 可視性證據。

## 非目標

- 不做 Pi deploy/runtime repair。
- 不接 live safety API。
- 不做自動山屋申請、入園申請或訊息發送。
- 不把外部網頁抓取放進無審核 runtime。
- 不修改既有 Scout core safety truth model。

## 驗收標準

- `scout.pretrip.route_briefing_compose` 可 dry-run，且 dry-run 不寫檔。
- 未授權正常 run 會被 workspace_write authorization 擋下。
- 授權後可寫出 HTML briefing。
- tool output boundary 必須包含：
  - `candidate_only=true`
  - `network_calls_made=false`
  - `runtime_safety_truth=false`
  - `model_output_is_runtime_truth=false`
  - `live_safety_api_calls_allowed=false`
- Scout AI 最終回答若使用此 briefing，必須把它稱為 pretrip candidate briefing，而非即時安全結論。

## 第一個可執行命令

```bash
python3 -m pytest tests/test_pretrip_route_briefing_compose.py -q
```

## 範例 tool run

```bash
python3 scout_agent_cli.py tools run scout.pretrip.route_briefing_compose \
  --manifest-dir tools/scout_agent_tool_manifests \
  --input tests/fixtures/pretrip/route_briefing/chilai_nanhua_research.json \
  --output /tmp/chilai-nanhua-route-briefing.html \
  --dry-run \
  --json
```
