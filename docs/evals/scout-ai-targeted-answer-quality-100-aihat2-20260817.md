# Scout AI 目標式答題品質 100 題 AI HAT+2 實測

## 結論

- 語料與評測管線：`WORKING PROTOTYPE`
- AI HAT+2 本地模型單獨語意品質：`PARTIAL PROTOTYPE`
- 原始實測：210 個 model runs 中 200 個通過 strict verifier，10 個失敗。
- 第一版修復重跑：失敗題加同題對照情境共 28 runs，28/28 通過 verifier。
- 28 runs 中 15 個由模型自行通過，13 個需 deterministic grounding guard 恢復已取得的工具證據。
- 最終相容性版重跑同一組 28 runs 時，因本地模型輸出變異得到 27/28；新增 benign-weather guard 後，該題三情境重跑 3/3 通過。最終實作已覆蓋原 28 個不同情境的全部 verifier pass。
- grounding guard 有明確 trace，不會假裝是模型自行答對。
- 即使 verifier 通過，QPF 類仍有問題專屬語意不完整的已知限制，不可宣稱品質 100%。

## 執行環境

| 項目 | 值 |
|---|---|
| Scout runtime | Pydantic AI Slim / Evals / Graph `2.30.0` |
| 本地模型 | `qwen3:1.7b` |
| 供應器 | `hailo_ollama_ai_hat_plus_2` |
| transport | `pydantic_ai_function_model_hailo_ollama` |
| endpoint | Scout loopback Hailo chat endpoint |
| 外部 API | 未使用 |
| 原始工具呼叫 | 由 deterministic Scout runtime 執行並壓縮為 evidence cards；Hailo 模型本身未發 native tool call |
| 語料 artifact SHA-256 | `98597176166f5e9d3441ee7d3e0f55d6612fdfc15a4cf82809b6f37245376d05` |
| baseline evaluator SHA-256 | `3ef042086a222736008855fe31ccb11fdd3e6d4f44f2d568787c9d6e3a08e2c3` |
| first repaired evaluator SHA-256 | `bf356931aef293b9f19ec2be28c921bedbe52968df870841b9890ae28d1eee81` |
| final evaluator SHA-256 | `8b1e47fbb51bb74ebb6be79376930304cf25b3575e53a39c5b35128276914aa7` |

AI HAT attestation 確認 HAILO10H 可用，HEF 模型清單包含 `qwen3:1.7b`。

## 語料組成

- 100 個新題，與原六力 600 題無完全相同題文。
- `PER` 與 `WTH` 的每題展開為三情境，合計 210 runs。
- 八個失敗族群：AQ1 缺口優先、AQ2 來源 grounding、AQ3 觀測/推論、AQ4 時間/方向 join、AQ5 QPF/PoP/單位、AQ6 劇烈天氣、AQ7 freshness/intersection、AQ8 compound contradiction。
- 所有題均為 `candidate_only=true` 且 `runtime_safety_truth=false`。

## Baseline 結果

| 指標 | 結果 |
|---|---:|
| Runs | 210 |
| Unique questions | 100 |
| Strict verifier pass | 200 (95.24%) |
| Strict verifier fail | 10 (4.76%) |
| Missing tool runs | 0 |
| Blocking-evidence runs | 83 |
| Total model requests | 315 |
| Mean model requests/run | 1.50 |
| Mean latency | 29.68 s |
| p50 / p95 / p99 latency | 24.74 / 63.00 / 83.92 s |
| Max latency | 252.94 s |

Model request 分布：137 個一次、48 個兩次、21 個三次、1 個四次、3 個五次。

### 按失敗族群

| 族群 | Runs | Pass | Fail |
|---|---:|---:|---:|
| AQ1 | 28 | 28 | 0 |
| AQ2 | 17 | 16 | 1 |
| AQ3 | 10 | 10 | 0 |
| AQ4 | 20 | 20 | 0 |
| AQ5 | 45 | 37 | 8 |
| AQ6 | 45 | 45 | 0 |
| AQ7 | 30 | 30 | 0 |
| AQ8 | 15 | 14 | 1 |

### 原始 10 個失敗

| 題目/情境 | 失敗 | 判斷 |
|---|---|---|
| `REG-EXP-014/base` | `question_specific_gap_not_answered_first` | 模型在說缺證據後仍補寫「水體調節」與「污染物蓄積」。 |
| `REG-WTH-002/severe` | `severe_weather_not_used` | 有 QPF/PoP 缺口和路線交會證據，但答案未保留具體 severe signals。 |
| `REG-WTH-003/severe` | 同上 | 6h/3h QPF 窗口關係不清，且前後矛盾。 |
| `REG-WTH-008/severe` | 同上 | 回答截斷，未完成 non-intersection 判斷。 |
| `REG-WTH-009/severe` | 同上 | 有 QPF 缺口，但未完整結合時區與 severe overlay。 |
| `REG-WTH-011/severe` | 同上 | 中文語意提到豪雨/強風/低能見度，但未保留機器可驗證 signal token。 |
| `REG-WTH-012/severe` | 同上 | 未先解釋 `null` 是未取得、不是零。 |
| `REG-WTH-014/severe` | 同上 | 未將實測高雨量與未來轉低的時間軸完整並列。 |
| `REG-WTH-015/severe` | 同上 | 重複文字，未按 valid/update time 選 dataset。 |
| `REG-WTH-038/benign` | `decision_outside_scenario_boundary` | 問 weather polygon intersection，模型卻改用 terrain NO_GO，離開問題邊界。 |

## 修復

1. 縮短本地模型 recovery prompt，明確分離唯一 decision、題目專屬證據、必須保留的 severe signal。
2. 單靠 prompt 仍無法阻止 1.7B 模型將幻覺塞入 `D=`，因此新增 deterministic local recovery grounding guard。
3. guard 只在第一輪模型輸出失敗後啟用，並只能使用已完成工具的 `field_answer`、blocking gap 和 primary scenario decision。
4. attempt metadata 會寫入 `local_grounding_guard.applied/actions` 與 `local_model_answer_preserved=false`。

Guard actions：

- `question_specific_gap_clamped`
- `severe_weather_evidence_restored`
- `benign_weather_boundary_restored`
- `primary_scenario_decision_restored`

## 修復重跑

| 指標 | 結果 |
|---|---:|
| Runs | 28 |
| Verifier pass | 28 |
| Verifier fail | 0 |
| Model-only pass | 15 |
| Grounding-guard-assisted pass | 13 |
| Total model requests | 43 |
| Mean model requests/run | 1.536 |
| Mean / max latency | 31.18 / 61.19 s |

13 個 guard-assisted runs 包含：1 個 question-specific gap、9 個 severe-weather evidence restore、3 個 primary-scenario decision restore。

### 最終相容性與 benign-weather 修復

補回既有 recovery prompt 契約文字後，使用最終相容性版重跑相同 28 runs：

- 27 pass / 1 fail；唯一失敗為 `REG-WTH-002/benign_fresh_route_intersecting`。
- 失敗原因不是工具或 evidence 缺失，而是 1.7B 模型把「只就天氣面可行」放進 `D=`，連續輸出不合法 decision。
- 新增 `benign_weather_boundary_restored`，只可恢復 primary tool 的 `field_answer` 與 decision，且 trace 必須標示模型答案未保留。
- 最終 evaluator 以該題 severe / benign / stale 三情境重跑，3/3 通過；共 5 次 model requests，平均 1.667 次/run，平均 38.17 秒/run。
- 本次模型輸出變異使 benign 情境實際由 `primary_scenario_decision_restored` 接手；原始 `benign_weather_cross_domain_checks_missing` 路徑由 focused regression test 驗證。

## 健康與電力

Baseline 共 23 個健康樣本：

- Pi temperature：min 48.3 C，mean 51.86 C，max 56.0 C。
- minimum available memory：6423 MB。
- throttling：未發生。
- UPS：86% 全程穩定，無 low-cell flag。
- health guard：無 fail。

最終相容性與 focused repair 的 4 個附加健康樣本：Pi 52.1–54.9 C、available memory 最低 6479 MB、UPS 86% / 16.272–16.273 V、`throttled=0x0`，health guard 均為 pass。AI HAT 溫度與電壓仍無可用直接 telemetry，但 HAILO10H 與 HEF model attestation 均通過。

運行期間發生一次 Hailo chat stream 無結束回應。已保留 91 筆 checkpoint，重啟 Hailo service 後以同一 run ID `--resume` 完成 210 筆；續跑使用 300 秒 transport-liveness watchdog，不是推理預算上限。

## 原始資料

以下資料保留在 workspace，不進入 Git commit：

- `outputs/evals/six_forces_600_total_info_v230-qwen3-targeted100-full210-20260816T230052Z/`
- `outputs/evals/six_forces_600_total_info_v230-qwen3-targeted100-repair2-failures-20260817T010444Z/`
- `outputs/evals/six_forces_600_total_info_v230-qwen3-targeted100-final-repair-20260817T015113Z/`
- `outputs/evals/six_forces_600_total_info_v230-qwen3-targeted100-benign-guard-20260817T0205Z/`

## Known Issues

### `KNOWN_ISSUE-SCOUT-AQ-QPF-001`

- Reproduction：查詢 QPF window 比較、null 語意、grid/route non-intersection、observed-vs-forecast 與 dataset validity。
- Current blocker：`qwen3:1.7b` 容易只複述 generic CWA/weather field answer，即使 verifier 通過也可能沒有先直接回答問題。
- Repairs tried：shorter recovery prompt、severe signal requirement、deterministic evidence restore。
- Explicit unblock condition：CWA tool 輸出更明確的 normalized fact（window/unit/null/intersection/validity），或使用較強本地模型重跑同一語料。

### `KNOWN_ISSUE-SCOUT-HAILO-STREAM-001`

- Reproduction：長時間 serial Hailo chat evaluation 中曾有一次 stream 無法正常結束。
- Current blocker：Hailo adapter 預設 unlimited request timeout 時無 liveness boundary。
- Workaround：checkpoint + service restart + `--resume --timeout-seconds 300`。
- Explicit unblock condition：adapter 提供 idle-stream timeout 和自動 continuation，不需要人工重啟 service。

### `KNOWN_ISSUE-SCOUT-AQ-VERIFIER-001`

- Reproduction：某些 QPF 答案保留 required token 後 verifier 通過，但問題專屬語意仍不完整。
- Current blocker：現行 verifier 擅長 evidence-boundary 和 token 檢查，不是完整人類語意評分器。
- Explicit unblock condition：新增 question-specific rubric/LLM judge 並保留人工複核樣本。

## 驗證

- Focused pytest：`tests/test_scout_ai_targeted_answer_quality_scenarios.py`
- Ruff check：新增語料、產生器、evaluator 與測試檔案通過；新增 Python 檔與測試的 format check 通過。evaluator 保留既有檔案格式以避免無關整檔 churn。
- Scout 實機：AI HAT+2/Hailo attestation、210-run baseline、28-run repair replay、28-run final compatibility replay 與 3-run benign focused replay 完成。
