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
candidates/
  route_context_points.json
```

`route_context_evidence.json` is the provenance and collection summary.
`source_manifest.json` is the source status, hash, cache, and missing-source
report. `route_context_pack.json` is the offline pack index used by Scout AI
tools. `route_context_points.json` is the candidate point list for map/UI/review.

## Input Sources

The first MVP reads only workspace-local artifacts:

- `outputs/mcp/mcp_candidates.json`
- `outputs/mcp/named_point_evidence.json`
- `outputs/mcp/mcp_ocr_labels.json`
- `candidates/route_note_candidates.json`
- `outputs/layers/normalized/web_case_evidence.json`
- `outputs/layers/normalized/raster_label_evidence.geojson`
- `outputs/import_manifest.json`
- `normalized/routes/route_summary.json`

Missing optional sources must be recorded as source gaps, not hidden.

Future source connectors may add official trails, historical maps, cultural
archives, biodiversity data, weather/season evidence, disaster records, and
Scout field observations. Those connectors must write workspace-local artifacts
first; Scout AI should read the local pack before calling remote tools.

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

- Running the collector after GPX import writes all four canonical artifacts.
- Missing web/raster evidence is visible in `source_manifest.json`.
- MCP and named-point evidence are merged without losing source provenance.
- Route notes are filtered to meaningful route context candidates.
- Sensitive cultural labels receive fuzzy or hidden coordinate display policy.
- Existing `scout.ai.route_context.assess.v0` can read the canonical
  `candidates/route_context_points.json`.
- Tests are fixture-backed and do not require live network.
