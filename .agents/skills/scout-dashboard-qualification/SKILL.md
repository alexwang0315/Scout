---
name: scout-dashboard-qualification
version: 1.2.0
description: Run Scout Dashboard browser qualification at any time, after changes, before merge, or before release using Playwright, Codex, immutable evidence bundles, baseline comparison, human review gates, and independent GPT review.
triggers:
  - qualify scout dashboard
  - run dashboard qualification
  - browser test scout
  - verify new scout feature
  - double-check scout dashboard
  - 建立 Scout 自動系統檢測
  - 檢查 Scout Dashboard 功能
  - 新功能完成後做完整驗證
  - 隨時檢查 Scout 是否退化
  - 執行 Scout 全面回歸檢核
  - compare scout against last qualified baseline
---

# Scout Dashboard Qualification Skill

## Purpose

Use this skill whenever Scout Dashboard functionality is added, changed, repaired, or prepared for merge/release.

The skill establishes a producer-reviewer separation:

1. Playwright is the deterministic browser-test authority.
2. Codex acts as implementation-aware test operator and exploratory tester.
3. GPT acts as an independent, read-only qualification reviewer.
4. GitHub Actions enforces merge gates.
5. Every verdict is bound to an immutable evidence bundle.
6. Failed tests are classified and presented at a Human Review Gate before any implementation change.

The skill must never treat an AI narrative as proof of functionality.

## Non-negotiable invariants

- A Playwright FAIL cannot be overridden by Codex or GPT.
- Retry-pass is FLAKY, never clean PASS.
- P0 FAIL or P0 FLAKY blocks merge.
- Missing required evidence is INSUFFICIENT_EVIDENCE.
- Untested capability is not presumed working.
- UI confirmation alone is insufficient for persistent or authoritative actions.
- Operational, candidate, shadow, projection, fixture, historical, sandbox, and runtime states must remain distinct.
- Smoke or fixture evidence must never be represented as runtime truth.
- GPT reviewer must not modify implementation or tests.
- Codex operator must not issue the final qualification verdict.
- Evidence hashes must match before review begins.
- Qualification is read-only by default: no production code, test expectation, fixture, manifest semantics, or contract may be changed merely because a test failed.
- A failed item must be recorded, classified, evidenced, and submitted for explicit human disposition before remediation.
- Only an explicit APPROVE_FIX or SPEC_CHANGE decision authorizes a subsequent modification phase.
- The skill must be callable on demand at any time, even when no feature or PR context is supplied.
- On-demand runs must default to read-only regression qualification and compare the current revision with the most recent trusted qualified baseline.
- Previously passing capabilities that now fail, become flaky, lose evidence, or change semantics must be classified as regressions and highlighted separately.


## Human Review Gate and no-auto-fix policy

Qualification and remediation are separate phases. During Bootstrap, Feature qualification, Full regression, and Review only modes, the operator must stop after evidence collection, classification, and proposed remediation. It must not automatically patch implementation code, loosen assertions, rewrite expected behavior, alter fixtures, or reclassify capability status to make the suite pass.

For every failed, flaky, blocked, contradictory, or evidence-insufficient item, create a durable review item and wait for one explicit human decision:

- `APPROVE_FIX`: authorize a bounded implementation/test repair matching the approved proposal.
- `REJECT_FIX`: preserve the repository and record why the proposed repair is rejected.
- `DEFER`: retain as unresolved and assign a milestone or review date when provided.
- `KNOWN_ISSUE`: accept the defect temporarily under an explicit scope, rationale, owner, and expiry/review condition.
- `SPEC_CHANGE`: treat the observed mismatch as a specification decision; update contracts/tests only in a separately authorized change.
- `REQUEST_MORE_EVIDENCE`: run additional read-only diagnostics without modifying behavior.

A human decision must bind to the issue ID, evidence root SHA-256, commit SHA, proposed scope, and decision timestamp. Silence, prior general approval, or a passing retry is not authorization.

## Defect classification taxonomy

Each review item must be classified on independent axes. Do not collapse these fields into one label. Unknown values must remain `UNKNOWN`, not guessed.

### 1. Abstraction level

- `HIGH_LEVEL`: product behavior, workflow, policy, safety authority, domain semantics, or cross-surface orchestration.
- `MID_LEVEL`: service/application coordination, state transitions, API orchestration, reducers, adapters, or component composition.
- `LOW_LEVEL`: local implementation, function, query, selector, serialization, timing, resource, dependency, or platform defect.
- `CROSS_CUTTING`: spans multiple abstraction levels.
- `UNKNOWN`.

### 2. System layer

Use one primary layer and zero or more secondary layers:

- `UI_PRESENTATION`
- `CLIENT_STATE`
- `APPLICATION_SERVICE`
- `DOMAIN_LOGIC`
- `AUTHORITY_PERMISSION`
- `API_CONTRACT`
- `INTEGRATION_ADAPTER`
- `PERSISTENCE_DATA`
- `RUNTIME_INFRASTRUCTURE`
- `SECURITY_PRIVACY`
- `OBSERVABILITY_PROVENANCE`
- `TEST_HARNESS_FIXTURE`
- `CI_QUALIFICATION`
- `DOCUMENTATION_COPY`
- `UNKNOWN`

### 3. Defect nature

- `LOGIC_ERROR`: implemented rule or state transition produces the wrong semantic result.
- `CODING_BUG`: implementation defect such as incorrect condition, null handling, race, selector, serialization, exception, or resource handling.
- `CONTRACT_MISMATCH`: producer/consumer, API/schema, manifest, version, or authority contract disagreement.
- `STATE_CONSISTENCY`: stale, duplicated, out-of-order, non-idempotent, or persistence inconsistency.
- `SECURITY_OR_AUTHORITY_VIOLATION`: privilege, provenance, safety boundary, spoofability, or trust-boundary failure.
- `DATA_QUALITY`: malformed, missing, ambiguous, corrupted, or incorrectly normalized data.
- `UX_ACCESSIBILITY`: user cannot understand, perceive, navigate, or complete the intended task.
- `PERFORMANCE_RELIABILITY`: timeout, instability, leak, excessive latency, flaky dependency, or capacity issue.
- `TEST_DEFECT`: incorrect assertion, unreliable selector, invalid fixture, missing isolation, or test-only problem.
- `CI_ENVIRONMENT`: runner, dependency, browser, container, seed, clock, network, or configuration problem.
- `SPEC_AMBIGUITY`: evidence cannot distinguish a bug from an unresolved product/contract decision.
- `EXPECTED_NOT_IMPLEMENTED`: behavior is intentionally unavailable and correctly represented.
- `UNKNOWN`.

### 4. Severity: 1–5, where 5 is most severe

- `S5_CRITICAL`: safety/authority/security boundary breach, data corruption or irreversible action, false runtime truth, system-wide outage, or a defect that can cause dangerous user action. Immediate merge/release block.
- `S4_HIGH`: core workflow unusable, persistent state wrong, major contract violation, broad regression, or no safe workaround. Merge block unless a narrowly governed human exception exists and P0 rules still permit it.
- `S3_MODERATE`: important function degraded or incorrect with a viable workaround; limited scope and no safety/authority breach. Normally requires correction or explicit defer/known-issue decision.
- `S2_LOW`: minor functional, UX, copy, compatibility, or edge-case defect with low operational impact. May be accepted as known issue.
- `S1_TRIVIAL`: cosmetic, diagnostic, or housekeeping issue with negligible user or operational impact.

Severity is impact-based, not effort-based. A one-line coding bug may be S5; a large refactor request may be S1 or not a defect.

### 5. Additional mandatory dimensions

- `impact_scope`: `SINGLE_CONTROL | SINGLE_CAPABILITY | SINGLE_SURFACE | MULTI_SURFACE | SYSTEM_WIDE | UNKNOWN`
- `reproducibility`: `ALWAYS | INTERMITTENT | ENVIRONMENT_SPECIFIC | DATA_SPECIFIC | NOT_REPRODUCED | UNKNOWN`
- `confidence`: integer 0–100 with supporting rationale.
- `user_exposure`: `NONE_INTERNAL | TEST_ONLY | LIMITED_USERS | ALL_USERS | SAFETY_CRITICAL_USERS | UNKNOWN`
- `data_effect`: `NONE | TRANSIENT | STALE | INCORRECT_PERSISTED | LOSS | CORRUPTION | UNKNOWN`
- `authority_effect`: `NONE | PRESENTATION_ONLY | MISLEADING_CLAIM | UNAUTHORIZED_ACTION | FALSE_RUNTIME_TRUTH | UNKNOWN`
- `fix_risk`: `LOW | MEDIUM | HIGH | UNKNOWN`
- `suggested_disposition`: one of the Human Review Gate decisions.

### Classification precedence

1. Safety, security, provenance, authority, and irreversible data effects dominate severity.
2. Root cause and observed symptom must be recorded separately.
3. When root cause is uncertain, classify the observed failure and mark cause as hypothesis.
4. Do not downgrade a real product failure because the immediate cause is in test infrastructure.
5. Do not classify intentional `NOT_IMPLEMENTED` behavior as a defect unless the UI, API, or documentation overclaims availability.

## Review item contract

Create one file per issue or a canonical array at:

```text
artifacts/qualification/<commit-sha>/review-items.json
```

Each item must include:

```yaml
id: SCOUT-Q-0001
title: concise factual title
capability_id: trip_intake.gpx_validate
status: OPEN | AWAITING_HUMAN_REVIEW | APPROVED_FOR_FIX | DEFERRED | KNOWN_ISSUE | REJECTED | RESOLVED
machine_state: FAIL | FLAKY | BLOCKED | INSUFFICIENT_EVIDENCE
abstraction_level: HIGH_LEVEL | MID_LEVEL | LOW_LEVEL | CROSS_CUTTING | UNKNOWN
primary_layer: DOMAIN_LOGIC
secondary_layers: [API_CONTRACT, UI_PRESENTATION]
defect_nature: LOGIC_ERROR
severity: S4_HIGH
impact_scope: SINGLE_CAPABILITY
reproducibility: ALWAYS
confidence: 88
user_exposure: ALL_USERS
data_effect: INCORRECT_PERSISTED
authority_effect: NONE
fix_risk: MEDIUM
observed_behavior: factual observation
expected_behavior: manifest or contract requirement
root_cause_status: CONFIRMED | PROBABLE | HYPOTHESIS | UNKNOWN
root_cause_hypotheses: []
evidence_refs: []
proposed_fix_scope: files/components/contracts likely affected; no patch applied
alternatives: []
regression_tests_required: []
suggested_disposition: APPROVE_FIX
merge_recommendation: BLOCK | ALLOW_WITH_HUMAN_EXCEPTION | ALLOW
human_decision: null
```

The generated review summary must group items by severity, abstraction level, system layer, defect nature, and merge recommendation.

## Result vocabularies

### Machine test states

- PASS
- FAIL
- FLAKY
- BLOCKED
- NOT_IMPLEMENTED
- INSUFFICIENT_EVIDENCE

### Independent review verdicts

- QUALIFIED
- QUALIFIED_WITH_LIMITATIONS
- NEEDS_CORRECTION
- BLOCKED
- INSUFFICIENT_EVIDENCE

## Inputs

The skill should locate or request only when impossible to infer:

- Scout repository root.
- Dashboard start command or compose file.
- Test environment configuration.
- Changed commit or PR diff.
- Existing Playwright configuration, if any.
- Existing Scout contracts and qualification packets.

Do not ask for information already present in the repository.

## Required repository artifacts

Create or maintain:

```text
qualification/
  dashboard-capability-manifest.yaml
  schemas/
    dashboard-capability-manifest.schema.json
    qualification-evidence.schema.json
    qualification-review.schema.json
  prompts/
    codex-operator.md
    gpt-reviewer.md
  policies/
    qualification-gates.yaml

tests/e2e/qualification/
scripts/qualification/
artifacts/qualification/
.github/workflows/dashboard-qualification.yml
```

## Execution modes

### Mode A — Bootstrap

Use when the qualification system does not yet exist.

1. Inventory Dashboard routes, capabilities, API boundaries, and state classifications.
2. Identify P0/P1/P2 criticality.
3. Create the capability manifest.
4. Establish deterministic test environment and fixtures.
5. Implement one vertical slice containing:
   - one normal workflow,
   - one fail-closed boundary,
   - one mobile viewport,
   - one server persistence assertion,
   - one intentional regression proving merge blocking.
6. Generate evidence bundle.
7. Run independent review.
8. Classify every non-pass item and open the Human Review Gate.
9. Report coverage gaps without claiming full Dashboard qualification.
10. Do not remediate until explicitly authorized.

### Mode B — Feature qualification

Use after a new feature or behavior change.

1. Inspect git diff.
2. Map changed code to capability IDs.
3. Fail if changed user-visible behavior lacks manifest coverage.
4. Update positive, negative, persistence, and authority-boundary tests.
5. Run deterministic browser suite.
6. Run Codex exploratory pass focused on changed surfaces and adjacent flows.
7. Seal evidence bundle.
8. Run independent GPT review.
9. Produce classified review items and independent verdict.
10. Stop at the Human Review Gate; do not remediate without an explicit bound decision.

### Mode C — Full regression

Use before release or milestone closure.

1. Execute all active operational capabilities.
2. Verify NOT_IMPLEMENTED and intent-only surfaces are not overclaimed.
3. Run desktop and large-mobile profiles.
4. Inspect skipped tests, retries, console errors, failed requests, and stale artifacts.
5. Produce release-bound qualification packet.
6. Classify non-pass items and stop at the Human Review Gate.

### Mode D — Review only

Use when evidence already exists.

1. Verify hashes.
2. Read raw evidence, not only summaries.
3. Evaluate each capability.
4. Produce independent verdict.
5. Do not modify code or tests.
6. Classify review items and await human disposition.

### Mode E — On-demand regression qualification

Use whenever the user asks to check Scout now, regardless of whether a feature was just completed, a PR exists, or the current changes are committed. This is the default mode when the invocation does not name another mode.

1. Determine the current worktree state, commit SHA, branch, and uncommitted diff without changing them.
2. Locate the most recent trusted baseline whose verdict is `QUALIFIED` and whose evidence hashes verify. Never use an unverified or `QUALIFIED_WITH_LIMITATIONS` packet as a clean baseline unless the user explicitly approves that comparison basis.
3. Snapshot the current capability manifest and execute all active P0/P1 capabilities plus the configured P2 regression set. A user may request `full`, `changed-plus-adjacent`, or `smoke`; default to `changed-plus-adjacent` only when a reliable diff-to-capability map exists, otherwise run `full`.
4. Always rerun global invariants and cross-cutting safety boundaries, even when the detected code diff appears unrelated. At minimum include provenance, authority/permission, persistence/idempotency, candidate-shadow-runtime separation, navigation shell, and error-boundary checks when present in the manifest.
5. Compare current outcomes with the trusted baseline per capability, assertion, evidence requirement, browser profile, and contract version.
6. Emit a dedicated regression delta with these states:
   - `NEW_REGRESSION`: baseline PASS, current FAIL/BLOCKED/INSUFFICIENT_EVIDENCE.
   - `NEW_FLAKY`: baseline clean PASS, current retry-pass or intermittent failure.
   - `EVIDENCE_REGRESSION`: behavior may pass but required evidence disappeared or weakened.
   - `SEMANTIC_DRIFT`: test still passes but manifest, contract, authority, or user-visible meaning changed.
   - `RESOLVED_SINCE_BASELINE`: prior non-pass item now passes, without automatically closing its human review record.
   - `UNCHANGED_PASS`, `UNCHANGED_NON_PASS`, or `NEW_CAPABILITY`.
7. Run Codex exploratory testing on changed, adjacent, and historically fragile surfaces.
8. Seal a new evidence bundle and run independent GPT review.
9. Create or update classified review items. Do not patch any code, test, fixture, manifest semantics, or expected result.
10. Present the Human Review Gate with a concise section titled `Regressions introduced since last qualified baseline`.

If no trusted baseline exists, continue the run as an initial full qualification and return `NO_TRUSTED_BASELINE`; do not invent a comparison result.

The on-demand command should be implementable through aliases such as:

```text
npm run qualification:check
npm run qualification:check:full
npm run qualification:check:smoke
```

A successful on-demand run creates a new immutable packet but must not silently promote it to the trusted baseline. Baseline promotion requires a verified independent verdict and the repository's configured human or merge policy.

## Capability manifest contract

Each user-visible or actionable capability must include:

```yaml
id: unique.capability.id
surface: route-or-surface-id
route: /example
criticality: P0 | P1 | P2
status: operational | partial | intent_only | candidate | shadow | sandbox | not_implemented
owner: optional-team-or-module
introduced_in_commit: optional-sha
expected_behavior:
  - precise observable requirement
forbidden_behavior:
  - precise prohibited outcome
required_tests:
  - happy_path
  - negative_case
required_evidence:
  - ui
  - network
  - server_state
authority_boundary:
  source: server | browser | reducer | none
  runtime_authority: true | false
```

A changed capability without manifest coverage is a blocking manifest mismatch.

## Browser qualification rules

Every authoritative or persistent action should verify three layers where applicable:

1. Visible UI state.
2. Network/API response.
3. Persistent server or artifact state.

Additionally capture:

- browser console errors,
- uncaught page errors,
- failed requests,
- screenshots on key states,
- Playwright trace,
- test video on failure or retry,
- viewport dimensions,
- fixture provenance,
- server contract identifiers.

## Codex operator role

Load and follow `templates/codex-operator.md`.

Codex may during an explicitly authorized implementation phase:

- inspect and modify tests,
- operate the browser,
- diagnose defects,
- create regression tests,
- update manifest entries,
- generate evidence.

During qualification, Codex may inspect but must not modify production code, expected behavior, fixtures, contracts, or tests solely to remove a failure.

Codex may not:

- approve its own changes,
- delete or suppress failure evidence,
- convert FLAKY to PASS,
- infer runtime authority from UI labels,
- substitute prose for machine evidence.

## GPT reviewer role

Load and follow `templates/gpt-reviewer.md`.

Reviewer must:

- remain read-only,
- verify evidence hashes,
- inspect raw reports and test source,
- separate fact, inference, and unknown,
- reject unsupported PASS claims,
- bind verdict to commit and evidence hashes.

## Evidence bundle

Generate:

```text
artifacts/qualification/<commit-sha>/
  manifest.snapshot.yaml
  git-diff.patch
  build-info.json
  environment.json
  playwright-report/
  junit.xml
  results.json
  screenshots/
  traces/
  videos/
  network/
  console-errors.json
  page-errors.json
  failed-requests.json
  exploratory-findings.json
  coverage-map.json
  evidence-index.json
  machine-verdict.json
  reviewer-input.json
  reviewer-verdict.json
  review-items.json
  human-decisions.json
  qualification-summary.md
```

`evidence-index.json` must contain SHA-256 hashes for every required evidence file.

## Default Scout P0 boundaries

Treat these as P0 unless the repository explicitly defines stricter rules:

- candidate/shadow/sandbox/projection cannot become runtime authority,
- smoke/fixture/historical provenance cannot become runtime,
- unknown provenance fails closed,
- stale reviewed baseline cannot silently rebind,
- Permission cannot imply departure, retreat, bivy, or runtime safety authorization,
- simulated receipt cannot imply real send or delivery,
- raw debug geometry and uncertainty visualization cannot enter actionable terrain events,
- safety-critical success requires server-side evidence.

## Recommended initial vertical slices

Prefer these when present:

1. Trip Intake validation.
2. Mission Baseline Save/Accept.
3. Debug provenance.
4. Emergency sandbox receipt semantics.

Do not fabricate functionality if any slice is absent.

## CI gate policy

Required checks:

- Scout Deterministic Qualification
- Scout Independent Evidence Review

Block merge on:

- P0 FAIL,
- P0 FLAKY,
- required test missing,
- manifest mismatch,
- evidence hash mismatch,
- unreviewed changed capability,
- INSUFFICIENT_EVIDENCE for P0/P1,
- reviewer verdict NEEDS_CORRECTION or BLOCKED,
- any unresolved S5 or S4 item,
- any issue awaiting required human review,
- any attempted unapproved auto-fix.

## Final response format

Always report:

1. Scope and commit under review.
2. Machine verdict.
3. Independent reviewer verdict.
4. P0/P1 blockers.
5. Flaky tests.
6. Coverage gaps.
7. Classified correction items grouped by severity, layer, abstraction level, and defect nature.
8. Human decisions required and proposed fix scopes.
9. Evidence artifact path.
10. Exact commands and exit codes.
11. Whether merge/release is permitted.
12. Explicit confirmation that no unapproved modification was made.

Never say “all functions are normal” unless every manifest capability in scope is qualified.
