# Milestone 10 Cross-Surface AI Assistant Runbook

這份 runbook 是 Scout Milestone 10: Cross-Surface AI Assistant Guardrails 的
readiness 操作筆記。它只描述 assistant 如何用在 admin/debug/pretrip/future
hardware readiness 介面，不是 Phase 1 safety runtime、Phase 2 Brain writeback、
Phase 4 planning approval、outbound transport 或 hardware control 的操作手冊。

Milestone 10 guardrail and UI slices are complete through the shared assistant
module, after-action live UI, fixture-backed hardware readiness, red-team
boundary tests, and read-only `AssistantObservability` metadata. 後續可以增加更
細的 context projection，但不可放寬本 runbook 的 read-only boundary。

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
    "model_name": "qwen2.5:0.5b",
    "base_url": "http://127.0.0.1:11434/v1",
    "token_id": "pi-local-ollama-ref"
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

### Cloud-to-Local Failover Guardrail

這個 failover 只適用於明確 opt-in 的 Pi field profile，不是 Mac/dev 預設模式。
Mac/dev default remains mock or cloud-only；若不需要本地模型，設定檔應把
`fallback_to_local_on_error` 設為 `false`，或直接使用 `mock provider`。

Pi local model evidence 來自 `docs/specs/pi5-local-ai-runtime-experiment.md`：
`qwen2.5:0.5b` 可作為低頻 offline fallback interpretation，但不是 safety
authority。啟用 `fallback_to_local_on_error=true` 時仍必須遵守：

- max local concurrency = 1；
- short timeout, initially 6-10s；
- no unbounded queue；
- discard stale model requests；
- 回答標示 `model_profile_used`、`failover_reason`、`local_model_name`；
- 不把 local output 寫成 ObservedFact、Brain、review decision 或 IncidentStore；
- never let local AI directly change L0-L4 safety state；
- readiness check、browser smoke、runbook 驗收不得啟動 Ollama、Pi、Docker 或
  local model listener。

Milestone 10.2 Slice 2 hardening 已用 mocked runners 驗證：

- cloud run failure 會 fallback 到 local runner，並回報
  `model_profile_used=local`、`failover_reason=primary_run_error:*`、
  `local_model_name=*`；
- local fallback 同時只允許一個 active request，第二個 overlapping request 會以
  `LocalFallbackBusy` / `local_busy:discard_stale_request` fail fast，不進入
  unbounded queue；
- local runner failure 會以 `local_run_error:*` 進入 `/assistant/query` 的 safe
  read-only failure response；
- 這些測試不啟動本地模型、不呼叫 Ollama、不啟動 Pi/Docker/hardware provider。

Milestone 10.2 Slice 12 adds the fixed-schema offline fallback provider
contract:

- `assistant_offline_fallback_contract.py` defines
  `ScoutOfflineFallbackInterpretation`。
- fixed schema version: `scout.offline_fallback.v1`。
- fixed prompt id: `scout.offline_fallback.fixed_schema.v1`。
- local fallback output must set `read_only=true`、
  `model_interpretation=true`、`safety_authority=false`、
  `phase1_state_change_allowed=false`、`observed_fact_write_allowed=false`、
  `outbound_action_allowed=false`、`hardware_control_allowed=false`。
- `FallbackPydanticAIRunner` 可在 local fallback path enforce schema，並回報
  `fixed_schema_offline_fallback_contract`。
- invalid schema 會成為 `local_schema_validation_error:*` safe provider
  failure，不是 safety/runtime action。
- 這些測試仍使用 mocked runners；不啟動本地模型、不呼叫 Ollama、不啟動
  Pi/Docker/hardware provider、不呼叫 `/safety/*` mutation、不寫 Scout state。

### Milestone 10.2 Slice 3: Pi Field Profile Status + Manual Failover Runbook

Slice 3 只增加 status/runbook guardrail，不啟動本地模型，也不讓 UI 或 status endpoint
切換 provider。`SCOUT_RUNTIME_PROFILE=pi-field` 只是一個明確標示 Pi field profile
的 opt-in runtime profile，manual Pi/Ollama verification 屬於 hardware prototype
track，not part of the assistant readiness gate。

手動檢查範例，只有在你已經自己啟動 Pi/Ollama 服務時才執行：

```bash
export SCOUT_RUNTIME_PROFILE=pi-field
curl --max-time 2 http://127.0.0.1:11434/api/tags
curl --max-time 5 http://127.0.0.1:9110/assistant/status
```

`/assistant/status` 應回報：

- `runtime_profile=pi-field`；
- `local_fallback_mode=pi_field_manual_opt_in`；
- `manual_verification_required=true`；
- `local_fallback_max_concurrency=1`；
- `readiness_starts_local_model=false`；
- `local_model_listener_required_for_readiness=false`；
- `status_model_switch_allowed=false`。

Mac/dev profile 若載入同一份 fallback config，`/assistant/status` 應顯示
`local_fallback_mode=configured_not_pi_field`，表示設定存在，但目前不是 Pi field
profile。這不得被解讀為自動啟用本地模型，也不得作為 readiness gate 的必要條件。

Slice 4 的手動觀測 artifact 放在 `docs/admin/pi-ollama-manual-verification.md`。
它只記錄 operator-observed Pi/Ollama status 與 latency，不納入 assistant readiness
gate，也不啟動 Ollama、本地模型或任何 hardware service。

### Milestone 10.2 Slice 10: Manual Pi/Ollama Artifact Chain

manual Pi/Ollama artifact chain 已整理到
`docs/admin/pi-ollama-manual-verification.md`，並保留在 hardware prototype track。
這段 cross-surface runbook 只做索引與邊界提醒，不把手動 artifact 接進 assistant API、
runtime 或 readiness gate。

Artifact chain:

- `docs/admin/pi-ollama-manual-verification.md`：完整手動驗證 artifact、schema、
  index、CLI 與 operator checklist 說明。
- `pi_ollama_manual_verification.py`：離線 Pydantic schema、summary formatter、
  optional append-only index schema。
- `tests/fixtures/hardware/pi_ollama_manual_verification.example.json`：optional
  operator-recorded result fixture。
- `tests/fixtures/hardware/pi_ollama_manual_verification.index.example.json`：optional
  append-only index fixture。
- `pi_ollama_manual_verification_cli.py`：read-only CLI renderer，只接受 `--result`
  或 `--index` 並輸出 summary stdout。
- operator checklist：人工確認 result/index/CLI/readiness observation 都沒有越界。

Manual chain boundaries:

- not part of the assistant readiness gate。
- read-only model interpretation。
- 不啟動本地模型。
- 不啟動 Ollama。
- 不呼叫 `/assistant/*`。
- 不呼叫 `/safety/*` mutation。
- 不寫 ObservedFact。
- 不寫 Phase 2 Brain。
- 不寫 IncidentStore。
- 不送 outbound。
- 不控制 hardware。
- 不控制 provider。
- 不讀取 token value。
- 不寫 Scout state。

### Milestone 10.2 Slice 11: Pi/Ollama Hardware Experiment Assets

The hardware experiment assets are now repo-owned and test-covered, but they
remain manual prototype tools:

- `docker-compose.pi.ai.yml` defines `scout-ollama` behind the
  `ai-experimental` Compose profile.
- `tools/pi_ollama_stress.py` probes an already-running Ollama listener and
  records latency, temperature, and load diagnostics as stdout JSONL.

Boundaries:

- not part of the assistant readiness gate。
- read-only model interpretation。
- 不啟動本地模型 from readiness checks。
- 不啟動 Ollama from readiness checks。
- 不呼叫 `/assistant/*`。
- 不呼叫 `/safety/*` mutation。
- 不寫 ObservedFact。
- 不寫 Phase 2 Brain。
- 不寫 IncidentStore。
- 不送 outbound。
- 不控制 hardware。
- 不控制 provider。

## 3. API Boundary

Assistant endpoint：

```text
POST /assistant/query
GET /assistant/status
```

`POST 只是查詢 body`，不是 mutation。第一版只允許 query body 帶入 surface、
question、context ref、selected event/artifact 或 project id。不得新增
`PUT`、`PATCH`、`DELETE` assistant endpoint，也不得接受 `approve`、`send`、
`write_fact`、`mutate`、`control_provider` 這類 action-like 欄位。

`GET /assistant/status` 只回 provider/config 狀態，例如 provider class、
startup status、cloud-only/local fallback 設定與 context budget。它不得回傳
token value、API key 或 secret payload。

`POST /assistant/query` 回應可帶 `AssistantObservability`。這是非權威、不可寫入
的 debug metadata，只能描述 provider class、source count、context size、
latency class 與 safe failure 狀態。它不是 IncidentStore、Brain、ObservedFact、
review decision、outbound 或 hardware control log。

## 4. Surface Boundaries

Debug/admin/pretrip/hardware readiness 可以讀不同 context，但每個 context adapter 都必須
read-only、bounded、auditable。

| Surface | 可以回答 | 不可以做 |
| --- | --- | --- |
| debug | timeline、L0-L4 transition、provider degraded、mock outbound 狀態 | 不可寫 Phase 1，不可呼叫 `/safety/*` mutation，不可改 debug log |
| admin after-action | evidence tree、incident refs、adapter preview | 不可改 IncidentStore，不可寫 Phase 2，不可重寫歷史 package |
| pretrip | source/candidate/review/readiness/departure state | 不可寫 Phase 4，不可接受或拒絕 candidate，不可核准 departure |
| hardware readiness | provider health fixture、sample replay、mock queue | 不可控制 hardware，不可開真 transport，不可部署 Pi/Docker |

Current admin surfaces:

- `/admin/debug`：runtime debug timeline assistant。
- `/admin/pretrip`：Phase 4 planning/review context assistant。
- `/admin`：after-action evidence assistant。
- `/admin/hardware-readiness`：fixture-backed provider dry-run assistant。

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
  tests/test_hardware_readiness_api.py \
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
