# Scout Dashboard v0.1

## Purpose

This document records the design and implementation process for Scout
Dashboard v0.1. The dashboard is a desktop alpha operator shell that gathers
the existing admin surfaces, map, timeline evidence, debug messages, observer
messages, workspace tooling, and new-trip import intake into one navigation
frame.

The runtime source remains `docs/admin/scout-dashboard-v0.1.html`.

## Active Recording Rule

Status: active.

Starting on 2026-07-02, every subsequent Scout Dashboard v0.1 UI, navigation,
import/preparation, workspace, map, timeline, debug, or operator-flow change in
this thread must add an entry to this file before final reporting.

Stop condition: continue recording until the user explicitly says to stop
recording.

Each entry should include:

- user request;
- scope and files changed;
- implementation steps;
- boundary and safety notes;
- verification commands or browser smoke evidence;
- known remaining gaps.

## Current Boundary

- The dashboard is a session-local operator UI shell.
- `Import New Trip` validates and records operator intent only.
- No dashboard action performs live safety automation.
- No dashboard action mutates Phase 1 runtime safety truth.
- No dashboard action sends outbound transport.
- No dashboard action directly writes or deletes workspace files unless the
  existing operator-approved admin/import tooling is explicitly invoked.
- GIS-related implementation remains outside this thread unless explicitly
  reassigned; dashboard GIS findings should record repro, screenshot, data
  path, expected result, and actual result.

## Implementation Record

### 2026-07-28 - Paginate Evidence inside each category

User request:

- Replace the tab-wide Evidence pager with independent pagination inside each
  category.
- Keep every category title visible and initially collapsed.

Implementation:

- Removed the shared 100-row page that split one tab across unrelated
  categories. Each category now owns its page number, page count and
  Previous/Next controls.
- Kept category shells visible while rendering row controls only for the one
  open category. This bounds the live DOM to at most 100 evidence rows without
  making later categories appear empty.
- Preserved page state independently by surface, tab and category. Switching
  categories or tabs no longer consumes or resets another category's page.
- Map source focus now opens the source category and moves directly to that
  category's page.
- Removed the misleading “Evidence exists in this category but is on another
  page” state. A declared category with no loaded row payload now states that
  distinction directly.

Boundary:

- This is a read-only information-architecture change. It does not add,
  infer, accept or mutate evidence or Phase 1 runtime safety truth.
- The previous tab-wide pagination record below remains historical and is
  superseded by this category-local model.

Verification:

- Isolated commit worktree Dashboard suite: `50 passed`; the integrated dirty
  worktree also passed its then-current Dashboard suite.
- `pnpm lint`: passed. The package typecheck smoke passed (`1 passed`).
- The package test aggregate retained two unrelated documentation-token
  failures (`AGENTS.md` Phase 9 wording and the legacy generated-code-network
  phrase); the other 15 package tests passed.
- Live Chromium against `http://127.0.0.1:9099/admin/dashboard#map` confirmed
  zero initially open categories, all 31 Map/Risk category shells, five Boss
  Point rows, and no legacy “another page” message.
- Baseline Risk rendered exactly 100 controls from 1,825 rows. Its local pager
  moved from items 1–100 / page 1 of 19 to items 101–200 / page 2 of 19,
  changed the first row, and kept that category open; only 100 evidence row
  controls existed in the rail. Page changes positioned the category header
  eight pixels below the rail viewport instead of leaving the user at the
  bottom of the previous page.
- Final browser verification reported zero JavaScript exceptions, console
  errors, failed requests or HTTP error responses. An earlier cold-runtime
  attempt observed transient optional weather-overlay `422/500` responses;
  they did not reproduce after the Dashboard runtime and workspace catalog
  were reverified.

### 2026-07-23 - Keep Timeline Evidence categories collapsed and visible

User request:

- Review the pretrip evidence contract after Risk and Boss categories appeared
  to be missing.
- Keep every category title visible even when its content is null or lies on a
  later evidence page.
- Start every Timeline Evidence category collapsed so large groups do not make
  the remaining capability categories look absent.

Implementation steps:

- Confirmed that Risk, Major Critical Points, Boss Points, mileage, Overpass,
  environment, GPX and review categories were already projected by the
  Dashboard.
- Removed the default-open policy for the first two groups and selected CP/MCP
  groups. Every evidence `<details>` group now starts collapsed.
- Changed evidence pagination to paginate rows while retaining every category
  shell on every page.
- Added distinct empty copy for a category with no loaded evidence versus a
  category whose evidence rows are available on another page.

Boundary:

- This is a read-only information-architecture correction. It does not add,
  infer, accept or mutate pretrip evidence, and it does not change Phase 1
  runtime safety truth.

Verification:

- Focused Dashboard regression: `3 passed, 42 deselected`.
- Frontend lint passed; the package typecheck smoke passed (`1 passed`).
- The package test suite reached `15 passed, 2 failed`; both failures are
  pre-existing Scout AI OS documentation-token expectations in
  `tests/test_scout_ai_os_docs.py`, outside this Dashboard change.
- Live browser smoke at
  `http://127.0.0.1:9099/admin/dashboard#timeline`: CP/Timeline rendered eight
  category titles with zero open groups, including Major Critical Points, Boss
  Points and Mileage Tags.
- Map/Risk rendered 31 category titles with zero open groups, including Risk
  Score, Baseline Risk, Calibrated Heat and Risk Delta.
- After moving to page 2 of 61, all 31 Map/Risk category titles remained
  present and collapsed. Browser console error count was zero.

### 2026-07-21 - Remove duplicate Safety / Emergency outer headers

User request:

- Remove the two large headers shown above the integrated desktop Emergency
  console: the Emergency UI description/status-chip header and the four-column
  Surface/Path/Transport/Operator status header.

Implementation steps:

- Removed `safety-emergency-commandbar` and its eyebrow, title, explanatory
  copy, and boundary chips from `renderEmergencyPage()`.
- Removed `safety-emergency-status-grid` and all four status cards.
- Removed the now-unused command-bar, boundary, status-grid, and status-card CSS.
- Kept the compact iframe toolbar, full desktop-only Emergency console, full-page
  link, and post-frame safety boundary note.
- Preserved `sent=false · external_send_performed=false` in that bottom boundary
  note instead of restoring either removed header.

Boundary:

- This is presentation-only. The desktop endpoint, Emergency decision controls,
  candidate/sandbox semantics, `sent=false` evidence, no-outbound boundary, and
  Phase 1 runtime safety behavior are unchanged.

Verification:

- Focused header-removal source contract: `1 passed`; the adjacent six-contract
  run exposed only the displaced `external_send_performed=false` audit marker
  (`5 passed, 1 failed`). After moving that marker to the bottom boundary note,
  the header-removal and Emergency-boundary contracts both passed (`2 passed`).
- Ruff and the scoped whitespace/diff check passed.
- Live 9099 read-only browser verification at 1440 x 1000 found zero command
  headers, zero status grids/cards, one visible compact toolbar, one 1166 x 790
  desktop iframe, zero mobile surfaces/devices, zero horizontal overflow, and no
  HTTP or JavaScript errors. No Emergency control was clicked.

### 2026-07-21 - Connect Six Axis Weather to the route decision API and CWA Map

User request:

- Generate the `Exploring for Six Axis -> Weather` page from APIs, using
  `scout-weather-environment-sensing` and Section 10 of
  `SCOUT_OUTDOOR_AI_AGENT_STANDARD` as the functional contract.
- Reuse the CWA capability already present on MAP inside Weather.

Implementation steps:

- Added cache-only
  `GET /admin/pretrip/projects/{project_id}/weather-dashboard`, which composes
  redacted rainfall/imagery manifests, persisted route rainfall trend, the nine
  route imagery risk features, explicit weather x TEII interactions, and the
  compact LoRa preview.
- Added a deterministic `Decision / Why / Where / When` candidate projection.
  Missing or stale evidence fails closed to `DELAY`; explicit echo, motion,
  convection, or terrain interaction evidence can produce `CHANGE_PLAN`.
- Changed Weather to make one API request and render the candidate decision,
  position/target one-hour trends, route risk features, terrain intersections,
  freshness, data delay, confidence, and LoRa `sent` state.
- Embedded the canonical Pre-trip Map through a same-origin Weather bridge.
  Radar/satellite product, 3/6/9/12-hour window, frame, play/pause, rainfall
  opacity, radar opacity, and satellite opacity invoke the existing CWA map
  controller. No projection or image-processing code is duplicated.
- Removed the oversized Weather editorial hero and its dedicated responsive
  styles. Weather now moves directly from the Six Axis tabs into the candidate
  decision band; the compact candidate-only boundary remains beside the
  operational evidence.

Boundary:

- All output remains cache-only, candidate-only, and human-review-required.
  The API does not fetch CWA upstream, evaluate a newly submitted location,
  persist coordinates, call `/safety/*`, send LoRa/RF, control hardware, or
  mutate runtime safety truth.
- Raspberry Pi and mobile clients consume prepared display assets and compact
  JSON only; image decode, georeference, route sampling, and motion estimation
  remain server-side.

Verification:

- `tests/test_scout_dashboard_page.py`: 44 passed. The embedded Dashboard
  JavaScript also parses successfully as one script.
- `tests/test_admin_cwa_imagery_overlay.py` plus
  `tests/test_admin_cwa_precipitation_grid.py`: 17 passed, covering prepared
  route-decision evidence, missing-cache state, image assets, and rainfall-grid
  projection.
- Live 9099 browser smoke resolved the current project to `unavailable` and
  `DELAY`, rendered all nine route imagery risk fields as unknown/zero-confidence,
  and disabled Frame/Play because this workspace currently has no prepared CWA
  imagery frames. Missing coverage was not rendered as zero rain.
- An isolated two-frame cache browser smoke reached `CWA MAP BRIDGE · READY`.
  Frame moved from `1/2` to `2/2`, both visible timeline controls synchronized
  to frame index `1`, and radar opacity changed from `62` to `40` through the
  canonical map controller. No image processing ran in the Dashboard client.
- A 390 x 844 responsive smoke retained `DELAY`, the visible canonical map, and
  zero horizontal overflow; the viewport override was reset after verification.

### 2026-07-21 - Move desktop Emergency UI from Pace Fit to Safety / Emergency

User request:

- Move the existing Pace Fit `Emergency UI` into the Dashboard
  `Safety / Emergency` entry, using the non-mobile interface rather than
  embedding the phone presentation or creating a second copy.

Implementation steps:

- Removed the `outdoor-pace-fit-emergency` navigation child, route truth entry,
  data-scope entry, renderer, iframe, and Pace-specific Emergency CSS. Pace Fit
  now contains only Pace Dashboard and Body Index.
- Reused the existing same-origin
  `/admin/dashboard/emergency-approval-desktop-v0` projection, which removes the
  mobile device surface and retains only the desktop Emergency approval console.
- Replaced the Safety / Emergency summary-and-map placeholder with the complete
  desktop approval console iframe, a compact frame toolbar, and a post-frame
  boundary note. This is now the single Dashboard Emergency UI location.
- Kept the console available as a full-window desktop link for detailed review.
- Added focused Dashboard source contracts proving that the Pace Fit Emergency
  route no longer exists and that Safety / Emergency points only to the desktop
  endpoint, never to the legacy mobile URL.

Boundary:

- This is a same-origin UI integration only. It does not call `/safety/*`, drive
  hardware, publish MQTT, send outbound messages, or promote candidate/sandbox
  evidence to Phase 1 runtime safety truth. The visible `sent=false` state
  remains explicit.

Verification:

- Focused Dashboard navigation, route, desktop endpoint, documentation, truth,
  and Safety / Emergency contracts: `11 passed`.
- Dashboard plus Emergency UI adjacent suites completed twice. The first run was
  `45 passed, 1 failed`; its unrelated Body Index watch-counter timing assertion
  passed immediately when rerun alone (`1 passed`). The second run was also
  `45 passed, 1 failed`; this time the unrelated, concurrently edited
  Architecture contract expected `architecturePassageTimingNodes`, which is not
  present in the current Dashboard HTML. No Architecture code was changed here.
- Live `127.0.0.1:9099` checks returned `200` for both `/admin/dashboard` and the
  desktop Emergency endpoint.
- A read-only 1440 x 1000 browser replay confirmed one 1166 x 790 desktop iframe,
  zero mobile surfaces/devices, no Pace Fit Emergency route or label, no
  horizontal overflow, and no HTTP or JavaScript errors on a clean reload. No
  Emergency decision control was clicked.

### 2026-07-21 - Retain the complete golden-route axis and filter GPX pairwise

User request:

- Treat the curated golden GPX as the complete current-trip start/finish scope,
  include it as one statistical source, and filter speed per adjacent point pair
  instead of rejecting a whole track or segment from its average.

Implementation steps:

- Removed the provisional crowd-support rebase from the Architecture projection.
  The page now always renders the golden-route `0K -> finish` axis; sparse crowd
  coverage appears as missing/low-confidence bins rather than a cropped prefix.
- Reference pace/energy analysis now prefers each complete staged source GPX,
  applies strict `1 < speed_kmh < 10` to each adjacent timed pair, and retains all
  other valid pairs from the same source.
- Kept the golden route as an equal-weight `scope_reference`; its geometry role
  does not grant special statistical weight.
- Updated Route Fingerprint, map lens metadata, and the summary board to explain
  the golden-scope contract directly.

Boundary:

- This remains aggregate, candidate-only pretrip route-demand evidence. No raw
  GPX or precise timestamps are embedded, no runtime safety truth is changed,
  and no `/safety/*` or outbound transport is used.

### 2026-07-21 - Add a dynamic Architecture lens color legend

User request:

- Explain directly on the Architecture map what each lens color means.

Implementation steps:

- Added a lens-aware legend to the map instead of presenting only the active
  lens name and geometry provenance.
- Terrain, Slow Passage, and Risk Passage now expose the shared candidate
  pressure bands: low `0–31`, moderate `32–54`, high `55–77`, and very high
  `78–100`, plus an explicit no-observed-bin state.
- Evidence exposes high, medium, low, unknown, and unmatched-bin meanings.
  Structure explains that cyan encodes connected geometry rather than metric
  magnitude; Reversibility explains that gray remains unverified candidate
  topology rather than a safe-return claim.
- Added symbols for the selected-segment amber glow and white checkpoint marker.
  The legend is a full-width block below the SVG on desktop and mobile, so it
  never overlays or obscures the route.

Boundary:

- Legend text explains existing candidate metrics only. It does not add a map
  layer, promote candidate evidence, or alter runtime safety truth.

### 2026-07-21 - Connect Architecture to the real chilai workspace

User request:

- Point the Dashboard at `chilai_nanhua_day1_scoutAI`, calculate the planned
  Architecture content from that workspace, and render the missing map.

Implementation steps:

- Diagnosed the active `9099` process as the generic `server:app` launch without
  `SCOUT_PRETRIP_WORKSPACE_ROOT`; the requested project API therefore returned
  `404` even though the local workspace was complete. The supported local entry
  point is `tools.dashboard_workspace_app --workspace-root
  /Users/alexwang0315/workspace`.
- Fixed shared map-data normalization so a compact route with
  `display_geometry.coordinate_segments` and no flattened `coordinates` is
  treated as connected geometry. Route bounds now accept `bounds`,
  `display_bounds`, or the existing `bbox_wgs84` shapes.
- Loaded the project-selected `compiled_mission_graph_candidate_ref` and used it
  only as candidate topology. The deterministic projection now derives a
  candidate route type, graph node/edge counts, and summed graph baseline time
  while keeping reviewed topology and reversibility explicitly unverified.
- Added real workspace counts to the page: route distance, CP/segment topology,
  reference tracks and mobility bins, route-pressure samples/peaks, Boss
  candidates, graph duration, artifact lineage, and rendered geometry count.

Observed `chilai_nanhua_day1_scoutAI` evidence:

- route source name `12能高安東軍00`, 112.258 km;
- 23 reference tracks, 260 observed bins, 245 guidance-eligible bins;
- 240 checkpoints, 239 candidate graph edges, one retreat candidate;
- 225 route-pressure samples, 20 peaks, five Boss candidates;
- `closed_route_candidate`, based on a 95.643 m start/finish gap;
- `late_route_pressure`, strongest observed bin at 98.50–98.75K;
- 52.168 hours summed candidate-graph baseline duration;
- normalized route architecture and reviewed mission graph remain missing, so
  status stays `partial` and reversibility stays
  `candidate_graph_unverified`.

Boundary:

- Candidate-only pretrip projection. No raw GPX is embedded in the browser
  payload, no `/safety/*` call or Phase 1 mutation occurs, and no outbound or
  hardware action is introduced.

Verification:

- Focused Architecture and Dashboard tests: `48 passed`.
- Scoped Ruff checks: passed.
- Real workspace compact API: 260 bins, 239 graph edges, 239 route geometry
  segments, candidate graph duration 52.168 hours.
- Browser smoke: map rendered with 453 colored path groups, 25 sampled CP
  markers, all 260 fingerprint bins, and no document-level horizontal overflow.

### 2026-07-20 - Build Route Architecture Intelligence workbench

User request:

- Turn the historical ref-GPX mobility-demand research into the real
  `Architecture / Route Architecture Intelligence` page for Section 9 of the
  Outdoor AI Agent Standard.

Implementation steps:

- Added a deterministic `route_architecture_intelligence` projection to the
  compact pretrip project response. It joins aggregate historical mobility
  bins, CP/segment candidates, retreat candidates, route-pressure evidence,
  optional normalized route architecture, optional compiled mission graph,
  ETA/daylight summaries, source refs, privacy, and hard planning boundaries.
- Added the full-width expedition drafting-table UI with a horizontally
  scrollable seven-lane `Route Fingerprint`: CP graph, terrain demand,
  historical mobility demand, risk passage, reversibility, time window, and
  evidence confidence all share one route-distance axis.
- Added Structure, Demand, Reversibility, and Evidence reading modes; a
  page-local Architecture map lens recolors the existing `segments` data group
  for terrain, slow passage, risk passage, reversibility, and evidence quality
  without adding a 33rd map layer.
- Synchronized fingerprint and map selections with a `Segment Microscope`
  showing the P25/P50/P75 historical speed envelope, grade, provider risk
  value, viscosity, continuous movement, track/traversal counts, data quality,
  and artifact lineage.
- Added a retreat-dependency view that shows only recorded candidate edges.
  Missing normalized architecture and compiled mission graph remain visible as
  `partial`; the UI does not invent branches, alternatives, or reversibility
  scores.
- Added a mobile-specific vertical route spine, sticky `Spine / Map / Segment`
  switch, and sticky segment inspector. The desktop fingerprint keeps its
  1780px working width and pans horizontally instead of shrinking to fit.

Current workspace evidence:

- `status=partial`;
- 260 observed mobility bins, 245 guidance-eligible;
- 239 segment candidates and one retreat candidate;
- `demand_shape=late_route_pressure`;
- normalized route architecture and compiled mission graph are both missing,
  so route type remains `unclassified` and reversibility remains `unverified`.

Boundary notes:

- Historical GPX is a selection-biased, sensorless route-demand estimate. It
  is not personal capacity, measured metabolic power, a completion probability,
  or runtime safety truth.
- The projection contains aggregate route metrics only: no raw GPX, raw health
  payload, precise activity timestamps, or home/work traces.
- The page is read-only and candidate-only. It makes no safety API call, Phase
  1 mutation, outbound send, or hardware action.

Verification:

- `PYTHONDONTWRITEBYTECODE=1 rtk ./venv/bin/python -m pytest tests/test_pretrip_route_architecture_intelligence.py -q`: 4 passed.
- `PYTHONDONTWRITEBYTECODE=1 rtk ./venv/bin/python -m pytest tests/test_scout_dashboard_page.py -q`: 43 passed.
- Combined Architecture + Dashboard focused run: 47 passed.
- `PYTHONDONTWRITEBYTECODE=1 rtk ./venv/bin/python -m pytest tests/test_pretrip_admin_view.py -q`: 29 passed.
- `rtk ruff check` on the changed Python/test surface: passed.
- Live 9199 compact endpoint: `partial`, 260 bins, privacy boundary true and
  runtime-safety-truth false.
- Desktop Playwright at 1440x1000: 260 fingerprint bins, synchronized segment
  selection, risk lens switch, 453 bounded map paths after rendering
  compaction, horizontal fingerprint pan, no body overflow, and no page errors.
- Mobile Playwright at 390x844: vertical spine, Segment and Map transitions,
  sticky mobile switch, `scrollWidth=clientWidth=390`, and no page errors.
- The adjacent Outdoor Standard coverage run passed 66 checks and retained two
  unrelated dirty-worktree failures: its registry count still expects 26 tools
  while the concurrent AI/tool workstream currently exposes 29.

### 2026-07-17 - Promote the Weather prototype into the Dashboard design system

User request:

- Restore the stronger, livelier visual direction from
  `docs/admin/scout-six-axis-weather-design.html` and apply that design language
  across every Dashboard page and all six-force capabilities instead of making
  Weather conform to the legacy visual shell.

Implementation steps:

- Added the shared `field-instrument-theme` to the real Dashboard shell with the
  prototype's forest-night canvas, lichen accent, amber warning, coral risk,
  cyan weather evidence, editorial headings, monospace evidence labels, sharp
  panels, textured map field, and restrained entrance motion.
- Applied the theme through common selectors for the sidebar, topbar, truth
  strip, workspace, panels, tabs, buttons, inputs, tables, maps, Evidence drawer,
  embedded admin surfaces, Agent, Debug, Living, Body Index, and Route Context;
  existing route markup and functionality remain intact.
- Restored the Weather prototype's hero statement and high-contrast decision
  instrument composition while keeping the integrated live CWA cache, canonical
  map layers, source timeline, recheck control, and compact Evidence drawer.
- Retained the corrected data-integrity behavior: unavailable rainfall and
  imagery produce `DELAY`, and the integrated page does not reuse the standalone
  prototype's fictional CP IDs, forecast times, or route decisions.
- Added responsive and reduced-motion rules so the design system applies to the
  desktop shell, mobile navigation drawer, narrow page grids, and accessible
  motion preferences.

Boundary notes:

- This is a visual-system promotion and Weather composition change. It does not
  modify API routes, persistence, safety policy, hardware control, or outbound
  behavior.
- Candidate weather layers remain cache-only and cannot represent or mutate
  runtime safety truth.

Verification:

- `python3 -m pytest -q tests/test_scout_dashboard_page.py`: passed.
- `pnpm typecheck`, `npm run lint`, and scoped `git diff --check`: passed.
- Desktop Playwright route sweep covered 24 Dashboard routes: Overview, trip
  planning, map/evidence, all six forces and Pace extensions, Emergency,
  Assistant, Living, embedded admin/debug surfaces, Observer, and Settings.
  Every route retained the shared theme, active navigation, non-empty title,
  and expected lichen design token without page-level JavaScript errors.
- Mobile Playwright sweep covered Overview plus all six forces at 390x844 with
  no horizontal page overflow. Six-force tabs remain horizontally scrollable.
- Visual evidence was captured for Overview, Route Context, Weather, Settings,
  and mobile Weather. Weather retained `DELAY` under the current missing-cache
  replay and did not fabricate a route decision.

### 2026-07-17 - Align Weather with the shared six-force UI

User request:

- Keep the Weather prototype's route-decision functionality while aligning its
  visual language with the other five `Exploring for Six Axis` pages.

Implementation steps:

- Rebuilt the Weather page on the existing Dashboard tabs, panels, chips,
  spacing, typography, map controls, responsive breakpoints, and compact
  Evidence drawer instead of importing the standalone prototype's separate
  application shell.
- Added a shared-style decision-readiness band, a 65/35 route-weather workspace,
  the canonical Scout Map filtered to weather-relevant layers, a source-time
  evidence timeline, operator next actions, and a read-only CWA integrity card.
- Added a working `Recheck candidate evidence` action that force-refreshes the
  existing rainfall-grid and weather-imagery data scopes without adding a new
  network or mutation path.
- Moved generic weather rules into a collapsed reference panel so live project
  evidence and the route intersection remain the primary reading path.
- Removed fictional CP and clock values from the integrated page. A route
  segment is not named until the available cache evidence is actually joined
  to route geometry.

Boundary notes:

- The page labels cache-only CWA products as candidate evidence and does not
  represent them as runtime safety truth.
- Freshness and bbox coverage make the evidence ready for operator review; they
  do not independently prove `GO`. Missing, stale, failed, or uncovered data
  produces a conservative `DELAY` posture.
- No `/safety/*`, outbound transport, hardware action, or Phase 1 mutation was
  added.

Verification:

- `python3 -m pytest -q tests/test_scout_dashboard_page.py`: passed.
- `pnpm typecheck`, `npm run lint`, and scoped `git diff --check`: passed.
- Desktop Playwright smoke at 1440x1000: six Six Axis tabs, 13
  weather-relevant map layers, working cache recheck, no horizontal overflow,
  and no page-level JavaScript errors.
- Mobile Playwright smoke at 390x844: shared Weather layout rendered without
  horizontal overflow; decision band and source timeline collapsed to one
  column.
- Degraded-data replay correctly rendered `DELAY` instead of `REVIEW READY`
  when neither rainfall nor imagery evidence was available.

### 2026-07-17 - Restore six-force navigation grouping

User request:

- Restore the six mountain capabilities from
  `docs/specs/SCOUT_OUTDOOR_AI_AGENT_STANDARD.md` sections 6-11 as one coherent
  left-navigation group instead of scattering them across Team & Pace, Safety
  Decisions, and Labs / Preview.

Implementation steps:

- Restored `Exploring for Six Axis` as the single navigation parent for Route
  Context, Pace Fit, Permission, Architecture, Weather, and Navigation in the
  standard's defined order.
- Kept Body Index and Emergency UI as nested Pace Fit extensions without
  presenting either extension as a seventh force.
- Promoted Safety / Emergency to a separate operator entry and removed the
  obsolete Team & Pace and Labs / Preview buckets.
- Collapsed non-active Plan Trip and Map & Evidence groups by default, while
  automatically opening every navigation ancestor of the active route so the
  current capability remains discoverable.
- Added an explicit six-force navigation contract and regression coverage for
  membership, order, extension placement, and the seven-item primary shell.

Boundary notes:

- This is a navigation and information-architecture correction only. Route
  maturity, data provenance, runtime behavior, and safety-effect boundaries are
  unchanged.

Verification:

- `python3 -m pytest -q tests/test_scout_dashboard_page.py`: 39 passed.
- `pnpm lint` and `pnpm typecheck`: passed.
- Desktop 1280x720 browser smoke: all six routes visible inside the sidebar,
  obsolete groups absent, and no horizontal overflow.
- Mobile 390x844 drawer smoke: the six-force group and all six routes visible,
  with `scrollWidth=clientWidth=390`.
- Repository `pnpm test`: 15 passed, 2 pre-existing AI OS documentation
  assertions failed; no Dashboard test failed.

### 2026-07-17 - Compact secondary six-force evidence drawers

User request:

- Collapse Permission Evidence, Architecture Evidence, Weather Evidence, and
  Navigation Evidence because the always-open secondary drawer consumed too
  much of the working surface.

Implementation steps:

- Added a route-scoped compact Evidence contract for the four requested pages;
  Route Context and Pace Fit behavior remains unchanged.
- The four Evidence drawers now default to a 48px desktop rail and expose an
  accessible Expand / Collapse control with `aria-expanded`, `aria-controls`,
  hidden-body semantics, and focus restoration after rerender.
- Expanded Evidence retains the existing 320-380px detail drawer and all
  Project, Workspace, Boundary, reference, and issue-tag content.
- At the mobile breakpoint, the compact drawer becomes a 44px horizontal row
  rather than reserving a second column.

Boundary notes:

- Evidence content and provenance are unchanged; this only changes default
  presentation and available workspace width.
- Drawer expansion is session-local UI state and does not persist or mutate
  project artifacts.

Verification:

- `python3 -m pytest -q tests/test_scout_dashboard_page.py`: 40 passed.
- `pnpm lint`, `pnpm typecheck`, and scoped `git diff --check`: passed.
- Desktop 1280x720: all four requested routes defaulted to a 48px collapsed
  Evidence rail without horizontal overflow.
- Permission Evidence expanded to 380px, collapsed back to 48px, preserved the
  correct accessible label, and returned focus to the toggle.
- Mobile 390x844: collapsed Navigation Evidence rendered as a 44px row with
  `scrollWidth=clientWidth=390`.

### 2026-07-13 - Dashboard and CWA P0-P2 completion

User request:

- Complete the full P0-P2 improvement backlog from the Dashboard review and
  the follow-up review of commit `e7ee30ca`.

P0 correctness and safety:

- Rainfall and imagery artifacts now bind `projectId`, the active
  Overpass-aligned-or-base route ref and SHA-256, source frame ids, and a
  deterministic pair id. Projection/trend files are prepared before the
  active manifest; failed multi-file publication rolls back instead of
  exposing a mixed generation.
- Rainfall truth has explicit `stale_data`, `no_coverage`, `missing_data`,
  `partial`, and zero-precipitation semantics. Unknown/no-data can no longer
  appear as `ready`, and unusable samples have zero confidence.
- CWA timestamps are evaluated against one injected server clock. Imagery
  freshness is recomputed on read and a missing cache asset is not advertised
  as an available URL.
- Current-position sampling now supports server-issued, project-scoped,
  expiring approval records. Attempt/completion/failure audits are durable but
  never persist latitude or longitude. Unregistered caller attestations are
  rejected by default; legacy acceptance requires an explicit server-side
  compatibility flag and is not enabled by the Dashboard workspace app.
- Final review hardening moved same-run Overpass alignment before CWA
  preparation, validates embedded route artifact kind/project identity, and
  rejects projection/manifest or projection/trend pair mismatches before any
  freshness or cells are exposed.
- Pre-trip artifact refs now resolve inside the selected project root with
  absolute, parent traversal, and symlink escape checks. The enriched debug
  projection applies the same project/route/pair validation as direct CWA
  endpoints.

P1 data and performance integration:

- Dashboard Weather consumes the same-project cache-only rainfall-grid and
  imagery endpoints. Pre-trip lazily loads bounded rainfall cells from
  `gridOverlayEndpoint`; an admin read never fetches CWA upstream.
- The compact project API removes duplicate heavy structures, serves rainfall
  cells lazily, and uses gzip in the real 9099 workspace app. On the current
  Chilai-Nanhua workspace the response changed from about 34.9 MB and
  100-second-class duplicate reads to 13.5 MB raw / about 1.01 MB gzip and
  5.5-8.5 seconds server time.
- Data is loaded per Dashboard route. Project id fallback from
  `_scoutAI` to an older project has been removed; failed debug endpoints show
  `DEGRADED` and expose an operator retry.

P2 information architecture and responsive UI:

- Primary navigation is consolidated into eight groups: Overview, Plan Trip,
  Map & Evidence, Team & Pace, Safety Decisions, Assistant, System, and Labs /
  Preview. Existing route ids remain compatible, and live/partial/preview
  states are disclosed.
- The map defaults to radar only. Playback is disabled with fewer than two
  frames, timestamps use Asia/Taipei semantic labels, and stale/no-coverage/
  zero/unavailable states use one shared truth model.
- Mobile navigation and a 44 px touch-target CWA peek/expanded sheet were
  added. The expanded sheet scrolls inside the evidence rail, remains within
  70dvh, respects the safe area, and preserves at least 25% visible map height.
- Mobile Map keeps the navigation drawer available and marks the off-canvas
  drawer inert/hidden to assistive technology while closed. Project changes
  update the URL and reload the page, preventing old-project async state from
  leaking into the newly selected project.
- Debug and after-action surfaces disclose that persisted rainfall-grid
  rendering is fully supported only in Pre-trip and Dashboard Map. Legacy
  example weather rules are labelled Preview rather than live decisions.

Boundary notes:

- All CWA-derived outputs remain cache-only, candidate-only, human-review
  evidence. No `/safety/*` path, Phase 1 runtime safety truth, recurring
  monitor, outbound send, or client-side image/grid processing was added.
- The current workspace still contains the pre-P0 CWA generation without the
  new route/pair fields. It remains readable as a legacy snapshot and is
  truthfully shown as stale. The next explicitly approved CWA preparation will
  publish the new provenance contract; this closeout did not silently refetch
  external weather data.

Verification:

- P0-P2 focused pytest: PASS (`92 passed`).
- Full pre-trip admin API regression: PASS (`81 passed`).
- Focused pre-trip CWA layer preparation: PASS (`3 passed`).
- `pnpm lint`, `pnpm typecheck`, and `pnpm test`: PASS (`17 passed`).
- Repo and real-workspace 32-layer contracts: PASS.
- Chromium admin smoke: PASS on desktop, 390x844, and 320x720; all expected
  layer toggles, keyboard controls, frame reuse, and overflow checks passed.
- Live 9099: PASS with 239 Segment paths, one cache-backed radar overlay,
  truthful stale/QPF-no-coverage display, no console/HTTP errors, and mobile
  expanded-sheet bounds of 377-824 px with 218 px of map still visible.

### 2026-07-13 - Dashboard MAP CWA numeric rainfall grids

- Reused the existing `cwa-qpf` layer for CWA past-one-hour QPE and
  next-one-hour QPF; the 32-layer contract remains unchanged.
- Added Dashboard/pretrip controls for rainfall product and opacity, plus the
  official millimetre color scale, source time, validity, and delay metadata.
- Recalculates product freshness on every read: QPF uses its forecast
  `validUntil`, QPE uses `sourceTimestamp + 2 hours`, and expired selections are
  visibly marked `STALE` instead of remaining `ready`.
- Persisted full validated numeric frames only in the workspace server output;
  the browser receives route-clipped cells and compact trend features.
- Added deterministic current-position, explicit-target, and route-corridor
  sampling. The cache-only evaluator validates input and omits submitted
  coordinates from both response and persistent artifacts.
- Raspberry Pi/mobile remain consumers of prepared compact outputs and never
  fetch, georeference, or sample full CWA grids.
- This slice installs no recurring monitoring schedule. Every explicit
  preparation refetches current CWA truth and appends a deduplicated evidence
  snapshot.

### 2026-07-13 - Dashboard MAP CWA imagery controls

User request:

- Integrate prepared CWA radar and satellite imagery into the Dashboard MAP
  page and update the related documentation.

Implementation steps:

- Kept `/admin/pretrip` as the single canonical map renderer and added a
  same-origin pretrip controller named `scoutCwaImageryController`.
- Added Dashboard-native controls for the `cwa-weather` layer, prepared
  product, 3/6/9/12-hour window, frame, radar/satellite opacity, and
  play/pause state.
- Mirrored only compact display state from the iframe. The Dashboard does not
  receive raw cache refs, ETags, credentials, upstream URLs, or image pixels
  for browser-side processing.
- Added a polite live status for source timestamp, data delay, type, extent,
  and explicit `not prepared` handling.

Boundary notes:

- Dashboard reads remain cache-only and candidate-only.
- Fetch, decode, georeference, route sampling, and motion estimation remain
  server-side. Raspberry Pi/mobile clients are compact artifact consumers.
- `cwa-weather` remains one of the existing 32 top-level layers; no new layer
  id or runtime safety-truth path was added.

Verification:

- Dashboard/CWA focused tests and keyboard/status accessibility assertions.
- 32-layer verifier and Dashboard desktop/mobile browser smoke.
- Real workspace verification uses `/admin/dashboard?projectId=<id>#map`
  after the approved one-shot CWA preparation worker has produced the cache
  manifest.

### 2026-07-02 - Scout Dashboard v0.1 Initial Integration

User request:

- Build a Vibe-Trading-like Scout Dashboard v0.1 with left navigation and a
  large content frame.
- Integrate existing `/admin`, `/admin/debug`, `/admin/pretrip`, map, timeline
  evidence, debug messages, MQTT/observer messages, settings/configure,
  safety/emergency context, and Outdoor/Six Axis pages.

Implementation steps:

- Created the dashboard shell at `docs/admin/scout-dashboard-v0.1.html`.
- Added left navigation sections for Home, Features, Admin Surfaces, Agent,
  Map, Timeline Evidence, Safety / Emergency, Exploring for Six Axis, Debug
  Message, MQTT / Observer Message, and Settings / Configure.
- Embedded existing admin surfaces through dashboard routes rather than
  replacing their original pages.
- Added the dashboard route at `/admin/dashboard` through the admin API static
  shell.
- Added tests in `tests/test_scout_dashboard_page.py`.

Boundary notes:

- Existing admin pages remain canonical for their own operator workflows.
- Dashboard surfaces are read-only or operator-intent-only unless explicitly
  routed to existing admin tooling.

Verification:

- Focused dashboard tests.
- Browser smoke through the admin server.

### 2026-07-02 - Map Page Uses Pre-trip Map Only

User request:

- The Map page should show only the map; do not embed the full pre-trip page
  with tabs and lower panels inside the Map page.
- The map should be scrollable and not clipped.
- Timeline evidence should be merged into the Map page and collapsible.

Implementation steps:

- Changed the dashboard Map route to keep a persistent `/admin/pretrip`
  map-only iframe.
- Hid the non-map pre-trip panels inside the dashboard map frame.
- Added map frame reuse checks so switching routes does not reload the map.
- Added collapsible map evidence rail with pre-trip evidence categories
  collapsed by default.
- Verified map frame layout on desktop and mobile.

Boundary notes:

- The Map page reuses the existing `/admin/pretrip` map rendering rather than
  forking GIS rendering logic.
- Timeline evidence selection remains dashboard/UI state and does not mutate
  safety truth.

Verification:

- Playwright smoke for dashboard map frame reuse.
- Admin visual smoke for map layer toggles.
- Scout layer contract verification for the 32-layer contract.

### 2026-07-02 - Agent Frame Integration

User request:

- Integrate `http://127.0.0.1:8765/` into the Agent tab.
- Make the embedded agent compact enough that Send is visible without a long
  scroll.

Implementation steps:

- Added dashboard Agent route and persistent iframe for the local Scout AI Mac
  Chat.
- Used compact embed query parameters for the local frame.
- Adjusted dashboard wide-frame behavior to reduce text overflow and fit the
  embedded chat.

Boundary notes:

- Agent frame remains local `127.0.0.1`.
- No live safety automation is connected from the dashboard Agent tab.

Verification:

- Dashboard page tests for agent iframe contract.
- Browser smoke for visible frame behavior.

### 2026-07-08 - Agent Tab Same-Origin Scout AI Chat

User request:

- Connect `http://127.0.0.1:9099/admin/dashboard?projectId=chilai_nanhua_day1_scoutAI#agent`
  directly to Scout AI so the dashboard can be used as the conversation surface.

Implementation steps:

- Replaced the old `127.0.0.1:8765` Mac chat iframe with a native dashboard
  chat panel.
- The Agent tab now checks `/assistant/status` and sends questions to
  `/assistant/query` on the same 9099 server.
- The request uses `surface=pretrip` and preserves the dashboard
  `projectId` as the Scout AI `project_id`.
- Added provider/status chips, read-only boundary display, transcript rendering,
  Enter-to-send, Shift+Enter newline, and clear-on-submit behavior.

Boundary notes:

- The dashboard does not call `/safety/*`, send outbound messages, or control
  hardware.
- `/assistant/query` must be mounted by launching the 9099 server with
  `SCOUT_AI_ASSISTANT_ENABLED=1`.
- If the assistant API is not mounted, the Agent tab shows a disconnected state
  instead of silently falling back to another server.

Verification:

- Dashboard page tests for same-origin Assistant API wiring.
- Manual smoke should use the 9099 dashboard URL and confirm one visible
  assistant answer from `/assistant/query`.

### 2026-07-02 - Workspace Statistics, Cache, and Operations

User request:

- Add workspace statistics such as length, counts, imported time, and other
  lifecycle metrics.
- Show workspace structure, cached materials, cached TTL, and basic operations
  such as clone, transfer, pack, restore, delete, and switch workspace.

Implementation steps:

- Added `Workspace` panels for route statistics, project counts, lifecycle
  times, workspace structure, material index, cached material, cached TTL, and
  cache refs.
- Added operator-intent buttons for Clone, Transfer, Pack, Restore, Delete.
- Added dashboard workspace switching through `scout.dashboardProjectId` and
  URL `projectId`.

Boundary notes:

- Workspace operations are recorded as operator intent only.
- Delete requires explicit destructive approval outside the dashboard.
- No filesystem mutation is performed by these dashboard controls.

Verification:

- Dashboard regression tests for workspace stats, cache, structure, and
  operations.

### 2026-07-02 - Exploring for Six Axis Rename

User request:

- Rename `戶外六力` to `Exploring for Six Axis`.
- Remove Chinese subtree names and keep only English labels.

Implementation steps:

- Updated the left navigation group name and six subtree labels.
- Updated dashboard evidence title generation for six-axis pages.
- Added tests that removed Chinese labels no longer appear in the dashboard
  shell.

Boundary notes:

- The underlying `SCOUT_OUTDOOR_AI_AGENT_STANDARD` alignment remains unchanged.

Verification:

- Dashboard regression tests.

### 2026-07-02 - Debug Message Dashboard Redesign

User request:

- Move event, hardware, software, Ln/API/skills/tools and debug information
  from the existing debug UI into the Debug Message tab.
- Represent hardware/software/API information graphically rather than as plain
  text lists.
- Match the professional dashboard style shown in the provided references.

Implementation steps:

- Added debug telemetry bar, runtime detail tabs, visual nodes, hardware
  interface bus, provider panels, boundary gates, API payload tiles, and stream
  tables.
- Connected dashboard debug panels to `/debug/events`, `/debug/state`,
  `/debug/messages`, `/debug/mobile-wearable/ingress`,
  `/debug/monitoring`, and `/admin/hardware-readiness/context`.
- Added graphical summaries for hardware readiness, GPIO/I2C/UART-style
  interfaces, providers, API payloads, outbound state, boundary state, skills,
  and tools.

Boundary notes:

- Debug Message is read-only.
- Outbound and safety states are evidence/metadata only and do not trigger
  live transport or safety mutation.

Verification:

- Dashboard debug contract tests.

### 2026-07-06 - Map Evidence Payload Timeout Fix

User request:

- Map evidence appeared to lose Segment and CP evidence while MCP still
  appeared available.

Implementation steps:

- Verified direct `/admin/pretrip?projectId=chilai_nanhua_day1_scoutAI`
  still rendered the map layer SVG groups for route, segments, checkpoints,
  MCP, and boss points.
- Verified the dashboard map iframe also retained visible SVG layer groups for
  route, segments, checkpoints, MCP, and boss points.
- Found the dashboard outer shell was aborting its own 35MB
  `/admin/pretrip/projects/... ?compact=1` evidence payload after the generic
  20 second fetch timeout, leaving the Map Evidence rail stuck at loading.
- Added a dedicated 180 second timeout only for the pretrip project compact
  payload while keeping ordinary dashboard/debug API requests at 20 seconds.
- Kept existing Map Evidence group placement unchanged; `Segments` remains in
  its prior dashboard tab unless an operator explicitly asks for a layout
  change.

Boundary notes:

- This change only affects dashboard evidence loading.
- It does not rebuild GIS data, mutate workspace files, trigger live safety
  automation, or send outbound messages.
- The canonical `/admin/pretrip` map rendering remains unchanged.

Verification:

- Browser inspection confirmed direct pretrip and dashboard iframe retained
  `segments`, `checkpoints`, `mcp`, `boss-points`, and `route` layer groups.
- Focused dashboard tests cover the dedicated pretrip evidence timeout and
  preserve the existing `Segments` group placement.
- Admin visual smoke returned `ok: true` for `/admin/debug`, `/admin`,
  `/admin/pretrip`, and the dashboard map-only shell.

### 2026-07-06 - Pace Fit Low-Information Blocks Removed

User request:

- Remove low-information Pace Fit content, including `Readiness & Pace Fit`,
  `Decision`, `Confidence`, and `Next action`.

Implementation steps:

- Removed the Pace Fit page decision band.
- Removed the `Readiness & Pace Fit` metric panel.
- Changed the Pace Fit topbar and six-axis summary system label so
  `Readiness & Pace Fit` no longer appears in the dashboard UI.
- Kept the Pace Fit page focused on the `Challenge Fit` pace budget panel.
- Removed the `CHANGE_PLAN` chip and `Data confidence` row from Pace Fit.

Boundary notes:

- This is a dashboard layout/content cleanup only.
- No map data, GIS layers, workspace files, safety truth, live safety
  automation, or outbound transport behavior changed.

Verification:

- Dashboard regression tests assert the removed Pace Fit blocks stay absent.

### 2026-07-06 - Pace Fit Dashboard Information Added

User request:

- Add Pace Fit information using the professional dense dashboard style shown
  in the provided reference image.

Implementation steps:

- Expanded Pace Fit into a three-column operator dashboard.
- Added route/current CP/leave-by/team pace/boundary status cells.
- Added Pace Controls, Current CP Status, Next Segment Risk, Risk Budget
  Calculator, CP Timeline, Pace Output, Pace Evidence, Artifact Metadata,
  Residual Risk, Pace Object Preview, and Synchronized Map sections.
- Used compact visual tables, bars, status chips, checkpoint dots, and a small
  route map instead of long explanatory prose.
- Set Pace Fit to wide-frame mode so its built-in right-side Pace Evidence
  drawer is not squeezed by the dashboard's generic evidence drawer.
- Preserved the prior removal of low-information `Decision`, `Confidence`,
  and `Next action` style header content.

Boundary notes:

- Pace Fit remains advisory/dry-run dashboard content.
- The page does not mutate safety truth, publish outbound messages, or change
  workspace files.

Verification:

- Dashboard regression tests assert the Pace Fit dashboard blocks and visual
  classes exist while the removed low-information blocks remain absent.

### 2026-07-06 - Pace Fit Emergency UI Subtree

User request:

- Integrate the Emergency UI from
  `docs/specs/scout-runtime-multi-gate-safety-reducer.md` into the Pace Fit
  subtree.

Implementation steps:

- Added a Pace Fit subtree under Exploring for Six Axis with `Pace Dashboard`
  and `Emergency UI` child routes.
- Added `outdoor-pace-fit-emergency` as a dashboard route.
- Embedded the Emergency UI in a wide-frame Pace Fit emergency page through
  the read-only dashboard route. The current embedded route is the
  desktop-only `/admin/dashboard/emergency-approval-desktop-v0` variant.
- Added local review boundary chips for `pending approval`, `sent=false`,
  `no safety endpoint`, and `no outbound transport`.
- Kept the mobile emergency approval surface as an independent static file and
  provided an `Open standalone` link.

Boundary notes:

- This dashboard integration is local review only.
- It does not call `/safety/*`, mutate Phase 1 runtime safety truth, invoke
  SMS/LoRa/MQTT/satellite transport, or claim verified delivery.
- Approval artifacts remain preview/dry-run unless a future production
  transport and authenticated approval workflow are added.

Verification:

- Dashboard regression tests assert the Pace Fit emergency subtree, iframe
  source, and boundary chips are present.

### 2026-07-06 - Pace Fit Emergency Desktop-only Frame

User request:

- In the Pace Fit emergency page, keep only the right-side emergency approval
  console and remove the left-side mobile version from the dashboard frame.

Implementation steps:

- Kept the standalone `docs/emergency/scout-emergency-mobile-approval-v0.html`
  file unchanged so the independent mobile artifact remains available outside
  the dashboard.
- Added a dashboard-serving desktop-only variant at
  `/admin/dashboard/emergency-approval-desktop-v0`.
- Removed the mobile `<section>` from the dashboard route response before it is
  embedded.
- Updated the Pace Fit emergency iframe to use the desktop-only route and
  added a `desktop only` boundary chip.
- Kept `/admin/dashboard/emergency-mobile-approval-v0` as a compatibility
  route, but it now returns the same desktop-only dashboard variant.

Boundary notes:

- This is a dashboard display change only.
- No safety endpoint, Phase 1 safety truth, SMS/LoRa/MQTT/satellite transport,
  or verified delivery behavior was added.

Verification:

- Dashboard regression tests assert the embedded route contains the desktop
  emergency surface and omits the mobile surface.

### 2026-07-06 - Pace Fit Emergency Header Cleanup

User request:

- Remove the low-value Pace Fit emergency header text from both the dashboard
  frame and the embedded desktop console.

Implementation steps:

- Removed the dashboard frame title and explanatory sentence above the
  emergency iframe.
- Kept only the compact boundary chip toolbar for `desktop only`,
  `pending approval`, `sent=false`, `no safety endpoint`, and
  `no outbound transport`.
- Removed the embedded desktop console header from the dashboard-served
  desktop-only variant.
- Moved `sent=false` into the Transport Readiness section so the boundary is
  still visible without taking header space.

Boundary notes:

- Display cleanup only.
- No safety endpoint, Phase 1 safety truth, outbound transport, or verified
  delivery behavior changed.

Verification:

- Dashboard regression tests assert the removed header text is absent and the
  desktop-only emergency surface still exposes `sent=false`.

### 2026-07-06 - Dashboard Low-value Information Cleanup

User request:

- Clear invalid or low-value information from Scout Dashboard v0.1.

Implementation steps:

- Removed the global page subtitle from the top bar.
- Removed repeated global status chips for `workable alpha`,
  `artifact boundary`, and long safety-boundary prose from the top bar.
- Removed the dashboard-wide decision band pattern and its unused CSS.
- Removed low-value decision/status bands from Home, timeline, LBS, Workspace,
  Import New Trip, Country Material Pool, Agent, Emergency, Observer,
  Settings, and non-Pace outdoor six-axis pages.
- Shortened admin surface labels and route summaries to direct operational
  labels.
- Shortened safety/outbound boundary copy to compact `closed` labels where the
  boundary still matters.

Boundary notes:

- Dashboard display cleanup only.
- No workspace mutation, map layer change, safety endpoint, Phase 1 safety
  truth mutation, or outbound transport behavior changed.

Verification:

- Dashboard regression tests assert removed low-value text and decision band
  structures stay absent while functional controls, frames, and boundary
  markers remain.

### 2026-07-02 - Import New Trip Tab Added

User request:

- Add an `Import New Trip` tab under Workspace/Features.

Implementation steps:

- Added `Features / Import New Trip` navigation route.
- Added `renderImportNewTripPage`, `renderImportTripPreflight`, and
  `renderImportTripPipeline`.
- Added basic intake fields for trip id, golden route GPX, and target
  workspace.
- Added Validate, Stage Import, and Open Workspace actions.
- Added draft state so dashboard re-rendering does not reset typed import
  values.
- Added Open Workspace behavior that stores `scout.dashboardProjectId` and
  routes to `Features / Workspace`.

Boundary notes:

- Validate and Stage Import only update dashboard status.
- Open Workspace only changes dashboard routing state.
- Import execution stays in the existing admin/import tooling.

Verification:

- `./venv/bin/python -m pytest tests/test_scout_dashboard_page.py -q`
- `pnpm lint`
- `pnpm typecheck`
- `pnpm test`
- Playwright Import New Trip smoke.

### 2026-07-02 - GPX Import and Map Preparation Parameters Exposed

User request:

- Confirm whether GPX import and map preparation parameters are open in
  `Import New Trip`; expose missing parameters.

Implementation steps:

- Compared the new dashboard page against `pretrip_import.py`,
  `pretrip_layer_preparation.py`, and the existing `/admin/pretrip` Import GPX
  panel.
- Added `GPX Import Parameters` for golden route GPX, reference GPX sources,
  workspace root, template project root, material root, DTM dirs, MCP
  named-point evidence, import profile, import stage, checkpoint spacing,
  max reference display points, GPX speed filtering, and overwrite.
- Added `Map Preparation Parameters` for layer ids, workspace/project root,
  bbox, route evidence bundle, route/reference corridors, preparation profile,
  network mode, explicit fetch flag, AI mode and output policy, imagery zoom
  and cache seed options, OSM PBF settings, osmium binary, and prepared time.
- Added front-end validation for required golden route GPX, layer ids, import
  numeric parameters, and map-preparation corridor parameters.

Boundary notes:

- The page prepares and validates parameters only.
- It does not perform server-side import or layer preparation directly.
- It preserves the operator-triggered artifact boundary.

Verification:

- Dashboard regression tests.
- Playwright parameter smoke against `http://127.0.0.1:9099`.
- `pnpm lint`
- `pnpm typecheck`
- `pnpm test`
- Scout layer contract repo/workspace gates.
- Admin visual smoke on isolated port `9109`.

### 2026-07-02 - Reference GPX Inputs Merged

User request:

- Merge `Reference GPX directory` and `Reference GPX paths` into one input.
- Accept either a full directory path so the importer can use all GPX files in
  that directory, or a list of multiple absolute GPX paths.

Implementation steps:

- Replaced the two separate reference fields with one textarea:
  `Reference GPX directory or paths`.
- Added `splitImportReferenceGpxSources` to split newline, comma, or semicolon
  separated entries.
- Added `classifyImportReferenceGpxSources` to classify the merged input as:
  `none`, `directory`, `explicit_gpx_paths`, or `invalid`.
- Allowed one absolute directory path or one/multiple `.gpx` absolute paths.
- Rejected mixed directory and GPX lists with:
  `Use either one directory path or a list of .gpx absolute paths.`
- Rejected relative entries with:
  `Reference GPX sources must be absolute paths.`
- Updated regression tests so the old `importReferenceDirectory` and
  `importReferenceGpxPaths` ids are no longer allowed.

Boundary notes:

- This is still front-end classification only.
- The backend importer remains responsible for actually expanding a directory
  through `reference_dir` or consuming explicit `reference_gpx_paths` when the
  operator-approved admin/import tooling runs.

Verification:

- `./venv/bin/python -m pytest tests/test_scout_dashboard_page.py -q`
- `pnpm lint`
- `pnpm typecheck`
- `pnpm test`
- Playwright smoke verified:
  - old fields are absent;
  - single directory path is accepted;
  - multiple absolute `.gpx` paths are accepted;
  - mixed inputs are rejected.
- Scout layer contract repo/workspace gates.
- Full admin visual smoke on isolated port `9109`.

### 2026-07-02 - Documentation Recording Rule Added

User request:

- Record every subsequent modification and supplement process in Scout
  Dashboard v0.1 documentation until the user says recording may stop.

Implementation steps:

- Added this document as `docs/admin/scout-dashboard-v0.1.md`.
- Added the active recording rule and stop condition.
- Backfilled the implementation record for the dashboard work already done in
  this thread.
- Added a regression test so the documentation record remains present and
  names the active logging rule.

Boundary notes:

- This document records process and decisions only.
- It does not change dashboard runtime behavior.

Verification:

- Dashboard documentation contract test.

### 2026-07-02 - Template Project Root and Material Root Clarified

User request:

- Explain what `Template project root` and `Material root` mean in
  `Import New Trip`.

Implementation steps:

- Checked `pretrip_import.py` and the Scout workspace/material specs.
- Confirmed that `template_project_root` is copied into the new project
  workspace with `shutil.copytree(...)` when the workspace is created.
- Confirmed that `material_root` is an input material bundle used by importer
  lookups such as material manifest, DTM source dirs, and MCP named-point
  evidence.
- Clarified that template content is a workspace skeleton or existing project
  baseline, while material content is source material consumed during import
  and preparation.

Boundary notes:

- This clarification does not change runtime behavior.
- The dashboard still records/imports these as operator-provided paths only.

Verification:

- Source review of `pretrip_import.py`.

### 2026-07-02 - Material Root Overlap With DTM and MCP Clarified

User request:

- Clarify whether `Material root` overlaps with `DTM directories` and
  `MCP named-point evidence`.

Implementation steps:

- Rechecked `pretrip_import.py` material resolution logic.
- Confirmed that `material_root` can provide both DTM directories and MCP
  named-point evidence through `material_manifest.json` or canonical files
  under the material bundle.
- Confirmed that explicit `DTM directories` are additive with material-root
  DTM dirs, then de-duplicated by resolved path.
- Confirmed that explicit `MCP named-point evidence` has priority over the
  material-root manifest/canonical candidates.

Boundary notes:

- `Material root` is the bundled/default source of related material.
- `DTM directories` and `MCP named-point evidence` are explicit overrides or
  supplements for targeted runs.
- This clarification does not change dashboard runtime behavior.

Verification:

- Source review of `_material_root_for_request`, `_dtm_source_dirs`, and
  `_resolve_mcp_named_point_evidence` in `pretrip_import.py`.

### 2026-07-02 - Optional Import Parameters Marked

User request:

- Add `(optional)` after parameters that have a default action when left blank.

Implementation steps:

- Reviewed `pretrip_import.py` and `pretrip_layer_preparation.py` argument
  defaults and fallback behavior.
- Updated `Import New Trip` labels to mark optional/default-backed inputs,
  including reference GPX sources, template/material overrides, DTM and MCP
  evidence overrides, import defaults, preparation defaults, optional OSM PBF
  material, and prepared-at timestamp.
- Left required identity/source inputs unmarked, including `Trip id`,
  `Golden route GPX path`, and workspace-root fields that are required by the
  underlying tooling.
- Added regression assertions so optional labels stay visible and required GPX
  source input is not mislabeled.

Boundary notes:

- This is a UI-label clarity change only.
- No importer, map preparation, workspace mutation, or runtime handoff behavior
  changed.

Verification:

- `tests/test_scout_dashboard_page.py` covers the optional labels.

### 2026-07-02 - Workspace Root and BBox Derivation Clarified

User request:

- Clarify whether GPX import `Workspace root` and map preparation
  `Prepare workspace root` are duplicated.
- Clarify whether `Project root` and `Target workspace` are duplicated.
- Clarify whether `BBox` should be derived from reference GPX bbox plus a
  delta distance instead of manually entered.

Implementation steps:

- Reviewed `pretrip_import.py` workspace creation and import CLI arguments.
- Reviewed `pretrip_layer_preparation.py` project root resolution, route
  evidence bundle loading, and bbox fallback logic.
- Confirmed that dashboard UX should treat GPX import workspace root as the
  single operator-entered workspace base for this one-trip flow.
- Confirmed that map preparation workspace root can be derived from the same
  workspace base, unless an advanced/manual preparation run intentionally
  targets a different project root.
- Confirmed that `Target workspace` is a project id/name while `Project root`
  is the resolved absolute path; they are related but should not both be
  primary operator inputs.
- Confirmed that map preparation already treats `BBox` as optional: it uses
  route evidence bundle scope when available, otherwise route summary bbox
  expanded by `route_corridor_m`.

Boundary notes:

- Recommended next UI cleanup: show one canonical workspace base and target
  workspace id, then display derived project root/preparation root as read-only
  or advanced override values.
- Recommended bbox UI: replace freeform primary bbox entry with a derived
  bbox preview plus a delta/corridor control; keep manual bbox only as an
  advanced override.
- No runtime behavior changed in this clarification step.

Verification:

- Source review of `run_pretrip_import`, `_resolve_project_root`,
  `_route_evidence_bundle_context`, and `_bbox_from_route_evidence_bundle`.

### 2026-07-02 - Workspace Root and Target Name Consolidated

User request:

- Consolidate `Workspace root`, `Prepare workspace root`, and
  `Target workspace (optional)` into the Import New Trip fields.
- Use only `Workspace root` plus `Target name` to answer those duplicated
  inputs.

Implementation steps:

- Moved `Workspace root` into the main `Import New Trip` intake panel.
- Replaced `Target workspace (optional)` with `Target name`.
- Removed the duplicate map-preparation `Prepare workspace root` input.
- Removed the manual map-preparation `Project root` input from the form.
- Added dashboard helpers to derive project root from
  `Workspace root + Target name`.
- Kept legacy draft keys populated from the derived values so existing
  downstream command construction can still map to `workspace_root`,
  `prepareWorkspaceRoot`, and `prepareProjectRoot`.

Boundary notes:

- This remains operator-triggered dashboard intake only.
- No importer execution, filesystem mutation, runtime handoff, or live safety
  behavior changed.
- `Project root` and `Prepare workspace root` are now derived routing details,
  not primary operator input fields.

Verification:

- `tests/test_scout_dashboard_page.py` asserts the new `Target name` field,
  derived project-root helpers, and absence of the duplicate old input ids.

### 2026-07-02 - Optional Parameters Collapsed Into Advanced Frame

User request:

- Recheck whether the many `(optional)` fields are all optional.
- If they are optional/default-backed, move them into a separate optional
  parameter frame because exposing many minor controls is poor dashboard UX.

Implementation steps:

- Confirmed that after the main intake consolidation, the visible import flow
  only needs `Trip id`, `Golden route GPX path`, `Workspace root`, and
  `Target name`.
- Treated the remaining GPX import and map preparation fields as
  default-backed or advanced override controls.
- Moved the remaining GPX import and map preparation controls into a collapsed
  `Optional Parameters` frame.
- Removed `(optional)` suffixes from individual labels because the containing
  frame now communicates optionality.
- Added default fallback for `Layer ids` through the dashboard so clearing or
  not opening the frame still uses the standard preparation layer set.

Boundary notes:

- The dashboard remains operator-triggered and does not execute import,
  mutate files, perform runtime handoff, or enable live safety automation.
- Optional controls remain available for advanced/debug use, but no longer
  dominate the first screen.
- This supersedes the earlier label-level optional marker UX while preserving
  the historical note.

Verification:

- `tests/test_scout_dashboard_page.py` asserts the collapsed optional frame,
  removal of `(optional)` label noise, and default layer fallback.
- Playwright should verify that advanced fields are hidden while the frame is
  collapsed.

### 2026-07-02 - Low-value Import Panels Condensed

User request:

- Reduce wordy dashboard panels such as `Import Boundary`,
  `Workspace Routing`, `Evidence Drawer`, `Preflight Checklist`,
  `Layer Preparation Target`, and `Runtime Handoff Guard`.
- Preserve useful guardrails while freeing the main work area for actual
  controls and operator input.

Implementation steps:

- Replaced the large `Import Boundary` and `Workspace Routing` metric panels
  with a compact import context block using short chips and two derived path
  rows.
- Replaced the three preflight/layer/handoff metric panels with one compact
  guard strip.
- Shortened the generic evidence drawer title to `Evidence` and reduced long
  boundary text to short issue/source tags.
- Updated tests so the old low-value panel titles cannot return unnoticed.

Boundary notes:

- The same safety and artifact boundaries remain visible as compact chips.
- No import execution, workspace mutation, runtime handoff, outbound send, or
  live safety behavior changed.

Verification:

- `tests/test_scout_dashboard_page.py` checks for the compact context/guard
  markers and asserts the old verbose panel titles are absent.

### 2026-07-02 - Country Material Pool Tab Added

User request:

- Add a country-wise material pool tab under the Import New Trip subtree.
- Use it for country/global material defaults such as DTM, base maps,
  government resources, and API pools for weather, geology, marine, and open
  data.
- Move country-specific API assumptions out of one-off import/map preparation
  thinking; for example, CWA is Taiwan-specific and must not be treated as a
  Japan/default global weather source.

Implementation steps:

- Turned `Import New Trip` into a navigation subtree with `Trip Intake` and
  `Country Material Pool`.
- Added a `COUNTRY_MATERIAL_POOLS` registry with Taiwan, Japan, and Global
  fallback profiles.
- Added the `Country Material Pool` page with country tabs, material class
  cards, API/provider matrix, factory defaults, and map-preparation usage
  summaries.
- Added a `Country material pool` selector to the Import New Trip intake form.
- Wired import defaults so `material_root`, `dtm_dirs`, `import_profile`, and
  `osm_pbf_source_url` can derive from the selected country pool unless an
  advanced override is explicitly entered.
- Cleared pool-derived override fields when switching countries so Taiwan
  defaults do not accidentally persist into Japan/Global profiles.
- Added regression tests for navigation, import selector wiring, country pool
  content, provider scope, and safety boundary text.

Boundary notes:

- The country material pool is a factory/default registry view only.
- It does not fetch data, mutate workspace files, run importer commands, load
  runtime packages, or change safety truth.
- Provider outputs remain candidate evidence/provenance material.
- Country-specific API scope is explicit: Taiwan uses CWA defaults; Japan uses
  Japan-scoped providers such as JMA/GSI; Global fallback requires
  operator-selected providers.

Verification:

- `tests/test_scout_dashboard_page.py` asserts the new route, selectors,
  provider matrix labels, default derivation helpers, and boundary text.

### 2026-07-02 - Taiwan Route Context References Added To Country Pool

User request:

- `docs/specs/scout-route-context-layer.md` also lists Taiwan reference
  websites and source families.
- Include those references inside the country-level material pool instead of
  leaving them as route/import-specific assumptions.

Implementation steps:

- Reviewed `docs/specs/scout-route-context-layer.md` and the aligned
  `.agents/skills/scout-route-context-briefing/references/source-catalog.md`.
- Added the Taiwan P0/P1 route-context source catalog to the Taiwan country
  material pool.
- Added a `Route Context References` section to the Country Material Pool page.
- Kept Japan and Global fallback pools free of Taiwan-specific route-context
  references.
- Added tests for representative P0/P1 Taiwan sources and the discovery-only
  boundary text.

Boundary notes:

- P0/P1 route-context catalog entries are discovery scope only.
- The catalog entries are not concrete evidence and are not route-specific
  URLs.
- Concrete URLs still need later discovery, operator-provided source lists, or
  source-specific adapters.
- No import execution, network fetch, workspace mutation, runtime package load,
  or safety-truth mutation was added.

Verification:

- `tests/test_scout_dashboard_page.py` asserts the Taiwan source catalog labels
  and discovery-only wording.

### 2026-07-02 - Route Context Tab Connected To Scout AI Trip Briefing

User request:

- Connect `Exploring for Six Axis / Route Context` to the trip briefing web
  page generated by the Scout AI route-context skill.

Implementation steps:

- Reviewed the Scout AI route-context briefing skill boundary and the existing
  pretrip briefing endpoint.
- Added dashboard helpers to resolve the briefing project id from the current
  dashboard workspace while preserving the `_scoutAI` workspace project id
  when that is the active source of the generated briefing artifact.
- Replaced the hand-written Route Context map/table with an embedded briefing
  iframe that loads
  `/admin/pretrip/projects/{project}/briefings/route-context`.
- Added an `Open briefing` action for opening the same briefing endpoint in a
  separate tab.
- Added source and boundary panels that name
  `outputs/briefings/route_context_briefing.html`,
  `scout-route-context-briefing skill`, and
  `pretrip_route_context_collection`.
- Added dashboard regression coverage so the Route Context tab remains wired
  to the generated Scout AI briefing endpoint instead of reverting to static
  copy.

Boundary notes:

- The embedded briefing is candidate-only trip context.
- The dashboard does not mutate Phase 1 runtime safety truth.
- The dashboard does not write to safety endpoints.
- The dashboard does not grant stop permission or route open/closed authority.
- The dashboard does not trigger live safety automation or outbound transport.

Verification:

- `tests/test_scout_dashboard_page.py` asserts the iframe, endpoint path,
  project resolution helper, source artifact path, Scout AI skill labels,
  and runtime safety boundary text.
- `./venv/bin/python -m pytest tests/test_scout_dashboard_page.py -q`
  passed.
- Playwright smoke on `http://127.0.0.1:9099/admin/dashboard#outdoor-route-context`
  confirmed the iframe source resolves to
  `/admin/pretrip/projects/chilai_nanhua_day1_scoutAI/briefings/route-context`,
  the frame body contains the generated `SCOUT 行前路線簡報`, and no page or
  console errors were emitted.
- Screenshot captured at `/tmp/scout-dashboard-route-context-briefing.png`.
- `PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python
  tools/verify_scout_layer_contract.py --repo-root .` passed.
- `PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python
  tools/verify_scout_layer_contract.py --repo-root . --project-root
  /Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI
  --require-workspace` passed.
- `pnpm lint`, `pnpm typecheck`, and `pnpm test` passed.
- `node tools/admin_ui_visual_smoke.js --python ./venv/bin/python` passed.

### 2026-07-02 - Route Context Briefing Metadata Collapsed

User request:

- `Briefing Source`, `Artifact Boundary`, and `Load Contract` are low-signal
  panels and should not occupy important screen space.
- The actual briefing is being compressed; hide those metadata panels unless
  the operator needs to inspect them.

Implementation steps:

- Removed the Route Context right-side metadata column.
- Changed the Route Context layout to a single primary briefing column.
- Marked Route Context as a wide-frame dashboard route so the global right-side
  evidence drawer does not squeeze the generated briefing.
- Moved `Briefing Source`, `Artifact Boundary`, and `Load Contract` into one
  collapsed `Briefing metadata` drawer below the briefing header.
- Increased the briefing iframe minimum height so the generated trip briefing
  gets the primary screen area by default.
- Added regression checks that the metadata drawer is present, collapsed by
  default, and the old right-side metadata stack does not return.

Boundary notes:

- The metadata remains available for source, artifact, and boundary review.
- The drawer is UI-only and does not change the candidate-only briefing
  boundary.
- No live safety automation, outbound transport, workspace mutation, or
  runtime safety-truth mutation was added.

Verification:

- `tests/test_scout_dashboard_page.py` asserts the collapsed drawer and
  Route Context briefing contract.
- Playwright smoke on `http://127.0.0.1:9099/admin/dashboard#outdoor-route-context`
  confirmed the global evidence drawer is hidden for this route.
- Playwright confirmed `Briefing metadata` is collapsed by default and expands
  to reveal `Briefing Source`, `Artifact Boundary`, and `Load Contract`.
- Playwright confirmed the briefing iframe width is 1206 px at a 1512 px
  desktop viewport.
- Screenshot captured at
  `/tmp/scout-dashboard-route-context-metadata-collapsed.png`.

### 2026-07-02 - Route Context Briefing Photos Restored

User request:

- The Route Context briefing appeared to have lost many photos.

Diagnosis:

- The dashboard iframe was loading the correct briefing endpoint.
- The active workspace briefing HTML had zero `<img>` elements and displayed
  the generated visual gap message.
- The workspace media manifest had `available_media_count=0`,
  `selected_media_count=0`, and `visual_kit_ready_count=0`.
- The workspace `web_case_evidence.json` was `empty_no_network`, so the route
  context collector had no image refs to curate.

Implementation steps:

- Added `sources/route_context_p0_images.html` inside the active workspace as
  a P0 official image source list.
- Imported the image list with `pretrip_p0_p1_source_collection` in no-network
  mode.
- Rebuilt route context artifacts with `pretrip_route_context_collection`.
- The regenerated media manifest now has 6 selected P0 images and all 6 visual
  kit slots ready.
- The regenerated briefing HTML now includes route-context photos again.

Boundary notes:

- The photo sources are candidate-only P0 official image evidence.
- The import used no live network fetch.
- Raw images were not embedded into JSON artifacts.
- Runtime safety truth, safety endpoints, outbound transport, and live safety
  automation were not touched.

Verification:

- `pretrip_p0_p1_source_collection` reported `image_source_count=6`,
  `network_calls_made=false`, and `runtime_safety_truth=false`.
- `pretrip_route_context_collection` reported `web_case_evidence loaded_count=6`
  and `route_context_point_count=66`.
- The admin briefing endpoint now contains 90 `<img>` matches.
- The generated workspace briefing file now contains 97 `<img>` elements.
- Playwright smoke on
  `http://127.0.0.1:9099/admin/dashboard#outdoor-route-context` confirmed
  `document.images.length=97`, `loaded=97`, and `brokenCount=0` inside the
  iframe.
- Screenshot captured at
  `/tmp/scout-dashboard-route-context-photos-restored.png`.

### 2026-07-02 - Route Context Decision Band Removed

User request:

- Remove the `Decision`, `Primary output`, `Confidence`, and `Next action`
  row from the Route Context briefing page because it has low information
  value and occupies the main briefing area.

Implementation steps:

- Removed the Route Context page `decisionBand(...)` render call.
- Kept the compact briefing header, candidate-only chip, runtime safety chip,
  and collapsed `Briefing metadata` drawer.
- Added a dashboard regression assertion so the Route Context briefing page
  does not reintroduce that decision-band row.

Boundary notes:

- This is a layout-only dashboard change.
- Artifact source metadata remains available in the collapsed metadata drawer.
- Candidate-only, runtime-safety-truth false, no live safety automation, and
  no outbound transport boundaries remain unchanged.

Verification:

- `tests/test_scout_dashboard_page.py` asserts the Route Context decision-band
  call is absent while the briefing iframe contract remains present.
- Playwright smoke on `http://127.0.0.1:9099/admin/dashboard#outdoor-route-context`
  confirmed `Decision`, `Primary output`, `Confidence`, and `Next action` are
  absent from the Route Context workspace text.
- Playwright confirmed the briefing iframe moved up to `y=231.984375` at a
  1512 px desktop viewport and still renders with width 1206 px.
- Screenshot captured at
  `/tmp/scout-dashboard-route-context-decision-band-removed.png`.
- `./venv/bin/python -m pytest tests/test_scout_dashboard_page.py -q`
  passed.
- `pnpm lint`, `pnpm typecheck`, and `pnpm test` passed.
- Scout layer contract passed for both repo and
  `/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI`.

### 2026-07-02 - Route Context Briefing Regeneration And Product Copy Cleanup

User request:

- Remove the low-information `Scout AI Trip Briefing` header from the dashboard
  Route Context page.
- Remove internal AI/design prompt wording from the generated briefing product
  page.
- Add a button that regenerates the briefing through Scout AI, with a real
  OpenRouter-backed backend call.

Implementation steps:

- Removed the visible Route Context briefing header row from
  `docs/admin/scout-dashboard-v0.1.html`.
- Added a compact `Regenerate with Scout AI` operator action bar that posts to
  `/admin/pretrip/projects/{project}/briefings/route-context/regenerate`.
- Added iframe cache-busting after successful regeneration so the dashboard
  reloads the rebuilt briefing without navigating away.
- Added the admin API regeneration endpoint. The endpoint requires
  `confirm_regenerate=true`, resolves an OpenRouter model, calls Scout AI, writes
  `outputs/scout_ai/route_context_briefing_regeneration.json`, and then rebuilds
  route-context artifacts with `pretrip_route_context_collection`.
- Updated the briefing renderer so the visual-kit section uses product-facing
  material readiness copy instead of internal generation/design instructions.

Boundary notes:

- The regenerate action is operator-triggered only.
- The backend requires an OpenRouter model; without `OPENROUTER_API_KEY` the
  real runner returns a 503 instead of pretending regeneration happened.
- The regeneration artifact stores prompt and model-output hashes plus a bounded
  model-output preview. It does not store API keys or raw prompts.
- Regeneration remains candidate-only, does not mutate Phase 1 runtime safety
  truth, does not trigger live safety automation, and does not send outbound
  transport.

Verification:

- `tests/test_scout_dashboard_page.py` asserts the header text is absent, the
  regenerate button and endpoint are present, and the only dashboard POST path
  is the operator-triggered briefing regeneration path.
- `tests/test_pretrip_admin_api.py` covers the backend endpoint with a fake
  Scout AI runner and verifies the regeneration artifact plus rebuilt briefing.
- `tests/test_pretrip_route_context_collection.py` and
  `tests/test_pretrip_p0_p1_source_collection.py` assert the old internal
  prompt-like copy is absent from generated briefing HTML.
- The current shell did not have `OPENROUTER_API_KEY`; real OpenRouter smoke was
  not executed locally. In this state the real endpoint is expected to return
  503 rather than fake a model call.
- Live endpoint smoke on the fixed 9099 admin server returned
  `503 OPENROUTER_API_KEY is required for Scout AI briefing regeneration`,
  confirming the backend route is registered and will not fake success without
  real OpenRouter credentials.
- Rebuilt the current
  `/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI` route-context
  briefing with `pretrip_route_context_collection` so the visible iframe no
  longer shows the old prompt-like copy while the new button remains the
  operator path for Scout AI/OpenRouter regeneration.
- `node tools/admin_ui_visual_smoke.js --python ./venv/bin/python` returned
  `ok: true`; dashboard map iframe reuse, desktop/mobile rendering, and Scout
  layer toggles passed.
- The fixed admin server was restarted as a detached background process on
  `http://127.0.0.1:9099` for operator review.

### 2026-07-03 - Persistent Scout Env For Shared API Keys

User request:

- Create a persistent `.env` so later Scout projects can access important API
  keys instead of depending only on the current repo-local `.env`.

Implementation steps:

- Created `/Users/alexwang0315/.scout/.env` with mode `600`.
- Merged key names from the repo-local `.env` into the persistent env without
  printing or recording secret values.
- Added a shared `scout_env.load_scout_env_files` helper.
- Admin surfaces now load environment values in this order:
  shell process env first, repo-local `.env` second, persistent
  `/Users/alexwang0315/.scout/.env` third.
- `phase4_admin_runtime` loads Scout env files before it snapshots
  `os.environ`, so 9099 runtime paths such as route-context briefing
  regeneration can see persistent API keys.
- Route-context briefing regeneration now inserts the repo `src` directory into
  `sys.path` before importing the Scout AI runner, so 9099 no longer depends on
  the operator manually setting `PYTHONPATH=src`.
- Route-context briefing regeneration uses a dedicated
  `SCOUT_DASHBOARD_BRIEFING_MAX_TOKENS` cap, defaulting to 2048, instead of the
  short-answer 512-token limit.

Boundary notes:

- Secret values are not printed, logged, embedded in dashboard artifacts, or
  returned by tests.
- Existing shell env values keep highest priority.
- Explicit test `environ` inputs remain hermetic and do not load the operator's
  real persistent env.
- This only enables operator-triggered Scout AI calls; it does not enable live
  safety automation, `/safety/*` mutation, hardware control, or outbound
  transport.

Verification:

- Persistent env file exists at `/Users/alexwang0315/.scout/.env`.
- File mode is `600`.
- Current persistent key names are `OPENROUTER_API_KEY`, `SCOUT_CWA_API_KEY`,
  and `CWA_API_KEY`.
- Added regression tests for env-file precedence and phase4 runtime env loading.
- Live regenerate smoke on 9099 completed with `status=completed`,
  `provider=openrouter`, `model=openrouter:z-ai/glm-5.2`, and
  `external_model_call_performed=true`.
- The regeneration artifact was verified with `raw_prompt_embedded=false`,
  `api_key_embedded=false`, `runtime_safety_truth=false`, and
  `live_safety_automation_triggered=false`.
- `pnpm lint`, `pnpm typecheck`, and `pnpm test` passed.
- Focused env/runtime/regeneration pytest checks passed.
- Scout layer contract passed for both the repo and
  `/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI`.
- `node tools/admin_ui_visual_smoke.js --python ./venv/bin/python` returned
  `ok: true`.

### 2026-07-03 - Route Context Intelligence Spec-Aligned Briefing Generation

User request:

- Generate the Route Context briefing according to
  `docs/specs/scout-route-context-intelligence-implementation.md`.

Implementation steps:

- Updated the operator-triggered briefing regeneration prompt so Scout AI
  returns a concise Route Context Intelligence plan, not raw HTML.
- The prompt now references the Route Context Intelligence implementation spec
  and asks Scout AI to reason from `route_context_pack.json`,
  `route_context_points.json`, `source_manifest.json`, route summary, and
  map/risk artifacts.
- The regeneration artifact now records
  `route_context_intelligence_contract` and a parsed
  `scout_ai_route_context_intelligence_plan` when the model returns JSON.
- The Scout AI plan parser accepts plain JSON, fenced JSON, or model text with
  a leading explanation followed by a JSON object, so the artifact remains
  reviewable when the provider wraps the structured answer.
- The prompt tells Scout AI not to call tools directly; the backend compiler is
  responsible for reading workspace cache files after the model returns the
  plan.
- Added a visible Route Context Intelligence section to the generated briefing
  HTML. It shows the workspace cache path, Sec. 6 layer coverage, P0/P1/P2
  source tier policy, and stop-permission boundary.
- Product copy now states that Scout AI produces the review plan while
  `pretrip_route_context_collection` produces the user-visible HTML from
  deterministic workspace artifacts.

Boundary notes:

- Regeneration remains operator-triggered only.
- Scout AI output is candidate-only and does not become runtime safety truth.
- The model is not allowed to authorize stop permission, route open/closed
  decisions, live safety automation, hardware control, outbound transport, or
  `/safety/*` mutation.
- A "worth observing" point remains a 3-minute observation candidate only; stop
  permission still belongs to Contextual Permissioning.
- Source tiers remain separated: P0 official baseline, P1 expansion evidence,
  and P2 Scout-owned review seed.

Verification:

- `tests/test_pretrip_admin_api.py` verifies the regeneration prompt, contract,
  fenced/parsed Scout AI JSON plan, boundary metadata, and rebuilt briefing.
- `tests/test_pretrip_route_context_collection.py` verifies the generated
  briefing contains the Route Context Intelligence section, workspace cache
  path, Sec. 6 layer names, P0/P1/P2 policy, and stop-permission boundary.
- `tests/test_scout_dashboard_page.py` verifies this change log entry remains
  recorded while active recording is enabled.
- Live 9099 regenerate completed with `provider=openrouter`,
  `model=openrouter:z-ai/glm-5.2`,
  `external_model_call_performed=true`, and parsed artifact schema
  `route_context_intelligence_plan.v1`.

### 2026-07-03 - Route Briefing Trip-Only Product Copy Guard

User request:

- All visible text in the generated trip briefing must describe the itinerary,
  route, sources, stops, photos, lodging, terrain, weather, or leader review.
- Product-visible text must not describe how the page is generated, internal
  wording, model instructions, page layout mechanics, or artifact filenames.

Implementation steps:

- Rewrote the route-context opening section as a route briefing for leader
  review: route context points, six trip axes, source trust, and short-stop
  boundaries.
- Removed product-visible implementation wording from the generated briefing:
  cache paths, compiler wording, model-output wording, internal artifact names,
  and machine-readable safety-boundary field names are no longer rendered in
  the HTML page.
- Replaced the previous photo/material language with itinerary wording:
  route photos, maps, lodging nodes, terrain, short stops, weather/seasonal
  checks, leader notes, and missing photo lists.
- Changed header/navigation labels from briefing-product wording to trip-facing
  wording: Scout pre-trip route explanation, pre-trip navigation, and route
  photo/map checks.
- Replaced the remaining English page title/navigation copy
  (`Scout Route Context Briefing`, `Route Context`) with trip-facing route
  explanation labels.
- Cleaned expanded detail rows as well, so review notes, source tiers, route
  point source labels, risk-card boundaries, and short-stop review text are
  shown as itinerary-facing language rather than raw internal fields.
- Kept machine-readable metadata in JSON artifacts for auditability, but added
  regression checks so those terms are not shown in the generated HTML.

Boundary notes:

- Regeneration remains operator-triggered and Scout AI backed.
- The generated page remains a pre-trip route explanation for human review; it
  does not authorize departure, stop permission, live safety automation,
  hardware control, outbound transport, or `/safety/*` mutation.
- Artifact boundary metadata is preserved in JSON outputs and hidden from the
  product-visible briefing copy.

Verification:

- `tests/test_pretrip_route_context_collection.py` now asserts the new route
  photo/map wording and blocks old product-copy phrases such as material-board,
  speaker-note, compiler, cache-path, model-output, prompt, and artifact-path
  wording from generated HTML.
- `tests/test_pretrip_admin_api.py` now checks regenerated Scout AI briefing
  HTML uses the trip-only copy and does not reintroduce old internal wording.
- `tests/test_scout_dashboard_page.py` verifies this change log entry remains
  recorded while active recording is enabled.
- Live 9099 briefing HTML was fetched from the workspace-backed route context
  endpoint and scanned for internal generation, prompt, cache, artifact, and
  old briefing/material wording.

### 2026-07-03 - Route Briefing Visual Kit Itinerary Copy Tightening

User request:

- The route briefing still contained low-value photo/map status language such
  as `行前照片與地圖狀態`, `已檢查開場...`, and `開場主視覺`.
- The visible copy should describe the trip and itinerary, not how the page or
  visual material is organized.

Implementation steps:

- Rewrote the photo/map visual kit header around itinerary sequence:
  entry, lodging, ridge/terrain, short observation stops, and weather.
- Replaced status and readiness wording with route-segment wording:
  photos and maps now map to itinerary segments rather than page-preparation
  states.
- Renamed visual slots from product/layout terms to trip terms, including
  entry/ridge view, full-route direction map, lodging/intermediate points,
  terrain passage, short observation point, and weather/season conditions.
- Replaced remaining photo-management labels such as image guide, image index,
  and available-image layout wording with itinerary photo route and segment
  checklist wording.
- Tightened the remaining screenshot panel: `行程畫面覆蓋`, `畫面偏薄`,
  abstract layer gaps, and `再補 N 張路線照片` now render as trip-facing
  route-segment review, concrete gap names, and route-condition checks.
- Added regression checks so the old photo/map status, opening-visual,
  readiness, and matched-image wording cannot reappear in generated HTML.

Boundary notes:

- This is copy and presentation only.
- It does not change route safety authority, stop permission, live automation,
  hardware behavior, outbound transport, or `/safety/*` state.

Verification:

- Route briefing unit tests assert the new itinerary-facing copy and block the
  old visual-kit status wording.
- Regenerated fixture and workspace briefing HTML should be scanned for the
  removed phrases before marking the UI clean.

### 2026-07-03 - Trip Briefing Generation Process Captured As Skill

User request:

- Capture the route-context trip briefing generation process as a reusable
  skill so future routes can produce a similar result.

Implementation steps:

- Updated `.agents/skills/scout-route-context-briefing/SKILL.md` instead of
  creating a parallel skill, so future route briefing requests keep using the
  existing route-context trigger.
- Added a future-route rule that forbids hardcoding Chilai, Nengao, or any
  previous route's URLs, image choices, lodging points, or copy into a new
  route briefing.
- Documented the Scout AI regeneration contract: OpenRouter/Scout AI can
  produce only a bounded candidate plan, while the deterministic compiler must
  render the final briefing from workspace artifacts.
- Added the trip-only product copy gate: visible HTML text must describe the
  itinerary, route segment, source, lodging/intermediate point, terrain,
  weather/season, observation stop, or leader review task.
- Added blocked visible-copy examples for prompt/model/cache/compiler/artifact
  wording and the old photo/map status phrases.
- Added preferred replacements such as route-segment photo checks, full-route
  direction map, lodging/intermediate points, short observation points, and
  weather/season conditions.
- Added a verification gate requiring focused route-context rendering tests,
  visible-text scans, image-to-route binding checks, and live 9099 endpoint
  scans when available.
- Extended the route-context skill regression test so these instructions stay
  pinned in the repo.

Boundary notes:

- The skill keeps trip briefings candidate-only and human-review oriented.
- It does not authorize departure, stop permission, live safety automation,
  hardware control, outbound transport, or `/safety/*` mutation.
- Secrets such as `OPENROUTER_API_KEY` must be loaded from environment only and
  never printed or written into briefing artifacts.

Verification:

- Focused route-context skill test passed.
- `pnpm lint` passed.
- `pnpm typecheck` passed.
- `pnpm test` passed.
- `git diff --check` passed.

### 2026-07-05 - Route Context Intelligence Variants Integrated

User request:

- Connect the dashboard Route Context / Route Context Intelligence surface to
  `skills/scout/route-context-intelligence.yaml`.
- Use Scout AI to generate a complete route briefing result from that skill.

Implementation steps:

- Added a route-context variants API flow:
  `POST /admin/pretrip/projects/{project_id}/briefings/route-context/variants/generate`.
- Added a read endpoint for current variants status:
  `GET /admin/pretrip/projects/{project_id}/briefings/route-context/variants`.
- Added a safe artifact file endpoint for the generated index, comparison,
  model audit, failure artifact, and each variant HTML file.
- Routed generation through
  `tools/scout_ai_route_context_briefing_variants.py`, which reads
  `skills/scout/route-context-intelligence.yaml` and performs the single Scout
  AI / Pydantic AI call required by the skill contract.
- Kept generated variants under
  `outputs/briefings/route_context_variants_ai_once` and did not overwrite the
  canonical `outputs/briefings/route_context_briefing.html`.
- Added dashboard Route Context controls to trigger five variants with Scout
  AI and show a compact, collapsible variants drawer with links to the index,
  comparison, model audit, and generated pages.
- Added regression coverage for the admin API flow and dashboard route-context
  UI contract.

Boundary notes:

- The variants flow is operator-triggered only.
- It does not mutate Phase 1 runtime safety truth.
- It does not trigger live safety automation, outbound transport, hardware
  control, or `/safety/*` writes.
- Model prompt, model response, token usage, skill hash, and model output hash
  are preserved in machine-readable audit artifacts, not in product-visible
  variant HTML.

Verification:

- Focused admin API and dashboard tests cover the fake Scout AI runner path and
  artifact serving path.
- Live generation against
  `/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI` used Scout AI via
  `nvidia:z-ai/glm-5.2` and recorded provider token usage:
  `input_tokens=7804`, `output_tokens=4043`, `total_tokens=11847`,
  `requests=1`, `tool_calls=0`.
- The generated workspace outputs are:
  `index.html`, `01-magazine_atlas.html`, `02-command_wall.html`,
  `03-field_notebook.html`, `04-topographic_feature.html`,
  `05-night_navigation.html`, `route_context_variant_comparison.json`,
  `route_context_variant_comparison.md`, and
  `scout_ai_route_context_variant_model_plan.json`.
- Desktop and mobile Playwright smoke verified the dashboard Route Context
  variants drawer, five artifact links, no 4xx responses, no console errors,
  and no horizontal overflow.

### 2026-07-05 - Route Context Variants Reference Gate And Re-Generation

User request:

- Generate another five Route Context Intelligence briefings and ensure they
  are not more than 60% similar to the existing dashboard five.
- Challenge whether the previous dashboard view came from a real Scout AI
  call, because it still matched the existing
  `route_context_variants_ai_once/index.html` output.

Implementation steps:

- Confirmed the previous visible dashboard was still pointing to the existing
  `outputs/briefings/route_context_variants_ai_once` artifact set.
- Added reference-aware generation support to
  `tools/scout_ai_route_context_briefing_variants.py`:
  `--reference-variants-dir` and `--max-reference-similarity`.
- Added a local similarity gate that compares Scout AI generated visible
  briefing copy, concepts, headings, chapter titles, observation prompts, and
  point-angle wording with a 4-gram cosine metric.
- Excluded fixed route evidence from the gate because the full HTML necessarily
  repeats the same route points, source tables, and renderer structure.
- Added reference avoidance prompt content so Scout AI does not reuse the old
  five frames: magazine atlas, command wall, field notebook, topographic
  feature, and night navigation.
- Changed reference-aware output filenames to use the generated variant slug
  instead of the old fixed filenames.
- Exposed `reference_similarity_gate`, per-variant
  `max_reference_similarity`, and gate pass/fail metadata through the admin API.
- Updated the dashboard variants drawer to show the reference gate result and
  to send `max_reference_similarity: 0.6` on future variant generation.
- Updated
  `/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI/project.json` to
  point the dashboard at
  `outputs/briefings/route_context_variants_ai_second_pass_20260705T082948Z`.

Final generated variants:

- `01-rehearsal-runthrough-v1.html`
- `02-ridge-valley-transect-v2.html`
- `03-hut-summit-ledger-v3.html`
- `04-weather-checkpoint-v4.html`
- `05-evidence-courtroom-v5.html`

Scout AI evidence:

- Final model: `nvidia:z-ai/glm-5.2`
- Provider-reported usage:
  `input_tokens=11278`, `output_tokens=4171`, `total_tokens=15449`.
- Reference gate: `passed`.
- Maximum observed reference similarity: `0.2605`.
- Maximum allowed reference similarity: `0.6`.

Boundary notes:

- This remains operator-triggered pretrip candidate output.
- Canonical `outputs/briefings/route_context_briefing.html` is unchanged.
- The flow does not mutate Phase 1 runtime safety truth, call `/safety/*`,
  trigger live safety automation, send outbound transport, or control hardware.

Verification:

- Focused generator, admin API, and dashboard tests passed.
- `pnpm lint` passed.
- `pnpm typecheck` passed.
- `pnpm test` passed.
- 9099 variants API returned the new output dir, five variants,
  provider-reported token usage, and `reference_similarity_gate.status=passed`.
- Playwright verified the dashboard Route Context page shows the new five
  slugs, `15449 tokens`, and `reference passed max 0.2605/0.6`.

### 2026-07-06 - Future LoRaWAN Sender Dashboard Placement

User request:

- Record that Scout will need a future sender, and decide where it should
  integrate with the dashboard.

Planning decision:

- The future sender is a transport/action service, not an observer.
- Working name: `scout_lorawan_sender.py`.
- Primary dashboard integration should be `MQTT / Observer Message`.
- The `MQTT / Observer Message` page should add a visually separated
  sender/action lane for command candidates, queue state, dry-run/live send
  readiness, latest RF audit, gateway/client observer status, and explicit
  operator confirmation for bounded sends.
- The top-level `Safety / Emergency` route may summarize emergency-relevant
  sender readiness and link to the `MQTT / Observer Message` sender lane, but
  it should not own the sender workbench.
- `Debug Message` may show sender status, queue, readiness, and JSONL audit
  links, but it must remain status-only and must not own the send button.

Boundary notes:

- No sender was implemented in this recording slice.
- No dashboard button was wired to RF, LoRaWAN uplink, remote outbound, or
  `/safety/*`.
- The page name `MQTT / Observer Message` does not convert the resident
  observers into senders; the future sender lane is a separate action path.
- The current `sx1303-gateway` and `lorawan-client` resident observers remain
  read-only evidence producers.
- Initial future allowed message types should be `diagnostic_ping`, `check_in`,
  and `last_known_position`.
- `send_sos`, `trigger_l4`, and `change_safety_level` stay blocked until a
  separate Safety Arbiter / operator confirmation design exists.

### 2026-07-09 - Pace Fit Body Index Dashboard

User request:

- Add a `Body Index Dashboard` under the Pace Fit subtree.
- Design the dashboard UI to show the Scout Pace Coefficient indicators listed
  in `specs/SCOUT_OUTDOOR_AI_AGENT_STANDARD` section 7.2.

Implementation steps:

- Added `Body Index` as a Pace Fit child route:
  `outdoor-pace-fit-body-index`.
- Added a wide-frame Body Index dashboard surface with a compact coefficient
  summary, three reserve/trust tiles, nine metric cards, route impact mapping,
  and a traceable evidence matrix.
- Mapped the nine section 7.2 indicators into dedicated UI cards:
  flat ground speed, ascent speed, descent speed, technical terrain slowdown,
  rest frequency, late-trip decay, load impact, weather impact, and experience
  confidence.
- Kept the visual style aligned with the engineering dashboard direction:
  dense dark panels, meters, coefficient chips, source tags, and minimal prose.
- Added dashboard contract tests so the route, metric ids, spec labels, CSS
  hooks, and safety boundary language remain visible in the static shell.

Boundary notes:

- Body Index is planning evidence only.
- It is not a diagnosis, medical inference, or runtime safety authority.
- Provider values remain `source_provider` evidence and do not become Scout
  safety truth.
- The page does not call `/safety/*`, mutate Phase 1 L0-L4 state, send
  outbound transport, control hardware, or trigger live safety automation.

Verification:

- PASS: focused dashboard tests:
  `tests/test_scout_dashboard_page.py` and
  `tests/test_scout_emergency_mobile_approval_ui.py`.
- PASS: `pnpm lint`, `pnpm typecheck`, and `pnpm test`.
- PASS: Playwright visual smoke on the 9099 dashboard route for desktop and
  mobile widths; nine Body Index metric cards were visible, no horizontal
  overflow was detected, and no safety or outbound requests were observed.

### 2026-07-09 - HealthExport Body Index UX Implemented

User request:

- Turn the Body Index UX template into an actual dashboard UI.
- Use the local `~/downloads/HealthExport` export inventory to show additional
  Body Index context without exposing raw personal health records.

Implementation steps:

- Added a `Body Index Overview` section to the Pace Fit Body Index route.
- Added aggregate HealthExport coverage cards for export count, parsed walking
  sessions, GPX tracks, 15-minute windows, and provider metric families.
- Added `Health Baseline Signals` cards for VO2max baseline, resting HR, HRV,
  walking HR average, active energy reset cue, recovery debt windows, HR
  pressure windows, and step/distance pattern.
- Added a `Window Pressure Timeline` panel that summarizes available sanitized
  15-minute window coverage by export period.
- Added a collapsed `Health Provider Metrics` drawer for provider metric names
  such as `vo2_max`, `blood_oxygen_saturation`,
  `heart_rate_variability`, `resting_heart_rate`,
  `walking_heart_rate_average`, `active_energy`, and
  `walking_running_distance`.
- Extended dashboard contract tests to lock the HealthExport-aware UI
  structure, metric labels, drawer behavior, and boundary copy.

Boundary notes:

- The UI uses aggregate availability and translated planning signals only.
- It does not embed raw HealthExport rows, GPX coordinates, raw heart-rate
  samples, exact timestamps, home/work traces, or private health payloads.
- Provider values remain `source_provider only`; they are not medical
  diagnosis, route approval, Scout safety truth, Phase 1 mutation, live safety
  automation, hardware control, or outbound transport.

Verification:

- PASS: focused dashboard tests:
  `tests/test_scout_dashboard_page.py` and
  `tests/test_scout_emergency_mobile_approval_ui.py`.
- PASS: `pnpm lint`, `pnpm typecheck`, `pnpm test`, and `git diff --check`.
- PASS: Playwright visual smoke on the 9099 Body Index route for desktop and
  mobile widths; HealthExport overview, eight health baseline signal cards,
  the 15-minute window pressure timeline, and collapsed provider metrics drawer
  rendered without horizontal overflow, console errors, safety requests, or
  outbound requests.

### 2026-07-09 - Body Index HealthExport Import Merge Button

User request:

- Add an import button that can import new local HealthExport data, deduplicate
  it, merge it into the existing Body Index metrics, and update the Body Index
  dashboard values.

Implementation steps:

- Added dashboard Body Index API endpoints:
  `/admin/dashboard/body-index` for reading the current sanitized snapshot and
  `/admin/dashboard/body-index/import` for operator-triggered import.
- Reused the deterministic `build_health_auto_export_physio_analysis`
  pipeline to parse local HealthExport zip files.
- Added a dashboard-local Body Index snapshot store under
  `outputs/dashboard/body_index/`, keyed by project id.
- Deduplicated imported sources by source zip SHA-256, not filename, so copied
  or renamed identical exports are skipped.
- Stored only sanitized source counters and metric names: source id, SHA-256,
  dashboard source label, GPX count, walking session count, analysis window
  count, pressure window counts, aggregate distance/duration, and provider
  metric names.
- Added an `Import HealthExport` action to the Body Index overview header.
  The button posts `confirm_import: true`, waits with a longer import timeout,
  then refreshes `state.bodyIndexData` from the returned snapshot without a
  page reload.
- Converted Body Index summary, coverage cards, health signals, pressure
  timeline, and provider metrics drawer from static values to snapshot-backed
  values with the previous design values as fallback.
- Added tests for the import API, duplicate detection, coverage updates, and
  raw payload redaction.

Boundary notes:

- Import is operator-triggered only.
- The dashboard does not call a safety endpoint, mutate Phase 1 safety truth,
  trigger live safety automation, control hardware, or send outbound transport.
- API output excludes raw HealthExport rows, GPX XML, coordinates, raw
  heart-rate sample arrays, and exact source timestamps.

Verification:

- PASS: focused dashboard/API tests:
  `tests/test_scout_dashboard_page.py` and
  `tests/test_scout_emergency_mobile_approval_ui.py`.
- PASS: `pnpm lint`, `pnpm typecheck`, `pnpm test`, and `git diff --check`.
- PASS: browser smoke on
  `http://127.0.0.1:9099/admin/dashboard?projectId=chilai_nanhua_day1_scoutAI#outdoor-pace-fit-body-index`.
  The first operator-triggered import processed 3 local HealthExport zip
  sources, merged 3 new sources, skipped 0 duplicates, and reported 0 errors.
- PASS: duplicate verification. Re-running the import against the same
  directory merged 0 new sources, skipped 3 duplicates, and kept 3 processed
  sources in the Body Index snapshot.
- PASS: privacy boundary check. The API response, page text, and persisted
  sanitized snapshot did not contain `heartRateData`, GPX XML, coordinates,
  or exact source timestamps.
- Evidence screenshot:
  `/tmp/scout-dashboard-body-index-import-desktop.png`.
- Duplicate-pass screenshot:
  `/tmp/scout-dashboard-body-index-import-deduped-desktop.png`.

### 2026-07-09 - Body Index Health Baseline Signal Values

User request:

- Health Baseline Signals should not only say `available`; VO2max Baseline,
  Resting HR, HRV Baseline, Walking HR Average, and related cards need
  numeric values.

Implementation steps:

- Extended the Body Index source snapshot with sanitized provider metric
  summaries: `metric_name`, `sample_count`, `min_value`, `median_value`, and
  `max_value`.
- Kept the provider summaries as source-provider aggregates only. No raw
  HealthExport rows, exact timestamps, coordinates, or GPX XML are embedded.
- Added top-level `provider_metric_summaries` to the Body Index API response.
- Updated Health Baseline Signals from four columns to five columns:
  label, state, value, detail, and affected pace coefficient dimension.
- Added numeric signal values such as `median ... / n=...` for VO2max,
  resting HR, HRV, walking HR average, active energy, step count, and walking
  distance.
- Added explicit window counts for Recovery Debt Windows and HR Pressure
  Windows.
- Updated the dashboard signal cards so the numeric value is the primary
  display and the status is a smaller engineering chip.
- Added backward-compatible rendering for older four-column signal snapshots.

Boundary notes:

- Values are advisory planning evidence only.
- Values remain `source_provider only`; they are not diagnosis, route approval,
  Scout safety truth, Phase 1 mutation, live safety automation, hardware
  control, or outbound transport.

Verification:

- PASS: focused dashboard/API tests:
  `tests/test_scout_dashboard_page.py` and
  `tests/test_scout_emergency_mobile_approval_ui.py`.
- PASS: regenerated the local sanitized Body Index snapshot from the 3
  deduped HealthExport sources. The import merged 0 new sources, skipped 3
  duplicates, and added provider metric summaries for 10 metric families.
- PASS: browser smoke on the 9099 Body Index route. Health Baseline Signals
  rendered numeric values including VO2max median, resting HR median, HRV
  median, walking HR average median, active energy median, HR pressure windows,
  recovery debt windows, and step/distance medians.
- PASS: privacy boundary check. The API response, page text, and persisted
  sanitized snapshot did not contain raw HealthExport rows, GPX XML,
  coordinates, original HealthExport zip names, or exact source timestamps.
- PASS: `pnpm lint`, `pnpm typecheck`, `pnpm test`, and `git diff --check`.
- Evidence screenshot:
  `/tmp/scout-dashboard-body-index-values-desktop.png`.

### 2026-07-09 - Body Index Baseline Trend Arrows

User request:

- Add trend arrows to each Health Baseline Signal card so the card shows how
  the baseline value relates to the average/baseline range and the minimum and
  maximum points.

Implementation steps:

- Added a sixth Health Baseline Signal field containing trend metadata.
- Added sanitized `mean_value` to provider metric summaries so the trend axis
  can show minimum, average, and maximum values without embedding raw samples.
- For provider metric cards, calculated the baseline marker position from the
  sanitized provider metric range: `(median - min) / (max - min)`.
- Classified the marker as `low`, `mid`, or `high`, then rendered the matching
  trend arrow on the card.
- For HR Pressure Windows and Recovery Debt Windows, calculated the trend
  marker from `window_count / total_sanitized_windows`.
- Added a compact min-average-max axis to each signal card. The arrow marker
  represents the baseline median position relative to that range.
- Kept backward-compatible rendering for older Body Index snapshots that do
  not yet include trend metadata.
- Extended dashboard contract tests to cover the trend metadata and UI hooks.

Boundary notes:

- Trend arrows are source-provider planning evidence only.
- The calculation uses sanitized aggregate min, median, max, and window counts.
- No raw HealthExport rows, raw GPX, coordinates, exact timestamps, safety
  mutation, live safety automation, hardware control, or outbound transport are
  introduced.

Verification:

- PASS: focused dashboard/API tests:
  `tests/test_scout_dashboard_page.py` and
  `tests/test_scout_emergency_mobile_approval_ui.py`.
- PASS: regenerated the local sanitized Body Index snapshot from the 3
  deduped HealthExport sources. The import merged 0 new sources, skipped 3
  duplicates, and added trend metadata to all 8 Health Baseline Signal cards.
- PASS: browser smoke on the 9099 Body Index route. The page rendered 8 trend
  axes and arrow markers across VO2max, resting HR, HRV, walking HR average,
  active energy, recovery debt windows, HR pressure windows, and step/distance
  pattern cards. Provider metric cards displayed min-average-max axis labels;
  the arrow marker represented the baseline median position.
- PASS: privacy boundary check. The API response, page text, and persisted
  sanitized snapshot did not contain raw HealthExport rows, GPX XML,
  coordinates, original HealthExport zip names, or exact source timestamps.
- PASS: `pnpm lint`, `pnpm typecheck`, `pnpm test`, and `git diff --check`.
- Evidence screenshot:
  `/tmp/scout-dashboard-body-index-trends-avg-desktop.png`.

### 2026-07-09 - Body Index Directory Watch Import

User request:

- Add a directory monitoring mechanism that scans the HealthExport directory
  on a fixed interval, automatically imports new files into the Body Index
  pool, and recalculates the baseline.

Implementation steps:

- Added operator-triggered Body Index watch APIs:
  `/admin/dashboard/body-index/watch/status`,
  `/admin/dashboard/body-index/watch/start`, and
  `/admin/dashboard/body-index/watch/stop`.
- Required `confirm_watch: true` to start a watcher because this is background
  monitoring of a private local health export directory.
- Implemented a per-project daemon watcher that scans the configured
  HealthExport directory at `interval_seconds`.
- The watcher compares current zip SHA-256 values against the persisted Body
  Index source pool. When a new zip SHA appears, it calls the existing
  sanitized Body Index import pipeline and recalculates the baseline snapshot.
- The watcher status records running state, interval, scan count, import
  count, last scan time, last import time, zip count, new candidate count,
  last sanitized import result, and last sanitized error.
- Added dashboard controls to the Body Index overview header:
  interval input, `Start Watch`, `Stop`, and a watch status chip.
- Added automatic dashboard refresh while the watcher is running so imported
  values and baseline cards update without a full page reload.
- Added regression tests that start the watcher, add a new HealthExport zip,
  wait for automatic import, verify the Body Index pool updates, and stop the
  watcher.

Boundary notes:

- The watcher is off by default and starts only after explicit operator action.
- It remains local to the admin server process and does not survive process
  restart unless the operator starts it again.
- The watcher reuses the same sanitized import path: no raw HealthExport rows,
  raw GPX XML, coordinates, original HealthExport zip names, exact timestamps,
  safety mutation, live safety automation, hardware control, or outbound
  transport are introduced.

Verification:

- PASS: focused dashboard/API tests:
  `tests/test_scout_dashboard_page.py`,
  `tests/test_scout_emergency_mobile_approval_ui.py`, and
  `tests/test_scout_runtime_physiologic_pipeline.py`.
- PASS: watcher regression test started a project-scoped watcher, added a new
  HealthExport zip, waited for automatic import into the Body Index pool,
  verified recalculated coverage, and stopped the watcher.
- PASS: browser smoke on the 9099 Body Index route. The `Start Watch`,
  `Stop`, interval input, and watch status chip rendered; watcher status API
  returned stopped by default.
- PASS: no safety, SMS/outbound, raw HealthExport, GPX XML, coordinate, zip
  filename, or exact timestamp leakage was observed in the tested watch/import
  outputs.
- PASS: `pnpm lint`, `pnpm typecheck`, `pnpm test`, and `git diff --check`.
- Evidence screenshot:
  `/tmp/scout-dashboard-body-index-watch-controls-desktop.png`.

### 2026-07-11 - Body Index Empty-state Evidence Integrity

User request:

- Take over Scout Dashboard v0.1 from the current 9099 admin runtime and
  continue development without exposing private health data or turning
  advisory evidence into safety truth.

Implementation steps:

- Added a regression test for a fresh project with no Body Index snapshot or
  imported HealthExport source.
- Replaced the default nonzero pace coefficient, reserve, vulnerability,
  experience, coverage, provider metrics, and historical pressure timeline
  with an explicit unavailable/zero state.
- Changed all eight default Health Baseline Signal cards to `pending` with
  unavailable values until sanitized source-provider evidence is imported.
- Kept all nine Scout Pace Coefficient section 7.2 cards visible, but removed
  their sample speeds, coefficients, penalties, and scores. The UI now accepts
  future evidence-backed `coefficient_metrics`; otherwise each card renders as
  pending.
- Added explicit empty states for pressure windows and provider metrics, and
  kept imported snapshots marked with `evidence_status=available`.
- Applied the same unavailable summary when every candidate ZIP fails parsing,
  so an error-only import cannot persist a calculated coefficient. The v1
  summary fields remain strings (`unavailable` before import) for response-type
  compatibility, while the UI displays `--`.

Boundary notes:

- This is a non-GIS Dashboard/API truthfulness repair; no GPX, map, layer,
  route projection, or workspace import path changed.
- No raw HealthExport row, raw GPX, coordinate, exact timestamp, original zip
  filename, Phase 1 safety mutation, live safety automation, hardware control,
  or outbound transport was added.
- The Body Index watcher remains stopped by default and still requires
  `confirm_watch=true`.

Known remaining gaps:

- The nine section 7.2 detail cards remain pending until an evidence-backed
  `coefficient_metrics` payload is implemented; the imported aggregate summary
  and Health Baseline Signals continue to render independently.
- The live Scout AI compact pretrip project payload is still large and slow
  enough to delay first-load data on some dashboard pages; this repair did not
  change the pretrip/GIS payload.
- `MQTT / Observer Message` remains a separate future data-backed dashboard
  slice and was not mixed into this Body Index truthfulness repair.

Verification:

- RED: the fresh-project regression test reproduced the fabricated default
  coefficient and coverage values.
- GREEN: the focused fresh-project regression test passed after the API and UI
  empty-state repair.
- PASS: `tests/test_scout_dashboard_page.py` (26 tests) and
  `tests/test_scout_runtime_physiologic_pipeline.py` (11 tests).
- PASS: `pnpm lint`, `pnpm typecheck`, `pnpm test`, and `git diff --check`.
- PASS: the restarted 9099 browser smoke rendered a fresh project with zero
  coverage, `--` coefficient, nine pending section 7.2 cards, eight pending
  health signals, empty timeline/provider states, stopped watcher, no
  fabricated strings, and no horizontal overflow.
- PASS: the existing imported project retained its 3-source sanitized
  snapshot, available/computable health signals, stopped watcher, and no
  browser console or 4xx response errors during the Body Index smoke.
- Evidence screenshots:
  `/tmp/scout-dashboard-body-index-empty-state-9099.png` and
  `/tmp/scout-dashboard-body-index-imported-9099.png`.

### 2026-07-11 - Map Segment Visibility And Geometry Repair

User request:

- Restore the Segment layer that appeared to be missing from the Dashboard Map.

Implementation steps:

- Confirmed the workspace and compact API still contained 239 source-backed
  Segment records and valid display geometry; no workspace rebuild was needed.
- Increased the pretrip Segment overlay contrast, width, opacity, and dashed
  visual identity so it remains distinguishable on light and dark basemaps.
- Preserved the canonical 32-layer render order and made Segment visible
  through the intentionally translucent risk overlays using a bright dashed
  stroke and dark contrast halo.
- Kept the existing map position, layer controls, fit/zoom tools, and iframe
  integration unchanged.
- Replaced the Dashboard fallback renderer's route-path imitation with one
  path per `state.project.segments[*].display_geometry.coordinate_segments`,
  preserving Segment ids and skipping absent/invalid geometry.
- Added regression coverage for Segment style, z-order, scale-aware stroke
  width, genuine per-segment paths, and no connected-route fallback to a fake
  Segment path.

Boundary notes:

- The repair is presentation-only and reads existing candidate evidence.
- It does not rebuild or mutate the workspace, alter Segment artifacts, call
  `/safety/*`, change Phase 1 runtime safety truth, control hardware, or send
  outbound transport.

Known remaining gaps:

- The two `overpass_aligned_*` Segment artifacts still carry an older
  `chilai_nanhua_day1_scoutAI_test0630_1` internal project id. They remain
  loadable but should be separately regenerated or re-bound under a reviewed
  provenance repair.

Verification:

- RED: focused pretrip/dashboard tests failed on the missing high-contrast
  style, risk-overlay z-order, and true per-segment renderer contract.
- GREEN: focused tests passed after the presentation and renderer repair.
- PASS: focused pretrip, dashboard, and layer-contract tests (54 tests).
- PASS: `pnpm lint`, `pnpm typecheck`, `pnpm test`, both 32-layer gates,
  workspace spec alignment, admin visual smoke, and `git diff --check`.
- PASS: live 9099 Dashboard Map rendered 239 non-empty, unique Segment paths
  with `stroke=rgb(0, 212, 255)`, `stroke-width=5.6px`, dashed styling,
  `opacity=.92`, a dark halo, checked control, no console/4xx errors, and no
  horizontal overflow while normal risk overlays remained enabled.
- PASS: the Dashboard fallback preview rendered 239 unique Segment ids and 239
  unique non-empty paths from `project.segments`; zero Segment paths matched
  the generic Route path, with no console/4xx errors or horizontal overflow.
- Evidence screenshot: `/tmp/scout-segments-dashboard-fixed.png`.

### 2026-07-11 - Overpass-Aligned Segment Provenance Repair

User request:

- Repair the two Overpass-aligned Segment artifacts that still carried the old
  `chilai_nanhua_day1_scoutAI_test0630_1` project identity.

Implementation steps:

- Confirmed the stale identity appeared in artifact metadata, route source
  refs, absolute source URIs, and propagated risk-ribbon feature ids.
- Added a producer regression that starts with stale source identity and
  requires aligned envelopes and records to use the current project identity.
- Changed the alignment producer to immutably stamp the current `project_id`
  and canonical `artifact.gpx.<project_id>` route artifact id.
- Rebuilt the current-project risk centerline and alignment in an isolated
  minimal workspace, then copied back
  `outputs/overpass_aligned_segments.json` and
  `outputs/overpass_aligned_segment_display_geometry.json`.
- Synchronized 13 deterministic upstream `outputs/risk/*` route, score,
  ribbon, diagnostic, and calibrated artifacts so every new aligned
  `source_feature_id` continues to resolve and the baseline/calibrated
  risk-delta join stays intact.

Boundary notes:

- The formal workspace's base GPX, candidates, checkpoints, project manifest,
  calibrated risk outputs, and other aligned artifacts were not rewritten.
  The 13 upstream risk artifacts were replaced only after backup and
  identity/numeric parity checks because they are required provenance sources
  for the two requested aligned artifacts.
- The two repaired artifacts remain candidate-only display evidence with
  `runtime_safety_truth=false`; no `/safety/*`, Phase 1 safety mutation,
  hardware control, private health data, or outbound transport was introduced.

Verification:

- RED: the producer regression reproduced inherited stale `project_id` and
  `route_artifact_id` values.
- GREEN: the regression passed after current-project identity stamping.
- PASS: all 239 Segment ids and alignment-status distributions were preserved.
- PASS: 10,262 lat/lon coordinate occurrences were byte-value equivalent
  before and after provenance repair.
- PASS: stale-id fields changed from 4,604 to 0 in aligned Segment candidates
  and from 8,059 to 0 in aligned display geometry.
- PASS: all 7,152 risk-ribbon sample refs, 3,648 aligned Segment feature refs,
  and 7,578 aligned display feature refs resolve in the formal workspace.
- PASS: all 13 synchronized upstream risk artifacts contain zero old-ID
  occurrences; route/risk numeric CSV content is unchanged after identity
  normalization.
- PASS: display geometry retained 239 logical segments, 239 parts, 5,131
  points, `candidate_only=true`, and `runtime_safety_truth=false`.
- PASS: focused alignment pytest (6 tests), `pnpm lint`, `pnpm typecheck`,
  `pnpm test`, both 32-layer gates, workspace spec alignment, admin visual
  smoke, and `git diff --check`.
- PASS: live 9099 Map retained 239 non-empty Segment paths, 3,576 baseline
  risk paths, 3,576 calibrated paths, 3,672 risk-delta SVG paths, a checked
  Segment control, no horizontal overflow, and zero console/4xx errors.
- Evidence screenshot: `/tmp/scout-provenance-repair-live-9099-final.png`.
- Backup: `/tmp/scout-provenance-repair.fgZG1X/backup`.

### 2026-07-15 - Joint Dashboard Truth, Workflow, And Usability Remediation

Source review:

- Implemented the P0-P2 findings from the joint Dashboard usability review in
  `/Users/alexwang0315/.codex/gpt-pro-collaboration/20260715-121919-dashboard-usability-review/final-report.md`.
- Kept the work in local Construction Mode. No workspace artifact, runtime
  safety truth, private HealthExport data, hardware, broker, or outbound
  transport was mutated.

P0 truth and broken-workflow repairs:

- Assistant maturity is `partial`; configured, connected, repository-ready,
  failed, unavailable, and checking states are separate. Green is possible
  only after both transport and repository readiness are verified.
- Trip Intake now calls a server GPX parser. Missing, unreadable, malformed,
  non-GPX, oversized, and directory paths fail closed; stage intent remains
  disabled until the exact input has a matching successful validation receipt.
- Route Context variant links use canonical `?ref=` URLs. The server also
  rewrites legacy bare relative links in existing generated indexes without
  mutating those workspace artifacts.
- Pace controls are labelled and rendered as read-only parameters, not fake
  buttons.
- Debug separates transport state from event provenance and labels live
  runtime, fixture replay, smoke, historical, and projected rows explicitly.

P1 truth, scope, and scale repairs:

- Every one of the 23 routes has a five-axis truth contract: Surface, Data,
  Action, Verification, and Provenance/Readiness. Dynamic loading, failure,
  stale, no-coverage, embedded-frame, Assistant, Settings, Map, and Debug
  states override static route copy and do not retain an `Operational` suffix
  while degraded.
- Workspace/import CTAs record intent only and emit explicit receipts stating
  that no filesystem mutation occurred.
- Assistant rejects blank and whitespace-only questions before a request.
- Timeline and Map evidence are windowed to 100 items per page, preserve the
  selected source/page across category changes, and expose total counts.
- Layer copy states `32 canonical layers; Pre-trip and Debug expose 31;
  completed-track is after-action only`.
- Permission is a `Permission Class Selector Preview` with a static rule set
  and no runtime decision or authorization claim.

P2 information architecture, Settings, mobile, and accessibility repairs:

- Overview starts with a Current Decision Brief for route context,
  weather/terrain freshness, and evidence gaps. Workspace metadata and preview
  taxonomy are secondary context; dense drill-downs remain available.
- Preview mode is explicit: Product Preview, Technical Prototype, Reference,
  or Static rule set.
- Settings validates project/API inputs, catches and rolls back synthetic
  storage failures, preserves success/failure receipts across background
  re-renders, enables reload only for changed values, and forces a real reload
  when the target URL is unchanged.
- Removed duplicate `dashboardMap` and `dashboardMapStatus` IDs. This fixes the
  Home-to-Map transition that previously selected a hidden preview instead of
  the real Map iframe, which made Map and Segment appear to disappear.
- Six Axis tablists support Arrow keys, Home, and End while preserving focus on
  the newly selected tab after route render.
- Disabled Assistant Send and Stage Import controls expose reasons through
  titles/status associations. Embedded surfaces provide a keyboard-activatable
  `Skip embedded surface` control that moves focus to an explicit exit marker.

Browser evidence:

- Desktop route smoke: 23/23 routes had the expected hash, active sidebar
  item, title, maturity, five truth fields, visible content, and no horizontal
  overflow.
- Settings: invalid `ftp:` was rejected; a reversible same-origin value was
  saved, survived background re-render, reloaded through the UI, restored to
  blank/same-origin, and reloaded to a clean disabled state.
- Route variants: all five cards in the existing index opened their generated
  HTML successfully.
- Timeline: 13,196 Map/Risk items remained bounded to 100 visible controls;
  next-page selection and category round-trip restored page and focus.
- Standard direct Pre-trip Map: five measured Segment cycles (10 real
  `setChecked` actions) ended `checked=true`, `isConnected=true`; console log
  count was zero. Longer single automation batches exceeded the harness time
  limit but did not establish a product detach.
- Mobile viewport was proven at 390x844 with both 1120px and 620px breakpoints
  active. Overview, Map, Timeline, Assistant, and embedded Pre-trip had
  `scrollWidth=clientWidth=390`. Home-to-Map produced a 390x602 iframe and a
  370x270 evidence rail (under 70dvh), with Segment visible and no duplicate
  IDs. Timeline showed 100 controls per page; the mobile drawer closed with
  Escape and restored focus.
- Embedded Pre-trip, Admin, and Debug frames reported `Inner surface ready -
  content verified`; Debug content exposed Transport and Event provenance.
- Emergency approval remained sandboxed: `decision=agree_send` could be
  reviewed locally while `external_send_performed=false`,
  `safety_api_called=false`, and `sent=false` remained unchanged.

Focused executable evidence before the final full-suite gate:

- Synthetic HealthExport invalid, sanitized/deduped import, and watcher
  lifecycle; Route Context model success and provider failure; Emergency
  sandbox: 7 passed.
- Assistant readiness matrix, Weather fresh/source-failure/stale/no-coverage,
  Settings validation/storage failure, and UI contract checks are covered by
  executable Node-in-pytest contracts.
- Final Dashboard and Debug suites: 59 passed. Final Admin API suite: 85
  passed. `pnpm lint` and `pnpm typecheck` passed.
- Repo and real-workspace layer verifiers both returned `ok=true` with 32
  canonical layers, 239 workspace Segments, and completed-track restricted to
  after-action controls.
- `pnpm test` completed 15/17 checks; the two failures are unrelated,
  pre-existing AI OS documentation assertions requiring legacy Phase 9 and
  safety-copy tokens in `AGENTS.md`. No Dashboard implementation test failed.

GPT Pro closure corrections:

- Debug provenance is now a server-ingestion contract, not a frontend text
  heuristic. The immutable enum is `runtime`, `fixture_replay`, `smoke`,
  `historical`, `projection`, or `unknown`; missing/untrusted channel values
  fail closed to `unknown`. Runtime, smoke, historical, spatial projection,
  repo fixture, and workspace pre-trip projection paths supply their channel
  server-side. Event message/source/payload text cannot promote a row to live.
- The Dashboard workspace runner explicitly marks its built-in Admin UI replay
  as `smoke_harness`. With all Debug endpoints loaded, the browser showed
  `Transport connected` alongside `0 live runtime · 4 non-live`; all four rows
  were `Smoke test`. The full `/admin/debug` surface showed the same result.
  Repeated GET, stream rehydration, connected transport metadata, and a fixture
  payload attempting to claim `runtime` are covered by focused regressions.
- Overview's primary DOM and visual order is now explicit:
  `workspace/trip -> current decision -> blocking truth -> next action`.
  Verification tasks and full evidence follow; Admin and Debug drill-downs do
  not appear in the first viewport. At desktop 1280x720 all four primary fields
  were fully visible. At 390x844 they occupied y=302..546 in the same order,
  used x=37..353, and the document remained `scrollWidth=clientWidth=390`.
  `stale_data` produced `HOLD · review blocking truth`; the first focusable
  Overview action was `Review route context`, before Weather, Evidence, Admin,
  or Debug actions.
- Reporting remains scope-qualified: the mobile claim covers the tested
  390x844 critical-route smoke, accessibility covers targeted keyboard/focus/
  naming checks, synthetic integrations are not live-provider evidence, and
  the configured secret-pattern scan is not a full security audit.
- Post-correction affected suites passed 82 tests; the complete Admin API file
  passed 86 tests. Python compilation, `pnpm lint`, `pnpm typecheck`, and scoped
  `git diff --check` passed; the high-risk secret-value pattern count was zero.
  Repository `pnpm test` remains 15/17 for the two disclosed legacy docs
  assertions. An additional, non-gating `tests/test_debug_api_mount.py` run in
  the project venv remains 1/4 because the current unrelated server composition
  exposes `/admin/debug` unconditionally and includes `_IncludedRouter` entries
  without `.path`; neither server composition nor that legacy test was changed
  in this Dashboard remediation.
- GPT Pro's second implementation review accepted both remaining issues
  (`SCOUT-OBS-001` and `SCOUT-IA-001`), found no remaining false claim or
  evidence gap blocking the original 16 issues, and explicitly concluded:
  `我同意原 report 的 P0-P2 remediation 已完成（approval-dependent real effects 保持 fail-closed）。`

## 2026-07-17 Living closed-loop sandbox slice

- Added the `Living` route to observe one server-side Emergency Mobile sandbox
  run from synthetic SensorLogger phone/wearable ingress through all six shadow
  gates, an immutable evaluation snapshot, reducer candidate, immutable alert
  packet, mobile approval, server-created sandbox attempt, manually selected
  simulator outcome/receipt, and a contiguous causal timeline.
- `Living` polls `GET /admin/dashboard/living` and its controls use only the
  isolated `/admin/dashboard/living/*` sandbox namespace. The page exposes the
  packet/approval/attempt/receipt lineage instead of inferring progress from UI
  timers.
- The Emergency Mobile v0 HTML can load the same projection and submit a
  packet-bound decision. It continues to preserve local callout alternatives
  and does not claim a production send.
- All displayed locations are privacy-safe route references. Synthetic replay,
  reducer candidates, attempts, and receipts remain separate from Phase 1
  truth, hardware control, broker publish, production transport, and verified
  delivery.
- `simulated_receipt_recorded` means the simulator receipt correlated to the
  authorized attempt. The UI states that no real transport or delivery
  occurred; it never renders this as verified delivery.

## 2026-07-17 - Preserve the route-weather intersection map composition

User request:

- Keep the Weather map's large contour field, vertical layer controls,
  route-weather callout, and integrated evidence timeline shown in the approved
  Weather design reference.

Implementation steps:

- Replaced the generic 13-layer Weather preview with a dedicated
  `Route-weather intersection` instrument using the approved forest contour
  composition and the existing shared Weather design tokens.
- Connected the Radar, Rainfall Grid, and Route buttons to the Dashboard's
  canonical `state.layerEnabled` values. Each control changes the rendered map
  instead of acting as a visual-only button.
- Projected the current admin route geometry and checkpoint labels when route
  data is available. When it is unavailable, the panel explicitly labels the
  route as a visual fallback rather than implying live geometry.
- Connected the integrated range control to cached CWA radar frame timestamps.
  Fewer than two cached frames disables the control and reports that the
  timeline is unavailable.
- Kept missing data honest: absent rainfall cells and radar frames render as
  labeled outlines, and the route callout treats missing coverage as unknown
  rather than zero rainfall.

Boundary notes:

- The map is route-bbox, cache-only candidate evidence. It does not calculate
  a runtime safety decision, mutate Phase 1 truth, or claim that rainfall cells
  intersect a specific route segment.
- The standalone reference's fictional checkpoint IDs, fixed forecast time,
  and fixed arrival-delay statement were not copied into the real Dashboard.

Verification:

- `./venv/bin/python -m pytest -q tests/test_scout_dashboard_page.py`: 42
  passed.
- `pnpm typecheck` completed its configured scaffold import check: 1 passed;
  `pnpm run lint` passed both configured Node syntax checks; scoped
  `git diff --check` passed.
- Chrome smoke at 1440x1000 confirmed the dedicated map, all three layer
  buttons, disabled no-frame timeline, and no horizontal overflow. Toggling
  Radar changed both `aria-pressed` and the corresponding SVG layer's hidden
  state.
- Mobile emulation at 390x844 retained the composition with a 366px-wide map
  panel and `scrollWidth === clientWidth === 390`.
- The current project returned expected 404s for missing project projection and
  rainfall-grid cache endpoints. The Dashboard remained degraded/read-only and
  rendered explicit unavailable/fallback states; weather imagery returned 200.

## 2026-07-21 - Default Dashboard Map OSM layer to off

User request:

- Make the OSM layer in Dashboard Map initially disabled.

Implementation steps:

- Changed the Dashboard map state so every canonical layer except `osm` starts
  enabled.
- Removed the initial checked state from the OSM control in the embedded
  pre-trip Map surface.
- Kept the OSM checkbox and render path intact, so operators can turn the layer
  on manually.

Boundary notes:

- This changes browser-local initial presentation only. It does not delete OSM
  data, change preparation/import defaults, mutate project artifacts, or alter
  runtime safety truth.

Verification:

- `./venv/bin/python -m pytest tests/test_scout_dashboard_page.py -q`: 43
  passed.
- Chrome smoke on the served `#map` route confirmed `checked=false` on first
  load and `checked=true` after clicking the OSM control.
- The only observed console error was the existing `/favicon.ico` 404; all
  Dashboard, pre-trip projection, OSM vector, and imagery requests used by the
  map returned 200.

## 2026-07-23 - Remove the Dashboard Map header

User request:

- Remove the large Map header containing the page title, maturity badge, and
  truth-status cards.

Implementation steps:

- Hide the outer Dashboard topbar whenever the Map route uses its full-frame
  layout, giving the map the released vertical space.
- Added a compact Map-only navigation toggle for viewports at or below 1120px,
  so removing the header does not strand mobile operators inside the Map route.
- Synchronized both navigation toggles through the existing sidebar state and
  Escape-key focus return path.
- Corrected the full-frame grid to a single `minmax(0, 1fr)` row. The initial
  header removal left the original two-row template in place, which auto-placed
  Map into a 150px `auto` row and pushed Map Evidence above the viewport.

Boundary notes:

- The embedded map, layer controls, Map Evidence rail, and truth-resolution
  data remain unchanged; this is a route-local presentation change only.

Verification:

- `./venv/bin/python -m pytest tests/test_scout_dashboard_page.py -q`: 45
  passed.
- Corrected desktop smoke at 1600x900 confirmed the Dashboard frame, content
  grid, Map shell, and iframe all use the full 900px height; Map Evidence is
  inside the viewport at `y=14` and the desktop navigation overlay is hidden.
- Corrected 430px smoke confirmed the frame, content grid, Map shell, and
  iframe all use the full 557px viewport height; Map Evidence is inside the
  viewport at `y=277` and the compact navigation toggle remains available.

## 2026-07-23 - Dashboard connected weather preparation

- Dashboard startup now triggers the local server-side
  `POST /admin/pretrip/projects/{project_id}/connected-preparation` job and
  polls its GET status. It no longer relies on a Dashboard default of
  `pi-offline + no-network`; connected map-preparation defaults are
  `mac-workstation + explicit-fetch + allow-network-fetch`.
- The manager loads the local repository `.env` or explicit `SCOUT_ENV_FILE`
  without exposing values, sets the CWA imagery server capability, requires a
  cache outside the workspace/repository, refreshes the provider-backed
  Overpass/CWA/GEE layer subset, and enables `prepare_cwa_imagery`. Existing
  route, terrain, and TEII artifacts remain inputs and are not regenerated on
  every refresh.
- The job is single-flight and schedules a service-lifetime refresh every ten
  minutes by default. Repeated Dashboard opens reuse the active/completed job
  and do not duplicate it. Stopping the Dashboard service cancels its timers.
- Queued/running request outcomes are tri-state: request/call fields remain
  `null` with `requestActivityState=in-progress` until observed results exist,
  and the UI shows `in progress` rather than a premature `false`.
- Connected polling no longer re-renders the Weather controls every three
  seconds while a job is active, so a Frame drag is not detached/reset. A
  temporary route-identity mismatch during manifest publication is rendered as
  preparing/loading and retried at completion, not as a permanent source error.
- Recurring refresh skips raster OCR, Boss-point synthesis, and mileage-tag
  alignment plus terrain/map-spec artifact regeneration
  (`skipped_connected_refresh`); those non-weather rebuilds remain available in
  the normal full preparation flow. Existing terrain artifacts are still read
  by route risk extraction.
- Weather keeps all reads cache-only, displays connected job provenance, and
  reloads prepared artifacts when the background run completes. Radar and
  satellite animation windows therefore accumulate only real fetched frames.
- The Weather page adds an explicit geolocation gesture. After the user selects
  a prepared checkpoint and approves browser location access, it obtains a
  short-lived server approval and calls `rainfall-trend`; submitted coordinates
  are not persisted. Null score presentation is `0% · no evidence`, not an
  unqualified zero-risk claim.
- Server-side outputs remain candidate-only. LoRa stays a byte-bounded
  `sent=false` preview; there is no RF send, hardware control, `/safety/*`
  mutation, Pi image processing, or mobile image processing.

## 2026-07-23 - Navigation & Terrain Intelligence contour workbench

User request:

- Redesign the Dashboard Navigation route around
  `SCOUT_OUTDOOR_AI_AGENT_STANDARD` section 11 and mark terrain structure,
  decision points, and terrain-risk areas on a contour map.

Implementation:

- Replaced the previous two-card Navigation reference with a full-width,
  interactive terrain-reading workbench.
- Added four reading lenses: terrain structure, slope pressure, risk terrain,
  and retreat direction.
- Added eight numbered contour-map annotations: ridge, valley, saddle, fork,
  cliff, gully, steep slope, and exposed terrain.
- Clicking an annotation updates a Terrain Inspector with recognition cues,
  terrain pressure, the field question to ask, and the next evidence required.
- Added a six-item map-literacy checklist covering offline maps, GPX/direction,
  contour reading, fork strategy, retreat direction, and positioning backup.
- Kept the 720px contour fixture horizontally scrollable inside the map at
  narrow widths instead of allowing it to widen the entire Dashboard.

Boundary notes:

- The contour map is explicitly a synthetic UX fixture and candidate terrain
  interpretation. It does not claim that the annotations belong to the current
  route, prove current walkability, recommend a safe route, or write runtime
  safety truth.
- The change does not alter canonical layer IDs/order, import preparation,
  workspace artifacts, `/safety/*`, hardware, location permission, or outbound
  transport.

Verification:

- `./venv/bin/python -m pytest tests/test_scout_dashboard_page.py -q`: 46
  passed.
- Desktop browser smoke at 1440x1050 showed all eight annotations, all four
  lenses, no page-level horizontal overflow, and a selected saddle detail.
  Switching to Risk and selecting Cliff changed the active detail to `崩壁`.
- Mobile browser smoke at 390x844 showed a 366px workbench/map panel with the
  720px contour SVG contained in the map's own scroll region; the document had
  no horizontal overflow.
- Browser console inspection reported no errors or warnings.

## 2026-07-23 - Workspace DEM projection for Terrain Intelligence

Implementation:

- Added a bounded, read-only
  `GET /admin/pretrip/projects/{project_id}/navigation-terrain-intelligence`
  projection. It reads prepared terrain visualization, route-aligned samples,
  and terrain-risk candidates from the selected local workspace.
- The projection returns same-origin raster URLs plus at most 240 evenly sampled
  route points and 50 review candidates. Raw DEM and GPX payloads are not
  embedded in the Dashboard response.
- Navigation now defaults to `Workspace evidence`; the original synthetic
  contour exercise remains available as `Training fixture`.
- The structure, pressure, risk, and retreat lenses share one terrain surface.
  Pressure uses the prepared slope-shading raster; risk points open a bounded
  inspector with TEII, TRI, pretrip-risk, review state, and the next evidence
  needed.
- The current bitmap fallback does not prepare reviewed ridge, valley, or
  saddle vectors. Those three capabilities render as `not_prepared` instead of
  being inferred from the raster by the UI.

Candidate boundary:

- All projected evidence is `candidate_only=true`,
  `runtime_safety_truth=false`, and `human_review_required=true`.
- Terrain-risk candidates are displayed as pressure locations, not relabeled as
  cliff, valley, exposed terrain, a retreat point, or a walkable route.
- The endpoint does not call `/safety/*`, mutate Phase 1 truth, control hardware,
  or perform outbound transport.

Chilai Nanhua replay:

- Prepared DTM: 20m cells, 12 source tiles, 35,546 selected cells, and 3,534
  contour markers.
- Route evidence: 1,826 source samples projected to 240 deterministic display
  points.
- Risk evidence: 50 source candidates; the map displays the first 30 ranked
  pressure points to keep the interactive SVG bounded.
- Desktop at 1440x1050 loaded the 432x169 hillshade/contour rasters, one route
  path, and 30 candidate markers with no page-level horizontal overflow.
- Mobile at 390x844 kept the 720px map surface inside a 364px horizontal scroll
  container while the document itself had no horizontal overflow.
- Browser interaction confirmed workspace/training source switching, risk-point
  selection, and slope-pressure lens rendering with hillshade, slope shading,
  contours, and 30 pressure dots.

Verification:

- `./venv/bin/python -m pytest tests/test_navigation_terrain_projection.py
  tests/test_scout_dashboard_page.py -q`: 50 passed.
- `pnpm lint`: passed.
- `pnpm typecheck`: passed, including its focused scaffold import test.
- The deterministic 32-layer contract verifier was not run because this slice
  did not change layer IDs, order, import preparation, or shared map-layer
  behavior.

## 2026-07-23 - DEM morphology, source ledger, and shared route topology

Implementation:

- The Navigation workspace projection now reads the bounded 20m DTM grid files
  behind the prepared slope bitmap and extracts deterministic ridge, valley,
  and saddle morphology candidates inside the route corridor. It uses local
  TPI, relief, neighbor sign changes, and non-maximum spacing; the browser does
  not infer candidates from raster pixels.
- The Chilai Nanhua replay examines 35,546 selected cells from 12 grid files.
  Raw candidates are ridge 698, valley 966, and saddle 61; the API and map
  expose at most 24 of each kind.
- Added a tier-preserving source ledger: P0 official DEM baseline, P1 archival
  or historical prose, and P2 operator-supplied GPX. Missing P1 evidence stays
  visible as a gap and P0/P1/P2 are never merged into a safety score.
- Added an ordered GPX waypoint clue chain and an explicit coordinate audit for
  EPSG:3826/TWVD2001 versus EPSG:4326/WGS84. These are navigation clues, not
  historical proof or survey-grade control.
- Added a shared route graph. The prepared Chilai route is represented as eight
  nodes, seven reusable observed edges, and one baseline option; 23 reference
  GPX files remain evidence sources rather than invented detours. A separately
  compiled historical hypothesis can add candidate options over shared edges.
- The workbench now shows the structure candidates, Source Ledger, Ordered Clue
  Chain, Shared Route Topology, and Contradictions & Gaps. Selecting a
  morphology point opens its TPI, local relief, slope, morphology score, and
  route proximity.
- Navigation terrain loading has its own 60-second bounded timeout and no longer
  starts the unrelated project aggregate scope on a direct Navigation open.
  This prevents cold DEM extraction from being aborted by concurrent
  project-preparation work.

Candidate boundary:

- A morphology candidate does not establish a ridge trail, valley trail,
  saddle shortcut, retreat line, access permission, present walkability, or
  suitability for solo travel.
- Historical options remain `candidate_only=true`,
  `runtime_safety_truth=false`, and `safe_or_walkable=not_determined`.
- The slice is read-only and does not write `/safety/*`, mutate Phase 1 truth,
  control hardware, expose raw GPX, or perform outbound transport.

Browser verification:

- Desktop 1440x1050: status
  `ready_with_candidate_structures`, 72 visible morphology points, one bounded
  route path, two 432x169 raster layers in the structure lens, four evidence
  panels, and no page-level horizontal overflow.
- Interaction: selecting valley candidate 24 updated the inspector; Risk showed
  30 risk-review candidates and hid morphology points; Pressure showed the
  slope-shading overlay, one route path, and 30 pressure dots; Training retained
  all eight synthetic teaching markers.

## 2026-07-23 - Chilai P1 evidence and compiled candidate topology

Correction:

- The Chilai workspace now links one P0 official historical baseline, one P1
  professional SameJan itinerary, and one P1 Keepon completed-trip/GPX landing
  page. The source ledger keeps those separate from the P2 operator-supplied
  GPX inventory.
- The historical compiler produces exactly three P1-described combinations:
  Qilai South plus Nanhua, Qilai South only, and Nanhua only. It reuses the
  shared approach edges instead of copying three independent route lines.
- The observed workspace route remains the sole baseline. Compiled variants
  render only as candidate topology with `runtime_safety_truth=false` and
  `safe_or_walkable=not_determined`; no additional luxury route or detour is
  invented.
- The former 1,472-line `navigation_terrain_workspace.py` is now a 17-line
  compatibility facade. DEM extraction, coordinate conversion, provenance
  projection, and topology projection live in separate focused modules.
- Mobile 390x844: the document had no horizontal overflow, all four evidence
  panels collapsed to one 364px column, and the 720px terrain map remained
  horizontally scrollable inside its 364px container. Selecting saddle
  candidate 24 updated the inspector.
- Browser console inspection reported no errors or warnings.

Verification:

- 64 focused tests passed across workspace extraction, API projection,
  historical compiler, and Dashboard contracts.
- Skill validation passed for
  `.agents/skills/infer-historical-dem-gpx-routes`.
- `pnpm lint`, `pnpm typecheck`, and Python bytecode compilation passed.
- The Iroko reference fixture compiled two route options with five shared
  edges while preserving the candidate/runtime boundary.
- The deterministic 32-layer contract verifier remains not applicable because
  no layer IDs, order, GPX/import preparation, or shared map behavior changed.

## 2026-07-24 - Expert terrain hierarchy and route-event slices

Implementation:

- Added a continuous candidate terrain hierarchy over the prepared 20m DEM:
  91 main-ridge edges, 29 spur-ridge edges, 98 drainage-trunk edges, and 22
  tributary edges are included in the bounded Chilai projection.
- Added ordered GPX-to-terrain events. The current replay generates 93
  candidates and projects the first 80 by route distance; events include ridge
  and watershed crossings, drainage crossings, saddle passages, ridge divides,
  headwater candidates, and alignment transitions.
- Added a `路線事件` workspace lens and a horizontally scrollable event
  timeline. Selecting an event updates both the map marker and inspector with
  `看到什麼`, `走錯徵兆`, `回復檢查`, and the evidence boundary.
- Training fixture now exposes only its four applicable contour-reading
  lenses. Switching from workspace events to training automatically returns to
  `地形結構`, avoiding an empty GPX-event lens.
- Event cards retain native button semantics and `aria-pressed`; the conflicting
  `role=listitem` override found during browser inspection was removed.
- A direct Navigation open no longer starts unrelated connected preparation.
  It requests only the Dashboard document, Navigation projection, and the
  terrain raster images required by the active lens.

Projection and safety boundary:

- The API returns at most 240 hierarchy edges, 500 nodes, 64 points per edge,
  and 80 route-terrain events. It does not embed raw DEM or GPX payloads.
- The hierarchy and event sequence remain
  `candidate_only=true`, `runtime_safety_truth=false`, and
  `safe_or_walkable=not_determined`.
- Terrain branches are not relabeled as trail forks. Event prompts are review
  cues and never establish path existence, current access, walkability, or
  suitability for solo travel.

Chilai browser replay:

- Desktop 1440x1050 displayed all 240 bounded hierarchy edges and 72 morphology
  points with no document-level horizontal overflow.
- The `路線事件` lens displayed 80 red event rings and 80 native event buttons.
  Selecting event 27 changed the inspector to the 4.46km saddle passage and
  synchronized the selected map ring.
- Workspace-to-training switching removed the event lens and reset the active
  lens to structure; switching back restored the workspace hierarchy.
- Mobile 390x844 kept the 720px terrain map and the long event timeline inside
  their own horizontal scroll containers. The document remained 390px wide
  with zero page-level horizontal overflow.
- A clean direct Navigation load issued four successful requests: Dashboard,
  Navigation projection, hillshade, and contours. Browser console inspection
  reported no errors, warnings, or issues.

Verification:

- 78 focused tests passed across expert annotations, DEM hierarchy, ordered
  events, workspace extraction, bounded projection, historical-route inference,
  and the full Dashboard page contract.
- The deterministic 32-layer verifier passed 32/32 against the real Chilai
  workspace with no errors or warnings.
- `pnpm lint`, `pnpm typecheck`, Ruff, Python compilation, and the
  `infer-historical-dem-gpx-routes` skill validator passed.
- The package-level `pnpm test` still has two unrelated existing documentation
  assertions: the current `AGENTS.md` no longer contains the old Phase 9 marker
  and one legacy generated-code-network phrase. The other 15 package tests
  passed.

## 2026-07-24 - Navigation page chrome reduction

- Navigation retains the six-axis switcher in its established order: Route
  Context, Pace Fit, Permission, Architecture, Weather, and Navigation.
- The shared Dashboard title/truth header and the Navigation intro, status, and
  source-selector hero are hidden on Navigation only. The switcher now leads
  directly into Workspace Terrain Evidence.
- Other six-axis routes retain the shared Dashboard header; switching from
  Weather back to Navigation reapplies the Navigation-only layout.
- Desktop 1440x1050 and mobile 390x844 browser checks showed no document-level
  horizontal overflow. The mobile terrain map remains horizontally scrollable
  inside its bounded panel.
- A clean Navigation load issued four successful requests: Dashboard,
  Navigation projection, hillshade, and contours. Browser console inspection
  reported no errors, warnings, or issues.

## 2026-07-24 - Compact Map Literacy header

- Map Literacy Checklist now replaces the former Workspace Terrain Evidence
  heading at the top of the terrain map panel.
- The six training checks remain available in a native disclosure, but are
  collapsed by default because they are supporting information rather than an
  ability-test result.
- The separate right-column checklist card was removed. Route × Terrain Event
  and Terrain Event Timeline now remain in the same visible work sequence
  without the always-expanded checklist between them.
- The collapsed header measured 59px high on both desktop and mobile checks.
  The event-detail-to-timeline gap measured 122px at 1440x1050 and 105px at
  390x844.
- Expanding the disclosure exposed all six checks in the accessibility tree.
  Desktop and mobile retained zero document-level horizontal overflow, and the
  browser console reported no errors, warnings, or issues.

## 2026-07-24 - Attach Terrain Event Timeline to the map

- The former layout placed the Timeline after the complete two-column
  workspace. Because the right-side Inspector was taller than the map, its
  height delayed the Timeline and left an empty block below the map.
- Map and Timeline now compose a dedicated primary column. The Inspector stays
  in the secondary column and no longer controls the Timeline start position.
- At 1440px the map-to-Timeline gap changed from 192px to the standard 14px
  component gap.
- At 1024px, 768px, and 320px the primary column retains the same 14px gap,
  followed by the Inspector. The 320px document has zero page-level horizontal
  overflow; the 720px map and long event track remain independently scrollable.
- DOM and accessibility reading order follows the visual hierarchy: map,
  Timeline, then Inspector on single-column layouts.

## 2026-07-24 - Shared map navigation contract

All spatial map surfaces now expose the same basic view operations:

- `+`, `-`, and `Fit` buttons zoom in, zoom out, and reset the view.
- `Pan` is the default interaction. Pointer drag pans the map; arrow keys pan
  the focused map; the mouse wheel zooms around the pointer.
- `Box` supports point zoom and directional rectangle zoom. A click zooms in,
  a down-right rectangle zooms in, and an up-left rectangle zooms out.
- Keyboard shortcuts are consistent across surfaces: arrows pan, `+`/`-`
  zoom, `0` resets, `P` selects Pan, `B` selects Box, and `Escape` cancels the
  active gesture.

Coverage:

- Dashboard-native maps use one shared viewport controller: Scout map preview
  (Overview, LBS, and Permission), Pace Fit, Architecture, Navigation training,
  and Navigation workspace DTM.
- Dashboard Map and Weather reuse the canonical Pre-trip renderer. Weather
  keeps the five basic map controls visible while hiding unrelated layer/edit
  chrome.
- Direct Pre-trip, After-Action Admin, and Runtime Debug maps expose the same
  Pan/Box modes and keyboard contract.

Responsive behavior:

- Verified at 1440, 1024, 768, and 320px with zero document-level horizontal
  overflow on the Navigation route.
- At 320px, map controls remain within the visible viewport. The Navigation
  workspace status moves below the controls, the shared Scout map preview
  shrinks to the containing panel, and the Weather CWA state badge sits below
  rather than over the map controls.
- This supersedes the earlier mobile horizontal-scroll behavior for map
  canvases. Large map content is now explored through the common pan/zoom
  controller; long evidence timelines may still scroll inside their own
  bounded container.

Browser evidence:

- Dashboard Navigation accepted button zoom, arrow-key pan, mouse drag pan,
  point zoom, forward rectangle zoom, reverse rectangle zoom, and Fit reset.
- The canonical Pre-trip map changed viewBox origin without changing its size
  during mouse drag pan, and changed viewBox size during point zoom.
- After-Action Admin and Runtime Debug accepted button zoom and focused-map
  keyboard pan.
- Pace Fit, Permission, Architecture mobile Map view, Dashboard Map, and
  Weather exposed all five controls. Weather controls and its CWA bridge badge
  have non-overlapping bounds on both 320px and 1440px layouts.

Verification:

- `tests/test_scout_dashboard_page.py`: 50 passed.
- Pre-trip, Debug, After-Action, and Assistant page suites: 70 passed plus 8
  subtests.
- Real Chilai workspace layer verifier: 32/32 layers passed with no errors or
  warnings.
- `pnpm lint` and `pnpm typecheck` passed.
- The package-level `pnpm test` retains two unrelated documentation failures:
  the removed Phase 9 marker in `AGENTS.md` and a legacy generated-code-network
  phrase. The other 15 package tests passed.

The controller changes map presentation only. They do not add route approval,
walkability proof, Phase 1 mutation, outbound transport, or runtime safety
truth.
