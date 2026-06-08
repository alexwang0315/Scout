# Hardware Readiness Assistant Runbook

這份 runbook 是 Slice 22 的 hardware readiness assistant 操作邊界。它用來說明
`/admin/hardware-readiness` 與 `/admin/hardware-readiness/context` 如何被安全地
當作 fixture-backed/read-only 的 admin 觀察介面使用；它不是硬體部署手冊、不是
provider 控制台、不是 outbound/SOS 操作流程，也不是 Phase 1 safety runtime、
Phase 2 Brain 或 Phase 4/4.5 review decision 的寫入入口。

## 1. Surface Boundary

`/admin/hardware-readiness` 是靜態 admin shell，`/admin/hardware-readiness/context`
是 context projection endpoint。兩者都必須保持 fixture-backed/read-only：

- `fixture-backed`：內容只來自 repo 內的 hardware readiness fixture，例如 provider
  health、sample replay timeline、runtime debug events 與 mock transport queue。
- `read-only`：只能讀取與呈現 context，不得建立、更新、刪除或補寫任何 runtime 狀態。
- `GET-only`：context endpoint 只接受 `GET`；不可新增 `POST`、`PUT`、`PATCH`、
  `DELETE` mutation。
- `model interpretation only`：assistant 回答只能標示為 read-only model
  interpretation，不是權威事實、不是 go/no-go、不是 departure approval。

中文邊界短句：

- `/admin/hardware-readiness` 是 fixture-backed/read-only。
- `/admin/hardware-readiness/context` 是 fixture-backed/read-only。
- 不呼叫 `/safety/*` mutation。
- 不寫 ObservedFact。
- 不寫 Brain。
- 不寫 IncidentStore。
- 不寫 review decision。

## 2. What The Assistant May Read

assistant 可以讀取的內容只限於 bounded context：

| Context | 用途 | 邊界 |
| --- | --- | --- |
| provider health fixture | 解釋 provider 狀態與 degraded reason | 不控制 provider，不切換 provider，不重啟 provider |
| sample replay timeline | 說明 fixture replay 是否完成 | 不啟動 Pi/Docker/k3s/MQTT/NATS/Coral/Jetson |
| runtime debug event fixture | 說明 read-only debug evidence | 不呼叫 live `/safety/*` mutation |
| mock transport queue | 說明 mock message queue | 不送真 SOS/SMS/satellite |

如果 selected provider ref 存在，assistant 可以用它縮小回答範圍；如果不存在，就只能用
fixture summary 回答。任何答案都必須保留 sources 與 limitations，並且不得把 fixture
projection 說成 live sensor、live route progress 或 field runtime 狀態。

## 3. Explicit Non-Goals

這個 runbook 明確排除下列行為：

- 不啟動 Pi。
- 不啟動 Docker。
- 不啟動 k3s。
- 不啟動 MQTT。
- 不啟動 NATS。
- 不啟動 Coral。
- 不啟動 Jetson。
- 不控制 provider。
- 不控制 assistant provider，不切換 model provider，不讀取 token value。
- 不控制 GNSS、IMU、BLE、LoRa、LTE、NTN、radio、modem 或任何 hardware provider。
- 不送真 SOS。
- 不送真 SMS。
- 不送真 satellite。
- 不送任何 real outbound transport。
- 不呼叫 `/safety/*` mutation。
- 不寫 ObservedFact。
- 不寫 Phase 2 Brain 或 BrainFileStore。
- 不寫 IncidentStore。
- 不寫 review decision。
- 不核准 departure，不產生 Final MissionGraph，不啟動 runtime handoff。

## 4. Safe Local Check Flow

從 repo root 只做 focused pytest：

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_hardware_readiness_runbook.py
```

若要一起檢查既有 hardware readiness API boundary，可額外執行：

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest \
  tests/test_hardware_readiness_api.py \
  tests/test_hardware_readiness_runbook.py
```

這些命令只讀取文件與 fixture-backed API 測試，不會啟動 Pi、Docker、k3s、MQTT、
NATS、Coral、Jetson，不會送 SOS/SMS/satellite，也不會呼叫 `/safety/*` mutation。

## 5. Operator Checklist

在把 hardware readiness assistant 顯示給 admin 使用者前，確認：

- 頁面文字仍明確標示 fixture-backed/read-only。
- context endpoint 仍是 GET-only。
- assistant panel 仍標示 read-only model interpretation。
- provider health 仍來自 fixture，不來自 live hardware probe。
- mock transport queue 仍只是 mock，不會升級成 live outbound。
- 沒有 action button 或 query field 代表 approve、send、write、mutate、control。
- 沒有寫入 ObservedFact、Brain、IncidentStore 或 review decision 的流程。

如果任一項不成立，先停止擴展 hardware readiness assistant；此 slice 的 acceptance 是
維持觀察與解釋邊界，不是把硬體、provider、outbound 或 safety runtime 接上 live path。
