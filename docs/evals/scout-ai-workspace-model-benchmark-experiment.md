# Scout AI Workspace Model Benchmark Experiment

```yaml
experiment_id: SCOUT-AI-EXP-WORKSPACE-001
hypothesis: >
  A small local model can read a bounded ScoutWorkspaceSnapshot and preserve
  evidence, missing, stale, conflict, and candidate authority in a typed answer.
current_baseline: >
  No model-scored full/missing/stale/conflicted/no-workspace benchmark existed.
proposed_architecture: >
  Workspace -> deterministic task-aware snapshot -> bounded model projection ->
  local model -> Pydantic validation -> deterministic evaluator. A second mode
  tests a deterministic server-owned envelope with model-owned narrative only.
implementation_scope:
  - Five immutable Workspace dependency cases.
  - One resident Ollama qwen3:1.7b CPU model with concurrency one.
  - Native JSON-schema and tool structured-output probes.
  - Exact evidence/domain/feature matching and candidate-only validation.
  - Deterministic-envelope composition as a separate, explicitly labeled mode.
out_of_scope:
  - No production Workspace migration.
  - No runtime safety, route, permission, notification, or emergency mutation.
  - No claim that deterministic-envelope score equals model Workspace literacy.
  - No MAX, Hailo, Raspberry Pi, cloud, SFT, or LoRA qualification.
test_dataset: >
  workspace-snapshot-benchmark-v0-20260822.json with full, missing, stale,
  conflicted, and no_workspace cases.
metrics:
  - Structured-output validity.
  - Exact expected behavior.
  - Exact evidence refs and missing/stale/conflicted domains.
  - Exact candidate feature IDs.
  - Workspace Dependency Score.
  - Model requests, tokens, and latency.
  - Manual narrative semantic review.
results:
  - Native full-contract attempt 2 produced four valid structured answers and one
    timeout, but passed 0/5. The model selected the right behavior and explained
    the state in prose while leaving typed arrays empty. Total model latency was
    491906 ms. Report hash:
    31f033e8ec59d77b214dfe851effddacf1b11570d3e0831d74b7da7021c2c429.
  - Stage A prompt/projection repair reduced total model latency to 369404 ms and
    produced five valid structured answers, but still passed 0/5 because all
    typed arrays remained empty. Report hash:
    77b2426d7d2467f4285acbba3f2004db802c75a0e1f46aba71468a8f3f309e3c.
  - Tool structured-output mode failed the missing case with
    UnexpectedModelBehavior after one model request and 104299 ms. Report hash:
    64fd6b9aa1aee7bc55717142b576d40e99d67f82de39ad1cb60e2d198264e072.
  - Deterministic-envelope mode passed the typed contract 5/5 with five model
    requests and 137430 ms total model latency. Typed facts were attached by
    deterministic Scout code; the model generated narrative only. Report hash:
    22f87c5763807b5b990ac99c7f3dddf0d7631b24d105e0044bc87320c15b6d99.
  - Manual narrative review classified four summaries as clean and the stale
    summary as review-required because it described refresh_required as a domain
    status and suggested some features were missing.
regression: >
  Focused evaluator tests pass. All outputs remain candidate-only and false for
  runtime_safety_truth. Existing production Agent, Workspace, reducers, and
  authority paths are unchanged.
decision: ACCEPT
decision_detail: >
  Accept deterministic server-owned answer envelopes for the experimental
  architecture. Do not qualify qwen3:1.7b as a full Workspace contract owner.
rollback_strategy: >
  Remove the experimental workspace_model_benchmark module, CLI, and artifacts.
  No production state or schema requires migration.
```

## Known Issue SWM-001

`qwen3:1.7b` through the tested Ollama OpenAI-compatible endpoint does not
reliably populate non-empty array fields in `WorkspaceModelAnswer`, even when it
correctly describes those arrays in prose.

- Reproduction: run the five-case benchmark with
  `assembly_mode=model_full_contract`.
- Native mode: valid schema shape, correct behavior/prose, empty typed arrays.
- Tool mode: `UnexpectedModelBehavior` on the targeted missing case.
- Attempted repair: compact projection plus explicit mechanical field bindings.
- Alternate model: not run; no additional local runtime was qualified in this
  slice, and no paid/cloud escalation was authorized.
- Current blocker: model/provider constrained-output behavior is insufficient for
  full Scout contract ownership.
- Unblock condition: another qualified runtime, adapter, SFT/LoRA, or decoding
  mode passes all five frozen cases without deterministic field injection.

`SWM-001` does not block deterministic-envelope architecture. It blocks claims
that this model has learned full Scout Workspace contract literacy.

## Architecture Decision

The model should not be asked to regenerate facts that deterministic Scout code
already knows. The server owns:

- behavior and sufficiency;
- evidence refs;
- missing, stale, and conflicted domains;
- candidate feature IDs;
- candidate/runtime authority flags.

The model may produce a bounded narrative, explanation, or candidate synthesis.
That narrative remains independently reviewable and cannot override the typed
envelope.
