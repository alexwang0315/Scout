# Scout Dashboard MapLibre pre-migration qualification boundary freeze

Status: active regression guard, not Dashboard productization
Effective date: 2026-08-21
Default scope: `guard`

This boundary keeps the current Dashboard usable while MapLibre is introduced. It does not certify the legacy SVG/iframe renderer as the long-term map architecture, and it does not expand product, terrain, preparation, safety, QGIS, or GRASS behavior.

## 2026-08-21 MapLibre construction addendum

Prototype status: `WORKING PROTOTYPE`

Qualification status: focused construction/browser qualification only; `official_qualification_eligible=false`. The historical 9099 guard packet below remains the pre-migration baseline and was not replaced by this development run. A final read-only 9099 smoke was performed, but the long-running process was deliberately not restarted.

The bounded migration now has these executable surfaces:

- Pre-trip Planning defaults to the shared MapLibre renderer when WebGL and the pinned module are available.
- Runtime Debug uses the same renderer, evidence identity, layer visibility, focus, fit, zoom, pan, raster status, and failure semantics.
- Dashboard Navigation retains its existing MapLibre 2D/3D terrain workbench and can add QGIS candidate GeoJSON through the shared adapter.
- `mapRenderer=svg`, WebGL unavailability, module-load failure, and renderer failure retain the existing SVG map as a fail-closed fallback.
- Active MapLibre updates no longer redraw the hidden full SVG. The SVG is rendered before activation and force-refreshed from current evidence only when fallback is selected or needed.
- SVG code is intentionally retained for reversibility; it is no longer the default renderer on the migrated Pre-trip and Debug surfaces.

Browser evidence from ephemeral local development runtimes:

| Runtime | State exercised | Result |
| --- | --- | --- |
| `127.0.0.1:9111` | Pre-trip and Debug MapLibre, desktop/mobile, raster toggle, evidence focus, SVG fallback | MapLibre ready; no horizontal overflow; candidate evidence identity preserved. |
| `127.0.0.1:9112` | QGIS fixture connected | Three MapLibre canvases (terrain 2D, terrain 3D, QGIS candidate), rendered fixture evidence, review pending. Fixture is synthetic and non-runtime. |
| `127.0.0.1:9113` | QGIS disabled with the same workspace-backed terrain project | Dashboard and both terrain MapLibre views remained ready; QGIS execution stayed disabled. |
| `127.0.0.1:9114` | QGIS configured with an unreachable localhost worker | Typed `UNAVAILABLE`; both terrain MapLibre views remained ready; QGIS execution stayed disabled. |
| `127.0.0.1:9099` | Existing long-running Dashboard, no restart | Existing terrain 2D/3D MapLibre remained ready at desktop/mobile with QGIS disabled and no overflow. The newly registered shared-adapter route returned 404 because this process predates the route; Pre-trip failed closed to a visible SVG map. |

Observed browser checks:

- Pre-trip mobile canvas: 367 x 284 CSS px at a 390 x 844 viewport, with zero document/body overflow.
- Debug mobile canvas: 350 x 260 CSS px; desktop canvas: 624 x 693 CSS px; both nonblank.
- QGIS candidate mobile canvas: 362 x 360 CSS px; rendered visual-evidence image: 362 x 202 CSS px.
- A 4x CPU-throttled desktop development trace observed LCP 674 ms and CLS 0.00. This is not Raspberry Pi performance evidence.
- A Timeline/feature selection resolved `cp.050`, updated the inspector, highlighted the stable MapLibre feature identity, and changed map center.
- A delayed raster event could not overwrite a hidden layer: OSM remained `hidden` after disable and returned to `available` after enable.
- Pre-trip and Debug hidden SVG payloads remained untouched during active MapLibre updates; an explicit force refresh still rebuilt them for fallback.
- Focused contract/API/page suite: 270 passed, 0 failed, 0 skipped in 176.16 seconds. JUnit: `artifacts/maplibre-migration/step-11/focused-pytest.xml`.
- Deterministic canonical layer verifier: `PASS: Scout layer contract (32 layers)`.

Authority invariants remain unchanged:

- `candidate_only=true`
- `runtime_safety_truth=false`
- `operational=false`
- Map rendering or GIS processing success is evidence of execution, not geographic or safety truth.
- The browser does not connect directly to QGIS MCP, and no arbitrary Python or shell capability is exposed.

Open promotion debt:

- MapLibre JS/CSS currently use a pinned `unpkg.com` URL. Offline/Pi deployment requires reviewed local vendoring or packaging; until then, an unavailable module degrades to SVG.
- No Raspberry Pi hardware benchmark, thermal/memory soak, offline tile-package qualification, or long-duration browser run was performed.
- No real QGIS/QGIS MCP process was available. QGIS browser evidence in this run is fixture/synthetic/non-runtime.
- Several canonical controls remain renderer-compatible boundaries while v0.1 exposes only the bounded vector plus Rudy/OSM raster slice.
- Independent review and a trusted 9099 runtime attestation are still required for official Dashboard qualification.
- The existing 9099 process must receive a controlled restart/deployment before `/admin/scout-maplibre-evidence.js` and the migrated Pre-trip/Debug MapLibre path can be qualified there. It was not restarted during this construction run.

## Preserved checks

| Check | Guard evidence | Blocking interpretation |
| --- | --- | --- |
| Dashboard load | A pre-existing live runtime must return the real Scout Dashboard and keep the same listener PID and Dashboard HTML identity for the round. | Failure is an `existing_regression` or `environment_limitation`, depending on runtime continuity. |
| Major route entry | Browser operation enters `home`, `map`, `timeline`, `outdoor-navigation`, and `diagnostic`. | A route that cannot be entered is an `existing_regression`; this is not exhaustive route qualification. |
| Current fallback map usable | A visible renderer surface has a usable `bbox` on desktop and large-mobile. The adapter accepts either the current iframe fallback or a same-document renderer. | Missing renderer or unusable bounds are a `maplibre_migration_blocker`. |
| Layer contract present | Runtime layer IDs must retain the canonical pre-trip layer contract. One available representative layer control is toggled and restored. | Missing IDs are a `maplibre_migration_blocker`; failure to change or restore a control is an `existing_regression`. |
| Evidence identity retained | A selected Timeline Evidence item retains its `selected_evidence`, `artifact_id`, and selected `highlight_state` in the map evidence rail. | Identity loss is a `maplibre_migration_blocker`. Disclosure-widget timing is not itself part of the map contract. |
| Browser fatal-error guard | Page errors and fatal console errors are absent during the guard. | A fatal error is an `existing_regression`. |
| Horizontal overflow guard | Document and body widths stay within the viewport for every guarded route at 1440 px and 390 px. | Overflow is an `existing_regression`. |
| Authority guard | The browser harness blocks mutation requests, observes zero POST requests, and never claims runtime safety truth or operational authority. | Any new authority or mutation request is blocking. Candidate evidence remains candidate-only. |
| Timeline/evidence rail continuity | Timeline groups load, a real evidence item can be selected, and the map evidence rail can resolve the same identity. | Missing identity is blocking; exhaustive content/UX review is not included. |

## Paused checks

The following checks remain available only through an explicit `legacy-full` scope and do not block the MapLibre pre-migration guard:

- exhaustive navigation of every Dashboard route;
- every visible control and every embedded-frame control;
- full-page visual qualification for every route and every operation;
- all nine legacy map surfaces;
- the legacy gesture matrix: fit, zoom in, zoom out, mouse pan, keyboard pan, and rectangle zoom;
- toggling every exposed layer control;
- detailed dynamic Rudy/TW tile behavior;
- SVG path, point, line, polygon, and implementation-specific DOM assertions;
- old iframe/SVG-specific rendering and interaction details.

Paused checks are retained for bounded legacy investigation only. They are not a MapLibre acceptance contract and must not be expanded as long-term product tests.

## Changed checks

- The capability manifest and browser action contract use a MapLibre pre-migration boundary with `active`, `paused`, and `outside_boundary` qualification states.
- `npm run qualification:check`, CI, and the Python orchestrator default to `guard`. Legacy execution requires the explicit `legacy-full` scope.
- The guard operates five major routes in a real browser at desktop and large-mobile viewports rather than claiming all-route coverage.
- Map evidence uses renderer-neutral identities: `map_feature`, `layer_id`, `artifact_id`, `bbox`, `highlight_state`, and `selected_evidence`.
- The map adapter accepts both the current iframe fallback and a future same-document renderer; SVG path selectors are not part of the guard.
- Layer verification checks the canonical ID set plus one toggle-and-restore operation instead of exercising every old layer control.
- The machine evaluator blocks only `active` capabilities in `guard`/`smoke`; `paused` capabilities re-enter only under `legacy-full`, while `outside_boundary` capabilities remain non-blocking.
- Browser failures are classified as `existing_regression`, `maplibre_migration_blocker`, `old_svg_implementation_detail`, `unrelated_dirty_worktree_issue`, or `environment_limitation` before any product repair is considered.
- Wrapper-prepared evidence roots use a strict allowlist. An evidence root containing prior browser results is still rejected.

## Intentionally not covered

- Dashboard productization, release readiness, or full acceptance;
- Dashboard, Terrain Intelligence, importer, or pre-trip preparation refactors;
- changes to Scout safety semantics, permission authority, or runtime safety truth;
- QGIS or GRASS feature introduction, workflow qualification, or visual-artifact acceptance;
- exhaustive Diagnostic question execution;
- Permission, Weather, Navigation, Route Context, hardware readiness, or API workflow qualification beyond entering the guarded route;
- every future MapLibre gesture, style, source, tile request, popup, label, or feature-selection behavior;
- performance, long-duration stability, offline behavior, accessibility, or full UX product review;
- every layer's data completeness, semantic correctness, or visual quality;
- automatic repair of failures discovered by this guard.

## MapLibre migration assumptions

- MapLibre may replace the current iframe/SVG implementation without preserving legacy DOM structure.
- The new renderer will expose or adapt to a visible map surface, a usable `bbox`, canonical `layer_id` values, and a representative layer toggle/restore operation.
- Timeline-to-map continuity will preserve stable `artifact_id` and `selected_evidence` identities plus a selected `highlight_state`.
- Layer identity remains sourced from the machine-readable Scout layer contract, not copied into renderer-specific test code.
- Renderer replacement does not grant operational or safety authority and cannot promote candidate evidence to runtime safety truth.
- New MapLibre behaviors receive focused tests when their contracts exist; they are not inferred from legacy SVG behavior.

## Remaining risks from the pre-migration guard

- The guard currently proves one live project (`chilai_nanhua_day1_scoutAI`) at two viewports; other projects and viewport classes may differ.
- The historical 9099 runtime below used the legacy fallback renderer. The current development slice has live same-document MapLibre proof; a focused 9099 smoke confirmed existing Dashboard terrain maps and SVG degradation, but the trusted guard has not been rerun after a controlled restart.
- The renderer still exposes 31 canonical pre-trip layer controls. The focused run proves identity presence and representative toggles, not completeness or quality of every layer's data.
- A mobile run observed one transient map-loading overlay that blocked a layer-control click and was classified as `environment_limitation`; an immediate bounded retry passed. This remains a reliability signal, not a confirmed product defect.
- Visual checkpoints can surface observations outside this boundary. For example, Navigation/QGIS candidate-state text may be flagged for readability, but QGIS and full UX qualification are intentionally deferred.
- Full legacy checks may drift while paused. They must not silently become MapLibre blockers; they should be revised or retired when the MapLibre evidence surface is defined.
- Independent GPT Pro review remains required before the run can receive a final human-reviewed qualification disposition.

## Historical pre-migration executable evidence

- Canonical live guard packet: `artifacts/qualification/runs/20260821-maplibre-boundary-freeze-live-r8`
- Evidence root SHA-256: `f7e29ae803b96a6e2d6cf20105008351f3eac7817e2b9487201b084595ef9e0c`
- Runtime: pre-existing `http://127.0.0.1:9099`, listener PID `2606`
- Live cases: desktop PASS, large-mobile PASS
- Active capabilities: regression guard PASS, deterministic baseline PASS, evidence integrity PASS
- Machine evaluation: PASS, zero active blockers
- Independent GPT Pro bounded review: PASS, zero evidence conflicts or open human gates
- Transient-environment evidence: `artifacts/qualification/runs/20260821-maplibre-boundary-freeze-live-r7`
- Bounded mobile retry evidence: `artifacts/qualification/runs/20260821-maplibre-boundary-freeze-live-r7-mobile-retry1`

The executable evidence proves a pre-migration regression guard only. It does not certify Dashboard productization or MapLibre readiness.
