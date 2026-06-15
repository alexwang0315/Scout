# P0/P1/P2 Source Catalog

Use P0/P1 entries as discovery scope for Scout route-context briefing work. They are not fixed route URLs. Concrete evidence URLs must be discovered from search, operator-provided source lists, or source-specific adapters.

Use P2 entries as Scout-owned workspace evidence categories. They are not public web sources and usually do not have URLs; preserve workspace path/hash/capture provenance and privacy/review state instead.

## P0 Baseline Sources

| Tier | Source | Family |
| --- | --- | --- |
| P0 | 林業及自然保育署自然步道資料 | official_baseline |
| P0 | 台灣山林悠遊網開放資料 | official_baseline |
| P0 | 臺灣登山申請一站式服務網 | official_baseline |
| P0 | 國家公園路線開放狀態 | official_status |
| P0 | 內政部國土測繪中心 DEM / DTM / 地形圖 | terrain_baseline |
| P0 | 中央氣象署 CODiS / 開放資料 | weather_baseline |
| P0 | NCDR 災害潛勢資料 | hazard_baseline |
| P0 | 消防署山域事故救援案件 | incident_baseline |
| P0 | TBN 台灣生物多樣性網絡 | natural_baseline |
| P0 | 中研院臺灣百年歷史地圖 | historical_map_baseline |

## P1 Expansion Sources

| Tier | Source | Family |
| --- | --- | --- |
| P1 | 國家文化記憶庫 | cultural_expansion |
| P1 | 臺灣記憶 | historical_expansion |
| P1 | 原住民族古道空間資訊網 | cultural_spatial_expansion |
| P1 | 地質雲 | geology_expansion |
| P1 | OpenStreetMap / Overpass / OSM full-history | map_expansion |
| P1 | 魯地圖 | map_expansion |
| P1 | 地圖產生器 / 山友 GPX | community_route_seed |
| P1 | 健行筆記 | community_article_evidence |
| P1 | Hikingbook | community_route_evidence |
| P1 | 登山補給站 | community_article_evidence |

## P2 Scout-Owned Evidence

| Tier | Source | Family |
| --- | --- | --- |
| P2 | 使用者實際 GPX / completed trip GPX | scout_completed_track |
| P2 | 偏航紀錄 | scout_deviation_record |
| P2 | 停留點 / 休息點 / 營地停留 | scout_dwell_record |
| P2 | 拍照點 | scout_photo_point |
| P2 | 語音註記 | scout_voice_note |
| P2 | IMU / PDR 異常 | scout_motion_evidence |
| P2 | 氣壓高度變化 | scout_barometric_altitude |
| P2 | 前鋒 / 後衛距離 | scout_team_spacing |
| P2 | 隊伍拉長紀錄 | scout_team_stretch |
| P2 | 使用者回報「值得停」或「不值得停」 | scout_stop_worthiness_feedback |
| P2 | Scout action log / 黑盒子事件紀錄 | scout_action_log |

## Context Layers

| Layer | Include |
| --- | --- |
| historical | 古道、警備道、駐在所、隘勇線、伐木路、產業道路、舊聚落、日治時期設施 |
| cultural | 原住民族地名、舊社、獵徑、地方傳說、土地使用變遷 |
| natural | 林相變化、植被帶、特殊植物、鳥類、溪流、地質、岩層 |
| terrain | 稜線、鞍部、谷線、崩壁、溪谷、展望點、風口 |
| seasonal | 花期、楓紅、雲海、溪水期、雨季、蚊蟲、芒草、低溫 |
| observation_point | 值得短暫停留觀察的點；這不是停留授權或 runtime safety truth |
| scout_owned | completed trip GPX、偏航、停留、照片、語音、IMU/PDR、氣壓高度、隊伍距離、隊伍拉長、使用者 stop-worthiness 回報、Scout action log |

## P2 Provenance Fields

P2 evidence should carry these fields when available:

| Field | Meaning |
| --- | --- |
| `source_tier` | Always `P2` for Scout-owned evidence |
| `source_family` | One of the P2 families above |
| `artifact_path` | Workspace-relative path to the source artifact |
| `artifact_sha256` | Hash of the source artifact or normalized evidence file |
| `captured_at` | Original capture time or trip/event time |
| `device_id` | Device attribution when safe to expose |
| `actor_id` | User/team attribution when safe to expose |
| `privacy` | `private`, `scout_local`, `redacted`, or `export_summary` |
| `review_state` | `unreviewed`, `ai_suggested`, `human_reviewed`, or `approved_for_package` |
| `route_binding` | Matched checkpoint, segment, route distance, or geometry reference |

## Source Use Rules

- Prefer P0 sources for baseline facts: route metadata, permit/status, terrain, weather, hazard, incident, natural and historical map baselines.
- Use P1 sources for expansion: route nicknames, repeated community descriptions, cultural context, old-place stories, geology, OSM/Overpass features, and community route evidence.
- Use unreviewed P2 Scout/user data only as route-context seeds, briefing caveats, or private admin evidence. Reviewed P2 may become route notes, observation points, pace-fit context, or next-trip pretrip suggestions.
- Preserve `source_tier`, `source_family`, URL or artifact path, retrieval/capture time, hash/provenance, privacy/review state, and candidate-only boundary in every generated artifact.
- Scout-local/admin HTML may include raw or detailed P2 evidence when operator intent and access boundary are clear. If exporting outside Scout, create a separate redacted/shareable variant.
