# Scout AI 200-Question Final Classification

- artifact_kind: `scout_ai_200_question_final_classification`
- artifact_version: `scout_ai_200_question_final_classification.v0`
- generated_on: `2026-06-06`
- source corpus: `docs/specs/scout-ai-200-question-corpus.json`
- source eval: `scout_ai_question_answerability_eval.v0`
- boundary: read-only; no `/safety/*`; no Phase 1 L0-L4 mutation; no outbound send; no medical diagnosis

## Summary

| 類別 | Answerability | 題數 | 意義 |
| --- | --- | ---: | --- |
| 目前可回答 | `answerable_by_current_read_only_tools` | 52 | Scout AI 目前可用 deterministic read-only workspace tools 或 local fallback 回答；答案仍維持 candidate/read-only boundary。 |
| 需要額外資料 | `requires_missing_evidence` | 135 | 問題類型已可判定，但目前 workspace/runtime 缺少必要 evidence；需補資料或建立工具 input contract 後才能可靠回答。 |
| 健康/醫療 advisory-only | `advisory_only_not_medical_diagnosis` | 7 | Scout AI 可整理 evidence 與風險提醒，但不能當醫療診斷或治療建議。 |
| 通報/報案/啟動/發送 blocked | `blocked_for_direct_action_can_only_explain` | 6 | Scout AI 可以解釋需要哪些欄位、playbook 或授權，但不能自行通知、報案、啟動安全狀態、發送 outbound packet 或改 Phase 1 L0-L4。 |

## 1. 目前可回答

共 52 題。這些題目目前可由 Scout AI 的 deterministic read-only workspace tools/local fallback 回答。

| ID | Corpus Category | 問題 | Current Tools | Recommended Tools |
| --- | --- | --- | --- | --- |
| seed-001 | pretrip_route | 這趟行程總共有幾個 CP？ | `pydantic_ai.tool.search_scout_route_structure.v0` (route structure) | - |
| seed-002 | pretrip_route | 起點到終點的總距離是多少？ | `pydantic_ai.tool.search_scout_route_structure.v0` (route structure) | - |
| seed-003 | pretrip_route | 這趟行程主要分成哪些路段？ | `pydantic_ai.tool.search_scout_route_structure.v0` (route structure) | - |
| seed-004 | pretrip_route | 哪些 CP 是重要轉折點？ | `pydantic_ai.tool.search_scout_route_structure.v0` (route structure) | - |
| seed-005 | pretrip_route | 哪些 CP 附近有水源？ | `pydantic_ai.tool.search_scout_route_structure.v0` (route structure), `pydantic_ai.tool.search_scout_major_points.v0` (major points) | `scout.ai.route_readiness.assess.v0` (route readiness assessment) |
| seed-008 | pretrip_route | 黑水塘在第幾個 CP 附近？ | `pydantic_ai.tool.search_scout_route_structure.v0` (route structure), `pydantic_ai.tool.search_scout_major_points.v0` (major points) | `scout.ai.route_readiness.assess.v0` (route readiness assessment) |
| seed-009 | pretrip_route | 天池山莊在路線哪一段？ | `pydantic_ai.tool.search_scout_route_structure.v0` (route structure), `pydantic_ai.tool.search_scout_major_points.v0` (major points) | - |
| seed-010 | pretrip_route | 哪些地名和 CP 有對應關係？ | `pydantic_ai.tool.search_scout_route_structure.v0` (route structure), `pydantic_ai.tool.search_scout_major_points.v0` (major points) | - |
| seed-011 | workspace_evidence | 這個 workspace 裡有哪些可用資料？ | `pydantic_ai.tool.search_scout_workspace_catalog.v0` (workspace catalog) | - |
| seed-012 | workspace_evidence | 有哪些 GPX、GeoJSON、OSM 或 map layer？ | `pydantic_ai.tool.search_scout_evidence_fulltext.v0` (evidence full-text) | - |
| seed-013 | workspace_evidence | 哪些資料是 candidate-only？ | `pydantic_ai.tool.search_scout_workspace_catalog.v0` (workspace catalog) | - |
| seed-015 | workspace_evidence | 哪些資料只是 pretrip planning evidence？ | `pydantic_ai.tool.search_scout_workspace_catalog.v0` (workspace catalog) | - |
| seed-016 | workspace_evidence | 這趟行程有哪些 major critical points？ | `pydantic_ai.tool.search_scout_major_points.v0` (major points) | - |
| seed-017 | workspace_evidence | 哪些 annotation 出現在 CP 附近？ | `pydantic_ai.tool.search_scout_route_structure.v0` (route structure), `pydantic_ai.tool.search_scout_map_perception.v0` (map perception) | - |
| seed-018 | workspace_evidence | 有哪些 OCR 或地圖標註資料？ | `pydantic_ai.tool.search_scout_workspace_catalog.v0` (workspace catalog), `pydantic_ai.tool.search_scout_map_perception.v0` (map perception) | - |
| seed-021 | risk_terrain | 哪些 CP 附近 risk score 最高？ | `pydantic_ai.tool.search_scout_route_structure.v0` (route structure), `pydantic_ai.tool.search_scout_risk_scores.v0` (risk scores) | - |
| seed-022 | risk_terrain | baseline risk 和 calibration risk 差在哪？ | `pydantic_ai.tool.search_scout_risk_scores.v0` (risk scores) | - |
| seed-023 | risk_terrain | 哪些路段 risk score 上升最多？ | `pydantic_ai.tool.search_scout_route_structure.v0` (route structure), `pydantic_ai.tool.search_scout_risk_scores.v0` (risk scores) | `scout.ai.energy_vitals.assess.v0` (energy/vitals advisory assessment) |
| seed-024 | risk_terrain | 哪些 CP 附近坡度最高？ | `pydantic_ai.tool.search_scout_route_structure.v0` (route structure), `pydantic_ai.tool.search_scout_terrain_scores.v0` (terrain scores) | - |
| seed-025 | risk_terrain | 哪些路段可能有崩塌風險？ | `pydantic_ai.tool.search_scout_route_structure.v0` (route structure), `pydantic_ai.tool.search_scout_risk_scores.v0` (risk scores) | - |
| seed-026 | risk_terrain | 哪些地方可能接近稜線或暴露地形？ | `pydantic_ai.tool.search_scout_terrain_scores.v0` (terrain scores) | - |
| seed-028 | risk_terrain | 哪些路段不適合夜間通過？ | `pydantic_ai.tool.search_scout_route_structure.v0` (route structure) | - |
| seed-044 | sensor_wearable | 哪些資料是 location？ | `pydantic_ai.tool.search_scout_workspace_catalog.v0` (workspace catalog) | - |
| seed-046 | sensor_wearable | 哪些資料是 accelerometer/gyro？ | `pydantic_ai.tool.search_scout_workspace_catalog.v0` (workspace catalog) | - |
| seed-053 | transport_router | 哪些資料走 raw archive？ | `pydantic_ai.tool.search_scout_workspace_catalog.v0` (workspace catalog) | - |
| seed-054 | transport_router | 哪些資料派給 navigation.ins_dr？ | `pydantic_ai.tool.search_scout_workspace_catalog.v0` (workspace catalog) | - |
| seed-055 | transport_router | 哪些資料派給 resource.energy_reserve？ | `pydantic_ai.tool.search_scout_workspace_catalog.v0` (workspace catalog) | - |
| seed-056 | transport_router | 哪些資料派給 beacon.tracer？ | `pydantic_ai.tool.search_scout_workspace_catalog.v0` (workspace catalog) | - |
| seed-057 | transport_router | 哪些資料派給 weather.route_advisor？ | `pydantic_ai.tool.search_scout_workspace_catalog.v0` (workspace catalog) | - |
| seed-066 | energy_vitals | 哪些資料缺少 7/28/90 天 baseline？ | `pydantic_ai.tool.search_scout_workspace_catalog.v0` (workspace catalog) | - |
| seed-067 | energy_vitals | 哪些活動資料可能代表過度消耗？ | `pydantic_ai.tool.search_scout_workspace_catalog.v0` (workspace catalog) | - |
| seed-078 | safety_admission | 哪些資料只是 admin visualization？ | `pydantic_ai.tool.search_scout_workspace_catalog.v0` (workspace catalog) | - |
| seed-081 | weather_camp | 這趟行程哪幾段遇雨風險最高？ | `pydantic_ai.tool.search_scout_risk_scores.v0` (risk scores) | - |
| seed-082 | weather_camp | 哪些 CP 附近適合避雨？ | `pydantic_ai.tool.search_scout_route_structure.v0` (route structure) | - |
| seed-086 | weather_camp | 哪些路段遇強風較危險？ | `pydantic_ai.tool.search_scout_route_structure.v0` (route structure), `pydantic_ai.tool.search_scout_risk_scores.v0` (risk scores) | - |
| seed-096 | admin_debug_ai | 哪些問題是工具回答，哪些是模型推論？ | `pydantic_ai.tool.search_scout_workspace_catalog.v0` (workspace catalog) | - |
| field-003 | field_pretrip | 這趟行程最容易出事的 CP 在哪裡？ | `pydantic_ai.tool.search_scout_route_structure.v0` (route structure), `pydantic_ai.tool.search_scout_risk_scores.v0` (risk scores) | - |
| field-004 | field_pretrip | 哪些地方一定要設 checkpoint？ | `pydantic_ai.tool.search_scout_route_structure.v0` (route structure) | `scout.ai.route_readiness.assess.v0` (route readiness assessment) |
| field-005 | field_pretrip | 哪些路段不適合摸黑走？ | `pydantic_ai.tool.search_scout_route_structure.v0` (route structure) | `scout.ai.route_readiness.assess.v0` (route readiness assessment) |
| field-007 | field_pretrip | 這條路線有沒有低容錯地形？ | `pydantic_ai.tool.search_scout_route_structure.v0` (route structure), `pydantic_ai.tool.search_scout_risk_scores.v0` (risk scores), `pydantic_ai.tool.search_scout_terrain_scores.v0` (terrain scores) | `scout.ai.route_readiness.assess.v0` (route readiness assessment) |
| field-008 | field_pretrip | 哪些地方要避免停留拍照？ | `pydantic_ai.tool.search_scout_map_perception.v0` (map perception) | `scout.ai.route_readiness.assess.v0` (route readiness assessment) |
| field-013 | field_terrain_route | 這裡看起來安全，但實際坡度危險嗎？ | `pydantic_ai.tool.search_scout_risk_scores.v0` (risk scores), `pydantic_ai.tool.search_scout_terrain_scores.v0` (terrain scores) | - |
| field-014 | field_terrain_route | 這段是不是滑墜後沒有停止點？ | `pydantic_ai.tool.search_scout_risk_scores.v0` (risk scores) | - |
| field-015 | field_terrain_route | 這條乾溝可以走嗎？ | `pydantic_ai.tool.search_scout_terrain_scores.v0` (terrain scores) | - |
| field-017 | field_terrain_route | 這個景觀點適合停下拍照嗎？ | `pydantic_ai.tool.search_scout_map_perception.v0` (map perception) | - |
| field-018 | field_terrain_route | 這裡是官方路線還是人走出來的路跡？ | `pydantic_ai.tool.search_scout_route_structure.v0` (route structure), `pydantic_ai.tool.search_scout_evidence_fulltext.v0` (evidence full-text) | - |
| field-020 | field_terrain_route | 這段容許路徑寬度應該抓多少？ | `pydantic_ai.tool.search_scout_route_structure.v0` (route structure) | - |
| field-073 | field_lost_survival | 我可以下切溪谷嗎？ | `pydantic_ai.tool.search_scout_terrain_scores.v0` (terrain scores) | `scout.ai.live_navigation_state.assess.v0` (live navigation state assessment), `scout.ai.survival_incident_playbook.explain.v0` (survival/incident playbook explainer) |
| field-075 | field_lost_survival | 哪裡比較容易被看見？ | `pydantic_ai.tool.search_scout_map_perception.v0` (map perception) | - |
| field-093 | field_post_trip | 哪個 CP 設錯或漏設了？ | `pydantic_ai.tool.search_scout_route_structure.v0` (route structure) | `scout.ai.post_trip_review.assess.v0` (post-trip incident review assessment) |
| field-094 | field_post_trip | 哪段路的 GPX corridor 太寬或太窄？ | `pydantic_ai.tool.search_scout_route_structure.v0` (route structure), `pydantic_ai.tool.search_scout_evidence_fulltext.v0` (evidence full-text) | `scout.ai.post_trip_review.assess.v0` (post-trip incident review assessment) |
| field-095 | field_post_trip | 是否有景觀點/拍照停留風險被忽略？ | `pydantic_ai.tool.search_scout_risk_scores.v0` (risk scores), `pydantic_ai.tool.search_scout_map_perception.v0` (map perception) | - |

## 2. 需要額外資料

共 135 題。這些題目不是不能回答，而是目前缺少必要 evidence 或工具 input contract。

### 缺資料類型總表

一題可能需要多種資料，所以此表是 multi-label 統計。

| 缺資料類型 | 題數 | 需要補的資料 |
| --- | ---: | --- |
| 目前位置 (`current_position`) | 24 | timestamped lat/lon/elevation、route progress、nearest CP/segment |
| GNSS 精度 (`gnss_accuracy`) | 24 | HDOP/VDOP、horizontal accuracy、fix type、satellite/C/N0 或 provider confidence |
| 近期 INS/DR/PDR 狀態 (`ins_dr_recent_samples`) | 24 | recent INS/DR estimates、heading/course、step/PDR samples、uncertainty、last anchor |
| 即時天氣/預報與 TTL (`fresh_weather_or_nowcast_with_ttl`) | 18 | forecast/nowcast、rain/wind/fog/temp/daylight、valid time/TTL、route-local exposure context |
| Runtime ingress/router trace (`runtime_ingress_router_trace`) | 16 | transport ingress records、parser output、router decisions、filter handoff、timestamps、latency/loss counters |
| 個人/隊伍 baseline profile (`user_or_team_baseline_profile`) | 16 | fitness baseline、expected pace、load、acclimatization、skill level、水/補給計畫、risk tolerance |
| 穿戴式生命徵象與 baseline (`wearable_vitals_and_baseline`) | 16 | heart rate、HRV/body battery/source values、activity/pace trend、baseline-relative thresholds、privacy scope |
| GPS/INS/DR 軌跡與 sensor records (`gps_ins_dr_estimates_or_sensor_vitals_record`) | 14 | GPS-only trajectory、INS/DR/PDR estimates、raw IMU/PDR/vitals records、trajectory-diff metrics |
| Safety candidate/admission state (`safety_candidate_or_admission_state`) | 12 | risk candidate status、admission decision、persistence state、operator review、no-mutation proof |
| 裝備/電量/資源 telemetry (`equipment_inventory_or_battery_telemetry`) | 10 | phone/watch/headlamp/powerbank battery、offline map state、food/water/fuel inventory、expected remaining time |
| 隊伍位置與最後回報 (`team_member_positions_and_last_heard`) | 9 | team member positions、last-heard timestamps、check-in schedule、rendezvous plan、comms state |
| 事故情境與授權 (`incident_context_or_authorization_ref`) | 8 | injury/lost/incident context、emergency playbook context、operator/留守 authorization ref before outbound action |
| 工具專屬 evidence 尚未驗證 (`tool_specific_evidence_not_verified`) | 8 | domain-specific source package 或 tool input contract 必須先定義並填入 |
| 完成旅程/事故紀錄 (`completed_journey_or_incident_record`) | 7 | completed journey log、warnings/events timeline、trajectory/corridor diff、incident package candidates、post-trip review notes |
| Review/provenance/conflict report (`review_queue_or_provenance_report`) | 5 | source provenance、review queue、conflict report、unanswered context requirements |

### 按主要缺資料分組

#### 目前位置 (`current_position`) - 24 題

- 需要補的資料：timestamped lat/lon/elevation、route progress、nearest CP/segment

| ID | Corpus Category | 問題 | 其他缺資料 | Recommended Tools |
| --- | --- | --- | --- | --- |
| seed-030 | risk_terrain | 哪些風險目前只是候選，不能觸發 Ln？ | GNSS 精度 (`gnss_accuracy`), 近期 INS/DR/PDR 狀態 (`ins_dr_recent_samples`), Safety candidate/admission state (`safety_candidate_or_admission_state`) | `scout.ai.live_navigation_state.assess.v0` (live navigation state assessment), `scout.ai.safety_boundary.explain.v0` (Scout safety-boundary explainer) |
| seed-041 | sensor_wearable | 目前有哪些 Sensor Logger observation？ | GNSS 精度 (`gnss_accuracy`), 近期 INS/DR/PDR 狀態 (`ins_dr_recent_samples`), Runtime ingress/router trace (`runtime_ingress_router_trace`) | `scout.ai.live_navigation_state.assess.v0` (live navigation state assessment), `scout.ai.runtime_ingress_status.search.v0` (runtime ingress/router/status search) |
| seed-042 | sensor_wearable | 目前有哪些 Sensor/Vitals records？ | GNSS 精度 (`gnss_accuracy`), 近期 INS/DR/PDR 狀態 (`ins_dr_recent_samples`), Runtime ingress/router trace (`runtime_ingress_router_trace`), 穿戴式生命徵象與 baseline (`wearable_vitals_and_baseline`) | `scout.ai.live_navigation_state.assess.v0` (live navigation state assessment), `scout.ai.energy_vitals.assess.v0` (energy/vitals advisory assessment), `scout.ai.runtime_ingress_status.search.v0` (runtime ingress/router/status search) |
| seed-059 | transport_router | 目前高頻資料適合 pipeline 還是 skill router？ | GNSS 精度 (`gnss_accuracy`), 近期 INS/DR/PDR 狀態 (`ins_dr_recent_samples`), Runtime ingress/router trace (`runtime_ingress_router_trace`) | `scout.ai.live_navigation_state.assess.v0` (live navigation state assessment), `scout.ai.runtime_ingress_status.search.v0` (runtime ingress/router/status search) |
| seed-061 | energy_vitals | 目前 energy reserve 狀態如何？ | GNSS 精度 (`gnss_accuracy`), 近期 INS/DR/PDR 狀態 (`ins_dr_recent_samples`) | `scout.ai.live_navigation_state.assess.v0` (live navigation state assessment) |
| seed-065 | energy_vitals | 目前有沒有 baseline-relative advisory？ | GNSS 精度 (`gnss_accuracy`), 近期 INS/DR/PDR 狀態 (`ins_dr_recent_samples`) | `scout.ai.live_navigation_state.assess.v0` (live navigation state assessment) |
| seed-073 | safety_admission | 目前是否有呼叫 /safety/*？ | GNSS 精度 (`gnss_accuracy`), 近期 INS/DR/PDR 狀態 (`ins_dr_recent_samples`), Safety candidate/admission state (`safety_candidate_or_admission_state`) | `scout.ai.live_navigation_state.assess.v0` (live navigation state assessment), `scout.ai.safety_boundary.explain.v0` (Scout safety-boundary explainer) |
| seed-077 | safety_admission | 目前有沒有不該觸發墜崖警報的點？ | GNSS 精度 (`gnss_accuracy`), 近期 INS/DR/PDR 狀態 (`ins_dr_recent_samples`), Safety candidate/admission state (`safety_candidate_or_admission_state`) | `scout.ai.live_navigation_state.assess.v0` (live navigation state assessment), `scout.ai.safety_boundary.explain.v0` (Scout safety-boundary explainer) |
| seed-091 | admin_debug_ai | Scout AI 目前使用哪個 provider？ | GNSS 精度 (`gnss_accuracy`), 近期 INS/DR/PDR 狀態 (`ins_dr_recent_samples`), Runtime ingress/router trace (`runtime_ingress_router_trace`) | `scout.ai.live_navigation_state.assess.v0` (live navigation state assessment), `scout.ai.runtime_ingress_status.search.v0` (runtime ingress/router/status search) |
| seed-095 | admin_debug_ai | 目前有哪些 deterministic tools 可用？ | GNSS 精度 (`gnss_accuracy`), 近期 INS/DR/PDR 狀態 (`ins_dr_recent_samples`) | `scout.ai.live_navigation_state.assess.v0` (live navigation state assessment) |
| seed-098 | admin_debug_ai | 哪些 context 目前缺失？ | GNSS 精度 (`gnss_accuracy`), 近期 INS/DR/PDR 狀態 (`ins_dr_recent_samples`), Runtime ingress/router trace (`runtime_ingress_router_trace`) | `scout.ai.live_navigation_state.assess.v0` (live navigation state assessment), `scout.ai.runtime_ingress_status.search.v0` (runtime ingress/router/status search) |
| field-011 | field_terrain_route | 前方是不是稜線轉折點？ | GNSS 精度 (`gnss_accuracy`), 近期 INS/DR/PDR 狀態 (`ins_dr_recent_samples`) | `scout.ai.live_navigation_state.assess.v0` (live navigation state assessment) |
| field-012 | field_terrain_route | 我是不是快接近崩壁或碎石坡？ | GNSS 精度 (`gnss_accuracy`), 近期 INS/DR/PDR 狀態 (`ins_dr_recent_samples`), 個人/隊伍 baseline profile (`user_or_team_baseline_profile`) | - |
| field-016 | field_terrain_route | 我現在是不是離主路太近但站在危險邊緣？ | GNSS 精度 (`gnss_accuracy`), 近期 INS/DR/PDR 狀態 (`ins_dr_recent_samples`) | `scout.ai.live_navigation_state.assess.v0` (live navigation state assessment) |
| field-021 | field_navigation | 我現在是不是偏離路線？ | GNSS 精度 (`gnss_accuracy`), 近期 INS/DR/PDR 狀態 (`ins_dr_recent_samples`) | `scout.ai.live_navigation_state.assess.v0` (live navigation state assessment) |
| field-022 | field_navigation | GPS 誤差會不會太大，不能相信？ | GNSS 精度 (`gnss_accuracy`), 近期 INS/DR/PDR 狀態 (`ins_dr_recent_samples`) | `scout.ai.live_navigation_state.assess.v0` (live navigation state assessment) |
| field-023 | field_navigation | IMU/PDR 推估跟 GPS 是否一致？ | GNSS 精度 (`gnss_accuracy`), 近期 INS/DR/PDR 狀態 (`ins_dr_recent_samples`), GPS/INS/DR 軌跡與 sensor records (`gps_ins_dr_estimates_or_sensor_vitals_record`) | `scout.ai.live_navigation_state.assess.v0` (live navigation state assessment), `scout.ai.ins_dr_trace.analyze.v0` (INS/DR trace and trajectory-diff analyzer) |
| field-024 | field_navigation | 我現在的方向是不是正在遠離主線？ | GNSS 精度 (`gnss_accuracy`), 近期 INS/DR/PDR 狀態 (`ins_dr_recent_samples`) | `scout.ai.live_navigation_state.assess.v0` (live navigation state assessment) |
| field-025 | field_navigation | 我是不是錯過轉彎點？ | GNSS 精度 (`gnss_accuracy`), 近期 INS/DR/PDR 狀態 (`ins_dr_recent_samples`), 個人/隊伍 baseline profile (`user_or_team_baseline_profile`) | `scout.ai.live_navigation_state.assess.v0` (live navigation state assessment) |
| field-028 | field_navigation | 我現在繼續下切是否危險？ | GNSS 精度 (`gnss_accuracy`), 近期 INS/DR/PDR 狀態 (`ins_dr_recent_samples`) | `scout.ai.live_navigation_state.assess.v0` (live navigation state assessment) |
| field-042 | field_energy_state | 我現在是不是太累不適合繼續下坡？ | GNSS 精度 (`gnss_accuracy`), 近期 INS/DR/PDR 狀態 (`ins_dr_recent_samples`), 穿戴式生命徵象與 baseline (`wearable_vitals_and_baseline`) | `scout.ai.live_navigation_state.assess.v0` (live navigation state assessment), `scout.ai.energy_vitals.assess.v0` (energy/vitals advisory assessment) |
| field-049 | field_energy_state | 我現在適合繼續上升嗎？ | GNSS 精度 (`gnss_accuracy`), 近期 INS/DR/PDR 狀態 (`ins_dr_recent_samples`) | `scout.ai.live_navigation_state.assess.v0` (live navigation state assessment), `scout.ai.energy_vitals.assess.v0` (energy/vitals advisory assessment) |
| field-058 | field_team_guardian | 隊伍目前誰最需要協助？ | GNSS 精度 (`gnss_accuracy`), 近期 INS/DR/PDR 狀態 (`ins_dr_recent_samples`), 隊伍位置與最後回報 (`team_member_positions_and_last_heard`) | `scout.ai.live_navigation_state.assess.v0` (live navigation state assessment), `scout.ai.team_status.assess.v0` (team status and留守 governance assessment) |
| field-065 | field_equipment_resource | 我現在是否該關閉耗電功能？ | GNSS 精度 (`gnss_accuracy`), 近期 INS/DR/PDR 狀態 (`ins_dr_recent_samples`) | `scout.ai.live_navigation_state.assess.v0` (live navigation state assessment) |

#### 即時天氣/預報與 TTL (`fresh_weather_or_nowcast_with_ttl`) - 18 題

- 需要補的資料：forecast/nowcast、rain/wind/fog/temp/daylight、valid time/TTL、route-local exposure context

| ID | Corpus Category | 問題 | 其他缺資料 | Recommended Tools |
| --- | --- | --- | --- | --- |
| seed-007 | pretrip_route | 哪些 CP 附近適合紮營？ | - | `scout.ai.weather_window.assess.v0` (weather window assessment) |
| seed-027 | risk_terrain | 哪些地方下雨後風險會變高？ | - | `scout.ai.weather_window.assess.v0` (weather window assessment) |
| seed-083 | weather_camp | 什麼時候應該提早紮營？ | - | `scout.ai.weather_window.assess.v0` (weather window assessment) |
| seed-084 | weather_camp | 哪些天氣資料是 forecast candidate？ | - | `scout.ai.weather_window.assess.v0` (weather window assessment) |
| seed-085 | weather_camp | 天氣建議能不能直接觸發安全狀態？ | - | `scout.ai.weather_window.assess.v0` (weather window assessment) |
| seed-087 | weather_camp | 哪些地點可能不適合紮營？ | - | `scout.ai.weather_window.assess.v0` (weather window assessment) |
| seed-088 | weather_camp | 天氣與地形風險是否重疊？ | - | `scout.ai.weather_window.assess.v0` (weather window assessment) |
| seed-089 | weather_camp | 是否需要延後出發？ | - | `scout.ai.route_readiness.assess.v0` (route readiness assessment), `scout.ai.weather_window.assess.v0` (weather window assessment) |
| seed-090 | weather_camp | 有哪些 weather evidence 缺少有效期限？ | - | `scout.ai.weather_window.assess.v0` (weather window assessment) |
| field-006 | field_pretrip | 哪些地方下雨後會變危險？ | - | `scout.ai.weather_window.assess.v0` (weather window assessment) |
| field-031 | field_weather_environment | 白牆下這段還適合走嗎？ | - | `scout.ai.weather_window.assess.v0` (weather window assessment) |
| field-033 | field_weather_environment | 日落前我還能到下一個安全點嗎？ | - | `scout.ai.weather_window.assess.v0` (weather window assessment) |
| field-034 | field_weather_environment | 這段如果起霧會不會容易失向？ | - | `scout.ai.weather_window.assess.v0` (weather window assessment) |
| field-035 | field_weather_environment | 今天的天氣窗口是否足夠？ | - | `scout.ai.weather_window.assess.v0` (weather window assessment) |
| field-036 | field_weather_environment | 溪水暴漲會不會阻斷路線？ | - | `scout.ai.route_readiness.assess.v0` (route readiness assessment), `scout.ai.weather_window.assess.v0` (weather window assessment) |
| field-037 | field_weather_environment | 這段下雨後會變成落石區嗎？ | - | `scout.ai.weather_window.assess.v0` (weather window assessment) |
| field-038 | field_weather_environment | 現在停下來會不會變冷太快？ | - | `scout.ai.weather_window.assess.v0` (weather window assessment) |
| field-039 | field_weather_environment | 風寒和濕衣是否已經構成風險？ | - | `scout.ai.weather_window.assess.v0` (weather window assessment) |

2026-06-24 routing update:

- `scout.ai.weather_window.assess.v0` remains the weather decision wrapper for
  this answerability class.
- Natural weather questions now expand to
  `scout.ai.cwa_environment.assess.v0` when prepared CWA evidence exists in the
  workspace.
- Rain, stream, wet terrain, rockfall, landslide, and weather-terrain compound
  questions also expand to `scout.ai.gee_environment.assess.v0`.
- These environment tools are candidate-only workspace readers. They do not
  perform live network fetches and cannot write runtime safety truth.

2026-06-24 fixture-backed retest against
`tests/fixtures/pretrip/projects/chilai_nanhua_day1`:

| ID | 問題 | Selected environment tools | Answerability |
| --- | --- | --- | --- |
| field-031 | 白牆下這段還適合走嗎？ | weather_window, CWA | evidence_available |
| field-032 | 現在風雨是否會放大失溫風險？ | weather_window, CWA, GEE | evidence_available |
| field-034 | 這段如果起霧會不會容易失向？ | weather_window, CWA | evidence_available |
| field-035 | 今天的天氣窗口是否足夠？ | weather_window, CWA | evidence_available |
| field-036 | 溪水暴漲會不會阻斷路線？ | weather_window, CWA, GEE | partial_evidence_with_missing_context |
| field-037 | 這段下雨後會變成落石區嗎？ | weather_window, CWA, GEE | partial_evidence_with_missing_context |
| field-039 | 風寒和濕衣是否已經構成風險？ | weather_window, CWA | partial_evidence_with_missing_context |
| seed-027 | 哪些地方下雨後風險會變高？ | weather_window, CWA, GEE | evidence_available |
| seed-088 | 天氣與地形風險是否重疊？ | weather_window, CWA, GEE | partial_evidence_with_missing_context |
| seed-089 | 是否需要延後出發？ | route_readiness, weather_window, CWA, GEE | evidence_available |

#### 個人/隊伍 baseline profile (`user_or_team_baseline_profile`) - 14 題

- 需要補的資料：fitness baseline、expected pace、load、acclimatization、skill level、水/補給計畫、risk tolerance

| ID | Corpus Category | 問題 | 其他缺資料 | Recommended Tools |
| --- | --- | --- | --- | --- |
| field-001 | field_pretrip | 這條路線對我的體能來說會不會太硬？ | 穿戴式生命徵象與 baseline (`wearable_vitals_and_baseline`) | `scout.ai.route_readiness.assess.v0` (route readiness assessment), `scout.ai.energy_vitals.assess.v0` (energy/vitals advisory assessment) |
| field-002 | field_pretrip | 我今天的配速有足夠 buffer 嗎？ | - | `scout.ai.route_readiness.assess.v0` (route readiness assessment) |
| field-009 | field_pretrip | 我需要準備多少水和補給？ | 穿戴式生命徵象與 baseline (`wearable_vitals_and_baseline`) | `scout.ai.route_readiness.assess.v0` (route readiness assessment) |
| field-010 | field_pretrip | 如果我晚出發一小時，是否還能安全完成？ | - | `scout.ai.route_readiness.assess.v0` (route readiness assessment) |
| field-026 | field_navigation | 我該回到上一個確定點嗎？ | - | - |
| field-040 | field_weather_environment | 我是不是該提前撤退？ | - | `scout.ai.weather_window.assess.v0` (weather window assessment) |
| field-041 | field_energy_state | 我的速度下降是不是異常？ | 穿戴式生命徵象與 baseline (`wearable_vitals_and_baseline`) | `scout.ai.energy_vitals.assess.v0` (energy/vitals advisory assessment) |
| field-044 | field_energy_state | 我是不是正在決策品質下降？ | 穿戴式生命徵象與 baseline (`wearable_vitals_and_baseline`) | `scout.ai.energy_vitals.assess.v0` (energy/vitals advisory assessment) |
| field-045 | field_energy_state | 我今天補水不足嗎？ | 穿戴式生命徵象與 baseline (`wearable_vitals_and_baseline`) | `scout.ai.route_readiness.assess.v0` (route readiness assessment), `scout.ai.energy_vitals.assess.v0` (energy/vitals advisory assessment) |
| field-046 | field_energy_state | 我補給吃得夠嗎？ | 穿戴式生命徵象與 baseline (`wearable_vitals_and_baseline`) | `scout.ai.route_readiness.assess.v0` (route readiness assessment) |
| field-047 | field_energy_state | 我是不是有高海拔不適風險？ | - | - |
| field-050 | field_energy_state | 我是不是該原地休息或下撤？ | 穿戴式生命徵象與 baseline (`wearable_vitals_and_baseline`) | `scout.ai.energy_vitals.assess.v0` (energy/vitals advisory assessment) |
| field-074 | field_lost_survival | 我該往稜線上移動找訊號嗎？ | - | `scout.ai.survival_incident_playbook.explain.v0` (survival/incident playbook explainer) |
| field-086 | field_accident_rescue | 我該移動到更開闊的地方嗎？ | - | - |

#### GPS/INS/DR 軌跡與 sensor records (`gps_ins_dr_estimates_or_sensor_vitals_record`) - 13 題

- 需要補的資料：GPS-only trajectory、INS/DR/PDR estimates、raw IMU/PDR/vitals records、trajectory-diff metrics

| ID | Corpus Category | 問題 | 其他缺資料 | Recommended Tools |
| --- | --- | --- | --- | --- |
| seed-031 | ins_dr_gps | GPS-only 軌跡和 INS/DR 軌跡差多少？ | - | `scout.ai.live_navigation_state.assess.v0` (live navigation state assessment), `scout.ai.ins_dr_trace.analyze.v0` (INS/DR trace and trajectory-diff analyzer) |
| seed-033 | ins_dr_gps | 哪些地方 INS/DR 需要重新 anchor？ | - | `scout.ai.ins_dr_trace.analyze.v0` (INS/DR trace and trajectory-diff analyzer) |
| seed-034 | ins_dr_gps | 哪些估計點 uncertainty 太大？ | - | `scout.ai.ins_dr_trace.analyze.v0` (INS/DR trace and trajectory-diff analyzer) |
| seed-035 | ins_dr_gps | 哪些軌跡偏差可能誤判離線？ | Safety candidate/admission state (`safety_candidate_or_admission_state`) | `scout.ai.ins_dr_trace.analyze.v0` (INS/DR trace and trajectory-diff analyzer), `scout.ai.safety_boundary.explain.v0` (Scout safety-boundary explainer) |
| seed-036 | ins_dr_gps | 有沒有 z 字形 DR 路徑？原因可能是什麼？ | - | `scout.ai.ins_dr_trace.analyze.v0` (INS/DR trace and trajectory-diff analyzer) |
| seed-037 | ins_dr_gps | 沒有 GPS 的地方是否仍有 PDR/IMU？ | - | `scout.ai.live_navigation_state.assess.v0` (live navigation state assessment), `scout.ai.ins_dr_trace.analyze.v0` (INS/DR trace and trajectory-diff analyzer) |
| seed-038 | ins_dr_gps | wearable PDR 能不能補室內路段？ | - | `scout.ai.live_navigation_state.assess.v0` (live navigation state assessment), `scout.ai.ins_dr_trace.analyze.v0` (INS/DR trace and trajectory-diff analyzer) |
| seed-039 | ins_dr_gps | 哪些 estimate 是 vendor-fused？ | - | `scout.ai.ins_dr_trace.analyze.v0` (INS/DR trace and trajectory-diff analyzer) |
| seed-040 | ins_dr_gps | 哪些 estimate 有 raw IMU baseline？ | - | `scout.ai.live_navigation_state.assess.v0` (live navigation state assessment), `scout.ai.ins_dr_trace.analyze.v0` (INS/DR trace and trajectory-diff analyzer) |
| seed-045 | sensor_wearable | 哪些資料是 pedometer/PDR？ | - | `scout.ai.live_navigation_state.assess.v0` (live navigation state assessment), `scout.ai.ins_dr_trace.analyze.v0` (INS/DR trace and trajectory-diff analyzer) |
| seed-050 | sensor_wearable | 哪些 sensor 資料被 router 派給 INS/DR？ | Runtime ingress/router trace (`runtime_ingress_router_trace`) | `scout.ai.ins_dr_trace.analyze.v0` (INS/DR trace and trajectory-diff analyzer), `scout.ai.runtime_ingress_status.search.v0` (runtime ingress/router/status search) |
| seed-076 | safety_admission | 哪些軌跡偏差可能是假警報？ | - | `scout.ai.ins_dr_trace.analyze.v0` (INS/DR trace and trajectory-diff analyzer) |
| field-019 | field_terrain_route | 歷史 GPX 這裡的軌跡分散嗎？ | - | `scout.ai.ins_dr_trace.analyze.v0` (INS/DR trace and trajectory-diff analyzer) |

#### 裝備/電量/資源 telemetry (`equipment_inventory_or_battery_telemetry`) - 10 題

- 需要補的資料：phone/watch/headlamp/powerbank battery、offline map state、food/water/fuel inventory、expected remaining time

| ID | Corpus Category | 問題 | 其他缺資料 | Recommended Tools |
| --- | --- | --- | --- | --- |
| field-061 | field_equipment_resource | 我的手機電量還夠求救嗎？ | 事故情境與授權 (`incident_context_or_authorization_ref`) | `scout.ai.equipment_resource.assess.v0` (equipment/resource assessment), `scout.ai.survival_incident_playbook.explain.v0` (survival/incident playbook explainer) |
| field-062 | field_equipment_resource | 手錶沒電後還能怎麼定位？ | - | `scout.ai.equipment_resource.assess.v0` (equipment/resource assessment) |
| field-063 | field_equipment_resource | 頭燈電量是否足夠走完下一段？ | - | `scout.ai.equipment_resource.assess.v0` (equipment/resource assessment) |
| field-064 | field_equipment_resource | 行動電源是否應該保留給通訊？ | - | `scout.ai.equipment_resource.assess.v0` (equipment/resource assessment) |
| field-066 | field_equipment_resource | 離線地圖是否已載入？ | - | `scout.ai.equipment_resource.assess.v0` (equipment/resource assessment) |
| field-067 | field_equipment_resource | 我是否有第二套導航工具？ | - | `scout.ai.equipment_resource.assess.v0` (equipment/resource assessment) |
| field-068 | field_equipment_resource | 裝備濕掉後是否該停止前進？ | - | `scout.ai.equipment_resource.assess.v0` (equipment/resource assessment) |
| field-069 | field_equipment_resource | 水剩多少才必須撤退？ | - | `scout.ai.route_readiness.assess.v0` (route readiness assessment), `scout.ai.weather_window.assess.v0` (weather window assessment), `scout.ai.equipment_resource.assess.v0` (equipment/resource assessment) |
| field-070 | field_equipment_resource | 瓦斯/食物是否足夠等待救援？ | 事故情境與授權 (`incident_context_or_authorization_ref`) | `scout.ai.equipment_resource.assess.v0` (equipment/resource assessment) |
| field-079 | field_lost_survival | 如果手機只剩 5%，怎麼用最有效？ | - | `scout.ai.equipment_resource.assess.v0` (equipment/resource assessment) |

#### Runtime ingress/router trace (`runtime_ingress_router_trace`) - 10 題

- 需要補的資料：transport ingress records、parser output、router decisions、filter handoff、timestamps、latency/loss counters

| ID | Corpus Category | 問題 | 其他缺資料 | Recommended Tools |
| --- | --- | --- | --- | --- |
| seed-043 | sensor_wearable | Apple Watch 傳回了哪些 sensor？ | - | `scout.ai.runtime_ingress_status.search.v0` (runtime ingress/router/status search) |
| seed-048 | sensor_wearable | 哪些 sensor 缺 timestamp？ | - | `scout.ai.runtime_ingress_status.search.v0` (runtime ingress/router/status search) |
| seed-049 | sensor_wearable | 哪些 message 有 gap 或 duplicate？ | - | `scout.ai.runtime_ingress_status.search.v0` (runtime ingress/router/status search) |
| seed-051 | transport_router | MQTT 現在有收到資料嗎？ | - | `scout.ai.runtime_ingress_status.search.v0` (runtime ingress/router/status search) |
| seed-052 | transport_router | MQTT message routing latency 是多少？ | - | `scout.ai.runtime_ingress_status.search.v0` (runtime ingress/router/status search) |
| seed-058 | transport_router | router 的 match reason 是什麼？ | - | `scout.ai.runtime_ingress_status.search.v0` (runtime ingress/router/status search) |
| seed-060 | transport_router | transport service 有沒有發送 outbound packet？ | - | `scout.ai.runtime_ingress_status.search.v0` (runtime ingress/router/status search) |
| seed-092 | admin_debug_ai | Pydantic AI 是否啟用？ | - | `scout.ai.runtime_ingress_status.search.v0` (runtime ingress/router/status search) |
| seed-093 | admin_debug_ai | assistant status 正常嗎？ | - | `scout.ai.runtime_ingress_status.search.v0` (runtime ingress/router/status search) |
| seed-094 | admin_debug_ai | 如果 provider 失敗，fallback 會怎麼回答？ | - | `scout.ai.runtime_ingress_status.search.v0` (runtime ingress/router/status search) |

#### Safety candidate/admission state (`safety_candidate_or_admission_state`) - 8 題

- 需要補的資料：risk candidate status、admission decision、persistence state、operator review、no-mutation proof

| ID | Corpus Category | 問題 | 其他缺資料 | Recommended Tools |
| --- | --- | --- | --- | --- |
| seed-014 | workspace_evidence | 哪些資料可以當 runtime safety truth？ | - | `scout.ai.safety_boundary.explain.v0` (Scout safety-boundary explainer) |
| seed-071 | safety_admission | 哪些 evidence 不可以直接觸發 Ln？ | - | `scout.ai.safety_boundary.explain.v0` (Scout safety-boundary explainer) |
| seed-072 | safety_admission | 哪些條件才可能進 safety admission？ | - | `scout.ai.safety_boundary.explain.v0` (Scout safety-boundary explainer) |
| seed-074 | safety_admission | 有沒有改 Phase 1 L0-L4 狀態？ | - | `scout.ai.safety_boundary.explain.v0` (Scout safety-boundary explainer) |
| seed-075 | safety_admission | 哪些 off-route 判斷仍需要 persistence？ | - | `scout.ai.safety_boundary.explain.v0` (Scout safety-boundary explainer) |
| seed-079 | safety_admission | 哪些候選風險需要 operator review？ | - | `scout.ai.safety_boundary.explain.v0` (Scout safety-boundary explainer) |
| seed-080 | safety_admission | 哪些 safety boundary 已被明確保留？ | - | `scout.ai.safety_boundary.explain.v0` (Scout safety-boundary explainer) |
| seed-100 | admin_debug_ai | 這個回答有沒有越界成 safety mutation 或 outbound send？ | - | `scout.ai.safety_boundary.explain.v0` (Scout safety-boundary explainer) |

#### 工具專屬 evidence 尚未驗證 (`tool_specific_evidence_not_verified`) - 8 題

- 需要補的資料：domain-specific source package 或 tool input contract 必須先定義並填入

| ID | Corpus Category | 問題 | 其他缺資料 | Recommended Tools |
| --- | --- | --- | --- | --- |
| seed-032 | ins_dr_gps | 哪些地方 GPS 訊號不好？ | - | `scout.ai.live_navigation_state.assess.v0` (live navigation state assessment) |
| field-027 | field_navigation | 我還能修正回主線嗎？ | - | `scout.ai.live_navigation_state.assess.v0` (live navigation state assessment) |
| field-029 | field_navigation | 這個偏離是正常 GPS drift 還是真的走錯？ | - | `scout.ai.live_navigation_state.assess.v0` (live navigation state assessment) |
| field-057 | field_team_guardian | 最後一次有效位置是哪裡？ | - | `scout.ai.team_status.assess.v0` (team status and留守 governance assessment) |
| field-071 | field_lost_survival | 我不確定自己在哪，第一步該做什麼？ | - | `scout.ai.survival_incident_playbook.explain.v0` (survival/incident playbook explainer) |
| field-072 | field_lost_survival | 我應該原地等待還是找路？ | - | `scout.ai.survival_incident_playbook.explain.v0` (survival/incident playbook explainer) |
| field-076 | field_lost_survival | 我要怎麼建立可視標記？ | - | `scout.ai.survival_incident_playbook.explain.v0` (survival/incident playbook explainer) |
| field-083 | field_accident_rescue | 我應該報座標還是地標？ | - | `scout.ai.survival_incident_playbook.explain.v0` (survival/incident playbook explainer) |

#### 隊伍位置與最後回報 (`team_member_positions_and_last_heard`) - 7 題

- 需要補的資料：team member positions、last-heard timestamps、check-in schedule、rendezvous plan、comms state

| ID | Corpus Category | 問題 | 其他缺資料 | Recommended Tools |
| --- | --- | --- | --- | --- |
| field-051 | field_team_guardian | 隊友距離我太遠了嗎？ | - | `scout.ai.team_status.assess.v0` (team status and留守 governance assessment) |
| field-052 | field_team_guardian | 後隊是不是停止移動太久？ | - | `scout.ai.team_status.assess.v0` (team status and留守 governance assessment) |
| field-053 | field_team_guardian | 我們是否已經形成隊伍分離事件？ | - | `scout.ai.team_status.assess.v0` (team status and留守 governance assessment) |
| field-054 | field_team_guardian | 有人沒抵達約定山屋，該怎麼辦？ | - | `scout.ai.team_status.assess.v0` (team status and留守 governance assessment) |
| field-056 | field_team_guardian | 我的定時回報是不是逾時了？ | - | `scout.ai.team_status.assess.v0` (team status and留守 governance assessment) |
| field-089 | field_accident_rescue | 哪些資訊要給留守人轉報？ | 事故情境與授權 (`incident_context_or_authorization_ref`) | `scout.ai.team_status.assess.v0` (team status and留守 governance assessment) |
| field-096 | field_post_trip | 這次是迷途、滑墜、資源不足還是隊伍治理問題？ | 完成旅程/事故紀錄 (`completed_journey_or_incident_record`) | `scout.ai.team_status.assess.v0` (team status and留守 governance assessment) |

#### 穿戴式生命徵象與 baseline (`wearable_vitals_and_baseline`) - 7 題

- 需要補的資料：heart rate、HRV/body battery/source values、activity/pace trend、baseline-relative thresholds、privacy scope

| ID | Corpus Category | 問題 | 其他缺資料 | Recommended Tools |
| --- | --- | --- | --- | --- |
| seed-006 | pretrip_route | 哪些 CP 附近適合休息？ | - | `scout.ai.energy_vitals.assess.v0` (energy/vitals advisory assessment) |
| seed-047 | sensor_wearable | 哪些資料是 heart rate 或 vitals？ | - | `scout.ai.energy_vitals.assess.v0` (energy/vitals advisory assessment) |
| seed-062 | energy_vitals | 哪些 vitals 只是 source value？ | - | `scout.ai.energy_vitals.assess.v0` (energy/vitals advisory assessment) |
| seed-068 | energy_vitals | 哪些 health evidence 只能進 pretrip/admin？ | - | `scout.ai.energy_vitals.assess.v0` (energy/vitals advisory assessment) |
| seed-069 | energy_vitals | Garmin Body Battery 能不能當 Scout truth？ | - | `scout.ai.energy_vitals.assess.v0` (energy/vitals advisory assessment) |
| seed-070 | energy_vitals | 哪些 vitals 需要 privacy boundary？ | - | `scout.ai.energy_vitals.assess.v0` (energy/vitals advisory assessment) |
| field-059 | field_team_guardian | 我們應該集合還是各自下撤？ | 隊伍位置與最後回報 (`team_member_positions_and_last_heard`) | `scout.ai.energy_vitals.assess.v0` (energy/vitals advisory assessment), `scout.ai.team_status.assess.v0` (team status and留守 governance assessment) |

#### 完成旅程/事故紀錄 (`completed_journey_or_incident_record`) - 6 題

- 需要補的資料：completed journey log、warnings/events timeline、trajectory/corridor diff、incident package candidates、post-trip review notes

| ID | Corpus Category | 問題 | 其他缺資料 | Recommended Tools |
| --- | --- | --- | --- | --- |
| field-091 | field_post_trip | 這次最早的風險訊號是什麼？ | - | `scout.ai.post_trip_review.assess.v0` (post-trip incident review assessment) |
| field-092 | field_post_trip | Scout 哪個 warning 應該更早出現？ | - | `scout.ai.post_trip_review.assess.v0` (post-trip incident review assessment) |
| field-097 | field_post_trip | 哪些資料應該進 incident package？ | - | `scout.ai.post_trip_review.assess.v0` (post-trip incident review assessment) |
| field-098 | field_post_trip | 這個案例應該變成 field case 嗎？ | - | `scout.ai.post_trip_review.assess.v0` (post-trip incident review assessment) |
| field-099 | field_post_trip | 哪些 spec 需要被更新？ | - | - |
| field-100 | field_post_trip | 下次行前規劃要改哪三件事？ | - | `scout.ai.post_trip_review.assess.v0` (post-trip incident review assessment) |

#### 事故情境與授權 (`incident_context_or_authorization_ref`) - 5 題

- 需要補的資料：injury/lost/incident context、emergency playbook context、operator/留守 authorization ref before outbound action

| ID | Corpus Category | 問題 | 其他缺資料 | Recommended Tools |
| --- | --- | --- | --- | --- |
| field-077 | field_lost_survival | 我應該保存哪些證據給搜救？ | - | `scout.ai.survival_incident_playbook.explain.v0` (survival/incident playbook explainer) |
| field-082 | field_accident_rescue | 求救訊息要包含哪些欄位？ | - | `scout.ai.survival_incident_playbook.explain.v0` (survival/incident playbook explainer) |
| field-084 | field_accident_rescue | 直升機是否有可能吊掛？ | - | `scout.ai.survival_incident_playbook.explain.v0` (survival/incident playbook explainer) |
| field-085 | field_accident_rescue | 這個地形搜救員能接近嗎？ | - | - |
| field-090 | field_accident_rescue | 救援不會立刻到，我們該怎麼撐過夜？ | - | `scout.ai.survival_incident_playbook.explain.v0` (survival/incident playbook explainer) |

#### Review/provenance/conflict report (`review_queue_or_provenance_report`) - 5 題

- 需要補的資料：source provenance、review queue、conflict report、unanswered context requirements

| ID | Corpus Category | 問題 | 其他缺資料 | Recommended Tools |
| --- | --- | --- | --- | --- |
| seed-019 | workspace_evidence | 哪些資料來源互相矛盾？ | - | `scout.ai.review_gap.assess.v0` (review/provenance gap assessor) |
| seed-020 | workspace_evidence | 哪些資料缺少 provenance？ | - | `scout.ai.review_gap.assess.v0` (review/provenance gap assessor) |
| seed-029 | risk_terrain | 哪些點需要人工複核？ | - | `scout.ai.review_gap.assess.v0` (review/provenance gap assessor) |
| seed-097 | admin_debug_ai | 這個回答引用了哪些 sources？ | - | `scout.ai.review_gap.assess.v0` (review/provenance gap assessor) |
| seed-099 | admin_debug_ai | 哪些 workspace 搜尋結果最相關？ | - | `scout.ai.review_gap.assess.v0` (review/provenance gap assessor) |

## 3. 健康/醫療 advisory-only

共 7 題。Scout AI 只能做 evidence framing 與風險提醒，不能做醫療診斷或治療指示。

| ID | Corpus Category | 問題 | 缺資料 | Recommended Tools |
| --- | --- | --- | --- | --- |
| seed-063 | energy_vitals | 哪些資料不能視為醫療診斷？ | - | - |
| seed-064 | energy_vitals | 心率資料能不能支持疲勞判斷？ | 穿戴式生命徵象與 baseline (`wearable_vitals_and_baseline`) | `scout.ai.energy_vitals.assess.v0` (energy/vitals advisory assessment) |
| field-032 | field_weather_environment | 現在風雨是否會放大失溫風險？ | 即時天氣/預報與 TTL (`fresh_weather_or_nowcast_with_ttl`) | `scout.ai.weather_window.assess.v0` (weather window assessment) |
| field-043 | field_energy_state | 心率偏高代表需要休息嗎？ | 穿戴式生命徵象與 baseline (`wearable_vitals_and_baseline`) | `scout.ai.energy_vitals.assess.v0` (energy/vitals advisory assessment) |
| field-048 | field_energy_state | 我該做高山症自評嗎？ | 個人/隊伍 baseline profile (`user_or_team_baseline_profile`), 穿戴式生命徵象與 baseline (`wearable_vitals_and_baseline`) | `scout.ai.energy_vitals.assess.v0` (energy/vitals advisory assessment) |
| field-081 | field_accident_rescue | 我滑倒受傷但位置清楚，該怎麼回報？ | 隊伍位置與最後回報 (`team_member_positions_and_last_heard`), 事故情境與授權 (`incident_context_or_authorization_ref`) | `scout.ai.team_status.assess.v0` (team status and留守 governance assessment) |
| field-087 | field_accident_rescue | 移動傷者是否會更危險？ | 事故情境與授權 (`incident_context_or_authorization_ref`) | `scout.ai.survival_incident_playbook.explain.v0` (survival/incident playbook explainer) |

## 4. 通報/報案/啟動/發送 blocked

共 6 題。Scout AI 可解釋流程、欄位與授權需求，但不得自行通知、報案、啟動模式、發送封包或改安全狀態。

| ID | Corpus Category | 問題 | 缺資料 | Allowed Response |
| --- | --- | --- | --- | --- |
| field-030 | field_navigation | 是否需要啟動精確導航模式？ | 目前位置 (`current_position`), GNSS 精度 (`gnss_accuracy`), 近期 INS/DR/PDR 狀態 (`ins_dr_recent_samples`) | Explain required fields/playbook/authorization only; no outbound send or safety mutation. |
| field-055 | field_team_guardian | 是否要通知留守人？ | 隊伍位置與最後回報 (`team_member_positions_and_last_heard`) | Explain required fields/playbook/authorization only; no outbound send or safety mutation. |
| field-060 | field_team_guardian | 留守人需要哪些資訊才能報案？ | 隊伍位置與最後回報 (`team_member_positions_and_last_heard`), 事故情境與授權 (`incident_context_or_authorization_ref`) | Explain required fields/playbook/authorization only; no outbound send or safety mutation. |
| field-078 | field_lost_survival | 我現在應該多久回報一次位置？ | 目前位置 (`current_position`), GNSS 精度 (`gnss_accuracy`), 近期 INS/DR/PDR 狀態 (`ins_dr_recent_samples`), 隊伍位置與最後回報 (`team_member_positions_and_last_heard`) | Explain required fields/playbook/authorization only; no outbound send or safety mutation. |
| field-080 | field_lost_survival | 我該把目前位置分享給誰？ | 目前位置 (`current_position`), GNSS 精度 (`gnss_accuracy`), 近期 INS/DR/PDR 狀態 (`ins_dr_recent_samples`), 個人/隊伍 baseline profile (`user_or_team_baseline_profile`) | Explain required fields/playbook/authorization only; no outbound send or safety mutation. |
| field-088 | field_accident_rescue | 我們是否需要建立現場指揮角色？ | - | Explain required fields/playbook/authorization only; no outbound send or safety mutation. |
