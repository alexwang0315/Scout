# Route Context Intelligence Implementation

本文件說明 `SCOUT_OUTDOOR_AI_AGENT_STANDARD` Sec. 6
`Route Context Intelligence`：探索力的 Scout 化，目前在 Scout AI / Pretrip
workspace / route briefing skill 中的實作方式、效果與離線重產能力。

## 1. 目標

Sec. 6 定義的探索力不是把山變成打卡清單，也不是鼓勵使用者追求攻頂數。
Scout 的探索力是：

> 把路線從一條 GPX，轉化成一段有歷史、文化、自然、地形、季節與地方脈絡的山林經驗。

產品上，Route Context Intelligence 要回答：

- 這條路線為什麼值得走？
- 沿途有哪些歷史、文化、自然、地形與季節觀察？
- 哪些地方值得停 3 分鐘，而不是只趕路通過？
- 哪些觀察點只適合行前理解，不應在現場自動停留？
- 哪些資料缺口必須回到 P0/P1/P2 source review？

Route Context Intelligence 只產生 pretrip candidate evidence。它不是導航權威，
也不是 runtime safety truth。

## 2. Scout 化的核心轉換

傳統探索力通常仰賴使用者自行上網查攻略、看社群文章、看 GPX 與照片。
Scout 化後，探索力被拆成可驗證的資料流程：

1. 將 route workspace 視為唯一工作邊界。
2. 將來源拆成 P0/P1/P2 provenance。
3. 將 web evidence、MCP、named point、OCR/map label、route notes 與 route summary
   統一投影成 route-context candidates。
4. 將候選點分成 historical、cultural、natural、terrain、seasonal、
   observation point 等 Sec. 6 layers。
5. 將簡報、Scout AI answer 與 admin debug 都接回同一份 workspace-local cache。
6. 將「值得停」與「可以停」分開：Route Context 只說候選觀察價值，
   真正能不能停、能停多久，必須交給 Contextual Permissioning。

這讓探索力不再是模型自由發揮的敘事，而是可追溯、可重跑、可審查的 pretrip
artifact pipeline。

## 3. Source Tier Policy

Route Context Intelligence 使用三層來源：

| Tier | 用途 | 例子 |
| --- | --- | --- |
| P0 | 官方 baseline / status / terrain / weather / hazard / incident / local incident / open data / natural / historical map / cultural trail baseline | 林業及自然保育署、山林悠遊網、入園申請、國家公園、NLSC、CWA、NCDR、消防署、地方消防局、政府開放事故資料、TBN、中研院歷史地圖、尋路・循路－臺灣原住民族古道空間資訊網 |
| P1 | 路線脈絡擴充、community evidence、rescue/reference evidence | 國家文化記憶庫、臺灣記憶、原住民族古道資料、地質雲、OSM、魯地圖、健行筆記、Hikingbook、PTT Hiking、登山補給站、山難救助協會訓練資料、公開專家/社群影音 |
| P2 | Scout-owned workspace evidence | completed GPX、偏航、停留點、照片點、語音註記、IMU/PDR、氣壓高度、隊伍距離、stop-worthiness feedback、Scout action log |

規則：

- P0/P1 catalog 只是 discovery scope，不是 route-specific URL 預設值。
- concrete URL 必須來自 operator 提供、source-list HTML、或未來受審核的 connector。
- P2 預設是 Scout-local/private evidence；未審核前只能當 seed/caveat。
- 所有 artifact 都必須保留 `source_tier`、`source_family`、URL 或 workspace path、
  hash/provenance、review state 與 candidate-only boundary。

## 4. 實作元件

目前實作由以下元件組成：

| 元件 | 角色 |
| --- | --- |
| `.agents/skills/scout-route-context-briefing/SKILL.md` | Codex/operator orchestration skill，規定 live network fetch、P0/P1/P2、candidate-only 與 briefing shape |
| `.agents/skills/scout-route-context-briefing/references/source-catalog.md` | P0/P1/P2 source catalog 與 Sec. 6 context layers |
| `pretrip_p0_p1_source_collection.py` | bounded live web evidence collector；只有 operator 明確允許時才 network fetch |
| `pretrip_route_context_collection.py` | offline-first route context compiler；不 fetch network，只讀 workspace cache 並輸出 canonical route-context artifacts |
| `pretrip_route_briefing_compose.py` | 將 research payload compose 成 route briefing HTML 的工具層 |
| `scout_route_context_tool.py` | Scout AI 可呼叫的 read-only route-context assessor |
| `tools/scout_agent_tool_manifests/scout.pretrip.route_context_collect.json` | Scout agent tool manifest |
| `tools/scout_agent_tool_manifests/scout.pretrip.route_briefing_compose.json` | route briefing compose tool manifest |
| `docs/specs/scout-route-context-layer.md` | Route Context Layer technical spec |
| `docs/specs/scout-workspace-layout.md` | workspace placement contract |

## 5. Workspace Cache Layout

跑過 route briefing / route context collection 後，workspace 會保留可離線重用的
cache 與 canonical artifacts：

```text
outputs/layers/plans/
  web_case_query_plan.json

outputs/layers/normalized/
  web_case_evidence.json
  raster_label_evidence.geojson

normalized/context/route_context/
  route_context_evidence.json
  source_manifest.json
  route_context_pack.json
  crawl_seed_plan.json
  media_manifest.json

candidates/
  route_context_points.json

outputs/briefings/
  route_context_briefing.html
```

重點：

- `web_case_evidence.json` 是 live network fetch 後的 bounded web evidence cache。
- `source_manifest.json` 記錄 source status、hash、missing source、cache policy。
- `route_context_pack.json` 是 Scout AI cache-first 查詢入口。
- `route_context_points.json` 是地圖、review、Scout AI answer 可用的候選點集合。
- `route_context_briefing.html` 是 operator-facing HTML 簡報。

`pretrip_route_context_collection.py` 的設計是 offline-first：它不負責 live network
fetch，而是讀取 workspace 內已存在的 source artifacts，重新產生 pack、points、manifest
與 HTML。

## 6. Live Network 與離線重產流程

第一次需要補 P0/P1 web evidence 時，operator 明確允許 live network：

```bash
PYTHONDONTWRITEBYTECODE=1 python -m pretrip_p0_p1_source_collection \
  --project-root /data/scout/admin/pretrip-workspaces/chilai_nanhua_day1 \
  --source-list-html /data/scout/admin/pretrip-workspaces/chilai_nanhua_day1/inputs/live_route_context_sources_20260616.html \
  --allow-network-fetch \
  --timeout-seconds 20 \
  --json
```

之後 compile route context 與 HTML：

```bash
PYTHONDONTWRITEBYTECODE=1 python -m pretrip_route_context_collection \
  --project-root /data/scout/admin/pretrip-workspaces/chilai_nanhua_day1 \
  --route-keyword "奇萊南華 能高越嶺道 光被八表 天池山莊" \
  --json
```

未來離線、沒有 live network 時，可以直接重跑第二個命令。只要 workspace 仍保有
`outputs/layers/normalized/web_case_evidence.json`、MCP/named point、route summary
與 route-context artifacts，Scout 就能重新產生 HTML briefing。

限制：

- HTML 可以離線重產。
- 文字、來源摘要、候選點、source manifest、route pack 都來自 workspace cache。
- 若 HTML 內引用遠端圖片 URL，瀏覽器在完全離線時可能無法顯示遠端圖片；目前
  artifact 不把 raw images 內嵌進 JSON。若要完整離線圖像，需要後續加入
  reviewed media asset cache。
- 若 workspace 從未收集過 P0/P1 web evidence，仍可產生 partial briefing，但會顯示
  missing evidence/source gap，而不是假裝已有完整脈絡。

## 7. Scout AI Answer Path

Scout AI 對 route-context 問題的查詢順序：

1. `route_context_pack.json`
2. `route_context_points.json`
3. `source_manifest.json`
4. route summary / map / risk artifacts
5. 只有 operator 明確允許時才使用 remote source connector
6. 若資料不足，回覆 uncertainty 與 missing evidence

目前 `scout.ai.route_context.assess.v0` 已可讀 canonical `route_context_pack_ref`，
因此可回答：

- 「奇萊南華建議幾天？」
- 「沿途有哪些歷史、文化、自然、地形、季節觀察？」
- 「哪些點值得停 3 分鐘？」
- 「哪裡適合拍攝或觀察？」
- 「這裡值得看什麼？」

回答必須標示：

- `candidate_only=true`
- `runtime_safety_truth=false`
- 不是現場停留授權
- 若要停留、拍攝、等待或繞行，仍需 Contextual Permissioning 檢查時間、天候、
  日照、隊伍、疲勞、撤退窗口與風險預算

## 8. 實作效果

Route Context Intelligence 的效果不是單純「簡報變漂亮」，而是讓 Scout 具備
以下能力：

1. GPX 不再只是線段，而是可被解釋的山林經驗。
2. 使用者能理解路線價值不只在終點，降低硬攻頂壓力。
3. Scout AI 可以回答 route-context 問題，而不是把所有文化、自然、觀察點問題都判成 missing tool。
4. Source provenance 可審查，避免模型把網路摘要升級成安全事實。
5. P2 Scout-owned evidence 可以在未來納入使用者自己的實際經驗，例如哪裡曾延誤、
   哪裡值得停、哪裡隊伍拉開。
6. 離線時仍能從 workspace cache 重建簡報與答題 evidence。
7. Route Context 與 Contextual Permission 分離，讓「值得看」不等於「現在可以停」。

## 9. 已確認的 Scout 主機離線重產證據

2026-06-16 在 `scout.local` 上做過離線 smoke：

1. 將正式 workspace
   `/data/scout/admin/pretrip-workspaces/chilai_nanhua_day1`
   複製到 `/data/scout/admin/tmp/route_context_offline_smoke_codex`。
2. 在 container 內不帶任何 live network fetch 參數，執行
   `python -m pretrip_route_context_collection --project-root <tmp> --route-keyword ... --json`。
3. 驗證後刪除 temp workspace。

結果：

```text
status=completed
route_context_point_count=19
briefing_exists=True
briefing_size=245256
source_manifest_exists=True
pack_exists=True
cached_web_evidence_exists=True
source_report_count=8
cache_live_fetch_performed=False
```

結論：

- 跑過 route briefing / route-context collection 後，資料確實 cache 在 workspace 內。
- 未來沒有 live networking 時，可以用 workspace cache 重產 HTML briefing。
- 重產過程不需要呼叫 `/safety/*`，也不會建立 runtime safety truth。

## 10. Acceptance Criteria

Route Context Intelligence 應符合：

- `pretrip_p0_p1_source_collection` 只有在 `--allow-network-fetch` 時才做 live network。
- `pretrip_route_context_collection` 可在 offline/cache-first 模式重產 route-context artifacts。
- `route_context_pack.json` 與 `route_context_points.json` 可供 Scout AI read-only tool 查詢。
- HTML briefing 顯示 P0/P1/P2 source tier、missing source、candidate-only boundary。
- 任何「值得停」都必須標成候選觀察點，不得直接變成停留授權。
- 不寫入 `/safety/*`。
- 不修改 Phase 1 runtime behavior。
- 不把模型文字、網頁摘要或簡報內容升級成 runtime safety truth。
