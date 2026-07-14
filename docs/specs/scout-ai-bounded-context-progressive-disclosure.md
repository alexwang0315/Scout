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
  -> context.find(top_k=3)
  -> optional context.read(token_budget)
  -> tool.find/tool.describe
  -> ToolPlan (3 ordinary, 5 compound)
  -> selected schemas only
  -> deterministic execution
  -> EvidenceCard (<=1,000 estimated tokens per tool)
  -> no-tool synthesis
  -> GroundingVerification
  -> zero or one repair
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

| Turn | Input target | Requests | Tools |
| --- | ---: | ---: | ---: |
| Simple | <=3,000 | 1 target | <=2 |
| Normal | <=8,000 | <=2 target | <=3 |
| Compound | <=15,000 target; 20,000 hard | <=3 hard | <=5 |

One schema-validation retry or one synthesis repair may consume the third
request; both cannot expand the turn beyond the same hard budget. A budget
stop reports the gap and does not continue an unbounded tool loop.

## Evaluation Contract

The unchanged corpus is:

`outputs/evals/scout_ai_workspace_grounded_100_questions_20260713_glm52_cases.json`

The recorded pre-change baseline is:

`outputs/evals/free_model_100_20260713/north_mini_code/live_tool_selection_openrouter_cohere_north_mini_code_free_20260713T081619Z.json`

Use the deterministic protocol replay before a live provider run:

```bash
./venv/bin/python tools/scout_ai_bounded_runtime_replay.py \
  --timeout-seconds 90 \
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
  --max-context-chars 2000 \
  --model-max-tokens 1800
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
usage exceeded the 2,000-token budget after a repair request (maximum 2,401).
The runtime now skips repair without 1,024 output tokens of headroom and caps a
repair request at 256 model tokens or one quarter of remaining output,
whichever is lower. The request hook preserves that lower repair cap, and a
post-response usage check discards any answer whose actual provider usage still
crosses a hard request, tool, input, output, total-token, repair, or cost limit.
Focused tests cover both preflight and post-response behavior. A second live
100-case confirmation is pending because the same run exhausted the free-tier
daily allowance; therefore the provider-level hard-output gate remains live
verification pending, not claimed as passed.

The original report labeled a 96% any-hit rate as Context Top-3 recall. The
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

## Acceptance Gates

- Context Top-3 recall >=95%.
- Required tool micro recall >=95%.
- Exact required tool-set match >=90%.
- Final user-visible unsupported claims = 0.
- Every concrete conclusion cites a source ref.
- Tenfold workspace growth increases p95 tokens by <=10%.
- Tenfold ToolCard growth does not load all schemas.
- Exceeding a budget stops and records `budget_stop_reason`.

The unchanged corpus currently contains three cases whose expected sets have
6, 9, and 10 tools. Under the required five-tool hard cap their theoretical
maximum combined recall is 180/190 (94.74%). This is a corpus-versus-runtime
contract conflict, not permission to weaken the hard cap. Keep the cases and
report the gap explicitly until expected evidence bundles are represented by
bounded composite tools or the corpus oracle is reviewed.

Current gate disposition:

- PASS: corrected Context Top-3 micro recall, deterministic exact tool set, bounded schema
  disclosure, tenfold workspace growth, tenfold ToolCard growth, and zero
  user-visible unsupported claims.
- FAIL: unchanged-corpus required-tool recall, because 94.74% is the maximum
  under the five-tool cap.
- FAIL: OpenRouter `/free` model quality, with 45.79% live tool recall and 2%
  end-to-end pass.
- VERIFICATION PENDING: provider-level hard output consumption after the
  conservative repair-cap fix.
- NOT APPLICABLE: Computer Use receipts because Slice 7 is still gated.

## Computer Use Gate

Slice 7 is not complete. Do not claim UI execution from a plan artifact. It may
start only after the retrieval, disclosure, grounding, budget, and growth gates
are accepted, and must implement observe, permission, act, observe-again, and a
before/after execution receipt through the existing allowlisted executor.
