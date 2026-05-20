# Scout Hardware Runtime Portability Audit

這份 audit 是 hardware-port Slice 1 的部署前盤點。目標是先確認 Scout 哪些模組可以放進
Pi 5 + Docker + `/data/scout` 的 Step 1 runtime-core，哪些模組必須留在 Mac/PC
workstation、optional provider、test-dev 或 ai-experimental 範圍。

中文註釋：這份文件不是部署腳本，也不是要改安全判斷。它只是在真的把 Scout 放到硬體前，
先把移植風險、模組邊界與驗證 ladder 寫清楚。

## 1. Boundary

Slice 1 仍是部署前準備：

- 不連 Pi。
- 不啟動 Docker。
- 不啟動 Ollama。
- 不啟動本地模型。
- 不控制真硬體。
- 不呼叫 live `/safety/*` mutation。
- 不送 outbound。
- 不送 SOS、SMS、satellite。
- 不改 Phase 1 safety decision。
- 不寫 ObservedFact、Brain、IncidentStore 或 review decision。

這些限制保證 portability audit 不會變成隱性部署，也不會把 assistant guardrail、Phase 4
pre-trip planning、runtime outbound、hardware provider control 混在一起。

## 2. Dependency Profiles

| Profile | 中文說明 | Step 1 處理 |
| --- | --- | --- |
| `runtime-core` | Pi field runtime 必須能載入的 deterministic core | 可以進 Docker image |
| `optional-provider` | GNSS、IMU、BLE、LoRa、LTE 等 provider adapter | Step 1 先 fixture/degraded |
| `admin-workstation` | Mac/PC admin、browser、after-action、planning、報表 | 不放進 Step 1 runtime-core |
| `test-dev` | pytest、fixture generator、release checker | 本機/CI 驗證，不要求在 Pi 長駐 |
| `ai-experimental` | local model、Ollama、Coral、Jetson、AI fallback 實驗 | 不把本地模型放進 Step 1 runtime-core |

中文註釋：Step 1 要證明 deterministic Scout runtime 可以在 Pi 上可靠啟動、讀 fixture、
寫 `/data/scout`，不是證明 AI、event bus、衛星或完整 admin workstation 都能跑。

## 3. Module Classification

| Module | Classification | Rationale |
| --- | --- | --- |
| `safety_api.py` | `runtime-core` | Phase 1 API shape，Step 1 需要 health 之外的 fixture ingest surface，但 smoke mutation 必須由 operator 手動決定 |
| `safety_runtime_session.py` | `runtime-core` | deterministic route-progress session，不能改 safety semantics |
| `route_progress.py` | `runtime-core` | L0-L4 評估基礎，必須硬體無關 |
| `safety_models.py` | `runtime-core` | typed Phase 1 state and incident package models |
| `incident_store.py` | `runtime-core` | incident package persistence，需落在 `/data/scout/incidents` |
| `observation_adapter.py` | `runtime-core` | SensorLog/fixture payload normalization，Step 1 可用 fixture |
| `mission_graph.py` | `runtime-core` | mission route/checkpoint structure |
| `phase1_replay_demo.py` | `test-dev` | 可作 smoke command，但不應是長駐 runtime dependency |
| `debug_api.py` | `admin-workstation` | read-only observability surface，Step 1 可由 workstation 讀，不必放進 field runtime |
| `assistant_api.py` | `admin-workstation` | read-only model interpretation，不屬於 Phase 1 safety runtime |
| `assistant_pydantic_provider.py` | `ai-experimental` | cloud/local model provider opt-in，不放進 Step 1 runtime-core |
| `pi_ollama_manual_verification.py` | `ai-experimental` | 只記錄 manual Pi/Ollama artifact，不啟動 Ollama |
| `hardware_readiness_api.py` | `admin-workstation` | fixture-backed readiness projection，不控制 provider |
| `macos_wifi.py` | `optional-provider` | macOS-only，必須留在 provider boundary 或 workstation |
| `visualize_signal.py` | `admin-workstation` | visualization/report helper，不應增加 Pi runtime image weight |
| `admin_api.py` | `admin-workstation` | admin/browser workflow，不屬於 deterministic field runtime baseline |
| `pretrip_*` | `admin-workstation` | Phase 4 planning workspace，不能阻塞 hardware port |

中文註釋：分類不是永久封印。它只是 Step 1 的 include/exclude 準則。等 Pi runtime-core 穩定後，
optional-provider、event bus、AI fallback 才能逐步回來。

## 4. Portability Blockers

目前部署前需要注意：

- `macos_wifi.py` 是 macOS-only，不可被 runtime-core import-time 依賴。
- `PdrSample` 與大型 field capture 不應進 Docker build context 或 commit boundary。
- `Phase 4` pre-trip planning 模組量大，而且有 review/write workflow，應留在
  workstation/admin track。
- visualization/report files 屬於 workstation-only，不應讓 Pi image 變重。
- local model、Ollama、Coral、Jetson、k3s、MQTT、NATS 都不是 Step 1 runtime-core。
- cloud model token 或 local model endpoint 不應是 Scout runtime 啟動條件。
- 不接 k3s、MQTT、NATS、Coral、Jetson。

中文註釋：第一台 Scout machine 的風險不在於缺少 AI，而在於 deterministic runtime 是否
能在斷網、重開機、沒有真硬體 provider 的狀況下仍然啟動並保留證據。
因此 audit 的重點是找出 import-time 依賴、資料根、可寫入目錄、provider 邊界、
fixture smoke 與 release gate 是否足夠清楚。只要某個模組會要求 macOS、雲端 token、
本地模型、特殊硬體或大型資料檔，它就不應該被放進第一版 Pi runtime-core。這樣做可以
讓硬體原型先證明最重要的事情：安全核心能啟動、能讀任務、能保存證據、能在缺少可選
provider 時維持 degraded 狀態，而不是因為周邊功能沒有準備好就整個服務失敗。

## 5. Verification Ladder

部署前本機驗證：

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest \
  tests/test_scout_hardware_prototype_prep.py \
  tests/test_scout_machine_deployment_smoke_runbook.py \
  tests/test_scout_hardware_runtime_portability_audit.py
```

Phase 1 baseline 建議另外跑：

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest \
  tests/test_safety_runtime_session.py \
  tests/test_safety_api.py
```

Release/boundary 建議另外跑：

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python phase2_release_check.py --repo-root /Users/alexwang0315/scout-fusion
```

這些都是 local validation，不連 Pi、不控制真硬體、不呼叫 live `/safety/*` mutation。
真正 Pi smoke 必須等 operator 指定 target host、port、data root 與啟動方式後再手動跑。

## 6. Next Slice

下一個可實作 slice 是 data-root and health contract：

- 定義 `/data/scout` 目錄布局；
- 定義 `/health` 最小欄位；
- 確認 incident store path 會落在 mounted data root；
- 用 temporary data root 做本機測試；
- 仍不啟動本地模型、不接 event bus、不接真 hardware provider。

中文註釋：下一步可以開始做最小 Pi runtime health contract，但那會更接近可部署 runtime。
若要真的跑 Docker 或對 Pi 發 curl，需要 operator 明確提供目標與允許手動 smoke。
