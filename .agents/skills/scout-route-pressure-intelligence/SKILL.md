---
name: scout-route-pressure-intelligence
description: Collect and synthesize public route-pressure evidence for Scout pretrip Readiness & Pace Fit, Route Boss Demand, Challenge Fit, pressure points, public difficulty consensus, rescue/incident context, and pressure briefing artifacts. Use when asked to find official/community pressure points, route difficulty hot spots, public rescue or incident evidence, or P0/P1 evidence that should inform Scout Boss Points without becoming runtime safety truth.
---

# Scout Route Pressure Intelligence

## Overview

Use this skill to turn public P0/P1 route evidence into pressure candidates for
Scout Readiness & Pace Fit. It complements `$scout-route-context-briefing`: route
context explains what the route is; route pressure explains where the route asks
more from the user/team.

## Core Boundary

- Treat all outputs as pretrip candidate-only evidence.
- Do not call `/safety/*`.
- Do not mutate Phase 1 runtime behavior or Phase 2 Brain facts.
- Do not treat model text, social posts, rescue anecdotes, or public articles as
  route truth without source refs and confidence labels.
- Do not hardcode route-specific URLs as defaults. Concrete URLs must come from
  operator input, source-list HTML, a reviewed search adapter, or workspace cache.
- Keep P0/P1 public evidence separate from P2 Scout-owned completed-trip evidence.

## Workflow

1. Identify the route scope.
   - Read workspace `project.json` when available.
   - Prefer route aliases, trailheads, huts/camps, peaks, ridges, exit routes,
     and known route distances.
   - For Chilai/Nanhua, broad aliases may include `奇萊南華`, `奇萊-南華`,
     `奇萊南峰 南華山`, `能高越嶺道西段`, `天池山莊`, and `光被八表`.

2. Read `references/pressure-source-catalog.md`.
   - Use it to choose source families and pressure terms.
   - Treat source entries as discovery scope, not fetched evidence.
   - Record missing source families as gaps instead of filling them with prose.

3. Gather P0 official pressure evidence.
   - Prefer official trail/status pages, permit/status portals, DEM/DTM,
     hazard/weather baselines, national incident statistics, government open
     data, and regional fire-department incident feeds.
   - P0 can support route status, terrain class, route distance/elevation,
     communication points, landslide/geology sensitivity, weather/rainfall, and
     incident context.

4. Gather P1 community/expert pressure evidence.
   - Use Hiking Biji, Hikingbook, PTT Hiking, 登山補給站, public GPX/route
     records, public maps, NGO rescue/training material, and reviewed expert
     media such as route-specific rescue/trail-runner videos or posts.
   - P1 can support repeated named pressure points, community difficulty
     language, pace anecdotes, route-profile diagrams, and technical-terrain
     warnings.

5. Collect bounded web evidence when explicitly allowed.

```bash
PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python -m pretrip_p0_p1_source_collection \
  --project-root <workspace-project-root> \
  --source-url <reviewed-source-url> \
  --source-url <reviewed-source-url> \
  --allow-network-fetch \
  --timeout-seconds 20 \
  --json
```

   - For plan-only work, omit `--allow-network-fetch`.
   - For many URLs, write an HTML source list and pass `--source-list-html`.
   - Do not scrape private, login-only, or robots-disallowed sources.

6. Extract pressure candidates.
   - Identify route-relative places or spans, not just page topics.
   - Prefer route-distance anchors such as `5.6K-6.0K`, named points, huts,
     bridges, forks, collapsed slopes, saddles, steep descents, and known exits.
   - Use route-profile images or DEM-derived terrain profile to explain steep
     sections, but cite the image/source and keep it as evidence.
   - Produce or update, when requested by the caller:

```text
outputs/route_pressure_external_candidates.json
outputs/route_pressure_external_candidates.geojson
```

7. Merge with Scout route-pressure logic.
   - Public evidence should feed `Route Boss Demand` as external support, not
     replace the route pressure profile.
   - The pressure centerline remains Overpass/risk-ribbon-backed. GPX evidence
     supplies timing/slow-passage behavior only after projection.
   - A Boss candidate should come from pressure-profile peaks plus MCP/named
     point/review evidence, not from rest-stop popularity.

## Anti-Misclassification Rules

- A hut, water source, camp, temple, or large flat rest point is not a Boss just
  because many people stop there.
- A viewpoint is not a Boss just because it is frequently mentioned.
- A slow point must represent sustained slow movement over a route span. Default
  minimum span is 500 m before it contributes to observed impedance.
- Route pressure should increase when public sources independently mention
  technical terrain, collapse walls, rope/bridge exposure, muddy/steep descent,
  route ambiguity, storm/rain sensitivity, rescue difficulty, communication
  gaps, or repeated incident context.
- Confidence should drop when evidence is stale, single-source, social-only,
  coordinate-uncertain, or contradicted by P0 status.

## Output Shape

Use compact JSON records with these fields when creating pressure candidates:

```json
{
  "candidate_id": "external_pressure.chilai_nanhua.001",
  "label": "6K 大崩壁",
  "route_distance_start_m": 5600,
  "route_distance_end_m": 6000,
  "pressure_reason": ["collapse_wall", "community_caution", "rain_sensitive"],
  "source_tier_counts": {"P0": 1, "P1": 3},
  "source_refs": [{"tier": "P1", "family": "community_article_evidence", "url": "..."}],
  "external_pressure_score": 72,
  "confidence": "medium",
  "requires_human_review": true,
  "candidate_only": true,
  "runtime_safety_truth": false
}
```

## Reporting

Report:
- source counts by tier/family;
- pressure candidate count and top candidates;
- missing source families;
- whether network calls were made;
- whether any source was social/video-only or requires manual review;
- candidate-only and no-runtime-safety boundary.
