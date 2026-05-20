# Scout Admin UI Direction

## Objective

Define the product and interface direction for Scout's admin-facing UI surfaces:

- Phase 3.5 runtime debug console at `/admin/debug`;
- Phase 1 after-action review at `/admin`;
- Phase 4 pre-trip planning workspace at `/admin/pretrip`.

This document is a design guide, not an implementation plan. It should keep
future UI work aligned with Scout's safety architecture: Phase 1 remains the
deterministic runtime baseline, Phase 2 remains fact-only writeback and
decision support, Phase 3 remains integration and release gates, Phase 3.5
remains read-only runtime observability, Phase 4 remains planning workspace,
and Phase 4.5 remains the explicit departure/runtime handoff boundary.

## Shared Product Principles

### Wilderness Safety First

Every admin surface should make Scout easier to trust as a wilderness safety
system. Navigation, planning, and AI assistance are supporting roles. The UI
should expose evidence, uncertainty, provenance, and human review state before
it presents recommendations.

### User Role Separation

Scout should not collapse every admin page into a single generic dashboard.
Each surface has a different user and different job:

| Surface | Primary user | Primary job | Interaction posture |
| --- | --- | --- | --- |
| `/admin/debug` | Engineer/operator | Diagnose runtime behavior | Dense, read-only, event-first |
| `/admin` | Mission owner/reviewer | Understand what happened | Map-first, evidence-led, readable |
| `/admin/pretrip` | Trip leader/planner | Prepare a future mission | Workspace-first, review-gated |

### Evidence Before Advice

Use the same hierarchy across surfaces:

1. Observed or deterministic evidence.
2. Derived measurements.
3. Human review state.
4. Model interpretation or candidate suggestion.
5. Reversible action or export.

Do not visually elevate model interpretation above observed facts. AI-generated
planning outputs should be marked as `candidate`, `reviewed`, `rejected`, or
`field_verify`.

### Explicit Boundaries

Every surface should show what it can and cannot do:

- `/admin/debug` is read-only and must not call mutation endpoints.
- `/admin` reviews completed evidence and must not rewrite historical missions.
- `/admin/pretrip` edits planning workspace material and must not imply live
  runtime activation.
- Phase 4.5 owns departure approval and runtime handoff.

## Visual Language

Scout admin UI should feel like a field instrument: clear, calm, evidence-rich,
and durable. Avoid marketing-style hero layouts, decorative cards, large
gradient backgrounds, and generic AI dashboard visuals.

### Layout

- Prefer map/evidence/detail work surfaces over landing pages.
- Keep controls close to the artifact they affect.
- Preserve dense scanning for engineering surfaces, but reduce cognitive load
  for trip-owner surfaces.
- Use full-height panes for map, timeline, evidence tree, and detail views.
- Do not nest cards inside cards. Use panels, split panes, tabs, and lists.

### Color

Use color as state, not decoration.

| Token group | Use |
| --- | --- |
| `route`, `checkpoint`, `segment`, `retreat`, `hazard`, `poi` | Map and mission artifacts |
| `ok`, `warning`, `bad`, `info` | Runtime and review status |
| `candidate`, `reviewed`, `rejected`, `field_verify` | Planning review state |
| `phase1`, `phase2`, `phase3`, `phase35`, `phase4`, `phase45` | Boundary and provenance labels |

Dark mode is appropriate for `/admin/debug`. The after-action and pre-trip
surfaces may use dark or light themes, but should not be dominated by one hue
family. Contrast must remain strong for outdoor review conditions.

### Typography

- Use small, stable headings inside tool surfaces.
- Use tabular numerals for metrics, event ids, timestamps, distances, ETA, and
  counts.
- Keep code identifiers and artifact refs visually distinct with monospace.
- Avoid oversized type except for true high-level mission titles.
- Long artifact paths, source ids, and event ids must wrap or truncate without
  breaking layout.

### Motion

- Use motion sparingly: selection, highlight, map focus, and panel transitions.
- Honor `prefers-reduced-motion`.
- Animate only `transform` and `opacity` unless there is a measured reason.
- Never make safety state changes depend on animation timing.

## Surface Direction

### `/admin/debug`: Runtime Debug Console

Purpose: help an engineer explain why Scout produced a runtime state, event,
message, bridge attempt, or skill-gate decision.

The debug console should stay dense and engineer-first. It should be optimized
for correlation, replay, and bug reports.

Core layout:

- chronological timeline as the primary navigation;
- current or selected L0-L4 snapshot;
- provider/degraded status;
- incident and bridge status;
- Ln / skill gate panel;
- outbound mock queue;
- schematic runtime map;
- boundary panel explaining read-only behavior.

Required behavior:

- All data fetches are GET-only.
- No POST, PATCH, PUT, DELETE, form submission, or runtime mutation controls.
- Timeline selection drives the details panel and runtime map highlight.
- Selected event state should be deep-linkable in the URL.
- Every event should expose copyable refs: event id, sequence, session id,
  incident ref, artifact ref, source path when available.
- Empty states should explain whether no data exists, the API is disabled, or a
  debug log path is missing.

Future improvements:

- Add an event causality drawer:
  `input -> deterministic rule -> state transition -> emitted event -> mock outbound effect`.
- Add filters by phase, severity, event kind, safety level, and outbound state.
- Add a compact bug-report export containing selected event refs and current
  boundary state.
- Add keyboard navigation for timeline and tabs.
- Replace focus styles that remove outlines with visible `:focus-visible`
  states.

Non-goals:

- Do not make `/admin/debug` a trip-planning UI.
- Do not expose live safety acknowledgements.
- Do not let debug tooling write Phase 2 Brain nodes.

### `/admin`: After-Action Review

Purpose: help a mission owner or reviewer understand what happened after a
completed mission.

The after-action surface should be map-first and evidence-led. It can retain a
technical JSON detail pane, but the primary experience should use human-readable
evidence labels and mission narrative.

Core layout:

- SVG map with route, corridor, checkpoint, segment, hazard, and event layers;
- evidence tree grouped by mission meaning, not only data type;
- selected evidence summary;
- optional raw JSON/details pane;
- filters for map layers and evidence categories.

Required behavior:

- Evidence tree selection drives map highlight by default.
- Map selection should locate the corresponding evidence node when possible.
- Completed mission evidence is immutable from this surface.
- Any next-plan output is a Phase 4 candidate, not a historical edit.
- Dense technical details should be available but not the first thing a
  non-engineer must parse.

Recommended evidence groups:

- Mission Summary.
- Route Progress.
- Checkpoints.
- Segment Capsules.
- Weak Signal / Map Evidence.
- Risk Events.
- Retreat / Backtrack Evidence.
- Recording Integrity.
- Next-Plan Candidates.

Future improvements:

- Add a "What happened?" narrative panel assembled from deterministic evidence.
- Add comparison against pre-trip plan when Phase 4 artifacts exist.
- Add reviewed lessons that export into Phase 4 as candidate artifacts.
- Add saved view links for specific evidence nodes.
- Improve mobile/tablet read mode for field debriefs.

Non-goals:

- Do not use after-action review to edit completed Phase 1 mission evidence.
- Do not automatically apply after-action lessons to a future mission.
- Do not hide provenance behind a single AI summary.

### `/admin/pretrip`: Planning Workspace

Purpose: help a trip leader assemble route, terrain, timing, map, weather,
team, and review evidence before a mission.

The pre-trip admin should behave like a project workspace, not a dashboard.
The user should understand what is ready, what is uncertain, and what still
requires human review before runtime handoff.

Core workflow:

```text
Inbox
  -> Normalized Artifacts
  -> Candidates
  -> Human Review
  -> Reviewed Package
  -> Departure Gate
  -> Runtime Handoff
```

Core layout:

- map with route, CP, segment, retreat, POI, hazard, and route-note layers;
- readiness summary focused on blockers and unresolved assumptions;
- review queue;
- CP / segment list;
- ETA, weather/daylight, terrain, resources, and remote-contact panels;
- provenance and artifact refs for every candidate;
- post-analysis tab for plan-vs-actual feedback once a mission exists.

Required behavior:

- Candidate artifacts must show source, confidence, and review state.
- Workspace write controls must be labeled as workspace-only.
- Planning actions must not imply departure approval.
- Reviewed planning package must remain distinct from runtime handoff.
- AI outputs remain `ModelInterpretation` or review artifacts until accepted.
- The UI should guide the user to unresolved blockers before exposing optional
  polish or bulk artifact browsing.

Future improvements:

- Add a top-level readiness strip:
  blockers, warnings, field-verify items, reviewed package status, departure
  gate status.
- Add source inbox with GPX, GeoJSON, article text, route images, DTM summary,
  previous field exports, and conversation notes.
- Add route-note review diffs: original source -> candidate interpretation ->
  human disposition.
- Add a phase boundary panel that explains why "reviewed package" is not the
  same as "runtime handoff".
- Add project switcher once multiple pre-trip workspaces exist.

Non-goals:

- Do not make Phase 4 a crawler-first product.
- Do not compile directly into live Phase 1 runtime without Phase 4.5 handoff.
- Do not treat community route references as ground truth.

## Common Interaction Rules

### Selection

- Selection should be shared across map, tree/list, and detail pane.
- Selecting a map feature should reveal its evidence record.
- Selecting an evidence record should highlight its map target when available.
- Selected state should survive refresh through URL query params when the
  surface is stateful.

### Filtering

- Filters should be visible, reversible, and reflected in empty states.
- Empty filtered states should explain how to recover.
- Common filters: category, severity, review state, phase, event kind, map
  layer, source type.

### Copying and References

Every technical surface should support copying:

- event id;
- source id;
- artifact path;
- session id;
- candidate ref;
- review decision id;
- runtime handoff id.

Copy actions should use specific labels such as `Copy Event ID` or `Copy
Artifact Path`.

### Errors and Loading

- Loading states should end with an ellipsis character.
- Error messages should include the next step.
- Async updates that matter should use `aria-live="polite"`.
- API-disabled and missing-fixture states should be separate messages.

## Accessibility Checklist

Use this checklist before changing any admin UI:

- Semantic landmarks exist: `header`, `main`, `section`, `nav` where useful.
- Icon-only or symbol-only buttons have `aria-label`.
- Tabs use `role="tablist"`, `role="tab"`, `role="tabpanel"`, and keyboard
  navigation.
- Interactive custom elements have keyboard handlers, or are replaced with
  native `button`/`a`.
- Focus is visible with `:focus-visible`; do not remove outlines without an
  equivalent replacement.
- Form controls have labels or `aria-label`.
- Status messages use `role="status"` and `aria-live="polite"` when updated
  asynchronously.
- SVG maps have accessible labels and do not trap keyboard focus.
- Text containers handle long source ids and artifact paths.
- `prefers-reduced-motion` is honored.
- Layout does not require horizontal scrolling on desktop.
- Dates and numbers use locale-aware formatting when rendered dynamically.

## Implementation Guardrails

### Keep the Current Architecture

The current static HTML/SVG/JavaScript pages fit Scout's fixture-backed and
low-dependency posture. Do not introduce a frontend framework just to polish
these surfaces. A framework may be justified later only if the UI state,
multi-project routing, or component reuse becomes too complex for the current
approach.

### Add Design Tokens Before Broad Restyling

Before a large visual pass, add a small shared token vocabulary in the target
page or a shared admin stylesheet:

- surfaces and borders;
- route/checkpoint/segment/retreat/hazard/POI;
- runtime state and severity;
- review state;
- phase labels;
- focus ring;
- typography and tabular numerals.

### Preserve Testable Contracts

Every UI slice should keep or add tests for:

- expected DOM ids and data attributes;
- read-only versus workspace-write boundaries;
- endpoint methods;
- map/tree/detail selection linkage;
- review state and filter behavior;
- no live `/safety/*` calls from admin planning/debug pages.

## Suggested Next Slices

1. Documented direction: this file.
2. Debug a11y hardening: visible focus, tab keyboard behavior, URL-selected
   event state.
3. After-action readability pass: mission narrative panel and JSON as secondary
   detail.
4. Pre-trip readiness strip: blockers, warnings, field-verify, reviewed
   package, departure gate.
5. Shared admin token vocabulary across the three pages.
6. Browser-based screenshot checks once the local servers for all three
   surfaces are consistently startable.

## Open Questions

- Should `/admin` eventually route to a role-aware landing surface, or should
  each surface remain directly addressable only?
- Should Scout maintain one shared admin stylesheet, or keep each static page
  self-contained until duplication becomes painful?
- Which after-action evidence types are allowed to become next-plan candidates
  in Phase 4?
- What is the first user-facing name for Phase 4.5 in the UI: "Departure Gate",
  "Runtime Handoff", or both?
- Should pre-trip planning support mobile/tablet review early, or stay desktop
  first until the workflow stabilizes?
