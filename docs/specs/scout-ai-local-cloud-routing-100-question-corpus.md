# Scout AI local/cloud routing 100 題 corpus

這是可供 JEV advisory routing 的題庫：70 題 local 使用短小固定答案，30 題 cloud 需要 web search、workspace/GIS tool 或即時證據。JEV 不得把 cloud-required 題降級成本地模型。所有輸出仍是 `candidate_only=true`，不是 runtime safety truth。

## Routing contract

- local：`exact` / `choice` / `structured`，無 required tool、無外部資料依賴。
- cloud：`evidence_grounded`，必須附 source refs、freshness 或 unknowns。
- JEV 可以把 local 題 advisory 升級到 cloud，但不能把 cloud-required 題降成 local。JEV、LLM 與模型輸出都不是硬體或安全 authority。

## 題目

| ID | route | category | question | standard answer / cloud reason |
|---|---|---|---|---|
| `LOCAL-001` | `local` | `arithmetic` | 已知路段 A 為 3.5 公里、B 為 2.25 公里，合計幾公里？ | 5.75 公里 |
| `LOCAL-002` | `local` | `unit_conversion` | 把 2 小時 30 分鐘換算成分鐘，答案是多少？ | 150 分鐘 |
| `LOCAL-003` | `local` | `unit_conversion` | 將 4,500 公尺換算成公里，保留小數兩位。 | 4.50 公里 |
| `LOCAL-004` | `local` | `arithmetic` | 每小時走 3 公里，走 2 小時 20 分鐘的距離是多少？ | 7 公里 |
| `LOCAL-005` | `local` | `arithmetic` | 起點海拔 420 公尺、終點海拔 1,020 公尺，爬升多少？ | 600 公尺 |
| `LOCAL-006` | `local` | `arithmetic` | 四段距離分別為 1.2、0.8、2.5、1.5 公里，總長是多少？ | 6.0 公里 |
| `LOCAL-007` | `local` | `arithmetic` | 剩餘 9 公里，平均速度 3 公里／小時，估計需要幾小時？ | 3 小時 |
| `LOCAL-008` | `local` | `arithmetic` | 將 75 分鐘加上 1 小時 10 分鐘，總共幾分鐘？ | 145 分鐘 |
| `LOCAL-009` | `local` | `arithmetic` | 里程從 12.4 公里增加到 15.1 公里，增加多少？ | 2.7 公里 |
| `LOCAL-010` | `local` | `arithmetic` | 一箱有 24 瓶水，分給 6 人且平均分配，每人幾瓶？ | 4 瓶 |
| `LOCAL-011` | `local` | `arithmetic` | 海拔 1,250 公尺下降到 980 公尺，下降多少？ | 270 公尺 |
| `LOCAL-012` | `local` | `arithmetic` | 路線全長 18 公里，已走 7.5 公里，剩餘多少？ | 10.5 公里 |
| `LOCAL-013` | `local` | `arithmetic` | 三個檢查點間距為 2、3.5、1.5 公里，這三段合計多少？ | 7 公里 |
| `LOCAL-014` | `local` | `arithmetic` | 一個坡段長 800 公尺，來回一次，總距離是多少？ | 1,600 公尺 |
| `LOCAL-015` | `local` | `unit_conversion` | 把 0.75 公里換算成公尺。 | 750 公尺 |
| `LOCAL-016` | `local` | `structured_extraction` | 資料卡寫著 CP=12、MCP=4、休息點=3。CP 數是多少？ | 12 |
| `LOCAL-017` | `local` | `structured_extraction` | 資料卡寫著總長 21.4 km、爬升 860 m。總長是多少？ | 21.4 公里 |
| `LOCAL-018` | `local` | `structured_extraction` | 表格欄位為 route_name=東段、surface=土路、grade=12%。surface 的值是什麼？ | 土路 |
| `LOCAL-019` | `local` | `structured_extraction` | 紀錄為 start=08:10、break=00:20、finish=15:40。start 是幾點？ | 08:10 |
| `LOCAL-020` | `local` | `structured_extraction` | 清單依序是入口、溪溝、鞍部、終點。第三個項目是什麼？ | 鞍部 |
| `LOCAL-021` | `local` | `structured_extraction` | JSON 摘要為 {"status":"ready","count":8}。status 是什麼？ | ready |
| `LOCAL-022` | `local` | `structured_extraction` | 欄位 elevation_m=1,234、segment_id=S07。elevation_m 是多少？ | 1,234 公尺 |
| `LOCAL-023` | `local` | `structured_extraction` | 資料列的 weather_source 是 cwa，rain_probability_pct 是 40。來源是什麼？ | cwa |
| `LOCAL-024` | `local` | `structured_extraction` | 路線標籤為 northbound，方向欄位的值是什麼？ | northbound |
| `LOCAL-025` | `local` | `structured_extraction` | 檔案有 5 個候選點，其中第 2 個標記 requires_human_review=true。該標記值是什麼？ | true |
| `LOCAL-026` | `local` | `structured_extraction` | 一筆紀錄含有 source=survey、confidence=0.8。source 欄位內容是什麼？ | survey |
| `LOCAL-027` | `local` | `structured_extraction` | 表格的四欄是 id、name、distance_km、note；第三欄名稱是什麼？ | distance_km |
| `LOCAL-028` | `local` | `structured_extraction` | 訊息標籤為 [route, terrain, candidate]。第二個標籤是什麼？ | terrain |
| `LOCAL-029` | `local` | `structured_extraction` | 摘要寫著 freshness=stale、candidate_only=true。freshness 是什麼？ | stale |
| `LOCAL-030` | `local` | `structured_extraction` | 記錄為 {"temperature_c":18.5,"unit":"C"}。溫度數值是多少？ | 18.5°C |
| `LOCAL-031` | `local` | `comparison` | 已知 A=8、B=5。A 是否大於 B？只回答是或否。 | 是 |
| `LOCAL-032` | `local` | `comparison` | 已知路段長度 4 公里且上限為 5 公里，是否超過上限？只回答是或否。 | 否 |
| `LOCAL-033` | `local` | `boundary` | 若資料標記 stale，是否等同於資料為零？只回答是或否。 | 否 |
| `LOCAL-034` | `local` | `boundary` | 若欄位值為 null，是否可以直接回答為 0？只回答是或否。 | 否 |
| `LOCAL-035` | `local` | `boundary` | 若來源標為 candidate，是否等同於 runtime safety truth？只回答是或否。 | 否 |
| `LOCAL-036` | `local` | `boundary` | 若題目只給觀察值，能否直接宣稱造成觀察的原因？只回答是或否。 | 否 |
| `LOCAL-037` | `local` | `unit_discipline` | 若單位是毫米，能否不換算就當成公尺？只回答是或否。 | 否 |
| `LOCAL-038` | `local` | `evidence_boundary` | 若兩個資料來源數值不同，是否應保留衝突而不是任選一個？只回答是或否。 | 是 |
| `LOCAL-039` | `local` | `routing_boundary` | 若題目明確提供所有運算數字，是否需要 web search 才能計算？只回答是或否。 | 否 |
| `LOCAL-040` | `local` | `answer_contract` | 若答案契約要求 exact，回答時是否應加入未提供的推測背景？只回答是或否。 | 否 |
| `LOCAL-041` | `local` | `evidence_gap` | 標準答案要求列出三個欄位，但輸入只提供兩個，應填空白還是指出缺欄？ | 指出缺欄 |
| `LOCAL-042` | `local` | `unit_discipline` | 一個數字標記為 60%，它的單位應回答百分比還是毫米？ | 百分比 |
| `LOCAL-043` | `local` | `instruction_following` | 題目說只回答 CP 數；資料是 CP=9、MCP=2。應回答哪個數字？ | 9 |
| `LOCAL-044` | `local` | `label_mapping` | 若輸入明確寫著 eastbound，eastbound 的反方向是什麼？ | westbound |
| `LOCAL-045` | `local` | `comparison` | 三個值為 2、2、3；最大值是多少？ | 3 |
| `LOCAL-046` | `local` | `comparison` | 三個值為 2、2、3；最小值是多少？ | 2 |
| `LOCAL-047` | `local` | `comparison` | 若 A=10 且 B=10，A 與 B 的關係是什麼？ | 相等 |
| `LOCAL-048` | `local` | `counting` | 資料列有 4 個項目，其中 1 個是 null。非 null 項目有幾個？ | 3 個 |
| `LOCAL-049` | `local` | `translation` | 路段標記為 dry。dry 的中文是什麼？ | 乾燥 |
| `LOCAL-050` | `local` | `translation` | route_summary 的中文可翻成什麼？ | 路線摘要 |
| `LOCAL-051` | `local` | `safety_boundary` | 候選結果若 candidate_only=true，最安全的描述是「候選結果」還是「已核准結果」？ | 候選結果 |
| `LOCAL-052` | `local` | `evidence_boundary` | 未提供座標時，能否回答精確經緯度？只回答是或否。 | 否 |
| `LOCAL-053` | `local` | `source_boundary` | 未提供來源時，能否把一般常識寫成 workspace 事實？只回答是或否。 | 否 |
| `LOCAL-054` | `local` | `language` | 若題目要求繁體中文，是否應使用簡體中文作答？只回答是或否。 | 否 |
| `LOCAL-055` | `local` | `unit_conversion` | 若輸入是 90 分鐘，換算為幾小時幾分鐘？ | 1 小時 30 分鐘 |
| `LOCAL-056` | `local` | `unit_conversion` | 若 1 公里等於 1,000 公尺，6.2 公里等於多少公尺？ | 6,200 公尺 |
| `LOCAL-057` | `local` | `structured_interpretation` | 若坡度欄位為 0%，應回答有坡度還是無坡度？ | 無坡度 |
| `LOCAL-058` | `local` | `translation` | 若狀態欄位為 ready，ready 的中文是什麼？ | 就緒 |
| `LOCAL-059` | `local` | `answer_contract` | 若輸入只有一個明確答案，回答應選一個答案還是列出三個猜測？ | 選一個答案 |
| `LOCAL-060` | `local` | `arithmetic` | 若題目明確給出 20-8，結果是多少？ | 12 |
| `LOCAL-061` | `local` | `arithmetic` | 若題目明確給出 7×6，結果是多少？ | 42 |
| `LOCAL-062` | `local` | `arithmetic` | 若題目明確給出 81÷9，結果是多少？ | 9 |
| `LOCAL-063` | `local` | `arithmetic` | 若 5 個相同物品平均分給 5 人，每人幾個？ | 1 個 |
| `LOCAL-064` | `local` | `arithmetic` | 若原值 10、增加 25%，新值是多少？ | 12.5 |
| `LOCAL-065` | `local` | `arithmetic` | 若距離 10 公里中已完成 40%，完成距離是多少？ | 4 公里 |
| `LOCAL-066` | `local` | `ordering` | 若資料排序為低、中、高，第二個等級是什麼？ | 中 |
| `LOCAL-067` | `local` | `structured_extraction` | 若布林欄位為 false，中文應回答真還是假？ | 假 |
| `LOCAL-068` | `local` | `translation` | 若資料的 freshness 是 fresh，中文應回答新鮮、最新或過期？ | 最新 |
| `LOCAL-069` | `local` | `format` | 若答案只需回傳 JSON 欄位 answer，是否應加入 markdown code fence？只回答是或否。 | 否 |
| `LOCAL-070` | `local` | `routing_boundary` | 若問題不涉及即時資料、web 或工具，預設應選本地還是雲端？ | 本地 |
| `CLOUD-071` | `cloud` | `current_weather` | 查詢今天八通關古道沿線的即時降雨與有效時間。 | 需要即時天氣與 freshness/TTL。 |
| `CLOUD-072` | `cloud` | `current_daylight` | 查詢今天玉山區域的日落時間，並附官方來源。 | 需要當日資料與外部來源。 |
| `CLOUD-073` | `cloud` | `current_regulation` | 查詢目前官方是否對該路線發布封閉或管制公告。 | 需要最新官方公告。 |
| `CLOUD-074` | `cloud` | `forecast` | 查詢本週末路線所在地的天氣預報，並比較降雨機率與 QPF。 | 需要 web search、時間有效性與單位辨識。 |
| `CLOUD-075` | `cloud` | `warning` | 查詢最近一次官方山域警報，判斷是否涵蓋這條路線。 | 需要最新警報與路線範圍比對。 |
| `CLOUD-076` | `cloud` | `workspace_aggregate` | 從 workspace 找出所有 checkpoint candidate 並計算數量。 | 需要 workspace tool 讀取與聚合。 |
| `CLOUD-077` | `cloud` | `workspace_filter` | 從 workspace 找出 requires_human_review=true 的地形候選。 | 需要條件篩選 workspace artifact。 |
| `CLOUD-078` | `cloud` | `cross_artifact_join` | 把 route_summary 與 route_mileage_k_anchors 對照，找出里程不一致處。 | 需要跨 artifact join 與衝突證據。 |
| `CLOUD-079` | `cloud` | `spatial_join` | 找出與 route corridor 相交的風險段，並列出來源 artifact。 | 需要 GIS 空間相交查詢。 |
| `CLOUD-080` | `cloud` | `spatial_join` | 判斷某個候選崩塌點是否位於目前路線 buffer 內。 | 需要座標與空間 buffer 計算。 |
| `CLOUD-081` | `cloud` | `historical_research` | 查詢這個歷史地名的由來，並比較至少兩個可追溯來源。 | 需要外部歷史資料與來源比較。 |
| `CLOUD-082` | `cloud` | `cultural_research` | 查詢八通關古道某段的文化脈絡，區分已證實與推測內容。 | 需要研究資料與來源歸因。 |
| `CLOUD-083` | `cloud` | `permission` | 查詢目前官方入山或進入許可要求，並附有效日期。 | 法規與許可會變動，需查官方來源。 |
| `CLOUD-084` | `cloud` | `artifact_comparison` | 比較 workspace 中兩份 GPX 的總長與通過點，說明差異來源。 | 需要讀取並比較多個 artifact。 |
| `CLOUD-085` | `cloud` | `freshness` | 從 workspace 讀取最新 weather_daylight_evidence 並檢查是否過期。 | 需要讀取 timestamp、valid_to 與 TTL。 |
| `CLOUD-086` | `cloud` | `runtime_metadata` | 查詢目前 route context 的生成版本、來源與 hash。 | 需要 workspace metadata/tool read。 |
| `CLOUD-087` | `cloud` | `spatial_aggregate` | 把路線高程段與風險分數做空間及 segment join，列出最高三段。 | 需要 GIS join、排序與聚合。 |
| `CLOUD-088` | `cloud` | `historical_weather` | 查詢指定日期是否有颱風或豪雨警報影響路線所在行政區。 | 需要日期限定的外部歷史資料。 |
| `CLOUD-089` | `cloud` | `access` | 查詢目前交通或道路進入條件，並與 workspace 起點位置對照。 | 需要外部現況與 workspace location join。 |
| `CLOUD-090` | `cloud` | `weather_route_compound` | 根據最新天氣、路線暴露段與日落時間產生候選風險摘要。 | 需要多來源證據；JEV 不得直接授權安全行動。 |
| `CLOUD-091` | `cloud` | `hydrology` | 查詢當前溪流水位或上游降雨，再比對路線渡涉點。 | 需要即時環境資料與路線工具。 |
| `CLOUD-092` | `cloud` | `current_access` | 查詢指定座標附近目前是否有道路施工或封閉資訊。 | 需要即時 web search 與座標關聯。 |
| `CLOUD-093` | `cloud` | `provenance_audit` | 從 workspace 找出所有缺少 source_ref 的候選結果。 | 需要讀取並稽核 artifact provenance。 |
| `CLOUD-094` | `cloud` | `freshness_comparison` | 比較兩個不同時間的 route weather snapshot，判斷哪個較新且仍有效。 | 需要時間欄位、TTL 與多 artifact 比較。 |
| `CLOUD-095` | `cloud` | `route_change` | 查詢官方地圖或公告是否有新的路線名稱或改線資訊。 | 需要最新官方來源與歷史比較。 |
| `CLOUD-096` | `cloud` | `warning_spatial` | 計算 route corridor 與警報 polygon 是否相交，並列出不相交時的證據缺口。 | 需要 GIS intersection 與缺證據處理。 |
| `CLOUD-097` | `cloud` | `retreat_join` | 查詢沿線可用的避難或撤退點，再與 workspace route segments 配對。 | 需要外部/工作區資料配對。 |
| `CLOUD-098` | `cloud` | `environment_research` | 查詢官方對該區域的野生動物或環境注意事項，附來源與日期。 | 需要外部官方資料、日期與引用。 |
| `CLOUD-099` | `cloud` | `evidence_sufficiency` | 使用最新定位、天氣與路線 evidence，判斷目前資料是否足以形成候選摘要。 | 需要即時多源 evidence sufficiency gate。 |
| `CLOUD-100` | `cloud` | `failure_escalation` | 若本地模型無法回答某題，查明是否因缺少工具、過期資料或題目需要 web search，並提出升級理由。 | 需要檢查工具、freshness 與 failure trace。 |

## Machine-readable source

`scout-ai-local-cloud-routing-100-question-corpus.json` 是執行與驗證使用的 canonical artifact；此 Markdown 由 generator 產生。
