# Spec: Scout 2026-05-12 Field Golden Case

## Objective
Capture the first real field-exploration golden case for Scout Phase 1. The case combines two Apple Watch SensorLog recordings from 2026-05-12 with an Overpass-derived offline map context for the surrounding route network.

This golden case exists to verify that Scout can preserve real wearable telemetry, attach real map evidence, and keep weak/noisy GPS behavior visible instead of smoothing it away.

## Tech Stack
- Python `unittest` for regression tests.
- GeoJSON `FeatureCollection` for Scout offline map context.
- Overpass QL with `out tags geom` for reproducible OpenStreetMap extraction.
- Apple Watch SensorLog JSON as local field evidence.

## Commands
```bash
./venv/bin/python generate_field_golden_case.py
./venv/bin/python generate_field_phase1_fixtures.py
./venv/bin/python -m pytest tests/test_field_golden_case.py tests/test_offline_map.py -q
./venv/bin/python -m pytest tests/test_field_phase1_fixtures.py -q
./venv/bin/python -m pytest tests/test_field_replay_case.py -q
./venv/bin/python -m json.tool tests/fixtures/field_cases/scout_260512_golden.json >/dev/null
./venv/bin/python -m json.tool tests/fixtures/maps/scout_260512_overpass_map_context.geojson >/dev/null
```

## Project Structure
```text
PdrSample/
  stream Apple Watch 260512 08_52_37.json  -> local raw field evidence, not required by CI
  stream Apple Watch 260512 09_39_31.json  -> local raw field evidence, not required by CI

tests/fixtures/field_cases/
  scout_260512_golden.json                 -> versioned golden metrics and acceptance thresholds

tests/fixtures/maps/
  scout_260512_overpass_query.ql           -> reproducible Overpass query
  scout_260512_overpass_map_context.geojson -> Scout offline map context converted from Overpass output

tests/fixtures/routes/
  scout_260512_field_route.gpx             -> downsampled two-segment field route fixture
  scout_260512_085237.gpx                  -> first Watch segment route fixture
  scout_260512_093931.gpx                  -> second Watch segment route fixture

tests/fixtures/mission_graph/
  scout_260512_field_mission.json          -> MissionGraph derived from golden representative samples

tests/fixtures/mission_context/
  scout_260512_field_normal.json           -> normal field mission context for Go/No-Go loading

tests/fixtures/risk_rules/
  scout_260512_field_rules.json            -> field-specific hazard escalation rules

tests/fixtures/route_progress/
  scout_260512_field_config.json           -> field replay tolerances for real GPS/map jitter

docs/specs/
  scout-260512-field-golden.md             -> this case specification

generate_field_golden_case.py              -> reproducible metrics generator from local raw SensorLog + map context
generate_field_phase1_fixtures.py          -> reproducible Phase 1 fixture generator from the golden case
```

## Code Style
Golden-case tests should read the small manifest and map fixture, not the large raw SensorLog exports:

```python
manifest = json.loads(GOLDEN_CASE.read_text())
context = load_offline_map_context(ROOT / manifest["map_context"])
self.assertGreaterEqual(len(context.corridors), manifest["acceptance"]["min_overpass_corridors"])
```

Keep thresholds explicit in `scout_260512_golden.json` so later field-data changes are reviewed as data decisions, not hidden test rewrites.

The manifest intentionally stores more than a tiny pass/fail summary. It preserves per-segment sensor availability, horizontal-accuracy distribution, elevation and speed profile, activity counts, route-network coverage metrics, and representative sampled observations. This is still much smaller than the raw SensorLog exports, but it is detailed enough to detect accidental smoothing or map-corridor regressions.

The Phase 1 fixture generator uses the golden manifest as the control document and the local raw SensorLog files as source evidence. It emits downsampled GPX fixtures with Watch extensions preserved, then derives MissionGraph checkpoints from the golden representative samples. The combined route intentionally keeps the observed gap between the two recordings visible; it is field evidence, not a claim of continuous walking across the gap.

## Testing Strategy
- Unit-level regression tests load the golden manifest and Overpass GeoJSON.
- Tests verify map context shape, source metadata, corridor counts, and route-network coverage thresholds.
- Tests verify expanded sensor metrics and representative samples are present.
- Tests verify generated field routes, MissionGraph, mission context, and risk rules load through current Phase 1 runtime interfaces.
- Tests verify the field route can replay against Overpass map evidence as L0 when using the field route-progress config.
- Tests do not require `PdrSample/*.json` raw files, because those files are large local evidence.
- Future replay tests may opt in to raw SensorLog files when they are present locally.

## Boundaries
- Always: preserve source metadata, bbox, acceptance thresholds, and raw-file provenance.
- Always: use `BSSID` for Wi-Fi fingerprint work in future signal cases; this golden case is Watch/GPS/IMU/map only.
- Ask first: moving large raw SensorLog files into versioned test fixtures.
- Ask first: replacing the Overpass bbox or widening the query to a substantially larger region.
- Never: silently filter or smooth the second segment's weak/noisy GPS behavior out of the golden metrics.
- Never: treat the Overpass map as authoritative ground truth without preserving confidence and staleness metadata.

## Success Criteria
- The Overpass map context loads with `load_offline_map_context`.
- The golden manifest records both 2026-05-12 Apple Watch segments and the gap between them.
- The map fixture contains at least 600 corridors, including footway/path/steps coverage.
- Each segment has at least 97% sampled GPS points inside the nearest corridor after horizontal accuracy is considered.
- The second segment keeps its weaker GPS profile: p90 horizontal accuracy remains above 20m in the manifest.
- Generated Phase 1 field fixtures load with `load_gpx_route`, `load_mission_graph`, `load_mission_context`, and `load_risk_rules`.
- The generated field route replays through MissionGraph, Overpass map context, risk rules, and normal mission context as `L0_NORMAL`.
- Focused tests pass with the raw SensorLog files absent.

## Open Questions
- Should the golden case become the new default `normal_climb` mission route, or stay separate as a field-validation case?
- What corridor widths should Scout derive from OSM `highway` and trail metadata beyond the current fixture defaults?
