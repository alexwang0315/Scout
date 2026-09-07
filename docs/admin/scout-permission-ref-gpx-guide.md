# Permission：Ref. GPX 歷史復刻操作

2026-09-07；指定 workspace：`dongqing_batongguan_historic_trail_newImport`。

[開啟這份資料的 Permission 頁面](http://127.0.0.1:9099/admin/dashboard?projectId=dongqing_batongguan_historic_trail_newImport#outdoor-permission)

## 此模式的正確行為

**Generate from Ref. GPX 複製參考行程已記錄的每日起終點、路徑、停留及 CP 時間，不需要再指定每日終點。**
先前使用 480 分鐘重新切成六天，以及要求補上「產生前指定終點」的說明均已更正；舊六天候選保留供追溯，請重新產生九天歷史復刻候選。

這份資料可還原 **9 天、89.827 km、219 筆 CP（218 筆有精確時間、1 筆缺時）及 32 處推定停留**。
每日起終點來自同一條整理後的 primary GPX；不必重做 Import 或地圖準備。產生結果不會混用 Chilai workspace。

## 如何操作

1. 開啟上方連結，等待左側顯示 `dongqing_batongguan_historic_trail_newImport`，進入 **Permission → Baseline**。
2. 選 **Generate from Ref. GPX**。Reference trip 保持 **Reference GPX with reviewed route axis**。
3. 按 **Preview source**，確認 **Copied historical itinerary** 顯示 9 recorded days、218 / 219 CP clocks、32 inferred stops。此步不寫檔。
4. 按 **Generate typed draft**。檢查 D1–D9 的 Rudy 地圖、起終點座標、歷史出發／抵達時間。展開 **Day route, ETA & evidence**，查看每一天所有 CP 的通過時間、上一 CP 至此的距離／耗時／平均速度、抵達當日終點的剩餘時間，以及停留座標與時段。此步也不寫檔。
5. 按 **Save candidate version**，在確認視窗按 **Confirm · create candidate version**。候選保存後應顯示 **ready for explicit review**。
6. 在 **Quick review** 閱讀並勾選：採用這份歷史每日行程、了解記錄缺口與推定停留、了解另需 Safety / Emergency 審查的候選。這是審閱已複製的內容，沒有重新填寫終點的步驟。
7. **Accept reviewed baseline** 此時會啟用。按下後會開啟最後確認視窗，列出精確的候選 hash 與審閱範圍；確認採用才送出接受。若只想查看，可按 **Cancel**。
8. 接受後若顯示 projection stale，按 **Rebuild from reviewed baseline**，再按 **Confirm · rebuild bounded projection**，將該版本綁入 Permission 的計畫時間與規則。這是獨立步驟；規則調整仍為 review_only，出發及 Safety 決策仍有各自流程。

重新 Preview 或 Generate 會清除目前畫面的舊版本與勾選狀態。請重新 Save／Review，避免誤接受上一份候選。

## 這份參考記錄的九天

時區為 Asia/Taipei。里程是同一 GPX 的累積路徑距離；「全日耗時」含停留與記錄間隙，並非純行走時間或 p75。

| 日 | 起點 → 終點累積里程 | 歷史出發 → 抵達 | 全日耗時（時:分:秒） | CP 筆數 | 推定停留 |
| --- | --- | --- | --- | ---: | ---: |
| D1 | 0.000 → 17.330 km | 05:36:20 → 16:20:20 | 10:44:00 | 41 | 4 |
| D2 | 17.350 → 37.934 km | 04:48:38 → 16:18:17 | 11:29:39 | 45 | 3 |
| D3 | 37.942 → 43.434 km | 05:48:58 → 11:18:30 | 05:29:32 | 14 | 2 |
| D4 | 43.471 → 52.392 km | 05:50:12 → 15:43:36 | 09:53:24 | 24 | 5 |
| D5 | 52.397 → 58.068 km | 06:27:41 → 14:04:38 | 07:36:57 | 17 | 5 |
| D6 | 58.087 → 63.529 km | 05:57:51 → 12:36:59 | 06:39:08 | 12 | 2 |
| D7 | 63.544 → 70.325 km | 06:22:16 → 13:46:14 | 07:23:58 | 18 | 5 |
| D8 | 70.332 → 76.884 km | 06:15:34 → 14:23:08 | 08:07:34 | 19 | 5 |
| D9 | 76.929 → 89.827 km | 06:11:08 → 16:12:57 | 10:01:49 | 29 | 1 |

- 八處跨夜記錄間隙保留原始前日終點與次日起點，不把它們移到同一座標，也不把跨夜時數算入白天的休息。
- `cp.177`（D9，約 88.503 km）缺少時間；相關耗時／速度顯示 unknown，不補 0、不插值。另有 D6 與 D9 的缺時點範圍。
- 32 處停留是從同一整理後 GPX 的近距離、低位移觀測重建，標示 inferred／derived。原始檔未提供每一處的休息或營地名稱，因此畫面使用座標與里程定位，不捏造命名或休息意圖。
- 舊休息候選混有跨年份的大幅錯誤時長，本模式不直接複製那些值。CP 區間平均速度包含區間內停留，不能讀成純移動速度。
- 1 項反向返回候選仍待 Safety / Emergency 審查；這不阻止審閱歷史行程本身。

## 接受前的正常狀態

未保存候選，或尚未完成該版本的 Quick review 時，Accept 仍會停用；這是正常的版本審閱流程。**九天歷史終點的來源已綁定，不再因缺少 `day_end_inputs` 被擋。**

頁面上方若仍顯示 `Permission bootstrap needs itinerary review` 或 `ESCALATE`，表示目前啟用的 Permission projection 尚是舊 bootstrap；新草稿需依序 Save → Review → Accept → Rebuild，才會成為已選 baseline。這個提示不代表九天草稿或 Rudy 產生失敗。

本模式保留歷史記錄，不等同驗證今日可通行、可住宿或出發獲准。

## 驗證紀錄

**WORKING PROTOTYPE**：已在指定 workspace 的真實頁面完成 Preview、Generate、九天明細、Save、Quick review、啟用 Accept 與開啟／取消確認視窗。最後一次保存版本為 `version.15f1d78018a8af8e`，目前留在頁面供使用者審閱，測試勾選已清除。

- 九張 Rudy PNG 全部 HTTP 200；402 張底圖快取檔 hash 不變。
- 畫面全部 219 筆 CP 通過時間與保存的來源逐筆一致；缺時欄位保持 unknown。
- 已修正長行程頁面的確認視窗落到畫面外問題；Accept、Cancel 都已確認在可視範圍內且可操作。
- 61 項相關測試通過，包含隔離 fixture 的完整 Save → Accept → Rebuild，以及來源變更、偽造終點／CP 時間／耗時的拒絕測試。
- pnpm lint、typecheck、test、Python Ruff、33 層契約與 Navigation report-only guard 已完成。
- 為驗證修復前後的確認視窗，本輪保存兩份九天候選；保留既有版本與十份來源檔。未替使用者送出真實 Accept／Rebuild，未新增接受收據。

來源稽核、每日完整內容、HTTP 與實際頁面操作證據位於
`artifacts/permission-ref-gpx-reconstruction-20260907/`。

工作狀態與實測結果以該目錄的 `verification.json` 為準。本次未提交或推送變更。
