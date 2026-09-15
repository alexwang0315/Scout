# Revision 5 — 待最終 UI 與真實 9099 畫面

這是 38 頁／113 目標的待拍草稿，image 均為 null，markers 為空，buildable=false。
capture-queue.json 的八檔來源盤點保留原日期與 SHA，不能當成最終服務或新擷取證明。
人工審查、Saved/Planned/Recorded 真實資料及地圖逐頁狀態要求保留。

capture-preparation/capture-worklist.json 提供逐頁入口、控制項順序、步驟 locator、
27 個可合併候選組與 Completed GPX 4 目標補充；合併尚未確認。
其 integration_readiness 明確記載 final_ui_source_hashes=null、capture_receipts=[]。
root 回報 Chrome 已重新連線；仍要等最終 UI freeze，才依真實服務逐頁擷取。

collect-target-rects.js 為唯讀 DOM helper；iframe 座標加上實際 border，
仍須與同次原始 screenshot 逐一目視核對。實際 screenshot 可回傳 JPEG，
不可由要求的 .png 名稱推定原 bytes 的格式。詳见 UI-MAINTENANCE.md。

這個草稿不得直接取代發布版 slides/index/PDF。當前畫面、來源、實際資料或人工核可
尚未滿足時，保持待拍／待驗，不用歷史截圖或假資料填補。
