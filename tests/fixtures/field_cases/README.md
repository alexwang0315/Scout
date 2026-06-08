# Field Cases

This directory stores versioned wilderness exploration cases that ground Scout system specifications and feature design.

Field cases are not only unit-test fixtures. They preserve real or realistic evidence about terrain, route progress, wearable telemetry, map context, signal quality, timing gaps, and safety-relevant human behavior. Specs and feature changes should use these cases as reference evidence before introducing new assumptions.

## What Belongs Here

- Small golden manifests with reproducible metrics, thresholds, provenance, and acceptance criteria.
- Pointers to supporting map, route, mission, risk-rule, and replay fixtures.
- Summaries of real-world ambiguity such as GPS drift, route gaps, weak signal, delayed response, or uncertain trail geometry.

## What Stays Elsewhere

- Small Scout-readable map fixtures belong in `tests/fixtures/maps/`.
- Derived route fixtures belong in `tests/fixtures/routes/`.
- Mission graphs, mission context, risk rules, and route-progress configs belong in their matching `tests/fixtures/` subdirectories.
- Large raw SensorLog, map, or media captures should stay out of normal test fixtures unless explicitly approved.

## Design Use

Use field cases when evaluating changes to:

- mission planning and checkpoint selection;
- route matching and route-progress semantics;
- alert escalation and incident package evidence;
- admin after-action review behavior;
- future wearable, map, radio, Wi-Fi, or environmental sensor integrations.

Every new field case should include a matching spec under `docs/specs/` and enough provenance for later reviewers to understand why the case matters.
