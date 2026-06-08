# Scout AI 52 Answerable Questions - Trial Answers

- project: `chilai_nanhua_day1`
- Scout AI path: `POST /assistant/query` through read-only assistant API with deterministic skill/tool fallback
- provider mode in this run: Pydantic provider intentionally failed to force local deterministic tool fallback; no cloud call required
- question_count: `52`
- boundary: read-only, no `/safety/*`, no runtime mutation, no outbound send, no hardware control

## Summary

- Route/CP/MCP answers are the strongest: CP count, Blackwater/CP mapping, route distance, MCP list.
- Risk-score answers are available as baseline candidate scores; calibration risk is unavailable in this fixture.
- Terrain slope answers are limited: DTM coverage metadata exists, but direct slope-score samples are absent.
- Wearable/IMU/activity questions among these 52 mostly answer as absent from the pretrip workspace, not as live data.

## Answers

### seed-001 這趟行程總共有幾個 CP？

Scout AI 回答：目前 pretrip context 有 124 個 CP/checkpoint candidates。以上都是 read-only pretrip/candidate evidence，不是 runtime safety truth，沒有呼叫 /safety/* 或改變 Scout 狀態。

Tool refs: `pydantic_ai.tool.search_scout_route_structure.v0`.
Scout AI raw status: HTTP 200; source refs: assistant_skill.pretrip.cp_count.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1, review_queue.chilai_nanhua_day1.v0, review_queue.chilai_nanhua_day1.contour.contour.g11.seg_001_003, review_queue.chilai_nanhua_day1.contour.contour.g11.seg_006_008.

### seed-002 起點到終點的總距離是多少？

Scout AI 回答：路線總距離約 55.175 km；高度約 1217-3351 m；GPX route point count 2612。以上都是 read-only pretrip/candidate evidence，不是 runtime safety truth，沒有呼叫 /safety/* 或改變 Scout 狀態。

Tool refs: `pydantic_ai.tool.search_scout_route_structure.v0`.
Scout AI raw status: HTTP 200; source refs: pydantic_ai.tool.search_scout_workspace_evidence.v0, assistant_skill.pretrip.local_evidence_search.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1, review_queue.chilai_nanhua_day1.v0, review_queue.chilai_nanhua_day1.contour.contour.g11.seg_001_003.

### seed-003 這趟行程主要分成哪些路段？

Scout AI 回答：目前主要是 123 個相鄰 CP segment candidates，來自 filtered GPX 的 deterministic spacing；它不是人工語意分段。前幾段是 Start->CP001、CP001->CP002、CP002->CP003。以上都是 read-only pretrip/candidate evidence，不是 runtime safety truth，沒有呼叫 /safety/* 或改變 Scout 狀態。

Tool refs: `pydantic_ai.tool.search_scout_route_structure.v0`.
Scout AI raw status: HTTP 200; source refs: pydantic_ai.tool.search_scout_workspace_evidence.v0, assistant_skill.pretrip.local_evidence_search.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1, review_queue.chilai_nanhua_day1.v0, review_queue.chilai_nanhua_day1.contour.contour.g11.seg_001_003.

### seed-004 哪些 CP 是重要轉折點？

Scout AI 回答：目前可當重要轉折/關鍵點的是 MCP 清單：舊林道叉路 -> Start(cp.start) [fork_junction]、黑水塘 -> CP 002(cp.002) [water_source/camp_hut_structure]、大崩壁 -> CP 003(cp.003) [extreme_terrain_hazard]、隱蔽樹林區 -> CP 005(cp.005) [hidden_forest_route_loss]、稜線啞口觀景點 -> CP 006(cp.006) [viewpoint_trailhead_pass]、稜線通訊點 -> CP 039(cp.039) [mobile_reception]；全數仍需 human review。以上都是 read-only pretrip/candidate evidence，不是 runtime safety truth，沒有呼叫 /safety/* 或改變 Scout 狀態。

Tool refs: `pydantic_ai.tool.search_scout_route_structure.v0`.
Scout AI raw status: HTTP 200; source refs: pydantic_ai.tool.search_scout_route_structure.v0, pydantic_ai.tool.search_scout_workspace_evidence.v0, assistant_skill.pretrip.local_evidence_search.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1, review_queue.chilai_nanhua_day1.v0.

### seed-005 哪些 CP 附近有水源？

Scout AI 回答：MCP 明確支持的水源是黑水塘/黑水池/黑水塘營地 -> CP 002；full-text route notes 另有活水源候選，最近約 CP017、CP070、CP084，但都需人工複核。以上都是 read-only pretrip/candidate evidence，不是 runtime safety truth，沒有呼叫 /safety/* 或改變 Scout 狀態。

Tool refs: `pydantic_ai.tool.search_scout_route_structure.v0`, `pydantic_ai.tool.search_scout_major_points.v0`.
Scout AI raw status: HTTP 200; source refs: pydantic_ai.tool.search_scout_major_points.v0, pydantic_ai.tool.search_scout_route_structure.v0, pydantic_ai.tool.search_scout_workspace_evidence.v0, assistant_skill.pretrip.local_evidence_search.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1.

### seed-008 黑水塘在第幾個 CP 附近？

Scout AI 回答：黑水塘在 CP 002 附近；MCP support 顯示 nearest_cp_candidate_id=cp.002、nearest_cp_distance_m=0.0、support_status=supported。以上都是 read-only pretrip/candidate evidence，不是 runtime safety truth，沒有呼叫 /safety/* 或改變 Scout 狀態。

Tool refs: `pydantic_ai.tool.search_scout_route_structure.v0`, `pydantic_ai.tool.search_scout_major_points.v0`.
Scout AI raw status: HTTP 200; source refs: assistant_skill.pretrip.place_to_cp.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1, review_queue.chilai_nanhua_day1.v0, review_queue.chilai_nanhua_day1.contour.contour.g11.seg_001_003, review_queue.chilai_nanhua_day1.contour.contour.g11.seg_006_008.

### seed-009 天池山莊在路線哪一段？

Scout AI 回答：天池山莊不是 MCP candidate，但 route-note evidence 可定位；天池山莊 最近 Rest area / camp area 001(cp.rest_area.001)，約 34.1 m。此 route note 標為 landmark_hint 且 requires_human_review。以上都是 read-only pretrip/candidate evidence，不是 runtime safety truth，沒有呼叫 /safety/* 或改變 Scout 狀態。

Tool refs: `pydantic_ai.tool.search_scout_route_structure.v0`, `pydantic_ai.tool.search_scout_major_points.v0`.
Scout AI raw status: HTTP 200; source refs: pydantic_ai.tool.search_scout_workspace_evidence.v0, assistant_skill.pretrip.local_evidence_search.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1, review_queue.chilai_nanhua_day1.v0, review_queue.chilai_nanhua_day1.contour.contour.g11.seg_001_003.

### seed-010 哪些地名和 CP 有對應關係？

Scout AI 回答：目前地名-CP 對應以 MCP/support 為主：舊林道叉路 -> Start(cp.start) [fork_junction]、黑水塘 -> CP 002(cp.002) [water_source/camp_hut_structure]、大崩壁 -> CP 003(cp.003) [extreme_terrain_hazard]、隱蔽樹林區 -> CP 005(cp.005) [hidden_forest_route_loss]、稜線啞口觀景點 -> CP 006(cp.006) [viewpoint_trailhead_pass]、稜線通訊點 -> CP 039(cp.039) [mobile_reception]；另有天池山莊 route-note 最近 cp.rest_area.001。以上都是 read-only pretrip/candidate evidence，不是 runtime safety truth，沒有呼叫 /safety/* 或改變 Scout 狀態。

Tool refs: `pydantic_ai.tool.search_scout_route_structure.v0`, `pydantic_ai.tool.search_scout_major_points.v0`.
Scout AI raw status: HTTP 200; source refs: pydantic_ai.tool.search_scout_major_points.v0, pydantic_ai.tool.search_scout_route_structure.v0, pydantic_ai.tool.search_scout_workspace_evidence.v0, assistant_skill.pretrip.local_evidence_search.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1.

### seed-011 這個 workspace 裡有哪些可用資料？

Scout AI 回答：71 個 artifact refs；domain 分布：route 20、workspace 20、review 8、tool 6、map 5、timing 4、runtime 3、terrain 2、risk 2、resource 1；missing 0。以上都是 read-only pretrip/candidate evidence，不是 runtime safety truth，沒有呼叫 /safety/* 或改變 Scout 狀態。

Tool refs: `pydantic_ai.tool.search_scout_workspace_catalog.v0`.
Scout AI raw status: HTTP 200; source refs: pydantic_ai.tool.search_scout_workspace_catalog.v0, pydantic_ai.tool.search_scout_workspace_evidence.v0, assistant_skill.pretrip.local_evidence_search.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1, review_queue.chilai_nanhua_day1.v0.

### seed-012 有哪些 GPX、GeoJSON、OSM 或 map layer？

Scout AI 回答：可用資料包含 GPX-derived route_summary/checkpoints/segments、GeoJSON map_context/overpass_vector_evidence/risk_ribbon、OSM/Overpass raw payload 與 candidates、MCP named points/OCR、DTM coverage metadata、review/runtime/resource manifests。以上都是 read-only pretrip/candidate evidence，不是 runtime safety truth，沒有呼叫 /safety/* 或改變 Scout 狀態。

Tool refs: `pydantic_ai.tool.search_scout_evidence_fulltext.v0`.
Scout AI raw status: HTTP 200; source refs: pydantic_ai.tool.search_scout_workspace_evidence.v0, assistant_skill.pretrip.local_evidence_search.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1, review_queue.chilai_nanhua_day1.v0, review_queue.chilai_nanhua_day1.contour.contour.g11.seg_001_003.

### seed-013 哪些資料是 candidate-only？

Scout AI 回答：candidate-only 主要包括 checkpoint/segment candidates、MCP candidates、map_candidates、overpass_evidence、risk_ribbon、contour interpretation candidates、review queue/departure bundle 候選；它們不能直接當 runtime safety truth。

Tool refs: `pydantic_ai.tool.search_scout_workspace_catalog.v0`.
Scout AI raw status: HTTP 200; source refs: pydantic_ai.tool.search_scout_workspace_evidence.v0, assistant_skill.pretrip.local_evidence_search.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1, review_queue.chilai_nanhua_day1.v0, review_queue.chilai_nanhua_day1.contour.contour.g11.seg_001_003.

### seed-015 哪些資料只是 pretrip planning evidence？

Scout AI 回答：pretrip planning evidence 包含 route/map/MCP/risk/terrain/resource/review manifests；目前這些都是行前規劃或 admin projection，不是 Phase 1 runtime truth。

Tool refs: `pydantic_ai.tool.search_scout_workspace_catalog.v0`.
Scout AI raw status: HTTP 200; source refs: pydantic_ai.tool.search_scout_terrain_scores.v0, pydantic_ai.tool.search_scout_workspace_evidence.v0, assistant_skill.pretrip.local_evidence_search.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1, review_queue.chilai_nanhua_day1.v0.

### seed-016 這趟行程有哪些 major critical points？

Scout AI 回答：目前有 6 個 MCP：舊林道叉路 -> Start(cp.start) [fork_junction]、黑水塘 -> CP 002(cp.002) [water_source/camp_hut_structure]、大崩壁 -> CP 003(cp.003) [extreme_terrain_hazard]、隱蔽樹林區 -> CP 005(cp.005) [hidden_forest_route_loss]、稜線啞口觀景點 -> CP 006(cp.006) [viewpoint_trailhead_pass]、稜線通訊點 -> CP 039(cp.039) [mobile_reception]。以上都是 read-only pretrip/candidate evidence，不是 runtime safety truth，沒有呼叫 /safety/* 或改變 Scout 狀態。

Tool refs: `pydantic_ai.tool.search_scout_major_points.v0`.
Scout AI raw status: HTTP 200; source refs: pydantic_ai.tool.search_scout_major_points.v0, pydantic_ai.tool.search_scout_workspace_evidence.v0, assistant_skill.pretrip.local_evidence_search.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1, review_queue.chilai_nanhua_day1.v0.

### seed-017 哪些 annotation 出現在 CP 附近？

Scout AI 回答：CP 附近 annotation/OCR 目前有「雲海保線所」OCR label，位置與 CP003 重合；另有 contour candidates 指向 seg001-003(cp.start-CP003) 與 seg006-008(CP005-CP008)。以上都是 read-only pretrip/candidate evidence，不是 runtime safety truth，沒有呼叫 /safety/* 或改變 Scout 狀態。

Tool refs: `pydantic_ai.tool.search_scout_route_structure.v0`, `pydantic_ai.tool.search_scout_map_perception.v0`.
Scout AI raw status: HTTP 200; source refs: pydantic_ai.tool.search_scout_route_structure.v0, pydantic_ai.tool.search_scout_map_perception.v0, pydantic_ai.tool.search_scout_workspace_evidence.v0, assistant_skill.pretrip.local_evidence_search.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1.

### seed-018 有哪些 OCR 或地圖標註資料？

Scout AI 回答：map perception material 有 1 個 OCR label、2 個 contour interpretation candidates、26 個 map layer materials；review_required_count=3，runtime_safety_truth_count=0。以上都是 read-only pretrip/candidate evidence，不是 runtime safety truth，沒有呼叫 /safety/* 或改變 Scout 狀態。

Tool refs: `pydantic_ai.tool.search_scout_workspace_catalog.v0`, `pydantic_ai.tool.search_scout_map_perception.v0`.
Scout AI raw status: HTTP 200; source refs: pydantic_ai.tool.search_scout_map_perception.v0, pydantic_ai.tool.search_scout_workspace_evidence.v0, assistant_skill.pretrip.local_evidence_search.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1, review_queue.chilai_nanhua_day1.v0.

### seed-021 哪些 CP 附近 risk score 最高？

Scout AI 回答：baseline risk 最高分約 79.58(high)。靠近 CP 的高分區包含：CP 002(cp.002, score 79.58, km 14.55)、CP 002(cp.002, score 79.58, km 14.65)、CP 014(cp.014, score 79.57, km 22.25)、CP 014(cp.014, score 79.57, km 22.35)、CP 100(cp.100, score 79.52, km 75.75)。以上都是 read-only pretrip/candidate evidence，不是 runtime safety truth，沒有呼叫 /safety/* 或改變 Scout 狀態。

Tool refs: `pydantic_ai.tool.search_scout_route_structure.v0`, `pydantic_ai.tool.search_scout_risk_scores.v0`.
Scout AI raw status: HTTP 200; source refs: pydantic_ai.tool.search_scout_route_structure.v0, pydantic_ai.tool.search_scout_risk_scores.v0, pydantic_ai.tool.search_scout_workspace_evidence.v0, assistant_skill.pretrip.local_evidence_search.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1.

### seed-022 baseline risk 和 calibration risk 差在哪？

Scout AI 回答：baseline risk 是目前 outputs/risk_ribbon.geojson 的行前候選風險分數；共有 841 筆，max 79.58、mean 64.896、high 648 筆。calibration surface 目前 unavailable，所以不能做 baseline-vs-calibration 實際差值。

Tool refs: `pydantic_ai.tool.search_scout_risk_scores.v0`.
Scout AI raw status: HTTP 200; source refs: pydantic_ai.tool.search_scout_risk_scores.v0, pydantic_ai.tool.search_scout_workspace_evidence.v0, assistant_skill.pretrip.local_evidence_search.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1, review_queue.chilai_nanhua_day1.v0.

### seed-023 哪些路段 risk score 上升最多？

Scout AI 回答：目前 calibration risk 不存在，因此「上升最多」無法計算；只能用 baseline 高分區作 proxy：CP 002(cp.002, score 79.58, km 14.55)、CP 002(cp.002, score 79.58, km 14.65)、CP 014(cp.014, score 79.57, km 22.25)、CP 014(cp.014, score 79.57, km 22.35)、CP 100(cp.100, score 79.52, km 75.75)。

Tool refs: `pydantic_ai.tool.search_scout_route_structure.v0`, `pydantic_ai.tool.search_scout_risk_scores.v0`.
Scout AI raw status: HTTP 200; source refs: pydantic_ai.tool.search_scout_risk_scores.v0, pydantic_ai.tool.search_scout_workspace_evidence.v0, assistant_skill.pretrip.local_evidence_search.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1, review_queue.chilai_nanhua_day1.v0.

### seed-024 哪些 CP 附近坡度最高？

Scout AI 回答：terrain score tool 回報 direct_slope_degrees_available=false，沒有 direct slope sample；但 DTM coverage metadata 有 48 個 candidate tiles、109 段 segment metadata，另有 contour candidates seg001-003 與 seg006-008 需人工複核。

Tool refs: `pydantic_ai.tool.search_scout_route_structure.v0`, `pydantic_ai.tool.search_scout_terrain_scores.v0`.
Scout AI raw status: HTTP 200; source refs: pydantic_ai.tool.search_scout_route_structure.v0, pydantic_ai.tool.search_scout_terrain_scores.v0, pydantic_ai.tool.search_scout_workspace_evidence.v0, assistant_skill.pretrip.local_evidence_search.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1.

### seed-025 哪些路段可能有崩塌風險？

Scout AI 回答：明確崩塌/極端地形候選是「大崩壁」MCP，class=extreme_terrain_hazard，linked risk segment=risk_ribbon.segment.0041；MCP support linked CP003，但座標最近 CP009，需 human review 對齊。以上都是 read-only pretrip/candidate evidence，不是 runtime safety truth，沒有呼叫 /safety/* 或改變 Scout 狀態。

Tool refs: `pydantic_ai.tool.search_scout_route_structure.v0`, `pydantic_ai.tool.search_scout_risk_scores.v0`.
Scout AI raw status: HTTP 200; source refs: pydantic_ai.tool.search_scout_evidence_fulltext.v0, pydantic_ai.tool.search_scout_workspace_evidence.v0, assistant_skill.pretrip.local_evidence_search.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1, review_queue.chilai_nanhua_day1.v0.

### seed-026 哪些地方可能接近稜線或暴露地形？

Scout AI 回答：接近稜線/暴露地形的候選包括「稜線啞口觀景點」-> CP006 與「稜線通訊點」-> CP039/suggested insertion；目前沒有已接受的 wind/exposure runtime layer。以上都是 read-only pretrip/candidate evidence，不是 runtime safety truth，沒有呼叫 /safety/* 或改變 Scout 狀態。

Tool refs: `pydantic_ai.tool.search_scout_terrain_scores.v0`.
Scout AI raw status: HTTP 200; source refs: pydantic_ai.tool.search_scout_terrain_scores.v0, pydantic_ai.tool.search_scout_workspace_evidence.v0, assistant_skill.pretrip.local_evidence_search.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1, review_queue.chilai_nanhua_day1.v0.

### seed-028 哪些路段不適合夜間通過？

Scout AI 回答：沒有 night-specific layer；行前應優先避免摸黑通過 MCP hazard/high-risk 區，如大崩壁、隱蔽樹林區，以及 baseline 高風險 CP002、CP014、CP096/097、CP100/101 附近。以上都是 read-only pretrip/candidate evidence，不是 runtime safety truth，沒有呼叫 /safety/* 或改變 Scout 狀態。

Tool refs: `pydantic_ai.tool.search_scout_route_structure.v0`.
Scout AI raw status: HTTP 200; source refs: pydantic_ai.tool.search_scout_workspace_evidence.v0, assistant_skill.pretrip.local_evidence_search.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1, review_queue.chilai_nanhua_day1.v0, review_queue.chilai_nanhua_day1.contour.contour.g11.seg_001_003.

### seed-044 哪些資料是 location？

Scout AI 回答：location 類資料包含 route_summary bbox、checkpoints/segments lat-lon、route_note lat-lon、MCP/named point coordinates、map_context/overpass GeoJSON、risk ribbon geometry。以上都是 read-only pretrip/candidate evidence，不是 runtime safety truth，沒有呼叫 /safety/* 或改變 Scout 狀態。

Tool refs: `pydantic_ai.tool.search_scout_workspace_catalog.v0`.
Scout AI raw status: HTTP 200; source refs: pydantic_ai.tool.search_scout_workspace_evidence.v0, assistant_skill.pretrip.local_evidence_search.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1, review_queue.chilai_nanhua_day1.v0, review_queue.chilai_nanhua_day1.contour.contour.g11.seg_001_003.

### seed-046 哪些資料是 accelerometer/gyro？

Scout AI 回答：目前這個 pretrip workspace 沒有 accelerometer/gyro 或 raw IMU records；要回答 IMU/PDR 題需要 runtime Sensor/Vitals 或 wearable ingress records。

Tool refs: `pydantic_ai.tool.search_scout_workspace_catalog.v0`.
Scout AI raw status: HTTP 200; source refs: pydantic_ai.tool.search_scout_workspace_evidence.v0, assistant_skill.pretrip.local_evidence_search.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1, review_queue.chilai_nanhua_day1.v0, review_queue.chilai_nanhua_day1.contour.contour.g11.seg_001_003.

### seed-053 哪些資料走 raw archive？

Scout AI 回答：目前可辨識的 raw archive 是 normalized/map/overpass_phase_a_raw.json；沒有 raw IMU/watch/MQTT archive 在此 pretrip fixture。以上都是 read-only pretrip/candidate evidence，不是 runtime safety truth，沒有呼叫 /safety/* 或改變 Scout 狀態。

Tool refs: `pydantic_ai.tool.search_scout_workspace_catalog.v0`.
Scout AI raw status: HTTP 200; source refs: pydantic_ai.tool.search_scout_workspace_evidence.v0, assistant_skill.pretrip.local_evidence_search.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1, review_queue.chilai_nanhua_day1.v0, review_queue.chilai_nanhua_day1.contour.contour.g11.seg_001_003.

### seed-054 哪些資料派給 navigation.ins_dr？

Scout AI 回答：目前沒有實際 navigation.ins_dr filter input/output records；可提供的只是 route/checkpoint/segment/map/risk 作為日後 INS/DR route constraint evidence。

Tool refs: `pydantic_ai.tool.search_scout_workspace_catalog.v0`.
Scout AI raw status: HTTP 200; source refs: pydantic_ai.tool.search_scout_workspace_evidence.v0, assistant_skill.pretrip.local_evidence_search.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1, review_queue.chilai_nanhua_day1.v0, review_queue.chilai_nanhua_day1.contour.contour.g11.seg_001_003.

### seed-055 哪些資料派給 resource.energy_reserve？

Scout AI 回答：resource.energy_reserve 目前可讀到 outputs/resource_plan.json，包含 4 個 device 與 4 個 equipment；尚無 vitals baseline 或 energy reserve runtime record。

Tool refs: `pydantic_ai.tool.search_scout_workspace_catalog.v0`.
Scout AI raw status: HTTP 200; source refs: pydantic_ai.tool.search_scout_workspace_evidence.v0, assistant_skill.pretrip.local_evidence_search.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1, review_queue.chilai_nanhua_day1.v0, review_queue.chilai_nanhua_day1.contour.contour.g11.seg_001_003.

### seed-056 哪些資料派給 beacon.tracer？

Scout AI 回答：目前沒有 beacon.tracer runtime stream；可供 beacon/tracer 使用的候選位置資料是 route/checkpoints/MCP/map/risk geometry。

Tool refs: `pydantic_ai.tool.search_scout_workspace_catalog.v0`.
Scout AI raw status: HTTP 200; source refs: pydantic_ai.tool.search_scout_workspace_evidence.v0, assistant_skill.pretrip.local_evidence_search.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1, review_queue.chilai_nanhua_day1.v0, review_queue.chilai_nanhua_day1.contour.contour.g11.seg_001_003.

### seed-057 哪些資料派給 weather.route_advisor？

Scout AI 回答：目前沒有 weather.route_advisor 的 fresh forecast/TTL evidence；可供 weather advisor 讀取的只有 route/risk/resource/terrain candidate context。

Tool refs: `pydantic_ai.tool.search_scout_workspace_catalog.v0`.
Scout AI raw status: HTTP 200; source refs: pydantic_ai.tool.search_scout_workspace_evidence.v0, assistant_skill.pretrip.local_evidence_search.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1, review_queue.chilai_nanhua_day1.v0, review_queue.chilai_nanhua_day1.contour.contour.g11.seg_001_003.

### seed-066 哪些資料缺少 7/28/90 天 baseline？

Scout AI 回答：目前沒有 7/28/90 天個人 baseline；缺的是 wearable/private profile history，不是 route workspace artifact。

Tool refs: `pydantic_ai.tool.search_scout_workspace_catalog.v0`.
Scout AI raw status: HTTP 200; source refs: pydantic_ai.tool.search_scout_risk_scores.v0, pydantic_ai.tool.search_scout_workspace_evidence.v0, assistant_skill.pretrip.local_evidence_search.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1, review_queue.chilai_nanhua_day1.v0.

### seed-067 哪些活動資料可能代表過度消耗？

Scout AI 回答：目前沒有活動/vitals records 可判定過度消耗；只能看到 route effort context。要回答需 pace/HR/hydration 或 wearable baseline。

Tool refs: `pydantic_ai.tool.search_scout_workspace_catalog.v0`.
Scout AI raw status: HTTP 200; source refs: pydantic_ai.tool.search_scout_workspace_evidence.v0, assistant_skill.pretrip.local_evidence_search.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1, review_queue.chilai_nanhua_day1.v0, review_queue.chilai_nanhua_day1.contour.contour.g11.seg_001_003.

### seed-078 哪些資料只是 admin visualization？

Scout AI 回答：admin visualization/projection-only 主要是 outputs/admin_projection.json、outputs/debug_projection_events.jsonl、outputs/runtime_audit_manifest.json；這些不是 runtime truth。

Tool refs: `pydantic_ai.tool.search_scout_workspace_catalog.v0`.
Scout AI raw status: HTTP 200; source refs: pydantic_ai.tool.search_scout_workspace_evidence.v0, assistant_skill.pretrip.local_evidence_search.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1, review_queue.chilai_nanhua_day1.v0, review_queue.chilai_nanhua_day1.contour.contour.g11.seg_001_003.

### seed-081 這趟行程哪幾段遇雨風險最高？

Scout AI 回答：沒有 weather-specific rain overlay；若以 baseline risk 作遇雨 proxy，高風險集中在 CP 002(cp.002, score 79.58, km 14.55)、CP 002(cp.002, score 79.58, km 14.65)、CP 014(cp.014, score 79.57, km 22.25)、CP 014(cp.014, score 79.57, km 22.35)、CP 100(cp.100, score 79.52, km 75.75)。

Tool refs: `pydantic_ai.tool.search_scout_risk_scores.v0`.
Scout AI raw status: HTTP 200; source refs: pydantic_ai.tool.search_scout_workspace_evidence.v0, assistant_skill.pretrip.local_evidence_search.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1, review_queue.chilai_nanhua_day1.v0, review_queue.chilai_nanhua_day1.contour.contour.g11.seg_001_003.

### seed-082 哪些 CP 附近適合避雨？

Scout AI 回答：可作避雨/停留候選的地點只有候選 evidence：黑水塘/雲海保線所一帶、天池山莊 route-note、部分營地 route-note；均需人工複核，不能當即時避難指令。

Tool refs: `pydantic_ai.tool.search_scout_route_structure.v0`.
Scout AI raw status: HTTP 200; source refs: pydantic_ai.tool.search_scout_route_structure.v0, pydantic_ai.tool.search_scout_workspace_evidence.v0, assistant_skill.pretrip.local_evidence_search.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1, review_queue.chilai_nanhua_day1.v0.

### seed-086 哪些路段遇強風較危險？

Scout AI 回答：沒有 strong-wind layer；可疑暴露點是稜線啞口觀景點、稜線通訊點與高風險 ribbon 區。需要天氣/風速 TTL 才能判斷強風危險。

Tool refs: `pydantic_ai.tool.search_scout_route_structure.v0`, `pydantic_ai.tool.search_scout_risk_scores.v0`.
Scout AI raw status: HTTP 200; source refs: pydantic_ai.tool.search_scout_workspace_evidence.v0, assistant_skill.pretrip.local_evidence_search.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1, review_queue.chilai_nanhua_day1.v0, review_queue.chilai_nanhua_day1.contour.contour.g11.seg_001_003.

### seed-096 哪些問題是工具回答，哪些是模型推論？

Scout AI 回答：這 52 題的答案都是 deterministic tools/skills 產生或整理：route_structure、major_points、workspace_catalog、evidence_fulltext、risk_scores、terrain_scores、map_perception；不是自由模型推論。

Tool refs: `pydantic_ai.tool.search_scout_workspace_catalog.v0`.
Scout AI raw status: HTTP 200; source refs: pydantic_ai.tool.search_scout_workspace_catalog.v0, pydantic_ai.tool.search_scout_workspace_evidence.v0, assistant_skill.pretrip.local_evidence_search.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1, review_queue.chilai_nanhua_day1.v0.

### field-003 這趟行程最容易出事的 CP 在哪裡？

Scout AI 回答：若以 baseline risk score 看，最容易出事的 CP 候選為 CP 002(cp.002, score 79.58, km 14.55)、CP 002(cp.002, score 79.58, km 14.65)、CP 014(cp.014, score 79.57, km 22.25)、CP 014(cp.014, score 79.57, km 22.35)、CP 100(cp.100, score 79.52, km 75.75)；另有 MCP hazard 大崩壁、隱蔽樹林區需 review。以上都是 read-only pretrip/candidate evidence，不是 runtime safety truth，沒有呼叫 /safety/* 或改變 Scout 狀態。

Tool refs: `pydantic_ai.tool.search_scout_route_structure.v0`, `pydantic_ai.tool.search_scout_risk_scores.v0`.
Scout AI raw status: HTTP 200; source refs: pydantic_ai.tool.search_scout_route_structure.v0, pydantic_ai.tool.search_scout_workspace_evidence.v0, assistant_skill.pretrip.local_evidence_search.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1, review_queue.chilai_nanhua_day1.v0.

### field-004 哪些地方一定要設 checkpoint？

Scout AI 回答：目前已有 124 個 CP；一定要保留/審查的關鍵點是 舊林道叉路 -> Start(cp.start) [fork_junction]、黑水塘 -> CP 002(cp.002) [water_source/camp_hut_structure]、大崩壁 -> CP 003(cp.003) [extreme_terrain_hazard]、隱蔽樹林區 -> CP 005(cp.005) [hidden_forest_route_loss]、稜線啞口觀景點 -> CP 006(cp.006) [viewpoint_trailhead_pass]、稜線通訊點 -> CP 039(cp.039) [mobile_reception]，其中稜線通訊點有 suggested insertion review required。以上都是 read-only pretrip/candidate evidence，不是 runtime safety truth，沒有呼叫 /safety/* 或改變 Scout 狀態。

Tool refs: `pydantic_ai.tool.search_scout_route_structure.v0`.
Scout AI raw status: HTTP 200; source refs: pydantic_ai.tool.search_scout_route_structure.v0, pydantic_ai.tool.search_scout_workspace_evidence.v0, assistant_skill.pretrip.local_evidence_search.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1, review_queue.chilai_nanhua_day1.v0.

### field-005 哪些路段不適合摸黑走？

Scout AI 回答：不適合摸黑走的候選是大崩壁、隱蔽樹林區、稜線啞口觀景點，以及 high risk ribbon 靠近 CP 002(cp.002, score 79.58, km 14.55)、CP 002(cp.002, score 79.58, km 14.65)、CP 014(cp.014, score 79.57, km 22.25)、CP 014(cp.014, score 79.57, km 22.35)、CP 100(cp.100, score 79.52, km 75.75)。以上都是 read-only pretrip/candidate evidence，不是 runtime safety truth，沒有呼叫 /safety/* 或改變 Scout 狀態。

Tool refs: `pydantic_ai.tool.search_scout_route_structure.v0`.
Scout AI raw status: HTTP 200; source refs: pydantic_ai.tool.search_scout_workspace_evidence.v0, assistant_skill.pretrip.local_evidence_search.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1, review_queue.chilai_nanhua_day1.v0, review_queue.chilai_nanhua_day1.contour.contour.g11.seg_001_003.

### field-007 這條路線有沒有低容錯地形？

Scout AI 回答：有低容錯候選。baseline risk 841 筆中 high 有 648 筆；MCP 另標出大崩壁、隱蔽樹林區、稜線啞口觀景點等候選。以上都是 read-only pretrip/candidate evidence，不是 runtime safety truth，沒有呼叫 /safety/* 或改變 Scout 狀態。

Tool refs: `pydantic_ai.tool.search_scout_route_structure.v0`, `pydantic_ai.tool.search_scout_risk_scores.v0`, `pydantic_ai.tool.search_scout_terrain_scores.v0`.
Scout AI raw status: HTTP 200; source refs: pydantic_ai.tool.search_scout_terrain_scores.v0, pydantic_ai.tool.search_scout_workspace_evidence.v0, assistant_skill.pretrip.local_evidence_search.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1, review_queue.chilai_nanhua_day1.v0.

### field-008 哪些地方要避免停留拍照？

Scout AI 回答：避免停留拍照的候選區包括大崩壁、隱蔽樹林區、高分 risk ribbon；景觀點「稜線啞口觀景點」本身是 viewpoint/trailhead_pass candidate，停留風險仍需人工/天氣複核。

Tool refs: `pydantic_ai.tool.search_scout_map_perception.v0`.
Scout AI raw status: HTTP 200; source refs: pydantic_ai.tool.search_scout_workspace_evidence.v0, assistant_skill.pretrip.local_evidence_search.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1, review_queue.chilai_nanhua_day1.v0, review_queue.chilai_nanhua_day1.contour.contour.g11.seg_001_003.

### field-013 這裡看起來安全，但實際坡度危險嗎？

Scout AI 回答：沒有目前座標時不能判斷「這裡」。就 workspace 而言 direct slope score 不存在；只能用 DTM coverage/contour candidates/risk ribbon 作行前候選判讀。

Tool refs: `pydantic_ai.tool.search_scout_risk_scores.v0`, `pydantic_ai.tool.search_scout_terrain_scores.v0`.
Scout AI raw status: HTTP 200; source refs: pydantic_ai.tool.search_scout_terrain_scores.v0, pydantic_ai.tool.search_scout_workspace_evidence.v0, assistant_skill.pretrip.local_evidence_search.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1, review_queue.chilai_nanhua_day1.v0.

### field-014 這段是不是滑墜後沒有停止點？

Scout AI 回答：目前沒有 fall-line/no-stop-zone 專門模型；能查的是 high risk ribbon 與 MCP hazard。若問具體路段，需要 current segment 或 lat/lon。

Tool refs: `pydantic_ai.tool.search_scout_risk_scores.v0`.
Scout AI raw status: HTTP 200; source refs: pydantic_ai.tool.search_scout_workspace_evidence.v0, assistant_skill.pretrip.local_evidence_search.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1, review_queue.chilai_nanhua_day1.v0, review_queue.chilai_nanhua_day1.contour.contour.g11.seg_001_003.

### field-015 這條乾溝可以走嗎？

Scout AI 回答：目前沒有「乾溝」專用候選或可走性模型；terrain tool 也沒有 direct slope samples，因此不能從 workspace 證明可走。安全回答是不要把 off-route 乾溝視為可通行路線。

Tool refs: `pydantic_ai.tool.search_scout_terrain_scores.v0`.
Scout AI raw status: HTTP 200; source refs: pydantic_ai.tool.search_scout_workspace_evidence.v0, assistant_skill.pretrip.local_evidence_search.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1, review_queue.chilai_nanhua_day1.v0, review_queue.chilai_nanhua_day1.contour.contour.g11.seg_001_003.

### field-017 這個景觀點適合停下拍照嗎？

Scout AI 回答：景觀點候選是「稜線啞口觀景點」；它只是 candidate-only map/named-point evidence，沒有天氣/風/停留安全模型，不能直接判定適合停下拍照。

Tool refs: `pydantic_ai.tool.search_scout_map_perception.v0`.
Scout AI raw status: HTTP 200; source refs: pydantic_ai.tool.search_scout_workspace_evidence.v0, assistant_skill.pretrip.local_evidence_search.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1, review_queue.chilai_nanhua_day1.v0, review_queue.chilai_nanhua_day1.contour.contour.g11.seg_001_003.

### field-018 這裡是官方路線還是人走出來的路跡？

Scout AI 回答：目前主路線是 filtered GPX deterministic import 與 Overpass/map evidence candidate；workspace 沒有把每一段正式標成 official route 或 social trail。

Tool refs: `pydantic_ai.tool.search_scout_route_structure.v0`, `pydantic_ai.tool.search_scout_evidence_fulltext.v0`.
Scout AI raw status: HTTP 200; source refs: pydantic_ai.tool.search_scout_workspace_evidence.v0, assistant_skill.pretrip.local_evidence_search.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1, review_queue.chilai_nanhua_day1.v0, review_queue.chilai_nanhua_day1.contour.contour.g11.seg_001_003.

### field-020 這段容許路徑寬度應該抓多少？

Scout AI 回答：目前 map_context 的 approved_corridor candidate 使用 corridor_half_width_m=30.0；checkpoint arrival_radius_m 也是 30 m。這是行前候選寬度，不是 runtime 離線判定門檻。

Tool refs: `pydantic_ai.tool.search_scout_route_structure.v0`.
Scout AI raw status: HTTP 200; source refs: pydantic_ai.tool.search_scout_workspace_evidence.v0, assistant_skill.pretrip.local_evidence_search.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1, review_queue.chilai_nanhua_day1.v0, review_queue.chilai_nanhua_day1.contour.contour.g11.seg_001_003.

### field-073 我可以下切溪谷嗎？

Scout AI 回答：不能把下切溪谷當成建議。workspace 沒有 current position，也沒有 dry-gully/valley descent safety layer；只能說目前沒有 evidence 支持離開主線下切。

Tool refs: `pydantic_ai.tool.search_scout_terrain_scores.v0`.
Scout AI raw status: HTTP 200; source refs: pydantic_ai.tool.search_scout_workspace_evidence.v0, assistant_skill.pretrip.local_evidence_search.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1, review_queue.chilai_nanhua_day1.v0, review_queue.chilai_nanhua_day1.contour.contour.g11.seg_001_003.

### field-075 哪裡比較容易被看見？

Scout AI 回答：workspace 只能提供候選：稜線啞口觀景點、稜線通訊點可能較開闊/有收訊，但沒有 visibility/rescue line-of-sight 模型；需要 current position 才能回答哪裡較容易被看見。

Tool refs: `pydantic_ai.tool.search_scout_map_perception.v0`.
Scout AI raw status: HTTP 200; source refs: pydantic_ai.tool.search_scout_workspace_evidence.v0, assistant_skill.pretrip.local_evidence_search.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1, review_queue.chilai_nanhua_day1.v0, review_queue.chilai_nanhua_day1.contour.contour.g11.seg_001_003.

### field-093 哪個 CP 設錯或漏設了？

Scout AI 回答：目前沒有已接受的「CP 設錯」結論；review queue 顯示 contour seg001-003、seg006-008 需審查，MCP 稜線通訊點有 suggested insertion review required。

Tool refs: `pydantic_ai.tool.search_scout_route_structure.v0`.
Scout AI raw status: HTTP 200; source refs: pydantic_ai.tool.search_scout_route_structure.v0, pydantic_ai.tool.search_scout_workspace_evidence.v0, assistant_skill.pretrip.local_evidence_search.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1, review_queue.chilai_nanhua_day1.v0.

### field-094 哪段路的 GPX corridor 太寬或太窄？

Scout AI 回答：目前 corridor candidate 半寬是 30 m，沒有 post-trip trajectory diff 或 corridor quality report 指出哪段太寬/太窄；只能回報現有 corridor 設定。

Tool refs: `pydantic_ai.tool.search_scout_route_structure.v0`, `pydantic_ai.tool.search_scout_evidence_fulltext.v0`.
Scout AI raw status: HTTP 200; source refs: pydantic_ai.tool.search_scout_workspace_evidence.v0, assistant_skill.pretrip.local_evidence_search.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1, review_queue.chilai_nanhua_day1.v0, review_queue.chilai_nanhua_day1.contour.contour.g11.seg_001_003.

### field-095 是否有景觀點/拍照停留風險被忽略？

Scout AI 回答：可能被忽略的景觀/停留風險候選是「稜線啞口觀景點」與 high risk ribbon 區；但目前沒有已接受的 missed-risk conclusion。以上都是 read-only pretrip/candidate evidence，不是 runtime safety truth，沒有呼叫 /safety/* 或改變 Scout 狀態。

Tool refs: `pydantic_ai.tool.search_scout_risk_scores.v0`, `pydantic_ai.tool.search_scout_map_perception.v0`.
Scout AI raw status: HTTP 200; source refs: pydantic_ai.tool.search_scout_workspace_evidence.v0, assistant_skill.pretrip.local_evidence_search.v0, assistant_context.pretrip, chilai_nanhua_day1, artifact.gpx.chilai_nanhua_day1, readiness.chilai_nanhua_day1, review_queue.chilai_nanhua_day1.v0, review_queue.chilai_nanhua_day1.contour.contour.g11.seg_001_003.
