# Scout Dashboard Internal Qualification

Status: COMPLETE — construction qualification; no release/productization claim
Owner: Scout engineering
Review: Codex + GPT Pro joint agreement required
Runtime UI impact: none

## 1. Purpose

This specification defines an internal-only qualification system that detects
program-design defects before runtime Dashboard acceptance. It is distinct from
`System -> Diagnostic`, which remains a black-box, read-only check of visible
and operable implemented functionality.

Internal Qualification must detect defects such as:

- a historically valid artifact that still parses but can no longer complete a
  supported workflow;
- a non-terminal state with no legal outgoing transition;
- a suggested action that returns to the same semantic state without progress;
- duplicated eligibility predicates that disagree;
- a new flag or field whose false, missing, legacy, or combined states were not
  evaluated;
- partial writes, missing rollback, idempotency conflicts, or restart recovery
  gaps;
- an upstream identity/hash change that leaves downstream projections partly
  fresh and partly stale;
- candidate or generated state crossing into runtime safety truth, outbound
  transport, private-data disclosure, or hardware control.

This is an engineering and release gate. It has no Dashboard route, no user
controls, and no user-facing report requirement.

## 2. Non-goals and boundaries

- Do not add Internal Qualification cases to Dashboard Diagnostic.
- Do not use line coverage, HTTP 200, schema parsing, or button existence as a
  completion proxy.
- Do not execute qualification writes against a real active workspace. Use
  isolated temporary workspaces and sanitized historical fixtures.
- Do not infer missing day ends, safety decisions, or runtime authorization in
  order to make a workflow pass.
- Do not read `.env`, credentials, raw GPX, raw health data, or unrelated private
  workspace contents.
- Do not claim mathematical completeness over arbitrary program behavior.
  Exhaust finite domain state machines and use bounded combinatorial, property,
  fault, and mutation techniques for the remaining state space.

## 3. Joint review and completion protocol

GPT Pro serves as a critical reviewer, alternative architect, and contradiction
finder. Codex owns local evidence collection, implementation, deterministic
verification, and the final requirement-by-requirement audit.

Each phase follows this loop:

1. Codex records the proposed contract and evidence plan.
2. GPT Pro challenges assumptions, missing states, oracle coupling, and false
   completion claims.
3. Codex verifies every factual claim against authorized local sources.
4. Differences are resolved through focused follow-up questions.
5. Both reviewers issue an explicit phase verdict: `AGREE`, `AGREE_WITH_DEBT`,
   or `DISAGREE`.
6. A phase may advance only with two compatible agree verdicts. Debt must be
   recorded and must not contradict that phase's acceptance criteria.

The overall task completes only after both reviewers agree on all three phases
and the final completion audit.

## 4. Known motivating counterexample

The initial Permission implementation demonstrates a lifecycle livelock:

```text
legacy_sparse reviewed baseline
  -> acceptance succeeds
  -> contextual_permission_projection_stale
  -> rebuild.eligible=false
  -> Generate from Ref. GPX remains available
  -> generated profile remains legacy_sparse when rich timing inputs are absent
  -> no primary day-end proposals are produced
  -> rebuild remains ineligible
```

The artifact remains `missionBaselineCandidate.v1` while proposal-first fields
change the semantic capability of the same nominal schema. Parsing succeeds,
but a later rebuild gate rejects the historical capability. The existing test
asserts that authoring remains callable, but does not prove the same workspace
can reach a rebuildable state.

Internal finding classification:

- `FLOW-LIVELOCK`
- `SCHEMA-SEMANTIC-DRIFT`
- `VERSION-TRAP`
- `HIDDEN-PREREQUISITE`
- `PREDICATE-DIVERGENCE-RISK`

## 5. Core qualification contracts

### 5.1 Canonical state vector

A qualification state is a bounded semantic snapshot, not an arbitrary object
dump or one flat lifecycle enum. Orthogonal facts must remain independently
observable because states such as `legacy_reviewed` and `projection_stale` may
be true at the same time.

The Permission vertical slice contains at least these axes:

- baseline capability: `absent`, `legacy_sparse`, `proposal_capable`, or
  `unknown_or_unsupported`;
- baseline lifecycle: `candidate`, `reviewed`, `current`, or `superseded`;
- required inputs: `missing`, `conflicting`, or `complete`;
- baseline review binding: `none`, `current`, or `stale`;
- migration: `none`, `required`, `candidate`, `review_pending`, `accepted`, or
  `blocked`;
- projection: `absent`, `stale`, `fresh`, or `orphaned_or_write_in_doubt`;
- policy review: `not_required`, `pending`, `current`, or `stale`;
- command-specific admission: `eligible`, `blocked`, or
  `stale_precondition`;
- qualification outcome: `ready`, `safely_blocked_for_migration`, or
  `invalid`.

The vector also records exact artifact, parent, dependency, review, migration-
contract, evaluator-version, and semantic receipt identities. Volatile request
IDs, timestamps, and trace IDs are excluded from the canonical signature.
Derived labels may summarize the vector but never replace it. A rebuild receipt
is an event; freshness means the resulting projection is bound to the exact
current baseline, dependency hashes, and evaluator version.

### 5.2 Transition

A transition defines:

- stable transition ID and requirement/source references;
- actor and intent: `system`, `human_decision`, `test_fixture_input`,
  `observation`, `idempotent_retry`, or `repair_action`;
- allowed source states;
- command or API entrypoint;
- preconditions and required confirmations;
- expected next-state relation;
- permitted writes and forbidden effects;
- idempotency and rollback behavior;
- observable progress keys;
- whether it is advertised as recovery, its root blocker, required external
  inputs, and its recovery rank;
- possible typed failures and recovery transitions.

Eligibility is command-specific and bound to
`command_id + canonical_snapshot_hash + evaluator_version`. If inputs change
between eligibility observation and command admission, the only valid mismatch
is a typed `stale_precondition` with no partial effect.

### 5.3 Independent oracle

The qualification model must not use the production eligibility function to
calculate expected reachability. The expected graph is an independent,
declarative contract. The harness executes real production commands and
compares observed states and effects with that contract.

Production code should still use one shared domain evaluator for presentation
eligibility and command admission so those two runtime paths cannot drift. The
independent qualification oracle verifies that shared evaluator end to end.

### 5.4 Progress, cycles, and quiescence

State change alone is not progress. The explorer uses a canonical progress
signature, closed non-terminal strongly connected component detection, and a
well-founded rank for actions advertised as repair. A deterministic repair must
decrease recovery rank or terminal distance. A typed no-progress result is
allowed only when it is not presented as a successful repair.

Only a receipt bound to an exact idempotency key and snapshot/artifact hash that
completes a previously pending obligation may advance the progress signature.
Duplicate acknowledgements, audit-only UUIDs, and retry receipts do not.

Read-only observations and valid idempotent no-ops may preserve the signature.
For asynchronous commands, the domain contract must define an `effect_pending`
state and deterministic quiescence rule; otherwise the Phase 1 commands are
treated and verified as synchronous.

### 5.5 Blockers and advertised recovery

Every blocked state exposes at least one typed root blocker. Derived blockers
such as `projection_stale` and `rebuild_ineligible` trace to that root blocker.
Each root blocker identifies a recovery action or the exact human/external
input contract. An advertised recovery cannot be a member of a closed
non-terminal component.

### 5.6 Historical support policy

Every artifact schema/capability previously accepted by production is a
supported historical start unless an explicit, auditable quarantine policy
marks it unsupported. Parseability, retained historical review, activation
compatibility, and rebuild compatibility are separate decisions.

New artifacts carry an unambiguous capability/version discriminator. Missing
historical discriminators are classified from immutable facts only; ambiguity
becomes `unknown_or_unsupported` and fails closed. A semantic contract change
requires both a discriminator for new artifacts and a compatibility, migration,
or quarantine rule for every accepted historical capability.

## 6. Finding taxonomy

| Finding | Meaning |
| --- | --- |
| `FLOW-DEAD-END` | Non-terminal supported state has no legal outgoing transition. |
| `FLOW-LIVELOCK` | A transition or cycle repeats without semantic progress. |
| `UNREACHABLE-SUCCESS` | A supported start state cannot reach an accepted terminal state. |
| `SCHEMA-SEMANTIC-DRIFT` | A schema version accepts artifacts with incompatible behavioral capabilities. |
| `VERSION-TRAP` | Historical data parses but cannot be upgraded or used. |
| `MIGRATION-MISSING` | A supported historical state requires a migration that is absent or unexecutable. |
| `HIDDEN-PREREQUISITE` | A recovery path depends on data the current workflow cannot produce. |
| `PREDICATE-DIVERGENCE` | Eligibility/readiness and actual command admission disagree. |
| `PARTIAL-EFFECT` | Failure leaves an invalid subset of writes or refs committed. |
| `RECOVERY-GAP` | Restart, retry, rollback, or idempotent replay cannot restore a valid state. |
| `DEPENDENCY-SPLIT-BRAIN` | Upstream identity changes while downstream artifacts disagree on freshness. |
| `FORBIDDEN-EFFECT` | Candidate qualification performs runtime, safety, outbound, private, or hardware effects. |
| `COVERAGE-GAP` | A required branch, historical version, transition, or invariant lacks executable evidence. |

## 7. Phase 1 — Permission vertical slice

### 7.1 Deliverables

- A sanitized historical legacy Permission fixture.
- A deterministic failing regression that reproduces the known livelock.
- An independent, orthogonal Permission state-vector and transition model.
- A finite-graph reachability/SCC explorer that emits the shortest
  counterexample; command execution remains bounded but reachability is not
  inferred merely from exhausting a depth limit.
- A real FastAPI/domain-command harness using a temporary workspace.
- A machine-only witness from legacy state to a typed, human-actionable
  migration offer.
- A second witness that supplies explicitly synthetic human inputs and review,
  then reaches a hash-bound fresh/ready state without silently inferring day
  ends.
- Focused checks for command/snapshot eligibility consistency, stale
  preconditions, lineage invalidation, idempotency, restart/partial-write
  recovery, forbidden effects, and one deliberate mutation canary.
- An immutable closure packet containing the oracle, fixture and supported-
  start manifest hashes, evaluator version, transition/effect traces,
  counterexample, SCC result, fault evidence, and mutation evidence.

### 7.2 Required Permission combinations

The explorer must represent, at minimum:

- no baseline;
- legacy candidate and legacy reviewed/current baselines;
- missing, conflicting, and complete migration inputs;
- proposal-capable candidate, reviewed, current, and superseded baselines;
- fresh, stale, absent, and interrupted/orphaned projections;
- current and stale baseline-review bindings;
- migration required, candidate, review pending, accepted, and blocked;
- policy review pending, current, stale, and not required;
- command-specific eligible, blocked, and stale-precondition admissions;
- ready, safely blocked for migration, corrupt, unsupported, invariant-breach,
  and write-in-doubt outcomes.

### 7.3 Acceptance

1. The uncorrected historical sequence is mechanically classified as a closed
   non-terminal livelock, with HTTP 200 excluded from the progress definition
   and a shortest counterexample containing state, blocker, capability, and
   effect identities.
2. State extraction independently represents reviewed legacy capability,
   missing inputs, stale projection, blocked rebuild, old review binding,
   migration status, and zero forbidden effects at the same time.
3. For the same command/snapshot/evaluator identity, read-side eligibility and
   actual command admission agree. Upstream replacement yields only typed
   `stale_precondition` and no partial write.
4. Missing proposal/timing inputs return a typed root blocker or explicitly
   incomplete migration draft. They do not create a semantically identical
   artifact/receipt that is counted or advertised as repair progress.
5. Machine-only exploration safely reaches a complete human-input contract;
   then explicit synthetic human inputs, immutable candidate creation, exact-
   hash review, activation, rebuild, and policy review/not-required evidence
   reach `ready`. `migration_required` alone is never reported as ready.
6. Changing any reviewed semantic field, capability, source/current dependency
   hash, or migration-contract version invalidates the appropriate review,
   projection, and policy bindings without silent rebind or legacy mutation.
7. No supported historical start has a closed non-terminal SCC. Every root
   blocker has a recovery contract and every advertised deterministic repair
   lowers recovery rank or returns typed no-progress without a success claim.
8. Accept, migration accept, and rebuild survive same-key retry, lost response,
   injected durable-write interruption/restart, and upstream replacement
   without duplicate semantic receipts, mixed parents, orphan projections, or
   write-in-doubt reported as fresh.
9. Per-transition effect traces prove the allowlist inside an isolated
   workspace and zero runtime safety, outbound, hardware, real-workspace,
   private-data, or qualification-only decision-bypass effects.
10. The original behavior fails, the corrected behavior passes, and deliberate
    predicate/progress/review-binding mutation canaries fail again. Codex and
    GPT Pro both review and agree on the same immutable Phase 1 closure packet.

### 7.4 Implemented Phase 1 evidence

Phase 1 is implemented as a focused vertical slice and is undergoing rev3 joint
closure review. GPT Pro returned `AGREE_WITH_CHANGES` on rev1 and rev2 and
explicitly withheld Phase 2 authorization. Rev2 closed the five substantive
implementation/evidence gaps; rev3 corrects the remaining packet-lineage
metadata and forces the interrupted-rebuild production replay through policy
review to an accepted terminal. It deliberately remains under
`tests/qualification/`; Phase 2 will extract the reusable engine rather than
allowing the Permission model to become the generic engine by accident.

Implemented qualification surfaces:

- `tests/qualification/contextual_permission_phase1.py` contains the independent
  state extractor, canonical progress signature, reachability/SCC analysis,
  shortest counterexample, predicate/invariant/forbidden-effect findings, and
  project-tree effect tracing. It does not import or call the production rebuild
  admission evaluator. Projection and policy freshness are independently
  invalidated when review lineage or current dependency evidence is stale.
- `legacy_sparse_livelock_trace.json` preserves the uncorrected HTTP-200/no-write
  livelock with state, blocker, capability, and effect identities.
- `supported_state_catalog.json` covers the required orthogonal axes and declares
  every supported start. `supported_state_replay_manifest.json` binds all seven
  declared starts to named executable tests that invoke real FastAPI or domain
  commands. Each supported start reaches `ready` or the explicitly bounded
  projection-fresh/policy-pending recovery state without a closed non-terminal
  SCC.
- The real FastAPI harness starts from a sanitized pre-discriminator reviewed
  legacy artifact, extracts the same canonical command snapshot as production,
  and proves the machine-only migration contract.
- The explicit-input witness adds synthetic reference timing plus a separate
  pre-candidate day-end decision contract. Each selected target binds an input
  ID, actor, decision reference, and SHA-256. Automatically inferred targets
  remain proposals and make `review_ready=false`; they cannot be activated.
  The witness then creates an immutable candidate, accepts the exact
  day/uncertainty/handoff set, rebuilds against the observed
  snapshot/evaluator, reviews the exact ordered Permission rule-node set, and
  reaches Dashboard `status=ready`.
- Attempt-level write instrumentation wraps every production append/replace
  primitive before execution. The allowlist therefore records transient
  transaction journals even when final-tree diffs would hide them, covers all
  Phase 1 commands, idempotent retries, injected interruption and recovery, and
  rejects canonical-store or outside-workspace writes. Response flags prove
  zero runtime-safety, outbound, external-send, or hardware effects.

Corrected production contracts discovered by the qualification slice:

- new baseline artifacts carry `legacy_sparse.v1` or
  `ref_gpx_proposal.v1`; new legacy drafts cannot be activated;
- missing timing returns a typed migration draft and never claims repair
  progress;
- read-side rebuild admission and command admission share one evaluator, while
  the command must echo the observed canonical snapshot hash and evaluator
  version;
- an upstream hash replacement returns
  `projection_rebuild_stale_precondition` before any derived write;
- rebuild uses a durable pending journal. An interrupted multi-file write is
  blocked as `contextual_permission_projection_write_in_doubt` and only the
  exact idempotent command may roll it forward after restart;
- Permission rule review is an explicit exact-node-set, source-hash-bound,
  idempotent command. Its immutable receipt is validated on every ready
  projection load;
- selected baseline, candidate, timing, baseline-review receipt, rules, and
  rules-review receipt bindings are revalidated before a projection can report
  ready;
- reviewed capability, source baseline hash, current timing dependency hash,
  and migration-contract version have separate mutation witnesses. Each breaks
  review, projection, and policy readiness in both the production path and the
  independent oracle;
- baseline activation now uses its own durable transaction journal before the
  first reviewed-baseline, receipt, log, project-pointer, or stale-marker write.
  A crash at the activation boundary reports
  `baseline_activation_write_in_doubt`; only the exact same-key command may
  validate and roll the complete transaction forward.

Current executable evidence:

| Gate | Evidence | Result |
| --- | --- | --- |
| Phase 1 focused qualification | `pytest tests/qualification/test_contextual_permission_phase1.py -q` | 26 passed |
| Permission domain/API regression | `pytest tests/test_scout_contextual_permission_workbench_api.py tests/test_scout_contextual_permission_workbench.py tests/qualification/test_contextual_permission_phase1.py -q` | 78 passed |
| Python static checks | `ruff check` on the changed Permission and qualification modules | pass |
| Dashboard request contract | focused Dashboard pytest; rev1 also recorded a live local DOM inspection | snapshot, evaluator, and guard present |
| Phase 1 closure packet rev1 | `docs/evals/dashboard-internal-qualification-phase1-closure.json` | historical; GPT Pro returned `AGREE_WITH_CHANGES` |
| Phase 1 closure packet rev2 | `docs/evals/dashboard-internal-qualification-phase1-closure-rev2.json` | historical; GPT Pro found ambiguous predecessor hash-domain metadata and one non-terminal production replay |
| Phase 1 closure packet rev3 | `docs/evals/dashboard-internal-qualification-phase1-closure-rev3.json` | emitted; canonical hash is recorded inside the packet |
| Codex Phase 1 verdict | rev3 AC-01 through AC-10, predecessor-lineage, and accepted-terminal audit | `AGREE` |
| GPT Pro Phase 1 verdict | exact rev3 canonical packet review | `AGREE`; blocking gaps `NONE`; Phase 2 authorization `YES` |

## 8. Phase 2 — Reusable qualification engine

### 8.1 Deliverables

- Reusable typed contracts for state, transition, invariant, observed effect,
  counterexample, and finding.
- Bounded graph exploration and shortest-counterexample reporting.
- Historical artifact and workspace fixture corpus with provenance.
- Schema/capability compatibility and migration checks.
- Decision-condition coverage using exhaustive tables for small high-risk gates
  and pairwise/bounded generation for larger state spaces.
- Failure injection for partial writes, hash replacement, idempotency reuse,
  concurrency, and restart recovery.
- Mutation canaries proving each critical invariant can fail.
- Internal JSON/JUnit/text outputs and non-zero process status on blocking
  findings.

### 8.2 Required invariants

- Every supported non-terminal state reaches an accepted terminal or explicit
  executable migration state.
- Every semantic schema change has a version/capability bump or migration.
- Every new gate input is tested true, false, missing, invalid, and in the
  agreed combinations.
- API/readiness predicates and actual commands agree under unchanged inputs.
- Idempotent retries do not duplicate effects; conflicting reuse fails closed.
- Interrupted transitions recover or roll back without split-brain refs.
- No qualification path crosses candidate/runtime safety boundaries.

### 8.3 Acceptance

- The Permission model is implemented only through reusable engine contracts,
  not special-cased test control flow.
- Deliberate mutants for schema drift, hidden prerequisites, predicate drift,
  partial writes, and forbidden effects are detected.
- Engine self-tests cover success, counterexample minimization, bounded-search
  exhaustion, and invalid model definitions.
- GPT Pro and Codex both agree on the Phase 2 engine and evidence.

### 8.4 Proposed Phase 2 architecture

Phase 2 generalizes only the mechanisms proved necessary by canonical Phase 1
packet `d9ffea5e169c874522bfe2da71244d10907b88b12301766450f661d0c7af84ed`.
The Phase 1 Permission domain facts remain a domain adapter; they do not become
generic engine assumptions.

```text
[x] Phase 1 Permission proof
          |
          v
[ ] Declarative domain model --------> [ ] finite explorer / SCC / shrinker
          |                                      |
          |                                      v
[ ] independent oracle <---------- [ ] expected states + counterexamples
          ^                                      |
          |                                      v
[ ] sanitized fixture -> [ ] production adapter -> [ ] observed trace/effects
          |                                      |
          +----------> [ ] compatibility          +--> [ ] fault controller
                       [ ] decision coverage       +--> [ ] mutation runner
                                  \                /
                                   v              v
                              [ ] one typed report
                               JSON / JUnit / text
```

The dependency direction is enforced:

- generic contracts, explorer, compatibility, coverage, effects, mutation, and
  reporting modules import no Dashboard production package;
- domain models may import generic contracts but not production evaluators;
  oracle predicates live in an oracle module that cannot import the production
  adapter, while the adapter cannot import the oracle;
- production adapters may call real APIs/domain commands and return bounded
  observations, but cannot define expected outcomes;
- every adapter observation crosses an immutable `ObservationEnvelope`. Each
  field path is classified as `raw_persisted_fact`, `command_response_claim`,
  `exact_identity`, `attempted_effect`, or `volatile_metadata`. Production
  eligibility, readiness, blocker, recovery, capability, and freshness labels
  are response claims: the report may compare them with the oracle, but the
  oracle may not consume them to derive its expectation;
- the domain model and oracle may not import production DTOs, generated
  semantic schemas, defaults, classifiers, decision constants, or helper
  functions. Raw facts are decoded into an independent qualification schema;
- reporters consume typed findings only and cannot change pass/fail status;
- the engine never discovers or writes to an active workspace. A run requires
  a fixture factory that returns a newly created temporary root or an explicit
  read-only snapshot adapter.

### 8.5 Reusable contracts

The reusable surface will contain immutable typed contracts for:

- `QualificationRunManifest`: run ID plus hashes or exact identities for the
  engine, model, oracle, adapter, production revision, fixtures, historical
  inventory, effect surface, search bounds, decision tables, fault and
  concurrency schedules, mutant manifest, configuration, deterministic clock/
  seed, and Phase 1 prerequisite;
- `ObservationEnvelope`: provenance-classified fields, source artifact or
  command identity, raw payload hash, declared field inventory hash, and the
  adapter code identity;
- `StateVector`: domain ID, stable state ID, semantic axes, root blockers,
  parent/evidence identities, progress signature, accepted-terminal flag, and
  forbidden effects;
- `TerminalSpec`: one of `ready`, `safe_external_action_required`, or
  `quarantined`, plus typed external-input/operator obligations and a Boolean
  that is true only for `ready`;
- `TransitionSpec`: actor/intent, allowed starts, command ID, expected relation,
  advertised-repair rank, allowed effect patterns, typed failure outcomes, and
  idempotency/fault obligations;
- `DomainModel`: contract version, supported starts, accepted terminals,
  state/transition registries, invariant set, fixture manifest, capability
  registry, observation-to-state projection, axis completeness declaration,
  and search bound disclosure;
- `ObservedTransition`: exact source/target observations, command/snapshot/
  evaluator identities, status, write attempts, final-tree effects, receipt
  identities, and typed failure;
- `ObligationSpec` and `ObligationResult`: stable obligation ID and kind,
  required replay/evidence, execution status, finding attribution, and exact
  covered model element;
- `EffectSurfaceManifest`, `FaultSpec`/`FaultResult`, and
  `ConcurrencyScheduleSpec`/`ConcurrencyScheduleResult`: complete applicable
  effect entrypoints, injected yield/failure points, fresh-instance recovery,
  conflict schedules, and observed results;
- `HistoricalCapabilityInventory`: provenance-bound discovery sources,
  discovered schema/capability combinations, declared disposition, and
  reconciliation result;
- `MutationSpec` and `MutationResult`: exact mutation site/change, activation
  witness, exercised obligation, expected finding or declared detection mode,
  and observed attributed result;
- `Finding` and `Counterexample`: stable finding code, severity, requirement
  refs, minimized state/transition path, mismatched identities/effects, and
  deterministic reproduction command;
- `QualificationReport`: packet prerequisites, coverage inventory, findings,
  unresolved/unsupported states, mutations killed/survived, fault results,
  resource telemetry, run-manifest hash, and one authoritative blocking
  verdict.

Model-definition validation fails before exploration when IDs are duplicated,
transitions reference unknown states, a supported start is absent, a `ready`
terminal has any outstanding obligation, a non-ready terminal has an
immediately executable machine-repair transition, a root blocker has no
recovery or explicit quarantine, an effect surface is incomplete, component
identities disagree with the run manifest, or a reporter/output path would
escape its provided result root. A `safe_external_action_required` or
`quarantined` terminal may carry typed human input, operator recovery, or export
obligations, but it never satisfies readiness.

The observation-to-state projection must reject an observed semantic value
that is absent from the declared axis inventory. It may not coerce an unknown
production value into the nearest known state. Every ignored observation field
must be listed as non-semantic with a reason; volatile fields are normalized
only after that declaration is validated.

The declared observation inventory contains every field path and classifies it
as semantic, identity-only, effect-only, volatile, or ignored with rationale.
Projection-equivalence validation is fail-closed: two observations that differ
in any contract-relevant field cannot collapse to the same `StateVector` or
progress signature unless a named, independently tested equivalence rule proves
that difference irrelevant. An omitted-semantic-field canary must be detected.
All input reads are confined to the new execution root or an exact-hash
read-only snapshot. A mutable or hash-mismatched snapshot is invalid; mutating
commands require a copied isolated execution root.

### 8.6 Exploration and coverage semantics

- Finite declarative graphs use complete reachability and Tarjan/Kosaraju SCC
  analysis, not a depth-limited success claim. The shortest counterexample is
  deterministic under stable transition order.
- Production execution is bounded separately. A bound exhaustion is
  `COVERAGE-INCOMPLETE`, never pass. The report records the unexecuted state or
  transition IDs and the configured bound.
- Small decision tables are exhaustively enumerated. Larger tables use a
  deterministic pairwise generator plus mandatory critical combinations.
- High-risk Boolean admission gates additionally require MC/DC evidence: for
  every condition, two observations differ only in that condition and change
  the decision. An infeasible pair must carry an explicit constraint witness;
  it cannot be silently omitted.
- Each gate input is represented in valid, false, missing, and invalid form when
  its type permits those states. Capability/version fields also require current,
  historical, unknown, and explicitly quarantined cases.
- Expected relations compare semantic axes and immutable identities. Volatile
  timestamps, UUIDs, formatting, and request ordering cannot satisfy progress.
- The declarative graph and the production replay inventory are separate
  coverage ledgers. Graph reachability never substitutes for executing every
  supported production start, and one production replay cannot satisfy two
  distinct start IDs unless the model declares and validates their equivalence.
- Production coverage is transition-oriented as well as start-oriented. Every
  required declarative transition, advertised recovery, typed blocker
  resolution, compatibility/migration path, and accepted terminal has a stable
  mapping to a real production replay or an explicit infeasibility/quarantine
  witness. Missing or exhausted mappings are blocking
  `COVERAGE-INCOMPLETE`.
- Equal-length shortest counterexamples use a canonical stable-ID ordering, so
  the same run manifest produces byte-stable counterexample selection.

### 8.7 Compatibility, fault, effect, and mutation layers

The capability registry distinguishes schema version from semantic capability.
An immutable `HistoricalCapabilityInventory` discovers and reconciles the
locally authoritative sources: production literal/schema contracts and
classification paths, declared release or migration manifests, retained
accepted fixtures, and predecessor closure packets. Source identities and
discovery rules are bound to the run manifest. A discovered/declared mismatch
blocks before production execution. Every accepted historical capability must
be one of:

- directly supported;
- connected by an executable migration path to a supported capability; or
- explicitly quarantined with a stable reason, detection rule, and operator
  recovery/export contract.

Missing coverage is a blocking `COVERAGE-GAP`; parseability is not support.

The generic production harness combines a static call-site inventory with
runtime interception against an `EffectSurfaceManifest`. Applicable surfaces
include filesystem reads plus mkdir/open/temp creation/write/flush/fsync/link/
rename/replace/delete and locks; canonical stores/databases; sockets and HTTP
clients; subprocesses; runtime/safety adapters; outbound senders; and hardware
interfaces. Every attempt is recorded before invocation and classified by root
and effect class. An undeclared or unclassified attempt blocks. Negative
call-site/import audits and deliberately injected forbidden-effect canaries are
required for surfaces declared absent.

Fault obligations are derived from the effect surface. They cover before,
inside, and after each relevant effect primitive, including partial append,
temporary-artifact, fsync/link, atomic-replace, delete, journal, pointer, and
cleanup failures where applicable. Each runs from a fresh process/workbench and
must end in the complete pre-state, complete post-state, or an exact-key
recoverable typed write-in-doubt state; an unclassified intermediate state
blocks.

Concurrency checks use a domain-declared conflicting-command matrix and
deterministic yield points at admission, journal creation, every durable write,
pointer activation, cleanup, and recovery. Required schedules cover same
snapshot/same key, same snapshot/different keys, changed upstream identities,
recovery racing a new command, and every declared conflicting pair at each
applicable shared-state yield. The report records the schedule, snapshots,
attempted effects, winner or typed rejection, and fresh-instance result. An
uncovered required schedule is a blocking coverage gap; a flaky stress loop is
supplementary only.

Mutation execution is differential, deterministic, isolated per mutant, and
attributed through `MutationSpec`/`MutationResult`. Activation proof must show
that the exact mutated site was exercised. A kill requires the declared stable
finding ID/class or declared detection mode; an unrelated compile error, runner
crash, fixture invalidity, or incidental test failure is not a kill. Phase 2
must kill at least these generic mutant classes:

- schema/capability drift without migration;
- hidden prerequisite or removed recovery edge;
- read/command predicate divergence;
- progress credited for a volatile-only change;
- partial write marked fresh;
- stale review or dependency marked current;
- forbidden store/outside/runtime/outbound/hardware effect;
- supported start removed from the manifest;
- non-accepted replay terminal mislabeled as pass.

A survived required mutant is a blocking `MUTATION-SURVIVED`, not test debt.

### 8.8 Outputs and executable evidence

Phase 2 adds a contextual-Permission-only internal runner while preserving the
Phase 3 plan to expand `--all` across Dashboard domains. The runner accepts an
explicit output directory and emits:

- canonical JSON for machine review and closure hashing;
- JUnit XML with one case per requirement/coverage obligation;
- concise text with the verdict, shortest counterexamples, uncovered items,
  survived mutants, and reproduction commands.

Canonical JSON is authoritative. Each run uses a unique empty result directory,
removes or rejects stale outputs before execution, writes canonical JSON through
a temporary file and atomic replacement, then rereads, schema-validates, and
hash-verifies it. Only that finalized report may produce JUnit and text. JUnit
and text are verified projections: each
must preserve the canonical verdict plus the exact stable IDs and severities of
all blocking findings, coverage gaps, survived required mutants, and missing
fault obligations. They need not reproduce every telemetry field. A reporter
cannot suppress or downgrade a canonical finding.

Exit status is `0` only when every required obligation completed, there are no
blocking findings or unknown coverage, every required mutant was attributed and
killed, all required faults/concurrency schedules ran, every supported
production replay reached its declared terminal, and canonical JSON was
atomically finalized, reread, schema-validated, and hash-verified. Exit `1`
means a complete valid run whose finalized canonical report contains blocking
findings. Exit `2` means any invalid or incomplete model, fixture, execution,
report, projection, or runner state, whether failure occurred before or after
production execution began. Reporter projection tests ensure no format can hide
a canonical finding.

Phase 2 implementation may begin only after both reviewers agree on this
design. Its closure packet must preserve the Phase 1 rev3 canonical prerequisite
identity and contain:

- generic engine module and self-test hashes;
- Permission adapter and fixture-manifest hashes;
- independent-oracle import audit;
- model-definition negative tests;
- exhaustive/pairwise/MC-DC coverage evidence;
- complete production replay inventory;
- fault-point and attempt-level effect evidence;
- required mutant kill matrix;
- JSON/JUnit/text equivalence and non-zero-exit evidence;
- explicit non-claims for Phase 3 domain coverage and productization;
- exact Phase 1 rev3 semantic-regression evidence: the retained historical
  livelock, independent dual witness, machine-only safe-migration result,
  explicit-input trajectory to ready, both crash/recovery paths, effect
  boundaries, and all required canaries. The prerequisite canonical identity is
  `d9ffea5e169c874522bfe2da71244d10907b88b12301766450f661d0c7af84ed`;
  `migration_required` remains non-ready and any semantic mismatch blocks.

### 8.9 Phase 2 design acceptance clauses

Implementation is authorized only when both reviewers explicitly accept all of
these clauses against the same immutable design packet:

| ID | Required design evidence |
| --- | --- |
| P2D-01 | Generic modules have enforced dependency direction and provenance; oracle/model cannot consume production schemas, classifiers, defaults, constants, or semantic response claims. |
| P2D-02 | Immutable contracts cover run identity, observations, states, terminals, transitions, obligations, effects, faults, schedules, history, mutations, findings/counterexamples, and the authoritative report. |
| P2D-03 | Fail-closed validation rejects undeclared fields, projection collisions, broken graph/recovery/effect/read/output contracts, component identity mismatch, and unknown semantics. |
| P2D-04 | Finite graph exploration is complete and production coverage maps every supported start plus every required transition/recovery/compatibility/terminal; incomplete coverage can never pass. |
| P2D-05 | Decision coverage combines exhaustive small tables, deterministic pairwise plus critical combinations, and MC/DC for high-risk Boolean gates. |
| P2D-06 | Provenance-bound historical discovery reconciles every accepted version/capability to direct support, executable migration, or typed quarantine/non-ready terminal. |
| P2D-07 | Complete effect-surface interception, read confinement, in-primitive faults, fresh-instance recovery, conflict matrix, and deterministic shared-state schedules are report obligations. |
| P2D-08 | Each required mutant has isolated activation proof and exact expected-finding attribution; any unexplained survivor blocks. |
| P2D-09 | Run identity and canonical JSON own the verdict; atomic finalization/reread/validation/hash is required; projections and total exit semantics cannot hide incomplete evidence. |
| P2D-10 | Phase 2 remains Permission-only proof of reuse and exactly replays Phase 1 rev3 semantic outcomes/canaries while making no Phase 3 or productization claim. |

### 8.10 Phase 2 design rev1 review disposition

Immutable rev1 design packet
`eee5d4d5dbbf7a67ddb7a02e2f16ed98c24b58660b21610f82630da5eb79ce04`
is retained as rejected history. GPT Pro returned `AGREE_WITH_CHANGES` and no
implementation authorization. Codex locally confirmed the substantive gaps:
the Phase 1 spec file evolved while all other rev3 artifact hashes remain
intact; the production Permission surface contains lower-level filesystem and
locking effects outside the two Phase 1 wrapper hooks; and accepted capability
knowledge is distributed across production literals/classifiers, fixtures, and
closure packets rather than one reconciled inventory. Rev2 incorporates all
accepted blocking changes above and must receive a fresh joint verdict.

### 8.11 Implemented Phase 2 evidence

Closure rev1 is immutable rejected history. GPT Pro returned
`AGREE_WITH_CHANGES`: P2D-01 through P2D-06 and P2D-09 through P2D-10 were
accepted, while P2D-07 and P2D-08 remained blocked. The missing evidence was a
machine-enforced effect-class reconciliation, complete primitive-by-fault-phase
and command-pair-by-yield matrices, and a distinct required non-recovery
transition-removal mutant. Phase 3 remained unauthorized.

The corrected exact closure is
`docs/evals/dashboard-internal-qualification-phase2-closure-rev2.json`, with
canonical content SHA-256
`76247f4e723ed6cc79144707ce103400d68f180f9ec16ab283d3d328e987c027`
and serialized-file SHA-256
`decf5f20f8e36a88f65e72b5278c323bbf4fc2d1a749d13c93519927e5bf6164`.
Codex's requirement-by-requirement verdict on rev2 is `AGREE`. GPT Pro echoed
the exact canonical identity, returned `AGREE`, accepted P2D-01 through P2D-10,
reported no blocking implementation gap and no remaining claim for Codex to
verify locally, and explicitly authorized Phase 3. Phase 2 therefore has joint
closure and is complete.

The rev2 authoritative isolated run is
`outputs/qualification/contextual-permission-phase2-evidence-v7/result/qualification-report.json`.
It exited `0`, finalized with `verdict=pass` and `complete=true`, and has
canonical content SHA-256
`a7056c72a3ba9633e55e19e695801a03bbfb88335ba5b9a8b6ef993c1f41cc95`.
Its evidence inventory is:

- 142 of 142 source-ref/line/signature effect callsites were classified;
- all seven absent effect classes have both a negative static audit and an
  invocation-before-block runtime canary;
- the fault manifest covers all 39 operation-by-before/inside/after cells:
  27 required executions passed on 27 unique fresh workbenches and all 12
  non-applicable cells carry validated rationales;
- the concurrency manifest derives all 28 schedules from four conflicting
  command pairs and their exact applicable yields; all passed with unique
  execution identities and no write overlap;
- the recovery race uses a genuinely new idempotency key; while a pending
  journal exists, different-key contenders may also reach the exact typed
  pre-lock write-in-doubt terminal instead of waiting on the store lock;
- 11 of 11 mutants activated and were killed with exact attribution, including
  separate recovery-edge and required non-recovery transition-removal sites;
- 41,560 attempted effects, 30 obligations, 10 production/quarantine replays,
  7 invariants, and 120 JUnit cases produced zero finding, unresolved state,
  counterexample, failed obligation, or surviving mutant.

Focused Phase 2 tests are 37 passed. The retained Phase 1 plus Permission
domain/API regression is 78 passed. Ruff, Python compile, canonical/hash and
component-identity recomputation, scoped diff check, and scoped secret-value
scan pass. v6 and closure rev1 remain preserved as the evidence reviewed and
rejected by GPT Pro; v7 and closure rev2 are the only current candidates.

## 9. Phase 3 — Dashboard domain expansion and release gate

### 9.1 Risk order

1. Contextual Permission.
2. Safety / Emergency.
3. Workspace import, Connected Preparation, and publication/recovery.
4. Weather, Map, and Navigation freshness/hash/cache closure.
5. Route Context, Architecture, and Pace.
6. Assistant and tool-planner workflows.
7. Body Index and private-data boundaries.
8. MQTT, Observer, Living, and hardware integration boundaries.

Only implemented behavior enters the model. Preview-only or future behavior is
excluded until it has an executable entrypoint and contract.

### 9.2 Cross-feature dependency DAG

The engine must verify identity and freshness closure through chains such as:

```text
route identity
  -> reference timing
  -> reviewed baseline
  -> permission rules
  -> workbench seed
  -> planned ETA
  -> Safety / Emergency packet
```

An upstream change must either rebuild every affected dependent artifact or
mark it stale with an executable recovery transition. Mixed provenance is a
blocking finding.

### 9.3 Internal command

Planned entrypoint:

```bash
python3 tools/verify_dashboard_internal_qualification.py --domain contextual-permission
python3 tools/verify_dashboard_internal_qualification.py --all
```

The command must never mutate a real workspace. It runs against temporary or
explicit read-only snapshots and returns a non-zero status for blocking
findings, incomplete required coverage, or unverified supported states.

### 9.4 Acceptance

- Every implemented Dashboard domain has a state model, historical/current
  fixtures, complete success trajectory, failure/recovery cases, cross-domain
  boundaries, and mutation evidence proportionate to its risk.
- The full internal command covers every queued model and reports no blocking or
  unknown required item.
- An active-workspace compatibility inventory is read-only and reports no
  unsupported persisted capability before release.
- Focused, cross-domain, and agreed full-suite checks pass.
- GPT Pro and Codex both agree on the Phase 3 coverage and final release gate.

### 9.5 Surface-closure inventory

Phase 3 starts from executable source discovery rather than a manually selected
test list. Immutable `DashboardSurfaceManifest` and
`DashboardExecutableEntrypointManifest` contracts reconcile all of these
sources against the same repository identity:

- every sidebar `data-route` plus its declared maturity in the canonical
  Dashboard HTML;
- every Dashboard API path constructor or literal used by that HTML;
- the matching FastAPI route template and production handler symbol;
- production modules, persisted artifact kinds/schema versions, and tool
  manifests used by the handler or Dashboard loader;
- backend lifespan/startup/import hooks, middleware, dependencies, background
  tasks, WebSocket/SSE handlers, CLI/worker/scheduler/watch callbacks, and
  dynamically registered tools;
- frontend event handlers, timers/animation callbacks, browser storage,
  fetch/WebSocket/EventSource/worker construction, postMessage bridges, and
  data-driven or indirect dispatch tables;
- an explicit disposition for every discovered surface: qualified domain,
  presentation-only shell contract, separately retained runtime Diagnostic,
  or executable-evidence-backed exclusion.

An item marked `preview` is not automatically excluded. Navigation and Observer
enter qualification because executable production entrypoints and contracts
exist. Country Material Pool enters `workspace-lifecycle` because it changes
the provider/default decision state used by Trip Intake; LBS enters
`geospatial-weather-navigation` because it reads project projections and emits
location/map evidence. An exclusion must prove the absence of every executable
semantic, freshness, authorization, external-read, and effect contract, not
merely the absence of writes. Any unmapped, multiply mapped, silently removed,
or newly executable surface is a blocking `SURFACE-INVENTORY-DRIFT` finding.

Discovery operates over closed Dashboard reachability roots: the Dashboard
HTML/bootstrap, Dashboard app/router factories, registered handlers, their
resolved dependencies and callbacks, and tools they can invoke. Every manifest
record carries source ref, line/symbol, entrypoint class, registration site,
reachable target, semantic/effect classification, and domain disposition.
Unknown syntax or unresolved dynamic dispatch is blocking rather than ignored.

The initial domain queue is:

| Domain ID | Dashboard responsibility | Risk tier |
| --- | --- | --- |
| `contextual-permission` | Contextual Permissioning workbench | inherited Phase 2 gate |
| `safety-emergency` | runtime safety reducer/store and Emergency/Living approval sandbox boundaries | 0 |
| `workspace-lifecycle` | trip intake, Country Material Pool, import, preparation, publication, review, and recovery | 0 |
| `geospatial-weather-navigation` | Map, LBS, Weather, imagery/cache/freshness, and Navigation projection | 1 |
| `route-intelligence` | Route Context, Architecture, and Pace advisory projections | 1 |
| `assistant-planner` | Assistant readiness/query planning and tool/effect boundaries | 1 |
| `body-index-privacy` | sanitized Body Index import/merge/dedup/watch lifecycle | 1 |
| `observer-hardware-boundary` | Observer/MQTT parsing and no-unapproved-hardware/outbound boundary | 1 |
| `dashboard-shell-control` | Overview, evidence timeline, debug/readiness, settings validation, navigation, and runtime-Diagnostic separation | 2 |

### 9.6 Per-domain qualification contract

Every queued domain receives an immutable `DashboardDomainSpec` containing:

- repository-bound production source refs, UI routes, API route templates, and
  persisted capability/artifact inventory;
- independent observation fields and provenance classifications; production
  responses cannot define the expected oracle value;
- finite state axes, supported start states, transitions, terminal classes,
  root blockers, and monotonically decreasing recovery ranks;
- current, known-historical, malformed, unknown-version, interrupted-write,
  and stale-upstream fixtures where applicable;
- at least one production-backed success trajectory, one typed failure or
  quarantine trajectory, and every advertised recovery trajectory;
- domain invariants, effect/read boundaries, privacy constraints, decision
  coverage obligations, fault obligations, concurrency conflicts, and required
  mutants proportionate to the declared risk tier.

Tier 0 domains require transition-complete replay, full applicable
effect-operation-by-fault-phase coverage, and every conflicting-command by
shared-yield schedule. Tier 1 domains require transition-complete state and
recovery coverage, complete discovered effect-class reconciliation, faults for
every durable publication primitive, and concurrency for every shared writer.
Tier 2 requires complete surface, validation, no-startup-write, and boundary
coverage; it does not inherit artificial durability/concurrency obligations
when discovery proves no durable writer exists. A `not_applicable` cell needs an
operation/phase-specific rationale and is validated as strictly as an executed
cell.

An immutable `DomainRiskProfile` prevents coverage downgrade. Source discovery
and domain contracts populate runtime/safety authority, privacy sensitivity,
durable publication, shared writers, external effects, human confirmation,
background/watch execution, and downstream-decision-impact axes. The engine
derives the minimum tier mechanically: safety authority or a shared durable
authority writer is Tier 0; privacy-sensitive, durable, confirming, background,
externally effectful, or downstream-decision surfaces are at least Tier 1; only
evidence-proved pure read/presentation/local-shell logic may be Tier 2. A tier
below the derived floor is invalid. Safety, privacy, admission, confirmation,
and authority gates retain the accepted Phase 2 exhaustive, pairwise, critical,
and MC/DC decision obligations regardless of tier. Every `not_applicable` cell
binds its risk profile, exact absent-callsite inventory, and an independently
executable infeasibility witness.

Contextual Permission is not reimplemented. The exact Phase 2 closure and its
current source-bound report are prerequisites, and the Phase 3 aggregate reruns
its retained semantic gate. If a reviewed harness-only correction rotates a
source hash, an immutable addendum must bind the old joint closure, the exact
new report, and a semantic hash that normalizes only the declared source-bound
identity fields. Any other report delta is invalid. A per-domain pass cannot
dilute or replace the accepted Phase 2 evidence.

### 9.7 Cross-domain identity and freshness closure

An immutable, source-derived `CrossDomainDependencyManifest` is built from
artifact producers/consumers, command read/write sets, admission snapshots,
parent/hash fields, persisted identities, tool plans, and freshness/invalidation
code. Each `DependencyEdgeSpec` records producer artifact, consumer domain,
join identities, freshness rule, invalidation trigger, allowed stale terminal,
and whether the edge may influence runtime safety truth. The declared DAG must
exactly reconcile with discovered edges; unknown, duplicate, unresolved, or
omitted dependencies invalidate the run. Edge expectations are derived from raw
identities independently of production freshness claims. At minimum, the
manifest covers:

```text
workspace publication identity
  -> route identity/hash
      -> route context + reference timing
      -> weather / imagery / navigation / architecture / pace
          -> reviewed mission baseline
              -> contextual permission rules + forward projection
                  -> planned ETA + Safety / Emergency review packet

Body Index -> Pace advisory only
Observer evidence -> deterministic safety admission only
Assistant output -> candidate/advice only
```

For every edge, Phase 3 executes unchanged, upstream-changed, consumer-missing,
consumer-stale, wrong-parent, and mixed-generation cases. An upstream change
must produce a fully rebuilt consumer with matching identities or an explicit
stale/quarantined terminal with a real recovery transition. Reusing a fresh
flag with mismatched hashes, mixing old and new parents, skipping an
intermediate invalidation, allowing Body Index/Assistant evidence to become
runtime safety truth, or letting Observer data bypass deterministic admission
is blocking.

Every shared cross-domain edge also derives deterministic producer/consumer
interleavings at admission, durable publication, pointer activation,
invalidation, recovery, and consumer read. Sequential edge cases cannot stand
in for these races.

### 9.8 Effects, privacy, and safe execution

All replays use unique temporary workbenches and unique result roots. The
runner never defaults to the configured active workspace and never reads `.env`,
browser/account state, raw GPX, raw health exports, exact private coordinates,
or unrelated user artifacts. Static discovery and invocation-time interception
classify filesystem reads/writes, databases/stores, HTTP clients, sockets,
subprocesses, runtime/safety adapters, outbound senders, and hardware
interfaces. Every attempted effect is recorded before invocation.

Allowed production writes are confined to the current synthetic execution root.
Network, real database, subprocess, outbound, hardware, production-state, and
runtime-safety-truth effects are blocked before invocation unless an exact
synthetic loopback primitive is declared by the domain contract. Absence of an
effect class requires both a static negative audit and an invocation-blocked
runtime canary. Unclassified effects, root escapes, source reads outside the
declared corpus, unsafe fields in public projections, or missing canaries make
the run invalid.

An immutable `AuthorityBoundaryManifest` enumerates raw, candidate, advisory,
normalized, sanitized, reviewed, approved, and runtime-authoritative artifact
classes, plus every publication, runtime-state, safety-truth, outbound, and
hardware sink. Its allowed source-to-sink graph is closed and source-derived.
Every confirmation or admission receipt binds the exact subject identity and
content hash, capability, generation, actor, policy/evaluator version, scope,
and idempotency identity. Any bound subject or policy change makes the receipt
stale; a generic boolean or old receipt cannot authorize a new subject.

Synthetic private-data sentinels are injected at every prohibited field source.
The verifier captures persisted artifacts, findings, canonical JSON, JUnit,
text, logs, and exception messages and proves that no sentinel propagates to
them. Sanitized bounded derivatives may pass only through their declared
transformation and identity contract.

### 9.9 Fault, recovery, and concurrency coverage

Fault coverage is derived from a total `EffectOperationInventory`, not a fixed
primitive list or global scenario count. Every discovered state-affecting
primitive maps to one normalized operation and before/inside/after cells or to
an exact validated non-applicable cell; a new or unclassified primitive makes
the run invalid. Applicable read/open/mkdir/temp/write/flush/fsync/link/replace/
delete/lock/store operations are the minimum, not a closed whitelist. Every
required cell runs in a fresh process and fresh workbench, proves activation,
and ends in an allowed typed state: unchanged, recoverable with the exact
recovery command, or quarantined/fail-closed. Partial publication may never be
reported fresh.

Concurrency coverage is derived from a source-derived
`CommandConflictManifest`. Each production command records complete read,
write, lock, journal, pointer, receipt, and identity sets from static discovery
plus instrumented production replay; unresolved or inconsistent sets invalidate
the run. Their intersections derive every intra-domain and cross-domain conflict
pair, which is crossed with every applicable admission, journal, durable-write,
pointer-activation, receipt, cleanup, invalidation, recovery, and consumer-read
yield. Same-key retry, different-key command, stale-snapshot command,
recovery-versus-new-command, import-versus-publication, refresh-versus-read,
and watch-start/stop races enter only where the corresponding domain owns that
shared state. Missing derived cells, reused execution identities, unactivated
schedules, overlapping critical sections, or unexplained outcomes block.

### 9.10 Mutation and anti-false-pass policy

Every mutation is isolated, activated, and killed by its declared stable
finding or detection mode. The required portfolio includes the retained Phase 2
mutants plus domain and cross-domain mutants for:

- removing a required transition or advertised recovery;
- accepting an unknown persisted capability or stale historical format;
- dropping a route/API/symbol from surface reconciliation;
- omitting a dependency edge or stale-propagation step;
- comparing the wrong identity/hash or accepting mixed generations;
- publishing fresh before durable completion;
- bypassing a privacy redaction, effect allowlist, deterministic safety
  admission, explicit-confirmation gate, or candidate-only boundary;
- hiding a failed domain/report projection or returning exit zero for incomplete
  aggregate evidence;
- lowering a mechanically derived minimum risk tier or forging an N/A witness;
- omitting a non-route executable entrypoint, required cross-domain dependency,
  conflict pair, or shared yield;
- reusing a confirmation/admission receipt after its subject or policy identity
  changes;
- accepting a workspace that changes during inventory, or accepting stale,
  foreign-run, or mixed-run per-domain evidence in the aggregate.

An unrelated exception, fixture failure, or test crash is not a mutation kill.
Any survivor blocks closure.

### 9.11 Read-only active-workspace compatibility inventory

`--workspace-inventory PATH` is an explicit opt-in read-only mode. It completely
enumerates the supplied root with no-follow metadata operations while reading
content only from whitelisted metadata/artifact refs. Unknown entries remain
blocking redacted path identities rather than being silently skipped. The
`WorkspaceInventorySnapshot` binds root device/inode/generation, sorted entry
type/device/inode/link-count/size/mtime/ctime/path-digest metadata, permitted
content hashes, and matching before/after seals. Symlinks, hard-linked permitted
metadata, mount crossings, root escapes, concurrent replacement, addition,
deletion, or metadata/content change invalidate the snapshot. It does not ingest
raw route or health payloads. Every discovered persisted capability must reconcile to direct
support, an executable migration, or a typed quarantine/non-ready terminal.
Unknown versions, unsafe refs, missing parent identities, or mixed provenance
block a release invocation.

Construction closure uses a generated synthetic compatibility workspace. A
separate `--release --workspace-inventory PATH` invocation is required before
an actual release and is intentionally not claimed unless the user explicitly
authorizes the active workspace. Release binds every domain run to that exact
sealed snapshot identity and repeats the seal before finalization. Omitting that
private-data-dependent release invocation cannot be represented as production
readiness.

### 9.12 Aggregate command and report identity

The Phase 3 command surface is:

```bash
python3 tools/verify_dashboard_internal_qualification.py \
  --domain DOMAIN --execution-dir UNIQUE_ROOT --output-dir UNIQUE_ROOT
python3 tools/verify_dashboard_internal_qualification.py \
  --all --execution-dir UNIQUE_ROOT --output-dir UNIQUE_ROOT
python3 tools/verify_dashboard_internal_qualification.py \
  --release --workspace-inventory PATH \
  --execution-dir UNIQUE_ROOT --output-dir UNIQUE_ROOT
```

`--all` executes every discovered queued domain, the cross-domain DAG suite,
surface/API reconciliation, aggregate mutations, and retained Phase 1/2 gates.
It emits one canonical aggregate JSON plus per-domain canonical JSON, JUnit, and
text projections. The aggregate manifest binds source, spec, fixture,
dependency, effect, mutation, per-domain report, and prerequisite hashes.
Outputs are finalized atomically, reread, schema-validated, and hash-verified
before exit `0`. Exit `1` means complete evidence with a blocking finding. Exit
`2` means invalid/incomplete evidence, unsafe configuration, missing coverage,
projection mismatch, stale component identity, or any partial report. A single
domain failure cannot be omitted from aggregate projections or exit status.

### 9.13 Phase 3 design acceptance clauses

Implementation begins only when Codex and GPT Pro explicitly accept all clauses
against the same immutable design packet:

| ID | Required design evidence |
| --- | --- |
| P3D-01 | Source-derived surface and executable-entrypoint closure maps routes, APIs, handlers, dependencies, middleware, lifecycle/background/CLI/watch callbacks, frontend events/timers/storage/network/dynamic dispatch, production symbols, and persisted capabilities exactly once; semantic/effect exclusions need executable evidence and drift blocks. |
| P3D-02 | Nine domain specs use independent observations and finite state/terminal/recovery contracts with current, historical, malformed, stale, and interrupted fixtures as applicable. |
| P3D-03 | A source-bound hazard profile derives the minimum risk tier and all transition/decision/effect/fault/concurrency/invariant/mutation obligations; downgrade is rejected and each N/A has absent-callsite evidence plus an executable infeasibility witness. |
| P3D-04 | A source-derived producer/consumer inventory exactly reconciles the DAG, enforces parent identity/freshness/rebuild-or-stale closure, blocks wrong/mixed generations, and derives producer/consumer race schedules. |
| P3D-05 | Contextual Permission is an exact retained Phase 2 prerequisite and cannot be weakened by the aggregate adapter. |
| P3D-06 | A source-to-authority-sink manifest enforces safety/privacy/candidate/confirmation/admission boundaries; receipts bind exact subject/policy identities, effects are recorded before invocation, and sentinels prove non-propagation through every output/log/error projection. |
| P3D-07 | A total discovered effect-operation inventory and source/replay-derived command read/write/lock/journal/pointer/receipt/identity sets derive all fault and intra/cross-domain schedule cells; applicable faults use fresh processes/workbenches and every uncovered/unactivated cell blocks. |
| P3D-08 | Domain and cross-domain mutants have isolated activation and exact attribution; tier/N-A, non-route entrypoint, dependency/conflict, receipt staleness, workspace TOCTOU, stale/mixed aggregate, surface, identity, publication, privacy, effect, and reporting false-pass mutants are mandatory. |
| P3D-09 | Explicit active-workspace inventory is a complete read-only metadata-bounded sealed snapshot; unknown entries block, path aliases/mounts/hard links/root escape and concurrent mutation are prevented or detected, and every capability reconciles to support, migration, or quarantine. |
| P3D-10 | `--all` and `--release` have distinct claims; aggregate canonical identity, atomic output, projection parity, and total exit semantics prevent omitted-domain or incomplete-evidence passes. |
| P3D-11 | Closure evidence includes focused domain tests, cross-domain tests, retained Phase 1/2 regressions, source/manifest recomputation, and exact per-domain/aggregate case reconciliation. |
| P3D-12 | Phase 3 remains internal pre-release qualification, separate from runtime Diagnostic UI, and makes no production-readiness, real-workspace, runtime-safety-authority, outbound, or hardware-control claim without the corresponding explicit gate. |

### 9.14 Phase 3 review and closure protocol

The design packet freezes the exact surface inventory rules, domain queue,
dependency graph, risk tiers, report contracts, acceptance clauses, Phase 2
prerequisite identity, and non-claims. After compatible design verdicts,
implementation evidence is frozen in a new immutable closure packet. Codex and
GPT Pro must each disposition P3D-01 through P3D-12 against the exact closure
hash. Any blocker, hash mismatch, uncovered surface, unresolved disagreement,
or surviving mutant keeps Phase 3 incomplete.

### 9.15 Phase 3 design rev1 review disposition

Immutable design rev1 packet
`9bfe427f0c596981f632d587af4400a5f2591ce34cd8e0a59fc8bf5f559b1dc8`
is retained as rejected history. GPT Pro returned `AGREE_WITH_CHANGES`: P3D-02,
P3D-05, P3D-10, P3D-11, and P3D-12 were accepted; P3D-01, P3D-03, P3D-04,
P3D-06, P3D-07, P3D-08, and P3D-09 were blocked. Codex locally confirmed that
the canonical frontend contains non-route event, timer, browser-storage, fetch,
and dynamic-dispatch entrypoints; the backend contains middleware and watcher
callbacks; Country Material Pool changes Trip Intake/provider decision state;
LBS consumes project projection and emits location/map evidence; and several
confirmation request shapes cannot be presumed to bind every subject/policy
identity required by an authority boundary. The rev2 design above accepts every
blocking correction and must receive a new compatible joint verdict before
implementation.

### 9.16 Phase 3 design rev2 consensus

The accepted immutable design is
`docs/evals/dashboard-internal-qualification-phase3-design-rev2.json`, canonical
content SHA-256
`5a3b14b3ea9fd64a086bb106b277140c0bb0ecc5ef3d6ed8415e347f43736112`
and serialized-file SHA-256
`938f3693aefb1262c92057405cb15aa5d8390b8f67721eebe7e1f3e17a993540`.
Codex and GPT Pro each returned `AGREE` for P3D-01 through P3D-12. GPT Pro
reported no blocking design gap, no remaining local claim for Codex to verify,
and explicitly authorized Phase 3 implementation. Implementation must use this
exact rev2 contract; rev1 remains rejected history.

### 9.17 Phase 3 implementation and frozen closure candidate

Phase 3 is implemented as an internal test/tool surface. The entrypoint is
`tools/verify_dashboard_internal_qualification.py`; its implementation lives in
the `tests/qualification/phase3_*.py` modules and has no runtime-Diagnostic UI
dependency. It supports a focused domain invocation, a synthetic construction
`--all` invocation, and a distinct `--release --workspace-inventory PATH`
invocation. The release form was intentionally not run because this closure
does not claim a real-workspace or production gate.

The first two persistent all-domain attempts were preserved as fail-closed
evidence:

1. `dashboard-phase3-evidence-v1` exited `2` because the retained Phase 2
   different-key concurrency schedule allowed the operating system to choose a
   different winner, changing the canonical receipt detail.
2. The scheduler was made deterministic only after both contenders crossed the
   admission barrier. `dashboard-phase3-evidence-v2` then exited `2` because
   the corrected adapter source hash properly rotated the source-bound Phase 2
   report identity.

The immutable determinism lineage addendum is
`docs/evals/dashboard-internal-qualification-phase2-determinism-addendum-rev1.json`,
canonical SHA-256
`94f6e5605b58b27128071a291ace179e02adcfd46711011bd5f5ee1f28976239`
and serialized SHA-256
`9a44fc9189a2554d5b3b86e526bee633187274f2e67753e440871792b95e9f7d`.
It leaves the joint Phase 2 closure and v7 report immutable, binds the exact
current v8 report
`0ed412162d4253d1b8e0d16b920430c789014d3d0535117130349b1bda10e98d`,
and proves that both reports normalize to the same semantic SHA-256
`3f7c719847c3f5da8069b00b591fdce1b9d7057e2dc30d95e394236cad72e071`
when and only when artifact identity, run-manifest identity, and the adapter
source digest are normalized. All other fields are exactly equal.

The authoritative construction run is
`outputs/qualification/dashboard-phase3-evidence-v3/result/qualification-report.json`.
It exited `0` with `verdict=pass`, `complete=true`, run ID
`dashboard.phase3.ef0ad8c89138700713a9`, canonical content SHA-256
`2adfef7d6b0b36ed57974154fd89c695d79be21a28eda74d36fa544c37d58495`,
and serialized JSON SHA-256
`28f150d13f2d207d3b2f3a960b372d105c3a0343e0476bcb36b600cd520cf504`.
It contains nine passing domain reports with 882 domain cases and zero domain
finding, plus 50 activated passing aggregate cases and zero aggregate finding.
Its source-derived telemetry records 397 executable entrypoints, 798 effect
callsites assigned to 57 operations, 171 fault cells, 216 command-conflict
schedules, nine dependency edges with 54 state cases and 48 race schedules,
and 27 activated/killed mutants. A persistent focused Dashboard Shell run also
exited `0` with canonical content SHA-256
`58e743f7f9097b3319f77daf0d8979accc20267766af18907c5eaf1063a5ce0b`.

The final composite regression is 182 passed: 47 Phase 3 tests, 38 Phase 2 and
engine tests, 78 retained Phase 1 plus Permission domain/API tests, and 19
Assistant-readiness/Body-Index regressions. Python compile, scoped Ruff,
projection parity, scoped diff, canonical/hash recomputation, and a value-safe
credential/private-key scan all pass. The qualification work found and fixed
three concrete defects before closure: readiness substring false positives,
Body Index local source metadata exposure, and the Phase 2 nondeterministic
concurrency report.

The frozen Phase 3 closure candidate is
`docs/evals/dashboard-internal-qualification-phase3-closure-rev1.json`, canonical
content SHA-256
`7eac8aceddb033e465ef8d8825e34fac0918b3550f6e45e14678e04f846e97f7`
and serialized-file SHA-256
`f48434dc444bbdb61fa4bb3574938c1f9db632fbc85298dbc9c940741cba7738`.
Codex's clause-by-clause verdict is `AGREE` for P3D-01 through P3D-12. Phase 3
did not close on this packet: GPT Pro reviewed the exact hash and returned
`AGREE_WITH_CHANGES`, accepting P3D-01 through P3D-04 and P3D-06 through
P3D-12 but blocking P3D-05. Closure rev1 and determinism addendum rev1 remain
immutable rejected/superseded history.

### 9.18 Phase 3 P3D-05 remediation and closure rev2

Packet 11 exposed a genuine lineage false-pass route. The rev1 comparison
normalized `report.run_manifest_sha256` without separately hash-binding and
comparing the complete retained and current `QualificationRunManifest`
payloads. Equal report outcomes therefore did not prove that a non-adapter
component had remained unchanged.

The immutable Phase 2 determinism addendum rev2 is
`docs/evals/dashboard-internal-qualification-phase2-determinism-addendum-rev2.json`,
canonical SHA-256
`52da07186d4fbe4a21413bf5bac31217be0bace1a401fe869f645aaf424090b3`
and serialized SHA-256
`1325730477dc7d07b2e5db2f931e63ab78399673a0fae8e1fea30b3c19004f93`.
It embeds and self-verifies both complete manifests. Their run ID, Phase 1
prerequisite, deterministic clock, seed, and 13 non-adapter component hashes
are byte-identical; only the deterministic scheduler adapter source digest
differs. The retained/current manifest canonical hashes are respectively
`2bbac7470466e0830f776694eb9a1e2b63223c27ff96c73d9c3f59ee3d0da589`
and `d986e42b525628c53319e320637428992b34cd31787716d695a3488d4e7b5ed9`.
Normalizing only that exact adapter digest yields full-manifest SHA-256
`9fd09a176cdad141a3d62f2d124ea07c5421e9f18bd3b77d94acb0c30096ccc1`;
binding it into the otherwise exact report yields SHA-256
`2905a18fd3d733752e9c26ecb7a412d66a47152f0a8fa7a3199f9bd943fb9a27`.
The exact current Phase 2 v9 report remains canonical SHA-256
`0ed412162d4253d1b8e0d16b920430c789014d3d0535117130349b1bda10e98d`.

`phase3_phase2_lineage.py` enforces those identities before aggregation and
returns exit `2` on any mismatch. The new
`phase2-non-adapter-manifest-drift-accepted` mutant changes the engine digest
while leaving result outcomes untouched; it activates, produces the exact
`PHASE2-REGRESSION` finding, returns lineage exit `2`, and cannot reach an
aggregate exit zero. The portfolio is now 28 of 28 activated and killed.

The refreshed authoritative construction run is
`outputs/qualification/dashboard-phase3-evidence-v5/result/qualification-report.json`.
It exited `0` with `verdict=pass`, `complete=true`, run ID
`dashboard.phase3.c0760fa4333e66089c42`, canonical content SHA-256
`d900de8adc7c2bbb48846b5b598736b40959934b82462c47a294ae6f6fe0874e`,
and serialized JSON SHA-256
`22e2396818a08db4e386107037c6d36d279db3cc0bf66f76ef2b19149d9dae6f`.
It binds nine passing domains, 882 domain cases, 51 passing aggregate cases,
397 entrypoints, 798 callsites, 57 operations, 171 fault cells, 216 command
conflict schedules, 54 dependency cases, 48 dependency races, 28 killed
mutants, and zero findings. The refreshed focused Dashboard Shell v3 report is
canonical SHA-256
`8e4c84889881342510ce0861d8285b33d83619535b6694218eebb87fa4f59ff8`.

The final post-remediation composite is 184 passed in 129.31 seconds: 49 Phase
3 tests, 38 Phase 2/engine tests, 78 retained Phase 1/Permission domain and API
tests, and 19 readiness/Body Index regressions. Python compile, Ruff,
projection parity, JSON/canonical/hash recomputation, scoped diff, and a
value-safe 64-file credential scan all pass.

The immutable Phase 3 closure rev2 packet is
`docs/evals/dashboard-internal-qualification-phase3-closure-rev2.json`,
canonical content SHA-256
`3159a82f641971157241ff9ec92acd7a7adfac1357b9d0fe7cef0e6476e9b00a`
and serialized-file SHA-256
`64aff0860e2091c53fed8cfb99bd0b35a0d3df290677f43b5564568e31866da6`.
Codex's clause-by-clause verdict is `AGREE` for P3D-01 through P3D-12. Phase 3
closed on 2026-08-04 after GPT Pro echoed this exact canonical hash, returned
`AGREE`, accepted P3D-01 through P3D-12, accepted all five explicit P3D-05
full-manifest/fail-closed checks, reported `BLOCKING_IMPLEMENTATION_GAPS:
NONE`, and returned `THREE_PHASE_COMPLETION: YES`. Codex independently retains
`AGREE` on the same immutable packet. All three construction phases therefore
have compatible joint verdicts.

## 10. Actual internal file layout

```text
tests/qualification/
  __init__.py
  contracts.py
  coverage.py
  effects.py
  engine.py
  explorer.py
  domains/
    contextual_permission_adapter.py
    contextual_permission_history.py
    contextual_permission_model.py
    contextual_permission_oracle.py
    contextual_permission_runner.py
  phase3_contracts.py
  phase3_catalog.py
  phase3_discovery.py
  phase3_validation.py
  phase3_workspace.py
  phase3_replays.py
  phase3_workers.py
  phase3_execution.py
  phase3_reporting.py
  phase3_mutations.py
  phase3_phase2_lineage.py
  phase3_runner.py
  test_contextual_permission_phase1.py
  test_contextual_permission_phase2.py
  test_engine.py
  test_phase3_*.py

tools/
  verify_dashboard_internal_qualification.py
```

The engine remains within the test/verification surface instead of becoming a
runtime framework. Production files change only when an executable replay
finds a concrete defect and a focused product regression is added.

## 11. Evidence and phase ledger

| Phase | Codex design verdict | GPT Pro design verdict | Implementation evidence | Codex final verdict | GPT Pro final verdict | Status |
| --- | --- | --- | --- | --- | --- | --- |
| Phase 1 | AGREE rev 1 | AGREE packet 1 follow-up | rev1 and rev2 retained as rejected immutable history; rev3 canonical packet `d9ffea5e169c874522bfe2da71244d10907b88b12301766450f661d0c7af84ed` | `AGREE` | `AGREE`; Phase 2 authorized | COMPLETE |
| Phase 2 | `AGREE` rev2 | `AGREE` rev2; implementation authorized | rev1 rejected history; closure rev2 canonical `76247f4e723ed6cc79144707ce103400d68f180f9ec16ab283d3d328e987c027`; report v7 canonical `a7056c72a3ba9633e55e19e695801a03bbfb88335ba5b9a8b6ef993c1f41cc95` | `AGREE` | `AGREE`; P2D-01 through P2D-10 accepted; Phase 3 authorized | COMPLETE |
| Phase 3 | `AGREE` rev2 | `AGREE` rev2; implementation authorized | closure rev1 rejected on P3D-05; closure rev2 canonical `3159a82f641971157241ff9ec92acd7a7adfac1357b9d0fe7cef0e6476e9b00a`; all-domain report v5 canonical `d900de8adc7c2bbb48846b5b598736b40959934b82462c47a294ae6f6fe0874e`; 184 tests pass | `AGREE` P3D-01 through P3D-12 | `AGREE`; all clauses and five P3D-05 checks accepted; blockers `NONE`; `THREE_PHASE_COMPLETION: YES` | COMPLETE |

## 12. Completion rule

Passing tests are necessary but insufficient. Completion requires a
requirement-by-requirement audit of this document, current implementation,
qualification output, mutation evidence, historical upgrade coverage,
cross-feature coverage, and both reviewers' explicit compatible agree verdicts.
Any missing or indirect evidence leaves the work incomplete.
