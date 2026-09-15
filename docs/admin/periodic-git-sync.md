# Mac / Scout 定期 Git 同步

> **目前狀態（2026-09-09）**：本文件記錄的 GitHub 雙端定期同步已停用。Scout
> 現在使用本機 bare Git server；請改看
> [`scout-local-git-server.md`](scout-local-git-server.md)。下面的內容保留作為歷史
> 設定與停用紀錄，不代表 timer 目前仍啟用。

本次設定只涵蓋 `scout-fusion`，兩端各自每 15 分鐘同步同一個遠端 Git 分支：

- 遠端：`https://github.com/alexwang0315/Scout.git`（也接受同一 repo 的 SSH URL）
- 分支：`codex/scout-wip-transfer-20260822`
- Scout checkout：`/home/alexwang0315/work/scout-fusion`
- 排程不呼叫 LLM，也不使用 Codex / OpenAI API 額度。

Mac 直接連 Git 遠端，不需要讓 Scout SSH 登入 Mac。Mac 安裝後使用
per-user LaunchAgent；Scout 使用 systemd user timer。

## 本次安裝結果（2026-09-07）

- Scout：timer 曾 enabled，18:15:17 Asia/Taipei 已由排程實際觸發一次（後於 2026-09-09 停用）。
- 實際 checkout：`blocked / dirty`，保留未提交的修改，尚未同步這些檔案。
- 遠端讀取：`git ls-remote` 成功。
- GitHub：使用者已完成 `alexwang0315` 瀏覽器授權，API 確認此 repo `can_push=true`。
- 授權依使用者同意保存在 Scout 的 GitHub CLI 本機未加密憑證檔；
  `/home/alexwang0315/.config/gh/hosts.yml` 為 `600`，所在目錄為 `700`。
  沒有把憑證寫入 checkout、排程設定或操作紀錄。
- 此 checkout 的 repo-local Git credential helper 已接上
  `/home/alexwang0315/.local/bin/gh auth git-credential`；不依賴 Mac 的 SSH agent。
- 實際背景服務的 push dry-run 已通過。測試使用遠端已有的提交
  `02285c84c9a6639d6c2613f61aebd33a6b7dc594`，沒有真正推送新的 commits。
- 更新遠端追蹤資訊後，本機落後指定遠端分支 4 個 commits、領先 0 個；
  本機仍有未提交修改，因此沒有自動合併或清除工作目錄。
- Mac：安裝程式與 plist 產生測試已準備，尚未在真實 Mac 安裝或驗證。
- 本機實際 Git 測試：10 項通過。
- 2026-09-09：已建立 `/home/alexwang0315/git/scout-fusion.git`（權限 `700`），
  停用 `scout-fusion-git-sync.timer`；Mac 的 3 個 branches 已遷移到新 bare server，
  但 Mac working tree 的未提交／未追蹤修改仍保留，尚未刪除 Mac checkout。

Scout 排程及推送授權已完成，但不能宣稱兩端已在自動同步。仍需在 Mac 安裝
排程，並由使用者整理提交兩端要同步的工作；若之後歷史分岔，需人工整合。

## 實際同步規則

| 情況 | 動作 |
|---|---|
| 已提交的本機分支領先遠端 | 普通 push，只推送檢查過的 commit 到指定分支 |
| 遠端分支領先本機 | `merge --ff-only` 快轉到遠端 commit |
| 已經一致 | 不修改檔案 |
| 有 staged、unstaged、untracked 修改或 dirty submodule | 保留修改並跳過 |
| 兩端都有不同 commits | 跳過，需人工整合 |
| 分支切換、detached HEAD、rebase/merge/bisect 中 | 跳過 |
| upstream 或遠端 URL 改變 | 跳過，需確認後重新設定 |
| 連線或登入失敗 | 記錄阻塞，下一個週期再試 |

程式不會自動 add、commit、stash、rebase、建立 merge commit、force-push、
reset 或刪除分支。`.env`、未追蹤資料與本機依賴不會因排程而被加入 Git。
已在 Git commit 裡的檔案則依 Git 正常同步，所以仍須在 commit 前檢查內容。

同時執行的排程使用本機 lock 避免重疊。兩端同時 push 時，Git 的普通 push
會拒絕非 fast-forward 更新；排程不會強制覆蓋遠端歷史。編輯期間有檔案未提交，
排程就會跳過；建議在另一台最新 commits 拉取完成後再開始新的修改，減少分岔。

## Scout 端安裝

```bash
cd /home/alexwang0315/work/scout-fusion
python3 scripts/install-scout-git-sync.py "$PWD"
```

安裝器把經檢查的同步程式複製到使用者的 `.local/lib/scout-git-sync/`，
排程執行這份固定副本，不會跟著 checkout 裡的程式自動變更。
安裝不要求 checkout 乾淨；真正同步仍會檢查是否有未提交修改。
既有排程不會被安裝器覆寫。

## Mac 端一次性安裝

先在 Mac 的 `scout-fusion` 專案根目錄開啟 Terminal，確認 `python3`、Git
和對 Scout 的 SSH 連線可用。接著執行：

```bash
scout_sync_setup=$(mktemp -d)
scp alexwang0315@scout.local:/home/alexwang0315/work/scout-fusion/scripts/sync-project-git.py \
    alexwang0315@scout.local:/home/alexwang0315/work/scout-fusion/scripts/install-scout-git-sync.py \
    "$scout_sync_setup/"
python3 "$scout_sync_setup/install-scout-git-sync.py" "$PWD"
```

這些檔案先下載到 Mac 的暫存目錄；安裝後的程式另有持久副本，因此不會新增
Mac checkout 的未追蹤檔案。指令不會要求開啟 Mac 遠端登入，只需 Mac 能 SSH 到 Scout。
安裝器會確認目前分支及 upstream 都是指定分支；若不符，先自行保存工作並確認
分支，再重新執行，不會自動切換。

Mac 還需要可供背景作業使用的 Git 遠端登入方式，例如既有 SSH key / Keychain
credential helper。背景作業不會開互動登入提示；首次安裝後應檢查 status.json。

Mac 排程在使用者登入時運作，離線或睡眠時不保證同步，恢復可用後會在後續週期
繼續檢查。LaunchAgent 設定依照 [Apple launchd 文件](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html)。

## 檢查與通知

Scout：

```bash
systemctl --user list-timers scout-fusion-git-sync.timer --all
systemctl --user start scout-fusion-git-sync.service
journalctl --user -u scout-fusion-git-sync.service -n 10 --no-pager
cat /home/alexwang0315/.local/state/scout-fusion-git-sync/status.json
```

Mac：

```bash
launchctl print "gui/$(id -u)/com.scout.fusion.git-sync"
cat "$HOME/.local/state/scout-fusion-git-sync/status.json"
```

每次檢查更新 `status.json`。相同狀態不重複輸出或通知；同步完成、出現新阻塞、
或阻塞解除時才嘗試桌面通知。Mac 的通知是否顯示取決於系統通知權限。
Scout 未安裝桌面通知工具時，`notification=unavailable`，請讀取 journal / status.json；
這不是 Codex App 的通知排程，也不會自動傳送聊天訊息。

## 停用

Scout：

```bash
systemctl --user disable --now scout-fusion-git-sync.timer
```

Mac：

```bash
launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.scout.fusion.git-sync.plist"
launchctl disable "gui/$(id -u)/com.scout.fusion.git-sync"
```

以上停用不刪除程式、設定或 Git 資料。再次啟用 Mac 時先 `launchctl enable`
對應的 label，再以原 plist `launchctl bootstrap`。

## 驗證與待辦

```bash
python3 -m unittest discover -s tests -p test_project_git_sync.py -v
```

測試使用本機 bare remote + Mac/Scout 兩份 checkout，實際執行 push / fast-forward
和保護情境。Mac plist 可在 Linux 產生並解析，但不等於已在真實 Mac 執行成功。
升格正式維運前可再增加跨機器通知管道、Mac 長期運行驗證及事件記錄輪替。
