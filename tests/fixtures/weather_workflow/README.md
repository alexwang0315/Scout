# Weather D replay scenarios

These are synthetic qualification inputs for the user-approved Weather D1–D3
acceptance revision (2026-09-14). They are not weather observations for a real
trip, user approval to depart, or runtime safety truth. No live provider request
creates these files.

- reviewed-weather-scenarios.json preserves the original thunderstorm, heat,
  forecast-disagreement and recent-rain test conditions as separately named
  route-package scenarios. Each caller supplies the explicit replay clock
  2026-06-24T06:00:00Z.
- prepared-environment-artifacts.json contains the complete CWA/GEE inputs
  needed by the selected tools. CWA background is a synthetic low-pressure
  supporting scene; elevated retains active warning and heavier rain. Tests
  exercise both, including when stronger CWA evidence changes the aggregate
  source. GEE remains coarse corridor background, not local slope clearance.
- tests/weather_workflow_fixtures.py creates isolated missing-weather,
  reviewed-weather and reviewed-route scenarios. It copies the existing
  Chilai/Nanhua fixture when route data is required and omits Weather/environment
  assets only in that new missing scenario. It never rewrites the shared
  historical fixture.
- Complete, missing CWA, missing GEE, missing both, future acquisition, stale
  acquisition, expired forecast window and future-valid forecast cases are
  separate tests. Query-reported hazards retain their own conservative rule
  while freshness gaps remain visible.
- Execution is observed at the real deterministic tool executor. Assertions
  compare exact tool IDs, counts, statuses and returned evidence; the observer
  does not synthesize or replace tool responses. A receipt of every observed
  call is written into the temporary test directory.

Only Weather D expectations are revised here. Existing failures about additional
Pace/Terrain sources, non-Weather fixture readiness or assistant fallback
wording remain unresolved until their own approval and verification.
