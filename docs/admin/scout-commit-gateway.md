# Mac 無 `.git` 的 Scout 提交閘道

Mac 專案檔案保留在 `/Users/alexwang0315/scout-fusion`；Git 的 canonical
歷史放在 Scout：

```text
alexwang0315@scout.local:/home/alexwang0315/git/scout-fusion.git
```

Mac 端的 `/Users/alexwang0315/bin/scout-commit` 會把專案快照送到 Scout
專用 staging checkout，再由 Scout 建立 commit 並以普通（非 force）push 寫入
bare server。Mac 的 `.git` 不需要存在，因此可以節省本地 Git 物件、index 與
reflog 空間。

## 日常操作

若尚未把 `~/bin` 放進 PATH，可直接使用完整路徑：

```bash
/Users/alexwang0315/bin/scout-commit status
/Users/alexwang0315/bin/scout-commit commit "描述這次修改"
```

`status` 只同步並顯示待提交檔案；`commit` 才會在 Scout staging checkout
執行 `git add --all`、檢查 whitespace、建立 commit，並推送到：

```text
/home/alexwang0315/git/scout-fusion.git
```

可選擇加入 PATH：

```bash
echo 'export PATH="$HOME/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
scout-commit status
```

提交後若要確認遠端 HEAD：

```bash
ssh scout.local 'git --git-dir=/home/alexwang0315/git/scout-fusion.git \
  log -1 --oneline codex/scout-wip-transfer-20260822'
```

## 傳輸邊界

同步會排除 Mac 本機資料：`.git/`、`artifacts/`、`node_modules/`、`reports/`、
`.env*`、虛擬環境、Python cache 與 `.DS_Store`。其餘已追蹤、修改及未追蹤檔案
都會成為 Scout staging 的候選快照；Git 自己的 `.gitignore`／exclude 仍會決定
哪些檔案真正進入 commit。

staging checkout 是閘道專用目錄：

```text
/home/alexwang0315/work/scout-fusion-mac-commit
```

若同步中斷，再次執行同一個命令會從既有 staging 續傳；不會覆蓋 Mac 原始檔案。
閘道使用單一 lock 避免兩個 Mac 提交同時執行，並拒絕空白 commit message、
whitespace 錯誤、歷史 divergence、force push 與遠端 branch 刪除。

## 目前遷移狀態（2026-09-09）

- Mac 工作樹仍保留；目前 branch 是 `codex/scout-wip-transfer-20260822`。
- Mac → Scout `status` 實測成功，沒有建立 commit。
- Mac 的 `.git` 已移除（約 448 MB）；移除只影響 Git metadata，沒有刪除專案檔案。
- 移除 `.git` 後再次執行 `status` 仍成功，證明閘道不依賴 Mac Git metadata。
- GitHub remote 仍保留作為歷史 fetch/archive 來源；閘道的提交目標固定是 Scout
  bare server。
