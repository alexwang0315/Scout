# Phase 4 Pre-Trip Planning Platform

## Problem Statement

Scout already has a downstream safety stack:

- Phase 1 records and evaluates a live trail mission as a deterministic safety
  black box.
- Phase 2 preserves evidence in a file-backed Brain and produces replay, audit,
  remote-status, and bounded decision-support artifacts.
- Phase 3 operationalizes the Phase 1 and Phase 2 bridge, admin review,
  fixture coverage, and release gates.

Phase 4 moves upstream. It should help a leader build a complete mission plan
before departure so the runtime has a route, checkpoints, POIs, terrain/map
evidence, resource assumptions, skill configuration, and artifact provenance
ready before the first observation arrives.

The planning layer is not a pretty map editor first. It is a mission compiler:
turn human planning inputs and trusted evidence into a versioned package that
Phase 1 can execute and Phase 2/3 can audit.

## Recommended Direction

Phase 4 should produce a `PreTripMissionPackage`.

That package should contain:

- a planned route and alternate routes;
- mission checkpoints and decision gates;
- POIs such as water, camp, trailheads, road access, signal points, hazards,
  shelters, and evacuation options;
- terrain and map evidence with source metadata;
- segment-level resource, daylight, communication, and risk assumptions;
- skill registry configuration for this mission;
- expected artifacts and evidence collection policies;
- provenance for every imported, edited, or inferred planning item;
- a compiled Phase 1 `MissionGraph`;
- Phase 2 Brain seed nodes and artifact refs;
- Phase 3 fixture candidates and release-gate expectations.

The core promise: when the team starts hiking, Scout is not improvising from a
track line. It is guarding against a predeclared mission model with auditable
assumptions and explicit fallbacks.

## User Roles

- Trip leader: builds the mission plan, accepts assumptions, chooses route and
  alternatives, and owns final go/no-go decisions.
- Team member: contributes device, fitness, constraints, emergency contact, and
  participation details.
- Remote safety contact: receives the final plan summary and later low-noise
  status artifacts.
- Reviewer or operator: audits plan quality, evidence provenance, and whether
  runtime behavior followed the declared mission package.

## Planning Inputs

Phase 4 should support these inputs over time:

- GPX, GeoJSON, KML, or hand-entered route geometry;
- offline map fixtures and future map provider exports;
- POI lists from trusted sources or manual entry;
- weather, daylight, terrain, communication, and resource assumptions;
- team roster, device capability, equipment, and emergency contacts;
- past mission Brain nodes and after-action lessons;
- incident-corpus derived planning heuristics;
- user-authored notes and route-specific constraints.

All imported inputs must keep source metadata. Inferred or model-assisted items
must be marked as interpretations or candidates until reviewed.

## Mission Compiler Output

Phase 4 should compile a plan into four downstream contracts:

1. Phase 1 runtime contract:
   - `MissionGraph`
   - `Checkpoint`
   - `RouteSegment`
   - `ControlZone`
   - `SegmentRequirement`
   - `DiversionPoint`
   - `RecordingPolicy`
   - map and POI evidence refs

2. Phase 2 Brain seed contract:
   - `Mission`
   - `Team`
   - `Person`
   - `Device`
   - `Equipment`
   - `Route`
   - `Segment`
   - `Checkpoint`
   - `Artifact`
   - deterministic planning measurements
   - reviewed human decisions

3. Phase 3 operations contract:
   - plan validation report;
   - fixture candidates for planned route and alternate outcomes;
   - release-gate expectations for required artifacts and safety checks;
   - plan-to-runtime audit hooks.

4. Human-facing artifact contract:
   - final route brief;
   - remote-contact brief;
   - team checklist;
   - emergency handoff summary;
   - go/no-go report.

## Product Principles

### Plan Before Runtime

Phase 4 must not rely on live runtime observation to define mission meaning.
The plan should be usable before departure, loadable offline, and inspectable
without starting the live app server.

### Evidence Beats Decoration

Every checkpoint, POI, hazard, control zone, and segment assumption should be
traceable to source evidence or explicit human review. Visual editing can come
later; the first durable value is a trustworthy plan graph.

### Human Reviewed, Machine Assisted

Model assistance may propose checkpoints, POIs, hazards, route splits, or skill
configuration. These proposals are not facts until the leader reviews them.

### Downstream Compatibility

The compiler should emit data that Phase 1 can consume without weakening the
safety state machine. It should seed Phase 2 with planning artifacts, not
runtime conclusions.

### Alternatives Are First-Class

A safe trip plan includes fallback routes, retreat points, camp options, water
points, communication windows, and explicit decision gates. Phase 4 should make
these alternatives structured, not buried in prose.

## Non-Goals

- Do not build a polished route-planning UI first.
- Do not add live map provider synchronization as the first slice.
- Do not let Phase 4 change live Phase 1 escalation semantics after departure.
- Do not treat model-suggested POIs, hazards, or skills as reviewed facts.
- Do not require cloud storage or a graph database.
- Do not collapse Phase 4 planning data into Phase 1 incident packages.
- Do not make Phase 4 a generic travel itinerary app.

## First Validation Questions

- Can a route plan compile into the current Phase 1 `MissionGraph` concepts
  without adding safety-runtime behavior?
- Which POI and checkpoint categories are mandatory for the first hiking
  mission package?
- What minimum provenance is required for map, terrain, weather, and POI
  evidence?
- How should reviewed planning assumptions become Phase 2 Brain nodes?
- Which planning gaps should block a mission from being marked ready?
- Which planning gaps should only produce warnings?
- What fixture proves that alternate routes and retreat points survive compile,
  replay, and after-action audit?
