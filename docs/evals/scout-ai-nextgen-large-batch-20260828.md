# Scout AI NextGen Large-Batch Evaluation 2026-08-28

Status: `WORKING PROTOTYPE / 96% MODEL-NATIVE / 100% COMPOSED PIPELINE / WIDER PER QUALIFIED`

Boundary: `candidate_only=true`, `runtime_safety_truth=false`

## Experiment

- 60 unique Six-Forces questions: 10 each from EXP, RPF, PER, RTE, WTH, NAV.
- PER and WTH were expanded across three deterministic context variants.
- Total: 100 live model runs.
- Model: `openrouter:deepseek/deepseek-v4-flash-0731`.
- Runtime: Pydantic AI 2.35.0, native evidence tools, task-aware MSER in
  `enforce` mode, deterministic Scout tools and weather replay.
- PraisonAI was not invoked by this answer runner. Praison remains a separately
  qualified intelligence plane and must not be credited for these answer scores.

## Live Result

| Metric | Result |
| --- | ---: |
| Context identity | 100/100 |
| Transport/schema | 100/100 |
| Safe uncertainty | 100/100 |
| Initial strict acceptance | 50/100 |
| Provider errors | 0 |
| Missing model outputs | 0 |
| Native tool coverage | all offered tools called |
| Candidate-only boundary | 100/100 |
| Runtime safety truth false | 100/100 |

The initial 50/100 result was dominated by MSER contract/verifier false
negatives, not transport or model-output failures. In particular, a conservative
tool-backed gap answer could not be represented, and a claim that cited both a
normal signal and a gap receipt was incorrectly rejected.

## MSER Repair And Replay

The verifier was changed to:

1. allow `DELAY`, or a conservative decision already emitted by selected
   deterministic tool evidence, while continuing to reject unsupported `GO`;
2. validate mixed signal and gap-receipt provenance without requiring every
   source to belong to the gap receipt;
3. bind contextual-permission decisions to a scenario source only when that
   exact scenario is already present in the server-owned MSER environment;
4. expose server-owned allowed gap decisions in the compact model context.

All 100 original model payloads were then revalidated without another model
request. Integrity checks confirmed 100/100 payloads were preserved and zero
revalidation model calls occurred.

| Force | Strict pass after repair |
| --- | ---: |
| EXP | 6/10 |
| RPF | 10/10 |
| PER | 23/30 |
| RTE | 9/10 |
| WTH | 30/30 |
| NAV | 10/10 |
| **Total** | **88/100** |

MSER answer verification improved from 53/100 to 95/100. Strict acceptance
improved from 50/100 to 88/100 without changing model answers.

## Structured Obligation Replay

The remaining exact-token failures were then evaluated with a typed,
candidate-only obligation record. Recovery is possible only when the complete
core verifier, including MSER enforcement, already passes and the sole quality
failure is `did_not_preserve_expected_tool_tokens`. The recovery handles three
narrow cases:

1. factual EXP answers with no meaningful tool `field_answer` must explicitly
   preserve uncertainty and record an evidence gap;
2. exposed strong-wind answers must use a conservative decision and preserve
   the exposed terrain, strong wind, sheltered next step, and 180 m distance;
3. stale GNSS answers must use a conservative decision, state that location is
   stale or unknown, and require position reacquisition.

Seven token-only false negatives were recovered. The eighth token failure,
EXP-031, remained rejected because MSER reported `unknown_signal_id`; the
quality layer could not override it.

| Force | Strict pass after obligation replay |
| --- | ---: |
| EXP | 9/10 |
| RPF | 10/10 |
| PER | 27/30 |
| RTE | 9/10 |
| WTH | 30/30 |
| NAV | 10/10 |
| **Total** | **95/100** |

The second deterministic replay again preserved 100/100 provider payloads,
performed zero model calls, kept all rows candidate-only, and left
`runtime_safety_truth=false` for every row.

## Typed Negative-Search Receipt Replay

The full-text evidence tool now emits a typed negative-search receipt only when
it has searched a non-empty, hash-bound local index and found zero matches. The
receipt binds the query, project, retrieval engine, requested limit, searched
record count, index snapshot SHA-256, and candidate-only authority boundary. It
proves only `no_match_in_bound_local_index_scope`; it does not prove that a fact
is false or absent in the world. A positive match emits no negative receipt, and
an empty or unavailable index fails closed without one.

The deterministic replay refreshed only the two legacy ambiguous full-text
cards, EXP-031 and EXP-091. EXP-031's UNKNOWN answer could then resolve to an
auditable gap receipt instead of failing with `unknown_signal_id`. EXP-091
remained valid. No prompt, model answer, or raw provider payload was regenerated.

| Force | Strict pass after receipt replay |
| --- | ---: |
| EXP | 10/10 |
| RPF | 10/10 |
| PER | 27/30 |
| RTE | 9/10 |
| WTH | 30/30 |
| NAV | 10/10 |
| **Total** | **96/100** |

Replay integrity: 100/100 model payloads preserved, zero model calls, two
deterministic evidence refreshes, zero MSER pipeline errors, all rows
candidate-only, and all rows `runtime_safety_truth=false`.

## Server-Owned Conservative Response Composition

The four remaining failures all had one and only one MSER violation:
`non_conservative_gap_decision`. Their model-authored decisions were `GO` or
`CONDITIONAL_GO` while the final MSER state still contained a typed gap receipt.

An opt-in, server-owned composer now handles only this exact condition. It
requires a valid base answer contract, `ready_to_explain_gap`, at least one typed
gap receipt, a preserved candidate-only boundary, and no verifier violation
other than `non_conservative_gap_decision`. It then produces a separate typed
effective response with `decision=DELAY`. The original provider output remains
unchanged and is retained as candidate explanation evidence. Missing receipts,
multiple violations, invalid candidate boundaries, or invalid base contracts
fail closed without composition.

The replay classified 96 rows as `not_applicable` and composed exactly four:
PER-021, PER-061, PER-081, and RTE-081. All four effective responses passed the
base verifier and MSER on a second deterministic verification pass.

| Force | Model-native pass | Composed pipeline pass |
| --- | ---: | ---: |
| EXP | 10/10 | 10/10 |
| RPF | 10/10 | 10/10 |
| PER | 27/30 | 30/30 |
| RTE | 9/10 | 10/10 |
| WTH | 30/30 | 30/30 |
| NAV | 10/10 | 10/10 |
| **Total** | **96/100** | **100/100** |

This is not a claim that the model natively answered 100/100. It demonstrates
that the Pydantic-authoritative pipeline can preserve a useful model explanation
while deterministically refusing an optimistic decision under unresolved typed
evidence gaps.

### Experimental Live-Path Qualification

The same composer is now connected to the shared Pydantic answer executor behind
`--compose-conservative-gap-responses`. The live path keeps three separate
records: the immutable provider-authored `model_output`, the server-owned
`effective_response`, and the typed composition receipt. The feature is accepted
only with `--mser-mode enforce`.

A focused executor integration test exercised an eligible live response through
the real MSER pipeline: the provider output remained unchanged, the separate
effective response became `DELAY`, and the second base/MSER verification passed.
Malformed output, additional violations, and invalid candidate boundaries remain
ineligible and fail closed.

A fresh 10-run OpenRouter sample then exercised the experimental path with
`deepseek/deepseek-v4-flash-0731` across PER-021, PER-061, PER-081, and RTE-081:

- 10/10 model-native verifier and MSER pass; 0 failures.
- 10/10 composition status `not_applicable`; no provider answer was rewritten.
- 11 harness attempts, 22 provider request records, and 33 native tool calls.
- Mean latency 158.06 seconds; maximum 699.90 seconds.
- The maximum-latency case used one harness attempt, two provider request
  records, three tool calls, and about 14.9K reasoning tokens.
- All rows remained `candidate_only=true` and
  `runtime_safety_truth=false`.

This sample proves non-interference and live-path observability, but it does not
contain a naturally occurring provider answer eligible for composition. Actual
composition is therefore evidenced by the 100-row preserved-output replay and
the focused live-executor integration test, not by claiming this 10-run sample
triggered it.

## Resource Trajectory

- Harness-level model attempts: 179, mean 1.79/run.
- Provider request records: 360.
- Native tool calls: 436.
- Input tokens: 1,600,187; cache-read tokens: 583,168.
- Output tokens: 420,994; reasoning tokens: 359,475.
- Mean latency: 43.94 seconds/run.
- p50: 23.63 seconds; p95: 112.91 seconds; p99: 335.36 seconds.
- Maximum: 505.82 seconds for one multi-attempt RPF run.
- MSER selected 219 planned tools versus 691 in the legacy plan, a reduction of
  472 planned selections (68.3%).

The original latency problem was total run duration. A 180-second timeout per
provider request did not bound a Pydantic tool round or a multi-attempt run, so
even one harness attempt could exceed eleven minutes.

### Total Run Deadline Qualification

The shared executor now accepts an opt-in `total_run_timeout_seconds` and a
`threading.Event` cancellation signal. The CLI exposes this as
`--total-run-timeout-seconds`; zero preserves the existing unbounded
Construction Mode behavior. The 10/10 call ceiling remains available and is not
reduced by this control.

OpenRouter advertises explicit run-control support. Its complete Pydantic Agent
tool round executes as a cancellable async task, while each provider call also
receives the smaller of its own timeout and the remaining total-run time.
Adapters without explicit support receive the remaining timeout as a cooperative
best effort and are labelled accordingly in the receipt.

When a deadline or external cancellation wins, Scout:

- sets the cancellation event and stops guided retries;
- preserves any partial raw provider trace inside `model_attempts`;
- discards late output from top-level `model_output`, `decision`, MSER
  verification, and conservative composition;
- prevents best-attempt fallback from restoring a stopped output;
- emits frozen `scout.model_run_cancellation_receipt.v0` provenance;
- returns verifier failure with `candidate_only=true` and
  `runtime_safety_truth=false`.

A real OpenRouter PER-021 run used a five-second total deadline. The Pydantic
tool round was cancelled at 5.013 seconds and the complete answer run returned at
5.017 seconds. It recorded one attempted model run, zero accepted model output,
zero decision, `failure_category=model_run_timed_out`, and one typed timeout
receipt. The command completed in 12.3 seconds including process startup, and no
evaluator process remained afterward.

This proves the OpenRouter path can terminate the in-flight coroutine. External
in-flight event cancellation is also covered by a focused executable test. It
does not yet prove hard interruption for every local or future sync backend;
those adapters must explicitly implement and advertise run-control support.

#### Matched 240-Second Sample

The same 10 OpenRouter runs used for the unbounded live-path sample were repeated
with a 240-second total deadline, four workers, MSER enforce mode, and the
experimental conservative composer enabled.

- 6/10 completed and passed; 4/10 produced typed timeout receipts.
- All 10 scenario identity checks passed.
- All four timeout rows had `model_output=null`, `decision=null`, no effective
  response, and no MSER verification of a late answer.
- All rows remained `candidate_only=true` and
  `runtime_safety_truth=false`; safe-uncertainty score remained 100/100.
- The timeout cases were all three sheltered-flat PER questions plus RTE-081
  base. Every timeout happened during the first model attempt.
- Completed runs averaged 66.54 seconds. Timeout receipts were recorded between
  240.025 and 240.644 seconds.
- Wall time fell from 703.36 to 438.71 seconds, a 37.63% reduction.
- Summed per-run duration fell only 13.92%, from 1,580.61 to 1,360.56 seconds.
- Provider usage is observable only for the six completed runs: 12 provider
  request records, 18 tool calls, and 13,310 reasoning tokens. Cancelled
  in-flight provider usage remains unknown and must not be counted as zero cost.

The completion loss is not a proxy for removing low-quality trajectories. In
the unbounded sample, all four subsequently timed-out cases passed with semantic
score 100. One of them, PER-081 sheltered-flat, previously completed in 37.88
seconds; another completed in 180.38 seconds. This demonstrates substantial
provider latency variance and rejects a fixed 240-second cutoff as a default
quality policy.

#### Matched Thinking-Off Sample and Spatial Relevance Audit

The same 10-run selection was then repeated with `thinking=off` while retaining
the 240-second total deadline, four workers, MSER enforce mode, and the
experimental composer.

- All 10 runs completed without a timeout; wall time was 86.86 seconds and mean
  per-run duration was 29.12 seconds.
- The run used 16 harness attempts, 32 provider request records, 48 native tool
  calls, 161,469 input tokens, 15,464 output tokens, and zero reasoning tokens.
- Compared with the unbounded thinking-default sample, wall time fell 87.65%
  and mean per-run duration fell 81.58%. Input tokens increased 6.41%, while
  output tokens fell 77.45%.
- Two natural provider outputs exercised the live composer: PER-061 sheltered
  and RTE-081 base. Their original provider payloads remained unchanged and
  separate server-owned effective responses used `DELAY`.
- The first machine pass reported 10/10, with all identity and authority
  boundaries preserved.

Manual evidence review then found one false positive. PER-021 sheltered asked
whether the user could rest "here", but its `NO_GO` answer copied a terrain
candidate at route distance 23.38 km and score 98.94. The candidate coordinate
was 1,276.901 metres from the scenario's current position, so it did not prove
the local terrain or the meaning of "here".

The deterministic evidence compiler now creates a typed
`scout.ai.candidate_spatial_binding.v0` from the current position and the raw
terrain record. The verifier rejects a remote terrain candidate used as
decisive current-location evidence unless the answer explicitly distinguishes
it from the current location. This experimental gate uses a 250-metre local
scope and remains candidate-only. A no-model-call revalidation preserved all
provider outputs and revised the honest result to 9/10; the manifest records
`revalidation_external_model_calls_made=false`.

Experiment decision for thinking-off routing:

- Latency and cancellation behavior: `ACCEPT` as experimental evidence.
- Typed spatial binding and current-location relevance gate: `ACCEPT` for the
  qualification surface.
- Global or silent `thinking=off` routing default: `MORE_EVIDENCE_REQUIRED`.
- Current model/task combination: `CONTINUE_RESEARCH`; it is faster, but the
  failed PER case shows that tool-grounding quality still needs repair.

#### Current-Location Permission Routing Repair

The failed PER-021 trace showed that the model did not ignore Contextual
Permission: the native tool catalog never offered it. MSER's three-tool minimal
set cover declared terrain, pace, and weather coverage complete and replaced
the legacy plan, even though the deterministic PER primary tool was Contextual
Permission.

The execution-plan resolver now preserves one narrow server-owned invariant:
for a PER question explicitly bound to the current location, the existing
Contextual Permission capability remains first even when the MSER information
need coverage is complete. Non-current-location lookup questions such as
"which places should avoid photo stops" retain the smaller terrain-only plan.

A deterministic real-workspace preflight resolved the failed case to four
tools, in this order:

1. `scout.ai.contextual_permission.assess.v0`
2. `pydantic_ai.tool.search_scout_terrain_scores.v0`
3. `scout.ai.pace_guardian.assess.v0`
4. `scout.ai.weather_window.assess.v0`

The Contextual Permission card completed without missing fields and returned a
candidate `CONDITIONAL_GO`: at most eight minutes, leave by the typed deadline,
stay at the flat sheltered candidate, and proceed directly to the next safe CP.

A fresh thinking-off OpenRouter replay then passed 1/1 in 19.291 seconds. The
model used Contextual Permission as decisive evidence and kept terrain, pace,
and weather in opposing evidence. MSER preserved the unresolved fresh-weather
gap, and the server-owned composer produced a separate effective `DELAY` while
leaving the provider's `CONDITIONAL_GO` payload unchanged. Transport, safe
uncertainty, and semantic scores were all 100; identity and candidate-only
boundaries passed.

The run required two harness attempts, four provider request records, and eight
native tool calls. Its first answer already had the exact sole violation
`non_conservative_gap_decision`; the second attempt produced invalid JSON, after
which the first answer was restored and composed. This is direct evidence that
per-attempt composition can remove a redundant retry without weakening the
eligibility gate.

Experiment decision:

- Narrow current-location PER primary-tool preservation: `ACCEPT` for the
  experimental execution-plan resolver.
- Broadly forcing Contextual Permission into every photo/stop lookup:
  `REJECT`.
- Promotion to a default Model Gateway route: `MORE_EVIDENCE_REQUIRED` until
  the matched sample and wider PER corpus are repeated.

#### Per-Attempt Conservative Composition

The narrow conservative composer now runs after each model attempt has passed
the base schema, answer-quality, source-reference, spatial-relevance, and native
tool-coverage gates. It may stop guided retry only when the remaining verifier
error set contains exactly
`mser_answer_verification_failed:non_conservative_gap_decision`. The provider
payload remains immutable; the composed candidate is recorded separately with
`attempt_status=server_composed`.

A matched live replay of PER-021 preserved the previous result while removing
the redundant second attempt:

| Metric | Post-loop composer | Per-attempt composer | Change |
|---|---:|---:|---:|
| Harness model attempts | 2 | 1 | -50.00% |
| Provider request records | 4 | 2 | -50.00% |
| Native tool calls | 8 | 4 | -50.00% |
| Input tokens | 24,982 | 16,079 | -35.64% |
| Output tokens | 2,502 | 843 | -66.31% |
| Duration | 19.291 s | 17.172 s | -10.98% |

Both runs passed 1/1 with identity, transport, safe-uncertainty, and semantic
scores at 100. The provider output remained `CONDITIONAL_GO`; the separate
server-owned effective response remained `DELAY`, with `candidate_only=true`
and `runtime_safety_truth=false`. The smaller wall-time change reflects provider
latency and cache variance, so the stronger result is the deterministic halving
of attempts, provider request records, and native tool calls.

Experiment decision:

- Per-attempt conservative composition: `ACCEPT` for the experimental eval
  path.
- Any broader automatic answer rewriting: `REJECT`.
- Production or default-route promotion: `MORE_EVIDENCE_REQUIRED` pending the
  matched 10-run sample and wider PER corpus.

#### Matched 10-Run Per-Attempt Qualification

The previous thinking-off 10-run selection was repeated with the current
execution-plan resolver and per-attempt composer. It used the same four base
questions (`PER-021`, `PER-061`, `PER-081`, and `RTE-081`), ten expanded runs,
DeepSeek v4 Flash 0731, four workers, MSER enforce mode, and the experimental
240-second total deadline.

| Metric | Previous matched sample | Current architecture | Change |
|---|---:|---:|---:|
| Strict verifier + quality acceptance | 9/10 | 10/10 | +1 run |
| Harness model attempts | 16 | 10 | -37.50% |
| Provider request records | 32 | 20 | -37.50% |
| Native tool calls | 48 | 33 | -31.25% |
| MSER selected-tool total | 30 | 33 | +10.00% |
| Input tokens | 161,469 | 128,163 | -20.63% |
| Output tokens | 15,464 | 8,399 | -45.69% |
| Mean duration | 29.120 s | 23.524 s | -19.22% |

All ten current runs passed on their first harness attempt. Six provider
answers passed directly. Four first answers (`PER-021`, `PER-061`, and
`PER-081` sheltered-flat plus `RTE-081` base) had the sole optimistic-gap
violation and were immediately recorded as `server_composed`; their original
provider payloads stayed unchanged while separate effective responses used
`DELAY`.

The selected-tool total increased because all three current-location PER-021
variants now receive Contextual Permission in addition to MSER coverage. Native
tool calls nevertheless fell because redundant model attempts disappeared.
Compared with the exact current run under the old post-loop timing, the four
first-attempt compositions avoided at least four additional harness attempts,
eight provider request records, and thirteen native tool calls. Comparisons
against the older provider run remain partially stochastic and are not treated
as pure causal attribution.

A no-model-call revalidation then preserved all ten provider payloads and the
four composition receipts. Integrity remained 10/10 with no mismatched run IDs,
no MSER pipeline errors, `candidate_only_all=true`, and
`runtime_safety_truth_all_false=true`.

Manual review confirmed that PER-021 sheltered uses Contextual Permission as
decisive evidence and labels the terrain candidate 1,276.901 metres away as
opposing evidence, not as proof of the current location. The sole blocking-gap
review is the GNSS-stale PER-021 variant: the safety buffer is unknown, so the
answer conservatively delays and requires position reacquisition. It is an
expected review signal, not an execution failure.

Experiment decision:

- Per-attempt composer across the matched sample: `ACCEPT` for the experimental
  qualification path.
- Current-location PER tool preservation: `ACCEPT` for wider PER evaluation.
- Default Model Gateway promotion: `MORE_EVIDENCE_REQUIRED` until the wider PER
  corpus confirms the result.

#### Wider Stratified PER Qualification

A fixed wider corpus selected 18 PER questions across all six PER subsections
and expanded each across exposed-wind, sheltered-flat, and stale-GNSS variants.
The resulting 54-run sample used DeepSeek v4 Flash 0731, thinking off, four
workers, MSER enforce mode, the per-attempt composer, and the experimental
240-second total-run deadline.

The first run accepted 46/54. All 54 identities passed, safe uncertainty was
100/100, and every row preserved the candidate-only authority boundary. The run
used 71 harness attempts, 141 provider request records, and 250 native tool
calls. Two runs timed out. The other six failures exposed deterministic gaps:

- all three PER-063 variants were incorrectly compiled as a non-safety answer
  mode for a critical compound decision;
- PER-003 could be misclassified as a next-checkpoint factual lookup;
- PER-100's explicit multi-dimensional question could receive a weather-only
  task profile;
- PER-001's permission gap receipt was rejected when another signal had already
  marked the same task-required dimension as covered.

The repair kept authority server-owned and changed only deterministic scope:

1. PER evaluation now supplies a typed safety-relevance hint; factual
   next-checkpoint routing requires an actual fact indicator, and compound
   safety questions keep the safety-decision contract.
2. permission profiles preserve mission-margin requirements, while explicit
   readiness and route-planning questions add their named dimensions.
3. gap receipts may bind to any dimension required by the typed task
   certificate, even if another signal currently covers it; unrelated receipt
   dimensions remain rejected.
4. the output parser accepts only a completely decodable JSON object at the end
   of a response after an abandoned draft. Schema and MSER validation still run
   afterward, so this does not recover an unsafe decision.

A no-model-call revalidation preserved all 54 provider payloads, made zero
model calls, and reduced MSER pipeline errors from three to zero. It intentionally
remained 46/54 because historical tool choices and the two empty timeout rows
were not regenerated.

A fresh repair replay then ran the six implicated questions across all three
variants without a total-run deadline. It accepted 17/18, completed every run,
recorded zero pipeline errors, and kept safe uncertainty and authority
boundaries at 100%. It used 23 harness attempts, 46 provider request records,
and 70 native tool calls. The repaired PER-003, both former timeout cases,
PER-001 stale, PER-100 exposed, and two PER-063 variants all passed.

The sole residual was PER-063 exposed. DeepSeek v4 Flash first emitted prose
plus a parseable trailing JSON answer that still asserted an unsupported route
risk comparison; its guided retry then emitted malformed JSON. This is an
appropriate fail-closed result, not an authority leak. A diagnostic model switch
using the same OpenRouter transport and `deepseek/deepseek-v3.2` passed the exact
case in one harness attempt, two provider request records, two native tool calls,
and 17.4 seconds. Its answer explicitly stated that the two routes could not be
compared from current evidence and did not promote candidate evidence to safety
truth.

Experiment decision:

- Wider deterministic PER contract and receipt repairs: `ACCEPT` for the
  experimental qualification path.
- DeepSeek v4 Flash as a universal answer model: `CONTINUE_RESEARCH`; 17/18 on
  the fresh repair set is useful but not sufficient for silent default routing.
- Explicit, observable alternate-model recovery after schema failure:
  `MORE_EVIDENCE_REQUIRED`; the one-case V3.2 pass is diagnostic evidence, not
  yet a global fallback policy.
- Fixed 240-second deadline as a default: `REJECT`; two high-value runs passed
  when rerun without that total deadline.

Experiment decision:

- Total-run cancellation mechanism: `ACCEPT` for the experimental control
  surface.
- Fixed 240-second default for this model/task mix: `REJECT`.
- Production deadline or routing policy: `MORE_EVIDENCE_REQUIRED`.

## Residual Findings

- Model-native acceptance remains 96/100. The four original optimistic
  decisions remain preserved and explicitly visible in precomposition records.
- Composed pipeline acceptance is 100/100 with four typed `DELAY` effective
  responses and no rewritten provider payloads.
- No run remains blocked by `unknown_signal_id`, an unauditable empty search, or
  `non_conservative_gap_decision` at the effective-response boundary.
- The composer is available only through an experimental live-path flag; it is
  not a production default or runtime safety authority.
- Fresh provider non-interference is demonstrated, while natural live-provider
  composition is now demonstrated by two thinking-off runs. The original
  thinking-default sample still had no natural composition.
- Total deadline and external cancellation are opt-in experimental controls;
  OpenRouter hard cancellation is demonstrated, while other synchronous
  backends remain cooperative until separately qualified.
- A 240-second deadline reduced wall time but lowered completion from 10/10 to
  6/10 and disproportionately removed previously high-quality answers. It must
  remain opt-in rather than becoming a global default.
- The matched thinking-off sample completes 10/10 within the deadline but passes
  only 9/10 after spatial relevance qualification. Lower latency therefore does
  not override evidence-to-question relevance.
- A focused rerun of that single failed case now passes after deterministic
  primary-tool preservation, but it does not retroactively turn the original
  matched sample into 10/10.
- The focused per-attempt composer replay preserved that pass while reducing
  harness attempts, provider request records, and native tool calls by 50%.
- The matched 10-run replay passed 10/10 with one harness attempt per run; its
  deterministic revalidation preserved all provider payloads without model
  calls.

## Praison Plane Qualification

Focused Praison MCP, background queue, and bounded web-research tests passed
32 tests with 6 environment-dependent skips. Two original failures showed that
MCP cold start took about 11.9 seconds on this Intel Mac while startup and task
timeouts shared one five-second budget. Startup timeout is now distinct from the
per-request timeout; normal round-trip, stale mission rejection, and explicit
0.25-second fail-closed startup timeout all pass.

## Architecture Decision

The next improvement should not be more agents. Per-attempt composition and the
wider PER deterministic repairs are now proven on fresh live paths. Remaining
priorities are:

1. Repeat the same 60-question/100-run matrix with the repaired router,
   task profiles, receipt verifier, and parser, before
   scaling to the full 1,000-run expansion.
2. Run a matched V4 Flash versus V3.2 recovery qualification on a bounded
   schema-failure and safety-compound subset. Any Model Gateway fallback must
   record both attempted models and may not route silently.
3. Keep reasoning mode observable and opt-in. Interactive synthesis may test
   bounded non-thinking execution, while long reasoning remains in the
   cancellable background queue; neither route may bypass qualification.
4. Connect MSER research information needs to the MCP Intelligence Gateway under
   a feature flag, then inject only validated Praison candidate evidence into
   Pydantic synthesis. Start with EXP evidence gaps; do not route every question
   through Praison.

Typed negative-search receipts are now implemented and qualified; they are no
longer an open architecture item. The conservative composer is connected to the
experimental live path but still carries production promotion and natural-live-
trigger evidence debt.

## Evidence

- Run directory:
  `/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI/outputs/evals/six_forces_600_openrouter_deepseek_v4_flash_large60x100_20260828`
- Summary: `summary.md`
- Model summary: `model_summary.json`
- Per-case trace: `per_case_results.jsonl`
- Revalidation integrity: `mser_revalidation_integrity.json`
- Fresh live-path run directory:
  `/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI/outputs/evals/six_forces_600_openrouter_deepseek_v4_flash_live_composer10_20260901`
- Total-deadline live run directory:
  `/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI/outputs/evals/six_forces_600_openrouter_deepseek_v4_flash_live_deadline5_20260901`
- Matched 240-second deadline run directory:
  `/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI/outputs/evals/six_forces_600_openrouter_deepseek_v4_flash_live_deadline240_10_20260901`
- Matched thinking-off and deterministic spatial revalidation run directory:
  `/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI/outputs/evals/six_forces_600_openrouter_deepseek_v4_flash_live_deadline240_thinking_off_10_20260901`
- Focused current-location PER routing replay:
  `/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI/outputs/evals/six_forces_600_openrouter_deepseek_v4_flash_live_per021_router_primary_thinking_off_20260901`
- Focused per-attempt composer replay:
  `/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI/outputs/evals/six_forces_600_openrouter_deepseek_v4_flash_live_per021_attempt_composer_thinking_off_20260901`
- Matched 10-run per-attempt composer replay:
  `/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI/outputs/evals/six_forces_600_openrouter_deepseek_v4_flash_live_attempt_composer_deadline240_thinking_off_10_20260901`
- Wider 54-run stratified PER qualification and deterministic revalidation:
  `/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI/outputs/evals/six_forces_600_openrouter_deepseek_v4_flash_live_per_stratified18x54_attempt_composer_thinking_off_20260901`
- Fresh 18-run deterministic repair replay:
  `/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI/outputs/evals/six_forces_600_openrouter_deepseek_v4_flash_live_per_repair6x18_unbounded_attempt_composer_20260901`
- PER-063 exposed alternate-model diagnostic:
  `/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI/outputs/evals/six_forces_600_openrouter_deepseek_v4_flash_live_per063_exposed_model_switch_deepseek_v32_20260901`
