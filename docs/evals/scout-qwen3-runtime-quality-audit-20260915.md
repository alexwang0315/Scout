# Qwen3 Runtime Quality Audit (2026-09-15)

Status: **PARTIAL PROTOTYPE**. The frozen 100-question capture and independent
semantic review are complete. Candidate v12 is running as a live source patch
on Scout. Its focused staged and deployed suites pass, and its repaired
12-question route/timing regression is 12/12 semantically correct. The wider
affected regression gate is still not green, two frozen workspace inputs still
differ, and the patch is not in a rebuilt image. This is not a release or a
safety qualification.

## Purpose

Evaluate the real Scout assistant HTTP path, including tool selection,
workspace retrieval, local model synthesis, verification and presentation.
The previous frozen-evidence model comparison supplied relevant facts directly
to the model. It does not establish that the complete assistant can find those
facts or answer the same questions correctly.

The selected primary model remains `hailo:qwen3:1.7b`, on AI HAT+2 / Hailo-10H.
No cloud inference is used in this audit. Cloud configuration is preserved.
Scout runs Python 3.12.14 and Pydantic AI 2.36.0; the Mac development environment
uses Python 3.12 and Pydantic AI 2.43. This is deliberately not an upgrade test.

## Evidence And Reproduction

- Local artifacts: `artifacts/qwen3-domain-audit-20260915/`.
- Scout artifacts: `/home/alexwang0315/hailo-upgrade/qwen3-domain-audit-20260915/`.
- Workspace: `/data/scout/admin/pretrip-workspaces/chilai_nanhua_day1_scoutAI`.
- Actual entrypoint: Scout admin `/assistant/query`, with the configured local
  profile, not a direct model-only endpoint or a dashboard substitute.
- Harness: `tools/scout_ai_local_model_quality_eval.py`.
- Frozen corpus: `cases.json`, 100 questions, 10 families, 80 diagnostic and
  20 held-out questions. Held-out means question-held-out, not source-disjoint.
- Corpus SHA-256:
  `0c6485101b8b2917148235a39f1e22025f437208c60bfbfd21f405d70cf6f362`.
- `rubric.md` locks 17 source hashes and 93 JSON Pointer references. Expected
  facts, answer criteria and source hints are never sent in HTTP questions.

### Workspace Input Mismatch

The 09:58:20 UTC checkpoint reconfirmed the rubric's already documented drift:
**2 of 13 declared workspace files on Scout differ from the Mac snapshot used
to build the rubric**. This was not first introduced by the ongoing run. The local
17-source verifier passing does not establish hardware input parity.

- `outputs/boss_points.json`: the parsed contents differ only in `generated_at`.
  The Boss facts compared at this checkpoint are otherwise identical. The byte
  mismatch remains recorded; it is not silently marked PASS.
- `outputs/route_weather_risk_package.json`: substantive differences include
  radar/satellite frame counts, timestamps, delay, confidence, rainfall and
  convection indicators, route SHA, and a pre-existing LoRa candidate payload.
  The Mac snapshot is dated August 25; Scout contains July 28 data. Scout file
  mtime/ctime both precede this audit. This is an input-parity defect, not evidence
  that Qwen3 invented or lost those facts during this run.

The receipt is `workspace-source-checkpoint-20260915T095820Z.json`; copies of
the two actual hardware files are in `live-input-checkpoint/outputs/`. Neither
workspace nor the frozen gold has been overwritten. Preserve the actual model
answers, but do not classify discrepancies caused by these inputs as model
errors or claim those cases are qualified. The user has been asked to choose
an independent Scout-based baseline or a separate Mac-snapshot test workspace
for subsequent reruns.

The 11:36:10 and 13:06:41 UTC source checkpoints have the same 13 source hashes
and the same two mismatches. They do not show additional declared-source drift
during the capture or before the paired replay; they also do not make the two
existing mismatches qualified.

Each run preserves `manifest.json`, `answers.jsonl`, `progress.json` and
`health.jsonl`. The manifest records the model, Python/Pydantic AI versions,
image ID, container start time, relevant source hashes and sanitized inference
settings. Resume rejects changed corpus/runtime identities. `PAUSE` stops after
the current case. Raw model answers, deterministic results and final rendered
answers are separate fields; missing telemetry does not prove no inference.

The harness now accepts optional paired `--workspace-root` and
`--source-hashes` inputs. It checks frozen declared workspace sources before
any model call and hashes each case's declared inputs before and after its
answer. A mismatch keeps the receipt/raw answer but stops further cases with
`input_mismatch`; missing snapshot configuration is explicitly unverified.
This covers declared case sources, not every implicit runtime read. Eighteen
focused tests pass, including source drift during inference, no network call
after preflight failure, and expected-fact exclusion from requests. The
completed v3 baseline used the original harness and is not retroactively
qualified. The candidate-v4 paired run uses the new hash gate.

## Baseline And Comparison Scope

The original 14-question pilot captured only 11 answers. Independent review of
those 11 final HTTP answers found 1 PASS, 1 PARTIAL and 9 FAIL. The sole PASS was
a deterministic CP-count shortcut, not model-only evidence. None of these 11
records retained a raw model answer, so a baseline model-only pass rate is
unknown. See `pilot-review.md` and `pilot-scores.json`.

Candidate v1 reran only the greeting and failed. Candidate v2 captured 8 pilot
answers before a deliberate case-boundary pause. Candidate v3 starts the frozen
100-question corpus. Do not label this as a paired 100-question before/after
experiment. Only identical captured pilot questions permit paired comparison.

An independent fixed capture of Q3A-001 through Q3A-014 found:

| Stream | PASS | PARTIAL | FAIL | UNKNOWN |
| --- | ---: | ---: | ---: | ---: |
| Raw model answer | 3 | 2 | 6 | 3 |
| Final HTTP answer | 1 | 1 | 12 | 0 |

These are 14 captured cases, not the complete corpus's scores. Q3A-001's raw
route name/distance/source are correct, but postprocessing attaches an unrelated
resume-segments citation. Q3A-005 supplies correct grouped ascent/descent values
but omits the requested aggregation basis. Q3A-002 confuses GPX point count with
segment count. Q3A-003 and Q3A-013 are deterministic shortcuts without retained
model answers. Exact verdicts and limits are in `independent-scores.json` and
`independent-review.md` under the audit artifact directory.

The next independent slice, Q3A-015 through Q3A-035, found raw-model-field
0 PASS / 18 FAIL / 3 UNKNOWN and final HTTP 0 PASS / 21 FAIL. Partial factual
credit is diagnostic only. The earlier 14-case review's PARTIAL labels must not
be promoted to case successes in the full-corpus aggregate. See
`independent-15-35-scores.json` and `independent-15-35-review.md`.

The independent Q3A-036 through Q3A-050 slice has raw 0 PASS / 12 FAIL /
3 UNKNOWN and final 0 PASS / 15 FAIL. Across the first 50 reviewed cases,
required omissions count as FAIL: raw 3 PASS / 38 FAIL / 9 UNKNOWN; final
1 PASS / 49 FAIL. These are end-to-end acquisition and synthesis results,
not an isolated measure of Qwen3 intelligence. Partial sub-facts remain in
the individual reviews but do not make an entire question successful.
`aggregate_reviews.py` preserves both the original reviewer label and this
complete-answer verdict, and separates NOT_REVIEWED from NOT_RUN.

Q3A-036 took 2289.749 seconds and returned an incomplete-continuation failure.
A read-only Hailo journal checkpoint during that request window recorded
19 generation starts and 9 `generation_context:timeout expired` events. These
are service-window events, not independently correlated per-request traces.
The raw answer was unavailable. Do not count this as a factual model answer,
or attribute all its time to a single generation or to thermal throttling.

### Complete 100-question semantic result

Independent review is complete for all 100 captured cases. A PARTIAL answer is
normalized to FAIL because an omitted requested value, distinction, source or
format is not a complete usable answer. The original diagnostic partial credit
is retained in the per-case review artifacts.

| Stream | PASS | FAIL | UNKNOWN | Pass rate over all 100 |
| --- | ---: | ---: | ---: | ---: |
| Recorded raw model field | 5 | 76 | 19 | 5% |
| Final HTTP answer | 3 | 97 | 0 | 3% |

The raw field is unavailable for 19 cases because no independently reviewable
raw text was retained. It is not reconstructed from deterministic or rendered
output. There were 146 recorded model requests. Median case latency was
39.635 s, maximum 2289.749 s and total elapsed time 13695.747 s (about 3 h
48 min). These are end-to-end request times, not isolated accelerator latency.

| Family | Raw PASS / FAIL / UNKNOWN | Final PASS / FAIL |
| --- | ---: | ---: |
| route quantities | 3 / 6 / 1 | 1 / 9 |
| point taxonomy | 0 / 7 / 3 | 0 / 10 |
| mileage / GPX axes | 0 / 10 / 0 | 0 / 10 |
| historical timing | 0 / 7 / 3 | 0 / 10 |
| historical notes / OCR | 0 / 8 / 2 | 0 / 10 |
| weather / freshness | 1 / 8 / 1 | 1 / 9 |
| recorded live evidence | 0 / 8 / 2 | 0 / 10 |
| units / aggregation | 0 / 6 / 4 | 0 / 10 |
| authority limits | 1 / 9 / 0 | 1 / 9 |
| conversation / format | 0 / 7 / 3 | 0 / 10 |

The only final-answer passes are Q3A-006, Q3A-052 and Q3A-084. Raw model passes
also include Q3A-001 and Q3A-009, which final postprocessing did not preserve as
complete supported answers. Held-out questions are all retained in the score;
none was used to design candidate-v4 repairs.

### Capability and failure diagnosis

The 100-case result does **not** support the conclusion that Qwen3 alone fails
97% of the domain. It establishes that the complete Scout path failed to
deliver a usable final answer in 97 cases. The distinction matters because
many failures occur before or after generation.

Observed Qwen3 strengths when the compact evidence is correctly bound:

- concise Traditional Chinese extraction of one or two labelled scalar facts;
- direct min/max segment answers when the tool supplies a specific comparison;
- conservative acknowledgement of missing rainfall quantity and some
  candidate-only/authority boundaries;
- useful route naming, distance conversion and source naming in raw output;
- acceptable latency for simple one-request answers (the first paired case was
  33.391 s end to end).

Observed model weaknesses even when some relevant evidence is present:

- binding a number to the wrong entity or axis, for example GPX point count as
  adjacent segment count;
- completing multi-part questions, tables, JSON shapes and requested
  explanations rather than stopping after one salient fact;
- arithmetic, aggregation and comparisons across multiple rows;
- preserving negation, direction, units, null/unknown semantics and historical
  versus live distinctions;
- following a corrective verifier prompt after producing the same invalid
  answer, which can turn a short query into multiple long generations.

Observed system defects that cannot honestly be blamed on model capacity:

- planner or shortcut routing selected CP, terrain, readiness or story evidence
  for a different requested entity;
- nested arrays, rows or scalar summaries were dropped during compact packing;
- a broad evidence card allowed a correct-looking number with the wrong entity
  to pass numeric verification;
- final citation attachment selected an incidental source and could invalidate
  a factually correct raw answer;
- static workspace questions were gated on absent live position, while factual
  terrain questions were replaced by permission-style GO/NO_GO text;
- deterministic/provider/continuation results were mixed with model provenance,
  leaving 19 raw outputs unavailable for independent assessment;
- Hailo generation timeouts and repeated verification created extreme latency
  tails without improving semantic correctness.

The highest-leverage repair order is therefore: typed deterministic acquisition
and derived facts first, compact entity-labelled evidence second, model
synthesis third, and reference-specific final verification fourth. Prompt-only
tuning cannot repair a missing row, wrong tool, wrong source or wrong arithmetic
contract.

The frozen v3 runtime does not change during its 100-case run. Later patches
are developed locally and need a separately identified hardware replay. Since
held-out results have now been inspected, a later rerun of those same questions
is exploratory regression evidence, not a new blind generalization test.

## Repairs Implemented

| Surface | Defect | Repair and verification |
| --- | --- | --- |
| `assistant_skill_router.py` | `cp` substring matched `MCP` and returned the CP count for a Boss question; zero could be discarded | Entity boundaries, compound-query exclusions, explicit zero handling; regression tests |
| `scout_ai_tool_planner.py` | Route distance/elevation/segment metrics could omit the structured route tool | Route metric family selects route structure alongside related tools; positive and negative tests |
| `assistant_pydantic_provider.py` | Default local answers lacked raw-model provenance | Retain actual raw local output separately from rendered answers and deterministic shortcuts |
| Same provider | Packed evidence preferred sample coordinates and duplicate metadata while dropping route summary values | Preserve scalar summaries, false/zero/unknown values; remove duplicate prose and source aliases before facts; replay a captured real tool result |
| Same provider | Sentence punctuation could stop a multi-fact answer; normalized matching stopped before closing delimiters | Require evidence completeness; retain closing parentheses/brackets; streamed regression tests |
| Same provider | Native-research action generation could continue after a complete action | Stop only after a complete JSON action passes the existing action parser; research remains enabled |
| Same provider | Local inference settings were not forwarded consistently | Preserve model settings through profile construction and isolation; use standard system/user roles, `think=false`, temperature 0.2 for this Qwen3 profile |
| `src/scout/services/bounded_agent_runtime.py` | Unsupported claims retried identical full-card verification for every source alias | Stop aliases only for a card-level unsupported claim; retain reference-specific checking and tokenization semantics |

The captured route-tool packing replay now retains route name, 36505.33 m,
2166 m and 3350 m in the existing 1200-token packing envelope. This is a local
packing policy inherited from the Hailo integration, not proof that the hardware
has an exact 1200-token context limit. Complete original evidence remains in
the ledger. No call budget, native-research permission or safety boundary was
reduced to improve the score.

## Known Limitations Under Investigation

- A count shortcut can still intercept compound GPX/CP comparisons.
- Selecting the correct tool does not ensure relevant facts reach synthesis.
- The current priority-100 `field_answer` contract may force an answer to a
  different question, for example longest segment versus shortest segment.
- Number verification can accept a number found elsewhere in a large card;
  it does not yet prove unit/entity binding or arithmetic correctness.
- Automatic citation attachment can select an incidental card source instead
  of the document that actually supports the claim.
- General greetings can retrieve a large unrelated workspace context. Do not
  solve this by endlessly enumerating greeting strings.
- A listed follow-up tool is not necessarily an executable local plan step.
- Context-full continuations, failed native-research planning and provider
  failures require separate accounting from answer correctness.

These are unresolved defects, not reasons to weaken the locked rubric.

## Candidate V4 Repairs And Hardware Deployment

- Preserve a model-named valid source when attaching a missing citation, instead
  of selecting an incidental alias first. Normal evidence verification still
  applies, and unsupported quantities cannot be validated by naming a source.
  Q3A-001's archived raw answer plus archived route-tool output passes this
  postprocessing replay without changing its factual text. This is not new
  live inference.
- Parse a correctly grouped decimal such as `4,439.0` as one quantity. Before
  repair, correct grouped values failed, while separate evidence values `4`
  and `439` could incorrectly validate `4,439`. Both directions have regression
  tests. This repairs numeric formatting, not the still-open general problem
  of entity/unit binding or arithmetic verification.
- In the local Hailo path, a disclosed follow-up tool schema with no executable
  plan no longer suppresses authorized workspace context reads. The fixture
  exercises the real artifact reader and a mocked model transport. A context
  read is not misreported as an executed workspace-query operation. Native
  research permissions and the cloud tool-calling path are unchanged.
- Remove first-three-record and fixed-depth/field-text dropping from evidence
  extraction. Packing preserves an explicit omitted-path list when a fact
  cannot fit the configured envelope; original evidence is retained. A bounded
  prefix search replaces repeated single-fact deletion. An initial regression
  dropped source aliases for a giant unrelated field; its failing receipt is
  retained, and the corrected packing suite passes 448 tests.
- Compound count/place questions now bypass single-answer shortcuts. Elevation
  bounds and Boss inventory queries acquire the corresponding structured tool
  evidence. Segment extrema compute minimum/maximum over actual finite values,
  retain ties/zero/missing counts, and respect negated superlative wording.
- Historical timing/statistics acquire the structured route evidence rather
  than a cultural story pack. The timing summary preserves P25 and all rows;
  duration superlatives no longer produce a distance-extremum shortcut. The
  same tests reproduced six summary/dimension failures and two routing failures
  before repair; the combined timing/routing regression now passes 49 tests.
- Route elevation range and per-segment historical duration range are computed
  from their actual minimum/maximum values. Missing, nonfinite, reversed or
  invalid negative duration bounds produce unknown, not zero. Negative terrain
  elevations and genuine zero ranges remain valid. The same focused tests went
  from 11 FAIL / 36 PASS to 47 PASS; this supplies verifiable derived facts and
  does not weaken the general arithmetic verifier.
- Checkpoint continuity now checks actual directed segment endpoints, duplicate
  IDs, missing endpoints, branches, merges, disconnected components and cycles.
  The legacy count comparison remains explicitly `count_only`; equal counts do
  not prove a chain. Array order does not change the result, malformed data
  stays unknown, and identifier linkage is never physical GPX continuity.
  The new 75-test suite goes from 74 FAIL / 1 PASS to 75 PASS. Its combined
  147-test run passes; six concurrent timing fixes in that combined baseline
  are not attributed to this graph repair.
- Factual terrain metadata/count/mileage queries retain their underlying score
  evidence without an unrelated GO/NO_GO/DELAY decision. Genuine permission
  questions retain the existing decision behavior. The same new terrain tests
  went from 17 FAIL / 12 PASS to 29 PASS; existing terrain tests also pass.
- The API's legacy `cloud_synthesized_retry` wording did not establish a cloud
  request. A plain configured local runner was being called through the helper
  with that historical name. The candidate now reports the actual local/cloud/
  unknown profile, keeps local raw retry output, and uses a model-neutral retry
  prompt. No cloud inference was requested as a repair. Tests reproduced all
  three provenance defects before the patch; the related API suite now has
  48 PASS, 2 unchanged pre-existing failures and 3 passed subtests. Those two
  failures remain unresolved, not waived or counted as PASS.

The subsequent focused run has 164 passed tests; the existing provider,
bounded-runtime, source-boundary and native-research suites have 496 passed
tests with one upstream Pydantic Graph event-loop deprecation warning. Later
timing additions have the separate 49-test receipt above; these overlapping
suites are not added together as a unique total. Focused Ruff passes using the installed standalone
Ruff executable; Ruff is not installed as a module in this repository venv.
This does not qualify all semantic answers.

Five pre-existing expectation failures were reproduced and retained in
`candidate-v4-existing-expectation-failures-corrected.xml`: two assistant API
expectations and three media-literacy/photo full-workflow missing-evidence
counts. No expected count or failure-answer convention was altered to make
the suite green. Any proposed expectation change needs its own reconciliation.

### Expanded Regression Investigation

The first expanded 23-file run was interrupted for diagnosis after
1151 PASS / 92 FAIL / 3 passed subtests, with an upstream warning. The receipt
is `candidate-v4-combined-regression.xml`. It is an incomplete run, not a
passing regression gate; the earlier five-failure list is not exhaustive.

The subsequent complete affected run is
`mac-owned-acquisition-comparison/after-affected.xml`: 1305 tests, 122 failures,
0 errors. A controlled run of exactly those 122 failures with only the three
audit-owned acquisition hunks reversed is
`mac-owned-acquisition-comparison/before-failures-complete122.xml`; all 122 still
fail. This demonstrates that those 122 current-worktree failures are not caused
by the candidate's changes to `scout_ai_tool_planner.py`,
`scout_workspace_search_tools.py` or `scout_terrain_score_tool.py`. It does not
make those failures acceptable or turn the affected regression gate green.

Four representative failures reproduce both with current Mac acquisition
modules and with only this audit's acquisition hunks reversed in isolated
copies: energy-vitals answer source selection, tripod missing-evidence count,
route-context wording and direct-retreat missing-evidence count. Unrelated
Mac `reference_time`, Team and terrain-tool changes remain intact. The
isolated copies, reverse diffs, imported-module hashes and identical unchanged
tests are under `mac-owned-acquisition-comparison/`. This comparison only
isolates the three acquisition modules; it does not waive the failures or
establish a cause for every expanded failure.

An earlier attempt to import entire archived Scout modules alongside current
Mac dependencies failed with a `reference_time` signature mismatch. That
attempt is preserved as invalid comparison evidence, not proof that any
assertion failure predated this audit. No shared expectation or fixture was
changed to hide a failure. Candidate v4 is not release-qualified.

## Candidate V9-V12 Paired Repair

The repaired regression uses the same 12 diagnostic questions selected before
the first paired run: Q3A-001 through Q3A-008, Q3A-031, Q3A-033, Q3A-037 and
Q3A-038. Their four declared route/timing inputs pass preflight and per-case
hash checks. This is an inspected regression set, not a new blind holdout and
not a replacement for the frozen 100-question baseline.

- Candidate v4/v5/v6/v8 exposed that Q3A-003 still selected live-navigation
  evidence or lost the exact route summary during 1,200-token packing. Candidate
  v7 failed staging and was never deployed. These stopped/failed attempts remain
  evidence; they are not counted as successful model runs.
- Candidate v9 made static GPX inventory route-only and preserved priority-100
  exact evidence before lower-priority cards. Q3A-003 then answered 2,958 route
  points versus 74 CPs correctly. Its complete 12-case replay had ten correct
  answers; Q3A-033 routed to major points, and Q3A-038 inverted an explicit
  negative claim.
- Candidate v10 classified named historical distributions before major-point
  routing. Q3A-033 then returned the correct eight samples and complete min/P50/
  P75/max distribution. Its polarity guard did not run under the configured
  active local profile, so Q3A-038 still failed.
- Candidate v11 moved the polarity check into the common bounded Hailo verifier.
  A direct Q3A-038 replay proved that the first model draft was rejected and a
  second real model request repaired `等於證明` to `不等於證明`. Its 12-case
  replay retained all requested facts, but Q3A-033 still added the unsupported
  qualitative label `變異不大`.
- Candidate v12 adds a derived 72.1-minute max-minus-min range, explicitly says
  that the evidence defines no large/small variation threshold, and rejects a
  categorical variation label when the priority-100 evidence says that threshold
  is undefined. The direct Q3A-033 replay and the complete 12-case replay both
  preserve that boundary.

### Candidate v12 result

All 12 final answers are semantically correct, retain actual Qwen3 output, and
use one real `pydantic_ai.tool.search_scout_route_structure.v0` execution each.
Eleven cases use one model request. Q3A-038 uses two requests and one repair;
the first draft is rejected rather than deterministically replaced. The final
aggregate is 13 model requests, 12 tool calls and one repair. Tool acquisition
and semantic answer quality are therefore both 12/12 for this repaired slice.

Visible source support is 10 PASS / 2 PARTIAL. Q3A-002's tool trace contains
checkpoint and segment sources, but its answer displays only
`candidates/checkpoints.json`; Q3A-003 displays only the route summary although
its CP count comes from the checkpoint collection. These are presentation
provenance defects and are not hidden inside the semantic score.

Total elapsed time is 478.716 seconds, median 24.1555 seconds and maximum
126.744 seconds. Q3A-037 is correct but forms a material latency tail despite
one request, 570 input tokens and 13 output tokens. Across the run, request
telemetry records 7,691 input tokens and 280 output tokens. This is end-to-end
latency and does not isolate accelerator generation time.

During 40 health samples, Pi temperature was 55.4-61.5 C, Hailo temperature
53.9-59.4 C, NNC utilization 0-96%, available memory 6,265-6,560 MiB, UPS
93-94%, and battery voltage 16.722-16.727 V. Raspberry Pi throttling remained
`0x0`; the Hailo service remained active at PID 952 with zero restarts. The
post-run snapshot records Pi 55.4 C, Hailo 56.8 C, UPS 94% and 16.725 V.

Candidate v12 passed 821 staged tests and the same 821 deployed-source tests on
Scout, each with two unchanged warnings. Mac focused tests pass 472/472 and
focused Ruff passes. `/health` reports `status=ok`, all 29 registry tools ready
and executable, and four of four ingress observers running. The v12 deployment
receipt confirms model/config preservation, no firmware or Hailo-service change,
no workspace mutation, and no image rebuild.

The paired four-source preflight matches before and after the run. The final
13-source checkpoint still has the same two pre-existing mismatches:
`outputs/boss_points.json` and `outputs/route_weather_risk_package.json`.
Candidate v12 remains ephemeral in `/app`; recreating the container loses it.
The frozen 100-case score remains 3% final-answer PASS because the other 88
questions were not rerun under v12. Full evidence is in
`paired-12-candidate-v12/`, `paired-12-candidate-v12-review.json`,
`candidate-v12-deployment.json`, `staged-hardware-tests-v12.xml`, and
`deployed-hardware-tests-v12.xml`.

## Scoring

Report transport completion, actual model generation, correct facts,
completeness, uncertainty/authority boundaries, source support and latency
separately. HTTP 200, a nonempty answer, `safe_failure=false`, tool selection or
an abstention string alone is never a semantic PASS. PARTIAL is not PASS.
Where raw output is unavailable, do not infer model-only correctness from a
deterministic fallback. Independently review the final answer and raw answer.

## Current Hardware Deployment And Verification

Candidate v12 was deployed at `2026-09-15T15:38:47.312467Z` by replacing eight
reviewed Python source files in the running admin container and restarting that
container only. The deployment receipt is `candidate-v12-deployment.json`.

- Runtime model remains `hailo:qwen3:1.7b`; the model configuration hash is
  unchanged and every recorded model-config field is preserved.
- Image ID remains
  `sha256:3696f5a3886b8c2236161e273ceb44b78db525960b9f10405a994fe1daa9cd80`;
  no image was rebuilt. Container recreation will therefore discard the patch.
- The Hailo inference service, HailoRT and firmware were not restarted or
  changed. Workspace evidence was not mutated.
- `/health` returned `status=ok` and all four configured ingress observers were
  running after deployment.
- The isolated staged suite passed 821/821 tests in 57.63 seconds. Receipt:
  `staged-hardware-tests-v12.xml`, SHA-256
  `f7cc51f166a6eaf2e1b612440affeb7597365cac66629d2ed264f712fed139b9`.
- The deployed actual-source suite passed the same 821/821 tests in 59.45
  seconds. Receipt: `deployed-hardware-tests-v12.xml`, SHA-256
  `360c6ef4f3ca06e314c7e44eb7e6f22dae91c17c9f054a2d5dee29168e02ed6d`.

The original predeployment health snapshot (`health-predeploy.json`) recorded
Pi 63.1 C, throttle `0x0`, core 0.8801 V, 5,494 MiB available memory, Hailo
48.6 C at idle, and UPS 94% with 16.723 V pack voltage and no low cell. The
current v12 run's ranges and post-run snapshot are recorded above. These are
health observations, not answer-quality proof.

## Verification And Deployment Caveats

Candidate v12 Mac focused tests: 472 PASS; focused Ruff: PASS. The isolated
staged and deployed Scout suites each pass 821 tests. An earlier Scout test
attempt imported stale sources from a temporary test directory and failed four
new regressions; its evidence is retained. The current clean reruns validate
the actual staged and deployed sources, not a lowered expectation.

Existing weather/API/router expectation failures were also reproduced against
archived original code. They remain unresolved and are not counted as PASS.
No Dashboard/GIS behavior, Phase 1 safety, outbound transport or hardware-control
implementation was changed. The admin container was restarted for the explicit
eight-file experimental patch described above. This is not a rebuilt image.
The complete wider affected suite still has 122 failures, so the current
prototype does not pass the repository's completion gate. Reproduction uses
recorded source hashes.

All patches are staged from archived live sources, transplanting only reviewed
audit functions. Unrelated Mac modifications are not deployed. The Mac commit
gateway snapshots all eligible changes, so a scoped commit must not accidentally
include the other tasks' pending work.

The candidate-v12 live regression selects 12 unchanged diagnostic cases:
001-008, 031, 033, 037 and 038. `paired-12-inputs/selection.json` records the
selection and parent corpus identity. The four declared source files have frozen
hashes and pass the harness's preflight and per-case checks. This is not a full
paired 100-case rerun, a new blind holdout test, or qualification of all implicit
workspace reads. Weather/Boss input drift is not hidden by this separately
labelled route/timing regression.
