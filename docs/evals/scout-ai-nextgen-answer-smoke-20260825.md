# Scout AI NextGen Answer Smoke

Date: 2026-08-25
Mode: Aggressive Construction Mode
Outcome: PARTIAL PROTOTYPE

## Experiment Packet

- Experiment ID: `SCOUT-NEXTGEN-ANSWER-001`
- Hypothesis: the current Pydantic AI answer path, typed Scout tools, MSER
  enforcement, OpenRouter model runtime, and separately qualified Praison
  research plane can produce useful answers while preserving authority.
- Baseline: NextGen transport, model-gateway, Praison MCP, and candidate-only
  contracts were qualified separately, but answer quality had not been measured
  through a current representative matrix.
- Requested and observed model: `openrouter:deepseek/deepseek-v4-flash-0731`
- Runtime: Pydantic AI `2.33.0`, thinking `high`, three cloud workers, native
  Pydantic tools, guided retry, and MSER `enforce`.
- Decision: `CONTINUE_RESEARCH`.

## Test Matrix

Six unique questions covered all six Scout forces. PER and WTH expanded into
three controlled variants, producing ten model runs.

| Question | Purpose | Variants |
|---|---|---:|
| `EXP-100` | historical, natural, and terrain synthesis | 1 |
| `RPF-041` | current pace delta | 1 |
| `PER-099` | safety-related continue/stop advisory | 3 |
| `RTE-022` | next checkpoint lookup | 1 |
| `WTH-096` | missing and stale weather evidence | 3 |
| `NAV-001` | current position lookup | 1 |

The source scenario artifact was the existing Chilai Nanhua Day 1 synthetic
replay bound to the real prepared Workspace. Weather was deterministic replay;
no live weather request was made.

## Results

| Metric | Result |
|---|---:|
| Unique questions | 6 |
| Model runs | 10 |
| Strict MSER-enforced acceptance | 3/10 |
| Same outputs under MSER shadow/off | 9/10 |
| Transport/schema score | 100 mean |
| Safe-uncertainty score | 100 mean |
| Semantic answer-quality score | 95 mean |
| Semantic score at least 80 | 8/10 |
| Runner model attempts | 19 |
| Native Pydantic tool calls | 47 |
| Mean per-run duration | 63.46 seconds |
| Candidate-only boundary | 10/10 |
| Runtime safety truth false | 10/10 |
| Scenario identity | 10/10 |

Strict passes were `EXP-100` and the severe/benign `WTH-096` variants. The
stale-weather variant correctly identified stale evidence and requested fresh
route weather, but MSER enforce still rejected normal reasoning while the state
was `evidence_gap`.

## Finding Classification

### Model and tool-use behavior

- All ten runs returned valid typed output and preserved candidate-only
  authority.
- The model called every offered evidence tool needed by the selected path.
- `EXP-100` correctly abstained because Workspace evidence cards contained
  references but no substantive historical or natural observations.
- `RPF-041` directly reported an 18-minute delay and the pace evidence supporting
  it.
- `RTE-022` detected that route progress `49.25 km` contradicted the route-summary
  length `36.505 km`, and kept the next CP distance unknown.
- `NAV-001` returned the scenario-bound position, route progress, nearest CP,
  heading, altitude, and GNSS accuracy.
- The three `PER-099` answers stayed advisory and never triggered safety,
  emergency, notification, or device actions.

### Control-plane bottleneck

Six of the seven strict failures passed the unchanged-output verifier when MSER
was changed from `enforce` to `shadow` or `off`. The dominant bottleneck is
therefore task-insensitive sufficiency enforcement, not output parsing or basic
model reasoning.

Examples:

- `NAV-001` asked only for current position, but MSER also required terrain
  complexity and terrain visibility.
- `RPF-041` asked for a factual pace delta, but MSER also required route
  feasibility, terrain complexity, and remaining daylight.
- `RTE-022` asked for a checkpoint lookup, but MSER required a broad route,
  terrain, escape, weather, and mission-margin envelope.
- Evidence-gap answers that explicitly say `UNKNOWN`, `DELAY`, or request fresh
  evidence are still classified as forbidden normal reasoning.

The remaining shadow/off failure was the exposed-wind `PER-099` variant. Its
short answer matched the scenario's action obligation, but the quality screen
required literal preservation of additional tool tokens. This needs a human
rubric check before calling it a model failure.

## Task-Aware Follow-up

The first recommended control-plane slice is now implemented as an additive
prototype:

- deterministic task contracts separate `factual_lookup`,
  `evidence_gap_explanation`, `candidate_analysis`, and `safety_decision`;
- factual position, pace, and next-checkpoint queries use narrow typed proof
  obligations instead of inheriting a broad safety profile;
- missing or stale reviewed-tool output produces a typed candidate-only gap
  evidence receipt;
- a gap receipt can support only an explicit `UNKNOWN` explanation with no
  decision or `DELAY`; it cannot support `GO` or another action decision;
- safety-related queries retain the full server-owned profile and remain
  blocked when evidence is insufficient.

The frozen ten model outputs were then revalidated without another provider
call. Strict acceptance changed from `3/10` to `4/10`. All ten original model
payloads were structurally unchanged in the revalidation comparison; no
revalidation model call occurred, no MSER pipeline error occurred, and all
candidate/safety invariants remained intact.

The additional pass is stale-weather: its sourced `UNKNOWN + DELAY` answer now
binds to a typed weather gap receipt. `RTE-022` remains rejected correctly. The
old provider run did not execute the newly required Major Points tool, so its
Map Perception gap receipt cannot be used as evidence for
`navigation.next_checkpoint`. `NAV-001` and `RPF-041` also remain rejected
because the frozen outputs emitted action decisions for factual lookups and/or
did not cite the newly supplied scenario provenance. The three `PER-099`
safety cases remain fail-closed.

A fresh `NAV-001` and `RTE-022` provider run was attempted at:

`/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI/outputs/evals/six_forces_600_openrouter_deepseek_v4_flash_newscout-task-aware-provenance-nav-rte-20260825`

OpenRouter returned HTTP `401 User not found` for every attempt. This was later
traced to a credential-source mismatch: the successful ten-case run used
`/Users/alexwang0315/.scout/.env`, while the failed retry used the different key
in `/Users/alexwang0315/scout-project/.env`. It was not an OpenRouter outage or
a DeepSeek answer-quality result.

The three factual cases were rerun with the successful credential source at:

`/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI/outputs/evals/six_forces_600_openrouter_deepseek_v4_flash_newscout-task-aware-factual-correct-env-20260825`

`RPF-041` and `RTE-022` passed on their first model request. `NAV-001` produced
a correct, MSER-verified answer on its first request, but the legacy outer
verifier rejected MSER-certified `workspace://...#sha256` references because
they were absent from its allowlist. The allowlist now includes server-owned
MSER certificate refs. A NAV-only proof run then passed at:

`/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI/outputs/evals/six_forces_600_openrouter_deepseek_v4_flash_newscout-task-aware-nav-certified-source-fix-20260825`

The final accepted trajectories are `3/3` strict PASS, one model request per
question, two total native tool calls, and a mean latency of `15.72 seconds`.
Transport/schema and safe-uncertainty scores are `100`; mean semantic score is
`91.67`. All remain candidate-only with runtime safety truth false.

NAV still needs a deterministic consistency repair: its answer repeats both a
route length of `36.505 km` and route progress of `59.25 km` without surfacing
the contradiction. It passes provenance and authority gates but remains
`NEEDS_REVIEW`, and must not be promoted as operational position truth.

Focused qualification under Pydantic AI `2.33.0` is `160 passed`; Ruff reports
no issue on the changed Python surface.

## Praison Research Probe

The original compound `EXP-100` research query was routed through:

```text
Pydantic IntelligenceRequest
  -> MCP
  -> PraisonAI deterministic router
  -> Research specialist
  -> web.search
```

Request `db1e8876-5773-4117-a4b4-301d0546f451` returned typed UNKNOWN because
the single compound search produced no in-scope official result. It made no
finding and no fetch call.

A focused official-domain query then passed:

- Request: `8aeb4ac1-525c-4040-ac54-0b27506ed0d8`
- Route: `Praison orchestrator -> deterministic router -> Research`
- Tools: `web.search`, `web.fetch`, `web.fetch`
- Result: two candidate-only Taroko National Park evidence records
- Core contract validation: accepted
- Runtime safety truth: false

The contrast proves that bounded Web Search works, but the current Praison path
does not yet decompose a long research question into history, natural
environment, and terrain subqueries. Its candidate evidence is also not yet
injected into the Pydantic final-answer context.

## Architecture Conclusion

The present New Scout components work individually, but they are not yet one
composed answer architecture:

```text
Current answer path:
Pydantic AI -> typed Workspace tools -> model -> MSER verifier

Current research path:
Pydantic Intelligence Gateway -> MCP -> Praison Research -> candidate evidence

Missing composition:
validated Praison candidate evidence -> task-aware context compiler
-> Pydantic final answer -> answer-mode-aware MSER gate
```

Consequently, adding a larger model alone is unlikely to raise strict answer
success materially. The strongest immediate gains are in control-plane context
requirements and typed evidence composition.

## Recommended Next Slice

1. Add a deterministic route-progress/route-length contradiction gate before
   using NAV or CP answers as operational evidence.
2. Determine why the synthetic `59.25 km` progress exceeds the bound
   `36.505 km` route length, then repair the fixture or route binding.
3. Add bounded Praison query decomposition and feed only gateway-accepted
   candidates into the Context Compiler.
4. Expand the fresh provider run to the frozen ten cases, then to a 30-question
   matrix only after the three factual cases pass.

## Raw Evidence

The complete run is retained at:

`/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI/outputs/evals/six_forces_600_openrouter_deepseek_v4_flash_newscout-pydantic233-deepseek-v4-flash-0731-sixforce-smoke-20260825`

- `model_summary.json` SHA-256:
  `446469c9564fcdef14919ddfd4d1fc3145fa027b2c22e8de843794a428dabd42`
- `per_case_results.jsonl` SHA-256:
  `be42591c9e3a9e21481479ea1ceaa1b43d8a38fb1a7f76540b09ea6f88278689`
- `mser_revalidation_integrity.json` SHA-256:
  `123bd619f2fffe67c6c3617f7d750f92d69d880c01cdf732d30a00bedaf0ff7a`
- factual three-case `model_summary.json` SHA-256:
  `45a758dc243d4957c9eafa8bacd70e8a3ba49e833f8ad69519a911de68518739`
- NAV source-fix `model_summary.json` SHA-256:
  `f8f5e39ff6f115b30a0b408b4ea31a818a87700ba77d56676e8802fe69741285`

No production routing, Workspace state, mission state, permission, safety,
emergency, notification, or hardware state was modified.
