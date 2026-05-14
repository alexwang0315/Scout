# Spec: Phase 1 Admin After-Action Viewer

## Objective

Build a local admin page for post-mission review of Scout Phase 1 safety evidence. The primary user is an operator or developer reviewing persisted mission artifacts after a route replay or field capture.

The page should show the route, offline Overpass-derived map corridors, mission waypoints/checkpoints, risk zones, safety transitions, Ln trigger evidence, segment capsules, and incident packages in one inspectable map view. Mouse hover and selection should reveal details without requiring the reviewer to open raw JSON files manually.

This is not a live navigation UI. It is an evidence viewer for "what happened, where, why did Scout raise L1/L2/Ln, and what evidence supported that decision?"

This page can later become part of the Phase 4 Pre-Trip Planning Admin flow.
The intended evolution is not to let the after-action page edit historical
Phase 1 evidence. It is to let a reviewer select evidence from a completed
mission and export reviewed planning lessons or candidates for the next route.
For example, a weak-GPS section, stale Overpass corridor, missed checkpoint, or
useful retreat point can become a candidate checkpoint, hazard note, route
segment requirement, recording policy adjustment, or POI for a future
`PreTripPackage`.

## Assumptions

1. The first implementation is local/dev admin only, served by the existing FastAPI app or opened through a local dev server.
2. Input data comes from existing versioned or persisted artifacts:
   - `tests/fixtures/field_cases/scout_260512_golden.json`
   - `tests/fixtures/routes/scout_260512_field_route.gpx`
   - `tests/fixtures/maps/scout_260512_overpass_map_context.geojson`
   - `tests/fixtures/mission_graph/scout_260512_field_mission.json`
   - `tests/fixtures/risk_rules/scout_260512_field_rules.json`
   - persisted incident packages under the configured incident store when available.
3. The map is evidence, not absolute truth. The UI should display map confidence/staleness where available and should not present Overpass corridors as unquestionable ground truth.
4. Phase 1 can avoid adding a heavy frontend framework. A plain HTML/CSS/JS admin page is enough unless later interaction complexity proves otherwise.

## Tech Stack

- FastAPI for read-only admin data endpoints.
- Plain HTML/CSS/JavaScript for the admin page.
- SVG or Canvas map rendering for first slice.
- No new map SDK dependency in the first slice.
- Existing Python parsers:
  - `load_gpx_route`
  - `load_mission_graph`
  - `load_offline_map_context`
  - `load_risk_rules`
  - `IncidentStore`

## Commands

```bash
SCOUT_SAFETY_MISSION_GRAPH=tests/fixtures/mission_graph/scout_260512_field_mission.json \
  ./venv/bin/python -m uvicorn server:app --reload --port 9099

./venv/bin/python -m pytest tests/test_admin_after_action.py -q
./venv/bin/python -m pytest tests -q
```

## Project Structure

```text
admin_after_action.py
  Read-only artifact loading and view-model generation.

safety_api.py or admin_api.py
  FastAPI routes for admin fixture/case data.

docs/admin/phase1-after-action.html
  Local admin viewer UI.

tests/test_admin_after_action.py
  View-model and API contract tests.

docs/specs/phase-1-admin-after-action-viewer.md
  This spec.
```

## Data Model

The admin page should consume a normalized view model rather than raw scattered files:

```json
{
  "case_id": "scout_260512_field_golden",
  "mission": {"mission_id": "...", "checkpoints": [], "segments": []},
  "route": {"points": [], "bounds": {}},
  "map": {"corridors": [], "hazards": [], "pois": [], "metadata": {}},
  "risk_rules": [],
  "safety_timeline": [],
  "segment_capsules": [],
  "incident_packages": []
}
```

Each visual item should include `source_path` or `source_id` so the reviewer can trace UI evidence back to the persisted artifact.

## UI Requirements

- Map pane:
  - route polyline
  - offline map corridors from Overpass-derived GeoJSON
  - checkpoints / waypoints
  - risk zones / hazards if present
  - incident trigger points and Ln transition points
- Timeline pane:
  - safety level changes
  - route deviation / weak GPS / backtracking / hazard evidence
  - checkpoint arrivals
  - segment capsule boundaries
- Details pane:
  - hover: compact detail for nearest visual item
  - click: pinned full detail with JSON source reference
- Filters:
  - route
  - map corridors
  - checkpoints
  - hazards
  - Ln events
  - incident packages
- Evidence stance:
  - distinguish `map evidence`, `device observation`, `runtime decision`, and `incident package`.
  - show confidence/staleness when available.

## Code Style

Keep the Python side boring: one loader builds one view model, endpoints only serialize it.

```python
def build_admin_case_view(case_id: str, *, root: Path = ROOT) -> dict[str, Any]:
    artifacts = resolve_admin_case_artifacts(case_id, root=root)
    route = load_gpx_route(artifacts.route_path)
    mission = load_mission_graph(artifacts.mission_graph_path)
    map_context = load_offline_map_context(artifacts.map_context_path)
    return AdminCaseView.from_artifacts(route, mission, map_context, artifacts).model_dump(mode="json")
```

## Testing Strategy

- Unit tests:
  - view model loads the 260512 field case.
  - route bounds and point count are non-empty.
  - checkpoints and route segments match MissionGraph.
  - Overpass corridors appear in the map layer.
  - every visual layer item has a source reference.
- API tests:
  - `GET /admin/cases/scout_260512_field_golden` returns a stable JSON contract.
  - unknown case returns 404.
- Manual UI verification:
  - open the admin page.
  - route, corridors, checkpoints, and layer toggles render.
  - hover/click shows item detail.

## Boundaries

- Always:
  - keep admin APIs read-only.
  - preserve source references for every rendered evidence object.
  - show map confidence/staleness metadata.
  - keep raw field SensorLog files out of CI requirements.
- Ask first:
  - adding Leaflet/MapLibre or another frontend dependency.
  - adding authentication.
  - storing uploaded admin cases in the repo.
  - changing persisted incident package schema.
- Never:
  - let the admin page modify mission graph, risk rules, or incident packages in Phase 1.
  - hide weak/noisy GPS evidence to make the path look cleaner.
  - present Overpass data as guaranteed current trail truth.
  - apply after-action findings directly to a future mission without explicit human review.

## Success Criteria

- A reviewer can open one admin page and visually inspect the 260512 field route over the offline map context.
- Hovering or selecting route points, checkpoints, corridors, and safety events shows meaningful detail.
- The UI can explain why an L1/L2/Ln event exists by linking it to map/device/runtime evidence.
- Tests validate the admin data view model and read-only API contract.
- Existing Phase 1 tests continue to pass.

## Future Phase 4 Integration

The Phase 4 integration target is an export boundary:

```text
after-action evidence selection
  -> next-plan candidate export
  -> Phase 4 PreTripPackage draft
  -> human review
  -> future MissionGraph compile
```

Candidate exports should reference the original case id, source paths,
artifact ids, map evidence ids, checkpoint ids, segment ids, segment capsule
ids, incident ids, and reviewer notes. They may include proposed changes, but
they must not mutate the completed mission or produce live safety decisions.

## Open Questions

- Should first UI render use SVG/Canvas projection, or should we add Leaflet/MapLibre for better map interaction?
- Should the admin page load only the latest configured mission, or support a case selector from multiple persisted runs?
- Should incident package raw samples be shown directly, summarized, or both?
- Do we want this page inside `server.py` now, or as a standalone static artifact until admin auth exists?
- Which after-action evidence types should be exportable as Phase 4 next-plan
  candidates first: checkpoints, hazards, route segments, POIs, recording
  policies, or skill config?
