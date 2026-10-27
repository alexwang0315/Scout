# Praison Agents 1.7.17 isolated Mac qualification

Date: 2026-10-27, Asia/Taipei.

**PARTIAL qualification. Do not promote this report to a production, model-quality,
JEV-routing, or hardware acceptance claim.** Only a private package overlay was
installed. Active Mac distributions, runtime pins, services, and Scout hardware
were not upgraded or restarted. No paid cloud model was called.

## Scope and installation

| Component | Active Mac before and after | Isolated candidate |
| --- | --- | --- |
| Python | 3.12.14 | Same interpreter |
| praisonaiagents | 1.7.12 | 1.7.17 |
| pydantic-ai-slim / evals / graph | 2.56.0 | Unchanged |
| websockets | Not installed | 17.3, to satisfy the MCP extra |
| Praison CLI / LiteLLM | Not installed | Not installed |

The SDK wheel was downloaded from PyPI, checked against its published SHA-256,
and inspected for Python startup hooks before installation:

`4db2d78cffbf7db8f9b1d6f92bf615ef618c0283b4976a568389eeafabed15a3`

The first candidate dependency check found the existing missing optional
`websockets>=12.0` dependency. It was added only to the overlay, its wheel hash
was checked, and the base plus MCP-extra dependency check then passed. The
complete candidate regression and real public-web smoke were rerun afterward.
Existing customized FastAPI/Starlette and all active venv packages were retained.
The active venv's `pip check` also passed.

Official release and implementation references:

- [Agents 1.7.17](https://pypi.org/project/praisonaiagents/1.7.17/).
- [Release comparison](https://github.com/MervinPraison/PraisonAI/compare/v4.7.18...v4.7.19).
- [Team rerun and retrieval state](https://github.com/MervinPraison/PraisonAI/pull/5981).
- [Custom LLM fallback](https://github.com/MervinPraison/PraisonAI/pull/6053).
- [Configurable loop guard](https://github.com/MervinPraison/PraisonAI/pull/6057).
- [OAuth and urllib redirect checks](https://github.com/MervinPraison/PraisonAI/pull/5970).
- [Context Replay](https://praison.ai/docs/features/replay/).

## New regression contracts

`tests/test_praison_1717_compat.py` adds 21 fixture-backed assertions with network
connections blocked, synthetic credentials, and temporary SDK homes:

- Sync/async `AgentTeam.start/astart` runs the second question rather than
  returning the first answer; earlier question context is absent and
  operator-supplied task variables remain intact.
- Real SDK custom-LLM recovery wrappers classify a synthetic OpenRouter 503 as
  fallback eligible and a 401 as non-eligible. Primary object/model identity
  remains unchanged. Provider transport and model responses are fixtures, not
  actual OpenRouter API calls.
- Same-provider fallback inherits connection settings; cross-provider fallback
  does not inherit fixture keys, authentication, or base URL. Bare names retain
  their configured provider connection.
- A tool that has already executed is not executed again by model fallback.
- Per-call RAG overrides do not mutate shared configuration; malformed retrieval
  filters raise before knowledge access.
- OAuth private/numeric hosts are rejected before HTTP. OAuth and the urllib
  WebFetch fallback reject an internal redirect before issuing its request.
- `ExecutionConfig(max_iter=10, max_execution_time=0)` preserves ten progressing
  read-tool calls across a simulated long-running turn. No Scout resource policy
  was weakened or new answer token/time budget imposed.
- A real SDK AgentFlow emits schema-1.1 step/run/parent relationships; source
  references survive and a synthetic credential is redacted. This validates SDK
  trace emission, not the uninstalled CLI's HTML/OTLP export or rerun features.

The module follows the existing candidate-version gate. It does not change the
active pin assertion. For the negative control, the identical test bodies were
forced on active 1.7.12 with `SCOUT_RUN_CANDIDATE_BASELINE=1`: all 21 failed.
Several failures are missing new APIs; this is not a count of 21 security bugs.

## Results

| Check | Observed result |
| --- | --- |
| New candidate assertions | 21 passed |
| Active old-stack affected regression, final isolated temp root | 111 passed, 2 existing xfailed |
| Candidate affected regression after MCP-extra repair | 136 passed, 2 existing xfailed, 1 explicitly deselected active-pin assertion |
| Original assertions on active old SDK | 21 failures, retained negative control |
| Known issues with xfail disabled | Both existing failures reproduced |
| Real public WebSearch/WebFetch through SDK/MCP child | 10/10 execution/boundary gates passed |
| Actual workspace two-query SDK orchestration replay | 6/6 read/source/exactness gates passed; no LLM called |
| New repository Python module | Ruff passed |
| Candidate base and MCP-extra dependencies | Satisfied after isolated websockets installation |
| Active package inventory before/after | All 108 versions and third-party paths unchanged; editable Scout metadata alias noted below |

The deliberately deselected assertion is
`tests/test_praison_runtime_compat.py::test_praison_core_version`, which requires
the unchanged active 1.7.12 pin and passes in the active baseline. The overlay
version and source directory are independently checked in the candidate process
and attested by the real MCP child. No old assertion or xfail was relaxed.

Two SDK issues remain acceptance gaps, not passes:

| Stable issue | 1.7.17 observation |
| --- | --- |
| PRAISON-SYNC-LATENCY-CLOCK-001 | SDK synchronous latency can be negative; unchanged nonnegative assertion fails |
| PRAISON-STREAM-FIRST-ARGS-001 | Initial SSE tool-call arguments are dropped; unchanged JSON assertion fails |

Existing regression coverage includes sync/async tool calls and returns,
structured output parsing, memory tenant scope, typed workflows, MCP process and
HTTP boundaries, cancellation, queue persistence, model gateway behavior, and
candidate-only authority. A passing fixture transport is not a live provider
result, and the two existing xfails prevent full acceptance.

## Real execution evidence

An ephemeral reviewed file launcher starts the existing
`scout.nextgen.intelligence_mcp_server --mode praison-live-web` path. Its own
attestation records Agents 1.7.17 from the private overlay and Pydantic AI 2.56.0.
The normal server launcher and services were not changed.

Final request ID: `5e3e43cd-fde4-491d-92ac-916ffe2aa9a4`.

Observed tools: `web.search`, `web.fetch`, `web.fetch`. Both official-domain
pages returned HTTP 200 with source URLs, fetch timestamps, and content hashes.
All ten existing transport, research-specialist, evidence, and candidate-only
gates passed. This is Scout public-web tool execution under SDK orchestration,
not provider-native WebSearch and not Praison cloud-model synthesis.

Both fetched artifacts explicitly report `truncated=true` at the existing
20,000-character projection. The broader product changelog is also less specific
than the AI changelog. Therefore the green execution gate must not be read as
complete-document retrieval or complete-answer quality. No new cap was added in
this qualification; altering the existing web projection was outside the
isolated-dependency scope.

The actual workspace replay reads:

`/Users/alexwang0315/workspace/dongqing_batongguan_historic_trail_newImport`

Using the existing `WorkspaceQueryService`, the same SDK Team runs a complete
CP count and then a complete `checkpoint_type` grouping through the documented
`team.start(content)` input. The second answer is not the first answer:

- CP candidates: 219.
- Groups: route_progress 179, rest_area 38, start 1, finish 1.
- Source: `candidates/checkpoints.json`.
- Source SHA-256:
  `a586f80a9ab3bfbe85addf62362424cf6af45dba77c247366087b30c6d7bde86`.

All six replay gates pass, including exact comparison against the original JSON,
no truncated list, and unchanged source bytes. The receipt explicitly records
`selected_model_called=false` and
`evaluation_kind=SDK_orchestration_replay_not_model_benchmark`. These are not two
successful LLM benchmark questions and are not JEV dispatch evidence.

## Preserved interruptions and harness repairs

- Initial active/negative runs encountered warnings from pytest's pre-existing
  shared temp-directory cleanup. Later runs use fresh receipt-local `--basetemp`
  directories; no manual deletion or warning filter was used.
- The first known-issue replay failed at setup because the private temp parent
  did not exist. The receipt driver now creates that parent; the next run
  reaches both original assertions and reproduces the actual SDK defects.
- The first private workspace replay mutated `Task.action` after Team creation,
  which retained a compiled initial task template. The harness was changed to
  the supported `team.start(content)` input and the real-data replay passed.
  This was a harness correction, not a fix to Scout runtime or model quality.
- The private inventory driver changed from last-match to first-match metadata
  enumeration while this task was running. Its first exact-path audit failed
  only for the editable `scout-ai-os==0.1.0` metadata alias: repo
  `src/scout_ai_os.egg-info` versus venv `scout_ai_os-0.1.0.dist-info`. Both
  directories exist. All 108 versions and every third-party package path match;
  the manifest records this exact first-party alias difference rather than
  claiming the raw inventories are byte-identical.
- Original failed/setup-error logs and XML remain in the receipt directory.

## Reproduction and remaining boundaries

Private receipt root:

`/Users/alexwang0315/.scout/evals/scout-praison-1717-20261027/`

The directory contains the wheel hashes, overlay, before/after inventories,
credential-free runner, test logs/XML, dependency receipts, MCP child
attestation, live web output, workspace replay, qualification manifest, and
new-file patch. Tests receive a minimal synthetic environment, not real env-file
values. The live query contains only public documentation terms.

Reproduce the focused suite with the private `run_checks.py` driver in
`candidate` mode, which prepends `overlay`, repo `src`, and repo root to
PYTHONPATH. Its recorded JSON receipts contain the exact argument lists.

Only these repository paths are new in this task:

- `tests/test_praison_1717_compat.py`
- `docs/evals/scout-ai-praison-1717-candidate-20261027.md`

No runtime source, dependency pin, existing test, Dashboard/GIS path, safety
truth, or hardware control was edited. Pydantic AI was intentionally not
upgraded alongside Praison. No live OpenRouter fallback, paid model synthesis,
Hailo/UPS performance, full CLI replay/export, or 100/600/1,000-question quality
benchmark was qualified. The SDK-only overlay does not include LiteLLM or a
full Praison CLI; tests of the custom-LLM wrappers use a fixture provider.

Promotion remains separate and should retain the two SDK known-issue gates and
verify the actual chosen live model/provider path before changing services.

The original qualification encountered a gateway error,
`Staging checkout diverged from Scout bare server`; that historical observation
and the original blocked manifest are retained.

## Authorized gateway repair and selective commit

On 2026-10-27 the user authorized repairing the gateway and committing only the
two paths above. Inspection found local staging was **ahead by two existing
commits and behind by zero**, not genuinely divergent. The old guard accepted
only identical or behind histories and incorrectly rejected a valid ahead state.

The operator gateway repair accepts an ahead ancestor relationship while still
rejecting actual divergence. It adds repeated `--path` selection: rsync sends
only those files without `--delete`, and `git commit --only` leaves unrelated
staged and unstaged work out of the new commit. `status` now fetches/reports
metadata without rsync or fast-forwarding the worktree. Thirteen fixture Git
tests and Ruff pass, including preservation of unrelated partial staging.

The two older commits are retained without rewriting; their synchronization is
fast-forward-only to Scout's existing local bare repository, not a GitHub push.
No reset, force-push, stash, local `.git` recreation, or all-files snapshot is
used. Before/after receipts compare unrelated worktree content and index entries.
The gateway helpers live outside the project checkout; their original copies,
candidate patches, tests, and preservation/commit receipts are under the private
`gateway-repair/` receipt directory. They are not extra files in this two-path
qualification commit, and no Scout runtime service or hardware is deployed.
