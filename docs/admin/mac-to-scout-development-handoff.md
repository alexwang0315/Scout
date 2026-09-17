# Mac → Scout 開發交接

這份流程把「程式碼同步」、「大型旅程資料交接」與「正式 runtime 部署」分開。
日常開發直接使用 Scout 上的健康 Git checkout；不要把 Mac checkout 整包 `rsync`
到 Scout，尤其不要複製 `.git`，因為 worktree pointer 會保留 `/Users/...` 的 Mac
路徑而在 Linux 上失效。

## 目錄角色

| 路徑 | 用途 | 日常開發是否直接修改 |
|---|---|---|
| `/home/alexwang0315/work/scout-fusion` | Scout 上的 Git 開發 checkout | 是 |
| `/home/alexwang0315/scout-ai-os-hardware-current` | 已封裝的 hardware/deployment artifact | 否 |
| `/home/alexwang0315/scout-fusion-runtime` | 正式 Docker runtime/rollback 區 | 否 |
| `/data/scout` | 路線、raster、runtime evidence 與 operator config | 依既有 handoff/runbook |

本流程啟動的是開發 API `:9120`，不會取代正式 runtime `:9099`，也不會啟用
hardware control、outbound send 或 Phase 1 safety mutation。

已 commit 的程式碼若要兩端定期同步，參考
[`periodic-git-sync.md`](periodic-git-sync.md)；Mac 不必開啟遠端登入。

## 1. 程式碼：Mac 遷移到 Scout 本機 Git server

Git server 現在放在 Scout 的
`alexwang0315@scout.local:/home/alexwang0315/git/scout-fusion.git`。
第一次遷移請依 [`scout-local-git-server.md`](scout-local-git-server.md) 執行；工具會
推送 Mac 本機所有 branches/tags，並將目前 branch 的 `git push` 預設送到 Scout。
先在 Mac 完成 review、commit，再 push：

```bash
cd /Users/alexwang0315/scout-fusion
git status --short
git add ...
git commit -m "..."
git push
```

再登入 Scout，確認 bare server 已收到 branch；Scout 的開發 checkout 仍須在 dirty
工作整理完成後才可 fast-forward：

```bash
ssh alexwang0315@scout.local
cd /home/alexwang0315/work/scout-fusion
git fetch scout-local --tags
git ls-remote scout-local
```

不要把 Mac `.git` 整包 `rsync` 到 Scout，也不要在 Scout dirty checkout 上直接
reset 或 force-update；若兩邊歷史不同，先人工決定要保留哪個 commit。Mac checkout
完全移除後，請改用 VS Code Remote SSH 或直接在 Scout checkout 上編輯。

## 2. 從 Scout 的 source checkout 啟動

第一次可建立獨立開發環境：

```bash
cd /home/alexwang0315/work/scout-fusion
python3 -m venv .venv-scout-dev
.venv-scout-dev/bin/pip install -e .
```

先載入真實 `scout.main:app` 並驗證必要 routes，不啟動服務或讀取 token：

```bash
PYTHONPATH=src:. .venv-scout-dev/bin/python -m scout.cli.dev_server \
  --check --host 0.0.0.0 --port 9120
```

回傳 `status=ready` 後再啟動：

```bash
PYTHONPATH=src:. .venv-scout-dev/bin/python -m scout.cli.dev_server \
  --host 0.0.0.0 --port 9120 --reload
```

開發 CLI 預設使用隔離的 `:memory:` SQLite，不會碰正式資料。若開發 session
需要跨重啟保留狀態，請明確加入例如
`--database-path /data/scout/dev/scout-ai-os.sqlite`；這會寫入指定檔案，先確認
該路徑不是正式 runtime database。

Mac 端連線：

```bash
./venv/bin/scout-ai-os-mac-chat --target-url http://scout.local:9120
```

## 3. 大型路線、GeoTIFF/KMZ 與離線地圖

這些 artifact 不進 Git。仍在 Mac 完成 raster build，再只把產生的 handoff
package 同步到 `/data/scout`：

```bash
rsync -a /tmp/scout-offline-map-handoff/chilai_nanhua_day1/ \
  alexwang0315@scout.local:/data/scout/
```

完整 manifest 與驗證流程見
[`docs/specs/pretrip-layer-preparation.md`](../specs/pretrip-layer-preparation.md)。

## 4. GPT-6 Astra：先準備、取得權限後切換

Scout 現在接受以下等價名稱，並固定透過 OpenAI Responses API：

```text
gpt-6-astra
openai:gpt-6-astra
openai-responses:gpt-6-astra
```

GPT-6 Astra 的工具呼叫使用 Responses API；Scout 會移除該模型不支援的
`temperature`，並以 `reasoning_effort=low` 起步。這不會替帳號開通模型權限，
也不會讓 Codex Desktop 的模型選單自動出現 GPT-6。

### Codex Desktop / CLI 的 Astra 選項

Codex 的模型選單與 Scout 專案 runtime 是兩套設定。官方建議可用下列方式
啟動 Astra：

```bash
codex -m gpt-6-astra
```

截至 2026-09-07，這台 Scout 的 Codex CLI 是 `0.149.1`，本機 catalog 尚未列出
`gpt-6-astra`；官方 `0.153.4` changelog 明列修正 Astra 在 bundled model picker
的可見性。先更新 Codex Desktop/CLI，再開新 task 檢查模型選單。更新後仍看不到
時，原因通常是 rollout、登入方式、方案或 Enterprise workspace model policy；
專案內的 model alias 無法繞過這些帳號端限制。

複製範例到 operator 管理的位置，不要直接改動正式設定：

```bash
install -m 600 \
  configs/assistant-models.openai-gpt-6-astra.example.json \
  /data/scout/config/assistant-models.gpt-6-astra.json
```

在 secret store 或未追蹤的 `.env` 提供 `OPENAI_API_KEY`；不可把 token 寫進
JSON 或 commit。完成模型權限確認後，才由 operator 將
`SCOUT_AI_ASSISTANT_CONFIG_PATH` 指向新檔並重啟開發服務。設定保留 AI HAT+2
本機模型 fallback，且 `connect_on_startup=false`，避免未經確認就產生付費請求。

官方相容性依據：

- [GPT-6 Astra migration guide](https://developers.openai.com/api/docs/guides/latest-model)
- [GPT-6 Astra model page](https://developers.openai.com/api/docs/models/gpt-6-astra)
- [Codex models and rollout notes](https://developers.openai.com/codex/models)
- [Codex changelog](https://developers.openai.com/codex/changelog)

## 5. 正式部署邊界

上述只是 development handoff。要替換 `scout-runtime`、寫入 live secret、切換
`:9099`、啟用真實硬體或 outbound transport，必須另走
[`scout-machine-step1-deployment-runbook.md`](scout-machine-step1-deployment-runbook.md)
並取得 operator 明確核准。
