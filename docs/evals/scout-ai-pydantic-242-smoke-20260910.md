# Scout Pydantic AI 2.42.0 Compatibility Qualification

Date: 2026-09-10 (Asia/Taipei)

Status: **WORKING PROTOTYPE - Mac compatibility verified**. No hardware
deployment, Dashboard restart, production promotion, or 1,000-question replay.

## Scope And Versions

The upgrade starts from clean Scout Commit Gateway baseline
`d97781db19c2bad950d7e3839ce8ce065b2739a2`. The Mac checkout has no local Git
repository; source delivery uses the Scout gateway, not a runtime redeployment.

| Distribution | Before | After |
| --- | --- | --- |
| pydantic-ai-slim | 2.41.0 | 2.42.0 |
| pydantic-evals | 2.41.0 | 2.42.0 |
| pydantic-graph | 2.41.0 | 2.42.0 |
| praisonaiagents | 1.7.4 | 1.7.4 |
| openai | 3.8.0 | 3.8.0 |

Interpreter: repo `venv`, Python 3.12.3. Before/after package inventories show
only the three Pydantic AI family packages changed. Editable project metadata
was rebuilt without dependency resolution. `uv pip check` verifies all 107
installed packages are compatible. No Praison CLI or additional provider was
installed or enabled. Pi admin/live/intelligence manifests are aligned to
2.42.0 for future deployment; this does not report an installed Pi version.

Official changes: [2.42.0 release](https://github.com/pydantic/pydantic-ai/releases/tag/v2.42.0),
[strict deferred approvals](https://github.com/pydantic/pydantic-ai/pull/8081),
[tool-content validation](https://github.com/pydantic/pydantic-ai/pull/7823),
[Code Mode references](https://github.com/pydantic/pydantic-ai/pull/8056).

## Verification Results

| Check | Observed result |
| --- | --- |
| Pre-upgrade 2.41 capability regressions | 9 passed, 3.52 s |
| Pre-upgrade known Praison MCP failure case | 1 passed, 4.76 s |
| New contracts and compatibility smoke unit suite | 34 passed, 10.02 s |
| Complete focused Pydantic/Praison suite | **128 passed, 24.56 s**, no skips/failures |
| CLI offline checks | **23/23 passed** |
| Real OpenRouter checks | **9/9 passed**, scope distinction below |
| Combined CLI report | **32/32 passed**, not 32 live questions |
| Ruff | All checks passed on the three changed Python files |
| Dependency resolution | 107 compatible packages |

New checks exercise actual Pydantic Agent deferral and resumption with local
fixture tools. None/string/integer/container approval values fail before
execution and cannot be coerced through JSON. Valid booleans and typed
`ToolApproved`/`ToolDenied` retain their behavior, including reviewed argument
overrides. Approved resumes execute once; denied resumes execute zero tools.
These fixtures do not grant permanent workflow or real-world effect approval.

The history smoke preserves 300 nested evidence cards, all source references,
candidate flags, tool-call identity, and a nested image through save/load/save.
Ambiguous URL mappings remain user data; explicit image media metadata restores
`ImageUrl` without network access. Code Mode checks cover scalar, array, enum
and nullable aliases in parameters/returns, using the SDK's actual signature
builder. They do not execute generated code or qualify the separate Monty
sandbox runtime. The existing 2.38/2.40/2.41 regression cases remain in the suite.

## Real OpenRouter Evidence

Model: `openrouter:deepseek/deepseek-v4-flash-0731`.
Credentials loaded server-side from `~/.scout/.env`; values are never recorded.
The exact model was not switched, and no hardware/local-model substitution was
used in these nine live checks.

| Path | Evidence |
| --- | --- |
| Function tool | `scout_runtime_version` call/return, installed `2.42.0` |
| Structured output | Validated `status=ok`, `runtime_version=2.42.0` |
| MCP streaming | `route_marker` -> `MCP-CP-07`; call/result/run-result events |
| Stream events | Real response deltas and final run-result event |
| Provider-native WebSearch | **Transport compatibility only**; no native call/return parts exposed |
| Scout traced WebSearch Capability | Real `scout_web_search` call/return with public search results |
| Scout traced WebFetch Capability | Real `scout_web_fetch`, HTTP 200, official Pydantic page title |
| ToolFailed | Failure delivered to model with no invented fixture value |
| ModelRetry | Two tool calls, one retry prompt, final `retry-recovered` |

Native-search prose alone is not proof of a search. Its report explicitly sets
`qualification_scope=provider_transport_only` and
`provider_exposed_native_parts=false`. Auditable search evidence comes from the
separate Scout function tool trace. One search backend reported a network
error; Brave/DuckDuckGo returned results and the traced search check succeeded.
This upgrade does not disable research or bypass the existing network guards.

The report retains bounded tool-return excerpts, not a complete provider token
ledger or full prompt archive. These are compatibility/transport checks, not an
answer-quality benchmark or performance SLA.

## Praison Deadline Investigation

Existing issue: `PRAISON-MCP-REPLAY-DEADLINE-001`. The previously failing test is
`test_model_backed_praison_team_runs_behind_mcp_process`. On this Mac it passes
**before** upgrading, so the earlier timeout cannot be credited as a 2.42 fix.

The same fixture replay was instrumented with monotonic phase timing and
Python import timing. No provider credentials were forwarded. Original limits
remain: initialize 30 s, tool execution 20 s. No runtime deadline was increased.

| Phase, seconds | 2.41.0 | 2.42.0 |
| --- | ---: | ---: |
| Process spawn | 0.0049 | 0.0030 |
| MCP initialize, including child imports/service construction | 2.4398 | 2.2208 |
| tools/call | 0.2419 | 0.2370 |
| Total with cleanup | 2.6969 | 2.4709 |
| Child cumulative pydantic_ai import, included in initialize | 1.7720 | 1.5539 |
| Child cumulative praisonaiagents import, included in initialize | 0.0183 | 0.0090 |

Both replays produced three findings, one fixture model request, and accepted
candidate-only responses with `runtime_safety_truth=false`. Import timings are
nested cumulative values, not independent stages to add to initialize time.

Current diagnosis: initialization/import dominates this small replay; inference
execution is short. The historical slow-run cause is **not reproduced or fully
proven**. Keep the issue open as intermittent, not as an upgrade regression.
If it recurs, collect the same phase timing alongside contemporaneous host
CPU/memory pressure. A package-version change or relaxed timeout alone is not
evidence of a repair. No tool, model or MCP production behavior was changed.

## Tool-Content Microprobe

A 48,302-byte, 300-card fixture was validated 50 times per repetition, five
repetitions per mode; adapters were warmed before measurement. Payload SHA-256:
`524e81089dfba5c080a06de441fbbfea26f273f061eaa82bced7953d6bc9e832`.

| Median ms/call | 2.41.0 | 2.42.0 |
| --- | ---: | ---: |
| validate_json | 9.769 | 10.966 |
| validate_python | 8.650 | 7.346 |

Mixed results on a shared, non-isolated Mac do **not** establish an overall
speedup, regression, or improved answer quality. This is a diagnostic sample,
not an acceptance ceiling. Do not apply upstream microbenchmark speedup claims
to Scout's full request latency.

## Reproduction And Artifacts

Raw evidence is retained locally under
`artifacts/pydantic-ai-242-20260910/` (excluded from gateway commits). It contains
`focused-suite.xml`, `new-contracts.xml`, `baseline-241.xml`, `baseline-mcp.xml`,
`live-openrouter.json`, before/after package inventories, the installation plan,
`probe_tool_content.py`, `probe_praison_mcp.py`, and before/after probe JSON.
The original run directory was
`/private/tmp/scout-pydantic-242-20260910-YuVtrL/`.

```bash
rtk proxy ./venv/bin/python -m pytest \
  tests/test_pydantic_ai_compat_smoke.py \
  tests/test_pydantic_ai_runtime_compat.py \
  tests/test_pydantic_ai_238_compat.py \
  tests/test_pydantic_ai_240_compat.py \
  tests/test_pydantic_ai_241_compat.py \
  tests/test_pydantic_ai_242_compat.py \
  tests/test_praison_runtime_compat.py \
  tests/test_scout_ai_exp_praison_bridge.py \
  tests/test_scout_ai_praison_background_mcp.py \
  tests/test_scout_ai_praison_background_mcp_http.py \
  tests/test_scout_ai_praison_background_queue.py \
  tests/test_scout_ai_praison_mcp_slice.py \
  tests/test_scout_ai_praison_web_research.py -q

rtk proxy ./venv/bin/python -m scout.cli.pydantic_compat_smoke \
  --live-openrouter --model deepseek/deepseek-v4-flash-0731 \
  --env-file /Users/alexwang0315/.scout/.env

rtk proxy ./venv/bin/python artifacts/pydantic-ai-242-20260910/probe_praison_mcp.py
rtk proxy uv pip check --python ./venv/bin/python
```

No full 1,000-case rerun, Hailo inference, hardware performance measurement,
Navigation/GIS regeneration, browser UI test, or unrelated full-stack suite
was performed. The 32-layer GIS gate is not applicable to this dependency and
compatibility-only change. Hardware promotion remains a separate task.
