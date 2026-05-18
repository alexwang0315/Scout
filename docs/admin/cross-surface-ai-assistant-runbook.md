# Milestone 10 Cross-Surface AI Assistant Runbook

這份 runbook 是 Scout Milestone 10: Cross-Surface AI Assistant Guardrails 的
readiness 操作筆記。它只描述 assistant 如何用在 admin/debug/pretrip/future
hardware readiness 介面，不是 Phase 1 safety runtime、Phase 2 Brain writeback、
Phase 4 planning approval、outbound transport 或 hardware control 的操作手冊。

Milestone 10 initial guardrail slice status: complete. 後續可以增加更好的 UI
reuse、after-action context 或 hardware-readiness fixtures，但不可放寬本 runbook
的 read-only boundary。

## 1. Default Mode

預設 provider 必須是 deterministic `mock provider`：

```bash
SCOUT_AI_ASSISTANT_PROVIDER=mock
```

`mock provider` 不做網路呼叫、不讀 secrets、不送 outbound、不控制 provider 或
hardware。它只回傳固定、可測試的 `read-only model interpretation`，用來驗證
request/response contract、surface boundary、sources 與 limitations。

中文邊界：

- AI 回答是 `ModelInterpretation`，不是 `ObservedFact`。
- 不可寫 Phase 1 safety runtime、route progress、risk rule、L0-L4 state。
- 不可寫 Phase 2 Brain、BrainFileStore、ObservedFact writer 或任何 writeback。
- 不可寫 Phase 4 planning candidate、review decision、departure approval 或 runtime handoff。
- 不可送 outbound、SOS、SMS、satellite、mock-to-live transport。
- 不可控制 hardware、sensor、provider、Pi、Docker、radio 或 modem。

## 2. Pydantic AI Opt-In

`Pydantic AI opt-in` 必須同時符合 opt-in mount 與 provider opt-in：

```bash
SCOUT_AI_ASSISTANT_ENABLED=1
SCOUT_AI_ASSISTANT_PROVIDER=pydantic_ai
SCOUT_AI_ASSISTANT_TIMEOUT_SECONDS=8
SCOUT_AI_ASSISTANT_MAX_CONTEXT_CHARS=12000
SCOUT_AI_ASSISTANT_CONFIG_PATH=/secure/local/scout-assistant-models.json
```

沒有 `SCOUT_AI_ASSISTANT_ENABLED=1` 時，assistant route 不應 mount。沒有明確設定
`SCOUT_AI_ASSISTANT_PROVIDER=pydantic_ai` 時，provider 必須回到 `mock provider`。
Pydantic AI provider 必須和 `/navigate` 分開；它只能解釋 bounded context，不可變成
PDR、route progress、risk transition、review approval 或硬體控制流程的一部分。

### External Model Config

server startup 會讀取 `SCOUT_AI_ASSISTANT_CONFIG_PATH` 指向的外部 JSON 設定檔。這個
設定檔必須同時提供 `cloud_model` 與 `local_model` 兩組 model profile：

```json
{
  "active_profile": "cloud",
  "cloud_model": {
    "profile": "cloud",
    "model_name": "openrouter/model-name",
    "base_url": "https://openrouter.ai/api/v1",
    "token_id": "cloud-token-ref",
    "token_env_var": "OPENROUTER_API_KEY"
  },
  "local_model": {
    "profile": "local",
    "model_name": "llama3.1:8b",
    "base_url": "http://127.0.0.1:11434/v1",
    "token_id": "local-model-ref"
  },
  "timeout_seconds": 8,
  "max_context_chars": 12000,
  "connect_on_startup": true,
  "fallback_to_local_on_error": true
}
```

`token_id` 是 token reference，不是 secret。實際 secret 應用 `token_env_var` 指向
環境變數。server 啟動 assistant provider 時會先嘗試 cloud model connection；若
cloud 通訊中斷、逾時或初始化失敗，provider 會 fallback to local model。fallback
仍然只能輸出 `read-only model interpretation`，不可因此打開 action、review、
outbound 或 hardware control。

## 3. API Boundary

Assistant endpoint：

```text
POST /assistant/query
```

`POST 只是查詢 body`，不是 mutation。第一版只允許 query body 帶入 surface、
question、context ref、selected event/artifact 或 project id。不得新增
`PUT`、`PATCH`、`DELETE` assistant endpoint，也不得接受 `approve`、`send`、
`write_fact`、`mutate`、`control_provider` 這類 action-like 欄位。

## 4. Surface Boundaries

Debug/admin/pretrip/hardware readiness 可以讀不同 context，但每個 context adapter 都必須
read-only、bounded、auditable。

| Surface | 可以回答 | 不可以做 |
| --- | --- | --- |
| debug | timeline、L0-L4 transition、provider degraded、mock outbound 狀態 | 不可寫 Phase 1，不可呼叫 `/safety/*` mutation，不可改 debug log |
| admin after-action | evidence tree、incident refs、adapter preview | 不可改 IncidentStore，不可寫 Phase 2，不可重寫歷史 package |
| pretrip | source/candidate/review/readiness/departure state | 不可寫 Phase 4，不可接受或拒絕 candidate，不可核准 departure |
| hardware readiness | provider health fixture、sample replay、mock queue | 不可控制 hardware，不可開真 transport，不可部署 Pi/Docker |

## 5. Readiness Check

Focused assistant suite：

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest \
  tests/test_assistant_model_config.py \
  tests/test_assistant_models.py \
  tests/test_assistant_provider.py \
  tests/test_assistant_pydantic_provider.py \
  tests/test_assistant_context.py \
  tests/test_assistant_api.py \
  tests/test_assistant_page.py \
  tests/test_assistant_readiness_check.py
```

Focused command：

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_assistant_readiness_check.py
```

Gate command：

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python assistant_readiness_check.py --pretty
```

Readiness check 會檢查：

- 必要檔案是否存在；
- `docs/specs/scout-cross-surface-ai-assistant.md` 是否保留 Milestone 10 guardrails；
- assistant foundation 是否沒有 forbidden tokens，例如 `SafetyRuntimeSession`、
  `BrainFileStore`、`IncidentStore`、ObservedFact writer/writeback、`requests`、
  `httpx`、`urllib`、`socket`、`twilio`、`@router.put`、`@router.patch`、
  `@router.delete`；
- `server.py` 是否只用 `SCOUT_AI_ASSISTANT_ENABLED` / `SCOUT_AI_ASSISTANT_PROVIDER`
  / `SCOUT_AI_ASSISTANT_CONFIG_PATH` 做 opt-in mount，且預設仍是 `mock provider`；
- 本 runbook 是否保留 mock provider、Pydantic AI opt-in、read-only boundary、
  不可寫 Phase 1、不可寫 Phase 2、不可寫 Phase 4、不可送 outbound、不可控制 hardware
  的操作語意。

如果 gate 失敗，先看輸出的 `failed_checks` 和 `missing_required_artifacts`。不要用
readiness check 自動修改 runtime；它只是 acceptance gate，不是修復工具。
