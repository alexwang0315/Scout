# Permission 教材工具與待拍草稿

本目錄目前只有教學工具與待拍 metadata，沒有發布版 index.html、PDF、圖片或新 capture receipt。
原教材保存在 Scout TASK/repo；這份新增整合不搬移或冒用其歷史圖片。

38 頁與 113 個數字目標完整保留在 drafts/revision5-current-9099，
另有 Completed GPX 身份拒收／恢復的 4 個待拍補充目標。來源盤點只作歷史規劃參考。
root 已回報 Chrome 恢復，但最終服務 UI 尚未凍結；current 捕捉數仍為 0。

操作清單：
drafts/revision5-current-9099/capture-preparation/capture-worklist.json。
先使用同目錄唯讀 inspector，依真實 UI 與工作表操作，再由 root 擷取原始畫面和 DOM receipt。
缺少 Saved／Planned／Recorded 或人工核可時保留待驗，不建立假狀態。

build.py／verify_ui_sync.py 的既有 freshness、38 頁逐步標記、圖片幾何與產物 checks 全保留；
verify-browser.js 只把可改名的章節標題改為既有唯一 ID。全部原 layout／dialog／keyboard／autoplay／offline／PDF checks 保留。
目前沒有可建置的 slides.json，這是阻止把待拍草稿當正式產物的明確狀態。

工具測試與整合收據：Scout recovery-20260914/guide-capture-preparation-v3。
test_ui_dependencies.py 與 test_capture_scaling.py 保留原有測試，依賴原歷史 fixture：
驗證時只在隔離副本放入保留的 slides.json、capture-sources.json 與兩張原始 asset。
不可把那些 fixture 複製到本目錄當成新截圖。
capture-preparation/test-capture-preparation-tools.js 以 SCOUT_GUIDE_BASELINE_ROOT 明確指定舊 metadata fixture；
可用 SCOUT_GUIDE_TOOL_TEST_REPORT 指定 Scout 磁碟的測試報告位置。

真正交付前依 UI-MAINTENANCE.md 完成當前服務/工作區/八檔來源、全部原始截圖、
每頁標記與手機/桌面/放大視窗/離線/PDF 檢查。所有適用結果通過才能更新交付狀態。
