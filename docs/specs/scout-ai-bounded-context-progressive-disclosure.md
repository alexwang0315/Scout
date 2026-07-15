# Scout AI Bounded Context and Progressive Tool Disclosure

Status: Assistant Slices 1-6 implemented; acceptance is partial and Computer
Use Slice 7 remains gated.

## Purpose

Keep one Scout AI turn proportional to evidence retrieved for that turn, not
to the total workspace or registry size. The model plans and synthesizes;
deterministic runtime code discovers context, discloses schemas, executes
tools, bounds evidence, accounts usage, verifies grounding, and stops.

## Runtime Contract

```text
question
  -> context.find(top_k=10)
  -> optional context.read
  -> tool.find/tool.describe
  -> typed question class and AgentRunBudget
  -> selected schemas only
  -> discover/query/optional join/verify
  -> sanitized EvidenceCard with stable provenance
  -> no-tool synthesis
  -> GroundingVerification
  -> verified no-tool repair/replan when needed
  -> external-limit checkpoint and fresh-budget continuation
```

`ContextHandle` and `EvidenceCard` always preserve provenance, freshness,
sensitivity, `candidate_only=true`, and `runtime_safety_truth=false`. Context
reads are confined to the resolved project root. Raw results remain in the
workspace or server-side invocation record and are not duplicated into the
synthesis prompt.

Model-generated tool arguments are not observations. The cloud/Pydantic path
discards asserted location, navigation quality, vitals, equipment state, team
state, risk score, and safety-buffer values before deterministic tool
execution. It records only the ignored field names. Workspace-backed paths
remain allowed after project-root confinement.

For a multi-tool plan, only an executed tool's schema is removed. Remaining
selected schemas stay available within the same request/tool budget. A draft
is discarded if any selected tool was not attempted. Grounding verification
also rejects safety-polarity contradictions such as an answer saying a route
is safe when its cited evidence says it is not safe.

## Budgets

`AgentBudgetPolicy.for_query()` is the deterministic policy source. Pydantic
AI `UsageLimits` only enforces the resulting request/tool/token limits; it does
not choose them. `AgentRunLedger` then verifies actual provider usage against
the same `AgentRunBudget` after the call.

| Question class | Tool calls | Model requests |
| --- | ---: | ---: |
| `static_workspace_fact` | 10 | 10 |
| `aggregate_workspace_fact` | 10 | 10 |
| `cross_artifact_join` | 10 | 10 |
| `spatial_route_fact` | 10 | 10 |
| `weather_terrain_compound` | 10 | 10 |
| `live_runtime_fact` | 10 | 10 |
| `safety_decision` | 10 | 10 |
| any new or unclassified class | 10 | 10 |

The schema guarantees at least 10 tool calls and 10 model requests per attempt
and per recovery stage. Independently metered planner, retriever, synthesis,
verifier, reviewer, repair, retry, replan, browser, and subagent categories also
default to 10. Unused capacity stops early and is not a target to consume.

Stages are deterministic: discover, query, join, and verify each expose the
same 10-call capacity. One attempt may use at most its 10 tool calls and 10 model
requests; a continuation, tool repair, model switch, or Codex-review stage gets
a fresh 10/10 rather than inheriting exhausted counters. Synthesis and repair
have no tools.

Aggressive Construction Mode leaves Scout-defined input/output/total-token,
tool-result-token, context-character, estimated-cost, answer-time, and replay-
time ceilings unset. Counters remain telemetry. External provider/platform
limits checkpoint evidence, call trace, and state, then resume through a
continuation instead of being reported as Scout reasoning failure.
The runtime stops when two calls add no evidence ID, a canonical tool call is
duplicated, a safe retry repeats the same root cause, a required artifact or
field is explicitly absent, live state is absent, or safety evidence remains
insufficient.

## Evaluation Contract

The unchanged corpus is:

`outputs/evals/scout_ai_workspace_grounded_100_questions_20260713_glm52_cases.json`

The recorded pre-change baseline is:

`outputs/evals/free_model_100_20260713/north_mini_code/live_tool_selection_openrouter_cohere_north_mini_code_free_20260713T081619Z.json`

Use the deterministic protocol replay before a live provider run:

```bash
./venv/bin/python tools/scout_ai_bounded_runtime_replay.py \
  --timeout-seconds 0 \
  --output-dir outputs/evals/bounded_context_progressive_disclosure
```

Then run a provider without printing the key:

```bash
./venv/bin/python tools/scout_ai_live_tool_selection_eval.py \
  --cases-file outputs/evals/scout_ai_workspace_grounded_100_questions_20260713_glm52_cases.json \
  --model openrouter:openrouter/free \
  --api-key-env-var OPENROUTER_API_KEY \
  --project-id chilai_nanhua_day1_scoutAI \
  --workspace-root /Users/alexwang0315/workspace \
  --timeout-seconds 0
```

Reports must keep harness/tool architecture, model tool selection, evidence
insufficiency, answer grounding, and provider/runtime failures separate. A
deterministic protocol replay proves disclosure and accounting behavior; it is
not a model-quality score.

## 2026-07-13 Measurements

The unchanged 100-case corpus produced these results.

| Measurement | Recorded baseline | Deterministic protocol replay | OpenRouter `/free` live run |
| --- | ---: | ---: | ---: |
| Input tokens / turn, mean | 57,694 | 1,176 | 3,627 ledger estimate/usage |
| Input tokens / turn, p95 | 140,546 | 1,688 | 5,611 |
| Requests / turn, mean | 3.11 | 2.68 | 2.64 |
| Context Top-3 micro recall | not recorded | 98.06% | 89.32% pre-ranking fix |
| Context Top-3 any-hit | not recorded | 100% | 98.63% pre-ranking fix |
| Context Top-3 exact match | not recorded | 97.26% | 86.30% pre-ranking fix |
| Required-tool micro recall | 34.74% | 94.74% | 45.79% |
| Exact required tool set | 19% | 97% | 46% |
| Final answer completion | 95% legacy definition | 26% | 4% |
| End-to-end case pass | not recorded | 26% | 2% |
| User-visible unsupported claims | not recorded | 0 | 0 |

Replay artifacts:

- `outputs/evals/bounded_context_progressive_disclosure/live_tool_selection_offline_deterministic_progressive_disclosure_replay_20260713T153818Z.json`
- `outputs/evals/bounded_context_progressive_disclosure/before_after_comparison.json`

Live artifact:

- `outputs/evals/bounded_context_progressive_disclosure/openrouter_free_100/live_tool_selection_openrouter_openrouter_free_20260713T125804Z.json`

Post-hardening one-case live smoke:

- `outputs/evals/bounded_context_progressive_disclosure/openrouter_free_post_final_smoke/live_tool_selection_openrouter_openrouter_free_20260713T155022Z.json`

The post-hardening smoke routed through `tencent/hy3:free`. It selected the
single required route-structure tool exactly, then failed answer grounding.
The runtime discarded the draft and did not start a repair after cumulative
output usage reached 1,884 of the 2,000-token hard budget. This is a verified
fail-closed result, not a completed answer.

`openrouter/free` is a dynamic router, not one fixed model benchmark. Of the
100 cases, 48 retained final provider metadata: 19 used
`openai/gpt-oss-20b:free`, 18 used `openai/gpt-oss-120b:free`, and 11 used
`tencent/hy3:free`; 52 cases had no final model metadata. Live latency was
37.1 seconds mean, 62.4 seconds p95, and 90.6 seconds maximum.

The live run separated 46 provider/runtime failures: 31 completion-token-limit
errors, 13 exhausted tool-schema retries, one output-retry exhaustion, and one
OpenRouter 429 free-tier limit. The remaining failures were 23 model
tool-selection failures, five evidence-insufficiency cases, two harness/tool
status failures, and 22 answer-grounding failures. Only two cases passed every
tool, evidence, completion, and grounding gate.

The live run also exposed three turns whose provider-reported cumulative output
usage exceeded the historical 2,000-token budget after a repair request
(maximum 2,401). The former 256-token/quarter-remaining repair cap was itself a
quality regression: a grounded repair could be truncated before any response
was produced. It is retired. The Productization-only finite envelope retains a
1,024-token repair-headroom preflight when an operator explicitly enables token
enforcement. Aggressive Construction Mode has no Scout-defined output headroom
gate; only an explicit local/operator model limit may cap that request.
Post-response usage checks still enforce the governing call envelope. Focused
tests cover both preflight and post-response behavior.

The current Construction Mode envelope is 10 tool calls and 10 model requests
per attempt/recovery stage, with no Scout-defined token, evidence-card,
context-character, cost, answer-time, or replay-time ceiling. These are
available capacities, not utilization targets, and duplicate/no-progress stops
still apply.

The original report labeled a 96% any-hit rate as Context Top-3 recall. Those
Top-3 labels are retained only as historical artifact field names. The current
runtime may disclose up to ten ranked handles. The
corrected evaluator reports micro recall, macro recall, any-hit, and exact match
separately; excludes health/team contexts that the bounded model path does not
disclose; and gives exact selected tool IDs priority over generic lexical
overlap. The post-fix deterministic replay reaches 98.06% micro recall. The
stored live artifact was recalculated against its historical pre-fix handles,
so its 89.32% value is not presented as a post-fix live confirmation.

Eval cases use isolated runner instances so a timed-out provider or local tool
thread cannot mutate the following case's ledger. Deterministic replay allows
90 seconds per case because large local evidence scans exceeded the generic
30-second provider timeout in two cases; this timing is not a model-quality
metric. Stored reports omit rejected draft text and private context metadata,
redact secrets and absolute paths, sanitize provider endpoints, and use
local-sensitive file mode `0600`.

Provider pricing was unavailable in the response metadata. Observability marks
`cost_estimate_available=false`; it must not present the zero accumulator as a
measured zero-dollar cost.

## 2026-07-14 Deterministic Workspace Query Slice

`scout.ai.workspace.query.v1` adds bounded record retrieval after domain-tool
discovery. Its typed operations are `inspect`, `exists`, `count`, `distinct`,
`filter`, `group_by`, `top_k`, `argmax`, `diff`, `freshness`, `nearest`,
`interval`, and `route_forward`. Result records retain an execution-scoped
evidence ID, source ref/hash, record ID, locator, timestamps, and candidate
boundary. Explicit `null` is a value; an absent requested field returns
`answerability=missing_required_fields` without discarding other evidence.

The 100-case operation gold is
`tests/fixtures/scout_ai_workspace_query_gold_100.json`. The evaluator
`tools/scout_ai_workspace_query_eval.py` is an offline deterministic
operation-level architecture replay. It does not call a cloud model and must
not be cited as model quality.

Latest real-workspace replay on
`/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI`:

| Metric | 2026-07-13 baseline | 2026-07-14 query slice |
| --- | ---: | ---: |
| Artifact selection | not recorded at operation level | 100% |
| Operation selection | not recorded | 100% |
| Required-tool pass | 97% legacy tool oracle | 100% |
| Exact required tool set | 97% | 100% |
| Answer completion | 26% | 100% deterministic fact/gap result |
| Grounded result | 26% | 100% |
| Deterministic fact accuracy | not recorded | 100% |
| Unsupported claims | 0 | 0 |
| Tool calls mean / p95 | not recorded | 1.23 / 2 |
| Model requests mean / p95 | not comparable | 3.19 / 4 budget estimate |
| Input tokens mean / p95 | not comparable | 1,771.63 / 5,072 estimate |
| Duplicate calls / budget exhaustion | not recorded | 0 / 0 |

The completion value means every case returned either its deterministic fact
or its explicitly labeled evidence gap. It does not mean a language model
answered every question. A separate provider-backed Pydantic AI run is
required for OpenRouter model selection and synthesis quality.

Root-cause findings:

| Hypothesis | Result | Implementation/eval evidence |
| --- | --- | --- |
| Catalog summaries were insufficient for record facts | CONFIRMED | The old replay completed and grounded 26/100; record operations now resolve exact counts, IDs, extrema, intervals, and spatial results. |
| Fixed request/tool caps prevented discover-query-join-verify | CONFIRMED | `AgentBudgetPolicy` now assigns fresh 10/10 to every typed or unknown question class and recovery stage while retaining evidence/no-progress and safety boundaries. |
| Source refs could be lost before grounding | CONFIRMED | Query evidence now carries source ref/hash and evidence ID through execution and verification. |
| Unrelated missing tools should reject a supported static fact | REJECTED as desired behavior | Grounding accepts the structured supported claim while safety/live/weather gaps remain fail closed. |
| Empty collection and missing field are equivalent | REJECTED | Empty collections are deterministic zero results; missing fields are warning gaps and explicit null remains present. |
| The previous generic classifier was adequate for compound queries | REJECTED | Before correction, operation selection was 69% and required-tool pass 73%; compound operation and explicit workspace-domain routing now reach 100%. |

### Focused 15K cross-artifact replay

The 2026-07-14 real-workspace replay used
`/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI` and the executable
`--workspace-15k-join-replay` path. It completed exactly ten deterministic tool
calls: manifest discovery, mileage schema inspection, 15K filtering, 15K count,
checkpoint schema inspection, nearest-CP join, exact-CP contradiction check,
mileage freshness, checkpoint freshness, and manifest/source verification.

The verified answer placed 15K at `24.034234788, 121.280180449`; the nearest
checkpoint was `cp.128`, about 268.21 metres away. Both concrete claims carried
their own workspace source refs. Source hashes were internally consistent,
grounding passed with two citations, and no stage-limit stop occurred. This is
a `WORKING PROTOTYPE` proof of
`search -> drilldown -> filter/count -> spatial join -> freshness and source
verification -> answer`; it is not a cloud-model quality benchmark.

## Acceptance Gates

- Ranked context-discovery micro recall >=95% at the configured shortlist width.
- Required tool micro recall >=95%.
- Exact required tool-set match >=90%.
- Final user-visible unsupported claims = 0.
- Every concrete conclusion cites a source ref.
- Tenfold workspace growth increases p95 tokens by <=10%.
- Tenfold ToolCard growth does not load all schemas.
- Reaching a stage call ceiling records the reason, checkpoints useful evidence,
  and transitions to a fresh continuation/recovery budget.

The governing budget is identical for every question class:

| Question class | Max tool calls | Max model requests |
|---|---:|---:|
| `static_workspace_fact` | 10 | 10 |
| `aggregate_workspace_fact` | 10 | 10 |
| `cross_artifact_join` | 10 | 10 |
| `spatial_route_fact` | 10 | 10 |
| `weather_terrain_compound` | 10 | 10 |
| `live_runtime_fact` | 10 | 10 |
| `safety_decision` | 10 | 10 |
| any new or unclassified class | 10 | 10 |

No lower average, p95, per-stage, or static-fact threshold is an acceptance
gate. The unchanged corpus cases requiring 6, 9, or 10 tools now fit the typed
runtime contract.

Current gate disposition:

- PASS: corrected ranked-context micro recall, deterministic exact tool set, bounded schema
  disclosure, tenfold workspace growth, tenfold ToolCard growth, and zero
  user-visible unsupported claims.
- PASS: unchanged-corpus tool bundles fit the current 10-tool ceiling.
- HISTORICAL FAIL: the 2026-07-13 OpenRouter `/free` run recorded 45.79% live
  tool recall and 2% end-to-end pass under the retired lower resource envelope.
- PASS (one-case smoke): `openrouter:tencent/hy3:free` selected the required
  workspace-catalog tool, completed three model requests and three tool calls,
  passed grounding, and stayed within the relaxed envelope on 2026-07-14.
- VERIFICATION PENDING: full-corpus provider-backed quality under the relaxed
  envelope; report it separately by concrete routed model rather than treating
  `openrouter/free` as one stable model.
- NOT APPLICABLE: Computer Use receipts because Slice 7 is still gated.

Failures are finite work items rather than reasons to reduce the budget again:
fix a faulty tool/evidence/schema/harness, switch model if the tools are sound,
export remaining cases for human review, obtain an independent Codex answer,
then register a known issue and stop if no grounded answer is available.

## Computer Use Gate

Slice 7 is not complete. Do not claim UI execution from a plan artifact. It may
start only after the retrieval, disclosure, grounding, budget, and growth gates
are accepted, and must implement observe, permission, act, observe-again, and a
before/after execution receipt through the existing allowlisted executor.
