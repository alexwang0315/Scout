# Spec: Pretrip Major Critical Point Synthesis

## Status

Draft for the next alpha branch.

`Major Critical Point`（MCP，主要關鍵點） is a compressed pretrip checkpoint
layer built from public route evidence, reference GPX, offline maps, OCR labels,
existing Scout CP candidates, terrain/risk outputs, and Pydantic AI structured
extraction.

This spec exists because the current CP candidate count can be very large. A
large candidate set is useful for review, but it contradicts the word
"critical" when shown directly to users. MCP is the human-scale layer: a small,
representative set of route decision points that hikers can understand, review,
share, and use for pacing.

## Objective

Build an evidence-backed synthesis pipeline that can:

- search public route information along a planned route;
- detect official and unofficial named points（NP，named point / 命名點） such as
  `黑水塘`, `軟腳坡`, local fork names, collapses, viewpoints, and water points;
- combine those named points with Scout-generated CP, GIS perception, terrain,
  risk, OSM, GPX, and OCR evidence;
- promote only a compact subset into MCP candidates;
- keep every MCP candidate pretrip-only until human review;
- avoid turning search results, OCR text, or model output into runtime safety
  truth.

## Position In Scout

```text
reference GPX / offline map / route guide / public web pages / OCR labels
  -> source retrieval and normalization
  -> NP extraction and evidence counting
  -> Scout CP / terrain / risk / OSM alignment
  -> MCP synthesis
  -> human review
  -> reviewed planning package
  -> later departure gate / runtime handoff
```

MCP does not replace:

- dense CP candidates;
- route geometry;
- Phase 1 checkpoint arrival;
- MissionGraph progress;
- risk score points;
- review queue items.

MCP is an additional planning abstraction for readability and decision-making.

## Key Terms

### Checkpoint Candidate（CP 候選）

A candidate point generated from GPX, GIS perception, OSM, terrain/risk, route
notes, or human edits. CP can be dense and review-heavy.

### Named Point（NP，命名點）

A place name repeatedly mentioned in public or user-supplied evidence. NP may be
official, colloquial, map-label-derived, or community slang. Examples include
water pools, informal slopes, named forks, collapse sections, scenic viewpoints,
and mobile reception points.

### Major Critical Point（MCP，主要關鍵點）

A compact, representative point selected from CP/NP/evidence clusters. MCP must
have enough route significance, evidence support, spatial separation, and human
review readiness to appear in the primary pretrip route story.

### Source Family（來源家族）

A named source class used for coverage checks. First alpha source families:

- `ptt_hiking`;
- `hiking_biji`;
- `sunriver_culture`;
- `public_web`;
- `reference_gpx`;
- `offline_map_ocr`;
- `scout_generated_cp`;
- `terrain_risk`.

## MCP Definition

An MCP candidate should satisfy all required gates.

### Gate A: Route-Significant Type

The point must represent at least one route-significant class:

1. fork / junction（岔路）;
2. camp, hut, shelter, building, road-end, or other human-made structure;
3. water source or water-collection decision point;
4. extreme terrain hazard, such as major collapse wall, exposed traverse,
   rockfall chute, landslide, cliff, or high-risk detour;
5. hidden forest, poor visibility, confusing route, or trail-loss-prone section;
6. scenic viewpoint, summit view, large landscape point, trailhead, saddle, pass,
   or route entrance/exit;
7. bridge, tunnel, rope section, ladder, fixed aid, river crossing, or other
   infrastructure / technical crossing;
8. mobile reception / communication point.

### Gate B: Spatial Separation

MCP points should not be too close to each other.

Default:

```text
minimum_mcp_spacing_m = 1000
```

If multiple route-significant points fall within 1000 m:

- choose a primary MCP for the route story;
- attach nearby points as `linked_named_points` or `linked_cp_candidates`;
- preserve semantic differences rather than merging them blindly;
- allow a human reviewer to override the spacing rule when two adjacent points
  are operationally distinct, such as a water source and a dangerous rope
  crossing.

### Gate C: Scout CP Support

The MCP should have nearby Scout-generated CP support:

```text
nearest_scout_cp_distance_m <= scout_cp_support_radius_m
```

Default:

```text
scout_cp_support_radius_m = 250
```

If no Scout CP exists nearby, MCP remains `mcp_review_required` and should
produce a suggested CP insertion rather than silently becoming accepted.

### Gate D: Named Point Evidence Frequency

For NP-derived MCP promotion:

```text
accepted_evidence_page_count > 10
named_point_mention_ratio >= 0.05
```

Where:

```text
named_point_mention_ratio =
  pages_or_documents_mentioning_np / accepted_evidence_page_count
```

The source corpus should include route-relevant public search results and must
attempt these source families:

- PTT Hiking（PTT 登山板）;
- Hiking Biji（健行筆記）;
- Sunriver Culture / route-guide material（上河文化 / 上河式步程圖資料）.

Promotion confidence rules:

- `high_confidence_mcp` requires the threshold above, source refs, route
  geometry alignment, and no unresolved mandatory-source gap.
- If one mandatory source family has no public route-relevant result, the MCP
  can remain `medium_confidence_mcp` only if the search log records the missing
  source family and another strong evidence source exists.
- If accepted evidence page count is `<= 10`, the point is NP evidence, not MCP.
- If mention ratio is `< 5%`, the name can be stored as a weak alias but should
  not drive MCP promotion.

## Pydantic AI Role

Pydantic AI should not "decide truth". It should orchestrate tools and emit
strict structured outputs.

Allowed Pydantic AI tasks:

- generate route-aware search queries;
- call registered web search, web fetch, local file, OCR, and evidence-index
  tools;
- extract NP aliases, coordinates, route-relative descriptions, point classes,
  and quoted source refs into Pydantic models;
- cluster equivalent aliases such as spelling variants or old/new names;
- explain why a point is MCP-worthy;
- emit low/medium/high confidence and missing-source reasons.

Not allowed:

- compile Final MissionGraph;
- call `/safety/*`;
- mutate Phase 1 runtime state;
- treat model text as source evidence;
- scrape private or login-only sources;
- bypass source robots/terms/rate limits;
- embed copyrighted article bodies or full map images into artifacts.

Implementation note: Pydantic AI supports tool-calling patterns and can use
provider-native or common toolsets for search/fetch depending on model/provider
configuration. Scout should wrap those tools behind Scout-owned capabilities so
tests can use fixtures instead of live network.

## Retrieval Strategy

### Inputs

- golden route GPX or route corridor;
- reference GPX set;
- route name aliases;
- known trailheads, peaks, huts, roads, administrative regions;
- offline OSM/Overpass map evidence;
- Scout risk/ribbon/heatmap/delta layers;
- route-guide timing references if supplied;
- OCR map tiles or scanned map references if supplied and allowed.

### Query Planning

Generate query groups:

```text
route_name + "登山"
route_name + "gpx"
route_name + "黑水塘" / "軟腳坡" / extracted alias
trailhead + peak + "岔路"
hut + water + "取水"
route + "通訊點"
route + "崩壁" / "崩塌" / "高繞" / "繩索"
site:ptt.cc/bbs/Hiking route_name
site:hiking.biji.co route_name
site:sunriver.com.tw route_name
```

Queries must be stored with:

- query text;
- source family target;
- generated_at;
- tool/provider id;
- result count;
- accepted result ids;
- rejected result ids and reason.

### Fetch And Normalize

For each accepted page/document:

- store URL and canonical URL;
- store title;
- store retrieval timestamp;
- store source family;
- store short snippet or hash, not full copyrighted body by default;
- store route relevance score;
- store extracted NP mentions with offsets or local excerpt hashes;
- store coordinate/bbox when available;
- store stale risk.

No live network is allowed in unit tests. Fixture files should represent search
results and fetched page summaries.

## OCR Map Tile / Raster Label Perception

OCR can be necessary because paper route maps often contain the most complete
local labels and hand-carryable route context.

Allowed OCR sources:

- user-supplied scanned map;
- licensed/offline map tile;
- public image where use is permitted;
- internal Scout raster tile already in the local map workspace.

OCR output should store:

- source image path or tile z/x/y;
- bbox in route/project coordinates;
- source image hash;
- OCR engine/version;
- label text;
- confidence;
- candidate NP id;
- whether raw image is retained or excluded.

Copyright boundary:

- do not commit full copyrighted map images;
- do not embed large OCR source images in MCP artifacts;
- store label geometry and source refs;
- require manual review before OCR labels become MCP.

## Data Model

### Named Point Evidence Set

```json
{
  "artifact_kind": "pretrip_named_point_evidence_set",
  "artifact_version": "named_point_evidence.v1",
  "project_id": "chilai_nanhua_day1",
  "source_path": "outputs/named_point_evidence.json",
  "search_profile": {
    "profile_id": "taiwan_hiking_public_sources.v1",
    "required_source_families": [
      "ptt_hiking",
      "hiking_biji",
      "sunriver_culture"
    ],
    "accepted_evidence_page_count": 36
  },
  "named_points": [
    {
      "named_point_id": "np.heishuitang",
      "canonical_name": "黑水塘",
      "aliases": ["黑水池", "黑水塘營地"],
      "point_class": ["water", "camp"],
      "mention_page_count": 7,
      "mention_ratio": 0.194,
      "source_families": ["ptt_hiking", "hiking_biji", "public_web"],
      "route_position": {
        "distance_m": 6420,
        "lat": 23.95,
        "lon": 121.18,
        "coordinate_confidence": "medium"
      },
      "nearest_scout_cp": {
        "candidate_id": "cp.gis.042",
        "distance_m": 84
      },
      "boundary": {
        "candidate_only": true,
        "phase1_runtime_safety_truth": false
      }
    }
  ]
}
```

### MCP Candidate Set

```json
{
  "artifact_kind": "pretrip_major_critical_point_candidates",
  "artifact_version": "mcp_candidates.v1",
  "project_id": "chilai_nanhua_day1",
  "source_refs": [
    "outputs/named_point_evidence.json",
    "outputs/gis_perception_candidates.json",
    "outputs/risk_attribution_diagnostic.json"
  ],
  "mcp_policy": {
    "min_spacing_m": 1000,
    "scout_cp_support_radius_m": 250,
    "np_min_mention_ratio": 0.05,
    "np_min_accepted_evidence_pages": 11,
    "required_source_families": [
      "ptt_hiking",
      "hiking_biji",
      "sunriver_culture"
    ]
  },
  "mcp_candidates": [
    {
      "mcp_id": "mcp.chilai_nanhua.003",
      "label": "黑水塘",
      "mcp_classes": ["water", "camp"],
      "distance_m": 6420,
      "lat": 23.95,
      "lon": 121.18,
      "confidence": "high",
      "promotion_reasons": [
        "named point mention ratio 19.4%",
        "nearby Scout CP within 84m",
        "route-significant water/camp point"
      ],
      "linked_named_points": ["np.heishuitang"],
      "linked_cp_candidates": ["cp.gis.042", "cp.route_note.017"],
      "linked_risk_segments": ["risk_ribbon.segment.120"],
      "nearby_points_suppressed_by_spacing": [
        {
          "source_id": "np.small_camp_alias",
          "distance_m": 310,
          "reason": "within primary MCP cluster"
        }
      ],
      "review_state": "needs_human_review",
      "boundary": {
        "candidate_only": true,
        "runtime_safety_truth": false,
        "compile_allowed": false
      }
    }
  ]
}
```

## MCP Scoring

Score components:

```text
mcp_score =
  type_weight
  + named_point_support
  + source_family_diversity
  + scout_cp_support
  + route_effort_position_value
  + terrain_risk_support
  + communication_value
  - spacing_conflict_penalty
  - stale_source_penalty
  - coordinate_uncertainty_penalty
```

Default type priorities:

| Class | Default weight |
| --- | ---: |
| extreme terrain hazard | 30 |
| fork / junction | 25 |
| water / camp / hut | 25 |
| technical infrastructure / bridge / rope | 22 |
| trailhead / pass / saddle / exit | 20 |
| mobile reception point | 18 |
| hidden forest / route-loss-prone section | 18 |
| scenic viewpoint | 10 |

Scenic viewpoints can become MCP when they are strong navigation or pacing
anchors, but they should not displace hazard, water, shelter, fork, or
communication points unless source support is exceptional.

## Spacing And Cluster Rules

The 1000 m spacing rule operates after semantic clustering:

1. cluster aliases for the same NP;
2. align NP to nearest route position;
3. attach nearby Scout CP and risk segments;
4. rank MCP candidates inside a 1000 m sliding window;
5. choose primary MCP;
6. retain secondary items as linked/suppressed points.

Do not force unrelated semantics into one MCP. Example:

```text
MCP: 大崩壁 entry
linked nearby point: 高繞入口
linked nearby point: rope section
```

The MCP can represent the area, while linked points preserve operational detail.

## UI Requirements

### `/admin/pretrip`

Add a primary route-story view:

- `MCP` layer toggle;
- MCP list sorted by route distance;
- source-family badges;
- mention ratio and page count;
- nearest Scout CP distance;
- spacing suppression details;
- confidence and stale-risk indicator;
- review actions: accept as MCP, link to existing CP, split, downgrade, reject.

MCP should not replace dense CP tabs. It should sit above them as a review aid.

### `/admin/debug`

Debug may show MCP projection as planning context only:

- no runtime mutation;
- no live `/safety/*`;
- MCP selected state can focus map target;
- source refs visible for audit.

### `/admin`

After-action can compare:

- planned MCP;
- actual checkpoint/segment events;
- missed or noisy MCP;
- future next-plan MCP suggestions.

## Commands

Proposed retrieval preview:

```bash
python -m pretrip_mcp_synthesis \
  search-preview \
  --project-root /data/scout/pretrip/workspaces/chilai_nanhua_day1 \
  --route-name "奇萊南華" \
  --source-profile taiwan_hiking_public_sources.v1 \
  --output-dir /data/scout/pretrip/workspaces/chilai_nanhua_day1/outputs/mcp
```

Proposed fixture-backed synthesis:

```bash
python -m pretrip_mcp_synthesis \
  synthesize \
  --project-root tests/fixtures/pretrip/projects/chilai_nanhua_day1 \
  --named-point-evidence tests/fixtures/pretrip/mcp/named_point_evidence.json \
  --output-dir /tmp/scout-mcp-out \
  --min-spacing-m 1000 \
  --np-min-mention-ratio 0.05 \
  --np-min-evidence-pages 11
```

Proposed tests:

```bash
./venv/bin/python -m pytest tests/test_pretrip_mcp_synthesis.py
./venv/bin/python -m pytest tests/test_pretrip_admin_view.py
./venv/bin/python -m pytest tests/test_pretrip_admin_page.py
```

## Project Structure

Planned files:

```text
pretrip_mcp_models.py
  Pydantic models for NP evidence, MCP policy, MCP candidates, source families,
  and review state.

pretrip_mcp_synthesis.py
  CLI and deterministic MCP synthesis from fixture-backed evidence.

pretrip_mcp_retrieval.py
  Retrieval planning and source normalization. Live network disabled in tests.

pretrip_mcp_ocr.py
  OCR label normalization from user-supplied or local map tiles.

pretrip_admin_view.py
  Read-only projection of MCP sections into /admin/pretrip and /admin/debug.

docs/admin/phase4-pretrip-planning.html
  MCP list, map layer, review actions, source badges.

tests/test_pretrip_mcp_synthesis.py
tests/fixtures/pretrip/mcp/
```

## Implementation Plan

### Slice 1: Spec And Fixture Contract

- Add this spec.
- Add fixture shape for named point evidence and expected MCP output.
- Acceptance:
  - fixture has >10 accepted evidence pages;
  - at least one NP has mention ratio >= 5%;
  - mandatory source-family coverage is represented or explicitly marked as
    missing-source gap.

### Slice 2: Deterministic MCP Synthesis

- Implement Pydantic models and deterministic scorer.
- Cluster NP and CP by route distance and semantic key.
- Apply 1000 m spacing.
- Acceptance:
  - nearest Scout CP support is computed;
  - close points are linked/suppressed instead of deleted;
  - candidate-only boundary flags exist.

### Slice 3: Retrieval Plan Artifacts

- Generate search plans from route aliases and MCP source profile.
- Store queries and fixture-backed search result summaries.
- Acceptance:
  - no unit test uses live network;
  - required source families are explicit;
  - rejected results preserve reason.

### Slice 4: OCR Label Evidence

- Normalize OCR tile labels into NP evidence.
- Acceptance:
  - stores tile/image hash, bbox, OCR confidence;
  - does not commit raw copyrighted maps;
  - OCR labels stay review-required.

### Slice 5: Admin Projection

- Add MCP section to `pretrip_admin_view.py`.
- Render MCP list/layer in `/admin/pretrip`.
- Acceptance:
  - map focus works from MCP list;
  - source badges visible;
  - dense CP list remains accessible.

### Slice 6: Review Actions

- Add local workspace review actions for MCP accept/link/split/downgrade/reject.
- Acceptance:
  - writes only local workspace review log;
  - no final package compile;
  - no `/safety/*`.

## Testing Strategy

Fixture-backed tests only for initial implementation.

Test cases:

- NP mention count above 5% promotes to MCP;
- accepted evidence page count <= 10 blocks MCP promotion;
- mandatory source-family gap limits confidence;
- two MCP candidates within 1000 m choose primary and link secondary;
- nearby Scout CP support increases score;
- no nearby Scout CP creates suggested insertion and review-required status;
- scenic point does not displace hazard/water/fork without stronger evidence;
- OCR label becomes NP evidence but not accepted MCP without review;
- artifacts include candidate-only and runtime-safety false boundaries.

Browser tests later:

- `/admin/pretrip` shows MCP layer and list;
- double-click MCP focuses map target;
- source-family badges and mention ratios are visible;
- no console errors;
- no `/safety/*` requests.

## Boundaries

Always:

- keep MCP candidate-only until human review;
- preserve query, source, retrieval, OCR, and model provenance;
- keep dense CP candidates available under the MCP layer;
- show missing source families and stale-risk indicators.

Ask first:

- live web search against public sites;
- OCR over copyrighted or user-private map scans;
- account login or authenticated source retrieval;
- remote community search index;
- changing MCP spacing default below 1000 m.

Never:

- scrape private or login-only data without consent;
- embed full copyrighted article or map payloads;
- call `/safety/*`;
- mutate Phase 1 runtime truth;
- compile MCP directly into Final MissionGraph without review;
- hide low evidence count behind confident language.

## Success Criteria

- A route can produce a compact MCP candidate list from NP, CP, map, OCR, and
  terrain/risk evidence.
- MCP list is much smaller than dense CP candidates and sorted by route
  distance.
- Every MCP has source refs, mention ratio, source-family coverage, nearest
  Scout CP support, spacing status, confidence, and boundary metadata.
- Mandatory source-family gaps are visible.
- Admin UI can review MCP without losing dense CP evidence.
- Tests pass without live network.

## Source Notes

Implementation should verify current source access and terms before enabling
live retrieval:

- Pydantic AI tools and toolsets: https://ai.pydantic.dev/tools/
- Pydantic AI common tools: https://ai.pydantic.dev/common_tools/
- Hiking Biji route/search content: https://hiking.biji.co/
- PTT Hiking board: https://www.ptt.cc/bbs/Hiking/
- Sunriver Culture route-guide material: https://www.sunriver.com.tw/

## Open Questions

- Should the 5% NP threshold count pages, documents, paragraphs, or independent
  authors?
- Should PTT推文/留言 count as separate evidence or only the article page?
- How should Scout handle route names that have multiple common aliases?
- Should MCP spacing be along-route distance only, or also straight-line
  distance?
- Should mobile communication points come from crowd reports, offline telecom
  maps, Scout observations, or explicit user check-ins?
- Which OCR engine should be used first for Traditional Chinese map labels?
