# Scout Dashboard v0.2 文案來源追查

日期：2026-09-22
對象：`docs/admin/scout-dashboard-v0.2.html`
證據：使用者提供的 v0.2 截圖，以及目前工作區的實際 source scan。
目前結論：截圖中的這一組文字不是 workspace/API 的真實資料，而是 v0.2 前端自行硬編碼的「route truth」狀態標籤。本輪已將該 truth strip 從一般使用者流程隱藏，只保留 Diagnostic 內部檢查使用。

## 1. 截圖中的文字逐項追查

| 畫面文字 | 直接來源 | 類型 | 問題 |
|---|---|---|---|
| `可用` | `ROUTE_TRUTH.home.maturity = "live"`；在 `48168` 由 `live → 可用` | 前端狀態翻譯 | 它代表介面成熟度，不代表目前 workspace、地圖、資料或決策真的可用，容易過度保證。 |
| `操作介面` | `ROUTE_TRUTH.home.surface`；同一筆資料的 `mode` 也再次使用 | 前端硬編碼分類 | 是工程分類，不是使用者要完成的工作，也造成同一詞重複出現。 |
| `唯讀導覽` | `ROUTE_TRUTH.home.action` | 前端硬編碼操作模式 | 這不是下一個實際操作，只是在描述權限／模式；使用者不知道下一步要點什麼。 |
| `目前畫面` | `renderTruthStrip()` 的欄位標題 | 前端固定欄位名 | 太抽象；沒有回答「現在正在做什麼」。 |
| `目前資料` | `renderTruthStrip()` 的欄位標題 | 前端固定欄位名 | 與「來源／可用度」重疊，且可能把資料狀態與資料內容混在一起。 |
| `混合專案證據` | `ROUTE_TRUTH.home.data` | 前端硬編碼分類 | 「證據」是內部術語；沒有說明目前資料是什麼、是否完整、能否使用。 |
| `下一步` | `renderTruthStrip()` 的欄位標題 | 前端固定欄位名 | 欄位名稱本身合理，但值是 `唯讀導覽`，所以沒有提供真正下一步。 |
| `確認狀態` | `renderTruthStrip()` 的欄位標題 | 前端固定欄位名 | 這裡顯示 `路線介面已驗證`，實際是在展示 QA／工程驗證，不是使用者的路線結果。 |
| `路線介面已驗證` | `ROUTE_TRUTH.home.verification` | 前端硬編碼 QA 狀態 | 把「介面是否通過內部檢查」放在使用者主視線，不能代替路線資料的實際狀態。 |
| `來源／可用度` | `renderTruthStrip()` 的欄位標題 | 前端固定欄位名 | 將來源、資料可用性與狀態混成一個欄位，語意過寬。 |
| `工作區與執行投影` | `ROUTE_TRUTH.home.provenance` | 前端硬編碼工程術語 | 「執行投影」不是使用者語言；沒有告訴使用者資料來自哪裡、是否新鮮、是否可操作。 |
| `操作介面 · 唯讀導覽` | `renderTruthStrip()` 將 `truth.surface` 與 `truth.action` 用 `·` 串接 | 前端組合文案 | 這是狀態摘要，不是標題或結果；內容抽象且佔據首屏注意力。 |
| `工作區與執行投影 · 操作介面` | `renderTruthStrip()` 將 `truth.provenance` 與 `truth.mode` 用 `·` 串接 | 前端組合文案 | 同一個工程分類再次重複，沒有新增可採取的資訊。 |

## 2. 實際產生流程

這個區塊的文字產生順序如下：

1. v0.2 的初始 state 將路由設為 `home`：`scout-dashboard-v0.2.html:15737`。
2. `ROUTE_TRUTH.home` 在 `scout-dashboard-v0.2.html:15162` 直接寫入：

   ```js
   {
     maturity: "live",
     surface: "操作介面",
     data: "混合專案證據",
     action: "唯讀導覽",
     verification: "路線介面已驗證",
     provenance: "工作區與執行投影",
     mode: "操作介面"
   }
   ```

3. `resolveRouteTruth(route)` 在 `scout-dashboard-v0.2.html:19606` 取得這筆硬編碼物件；截圖中的 home 狀態沒有被 workspace API 的具體資料取代。
4. `renderTruthStrip(route)` 在 `scout-dashboard-v0.2.html:19858` 將它渲染成五個欄位：`目前畫面`、`目前資料`、`下一步`、`確認狀態`、`來源／可用度`。
5. 同一個 `renderTruthStrip()` 在 `scout-dashboard-v0.2.html:19874` 產生右上摘要：

   ```js
   `${truth.surface} · ${truth.action}`
   ```

6. v0.2 的工作流 orientation layer 在 `scout-dashboard-v0.2.html:48168` 將工程值翻成畫面用詞：

   ```js
   {live: "可用", partial: "部分可用", preview: "預覽", sandbox: "沙盒"}
   ```

## 3. 它們不是從哪裡來的

對目前 repository 做 exact-string search 後：

- `混合專案證據` 只出現在 `scout-dashboard-v0.2.html`。
- `唯讀導覽` 只出現在 `scout-dashboard-v0.2.html`。
- `路線介面已驗證` 只出現在 `scout-dashboard-v0.2.html`。
- `工作區與執行投影` 只出現在 `scout-dashboard-v0.2.html`。
- `來源／可用度` 只出現在 `scout-dashboard-v0.2.html`。

因此目前沒有證據顯示這些字串來自：

- `dongqing_batongguan_historic_trail_newImport` workspace metadata；
- CWA、GPX、地圖或 route API；
- 使用者輸入；
- `admin_api.py` 的動態回應；
- Named CP 或歷史資料。

它們是 v0.2 前端在 route metadata 層新增的固定詞彙。`ROUTE_TRUTH` 的命名也顯示它們原本是為了工程／診斷用途建立的 truth contract，後來直接被放到使用者可見的 top status strip。

## 4. 為什麼會被看成標語與無用詞

這個區塊同時混合了四種不同層級的資訊：

| 層級 | 截圖中的內容 | 正確位置 |
|---|---|---|
| 使用者結果 | 目前路線是否能繼續、資料是否足夠、下一個要檢視什麼 | 首屏主要結果／主要操作 |
| 資料狀態 | 路線資料、地圖、天氣、個人資料是否可用 | 結果旁的短狀態 |
| 系統模式 | 唯讀、候選、預覽、未啟用 | 鄰近 info hint 或次要狀態 |
| 內部驗證 | 路線介面已驗證、workspace projection、truth contract | Diagnostic 或開發者區域 |

目前 v0.2 把後三種資訊放在使用者首屏，並用「目前資料／確認狀態／來源／可用度」包裝成像產品結論的語氣，所以看起來像沒有意義的標語。

## 5. 初步清理判定

以下不是本次直接修改，而是依來源追查得到的清理判定：

- `操作介面`：從使用者首屏移除；若工程需要，保留在 Diagnostic metadata。
- `混合專案證據`：改成具體的「系統目前狀態」，並由實際資料狀態填入。
- `唯讀導覽`：不作為下一步；改成真正可執行的操作，例如「檢視路線背景」或「選取路線區段」。
- `路線介面已驗證`：從使用者主畫面移到 Diagnostic；主畫面改顯示資料是否完整、是否需要更新或是否可繼續。
- `工作區與執行投影`：從主畫面移除；來源需要顯示實際來源名稱或藏在鄰近 hint。
- `來源／可用度`：拆成具體的「資料來源」與「資料狀態」，沒有值就不顯示空泛欄位。
- `可用`：不能直接由 `maturity: live` 翻譯而來；必須改由實際目前資料狀態決定，避免「介面可用」被誤讀成「路線可行」。
- `目前畫面／目前資料／確認狀態`：若沒有具體結果或行動價值，移到 hover hint 或刪除。

## 6. 相關但不是截圖主詞的來源問題

同一個 v0.2 source 在 `projectLabels` 仍保留 `chilai_nanhua_day1` 的 label mapping；目前 workspace 應以 `dongqing_batongguan_historic_trail_newImport` 為準。這不是截圖中五個詞的來源，但屬於同一類「前端固定 metadata 與目前真實 workspace 混用」問題，必須一併列入清理。

## 7. 下一輪清查方式

後續應把 v0.2 所有固定文案分成三份清單，而不是只靠肉眼看畫面：

1. 使用者結果與下一步：允許出現在首屏。
2. 資料狀態與來源：只保留對目前決策有用的短句。
3. 工程／診斷／版本／權限 metadata：移到 Diagnostic、hover hint 或 source drawer。

每一筆固定文案都要記錄：source file、line、產生函式、是否來自 API、是否是變數、使用者用途、是否 ≤20 words、是否應刪除或改寫。

本文件完成來源追查後，已立即修改 v0.2：一般使用者 route 不再渲染這組工程 truth metadata；Diagnostic route 仍保留內部檢查用途。下一步仍需用真實 workspace 逐頁驗證沒有其他固定詞句冒充動態資料。
