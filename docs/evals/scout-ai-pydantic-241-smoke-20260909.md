# Pydantic AI 2.41 本機升級與相容性驗證

日期：2026-09-09。升級 slice：`WORKING PROTOTYPE`。
整體 focused suite 並非全綠：另有一項升級前已存在的 Praison MCP deadline 問題。

## 範圍與版本

本輪只修改 Mac venv、dependency manifests、相容性 smoke/tests 與現行版本文件。
沒有部署 Scout 硬體、重啟 Dashboard/worker、修改 Navigation/GIS、改變模型選擇
或 runtime safety 權限，也沒有重新跑 1,000 題。相容性成功不等於答題品質或
硬體效能提升。

| 套件 | 升級前 | 升級後 |
| --- | --- | --- |
| pydantic-ai-slim | 2.40.0 | 2.41.0 |
| pydantic-evals | 2.40.0 | 2.41.0 |
| pydantic-graph | 2.40.0 | 2.41.0 |
| praisonaiagents | 1.7.4 | 1.7.4 |
| openai | 3.8.0 | 3.8.0 |

Python 保持 3.12.3。完整套件清單比較只有三個 Pydantic 套件版本改變，沒有
移除其他套件。`scout-ai-os` 的 editable metadata 使用 `--no-deps --editable .`
重建，清除舊 2.40 依賴記錄；`uv pip check` 檢查 107 個套件，全部相容。

`pyproject.toml`、Pi admin/live/intelligence 三份 manifest 及 smoke version gate
一併對齊。初輪 pin regression 曾抓到 intelligence manifest 遺漏，修正後同一
測試已通過。修改 manifest 不代表該 sidecar 或 Pi 已完成部署。

## 相容性變更

- 新增 `fallback_subagent_model` constructor、舊 `fallback_model` warning/alias、
  雙參數衝突拒絕，以及 local-tool/subagent 合併衝突回歸。現有 Scout runtime
  沒有使用 `ImageGeneration` 或 `XSearch`，沒有需要遷移的業務呼叫。
- 新 `ImageGenerator` API 僅以 SDK 的 `TestImageGenerationModel` 執行離線
  fixture，驗證圖片型別、模型身分及設定傳遞；不是新增圖片生成服務。
- `openai-codex` 僅驗證 import；不讀取訂閱 credential、不登入、不更換 provider。
- `RequestUsage.details.web_search_requests` 通過 message JSON round trip。
  這不是 Anthropic live 搜尋或計價正確性的驗證；本輪未呼叫 Anthropic。
- 保留既有 Capability merge、WebSearch/WebFetch、取消續跑、MCP 串流、
  event hook、deferred-tool reveal、ToolFailed/ModelRetry 回歸。

官方依據：[2.41 release](https://github.com/pydantic/pydantic-ai/releases/tag/v2.41.0)、
[fallback 參數 migration](https://github.com/pydantic/pydantic-ai/pull/8077)、
[Pydantic AI 2.41 PyPI](https://pypi.org/project/pydantic-ai/2.41.0/)、
[PraisonAI Agents 1.7.4](https://pypi.org/project/praisonaiagents/1.7.4/)。

## 執行結果

| 檢查 | 實際結果 |
| --- | --- |
| 2.40 focused pytest 基線 | 96 passed / 1 failed，248.59 秒 |
| 2.40 失敗題單獨重跑 | 同一 MCP timeout 再次失敗，63.60 秒 |
| 2.40 offline CLI 基線 | 19/19 passed |
| 2.41 focused pytest | 105 passed / 1 failed，291.26 秒 |
| 2.41 CLI offline checks | 20/20 passed |
| 2.41 CLI live OpenRouter checks | 9/9 passed |
| 2.41 CLI 合計 | 29/29 passed，不是 29 題語意評測 |
| Ruff 0.15.18 | 3 個變更 Python 檔通過 |
| dependency check | 107 個套件相容 |
| scoped diff / secret-pattern scan | whitespace 通過；13 個本輪檔案無 credential pattern 命中 |

兩輪 timing 沒有控制主機負載、cache、cold import 與執行順序，不可拿來推論
版本效能變好或變差。

真實 OpenRouter 模型固定為 `openrouter:deepseek/deepseek-v4-flash-0731`。
版本工具 `scout_runtime_version` 實際回傳 `2.41.0`；structured output、
`route_marker` MCP call/result stream、模型串流、`scout_web_search`、
`scout_web_fetch`、可見的工具失敗，以及 retry 後恢復皆通過。

Provider-native WebSearch 沒有回傳 native tool parts，仍僅標為
`provider_transport_only`。有 source/tool evidence 的搜尋與抓頁證據，來自
Scout server-side traced tools，不能用 HTTP 200 替代來源驗證。

## 既有 MCP 問題

追蹤 ID：`PRAISON-MCP-REPLAY-DEADLINE-001`。

- Reproduction：`tests/test_scout_ai_praison_mcp_slice.py::test_model_backed_praison_team_runs_behind_mcp_process`。
- 原設定：request timeout 20 秒、startup timeout 30 秒。2.40 基線與獨立重跑、
  2.41 focused suite 都回傳 `IntelligenceTransportStatus.TIMEOUT`。
- 隔離診斷：不改原測試或 runtime，在暫存 probe 將 request/startup 等待各設為
  120 秒；41.393 秒取得 `status=ok`、3 筆 finding、1 次
  `local.fast.pydantic-function` request，`runtime_safety_truth=false`。
- 判斷：此 fixture 路徑可執行，原 deadline 對目前主機環境敏感。總耗時尚未拆成
  startup、SDK import 與 tool execution，因此不宣稱已定位是哪個階段過慢。
  沒有證據支持把它算成 2.41 新回歸或雲端模型答題失敗。
- 未修改原測試來算通過，未更換模型；這不是 AI HAT 或真實 Praison 雲端測試。
- 下一步：分段記錄 worker readiness/import/execution timing，確認 startup 與
  execution 各自的 gate。Unblock：原 focused case 在明確定義的執行條件下
  可重複通過，且 timeout/degraded 分支仍能被獨立測試。

## 證據與重跑

原始 artifact 目錄：
`/private/tmp/scout-pydantic-241-20260909-0qHJyv/`

- `baseline-pytest.xml`、`baseline-mcp-retry.xml`、`baseline-offline.json`
- `new-contracts.xml`：初輪 manifest 遺漏的失敗證據，未覆蓋
- `upgraded-pytest.xml`：修正後完整 focused suite
- `live-openrouter.json`：29 項結果、實際模型輸出及 tool traces
- `probe_praison_mcp.py`、`mcp-relaxed-deadline.json`：隔離 deadline 診斷

```sh
rtk proxy ./venv/bin/python -m pytest \
  tests/test_pydantic_ai_compat_smoke.py tests/test_pydantic_ai_runtime_compat.py \
  tests/test_pydantic_ai_238_compat.py tests/test_pydantic_ai_240_compat.py \
  tests/test_pydantic_ai_241_compat.py tests/test_praison_runtime_compat.py \
  tests/test_scout_ai_exp_praison_bridge.py tests/test_scout_ai_praison_background_mcp.py \
  tests/test_scout_ai_praison_background_mcp_http.py tests/test_scout_ai_praison_background_queue.py \
  tests/test_scout_ai_praison_mcp_slice.py tests/test_scout_ai_praison_web_research.py -q

rtk proxy ./venv/bin/python -m scout.cli.pydantic_compat_smoke --live-openrouter \
  --model deepseek/deepseek-v4-flash-0731 --env-file /Users/alexwang0315/.scout/.env

rtk proxy uv pip check --python ./venv/bin/python
```

Live smoke 會產生外部 API 用量，僅使用相容性 fixture 與公開文件，沒有傳送
私人 workspace。credential 僅 server-side 使用，未印出或寫入上述報告。
Navigation/GIS/browser/hardware gates 本輪不適用；未進行 production promotion。
