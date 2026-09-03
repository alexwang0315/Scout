# Scout Pydantic AI 2.37 / Praison Core 1.7.3 Compatibility

日期：2026-09-03。結論：`WORKING PROTOTYPE`，本機相容性通過。
這不是硬體部署、效能比較或答題品質驗收。

## 升級範圍

| 套件 | 升級前 | 本機驗證版本 |
| --- | --- | --- |
| `pydantic-ai-slim` | 2.36.0 | 2.37.0 |
| `pydantic-evals` | 2.36.0 | 2.37.0 |
| `pydantic-graph` | 2.36.0 | 2.37.0 |
| `praisonaiagents` | 1.7.0 | 1.7.3 |
| `genai-prices`，解析器同步更新 | 0.1.4 | 0.1.6 |

- 主機是 Mac，Python 3.12.3，使用 repo `venv`。
- `praisonai` CLI 並未安裝，也不是 Scout Intelligence Service 的必要依賴。
- 更新 `pyproject.toml`、`requirements.pi.admin.txt`、
  `requirements.pi.live.txt`、`requirements.pi.intelligence.txt` 的相關版本。
  Pi 清單更新不代表 Scout 硬體已安裝新版。
  其中新的 intelligence 清單屬於另一工作線尚未提交的 sidecar，留在工作目錄，
  不隨本次升級 commit 提交；Praison 的已追蹤版本入口是 package extra。
- 已刷新本機 editable `scout-ai-os` 安裝資訊；否則套件雖已升級，舊的
  installed metadata 仍會要求 2.36.0，導致 dependency check 誤報不一致。
- 基準 Git SHA：`803399fbf7b4f9881fc83e59c946e7f9031ee936`。
  驗證使用含其他任務修改的工作目錄，不是此 SHA 的乾淨 checkout。
  原有 Praison MCP、Dashboard 與 provider 改動均保留，不納入升級 commit。

## 驗證結果

| 檢查 | 結果 | 能證明的範圍 |
| --- | --- | --- |
| 升級前 focused baseline | 54 passed | 既有 Pydantic/Praison 相容性基準 |
| 升級後最終 focused pytest | 92 passed，0 skipped | 10 個測試檔，19.55 秒 |
| Pydantic offline compatibility | 18/18 | 工具、typed output、Capability、MCP、串流及例外契約 |
| OpenRouter live compatibility | 9/9 | 真實 API；與 offline 合計 27/27 |
| Praison live web MCP | PASS | 1 次搜尋、2 次擷取、2 筆有 hash/source 的 evidence，7,193 ms |
| Praison 記憶與 import | 5 passed，包含於 92 | SDK 介面存在，預設不寫記憶，測試用 opt-in memory 隔離 |
| Ruff / scoped diff check | PASS | 本輪 Python 檔案及差異 |
| Dependency check | PASS | 105 個已安裝套件無衝突 |

pytest 耗時受測試數、import/cache 及本機負載影響，不能拿 baseline 的執行時間
直接推論新版比較快。本輪沒有衡量 1,000 題答題率或硬體吞吐量。

### 提交隔離驗證

提交前將 Git index 的程式、依賴清單與測試匯出至獨立暫存目錄，確認 Python
從該快照載入 Scout，而非原工作目錄。未追蹤的 sidecar、新增 result helper，
以及其他既有檔案中未暫存的變更均不在此快照內。

- 8 個已追蹤或本次新增的測試檔，共 88 項；首輪 87 passed、1 failed，231.65 秒。
- 失敗案例為 `test_model_backed_praison_team_runs_behind_mcp_process`，
  回傳既有 20 秒 MCP timeout。保持相同程式與 timeout，單獨重跑
  `1 passed in 43.17s`；此時間包含測試程序啟動，不是 MCP call latency。
- 提交檢查指出離線 Z.AI fixture 的固定假金鑰，已改成臨時產生的測試值；
  此路徑仍只使用 MockTransport。相關測試 `9 passed in 5.90s`，再執行
  最後一輪完整快照驗證：`88 passed in 23.07s`，0 failed、0 skipped。
- 首次逾時仍保留；本輪未證明逾時的根因是套件、cold start 或主機負載，
  不能因後續通過就刪除這個觀察。
- 快照上的 Ruff、暫存差異檢查與 105 個本機套件 dependency check 均通過。
- 僅暫存主套件與 Admin/Live 的版本差異，未帶入 HTTP MCP console script、
  Admin 的另案 httpx 變更或 intelligence sidecar manifest。

### 真實模型與工具

Live smoke 使用 `openrouter:deepseek/deepseek-v4-flash-0731`。
金鑰只由 server-side `~/.scout/.env` 載入，未寫入結果；沒有修改模型設定。
9 項 live 檢查不等於 9 次模型請求，工具回合及 retry 會增加實際請求數。

- Function tool 回傳並由模型回答 `2.37.0`。
- Structured output 通過 schema，內容包含正確 runtime version。
- MCP 經 `run_stream_events()` 出現工具呼叫、工具回傳，再出現 final result；
  模型回答 `MCP-CP-07`，不是只證明列出了工具。
- Scout traced `scout_web_search` 與 `scout_web_fetch` 都有呼叫/回傳紀錄，
  fetch 實際取得官方頁面 HTTP 200。
- 工具失敗及 `ModelRetry` 能呈現失敗原因，並完成恢復回合。

### 不可誤讀的結果

1. OpenRouter provider-native search 有回覆官方 URL，但兩輪都沒有
   `NativeToolCallPart` / `NativeToolReturnPart`。結果明確標記
   `qualification_scope=provider_transport_only`，不證明實際執行了原生搜尋，
   更不等於答案已通過來源驗證。Scout 的可稽核搜尋/fetch 路徑仍保持啟用。
2. 初輪 smoke 殘留 native search `max_uses=1`，本輪已改為 10，補 regression
   並重新執行全部 27 項 smoke。10 是可用容量，不是強制消耗次數。
3. Praison MCP 使用真實 `AgentTeam`/`Task`，但此 web qualification 的 specialist
   synthesis 是 deterministic replay，沒有 Praison 雲端 LLM 推理。
   Scout Model Gateway 的整合驗證則使用 Pydantic `FunctionModel` fixture。
4. Praison 搜尋取得 AI Upgrade Guide，也混入 Pydantic Validation changelog；
   兩頁內容均被既有 qualification scope 截斷。這能證明搜尋/擷取管線工作，
   不能認定精準找到了 2.37 release notes。Release-specific retrieval quality
   仍需另外用官方 release URL、路徑過濾及內容相關性驗收。
5. 記憶測試只在 pytest 暫存目錄使用虛構資料。沒有啟用 Scout 長期記憶，
   也沒有把候選資料變成 runtime safety truth。

## 新增回歸

- 套件主依賴、smoke extra、Praison extra 與實際存在的 Pi 清單版本一致性。
  Admin/Live 清單必須存在；另案開發的 intelligence 清單若存在也會檢查，
  但本次測試不依賴該尚未提交的檔案。
- Z.AI 三種非標準 finish reason 的非串流/串流，共 6 個 fixture 情境：
  `sensitive -> content_filter`、`model_context_window_exceeded -> length`、
  `network_error -> error`。保留部分回覆與 provider 原始終止原因。
  此測試沒有 live Z.AI 呼叫，也不代表 NVIDIA/OpenRouter 自動套用相同 adapter。
- Praison `Agent`、`Task`、`AgentTeam`、`AgentFlow` import；後者只驗證 import，
  Scout 實際採用的 `AgentTeam`/`Task` 另有 executable workflow/MCP tests。
- `memory=None/False` 不會自行保存資料；明確 opt-in file memory 的兩個 Agent
  不會互相讀到對方測試記憶。
- 原生搜尋 10 次容量與 transport-only 標記。

## 重跑方式

在 repo 根目錄執行；offline pytest 不載入真實 `.env`：

```bash
rtk proxy ./venv/bin/python -m pytest \
  tests/test_pydantic_ai_compat_smoke.py \
  tests/test_pydantic_ai_runtime_compat.py \
  tests/test_praison_runtime_compat.py \
  tests/test_scout_ai_praison_mcp_slice.py \
  tests/test_scout_ai_praison_web_research.py \
  tests/test_scout_ai_praison_background_queue.py \
  tests/test_scout_ai_exp_praison_bridge.py \
  tests/test_scout_ai_nextgen_contracts.py -q

rtk proxy ./venv/bin/python -m scout.cli.pydantic_compat_smoke \
  --live-openrouter --model deepseek/deepseek-v4-flash-0731 \
  --env-file "$HOME/.scout/.env"

rtk proxy ./venv/bin/python tools/scout_ai_praison_web_qualification.py \
  --allowed-domain pydantic.dev \
  --query 'Find the official Pydantic AI changelog and its v2.37.0 release notes.'

rtk proxy uv pip check --python ./venv/bin/python
```

原工作目錄的 92 項測試另含 `test_scout_ai_praison_background_mcp.py` 與
`test_scout_ai_praison_background_mcp_http.py`，這兩個新檔屬於另案 sidecar
開發，不納入本次 commit；上面的重跑命令只使用本次提交可取得的測試。

## 證據與未測範圍

- [最終 27 項 smoke 原始結果](../../artifacts/scout-ai-compatibility/pydantic-237-praison-173-20260903/pydantic-live-final.json)
- [初輪結果，保留作為修正前紀錄](../../artifacts/scout-ai-compatibility/pydantic-237-praison-173-20260903/pydantic-live.json)
- [Praison 真實 MCP/web 結果](../../artifacts/scout-ai-compatibility/pydantic-237-praison-173-20260903/praison-live-web.json)
- [驗證摘要與來源 SHA-256](../../artifacts/scout-ai-compatibility/pydantic-237-praison-173-20260903/verification.json)
- [提交快照驗證與首次逾時紀錄](../../artifacts/scout-ai-compatibility/pydantic-237-praison-173-20260903/staged-verification.json)

未重啟既有長時間運行的服務、未部署 Pi/Hailo、未改安全/硬體行為、未跑完整
1,000 題。Durable smoke 驗證 named-operation 契約，沒有啟動 DBOS、Temporal
或 Prefect engine；AG-UI/CLI 的新功能也不屬於本輪已證明的整合能力。
硬體效能與端到端答題品質需要獨立驗證，不因套件版本提升就宣稱改善。

官方依據：[Pydantic AI 2.37.0 release](https://github.com/pydantic/pydantic-ai/releases/tag/v2.37.0)、
[Z.AI finish reason 修正](https://github.com/pydantic/pydantic-ai/pull/7685)、
[PraisonAI Core 1.7.3](https://pypi.org/project/praisonaiagents/1.7.3/)。
