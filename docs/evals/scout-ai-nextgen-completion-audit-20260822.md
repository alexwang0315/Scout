# Scout AI NextGen Completion Audit - 2026-08-22

Classification: `WORKING PROTOTYPE`
Production readiness: `NOT REQUESTED / NOT CLAIMED`
Authority: `candidate_only=true`, `runtime_safety_truth=false`

## Capability Evidence

| Slice | Result |
| --- | --- |
| Intelligence contracts/capability boundary | PASS |
| MCP lifecycle/crash/timeout/stale isolation | PASS |
| Real PraisonAI 1.7.0 specialist execution | PASS |
| Pure terrain deterministic routing | PASS; one Terrain model call plus deterministic QGIS ingestion |
| Candidate equivalence | PASS; exact three findings and three evidence items vs three-model baseline |
| Terrain latency ablation | PASS; Praison segment 209252 ms to 92460 ms, 55.8 percent lower |
| Independent tool calling | PASS; exact one read-only tool with server-owned attestation |
| WorkspaceSnapshot compiler | PASS; full/missing/stale/conflicted/no-workspace |
| Training corpus boundary | PASS; Frozen Gold leakage blocked, human promotion required |
| Controlled synthetic generator | PASS; five verified records, zero training eligible |
| Failure matrix | PASS; 13 scenarios and 13 probes |
| Local model full Workspace contract | FAIL; `SWM-001`, qwen3:1.7b baseline 0/5 |
| Deterministic Workspace envelope | PASS; 5/5 typed contracts, narrative remains separately reviewable |

## Verification

- Main Scout environment: `82 passed, 8 skipped in 38.87s`.
- Isolated PraisonAI 1.7.0 environment: `66 passed in 31.51s`.
- Ruff: all scoped NextGen source, tools, and tests passed.
- Failure qualification artifact: `13 passed, 1 warning in 8.58s`.
- Artifact integrity audit: all selected wrapper/report hashes and authority flags
  passed.
- Temporary Ollama and MCP service processes: stopped.
- Secret scan: no real credential/private-key material found in the scoped files.

The eight main-environment skips are optional PraisonAI tests; the same real
paths passed in the isolated dependency environment and are not treated as
unverified skips.

## Primary Artifacts

- `workspace-snapshot-benchmark-v0-20260822.json`
- `synthetic-workspace-corpus-v0-20260822.json`
- `nextgen-failure-qualification-v0-attempt2-20260822.json`
- `model-runtime-qualification-ollama-qwen3-1.7b-router-v1-one-agent-edge-cpu-attempt2-20260822.json`
- `model-runtime-qualification-ollama-qwen3-1.7b-tool-attested-20260822.json`
- `model-capability-attestation-ollama-qwen3-1.7b-tool-calling-20260822.json`
- `workspace-model-benchmark-ollama-qwen3-1.7b-attempt3-stage-a-20260822.json`
- `workspace-model-benchmark-ollama-qwen3-1.7b-deterministic-envelope-20260822.json`

The first aggregate failure-matrix artifact remains retained as failed evidence;
it is not relabeled after the passing rerun.

## Authority Audit

No experimental path can write:

- mission state;
- reviewed baseline;
- route state or route promotion;
- permission state;
- deterministic safety state;
- emergency or notification authority;
- device/hardware controls.

All promotion remains an explicit Pydantic/deterministic review, reducer,
permission, and provenance concern.

## Known Issue

`SWM-001`: the tested qwen3:1.7b/Ollama runtime correctly described Workspace
states in prose but did not populate non-empty typed arrays in full-contract
mode. Tool structured output failed with `UnexpectedModelBehavior`.

The architecture response is to keep known facts in a deterministic envelope,
not to lower schema expectations. Another qualified runtime or model adaptation
must pass the same frozen five cases before claiming full Workspace literacy.

## Explicitly Unproven

- Live MAX inference server compatibility and performance.
- Raspberry Pi 5 + AI HAT+2/Hailo NextGen runtime equivalence.
- Live heavy QGIS workstation execution through the Intelligence Service.
- Thermal, battery, and energy-aware hard routing policy.
- NextGen Dashboard telemetry/review UI.
- SFT, LoRA, Mojo kernels, expanded specialists, or distributed intelligence.

These are later qualification phases, not hidden completion claims.

## Rollback

Remove the experimental `src/scout/nextgen/` namespace, its configs, tools,
tests, artifacts, and documents. Existing production Pydantic Agent, Workspace,
reducers, permission, safety, emergency, and runtime stores require no schema or
data rollback.
