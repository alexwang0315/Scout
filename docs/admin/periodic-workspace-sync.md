# Mac → Scout 定期 workspace 資料同步

這是資料夾同步，與 `periodic-git-sync.md` 的 Git commit 同步分開。

- 來源：Mac 登入使用者的 `~/workspace/`。
- 目的：Scout `/home/alexwang0315/workspace/`。
- 預設每 15 分鐘，Mac 主動經 SSH 推送，不需開啟 Mac「遠端登入」。
- Mac 為同名檔案的主來源；Scout 獨有檔案與 Mac 已刪除的檔案不會被刪除。
- 被替換的 Scout 舊檔保存在 `/home/alexwang0315/.local/state/scout-workspace-sync/backups/<UTC-run-id>/`。
- 這不是雙向同步，不會將 Scout 修改送回 Mac；不要同時編輯兩端同一個檔案。
- 不使用 GitHub、Codex 或 OpenAI API，不讀取使用者的 SSH 私鑰或 GitHub 憑證檔內容。

## 在 Mac 安裝一次

需要 `python3`、`rsync`，以及已驗證 Scout host key、可非互動登入的 SSH。
在 Mac Terminal 執行（不要在 Scout 的 SSH shell 執行）：

```bash
scout_workspace_setup=$(mktemp -d) && \
scp alexwang0315@scout.local:/home/alexwang0315/work/scout-fusion/scripts/sync-mac-workspace.py "$scout_workspace_setup/" && \
python3 "$scout_workspace_setup/sync-mac-workspace.py" install
```

若 `scout.local` 解析失敗，可在 `scp` 改成 Scout 的 IP，並在 `install` 後加
`--host 192.168.8.230`（這是 2026-09-09 確認的 IP，日後以實際網路設定為準）。
若來源不同，用 `--source /Users/alexwang0315/workspace` 指定。
安裝器先用 BatchMode SSH 與 rsync dry-run 檢查，失敗時不啟用排程，
不會降低 SSH host key 驗證或把密碼寫進排程。

若失敗，先在 Mac 檢查：

```bash
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes alexwang0315@scout.local true
```

首次連線的 host key 應人工確認；背景作業無法回答密碼提示。
若只有互動 shell 的短期 SSH agent 能登入，需另外設定能在 Mac 登入工作階段
持續使用的 SSH key / Keychain。此安裝器不建立、複製或修改金鑰。

## 安裝內容與檢查

- 固定程式副本：`~/.local/lib/scout-workspace-sync/sync-mac-workspace.py`。
- 排程：`~/Library/LaunchAgents/com.scout.workspace-sync.plist`。
- Mac 狀態：`~/.local/state/scout-workspace-sync/status.json`。
- Mac 事件與最新 rsync 摘要：相同目錄的 `events.log`、`errors.log`、`last-rsync.log`。
- Scout 成功收件紀錄：`/home/alexwang0315/.local/state/scout-workspace-sync/last-success.json`。

```bash
launchctl print "gui/$(id -u)/com.scout.workspace-sync"
cat "$HOME/.local/state/scout-workspace-sync/status.json"
```

`installed` 只代表 launchd 接受排程；`synced` 和 Scout 收件紀錄才證明完成實際傳輸。
安裝後立即觸發第一次，再依 `StartInterval=900` 定期執行。
Mac 必須登入、醒著且能連線到 Scout；睡眠或離線期間不保證同步，恢復後於後續週期重試。
這些排程語意參照 [Apple LaunchAgent 文件](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html)。

## 同步與安全邊界

使用 `rsync -rlt --backup --backup-dir=... --partial-dir=.scout-sync-partial --delay-updates`。
以大小與修改時間判定增量更新；沒有 `--delete`、`--inplace` 或來源刪除。
目標根目錄的既有權限保留；新建資料透過 `umask 077` 限制權限。
先暫存資料再替換，可降低讀到未完成單檔的風險，但不是跨檔案／資料庫的一致性快照。
備份、延遲更新及增量比較語意參照 [rsync 手冊](https://download.samba.org/pub/rsync/rsync.1)。

符號連結保留原連結，不沿連結複製範圍外的資料；Mac 絕對路徑連結在 Scout 可能失效。
不排除一般隱藏檔、地圖、DEM 或大型資料；`.scout-sync-partial` 是同步程式保留名稱。
不改寫 manifest 裡的 Mac 絕對路徑，不驗證每個 workspace 能在 Scout runtime 開啟。
正在寫入的 SQLite / GeoPackage 與多檔專案，不保證該次副本一致；重要快照應先暫停寫入。
僅保留一份最新 rsync 輸出；事件與歷史備份不自動清理，之後需觀察磁碟用量。
不對外傳送聊天訊息；沒有變化的成功週期保持安靜，有錯誤則記錄並於下次重試。

## 停用（不刪除資料）

```bash
launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.scout.workspace-sync.plist"
launchctl disable "gui/$(id -u)/com.scout.workspace-sync"
```

恢復時先 `launchctl enable "gui/$(id -u)/com.scout.workspace-sync"`，再以同一個 plist
執行 `launchctl bootstrap`。安裝器拒絕覆蓋現有程式／排程；調整頻率前先檢查與停用。

## 驗證狀態（2026-09-09）

Scout 已有約 7.2 GB workspace 資料，但無法由 Scout SSH 登入 Mac（port 22 refused）。
因此本次準備安裝程式，在本機用真實 rsync fixture 驗證資料傳輸與備份，並解析 launchd plist；
尚未在真實 Mac 安裝或證明背景傳輸。Mac 完成安裝後，應確認 Scout 成功收件紀錄。
13 項 focused tests 通過，包含真實 rsync 增量傳輸、舊檔恢復來源、無刪除、dry-run、
互斥鎖、失聯／來源消失、SSH 驗證選項、成功收件紀錄及拒絕覆蓋既有排程。
Python 編譯檢查通過；未安裝／設定獨立 lint 工具，因此沒有另跑 lint。

```bash
python3 -m unittest discover -s tests -p test_mac_workspace_sync.py -v
```

不改動 Git sync、GIS contract、資料準備流程或應用程式；未跑無關的全專案／瀏覽器測試。
