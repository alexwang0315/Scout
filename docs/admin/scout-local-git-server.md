# Scout 本機 Git server 遷移

Scout 現在提供一個只允許 `alexwang0315` 使用的 SSH Git bare repository：

```text
alexwang0315@scout.local:/home/alexwang0315/git/scout-fusion.git
```

它使用現有的 SSH server，不需要另外開 Git daemon 或新的網路埠。bare repo
設定了 `receive.denyNonFastForwards=true`、`receive.denyDeletes=true`、
`receive.fsckObjects=true`，避免一般 push 改寫或刪除遠端歷史。
Scout 目錄與 bare repo 都是 `700`；GitHub 憑證沒有搬進 repo。

## 在 Mac 遷移一次

先確認 Mac checkout 沒有未提交／未追蹤修改；Git push 不會搬移工作目錄的未提交檔案。
以下指令下載受保護的遷移工具，推送 Mac 本機所有 branches 與 tags，驗證目前 branch
的 commit，並把 `git push` 預設目標改為 Scout。它不使用 force push、mirror push、刪除
remote、刪除 branches，也不移除 GitHub remote：

```bash
cd /Users/alexwang0315/scout-fusion
scout_git_setup=$(mktemp -d) && \
scp alexwang0315@scout.local:/home/alexwang0315/work/scout-fusion/scripts/migrate-mac-repo-to-scout.py "$scout_git_setup/" && \
python3 "$scout_git_setup/migrate-mac-repo-to-scout.py" "$PWD"
```

如果 Mac checkout 不在上述路徑，把 `cd` 改成實際專案根目錄。工具會先驗證 SSH
host key 與 Scout bare repo；若工作目錄 dirty 或已存在不同的 `scout` remote，會停止且
不 push。要先預覽，可在最後加 `--dry-run`。

成功輸出 `"status": "migrated"` 後，Mac 的目前 branch 已 upstream 到 `scout/<branch>`，
之後通常執行：

```bash
git add ...
git commit -m "..."
git push
```

`git commit` 仍在本地工作目錄產生 commit；`git push` 才會把它送到 Scout。要讓 Mac
完全不保留 checkout，必須改用 VS Code Remote SSH、SSH shell，或在 Scout checkout
`/home/alexwang0315/work/scout-fusion` 上編輯；不能在沒有工作目錄的 Mac 上直接執行
本地 `git commit`。

## Scout checkout

目前 Scout 的開發 checkout `/home/alexwang0315/work/scout-fusion` 保留了既有未提交修改，
沒有被遷移流程覆蓋。它已加入 `scout-local` remote，但尚未自動把 GitHub 歷史切換成
新 bare repo。Mac migration 成功後，再在 Scout 上檢查：

```bash
cd /home/alexwang0315/work/scout-fusion
git fetch scout-local --tags
git ls-remote scout-local
git status --short --branch
```

若要讓 Scout checkout 也以本機 bare repo 為 upstream，必須先確認 Mac 推上去的 branch
和目前 Scout 的未提交工作如何整合；本步不自動 merge、reset、stash 或覆蓋檔案。

## 舊排程

原本連 GitHub 的 `scout-fusion-git-sync.timer` 已停用（停用不刪除 repo、state 或程式）。
新的 single-server 模式不需要兩端定期互相 pull/push；Mac 由 SSH push 到 Scout，Scout
上的 bare repo 成為 canonical Git server。workspace 資料同步仍是另一條 Mac → Scout
路徑，不會取代 Git。

## Mac 保留檔案、Scout 負責 commit

若要在 Mac 保留編輯檔案但移除 Mac `.git` 以節省空間，使用專用提交閘道：

```bash
/Users/alexwang0315/bin/scout-commit status
/Users/alexwang0315/bin/scout-commit commit "描述這次修改"
```

閘道會把 Mac 快照送到 `/home/alexwang0315/work/scout-fusion-mac-commit`，在 Scout
執行 `git add --all` 與 commit，再以普通 push 寫入本機 bare repo。它排除 Mac 的
`.git/`、`artifacts/`、`node_modules/`、`reports/`、`.env*`、虛擬環境與 cache；
Git exclude／ignore 仍是最後的提交邊界。完整操作見
[`scout-commit-gateway.md`](scout-commit-gateway.md)。

## 驗證與保留邊界

Scout 端已驗證 bare repo 存在、權限為 `700`、receive 防護設定已寫入，並已確認舊 timer
停用。遷移工具在本地 bare-repo fixture 通過 5 個 focused tests，包含完整 branches/tags
推送、dirty 阻擋、dry-run、錯誤 remote 拒絕與 host injection 拒絕。

2026-09-09 實際遷移結果：Mac 的 3 個 local branches 已以普通 push 推到 bare server，
Scout `git fsck --full --no-reflogs` 通過；Mac 的 pre-push hook 也通過 lint、typecheck
及 21 項測試。因 Mac working tree 有未提交／未追蹤修改，沒有建立 WIP commit，也沒有
刪除 Mac checkout；這些修改仍保留在 Mac，待人工挑選後再 commit。

2026-09-09 閘道實測：Mac → Scout `status` 完整同步成功，回報 41 個 tracked 修改與
15 個 untracked 候選，未建立 commit；Mac `.git`（約 448 MB）已移除，專案檔案仍保留。
移除後再次執行 `status` 成功。
