# Scout AI Live Tool Selection Eval

- model: `openrouter:z-ai/glm-5.2`
- project: `chilai_nanhua_day1`
- pass_rate: `7/10`
- assistant_api_pre_augmentation_used: `False`
- counts_only_model_native_tool_calls: `True`

| Case | Required matched | Native tool calls | Missing required |
| --- | --- | --- | --- |
| field-031 | False | `pydantic_ai.tool.search_scout_terrain_scores.v0, pydantic_ai.tool.search_scout_risk_scores.v0, scout.ai.route_context.assess.v0, scout.ai.cwa_environment.assess.v0, scout.ai.gee_environment.assess.v0, scout.ai.weather_window.assess.v0` | `-` |
| field-032 | True | `pydantic_ai.tool.search_scout_terrain_scores.v0, scout.ai.gee_environment.assess.v0, scout.ai.cwa_environment.assess.v0, scout.ai.weather_window.assess.v0, pydantic_ai.tool.search_scout_risk_scores.v0` | `-` |
| field-034 | False | `scout.ai.cwa_environment.assess.v0, scout.ai.weather_window.assess.v0, scout.ai.route_context.assess.v0, scout.ai.navigation_terrain.assess.v0` | `-` |
| field-035 | True | `scout.ai.weather_window.assess.v0, scout.ai.cwa_environment.assess.v0, scout.ai.gee_environment.assess.v0` | `-` |
| field-036 | True | `pydantic_ai.tool.search_scout_terrain_scores.v0, scout.ai.weather_window.assess.v0, scout.ai.cwa_environment.assess.v0, scout.ai.gee_environment.assess.v0, pydantic_ai.tool.search_scout_risk_scores.v0` | `-` |
| field-037 | True | `pydantic_ai.tool.search_scout_terrain_scores.v0, pydantic_ai.tool.search_scout_risk_scores.v0, scout.ai.weather_window.assess.v0, scout.ai.gee_environment.assess.v0, scout.ai.cwa_environment.assess.v0` | `-` |
| field-039 | True | `scout.ai.gee_environment.assess.v0, scout.ai.weather_window.assess.v0, scout.ai.cwa_environment.assess.v0` | `-` |
| seed-027 | True | `pydantic_ai.tool.search_scout_terrain_scores.v0, scout.ai.weather_window.assess.v0, pydantic_ai.tool.search_scout_risk_scores.v0, scout.ai.gee_environment.assess.v0, scout.ai.cwa_environment.assess.v0` | `-` |
| seed-088 | False | `pydantic_ai.tool.search_scout_terrain_scores.v0, pydantic_ai.tool.search_scout_risk_scores.v0, scout.ai.gee_environment.assess.v0, scout.ai.weather_window.assess.v0, scout.ai.cwa_environment.assess.v0` | `-` |
| seed-089 | True | `scout.ai.gee_environment.assess.v0, scout.ai.cwa_environment.assess.v0, scout.ai.weather_window.assess.v0, scout.ai.route_readiness.assess.v0` | `-` |

## Answer Previews

### field-031

Question: 白牆下這段還適合走嗎？



### field-032

Question: 現在風雨是否會放大失溫風險？

## 風雨是否放大失溫風險 — 證據綜合判斷  **簡短回答：是，目前多源證據一致顯示風雨條件正在放大失溫風險，且已達需要改變計畫的保守門檻。**  ---  ### 1. 天氣窗 (Weather Window) — 決策：DELAY  - **觸發規則**：`query_reported_wind_cold_exposure_review`

### field-034

Question: 這段如果起霧會不會容易失向？



### field-035

Question: 今天的天氣窗口是否足夠？

## 天氣窗口評估：奇萊南華 Day 1（chilai_nanhua_day1）  ### 綜合判斷：⚠️ 天氣窗口**不足夠直接出發**，需人工複核  三個證據來源出現分歧，以下逐層說明：  ---  ### 1. Route Weather Package（search_scout_weather_window） **決策：CONDITIONAL_GO（有條件通過）** — 但非自動放行  | 路段 | 風險等級 | final_risk | 主要因素 | |------|---------|-----------|---------| | approach（0–3.2K） | LOW | 0.22 | 早晨天氣穩定、林道接近 | | yunhai_approach（3.2–7.6K） | MODERATE | 0.54 | 午後雲量增多、稜線風暴露、濕地可能 | | **tianchi_late（7.6–14.55K）** | **ELEVATED** | **0.62** | **

### field-036

Question: 溪水暴漲會不會阻斷路線？

## 溪水暴漲是否會阻斷路線？— 行前候選證據綜整  以下為五項工具回傳的唯讀候選證據綜整，**均非 runtime safety truth**，需人工複核後方可做最終決策。  ---  ### 1. 降雨與水文背景（多源一致偏高）  | 證據來

### field-037

Question: 這段下雨後會變成落石區嗎？

## 雨後落石風險評估 — chilai_nanhua_day1  我已同時查詢天氣窗、CWA 官方天氣、GEE 水文背景、風險分數與地形分數五項證據。以下是綜合判讀：  ---  ### 🌧️ 當前降雨與前兆雨量（確有降雨事實）  | 證據來源 | 關鍵數據 | source ref | |---|---|---| | **CWA 警特報** | 南投山區豪雨特報（heavy rain advisory, severity=moderate） | `outputs/environment/cwa/warnings.geojson` | | **CWA 觀測** | 廬山雨量站：1h=8.5mm、

### field-039

Question: 風寒和濕衣是否已經構成風險？

## 風寒與濕衣風險評估 — chilai_nanhua_day1  ### 綜合判斷：是，風寒與濕衣已構成可辨識風險，三項工具均建議延後或變更計畫。  以下依據三項已完成的唯讀工具結果綜合說明：  ---  ### 1. 風寒（Wind Chill / 失溫）風險  **Weather Window** 明確觸發 `WIND` + `COLD` 警示碼，決策為 **DELAY**： - 路線條件包含 `strong wind exposure`（強風曝露）與 `cold stress / hypothermia context`（冷壓力/失溫情境）。 - 中段（yunhai_approach, 3.2–7.6 km）因素含 `ridge wind exposure`（稜線風曝露）。 - 最高風

### seed-027

Question: 哪些地方下雨後風險會變高？

## 雨後風險變高地點分析 — chilai_nanhua_day1  以下基於五個 Scout 工具的候選證據綜合，所有證據均為 **candidate-only，非 runtime safety truth**。  ---  ### 🌧️ 降雨背景（CWA + GEE）  | 來源 | 關鍵數據 | 備註 | |------|---------|------| | CWA QPF 走廊摘要 | max=32

### seed-088

Question: 天氣與地形風險是否重疊？



### seed-089

Question: 是否需要延後出發？

## 是否需要延後出發？— 綜合判斷  已呼叫完整的 ROUTE_READINESS_ENV_BUNDLE（route_readiness + weather_window + CWA + GEE），以下為四個工具的候選證據綜合：  ---  ### 🚦 各工具決策摘要  | 工具 | 決策 | 信心 | 來源 | |------|------|------|------| | Route Readiness | **CONDITIONAL_GO** | 低 | `outputs/readiness_report.json` | | Weather Window | **DELAY** | 中 | `outputs/route_weather_package.reviewed.json` | | CWA Environment | **CHANGE_PLAN** | — | `outputs/environment/cwa/cwa_weather_evidence.json` | | GEE Environment | **CHANGE_PLAN** | — | `outputs/environment/gee/smap_l4_corridor_summary.json` |  ---  ### 📋 關
