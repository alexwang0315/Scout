# Pydantic AI 2.40 / PraisonAI Agents 1.7.4 本機相容性驗證

日期：2026-09-07。狀態：`WORKING PROTOTYPE`。

本輪只升級 Scout Mac 開發 venv、repo dependency pins 與相容性驗證；沒有部署
Scout 硬體、重啟 Dashboard/worker、修改 Navigation/GIS 行為，或重跑完整答題
corpus。這份結果證明 transport、tool/capability 與框架契約相容，不代表回答
品質、安全決策品質或硬體效能有所提升。

## 版本

- `pydantic-ai-slim==2.40.0`
- `pydantic-evals==2.40.0`
- `pydantic-graph==2.40.0`
- `praisonaiagents==1.7.4`
- Python `3.12.3`

Pydantic family 一次對齊升級；其解析同時將 `openai` 從 3.6.0 更新至 3.8.0。
Praison 1.7.4 新增解析依賴 `croniter==6.2.4` 與
`python-dateutil==2.9.0.post0`。`uv pip check` 檢查 107 個套件全部相容。

官方 Pydantic 2.40 release 新增 `Agent.on_event`、realtime enqueue/respond/
barge-in，並修正 OpenAI Responses stream finish reason、capability derived-state
cache 與平行批次中的 deferred-tool reveal 順序。Scout 本輪不啟用 realtime
控制面，只針對既有 agent/tool 路徑與會影響 Scout 的新契約加 regression。

來源：

- [Pydantic AI 2.40.0 release](https://github.com/pydantic/pydantic-ai/releases/tag/v2.40.0)
- [Pydantic AI 2.39.0 release](https://github.com/pydantic/pydantic-ai/releases/tag/v2.39.0)
- [PraisonAI Agents 1.7.4 on PyPI](https://pypi.org/project/praisonaiagents/1.7.4/)

Praison 1.7.4 的官方套件頁沒有提供足以辨識 migration 或 breaking change 的
逐項 release note，因此採基線對照與 Scout integration smoke 作為升級依據，
不從版本號推論未公布的行為。

## 驗證結果

升級前基線：

- focused Pydantic/Praison pytest：`95 passed`，191.79 秒。
- Pydantic CLI offline smoke：`18/18 passed`。

升級後：

- focused Pydantic/Praison pytest：`97 passed`，59.98 秒。
- Pydantic CLI offline smoke：`19/19 passed`。
- 真實 OpenRouter smoke：`28/28 passed`，模型固定
  `openrouter:deepseek/deepseek-v4-flash-0731`。
- Ruff、diff whitespace 與 14-file scoped secret-pattern scan 均通過。

基線與升級後 pytest 的 cache、process 與執行順序不同，不能用上述秒數推論
2.40.0 有效能提升。

真實 OpenRouter smoke 已觀察：

- function tool call/return，版本工具實際回傳 `2.40.0`；
- typed structured output；
- MCP `FunctionToolCallEvent`、`FunctionToolResultEvent` 與最終 run event；
- streamed model events；
- Scout traced WebSearch 與 WebFetch；
- `ToolFailed` 對模型可見且沒有被誤當自動 retry；
- `ModelRetry` 後第二次 tool call 成功。

OpenRouter provider-native search 有成功完成 HTTP/model transport，但沒有暴露
native tool parts，因此仍只記為 `provider_transport_only`。可稽核的網路研究證據
來自 Scout server-side traced `scout_web_search` / `scout_web_fetch`，不得把前者
誤報成具來源的原生搜尋證明。

## 新增回歸

- `Agent.on_event(PartStartEvent)` listener 會收到一次篩選事件，且不改變最終輸出。
- 平行 sibling tool results 必須先維持在同一個 request；兩個 synthetic
  deferred-tool reveal call/return 隨後逐組相鄰，且不得跨越 user message barrier。
- 既有 2.38 regressions 繼續涵蓋 capability merge、WebSearch/WebFetch 保留、
  第一個 tool 執行中取消後保存 history 並續跑，以及 provider finish reason。
- Praison focused tests 繼續涵蓋 Agent/Task/AgentTeam/AgentFlow import、memory
  isolation、MCP、background queue、web research 與 candidate-only Scout bridge。

## 重跑命令

```sh
rtk proxy ./venv/bin/python -m pytest \
  tests/test_pydantic_ai_compat_smoke.py \
  tests/test_pydantic_ai_runtime_compat.py \
  tests/test_pydantic_ai_238_compat.py \
  tests/test_pydantic_ai_240_compat.py \
  tests/test_praison_runtime_compat.py \
  tests/test_scout_ai_exp_praison_bridge.py \
  tests/test_scout_ai_praison_background_mcp.py \
  tests/test_scout_ai_praison_background_mcp_http.py \
  tests/test_scout_ai_praison_background_queue.py \
  tests/test_scout_ai_praison_mcp_slice.py \
  tests/test_scout_ai_praison_web_research.py -q

rtk proxy ./venv/bin/python -m scout.cli.pydantic_compat_smoke

rtk proxy ./venv/bin/python -m scout.cli.pydantic_compat_smoke \
  --live-openrouter \
  --model deepseek/deepseek-v4-flash-0731 \
  --env-file /Users/alexwang0315/.scout/.env
```

Live smoke 會產生外部 API 用量。命令與報告不輸出 credential 值。

Praison integration tests 使用當前工作樹執行；工作樹中既有、非本輪所有的
`src/scout/nextgen/praison_service.py` 修改未被覆寫或納入本次升級 diff。獨立的
SDK import/version/memory-isolation tests 也已通過，避免只以該整合檔判定相容。
