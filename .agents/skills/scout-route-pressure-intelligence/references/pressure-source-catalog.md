# Route Pressure Source Catalog

Use this reference when `$scout-route-pressure-intelligence` is asked to collect
public pressure evidence. These are discovery scopes, not route-specific
defaults.

## P0 Official / Baseline Pressure Sources

| Source | Family | Use For |
| --- | --- | --- |
| 林業及自然保育署自然步道資料 | official_baseline | Trail distance, route class, official notes, trail GPX/KML links |
| 台灣山林悠遊網開放資料 | official_baseline | Official trail attributes, difficulty descriptions, communication points |
| 臺灣登山申請一站式服務網 | official_baseline | Permit/bed status, route-open dashboard, incident dashboard |
| 國家公園路線開放狀態 | official_status | Park route status and controlled-area changes |
| 天池山莊 / Forestry route notices | official_forest_notice | Route-specific openings, closures, line-change or difficulty notices |
| 地方消防局山域事故 / 即時災情 | incident_local_baseline | Regional rescue dispatch, local terrain/weather constraints, location clues |
| 內政部消防署山水域救援統計 | incident_baseline | National accident trend and cause categories |
| 政府資料開放平臺山域事故清冊 | incident_open_data_baseline | Structured incident records, route/place names, time-to-rescue fields |
| NCDR 災害潛勢資料 | hazard_baseline | Landslide, debris-flow, slope or disaster-potential context |
| 內政部國土測繪中心 DEM / DTM / 地形圖 | terrain_baseline | Terrain profile, slope, contours, hillshade, route-distance anchoring |
| 中央氣象署 CODiS / 開放資料 | weather_baseline | Rain, temperature, wind, daylight/weather context |
| 地質雲 | geology_expansion | Geological sensitivity and route-region terrain interpretation |
| 尋路・循路－臺灣原住民族古道空間資訊網 | cultural_trail_baseline | Historic trail baseline and cultural route context |

## P1 Community / Expert Pressure Sources

| Source | Family | Use For |
| --- | --- | --- |
| 健行筆記 | community_article_evidence | Repeated named points, route-profile images, route difficulty language |
| Hikingbook | community_route_evidence | Public GPX, waypoint, split-pace, pack/RPE evidence when visible |
| PTT Hiking | community_article_evidence | Public trip reports, pace logs, difficult-section consensus |
| 登山補給站 | community_article_evidence | Older trip reports, route timing, named points |
| 地圖產生器 / 山友 GPX | community_route_seed | Public route geometry and route-note seed evidence |
| OpenStreetMap / Overpass / OSM full-history | map_expansion | Route topology, bridges, shelters, paths, communication-linked features |
| 魯地圖 | map_expansion | Community map labels and named-place expansion |
| 中華民國山難救助協會 / regional rescue associations | rescue_training_reference | Rescue/training perspective, terrain-reading terms, risk education |
| 跑山獸 / 山小白 / reviewed expert public media | field_rescue_expert_observation | Expert route/risk interpretation, rescue-process or terrain warnings |
| Public YouTube / Instagram / Facebook / Threads route posts | community_media_evidence | Visual evidence and public comments; use only with review and provenance |

## Pressure Signal Terms

Use these as extraction signals. Do not let one keyword alone create a Boss.

| Class | Terms |
| --- | --- |
| collapse / exposure | 崩壁, 崩塌, 落石, 斷崖, 峭壁, 暴露, 地滑 |
| technical passage | 拉繩, 吊橋, 棧橋, 碎石, 泥濘, 濕滑, 陡下, 陡上 |
| route ambiguity | 路跡不明, 高繞, 岔路, 迷路, 箭竹, 芒草, 隱蔽 |
| physiology / pacing | 重裝, 長距離, 喘, 耗力, 抽筋, 高山症, 後段疲勞 |
| rescue friction | 無訊號, 定位不良, 救援困難, 搜救時間長, 下切溪谷 |
| weather sensitivity | 颱風, 豪雨, 大雨後, 溪水暴漲, 低溫, 強風, 日照不足 |

## Confidence Rules

- `high`: at least one P0 support plus two independent P1 sources, route-distance
  anchor, and terrain/risk support.
- `medium`: repeated P1 support or one P0 support with clear route binding, but
  incomplete source-family coverage.
- `low`: social/video-only, single-source, old/stale, or coordinate-uncertain.
- `rest_context_only`: huts, water, camps, temples, large rest areas, or scenic
  points without independent technical/terrain/incident support.

## Route Binding Rules

- Prefer Overpass/risk-ribbon route distance as the centerline.
- Use public GPX and historical/user GPX as timing/behavior evidence only after
  projection to the centerline.
- Flag GPX spans with long straight-line gaps, power-off discontinuities, or
  implausible movement as `low_interpretability`.
- For route-profile images, record source URL, image URL or local ref, axis
  interpretation, and whether distances are estimated from the image.
