# Scout AI 六力題庫與情境化評測設計紀錄

**Status:** Design decision and implementation handoff 0.1

**Recorded:** 2026-07-16

**Primary standard:** `docs/specs/SCOUT_OUTDOOR_AI_AGENT_STANDARD.md`

**Question corpus:** `docs/specs/scout-ai-six-forces-600-question-corpus.md`

## 1. 討論目的

本文件記錄 Scout AI 本地模型評測後，對「真實登山者會問什麼」及「開發時如何提供當下情境」所形成的產品與工程共識。

核心問題不是讓模型回答任意聊天題，而是確認 Scout 能否在登山者缺少一項或多項戶外能力時，整合複雜證據，提供冷靜、可追溯且可反駁的第二票判斷。

## 2. Scout 的角色：Evidence-Based Second Opinion

Scout 不是一般聊天助理、行政助理或通訊 SOP 查詢器。登山者通常已有一個主觀感受或準備採取的行動，但無法同時處理位置、時間、腳程、天氣、地形、隊伍與撤退窗口等多維因素。

Scout 的核心價值是提供一票 evidence-based second opinion：

- `SUPPORT`：目前客觀證據支持使用者判斷。
- `OPPOSE`：目前客觀證據不支持使用者判斷。
- `HOLD`：關鍵證據不足；在高風險行動中不支持繼續擴大暴露。

正式輸出仍應映射到標準決策詞：

- `GO`
- `CONDITIONAL_GO`
- `GUIDED_ONLY`
- `CHANGE_PLAN`
- `DELAY`
- `NO_GO`
- `ESCALATE`

Scout 不取代使用者、領隊或正式安全機制，但必須清楚說明支持或反對的證據、殘餘風險，以及什麼條件會使判斷改變。

## 3. 六力是核心問題的上位本體

`SCOUT_OUTDOOR_AI_AGENT_STANDARD` 定義六項戶外核心能力：

| 六力 | Scout capability | 使用者主要缺口 |
|---|---|---|
| 探索力 | Route Context Intelligence | 不理解路線的歷史、文化、自然、地形與觀察價值。 |
| 自信力 | Readiness & Pace Fit | 無法客觀判斷自己與隊伍的腳程、體能、經驗與路線需求是否匹配。 |
| 勇氣力 | Contextual Permissioning | 無法判斷此刻可不可以停、等、拍、攻頂、改線或撤退。 |
| 路線力 | Route Architecture Intelligence | 無法把路線拆成 CP、難點、撤退、補給、時間窗與替代方案。 |
| 天氣力 | Weather-to-Decision Intelligence | 無法把天氣資訊轉成 route-specific decision。 |
| 地圖力 | Navigation & Terrain Intelligence | 無法把位置、GPX、等高線、岔路與地形轉成導航及撤退判斷。 |

真正需要 Scout 的使用者通常不會六力完備。問題應來自一項或多項能力缺口，而不是為了逐一呼叫工具而編寫。

## 4. 核心 Field Eval 的准入規則

每一題核心登山問題必須：

1. 映射至少一項六力。
2. 存在可取得或可明確標示缺失的客觀 evidence。
3. 對應路線理解、現況判斷或下一步決策。
4. 是登山者可能在行前、途中或行後自然提出的問題。
5. 可由事實答案或標準決策詞表達，不依賴模型猜測測試作者意圖。

以下問題不應計入六力核心答題率：

- Scout 有哪些 tools、skills 或 models。
- transport 是否送出 packet。
- observer、admin、debug 或 container 狀態。
- 位置應分享給誰。
- 留守轉報訊息有哪些欄位。
- 為覆蓋所有已註冊工具而設計的模糊問題。

這些能力仍可保留在獨立套件：

- `workflow_eval`
- `admin_debug_eval`
- `robustness_eval`
- `adversarial_eval`
- `capability_probe_eval`

它們不得扭曲 outdoor field quality score。

## 5. 六力 600 題成果

依上述原則已建立 600 題題庫：

| Force | IDs | Count |
|---|---:|---:|
| 探索力 | `EXP-001`–`EXP-100` | 100 |
| 自信力 | `RPF-001`–`RPF-100` | 100 |
| 勇氣力 | `PER-001`–`PER-100` | 100 |
| 路線力 | `RTE-001`–`RTE-100` | 100 |
| 天氣力 | `WTH-001`–`WTH-100` | 100 |
| 地圖力 | `NAV-001`–`NAV-100` | 100 |

題號、ID 與題目文字已確認各 600 個且無重複。跨力問題按照使用者的主要能力缺口歸類。

## 6. Question Template 不等於 Eval Case

題庫中的自然語言問題只是 Question Template。包含「這裡、現在、前方、下一個」的問題，如果沒有當下位置與情境，人類和 AI 都無法合理回答。

例如：

> `PER-095` 這裡適合做臨時避風停留，還是需要繼續移動？

可執行評測單位必須是：

```text
Eval Case
= Question Template
+ Workspace
+ Boss Approach Location
+ Scenario Context
+ Expected Evidence Contract
+ Expected Decision Boundary
```

不能把缺少位置的問題交給模型，再把模型無法回答視為能力不足。

## 7. 位置是情境化評測的第一錨點

時間、地形、天氣、路線與其他資料可以由 Scout 的 Total Info、workspace tools 或 live API 取得，但「這裡」首先必須有明確位置。

開發評測採用每個 Boss Point 前 500 m 作為位置錨點，理由是：

- 使用者尚未進入主要難點。
- Scout 已經必須開始評估是否繼續。
- 能測試預警是否足夠提早，而不是進入危險後才描述風險。
- 每個位置都有不同 route、terrain、risk、CP 與撤退脈絡。

## 8. Boss Approach Anchor 推導規則

來源 workspace：

`/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI`

主要 artifacts：

- `outputs/boss_points.json`
- `outputs/risk/risk_ribbon.geojson`
- `candidates/checkpoints.json`
- `normalized/routes/route_summary.json`

推導方式：

```text
target_route_progress_m
= boss.route_position.distance_m - 500
```

座標必須沿 canonical risk ribbon 的 route distance interpolation 取得，不得使用直線距離回推，也不得手工虛構。必須保存 `travel_direction` 和 `route_progress_m`，避免原路往返或重疊路段只靠 lat/lon 而匹配到錯誤行程階段。

目前 workspace 的交叉檢查值：

| Boss Rank | Boss label | Boss progress | Approach progress | Approximate location |
|---:|---|---:|---:|---|
| 1 | 13.4K | 59,750 m | 59,250 m | 24.058167, 121.282862 |
| 2 | 6.1K | 49,750 m | 49,250 m | 24.053578, 121.241105 |
| 3 | 0.5K | 43,750 m | 43,250 m | 24.050482, 121.215181 |
| 4 | 5.2K | 48,750 m | 48,250 m | 24.047717, 121.237805 |
| 5 | 10K | 53,750 m | 53,250 m | 24.048744, 121.260415 |

這些值只用於驗證動態 generator，不應取代從 workspace 推導。所有 anchors 必須標示：

- `source_mode=synthetic_replay`
- `candidate_only=true`
- `runtime_safety_truth=false`
- source refs 與 source hashes

## 9. 600 題與五個位置的配置

建議在每一力中，將 100 題平均分配到五個 Boss Approach Anchors：

```text
每力 100 題
/ 5 anchors
= 每個 anchor 每力 20 題
```

因此每個位置會承擔六力共 120 題。即使某題詢問全線資訊，仍提供目前位置，使「前方、下一段、目前」有一致語意。

## 10. Total Info 的單一資料入口

正式運行與開發評測必須走相同入口：

```text
實際登山
GNSS hardware
  -> live_navigation_snapshot
  -> Total Info Entry
  -> tools / compact evidence / model

開發評測
Boss Approach fixture
  -> live_navigation_snapshot
  -> Total Info Entry
  -> tools / compact evidence / model
```

現有 `ScoutAssistantQuery` 已有 `live_navigation_snapshot`；Total Info 也會優先使用 Query snapshot，再退到 hardware GNSS snapshot。

已知缺口是 `tools/scout_ai_aihat2_fallback_eval.py` 的 `build_total_info()` 尚未注入 synthetic location，而 navigation tool 另用一組固定 synthetic position。這會使 Total Info 與工具看到不同位置，必須改成由同一個 `ScenarioContext` 注入。

## 11. Location Fixture 最小欄位

```json
{
  "anchor_id": "boss-rank-1-approach-500m",
  "boss_point_id": "boss...",
  "boss_rank": 1,
  "observed_at": "fixture reference time",
  "lat": 24.058167,
  "lon": 121.282862,
  "horizontal_accuracy_m": 5,
  "fix_quality": "synthetic_valid_fix",
  "route_progress_m": 59250,
  "distance_to_boss_along_route_m": 500,
  "nearest_cp_id": "derived by route join",
  "nearest_route_distance_m": 0,
  "heading_deg": "derived from route tangent",
  "travel_direction": "forward",
  "source": "synthetic_boss_approach_fixture",
  "candidate_only": true,
  "runtime_safety_truth": false
}
```

## 12. 位置固定後的其他情境資訊

位置只是第一錨點。Scout 應從當下或 workspace evidence 補齊：

- current time、日落與 daylight buffer；
- route segment、下一 CP、Boss Point 與撤退點；
- terrain/risk candidates；
- live weather、wind、rain、temperature、visibility；
- pace、body resource、walking stability；
- device/navigation readiness。

相同問題在不同情境下必須允許不同答案。這是檢驗模型是否真的使用 evidence，而不是背誦固定句子的必要條件。

## 13. 天氣的 Live 與 Replay 雙模式

地點固定不代表天氣固定。天氣應區分：

### 13.1 Live Weather Integration (`live_weather_integration`)

- 由 server-side CWA API 即時取得。
- 不暴露 API key。
- 保存 request time、valid time、dataset/source、raw hash 與 provenance。
- 不比對固定答案文字。
- 依當次 evidence 驗證決策是否一致。

### 13.2 Deterministic Weather Replay (`deterministic_weather_replay`)

- 使用 fixture/mock normalized response。
- 測試不依賴 live network。
- 可重現 freshness、QPF、warning 與 route intersection。
- 用於 regression 和模型比較。

Live mode 驗證整合與 freshness；replay mode 驗證可重現推理。兩者不能互相冒充。

## 14. 預期答案不是固定句子

評測不應保存完整 reference answer 供模型複製。每個 Case 應保存：

- `required_context`
- `required_evidence`
- `allowed_decisions`
- `forbidden_claims`
- `expected_source_refs`
- `missing_evidence_policy`

以 `PER-095` 為例：

1. 暴露、強風、前方有背風候選點：不支持原地停留。
2. 背風平坦、時間充足：支持限時停留。
3. GNSS stale 或位置不明：不得假裝知道「這裡」。

驗收重點是位置、evidence、decision 與 boundary 是否一致，而不是逐字比對。

## 15. 建議實作成果

正式開發應產生：

- `scout_ai_six_forces_scenarios.py`
- `tools/generate_scout_ai_six_forces_scenarios.py`
- Boss Approach Anchors machine-readable artifact
- Six-Forces 600 Case Mapping artifact
- fixture-backed weather replay artifacts
- `tests/test_scout_ai_six_forces_scenarios.py`
- Total Info / fallback eval integration tests

## 16. 驗收條件

1. 動態產生五個 anchors。
2. 每個 anchor 與 Boss route progress 相差 500 m，允許合理浮點誤差。
3. 五個座標均由 canonical route interpolation 產生。
4. 600 cases、每力 100、每 anchor 每力 20。
5. Total Info、selected tools 和 compact evidence 使用相同 scenario ID 與位置。
6. 實際硬體與 synthetic replay 使用同一 Query/Total Info boundary。
7. Live weather 具 freshness/provenance，fixture tests 不依賴網路。
8. 同一題在不同情境下可得到不同、但 evidence-consistent 的決策。
9. 不把 candidate terrain、weather 或 model text 升級成 runtime safety truth。
10. 不呼叫 `/safety/*`、不控制硬體、不進行 outbound send。

## 17. 核心結論

六力定義 Scout 應回答什麼；Boss Approach Location 定義「現在在哪裡」；Total Info 定義「此刻還知道什麼」。三者結合後，600 題才從語言題庫成為可驗證的戶外決策評測。

目標不是讓 Scout 背出 600 個答案，而是證明：

> 同一個問題放在不同位置、時間、天氣、地形與人員狀態下，Scout 能取得正確證據，並做出可預期、可解釋且不越權的不同判斷。
