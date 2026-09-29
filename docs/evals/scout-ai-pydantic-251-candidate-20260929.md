# Pydantic AI 2.51.0 isolated qualification

Date: 2026-09-29. Outcome: **PARTIAL / not approved for promotion**.

This run first tested the 2.51.0 candidate on Mac, then exercised an isolated
2.51.0 environment on Scout's Hailo-10H. It did not change the active venv,
Pydantic AI version pins, running services, or hardware configuration. The active `pydantic-ai-slim`,
`pydantic-graph`, and `pydantic-evals` versions remain 2.45.0. Candidate packages
were loaded from `/private/tmp/scout-pydantic-251-20260929/candidate` with the
repository venv interpreter. A separately resolved venv was then built at
`/private/tmp/scout-pydantic-251-20260929/resolved-venv`. Scout's separate test
venv was `/tmp/scout-pydantic-251-hailo`. The running Scout API uses a separate
`scout-ai-os-hardware-current` venv (Pydantic AI slim 1.106.0), and the older
Scout worktree venv reports 2.43.0; neither was changed. These are not a
controlled version-to-version hardware-performance comparison.

Official release references: [2.50.0](https://github.com/pydantic/pydantic-ai/releases/tag/v2.50.0)
and [2.51.0](https://github.com/pydantic/pydantic-ai/releases/tag/v2.51.0).

## Evidence

| Gate | Result |
|---|---|
| Package import | All three candidate packages report 2.51.0 from the overlay. |
| Compatibility smoke | `smoke.json`: 34/34 passed, including 9 live OpenRouter checks on `deepseek/deepseek-v4-flash-0731`. |
| Focused regression | Initial overlay: 76 passed. Resolved venv: 94 passed. After the Hailo runner fix, a focused resolved-venv rerun passed 90 tests; both runs observed one `pydantic_graph/_utils.py` event-loop `DeprecationWarning`. |
| Ruff | All changed Python files pass. |
| Active-version isolation | Active venv still reports 2.45.0 for all three packages. |
| Scout Jev routing | The missing `scout.nextgen.jev_decisions` adapter was restored. One Mac Jev-to-cloud and one Scout Jev-to-local workspace lane probe passed. |
| Scout hardware performance | Three warm fixed-prompt samples, 1,902-1,951 ms, median 1,904 ms; sampled Hailo NNC peak 93.6%, die peak 49.5 C. Not a cross-version or endurance benchmark. |

The 2.50 route helpers moved from `pydantic_ai.models.typesafe` to
`pydantic_ai.models.decision`. The existing 2.47 compatibility test now uses
the correct location by SDK version. Two additional candidate-only tests check
`None` plus multiple tool-route labels and rejection of a route not offered.
These are SDK-contract tests; the separate Jev lane probe below supplies one
actual Scout cloud dispatch proof.

### Resolved dependency set

The clean test venv has 85 packages and passes `uv pip check`. Its relevant
versions are Pydantic AI slim/graph/evals 2.51.0, MCP 1.30.0, and FastMCP Slim
3.4.7. Unconstrained resolution first selected MCP 2.2.0, which removed
`mcp.server.fastmcp`. Constraining only `mcp<2` still left FastMCP Slim 4.x
incompatible. The working pair requires `mcp<2` **and** `fastmcp-slim<4`; both
bounds were added to the smoke extra and the three Pi requirements files, while
their Pydantic AI 2.45.0 pins stayed unchanged.

The resolved-venv live smoke passed 34/34 checks. Its one event-loop warning
also occurs under the unchanged 2.45 venv, so it is not a new 2.51 regression.
It remains an observed WARN rather than being suppressed.

### Live provider and research boundary

The smoke received actual OpenRouter responses. Function tool, MCP streaming,
structured output, Scout `scout_web_search`, and Scout WebFetch checks passed.
The MCP check executed one server tool and received its return. The Scout web
search and fetch checks each show one tool call and one return.

The provider-native WebSearch check reports `qualification_scope=provider_transport_only`:
the request was accepted, but **zero native search call and return parts** were
exposed. It does not prove that the provider performed a search. The live fetch
receipt contains fetched HTML in the temporary JSON; do not publish that raw
receipt as a user-facing report.

### Jev Decisions API and workspace dispatch

The restored adapter calls OpenRouter's
[Decisions API](https://openrouter.ai/blog/tutorials/how-to-use-jev/) at
`POST /api/alpha/decisions`, not Chat Completions. It sends typed `state` and
`questions`, validates the returned choice against offered criteria, and fails
closed on missing usage, malformed output, or an unoffered route. The anonymized
workspace projection contains only evidence-category names and a SHA-256 of
`project.json`; it contains no project path, answer count, or answer key.

The Mac-only `--jev-route` probe asked the blind CP-count question. Jev
`typesafe/jev-1.13-20260917` returned `cloud` (691 input, 40 output tokens),
and the receipt records `dispatch_source=jev_decision`. Scout's deterministic
route-structure tool then completed; OpenRouter DeepSeek made one native evidence
call and return; the exact verifier passed `219` and
`candidates/checkpoints.json`, with unchanged source bytes. This proves **one
cloud question** on the real Dongqing workspace. This cloud probe alone does
not prove a local choice or Hailo execution; those have a separate test below.
Neither probe establishes broad routing accuracy or safety-decision authority.

### Scout Hailo local branch and hardware samples

The blind runner now completes deterministic read-only workspace collection
before asking Jev to choose a model. Its Jev request says only whether that
evidence completed; it does not send the answer value. The local compact card
retains the route summary's source path as well as its value. Regression tests
check the execution order, source retention, and no answer leakage into Jev.

On Scout (aarch64, Python 3.13.5), the isolated venv resolved Pydantic AI
slim/graph/evals 2.51.0 with `mcp<2` and `fastmcp-slim<4`; `pip check` found no
broken requirements. The running Hailo Ollama service, Scout API, and active
Python environments were not replaced or restarted. `hailortcli scan` found
`pci/0001:03:00.0`; `/api/tags` listed `qwen3:1.7b` as HEF.

For blind question Q-001, "本旅程長度多少距離，以公里為單位回答我",
the real workspace route-structure tool completed first. Jev
`typesafe/jev-1.13` then chose `local` and the runner recorded
`dispatch_source=jev_decision`. Scout's Pydantic AI 2.51.0 FunctionModel adapter
made one request to the Hailo-backed `qwen3:1.7b`; there were zero cloud answer
model calls. It returned `89.827`, matching `route_summary.distance_km=89.827`
from `normalized/routes/route_summary.json` (original `distance_m=89827.14`).
The exact verifier passed. In the final source-retention rerun, the model-call
wall time was 16,129 ms and Hailo reported 5,592 ms total duration; an earlier
run observed 15,887 ms and 5,628 ms respectively. These single-case times may
include model loading and are not warm-latency estimates.

Three subsequent read-only fixed-prompt measurements through the same Scout
Pydantic AI 2.51.0 adapter all returned exactly `89.827`:

| Sample | Wall latency | Hailo reported duration | Output tokens |
|---|---:|---:|---:|
| 1 | 1,951 ms | 1,876 ms | 6 |
| 2 | 1,902 ms | 1,877 ms | 6 |
| 3 | 1,904 ms | 1,877 ms | 6 |

The warm median was 1,904 ms. This fixed-prompt measurement is **not** three
independent workspace-grounded questions. During the samples, 24
`hailortcli monitor` readings showed sampled peaks of 93.6% NNC utilization,
3,210/7,221 MB Hailo RAM, and 49.5 C die temperature; die voltage ranged
800-802 mV. Pi temperature readings were 47.7-48.3 C, `throttled=0x0`, and
the test Python process reported a peak RSS of 113,136 KiB. The UPS monitor
reported 90% battery, 5.097-5.119 V external 5V, and no current or historical
undervoltage. These are sampled measurements, not thermal or power guarantees.

The native Scout receipt is at
`scout.local:/tmp/scout-hailo-local-20260929-pi251/`:
`summary.json` SHA-256
`15be0fc9a4848e176ee933f662d3b189dacc572cd1f4c2d55da7198804a5ae9b`,
`per_question.jsonl` SHA-256
`c4253e756bc3555906a9d3164ec8a22c08f67f782a37bd423e5d1564e197a346`.
The Mac-to-Scout SSH-forwarded 2.51.0 probe also passed, but the native Scout
run above is the hardware-local result. The credential was supplied only to
the isolated test process through SSH stdin, not written to Scout files.

### Fixed-cloud workspace lane probe

The real workspace probe used
`/Users/alexwang0315/workspace/dongqing_batongguan_historic_trail_newImport`.
Its blind question asked for the current CP total and source file. The existing
read-only `pydantic_ai.tool.search_scout_route_structure.v0` completed, then
`OpenRouterModelCaller.call_with_context` returned:

```json
{"checkpoint_count": 219, "source_ref": "candidates/checkpoints.json"}
```

The verifier independently counted 219 entries in the source JSON and passed
all seven gates: workspace tool completion, selected-model response, one cloud
native tool call, one native return, exact integer count, exact source path,
and unchanged source bytes. The receipt stores a hash scoped to `project.json`
and the checkpoint file, not to the entire workspace. This is one fixed-cloud
`lane_probe`, not a Jev dispatch test, list-completeness test, or answer-quality
benchmark.

## Reproduction

Run from `/Users/alexwang0315/scout-fusion` with the existing venv interpreter.
The live commands load credentials server-side; do not print the env file or key.

```sh
rtk proxy env PYTHONPATH=/private/tmp/scout-pydantic-251-20260929/candidate:src:. \
  ./venv/bin/python -m scout.cli.pydantic_compat_smoke \
  --expected-version 2.51.0 --live-openrouter \
  --model deepseek/deepseek-v4-flash-0731
rtk proxy env PYTHONPATH=/private/tmp/scout-pydantic-251-20260929/candidate:src:. \
  ./venv/bin/python -m pytest tests/test_pydantic_ai_238_compat.py \
  tests/test_pydantic_ai_240_compat.py tests/test_pydantic_ai_241_compat.py \
  tests/test_pydantic_ai_242_compat.py tests/test_pydantic_ai_243_compat.py \
  tests/test_pydantic_ai_247_compat.py tests/test_pydantic_ai_251_compat.py \
  tests/test_pydantic_candidate_workspace.py -q
rtk proxy env PYTHONPATH=/private/tmp/scout-pydantic-251-20260929/candidate:src:. \
  ./venv/bin/python tools/verify_pydantic_candidate_workspace.py \
  --workspace /Users/alexwang0315/workspace/dongqing_batongguan_historic_trail_newImport \
  --output /private/tmp/scout-pydantic-251-20260929/repeated-workspace-probe.json
```

Raw receipts: `/private/tmp/scout-pydantic-251-20260929/smoke.json` and
`workspace-probe.json`. The resolved-run receipts are
`resolved-smoke-mcp1-fastmcp3.json` and `resolved-jev-workspace-probe-final.json`;
all are temporary and may be removed by the OS. The resolved run uses the same
smoke and pytest commands with
`/private/tmp/scout-pydantic-251-20260929/resolved-venv/bin/python` and
`PYTHONPATH=src:.`. Its workspace probe adds `--jev-route`.

## Remaining gates

One cloud lane and one Scout Hailo local lane are proven, but broad routing
accuracy, cross-version hardware performance, and sustained load remain untested.
Resolve or explicitly adjudicate the baseline
event-loop warning before claiming a no-WARN qualification. Keep provider-native
search classified as transport-only until execution receipts become available.
The active Mac venv and Pydantic AI version pins remain 2.45.0; the production
Scout API environment was not upgraded. No 1,000-question or general hardware
SLO claim follows from this focused qualification.
