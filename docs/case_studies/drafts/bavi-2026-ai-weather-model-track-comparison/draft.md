# Case Study Draft: 2026 Bavi AI weather-model track comparison

Status: draft review artifact

Boundary labels: `not_diagnosis`, `no_fault_assignment`, `not_official_sop`, `requires_human_review`

本草稿整理 2026 年第 9 號颱風巴威（BAVI）期間，AIGEFS、ECMWF AIFS 與 Google AI 氣象模型的名稱、來源與路徑比較主張。它是氣象知識與預報驗證案例，不是官方預報、警報或 Scout runtime 規則。

## 查證摘要

### AIGEFS

- 正式全名為 NOAA/NCEP 的 `Artificial Intelligence Global Ensemble Forecast System`。
- NOAA 於 2025-12-17 將 AIGEFS v1.0 作業化；它以 Google DeepMind GraphCast 為基礎，由 31 個成員形成集合預報。
- `HGEFS` 才是把 31 個 AIGEFS 成員與 31 個傳統 GEFSv12 成員合併的 62 成員混合集合。
- Open-Meteo 提供 AIGEFS 資料的 API／再分發介面，但不是 AIGEFS 的開發者。因此「Open-Meteo 利用 AI 模擬 GEFS」會混淆模型所有者、資料提供者，以及 AIGEFS 與 HGEFS 的關係。

建議改寫：

> AIGEFS 是 NOAA/NCEP 開發、以 GraphCast 為基礎的 31 成員 AI 全球集合預報系統；Open-Meteo 提供其資料存取介面。若要把 AI 與傳統 GEFS 成員合併，對應的系統名稱是 HGEFS。

### ECMWF AIFS

- AIFS 是 ECMWF 的 `Artificial Intelligence Forecasting System`，以機器學習從歷史再分析與作業分析資料學習大氣演變。
- `AIFS Single` 已於 2025-02-25 正式作業化；`AIFS ENS` 已於 2025-07-01 正式作業化。ECMWF 於 2026-05-12 將兩者升級至 v2。
- AIFS 與物理式 IFS 並行且互補，但已不能描述為「目前只做為 EC IFS 輔助」或仍只是實驗模型。
- 「速度快、能耗低」方向正確；ECMWF 公開說明提到單次預報能耗約可降低 1,000 倍，但這不代表每個變數、區域或極端事件都必然優於 IFS。

建議改寫：

> ECMWF AIFS 是已正式作業化的資料驅動預報系統，包含單一路徑與集合版本，與傳統物理式 IFS 並行互補；推論速度與能耗顯著較低，但仍須按變數、區域、預報時效與個案驗證技巧。

### Google AI 氣象模型

- 「Google AI 天氣模型」不是唯一且足夠精確的模型名稱。Google 的模型家族至少包含 GraphCast／WeatherNext Graph、GenCast／WeatherNext Gen，以及 Weather Lab 的實驗性專用熱帶氣旋模型。
- 2026 巴威相關二手報導把圖中路徑標為 `Google FNV3`；Google 官方公開頁面則以「latest experimental cyclone model」描述能產生 50 個情境、預測生成、路徑、強度、大小與形狀的模型。沒有原圖圖例或資料欄位時，不應逕自把它寫成 GraphCast、GenCast，或泛稱一個「完全由神經網路學習」的單一 Google 模型。
- AI 模型仍依賴觀測、再分析或傳統作業分析提供訓練資料與初始場；「完全由神經網路學習」容易讓讀者誤以為它不依賴傳統氣象資料鏈。

建議改寫：

> 圖中若標示 Google FNV3，應保留該精確標籤，並註明它屬 Google Weather Lab 的實驗性熱帶氣旋 AI 預報；若圖上標的是 GenCast 或 WeatherNext Graph，則需依各自的確切模型說明，不能統稱為同一套 Google AI 模型。

## 巴威個案的可驗證範圍

- 中央氣象署的即時資料確認本事件為 `202609` 巴威，海上警報於 2026-07-09 14:30 發布、陸上警報於 2026-07-10 05:30 發布。
- 截至本草稿查證日 2026-07-11，氣象署個案頁仍未填入解除時間、最終侵臺路徑分類、登陸地段與完整事後分析；日本氣象廳也尚未發布 2609 的事後確定位置表。
- 使用者提供的文字主張黑線代表實際路徑，且 AIGEFS 在五條預測中最接近。此主張可以保留為待驗證的個案觀察，但目前缺少原圖、模式起報時間、路徑追蹤方法、集合平均或單一成員定義，以及官方最終 best track，尚不能重現或量化「勝出」。
- 即使日後量化確認 AIGEFS 在這一次起報最接近，也只能支持「此個案、此起報、此評分方法下表現最佳」，不能推出 AIGEFS 普遍優於 AIFS、Google 模型、IFS 或 GFS。

## 公平比較所需欄位

1. `storm_id`：例如 `202609`／BAVI。
2. `forecast_initialized_at`：所有模式須對齊同一 UTC 起報時間。
3. `model_id` 與 `model_version`：區分 AIGFS、AIGEFS、HGEFS、AIFS Single、AIFS ENS、FNV3、GenCast 等。
4. `forecast_kind`：deterministic、ensemble mean、ensemble median 或指定 member。
5. `tracker_method`：各模式的颱風中心如何從格點場抽取。
6. `verification_track_source`：CWA、JMA、JTWC 或其他 best track，不可混用而不註明。
7. `lead_hours`：在共同的 24、48、72、96、120 小時預報時效比較。
8. `track_error_km`：逐時效球面距離誤差，以及共同時效的平均／中位誤差。
9. `ensemble_spread_km`：不可只畫集合平均而隱藏不確定性。
10. `landfall_or_passage_classification`：是否登陸、最近海島通道與最接近距離須使用一致定義。

## Scout Design Implications

- Taxonomy: `weather_model_provenance`, `forecast_cycle_alignment`, `ensemble_uncertainty_preservation`, `single_event_model_verification`, `official_warning_authority`.
- `pretrip_weather.model_identity_and_provider_provenance`: 顯示模型開發者、資料供應者、模型版本與 deterministic／ensemble 類型，避免把 Open-Meteo 誤認為 AIGEFS 開發者。
- `pretrip_weather.forecast_cycle_alignment`: 只在相同起報時間與共同預報時效下比較模式。
- `pretrip_weather.ensemble_spread_preservation`: 保留集合成員範圍、平均與離散度，不把單一路徑當成完整風險分布。
- `after_action.weather_track_verification`: 等官方事後 best track 發布後才計算誤差並標示評分方法；事件進行中只標 `provisional`。
- `pretrip_weather.official_warning_precedence`: AI 與傳統模式皆為候選證據；戶外行程決策仍以中央氣象署／所在地官方氣象機關的警報與人工預報為權威來源。

以上都是 `assumption`／`future_research` 等級的案例訊號，不會自動修改 Scout 安全門檻、`cwa-weather` layer 或 runtime safety truth。

## Non-Goals

- 不宣告任何模型在所有颱風或所有預報時效中普遍勝出。
- 不以一張視覺疊圖取代同起報時間、同時效的定量驗證。
- 不把實驗性 Google Weather Lab 輸出當成官方警報。
- 不從此案例自動更改 Scout 氣象風險門檻或行程決策。

## Discussion Questions

1. Scout 是否應把 `model_owner`、`data_provider`、`model_version` 與 `forecast_kind` 設為每筆模式證據的必填 provenance？
2. 沒有同一起報時間、集合定義與官方 best track 時，UI 是否應阻止顯示「模型勝出」標籤？
3. 事後評分應採共同時效平均路徑誤差、最近接近點、登陸分類，還是同時保留多個指標？
4. 事件仍進行中時，Scout 是否應顯示 `provisional` 並延後建立永久學習 artifact？

## Promotion Checklist

- 取得原始比較圖、圖例、資料來源與 UTC 起報時間。
- 確認 `Google FNV3` 在原圖／資料中的正式模型識別，不以相似名稱代換。
- 等 CWA 或 JMA 發布事後確定路徑，再用共同時效重算各模式誤差。
- 人工審核後才決定是否移至 `docs/case_studies/accepted/`。
- 任何 runtime、layer contract 或 Phase 1/2 規格變更另案處理。

## Sources

- NOAA/NWS, [SCN 25-89: AIGFS, AIGEFS and HGEFS implementation](https://www.weather.gov/media/notification/pdf_2025/scn25-89_AIGFS_AIGEFS_and_HGEFS.pdf).
- NOAA/NCEP, [Development of a hybrid ML and physical model global ensemble system](https://repository.library.noaa.gov/view/noaa/70717).
- Open-Meteo, [Ensemble API documentation](https://open-meteo.com/en/docs/ensemble-api).
- ECMWF, [ECMWF's AI forecasts become operational](https://www.ecmwf.int/en/about/media-centre/news/2025/ecmwfs-ai-forecasts-become-operational) and [AIFS Machine Learning data](https://www.ecmwf.int/en/forecasts/datasets/aifs-machine-learning-data).
- Google DeepMind, [How we're supporting better tropical cyclone prediction with AI](https://deepmind.google/blog/how-were-supporting-better-tropical-cyclone-prediction-with-ai/).
- 中央氣象署, [2026 年第 9 號颱風巴威個案頁](https://rdc28.cwa.gov.tw/TDB/public/typhoon_detail?typhoon_id=202609).
- 日本氣象廳, [2026 年台風位置表](https://www.data.jma.go.jp/typhoon/position_table/table2026.html).
- 使用者提供文字，以及二手報導中對「觀氣象看天氣」圖例的轉述；僅用於保存待驗證主張，不作模型規格的權威來源。
