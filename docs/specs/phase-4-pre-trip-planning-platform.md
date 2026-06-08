# Spec: Phase 4 Pre-Trip Planning Platform

## Objective

Build Phase 4 as Scout's upstream pre-trip planning layer.

Phase 4 creates, validates, versions, and compiles a mission plan before
departure. Its output should let Phase 1 guard the user against a declared plan,
let Phase 2 preserve planning evidence in the Brain, and let Phase 3 audit
whether runtime behavior followed the pre-trip contract.

Success means:

- a leader can define a mission package with route, checkpoints, POIs, terrain
  evidence, resource assumptions, skill configuration, and expected artifacts;
- the package can compile into a Phase 1-compatible `MissionGraph`;
- reviewed planning data can seed Phase 2 Brain nodes without pretending that
  model suggestions are facts;
- Phase 3 can validate plan quality and compare plan assumptions with runtime
  evidence after the trip;
- the first implementation can be proven with files and tests, without UI,
  cloud storage, or live map providers.

## Assumptions

- Phase 1 remains the deterministic live safety baseline.
- Phase 2 remains the file-backed Brain, replay, audit, and decision-support
  layer.
- Phase 3 remains the operational bridge, fixture matrix, admin after-action,
  and release-gate layer.
- Phase 4 runs before the mission starts and produces downstream artifacts.
- The first deliverable is a file-backed planning compiler, not a route editor
  UI.
- Planning data may be model-assisted, but reviewed human decisions and source
  evidence must be separated from candidates and interpretations.

## Scope

### In Scope

- `PreTripMissionPackage` model and fixture format.
- Route and alternate route references.
- Checkpoints, decision gates, control zones, and segment boundaries.
- POIs for water, camp, shelter, road access, signal, hazard, trailhead,
  evacuation, rendezvous, and observation points.
- Terrain, map, weather, daylight, communication, and resource evidence refs.
- Segment-level assumptions and `SegmentRequirement` candidates.
- Mission-specific skill configuration and activation expectations.
- Expected artifacts, recording policies, and evidence collection plan.
- Provenance for every imported, edited, inferred, or reviewed item.
- Compile path into Phase 1 mission graph concepts.
- Brain seed export for Phase 2 planning artifacts and reviewed facts.
- Validation report for missing, weak, or unreviewed planning inputs.
- Fixture-backed tests for a first hiking mission package.

### Out of Scope

- Polished map UI or itinerary UI.
- Live provider sync for maps, weather, or trail databases.
- Production offline map engine.
- Cloud collaboration.
- Account management or permission model.
- Live Phase 1 escalation changes after departure.
- Runtime incident import behavior, which belongs to Phase 3.
- LLM-only route planning without source evidence and human review.

## Core Concepts

### PreTripMissionPackage

The top-level versioned package for one planned mission.

It should include:

- package id, mission id, version, status, owner, timestamps;
- route plan refs, alternate route refs, and route source metadata;
- team, device, equipment, emergency contact, and remote contact refs;
- checkpoints, POIs, control zones, and segment assumptions;
- skill configuration for this mission;
- artifact manifest for imported source files and generated planning outputs;
- validation report refs;
- compile outputs for Phase 1 and Phase 2.

Initial statuses:

- `draft`
- `needs_review`
- `ready_for_field_trial`
- `frozen_for_departure`
- `superseded`
- `archived`

### Planning Item Provenance

Every planning item should declare how it entered the package:

- `imported_source`: loaded from GPX, GeoJSON, map fixture, article, or other
  source file;
- `manual_entry`: created directly by the leader;
- `deterministic_derived`: computed from reviewed route/evidence;
- `model_candidate`: proposed by a model and not yet accepted;
- `human_reviewed`: accepted, rejected, or edited by a human reviewer.

Only imported, manual, deterministic, or human-reviewed data may become Phase 1
runtime inputs. Model candidates may be preserved as Phase 2 interpretations or
planning-review artifacts.

### Route Plan

The route plan contains:

- primary route geometry refs;
- optional alternate route geometry refs;
- route source and license metadata;
- expected direction and route type;
- planned start/end time window;
- segment split candidates;
- confidence and known limitations.

### Checkpoint and Decision Gate

A checkpoint is a mission boundary. A decision gate is a checkpoint where the
leader must explicitly evaluate continuation assumptions.

Examples:

- ridge entry;
- forest or weak-GPS boundary;
- last reliable signal point;
- water source;
- camp or shelter;
- retreat fork;
- high-risk terrain entry;
- latest safe turn-back point.

Decision gates should compile into Phase 1 checkpoint and segment requirement
data, and into Phase 2 reviewed planning artifacts.

### POI Evidence

POIs should be typed, source-linked, and usable by downstream systems.

Initial POI types:

- `water`
- `camp`
- `shelter`
- `trailhead`
- `road_access`
- `signal_point`
- `hazard`
- `viewpoint`
- `evacuation`
- `rendezvous`
- `medical`
- `supply`
- `unknown_candidate`

`unknown_candidate` should never compile into a safety-critical Phase 1
requirement without review.

### Terrain and Map Evidence

Terrain and map evidence should support:

- corridor confidence;
- slope or grade assumptions;
- expected GPS reliability;
- known hazards;
- route ambiguity;
- water crossing;
- exposure or ridge section;
- vegetation or canopy context;
- communication expectation.

The first implementation may use fixture GeoJSON and static metadata. It should
not require full vector tile ingestion.

### Skill Configuration

Phase 4 chooses mission-specific skill expectations. It does not execute live
runtime skills during planning acceptance.

Examples:

- required preflight skills;
- optional route-analysis skills;
- remote-status skill settings;
- checkpoint-delay skill thresholds;
- communication-state skill expectations;
- rendezvous or beacon skill eligibility;
- forbidden or unavailable skills for this mission.

The output should be compatible with the Phase 2 skill registry and activation
gate model.

## Downstream Contracts

### Phase 1 Compile Contract

Phase 4 may emit:

- `MissionGraph`
- `Checkpoint`
- `RouteSegment`
- `ControlZone`
- `RecordingPolicy`
- `SegmentRequirement`
- `DiversionPoint`
- route geometry refs
- offline map evidence refs

Phase 4 must not emit:

- live safety states;
- incident packages;
- safety transitions;
- Phase 2 interpretations as Phase 1 facts;
- runtime overrides that can downgrade or suppress Phase 1 escalation.

### Phase 2 Brain Seed Contract

Phase 4 may seed:

- `Mission`
- `Team`
- `Person`
- `Device`
- `Equipment`
- `Route`
- `Segment`
- `Checkpoint`
- `Artifact`
- deterministic route measurements;
- reviewed planning decisions;
- model planning candidates as append-only interpretations.

Automatic Brain writeback remains fact-only. A reviewed planning decision is a
human review artifact, not proof that the future field condition will happen.

### Phase 3 Operations Contract

Phase 4 should produce:

- plan validation report;
- readiness status;
- missing evidence list;
- warnings and blockers;
- fixture candidates for replay and after-action comparison;
- plan version id for runtime and audit correlation.

Phase 3 can later compare:

- planned checkpoint timing vs. observed checkpoint timing;
- planned route and alternates vs. route-progress evidence;
- declared POIs vs. used POIs;
- expected communication windows vs. actual communication evidence;
- planned skill configuration vs. runtime skill runs.

## Validation Rules

Initial blockers:

- no primary route;
- no mission owner;
- no start window;
- no checkpoints;
- no route source provenance;
- no emergency or remote contact plan for a team mission;
- safety-critical model candidates not reviewed;
- Phase 1 compile output missing required mission graph fields.

Initial warnings:

- no alternate route;
- no water or camp POIs on long routes;
- no signal expectations;
- no daylight margin;
- no weather assumption;
- no team device inventory;
- incomplete skill configuration;
- map evidence has low confidence;
- checkpoint spacing is too wide for terrain risk.

## Commands

Initial doc-only planning verification:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_phase1_phase2_adapter.py tests/test_phase2_case_replay.py
```

Future Phase 4 focused verification:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_phase4_pretrip_models.py tests/test_phase4_mission_compiler.py tests/test_phase4_plan_validation.py
```

Full regression:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest
```

Release gate after Phase 4 is registered:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python phase2_release_check.py --repo-root /Users/alexwang0315/scout-fusion
```

## Project Structure

Proposed future structure:

```text
phase4_pretrip_models.py              # package, route, POI, provenance models
phase4_plan_validation.py             # readiness blockers and warnings
phase4_mission_compiler.py            # Phase 4 -> Phase 1 MissionGraph output
phase4_brain_seed.py                  # Phase 4 -> Phase 2 Brain seed output
tests/test_phase4_pretrip_models.py
tests/test_phase4_plan_validation.py
tests/test_phase4_mission_compiler.py
tests/test_phase4_brain_seed.py
tests/fixtures/phase4/
docs/specs/phase-4-pre-trip-planning-platform.md
docs/ideas/phase-4-pre-trip-planning-platform.md
```

## Code Style

Use explicit data models and deterministic transforms. Do not hide safety
semantics in string parsing or prompt text.

Example target shape:

```python
package = PreTripMissionPackage(
    package_id="pretrip.alishan_loop.20260514.v1",
    mission_id="mission.alishan_loop.20260514",
    status="needs_review",
    primary_route_ref="artifact.route.alishan_loop.gpx",
    checkpoints=[ridge_entry_checkpoint],
    pois=[water_source_poi, retreat_fork_poi],
    provenance=[route_import_provenance],
)

report = validate_pretrip_package(package)
compiled = compile_phase1_mission_graph(package, require_ready=True)
```

Conventions:

- use stable ids with semantic prefixes;
- keep artifacts by reference instead of embedding raw map or track payloads;
- reject unreviewed model candidates for safety-critical compile fields;
- keep deterministic measurements separate from model interpretations;
- make validation errors structured and fixture-testable.

## Testing Strategy

Phase 4 should be fixture-first.

Test levels:

- model tests for required fields, ids, provenance, and status transitions;
- validation tests for blockers and warnings;
- compiler tests for Phase 1 `MissionGraph` compatibility;
- Brain seed tests for Phase 2 fact/interpretation separation;
- golden fixture tests for one complete hiking mission package;
- regression tests proving Phase 1 and Phase 2 behavior is unchanged by
  planning code.

No Phase 4 test should require network access, cloud storage, or local-only raw
capture files.

## Boundaries

Always:

- keep Phase 4 upstream of live runtime;
- preserve source provenance for every planning item;
- separate model candidates from human-reviewed inputs;
- compile only reviewed or deterministic data into Phase 1 runtime inputs;
- keep fixtures small, versioned, and loadable without the app server.

Ask first:

- adding a database;
- adding a map provider dependency;
- changing Phase 1 `MissionGraph` semantics;
- changing Phase 2 Brain writeback policy;
- adding UI surfaces;
- importing large map datasets into the repository.

Never:

- let Phase 4 downgrade, suppress, or override live Phase 1 escalation;
- compile unreviewed model candidates into safety-critical fields;
- rewrite persisted incident packages;
- require network access for core tests;
- store secrets or provider tokens in plan packages;
- treat a planned assumption as an observed field fact.

## Implementation Plan

### Milestone 0: Spec and Calibration Fixture

Goal: agree on the planning contract before implementation.

Acceptance:

- this spec exists under `docs/specs`;
- the product direction exists under `docs/ideas`;
- one first mission scenario is chosen with route, checkpoint, POI, terrain,
  resource, communication, and skill assumptions.

Suggested future files:

- `tests/fixtures/phase4/first_pretrip_package.json`

### Milestone 1: PreTrip Models and Provenance

Goal: define the package, route, checkpoint, POI, evidence, skill config, and
provenance data models.

Acceptance:

- package loads from JSON;
- every planning item has provenance;
- status transitions are explicit;
- safety-critical fields reject unreviewed model candidates.

Verify:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_phase4_pretrip_models.py
```

### Milestone 2: Plan Validation

Goal: classify planning gaps as blockers or warnings.

Acceptance:

- missing primary route blocks readiness;
- missing alternate route warns but does not block by default;
- unreviewed safety-critical candidates block compile;
- validation report is deterministic and artifact-linkable.

Verify:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_phase4_plan_validation.py
```

### Milestone 3: Phase 1 Mission Compiler

Goal: compile reviewed planning data into Phase 1 mission graph concepts.

Acceptance:

- checkpoints become Phase 1 checkpoints;
- decision gates become segment requirements;
- POIs become diversion points or map evidence refs only when reviewed;
- route and terrain refs remain artifact-backed;
- compile failure does not change Phase 1 runtime behavior.

Verify:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_phase4_mission_compiler.py tests/test_phase1_replay_runner.py
```

### Milestone 4: Phase 2 Brain Seed Export

Goal: seed planning artifacts into the Brain without violating fact-only
writeback.

Acceptance:

- reviewed plan entries become planning artifacts or human review nodes;
- deterministic route measurements become `DerivedMeasurement`;
- model suggestions remain append-only interpretation/candidate artifacts;
- source files become `Artifact` refs.

Verify:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_phase4_brain_seed.py tests/test_phase2_writeback_policy.py
```

### Milestone 5: Phase 3 Readiness and Audit Hooks

Goal: make the plan package usable by release gates and after-action review.

Acceptance:

- package id and version can be carried into runtime artifacts;
- validation report can be surfaced by admin/release tooling later;
- fixture candidate metadata exists for planned route and alternate outcomes;
- no UI work is required for acceptance.

Verify:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_phase4_plan_validation.py tests/test_phase2_release_check.py
```

## Success Criteria

Phase 4 planning is ready for implementation when:

- the team accepts this upstream/downstream boundary;
- the first mission fixture is selected;
- blockers and warnings are considered correct for field-trial readiness;
- the compiler contract is accepted as Phase 1-compatible;
- Brain seed behavior is accepted as Phase 2-compatible;
- implementation can proceed in small tested slices without UI.

## Resolved Decisions

- First mountain calibration case: Chilai-Nanhua / Nenggao Day 1.
- Alternate/retreat readiness: missing alternate or retreat evidence is a
  warning by default unless a reviewed mission policy or segment requirement
  makes it mandatory.
- Compiler target: emit the current Phase 1 `MissionGraph`/mission model shape
  directly.
- Skill config: reference external manifests and mission-specific config
  artifacts from the pre-trip package.
- Terrain evidence: raw DTM stays local/offline; version only metadata and
  reduced summaries needed by fixtures or CI.
- ETA readiness: use conservative total elapsed time when the guide-time
  multiplier basis is unknown.
- Wrong-scope route stats: ignore 33.43km stats that do not belong to the
  selected calibration route.

## Backlog / Next Decisions

- Decide which POI types block readiness in the first hiking use case.
- Define the minimum remote-contact plan summary before departure.
- Set minimum weather/daylight evidence depth for readiness.
- Decide the contour interpretation workflow for paper/image-map references.
- Choose known-case route-comparison sources after legal and fixture-use terms
  are clear.
