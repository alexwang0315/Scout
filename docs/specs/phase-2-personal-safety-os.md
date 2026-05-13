# Spec: Phase 2 Personal Safety Operating System

## Objective

Phase 2 expands Scout from a Phase 1 trail safety black box into a team-first
mountain mission operating system.

Scout is not a hiking chatbot and not a single-route navigation assistant. It
should record verified field facts, preserve mission evidence, run bounded
skills, generate remote status artifacts, and help the trip leader preserve the
largest set of viable options under uncertainty.

Phase 2 starts with team hiking because it is the largest practical market and
because real mountain travel often involves dispersed pace, weather gaps,
waiting points, regrouping, and remote family or friend awareness.

Success means:

- A team mission can produce a recoverable file-based Scout Brain.
- The Brain separates observed facts, deterministic measurements, model
  interpretations, human reviews, skill runs, and raw artifacts.
- Scout can produce remote status JSON without requiring the hiker to manually
  report safety status.
- A real skill registry can run preflight checks, enforce activation gates,
  record failures, and leave an audit trail.
- Scout generates option sets before making intrusive recommendations.
- Phase 1 emergency escalation remains deterministic and auditable.

## Product Principles

### Team-First Mission Context

The first Phase 2 scenario is team hiking, including:

- one trip leader or mission owner;
- multiple team members with different pace, device, and communication states;
- remote safety contacts who need low-noise status updates;
- team separation, waiting, regrouping, and checkpoint delay events;
- post-mission review of route, weather, body state, device state, and decisions.

Solo hiking remains supported as a special case of a one-person team. Search and
rescue use is not the first buyer persona, but the evidence model should support
handoff to rescuers later.

### Pilot-In-Command

The adventure leader is the pilot-in-command. Scout provides evidence, options,
and bounded recommendations. It does not replace the leader's authority.

Scout should prefer maximum optionality over a single "best" strategy. In the
field, the safest answer is often the one that preserves the most reversible
actions, not the one that optimizes speed or route efficiency.

Before producing an intrusive recommendation such as `rest`, `turn_back`, or
`divert`, Scout should generate an option set with tradeoffs:

- resource requirements;
- estimated time;
- daylight margin;
- battery cost;
- communication chance;
- team impact;
- reversibility;
- failure modes;
- confidence and uncertainty.

Exceptions are allowed only for high-confidence emergency preservation actions
already governed by the deterministic safety runtime.

### Fact-Only Automatic Writeback

Automatic writeback to the Scout Brain is limited to facts and deterministic
derived measurements.

Allowed automatic writeback:

- observed facts, such as location, checkpoint arrival, heart rate, battery,
  signal state, weather observation, safety transition, or delivery attempt;
- deterministic derived measurements, such as checkpoint delay, pace drop,
  battery drain rate, stop frequency, RSSI trend, or daylight remaining.

Not allowed as automatic facts:

- model interpretations;
- risk explanations;
- inferred emotional or cognitive state;
- retreat or continuation advice;
- human conclusions.

Model output must be append-only, versioned, and linked to its input artifacts.
It may inform a later human review, but it cannot overwrite the source of truth.

### File-Based Graph First

The first Scout Brain is a file-based graph backed by artifacts. This is an
intentional failover choice. If an index, process, or device runtime fails, the
mission should still be partially recoverable from distributed structured files
and artifact references.

SQLite may be used as a local cache, index, or migration helper. It is not the
Phase 2 semantic source of truth. A dedicated graph database is a future option,
not a v0.1 dependency.

### Skills Are Auditable Work Units

A skill is not a prompt. A skill is a registry-managed work unit with:

- declared triggers;
- required inputs;
- preflight dependencies;
- allowed reads and writes;
- activation gates;
- failure policy;
- output schema;
- audit policy;
- replay fixtures and tests.

The registry must support long-term evolution. New field experience, real
incidents, rescue reports, and after-action reviews can produce skill
candidates, but candidates must pass through review, simulation, and controlled
trial before becoming stable skills.

## Architecture

### Scout Brain

The Scout Brain is a file-based graph plus artifact references.

Suggested directory shape:

```text
brain/
  missions/
  routes/
  teams/
  people/
  devices/
  equipment/
  checkpoints/
  segments/
  facts/
  measurements/
  interpretations/
  reviews/
  skill-runs/
  artifacts/
  indexes/
```

Each graph node should be independently readable. Index files can accelerate
lookup but must be rebuildable from nodes and artifacts.

Initial node types:

- `Mission`
- `Team`
- `Person`
- `Device`
- `Equipment`
- `Route`
- `Segment`
- `Checkpoint`
- `ObservedFact`
- `DerivedMeasurement`
- `ModelInterpretation`
- `HumanReview`
- `SkillDefinition`
- `SkillRunRecord`
- `Artifact`
- `RemoteStatusArtifact`
- `DecisionOptionSet`
- `BeaconNode`
- `TeamSeparationEvent`
- `SignalBearingMeasurement`

Raw logs, GPX, GeoJSON, photos, incident packages, segment capsules, beacon scan
captures, and replay outputs are artifacts. Graph nodes reference those
artifacts instead of embedding all raw samples.

### Brain Layers

#### Observed Fact

An `ObservedFact` records something directly observed by a device, person, or
trusted system boundary.

Example:

```json
{
  "id": "fact.cp2_arrival.member_02.20260513T092211",
  "type": "ObservedFact",
  "subject": "person.member_02",
  "predicate": "arrived_at_checkpoint",
  "object": "checkpoint.cp2",
  "observed_at": "2026-05-13T09:22:11+08:00",
  "evidence": [
    "artifact.sensorlog.applewatch.20260513",
    "artifact.gpx.track.member_02.20260513"
  ],
  "confidence": "high",
  "write_policy": "automatic"
}
```

#### Derived Measurement

A `DerivedMeasurement` records deterministic computation over facts or
artifacts.

Example:

```json
{
  "id": "measurement.cp2_delay.team.20260513",
  "type": "DerivedMeasurement",
  "subject": "team.weekend_group_01",
  "metric": "checkpoint_arrival_delay_minutes",
  "value": 18,
  "unit": "minutes",
  "derived_from": [
    "fact.cp2_arrival.member_02.20260513T092211",
    "route_plan.cp2_eta"
  ],
  "method": "planned_eta_vs_observed_arrival",
  "write_policy": "automatic"
}
```

#### Model Interpretation

A `ModelInterpretation` records a model's explanation, hypothesis, or
recommendation. It is never a fact.

Example:

```json
{
  "id": "interpretation.delay_reason.model_a.20260513T094000",
  "type": "ModelInterpretation",
  "subject": "measurement.cp2_delay.team.20260513",
  "model": "model_a",
  "model_version": "2026-05-13",
  "claim": "Delay may be related to rain, slope, and team pace compression.",
  "input_refs": [
    "measurement.cp2_delay.team.20260513",
    "measurement.slope_segment_2",
    "fact.weather_rain_segment_2"
  ],
  "write_policy": "append_only_requires_review"
}
```

#### Human Review

A `HumanReview` records what the leader, team member, or reviewer confirmed,
rejected, or corrected after seeing facts and interpretations.

Human review may update mission notes or mark an interpretation as accepted, but
it should not mutate the original observed facts.

### Skill Registry Manifest

Initial skill manifest shape:

```yaml
skill_id: team-checkin-summary
version: 0.1.0
status: experimental
type: workflow
description: Generate a low-noise team hiking status summary as JSON.

priority: 80

triggers:
  - checkpoint_arrived
  - scheduled_checkin_due
  - safety_level_changed
  - remote_contact_requested_status

activation_gate:
  gate_type: safety_level_constraint
  default_min_level: L0
  hard_min_level: L0
  require_policy_eval: true

noise_control:
  cooldown_minutes: 15
  suppress_if_recently_acknowledged: true
  require_new_evidence: true

preflight:
  required:
    - device-capability-check
    - communication-state-check
    - latest-team-position-check
  optional:
    - battery-health-check
    - location-confidence-check

required_inputs:
  - mission_id
  - team_id
  - latest_checkpoint_state
  - latest_safety_state

allowed_reads:
  - Mission
  - Team
  - Person
  - Device
  - Checkpoint
  - ObservedFact
  - DerivedMeasurement
  - SafetyEvent

allowed_writes:
  - SkillRunRecord
  - RemoteStatusArtifact
  - DeliveryAttemptFact

forbidden_writes:
  - ObservedFactWithoutEvidence
  - SafetyStateOverride
  - ModelInterpretationAsFact

output_schema:
  type: json
  artifact_type: remote_status_json

on_fail:
  retry:
    max_attempts: 2
    backoff_seconds: 30
  fallback_skills:
    - low-bandwidth-status-summary
    - store-and-forward-status
    - nearby-pull-beacon-update
  failure_events:
    - type: SKILL_EXECUTION_FAILED
      write_as: observed_fact
    - type: COMMUNICATION_DEGRADED
      write_as: observed_fact
  degraded_mode:
    produce_local_json: true
    attach_to_incident_package: true

control_surface:
  type: software_tool
  requires_human_confirm: false
  max_autonomy_level: supervised

audit:
  record_inputs: true
  record_outputs: true
  record_model: true
  record_prompt_hash: true
  record_artifact_refs: true
```

Manifest fields:

- `priority`: ordering when multiple skills are eligible.
- `preflight.required`: skills or tools that must pass before execution.
- `activation_gate`: safety-level and mission-policy gate.
- `noise_control`: rules that prevent intrusive or repetitive advice.
- `allowed_reads` / `allowed_writes`: Brain access contract.
- `forbidden_writes`: hard safety boundaries.
- `on_fail`: retry, fallback, degraded mode, and failure event policy.
- `control_surface`: software, communication, or hardware control boundary.
- `audit`: what must be recorded for replay and review.

### Activation Gates and Ln Constraints

Skill execution must pass through an activation gate. The skill manifest declares
the gate type and defaults, but the final decision comes from a runtime
`LnConstraintEvaluator`.

The evaluator considers:

- current safety level;
- mission type;
- route type, such as traverse, loop, out-and-back, or expedition;
- duration class, such as same-day or multi-day;
- team state;
- terrain and weather;
- communication and device state;
- new evidence since the previous prompt;
- route-specific or region-specific policy.

Possible decisions:

- `allow`
- `disallow`
- `defer`
- `degrade`

Every decision must record policy id, version, evidence refs, and reason.

Preflight skills such as `device-capability-check` must be allowed at L0. More
intrusive skills such as `retreat-decision-support` may require L1 or L2
depending on the route and mission policy.

### Decision Option Sets

Skills that support decisions should output option sets, not single commands.

Example:

```json
{
  "type": "DecisionOptionSet",
  "mission_id": "mission.hehuan_2026_05_13",
  "generated_at": "2026-05-13T10:42:00+08:00",
  "current_safety_level": "L2",
  "pilot_in_command": "person.team_leader",
  "options": [
    {
      "id": "option.rest_reassess",
      "label": "Rest and reassess",
      "action": "rest",
      "estimated_time_minutes": 20,
      "resource_cost": "low",
      "reversibility": "high",
      "primary_risks": ["weather may worsen", "arrival delay increases"],
      "preserves_options": ["continue", "turn_back", "divert"],
      "confidence": "medium"
    },
    {
      "id": "option.return_to_cp2",
      "label": "Return to CP2",
      "action": "turn_back",
      "estimated_time_minutes": 45,
      "resource_cost": "medium",
      "reversibility": "medium",
      "primary_risks": ["descending wet terrain", "team fatigue"],
      "preserves_options": ["known waiting point", "last signal point"],
      "confidence": "high"
    }
  ],
  "scout_preference": {
    "preferred_options": ["option.rest_reassess", "option.return_to_cp2"],
    "reason": "These options preserve more recovery paths under current daylight and weather uncertainty."
  }
}
```

### Remote Status JSON

Phase 2 v0.1 produces JSON first. Communication transport is selected later by
skills.

Example:

```json
{
  "type": "RemoteStatusArtifact",
  "mission_id": "mission.hehuan_2026_05_13",
  "generated_at": "2026-05-13T14:32:00+08:00",
  "freshness_seconds": 180,
  "status": "delayed_but_moving",
  "latest_checkpoint": "checkpoint.cp2",
  "next_checkpoint": "checkpoint.cp3",
  "eta": "2026-05-13T16:10:00+08:00",
  "team_summary": {
    "member_count": 4,
    "confirmed_nearby": 3,
    "possible_separation": 1
  },
  "safety_level": "L1",
  "uncertainty": "medium",
  "message": "Team is delayed but still moving. One member has weaker position freshness."
}
```

The artifact should be understandable by a remote family member or friend
without exposing unnecessary raw telemetry.

### Team Cohesion and Rendezvous Beacon

Beacon mode is a team cohesion, rendezvous, and rescue marker capability. It is
not general destination navigation.

When the team stretches out because of pace, weather, visibility, or waiting
conditions, Scout may designate one node as a beacon. Other Scout nodes can scan
supported radio signals and use RSSI trends to move toward the rendezvous point.

Supported future radio modes may include:

- Wi-Fi AP or SoftAP;
- BLE advertising;
- LoRa beacon;
- UWB ranging;
- multiple concurrent radios.

Phase 2 v0.1 should model this with mock radio measurements and JSON artifacts.
Hardware integration comes later.

Beacon output must be trend-based. Scout should say that signal improves when
moving north or northeast, not claim exact position from RSSI alone.

### Reconnaissance Skills

Future hardware-control skills may use drones, second devices, team phones,
fixed beacons, or cameras to collect forward-route evidence.

Recon skills are evidence-gathering tools. They do not become autonomous rescue
commanders. They must support:

- preflight checks;
- battery and weather checks;
- legal or airspace checks when applicable;
- human confirmation for hardware control;
- artifact-backed evidence output;
- audit records;
- fallback behavior.

The registry must be expressive enough for these skills even if Phase 2 v0.1
does not implement them.

### Skill Evolution Lifecycle

Scout's skill registry remains open after product launch.

Lifecycle:

```text
Field Experience
-> Skill Candidate
-> Spec Draft
-> Replay / Simulation
-> Controlled Trial
-> Registry Admission
-> Versioned Updates
-> Deprecation / Replacement
```

Skill statuses:

- `candidate`
- `experimental`
- `field_trial`
- `stable`
- `deprecated`
- `disabled`

Every new skill candidate should explain:

- field problem;
- expected value;
- trigger conditions;
- required evidence;
- possible failure modes;
- noise risk;
- safety level gate;
- replay or field validation plan.

## Commands

The repository currently uses direct Python modules and tests rather than a
single package command file. Phase 2 implementation should keep commands
explicit.

Baseline verification:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest
```

Expected Phase 2 targeted commands after implementation:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_phase2_brain.py
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_skill_registry.py
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_phase2_remote_status.py
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_phase2_case_replay.py
```

## Testing Strategy

Phase 2 is replay-first and audit-first.

Test levels:

- Schema tests for Brain node validation.
- Writeback policy tests proving model interpretations cannot overwrite facts.
- Skill manifest tests for required fields, permissions, gates, failure policy,
  and output schema.
- Ln constraint tests for route, duration, activity, weather, and safety-level
  differences.
- Remote status tests for JSON shape, freshness, uncertainty, and low-noise
  output.
- Team cohesion tests using mock separation and beacon RSSI trend artifacts.
- Case replay tests using real mountain incident timelines where possible.
- Regression tests proving Phase 1 replay and incident behavior still passes.

Case replay should not claim that Scout would certainly prevent a tragedy. It
should evaluate whether Scout would create earlier awareness, preserve more
options, improve remote awareness, or leave better evidence.

Case replay verdict levels:

- `no_effect`
- `evidence_improvement`
- `earlier_awareness`
- `decision_window_created`
- `likely_outcome_improvement`

## Boundaries

Always:

- Keep Phase 1 safety state machine as the emergency escalation authority.
- Write only observed facts and deterministic measurements automatically.
- Store model output as append-only interpretation with model and input refs.
- Record skill runs with inputs, outputs, policy decisions, and artifact refs.
- Produce remote status with freshness and uncertainty.
- Generate option sets before intrusive recommendations.
- Keep file-based graph nodes recoverable without a live index.

Ask first:

- Adding a dedicated graph database.
- Changing incident package semantics.
- Allowing AI output to affect safety levels.
- Adding cloud sync or third-party delivery services.
- Storing long-term team member health or location history.
- Controlling hardware such as drones, radios, or beacons outside a mock.

Never:

- Let an LLM directly decide L3 or L4 emergency escalation.
- Treat model interpretation as observed fact.
- Store unlimited raw sensor streams directly in the graph.
- Infer fear, attention, or mental state as automatic fact.
- Make Scout's option preference look like a command from the system.
- Use RSSI as precise positioning evidence without uncertainty.

## Success Criteria

Phase 2 v0.1 is complete when:

- A team hiking replay produces a file-based Scout Brain.
- Brain nodes clearly separate facts, measurements, interpretations, human
  reviews, skill runs, and artifacts.
- At least three registry-managed skills run and write audited skill records.
- A remote status JSON artifact is generated without manual hiker input.
- Ln activation gates can allow, disallow, defer, or degrade skill execution
  based on mission context.
- A decision-support skill outputs an option set instead of a single command.
- A mock team separation case produces a rendezvous or beacon artifact.
- At least three real or realistic case replays produce verdicts and audit
  timelines.
- Phase 1 replay and safety tests continue to pass.

## Open Questions

- Which specific team hiking route should become the first Phase 2 field replay?
- What is the minimal file naming and id scheme for recoverable graph nodes?
- How much personal health history should be retained by default?
- Which real mountain incidents are appropriate for initial case replay without
  overfitting or making unsupported rescue claims?
- Should the first beacon mock model Wi-Fi SoftAP, BLE advertising, or a generic
  radio signal abstraction?
- Where should Scout-specific skills live relative to Codex skills and future
  product skills?
