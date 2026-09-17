# Scout TRH Narrative Guidance Completion Audit

Date: 2026-09-02

Mode: working prototype, candidate-only terrain evidence

## Authority boundary

Every plan, review, execution plan, hypothesis, explanation, failure, and
Dashboard projection remains:

```text
authority=candidate_only
source_type=terrain_hypothesis (R4 output) or historical_route (input evidence)
runtime_safety_truth=false
operational=false
safe_or_walkable=not_determined
```

Scout AI does not select map anchors, promote historical prose, modify GPX,
write official-trail or safety truth, or authorize movement.

## Work-package audit

| # | Work package | Status | Executable evidence |
|---:|---|---|---|
| 1 | Authority contract | PROVEN | Typed literals and promotion guards cover plan through R4 output; authority tests reject unsafe labels and truth mutation. |
| 2 | Typed guidance models | PROVEN | Source spans, constraints, conflicts, unknowns, resolution, review decisions, anchors, cost modifiers, and execution plan are strict Pydantic models. |
| 3 | Scout Pydantic AI specialist | PROVEN | Dedicated provider/agent and read-only `terrain_narrative_guidance.interpret` tool emit typed preview only. Prompt-injection tests preserve authority. |
| 4 | Deterministic constraint validator | PROVEN | Constraint order, required anchors, candidate membership, review decisions, hashes, CRS, finite values, modifier order, and promotional text fail closed. |
| 5 | Terrain spatial resolver | PROVEN | Bounded A/B feature clipping, DEM elevation sampling, saddle proxies, ridge/valley/drainage candidates, and optional corridor overlap ranking are implemented and tested. |
| 6 | Dashboard constraint preview | PROVEN | Text input, source metadata, typed preview, unknown/conflict states, rank markers, and refresh-safe workspace recovery are covered by static/API/browser tests. |
| 7 | Map anchor confirmation | IMPLEMENTED; REAL REVIEW PENDING | Only explicit human WGS84 Points can unlock R4. Review v0.2 records AI selection as none and preserves each human selection/disable decision. Real G1/G6/G7/G11 points still require a person. |
| 8 | R4 guidance cost compiler | PROVEN ON MAC | One bounded local modifier per reviewed anchor; allowlisted expression; 20-500 m radius; 0.5-1 multiplier; R1-R3 unchanged. Real GRASS smoke changed 3.4 to 2.652 at a 0.78 anchor. |
| 9 | Ordered GRASS route execution | PROVEN IN WORKER HARNESS; REAL R4 PENDING | R4 executes A to anchors to B with one `r.walk`/`r.path` pair per segment and no straight-line fallback. Full real path waits for human points. |
| 10 | Backend/API integration | PROVEN | Guidance selection is hash-bound through Admin API, QGIS backend, worker request, atomic artifacts, and Navigation projection. |
| 11 | Scout AI tool registry | PROVEN | Generate, explain, compare, consistency inspect, and narrative interpretation are narrow registered tools. R4 explanation now reports anchor alignment/conflict without route recommendation. |
| 12 | Provenance, cache, and tests | PROVEN FOR LOCAL MACHINE PATH; SCOUT R4 PENDING | DEM/review/model/module hashes and manifests are persisted; guidance invalidates cost/route cache only; focused deterministic/failure tests pass. Scout host is currently out of network range. |

## Real GRASS modifier smoke

- Runtime: QGIS-LTR Processing with GRASS 8.5.0 on macOS.
- Input raster SHA-256:
  `31324ea68d639784283ac2b6490805a614a16419f989cd61768e3acc9d428d28`.
- Output raster SHA-256:
  `29b56e51b619422e7177401f7b4e34304d17ace46e7acb2f15058d68e73311f7`.
- Grid: 234 by 147, 20 m, EPSG:3826.
- Valid pixels: 100 percent.
- Input anchor friction: `3.4`.
- Reviewed ridge multiplier: `0.78`.
- Output anchor friction: `2.652`.
- Output range: `2.0-31.0`, finite and positive.

The smoke proves expression execution and bounded raster behavior. It does not
prove the historical point, route geometry, trail existence, passage, safety,
or legal access.

## Verification results

- `489 passed` in the expanded affected-surface suite covering Admin API,
  pretrip import, workspace clone, MapLibre projection, Navigation, QGIS bridge
  and worker, host parity, Scout AI tools, guidance, consistency, Dashboard, and
  documentation contracts.
- A separate cross-layer TRH slice completed `296 passed`.
- Ruff reported no issues for the changed Python surface.
- Live Dashboard smoke used
  `dongqing_batongguan_historic_trail_qgisGrass_clean_20260828` on port 9099.
  Both 2D and 3D states rendered one 588 by 860 backing canvas at a 294 by 430
  CSS size, showed no visible MapLibre/WebGL error, and retained the explicit
  candidate-only label.
- Human review and R4 generation remained disabled because no human Point
  anchors have been saved. The smoke did not click or synthesize those points.

## Milestones

| Milestone | Status |
|---|---|
| M1 narrative to typed constraints | PROVEN |
| M2 Dashboard preview and human review gate | PROVEN; real point choices pending |
| M3 reviewed R4 compiler and ordered worker execution | PROVEN in unit/worker harness plus real raster smoke; full real R4 pending |
| M4 Scout AI explanation of alignment/conflicts | PROVEN |
| M5 Mac/Scout reproducibility | PROVEN for unguided R1-R3; R4 parity pending Scout connectivity and the same reviewed plan |

## Remaining UNKNOWN

- The correct real map locations for G1, G6, G7, and G11.
- Whether the historical wording corresponds to today's terrain or route.
- Vegetation and trail-surface state.
- Meter-scale microterrain hidden by the 20 m DEM.
- Current water and drainage conditions.
- Recent landslide or collapse.
- Engineered bridges, ropes, ladders, stairs, retaining works, or tunnels.
- Legal access, permits, closure, ownership, and permission.
- Full reviewed R4 equivalence on the Scout host while it is out of network range.

These remain UNKNOWN until independent evidence or human review exists; no
candidate geometry is allowed to fill them in.
