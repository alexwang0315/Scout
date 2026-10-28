# Scout Dashboard 全面 UX／資訊架構／視覺層級審查

審查日期：2026-09-21
審查模式：`product-design:audit` + browser qualification evidence
產物狀態：`PARTIAL AUDIT / DEMO READY`
正式頁面：未修改

這一輪先完成全 Dashboard inventory 與可互動設計 demo。正式頁面仍維持原狀，尚未進入自動修正階段。

## 先看結論

目前 Dashboard 的主要問題不是單一 Pace Fit 或 Body Index 元件，而是整個資訊架構同時承擔三種不同工作：行程決策、候選證據檢視、系統除錯。它們現在共用同一個 sidebar 與同一種 panel 語言，導致使用者很難在第一眼回答三個問題：

1. 我現在在哪個工作流程？
2. 這一頁最重要的結果是什麼？
3. 下一個最常做的操作在哪裡？

本次先提出三個共用原則：

- 每個工作流程只有一個固定控制中心；選取節點或區間後，同步更新地圖、結果、證據與下一步。
- 主要結果先於計算細節；沒有個人估計時顯示 `--`，但保留歷史平均與基準資料。
- 技術邊界、候選狀態、raw payload、renderer、QGIS receipt 移到資訊 icon 的 hover／keyboard focus hint 或次要 drawer。

完整 route、map surface、state、control priority inventory 在 [scout-dashboard-ux-inventory-20260921.json](/home/alexwang0315/work/scout-fusion/docs/admin/scout-dashboard-ux-inventory-20260921.json)。三種可操作畫面在 [scout-dashboard-ux-demo-20260921.html](/home/alexwang0315/work/scout-fusion/docs/admin/scout-dashboard-ux-demo-20260921.html)。

## 審查範圍與證據

### 已盤點

- 26 個 Dashboard／sidebar route：route contract 的 25 個 route，加上 sidebar 可進入但 contract 未註冊的 `trip-notebook`。
- 7 個外部或嵌入 surface：`/admin/dashboard`、`/admin`、`/admin/pretrip`、`/admin/trip-notebook/`、`/admin/debug`、`/admin/intelligence`、`/admin/dashboard/scout-monitor`。
- 9 個 map surface：7 個 native map 加上 `#pretripMapFrame` 與 weather embedded map。
- Workspace、GPX／HealthExport 匯入、route context、CP timeline、pace、body index、permission、architecture、weather、navigation、emergency、assistant、system／diagnostic。
- 首次載入、資料完整、資料不足、空資料、錯誤與恢復的共同狀態模型。

### 目前可引用的 browser 證據

qualification artifact 位於 `/home/alexwang0315/work/scout-fusion/artifacts/dashboard-ux-audit-20260921`：16 個案例中 10 PASS、6 FAIL；但 qualification contract 本身標示完整 live visual/control evidence 尚未取得，因此不把這次 run 當作全畫面 UX 通過。

目前最直接的畫面證據：

- Diagnostic 首屏包含長篇實作邊界與技術聲明，結果卡被推到下面：[diagnostic-controls/final.png](/home/alexwang0315/work/scout-fusion/artifacts/dashboard-ux-audit-20260921/cases/diagnostic-controls/final.png)。
- Navigation partial state 進入後幾乎只有 sidebar 與空白工作區：[navigation-partial-read-only-shell/final.png](/home/alexwang0315/work/scout-fusion/artifacts/dashboard-ux-audit-20260921/cases/navigation-partial-read-only-shell/final.png)。
- Architecture 初始畫面顯示 `No segment selected`，未替使用者預選第一個可用區段：[architecture-dynamic-rudy-tiles/final.png](/home/alexwang0315/work/scout-fusion/artifacts/dashboard-ux-audit-20260921/cases/architecture-dynamic-rudy-tiles/final.png)。

qualification 的 6 個失敗也必須保留，不可當成 UX 工作已完成：Diagnostic 50/50、Navigation partial truth、weather overlay 的 workspace mutation、Navigation dynamic tile timeout、Architecture 沒有 active Fit matrix、Weather 未提升到較高 native generation。這些是現況與環境／回歸證據，不在本輪自行修改。

## 目前 IA：使用者流程與系統工具混在一起

現有 sidebar 在 [scout-dashboard-v0.1.html](/home/alexwang0315/work/scout-fusion/docs/admin/scout-dashboard-v0.1.html:11914) 同時放入：

| 區塊 | 現有 route | UX 判斷 |
| --- | --- | --- |
| 概覽 | Overview | 使用者入口，應只回答目前結果與下一步。 |
| 規劃與匯入 | Workspace、Trip Intake、Country Material Pool | 同一條工作流程，應共享工作區與匯入狀態。 |
| 地圖與證據 | Map、Timeline Evidence、LBS | 應以路線、選取節點與證據為中心，不應各自維護選取。 |
| 路線分析 | Route Context、Pace Dashboard、Body Index、Permission、Planning Fine-tune Panel、Architecture | 需要按實際任務拆成「路線脈絡」「時間比較」「個人資料」「申請條件」「路線結構」，不應只用相同 tab 樣式。 |
| 天氣與導航 | Weather、Navigation | 共享路線與區段，但控制中心不同：Weather 以日期／天氣圖層為主；Navigation 以地形觀點／事件為主。 |
| 安全與協助 | Safety / Emergency、Assistant | 保留，但必須明確區分「查看事件」與「詢問資料」。 |
| 系統 | Living、Logs、Intelligence、scout monitor、Debug Surface、Debug Message、MQTT / Observer、Settings、Diagnostic | 低頻、技術性功能應從主要行程流程退到系統工具區。 |

### 已確認的 IA 衝突

1. `trip-notebook` 出現在 sidebar，但 route contract diagnostic 報告 `Unregistered sidebar route IDs: trip-notebook`（[canonical page](/home/alexwang0315/work/scout-fusion/docs/admin/scout-dashboard-v0.1.html:21511)）。這不是單純文字問題：它會破壞路由清單、測試覆蓋與返回路徑的可信度。
2. 使用者工作流程與 debug／monitor／diagnostic 共用同一個導航層級。系統工具不應在視覺權重上與「匯入行程」「地圖」「時間比較」相同。
3. `Pace Dashboard`、`Body Index`、`Permission`、`Architecture`、`Weather`、`Navigation` 都掛在同一個「Exploring for Six Axis」群組，但每一頁任務、控制頻率與結果類型不同；不應套同一個固定模板。
4. 主要工作流程之間沒有明確的共用 selected state contract。inventory 將 `project_id`、`route_identity`、`selected_named_point`、`selected_segment`、`selected_layer`、`data_truth`、`map_camera` 列為必須共用的狀態。

## 控制頻率 × 重要性排序

目前 repository 沒有真實操作 telemetry，因此「頻繁度」是依工作流程依賴與使用者要求的初始推估，不冒充實測數字。正式產品化時應收集操作事件再校準。

| 優先層 | 頻繁度 | 重要性 | 位置 | 控制 |
| --- | --- | --- | --- | --- |
| P0 | 高 | 高 | 首屏／固定控制中心 | 工作區、路線／節點選取、CP Timeline、Fit route、主要結果、下一步 |
| P1 | 中 | 高 | 主內容旁 | 日期、圖層、資料來源、重試、比較基準、事件篩選 |
| P2 | 中 | 中 | 次主區域 | 圖例、歷史分布、資料完整度、關聯證據 |
| P3 | 低 | 低 | info icon、hover／focus、drawer | raw JSON、provider id、artifact hash、renderer、QGIS receipt |

這個排序不代表所有頁面都用同一版面：P0 控制中心的內容依頁面任務改變。CP 工作流程的 P0 是 CP Timeline；Weather 的 P0 是日期／天氣圖層；Navigation 的 P0 是地形觀點／事件；Diagnostic 的 P0 是檢查範圍與結果摘要。

## 各工作流程的目標版面

### 1. 工作區與匯入

1. 使用者目標：選行程、匯入來源、知道資料是否可用。
2. 主要控制中心：工作區選擇器與匯入步驟列，固定在頁面上方。
3. 主要結果區：目前工作區、真實路線名稱、匯入進度、下一步。
4. 補充證據區：來源檔名、過濾點數、產生節點、資料時間。
5. 低頻率資訊區：artifact hash、importer version、raw manifest。
6. 容易誤解：`Trip Intake`、`Country Material Pool`、workspace path；改成「匯入行程」「路線資料來源」「目前工作區」。

### 2. 路線與地圖

1. 使用者目標：看懂目前路線，找到下一個要檢查的節點。
2. 主要控制中心：地圖控制列加上 Named CP／地標清單。
3. 主要結果區：路線、目前選取節點、距離、下一步。
4. 補充證據區：圖例、來源、資料狀態、marker 詳情。
5. 低頻率資訊區：tile generation、renderer、source hash。
6. 容易誤解：地圖只有背景沒有路線、marker 只有流水號、Fit 後視角不在路線範圍內。

### 3. 時間比較與個人資料

1. 使用者目標：知道區間要花多久，以及目前資料能否支持比較。
2. 主要控制中心：CP Timeline，需固定可見，不因換資料而消失。
3. 主要結果區：區間時間、歷史平均、個人估計、比較結果。
4. 補充證據區：分布、來源檔案、計算關係、資料覆蓋率。
5. 低頻率資訊區：參數、raw object、risk budget、provider details。
6. 容易誤解：`Pace Parameters`、`Pace Evidence`、`Read-only preview` 置於主視線；應改為「時間參考」「來源與計算」，並用短 hint 說明限制。

比較公式固定用：

```text
個人估計耗時 ÷ 同一區間歷史平均耗時 × 100
```

若個人估計尚未產生：

```text
個人估計：--
歷史平均：106.4 分鐘
比較結果：--
```

目前正式 Pace 頁面仍將 `Supporting pace preview and evidence`、`Pace Parameters`、`Pace Evidence` 放在 supporting details（[source](/home/alexwang0315/work/scout-fusion/docs/admin/scout-dashboard-v0.1.html:37317)），並在頁面中使用長句與 `Read-only preview`（[source](/home/alexwang0315/work/scout-fusion/docs/admin/scout-dashboard-v0.1.html:37340)）。這是本輪最高優先的視覺層級調整候選。

### 4. 路線結構、天氣與導航

1. 使用者目標：分別理解路線壓力、可用時間窗與地形導航重點。
2. 主要控制中心：Architecture 用觀點／區段；Weather 用日期／圖層；Navigation 用地形觀點／事件。
3. 主要結果區：每頁自己的結論，不使用共同空白模板。
4. 補充證據區：高程、路線骨架、雷達、風險點、回撤幾何。
5. 低頻率資訊區：QGIS receipt、artifact metadata、DEM method、provider cache。
6. 容易誤解：Architecture 初始 `No segment selected`；Weather 的 candidate boundary 長句；Navigation 的技術 legend 與主要結果權重相同。

正式 Architecture 畫面目前確實以 `No segment selected` 作為空內容（[source](/home/alexwang0315/work/scout-fusion/docs/admin/scout-dashboard-v0.1.html:36911)）；demo 改為預選第一個可用 Named CP／區段，避免使用者先找控制才看到結果。

### 5. 安全、事件與協助

1. 使用者目標：了解事件狀態，或查詢目前資料。
2. 主要控制中心：Emergency 用事件／人工確認；Assistant 用問題輸入／來源。
3. 主要結果區：目前狀態與可做下一步。
4. 補充證據區：位置、時間、聯絡資料、使用的來源。
5. 低頻率資訊區：transport receipt、provider class、raw payload。
6. 容易誤解：查看、確認、發送三種動作若用相同按鈕，使用者無法預期副作用；所有可能產生外部效果的操作需明確標示。

### 6. 系統與診斷

1. 使用者目標：確認系統狀態或找出失敗原因。
2. 主要控制中心：模組／事件篩選器與診斷執行列。
3. 主要結果區：狀態摘要、失敗項目、可恢復下一步。
4. 補充證據區：事件時間、來源、關聯工作區、重測紀錄。
5. 低頻率資訊區：raw payload、hash、transport、evaluator score。
6. 容易誤解：技術說明先於檢查結果；Diagnostic screenshot 已顯示 50 個檢查與長段落說明佔據首屏。

## 地圖與資料驗證清單

本輪以 9 個 contract map surface 建立驗證矩陣，但沒有把未執行的項目算成 PASS。qualification artifact 明確記錄 `map_surface_results: 0`、`visual_checkpoints: 0`、`operated_controls: 0`，因此以下是待補驗證清單：

- 首次載入：確認不是只有 grid／空白背景。
- 自動 fit：確認 route bbox、Named CP、rest area、地標都在合理視窗。
- 選取同步：清單、marker、結果卡、證據來源使用同一個 selected id。
- 操作：Fit、zoom in、zoom out、mouse pan、keyboard pan、rectangle zoom。
- 資料狀態：loading、complete、partial、empty、recoverable error 都保留 route identity。
- 排序：依實際距離排序，補上較早距離的 rest area／地標，不以頁面出現順序代替地理順序。
- 名稱：保留 `雲海保線所`、`大崩壁`、`黑水塘`、`稜線啞口觀景點` 等真實名稱，不輸出 `CP 001` 取代它們。

目前資料 fixture 已提供可用的真实名稱與數值：`雲海保線所` 1.5 km、`黑水塘` 2.35 km、`大崩壁` 4.1 km、`固定繩橋段` 4.7 km、`隱蔽樹林區` 6.9 km、`稜線啞口觀景點` 8.2 km；時間資料有 `屯原登山口 -> 雲海保線所` 歷史 p50 106.4 分鐘。Demo 使用這些名稱與狀態，沒有用流水號替代。

## 文字、圖示與色彩規則

### 文字

- 固定文案最多 20 words；用短句，不用產品內部術語。
- `目前結果`、`區間時間`、`歷史平均`、`個人估計`、`時間參考`、`來源與計算`、`下一步` 作為共用詞彙。
- 使用者資料、路線名稱、Named CP、距離、時間、百分比與活動數量保持真實變數值。
- `candidate-only`、`read-only preview`、`runtime safety truth` 等邊界只在短 hint 出現，不在主結果區形成長篇 disclaimer。

### 圖示

- 路線／地圖：藍色／青色。
- 時間軸／選取：柔和紫色。
- 結果／比較：琥珀色。
- 個人／基準：柔和綠色。
- 下一步：綠松色。
- 來源：暖橘色。
- 尺寸：頁面 44–50 px、區塊 32–36 px、指標 26–30 px、hint 20–24 px。
- 圖示使用柔和圓角線性語言；圖示本體要填滿外框比例，不能變成厚重黑色剪影。

## Demo 內容與互動

Demo 不是正式頁面替換，而是供下一輪審查與核准的可操作 layout proof：

1. **目前行程**：以 `奇萊南華-能高越嶺步道Day1`、`2013-10-08 10:58:50 每日記錄`、`雲海保線所` 等真實名稱展示「控制中心優先」。選節點會同步 marker、結果卡與下一步。
2. **區間比較**：右側 CP Timeline 固定顯示，選取 `雲海保線所` 後同步地圖與結果；沒有個人估計時顯示 `--`，仍保留歷史平均 106.4 分鐘與公式。
3. **匯入與資料不足**：展示匯入完成、個人資料尚未產生、歷史資料仍可用、地圖載入失敗可重試的狀態。

Demo 互動規則：

- 所有控制是可用 button，支援鍵盤 focus 與 Enter／Space。
- 節點選取會更新同一個 `selected_named_point`，切換視圖後不重置。
- 符合路線範圍、重試、下一步都有 `aria-live` 短回饋。
- 技術來源說明使用色彩 info icon 的 hover／focus hint。
- 390 px 寬度改為單欄，控制中心仍在主要結果之前，不需要反覆展開。

### Demo 截圖與驗證

- [控制中心優先](/home/alexwang0315/work/scout-fusion/artifacts/dashboard-ux-audit-20260921/demo-screenshots/01-control-center.png)
- [結論優先](/home/alexwang0315/work/scout-fusion/artifacts/dashboard-ux-audit-20260921/demo-screenshots/02-conclusion-first.png)
- [錯誤狀態](/home/alexwang0315/work/scout-fusion/artifacts/dashboard-ux-audit-20260921/demo-screenshots/03-error-state.png)
- [恢復後狀態](/home/alexwang0315/work/scout-fusion/artifacts/dashboard-ux-audit-20260921/demo-screenshots/03-evidence-and-states.png)
- [390 px 控制中心](/home/alexwang0315/work/scout-fusion/artifacts/dashboard-ux-audit-20260921/demo-screenshots/04-mobile-control-center.png)
- Playwright focused run：桌面／390 px、節點與區間同步、地圖 zoom／fit、排序狀態、錯誤重試、keyboard focus、ARIA tabpanel、marker pressed、無 console/page/request error，全部 PASS。
- [image-diff evidence](/home/alexwang0315/work/scout-fusion/artifacts/dashboard-ux-audit-20260921/visual-qa-image-diff.json)：同一 deterministic demo state 的 reference／actual 為 100/100、alpha intact；它證明穩定渲染，不等同外部設計稿 pixel fidelity。
- [focused browser check JSON](/home/alexwang0315/work/scout-fusion/artifacts/dashboard-ux-audit-20260921/demo-browser-checks.json)：記錄桌面／行動版互動、focus、ARIA、錯誤恢復與 request／console 結果。

兩個 quick visual-qa oracle 的最後 verdict 都是 `PASS`：P1/P2 為 0，沒有新的確定缺陷。這個 PASS 僅適用於獨立 demo 的目前 revision；不代表正式 Dashboard 已完成改版，也不替代前述 16-case qualification 的 6 個既有失敗。

## 尚未解決的衝突／待決策

以下項目不能由本輪自行替使用者決定：

1. `trip-notebook` 是否正式納入 route contract，或從 sidebar 移除並改成 workflow 內的操作。
2. Dashboard 的主要工作頁是否保留現有深色主題；demo 使用柔和淺色版面以驗證層級，但沒有直接替換正式 theme。
3. 操作頻率目前只有推估；需要決定是否加入 route、control、fit、layer、retry 的 telemetry。
4. Navigation／Architecture／Weather 的 dynamic Rudy map 失敗是既有回歸、環境資料生成，還是 UI 狀態缺陷；需先依既有 diagnostic 衝突規則裁決。
5. 哪些 external action 允許放入主要控制中心；Emergency、Settings、匯入與 connected preparation 需各自確認副作用邊界。

## 下一步建議

下一輪若要讓 Codex 自動修正，建議採用這個序列：

1. 先核准本 inventory 與三視圖 demo 的資訊架構。
2. 以 P0 控制中心與結論優先為第一個正式垂直切片。
3. 每修改一個 workflow，先跑該 workflow 的 browser capture，再跑 `product-design:audit` 的問題清單。
4. 只有 audit 找不到新的 P0／P1，且 visual QA、keyboard flow、地圖同步與既有 regression 都通過，才進入下一個 workflow。

本輪沒有宣稱正式 Dashboard 已修正或通過；正式頁面仍等待 demo 與待決策項目核准。
