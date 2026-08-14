---
name: scout-dashboard-qualification
version: 1.5.0
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
3. GPT Pro, reached only through `$gpt-pro-collaboration` in the Codex in-app browser, acts as an independent, read-only qualification reviewer.
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
- Official qualification must connect to a pre-existing real Scout runtime Dashboard. The qualification runner must not start, seed, replace, or stop that runtime.
- The exact runtime URL, port, selected real workspace, initial/final reachability, and runtime continuity evidence must be recorded. A missing or restarted runtime is `INSUFFICIENT_EVIDENCE` or `BLOCKED`, never PASS.
- Browser qualification must exercise the visible Dashboard through browser operations. Direct API, unit, fixture, DOM-construction, or screenshot-only evidence may supplement but never replace the browser run.
- Qualification contract tests validate the qualification machinery only. Their count and result must be reported separately and can never be counted as Dashboard functions tested, browser actions completed, or visual states qualified.
- Official full qualification must load `qualification/dashboard-browser-action-contract.json`, reconcile it with the live navigation, and fail if any contracted route, visible control, map surface, layer control, browser action, or visual state lacks evidence.
- Every ordinary interactive control must be operated in the browser and have before/after UI state plus before/after screenshot evidence. A DOM node, event-handler string, API response, or enabled checkbox alone is not success.
- The control census includes the main document and every rendered embedded frame. A control inside the Map or Weather iframe is not covered merely because the parent iframe is visible.
- A disabled control or a select with only one runtime value is unexercised, not proof of the function. Official qualification needs a real project/state where the function can execute, unless a separate explicit guard-state capability is being verified.
- A delegated control counts only when its named specialist browser case passes; delegation is routing, never evidence by itself.
- Every Dashboard map surface must receive real Fit, zoom-in, zoom-out, mouse-pan, keyboard-pan, and rectangle-zoom input. A successful click without a changed map view is FAIL.
- Every exposed map layer must be switched off and on through the rendered control. The enabled state must contain visible rendered tile, vector, point, line, polygon, or specifically approved single-image content.
- Visual acceptance is blocking. Unintended blur, low-resolution raster upscaling, broken imagery, clipped text, horizontal overflow, covered controls, overlapping controls, blank states, or unreadable text cannot pass.
- Pixel/DOM heuristics supplement rather than replace independent visual inspection. GPT Pro must inspect every hash-bound route/action screenshot before returning a visual verdict.
- Synthetic, fixture, replay-only, or temporary-workspace runs are harness-development evidence only and are permanently ineligible for an official verdict or trusted baseline.
- GPT reviewer must not modify implementation or tests.
- Codex operator must not issue the final qualification verdict.
- Direct model/API review is not a substitute for `$gpt-pro-collaboration`; the independent review must be performed through the Codex in-app browser and bound to its resumable ledger.
- Evidence hashes must match before review begins.
- Every bound screenshot's filename extension and declared media type must match its detected magic bytes. A mismatch blocks sealing and review; never relabel JPEG bytes as PNG.
- Evidence-root canonicalization must explicitly declare UTF-8 relative-path sorting and the exact `{sha256}  {path}\n` line format. The root hash must not depend on unspecified list or hash-line ordering.
- Qualification is read-only by default: no production code, test expectation, fixture, manifest semantics, or contract may be changed merely because a test failed.
- A failed observation must be preserved as a candidate finding; after GPT Pro review, any confirmed or blocking item must be classified, evidenced, and submitted for explicit human disposition before remediation.
- Only an explicit APPROVE_FIX or SPEC_CHANGE decision authorizes a subsequent modification phase.
- The skill must be callable on demand at any time, even when no feature or PR context is supplied.
- On-demand runs must default to read-only regression qualification and compare the current revision with the most recent trusted qualified baseline.
- Previously passing capabilities that now fail, become flaky, lose evidence, or change semantics must be classified as regressions and highlighted separately.
- Machine and exploratory failures are candidate findings until GPT Pro reviews the sealed live-runtime evidence. Candidate findings must not be written as confirmed issues.
- Every qualification round must end by presenting GPT-Pro-reviewed findings to the user for explicit human disposition. No remediation or specification addition may begin before the matching issue receives `APPROVE_FIX` or `SPEC_CHANGE`.

## Mandatory live-runtime browser gate

An official qualification round is valid only when all of the following are true:

1. A real Scout runtime Dashboard is already running before evidence collection begins.
2. Its base URL and port are explicitly resolved and recorded; do not silently assume port 9099.
3. The selected project exists in the runtime workspace catalog and is not a qualification fixture, temporary seed, synthetic workspace, or replay server.
4. The runner connects to that runtime without starting or stopping any server and verifies the same runtime remains reachable for the entire round.
5. Playwright operates the rendered Dashboard, including navigation, controls, individual Diagnostic retests, Diag all, applicable map interactions, and observed error states.
6. Applicable authoritative or persistent behavior is corroborated by browser-observed network responses and server/artifact state.
7. All active capabilities in scope are exercised. Missing real runtime state coverage remains `INSUFFICIENT_EVIDENCE`; never fill the gap with a fixture.
8. All routes and visible controls in both the main document and embedded frames reconcile with the browser action contract. Zero unmapped, disabled-only, or unexercised controls is required.
9. All nine contracted map surfaces complete the six required browser gestures; embedded maps also operate every visible directional pan control. Every exposed canonical/Weather layer, layer preset, and CWA display control completes its rendered behavior check.
10. Desktop and large-mobile route states have full scroll screenshots and pass the visual-quality gate. The number of Python/JavaScript contract tests is never reported as Dashboard feature coverage.

The official command must fail closed when the runtime URL or project cannot be resolved. A fixture harness may exist behind an explicit `--fixture-harness`-style opt-in, but its output must state `official_qualification_eligible=false`, must not be promoted to a baseline, and must not create confirmed issue records.

## Finding, review, and human-confirmation lifecycle

The order is mandatory and cannot be collapsed:

1. `candidate-findings.json`: Codex records browser-observed failures, warnings, contradictions, and evidence gaps as unconfirmed candidate findings.
2. Seal and hash the live-runtime evidence bundle. No evidence-producing test or expected behavior may change afterward.
3. Load `$gpt-pro-collaboration`, use the Codex in-app browser, and submit bounded review packets to GPT Pro. The ledger must bind the review to commit SHA, evidence root SHA-256, runtime-attestation SHA-256, and candidate finding IDs.
4. GPT Pro marks each candidate `CONFIRMED`, `DISPUTED`, or `INSUFFICIENT_EVIDENCE`, with evidence references and uncertainty. GPT Pro cannot erase a machine FAIL.
5. Only `CONFIRMED` or still-blocking `INSUFFICIENT_EVIDENCE` findings may be materialized into `review-items.json`; each record must reference the GPT Pro review and start as `AWAITING_HUMAN_REVIEW`.
6. Codex summarizes the round in this conversation and asks the user for a finding-specific Human Review Gate decision.
7. Only `APPROVE_FIX` authorizes the bounded repair described for that issue. Only `SPEC_CHANGE` authorizes adding or changing specification/contract behavior. All other decisions preserve the no-change gate.

Neither a deterministic failure nor GPT Pro agreement is human authorization to repair or extend the specification.


## Human Review Gate and no-auto-fix policy

Qualification and remediation are separate phases. During Bootstrap, Feature qualification, Full regression, and Review only modes, the operator must stop after evidence collection, classification, and proposed remediation. It must not automatically patch implementation code, loosen assertions, rewrite expected behavior, alter fixtures, or reclassify capability status to make the suite pass.

For every GPT-Pro-reviewed failed, flaky, blocked, contradictory, or evidence-insufficient item, create a durable review item with its GPT Pro review reference and wait for one explicit human decision:

- `APPROVE_FIX`: authorize a bounded implementation/test repair matching the approved proposal.
- `REJECT_FIX`: preserve the repository and record why the proposed repair is rejected.
- `DEFER`: retain as unresolved and assign a milestone or review date when provided.
- `KNOWN_ISSUE`: accept the defect temporarily under an explicit scope, rationale, owner, and expiry/review condition.
- `SPEC_CHANGE`: treat the observed mismatch as a specification decision; update contracts/tests only in a separately authorized change.
- `REQUEST_MORE_EVIDENCE`: run additional read-only diagnostics without modifying behavior.

A human decision must bind to the issue ID, evidence root SHA-256, runtime-attestation SHA-256, GPT Pro collaboration ledger/review reference, commit SHA, proposed scope, and decision timestamp. Silence, prior general approval, GPT Pro agreement, or a passing retry is not authorization.

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
candidate_finding_id: SCOUT-CANDIDATE-0001
title: concise factual title
capability_id: trip_intake.gpx_validate
status: OPEN | AWAITING_HUMAN_REVIEW | APPROVED_FOR_FIX | DEFERRED | KNOWN_ISSUE | REJECTED | RESOLVED
confirmation_status: GPT_PRO_CONFIRMED | GPT_PRO_INSUFFICIENT_EVIDENCE
gpt_pro_review_ref: collaboration ledger and finding-level review reference
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

Do not allocate a `SCOUT-Q-*` ID or write this canonical record before GPT Pro completes the finding-level review. Browser observations remain `SCOUT-CANDIDATE-*` entries until then.

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
- Exact base URL and port of an already-running real runtime Dashboard.
- Real runtime project/workspace ID and read-only runtime environment context.
- Dashboard start command or compose file for operator reference only; qualification must not start the runtime itself.
- Test environment configuration and runtime continuity evidence.
- Changed commit or PR diff.
- Existing Playwright configuration, if any.
- Existing Scout contracts and qualification packets.

Do not ask for information already present in the repository.

## Required repository artifacts

Create or maintain:

```text
qualification/
  dashboard-capability-manifest.yaml
  dashboard-browser-action-contract.json
  schemas/
    dashboard-browser-action-contract.schema.json
    dashboard-capability-manifest.schema.json
    qualification-evidence.schema.json
    qualification-review-item.schema.json
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
4. Establish deterministic harness fixtures for test-development only, and separately connect the official qualification slice to an already-running real runtime Dashboard.
5. Implement one vertical slice containing:
   - one normal workflow,
   - one fail-closed boundary,
   - one mobile viewport,
   - one server persistence assertion,
   - one intentional regression proving merge blocking.
6. Generate a live-runtime evidence bundle; fixture output cannot satisfy this step.
7. Run independent review through `$gpt-pro-collaboration` in the Codex in-app browser.
8. Classify every GPT-Pro-reviewed non-pass item and open the Human Review Gate.
9. Report coverage gaps without claiming full Dashboard qualification.
10. Do not remediate until explicitly authorized.

### Mode B — Feature qualification

Use after a new feature or behavior change.

1. Inspect git diff.
2. Map changed code to capability IDs.
3. Fail if changed user-visible behavior lacks manifest coverage.
4. Update positive, negative, persistence, and authority-boundary tests.
5. Connect to the pre-existing real runtime and run the deterministic browser suite against it; never substitute a seeded fixture server.
6. Run Codex exploratory pass focused on changed surfaces and adjacent flows.
7. Seal evidence bundle.
8. Run independent GPT Pro review through `$gpt-pro-collaboration` and the Codex in-app browser.
9. Produce classified review items only for reviewed findings and bind the independent verdict to the collaboration ledger.
10. Present every reviewed item to the user and stop at the Human Review Gate; do not remediate or add specification without an explicit bound decision.

### Mode C — Full regression

Use before release or milestone closure.

1. Execute all active operational capabilities through browser operations on the already-running real runtime Dashboard.
2. Verify NOT_IMPLEMENTED and intent-only surfaces are not overclaimed.
3. Run desktop and large-mobile profiles.
4. Inspect skipped tests, retries, console errors, failed requests, and stale artifacts.
5. Produce release-bound qualification packet.
6. Submit the sealed packet to GPT Pro, classify reviewed non-pass items, present them to the user, and stop at the Human Review Gate.

### Mode D — Review only

Use when evidence already exists.

1. Verify hashes.
2. Read raw evidence, not only summaries.
3. Evaluate each capability.
4. Use `$gpt-pro-collaboration` in the Codex in-app browser to produce the independent verdict; reject packets without live-runtime attestation.
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
8. Seal a new live-runtime evidence bundle and run independent GPT Pro review through `$gpt-pro-collaboration`.
9. Create or update classified review items only after that review. Do not patch any code, test, fixture, manifest semantics, or expected result.
10. Present every reviewed issue for human confirmation, including a concise section titled `Regressions introduced since last qualified baseline`, and stop.

If no trusted baseline exists, continue the run as an initial full qualification and return `NO_TRUSTED_BASELINE`; do not invent a comparison result.

The on-demand command should be implementable through aliases such as:

```text
npm run qualification:check
npm run qualification:check:full
npm run qualification:check:smoke
```

A successful on-demand run creates a new immutable packet but must not silently promote it to the trusted baseline. Baseline promotion requires live-runtime attestation, a verified GPT Pro collaboration verdict, and the repository's configured human or merge policy. Historical fixture/synthetic packets are never trusted baselines even if their old verdict says `QUALIFIED`.

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

Playwright must connect to the explicitly recorded real runtime URL. The runner must not call a fixture server factory, seed a temporary workspace, reserve an ephemeral Dashboard port, or terminate the runtime. Browser action evidence must include the clicked control or route, timestamp, resulting UI state, and correlated network observations.

The full browser run is inventory-driven:

1. Reconcile all rendered navigation routes with `dashboard-browser-action-contract.json`.
2. On desktop and large-mobile, open every route, physically scroll its complete rendered height, and capture each visible viewport state.
3. Discover every visible `button`, link, input, select, textarea, summary, tab, role-button, and keyboard-focusable control in the main document and every rendered embedded frame. Operate it or bind it to a specialist browser case. `UNMAPPED`, `NOT_EXERCISED`, `MISSING_AFTER_RELOAD`, `NO_STATE_CHANGE`, `NO_VISUAL_CHANGE`, and `EFFECT_AUTHORIZATION_REQUIRED` are blocking coverage gaps. Disabled controls and single-value selects remain `NOT_EXERCISED` until a real executable state is supplied.
4. For persistent, outbound, hardware, preparation, generation, or other effectful controls, use only an explicitly authorized, reversible, real QA runtime/project. Without that authority, preserve the control as `EFFECT_AUTHORIZATION_REQUIRED`; do not click it and do not claim full qualification.
5. Exercise all contracted maps and layers using real mouse and keyboard input. For embedded maps, also operate all four directional pan buttons, every layer preset, and every CWA product/window/timeline/opacity/play control. Validate the changed view/render group and browser-observed raster requests, not merely the control state.
6. Save before/after screenshots for every operation. Machine-check blur filters, sharpness, raster resolution, broken images, text clipping/readability, overflow, occlusion, and interactive overlap.
7. Require GPT Pro to inspect every bound screenshot. A screenshot path, screenshot count, or machine sharpness score is not independent visual confirmation.

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
- runtime provenance and continuity attestation,
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

Load and follow `templates/gpt-reviewer.md`, then load `$gpt-pro-collaboration` and `$browser:control-in-app-browser`. The only accepted official reviewer channel is a GPT Pro dialogue operated through the Codex in-app browser. A direct OpenAI API call, local model, prose-only Codex review, or standalone browser does not satisfy this gate.

Reviewer must:

- remain read-only,
- verify evidence hashes,
- inspect raw reports and test source,
- separate fact, inference, and unknown,
- reject unsupported PASS claims,
- bind verdict to commit and evidence hashes.
- reject a packet whose runtime attestation is missing, synthetic, fixture-backed, temporary, discontinuous, or not hash-bound;
- return a finding-level `CONFIRMED | DISPUTED | INSUFFICIENT_EVIDENCE` decision;
- preserve its resumable collaboration ledger reference in the qualification packet.

## Evidence bundle

Generate:

```text
artifacts/qualification/<commit-sha>/
  manifest.snapshot.yaml
  git-diff.patch
  build-info.json
  environment.json
  runtime-attestation.json
  browser-action-contract.snapshot.json
  browser-action-log.json
  browser-control-inventory.json
  browser-visual-audit.json
  browser-map-interactions.json
  browser-layer-interactions.json
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
  candidate-findings.json
  coverage-map.json
  evidence-index.json
  machine-verdict.json
  reviewer-input.json
  gpt-pro-review-status.json
  gpt-pro-review-reference.json
  reviewer-verdict.json
  review-items.json
  human-decisions.json
  qualification-summary.md
```

`evidence-index.json` must contain SHA-256 hashes for every required evidence file, a magic-byte-derived media type for every bound screenshot, and an explicit `root_canonicalization` object declaring the relative-path sort key, encoding, line format, and digest algorithm.

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
- runtime URL/project not explicitly resolved or runtime continuity not proven,
- synthetic, fixture, or temporary evidence presented as official qualification,
- GPT Pro collaboration review missing or not bound to the sealed evidence,
- a reviewed issue missing its required human disposition before repair or specification work.

## Final response format

Always report:

1. Scope and commit under review.
2. Exact runtime URL, port, project ID, continuity result, and runtime-attestation hash.
3. Provisional machine verdict.
4. Independent GPT Pro verdict and collaboration ledger reference, or `AWAITING_GPT_PRO_REVIEW`.
5. P0/P1 blockers.
6. Flaky tests.
7. Coverage gaps.
8. Candidate findings and their GPT Pro confirmation state.
9. Classified correction items grouped by severity, layer, abstraction level, and defect nature.
10. Human decisions required and proposed fix or specification scopes; explicitly stop for the user's confirmation after every round.
11. Evidence artifact path.
12. Exact commands and exit codes.
13. Whether merge/release is permitted.
14. Explicit confirmation that no unapproved modification was made.
15. Contract-test count separately from live browser counts: routes opened, controls operated, map surfaces/gestures completed, layers toggled, screenshots visually inspected, and any unexercised/effect-authorization gaps.

Never say “all functions are normal” unless every manifest capability in scope is qualified.
