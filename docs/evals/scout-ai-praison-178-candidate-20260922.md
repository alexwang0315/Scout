# PraisonAI 1.7.8 Isolated Compatibility Assessment

Date: 2026-09-22, Asia/Taipei.
Status: **PARTIAL VALIDATION; candidate not promoted**.

## Environment and scope

Mac Python 3.12.3. Active environment remains `pydantic-ai-slim==2.45.0`
and `praisonaiagents==1.7.6`. The candidate SDK `1.7.8` was installed with
`uv pip install --target artifacts/praison-178-20260922/candidate --no-deps`
and selected through PYTHONPATH. No service restart or hardware deployment.
Praison CLI is not part of this upgrade assessment and was not installed.
Pydantic AI 2.46.0 was not tested or installed by this assessment.

All seven unconditional candidate dependencies satisfy their installed version
constraints. `uv pip check --python ./venv/bin/python` reports 108 compatible
active packages. This does not qualify every optional SDK extra.

## Upstream review

The official release body only says `Release v4.7.10`; the GitHub compare API
successfully supplied the missing detail. Review covers the installed SDK's
corresponding v4.7.8 baseline through v4.7.10 (100 commits), including v4.7.9.

- Backend adoption recognizes the executor's `get_response` and
  `get_response_async` interfaces. Explicit legacy runtime instances are
  preserved instead of silently selecting the default backend.
- Asynchronous agent cleanup releases already-created LLM clients.
- Team/agent concurrency ownership and shared-LLM token attribution changed.
- Plugin tool registration, allow-list enforcement and clone ownership changed.
- Custom knowledge adapters are preserved; default adapter wiring changed.
- A new isolated code execution mode bridges allow-listed tools to subprocesses.
  This assessment does not enable or qualify that execution mode in Scout.
- CLI chat tool restrictions changed; the CLI is not installed in Scout here.

Sources:
[release](https://github.com/MervinPraison/PraisonAI/releases/tag/v4.7.10),
[compare](https://github.com/MervinPraison/PraisonAI/compare/v4.7.8...v4.7.10),
[SDK](https://pypi.org/project/praisonaiagents/1.7.8/).
The retained compare response is `upstream-compare.json` below.

## Results

| Check | Actual result |
| --- | --- |
| Identical focused suite, active SDK 1.7.6 | 90 passed, 3 xfailed, 48.26 s |
| Identical focused suite, isolated SDK 1.7.8 | 89 passed, 2 failed, 2 xfailed, 56.79 s |
| Three known issues with `--runxfail`, SDK 1.7.8 | 1 passed, 2 failed, 3.37 s |
| Pydantic compatibility CLI, actual OpenRouter | 34 checks passed: 25 offline and 9 live |
| Isolated SDK through real MCP and public web | 10/10 checks passed, 7.803 s; one search, two fetches, two findings |

The candidate suite's two failures are the intentionally unchanged 1.7.6
version assertion and a strict XPASS for the now-fixed Team concurrency issue.
Neither is a new functional regression. The two remaining xfails are real
defects, independently reproduced using `--runxfail`; they do not count as
passes. Existing Diagnostic/test expectations have not been changed.

Fixture coverage includes sync/async tool loops, streamed/non-streamed tool
results, structured answers, request isolation, opt-in file memory isolation,
embedding routing, typed workflow variables, background queue/MCP recovery,
and observability. These are compatibility results, not answer-quality scores
or proof of remote provider performance.

OpenRouter used `deepseek/deepseek-v4-flash-0731`, loading credentials server-side
from the normal Scout env sources. Actual calls covered tools, structured
output, MCP streaming, response streaming, WebSearch/WebFetch and error recovery.
Native search exposed **zero native call/return parts**; its PASS means provider
transport only. Auditable search/fetch execution came from the separate Scout
function tools. The CLI exercises Pydantic AI 2.45.0, not Praison model synthesis.

The separate Praison web probe selects the candidate in both the parent and MCP
child, runs the existing `praison-live-web` qualification, and records actual
web evidence. It uses the deterministic research router with SDK orchestration,
not a cloud LLM. Candidate provenance and `runtime_safety_truth=false` were
verified. No combined live Praison-to-cloud synthesis claim is made.

## Remaining issues and recommendation

| Issue | Candidate result | Next step |
| --- | --- | --- |
| PRAISON-ASYNC-TEAM-REENTRY-001 | Pass under `--runxfail`; strict XPASS in unchanged suite | Review upstream fix before updating the xfail marker on promotion |
| PRAISON-SYNC-LATENCY-CLOCK-001 | Fail: SDK mixes wall and monotonic clocks | Retain Scout timing; qualify an upstream fix before relying on SDK latency |
| PRAISON-STREAM-FIRST-ARGS-001 | Fail: first SSE chunk loses tool arguments | Retain Scout/Pydantic provider parsing; qualify an upstream parser fix |

Do not replace the active SDK on the strength of a green transport smoke alone.
Retain the candidate for follow-up, preserve existing failure checks, and review
or repair the two SDK defects before declaring full qualification. No model
switch is needed to diagnose reproducible clock/parser defects. Do not patch
site-packages or count xfails as upgrade acceptance. No 1,000-question rerun is
indicated by this dependency assessment alone.

## Evidence and reproduction

Evidence directory: `artifacts/praison-178-20260922/` (excluded from commit gateway).

- `baseline-tests.xml`, `baseline-tests.log`
- `candidate-tests.xml`, `candidate-tests.log`
- `known-issues.xml`, `known-issues.log`
- `live-smoke.json`, `live-smoke.stderr`
- `praison-web.json`, `praison-web.stderr`, `probe_web.py`
- `upstream-compare.json`, isolated `candidate/` distribution

```sh
rtk proxy env PYTHONPATH=artifacts/praison-178-20260922/candidate:src:. \
  ./venv/bin/python -m pytest \
  tests/test_praison_runtime_compat.py tests/test_praison_175_compat.py \
  tests/test_scout_ai_praison_mcp_slice.py \
  tests/test_scout_ai_praison_web_research.py \
  tests/test_scout_ai_praison_background_queue.py \
  tests/test_scout_ai_praison_background_mcp.py \
  tests/test_scout_ai_praison_background_mcp_http.py \
  tests/test_scout_ai_exp_praison_bridge.py \
  tests/test_pydantic_ai_compat_smoke.py -q

rtk proxy env PYTHONPATH=artifacts/praison-178-20260922/candidate:src:. \
  ./venv/bin/python -m pytest tests/test_praison_175_compat.py --runxfail \
  -k 'sync_latency or shared_team or initial_chunk' -q

rtk proxy env PYTHONPATH=artifacts/praison-178-20260922/candidate:src:. \
  ./venv/bin/python -m scout.cli.pydantic_compat_smoke \
  --live-openrouter --model deepseek/deepseek-v4-flash-0731

rtk proxy env PYTHONPATH=artifacts/praison-178-20260922/candidate:src:. \
  ./venv/bin/python artifacts/praison-178-20260922/probe_web.py
```

UI, Navigation and GIS were not changed. Three pre-existing modified paths
were present before work: `docs/admin/scout-dashboard-v0.1.html`,
`docs/admin/scout-dashboard-v0.1.md`, `tests/test_scout_dashboard_page.py`.
They are outside this assessment. The snapshot-only commit gateway cannot
commit this report separately without a user-approved selective workflow.
