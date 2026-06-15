---
name: scout-route-context-briefing
description: Generate Scout pretrip route-context briefings from route/workspace inputs, P0/P1 public source discovery, P2 Scout-owned evidence, collected web evidence, and Scout route context artifacts. Use when asked to build hiking route context, major context points, route briefing HTML, source discovery plans, or Scout admin/pretrip route-context outputs from web/search/workspace/evidence data.
---

# Scout Route Context Briefing

## Overview

Use this skill to turn a route name, workspace, GPX/import result, completed-trip record, or source list into Scout pretrip route-context artifacts and a briefing HTML. Keep the result as pretrip candidate/evidence only; never promote source text, Scout-owned observations, or model output into runtime safety truth.

## Core Boundary

- Treat all outputs as pretrip candidate-only evidence.
- Do not call `/safety/*`.
- Do not mutate Phase 1 runtime behavior or Phase 2 Brain facts.
- Do not embed raw GPX, raw DEM, raw tiles, raw HTML, or large scraped text in JSON artifacts.
- Require explicit operator intent before live network fetches. Plan-only dry runs are allowed without network.
- Preserve source tier/family provenance from P0/P1 source discovery and P2 Scout-owned evidence through `web_case_evidence`, `route_context_points`, `source_manifest`, and the briefing.
- Treat P2 Scout-owned evidence as Scout-local/private by default. Scout admin/workspace briefings may include raw or detailed P2 when operator intent is clear and provenance/privacy/review state remain visible; redaction is required only for export, share, or public handoff variants.

## Workflow

1. Identify the project/workspace and route keywords.
   - Prefer an existing Scout pretrip workspace under the configured workspace root.
   - If only a route name is provided, build route keywords first and use source discovery before making conclusions.
   - If the user provides a pasted HTML/source list, use it as concrete source input, not as final truth.

2. Build a P0/P1 source discovery plan.
   - Read `references/source-catalog.md` before choosing source families.
   - Use catalog entries as search scope, not as fixed route URLs.
   - Avoid route-specific hardcoded defaults. Concrete URLs must come from `--source-url`, `--source-list-html`, or a future search adapter output.
   - Prefer official P0 evidence for status/baseline facts and P1 evidence for community names, context expansion, and repeated named-point references.

3. Inspect P2 Scout-owned evidence when a workspace or completed trip is available.
   - Look for completed/user GPX, deviation records, dwell/stay points, photos, voice notes, IMU/PDR events, barometric altitude changes, team spacing records, user stop-worthiness reports, and Scout action logs.
   - Keep P2 as route-specific evidence with `source_tier=P2`, `source_family=scout_owned_evidence`, local path/hash provenance, capture time, device/user attribution when safe, privacy classification, and review state.
   - Use unreviewed P2 only as seeds for route-context candidates or briefing caveats. Do not write it as confirmed route context until reviewed.
   - Use reviewed P2 to explain how this route behaved for this user/team: pacing friction, regroup points, unexpectedly valuable observation points, route notes, and future pretrip suggestions.

4. Collect bounded web evidence when explicitly allowed.
   - Use the repo tool:

```bash
PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python -m pretrip_p0_p1_source_collection \
  --project-root <workspace-project-root> \
  --source-list-html <html-with-source-links> \
  --allow-network-fetch \
  --timeout-seconds 20 \
  --json
```

   - For known URLs without an HTML file, pass repeated `--source-url <url>`.
   - For plan-only output, omit `--allow-network-fetch` or add `--dry-run`.
   - If no concrete URLs are provided, expect `planned_requires_source_discovery`; do not treat that as evidence.

5. Compile route context artifacts.

```bash
PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python -m pretrip_route_context_collection \
  --project-root <workspace-project-root> \
  --route-keyword "<route keyword>" \
  --json
```

   Expected outputs include:
   - `outputs/layers/plans/web_case_query_plan.json`
   - `outputs/layers/normalized/web_case_evidence.json`
   - `candidates/route_context_points.json`
   - `normalized/context/route_context/source_manifest.json`
   - `normalized/context/route_context/route_context_pack.json`
   - `outputs/briefings/route_context_briefing.html`

6. Verify the workspace contract when artifacts are written.

```bash
PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python tools/verify_pretrip_workspace_spec_alignment.py \
  --workspace-root <workspace-root> \
  --project-id <project-id> \
  --admin-base-url <admin-base-url> \
  --admin-bearer-token-file <token-file> \
  --allow-network-calls
```

7. Report results with provenance.
   - Include source counts by tier/family.
   - Include P2 Scout-owned evidence counts by type and review state when present.
   - Include route context point count and briefing path.
   - State whether network calls were made.
   - State candidate-only and runtime-safety-truth boundaries.
   - List failed/empty source families separately from successful evidence.

## Briefing Content Shape

Structure generated route context briefings around:

- historical layer: old routes, guard roads, police posts, logging roads, old settlements, historical facilities.
- cultural layer: indigenous place names, old communities, hunting trails, local stories, land-use changes.
- natural layer: forest type, vegetation belt, plants, birds, streams, geology.
- terrain layer: ridges, saddles, valleys, collapse walls, stream valleys, viewpoints, wind gaps.
- seasonal layer: flowering, cloud sea, rain season, water conditions, insects, grass, low temperature.
- observation points: places worth a short planned observation stop, never automatic stop permission.
- P2 Scout-owned layer: completed-trip GPX, deviations, dwell/stay points, photos, voice notes, IMU/PDR events, barometric altitude, team spacing, user stop-worthiness feedback, and Scout action logs that explain how the route actually unfolded for this user/team.

## Visual / Map Briefing Template

Future route briefing HTML should reuse the same high-energy briefing structure,
not fall back to a source table or engineering report:

- visual agenda: first-screen navigation for itinerary, imagery, map, context, observation stops, schedule, and sources.
- photo essay: use real P0/P1/P2-backed images when available. Never fake missing photos with decorative placeholders.
- visual kit: fixed slots for cover image, route map, lodging/intermediate nodes, terrain passage, 3-minute stop, and weather/season image. Missing slots must become an explicit shot list or evidence gap.
- map atlas: include a real route overview/map image when available, plus route scale, elevation range, bbox span, and P0/P1/P2 map evidence cards so the route feels broad and spatially grounded.
- source tier spine: show P0 official baseline, P1 expansion evidence, and P2 Scout-owned review data as separate visible cards before the detailed source table.
- six context layers: historical, cultural, natural, terrain, seasonal, and observation points must each have a briefing card or an explicit missing-evidence state.
- color direction: use a bold expedition palette with dark ground, ember/red action accents, signal yellow, and high-contrast map/source panels. Keep Scout safety boundary text clear and do not hide candidate-only status.
- public/share variants must redact private P2 details, but Scout-local/admin briefings should still show that P2 exists and what category/review state it has.

For each point, distinguish:
- why it matters for route understanding;
- source tier/family and URL;
- for P2, local artifact path/hash, capture time, review state, and privacy classification instead of a public URL;
- whether it is a named point, official status, community evidence, terrain evidence, or cultural expansion;
- whether it needs human review before becoming part of a reviewed trip package.
- whether it is Scout-local only, exportable after redaction, or approved for a shared briefing.

## Scout/Admin HTML

If the user asks for a Scout-local HTML/admin briefing instead of workspace artifacts:

- Still use the P0/P1 source discovery flow.
- Include source links and retrieval dates for P0/P1, and artifact path/hash/capture/review provenance for P2.
- Mark the document as a Scout pretrip briefing, not Scout runtime safety output.
- Avoid implying current route open/closed status unless it was freshly sourced from P0 official status pages.
- Include P2 as an explicitly labeled Scout-owned section. If no P2 exists, state that P2 will be populated after completed-trip import rather than fabricating examples.
- If this Scout-local document is later exported outside Scout, produce a separate redacted/shareable variant instead of treating the Scout-local file as public.
- Prefer saving under `docs/admin/` only when the user asks for a repo document.

## Common Pitfalls

- Do not use route notes as final context; use them only as crawl/search seeds.
- Do not use unreviewed P2 Scout-owned data as confirmed context or safety truth; it remains Scout-local candidate evidence until reviewed.
- Do not let a previous route's URLs become defaults for the next route.
- Do not count source catalog entries as fetched evidence.
- Do not count P2 artifact existence as route context unless the artifact was parsed, summarized, and tied to a route point/segment with provenance.
- Do not hide empty web evidence behind a fluent narrative; show the missing-source state.
- Do not collapse P0/P1/P2 provenance into a single generic tier when merging into route context.
