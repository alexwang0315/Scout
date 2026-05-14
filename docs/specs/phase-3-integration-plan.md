# Plan: Phase 3 Integration and Operations

## Goal

Phase 3 turns the completed Phase 1 safety black box and Phase 2 file-backed
Brain into an operational system without weakening the safety boundary.

Phase 1 remains the live deterministic safety baseline. Phase 2 remains the
evidence, replay, remote status, decision-support, and audit layer. Phase 3
adds the operational bridge, fixture coverage, admin workflows, and release
gates needed to run both phases together.

## Non-Goals

- Do not let Phase 2 decide, downgrade, or block L3/L4 emergency escalation.
- Do not call Phase 2 from `/safety/observations`, `/safety/ack`,
  `/safety/incidents/{incident_id}`, `/pdr/update`, route-progress evaluation,
  map evidence, recording policy, or risk rules.
- Do not turn model output into `ObservedFact`.
- Do not require a graph database, cloud transport, live radio hardware, drone
  control, or production mobile UI for Phase 3 acceptance.
- Do not rewrite persisted Phase 1 incident packages to satisfy Phase 2.

## Current Inputs

Phase 1 currently provides:

- route-aware mission planning;
- checkpoint sealing and segment capsules;
- L0-L4 safety state transitions;
- route progress and offline map evidence;
- incident packages with raw-window metadata and `ai_summary_input`;
- ack/reack and after-action admin surfaces;
- field golden fixtures and deterministic replay tests.

Phase 2 currently provides:

- file-backed Brain models and store;
- automatic writeback policy limited to `ObservedFact` and deterministic
  `DerivedMeasurement`;
- fixture-backed Phase 1 evidence adapter;
- manual Phase 1 incident import CLI;
- artifact manifest and admin preview surfacing for adapter evidence;
- skill registry, skill runs, remote status JSON, option sets, beacon mock, and
  case replay;
- release checker and focused regression matrix.

## Integration Principle

The integration path is one-way:

```text
Phase 1 live safety decision
  -> persisted IncidentPackage JSON
  -> Phase 1 to Phase 2 adapter
  -> Phase 2 Brain nodes
  -> replay, remote status, options, admin, manifest, review
```

Phase 2 may explain, summarize, replay, and support decisions after evidence is
persisted. Phase 2 must not become an input to Phase 1 escalation.

## Milestone 1: Post-Persistence Incident Bridge

Goal: add a disabled-by-default live bridge that imports persisted incident
packages into a Phase 2 Brain store after Phase 1 persistence succeeds.

Status: first implementation slice complete.

Implemented:

- `Phase1IncidentBridge` is disabled by default and enabled only through
  explicit server env configuration.
- `SafetyRuntimeSession` invokes the bridge only after an `IncidentStore`
  write has returned a persisted path.
- bridge import uses `phase1_phase2_adapter.py` and writes only adapter output.
- bridge failures are logged and swallowed so Phase 1 incident persistence,
  escalation state, and response payload construction continue.
- focused tests cover disabled default, idempotent repeated import,
  persistence-failure isolation, post-persistence runtime import, and no direct
  bridge call from `/safety/observations` or `/pdr/update`.

Remaining:

- broaden the incident fixture matrix before claiming complete Phase 3 release
  coverage.
- add read-only admin after-action surfacing for the new fixture classes.

Acceptance:

- bridge is off by default; done in first slice.
- bridge runs only after `IncidentStore` persistence succeeds; done in first
  slice.
- bridge failure is logged and does not change Phase 1 response payload,
  escalation state, incident ids, or persisted package JSON;
- importing the same incident twice is idempotent; done in first slice.
- malformed or incompatible packages fail without corrupting the Brain store;
- bridge uses existing `phase1_phase2_adapter.py` behavior instead of adding new
  evidence semantics; done in first slice.

Suggested files:

- `phase1_incident_bridge.py`
- `tests/test_phase1_incident_bridge.py`
- small env/config parsing near the existing safety runtime composition point
- optional release-check registration after the slice is stable

Verification:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_phase1_phase2_adapter.py tests/test_phase1_incident_bridge.py
```

## Milestone 2: Incident Fixture Matrix

Goal: expand fixture coverage so Phase 2 can simulate and inspect multiple
Phase 1 safety outcomes.

Status: complete for Phase 3 release gate.

Implemented:

- versioned offline fixtures cover missed checkpoint, weak GPS/PDR fallback,
  backtracking loop, steep slope/map hazard, resource constraint, unsafe
  continuation, sensor anomaly, and multiple incidents in one mission;
- `tests/test_phase1_adapter_fixture_matrix.py` verifies every fixture loads
  without live server imports, adapts deterministically, persists idempotently,
  and avoids `ModelInterpretation` automatic writes;
- admin preview and artifact manifest tests glob the fixture matrix and verify
  grouped Phase 1 adapter evidence by incident id.

Add incident package fixtures for:

- `missed_checkpoint`;
- `weak_gps` with PDR fallback;
- `backtracking_loop`;
- `steep_slope` or `map_hazard`;
- `resource_constraint`;
- `unsafe_continuation`;
- `sensor_anomaly`;
- multiple incidents in one mission.

Each fixture should include stable ids for:

- incident id;
- trigger event;
- route and checkpoint evidence;
- raw-window metadata;
- map evidence when relevant;
- segment capsule refs;
- safety transitions;
- optional ack/check-in evidence.

Acceptance:

- every fixture loads without starting the live app server;
- adapter output has artifact provenance for every automatic fact and
  measurement;
- artifact manifest and admin preview can surface every fixture type;
- no fixture requires local-only `PdrSample/*` files unless a derived, versioned
  fixture is explicitly created.

Suggested files:

- `tests/fixtures/phase2/phase1_adapter/*.json`
- `tests/test_phase1_phase2_adapter.py`
- `tests/test_phase2_artifact_manifest.py`
- `tests/test_phase2_admin_preview.py`

## Milestone 3: Phase 2 Decision-Support Replay Matrix

Goal: prove Phase 2 support outputs remain bounded across realistic operational
scenarios.

Status: complete for Phase 3 release gate.

Implemented:

- existing ridge and forest team replay fixtures cover possible separation and
  stale-but-not-separated remote status;
- ridge decision options now include hold, turn back, wait/rest/reassess,
  rendezvous beacon trend, notify remote contact, and continue with degraded
  confidence;
- `tests/test_phase3_decision_support_matrix.py` verifies support outputs are
  fixture-backed, manual/policy-gated, and do not claim guaranteed outcomes.

Add or extend fixtures for:

- team separation that later resolves;
- stale member status that does not become a separation event;
- leader and member checkpoint disagreement;
- partial remote contact visibility;
- turn-back option;
- wait/rest/reassess option;
- rendezvous beacon option;
- notify remote contact option;
- continue with degraded confidence option.

Acceptance:

- decision options do not read from live Phase 1 state;
- option sets remain explicit/manual write or policy-gated;
- remote status remains concise and low-noise;
- case replay verdicts remain bounded and avoid guaranteed outcome claims.

Suggested files:

- `tests/fixtures/phase2/team_replay/*.json`
- `tests/fixtures/phase2/cases/*.json`
- `tests/test_phase2_option_replay.py`
- `tests/test_phase2_case_replay.py`
- `tests/test_phase2_team_replay_second_fixture.py`

## Milestone 4: Unified Admin After-Action Workflow

Goal: let reviewers inspect Phase 1 evidence and Phase 2 support outputs in one
workflow without creating write paths into Phase 1 runtime.

Status: complete for Phase 3 release gate.

Implemented:

- Phase 2 admin preview surfaces imported Phase 1 adapter evidence read-only;
- artifact manifest groups Phase 1 adapter evidence by incident id;
- tests persist the expanded fixture matrix into a Brain store and verify
  preview/manifest construction does not mutate stored nodes;
- Phase 1 SVG after-action viewer remains a separate surface.

Acceptance:

- Phase 1 after-action evidence remains available as SVG-linked evidence;
- Phase 2 admin preview includes imported Phase 1 adapter evidence;
- artifact manifest includes Phase 1 adapter evidence sections;
- admin API remains read-only;
- selected evidence can be traced back to persisted artifacts or Brain refs.

Suggested files:

- `phase2_admin_preview.py`
- `phase2_admin_api.py`
- `docs/admin/phase1-after-action.html`
- `docs/architecture/phase-1-2-architecture.html`
- `tests/test_phase2_admin_preview.py`
- `tests/test_phase2_admin_api.py`
- `tests/test_admin_after_action.py`

## Milestone 5: Operational Release Gate

Goal: make Phase 1 + 2 integration releasable with one documented acceptance
path.

Status: complete for Phase 3 release gate.

Implemented:

- `phase2_release_check.py` verifies Phase 3 docs, bridge modules, bridge tests,
  focused tests, and fixture-matrix scenario coverage;
- release check now passes with the versioned Phase 3 fixture matrix;
- focused Phase 3 tests cover bridge failure isolation, fixture matrix,
  admin/manifest read-only surfacing, decision-support replay, and release
  gates.

Acceptance:

- focused Phase 3 tests are listed in release docs;
- `phase2_release_check.py` verifies required Phase 3 docs, bridge, fixtures,
  and tests after they exist;
- full pytest remains green;
- release checklist explicitly excludes local-only raw files unless promoted to
  versioned fixtures;
- failure-isolation tests prove Phase 2 cannot block Phase 1 safety behavior.

Suggested files:

- `phase2_release_check.py`
- `tests/test_phase2_release_check.py`
- `docs/specs/phase-2-release-checklist.md`
- `docs/specs/phase-2-release-notes.md`
- `README.md`

Verification:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest
/Users/alexwang0315/scout-fusion/venv/bin/python phase2_release_check.py --repo-root /Users/alexwang0315/scout-fusion
```

Focused gate verification:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_phase2_release_check.py
```

Focused Phase 3 verification:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest \
  tests/test_phase1_incident_bridge.py \
  tests/test_phase1_phase2_adapter.py \
  tests/test_phase1_adapter_fixture_matrix.py \
  tests/test_phase2_import_phase1_incident_cli.py \
  tests/test_phase2_admin_preview.py \
  tests/test_phase2_artifact_manifest.py \
  tests/test_phase3_decision_support_matrix.py \
  tests/test_phase2_release_check.py
```

Latest known focused Phase 3 result:
`50 passed, 1 warning in 114.31s`.

Latest known full repository regression:
`274 passed, 1 warning in 388.29s`.

## Parallel Work Opportunities

These can proceed in parallel:

- additional Phase 1 adapter fixtures;
- admin preview refinements over already persisted Brain nodes;
- artifact manifest coverage for new fixture classes;
- case replay scenarios and bounded verdict checks;
- documentation and architecture diagrams.

These should remain sequential:

- live bridge design before live bridge implementation;
- bridge implementation before background scanning;
- fixture matrix before claiming Phase 3 release coverage;
- failure-isolation tests before enabling any bridge outside local development.

## Required Guardrails

- Phase 1 packages are source artifacts, not mutable Phase 2 working data.
- `ObservedFact` must come from deterministic Phase 1 or device/person evidence,
  not model interpretation.
- `DerivedMeasurement` must be deterministic and provenance-linked.
- `ModelInterpretation` must be append-only and reviewable.
- Phase 2 write failures must not affect Phase 1 safety responses.
- Any future live bridge must be explicit, opt-in, and post-persistence only.

## Completion Criteria

Phase 3 is complete when:

- a disabled-by-default bridge imports persisted incidents into the Brain with
  failure isolation;
- the fixture matrix covers major Phase 1 incident classes and Phase 2 support
  situations;
- admin and artifact manifest surfaces show integrated evidence read-only;
- release gates include Phase 1 + 2 integration checks;
- full regression passes without requiring local-only raw captures;
- docs clearly show that Phase 1 remains the safety baseline and Phase 2 remains
  downstream evidence and support.
