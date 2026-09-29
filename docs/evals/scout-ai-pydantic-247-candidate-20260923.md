# Pydantic AI 2.47.0 isolated qualification

Date: 2026-09-23. Outcome: **PARTIAL / not a deployment approval**.

## Scope

Test the recommended 2.47 candidate without changing Scout's active venv,
dependency pins, services, hardware, or unrelated work. Active Pydantic AI remains
2.45.0. No Praison upgrade or hardware/model benchmark was performed.

Official compatibility reference:
https://github.com/pydantic/pydantic-ai/releases/tag/v2.47.0

The candidate changes `NoneType` output-route naming to `None` and rejects invalid
user prompt content. TypeSafe route descriptions and optional routes also changed.
These are compatibility changes, not evidence of improved answer quality.

## Environment and evidence

- Python: 3.12.3 on Mac.
- Isolated overlay: `/private/tmp/scout-pydantic-247-20260923/candidate`.
- Pydantic AI slim, graph, evals: 2.47.0.
- Optional TypeSafe SDK: 0.7.1, installed only in overlay.
- SDK dependency resolution also installed overlay Pydantic 2.13.5, pydantic-core
  2.46.5, httpx2/httpcore2 2.13.0 and supporting dependencies. This is a candidate
  dependency set, not a one-package controlled performance experiment.
- Required non-extra dependencies for the three Pydantic packages and TypeSafe
  SDK were checked against installed versions: no violations found.
- Repository `artifacts` symlink points to an unmounted `/Volumes/MacData`.
  No symlink was replaced and no mount/deletion was attempted. Raw receipts are
  in the temporary directory above and are not durable release artifacts.

## Results

| Check | Evidence / result |
|---|---|
| Existing compatibility smoke | `smoke.json` and post-SDK `smoke-final.json`: each 34/34 harness checks passed, including 9 live OpenRouter checks |
| Focused compatibility regression | `compat-regression.txt`: 66 passed, one deprecation warning |
| New 2.47 contracts | 11 tests included in the 66: invalid/valid prompt content, None naming, described None and wrapped Choices route descriptions |
| Exact verifier negative controls | 8 passed: wrong count/source, failed workspace/model, zero native call, changed source and non-JSON answers cannot pass |
| Ruff | All three new Python files passed |
| Scout Jev integration | BLOCKED: missing `scout.nextgen.jev_decisions`; candidate and unchanged 2.45 baseline both fail collection |
| Live TypeSafe/Jev dispatch | NOT VERIFIED; schema-helper tests are not live routing evidence |
| Hardware performance | NOT RUN |

The deprecation warning is from `pydantic_graph/_utils.py` calling
`asyncio.get_event_loop()` without a current loop during
`test_duplicate_search_keeps_later_local_fallback_and_fetch`. It was not hidden or
counted as a clean qualification. The missing Jev module belongs to an existing
unfinished integration in this checkout; no replacement schema was invented to
make its tests green.

### Web evidence boundary

The provider-native WebSearch check reports `qualification_scope=provider_transport_only`
and zero exposed native search call/return parts. Its PASS means the provider
accepted the request, **not that search execution was proven**. Model prose saying
it searched is not execution evidence.

Scout `scout_web_search` and WebFetch checks do have tool-call/return evidence.
One search backend returned HTTP 429; another returned results. Do not attribute
those search results to the unobserved provider-native search path.

### Real workspace lane probe

Workspace: `/Users/alexwang0315/workspace/dongqing_batongguan_historic_trail_newImport`.

Blind question: `目前這份 workspace 有多少個 CP 檢查點？請提供完整總數與來源檔案路徑。`

The script independently reads the raw checkpoint array for verification, executes
the existing deterministic route-structure tool, then uses Scout's existing
`OpenRouterModelCaller.call_with_context`. The answer is never embedded in the
question. Research capabilities remain enabled. This is explicitly a fixed cloud
**lane_probe**, not a Jev dispatch qualification or broad semantic benchmark.

- Provider/model: OpenRouter `deepseek/deepseek-v4-flash-0731`.
- Tool: `pydantic_ai.tool.search_scout_route_structure.v0`.
- Exact model answer: `{"checkpoint_count":219,"source_ref":"candidates/checkpoints.json"}`.
- Raw JSON: 219 entries; exact source path and integer agree.
- First receipt: `workspace-probe.json`; 2 model requests, 1 native evidence call
  and return; 11,596 input tokens, 220 output tokens (162 reasoning tokens reported).
- Gate additionally checks deterministic tool completion, model response,
  native call and return, and source unchanged after inference.
- After extracting and testing the verifier, `workspace-probe-final.json` repeated
  the real provider/tool path and passed all seven gates with the same exact answer.
  This is two runs of one question, not two unique questions.
- Receipt contains request, evidence card, native trace, model metadata, verifier
  and a SHA-256 over `project.json` plus the checkpoint file. Hash scope is explicit;
  this is not a hash of every workspace file.
- This is a scalar total-count test. It does not qualify list completeness,
  cross-artifact joins, safety answers, Jev selection or Hailo.

## Reproduction

Set `PYTHONPATH=/private/tmp/scout-pydantic-247-20260923/candidate:src:.` for candidate commands.
Use the repository venv interpreter, not a system Python. Live commands load keys
server-side through the existing env loader; never print the key.

```sh
rtk proxy env PYTHONPATH=/private/tmp/scout-pydantic-247-20260923/candidate:src:. \
  ./venv/bin/python -m scout.cli.pydantic_compat_smoke \
  --expected-version 2.47.0 --live-openrouter \
  --model deepseek/deepseek-v4-flash-0731
rtk proxy env PYTHONPATH=/private/tmp/scout-pydantic-247-20260923/candidate:src:. \
  ./venv/bin/python -m pytest tests/test_pydantic_ai_247_compat.py \
  tests/test_pydantic_candidate_workspace.py -q
rtk proxy env PYTHONPATH=/private/tmp/scout-pydantic-247-20260923/candidate:src:. \
  ./venv/bin/python tools/verify_pydantic_candidate_workspace.py \
  --workspace /Users/alexwang0315/workspace/dongqing_batongguan_historic_trail_newImport \
  --output /private/tmp/scout-pydantic-247-20260923/repeated-workspace-probe.json
```

## Remaining promotion gates

Restore/complete the authoritative missing Jev implementation from its owning
integration, rerun its tests and a live routing case, and resolve the event-loop
warning before claiming full compatibility. Preserve the transport-only search
label unless provider execution receipts become available. Do not rerun 1,000
questions merely to mask a missing module or substitute volume for verification.
