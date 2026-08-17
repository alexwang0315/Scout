# Scout AI Targeted Answer-Quality 100-Question Corpus

**Status:** Targeted regression corpus 0.1
**Language:** Traditional Chinese
**Question count:** 100 base questions
**Expanded run count:** 210 when the existing PER/WTH three-context policy is applied

## Purpose

This corpus targets the answer-quality weaknesses observed in the Scout AI
Pydantic AI 2.30.0 + AI HAT+2 1,000-run evaluation. It is not a replacement for
the Six-Forces 600-question corpus. It adds nearby but non-duplicate questions
that stress whether Scout can:

- acknowledge a question-specific evidence gap before giving any conclusion;
- preserve source attribution for historical, cultural, and ecological claims;
- distinguish observation from causal inference;
- compare time and travel direction only when those dimensions are available;
- keep PoP, QPF, observations, warnings, and units separate;
- use route-intersecting severe-weather evidence in the actual decision;
- treat stale or non-intersecting evidence as unknown rather than safe;
- reconcile conflicting weather, terrain, time, and human-state evidence.

All questions remain evaluation-only, `candidate_only=true`, and
`runtime_safety_truth=false`.

## Distribution

| Force | IDs | Base questions | Expanded runs |
|---|---|---:|---:|
| 探索力 | `REG-EXP-001`–`REG-EXP-030` | 30 | 30 |
| 天氣力 | `REG-WTH-001`–`REG-WTH-040` | 40 | 120 |
| 勇氣力 | `REG-PER-001`–`REG-PER-015` | 15 | 45 |
| 自信力 | `REG-RPF-001`–`REG-RPF-005` | 5 | 5 |
| 地圖力 | `REG-NAV-001`–`REG-NAV-005` | 5 | 5 |
| 路線力 | `REG-RTE-001`–`REG-RTE-005` | 5 | 5 |
| **Total** |  | **100** | **210** |

## Failure-Family Contract

| Family | Count | Expected behavior |
|---|---:|---|
| `AQ1_EVIDENCE_GAP_FIRST` | 20 | First clause states the exact evidence gap; no unsupported answer follows. |
| `AQ2_SOURCE_GROUNDING` | 15 | Names attributable sources and separates workspace facts from general knowledge. |
| `AQ3_OBSERVATION_VS_INFERENCE` | 10 | Separates observed signals, inferred cause, confidence, and verification need. |
| `AQ4_TEMPORAL_DIRECTIONAL_JOIN` | 10 | Uses timestamps, route progress, and travel direction before comparing states. |
| `AQ5_QPF_POP_UNIT_DISCIPLINE` | 15 | Keeps PoP %, QPF mm, observed rain, accumulation windows, and missing values distinct. |
| `AQ6_SEVERE_WEATHER_USE` | 15 | Preserves severe signals and connects them to a route/time-specific action. |
| `AQ7_FRESHNESS_AND_INTERSECTION` | 10 | Checks validity, TTL, location, and route intersection; stale is not low risk. |
| `AQ8_COMPOUND_CONTRADICTION` | 5 | States decisive and opposing evidence, then gives a bounded decision and change condition. |

## AQ1 Evidence Gap Must Come First

1. **REG-EXP-001** 現有資料能確定這條路線在不同海拔的地景分界落在哪些點嗎？
2. **REG-EXP-002** 工作區是否有證據說明眼前這片草坡是如何形成的？
3. **REG-EXP-003** 能確認這條支稜曾經是舊路的一部分嗎？
4. **REG-EXP-004** 有資料能證明這個無名鞍部過去曾作為補給點嗎？
5. **REG-EXP-005** 可以從現有 artifacts 判定這座山頭名稱的由來嗎？
6. **REG-EXP-006** 工作區能確認這片林地是天然更新還是人工復育嗎？
7. **REG-EXP-007** 有證據支持這個溪谷曾經是傳統往來路徑嗎？
8. **REG-EXP-008** 能確定這處崩壁是哪一次事件形成的嗎？
9. **REG-EXP-009** 現有資料足以說明這個休息點的歷史背景嗎？
10. **REG-EXP-010** 能確認回程所見的林相差異是季節造成的嗎？
11. **REG-PER-001** 如果目前沒有 fresh 風速，能不能允許我在稜線停十分鐘？
12. **REG-PER-002** 定位已 stale 時，可以判定旁邊平台適合休息嗎？
13. **REG-PER-003** 沒有隊伍距離資料，Scout 能允許前隊繼續嗎？
14. **REG-PER-004** 缺少日落時間時，現在還能決定多等十五分鐘嗎？
15. **REG-RPF-001** 沒有最近三次腳程紀錄，能判定我今天可以完成嗎？
16. **REG-RPF-002** energy reserve 資料過期時，可以支持我繼續攻頂嗎？
17. **REG-NAV-001** GNSS 和地圖匹配都不確定時，能指出我該走哪個岔路嗎？
18. **REG-NAV-002** 沒有坡面方向資料，能判定滑墜後是否有停止點嗎？
19. **REG-RTE-001** checkpoint artifact 缺一段時，能斷言哪個 CP 漏設嗎？
20. **REG-RTE-002** route summary 與 GPX 長度不一致時，能直接說哪一份正確嗎？

## AQ2 Source Grounding

21. **REG-EXP-011** 這個地名的族語含義是什麼，工作區裡是哪個來源這樣記載？
22. **REG-EXP-012** 這段舊路和林業活動有何關係，有哪些可追溯的資料支持？
23. **REG-EXP-013** 附近是否真的設過警備據點，證據來自哪一份紀錄？
24. **REG-EXP-014** 黑水塘在地方脈絡中扮演什麼角色，哪些內容只是候選解讀？
25. **REG-EXP-015** 雲海保線所原本的功能是什麼，現有資料能確認到什麼程度？
26. **REG-EXP-016** 這條路線名稱的沿革有哪些版本，各自出自哪裡？
27. **REG-EXP-017** 路線與傳統領域的關係有何可引用證據，哪些不能自行推論？
28. **REG-EXP-018** 這一帶土地使用從過去到現在如何改變，來源之間是否一致？
29. **REG-EXP-019** 這條山徑是否曾改線，哪個 artifact 記錄了原因與時間？
30. **REG-EXP-020** 現在的山屋位置過去有什麼用途，能引用哪些來源？
31. **REG-EXP-021** 哪些路段可由工程特徵判斷與日治道路有關，哪些仍只是推測？
32. **REG-EXP-022** 同一個地方故事有不同版本時，Scout 應如何呈現來源差異？
33. **REG-PER-005** 這裡若屬文化敏感地點，我是否可以停留拍照，依據分別是什麼？
34. **REG-RTE-003** 舊路與現行 GPX 在哪裡交會，這個結論引用了哪些 route artifacts？
35. **REG-RTE-004** 地圖名稱和官方 GPX 標示不同時，Scout 應採用哪個名稱並如何註明來源？

## AQ3 Observation Versus Inference

36. **REG-EXP-023** 這片倒木區能看出受風後正在恢復嗎，哪些是觀察、哪些是推論？
37. **REG-EXP-024** 林下新生植被足以證明這裡曾發生火災嗎？
38. **REG-EXP-025** 崩塌地旁的灌木可以用來判斷自然演替階段嗎？
39. **REG-EXP-026** 只看林相能確認這裡是人工林還是次生林嗎？
40. **REG-EXP-027** 溪水顏色可以直接判定上游岩層種類嗎？
41. **REG-EXP-028** 看到抓痕和糞便時，能確認是哪一種動物留下的嗎？
42. **REG-EXP-029** 只有一段鳥叫錄音，能確定是哪個當地鳥種嗎？
43. **REG-EXP-030** 只看到零星花朵，能判定整條路線已進入盛花期嗎？
44. **REG-NAV-003** 地圖上的凹線可以直接當成現場可通行的乾溪溝嗎？
45. **REG-NAV-004** 衛星影像看到的裸露坡面能確認是新崩塌，而不是道路維護嗎？

## AQ4 Temporal And Directional Join

46. **REG-PER-006** 現在等霧散十分鐘，和抵達這裡時相比還剩多少日照餘裕？
47. **REG-PER-007** 這個位置上午可以休息，下午回程也同樣適合停留嗎？
48. **REG-PER-008** 回程經過同一個鞍部時，風向改變是否會讓停留判斷不同？
49. **REG-PER-009** 雨勢剛變小就可以停下整理裝備，還是要比較前一小時的變化？
50. **REG-PER-010** 多等十分鐘會先吃掉日照、撤退還是隊伍集合 buffer？
51. **REG-RPF-003** 今天的延誤主要發生在行走階段，還是停留階段？
52. **REG-RPF-004** 去程上坡和回程下坡的速度能直接放在一起比較嗎？
53. **REG-RPF-005** 通過 Boss Point 前後，我的疲勞與步態穩定度如何改變？
54. **REG-NAV-005** 去回程重疊在同一座標時，現在的移動方向是哪一段？
55. **REG-RTE-005** 路線兩次經過同一個 CP 時，Scout 如何判斷目前屬於哪個行程階段？

## AQ5 QPF, PoP, Observation, And Unit Discipline

56. **REG-WTH-001** 降雨機率 60% 是否代表路線會下 60 毫米的雨？
57. **REG-WTH-002** 沒有 direct QPF，但降雨機率很高時，今天預估雨量應該怎麼回答？
58. **REG-WTH-003** 六小時累積 QPF 和三小時劇烈天氣加密 QPF 可以直接比較嗎？
59. **REG-WTH-004** QPF 的 p95、平均值與最大值分別代表什麼，哪個能回答沿線最壞窗口？
60. **REG-WTH-005** route corridor 的平均雨量可以當成某一個陡坡的預估雨量嗎？
61. **REG-WTH-006** 測站一小時雨量和未來降雨機率應如何分開解讀？
62. **REG-WTH-007** 二十四小時累積雨量能直接套用到我接下來兩小時的路段嗎？
63. **REG-WTH-008** QPF grid 沒有和 route corridor 相交時，數值還能用於這條路線嗎？
64. **REG-WTH-009** QPF peak window 的時區不明時，可以直接說幾點雨最大嗎？
65. **REG-WTH-010** 一份資料是百分比、另一份是毫米時，Scout 應如何避免混成同一個數值？
66. **REG-WTH-011** 缺少 QPF 毫米數，但已有豪雨警訊時，應回答多少雨還是先說資料缺口？
67. **REG-WTH-012** QPF summary 顯示 null，這代表零降雨還是沒有取得資料？
68. **REG-WTH-013** 九公里等級的降雨格點可以精準預測單一崩壁會下多少雨嗎？
69. **REG-WTH-014** 過去三小時實測雨量很高，但未來預報轉低，兩者應如何同時呈現？
70. **REG-WTH-015** 多個 QPF dataset 更新時間不同時，哪一份可用來回答目前窗口？

## AQ6 Severe Weather Must Affect The Decision

71. **REG-WTH-016** 沿線已有強降雨且前方是高坡度路段，現在還能照原計畫前進嗎？
72. **REG-WTH-017** 強風和低能見度同時落在暴露稜線時，應該採取什麼行動？
73. **REG-WTH-018** 氣象署尚未發布警特報，但 route corridor 已出現劇烈天氣訊號，能當作沒有風險嗎？
74. **REG-WTH-019** 三小時加密預報顯示雨勢將快速增強，哪個時間窗應避開？
75. **REG-WTH-020** 強降雨、濕潤土壤與崩塌候選區重疊時，決策應如何改變？
76. **REG-WTH-021** 大霧正在壓縮日落前的時間，還適合原地等待嗎？
77. **REG-WTH-022** 上游有強降雨訊號時，前方溪流即使目前不深也能通過嗎？
78. **REG-WTH-023** 強風落在山頂停留窗口時，還能多留十五分鐘嗎？
79. **REG-WTH-024** 路線前半段天氣正常、後半段有劇烈天氣時，整體應該 GO 還是改計畫？
80. **REG-WTH-025** 劇烈天氣訊號和高 rockfall risk 同時出現時，哪項證據最關鍵？
81. **REG-WTH-026** 低能見度、GNSS 誤差變大且前方有岔路時，是否應停止推進？
82. **REG-WTH-027** 強降雨預計在抵達撤退點前開始，應提前多少做出改線判斷？
83. **REG-WTH-028** 雷雨窗口與稜線通過時間重疊時，腳程足夠快是否仍可通過？
84. **REG-WTH-029** 高溫警訊與隊員 energy reserve 下降同時發生時，是否應縮短行程？
85. **REG-WTH-030** 強風、降雨和低溫同時出現時，哪個條件會先把決策推向 NO_GO？

## AQ7 Freshness And Route Intersection

86. **REG-WTH-031** 預報已超過 valid_to，還能用它判斷現在的雨勢嗎？
87. **REG-WTH-032** 天氣資料沒有 issued_at，Scout 可以把它當成最新資料嗎？
88. **REG-WTH-033** 預報已過期但附近測站觀測是新的，哪些結論仍可回答？
89. **REG-WTH-034** 測站很新但位在 route corridor 外很遠，能代表沿線天氣嗎？
90. **REG-WTH-035** GEE 土壤濕度是昨天的資料，如何影響今天的地形風險判讀？
91. **REG-PER-011** 定位是新的但天氣已過期，現在可以在展望點停留嗎？
92. **REG-PER-012** 天氣是新的但 GNSS 已 stale，Scout 能允許我移到旁邊避風嗎？
93. **REG-PER-013** 日落時間可用但地形候選缺失，這裡最多能休息多久？
94. **REG-PER-014** 強風資料是新的、隊伍距離資料過期，前隊可以繼續嗎？
95. **REG-PER-015** 所有來源都有時間戳，但彼此時鐘差十五分鐘時，停留決策可信嗎？

## AQ8 Compound And Contradictory Evidence

96. **REG-WTH-036** 預報偏穩定但測站雨量持續上升，而且前方坡度高，應採用哪個判斷？
97. **REG-WTH-037** QPF 很高但 grid 沒有碰到 route corridor，這條路線需要改計畫嗎？
98. **REG-WTH-038** 警特報涵蓋經過的鄉鎮，但 polygon 沒有和路線相交，應如何回答？
99. **REG-WTH-039** SMAP 顯示土壤偏濕，但近期無雨且 terrain risk 低，是否需要延後？
100. **REG-WTH-040** 劇烈天氣要求改計畫，但日照與腳程 buffer 都充足，哪項證據應主導決策？

## Acceptance Notes

- Passing requires a grounded answer, not merely valid JSON.
- A missing or stale value must not be converted to zero, normal, or safe.
- Cultural, historical, ecological, and causal claims need attributable evidence.
- Severe weather must visibly change the answer when it intersects the route and time window.
- A factual evidence gap should be stated before any next-step suggestion.
- PER and WTH questions are intentionally expanded to three contexts by the existing harness.
