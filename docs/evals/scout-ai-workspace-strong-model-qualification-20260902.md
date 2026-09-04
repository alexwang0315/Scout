# Scout AI Workspace Strong-Model Qualification

```yaml
experiment_id: SCOUT-AI-EXP-WORKSPACE-STRONG-MODEL-20260902
hypothesis: >
  A stronger cloud model can satisfy the same immutable five-mode Workspace
  dependency contract that Pi CPU qwen3:1.7b failed, without server-owned field
  injection or authority promotion.
decision: ACCEPT_GPT56_SOL_FOR_EXPERIMENTAL_BASELINE
candidate_only: true
runtime_safety_truth: false
```

## Legacy Corpus Recovery

The missing 100-question corpus was recovered from the preserved
`scout-fusion-legacy-20260823` tree. Its 100 case IDs and 100 question strings
match the recorded 2026-07-13 100-run sample exactly. The restored canonical
fixture is now tracked under `tests/fixtures/` rather than the ignored
`outputs/evals/` directory.

- Restored corpus SHA-256:
  `57d151ad0834aff75e8365b1c8b2509cde1c2e445059c1b0067523298c766736`.
- Workspace query evaluator result: 8/8 focused tests passed.

## Runtime Comparison

All runs used the unchanged model-evaluation artifact from 2026-09-01. No
frozen case was copied into the synthetic training seed or corpus.

| Runtime | Output mode | Best result | Requests | Model latency | Decision |
| --- | --- | ---: | ---: | ---: | --- |
| Pi CPU `qwen3:1.7b` | native | 0/5 | 5 | 213,122 ms | failed baseline |
| OpenRouter `deepseek/deepseek-v4-flash-0731` | native | 3/5 | 4 | 88,664 ms | partial; retain as comparison |
| OpenRouter `deepseek/deepseek-v4-flash-0731` | tool | 0/5 | 4 | 26,713 ms | reject this output mode |
| OpenRouter `openai/gpt-5.6-sol` | native | 5/5 | 5 | 11,880 ms | accepted experimental strong-model baseline |

The qualified GPT-5.6 Sol report has Workspace Dependency Score 1.0, five
valid structured outputs, 4,271 input tokens, 575 output tokens, and report
hash
`fe74bb1413aa2adcc0e0124f948800b966b82fce399c850a545152b1d56a0f35`.

## Harness Finding

Invoking the benchmark as `python tools/...` without `PYTHONPATH=.` allowed an
unrelated uncommitted Terrain-agent import to fail on
`terrain_route_guidance`. This happened before the first model request and
artificially produced a 4/5 report. Running with the repository root explicitly
on the module path removed the cross-worktree contamination and produced the
clean 5/5 result. The failed reports remain evidence and are not model-quality
scores.

OpenRouter also returned a non-standard `finish_reason=error` during one
DeepSeek attempt. Pydantic AI rejected it rather than accepting an incomplete
structured response. The failure remains transport evidence, not a passing
answer.

## Gate Result Before Human Review

The aggregate gate was rerun with the qualified GPT-5.6 Sol report and the
unchanged deterministically verified synthetic corpus:

```text
model_baseline_quality    PASS
all lineage checks        PASS
corpus verification       PASS
human_review_promotion    FAIL
```

- Disposition: `blocked_human_review`.
- Failed checks: `human_review_promotion` only.
- Report hash:
  `c7bae010efd17e2131c9a637105b7528a647b61f25443f2e5f278d2b93a9d112`.

The five exact records and approval boundary are in
`docs/evals/scout-ai-synthetic-corpus-human-review-20260902.md`. No assistant,
model, or deterministic verifier is represented as a human reviewer.

## Final Gate Result

The human reviewer subsequently approved all five source record hashes only
for `experimental_workspace_behavior_training_only`. A separate promoted
corpus was generated without modifying the approved source corpus. Human review
metadata was included in each promoted record, every record hash was
recomputed, and five new deterministic receipts were bound to those hashes.

```text
all 12 gate checks             PASS
training records               5
training eligible              5
failed checks                  none
disposition                    ready_for_experimental_training
production promotion allowed   false
```

- Promoted corpus artifact hash:
  `8106301eb21bbcdd9fa23ecd01ae6f011047659ab2a90f4f8f33592edb385eed`.
- Promoted corpus file SHA-256:
  `b9f744923262a5c5edeac723c0fe4cbaf65694602873c29d278e5e9420d60ea3`.
- Final gate report hash:
  `d76ecdcfb07b60b1a6a5d2207598e256d3ea8ef5876c6729cf4ab29f9e35794b`.
- Final gate file SHA-256:
  `1db6cd0082683a4adbb1b9b90df8333399098da0b25df6f573c1bf69bd8f0cff`.

This opens an isolated experimental behavior-training run only. It does not
start training, promote weights, modify Scout runtime routing, or authorize any
production or safety-relevant use.

## Verification

- 29 focused Workspace query, corpus, promotion, model benchmark, and training
  gate tests passed.
- Ruff passed for all Python files changed in this qualification slice.
- The promoted corpus, qualified model report, and final gate report passed
  their typed hash and authority-contract validation.
- A scoped credential-pattern scan found no embedded key or bearer token.
- The promotion CLI rejects attempts to overwrite the approved source corpus.

The repository-wide suite was not used as this experiment's acceptance gate.
Separately observed legacy bounded-replay model-policy and L5 environment-gate
failures remain outside this corpus-promotion slice.

## Rollback

Remove the restored fixture path updates, OpenRouter experimental configs,
2026-09-02 artifacts, and these experiment packets. No production route,
Workspace, model weight, permission, or safety state changed.
