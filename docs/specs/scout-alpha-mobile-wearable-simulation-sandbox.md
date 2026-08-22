# Scout Alpha Mobile/Wearable Simulation Sandbox 主規格

Status: **WORKING PROTOTYPE / local single-operator only**
Version: `v0.1`
Last updated: `2026-07-21`
Canonical document: `docs/specs/scout-alpha-mobile-wearable-simulation-sandbox.md`

## 1. 文件定位與權責

本文件是 Scout Alpha 手機／穿戴裝置模擬沙箱的主規格，集中說明設計目的、
目前可執行能力、資料契約、API、操作流程、artifact lineage、安全邊界、驗收
方式與產品化缺口。

既有文件不會被本文件取代或刪除，而是保留各自的專屬責任：

- [Runtime Multi-Gate Safety Reducer](scout-runtime-multi-gate-safety-reducer.md)
  保留跨系統 safety reducer、Phase 1 與 Emergency Mobile 的安全契約。
- [Workspace Agent Tool Spec](scout-ai-workspace-agent-tool-spec.md)
  保留實際 workspace 執行紀錄與 artifact evidence。
- [Alpha Sandbox Operator UI](../emergency/scout-alpha-sandbox-v0.html)
  是瀏覽器可見的 operator surface。
- [Emergency Mobile Approval v0](../emergency/scout-emergency-mobile-approval-v0.html)
  保留前一代 approval／Living UI 的設計脈絡。
- Typed models、測試與 artifact schemas 是目前 executable contract；若它們與本
  文件不一致，應在同一變更中修正規格或程式，不可靜默選擇其中一方。

本文件記錄的是 Alpha prototype 的 intended contract，不宣稱已完成正式 runtime
或產品化。

## 2. 目標與非目標

### 2.1 目標

沙箱必須能在沒有真實登山者、真實穿戴裝置或真實緊急傳送的情況下，忠實模擬
Alpha 使用架構的大部分輸入與狀態變化：

1. 以歷史 GPX 模擬使用者沿路線移動。
2. 產生手機與穿戴裝置的 SensorLogger wire-shape 訊息。
3. 透過真實 MQTT protocol loopback 或 deterministic direct feed 進入相同 observer
   boundary。
4. 模擬網路、封包、GNSS、電量、裝置與感測器故障。
5. 執行六個 runtime safety gates 的 shadow replay。
6. 在高於 L0 時產生 candidate alert、人工 approval、sandbox transport attempt 與
   correlated simulated receipt。
7. 讓 operator 從 Living projection 看到完整、可追溯的因果鏈。
8. 產生可重現、可驗證且不能冒充 runtime safety truth 的 artifacts。

### 2.2 非目標

v0.1 不提供：

- 真實遠端手機 App 或真實穿戴裝置連線。
- production MQTT broker、SMS、衛星、LoRaWAN 或其他 outbound transport。
- `/safety/*` 呼叫或 Phase 1 L0-L4 state mutation。
- 硬體控制、麥克風、喇叭或 GNSS hardware control。
- live CWA weather；`weather_exposure` 是 deterministic synthetic overlay。
- 醫療診斷或由單一生理數值直接推導危險結論。
- LAN／Internet operator authentication、正式授權或多租戶隔離。
- transactional crash recovery 或 hostile-filesystem integrity guarantee。

## 3. 目標部署模型與目前原型

### 3.1 Alpha 目標部署模型

Alpha 的角色分工是：

- Scout 硬體與軟體常駐機房，以伺服器方式運行。
- 使用者攜帶一支手機與一個或多個穿戴裝置。
- 手機與穿戴裝置透過 MQTT 或後續等價的受控 transport 回傳位置、活動、裝置、
  感測與互動事件。
- Scout 透過網路提供手機 UI、文字／語音雙向互動及 operator-facing Living
  projection。
- Deterministic runtime 負責 schema、permission、execution、persistence、hash、
  receipt 與 effect enforcement；模型只能說明或提出 candidate。

### 3.2 v0.1 真正證明的範圍

目前原型在同一台主機內模擬遠端裝置資料流：

- GPX、手機訊息與穿戴訊息都是 synthetic replay。
- `loopback_mqtt_broker` 使用真實 MQTT 3.1.1 封包，但只綁定
  `127.0.0.1:0`。
- `broker_connection_verified=true` 只證明本機 broker/client roundtrip。
- UI 是 mobile-responsive operator console，不是真實 field phone application。
- approval 與 receipt 只驗證 sandbox lineage；沒有 transport 或 delivery。

因此目前狀態是 `WORKING PROTOTYPE`，不是 remote-device integration proof，也不是
production safety system。

## 4. 系統架構與資料流

```text
historical workspace GPX
  -> deterministic virtual clock + sampled route frames
  -> synthetic phone + wearable SensorLogger payloads
  -> loopback_mqtt_broker OR synthetic_direct_feed
  -> SensorLoggerMqttObserver.handle_message()
  -> ingress / device / network / route / fault projections
  -> run_runtime_shadow_replay()
  -> six gate candidates + deterministic reducer dry-run
  -> candidate alert packet when result > L0
  -> packet-bound operator approval
  -> sandbox-only transport attempt
  -> manually selected simulation outcome
  -> optional correlated simulated receipt
  -> Alpha Living projection + immutable source refs/hashes
```

### 4.1 元件責任

| 元件 | 責任 |
|---|---|
| `scout_alpha_simulation_models.py` | Strict Pydantic requests、faults、projections、boundaries |
| `scout_alpha_simulation_scenarios.py` | 10 個 profile、default faults、六閘門 synthetic overlays |
| `scout_alpha_simulation_sandbox.py` | replay lifecycle、observer ingress、shadow reducer、artifacts、integrity checks |
| `scout_local_mqtt_broker_harness.py` | 只允許 loopback 的 MQTT 3.1.1 broker/client harness |
| `scout_alpha_simulation_api.py` | Admin API、workspace/GPX pinning、HTTP error mapping |
| `admin_api.py` | feature-flagged router 與 UI mount |
| `docs/emergency/scout-alpha-sandbox-v0.html` | operator controls、Living、timeline、approval UI |
| `tools/run_scout_alpha_simulation_sandbox.py` | 單一 profile 或 scenario matrix CLI |

## 5. 功能需求

### FR-01 Workspace 與 GPX

- API 必須使用 server-configured workspace，不接受 client 任意路徑。
- Workspace `project.json` 必須明確包含
  `actual_user_track_available=false`，且必須是 JSON boolean。
- API 必須 pin `project_id` 與 server-selected canonical filtered GPX。
- GPX 必須位於 workspace 內、不是 symlink、是 `.gpx`，並通過大小限制。
- CLI 可由 operator 明確指定 workspace 內的相對 GPX ref。
- Replay source 必須標示 `historical_reference_gpx`，不可稱為 live user track。

### FR-02 Deterministic Replay

- 狀態必須依序為 `prepared -> running -> completed`。
- Virtual clock 必須由 `virtual_start_at`、來源時間與 `speed_multiplier` 推導。
- `max_frames` 範圍為 2-512；來源點可 deterministic sampling。
- 沒有來源 timestamp 時使用 bounded fallback interval。
- 每次 advance 都必須帶 `expected_revision`，stale revision 必須拒絕。
- `to_completion=true` 必須跑到最後 frame，不可只做 client-side animation。

### FR-03 Phone／Wearable Ingress

- 每個 route frame 可產生 phone 與 wearable payload。
- 所有 payload 必須進入 `SensorLoggerMqttObserver.handle_message()`。
- `synthetic_direct_feed` 可用於 deterministic tests。
- `loopback_mqtt_broker` 必須走真正 CONNECT、SUBSCRIBE、PUBLISH、PUBACK、PING
  與 DISCONNECT 協定路徑。
- Broker 只能綁定 `127.0.0.1` 與 ephemeral port，支援 QoS 0/1。
- Production-facing `network_mqtt_publish_performed` 永遠為 false；只有
  `local_loopback_mqtt_publish_performed` 可以為 true。

### FR-04 Fault Injection

- Fault 可在 run request 內排程，也可由 UI 針對後續 frame 注入。
- Default、request 與 dynamic faults 合計最多 128 個。
- Fault ID 必須唯一，frame window 必須合法且不得超出 replay。
- Device target 只能是 `sandbox-phone-v0` 或 `sandbox-wearable-v0`。
- GNSS faults 只能作用於 sandbox phone。
- 不支援的 fault kind、parameter 或數值範圍必須 fail closed。

### FR-05 Synthetic Interaction

- 支援 `text`、`voice` 與 `ui_action` channels。
- Voice 只代表預先轉錄的 synthetic transcript，不得存取麥克風或播放硬體。
- 每次 user interaction 產生 user-to-Scout 與 Scout acknowledgement 兩個事件。
- 每個 run 最多保存 64 個 interaction events。
- Free-form text／voice 原文只能在該次 request 的記憶體中使用；artifact 只保留
  redaction marker、digest 與 correlation id。
- 只有 exact allow-listed `fault.*` UI controls 可保留明文。

### FR-06 Six-Gate Shadow Replay

- 每次 execution 必須產生六個 gate projections：`pace_gate`、`delay_gate`、
  `physiologic_gate`、`weather_gate`、`darkness_gate`、
  `environment_threat_gate`。
- Phase 1 adapter 與 mutation 必須保持 disabled。
- GNSS stale／missing 時，結果必須保留 missing context，不可假裝知道「這裡」。
- Candidate terrain、weather、physiology 或 obstruction 不可寫成確認的 field truth。

### FR-07 Candidate Approval／Receipt

- L0 不得虛構 alert packet。
- 高於 L0 時可產生 immutable candidate alert，綁定 reducer ref/hash、revision、
  gate、location ref 與 recommendation。
- Approval 必須綁定 packet id/hash、decision 與 idempotency key。
- `agree_send` 只建立 sandbox transport attempt；不得建立 network connection。
- Simulator outcome 必須綁定 attempt 與 packet。
- `simulated_receipt_recorded` 可建立 correlated receipt，但必須明示：
  `No real transport or delivery occurred`。
- Production `sent` 與 delivery verified 欄位必須保持 false。

### FR-08 Living Projection

- Living 必須顯示 scenario、playback、ingress、network、devices、route、faults、
  timeline、interactions、六閘門、candidate、approval、attempt、simulation、receipt、
  source refs/hashes 與 boundary flags。
- Timeline 必須至少保留 `replay_prepared` 與最終 `replay_completed`。
- Living 是 read projection，不是 safety authority。

### FR-09 CLI 與 Matrix

- CLI 必須要求 `--confirm-sandbox-run`。
- 可執行單一 profile 或 `--scenario-matrix`。
- `--simulate-approval-receipt` 只能新增 local approval／simulation artifacts。
- 預設輸出為 `<workspace>/outputs/sandbox/alpha/`。
- CLI result 必須提供 machine-readable verification summary。

## 6. Lifecycle 與狀態機

```text
no current run
  -> prepare(confirm_sandbox_run=true)
prepared@revision=1
  -> advance(expected_revision=1)
running@revision=N
  -> advance(to_completion=true)
completed@revision=N+1
  -> optional approval(candidate packet id/hash)
approved / declined@revision=N+2
  -> optional transport simulation(approved attempt id/hash)
simulated outcome + optional receipt@revision=N+3
```

共同規則：

- Scenario ID、run ID 與 expected revision 不符時回傳 conflict。
- Run directory 已存在時不得覆寫。
- 完成後不得再注入 replay fault。
- 同一 candidate 只能有一個 approval action。
- Idempotency key 對應不同 request 時必須拒絕。
- Crash 後若發現 effect artifact 與 current projection 不一致，v0.1 會 fail closed
  並要求 operator recovery，不宣稱自動 transaction reconstruction。

## 7. Scenario Catalog

下表是 deterministic fixture 的預期，不是現場安全結論：

| Profile | 主要目的 | 預期 selected gate | 目前 fixture 結果 |
|---|---|---|---|
| `nominal_gpx` | 健康裝置與網路的基準回放 | 無 | `L0_NORMAL` |
| `pace_pressure` | 進度落後 | `pace_gate` | `L3_RETREAT` |
| `delay_pressure` | 預計到達超過 camp deadline | `delay_gate` | `L3_RETREAT` |
| `ridge_distress` | synthetic effort／saturation aggregate | `physiologic_gate` | `L3_RETREAT` |
| `weather_exposure` | synthetic 強風／雷擊 route intersection | `weather_gate` | `L4_ALERT_REVIEW` |
| `darkness_pressure` | safe objective 超出 daylight buffer | `darkness_gate` | `L4_ALERT_REVIEW` |
| `environment_threat` | synthetic impassable obstruction | `environment_threat_gate` | `L4_ALERT_REVIEW` |
| `gnss_degraded` | stale／inaccurate／missing position | 無 | `L0_NORMAL` + missing context |
| `network_recovery` | weak／offline／recovery | 無 | `L0_NORMAL` |
| `device_dropout` | wearable dropout／stale sensor／low battery | 無 | `L0_NORMAL` |

## 8. Fault Injection Catalog

| Fault kind | Target | Allowed parameters | Bound |
|---|---|---|---|
| `network_offline` | link | 無 | frame window |
| `network_weak` | link | `latency_ms` | 0-60,000 |
| `packet_drop` | phone/wearable/unspecified | 無 | frame window |
| `packet_delay` | phone/wearable/unspecified | `release_after_frames` | integer 1-512 |
| `packet_duplicate` | phone/wearable/unspecified | 無 | frame window |
| `packet_out_of_order` | phone/wearable/unspecified | 無 | frame window |
| `gnss_dropout` | phone | 無 | frame window |
| `gnss_stale` | phone | `stale_seconds` | 0-86,400 |
| `gnss_accuracy_degraded` | phone | `horizontal_accuracy_m` | 1-10,000 |
| `gnss_jump` | phone | `lat_delta`, `lon_delta` | -1 至 1 degree |
| `device_offline` | phone/wearable | 無 | frame window |
| `low_battery` | phone/wearable | `level` | 0-1 |
| `sensor_stale` | phone/wearable | `stale_seconds` | 0-86,400 |

目前 UI allow-list controls：

- `fault.network.offline`
- `fault.network.online`
- `fault.gnss.stale`
- `fault.gnss.dropout`
- `fault.gnss.jump`
- `fault.wearable.offline`
- `fault.phone.low_battery`
- `fault.wearable.low_battery`
- `fault.clear`

## 9. Scenario／Projection Schema

### 9.1 Run Request

`AlphaSandboxRunRequest` 至少包含：

- `scenario_id`, `run_id`
- `project_id`, `workspace_root`, `gpx_ref`
- `scenario_profile`
- `ingress_mode`
- `playback.virtual_start_at`
- `playback.speed_multiplier`
- `playback.max_frames`
- `playback.fallback_source_interval_s`
- `faults[]`
- `confirm_sandbox_run`

API 會覆寫／pin workspace、project 與 GPX；CLI 由 operator 明確提供。

### 9.2 Living Projection

`AlphaSandboxLivingProjection` 的主要 domain：

- `scenario`: source mode、historical GPX、project、run、relative refs。
- `playback`: state、cursor、frame counts、source/virtual time、anomalies。
- `ingress`: adapter、mode、message/drop/delay/order counts、broker proof。
- `network`: online／weak／offline／recovered 與 transition refs。
- `devices`: phone／wearable state、sensors、battery、offline/stale counts。
- `route`: progress、historical coordinates、heading、accuracy、fix quality。
- `fault_summary`: scheduled/applied faults 與 event refs。
- `timeline`, `interactions`。
- `safety`: six gates、selected gate、candidate level、missing context。
- `alert_candidate`, `approval`, `transport_attempt`, `transport_simulation`,
  `transport_receipt`。
- `source_hashes`, `source_refs`, `artifacts`, `boundary`。

### 9.3 Interaction-at-Rest Contract

User-to-Scout text／voice 必須：

- `synthetic=true`
- `content_redacted=true`
- `content_sha256=<64 hex>`
- `hardware_audio_invoked=false`
- `external_send_performed=false`

## 10. API Contract

Admin Alpha surface 預設不掛載。只有明確設定
`SCOUT_ALPHA_SANDBOX_ENABLED=true` 或 application constructor 等價參數才會出現。
此旗標不是 authentication。

| Method | Route | 用途 | 主要 guard |
|---|---|---|---|
| GET | `/emergency/sandbox-alpha-v0` | Operator UI | feature flag |
| GET | `/admin/dashboard/living/alpha` | Current Living projection | configured workspace lineage |
| GET | `/admin/dashboard/living/alpha/scenarios` | 10-profile catalog 與 server defaults | 不回傳 absolute workspace path |
| POST | `/admin/dashboard/living/alpha/runs` | Prepare replay | workspace/project/GPX pinning + confirm |
| POST | `/admin/dashboard/living/alpha/advance` | Step 或 complete | identity + expected revision + confirm |
| POST | `/admin/dashboard/living/alpha/interactions` | Synthetic text/voice/UI event | identity + revision + quota + confirm |
| POST | `/admin/dashboard/living/alpha/approvals` | Candidate-bound operator decision | completed replay + packet id/hash + confirm |
| POST | `/admin/dashboard/living/alpha/transport/simulations` | Local simulator outcome／receipt | approval + attempt + packet lineage + confirm |

HTTP mapping：

- `400`: boundary／confirmation／client substitution error。
- `409`: stale revision、identity、lineage、idempotency 或 current-state conflict。
- `422`: 其他 typed sandbox error。
- `503`: server-configured workspace 缺失或不合法。

## 11. Operator UI 與操作流程

UI 必須提供：

1. Workspace、canonical GPX 與 scenario catalog readout。
2. Prepare、Step、Run to completion。
3. Network、GNSS、wearable 與 battery fault controls。
4. Synthetic text／voice transcript controls與明確 privacy warning。
5. Replay timeline、phone/wearable state、network state、route state。
6. 六個 gate cards、selected gate、candidate level、missing context。
7. Candidate approval、do-not-send 與 simulated receipt controls。
8. `Synthetic replay`、`Candidate only`、`Not runtime safety truth` 等常駐標示。

瀏覽器只能呼叫 same-origin allow-listed Alpha endpoints，不得使用 geolocation、
microphone、WebSocket、EventSource、sendBeacon 或 external URLs。

## 12. Artifact 與 Provenance Contract

預設 artifact root：

```text
<workspace>/outputs/sandbox/alpha/
  current.json
  last_cli_result.json
  runs/<run_id>/
    scenario_request.json
    replay_manifest.json
    living_projection.json
    interactions.jsonl                       # 有 interaction 時
    dynamic_fault_commands.jsonl             # 有 dynamic fault 時
    revisions/revision-NNNN/
      living_projection.json
      replay_summary.json
      replay_fault_events.json
      alert_candidate.json                   # result > L0 時
      ingress/
        sensorlogger_mqtt_status.json
        sensorlogger_mqtt_ingress_index.jsonl
        sensorlogger_mqtt_sensor_vitals_records.jsonl
        sensorlogger_mqtt_latency.jsonl
        sensorlogger_mqtt_raw.jsonl
        sensorlogger_mqtt_filter_outputs.jsonl
        sensorlogger_mqtt_application_routes.jsonl
      shadow_replay/
        runtime_safety_gate_event_batch.json
        runtime_route_gate_feed_result.json
        runtime_safety_reducer_dry_run.json
        runtime_safety_phase1_adapter_result.json
        runtime_shadow_replay_result.json
    approvals/<idempotency_key>.json
    transport_attempts/<idempotency_key>.json
    simulations/<idempotency_key>.json
    receipts/<idempotency_key>.json
```

### 12.1 Integrity Checks

在使用 artifact 前，deterministic code 必須驗證：

- `scenario_request_sha256`
- `replay_manifest_sha256`
- historical GPX SHA-256 與 contained relative ref
- scenario/run/project/GPX identity
- reducer artifact SHA-256
- candidate content SHA-256 與 packet SHA-256
- approval／attempt persisted lineage

Hash 是 local corruption/tamper evidence，不是簽章或 hostile-host trust anchor。

## 13. Safety、Privacy 與 Effect Boundaries

每個 projection 必須維持：

```text
local_only=true
synthetic_scenario=true
historical_reference_gpx_only=true
candidate_only=true
runtime_safety_truth=false
phase1_runtime_safety_truth=false
phase1_l0_l4_state_mutated=false
safety_api_called=false
real_outbound_send_performed=false
production_transport_invoked=false
hardware_control_invoked=false
hardware_audio_invoked=false
network_mqtt_publish_performed=false
loopback_network_only=true
external_network_calls_made=false
precise_real_user_location_embedded=false
raw_real_user_health_payload_embedded=false
```

例外是 `local_loopback_mqtt_publish_performed=true` 可以表示本機協定 roundtrip，
但不得縮寫成 production MQTT 或 field connectivity。

Privacy rules：

- UI 不接受手工輸入真實位置。
- 歷史 GPX 座標只能標為 reference evidence。
- Free-form synthetic text／voice 不得以原文落盤。
- API scenario catalog 不回傳 absolute server path。
- API key、token、`.env` 或 private key 不得進入 log、UI 或 artifact。

## 14. Workspace、Total Info 與 Runtime Truth 隔離

Sandbox artifacts 可寫入指定 workspace 的 `outputs/sandbox/alpha/`，但必須保持：

- 不加入 workspace retrieval catalogs。
- 不加入 Total Info。
- 不加入 live navigation history。
- 不加入 live weather truth。
- 不成為 body/device runtime truth。
- 不寫入 Phase 1 safety state。
- 不被模型當成 field observation 或 verified delivery。

Workspace spec 只記錄「此 workspace 曾執行哪個 replay 與得到何種 candidate evidence」，
不把 replay 內容升格為該次登山活動的真實觀測。

## 15. 執行方式

### 15.1 CLI Scenario Matrix

```bash
rtk proxy python3 tools/run_scout_alpha_simulation_sandbox.py \
  --workspace /path/to/scout-workspace \
  --scenario-matrix \
  --ingress-mode loopback_mqtt_broker \
  --max-frames 16 \
  --speed-multiplier 600 \
  --simulate-approval-receipt \
  --confirm-sandbox-run
```

如需指定來源，`--gpx-ref` 必須使用 workspace 內的相對 canonical GPX ref。

### 15.2 Admin UI

1. 由 trusted local operator 明確啟用 `SCOUT_ALPHA_SANDBOX_ENABLED=true`。
2. Server 必須設定合法 pretrip workspace。
3. 開啟 `/emergency/sandbox-alpha-v0`。
4. 選擇 scenario，Prepare 後 Step 或 Run to completion。
5. 視需要注入 fault 或 synthetic interaction。
6. 若產生 candidate，檢查 gate/reducer evidence 後才操作 approval。
7. Simulated receipt 只能被解讀為 lineage proof。

未完成 authentication、authorization 與 deployment network policy 前，不得在 LAN 或
Internet 暴露此 surface。

## 16. 驗收標準

### 16.1 Functional Acceptance

- 10 個 catalog profiles 可 prepare 與 complete。
- Phone 與 wearable 訊息經同一 observer boundary。
- Loopback mode 取得 broker connection 與 subscriber delivery proof。
- 六個 pressure profiles 各自選中預期 gate。
- GNSS、network、device profiles 產生預期 fault evidence。
- L0 profiles 不建立 alert；pressure profiles 建立 candidate alert。
- Approval、attempt、simulation、receipt lineage 完整且 idempotent。
- Living timeline 同時包含 replay 與 interaction events。

### 16.2 Boundary Acceptance

- 無 `/safety/*`。
- 無 Phase 1 mutation。
- 無 external network、hardware 或 production transport。
- Synthetic text／voice 原文不在 persisted projection/JSONL。
- Workspace、project、GPX substitution fail closed。
- Manifest、GPX、reducer 或 candidate tampering fail closed。
- Missing position 不得生成確定的「這裡」敘述。

### 16.3 Verification Commands

```bash
rtk proxy pytest \
  tests/test_scout_alpha_simulation_docs.py \
  tests/test_scout_alpha_simulation_sandbox.py \
  tests/test_scout_alpha_simulation_ui.py \
  tests/test_scout_local_mqtt_broker_harness.py -q

rtk ruff check \
  scout_alpha_simulation_api.py \
  scout_alpha_simulation_models.py \
  scout_alpha_simulation_sandbox.py \
  scout_alpha_simulation_scenarios.py \
  scout_local_mqtt_broker_harness.py \
  tools/run_scout_alpha_simulation_sandbox.py \
  tests/test_scout_alpha_simulation_docs.py \
  tests/test_scout_alpha_simulation_sandbox.py \
  tests/test_scout_alpha_simulation_ui.py \
  tests/test_scout_local_mqtt_broker_harness.py
```

## 17. 已驗證的真實 Workspace Evidence

Workspace：`chilai_nanhua_day1_scoutAI`
Result：`outputs/sandbox/alpha/last_cli_result.json`
Run prefix：`alpha-final-audit-20260720T1900Z-{profile}`

已記錄：

- Canonical historical GPX：11,191 points。
- GPX SHA-256：
  `4877c9535dec152679e96aa9d992a88ceec5663ae5eedc96e4c40bcbd295fd75`。
- 10/10 profiles completed，each 16 frames。
- 10/10 local MQTT broker connections verified。
- 六個 pressure profiles 選中六個預期 gates。
- 6 candidate alerts、6 local approvals、6 sandbox attempts、6 simulated receipts。
- Request、manifest、GPX、candidate-to-reducer lineage checks 通過。
- 所有 production delivery、runtime truth 與 Phase 1 mutation flags 為 false。

完整 run record 保留於
[Workspace Agent Tool Spec](scout-ai-workspace-agent-tool-spec.md)；它是 evidence
record，不是本文件的 normative schema 替代品。

## 18. 產品化缺口

進入 Productization Mode 前至少需要：

1. Operator authentication、authorization、session／CSRF policy。
2. Body size、rate limit、concurrency、storage quota 與 retention policy。
3. TLS MQTT、device identity、topic ACL、reconnect／offline queue 與 remote broker
   integration。
4. 真實 phone/wearable emulator 或 test application，而不是只在 server 內生成
   payload。
5. Crash-safe transactional journal、recovery／reconciliation 與 multi-process locking。
6. Signed/HMAC provenance 或其他 hostile-host trust anchor。
7. GPX parser point-count／complexity limits與 broker connection/subscription caps。
8. Production CSP、deployment binding、reverse-proxy 與 network policy review。
9. Live weather replay/integration contract 與 freshness／route intersection verification。
10. Phase 1 promotion review；prototype eval 永遠不能直接開啟 runtime mutation。
11. Browser/mobile E2E、real-device accessibility、latency、load、cost 與 observability
    gates。
12. Rollback、artifact migration、cleanup、retention 與 incident runbook。

## 19. 變更治理

任何新增 scenario、fault、API、effect 或 artifact schema 的變更必須：

1. 先更新 typed schema 或 deterministic implementation。
2. 增加 focused executable contract test。
3. 更新本主規格的 catalog／API／artifact／boundary 相關段落。
4. 在專屬下游文件保留簡短摘要與回指本文件的捷徑。
5. 若實際 workspace 有重新執行，更新 Workspace Agent Tool Spec 的 evidence record。
6. 不得因文件整併而刪除歷史 evidence 或 reducer-specific rationale。
7. 不得用 feature flag 取代 authentication，也不得用 simulated receipt 取代
   delivery evidence。

## 20. 導覽與來源索引

### Normative／Architecture

- [Runtime Multi-Gate Safety Reducer](scout-runtime-multi-gate-safety-reducer.md)
- [Workspace Agent Tool Spec](scout-ai-workspace-agent-tool-spec.md)
- [Outdoor AI Agent Standard](SCOUT_OUTDOOR_AI_AGENT_STANDARD.md)

### Operator Surfaces

- [Alpha Sandbox Operator UI](../emergency/scout-alpha-sandbox-v0.html)
- [Emergency Mobile Approval v0](../emergency/scout-emergency-mobile-approval-v0.html)

### Entry Point／Executable Contracts

- [CLI](../../tools/run_scout_alpha_simulation_sandbox.py)
- [Sandbox/API tests](../../tests/test_scout_alpha_simulation_sandbox.py)
- [UI tests](../../tests/test_scout_alpha_simulation_ui.py)
- [MQTT harness tests](../../tests/test_scout_local_mqtt_broker_harness.py)
- [Documentation-link tests](../../tests/test_scout_alpha_simulation_docs.py)

### Implementation

- [`scout_alpha_simulation_models.py`](../../scout_alpha_simulation_models.py)
- [`scout_alpha_simulation_scenarios.py`](../../scout_alpha_simulation_scenarios.py)
- [`scout_alpha_simulation_sandbox.py`](../../scout_alpha_simulation_sandbox.py)
- [`scout_alpha_simulation_api.py`](../../scout_alpha_simulation_api.py)
- [`scout_local_mqtt_broker_harness.py`](../../scout_local_mqtt_broker_harness.py)
