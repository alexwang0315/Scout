# Pydantic AI 2.52.0 Mac upgrade qualification

Date: 2026-10-01. Scope: the Mac venv, dependency declarations, and focused
compatibility tests. Scout services, hardware environments, PraisonAI, model
configuration, Dashboard, and runtime safety behavior were not changed.

Local regression gates pass. Provider-native WebSearch execution remains
**NOT VERIFIED**; its transport receipt is not search execution proof. This is
not a 600/1,000-question benchmark or production/hardware qualification.

## Upgrade And Security Reason

Official sources:

- [2.52.0 release](https://github.com/pydantic/pydantic-ai/releases/tag/v2.52.0).
- [WebFetch security advisory GHSA-v36g-jcw9-x7cw](https://github.com/pydantic/pydantic-ai/security/advisories/GHSA-v36g-jcw9-x7cw).
- [Official changelog](https://pydantic.dev/docs/ai/project/changelog/).

The advisory concerns excessive CPU/memory consumption during the SDK's local
HTML-to-Markdown conversion of attacker-controlled nested HTML. The 2.x fix is
2.52.0; provider-native fetch does not use this converter. Scout already supplies
its own local fetch callable. Tests cover both the upstream patch and Scout's
actual capability/tool path without claiming general immunity to hostile pages.

The changed Mac package versions are:

| Package | Before | After |
|---|---|---|
| pydantic-ai-slim | 2.45.0 | 2.52.0 |
| pydantic-evals | 2.45.0 | 2.52.0 |
| pydantic-graph | 2.45.0 | 2.52.0 |
| openai | 3.8.0 | 3.22.1 |
| genai-prices | 0.1.6 | 0.1.9 |

`pydantic==2.13.5`, `mcp==1.29.1`, `fastmcp-slim==3.4.7`, and
`praisonaiagents==1.7.6` remain unchanged. Existing `mcp<2` and
`fastmcp-slim<4` constraints are preserved. All Pydantic AI version declarations
in `pyproject.toml` and the three Pi requirements files now use 2.52.0, but this
does not mean those versions have been deployed to Scout.

The editable `scout-ai-os` metadata was rebuilt with `--no-deps`; `pip check`
then passed. No dependency-wide upgrade was performed. A clean recreation was
not used: the existing FastAPI/Starlette custom-wheel references point into an
unmounted `artifacts` volume. Their installed packages were preserved; the
broken symlink and external volume were not modified.

## Verification

| Gate | Observed result |
|---|---|
| Final affected regression suite | 613 passed, no warning/skip/failure reported; 74.13 seconds. |
| Final active-venv offline compatibility smoke | 25/25 passed. |
| Isolated 2.52.0 live OpenRouter smoke | 34/34 smoke checks passed, including 9 live checks. |
| Active-venv live repeat | Checkpointed rerun: 34/34 smoke checks passed; the earlier interrupted run is preserved separately and not counted. |
| Active-venv real workspace cloud lane probe | All 7 exact/source/tool gates passed. |
| WebFetch security/provenance tests | Four new fixture-backed cases passed as part of the final suite. |
| Optional SubAgents | Explicit child tool executed once; 4 model requests; fixture-only, no network or host tools. |
| Changed Python files | Ruff passed. |
| Installed requirements | `pip check`: no broken requirements. |

The initial active live repeat stalled after its streaming request and did not
produce a final receipt. It was stopped as `INTERRUPTED_NOT_VERIFIED`, not counted
as a successful run or evidence of SDK regression. A temporary runner then
executed the same existing checks, persisting each result before starting the
next. All 34 passed in that separate repeat, including stream events. No model,
tool capability, call ceiling, or verifier was downgraded for the rerun.

The regression scope includes SDK contracts (2.38/2.40/2.41/2.42/2.43/2.47/2.51/
2.52), smoke pin alignment, local WebSearch/WebFetch, model resource/session/
provider-loop lifecycle, runtime compatibility, assistant provider, model gateway,
JEV blind routing, and the workspace probe. The final suite was rerun after the
last source edit. It is broader than the four newly added tests, not the full
repository test suite.

Initial candidate failures were repaired rather than excluded: the DeepSeek
profile assertion now uses 2.52's generic forced-tool fields while preserving
the earlier-version assertions; the sync-agent fixture owns its model session
instead of hiding a deprecation warning. An initial malicious-HTML fixture
collapsed to benign whitespace; the final fixture genuinely exercises the
converter's complexity rejection. Absolute `PYTHONPATH` values preserve imports
for subprocess checks that change working directory. Ruff-only context-manager
and callable cleanup does not change tool behavior.

### Real Workspace Answer

The active Mac probe used
`/Users/alexwang0315/workspace/dongqing_batongguan_historic_trail_newImport` and
asked for the full CP count and source path without including the answer.
Dispatch is explicitly `explicit_cloud_compatibility_probe`, **not JEV routing**.

The existing deterministic `pydantic_ai.tool.search_scout_route_structure.v0`
read the workspace JSON. `OpenRouterModelCaller.call_with_context` then offered
the native evidence tool to `deepseek/deepseek-v4-flash-0731`. The model made
one tool call and received one return before answering:

```json
{"checkpoint_count": 219, "source_ref": "candidates/checkpoints.json"}
```

All seven gates passed: workspace tool completed, selected model called, native
tool call, native tool return, exact count, exact source, and source unchanged.
The hash scope is `project.json` plus `candidates/checkpoints.json`, not the
entire workspace. Provider response ID:
`gen-1790833252-IGXngyVu79kYhUNbmbfa`.

This case used 2 model requests, 1 tool call, 11,598 input tokens, and 183 output
tokens. It proves one cloud compatibility case, not broad answer quality,
list completeness, JEV routing accuracy, or Hailo/fallback behavior.

### Research And SubAgents Boundaries

In both the isolated smoke and the checkpointed active repeat, function tools,
MCP streaming, Scout WebSearch, and Scout WebFetch each show one tool call and
one return. Structured output,
stream events, ToolFailed visibility, and ModelRetry recovery also passed.

The provider-native WebSearch receipt has
`qualification_scope=provider_transport_only` and zero provider-exposed native
search call/return parts. Its passed smoke status means transport compatibility
only; search execution remains **NOT VERIFIED**. Scout callable search/fetch
and provider-native search must not be conflated.

`pydantic-ai-harness==0.52.0` was loaded only in an isolated optional test path,
not installed into the active venv or made a production dependency. The test
used explicit child agents/tools, did not use deprecated `inherit_tools`, and
confirmed disk-agent loading defaults to `None`. No disk agents, host shell,
hardware controls, or arbitrary workspace writes were enabled. The new
DecisionModel retry test verifies that the original user question remains the
text under judgment while correction prompts stay in retry history.

## Receipts And Reproduction

Private receipts are preserved under
`/Users/alexwang0315/.scout/evals/scout-pydantic-252-20261001/`:
`final-tests.xml`, `final-offline-smoke.json`, `live-smoke.json`,
`active-live-repeat-checkpointed.json`, `active-repeat-progress.jsonl`,
`interrupted-live.json`, `active-live-smoke.stderr`,
`active-workspace-probe.json`, `active-subagents.json`, and before/after package
inventories. `repeat_live_checkpointed.py` records the temporary continuation
runner. `receipt-sha256.txt` records file hashes. Raw tool payloads include fetched public
HTML and workspace evidence; they are not committed. Credential values are not
included in the report or tests.

Run from `/Users/alexwang0315/scout-fusion`:

```sh
rtk proxy ./venv/bin/python -m pip check
rtk proxy env PYDANTIC_AI_NO_BANNER=1 \
  PYTHONPATH=/Users/alexwang0315/scout-fusion/src:/Users/alexwang0315/scout-fusion \
  ./venv/bin/python -m scout.cli.pydantic_compat_smoke \
  --live-openrouter --model deepseek/deepseek-v4-flash-0731
rtk proxy env PYDANTIC_AI_NO_BANNER=1 \
  PYTHONPATH=/Users/alexwang0315/scout-fusion/src:/Users/alexwang0315/scout-fusion \
  ./venv/bin/python tools/verify_pydantic_candidate_workspace.py \
  --workspace /Users/alexwang0315/workspace/dongqing_batongguan_historic_trail_newImport \
  --output /private/tmp/pydantic-252-workspace-repeat.json
```

The live commands load existing credentials server-side. Do not print `.env`
or key values. Capacity remains 10 model requests / 10 tool calls per attempt;
this change does not introduce a lower call budget.

## Remaining Scope

- Hardware deployment, Hailo utilization, UPS, version-to-version performance,
  fallback safety, and 600/1,000-question quality were not tested in this run.
- Provider-native search execution needs observable receipts before it can be
  called verified; SDK transport acceptance is insufficient.
- Optional harness delegation is fixture evidence, not a Scout production
  subagent integration.
- No UI/map/shared-GIS source was changed. Browser/Navigation/terrain layer gates
  are not applicable to this dependency/compatibility slice.
- The commit gateway reported an existing staging/bare HEAD mismatch before
  this turn. Selective commit must preserve that history and unrelated dirty
  files; do not reset it or include a broad Dashboard/JEV snapshot.
