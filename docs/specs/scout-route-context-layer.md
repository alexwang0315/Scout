# Scout Route Context Layer

## Purpose

Scout Route Context Layer turns an imported route from a GPX line into
candidate-only route context evidence. It supports Scout AI answers about why a
route matters, what the route passes through, where an observation may be worth
considering, and what source gaps remain before a user or operator can trust the
answer.

This layer is not a navigation authority and does not create runtime safety
truth. It is an offline-first pretrip evidence layer.

## Scope

The layer aligns with `SCOUT_OUTDOOR_AI_AGENT_STANDARD` Sec. 6 Route Context
Intelligence and the `scout-workspace-layout.md` Outdoor AI Agent Data
Placement contract.

See `scout-route-context-intelligence-implementation.md` for the current Scout
AI, skill, workspace-cache, and offline briefing regeneration behavior.

It covers these context families:

- historical: old trails, guard roads, police stations, forestry roads, old
  settlements, and historical facilities.
- cultural: indigenous place names, old communities, hunting paths, local
  stories, and land-use change.
- natural: forest type, vegetation belts, wildlife, streams, geology, and
  ecological observations.
- terrain: ridges, saddles, valleys, collapses, cliffs, gullies, viewpoints,
  and wind gaps.
- seasonal: flowering, maple season, cloud sea, rainy season, low temperature,
  grass, insects, and water seasonality.
- observation point: candidate places where a short stop may be meaningful, but
  only after contextual permission and route-risk checks.

## Non-Goals

- Do not call `/safety/*`.
- Do not mutate Phase 1 runtime state.
- Do not write Phase 2 Brain observed facts.
- Do not treat model output as field truth.
- Do not fetch live network sources in fixture-backed tests.
- Do not expose sensitive cultural or private locations with exact coordinates
  before human review.

## Workspace Outputs

After GPX import and MCP synthesis, a developer or operator may run the route
context collector. In the full Scout rebuild flow, it should run after layer
preparation as well, so `web_case_evidence` and `raster_label_evidence` can be
folded into the final local pack. The collector writes:

```text
normalized/context/route_context/
  route_context_evidence.json
  source_manifest.json
  route_context_pack.json
  crawl_seed_plan.json
outputs/briefings/
  route_context_briefing.html
candidates/
  route_context_points.json
```

`route_context_evidence.json` is the provenance and collection summary.
`source_manifest.json` is the source status, hash, cache, and missing-source
report. `route_context_pack.json` is the offline pack index used by Scout AI
tools. `crawl_seed_plan.json` records route-wide search seeds and route-note
seeds for later crawler/connector runs. `route_context_briefing.html` is the
reader-facing briefing for operators. `route_context_points.json` is the
candidate point list for map/UI/review.

## Route Context Briefing Skill

Scout provides a repo-local Codex skill for this workflow:

```text
.agents/skills/scout-route-context-briefing/
  SKILL.md
  agents/openai.yaml
  references/source-catalog.md
```

Use `$scout-route-context-briefing` when an operator asks for a route context
briefing HTML, a P0/P1 source discovery plan, public web evidence collection,
or regenerated route-context artifacts for a Scout workspace.

The skill is an orchestration guide, not a separate data source. It must call
the same workspace tools described below and must preserve the same boundaries:
candidate-only, no `/safety/*`, no runtime mutation, no Phase 2 Brain fact
writeback, and no raw HTML or large scraped-text embedding.

The skill reference `references/source-catalog.md` is the human-readable source
catalog. It should stay aligned with the source catalog embedded in
`pretrip_p0_p1_source_collection.py`.

## Input Sources

The first MVP reads only workspace-local artifacts and records source tiers:

- P0 baseline sources: Forestry and Nature Conservation Agency trail data,
  Taiwan Mountain Forest open data, the mountain permit portal, national park
  route status, NLSC DEM/DTM/topographic maps, CWA CODiS/open data, NCDR
  disaster potential data, Fire Agency mountain rescue cases, TBN biodiversity
  data, and Academia Sinica historical maps.
- P1 expansion sources: National Culture Memory Bank, Taiwan Memory,
  indigenous trail spatial data, Geology Cloud, OSM/Overpass/full-history,
  RudyMap, map-generator or hiker GPX, Hiking Biji, Hikingbook, and
  登山補給站.
- P2 Scout-owned sources: completed user GPX, off-route records, stay points,
  photo points, voice notes, IMU anomalies, barometric altitude changes,
  front/rear team distance, team stretch records, and user feedback such as
  worth-stopping or not-worth-stopping.

Current local artifacts:

- `outputs/mcp/mcp_candidates.json`
- `outputs/mcp/named_point_evidence.json`
- `outputs/mcp/mcp_ocr_labels.json`
- `candidates/route_note_candidates.json`
- `outputs/layers/normalized/web_case_evidence.json`
- `outputs/layers/normalized/raster_label_evidence.geojson`
- `outputs/import_manifest.json`
- `normalized/routes/route_summary.json`

Missing optional sources must be recorded as source gaps, not hidden.

Route notes are P2 seed material by default. They may seed P0/P1 searches, but
they should not become briefing conclusions or representative route-context
points unless a human explicitly promotes them or another source corroborates
the point. For the Chilai/Nanhua alpha workspace, the broad route keyword seed is
`chilai_nanhua_day1` plus `奇萊-南華`, `奇萊南華`, and `奇萊南峰 南華山`.

Future source connectors may add official trails, historical maps, cultural
archives, biodiversity data, weather/season evidence, disaster records, and
Scout field observations. Those connectors must write workspace-local artifacts
first; Scout AI should read the local pack before calling remote tools.

## P0/P1 Source Discovery Contract

P0/P1 sources are discovery scope, not route-specific defaults.

The default catalog contains national, regional, or community-scale sources:

- P0 `official_baseline`: 林業及自然保育署自然步道資料、台灣山林悠遊網開放資料、臺灣登山申請一站式服務網.
- P0 `official_status`: 國家公園路線開放狀態.
- P0 `terrain_baseline`: 內政部國土測繪中心 DEM / DTM / 地形圖.
- P0 `weather_baseline`: 中央氣象署 CODiS / 開放資料.
- P0 `hazard_baseline`: NCDR 災害潛勢資料.
- P0 `incident_baseline`: 消防署山域事故救援案件.
- P0 `natural_baseline`: TBN 台灣生物多樣性網絡.
- P0 `historical_map_baseline`: 中研院臺灣百年歷史地圖.
- P1 `cultural_expansion`: 國家文化記憶庫.
- P1 `historical_expansion`: 臺灣記憶.
- P1 `cultural_spatial_expansion`: 原住民族古道空間資訊網.
- P1 `geology_expansion`: 地質雲.
- P1 `map_expansion`: OpenStreetMap / Overpass / OSM full-history、魯地圖.
- P1 `community_route_seed`: 地圖產生器 / 山友 GPX.
- P1 `community_article_evidence`: 健行筆記、登山補給站.
- P1 `community_route_evidence`: Hikingbook.

The catalog is used to search or choose adapters. It must not be counted as
evidence by itself.

Concrete evidence URLs must come from one of these sources:

- operator-provided `--source-url`;
- operator-provided `--source-list-html`;
- a future search adapter output that records query, source family, URL, and
  retrieval metadata.

If no concrete URL is provided, `pretrip_p0_p1_source_collection` should produce
a plan with `planned_requires_source_discovery`, `source_count = 0`, and no
network calls. This is a valid planning result but not evidence.

Route-specific pages, such as a particular mountain hut announcement or a
specific community article, may be collected only after discovery. They must not
become global defaults for other routes.

## Web Evidence Collection

The bounded web evidence collector writes the existing map-preparation refs:

```text
outputs/layers/plans/web_case_query_plan.json
outputs/layers/normalized/web_case_evidence.json
```

Plan-only, no network:

```bash
PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python -m pretrip_p0_p1_source_collection \
  --project-root <workspace-project-root> \
  --dry-run \
  --json
```

Fetch concrete URLs from an HTML source list:

```bash
PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python -m pretrip_p0_p1_source_collection \
  --project-root <workspace-project-root> \
  --source-list-html <html-with-source-links> \
  --allow-network-fetch \
  --timeout-seconds 20 \
  --json
```

Fetch known concrete URLs directly:

```bash
PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python -m pretrip_p0_p1_source_collection \
  --project-root <workspace-project-root> \
  --source-url <url> \
  --source-url <url> \
  --allow-network-fetch \
  --timeout-seconds 20 \
  --json
```

The collector stores only bounded snippets, source status, hashes, and
provenance. It must not store raw HTML in JSON. It must mark:

- `candidate_only = true`
- `requires_human_review = true`
- `runtime_safety_truth = false`
- `raw_html_embedded = false`
- `large_scraped_text_embedded = false`

## Orchestration Order

For a complete pretrip workspace rebuild:

```text
pretrip_import
  -> pretrip_layer_preparation
  -> pretrip_route_context_collection
  -> verify_pretrip_workspace_spec_alignment
```

`pretrip_route_context_collection` remains safe to call immediately after import
for a partial MCP/named-point/route-note pack, but the canonical deployable pack
is the post-layer-preparation output.

After concrete P0/P1 web evidence is collected, route-context compilation is:

```bash
PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python -m pretrip_route_context_collection \
  --project-root <workspace-project-root> \
  --route-keyword "<route keyword>" \
  --json
```

When written artifacts should be checked against a workspace:

```bash
PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python tools/verify_pretrip_workspace_spec_alignment.py \
  --workspace-root <workspace-root> \
  --project-id <project-id> \
  --admin-base-url <admin-base-url> \
  --admin-bearer-token-file <token-file> \
  --allow-network-calls
```

## Data Model

Each `route_context_points.json` point must include:

- `candidate_id`
- `source_candidate_id`
- `display_label`
- `context_kind`
- `sec6_layers`
- `evidence_families`
- `lat`, `lon`, `distance_m` when available
- `sensitivity_level`
- `display_policy`
- `source_freshness`
- `observation_score`
- `stop_advisory_candidate`
- `source_refs`
- `candidate_only = true`
- `runtime_safety_truth = false`
- `phase1_runtime_mutation_allowed = false`
- `phase2_brain_writeback_allowed = false`
- `source_tier`
- `promotion_basis`

The `observation_score` is a pretrip candidate score:

```text
observation_score = observation_value - risk_penalty
```

It does not grant permission to stop. A short-stop recommendation must still go
through contextual permission and route-risk checks.

## Sensitive Data Policy

Sensitivity levels:

- `public`: label and exact candidate coordinate can be shown.
- `cultural_review`: cultural context that should be reviewed before exact
  coordinate display.
- `sensitive`: old community, hunting path, indigenous context, or similar
  location where precise display should be fuzzy.
- `restricted`: sacred, burial, taboo, private, or restricted context; exact
  coordinate should be hidden or reduced to area-level display.

Sensitive and restricted points must remain review-only until a human or
authorized source policy allows display.

## Query Policy

Scout AI should answer route context questions in this order:

1. Local route context pack.
2. Local route context points and source manifest.
3. Local route summary and map/risk artifacts.
4. Remote source connector only if explicitly allowed.
5. Fallback answer with uncertainty and source gaps.

The answer must disclose source limits. If the pack has only candidate evidence,
the answer must say so.

## MVP Acceptance

- Running the collector after GPX import writes route context evidence, source
  manifest, context pack, crawl seed plan, route context points, and the HTML
  route context briefing.
- Missing web/raster evidence is visible in `source_manifest.json`.
- MCP and named-point evidence are merged without losing source provenance.
- Route notes are filtered to meaningful crawler seeds by default and are not
  promoted into representative context points unless explicitly requested.
- Sensitive cultural labels receive fuzzy or hidden coordinate display policy.
- Existing `scout.ai.route_context.assess.v0` can read the canonical
  `candidates/route_context_points.json`.
- Tests are fixture-backed and do not require live network.
- `$scout-route-context-briefing` exists as a repo-local skill and points to the
  same source catalog and tools as this spec.
- Default P0/P1 source catalog entries are not route-specific URLs and are not
  counted as fetched evidence.
- `pretrip_p0_p1_source_collection` returns
  `planned_requires_source_discovery` with zero source/evidence count when no
  concrete URLs are provided.
