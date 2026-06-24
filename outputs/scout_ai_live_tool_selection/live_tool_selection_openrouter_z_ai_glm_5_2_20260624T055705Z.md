# Scout AI Live Tool Selection Eval

- model: `openrouter:z-ai/glm-5.2`
- project: `chilai_nanhua_day1`
- tool_selection_pass_rate: `10/10`
- pass_rate: `10/10`
- assistant_api_pre_augmentation_used: `False`
- counts_only_model_native_tool_calls: `True`

| Case | Required selected | Full answer ok | Native tool calls | Missing required |
| --- | --- | --- | --- | --- |
| field-031 | True | True | `scout.ai.gee_environment.assess.v0, scout.ai.weather_window.assess.v0, pydantic_ai.tool.search_scout_terrain_scores.v0, scout.ai.cwa_environment.assess.v0, pydantic_ai.tool.search_scout_risk_scores.v0` | `-` |
| field-032 | True | True | `pydantic_ai.tool.search_scout_terrain_scores.v0, pydantic_ai.tool.search_scout_risk_scores.v0, scout.ai.weather_window.assess.v0, scout.ai.gee_environment.assess.v0, scout.ai.cwa_environment.assess.v0` | `-` |
| field-034 | True | True | `scout.ai.route_context.assess.v0, scout.ai.weather_window.assess.v0, scout.ai.navigation_terrain.assess.v0, scout.ai.cwa_environment.assess.v0` | `-` |
| field-035 | True | True | `scout.ai.cwa_environment.assess.v0, scout.ai.weather_window.assess.v0, scout.ai.gee_environment.assess.v0` | `-` |
| field-036 | True | True | `pydantic_ai.tool.search_scout_risk_scores.v0, scout.ai.gee_environment.assess.v0, scout.ai.weather_window.assess.v0, scout.ai.cwa_environment.assess.v0, pydantic_ai.tool.search_scout_terrain_scores.v0, scout.ai.route_context.assess.v0` | `-` |
| field-037 | True | True | `pydantic_ai.tool.search_scout_terrain_scores.v0, scout.ai.weather_window.assess.v0, scout.ai.gee_environment.assess.v0, scout.ai.cwa_environment.assess.v0, pydantic_ai.tool.search_scout_risk_scores.v0` | `-` |
| field-039 | True | True | `scout.ai.weather_window.assess.v0, scout.ai.gee_environment.assess.v0, scout.ai.cwa_environment.assess.v0` | `-` |
| seed-027 | True | True | `pydantic_ai.tool.search_scout_terrain_scores.v0, scout.ai.weather_window.assess.v0, scout.ai.gee_environment.assess.v0, pydantic_ai.tool.search_scout_risk_scores.v0, scout.ai.cwa_environment.assess.v0` | `-` |
| seed-088 | True | True | `pydantic_ai.tool.search_scout_terrain_scores.v0, pydantic_ai.tool.search_scout_risk_scores.v0, scout.ai.weather_window.assess.v0, scout.ai.gee_environment.assess.v0, scout.ai.cwa_environment.assess.v0` | `-` |
| seed-089 | True | True | `scout.ai.weather_window.assess.v0, scout.ai.gee_environment.assess.v0, scout.ai.cwa_environment.assess.v0, scout.ai.route_readiness.assess.v0` | `-` |

## Answer Previews

### field-031

Question: 白牆下這段還適合走嗎？

## 白牆下這段還適合走嗎？— 多源證據綜合判斷  ### 綜合決策傾向：**不建議照原節奏通過，建議改線/縮短/撤退**  以下為五項工具證據的交叉比對結果（均為候選規劃證據，非 runtime safety truth）：  ---  ### 1. 天氣窗口（Weather Window）— CONDITIONAL_GO ⚠️ - **最高風險段**：`weather.seg.tianchi_late`（7.6 km → 14.55 km），風險等級 **ELEVATED**，final_risk=**0.62**，weather_risk=**0.42** - **關鍵因素**：`late-day fog chance`（午後起霧/白牆機率）、`daylight buffer pressure`（日照餘裕壓力）、`wet boardwalk possible`（濕滑棧道） - **其他段**：`yunhai_approach`（3.2–7.6 km）為 MODERATE，有 `afternoon cloud buildup`、`ridge wind exposure` - 來源：`outputs/route_weather_package.reviewed.json`  ### 2. CWA 官方天氣環境 — CHANGE_PLAN 🚫 - **警特報**：南投山區豪雨 advisory（moderate severity） - **觀測**：廬山雨量站 1h=8.5mm、24h=42.0mm - **QPF**：max=**32.0mm**、p95=29.1mm，峰值窗

### field-032

Question: 現在風雨是否會放大失溫風險？

## 風雨是否放大失溫風險 — 綜合判讀  **結論：是的，目前證據顯示風雨條件確實會放大失溫風險，且多項指標同時指向 ELEVATED 等級。**  以下為五項工具證據的交叉比對：  ---  ### 1. 天氣窗口（Weather Window）— 決策：DELAY - **來源**：`outputs/route_weather_package.reviewed.json`（reviewed） - 路線特定條件明確標示：**`strong wind exposure`（強風曝露）** 與 **`cold stress / hypothermia context`（冷壓力/失溫情境）** - 最高風險段 `weather.seg.tianchi_late`（7.6–14.55 km，ETA 14:58–18:28），final_risk=**0.62**，risk_level=**ELEVATED** - 因素包含：`ridge wind exposure`（稜線風曝露）、`late-day fog chance`、`daylight buffer pressure`、`wet boardwalk possible` - Weather-to-Decision 候選判斷為 **DELAY**：強風低溫、裝備與撤退 buffer 完成審核前，不得承諾曝露稜線或紮營計畫  ### 2. CWA 官方環境 — 決策：CHANGE_PLAN - **來源**：`outputs/environment/cwa/` 系列（candidate_only, human_review_requ

### field-034

Question: 這段如果起霧會不會容易失向？

## 起霧失向風險評估 — 奇萊南華 Day 1  以下為基於四項 Scout 工具回傳的候選證據綜合，**均為行前候選證據，非 runtime safety truth**。  ---  ### 1. 起霧可能性 — 有明確證據顯示風險存在  | 來源 | 關鍵發現 | |---|---| | **Weather Window** (`outputs/route_weather_package.reviewed.json`) | 最高風險段 `weather.seg.tianchi_late`（7.6K–14.55K，ETA 14:58–18:28）評為 **ELEVATED**（final_risk=0.62, weather_risk=0.42），明確列出 **"late-day fog chance"** 為風險因子。中段 `weather.seg.yunhai_approach`（3.2K–7.6K）為 MODERATE，含 **"afternoon cloud buildup"**。 | | **CWA Environment** (`outputs/environment/cwa/`) | 南投山區 **豪雨特報**（moderate severity）；廬山雨站觀測 24h 累積 42mm、1h 8.5mm；QPF 峰值 32mm（p95=29.1mm），雨機率 70%。雨後濕度高、午後對流旺盛，**起霧條件明確存在**。CWA 決策為 **CHANGE_PLAN**，需人工複核。 | | **Dense Fog 門檻** | Weather Window 政策

### field-035

Question: 今天的天氣窗口是否足夠？

## 天氣窗口評估結果：**不足，建議延後（DELAY）**  三項 Scout 工具一致指向今天的天氣窗口不夠安全出發。以下為綜合證據摘要：  ---  ### 1. Weather Window 決策：**DELAY** - **來源**：`outputs/route_weather_package.reviewed.json`（reviewed） - **主因**：強風曝露、低溫失溫風險升高、午後起霧機率、日照 buffer 壓力、步道可能濕滑 - **最高風險段**：`weather.seg.tianchi_late`（7.6km–14.55km，往天池末段）   - final_risk = **0.62（ELEVATED）**   - ETA 約 14:58–18:28，需嚴守日照紀律，不可任意延遲 - **三段風險分佈**：  | 路段 | 風險等級 | final_risk | 主要因素 | |------|---------|-----------|---------| | approach（0–3.2km） | LOW | 0.22 | 早晨天氣穩定、林道接近 | | yunhai_approach（3.2–7.6km） | MODERATE | 0.54 | 午後雲量增多、稜線風曝、濕地可能 | | tianchi_late（7.6–14.55km） | **ELEVATED** | **0.62** | 午後起霧、日照壓力、濕木板步道 |  ---  ### 2. CWA 官方氣象證據：**CHANGE_PLAN** - **來源**：`outputs/

### field-036

Question: 溪水暴漲會不會阻斷路線？

## 溪水暴漲是否會阻斷路線？— 行前候選證據綜整  以下為 read-only 行前證據綜整，**非 runtime safety truth**，需人工複核後才能作為路線決策依據。  ---  ### 1. 降雨與水文背景（多重證據一致指向升高風險）  | 證據來源 | 關鍵數據 | 決策建議 | |---|---|---| | **CWA 警特報** | 南投山區豪雨 advisory（moderate）；1 件 warning | **CHANGE_PLAN** | | **CWA QPF** | 6h 累積 max=32.0mm、p95=29.1mm、peak window=2026-06-24 12:00–18:00Z；heavy_rain_event_count=1 | 升高天氣檢視壓力 | | **CWA 觀測** | 廬山雨量站：1h=8.5mm、24h=42.0mm | 已有實質降雨 | | **GEE GPM IMERG** | 72h 雨量 latest=88.0mm（max=101.0mm，trend=rising）；24h=42.0mm（rising） | 前期降雨已顯著且持續上升 | | **GEE SMAP L4** | 表面濕度 latest=0.74（max=0.82，trend=rising）；根區濕度 0.68（rising） | 土壤含水量高，地表已飽和趨勢 |  > **來源 refs**: `outputs/environment/cwa/warnings.geojson` (W-C0033-001)、`outputs/enviro

### field-037

Question: 這段下雨後會變成落石區嗎？

## 雨後落石風險評估 — chilai_nanhua_day1  我已呼叫完整的天氣-地形複合風險工具包（weather_window + CWA + GEE + risk_scores + terrain_scores），以下是綜合判讀。  ---  ### 🌧️ 降雨與水文背景（確有顯著降雨）  | 證據來源 | 關鍵數據 | source_ref | |---|---|---| | **CWA 警特報** | 南投山區豪雨特報（heavy_rain, moderate） | `outputs/environment/cwa/warnings.geojson` | | **CWA 觀測** | 廬山雨站：1h=8.5mm、24h=42.0mm | `outputs/environment/cwa/observations.geojson` | | **CWA QPF** | 6h累積最大 32.0mm、p95=29.1mm、降雨機率 70%、peak window 2026-06-24T12:00–18:00Z | `outputs/environment/cwa/qpf_corridor_summary.json` | | **GEE GPM** | 72h 前期雨量 latest=88.0mm（↑上升）、24h=42.0mm（↑上升） | `outputs/environment/gee/gpm_imerg_corridor_summary.json` | | **GEE SMAP** | 地表濕度 latest=0.74（↑上升）、根區濕度 0.68（↑上升） |

### field-039

Question: 風寒和濕衣是否已經構成風險？

## 風寒與濕衣風險評估 — chilai_nanhua_day1  ### 綜合判斷：是，風寒與濕衣已構成風險  三項工具證據一致指向 **強風低溫曝露 + 降雨濕衣** 的複合失溫風險升高，且均建議暫緩或調整計畫。  ---  ### 1. Weather Window — 決策：DELAY  | 項目 | 內容 | |------|------| | 決策 | **DELAY**（建議延後） | | 警報碼 | `WIND`、`COLD` | | 路線特定條件 | strong wind exposure、cold stress / hypothermia context、wet boardwalk possible | | 最高風險段 | `weather.seg.tianchi_late`（7.6–14.55 km），final_risk=**0.62**，ELEVATED | | 主要原因 | 使用者回報強風或低溫曝露，失溫風險可能升高；稜線與紮營決策需同時審核風、溫度、裝備與撤退 buffer | | 來源 | `outputs/route_weather_package.reviewed.json`（reviewed） |  > ⚠️ 此為 Weather-to-Decision 候選判斷，**不是 runtime safety truth**。  ---  ### 2. CWA 官方環境證據 — 決策：CHANGE_PLAN  | 項目 | 內容 | |------|------| | 決策 | **CHANGE_PLAN** | | 警特報 | 南投山區豪雨

### seed-027

Question: 哪些地方下雨後風險會變高？

## 雨後風險升高地點分析 — chilai_nanhua_day1  以下為五項工具證據的綜合判讀，所有證據均為 **候選規劃證據（candidate-only）**，非 runtime safety truth。  ---  ### 🌧️ 當前水文與降雨背景（已偏高且持續上升）  | 指標 | 數值 | 趨勢 | 來源 | |------|------|------|------| | GPM 72h 累積雨量 | **88.0 mm** | ↑ rising | `gee_gpm_imerg_corridor_summary` | | GPM 24h 累積雨量 | 42.0 mm | ↑ rising | 同上 | | SMAP 表面濕度 | **0.74** | ↑ rising | `gee_smap_l4_corridor_summary` | | CWA QPF 6h 最大 | **32.0 mm** | peak window 2026-06-24T12:00–18:00Z | `cwa_qpf_corridor_summary` | | CWA 警特報 | **南投山區大雨特報**（moderate） | — | `cwa_warnings_geojson` | | 廬山雨量站觀測 | 1h=8.5mm, 24h=42mm | — | `cwa_observations_geojson` |  > ⚠️ 前期降雨已使地表濕度偏高，且 QPF 預報仍有 32mm 峰值，雨後風險疊加效應明確。  ---  ### 📍 雨後風險升高的路段（由高至低）  #### 1

### seed-088

Question: 天氣與地形風險是否重疊？

## 天氣與地形風險重疊分析 — chilai_nanhua_day1  已呼叫完整 WEATHER_TERRAIN_OVERLAP_BUNDLE（五工具），以下為綜合判讀。  ---  ### ✅ 結論：是的，天氣與地形風險確實重疊，且重疊區段集中在後半段  ---  ### 1. 路線分段天氣×地形重疊（來源：weather_window）  | 路段 | 里程 | terrain_risk | weather_risk | final_risk | 等級 | 重疊因素 | |------|------|-------------|-------------|-----------|------|---------| | `weather.seg.approach` | 0–3.2 km | 0.22 | 0.18 | 0.22 | **LOW** | 晨間穩定天氣、林道接近 | | `weather.seg.yunhai_approach` | 3.2–7.6 km | **0.58** | 0.38 | 0.54 | **MODERATE** | 午後雲系發展、稜線風暴露、濕滑地形可能 | | `weather.seg.tianchi_late` | 7.6–14.55 km | **0.52** | **0.42** | **0.62** | **ELEVATED** | **午後起霧、日照壓力、濕滑棧道** |  > 來源：`outputs/route_weather_package.reviewed.json`（source_status=reviewed）  *

### seed-089

Question: 是否需要延後出發？

## 是否需要延後出發？— 綜合證據判讀  **簡要結論：多項證據指向「建議延後或變更計畫」，目前不具備直接出發條件。**  以下為四項工具的交叉判讀（均為 candidate-only 行前規劃證據，非 runtime safety truth）：  ---  ### 1. 路線準備度（Route Readiness） - **決策：CONDITIONAL_GO**（可有條件進入人工出發門檢） - **信心度：低**；**警告缺口：8 項** - 關鍵限制：   - 已審核 planning package ≠ 出發核准   - 日照政策尚未用 sunrise/sunset window 完整評估   - 隊友手機電量、水計畫、頭燈數量仍需審核確認 - 最晚折返點：**雲海保線所**，必須於 `2013-10-08T14:58:50+08:00` 前離開/折返 - 目標 ETA：`2013-10-08T18:28:50+08:00`；最晚回程：`20:30` - *Source: `outputs/readiness_report.json`, `outputs/planned_eta.json`*  ### 2. 天氣窗（Weather Window） - **決策：DELAY**（建議延後） - 原因：   - **強風低溫曝露**，失溫風險可能升高   - 稜線與紮營決策需同時審核風、溫度、裝備與撤退 buffer   - 路線特定條件：strong wind exposure、cold stress/hypothermia context、late-day fog c
