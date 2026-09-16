# Permission 教學與介面同步

## 2026-09-14：當前 UI 依賴必須一起核對

第 1–38 頁的目前版本擷取流程以 Mac 的
`/Users/alexwang0315/scout-fusion` 為實際來源；教學檔案雖放在 Scout TASK/repo，
不代表 TASK/repo 的舊 UI 是正在服務 9099 的版本。保留根層歷史來源 hashes
及原擷取回執，不能拿它們代替目前來源。

`current_ui_source.ui_source_hashes` 現在要求以下八個檔案：

- `docs/admin/scout-dashboard-v0.1.html`
- `docs/admin/phase4-pretrip-planning.html`
- `docs/admin/scout-maplibre-evidence.js`
- `docs/admin/scout-planned-route.js`
- `docs/admin/scout-planned-map-review.js`
- `docs/admin/scout-planned-review-ui.js`
- `docs/admin/scout-exploration-workflow.js`
- `docs/admin/scout-recorded-workflow.js`

原本三個地圖檔案仍強制保留；新增五個外載模組是因為它們在實際 Dashboard
直接渲染 Planned、Saved review、Exploration、Recorded 章節。缺少任何一個
目前來源 hash，或擷取後任一來源變更，都會使同步檢查失敗。使用既有
`current_ui_source.checkout_root` 指向實際來源；遠端驗證仍使用下文的明確 SSH
環境設定，來源不可取得時沒有歷史 fallback。

第 35–38 頁雖共用 Phase4 與 MapLibre，仍各自需要當前 Main／Weather 畫面和
DOM 步驟座標。revision5 的 capture queue 已補齊八檔盤點，但盤點 hash 只表示
檔案曾被讀取，不是擷取回執、功能 PASS 或文字審查結果。全部 38 頁仍待當前
實拍；`image=null`、`markers=[]` 的草稿不能建置成交付檔。

`build.py` 繼續先跑同一個 Verifier，檢查失敗前不寫 HTML／講稿／manifest。
完整同步檢查另要求最終 PDF hash、頁數及交付回執；只有 captures-only 通過
仍不能宣稱 PDF 已更新。不得只改 hash 或移除模組，讓舊截圖被算成目前版本。

使用者要求：每一頁都提供目前介面截圖，步驟 1、2、3 必須對應畫面中的編號與位置。Permission 與其引用的主地圖按鈕、文字、位置、條件或流程改變時，同一項修改也要更新受影響的投影片、講稿與 PDF，再完成驗證。這是每次修改的交付流程，沒有建立背景監控或排程。

所有製作與證據保存在 Scout。練習入口必須核對完整的 `dongqing_batongguan_historic_trail_newImport`，不能用相似工作區的結果代替。如果某項進階操作只能使用其他既有示範工作區，必須在該頁明示來源與限制。

## 同步順序

1. **檢查修改與目前介面。** 先讀 UI diff，列出受影響的頁面、步驟、按鈕名稱與狀態。在執行中的 Dashboard 重載後，確認實際 workspace、網址、資料來源，以及要教的控制項確實存在。
2. **重新擷取真實畫面。** 在目前 UI 到達必要的可讀狀態；以 `tab.screenshot()` 擷取未修改的完整 PNG 或 JPEG 到 `assets/`，同時記錄時間、網址、project ID、圖片尺寸與每個目標的 DOM locator／bounding box。截圖與 DOM 位置必須取自同一個已穩定畫面。使用擷取當時的原始視窗 JPEG 與同一視窗的 DOM 座標，不轉檔、不裁切；實際尺寸記入回執，不以固定 1280×720 作為通過條件。副檔名必須符合原始位元組的實際格式。背景分頁的 CDP 裁切、殘留裝置尺寸及頁面縮放曾造成偏移或不完整繪製；必要時改用乾淨原生頁籤與預設縮放，並核對圖片尺寸與 DOM 視窗一致，因此不能只核對兩份 DOM 數字便當成通過。不要用估計位置、合成按鈕或舊圖改字代替實際擷取。
3. **同步步驟與標記。** 更新 `slides.json` 的每一個受影響頁面。包括封面與概念頁，每頁都需要 `image`、非空 `steps`，以及每個步驟唯一的 `markers`。標記編號從 1 連續起算，正文順序與圖上編號相同；標記與目標框都必須在圖片內。目標不在同一視窗時，先捲到目標可見的位置，再擷取該完整視窗或拆頁；捲動後重新記錄 DOM 座標。
4. **寫入擷取回執。** 更新 `capture-sources.json` 對應頁面的 `shots`，保留真實時間與來源。核對受影響頁面後才更新 `ui_source_hashes`；必須包含 Dashboard 主 HTML，以及此次教學會受其影響的其他 UI 來源。不能只刷新來源 hash、刪掉變動檔案的追蹤，或更改日期來消除過期訊號。
5. **重建並檢查交付檔。** 先執行 captures-only 檢查，再重建 HTML／講稿、重新列印 PDF。完成版面、標記、互動與 PDF 頁數檢查後，更新 `delivery.json` 的最終 HTML／PDF hash、檔案大小與頁數。最後執行完整同步檢查，再審閱範圍並提交。

僅為製作教學，不得代替使用者勾選審查、接納候選或改寫既有 workspace。需要展示尚未核可的步驟時，保留實際待審／停用狀態，並在講稿說明由使用者何時執行。`candidate_only=true`、`runtime_safety_truth=false`、R4 暫緩的邊界持續適用。

## 擷取資料契約

每頁使用穩定 `id`；`image` 是 `assets/` 內的原始 PNG（`.png`）或 JPEG（`.jpg`／`.jpeg`）檔名。`steps` 沿用 `{title, body}`，每項至少有非空標題。每個 `marker` 使用圖片像素，不使用瀏覽器視窗百分比：

```json
{
  "id": "saved-candidate-restore",
  "image": "saved-candidate-restore.jpg",
  "steps": [{"title": "按 Restore saved candidate", "body": "載入所選版本。"}],
  "markers": [{
    "step": 1,
    "x": 124,
    "y": 88,
    "locator": "role=button; name=Restore saved candidate; exact=true",
    "target": {"x": 140, "y": 74, "width": 208, "height": 36}
  }]
}
```

上例僅說明結構，數字與 locator 不可當成實際擷取證據。圓形編號可以放在目標旁，`target` 則必須是實際 DOM 區域。縮放圖像時，編號、目標框與連線必須一起縮放。

`capture-sources.json` 使用 `schema_version: 2`：

- `ui_source_hashes`：repository 相對來源路徑對應小寫 SHA-256；至少包含 `docs/admin/scout-dashboard-v0.1.html`。
- `shots`：每頁一筆，包含 `page_id`、`asset`、`sha256`、`project`、`url`、含時區的 `captured_at`、原始圖像 `width`／`height`。
- 每筆 shot 的 `targets` 包含 `{step, locator, box: {x, y, width, height}}`。其 step、locator、座標框須與該頁的 marker 對應；座標允許 0.01 像素浮點誤差。

相同截圖可以服務多頁，但每頁仍須有自己的 shot 回執與目標集合，不能漏掉封面、概念頁或結尾頁。

## 檢查命令

在 Scout repository 根目錄執行：

```bash
python3 docs/tutorials/permission-guide/verify_ui_sync.py --captures-only
python3 docs/tutorials/permission-guide/build.py
```

然後執行既有的版面／互動與 PDF 產製流程。`verify-browser.js` 使用 Scout 已有 Playwright 與 Chromium；第一個參數必須是 Scout 的 QA 輸出目錄。它會重新寫入 PDF，因此最終 PDF 驗證與 `delivery.json` 回執必須在它之後完成。

```bash
node docs/tutorials/permission-guide/verify-browser.js /absolute/scout/qa-output-directory
python3 docs/tutorials/permission-guide/verify_ui_sync.py
python3 docs/tutorials/permission-guide/verify_ui_sync.py --json
```

`NODE_PATH` 與 `SCOUT_BROWSER_EXECUTABLE` 依現有 Scout 執行環境設定；不需要為同步檢查另外安裝 Python 套件。`--guide-dir`／`--repo-root` 僅供獨立測試或搬移後指定根目錄，預設就是本教學與所屬 repository。

## PASS 的意義

`verify_ui_sync.py` 是唯讀檢查，不會更新圖片、hash 或回執。任一檢查失敗即以非零狀態結束：

- 每頁均有截圖、步驟、穩定 ID 與唯一擷取回執；編號與來源 DOM 目標一一對應。
- 以 magic bytes 判定檔案為 PNG 或 JPEG，核對副檔名；讀取 PNG IHDR 或 JPEG SOF 的實際尺寸，再核對原始圖片 SHA、目標框、標記邊界及 locator。JPEG 缺少完整 frame header 或結束標記也會失敗。
- 目前被追蹤的 UI 原始檔 SHA 與擷取時記錄一致；變動時回報教學過期並要求核對、重拍及重建。
- 完整模式另核對 `build-manifest.json.files` 的 `slides.json`、`index.html`、`presenter-notes.md`、`capture-sources.json`、`build.py`、`verify-browser.js` hashes，以及 `delivery.json` 的 HTML／PDF hashes 和頁數回執。

PASS 證明資料與檔案彼此一致；header 檢查不等於完整圖像解碼。它不能單獨證明 screenshot 確實來自該 DOM、底圖未偏移、文字仍正確、縮放後標記可讀，或 PDF 視覺無誤。因此仍須查看更新頁面的桌面／手機畫面、放大截圖，確認每一個步驟指向正確控制項；PDF 另查實際頁數、順序、尺寸及文字／圖片邊界。來源 hash 一致也不能替代對動態資料、載入錯誤或 workspace 狀態的核對。


## 9099 當前入口與 TASK 歷史頁

目前 Dashboard 是 Mac checkout 的 `http://127.0.0.1:9099/admin/dashboard?projectId=dongqing_batongguan_historic_trail_newImport`。19111 已關閉；不能為補教學另啟動替代 Dashboard。已發行版本第 1–34 頁使用 2026-09-11 TASK 歷史畫面。本輪確定重拍第 **5、35–38 頁**，其餘 **1–4、6–34 頁，共 33 頁**保留原圖、URL、日期與 hashes。第 5 頁取得新拍攝回執後才移入當前來源群組；不能因計畫已更新而宣稱整份教學已完成當前功能對齊。

9099 主地圖與 Weather 頁使用 `capture_context: mac-9099`；shot 使用相同 `source_context`。`capture-sources.json.current_ui_source` 記錄當前來源根目錄與三個 UI 檔 hashes：Dashboard HTML、Phase4 HTML、MapLibre adapter。這組 hashes 與根層的六個 TASK 歷史 hashes 分開。待擷取不能填假座標或以歷史 hashes 補值。

在 Mac 本機可直接讀來源；在 Scout 執行 build／check 時明確提供既有的唯讀 SSH 通道：

```bash
export SCOUT_PERMISSION_GUIDE_MAC_HOST=alexwang0315@Lamb780722de-MacBook-Pro.local
export SCOUT_PERMISSION_GUIDE_MAC_IDENTITY=/home/alexwang0315/.ssh/scout-to-mac
python3 docs/tutorials/permission-guide/verify_ui_sync.py --captures-only
```

檢查器只讀 `docs/admin/` 內指定 HTML／JS／CSS 的 SHA，不讀金鑰內容、不改 UI、不啟動服務。已驗證的 Mac IP 可在 mDNS 失效時指定於 host 變數；host key 檢查保持 StrictHostKeyChecking=yes。來源離線、金鑰通道未配置或當前 hash 不符，都會 FAIL。

## 主地圖與 Weather 的共用圖磚流程

2026-09-12 本輪同步目標：主地圖與 Weather iframe 使用同一套 Phase4 地圖流程，兩頁均顯示共用 `refreshMapTiles` 按鈕（「停止更新／更新圖磚」）。第 35–38 頁須以本輪實拍整組替換，維持原頁面數量與穩定 ID；不能沿用舊圖宣稱已支援共用按鈕。舊的主地圖 Layers → ↻ 操作圖與 Weather 專用 `refreshWeatherMapTiles` 畫面，只保留在 Git 歷史及原始證據中。

圖磚請求必須區分以下三種狀態，不得把同一種測試結果套用到其他狀態：

1. **預設／一般縮放的自動補圖。** 在尚未手動開啟強制更新的預設狀態，Rudy 先讀取快取；缺少所需原生細節才以 `native=1&exact=1` 自動補圖。這不代表已開啟手動更新後的所有縮放仍不會 refresh。
2. **Main Map／Weather 明確手動更新。** 使用者按「停止更新」後切為只讀快取；再按「更新圖磚」會更新目前視野內已勾選的 raster 圖層。現行 Phase4 `toggleRasterRemoteRefresh` 在一般 UI 把 `rasterForceRemoteRefresh` 設為 true，可包含 refresh 與既有快取替換。不得宣稱這個手動操作只補缺圖、永不強制重抓，也不需要捏造另一個 force 按鈕才能解釋現有行為。
3. **D037 隔離 native probe。** 已核准的 `DIAGNOSTIC_NATIVE_TILE_PROBE` 會抑制 force flag，用於隔離驗證 native 圖磚路徑。其 no-refresh 回執只證明該測試模式，不能代替一般 Main／Weather 按鈕的真實手動更新結果。

上列手動差異已唯讀核對 `docs/admin/phase4-pretrip-planning.html` 的 `toggleRasterRemoteRefresh`（本次行號 8952）；原始碼核對仍不是最終畫面 PASS。Permission D1 的共用 SVG 控制可走 native 恢復，須另記實際請求模式，不能推論 Main／Weather 同樣不 force。古地圖預設仍只讀快取；明確勾選圖層後的手動更新另記回執。圖磚控制不會自動重建氣象資料或行程。教學正文可寫「按『更新圖磚』，重新取得目前視野的圖磚，再核對結果」；參數、cache replacement 與 diagnostic 模式留在回執及驗證說明。

以上是本輪要求核對的共用行為，不是僅憑規格即可宣稱的成功。主地圖與 Weather 各需一張自動補圖後的清晰畫面，以及一張停止後確實缺圖、可手動恢復的畫面。保留原始時間、URL、project、實際尺寸、renderer、按鈕文字與狀態、requested／displayed 層級、缺圖或載入結果。目標位於 iframe 時，記錄 iframe 原點與 DOM 座標；只有完成到完整圖片座標的映射後，才設定數字標記。

自動補圖、停止、手動恢復須有各自的真實 UI 與請求回執。成功訊息可能隱藏；成功頁第三步改標實際可見的等高線區域（MapLibre 的 `mapLibreEvidenceMap` 或 SVG 的 `map`），不能把不可見訊息當成標記目標。所有原生圖磚都缺失或失敗時，不得以 adapter 的 available、已掛載圖層或低層級放大當成細節已載入。MapLibre 與 SVG 均核對實際 requested／displayed 及缺圖狀態；不能僅因其他功能頁顯示同一來源成功，就推論這一頁也可用。若手動恢復的成功發生在截圖之後，分開記錄後續回執，不改寫截圖原本的關閉或失敗狀態。

原第 1–34 頁中未受本輪 UI 影響者，保留原圖、URL、拍攝時間與 DOM 目標；六個 TASK 歷史 source hashes 不改寫。D037A／D037B 的每日互動地圖已使第 5 頁成為需要重拍的例外，連同第 35–38 頁更新。取得最終實拍前，不改這些頁面的影像、回執日期或來源 hash；文字草稿與未完成驗證另存在本輪 Scout QA 目錄。實拍與實際來源核對完成後，再更新當前三個 UI hashes、歷史／當前頁面範圍與交付計數，重建 HTML、講稿及 PDF，並檢查全部頁面。舊來源可由 Git 及證據回執取回，不能把新拍攝版本寫成舊圖的原始來源。


## 本輪必備的四種地圖證據

主地圖、Weather 與第 5 頁教的 Permission D1，每個適用 renderer 均需保留以下四種實測。草稿與既有小範圍測試不是完成回執：

1. **一般縮放（normal）。** 在真實入口、尚未明確手動更新的預設狀態，Fit 後第一次 ＋、－、再 Fit，記錄視野、需求／實際原生層級、成功／缺圖數與更新模式。此預設自動補圖應重用既有快取；不能把已開啟 force 的手動更新狀態或 D037 隔離模式混入。放大同張低細節影像不能當成讀到新層級。
2. **實際原生上限（actual maximum）。** 到達支援的最大細節後再按一次 ＋，記錄相機 zoom 或 SVG scale、實際限制、DPR、CSS／截圖尺寸、原生圖磚尺寸與顯示比例，以及 requested／displayed 層級。Rudy 原生來源上限 Z20 與 renderer 的相機 zoom 不必相等，須依實際像素密度映射核對。已發現的 camera Z22／native Z20 放大 8 倍不算最大原生細節通過；修復與 D037 第 10 階段證據未通過前，第 35／37 頁不得發布最大層級成功說明。
3. **停止後實際缺圖（stop 404）。** 在支援的原生層級以真實未快取視野觀測 `cache_only=1&exact=1` 的 HTTP 404、按鈕關閉及缺圖／部分載入提示；不刪除或重建 workspace 來製造測試。所有原生圖磚失敗時，available、圖層掛載或 fallback 都不是成功。
4. **相同視角恢復（same-view recover）。** 保持失敗時的視野、圖層、來源與候選不變，按「更新圖磚」，另存目前視野圖磚的成功回執。Main／Weather 的真實手動更新可帶 refresh、替換已勾圖層快取，必須如實記錄；D037 隔離 native probe 的 no-force 恢復與 D1 共用 SVG 恢復分開標記。每筆回執記入口／模式、按鈕動作、remote／force 狀態、native／exact／cache_only／refresh 參數及來源／替換結果。後續成功不改寫先前 off／404 截圖。

第 35／37 頁使用最終清晰成功畫面，並附預設自動補圖、一般縮放與實際上限證據；第 36／38 頁使用停止後缺圖畫面，另附同視角的真實手動更新結果，不能以 D037 隔離 native probe 取代。Chrome 連續 CDP timeout、Debugger unattached 或使用者重整待完成時，只能完成計畫與文字草稿；不能填入今天的舊圖回執、刷新 hash 消除 drift 或產生宣稱完成的 PDF。source freeze 本身不代表真實畫面驗收通過。

主地圖／Weather 新增可見的 `.pretrip-map-evidence-picker` 證據選單，重拍時保留其實際位置與選取狀態，另記 keyboard focus／highlight 回執。第 35–38 頁仍以圖磚三步驟為主題，不為新增選單硬塞步驟；需要說明時以實際可見文字補充講稿。依 2026-09-13 裁決，凡實際提供的 Box 皆以任意方向框選放大、以 − 縮小；Navigation 的控制項仍須各自實測，不能借用每日圖的框選證據宣稱通過。

## Permission 每日互動圖的教學同步

第 5 頁必須更換舊的「單一 Rudy 影像」實拍。指定 Dongqing workspace，Restore `version.15f1d78018a8af8e`，其 ref 為 `candidates/mission_baselines/baseline.461a71a24faf047c/versions/version.15f1d78018a8af8e.json`，原始 `version_sha256` 為 `a191c171332add7739bd27d41ce9bc48a669047241e9309694ecd69c1b326ac6`。版本 SHA 與 JSON 檔案 bytes 的 SHA 是不同用途，不可混用。核對 9 日、89.8 km 與 D1 0.0–17.3 km；舊 review-ready 不覆蓋目前 projection 狀態。

以同版 D1 卡為例，核對 `[data-permission-day-map]` 內真實 `[data-dashboard-map-viewport]` 值、當日標題、起終點與證據摘要。保留完整未修改的 viewport 截圖，可同時顯示左右兩天，只在 D1 標示四組編號：① 當日標題；② 右上縮放／平移／框選／Fit 工具列；③ 底部 Rudy 更新、重試與原生數量；④ Day route, ETA & evidence。每組都使用實際 DOM 元素框。先重新載入最終 theme-scoped CSS，確認底部文字與按鈕可讀，再拍攝。

760×248 是內部地圖幾何，不代表整張截圖或 CSS 顯示尺寸；root 最近觀測 D1 顯示為 561×248，也不能當成最終固定尺寸。標記使用新實拍像素及當次 DOM 座標；未提供新圖前不設定假座標。

右上工具列涵蓋 zoom-in、zoom-out、reset、pan、box-zoom；底部包含 `data-map-rudy-updates`、`data-map-rudy-retry` 與 `data-dashboard-rudy-status` 的真實原生圖磚數。若一個步驟介紹整組控制，目標框必須取實際共同父元素，不能自行拼湊聯集矩形。更新按鈕的 aria-pressed=true 表示「停止更新」，false 表示「更新圖磚」；缺圖與 Retry 是否可見均以當次畫面為準。

擷取前確認一般縮放、實際原生上限、平移、框選與 Fit。平移必須改變 D1 視野，工具列、卡片位置與瀏覽器捲動位置保持正確；其餘八日的視野、原生層級與更新模式維持不變。`overflow: clip` 的原始碼變更與 D1 初次 ＋ 的 10/10 圖磚回執，都不能替代最終完整實測。另保存停止後只讀快取、HTTP 404 缺圖、D1 共用 SVG 實際恢復／重試模式與完成狀態，不把其後成功寫回早先失敗截圖，也不為拍攝而 Save、Accept、Rebuild、提交人工審查或改寫候選。

第 15 頁的 Golden／Planned 對照圖是 `[data-planned-map="preview"]` 的純向量預覽，不套用 Rudy Z20／native raster 圖磚驗收。此頁只檢查本輪 UI 影響與其獨立控制項、幾何／疊圖可見性及標記位置；若受影響才另列需重拍。每日圖通過不表示其他入口的控制項、所有地圖 UI、Diagnostic、Permission 或 G1–G6 均已完成；最終資料和說明必須沿用實際驗收範圍。


## Navigation／R1–R3 引用頁的有界盤點

本輪已核對 38 頁的 URL、DOM 標記與講稿，另查看第 11、12、15、19、28–30 頁原始 JPEG。沒有 Navigation 真地圖入口或 Navigation 控制項標記：11 是來源選段表單、12 是素材目錄、19 是八項 Navigation 人工確認欄位、28–30 是探索／AOI／TRH 請求表單，均未展示 Navigation／R1–R3 地圖。新增 Pan／證據選單未使這些表單增加確定重拍頁；確定重拍仍為 **5、35–38**。第 15 頁的驗收範圍已依 2026-09-13 裁決確定為向量比較用途，仍待獨立 UI／控制影響檢查；若需換圖，必須使用指定東清 workspace 的真實 Planned 比較資料，不能把奇萊歷史樣本當成當前東清示範。

第 12 頁的舊 Layers → ↻ 講稿已於本輪文字修正為「更新圖磚」，同步修改 slides.json 與 presenter-notes.md，保留預設自動補圖／明確手動更新的差異。HTML 不顯示 note 欄位，故本次不修改 HTML 或圖片；PDF 仍待重建。build-manifest 保留上次完整產製回執，來源文字變動持續可見，不以刷新 hash 偽造完成。D038 是指南尚未涵蓋的 Diagnostic 專用 UI，不為這輪同步另增頁。這項盤點只界定文件影響，沒有把任何舊圖標為新拍，也不代表受影響 UI 或 PDF 已完成更新。


## 2026-09-13 恢復同步的條件

保留 04146d12 的第 12 頁講稿修正：如果按鈕顯示「停止更新」，先停止，再按「更新圖磚」。六項新裁決納入後，仍須取得 root 在使用者 Chrome 的新實拍與最終來源 hashes，才能更新第 5、35–38 頁及必要時的第 15 頁。

Box 任意方向皆放大，以 − 縮小；純 Planned 向量比較不套用 Rudy Z20 驗收，也不捏造它未提供的 Box 控制。loading、partial、failed 與 ready 依實際結果保留；清理 UI 字串不能當成操作已成功。明確候選點定位屬有目的的鏡頭移動，須另記動作與候選 ID，不能混入要求同一視角的圖磚恢復比對。historical 僅加 auxiliary 定位，其餘來源與行為邊界照舊；圖片未實拍前不補造標籤。

root 獨占 Dashboard／使用者 Chrome 的操作與驗收。已明確允許 Scout 的 headless Chromium 僅用於已產生的靜態教學 HTML 版面檢查及 PDF 輸出；不得藉此操作或驗收 9099，也不能取代使用者 Chrome 證據。收到最後擷取與來源凍結確認前不啟動 final build。Planned 新圖若缺真實東清資料，保留缺口並回報，不為製圖建立或核可新候選。


## 2026-09-13 中斷後恢復：教材輸出工具與待拍清單

本段狀態為 **未完成完整教學／PDF**。19120 目前 HTML、PDF 和原 capture manifest
保持原內容；尚未把舊圖標成目前 UI，也未發布本次修正。

- build.py 對高 DPR 原始截圖同步放大數字圈、字體及框線；保留 target focus 的加粗。
  verify_ui_sync.py 要求 pixel_ratio、CSS viewport 與原始 css_box 的確定換算。
- test_capture_scaling.py 9/9 通過，包括 DPR1 保持、DPR2 視覺大小與錯誤換算拒絕。
- verify-browser.js OUTPUT --no-pdf 只驗離線教材，不覆寫現行 PDF；
  HTTP(S) 直接阻擋，任何請求仍會使檢查失敗。實際原 38 頁 × 9 視窗
  342/342 布局通過，這不是 38 頁已按新 UI 更新的證據。
- 新 Saved candidate 第 3 頁由 root 在 2026-09-13T07:11:28.091Z 真實 Chrome 擷取；
  原始 PNG 與 source SHA、CSS rectangles 均保留，未覆蓋歷史 JPG。
  隔離草稿標記步驟 1、2、3；畫面上 rebuild_required 原样保留。
  此時只選取既有15f版本，Restore 啟用但未點擊，不能聲稱已還原成功。
- 實際 captures-only gate 仍 FAIL：Dashboard、Phase4、MapLibre 三個 current source
  與舊擷取 SHA 不符。原檢查、失敗與原素材保留，不能更新 hash 來取代重拍。
- 完整捕捉清單、draft、raw test logs 與 checkpoint：
  /home/alexwang0315/work/scout-pretrip-all-seven-20260910/main-rudy-zoom-20260913/guide-recovery/

完成順序：確認最終 UI → 每頁重拍與 DOM 步驟定位 → 通過 capture/source gate →
重新生成 HTML／講稿 → 全頁離線版面／互動 → 由同版 HTML 生成並逐頁核對 PDF。
目前缺少的 14 頁流程和真實 Saved Planned 資料需求保持待處理，不自行停用章節。

## 2026-09-14：保留 screenshot 原格式與 MIME

拍攝工具要求的檔名／格式，不是回傳格式的證明。先保存原始 bytes，
以 PNG magic（89504e470d0a1a0a）或 JPEG magic（ffd8）辨識；
JPEG 使用 .jpg／.jpeg，PNG 使用 .png。若檔名錯誤，只修正隔離 staging
中的檔名和回執，保留原 bytes 與 SHA，不轉檔、重壓或修改圖片來配合檔名。

新 capture receipt 請記錄工具實際回傳的 mime_type、原始 byte magic、
SHA 與 image header 尺寸。若工具沒有提供 MIME，記錄其缺失，不捏造回傳值。
verify_ui_sync.py 已保留原副檔名／magic 核對；凡 shot 含 mime_type，
其值還須為 image/png 或 image/jpeg，且與原 bytes 一致。歷史 receipt
沒有 MIME 欄位時沿用原契約，不將其改寫成本次擷取。

資料門檻通過後，build.py 的 data URI MIME 與原 bytes 仍須一致。
test_capture_format.py 以保留的歷史原 bytes 重現 JPEG 誤命名 PNG、
錯誤／非法 MIME、截斷格式及 build 拒收；這些 fixture 是教材工具回歸，
不代表 9099 Dashboard、目前截圖或 PDF 已完成驗收。
