---
name: scout-route-context-briefing
description: Generate Scout pretrip route-context briefings from route/workspace inputs, P0/P1 public source discovery, P2 Scout-owned evidence, Scout AI regeneration plans, collected web evidence, and Scout route context artifacts. Use when asked to build hiking route context, major context points, trip briefing HTML, source discovery plans, Scout AI route briefing regeneration, or Scout admin/pretrip route-context outputs from web/search/workspace/evidence data.
---

# Scout Route Context Briefing

## Overview

Use this skill to turn a route name, workspace, GPX/import result, completed-trip record, or source list into Scout pretrip route-context artifacts and a briefing HTML. Keep the result as pretrip candidate/evidence only; never promote source text, Scout-owned observations, or model output into runtime safety truth.

## One-click New Journey Pipeline

For a completely new journey, use this Skill as the operator-facing one-click
surface and `pretrip_route_context_pipeline.py` as the deterministic execution
engine. The Skill owns interaction and the selected semantic-review handoff;
the program owns validation, files, stage receipts, compilation, and completion
status. The reviewer may be `chatgpt-pro` or the configured
`scout-ai-cloud` model.

The required state machine is:

1. `輸入契約 / input_contract`
   - Validate the YAML contract and every referenced local input before writing.
   - Bind one new `project_id` to the golden GPX, reference GPX set, route
     keywords, and SHA-256 input fingerprints.
   - Refuse an existing project unless `--resume` points to the same config and
     unchanged inputs. Never overwrite or rebuild another route workspace.
2. `證據收集 / evidence_collection`
   - Import the route, optionally prepare requested layers, and collect only the
     explicitly supplied P0/P1 sources.
   - Require both YAML opt-in and `--confirm-network-fetch` before live fetches.
   - Record evidence counts, source tiers, retrieval outcomes, network use, and
     the normalized evidence hash.
3. `確定性編譯 / deterministic_compile`
   - Compile route-context points, source manifest, route-context pack, and
     briefing HTML from the bound workspace.
   - Require all outputs to exist, match the project, and have recorded hashes.
   - Do not use a prior route's aliases, URLs, images, lodging, or copy as
     fallback content.
4. `內容審核 / content_review`
   - First run deterministic gates for project binding, route identity,
     prior-route contamination, blocked product copy, P0/P1 coverage, evidence
     materialization, document shape, and candidate-only boundaries.
   - For `chatgpt-pro`, invoke `$gpt-pro-collaboration` in the Codex in-app
     browser with only the generated briefing and
     `outputs/route_context_pipeline/content_review_packet.json` in scope.
   - For `scout-ai-cloud`, invoke
     `pretrip_route_context_scout_ai_review.py` with the exact pipeline review
     packet as `--binding-review-packet`. Use the configured cloud profile and
     never silently fall back to the local model.
   - Accept only the selected reviewer result matching `project_id`, the exact
     briefing SHA-256, and—for Scout AI—the exact review-packet SHA-256.
     `NEEDS_WORK`, a missing review, or any mismatch must not become
     `completed`.

Before any import/preparation run, read
`docs/specs/scout-pretrip-full-preparation-runbook.md` and record newly
discovered import/preparation mistakes or corrections there.

Start by copying and editing:

```text
config/pretrip-route-context-pipeline.example.yaml
```

Validate without writing:

```bash
rtk ./venv/bin/python -m pretrip_route_context_pipeline \
  --config <new-trip.yaml> \
  --dry-run
```

Run the local deterministic stages:

```bash
rtk ./venv/bin/python -m pretrip_route_context_pipeline \
  --config <new-trip.yaml> \
  --confirm-network-fetch
```

Exit status `3` and pipeline status `needs_semantic_review` are an intentional
handoff, not success. For ChatGPT Pro, use the collaboration ledger, send the
review packet and briefing, and save the strict JSON response locally using the
packet's `expected_result_schema`.

For Scout AI / DeepSeek, set `review.reviewer: scout-ai-cloud` in the input
contract and run:

```bash
rtk ./venv/bin/python -m pretrip_route_context_scout_ai_review \
  --project-root <workspace-root>/<project-id> \
  --model-config configs/assistant-models.dashboard-aihat2.json \
  --binding-review-packet \
    <workspace-root>/<project-id>/outputs/route_context_pipeline/content_review_packet.json
```

This produces:

- `scout_ai_content_review_packet.json`, containing the bounded visible briefing
  and evidence snapshot sent to the model;
- `scout_ai_semantic_review_result.json`, containing provider/model identity,
  briefing/review-packet hashes, verdict, findings, usage, and candidate-only
  boundaries;
- `semantic_review_comparison.json` and `.md`, ready to receive a hash-matched
  ChatGPT Pro result for side-by-side comparison.

Then resume with either reviewer result:

```bash
rtk ./venv/bin/python -m pretrip_route_context_pipeline \
  --config <new-trip.yaml> \
  --confirm-network-fetch \
  --resume \
  --semantic-review-result <semantic-review-result.json>
```

For the operator, this is one Skill request: the Skill executes, hands off to
GPT Pro, waits for the reviewed response, and resumes the same run. Report
success only when the manifest says `completed` and all four stage receipts say
`pass`. Do not generate briefing variants, edit the Route Context Intelligence
implementation spec, or rebuild a Chilai workspace unless the user separately
authorizes that scope.

## Evidence-bound Scout AI Regeneration

Use this branch when an existing Route Context has already been judged
`NEEDS_WORK` and the user asks Scout AI plus a configured cloud model to rebuild
the briefing. This is a separate, hash-bound regeneration cycle; it must not
silently rerun import, map preparation, route binding, or another journey.

The input is one reviewed JSON contract with schema
`scout.route_context_regeneration_evidence.v1`. It must bind the exact
`project_id` and contain:

- the display name and bound track identity;
- `current_status.operability` as `open`, `closed`, or `unknown`;
- P0-backed current status and application rules;
- sourced historical/reference itinerary and logistics;
- the six context-layer claims, unresolved items, and complete source ledger.

Run the Scout AI editorial pass and deterministic compiler:

```bash
rtk ./venv/bin/python -m pretrip_route_context_scout_ai_regenerate \
  --project-root <workspace-root>/<project-id> \
  --evidence <reviewed-regeneration-evidence.json> \
  --model-config configs/assistant-models.dashboard-aihat2.json \
  --skill .agents/skills/scout-route-context-briefing/SKILL.md \
  --model deepseek/deepseek-v3.2 \
  --env-file <repo-env-file>
```

The cloud model may choose only the editorial title, section headings, reading
order, reader questions, and closing note. It never writes the HTML or changes
facts. Deterministic code validates every source reference, requires P0-only
support for current status and application rules, archives the prior briefing,
and compiles the visible document from the typed evidence.

Then run an independent model pass against the regenerated hash:

```bash
rtk ./venv/bin/python -m pretrip_route_context_scout_ai_review \
  --project-root <workspace-root>/<project-id> \
  --model-config configs/assistant-models.dashboard-aihat2.json \
  --model deepseek/deepseek-v3.2 \
  --env-file <repo-env-file>
```

Accept the result only when briefing, regeneration receipt, review packet, and
semantic review all name the same briefing SHA-256. Preserve every previous
different-hash briefing and review under their archive directories.

For `closed` routes, compile a `closed_route_context`: an unmistakable
not-open warning, a Gate 0 that waits for official reopening, historical
itinerary anti-reuse copy, and the post-reopening verification order. Review
the document as a readable historical and status guide; a content `PASS` never
means open, passable, safe, or approved to depart.

If the reviewer returns `NEEDS_WORK`, use its findings to repair the evidence
contract, deterministic renderer, or editorial constraints, then run a fresh
regeneration and independent review. Do not weaken the rubric or rewrite a
review result into `PASS`.

For the operator this remains one Skill request. The Skill performs evidence
preflight, regeneration, independent review, focused tests, hash checks, and a
browser smoke before returning. The two programs remain separate so the
generator cannot mark its own content as reviewed.

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
   - Do not hardcode Chilai, Nengao, or any previous route's URLs, image choices, lodging points, or copy into a new route briefing. Treat previous route artifacts only as examples of structure.

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
  --image-list-html <html-with-route-image-refs> \
  --allow-network-fetch \
  --timeout-seconds 20 \
  --json
```

   - For known URLs without an HTML file, pass repeated `--source-url <url>`.
   - If the same operator source file contains route photos or map images, pass it
     to both `--source-list-html` and `--image-list-html`. Using it only as
     `--source-list-html` can refresh source provenance while stripping the rich
     image set from the briefing.
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

6. Regenerate with Scout AI only as an operator-triggered candidate plan.
   - Use Scout AI/OpenRouter regeneration only when the operator requests it.
   - Load `OPENROUTER_API_KEY` from the repo/persistent environment without printing or storing the secret value.
   - Scout AI should return a bounded JSON plan: route title, route-facing copy candidates, source priorities, visual gap candidates, and review notes.
   - The deterministic compiler must read workspace artifacts and render the final HTML. Do not let model output directly become runtime safety truth, live navigation authority, or unreviewed product-visible HTML.
   - Do not let a compact Scout AI rewrite replace the canonical briefing HTML.
     Canonical output must retain the full briefing architecture: visual agenda,
     photo essay, visual kit, map atlas, source-tier spine, six context layers,
     source health, P2 review layer, and source table. If the rewrite loses that
     structure, keep it as a rejected candidate artifact and rerun the
     deterministic compiler.
   - Store regeneration provenance and boundary metadata in machine-readable artifacts such as `outputs/scout_ai/route_context_briefing_regeneration.json`, but hide raw model/prompt/cache/file-path fields from the product-visible page.

7. Verify the workspace contract when artifacts are written.

```bash
PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python tools/verify_pretrip_workspace_spec_alignment.py \
  --workspace-root <workspace-root> \
  --project-id <project-id> \
  --admin-base-url <admin-base-url> \
  --admin-bearer-token-file <token-file> \
  --allow-network-calls
```

8. Report results with provenance.
   - Include source counts by tier/family.
   - Include P2 Scout-owned evidence counts by type and review state when present.
   - Include route context point count and briefing path.
   - State whether network calls were made.
   - State candidate-only and runtime-safety-truth boundaries.
   - List failed/empty source families separately from successful evidence.

## Briefing Content Shape

Structure generated route context briefings around:

- route baseline: route name aliases, route class/difficulty, distance,
  ascent/descent, elevation range, route region, entry/exit trailheads, summit
  or objective list, and recommended days.
- permit/lodging/application layer: required permits, application windows,
  lodging/campsite capacity, booking/opening windows, meal/water services,
  official status page, and stale-status warnings.
- itinerary operations layer: 2D/3D or other common itinerary options, daily
  start times, segment distance/time/elevation, rest/resource points,
  day-by-day pressure, and turnaround or shorten conditions.
- access/transport layer: self-drive access, public transport limitations,
  shuttle/taxi needs, trailhead parking, pre-night lodging town/settlement, and
  post-trip recovery options when sourced.
- equipment/readiness layer: water carry, food/meal plan, headlamp/mid-layer,
  shelter/camp needs, weather/season gear, navigation level, and target hiker
  profile.
- contingency/business layer: alternative routes, route closure responses,
  weather-shortened plans, vendor/shuttle/guide/lodging support categories, and
  cancellation/refund or rescheduling notes when the source is an activity
  provider page.
- peer timing layer: public completed-trip time samples, pace coefficients,
  route popularity, and completion distribution only when sourced and presented
  as reference evidence, never as a normative pace requirement.
- historical layer: old routes, guard roads, police posts, logging roads, old settlements, historical facilities.
- cultural layer: indigenous place names, old communities, hunting trails, local stories, land-use changes.
- natural layer: forest type, vegetation belt, plants, birds, streams, geology.
- terrain layer: ridges, saddles, valleys, collapse walls, stream valleys, viewpoints, wind gaps.
- seasonal layer: flowering, cloud sea, rain season, water conditions, insects, grass, low temperature.
- observation points: places worth a short planned observation stop, never automatic stop permission.
- P2 Scout-owned layer: completed-trip GPX, deviations, dwell/stay points, photos, voice notes, IMU/PDR events, barometric altitude, team spacing, user stop-worthiness feedback, and Scout action logs that explain how the route actually unfolded for this user/team.

## Product Copy Gate

Every visible word in the briefing HTML must describe the trip, itinerary,
route segment, source, lodging/intermediate point, terrain, weather/season,
observation stop, or leader review task. Hide implementation details in
collapsed admin metadata or JSON artifacts.

Block product-visible copy that describes how the briefing was generated,
organized, or prompted. Do not show words or phrases such as:

- prompt, model output, compiler, cache path, artifact path, load contract,
  boundary metadata, source tier machine field, candidate-only, runtime safety
  truth, review_state, JSON plan, material board, image index, image guide,
  speaker note, visual kit, opening visual, photo readiness, page preparation,
  or internal AI/design guidance.
- `行前照片與地圖狀態`, `已檢查開場`, `開場主視覺`, `行程畫面覆蓋`,
  `畫面偏薄`, `圖像導覽`, `畫面索引`, `把可用圖片一次攤開`,
  `素材板`, `提示詞`, `產生方式`, `內部查核`, `模型輸出`.

Use trip-facing replacements:

- `出發前補查路段`, `部分路段待補查`,
  `照片與地圖對應的行程段落`, `入山與稜線遠景`,
  `路線全段走向圖`, `宿點與中繼點`, `短停觀察點`,
  `雲霧低溫與季節條件`, `行程照片清單`,
  `按行程段落檢查哪些路段還缺照片`.

If an image, source, or context layer is missing, state the route segment or
leader-review task that needs checking. Do not explain the page template or
apologize for missing media.

## Visual / Map Briefing Template

Future route briefing HTML should reuse the same high-energy briefing structure,
not fall back to a source table or engineering report:

- visual agenda: first-screen navigation for itinerary, imagery, map, context, observation stops, schedule, and sources.
- photo essay: use real P0/P1/P2-backed images when available. Never fake missing photos with decorative placeholders.
- visual kit: fixed slots for cover image, route map, lodging/intermediate nodes, terrain passage, 3-minute stop, and weather/season image. Missing slots must become an explicit shot list or evidence gap.
- map atlas: include a real route overview/map image when available, plus route scale, elevation range, bbox span, and P0/P1/P2 map evidence cards so the route feels broad and spatially grounded.
- source tier spine: show P0 official baseline, P1 expansion evidence, and P2 Scout-owned review data as separate visible cards before the detailed source table.
- six context layers: historical, cultural, natural, terrain, seasonal, and observation points must each have a briefing card or an explicit missing-evidence state.
- professional itinerary spine: include sourced baseline metrics, permit/lodging
  application status, daily itinerary options, segment time/distance/elevation,
  transport/access, water/meal/lodging services, gear/readiness, contingency
  choices, and peer timing samples when available.
- color direction: use a bold expedition palette with dark ground, ember/red action accents, signal yellow, and high-contrast map/source panels. Keep Scout safety boundary text clear and do not hide candidate-only status.
- public/share variants must redact private P2 details, but Scout-local/admin briefings should still show that P2 exists and what category/review state it has.

For product-visible labels, translate those internal slots into itinerary
language: entry/ridge view, full-route direction map, lodging/intermediate
points, terrain passage, short observation point, and weather/season
conditions.

## Professional Itinerary Intelligence Gate

When comparing Scout Route Context output with a professional itinerary or route
encyclopedia page, treat the following fields as first-class briefing coverage,
not optional prose. The Samejan Travel Chilai Nanhua page is an example of this
content shape: headline metrics, route grade, application rules, daily
itinerary, segment details, resource points, transportation, cautions,
highlights, alternatives, support vendors, and public completion samples.

Required behavior:

- Extract the professional page's section inventory before synthesis. At
  minimum check for: route metrics, route grade, route aliases, summit/objective
  metadata, trailheads, application/permit/lodging rules, itinerary variants,
  segment-by-segment distance/time/elevation, water/resource/service points,
  transportation/access, lodging/pre-night/post-trip logistics,
  equipment/readiness, caution list, route highlights, alternative or shortened
  routes, support vendor categories, and public completed-trip timing samples.
- Compare that inventory against existing Scout artifacts:
  `route_context_pack`, `route_context_points`, `source_manifest`,
  `media_manifest`, route summary, P2 Scout-owned evidence, and rendered
  briefing HTML.
- Add missing professional-itinerary fields to the briefing as sourced
  candidate sections or explicit evidence gaps. Do not hide gaps behind a fluent
  route story.
- Keep P0/P1/P2 provenance for each field. Official route status, permit,
  lodging, closure, price, and booking-window facts should prefer P0 official
  sources; P1 professional/community pages may supplement but must not override
  fresher P0 evidence.
- Never invent or normalize vendor names, Line IDs, phone numbers, prices,
  booking windows, bed counts, shuttle availability, or public transport
  details. If a source is login-gated or redacted, show the support category
  and the review task, not fake contact details.
- Distinguish activity planning from on-route permission. Itinerary sections may
  say what operators commonly plan, but stopping, detouring, waiting, taking
  photos, or continuing still requires Contextual Permissioning and current
  conditions.
- Treat public peer timing samples as evidence of route variability. They can
  inform pace-fit review, but they cannot become a required pace, safety
  decision, or user ranking.
- For route-open/closed status, record retrieval date and source freshness. If a
  professional P1 page conflicts with a newer P0 official status page, surface
  the contradiction and require leader review.
- For Scout-local/admin briefings, include a concise comparison table:
  professional-itinerary field, Scout coverage status, source tier, evidence
  ref, and next action. Public/share variants may collapse this into a leader
  review checklist.

## Media Quality Gate

Before rendering a briefing HTML, curate visual evidence as route content rather than generic web-page media:

- Prefer route-specific photos or maps from P0 official pages, P1 route/community pages, or reviewed P2 Scout-owned media.
- Bind every selected image to a route point, lodging point, route segment, context layer, or source section. A photo with no route/context relationship is decoration and should not be used.
- Reject website chrome and tracking media: logos, logotypes, SVG icons, menu/search/close/language/share buttons, app/web UI screenshots, badges, avatars, social icons, tracking pixels, and generic education/brand tiles.
- Reject images whose URL, alt text, caption, title, or source role indicates `icon`, `logo`, `logotype`, `button`, `menu`, `search`, `close`, `language`, `facebook`, `line`, `tracking`, `pixel`, `avatar`, `badge`, or non-route campaign/education graphics.
- Do not use a generic icon, placeholder, or decorative graphic to fill a required slot. If a suitable real photo/map is unavailable, show an explicit visual evidence gap and shot list.
- Prefer stable content image formats such as JPG, JPEG, PNG, or WEBP. Treat SVG/GIF/ICO as suspect unless the artifact is a route map with clear provenance.
- Keep repeated photos intentional. Reuse a hero image only when it anchors the route; avoid filling a gallery with duplicates when other verified route visuals exist.
- After rendering, inspect the generated HTML image sources. A Scout-local route briefing should have zero selected gallery/hero images from UI chrome, tracking, generic icon, or unrelated brand assets.

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

## Verification Gate

Before handing off a generated or regenerated route briefing:

- Run a focused route-context test that renders the fixture briefing.
- Scan visible HTML text with `script`, `style`, SVG, and JSON payloads removed.
- Fail the check if any blocked Product Copy Gate phrase is visible.
- Confirm every selected image has a route point, route segment, lodging point,
  context layer, or source relationship.
- When the 9099 admin server is available, fetch the live
  `/admin/pretrip/projects/{project}/briefings/route-context` endpoint and run
  the same visible-text scan against the served page.
- Run the repo's focused tests plus `pnpm lint`, `pnpm typecheck`, and
  `pnpm test` when code or tests changed.
- Run the Scout layer contract and admin UI smoke only when the change affects
  GPX import, map preparation, GIS/admin surfaces, layer controls, route
  projection, terrain/risk outputs, or layer artifacts.

## Common Pitfalls

- Do not use route notes as final context; use them only as crawl/search seeds.
- Do not use unreviewed P2 Scout-owned data as confirmed context or safety truth; it remains Scout-local candidate evidence until reviewed.
- Do not let a previous route's URLs become defaults for the next route.
- Do not count source catalog entries as fetched evidence.
- Do not count P2 artifact existence as route context unless the artifact was parsed, summarized, and tied to a route point/segment with provenance.
- Do not hide empty web evidence behind a fluent narrative; show the missing-source state.
- Do not collapse P0/P1/P2 provenance into a single generic tier when merging into route context.
- Do not let site icons, logos, tracking pixels, or generic education graphics become the cover, gallery, or route visual material.
- Do not ship prompt-writing, design-process, material-board, cache, model,
  compiler, artifact-boundary, or safety-truth wording as visible trip briefing
  copy.
