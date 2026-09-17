# Scout Praison SDK 1.7.5 Compatibility Qualification

Date: 2026-09-11 (Asia/Taipei)

Status: **WORKING PROTOTYPE - existing Scout integration qualified locally;
three upstream SDK limitations remain**. This is not production promotion,
hardware deployment, an answer-quality benchmark, or a 1,000-question replay.

## Scope And Versions

Started with a clean Scout Commit Gateway at
`2dafdc9ff8f5249526cb3cf9d18fde922df15581`. The Mac checkout intentionally has no
`.git`; delivery through the private gateway is not a running-service deploy.

| Distribution | Before | After |
| --- | --- | --- |
| praisonaiagents | 1.7.4 | 1.7.5 |
| pydantic-ai-slim | 2.42.0 | 2.42.0 |
| pydantic-evals | 2.42.0 | 2.42.0 |
| pydantic-graph | 2.42.0 | 2.42.0 |
| openai | 3.8.0 | 3.8.0 |

Python 3.12.3, repo `venv`. Package inventories confirm only `praisonaiagents`
changed. `uv pip check` verifies 107 compatible installed distributions.
Editable project metadata was refreshed with `--no-deps`. Praison CLI is not
installed. The Pi intelligence manifest is updated for a future deployment,
but no Pi runtime upgrade, server restart, Dashboard change or hardware control
was performed.

Official reference: [SDK 1.7.5](https://pypi.org/project/praisonaiagents/1.7.5/),
[upstream release](https://github.com/MervinPraison/PraisonAI/releases/tag/v4.7.7),
[handoff and approval isolation](https://github.com/MervinPraison/PraisonAI/pull/4938),
[local embedding and tool-loop fixes](https://github.com/MervinPraison/PraisonAI/pull/4870),
[async retrieval and observability](https://github.com/MervinPraison/PraisonAI/pull/4887),
[typed workflow state](https://github.com/MervinPraison/PraisonAI/pull/4981).
The top-level release number includes CLI changes, not all of which apply to
the lightweight SDK installed here.

## Focused Results

| Check | Result |
| --- | --- |
| Pre-upgrade focused suite | 128 passed, 29.17 s |
| Final focused suite | **151 passed, 3 xfailed**, 42.70 s |
| New SDK contracts | 19 passed, 3 strict expected failures |
| Additional Scout request isolation checks | 2 passed, replay and Model Gateway paths |
| Additional MCP harness checks | 2 passed, evidence-feedback repair and failure trace |
| Initial compatibility CLI | 31/32 overall, 8/9 live; missing MCP call |
| Repaired-harness compatibility CLI | **32/32 overall**, 23 offline + **9/9 live**, native-search distinction below |
| Ruff | Passed on all five changed Python files |
| Package resolution | 107 compatible packages, only SDK version changed |

Expected failures execute; they are not skipped or counted as passes. Separate
`--runxfail` runs reproduce all three as real failures under 1.7.4 and 1.7.5.
The older SDK is installed only into an artifact-local target directory and
selected with `PYTHONPATH` for those comparisons; the active venv stays 1.7.5.

### What The New Tests Prove

- AgentTeam rejects overlapping execution from different threads and releases
  its guard for the next run. Same-event-loop async reuse remains a known issue.
- Overlapping async handoffs to one target serialize their seeded histories,
  return the correct source-specific fixture and restore the target history.
- Closing or asynchronously closing one same-named agent clears its scoped
  grants without clearing another's grants. ContextVar caches are checked in
  the same context that created the approval, not a different parent context.
- Eight sync/async and streaming/non-streaming tool-loop cases run the actual
  SDK and OpenAI transport stack against HTTP/SSE fixtures. Each verifies
  execution, tool-call ID pairing, returned source refs, final typed output,
  and recovery after a tool error. They are not live model answers.
- Async LLM start/end events are paired with nonnegative per-request timings.
  Sync pairing works, but the SDK's timing number is not trustworthy yet.
- Explicit Ollama and local OpenAI-compatible embedding configurations route
  both document content and search queries to the configured local endpoint.
  Embedding and vector-store backends are fixtures, and socket connections fail
  the test. This proves argument routing with zero egress, not operation of a
  real Ollama/Chroma server, automatic model discovery, or every SDK memory mode.
- SDK `SearchResult` and legacy dictionary retrieval both preserve evidence.
  Existing isolated opt-in file-memory tests still pass. No real personal
  memory, workspace document or API secret is loaded by these fixtures.
- Typed workflow state validates construction and explicit post-run variables,
  rejects typos and invalid types, and leaves legacy untyped flows usable.
  A handler must return `StepResult(variables=...)`; auto-generated `input` and
  `<step>_output` keys must be accounted for in a full state schema.
- Local adapters recover a textual JSON tool proposal; hosted prose is not
  reinterpreted. Parsing is not authorization, and the Scout registry and
  capability grants remain authoritative. This is not a live small-model eval.
- Both Scout Praison runtimes create distinct Teams, Tasks and approval scope
  IDs for consecutive requests. Real SDK orchestration and Pydantic model replay
  preserve request-bound receipts and three candidate findings per request.

## OpenRouter Evidence

Model remains `openrouter:deepseek/deepseek-v4-flash-0731`. Credentials are loaded
server-side from `~/.scout/.env`; no key values are printed or stored.

Initial run: **31/32 overall**, comprising 23 offline checks and **8/9 live**.
The failed live MCP case returned without calling the tool. It is a failure,
not proof that MCP was unavailable and not proof of a successful answer.

Harness repair: the MCP smoke now requires a server-side execution receipt and
uses an output validator to ask the model to obtain/use that evidence when it
tries to finish without it. No Python code fabricates a tool result or forces
a successful grade. Capacity remains 10 model requests and 10 tool calls, and
the model can finish early. A fixture demonstrates missing evidence -> retry
feedback -> model tool call -> MCP execution -> returned marker -> answer.
Post-run assertion failures now retain the bounded diagnostic trace.

The original run and the repaired-harness run are retained separately. The
second run passed **32/32**, including **9/9 live** checks:

| Live path | Recorded evidence |
| --- | --- |
| Function tool | `scout_runtime_version` -> installed `2.42.0` |
| Structured output | Validated `status=ok`, `runtime_version=2.42.0` |
| MCP streaming | One `route_marker` call/return and server execution; final answer uses `MCP-CP-07` |
| Stream events | Actual response deltas and `AgentRunResultEvent` |
| Native WebSearch | Provider transport only; no auditable native tool parts |
| Scout WebSearch | One `scout_web_search` call and result, relevance limitation below |
| Scout WebFetch | One `scout_web_fetch` call/result, HTTP 200, official page title |
| ToolFailed | One failed tool result delivered; no invented fixture value |
| ModelRetry | Two `transient_candidate` calls, one retry prompt, final `retry-recovered` |

The second live MCP run selected the tool immediately (`retry_prompt_count=0`).
It therefore proves successful execution, not that the new feedback guard
caused the difference from the initial run. The three-request fixture, not this
live sample, demonstrates recovery from an omitted call. Never replace the
initial failed artifact with a successful retry or label this an accuracy gain.

Provider-native search is a **transport-only** check when OpenRouter exposes no
native call/return parts. Actual auditable search evidence comes from separate
`scout_web_search` and `scout_web_fetch` call/return traces. Search result
relevance and answer quality are separate: the initial top result was the
Pydantic Validation get-started page rather than the requested AI changelog.
This is not graded as perfect research. Fetch returned HTTP 200 for the official
changelog URL, with page title `Upgrade Guide | Pydantic Docs`.

## MCP Phase Timing

Same faithful model-backed replay, original startup 30 s / execution 20 s
diagnostic settings. No provider credentials are forwarded to the subprocess.

| Phase | SDK 1.7.4 | SDK 1.7.5 |
| --- | ---: | ---: |
| Process spawn | 0.0052 s | 0.0039 s |
| MCP initialize, including child imports | 3.8801 s | 5.2096 s |
| tools/call | 0.3196 s | 0.2938 s |
| Total | 4.2265 s | 5.5261 s |
| Child pydantic_ai cumulative import, included above | 3.0643 s | 4.0160 s |

Both runs return three findings, one model request, accepted candidate-only
validation, and `runtime_safety_truth=false`. The previous
`PRAISON-MCP-REPLAY-DEADLINE-001` does not reproduce in either run. Most variation
is initialization/import time; one sample on a shared Mac is insufficient to
attribute a speedup or regression to the SDK. No deadline was raised.

## Known Issues

All three reproduce in both SDK versions with fixture data. Codex source review
identified library implementation issues, not missing Scout tools or a weak
cloud model. Model switching cannot repair these paths; no model was switched.
Do not patch site-packages or promote these SDK paths merely to get a green run.

| Stable ID | Reproduction and cause | Scout handling and unblock condition |
| --- | --- | --- |
| `PRAISON-SYNC-LATENCY-CLOCK-001` | `test_sdk_sync_latency_is_nonnegative`; sync SDK subtracts `time.time()` from `perf_counter()`, producing negative latency | Keep Scout's monotonic phase measurements. Unblock when both calls use one clock and the regression passes with `--runxfail`. |
| `PRAISON-ASYNC-TEAM-REENTRY-001` | `test_shared_team_rejects_same_event_loop_concurrent_runs`; thread-based owner identity admits two distinct asyncio tasks | Keep a fresh Team per request; verified for both Scout runtimes. Unblock when guard ownership distinguishes tasks while preserving sequential batch reentry. |
| `PRAISON-STREAM-FIRST-ARGS-001` | `test_stream_parser_preserves_arguments_in_initial_chunk`; initial SSE tool-call ID/name branch drops arguments in the same chunk | Keep Scout Model Gateway/Pydantic provider parsing. Ordinary split-argument SDK SSE fixtures pass; arbitrary chunk layouts are not qualified. Unblock when the parser preserves initial and subsequent arguments without changing tool IDs. |

Last evidence: `known-issues-174-final.xml` and `known-issues-175.xml` in the
artifact directory below. Initial fixture mistakes (empty Team, wrong adapter
class, patching only a non-stream provider method, and mutating a copied
workflow context) were corrected against the installed API, not reclassified
as product successes. SDK limitations remain strict xfails with stable IDs.
An upstream fix will produce XPASS and fail the suite until reviewed.

## Artifacts And Reproduction

Local retained directory, intentionally excluded from the Git gateway:
`artifacts/praison-175-20260911/`.

- `packages-before.json`, `packages-after.json`, `install-plan.log`
- `baseline.xml`, `focused-suite.xml`, `new-contracts.xml`
- `mcp-before.json`, `mcp-after.json`, `probe_praison_mcp.py`
- `live-openrouter.json`, `live-openrouter-after.json` and secret-safe logs
- `isolated-baseline-version.json`, `known-issues-174-final.xml`, `known-issues-175.xml`

Focused regressions:

```sh
rtk proxy ./venv/bin/python -m pytest \
  tests/test_pydantic_ai_compat_smoke.py tests/test_pydantic_ai_runtime_compat.py \
  tests/test_pydantic_ai_238_compat.py tests/test_pydantic_ai_240_compat.py \
  tests/test_pydantic_ai_241_compat.py tests/test_pydantic_ai_242_compat.py \
  tests/test_praison_runtime_compat.py tests/test_praison_175_compat.py \
  tests/test_scout_ai_exp_praison_bridge.py \
  tests/test_scout_ai_praison_background_mcp.py \
  tests/test_scout_ai_praison_background_mcp_http.py \
  tests/test_scout_ai_praison_background_queue.py \
  tests/test_scout_ai_praison_mcp_slice.py \
  tests/test_scout_ai_praison_web_research.py -q
```

Authorized live smoke, not a fixture test:

```sh
rtk proxy ./venv/bin/python -m scout.cli.pydantic_compat_smoke \
  --live-openrouter --model deepseek/deepseek-v4-flash-0731 \
  --env-file /Users/alexwang0315/.scout/.env
```

No full frontend, GIS, Navigation, hardware, or answer-corpus suite was run.
These surfaces were not changed. The next relevant work is resolving upstream
SDK limitations before adopting those direct SDK paths, not rerunning 1,000
questions solely for this package upgrade.
