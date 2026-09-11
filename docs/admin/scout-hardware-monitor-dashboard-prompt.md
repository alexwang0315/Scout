# 可直接交給 Scout Dashboard 的實作提示詞

```text
請在現有 Scout Dashboard 實作「硬體監控」UI，接上已完成的 Scout Hardware Monitor API。
請直接完成可操作的 UI、資料接線與實測。沿用現有框架、元件及視覺風格，使用繁體中文。

先讀目前 checkout 的 AGENTS.md，以及：
/home/alexwang0315/work/scout-fusion/docs/admin/scout-hardware-monitor-api.md
/home/alexwang0315/work/scout-fusion/scout_hardware_monitor_api.py
完整欄位契約可從已運作的 http://127.0.0.1:9151/openapi.json 取得。
已有可運作的獨立總覽頁 http://127.0.0.1:9151/monitor，可參考其資料接線與互動。
9151 API、採樣器與 timer 已配置隨 Scout 開機啟動，請沿用這個埠。

API 路徑：
GET /api/v1/hardware-monitor/status
GET /api/v1/hardware-monitor/history?limit=60
GET /api/v1/hardware-monitor/events?limit=50

先確認 Dashboard 後端跑在 Scout、Mac 還是容器。Scout 主機的 upstream 是
http://127.0.0.1:9151；Mac 目前也有同埠的暫時 SSH forward；容器 localhost 不等於 Scout。
瀏覽器請 fetch 同源相對路徑，由後端代理固定 API routes，沿用既有登入／權限與短 timeout。
若 FastAPI Dashboard 與採樣器在同一主機，可以掛載 create_hardware_monitor_router。
API 的監控 GET 不得觸發採樣、通知、設定修改、重啟或任何硬體控制。

UI 要有：
1. 頁首顯示整體狀態、最後採樣時間（Asia/Taipei）、距今多久與手動重新讀取按鈕。
2. 電池卡：百分比、充電／放電／待機、功率；詳情可看電壓、電流、四芯電壓與 5V 供電。
3. 記憶體卡：使用比例、已用／總量／可用 GiB，以及 Swap。
4. 磁碟卡或列表：所有 disks[] 的掛載點、已用比例、剩餘／總量 GiB、inode、唯讀狀態。
5. CPU／散熱卡：CPU 使用率、1/5/15 分鐘負載、CPU 與各 NVMe 溫度、風扇 RPM、開機時間。
6. 最近採樣趨勢：電池、記憶體、CPU／NVMe 溫度；使用真實 captured_at 作 X 軸。
7. 目前告警及最近狀態變更事件，顯示嚴重度與可採取的下一步。
8. data.inventory.sections：Wi-Fi／Ethernet 連線、SSID／訊號／IP，藍牙控制器與已連線裝置，
   USB／PCIe 裝置與驅動、I²C 匯流排與已登錄裝置、GPIO 方向／consumer、UART 節點。
   每類可展開查看 properties；GPIO 可展開 lines，value=null 表示未採樣。
   section.status=ok 只表示資訊可讀，裝置的實際連線／電源狀態看 item.state。

資料來自 status 回應的 data.power／memory／disks／sensors／alerts／thresholds。
history.items[] 與 data 共用 Snapshot schema；events.items[] 是 {captured_at, events: string[]}。
以頂層 status 和 freshness 判定現在是否正常，不可只看 data.status。
每 60 秒重新讀取；切換頁面取消 pending request 與 timer，避免重複輪詢；手動刷新只讀 API。

必須正確處理：
- 首次 loading、API 斷線、data=null、503 的 JSON body、空歷史／空事件、history.status=partial。
- 超過 150 秒會回 HTTP 503 / status=stale，仍有最後 data；顯示「資料已過期」及最後時間，
  保留舊數值作參考但不畫成目前正常。斷線時亦明確標記連線失敗。
- null／缺失顯示「未知」或「—」，不可補零；歷史缺口不補造數據。
- GiB = bytes / 1024^3；battery_power_w 正值充電、負值放電，顯示絕對值與方向。
- 同名 NVMe 感測器以 source 區分；風扇 0 RPM 與歷史欠壓旗標不能直接當成目前故障。
- inventory=null 是舊採樣未包含清單；I²C 未列出不等於未接上。不可加入主動位址掃描、
  藍牙配對／探索或 GPIO 電位讀寫；裝置名稱與 SSID 以純文字渲染。
- 告警與門檻採後端值；用文字／圖示加顏色表達，兼顧桌面、手機及鍵盤操作。

保留現有 Dashboard 與未提交修改；只做這個監控頁所需的接線與 UI，不改 Navigation/GIS。
依 AGENTS.md 執行適用檢查，若 freeze guard 缺少就如實記錄，不建立替代 baseline。
用正常、warning、critical、stale、unavailable、503、斷線、空資料情境做針對性驗證，
再連真實 API 完成一次瀏覽器 smoke。示範數據只能用於測試，正常畫面要接真實 API。
完成後提交這次變更的 Git commit，提供驗證結果、Mac 可開啟的 UI URL 與 Chrome 開啟命令；
既有 Scout-to-Mac SSH 可用時依使用者偏好主動開啟。不要 push、merge 或公開部署。
```
