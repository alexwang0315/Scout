# Pydantic AI 2.38 本機升級與既有失敗題驗證

日期：2026-09-04。相容性升級狀態：`WORKING PROTOTYPE`。

2.38.0 先在隔離環境完成相容性與真實模型驗證，取得本輪明確批准後，
**repo pins 與本機 `venv` 也已完成升級及驗證**。Scout 硬體未部署，
Dashboard/worker 未由本輪重新啟動，也未驗證既存行程已載入新版。
這是相容性升級完成，不代表以下答題缺陷已修復或答題品質提升。

## 批准後本機更新

- 使用者明確批准本輪相依版本與本機 venv 升級，隨後進一步授權：
  「升級venv應該跟navigation頁面無關，未來都可以自行升級」。
  已將本機 venv 升級與 focused compatibility tests 的持續授權記入
  `AGENTS.md`、`qualification/policies/navigation-freeze.md`；不擴張為
  Navigation 程式、GIS 契約、worker 重啟、硬體部署或 baseline 修改授權。
- 本機 Python：`/Users/alexwang0315/scout-fusion/venv/bin/python`，3.12.3。
  Slim / Evals / Graph 均為 `2.38.0`，Praison SDK 維持 `1.7.3`。
- 使用 `uv pip install --no-deps` 只升級上述三個套件，再以
  `--no-deps --editable .` 更新 Scout package metadata。安裝前後 freeze 比對
  僅三個套件版本變動；`uv pip check` 檢查 **105 個套件通過**。
- 本機 venv focused pytest：**101 passed、0 skipped**，20.68 秒；一則
  上游 TestModel 同步 event-loop DeprecationWarning。這不是效能 A/B 結論。
- 本機 venv 真實 OpenRouter smoke：**27/27**，不使用 `--expected-version`
  覆寫；configured、expected、installed 都為 `2.38.0`。版本工具實際回傳
  `2.38.0`，模型有讀取此回傳。MCP stream、typed output、traced search/fetch、
  ToolFailed 與 retry 均通過；native search 仍僅為 `provider_transport_only`。
- Ruff、`git diff --check` 與 scoped secret-pattern scan 通過。
- 本輪開始前 guard 已有五個漂移：初始階段的四個檔案，另加
  `dashboard_connected_preparation.py`。它們都未由本輪改動。
  更新後新增的漂移只有核准範圍內的 `AGENTS.md`、`pyproject.toml`、
  `qualification/policies/navigation-freeze.md`、`requirements.pi.admin.txt`。
  Guard 仍回報 `NAVIGATION_APPROVAL_REQUIRED`，因為它只比較來源 hash，
  不讀取對話授權。**未更新 baseline、未停用 guard，也不宣稱整體凍結檢查通過。**
- 驗證階段沒有重跑整套一千題，沒有再次重複以下十四個 A/B runs，當時尚未
  commit，也沒有 push 或硬體部署。既有人工複核問題保留待修。

## 初始隔離階段

- 隔離 Python：`/private/tmp/scout-pydantic238-20260904/bin/python`。
- Slim / Evals / Graph 均為 `2.38.0`；Praison SDK 維持 `1.7.3`。
- 此階段原本 `venv` 的 Slim / Evals / Graph 為 `2.37.0`。
- 複製已安裝的依賴到獨立環境，僅替換上述三個套件；`uv pip check` 檢查
  104 個套件通過。最初完整重裝碰到 cryptography 原始碼編譯，已中止該安裝，
  當時沒有改動原本環境。
- 模型固定 `openrouter:deepseek/deepseek-v4-flash-0731`，沒有切換預設模型。
- 使用原 workspace 的獨立副本；未重新 preparation、改寫原 GPX/DEM、
  啟動 QGIS worker 或部署硬體。
- `pyproject.toml`、`requirements.pi.admin.txt` 在 Navigation 凍結範圍內。
  初始階段尚未收到 scoped approval，因此版本宣告保留原樣；取得批准後的
  實際更新及持續 venv 授權見上節。

初始隔離階段前後 Navigation guard 均回報同四個既存漂移路徑：

1. `docs/admin/scout-dashboard-v0.1.html`
2. `docs/admin/scout-maplibre-evidence.js`
3. `tests/test_navigation_diagnostics.py`
4. `tools/dashboard_diagnostic_browser_smoke.js`

本輪未修改這些檔案，也未更新 baseline 或繞過 guard。相同漂移清單只代表
沒有增加被偵測的漂移路徑，不代表這些既存變更已通過 Navigation 驗證。

## 相容性結果

- 新版 focused pytest：**101 passed**，一則 TestModel 同步 event-loop
  DeprecationWarning，未修改上游套件。
- 原本 2.37 環境的相容性回歸：**30 passed**。
- 真實 OpenRouter smoke：**27/27**，包含 18 項離線檢查與 9 項 live 檢查，
  不是 27 次 API request。
- Ruff、scoped diff whitespace 檢查通過。
- Praison AgentTeam/MCP、memory isolation、background queue、候選證據邊界
  回歸納入 focused pytest；沒有宣稱 Praison 本輪進行雲端答題。

新版專屬 fixture 覆蓋：

- 相同 ID 的 WebSearch 合併、collection 聯集與後項 scalar 優先。
- 重複 local search 只留下後項，但 WebFetch 不會消失。
- run-level search 覆寫與 explicit distinct IDs。
- Scout 本身仍產生一個 traced search 與一個 traced fetch；10 次以上容量保留。
- 缺少 finish_reason 的串流：預設仍接受；明確開啟嚴格 profile 才拋錯，
  Agent message history 保留部分內容且標為 `interrupted`。沒有對 Hailo 或
  所有 OpenAI-compatible endpoints 全面強制啟用此 profile。
- 第一個工具執行中取消後，保留 history 並能以 interrupted tool receipt 續跑。
- DeepSeek 直連 provider 的 thinking/tool-choice 與 Responses schema profile；
  不將這些直連修正推論為 OpenRouter 的相同行為。

版本依據：[官方 2.38.0 release](https://github.com/pydantic/pydantic-ai/releases/tag/v2.38.0)。

Live evidence 確認 function call、tool return、typed output、MCP stream events、
traced WebSearch 與 WebFetch。版本工具實際回傳 `2.38.0`，不再回傳固定 pin 字串。
Provider-native WebSearch 仍未回傳 native tool parts；其 HTTP/文字成功僅算
transport smoke，**不是已證明搜尋過且有出處的答案**。可稽核搜尋仍使用 Scout
traced fallback。本輪搜尋結果含 Upgrade Guide 與其他 Pydantic 頁面，並非
特定 2.38 release-content relevance 的合格證明。

## 既有失敗題與對照方式

沿用原題、原情境，不新編題目。PER 兩題均保留三情境，加上 EXP 一題，
每個版本七個 runs，共十四個真實模型 runs。

歷史失敗來源位於原 workspace `outputs/evals/`：

- `six_forces_600_openrouter_deepseek_v4_flash_large60x100_20260828`：
  EXP-031 曾因 `unknown_signal_id` 失敗；PER-021 曾因 evidence gap 失敗。
- `six_forces_600_openrouter_deepseek_v4_flash_live_per_repair6x18_unbounded_attempt_composer_20260901`：
  PER-063 exposed 曾因 invalid JSON / no claims 失敗。

兩組使用同一份 scenario snapshot，SHA-256：
`bb34a0b2dce2565967cfa8e59576b4c408dd0711db624a2557a6c9a6416da330`。
七組 case IDs 與保存的 workspace source hashes 一致。

控制條件：相同當前 harness 與來源副本、MSER enforce、thinking off、單 worker、
10/10 容量、無 output token 或總執行時間上限。未啟用 conservative answer
composer，保留模型原始答案。天氣是歷史 synthetic scenario replay，非今日
真實天氣。Pydantic AI 真的發出工具呼叫取得完整 evidence cards；這證明
已提供工具的執行及證據答題，不等同未限定工具集合的完整 router 評測。

| 原題 / 情境 | 2.37 verifier | 2.38 verifier | 人工複核 |
|---|---|---|---|
| EXP-031：這一帶的原住民族地名代表什麼意思？ | PASS | PASS | 都是合理回報索引沒有證據，**沒有回答地名含義** |
| PER-021：我可以在這裡停下來拍照嗎？ / 暴露強風 | PASS | PASS | 依情境提出不在原地停留、重新評估背風候選點 |
| 同題 / 遮蔽平坦 | FAIL | FAIL | 主工具允許八分鐘，但 MSER 有必要證據缺口；兩版都未解決衝突 |
| 同題 / GNSS 過期 | PASS | PASS | 保留位置未知，要求重新取得定位 |
| PER-063：現在改線的風險比照原路前進低嗎？ / 暴露強風 | PASS | PASS | 都不宣稱已證明替代路線較安全 |
| 同題 / 遮蔽平坦 | PASS | PASS | **2.38 語意失敗**：沒有替代路線比較證據，卻回答「否」 |
| 同題 / GNSS 過期 | PASS | PASS | 都承認資料不足，不能比較兩條路線 |

因此不是「答對 6/7」。自動 verifier 兩版均為 6/7；人工檢查另發現新版
PER-063 的 false pass。合理不確定性與真正回答出缺失事實也必須分開計算。
同一模型的少量隨機輸出不能證明升版造成語意進步或退步。

| 觀測項目 | 2.37.0 | 2.38.0 |
|---|---:|---:|
| Verifier 通過 | 6/7 | 6/7 |
| Harness attempts | 9 | 8 |
| Provider requests | 18 | 17 |
| Function tool calls / returns | 25 / 25 | 24 / 24 |
| Input tokens | 115,528 | 116,735 |
| Output tokens | 9,994 | 8,906 |
| Reported reasoning tokens | 0 | 0 |
| 平均時間 | 34.18 秒 | 44.03 秒 |

全部 offered evidence tools 有實際 call/return。三軸既有 proxy 的平均值兩版
同為 transport/schema 100、safe uncertainty 100、semantic 96.43；這些數字
與人工發現的錯誤不一致，**不得當作安全性或實際品質 100% 的證明**。
樣本小、執行有部分重疊且雲端時間浮動，不能據此判斷 2.38 效能退步。

## 待修問題

### SCOUT-PER-021-CONTRACT-CONFLICT-20260904

原題：`PER-021/sheltered_flat_time_available`。

- 原始回答允許最多八分鐘，符合 primary contextual permission 工具。
- Legacy gap classification 顯示 blocking 為空、weather gap 為 supplemental。
- 但 final MSER receipt 包含 weather/remaining-daylight 缺口，只允許
  `DELAY`、`CHANGE_PLAN`、`NO_GO`。
- `_answer_obligations_for_run` 又要求 primary permission 優先，形成衝突。
- 兩版均被 `non_conservative_gap_decision` 正確攔截；不能移除 gate 抬高分數。
- Codex review：Harness Failure / Missing Evidence，而非 2.38 transport regression。
- 解鎖條件：先統一必要證據缺口、primary-tool obligations、scenario expectation
  的型別契約，保留缺口來源，再重跑這個原情境。不可合成不存在的 daylight。

### SCOUT-PER-063-RELATIVE-RISK-FALSE-PASS-20260904

原題：`PER-063/sheltered_flat_time_available`。

- 新版原始答案首句：「否，改線風險不比原路低」。
- 後續只引用原路 CP 003 近旁高風險與天氣缺口，沒有替代路線的可比較證據。
- 保守的 NO_GO 不能證明這個相對風險陳述正確；自動 semantic proxy 卻給 100。
- Codex review：Model Weakness / Harness Failure / Missing Evidence。
- 解鎖條件：比較題必須保留兩側證據及可比條件；只有單側分數時應明說不能比較，
  verifier 必須能拒絕無證據的肯定或否定比較。以本輪原始答案作 regression fixture。

本輪只修相容性驗證工具，沒有混入 MSER/domain rule、workspace/provenance 或
Navigation 契約修改，也未切模型來掩蓋矛盾。上述業務問題保留為 review findings，
不宣稱已完成工具修復或完整失敗升級流程。

## 修改檔案

- `pyproject.toml`、`requirements.pi.admin.txt`、`requirements.pi.live.txt`：
  相關 Pydantic pins 對齊 `2.38.0`。
- 既有未追蹤的 `requirements.pi.intelligence.txt` 僅對齊 Slim pin；其餘
  intelligence sidecar 內容及擁有權不變，不把整個檔案當成本輪新功能。
- `src/scout/cli/pydantic_compat_smoke.py`：新增 `--expected-version`，保留
  configured/expected/installed 三者的區別；預設 `2.38.0`；版本工具讀實際
  installed metadata。
- `tests/test_pydantic_ai_compat_smoke.py`：候選版本、family mismatch、預設 gate
  與無 key 的 fail-closed regression。
- `tests/test_pydantic_ai_runtime_compat.py`：檢查 metadata API 實際版本，不將
  helper 的測試寫死為某一版；正式 pin 對齊仍由獨立測試檢查。
- `tests/test_pydantic_ai_238_compat.py`：十項新版 regression。
- `AGENTS.md`、`qualification/policies/navigation-freeze.md`：記錄本機 venv
  升級的持續授權，不修改 guard 或 baseline。
- `docs/specs/scout-ai-tool-interface.md`、`docs/specs/SCOUT_AI_OS_MVP_SPEC.md`、
  `docs/specs/scout-cross-surface-ai-assistant.md`：同步目前版本與相容性範圍，
  保留歷史升級紀錄與安全邊界。
- 本報告。驗證後使用者要求提交這次更新；不 push 或部署硬體。

### 提交範圍

本次提交僅包含版本宣告、相容性 smoke/regression、上述規格與驗證報告，
以及 local venv 持續授權段落。共用檔案採部分暫存，不納入另一線的 Navigation
freeze suspension、MCP HTTP entrypoint 或 admin `httpx` 相依變更。
`requirements.pi.intelligence.txt` 與完整測試產物仍留在本機，不連同 sidecar
或大型 ignored artifacts 加入版本控制。上節 guard 狀態與 hash 均為升級當時
的歷史紀錄，不代表提交整理時其他對話串的 Navigation 政策狀態。

## 證據與重跑

Repo artifact 目錄：`artifacts/scout-ai-compatibility/pydantic-238-20260904/`。

- `live-smoke.json`：完整 27 項結果。
- `comparison.json`：版本、逐題原始答案、工具、source hashes、人工 review。
- `baseline237/`、`candidate238/`：原始 per-case JSONL、model attempts、provider
  response IDs、tool call IDs、usage、scenario snapshot 與 manifest。
- `candidate-requirements.txt`：隔離環境依賴快照，不是已套用的正式 runtime pin。
- `promotion-verification.json`：取得批准後的本機升級驗證收據。
- `promoted-live-smoke.json`、`pytest-promotion.xml`：本機原 venv 新跑的
  27 項 smoke 與 101 項測試結果，不覆寫初始隔離證據。
- `promotion-before-requirements.txt`、`promotion-after-requirements.txt`：
  確認僅三個 Pydantic 套件升版的快照。
- `promotion-navigation-before.json`、`promotion-navigation-after.json`：
  既存漂移與本輪核准漂移的區分。

結果 JSONL SHA-256：

- baseline：`6539607f2e7ee0e507c64767e58d8a0822d7d936dd53a03c9459eadee8a2fae6`
- candidate：`c63f46a4812253291ff5880bc3d73d905dcbacd2f3067d05129ee959a2300af0`

```sh
rtk proxy ./venv/bin/python -m scout.cli.pydantic_compat_smoke \
  --live-openrouter --model deepseek/deepseek-v4-flash-0731 \
  --env-file /Users/alexwang0315/.scout/.env

rtk proxy env PYTHONPATH="$PWD/src:$PWD" \
  /private/tmp/scout-pydantic238-20260904/bin/python \
  -m scout.cli.pydantic_compat_smoke --expected-version 2.38.0 \
  --live-openrouter --model deepseek/deepseek-v4-flash-0731 \
  --env-file /Users/alexwang0315/.scout/.env

rtk proxy env PYTHONPATH="$PWD/src:$PWD" \
  /private/tmp/scout-pydantic238-20260904/bin/python \
  tools/scout_ai_six_forces_openrouter_eval.py \
  --workspace /private/tmp/scout-pydantic238-20260904/workspace \
  --scenario-artifact outputs/evals/six_forces_600_openrouter_deepseek_v4_flash_large60x100_20260828/scenario_artifact.snapshot.json \
  --env-file /Users/alexwang0315/.scout/.env \
  --model deepseek/deepseek-v4-flash-0731 \
  --question-id EXP-031 --question-id PER-021 --question-id PER-063 \
  --mser-mode enforce --thinking off --workers 1 --timeout-seconds 0
```

這些命令會再次產生真實 OpenRouter API 用量。不得把副本的歷史情境當成今日
即時天氣或現場狀態。本機升級已完成；未來本機 venv 升級可依本次持續授權
自主執行，真正 Navigation/GIS 行為修改仍依凍結規則處理。
無需為這次小版升級重跑整套一千題。
