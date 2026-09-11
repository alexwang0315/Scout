# Dashboard 專案名稱復發：版本分歧調查

擷取時間（台北）：2026-09-11T13:00:12+08:00

這次復發的主要原因是 **9099 與先前 19111 使用不同 checkout，而 9099 的版本缺少昨天已完成的名稱修正**。不能把本次現象只歸因於七月原始缺陷一直沒有修好。

## 本次版本證據

| 入口／版本 | Git HEAD | 名稱修正 |
|---|---|---|
| Mac 原生 9099 所對應的 Mac mirror 提交 | `ccfb6676138f2a64a6a73385b36042eb9f54cc39` | 不含 `fb6f2600`；歷史 HTML 仍寫 Chilai，render 未同步專案名稱 |
| 先前 19111 的 TASK repo 提交 | `0e74c04882873821a5fde86acc0efcfba8961dec` | 包含 `fb6f2600`；HTML 使用 Loading workspace，render 同步 URL 選定專案 |
| 已完成的修正 | `fb6f260064bf5a1f8217b9eb75f677ff0cbab559` | 2026-09-10 18:26:47 +08:00；`fix(dashboard): show selected workspace in settings and page identity` |

入口與 checkout 的對應由主工作程序驗證。本檔以明確提交 hash 查 Git 歷史；修補中的 Mac working tree 不被當作舊版本證據。本輪已移植昨天的四處名稱修正；9099 重新載入後，瀏覽器的 sidebar、文件標題、Map iframe 與 API 均指向 dongqing_batongguan_historic_trail_newImport。

祖先關係結果：

- `git merge-base --is-ancestor fb6f260064bf5a1f8217b9eb75f677ff0cbab559 ccfb6676138f2a64a6a73385b36042eb9f54cc39` 回傳 **1**：不是 Mac HEAD 祖先。
- `git merge-base --is-ancestor fb6f260064bf5a1f8217b9eb75f677ff0cbab559 0e74c04882873821a5fde86acc0efcfba8961dec` 回傳 **0**：是 TASK HEAD 祖先。
- Mac mirror 自身 `git cat-file -t fb6f260064bf5a1f8217b9eb75f677ff0cbab559` 回傳 128，當時本地物件庫也沒有此物件；TASK 的共用 bare repository 同時有兩邊物件，因此 ancestor／merge-base 比較在 TASK 執行。
- Blob 摘錄與 SHA256、全部命令結果見 [原始歷史證據](http://127.0.0.1:19121/rudy-9099-repair-20260911/history-evidence.txt)。

## 昨天的修正實際包含什麼

`fb6f2600` 修改三個檔案（40 行新增、3 行刪除）；完整原始 patch 保存在 evidence：

1. Dashboard sidebar 初始文字：Chilai 改為 `Loading workspace…`。
2. Agent context chip：`project=chilai_nanhua_day1_scoutAI` 改為 `project=loading`。
3. `render()` 開始時讀取 `projectId()`，更新文件標題與 sidebar，並保留同專案的 retrying 訊息。
4. Settings 的 Project 從常數 `PROJECT_ID` 改為 `projectId()`。
5. 同步新增 project identity 的回歸測試及 Permission guide 驗證紀錄。

因此，9099 的舊版本缺的是一份已存在但尚未整合過去的修正，而不是昨天完全沒有做這項修復。

## 原始缺陷的歷史補充

| 台北時間 | Commit | 影響 |
|---|---|---|
| 2026-07-01 11:21:31 | `2b3c79f9` | 初建 Dashboard，HTML 已有 Chilai 初始文字；當時 loadData 會立即由 projectId 覆寫，URL 專案解析優先。 |
| 2026-07-13 16:13:17 | `31ca8d95` | 把名稱更新移至 loadDataForRoute；初次 setRoute 的 loadRouteData 預設 false。但 Map 當時仍有 project scope，所以直入 Map 尚正常。 |
| 2026-07-28 13:15:10 | `a71d1fb5` | loadData 在沒有 scope 時直接 return；當時 Map 仍有 project scope。 |
| 2026-07-28 14:15:22 | `107cfe19` | Map 改由 iframe bridge 取資料，移出 ROUTE_DATA_SCOPES.project，卻未獨立處理 sidebar 名稱更新；直入 Map 因此可能停留於 HTML 初始 Chilai 字串。 |
| 2026-09-10 18:26:47 | `fb6f2600` | 在 TASK 分支修復名稱、標題與 Settings，並補測試。 |
| 本次入口版本核對 | Mac `ccfb6676` 對 TASK `0e74c048` | TASK 的修正沒有出現在 Mac 提交；切回 9099 便再次呈現舊行為。 |

Git author 紀錄都是 alexwang0315，不能以提交設定推定究竟由使用者或哪一個 agent 實際編輯。

## 隔離重播與解讀

本輪使用歷史 blob 的實際 projectId、loadData、loadDataForRoute、scope table，以及 render 開頭的名稱更新區塊做隔離 Node 控制流程重播。API 讀取全 stub，並把 URL 設為 Dongqing、route 設為 map。這是因果確認，並非完整瀏覽器驗收。

| 版本 | 初次 render 有名稱修正 | loadData 的 Map scope | 最終 sidebar |
|---|---|---|---|
| `2b3c79f9` | 無，舊 loadData 會更新 | 舊流程 | Dongqing |
| `31ca8d95` | 無 | project | Dongqing |
| `a71d1fb5` | 無 | project | Dongqing |
| `107cfe19` | 無 | 無 | Chilai |
| Mac `ccfb6676` | 無 | 無 | Chilai |
| 修正 `fb6f2600` | 有 | 無 | Dongqing |
| TASK `0e74c048` | 有 | 無 | Dongqing |

前一輪僅檢查 Mac 歷史，未比對 TASK 的近期修正，因而把「缺陷起源」誤當成「本次復發原因」。本檔以近期版本差異修正此結論。

## 後續整合參考

共同祖先：`3ba8cb2c74418a29955b24695d66a9a3066c8d27`。兩邊各自多出的提交數：Mac **6**，TASK **7**。這是調查時的已提交歷史，不包括本輪 working tree 修補；本次調查未做 merge、rebase 或 cherry-pick，修補另由 Scout commit gateway 記錄。

Mac 獨有提交：

```text
ccfb6676 2026-09-11T12:21:48+08:00 feat(dashboard): add read-only Scout device inventory
45886e9c 2026-09-11T11:47:05+08:00 refactor(dashboard): keep Scout monitor focused on Scout hardware
e8df6fb7 2026-09-11T11:07:54+08:00 feat(dashboard): integrate Scout hardware monitor in System
fc3b7019 2026-09-11T10:36:22+08:00 chore: upgrade Praison SDK to 1.7.5 and qualify Scout compatibility
2dafdc9f 2026-09-11T09:08:51+08:00 Use available default port for macOS resource monitor
2764a288 2026-09-11T09:06:42+08:00 Add read-only macOS Scout resource monitor
```

TASK 獨有提交：

```text
0e74c048 2026-09-11T11:27:03+08:00 docs(permission): add current UI screenshots and numbered steps
af973565 2026-09-10T18:52:35+08:00 docs(permission): explain saved candidate restore and review workflow
fb6f2600 2026-09-10T18:26:47+08:00 fix(dashboard): show selected workspace in settings and page identity
999f736f 2026-09-10T18:04:59+08:00 fix(permission): enable Dongqing baseline recovery and tutorial entry
00124440 2026-09-10T16:54:07+08:00 docs(permission): add visual onboarding deck PDF and presenter guide
04525e7b 2026-09-10T16:06:10+08:00 docs(pretrip): record seven-workstream native qualification and R4 deferral
aa176008 2026-09-10T15:56:54+08:00 feat(pretrip): integrate planning context maps and recorded reanalysis
```

需要整合的是兩邊的功能與修正：Mac 的裝置監測和 SDK 更新，以及 TASK 的行前工作流、Permission 與教學成果。後續應逐項確認 shared Dashboard／tests／教學產物，不能以整個 checkout 覆蓋另一邊。唯一入口的驗收應記錄 repo 路徑、提交及必要修正存在性，避免只看 port 可連線就當成同一版本。

## 本輪已完成的修補與範圍

- 19111 的 Scout 服務與 Mac 轉接埠均已關閉。9099 仍由 Mac checkout 的 `tools/dashboard_workspace_app.py` 提供。
- 補回 `fb6f2600` 的 sidebar、標題、Agent 初始標籤與 Settings 專案名稱修正。直接進入東清 `#map` 的瀏覽器與真實 JavaScript 函式重播均通過。
- Rudy+TW 不再把準備階段的 Z14 上限當成來源上限；會請求目前需要的原生層級，並在 cache-only 模式讀取相同來源／指紋的既有精確快取。
- `exact=1` 缺圖回 404，不用父層放大或透明圖片偽裝成成功；保留原本非 exact API 行為。未擴大預設遠端取圖權限。
- 地圖縮放數字直接跟隨 MapLibre 視角；圖磚錯誤不會被後來的 source-loaded 事件掩蓋。窄版 Layers 展開時，更新按鈕不再被其他地圖控制蓋住。

實際瀏覽器證據（東清，9099）：

| 檢查 | 觀測結果 |
|---|---|
| 主地圖 | 畫面 z15.5，記錄到 9 筆 Z16 圖磚 HTTP 200，`local_source_cache`、`X-Scout-Tile-Exact: true` |
| Weather 地圖 | 畫面 z15.0，記錄到 9 筆 Z16 圖磚 HTTP 200，同樣為精確來源快取 |
| 預設取圖政策 | 圖磚請求保留 `cache_only=1`，本輪不需下載便能顯示已存的細節 |
| 窄版更新按鈕 | Layers 展開後，按鈕中心的 DOM hit-test 確認可接收點擊 |

連續縮放途中有被瀏覽器取消的舊視角請求；這些不是 HTTP 圖磚錯誤。以上是被測視角的原生細節證明，不能擴張為整條路線或所有地區的完整離線覆蓋。

![主地圖原生 Rudy 細節](http://127.0.0.1:19121/rudy-9099-repair-20260911/ui-main-map-native-zoom.jpg)

![Weather 原生 Rudy 細節](http://127.0.0.1:19121/rudy-9099-repair-20260911/weather-native-detail.jpg)

檢查紀錄存於 Scout `rudy-9099-repair-20260911/`：後端／頁面初次組合 93 passed、1 項既有 historical-map auxiliary 文字斷言失敗；該斷言在修補前 HEAD 也不成立，未為它回退已存在的圖層契約。最終前端組合 50 passed，API／adapter 組合 26 passed；pnpm lint、typecheck 通過，pnpm test 使用 Scout 已有 QA 依賴後 27 passed。JavaScript 語法檢查與現行 33-layer 契約通過。Navigation guard 仍是 `NAVIGATION_FREEZE_SUSPENDED`，沒有變更 baseline。

**未完成整併**：Mac 仍缺少 TASK 的四個 Permission／recorded／exploration 前端模組，不能宣稱 9099 已包含另一分支全部功能。這次沒有覆蓋任一工作區、改動審查決定、重跑行前準備或把 Mapsforge `.map` 加成底圖。教學會保留既有 34 頁截圖的歷史來源，另補本輪實測地圖操作頁，避免把舊畫面標成 9099 當前版本。
