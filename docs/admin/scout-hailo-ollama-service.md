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
journalctl --user-unit scout-hailo-ollama.service -n 100 --no-pager
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
`127.0.0.1:18000` tunnel。Hailo 服務只綁 host loopback 時，一般 Docker bridge
上的 `host.docker.internal` **無法**連到 `127.0.0.1:8000`。容器驗證應使用一次性
`--network host` smoke，或在產品化時加入經審核的 local proxy/socket；不可為了
容器連線而把 Hailo listener 改成 field LAN 可達。

Hailo Ollama 5.3 的 OpenAI-compatible response 會把 `created` 回成奈秒 Unix
timestamp。Pydantic AI 2.22 預期秒，因此 Scout 的 `hailo:` model adapter 只在
本地 Hailo 路徑建立 response copy，將毫秒、微秒或奈秒值除到 Unix 秒範圍後再
交給 Pydantic AI；OpenRouter、NVIDIA 與 OpenAI provider 不使用此修正。

## Restart Verification

不需要重開機即可先驗證 recovery：

```bash
systemctl --user restart scout-hailo-ollama.service
systemctl --user is-active scout-hailo-ollama.service
curl --fail --silent http://127.0.0.1:8000/api/tags
```

完成一次實機 reboot 後，再重跑相同 health check，才算 boot recovery 已驗證。

## Verified Boot Recovery

2026-07-11 在 Scout Pi 5 + AI HAT+ 2 實機完成 reboot recovery：

- boot ID 在 reboot 後改變；
- `Linger=yes`；
- service 在 uptime 約 60 秒時已為 `enabled`、`active (running)`；
- unit SHA256 與 repo 相同；
- listener 仍只綁定 `127.0.0.1:8000`；
- HailoRT、PCIe driver、model zoo 與 firmware 均為 5.3.0；
- `qwen3:1.7b` post-reboot inference 回傳 HTTP 200；
- `NRestarts=0`，錯誤後 inference 仍可成功。

Hailo Ollama 5.3 的 `/api/chat` 對 message content 中的 LF、CR、tab 等控制
字元有額外相容性限制。Scout Hailo client 必須在 transport boundary 將 C0/C1
control characters 正規化成空格，仍使用 `json.dumps` 產生 JSON。2026-07-11 的
multiline live smoke 與 dashboard `/assistant/query` smoke 都沒有增加 journal
中的 `Failed to render prompt from JSON strings` 計數。

AI workload 後曾出現 `get_throttled=0x50000`，表示本次開機曾發生低電壓與
throttling，但檢查當下低位元為 0。這不影響 boot recovery 的 PASS 判定，仍需
在 UPS/供電 baseline 中追蹤。

## Rollback

```bash
systemctl --user disable --now scout-hailo-ollama.service
rm -f ~/.config/systemd/user/scout-hailo-ollama.service
systemctl --user daemon-reload
```

Rollback 只移除常駐服務，不刪除模型、HailoRT、driver、firmware 或 Scout
evidence。
