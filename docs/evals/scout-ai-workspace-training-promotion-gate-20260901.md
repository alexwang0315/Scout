# Scout AI Workspace Training Promotion Gate

```yaml
experiment_id: SCOUT-AI-EXP-WORKSPACE-TRAINING-GATE-20260901
hypothesis: >
  Scout can keep model-evaluation cases, synthetic training seeds, verified
  corpus records, model-quality evidence, and human review as distinct typed
  gates before any SFT or LoRA experiment begins.
current_baseline: >
  Workspace snapshots, five dependency modes, corpus records, verifier receipts,
  split policy, and human promotion existed, but the synthetic corpus CLI could
  consume the same benchmark artifact used for model evaluation. Split labels
  alone did not prove lineage isolation.
decision: ACCEPT_GATE_REJECT_TRAINING
candidate_only: true
runtime_safety_truth: false
```

## Implemented Gate

Workspace benchmark artifacts now declare one role:

- `model_evaluation`: accepted by the model dependency benchmark and rejected
  by the synthetic generator.
- `synthetic_seed`: accepted by the controlled synthetic generator and rejected
  as frozen model-evaluation evidence.

The aggregate training gate validates:

1. candidate-only authority on frozen, model, and corpus evidence;
2. model report SHA-256 binding to the frozen artifact;
3. exact five-mode frozen coverage;
4. explicit synthetic-seed source role;
5. source-artifact, case-ID, snapshot-hash, and semantic-fingerprint separation;
6. full frozen model baseline quality;
7. one accepted verifier receipt per corpus record;
8. TRAIN-only records;
9. explicit human review and `training_eligible` promotion for every record.

The semantic fingerprint excludes IDs, timestamps, and evidence hashes. Renaming
a frozen case therefore does not make it an independent training scenario.

Even a passing report only sets `ready_for_experimental_training=true`.
`production_promotion_allowed` is permanently false in this contract.

## Executed Evidence

### Frozen Model Evaluation

- Artifact role: `model_evaluation`.
- Five modes: full, missing, stale, conflicted, and no Workspace.
- File SHA-256:
  `7e43e1154325bf83f22d6e0f713e02b68bfa2e692846413a5db39d205130312e`.
- Passing this artifact to the synthetic corpus CLI was rejected before output
  creation with `Workspace benchmark is not an approved synthetic seed`.

### Independent Synthetic Seed

- Artifact role: `synthetic_seed`.
- Separate counterfactual Workspace, mission, route, question, evidence refs,
  candidate features, case namespace, snapshot hashes, and semantics.
- File SHA-256:
  `d608d9bd0b6127da76431aaea33f60560ab4de2877683b2c6dca573ab5215396`.
- Generated corpus: five records, five accepted deterministic receipts, zero
  training-eligible records.
- Corpus file SHA-256:
  `c0eccf64c5012c0f53d0401919459cf0568b82cbb747d11a8b8ebdb750ee1f3f`.

### Raspberry Pi Model Baseline

The Pi CPU Ollama `qwen3:1.7b` runtime executed all five frozen cases with local
concurrency one and no cloud fallback:

- five valid structured outputs;
- zero passing cases;
- Workspace Dependency Score: `0.0`;
- five model requests;
- 3,240 input tokens and 336 output tokens;
- 213,122 ms total model latency;
- report hash:
  `d43aea58015a93479ad972f4ea982e05f16b5567d8f3d0ff51ff6ae77ec235b7`.

The model selected the correct high-level behavior in every mode. It still
omitted typed evidence references and missing/stale/conflicted domain arrays.
The full case did return all candidate feature IDs. This keeps `SWM-001` open:
the model can explain Workspace state but cannot own the complete contract.

During the equivalent live Pi run, sampled temperature reached 72.5 C without
throttling. Post-run state was 54.9 C, `throttled=0x0`, with about 4.44 GiB
available memory.

## Final Gate Result

```text
authority boundary             PASS
frozen benchmark binding       PASS
five-mode coverage             PASS
synthetic-seed role            PASS
source/case/snapshot lineage   PASS
semantic lineage               PASS
corpus verification            PASS
TRAIN-only records             PASS
model baseline quality         FAIL
human review promotion         FAIL
```

- Disposition: `blocked_model_quality`.
- Training record count: 5.
- Training-eligible count: 0.
- Report hash:
  `786b6bb53896b4220dcdff222bed9b2c11e1c242ea3c8a184787039f12316812`.
- Experimental training was not started.
- No production model, prompt, adapter, Workspace, or runtime route changed.

## Unblock Conditions

1. A qualified strong model must pass all five frozen cases with exact typed
   evidence and domain arrays. Deterministic field injection cannot satisfy this
   particular model-literacy gate.
2. Each distinct training record must receive explicit human review and a new
   hash-bound verifier receipt after promotion.
3. The gate must be rerun against the same untouched frozen artifact.

MAX, another local model, or an explicitly authorized cloud model may be tested
later, but no runtime may silently replace this failed baseline or access frozen
cases as training material.

## Evidence Files

- `artifacts/scout-ai-nextgen/workspace-training-gates-20260901/frozen-workspace-benchmark.json`
- `artifacts/scout-ai-nextgen/workspace-training-gates-20260901/training-seed-workspace-benchmark.json`
- `artifacts/scout-ai-nextgen/workspace-training-gates-20260901/synthetic-training-corpus.json`
- `artifacts/scout-ai-nextgen/workspace-training-gates-20260901/workspace-model-benchmark-pi-cpu-qwen3-1.7b.json`
- `artifacts/scout-ai-nextgen/workspace-training-gates-20260901/workspace-training-gate-report.json`

## Rollback

Remove the artifact-role field, training gate module/CLI, counterfactual seed
fixtures, focused tests, artifacts, and this experiment packet. No production
state or model weights require rollback because training and promotion never ran.
