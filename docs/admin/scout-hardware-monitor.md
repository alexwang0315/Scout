# Scout 硬體背景監控

Construction Mode：獨立的每分鐘本機監控，使用 Python 標準函式庫及 user systemd timer。
使用者於 2026-09-11 明確選擇持續背景監控與異常提示。

Dashboard 可透過新增的唯讀 HTTP API 讀取結果：
[`scout-hardware-monitor-api.md`](scout-hardware-monitor-api.md)。
可直接交給 UI 實作任務的提示詞：
[`scout-hardware-monitor-dashboard-prompt.md`](scout-hardware-monitor-dashboard-prompt.md)。

## 讀取範圍

- 電池電量、充放電、電池功率、四芯電壓與 5V 供電。
- 記憶體使用量、可用量、Swap 使用量。
- 已掛載本機磁碟的總量、可用容量、使用率、inode、系統磁碟唯讀狀態。
- CPU／NVMe 溫度、風扇轉速、1/5/15 分鐘負載、兩次採樣間 CPU 使用率與開機時間。
- 目前與本次開機歷史的欠壓／降頻旗標；歷史旗標不當成當下故障。

UPS 資料沿用 `/home/alexwang0315/scout-power-path-monitor/power-path-telemetry.jsonl`。
每次只讀最多 64 KiB 的檔案尾端，15 秒以上的舊資料及錯誤資料會發出感測告警。
不存取 I2C、不控制 OLED／風扇／充電、不關機或修復系統，也不改動既有 UPS 服務。
既有 UPS 的大容量歷史檔案保持原樣。

## 設定門檻

這些是本次監控的操作門檻，不代表廠商保證的安全界限。

| 指標 | 警告 | 嚴重 |
| --- | --- | --- |
| 電池 | ≤20% | ≤10% |
| 記憶體使用率 | ≥90% | ≥95% |
| 磁碟／inode 使用率 | ≥85% | ≥95% |
| CPU 溫度 | ≥75°C | ≥85°C |
| NVMe 溫度 | ≥65°C | ≥75°C |
| 電芯 | — | <3.15V |
| 5V 電壓 | <4.8V | 目前有欠壓／降頻旗標 |

記憶體使用率採用 `MemTotal - MemAvailable`，避免將可回收快取誤報成不足。
磁碟使用率排除 ext4 保留空間，與 `df` 的分母一致。5 分鐘負載超過 CPU 數量的
1.5 倍也會警告。低溫時風扇 0 RPM 僅記錄，不單獨判定異常。

## 安裝及查看

```bash
python3 scripts/install-scout-hardware-monitor.py --notify-mac
systemctl --user list-timers scout-hardware-monitor.timer
cat ~/.local/state/scout-hardware-monitor/status.txt
watch -n 5 cat ~/.local/state/scout-hardware-monitor/status.txt
journalctl --user -u scout-hardware-monitor.service -n 20
```

安裝程式把獨立程式複製到 `~/.local/lib/scout-hardware-monitor/monitor.py`，
排程不依賴開發 checkout 的後續變化。已有同名安裝時不覆寫。
`--render-only DIRECTORY` 可先產生可審查的 unit 檔，不安裝或啟動。
監控的使用者需已啟用 linger 才能在登出後繼續執行，部署時以
`loginctl show-user alexwang0315 -p Linger` 驗證。此安裝器不改全域登入政策。

`status.json` 與 `status.txt` 是最新快照，包含採樣時間；檢查快照時務必查看時間。
`history.jsonl`、`events.jsonl` 各在 10 MiB 輪替，保留目前檔案及三份備份。
本機紀錄以私有權限建立，原子更新最新快照，鎖定避免重疊採樣。

## 通知

異常出現、嚴重度改變、恢復、充放電改變或重新開機時，向擁有者的 Mac 提出
macOS 通知請求。狀態相同不重複通知。這不是 Codex 排程，也不會自動在 Codex
任務內發訊息。

使用既有 Scout-to-Mac 專用 SSH identity、嚴格 host key 驗證與固定 AppleScript。
文字以獨立資料參數傳入，無任意命令入口。沒有郵件、Slack 或第三方推播服務。
Mac 離線時本機監控繼續，通知暫存並每五分鐘重試；新狀態變化可提前重試。
待送通知最多保留最近 100 筆與更早筆數，事件另記於輪替紀錄。
通知成功只表示 macOS 接受請求；橫幅顯示受 macOS 通知權限與專注模式影響。

## 暫停及回復

```bash
systemctl --user disable --now scout-hardware-monitor.timer
systemctl --user stop scout-hardware-monitor.service
# 恢復
systemctl --user enable --now scout-hardware-monitor.timer
```

暫停僅影響此監控，既有 UPS 觀測器與 Scout runtime 持續執行。

## 驗證及後續工作

執行 `./venv/bin/python -m pytest tests/test_scout_hardware_monitor.py`，以及真實 Scout
的 CLI 採樣、實際 timer 觸發、Mac 通知請求。測試使用固定感測資料或模擬，
不讀取真實 `.env` 或操控硬體。

2026-09-11 部署驗證（Asia/Taipei）：

- 13 項針對性測試通過；systemd unit 靜態驗證通過。
- 08:51:03 真實採樣：電池 80%／充電 17.96W，記憶體 1.26/7.87 GiB，
  主磁碟可用 710.53 GiB，CPU 46.9°C，欠壓／降頻旗標 `0x0`，無告警。
- 該次 service 成功結束；systemd 計量記憶體峰值 11.27 MiB、CPU 時間約 81 ms。
- 08:51:04 Mac 接受啟用通知請求，沒有宣稱已目視確認橫幅。
  收據：`~/.local/state/scout-hardware-monitor/notification-setup-receipt.json`。
- 已確認 `Linger=yes`，排程開機後可繼續運作；安裝副本與原始碼 SHA-256 一致。
- 08:52:00 已由 timer 自動觸發且成功結束，下一次為 08:53:00。累計三次真實採樣，
  最新電池 81%／充電中，狀態 `ok`、通知 `quiet`、待送數 0；無告警時保持安靜。
- 安全檢視涵蓋固定 SSH 目的地／腳本、參數轉義、嚴格 host key、私有狀態檔權限、
  原子寫入及紀錄輪替。沒有新增套件或修改既有 runtime。

未產品化：Scout 完全停電／關機時無法由自身發出離線通知；要偵測此情況需另設
Mac 側的存活監控。SSD 的 SMART 壽命／媒體錯誤尚未收集。告警門檻尚無防抖，
跨門檻反覆波動會按狀態變化通知。沒有修改 Dashboard、Navigation 或 GIS，
相關瀏覽器與圖層檢查不適用。
