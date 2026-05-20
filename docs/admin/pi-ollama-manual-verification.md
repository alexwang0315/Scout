# Pi/Ollama Manual Verification Artifact

這份文件是 Milestone 10.2 Slice 4 的 manual Pi/Ollama verification artifact。
它只屬於 hardware prototype track，用來記錄操作者已經手動啟動 Pi/Ollama 之後的
assistant fallback 觀測結果。它不是 Scout safety runtime、不是 Phase 1 runtime
gate、不是 Phase 2 Brain 寫入流程、不是 Phase 4/4.5 review/departure 流程，也不是
assistant readiness gate。

重要邊界：

- not part of the assistant readiness gate。
- must stay outside the assistant readiness gate。
- 不納入 assistant_readiness_check.py。
- 不啟動本地模型。
- 不啟動 Ollama。
- 不啟動 Pi、Docker、k3s、MQTT、NATS、Coral 或 Jetson。
- 不讀取 token value。
- 不切換 global provider state，也不提供 UI model switch。
- local output 只能是 read-only model interpretation。

這份 artifact 的目的，是讓人可以把 Pi 上已經存在的 Ollama service 當成手動觀測對象，
記錄 latency、status 與安全邊界是否仍成立。它不負責啟動任何 service，也不要求 Mac/dev
環境有本地模型。

## 1. Manual-Only Preconditions

只有在下列條件都已由操作者手動確認時，才可以做本文件的檢查：

- Pi 端已經由操作者手動啟動 Scout runtime 與 Ollama。
- Ollama 已經有 `qwen2.5:0.5b` 或當次測試指定的 tiny local model。
- Scout server 已由操作者手動啟動，且 assistant endpoint 已 opt-in。
- 外部 assistant model config 已由操作者設定，且包含
  `fallback_to_local_on_error=true`。
- 這不是 release gate，也不是自動化 readiness gate。

範例環境變數，只描述手動執行時的形狀：

```bash
export SCOUT_RUNTIME_PROFILE=pi-field
export SCOUT_AI_ASSISTANT_ENABLED=1
export SCOUT_AI_ASSISTANT_PROVIDER=pydantic_ai
export SCOUT_AI_ASSISTANT_CONFIG_PATH=/Users/alexwang0315/.scout/assistant-models.json
```

`SCOUT_AI_ASSISTANT_CONFIG_PATH` 指向外部設定檔，不應把 token value 寫進 repo。設定檔可
包含 `token_id` 或 `token_env_var` reference，但手動紀錄只能保存 reference metadata，
不可保存 secret value。

## 2. Safe Manual Command Shape

以下命令只適用於已經手動啟動 service 的環境。不要讓 CI、readiness gate 或 browser
smoke 自動執行這些命令。

先確認 Ollama listener 已存在：

```bash
curl --max-time 2 http://127.0.0.1:11434/api/tags
```

確認 assistant status 不會切換 provider，也不會要求 readiness 啟動本地模型：

```bash
curl --max-time 5 http://127.0.0.1:9110/assistant/status
```

手動送一個 read-only query，只問資料狀態或為什麼系統如此判斷：

```bash
curl --max-time 10 -X POST http://127.0.0.1:9110/assistant/query \
  -H "Content-Type: application/json" \
  -d '{
    "surface": "debug",
    "question": "請用一句話說明本地 fallback 模型在 Scout 斷線時的角色。"
  }'
```

這個 query 仍然只是查詢 body，不是 mutation。回答必須保留
`read-only model interpretation` 標示。

## 3. Manual Result Template

每次手動檢查可以記錄一份 `manual_only_pi_ollama_verification` 結果。建議保存到外部
operator notebook 或臨時實驗記錄，不要把 secret 或大型 raw output 放進 repo。

```json
{
  "artifact_type": "manual_only_pi_ollama_verification",
  "timestamp": "2026-05-19T00:00:00+08:00",
  "runtime_profile": "pi-field",
  "assistant_provider": "pydantic_ai",
  "config_path_ref": "/Users/alexwang0315/.scout/assistant-models.json",
  "fallback_to_local_on_error": true,
  "ollama_tags_checked": true,
  "local_model_name": "qwen2.5:0.5b",
  "operator_observed_latency_ms": 0,
  "assistant_status": {
    "local_fallback_mode": "pi_field_manual_opt_in",
    "manual_verification_required": true,
    "local_fallback_max_concurrency": 1,
    "readiness_starts_local_model": false,
    "local_model_listener_required_for_readiness": false,
    "status_model_switch_allowed": false,
    "token_values_exposed": false
  },
  "assistant_response": {
    "model_profile_used": "local",
    "failover_reason": "manual_observation",
    "read_only": true,
    "model_interpretation": true
  },
  "boundary_observation": {
    "phase1_state_changed": false,
    "observed_fact_written": false,
    "phase2_brain_written": false,
    "incident_store_written": false,
    "review_decision_changed": false,
    "outbound_sent": false,
    "hardware_controlled": false
  }
}
```

`operator_observed_latency_ms` 是人工觀測值或外部計時值，不是 Scout runtime 事實。
如果保存結果，必須把它標成 manual verification evidence，不能把它當成 ObservedFact、
DerivedMeasurement、IncidentStore entry 或 review decision。

## 4. Pass Criteria

手動觀測可以視為通過，只表示這次硬體原型檢查沒有越界：

- `/assistant/status` 顯示 `runtime_profile=pi-field`。
- `/assistant/status` 顯示 `local_fallback_mode=pi_field_manual_opt_in`。
- `/assistant/status` 顯示 `manual_verification_required=true`。
- `/assistant/status` 顯示 `token_values_exposed=false`。
- `/assistant/status` 顯示 `status_model_switch_allowed=false`。
- 回答仍標示 read-only model interpretation。
- 記錄中 `phase1_state_changed=false`。
- 記錄中 `observed_fact_written=false`。
- 記錄中 `outbound_sent=false`。
- 記錄中 `hardware_controlled=false`。

## 5. Stop Criteria

如果出現下列任一狀況，應停止 assistant fallback 擴展，先回到 spec 或 provider hardening：

- status 或 UI 可以切換 model provider。
- status 回傳 token value、API key 或 secret payload。
- local fallback 被 Mac/dev profile 靜默視為 field-approved path。
- assistant 回答宣稱可以改變 L0-L4 safety state。
- assistant 回答被寫入 ObservedFact、Phase 2 Brain、IncidentStore 或 review decision。
- assistant query 觸發 outbound、SOS、SMS、satellite、provider control 或 hardware control。
- readiness gate、browser smoke 或 CI 嘗試啟動 Ollama listener。

## 6. Explicit Non-Mutations

本文件不授權任何 Scout 狀態變更：

- 不呼叫 `/safety/*` mutation。
- 不改 Phase 1 safety decision。
- 不寫 ObservedFact。
- 不寫 Phase 2 Brain。
- 不寫 IncidentStore。
- 不接受或拒絕 pretrip candidate。
- 不改 HumanReview。
- 不改 review decision。
- 不送 outbound message。
- 不接真 SOS、真簡訊或真衛星。
- 不控制 hardware。
- 不控制 provider。
- 不核准 departure。
- 不產生 Final MissionGraph。

## 7. Focused Verification

本 slice 的自動測試只驗證文件邊界：

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_pi_ollama_manual_verification_doc.py
```

整體 assistant readiness 仍可跑：

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python assistant_readiness_check.py --pretty
```

但 `docs/admin/pi-ollama-manual-verification.md` 不應成為
`assistant_readiness_check.py --pretty` 的 required artifact。這份文件可以輔助手動 Pi
硬體原型驗證；它不應讓沒有 Pi/Ollama 的開發環境失敗，也不應啟動任何 local model
listener。

## 8. Milestone 10.2 Slice 5 Schema And Example Fixture

Milestone 10.2 Slice 5 adds `pi_ollama_manual_verification.py` and
`tests/fixtures/hardware/pi_ollama_manual_verification.example.json` as an
optional operator-recorded fixture path. 這個 fixture 只是把人工觀測到的 Pi/Ollama
結果變成可驗證 JSON，不是 readiness gate、不是 API payload、不是 Scout runtime
state，也不是 ObservedFact。

Slice 5 的 schema 要求：

- `artifact_type=manual_only_pi_ollama_verification`。
- `runtime_profile=pi-field`。
- `assistant_provider=pydantic_ai`。
- `fallback_to_local_on_error=true`。
- `ollama_tags_checked=true`。
- `operator_observed_latency_ms` 只能是人工或外部計時觀測。
- `token_values_exposed=false`。
- `status_model_switch_allowed=false`。
- `phase1_state_changed=false`。
- `observed_fact_written=false`。
- `outbound_sent=false`。
- `hardware_controlled=false`。

`pi_ollama_manual_verification.py` 只做離線 JSON parsing 與 Pydantic validation。
它不得呼叫 network，不得啟動 Ollama，不得讀取 token value，不得呼叫 `/safety/*`
mutation，不得寫 Phase 1、Phase 2 Brain、IncidentStore、HumanReview、pretrip review、
outbound 或 hardware/provider state。

Slice 5 focused test：

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest \
  tests/test_pi_ollama_manual_verification_result.py
```

`pi_ollama_manual_verification.example.json` 是 optional operator-recorded fixture，
not part of the assistant readiness gate。它可以作為人工 Pi 實驗的格式範例，但不應讓
沒有 Pi/Ollama 的開發環境失敗。

## 9. Milestone 10.2 Slice 6 Summary Formatter

Milestone 10.2 Slice 6 adds `format_pi_ollama_manual_verification_summary` as a
small formatter for validated manual results. It turns the optional
operator-recorded fixture into a bounded text report headed
`Manual Pi/Ollama verification summary`.

這個 formatter 只接受已通過 `pi_ollama_manual_verification.py` schema 的資料。它不讀
外部 config、不輸出 `SCOUT_AI_ASSISTANT_CONFIG_PATH`、不輸出 `token_id` 或
`token_env_var`、不呼叫 network、不啟動 Ollama、不啟動本地模型，也不寫 Scout state。

摘要必須保留：

- `runtime_profile=pi-field`。
- `assistant_provider=pydantic_ai`。
- `local_model_name=qwen2.5:0.5b`。
- `operator_observed_latency_ms=*`。
- `readiness_starts_local_model=false`。
- `local_model_listener_required_for_readiness=false`。
- `status_model_switch_allowed=false`。
- `token_values_exposed=false`。
- `phase1_state_changed=false`。
- `observed_fact_written=false`。
- `outbound_sent=false`。
- `hardware_controlled=false`。

這份 summary 是人工驗證報告，不是 ObservedFact、IncidentStore、Phase 2 Brain、
HumanReview、pretrip review、outbound log 或 hardware/provider control log；仍然是
read-only model interpretation 的旁路說明，not part of the assistant readiness gate。

## 10. Milestone 10.2 Slice 7 Optional Index

Milestone 10.2 Slice 7 adds `PiOllamaManualVerificationIndex` and
`tests/fixtures/hardware/pi_ollama_manual_verification.index.example.json` as an
optional append-only index for multiple operator-recorded Pi/Ollama experiment
references.

這個 index 只能保存 reference 與小型摘要欄位：

- `artifact_type=manual_only_pi_ollama_verification_index`。
- `index_version=1`。
- `summary_ref=*`。
- `fixture_path=tests/fixtures/hardware/*.json`。
- `operator_observed_latency_ms=*`。
- `read_only=true`。
- `model_interpretation=true`。
- `phase1_state_changed=false`。
- `observed_fact_written=false`。
- `outbound_sent=false`。
- `hardware_controlled=false`。

這個 index 不得嵌入 `raw_model_output`，不得保存 absolute path、token value、API key、
bearer string、external config path 或大型 transcript。它也不得成為
assistant_readiness_check.py 的 required path；沒有 Pi/Ollama 的 dev environment 不應因為
缺這份 index 而失敗。

`summarize_pi_ollama_manual_verification_index` 只把 validated index 轉成
`Manual Pi/Ollama verification index summary`。它不讀 fixture 內容、不呼叫 network、
不啟動本地模型、不呼叫 `/assistant/*` 或 `/safety/*`，也不寫 Scout state。

## 11. Milestone 10.2 Slice 8 Read-Only CLI Renderer

Milestone 10.2 Slice 8 adds `pi_ollama_manual_verification_cli.py` as a
read-only CLI renderer for the optional manual result and optional append-only
index files.

Result summary:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python pi_ollama_manual_verification_cli.py \
  --result tests/fixtures/hardware/pi_ollama_manual_verification.example.json
```

Index summary:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python pi_ollama_manual_verification_cli.py \
  --index tests/fixtures/hardware/pi_ollama_manual_verification.index.example.json
```

`--result` 與 `--index` 互斥，一次只能讀一種 input。這個 CLI 只把已驗證 JSON 轉成
summary stdout，不寫檔、不呼叫 `/assistant/*`、不呼叫 `/safety/*` mutation、不啟動
Ollama、不啟動本地模型、不控制 hardware/provider，也 not part of the assistant
readiness gate。

## 12. Milestone 10.2 Slice 9 Operator Checklist

這份 operator checklist 用來把 Slice 5 result fixture、Slice 7 optional append-only
index、Slice 8 read-only CLI renderer 串成一個人工檢查流程。它不是自動化 gate，也
not part of the assistant readiness gate。

Checklist record shape:

```json
{
  "checklist_type": "manual_pi_ollama_operator_checklist",
  "checked_by_operator": "operator-id-or-initials",
  "validate_result_fixture": true,
  "validate_optional_index": true,
  "run_read_only_cli_renderer": true,
  "readiness_check_observed_only": true,
  "no_local_model_started_by_checklist": true,
  "no_scout_state_written": true
}
```

Operator steps:

- validate result fixture：執行 `tests/test_pi_ollama_manual_verification_result.py`。
- validate optional append-only index：執行 `tests/test_pi_ollama_manual_verification_index.py`。
- run read-only CLI renderer：用 `--result` 或 `--index` 只輸出 summary stdout。
- 可觀察 `assistant_readiness_check.py --pretty`，但不得把 manual result/index/CLI 加入
  required paths。
- 確認 checklist 沒有啟動 Ollama、沒有啟動本地模型、沒有讀取 token value、沒有寫
  Scout state。

這個 checklist 必須繼續保留：

- read-only model interpretation。
- 不呼叫 `/safety/*` mutation。
- 不改 Phase 1 safety decision。
- 不寫 ObservedFact。
- 不寫 Phase 2 Brain。
- 不寫 IncidentStore。
- 不接受或拒絕 pretrip candidate。
- 不改 HumanReview。
- 不送 outbound message。
- 不控制 hardware。
- 不控制 provider。
- 不寫 Scout state。

## 13. Milestone 10.2 Slice 11 Hardware Experiment Assets

Milestone 10.2 Slice 11 promotes the local Pi/Ollama hardware experiment assets
from loose operator files into repo-owned, test-covered artifacts:

- `docker-compose.pi.ai.yml`：optional `scout-ollama` service，必須用
  `ai-experimental` Compose profile 才會啟動。
- `tools/pi_ollama_stress.py`：manual stress probe，只連到 already-running
  Ollama listener，輸出 JSONL latency / temperature / load diagnostics。

Safe manual command shape:

```bash
docker compose -f docker-compose.pi.ai.yml --profile ai-experimental up -d
/Users/alexwang0315/scout-fusion/venv/bin/python tools/pi_ollama_stress.py \
  --url http://127.0.0.1:11434/api/generate \
  --model qwen2.5:0.5b \
  --duration-s 180 \
  --workers 4
```

Slice 11 boundaries:

- not part of the assistant readiness gate。
- read-only model interpretation。
- 不啟動本地模型 from readiness checks。
- 不呼叫 `/safety/*` mutation。
- 不呼叫 `/assistant/*`。
- 不寫 ObservedFact。
- 不寫 Phase 2 Brain。
- 不寫 IncidentStore。
- 不送 outbound message。
- 不控制 hardware。
- 不控制 provider。
- 不寫 Scout state。

Focused verification:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest \
  tests/test_pi_ollama_hardware_experiment_assets.py
```
