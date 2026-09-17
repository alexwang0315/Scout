# Workspace native retrieval: capability evidence and known stall

Date: 2026-09-07. Status: `WORKING_PROTOTYPE`; decision: `CONTINUE_RESEARCH`.
This is a sanitized, version-controlled summary of local experiment reports,
not a new live model run or production qualification.

## Executable path and boundary

An empty-evidence question enters the isolated MCP background queue, then a
Praison Research specialist invokes ScoutModelGateway and Pydantic AI native
tools. The model discovers permitted filenames, inspects schema, and selects
typed queries. Deterministic Python validates grants, source hashes, query
operations, execution receipts, and cited scalar facts. Expected answers are
not supplied to the service. The six-file inventory is explicitly scoped;
whole-workspace discovery and general natural-language answer quality remain
unproven. There is one specialist, not demonstrated multi-agent collaboration.

All answers remain `candidate_only=true`, `runtime_safety_truth=false`.
Historical data never grants route, permission, emergency, or hardware authority.
The tools are read-only; audit files belong outside the source workspace.

## Recorded live evidence

Local audit sources (intentionally excluded from the tracked summary):

- `artifacts/scout-ai-nextgen/workspace-retrieval-20260907/README.md`,
  corrected `root-scope-verified/qualification.json`, and
  `postrun-verification.json`.
- `artifacts/scout-ai-nextgen/workspace-retrieval-deepseek-20260907/README.md`
  and `qualification-verified.json`.

The corrected Sol development run completed five questions with 22 model
requests and 22 native tool calls. It is historical evidence: the CLI now
defaults to `deepseek/deepseek-v4-flash-0731` and tool-output mode, so its current
default invocation does not reproduce that historical model configuration.

The DeepSeek experiment eventually verified all five questions using selected
successful trajectories from `candidate-count-retry`, `remaining`, and
`review-status-retry`. Those selected trajectories used 28 model requests,
33 attempted calls, and 32 executed tools, with one typed schema rejection.
They are not one uninterrupted five-case run. Across all 14 attempts there were
six valid final outputs (one repeated case), five failures, and three
cancellations. All 92 observed responses named the requested DeepSeek model;
three cancelled requests had no observed response. No fallback-model success
is implied. Dependency and adapter changes prevent a held-constant comparison
between models or between the initial and repaired DeepSeek attempts.

Repair history includes a flat tool-input schema and verifier corrections for
wrapped/unwrapped arguments and typed kernel rejections. Original failed traces
and scores remain preserved. Successful scalar validation does not independently
qualify free-form prose semantics, unseen questions, or runtime safety.

## Known issue: WRT-DEEPSEEK-RESPONSE-STALL-001

Two repaired trajectories stopped receiving model output after successful
workspace queries. Operators cancelled them at 714.688 and 440.922 seconds of
inference time. No SDK/provider timeout exception established a root cause.
Later fresh requests succeeded, proving observed recoverability but not
reliable automatic recovery. Provider, transport, and client causes remain
unresolved.

Unblock evidence: add request/response lifecycle instrumentation and verify
cancellation/retry using the exact configured model, then demonstrate one
uninterrupted five-case run. Do not repeatedly rerun this issue without new
evidence or a relevant change, silently substitute another model, or impose a
new Scout cumulative time/token ceiling to hide the stall.

## Commit-preparation regression

`WorkspaceToolBackend` now uses the shared `pydantic_agent_runtime_kwargs()`
helper, retaining ten retries and explicitly choosing `end_strategy="early"`
as required by `docs/specs/scout-ai-workspace-agent-tool-spec.md`.

The focused service replay uses actual Praison/Pydantic execution and real
temporary workspace files with an HTTP mock provider. It covers native output,
tool output, and a tool response containing both a valid `final_result` and an
additional executable search. Existing assertions require exactly three
workspace receipts and their matching provenance, proving the extra search
does not execute after the valid output. This compatibility repair is not
claimed to fix the provider-response stall.

Checks recorded for this repair: **30 passed in 8.57 seconds**, scoped Ruff
clean. A process-local negative control forced `end_strategy="exhaustive"`;
the mixed-response case failed because provenance contained an extra
`workspace.catalog.search`. No source file was changed for that negative
control. This confirms that the regression distinguishes the execution
behavior rather than merely checking constructor arguments.

Reproduce without credentials or external model calls:

```bash
rtk proxy ./venv/bin/python -m pytest tests/test_scout_ai_workspace_retrieval.py -q
```

For preparation only, supply an authorized workspace and existing QGIS run:

```bash
rtk proxy env PYTHONPATH=.:src ./venv/bin/python \
  tools/scout_ai_workspace_retrieval_qualification.py \
  --workspace-root "$SCOUT_RETRIEVAL_WORKSPACE" \
  --qgis-run "$SCOUT_RETRIEVAL_QGIS_RUN" \
  --model-config configs/scout-nextgen-openai-compatible.openrouter-deepseek-v4-flash-0731.json \
  --structured-output-mode tool \
  --output-dir "$SCOUT_RETRIEVAL_NEW_AUDIT_DIR"
```

Use a new audit directory outside the source workspace for each attempt.
Preparation makes zero model requests. Adding `--live` executes cloud inference
and requires the existing scoped authorization and privately configured
credential; never put credential values in command arguments or this report.
Private oracles, raw traces, coordinates, and workspace records remain local.
Rollback is to stop using the isolated entrypoint; no production switch is made.

Full repository, browser/GIS, hardware, held-out semantic evaluation, and
production hardening are outside this slice and are not claimed.
