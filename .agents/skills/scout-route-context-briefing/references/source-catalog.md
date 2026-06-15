# P0/P1 Source Catalog

Use these as discovery scope for Scout route-context briefing work. They are not fixed route URLs. Concrete evidence URLs must be discovered from search, operator-provided source lists, or source-specific adapters.

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

## Context Layers

| Layer | Include |
| --- | --- |
| historical | 古道、警備道、駐在所、隘勇線、伐木路、產業道路、舊聚落、日治時期設施 |
| cultural | 原住民族地名、舊社、獵徑、地方傳說、土地使用變遷 |
| natural | 林相變化、植被帶、特殊植物、鳥類、溪流、地質、岩層 |
| terrain | 稜線、鞍部、谷線、崩壁、溪谷、展望點、風口 |
| seasonal | 花期、楓紅、雲海、溪水期、雨季、蚊蟲、芒草、低溫 |
| observation_point | 值得短暫停留觀察的點；這不是停留授權或 runtime safety truth |

## Source Use Rules

- Prefer P0 sources for baseline facts: route metadata, permit/status, terrain, weather, hazard, incident, natural and historical map baselines.
- Use P1 sources for expansion: route nicknames, repeated community descriptions, cultural context, old-place stories, geology, OSM/Overpass features, and community route evidence.
- Use P2 Scout/user data only as seeds unless a reviewed package explicitly promotes it.
- Preserve `source_tier`, `source_family`, URL, retrieval time, hash/provenance, and candidate-only boundary in every generated artifact.
