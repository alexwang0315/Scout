# Scout Pydantic AI 2.43 Compatibility Verification

Date: 2026-09-14 (Asia/Taipei)

Status: **PARTIAL VERIFICATION**. The local upgrade is installed and the existing
compatibility CLI passes 34/34 checks, including nine real OpenRouter cases.
Broad regression has 1,250 passes, the same five pre-upgrade failures and the
same three strict expected failures. All 12 new version tests pass; no existing
test outcomes changed. Remaining failures are not counted as passes or silently
excluded. Search relevance is not qualified by a transport pass.

## Scope And Provenance

- Entry point: `./venv/bin/python -m scout.cli.pydantic_compat_smoke`.
- Execution host: Mac, `/Users/alexwang0315/scout-fusion`, Python 3.12.3.
- Gateway source HEAD at inspection:
  `1addcce9e22b1e9fa91bc28469e8c352bab4753e`, plus the scoped patch in the commit
  containing this report.
  The shared checkout contains unrelated work, not included in this upgrade.
- Installed `pydantic-ai-slim`, `pydantic-evals`, and `pydantic-graph`:
  **2.42.0 -> 2.43.0**. Praison SDK remains **1.7.5**.
- All 107 installed packages were inventoried before and after; only those
  three versions changed. Editable Scout metadata was refreshed without
  dependency resolution. `uv pip check` passes.
- Real model smoke uses OpenRouter `deepseek/deepseek-v4-flash-0731` and
  server-side `~/.scout/.env`. No secret values are included in this report.
  Fixture tests do not read operator credentials or use live network.
- No Pi deployment, existing service/worker restart, provider/model policy
  change, Praison CLI installation, persistent memory activation, or runtime
  safety mutation. Pi dependency manifests are updated for a future deployment,
  not evidence that Pi is running the new version.

## Impact And Verification Matrix

| Surface | Evidence / acceptance | Result |
| --- | --- | --- |
| Installed stack and manifests | Same exact slim/evals/graph version; keep Praison and other packages | PASS |
| OpenAI/OpenRouter stream consumer | Text/tool/text, thinking tags, one/two tools; balanced start/delta/end, call/result pairing and source refs | 8/8 PASS |
| CLI banner and JSON output | Credential-free subprocess, two agent runs; exactly one stderr banner, clean JSON stdout, API/env/CI suppression | 4/4 PASS in CLI and final pytest |
| Existing compatibility entry point | 25 offline checks, including prior 2.36-2.42 contracts and the two new checks | 25/25 PASS |
| Actual OpenRouter | 9 live checks: function, structured output, MCP streaming, events, native search transport, traced search, fetch, failure, retry | 9/9 compatibility PASS; quality limitations below |
| Python lint | Scoped runtime/helper/test files with configured Ruff | PASS |
| Broader shared provider/runtime/API/eval consumers | Same 47 pre-upgrade files plus the new version regressions | 1,250 passed, 5 failed, 3 xfailed; 3 additional passed subtests. **Not fully qualified** |
| Temporal workflow execution | No TemporalAgent, Temporal runtime imports, or dependency in Scout source/manifests | NOT APPLICABLE: no integrated execution path, identified before testing |
| Dashboard/GIS browser and hardware | No page/map/worker/runtime deployment changes in this patch | Not exercised; no UI or hardware qualification claimed |

The Vercel adapter is used as a faithful upstream stream consumer in the new
fixtures. Scout does not currently expose a Vercel UI runtime. This proves the
provider lifecycle contract, not a repaired Dashboard rendering defect.

## Demonstrated Pre-Upgrade Failure

The regression matrix uses actual Pydantic AI/OpenAI SDKs over
`httpx2.MockTransport` SSE. Agent tools really execute locally; they return
fixture route markers with source references and candidate-only metadata.
Assertions check the consumer lifecycle, not just a plausible final string.

Under **2.42.0**:

- Six of eight stream cases fail with `text-delta on ended or missing part`:
  both providers with one/two tools and ordinary text, and both providers with
  two tools and thinking tags.
- Both single-tool thinking cases pass and remain regression coverage.
- Four new banner tests cannot run their contract because 2.42 has no public
  `BANNER_ENABLED` opt-out. This is an added API, not four historical production
  defects.

Under the initial **2.43.0** test:

- All eight stream cases pass, including the six previously failing cases.
- Three banner suppression cases pass. The enabled-banner test fails because
  the new harness counted `Pydantic AI` instead of the actual `pydantic-ai v`
  header. The original stderr proves the banner was present and stdout remained
  valid JSON. Correcting that literal preserves the acceptance criterion: one
  banner on stderr and none on stdout.

An earlier fixture setup used a bare OpenRouter model ID. It was corrected to
`openai/scout-fixture` before the pre-upgrade reproduction matrix was accepted.
Both the initial and corrected artifacts are retained; harness errors are not
reported as SDK defects.

The final broad run and compatibility CLI both pass the complete 8-stream /
4-banner matrix after those two harness corrections. Existing checks were not
deleted, skipped, or relaxed to obtain these results.

## Real OpenRouter Results

The complete invocation exited 0 with `check_count=34`, `passed_count=34`, and
`failed_count=0`. It is not a deterministic-only or mock-model run: the nine
`live_openrouter_*` checks use the configured remote model, while the first 25
checks intentionally use local fixtures.

| Live check | Actual evidence |
| --- | --- |
| Function tool | `scout_runtime_version` called once; receipt and model answer both `2.43.0` |
| Structured output | Parsed output has `status=ok`, `runtime_version=2.43.0` |
| MCP streaming | Server executed `route_marker` once; call and result stream events precede final result; answer uses `MCP-CP-07` without a retry |
| Stream events | Content deltas, `FinalResultEvent`, and `AgentRunResultEvent` observed |
| Provider-native WebSearch | Request accepted and response produced; **no exposed native call/return parts**; scope is `provider_transport_only` |
| Traced WebSearch | One `scout_web_search` call and return. Search returned `Pydantic Validation` at `/docs/validation/latest/get-started/`, not the requested AI changelog. Model acknowledged the mismatch. **Execution works; retrieval relevance failed this sample** |
| Traced WebFetch | One `scout_web_fetch` call and return; official changelog URL returned HTTP 200; answer gives its `Upgrade Guide` title |
| ToolFailed | One `unavailable_candidate` call; failure visible, no invented candidate evidence |
| ModelRetry | Two `transient_candidate` calls, one retry prompt, then `retry-recovered` used in answer |

Do not promote the WebSearch compatibility predicate (actual call/return and a
source URL) to a semantic success predicate. A future search-quality change
should add or arbitrate explicit relevance criteria without overwriting this
run or disabling native research. No provider-native search execution can be
inferred from fluent text alone. No token/cost or hardware-performance
improvement is claimed from this smoke.

## Broad Regression Baseline And Unresolved Gates

Pre-upgrade run: **1,238 passed, 5 failed, 3 xfailed**, plus **3 passed
subtests**, in 474.54 seconds. JUnit counts the subtests separately (1,249).

Post-upgrade run: **1,250 passed, 5 failed, 3 xfailed**, plus **3 passed
subtests**, in 595.74 seconds (JUnit count 1,261). Comparison by test identity
finds no removed tests, no changed outcomes among existing tests, and exactly
12 added passing tests. The five failure identities below are unchanged.
This is a regression comparison, not a performance benchmark: the later run
adds subprocess/stream cases, executes in a different order, and overlaps the
authorized live smoke. These wall times do not measure model latency or a
package speedup/slowdown.

| Check | Original expectation / observed baseline | Disposition |
| --- | --- | --- |
| `test_runtime_package_versions_attest_pydantic_ai_stack` | Hardcodes 2.36.0 for slim/evals/graph; installed version already 2.42.0 | Preserve failing check and evidence; version-standard arbitration required |
| `test_live_runtime_requirements_are_not_added_to_step1_runtime_core` | Hardcodes Pi live slim 2.36.0; manifest already pins 2.42.0 | Preserve check; do not silently change its expectation |
| `test_real_monty_code_mode_executes_allowlisted_tool_and_builds_receipt` | Requires optional `pydantic_ai_harness` and `pydantic_monty`; both absent | L5 execution remains unverified and fail-closed; no host Python fallback |
| `test_l5_eval_readiness_accepts_exact_100_cases_and_confined_project` | Requires installed L5 runtime readiness; same missing dependencies | Preserve failure; do not install additional runtime as part of this three-package upgrade |
| `test_phase4_admin_docker_context_includes_runtime_import_closure` | Admin Docker import closure lacks 42 source modules | Existing packaging failure; no Docker/GIS source repair or deployment in this patch |

Diagnostic arbitration proposal, not applied: align the two stale version tests
with the reviewed current dependency target while retaining exact installed
version checks, extras, and the Step 1 isolation assertions. Keeping 2.36.0 as
the expected value instead leaves those checks failing for every current
upgrade. The user must decide before these acceptance expectations change.

Praison's three existing strict expected failures remain separate from passes:

- `PRAISON-SYNC-LATENCY-CLOCK-001`: mixed wall/monotonic clocks.
- `PRAISON-ASYNC-TEAM-REENTRY-001`: thread guard does not isolate asyncio tasks.
- `PRAISON-STREAM-FIRST-ARGS-001`: first SSE tool arguments are dropped.

See the [1.7.5 qualification report](scout-ai-praison-175-smoke-20260911.md).
Scout's fresh per-request Teams, own clocks and Model Gateway remain unchanged.

## Reproduction And Artifacts

Artifacts are local, untracked construction evidence under
`artifacts/pydantic-243-20260914/`, not deployable workspace safety evidence:

- `packages-before.json`, `packages-after.json`: installed distributions.
- `baseline.xml`: full pre-upgrade regression failures and test identities.
- `new-contracts-on-242.xml`: initial fixture setup error, retained.
- `new-contracts-on-242-corrected.xml`: six stream failures and missing new API.
- `new-contracts-on-243.xml`: initial 11-pass run and banner literal mismatch.
- `upgraded.xml`: final broad regression plus the 12 new version cases.
- `regression-comparison.json`: test-identity comparison; no existing outcome
  changes or removed cases, exactly 12 new passing cases.
- `live-smoke.json`, `live-smoke.stderr`: actual CLI result and separate stderr.
- `tested-sources.sha256`: hashes of the eight changed runtime, manifest, and
  test files used for the final checks.
- `ruff.txt`, `package-check.txt`: lint and installed-dependency checks.
- `gateway-status.json`: dirty-worktree inventory, including unrelated paths.

The before/after broad suite selection is:

```sh
rtk proxy ./venv/bin/python -m pytest \
  $(rtk proxy rg -l --glob 'test_*.py' \
    'from pydantic_ai|import pydantic_ai|pydantic_provider|pydantic_ai_compat|praison' tests) \
  tests/test_pydantic_ai_243_compat.py -q \
  --junitxml=artifacts/pydantic-243-20260914/upgraded.xml
```

The baseline omitted the new version file, which did not yet exist. Run the
new file alone to reproduce the stream/banner matrix. Live invocation:

```sh
rtk proxy ./venv/bin/python -m scout.cli.pydantic_compat_smoke \
  --live-openrouter --model deepseek/deepseek-v4-flash-0731 \
  --env-file /Users/alexwang0315/.scout/.env \
  > artifacts/pydantic-243-20260914/live-smoke.json \
  2> artifacts/pydantic-243-20260914/live-smoke.stderr
```

Native provider search transport is not proof of an auditable search execution
when the provider omits tool receipts/citations. Traced local search/fetch and
MCP call/return evidence must be reported independently. Compatibility success
does not establish better six-force answer quality or warrant a claim that a
1,000-question benchmark passed.

## Change Inventory And Delivery

The intended source-control scope is exactly these 12 files:

1. `pyproject.toml`
2. `requirements.pi.admin.txt`
3. `requirements.pi.live.txt`
4. `requirements.pi.intelligence.txt`
5. `src/scout/cli/pydantic_compat_smoke.py`
6. `src/scout/cli/pydantic_243_checks.py` (new)
7. `tests/test_pydantic_ai_compat_smoke.py`
8. `tests/test_pydantic_ai_243_compat.py` (new)
9. `docs/specs/scout-ai-tool-interface.md`
10. `docs/specs/SCOUT_AI_OS_MVP_SPEC.md`
11. `docs/specs/scout-ai-nextgen-operating-architecture-v0.md`
12. `docs/evals/scout-ai-pydantic-243-smoke-20260914.md` (this report)

The gateway status and scoped remote diff were inspected. No unrelated changes
were reverted or staged. The Mac checkout has no local Git repository; the
normal gateway commit sweeps all eligible dirty files. On September 14, the
user approved committing this 12-file scope through the Scout staging checkout.
That approval covers version control only, not hardware deployment, acceptance
standard changes, or resolution of the outstanding qualification failures.
No blanket snapshot of the unrelated work is authorized.

## Official Change Sources

- [Pydantic AI v2.43.0 release](https://github.com/pydantic/pydantic-ai/releases/tag/v2.43.0).
- [Text after tool-call streaming fix](https://github.com/pydantic/pydantic-ai/pull/8235).
- [Optional Temporal/MCP fix](https://github.com/pydantic/pydantic-ai/pull/8257).
- [First-run banner and opt-outs](https://github.com/pydantic/pydantic-ai/pull/7447).
- [Published slim 2.43.0 package](https://pypi.org/project/pydantic-ai-slim/2.43.0/).
