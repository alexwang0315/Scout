# CP 顯示名稱重匯實驗

狀態：WORKING PROTOTYPE。日期：2026-09-14。

`dongqing_batongguan_historic_trail_newImport` 的 219 個 CP 已依命名優先序
重匯，Mac 主來源與 Scout 副本的 ID／名稱對照一致，219 個顯示名稱皆不重複。
CP ID、座標、route point index、checkpoint type、arrival radius 與
compression boundary 均與原始工作區相同。

## 實際結果

| 命名依據 | 數量 |
| --- | ---: |
| 人工確認名／既有自訂名／明確信任來源 | 0 |
| 跨 GPX 檔同名佐證 | 2 |
| GPX name、cmt、desc 中的地點描述 | 52 |
| 高度＋坡段／停留點 | 165 |
| 純里程備援 | 0 |

| CP ID | 新顯示名稱 |
| --- | --- |
| `cp.start` | 新登山口 |
| `cp.001` | H約1210上坡段 |
| `cp.rest_area.001` | H約1270停留點 |
| `cp.055` | 中央金礦山屋 |
| `cp.078` | 接稜 |
| `cp.100` | NUNUSUN家屋遺址 |
| `cp.123` | 石階 · 61.507K |
| `cp.finish` | 咖啡園上車處附近 |

主 GPX 沒有 waypoint；參考 GPX 共提供 832 則 waypoint 註記。高度使用
主 GPX 的 `ele`，四捨五入至 10 m 並標示「H約」，不是重新量測的 DEM
等高線高度。沒有地形事件證據時，不把路線轉彎判為轉稜，也不把局部低點
判為鞍部。停留群聚只命名為停留點，不自動確認為營地。

## 規則與來源保留

`pretrip_import.run_pretrip_import` 在選點完成、建立規劃包與事件之前呼叫
`pretrip_checkpoint_naming.name_checkpoints`：

1. 保留位置／route index 相符的人工確認或既有自訂名稱。人工 correction
   的原始 review 保留在命名證據中；既有自訂名沒有 review 時，不宣稱人工
   確認。先前自動命名不會因為再次匯入而升級為人工確認。
2. 明確信任的 GPX SHA-256 可使用原名；或使用至少兩個不同內容 SHA-256
   檔案、同一位置的同名佐證。同一 GPX 的重複副本不增加佐證。
   跨檔同名可能源於山友互相複製，證據明確標記為「同名一致」，不等於現場查證。
3. 擷取短地點描述，保留原始 name／cmt／desc、來源 SHA、waypoint index、
   時間與距離。排除純流水號、純高度／里程、匯出器統計與純行政區地址。
   `001上切點` 的零開頭匯出序號可去除；`H1648營` 的高度不改寫。
4. 無地點描述時，採高度與起終點／停留點／GPX 局部坡段描述；缺少足夠
   高程或坡段證據才退回里程。
5. 同名自動候選加實際路線里程區分。人工名維持原文；內部識別仍用原 CP ID。

匹配上限：CP 至 waypoint 50 m、沿主路線進度差 75 m；已有非零高程時，
高度差不得超過 60 m。距離超過 20 m 的名稱加「附近」。無法區分同位置的
不同路線通過次序時，不套用該註記。方向詞保留原註記語境，不生成反向導航指令。

逐 CP 的命名證據存於工作區 `outputs/checkpoint_naming.json`，並由
`project.json` 的 `checkpoint_naming_ref` 引用。CP `source_attribution`
另帶 `checkpoint_naming` 記錄；選點理由、候選狀態與 runtime safety truth
邊界維持原契約。

## 可重現入口

在包含這次程式變更的 Scout checkout 執行：

```bash
./venv/bin/python tools/reimport_pretrip_checkpoint_names.py \
  --project-root /home/alexwang0315/workspace/dongqing_batongguan_historic_trail_newImport \
  --apply
```

工具驗證 source inbox 原始 GPX 的 SHA，在隔離位置執行完整 GPX importer，
確認所有 CP 身分／幾何相同後，只更新候選名稱與相關顯示投影。
使用既有 `DashboardWorkspacePublication` 的鎖、generation 與原子目錄交換。
已審核 mission baseline 與已審核規劃包維持歷史快照。

路線分析使用名稱投影，原始測量與統計不重算。既有分析輸入若已過期，
不因改名而標為 fresh。這是命名重匯，不是氣象／GIS provider 的重新抓取。

新 workspace 的一般 importer 已自動套用規則。需要另外提供既有名稱時，可用
`--checkpoint-naming-source-root`；明確信任來源可重複提供
`--trusted-checkpoint-name-sha256`。

## Mac／Scout 同步與驗證

既有 Mac → Scout 同步以 Mac 同名檔為主，每 15 分鐘可能覆蓋 Scout 的本地
改名。因此本次也在 Mac 的同名 workspace 執行重匯，沒有變更同步排程。
Mac 執行使用暫存程式 overlay 與既有 venv；沒有覆蓋 Mac 常駐服務的程式，
也沒有重啟常駐服務。其既有匯入按鈕要自動使用新規則，仍需另行部署這份
Scout 程式；本次主來源資料的改名已生效。

兩端 ID／名稱 JSON 對照的 SHA-256：
`f80ffc0e946e9805dd96b37fbe6408e324b43a18132e4502db30c0c94631b4c1`。

- 原始分析的 observed bins 328、guidance eligible bins 322 與 passage nodes
  226 保留。早期試跑連帶重算的統計已從備份恢復，並加入不重算測量的測試。
- 40 個聚焦測試通過：命名優先序、來源副本、空高程、位置歧義、既有名稱、
  重複名稱、重匯冪等性、真實 importer／atomic swap 與統計保留。
- 32 層 workspace 契約通過；沒有 layer ID／順序變更。
- Mac Chrome／Playwright 真實頁面選取 `cp.001`，地圖、路段與側欄均呈現
  `H約1210上坡段`，JavaScript page errors 為 0。已送出 Chrome 開啟要求。
- 此 checkout 缺少 `tools/verify_navigation_freeze.py`，無法執行 freeze guard；
  未建立替代基準。Navigation freeze 依現行 AGENTS 為暫停狀態。
- 沒有安裝新依賴、執行外部模型請求、更新 runtime safety truth 或跑無關全套測試。

持久驗證紀錄位於 `artifacts/cp-naming-20260914/`：`tests.log`、
`mac-reimport-final.log`、`scout-reimport-final.log`、`final-verification.json`、
`scout-cp-naming-browser-report.json` 與 `scout-cp-naming-browser.png`。

Mac 原始檔備份：
`/Users/alexwang0315/workspace/.checkpoint-name-backups/dongqing_batongguan_historic_trail_newImport.fbca8519f84b413a8a2a95285c2afe78/`。
Scout 最早改名前備份：
`/home/alexwang0315/workspace/.checkpoint-name-backups/dongqing_batongguan_historic_trail_newImport.15b65f9ebfad4648b0ef35473f09a6ee/`。
各次工具執行皆另記錄自己的 `backup_root` 與檔案雜湊。

Mac 檢視頁：
`http://127.0.0.1:9099/admin/dashboard?projectId=dongqing_batongguan_historic_trail_newImport#outdoor-architecture`。
