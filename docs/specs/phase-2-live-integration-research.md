# Phase 2 Live Integration Research

This note evaluates whether Phase 2 should connect all current replay and Brain
work to live Phase 1 safety outputs. It is a research and boundary document, not
a live wiring implementation.

## Current State

Implemented Phase 2 surfaces are replay-first and file-backed:

- Brain nodes, file store, and artifact-reference validation;
- automatic writeback for `ObservedFact` and deterministic
  `DerivedMeasurement` only;
- explicit append-only policy for model interpretations, reviews, option sets,
  and skill run records;
- team replay fixtures, remote-status JSON, decision option replay, case replay,
  admin preview, artifact manifest, and release checker;
- fixture-backed Phase 1 incident package adapter that reads persisted
  `IncidentPackage` JSON and writes Phase 2 Brain artifacts, facts, and
  deterministic measurements.

The adapter proves the correct downstream direction: Phase 1 writes incident
packages first; Phase 2 reads them later. It does not call `/safety/*`, mutate
`MissionGraph`, alter route progress, or participate in emergency escalation.

## Live Connection Question

The useful live connection is not "Phase 2 joins every live route." The safer
question is:

Can Phase 1 emit persisted, deterministic evidence that a separately configured
Phase 2 bridge reads after the Phase 1 safety decision is complete?

The answer is yes, but only behind an explicit bridge that preserves Phase 1 as
the safety baseline.

## Candidate Integration Points

Recommended first live-capable point:

- `IncidentStore.save(package)` output after persistence succeeds.

Acceptable later read-only points:

- explicit CLI import of an incident package file;
- read-only admin action that imports a chosen persisted incident into a Phase 2
  Brain store;
- background adapter job that scans an incident-store directory and imports
  packages idempotently.

Rejected first live points:

- `/safety/observations`;
- `/safety/ack`;
- `/safety/incidents/{incident_id}` request handling path;
- `/pdr/update`;
- `MissionGraph`, `MissionProgressTracker`, `RouteProgressEvaluator`, offline
  map evidence, risk rules, or recording policy code.

Those rejected points are inside the live safety decision loop. Phase 2 should
not add latency, dependency failures, model output, or Brain-store state to that
loop.

## Recommended Architecture

Add a Phase 2 bridge as a disabled-by-default, post-persistence path:

1. Phase 1 evaluates observations exactly as it does today.
2. Phase 1 persists an incident package through `IncidentStore`.
3. A separate bridge receives the persisted file path or scans the store.
4. The bridge calls `phase1_phase2_adapter.load_phase1_incident_package()`.
5. The bridge calls `adapt_phase1_incident_package()`.
6. The bridge writes artifacts first, then automatic facts and measurements with
   strict artifact refs.
7. Any model interpretation, skill run, remote-status artifact, or option set is
   generated later through existing explicit Phase 2 policy paths.

The bridge should be idempotent. Reprocessing the same incident id should either
produce the same deterministic node ids or skip already-present nodes.

## Configuration Requirements

Live bridge configuration should be explicit:

- `SCOUT_PHASE2_INCIDENT_BRIDGE=1` enables the bridge;
- `SCOUT_PHASE2_BRAIN_STORE_ROOT` selects the target Brain store;
- missing or unwritable Brain store root disables the bridge and logs a warning;
- bridge failure must not change Phase 1 response payloads or escalation state.

Default behavior remains off.

## Acceptance Gates Before Live Wiring

Before connecting a live bridge:

- keep the fixture-backed adapter tests green;
- add an idempotent bridge test that imports the same persisted package twice;
- add a failure-isolated bridge test where Brain writing fails but Phase 1
  incident persistence still succeeds;
- prove no imports from Phase 2 modules are required by Phase 1 core model or
  evaluator modules;
- run the full regression gate.

## Decision

Do not connect all Phase 2 outcomes directly into live Phase 1 yet. Connect the
smallest useful live point first: persisted incident package to Phase 2 Brain
store, disabled by default and failure-isolated.

This gives the team live after-action evidence without changing the emergency
decision loop. Remote status, option replay, case replay, and model
interpretations can then build on imported Brain evidence through their existing
Phase 2 policies.
