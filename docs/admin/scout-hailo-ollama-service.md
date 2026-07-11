# Scout Hailo Ollama 5.3 User Service

這份 runbook 將 Raspberry Pi 5 + AI HAT+ 2 的 Hailo Ollama 變成 Scout
使用者層常駐服務。服務只綁定 `127.0.0.1:8000`，供同機 Scout AI fallback
使用，不直接暴露到 field LAN。

這個服務是本地 inference provider，不是 safety authority。固定邊界為：

- `phase1_safety_decision_change_allowed=false`
- `remote_outbound_allowed=false`
- 模型輸出只能成為 command candidate。
- native `tools` request field 在 Hailo Ollama 5.3 仍可能回 HTTP 500。
- 工具候選必須再經 Scout deterministic allowlist、confirmation 與 expiry。

## Preflight

先確認 runtime、driver 與 firmware 都是 5.3：

```bash
dpkg-query -W hailort hailort-pcie-driver hailo-gen-ai-model-zoo
hailortcli fw-control identify
```

預期包含 `Firmware Version: 5.3.0` 與 `Device Architecture: HAILO10H`。

確認 user manager 可在沒有登入 shell 時維持：

```bash
loginctl show-user alexwang0315 -p Linger
```

預期為 `Linger=yes`。若不是，operator 必須另外執行：

```bash
sudo loginctl enable-linger alexwang0315
```

## Deploy

從 Scout repo 執行：

```bash
install -d -m 0755 ~/.config/systemd/user
install -m 0644 deploy/systemd/scout-hailo-ollama.service \
  ~/.config/systemd/user/scout-hailo-ollama.service
systemctl --user daemon-reload
systemctl --user enable --now scout-hailo-ollama.service
```

若先前有手動啟動的 `/usr/bin/hailo-ollama`，先停止該程序，避免 port
`8000` 衝突，再啟動 service。

## Health Check

```bash
systemctl --user is-active scout-hailo-ollama.service
systemctl --user status scout-hailo-ollama.service --no-pager
curl --fail --silent http://127.0.0.1:8000/api/tags
journalctl --user -u scout-hailo-ollama.service -n 100 --no-pager
```

模型檔預設寫入：

```text
~/.local/share/hailo-ollama/models/
```

Mac 若需要人工測試，使用 SSH tunnel，不修改 service listener：

```bash
ssh -N -L 18000:127.0.0.1:8000 alexwang0315@scout.local
curl --fail --silent http://127.0.0.1:18000/api/tags
```

Mac dashboard 的 `configs/assistant-models.dashboard-aihat2.json` 使用上述
`127.0.0.1:18000` tunnel。若 Scout admin 跑在同機 Docker container，provider
可使用 `http://host.docker.internal:8000`，但 compose 必須明確配置 host
gateway；這個名稱只代表同機 host bridge，不得換成 field LAN 或任意遠端 URL。

## Restart Verification

不需要重開機即可先驗證 recovery：

```bash
systemctl --user restart scout-hailo-ollama.service
systemctl --user is-active scout-hailo-ollama.service
curl --fail --silent http://127.0.0.1:8000/api/tags
```

完成一次實機 reboot 後，再重跑相同 health check，才算 boot recovery 已驗證。

## Rollback

```bash
systemctl --user disable --now scout-hailo-ollama.service
rm -f ~/.config/systemd/user/scout-hailo-ollama.service
systemctl --user daemon-reload
```

Rollback 只移除常駐服務，不刪除模型、HailoRT、driver、firmware 或 Scout
evidence。
