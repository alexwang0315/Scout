# Scout Dashboard UX Issue Ledger

版本：2026-09-22
範圍：整個 Scout Dashboard，而不是單一的總攬、Pace Fit 或 Body Index 頁面。
目前狀態：`LEDGER CREATED / FULL PAGE REDESIGN AND REGRESSION PENDING`

這份文件是目前所有 UX、資訊架構、視覺層級、互動、地圖、資料呈現、內容、路徑與驗證問題的總帳。後續每一頁的設計與修正，都必須回到這份文件逐項關閉，不能只修使用者當下看到的單一畫面。

## 使用方式與狀態定義

- `OPEN`：已確認或已提出，但尚未完成修正或驗證。
- `PARTIAL`：已有局部 demo、元件或規格，但尚未涵蓋所有頁面、路由與狀態。
- `IMPLEMENTED — REGRESSION PENDING`：目前已有實作證據，但尚未完成全 Dashboard 回歸。
- `VERIFIED — CURRENT DEMO`：只代表目前指定 demo 與當前狀態已驗證，不代表所有正式頁面都已通過。
- `DECISION REQUIRED`：需要產品或使用者決定，不能由 Codex 自行改寫規格或 Diagnostic 預期。
- `STALE REFERENCE`：文件或 fixture 仍引用舊專案，必須更新後才能作為驗收證據。
- `HISTORICAL`：描述過去版本的問題，保留作為回歸背景，不當作目前已完成的證據。

完成條件遵循專案的全面回歸門檻：所有適用項目必須是 `PASS`；有 `FAIL`、`WARN`、`SKIP`、未驗證或不穩定結果時，只能報告未完成或部分驗證。

## 當前基準與參考文件

- 當前 workspace：`dongqing_batongguan_historic_trail_newImport`
- 舊 workspace `chilai_nanhua_day1`：禁止作為目前 Dashboard、demo 或驗收資料。
- 全面審查：[scout-dashboard-ux-audit-20260921.md](scout-dashboard-ux-audit-20260921.md)
- 語言與資訊層級規格：[scout-dashboard-ux-language-spec.md](scout-dashboard-ux-language-spec.md)
- 路由與狀態盤點：[scout-dashboard-ux-inventory-20260921.json](scout-dashboard-ux-inventory-20260921.json)
- v0.1 demo：[scout-dashboard-v0.1.html](scout-dashboard-v0.1.html)
- v0.2 demo：[scout-dashboard-v0.2.html](scout-dashboard-v0.2.html)

注意：目前 inventory JSON 仍有 `chilai_nanhua_day1` 的 `source_of_truth` fixture，因此它只能作為歷史盤點參考，不能直接宣稱已符合目前 workspace。

## A. 工作流程、盤點與資訊架構

| ID | 缺失／問題 | 影響範圍 | 驗收條件 | 狀態 |
|---|---|---|---|---|
| UX-001 | 版面沒有穩定依照「操作頻繁度 × 控制重要性」安排；高頻、高重要性操作沒有固定位於主要視線與主要操作區。 | 所有 Dashboard 頁面與共用 shell | 每頁列出控制頻率與重要性；最高優先控制在首屏主要操作區；低頻技術資訊不佔主版面。 | `OPEN` |
| UX-002 | 尚未形成可重複執行的 `product-design:audit → Codex 自動修正 → visual-qa` 工作流。 | 全 Dashboard 審查流程 | 每輪保留 audit 問題、修正 diff、visual QA 截圖與未解問題；Codex 可依 ledger 批次修正，而不是等使用者逐項提醒。 | `OPEN` |
| UX-003 | 先前審查容易集中在 Pace Fit、Body Index 或總攬，沒有把它們當作全站範圍的一部分。 | 所有頁面、路由、地圖、資料面板、匯入、結果、空狀態、錯誤狀態與控制 | 完成 route/surface inventory，逐頁標示任務、控制、結果、狀態與驗證證據。 | `PARTIAL` |
| UX-004 | 尚未以一份可追蹤清單完整盤點所有頁面的主要任務、最常用控制、最重要結果、選取狀態、資料來源、共用狀態與載入／空／完整／不足／錯誤／恢復狀態。 | 26 routes、外部／嵌入 surface、所有主要流程 | inventory 與實際當前 workspace、當前路由、當前版本一致；每一個頁面都有狀態覆蓋。 | `PARTIAL` |
| UX-005 | 每個工作流程缺少唯一且常駐的主要控制中心，使用者需要猜測哪個按鈕才是主操作。 | CP、路線、匯入、比較、天氣、導航、系統與分析流程 | 每個流程只有一個主要控制中心；不因資料切換消失；選取後同步更新地圖、結果與比較資料。CP 流程以 CP Timeline 作為完整右側控制中心。 | `OPEN` |
| UX-006 | 「決策台」、「路線脈絡」、「證據摘要」目前內容與控制大同小異，造成灌水與重複導航。 | 相關頁面與側邊導覽 | 若控制、結果與下一步相同則合併；若保留分頁，必須有清楚不同任務與不同主要結果。 | `OPEN` |
| UX-007 | v0.2 相較 v0.1 疑似省略 `Exploring for Six Axis`、`Debug Surface`、`Map preview`，沒有清楚標示保留、移動或刪除原因。 | v0.1 → v0.2 migration、導覽與 demo | 對每個 v0.1 surface 給出 `保留／合併／移動／移除` 結果；不可無聲消失。 | `OPEN` |
| UX-008 | 目前最新資料是 `dongqing_batongguan_historic_trail_newImport`，舊的 `chilai_nanhua_day1` 仍出現在 inventory 或歷史產物。 | inventory、demo、路由預設、文件與驗收 | 所有目前可見資料、demo 與測試預設使用 Dongqing；舊名稱只能出現在 migration/歷史說明。 | `PARTIAL` |
| UX-009 | 切換到 `dongqing_batongguan_historic_trail_newImport` 後無法切換各個頁面。 | workspace 切換、sidebar、所有 route | 切換 workspace 後 sidebar、路由、頁面資料與返回操作仍可用；重新載入後也能恢復。 | `OPEN` |
| UX-010 | `trip-notebook` 出現在 sidebar，但 route contract 未註冊，造成導覽與實際路由不一致。 | sidebar、route registry、direct link | 決定正式註冊或移除；註冊後 direct link、返回、選取狀態與錯誤頁都必須通過。 | `DECISION REQUIRED` |
| UX-011 | 使用者工作流程與 system/debug/monitor/diagnostic 工具混在同一層，低頻技術工具競爭主要注意力。 | sidebar、總攬與 Debug Surface | 使用者任務、系統狀態與診斷工具分層；低頻工具可到次要入口，但仍保留可達性。 | `OPEN` |
| UX-012 | 六軸頁面被套用相同群組與模板，沒有依實際任務、控制中心與主要結果設計。 | 六軸分析、CP、天氣、個人與歷史比較 | 共用設計系統，但各流程可有不同版面；每頁明確列出主任務、主控制、主結果。 | `OPEN` |
| UX-013 | 使用者無法第一眼理解目前在哪個工作流程、目前最重要的結果、下一個最常用操作、主要結果與補充證據的差異。 | 所有頁面首屏 | 首屏按「目前流程 → 主要結果 → 下一步 → 系統目前狀態 → 補充資料」排序。 | `OPEN` |

## B. v0.2 視覺層級、內容與用詞

| ID | 缺失／問題 | 影響範圍 | 驗收條件 | 狀態 |
|---|---|---|---|---|
| UX-020 | v0.2 給人的感受只是換底色，資訊層級、頁面任務、控制順序與可讀性沒有真正重新設計；目前接近不可用。 | 所有 v0.2 頁面 | 每一頁重新依工作流程設計，不以換色或套同一模板視為完成；需有逐頁 screenshot 與互動驗證。 | `OPEN` |
| UX-021 | 固定標語式文字過長，沒有嚴格遵守 20 words 內。 | 頁面副標題、區塊標題、操作說明、提示句、設計註解、空狀態 | 所有固定文案逐項計數；每項 ≤20 words。workspace 名稱、路線名稱、Named CP、距離、時間、百分比、檔名與其他變數不計入。 | `PARTIAL` |
| UX-022 | 本應移到 hover/focus hint 的小標題、補充說明與問題句仍直接佔據主內容，例如「路線結構（難點、撤退點與容錯率如何分布？）」沒有靠近標題的 hint。 | 所有頁面標題、區塊標題與技術說明 | 主標題只保留可理解名稱；補充解釋使用緊鄰標題的彩色語意 icon，hover 與 keyboard focus 顯示。 | `PARTIAL` |
| UX-023 | 文字顏色接近背景，對比不足，實際畫面不可讀。 | 目前總攬與資料卡，並可能影響全站 theme | 主要文字、次要文字、disabled、錯誤與提示色都有可讀對比；在實際 browser screenshot 檢查，不只看 CSS 值。 | `OPEN` |
| UX-024 | 低價值、技術性或補充資訊佔據重要空間，主要結果被推到下方。 | 資料卡、debug、provenance、警語、次要指標 | 首屏先顯示結果、單位、目前選取與下一步；技術細節移到 hint、drawer 或次要區域。 | `OPEN` |
| UX-025 | 長篇警語、限制聲明與 technical disclaimer 佔據主要內容，例如非即時安全判定、read-only preview、candidate-only、內部假設。 | 總攬、天氣、導航、安全與 provenance | 刪除沒有行動價值的段落；必要限制改為短句、彩色 info icon 的 hover/focus hint，不阻擋主要操作。 | `OPEN` |
| UX-026 | 使用 `Pace Parameters`、`Pace Evidence`、`Supporting Evidence`、`Architecture route moving-energy candidate` 等艱深術語，原作者也不易理解。 | 所有頁面固定文案與欄位 | 改用清楚中文，例如「目前結果」、「區間時間」、「歷史平均」、「個人估計」、「時間參考」、「來源與計算」、「下一步」。 | `PARTIAL` |
| UX-027 | 特定術語沒有統一轉成可理解的使用者語言：資料邊界、投影資料、阻擋、需要使用者處理、重大／次要、Dashboard 可見、GIS 相關、僅供重現。 | status badge、metadata、provenance、debug 與資料卡 | 統一採用：「資料用途」、「整理後資料」、「先處理」、「需要先處理」、「重要程度」、「顯示於目前頁面」、「地圖資料」、「方便重現」；若仍無具體用途則依 UX-028 移除。 | `PARTIAL` |
| UX-028 | 下列固定區塊若沒有可採取的後續行動或具體狀態，只有佔位與分類價值：`規劃用資料／不送出`、`需要注意`、`先處理`、`完成後才能繼續`、`重要程度`、`顯示於目前頁面`、`地圖資料`、`方便重現畫面`。 | 所有 metadata、狀態卡與 provenance | 無具體後續價值就刪除；若保留，必須同時顯示真實狀態、影響與可執行下一步。 | `OPEN` |
| UX-029 | 圖示太少、沒有形成重點，或以首字代替 icon；圖示語言與顏色不一致。 | 全 Dashboard icon、button、status、hint | 使用真正語意圖示，不用首字；圖示有柔和色彩、圓角、適度線寬，不用厚重黑色剪影。主圖示 44–50px、區塊 32–36px、指標 26–30px、hint 20–24px。 | `OPEN` |
| UX-030 | hover hint 與標題距離太遠，使用者不知道它解釋哪個標題。 | 所有標題旁的 info/help icon | hint icon 緊緊跟隨標題，與標題形成單一視覺群組；不能漂到另一個 card 或頁面邊緣。 | `PARTIAL` |
| UX-031 | hover hint 曾被多層 element、overflow 或 card 遮住。hint 必須優先於所有 element。 | 所有 hover/focus hint、modal、drawer、map、sticky header | 使用 fixed top-level portal 或等效最高層；自動選擇可見位置，不被 clipping、overflow、sticky、map 或 modal 遮擋；hover 與 keyboard focus 都能讀完。 | `IMPLEMENTED — REGRESSION PENDING` |
| UX-032 | 專案名稱太長時擠壓狹窄空間，不能縮小字型或換行。 | sidebar、header、workspace selector、狀態卡、資料卡、分析頁 | 單行顯示部分名稱加刪節號；保留真實全名供 hover/focus hint；不縮小字、不換行、不破壞 layout。 | `IMPLEMENTED — REGRESSION PENDING` |
| UX-033 | workspace 與 project/trip 名稱相同時重複顯示，例如 `dongqing_batongguan_historic_trail_newImport / dongqing_batongguan_historic_trail_newImport`。 | 暫停狀態、工作區標頭、route context | 同一個識別值只顯示一次；只有 project/trip 不同時才並列顯示，並保留可複製或 hint 的完整值。 | `VERIFIED — CURRENT DEMO` |

## C. 路徑、捷徑與來源資訊

| ID | 缺失／問題 | 影響範圍 | 驗收條件 | 狀態 |
|---|---|---|---|---|
| UX-034 | 路徑直接顯示整串，長路徑換行並佔據主要空間；使用者又需要完整路徑時缺少方便取得的方式。 | workspace、使用規範、行前資料、source/provenance、debug | 畫面只顯示最後一個目錄或檔名；旁邊有真正的 copy path icon；複製內容仍是完整路徑。 | `PARTIAL` |
| UX-035 | 路徑除了 copy path 外，也需要可點選的捷徑；query string 不應成為主畫面的閱讀內容。 | `/admin`、HTTP endpoint、spec、workspace path | 可點選的路徑開啟對應入口；完整 path/query 只存在 copy value 或 link target；顯示文字保持短。 | `PARTIAL` |
| UX-036 | 路徑範例與目前 workspace 不一致，仍會出現 `chilai_nanhua_day1`。 | 工作區、使用規範、行前資料連結 | 顯示 `dongqing_batongguan_historic_trail_newImport`；舊名稱只留在歷史 migration 註記。 | `OPEN` |
| UX-037 | 「資料來源／計算」若把實作 boundary、server/cache、candidate-only 一次攤在主畫面，使用者難以判斷它對目前決策的作用。 | provenance、weather、result、diagnostic | 主畫面只顯示對目前結果有用的來源與狀態；詳細 boundary 放在鄰近 hint 或次要 drawer。 | `OPEN` |

## D. 地圖與空間資訊

| ID | 缺失／問題 | 影響範圍 | 驗收條件 | 狀態 |
|---|---|---|---|---|
| UX-040 | 部分地圖首次載入沒有真正顯示地圖，或路線沒有自動 fit 到合理範圍，留下大量空白。 | 所有 map surface、總攬 preview、路線頁、導航頁 | 每個地圖在首次載入、重新載入與切換 workspace 後可見；路線、marker 與控制位於合理視野；不能用另一頁或預載 cache 代替。 | `OPEN` |
| UX-041 | marker、名稱、距離、路線、放大、平移、重新定位與資料狀態的關係不夠清楚。 | 2D/3D/Rudy+TW、route、CP、rest area、landmark | 地圖與側邊控制共享同一選取狀態；控制容易找到；空、資料不足與錯誤狀態仍能理解目前地圖內容。 | `OPEN` |
| UX-042 | 路線上的 CP、rest area 與地標可能沒有依實際距離正確排序，且曾遺漏較早距離的項目。 | route context、CP timeline、map list、比較頁 | 以實際路線距離排序；逐一檢查較早與較晚項目；map marker、timeline、列表順序一致。 | `OPEN` |
| UX-043 | 真實 Named CP、路線名稱或地標可能被 CP1、CP2 或流水號取代。 | 所有 demo、地圖、timeline、結果與比較資料 | 顯示真實名稱；流水號只能作為輔助排序，不能取代 Named data。 | `OPEN` |
| UX-044 | 地圖 qualification 證據不足：`map_surface_results` 為 0、動態 tile timeout、只證明 HTTP 200 或另一頁成功，無法證明當前頁完整載入。 | browser qualification、所有 map renderer | 每個相關地圖都要有當前頁 screenshot、原生圖磚與必要網路證據，並驗證放大、平移、fit、marker 與路線細節。 | `OPEN` |
| UX-045 | map、結果與側邊控制的選取狀態可能各自存在，切換 CP 或資料後不同步。 | 地圖、CP timeline、result panel、comparison | 點選任一來源都更新其他區域；重新載入與切換視角後保留或明確重設選取狀態。 | `OPEN` |

## E. 資料、計算與結果呈現

| ID | 缺失／問題 | 影響範圍 | 驗收條件 | 狀態 |
|---|---|---|---|---|
| UX-050 | 比較型、計算型頁面沒有穩定採用「結論先、依據後」，主要結果常被來源、警語或技術資料推到下方。 | Pace Fit、Body Index、CP、歷史比較、天氣與分析結果 | 首屏固定顯示主要結果、單位、目前選取與下一步；證明與計算放後面。 | `OPEN` |
| UX-051 | 個人估計與歷史參考的計算關係沒有清楚呈現，或個人估計缺失時把歷史平均一起隱藏。 | 個人／歷史比較、區間結果 | 顯示 `個人估計耗時 ÷ 同一區間歷史平均耗時 × 100`；個人估計尚未產生時顯示 `--`，仍保留歷史平均與基準資料。 | `OPEN` |
| UX-052 | 技術計算細節、來源、內部假設與原始欄位直接佔用主版面。 | result card、provenance、debug、data batch | 主要結果可獨立理解；計算細節在「來源與計算」hint/drawer；不因其他模組未完成而隱藏可用基準資料。 | `OPEN` |
| UX-053 | 目前選取資料、單位、Named data、資料不足狀態沒有在每個結果頁穩定顯示。 | 所有計算、比較、時間、距離、活動與 weather 結果 | 結果旁有單位與選取來源；資料不足用短句或 `--`；不使用模糊的技術狀態代替使用者可理解狀態。 | `OPEN` |
| UX-054 | Demo 必須使用真實 Named CP、路線名稱與真實資料狀態，但目前部分畫面仍可能使用流水號或舊 workspace。 | v0.1/v0.2 demo、截圖、驗收 | 三種 demo 都使用 Dongqing 真實名稱，並覆蓋資料完整、資料不足與錯誤狀態。 | `PARTIAL` |

## F. 互動一致性、可及性與恢復

| ID | 缺失／問題 | 影響範圍 | 驗收條件 | 狀態 |
|---|---|---|---|---|
| UX-060 | 選取狀態不一定清楚，或選取後地圖、結果、比較與側邊資訊不同步。 | 所有帶有 selection 的流程 | 選取有明顯視覺狀態、文字狀態與 keyboard 狀態；所有相關區域同步更新。 | `OPEN` |
| UX-061 | 切換資料可能意外重置畫面，或使用者需要反覆重新展開主要控制區塊。 | workspace、CP、filter、比較與資料切換 | 主要控制中心常駐；資料切換不清除必要選取；不需要重複展開才能完成下一個高頻操作。 | `OPEN` |
| UX-062 | 主要流程的鍵盤操作、focus 順序、tooltip focus 與 button 語意未完整驗證。 | 所有主要控制與 hint | 不使用滑鼠也能完成主要流程；每個 icon button 有名稱；hint 可透過 focus 顯示並可讀完。 | `OPEN` |
| UX-063 | 空狀態只告知沒有資料，沒有合理下一步；錯誤狀態也可能無法恢復正常操作。 | import、result、map、weather、analysis、error page | 空狀態保留可執行下一步；錯誤有重試、返回或替代流程；恢復後不需重新載入整個 Dashboard。 | `OPEN` |
| UX-064 | 長專案名稱、中文文案與狹窄 viewport 可能造成裁切、換行或橫向溢出。 | sidebar、header、cards、390px viewport | 390px 與常用 desktop viewport 都無水平溢出；專案名稱使用 ellipsis；固定文案仍可讀。 | `OPEN` |
| UX-065 | 共用設計規則尚未在所有頁面一致套用，但又不能把所有頁面做成同一固定模板。 | 全 Dashboard | 共用 icon/color/type/hint/path/selection 規則一致；每個 workflow 仍有適合自己的控制中心與結果版面。 | `OPEN` |
| UX-066 | hint、modal、drawer、sticky header、map overlay 的層級關係不清楚，導致 hint 被遮住或無法點選。 | 多層 UI 所有頁面 | 建立全站 overlay 層級契約；hint 最高優先且不被任何 element 遮擋；點擊外部或 Escape 可恢復正常操作。 | `PARTIAL` |

## G. Demo、驗證與尚未解決的產品決策

| ID | 缺失／問題 | 影響範圍 | 驗收條件 | 狀態 |
|---|---|---|---|---|
| UX-070 | 要求先做整體 Dashboard demo，再修改正式頁面；目前 demo 與正式頁面之間的覆蓋範圍與差異沒有完整記錄。 | v0.1、v0.2、正式 routes | 先交付三種 demo：控制中心優先、結論優先、證據／系統狀態優先；取得截圖與互動結果後才逐頁套用。 | `PARTIAL` |
| UX-071 | Demo 交付物尚未全部固化：全站 inventory、控制頻率／重要性、共用 icon/color/text 規則、主要操作流程、map/data validation、三張截圖、互動結果與未解衝突。 | 審查交付與後續實作 | 每次 audit 都附完整 artifact index；未完成項目不能被標記為完成。 | `PARTIAL` |
| UX-072 | 目前 qualification 已知 16 cases 中 10 PASS、6 FAIL；Diagnostic 為 50/50、Navigation 只有 partial truth、weather overlay 會改 workspace、Navigation dynamic tile timeout、Architecture 沒有 active Fit matrix、Weather 沒有 higher native generation。 | qualification、Navigation、Weather、Architecture、overlay | 逐項保留原失敗證據；依使用者裁決更新規格或修正實作；在未完成前不得宣稱 Dashboard 全面通過。 | `OPEN` |
| UX-073 | audit 已列出的產品決策尚未定案：`trip-notebook` 是否正式註冊、theme 方向、telemetry 是否需要、動態地圖失敗如何呈現、外部 action boundary。 | route、視覺系統、診斷、地圖與操作 | 每個決策有選項、影響與使用者裁決；在裁決前不得把衝突 Diagnostic 自行改成 PASS。 | `DECISION REQUIRED` |
| UX-074 | 先前沒有一份完整 issue ledger，使用者只能逐次指出問題，Codex 也無法可靠確認哪些缺失已記錄、哪些頁面尚未套用。 | 全流程與回歸 | 本文件成為 canonical ledger；每項 issue 有 ID、狀態、範圍、驗收條件與 evidence link。 | `VERIFIED — CURRENT DOC` |
| UX-075 | 使用者指出的細節沒有保證傳播到每一個頁面；目前存在「總攬修了，但其他頁面仍保留舊文字／舊層級／舊 hint」的風險。 | 所有 routes、states、shells 與 embedded surfaces | 每一項 shared rule 都有全站搜尋與逐頁 screenshot/interaction evidence；不可只以總攬通過代表全站通過。 | `OPEN` |
| UX-076 | v0.1 一度被要求保留原始資訊作為比較基準；v0.2 又需要重新設計所有頁面。若不保留版本差異，容易把功能刪除誤判為 UX 簡化。 | v0.1/v0.2 comparison | v0.1 作為 baseline；對每個消失的 surface 提供保留／合併／移動／移除理由。 | `HISTORICAL` |
| UX-077 | 目前不同 demo 的資料來源與入口不同：v0.1 為預設頁，v0.2 需明確 endpoint；若未記錄實際入口，截圖可能不是同一版本。 | live demo、browser QA、交付證據 | 每張截圖記錄 URL、workspace、版本／來源 SHA、資料狀態與時間；確認驗收版本就是通過測試版本。 | `OPEN` |
| UX-078 | 尚未取得真實操作頻率 telemetry，控制頻率排序目前仍多為設計假設。 | 控制優先級、主要操作區 | 先以明確假設建立排序並標記；有實際使用資料後回填頻率，不能把猜測寫成事實。 | `OPEN` |
| UX-079 | 「資料用途／不送出」、「read-only」、「candidate-only」等文字涉及操作邊界，但目前沒有統一判斷哪些應公開、哪些應藏在 hint、哪些必須保留。 | import、weather、assistant、external action | 每個 boundary 有使用者可理解的短句與可操作下一步；不把安全或技術真相隱藏到會造成誤判的程度，也不以長 disclaimer 阻塞主流程。 | `DECISION REQUIRED` |
| UX-080 | v0.2 總覽右上與展開面板出現 `可用`、`操作介面`、`混合專案證據`、`唯讀導覽`、`路線介面已驗證`、`工作區與執行投影` 等空泛詞句；它們不是 workspace/API 真實資料，而是前端 `ROUTE_TRUTH.home` 的硬編碼工程 metadata。 | v0.2 top status strip、總覽、所有 route truth 欄位 | 將使用者結果、資料狀態、來源與內部 QA 分離；無行動價值的欄位刪除或移到 Diagnostic/hint；詳細來源見 [v0.2 文案來源追查](scout-dashboard-v0.2-copy-source-audit.md)。 | `IMPLEMENTED — REGRESSION PENDING` |

## 逐頁套用清單

以下清單是每一個 route／surface 在關閉 issue 前都必須執行的最低檢查。不得只檢查總攬：

1. 確認目前 workflow、主要結果、下一步與目前選取資料。
2. 確認只有一個主要控制中心，且不需要反覆展開。
3. 確認固定標語 ≤20 words；變數名稱保留真實資料。
4. 確認技術補充改為鄰近標題的語意 icon + hover/focus hint。
5. 確認 hint 緊鄰標題、在最高 overlay 層、不被任何 element 遮擋。
6. 確認文字與背景有足夠對比，中文、英文與數字都可讀。
7. 確認低頻、補充、debug、provenance 不佔據主要結果空間。
8. 確認路徑只顯示最後一段，copy icon 複製完整 path，捷徑可點選。
9. 確認長 workspace/project 名稱單行 ellipsis，不縮小字、不換行，hint 顯示全名。
10. 確認同一 workspace/project/trip 不重複顯示。
11. 確認 map 首次載入、fit、marker、實際名稱、距離排序、zoom、pan、recenter。
12. 確認 map、側邊控制、結果與比較資料使用同一 selected state。
13. 確認結論先於依據；單位、公式、`--` 與資料不足狀態清楚。
14. 確認 empty、incomplete、error、recovery 都有可理解的下一步。
15. 確認鍵盤可完成主要流程，icon button 可 focus 且有名稱。
16. 確認 390px 與 desktop viewport 沒有橫向溢出或中文裁切。
17. 使用 Dongqing 真實 Named CP、路線名稱與資料狀態，不使用舊 Chilai fixture。
18. 記錄 URL、workspace、版本／來源 SHA、截圖、互動結果與剩餘 FAIL/WARN。

## 目前結論

已經有局部規格與 demo 證據的項目包括：hover hint 的全域層級方向、長名稱 ellipsis 方向，以及相同 workspace/project 名稱去重。這些只算目前 demo 驗證，尚未代表所有正式 route 通過。

目前仍不能宣稱「整個 Dashboard 已修好」：全頁重新設計、路由切換、舊資訊回溯、地圖實際載入、全站文字／hint 傳播、資料結果優先順序、空錯誤恢復，以及既有 qualification FAIL 都尚未完成全面回歸。

下一步應依本 ledger 的 ID 逐頁建立 `audit → fix → visual-qa → regression evidence`，並在每次修改後更新狀態與證據，不再依賴使用者逐個重新指出同一類問題。
