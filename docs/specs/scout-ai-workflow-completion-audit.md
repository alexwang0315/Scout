# Scout AI Workflow Completion Audit

Date: 2026-06-07

Scope: current `/Users/alexwang0315/scout-fusion` worktree. This audit checks
whether Scout AI currently satisfies the requested workflow:

```text
User question
-> context registry / source discovery
-> registry-backed skill/tool planner
-> deterministic Scout AI tools
-> evidence collection
-> model synthesis only after evidence is gathered
-> answer with sources, limitations, missing evidence, safety boundary
-> eval suite verifies behavior
```

## Current Verdict

Status: **complete for the requested read-only Scout AI workflow**.

The deterministic Scout AI workflow is implemented, manifest-backed, tested, and
exposed through read-only assistant status/UI surfaces. The normal provider
success path now attaches compact full-workflow evidence before
`provider.answer(...)` for pretrip questions that can be handled by the
registry-backed planner. Provider fallback behavior still preserves the same
read-only evidence and safety boundary.

## Verification Commands

These commands were run during this audit:

```bash
./venv/bin/python -m pytest tests/test_scout_ai_tool_planner.py tests/test_scout_ai_workflow_discovery.py tests/test_scout_ai_evidence_collection.py tests/test_scout_ai_answer_synthesis.py tests/test_scout_ai_full_workflow.py tests/test_scout_ai_assistant_workflow_eval.py -q
```

Result: `49 passed in 28.51s`.

```bash
./venv/bin/python -m pytest tests/test_assistant_skill_router.py tests/test_assistant_api.py tests/test_assistant_page.py tests/test_assistant_readiness_check.py -q
```

Result: `72 passed, 1 warning in 38.05s`.

```bash
./venv/bin/python assistant_readiness_check.py --pretty
```

Result summary:

```json
{
  "returncode": 0,
  "ok": true,
  "failed_checks": [],
  "scout_ai_workflow_gate_missing": [],
  "assistant_ui_smoke_missing": []
}
```

Additional provider success evidence-first verification:

```bash
./venv/bin/python -m pytest tests/test_assistant_api.py -q
```

Result: `34 passed, 1 warning in 62.18s`.

```bash
./venv/bin/python -m pytest tests/test_assistant_skill_router.py tests/test_scout_ai_full_workflow.py tests/test_scout_ai_assistant_workflow_eval.py -q
```

Result: `42 passed in 67.60s`.

## Requirement Matrix

| Requirement | Current status | Evidence |
|---|---:|---|
| Context registry / source discovery exists before planning | Proven | `scout_ai_workflow_discovery.py` calls `discover_scout_ai_context_sources(...)`; `docs/specs/scout-ai-tool-interface.md` defines `scout.ai.context_registry.describe`; readiness gate checks the spec and manifest. |
| Registry-backed planner exists | Proven | `scout_ai_tool_planner.py` exposes `plan_scout_ai_tools(...)`; `tests/test_scout_ai_tool_planner.py` covers CP count, named place/MCP, map perception, risk, terrain, weather, health, safety boundary, and INS/DR trace selection. |
| Planner output is structured | Proven | `ScoutAiToolPlanItem` includes `tool_id`, `reason`, `required_fields`, `missing_fields`, `status`, `request`, `boundary`; planner tests assert those fields for ready and contract-gap tools. |
| Ready deterministic tools execute through one executor | Proven | `scout_ai_tool_executor.py` dispatches ready tools through `execute_scout_ai_tool(...)`; evidence collection tests cover execution and read-only boundaries. |
| Contract-only tools return missing fields / implementation gap | Proven | Weather window is contract-only in planner/evidence/full workflow tests and reports `provider` / `ttl_s` instead of guessing. |
| Evidence collection happens before answer synthesis in the full workflow runner | Proven | `collect_and_synthesize_scout_ai_answer(...)` calls `collect_scout_ai_evidence(...)` before `synthesize_scout_ai_answer_from_evidence(...)`; full workflow tests assert discovery, evidence collection, and answer synthesis step order. |
| Answer includes sources, limitations, missing evidence, and safety boundary | Proven for full workflow | `scout_ai_answer_synthesis.py` emits sources, `missing_evidence`, limitations, and `ScoutAiToolBoundary`; tests cover risk/terrain and weather missing-evidence outputs. |
| Candidate evidence is not runtime safety truth | Proven for deterministic workflow and assistant fallback | Tool contracts, workflow policies, manifests, answer synthesis, UI status, and eval tests assert `runtime_safety_truth=false` and no `/safety/*`, outbound, or hardware control. |
| Eval suite verifies behavior | Proven | `scout_ai_assistant_workflow_eval.py` evaluates assistant responses and full workflow artifacts; tests cover successful answers, missing evidence, missing full workflow source, and read-only boundaries. |
| Readiness gate protects the workflow | Proven | `assistant_readiness_check.py --pretty` is green and checks `scout_ai_workflow_gate`, manifests, spec tokens, UI smoke, and server mount. |
| Admin/debug/pretrip UI shows workflow status | Proven | `docs/admin/scout-assistant-ui.js` renders `/assistant/status.assistant_workflow`; page tests and JS-executed smoke verify `assistantWorkflowStatusList`. |
| Normal provider-success path performs full evidence collection before model answer | Proven | `assistant_api.py` calls `_augment_pretrip_evidence_first_sources(...)` before `provider.answer(...)`; `tests/test_assistant_api.py::test_provider_success_receives_full_workflow_evidence_before_answer` verifies a successful provider receives `assistant_context.tool_registry`, `assistant_skill.pretrip.tool_planner.v0`, `assistant_skill.pretrip.full_workflow.v0`, and the weather contract-gap source before answering. |
| Model synthesis only after evidence is gathered | Proven for provider path | The full workflow runner remains deterministic and records `model_provider_used=false`; when a provider is used, the provider receives the deterministic full-workflow evidence before answer generation. |

## Safety Boundary Audit

The current deterministic workflow and status surfaces are advisory-only:

- No `/safety/*` call is made by Scout AI workflow tools.
- No Phase 1 L0-L4 runtime truth mutation is allowed.
- No Brain / ObservedFact / HumanReview write is allowed.
- No outbound / SOS / beacon send is allowed.
- No hardware control is allowed.
- `candidate_evidence_is_runtime_truth=false` is visible in UI workflow status.

This is covered by tool boundaries, workflow policies, manifests, readiness gate,
assistant response boundaries, and workflow eval checks.

## Follow-Up Hardening

The workflow goal is satisfied for the current requested scope. Useful
hardening slices remain:

- Promote these untracked workflow files into a bounded commit once review is
  complete.
- Add a browser-backed smoke path if Playwright/jsdom is available in the local
  Node environment.
- Extend provider success tests from weather contract-gap to a ready-tool
  risk/terrain question.

Suggested regression commands:

```bash
./venv/bin/python -m pytest tests/test_assistant_api.py tests/test_assistant_skill_router.py -q
./venv/bin/python -m pytest tests/test_scout_ai_full_workflow.py tests/test_scout_ai_assistant_workflow_eval.py -q
./venv/bin/python assistant_readiness_check.py --pretty
```
