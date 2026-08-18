# Scout Generated Evidence Retention Manifest — 2026-08-18

Status: inventory complete; no deletion or external archive authorized
Inventory repository HEAD: `d64a17a95b542258a5bb1006f56593e29d240c8b`

## Purpose

This manifest separates canonical evidence from generated runtime output. Raw
browser captures, qualification executions, and model-evaluation traces remain
outside normal Git history. Small conclusions, manifests, and checksums belong
under `docs/evals/`.

Ignoring a path does not authorize deleting it. Destructive cleanup requires a
separate, exact-path allowlist approved by the user.

## Retention classes

| Class | Meaning | Current action |
|---|---|---|
| `ACTIVE_REVIEW` | Evidence still subject to independent or human review | Keep locally and do not modify |
| `CANONICAL_REPORT` | Final machine-readable report cited by committed qualification documents | Preserve; later copy a bounded summary into `docs/evals/` |
| `BASELINE_ARCHIVE` | Expensive evaluation baseline needed for later comparison | Preserve outside ordinary Git; archive only after destination and checksum verification |
| `QUARANTINED_RAW` | Supporting captures or intermediate runs | Keep until canonical evidence is sealed, then present an exact cleanup allowlist |
| `REGENERABLE` | Mutable local Dashboard or editor state | Ignore now; eligible for later approved cleanup |
| `EVIDENCE_GAP` | A committed document refers to evidence not present in this checkout | Locate or correct the reference before claiming complete preservation |
| `REMOTE_UNVERIFIED` | A historical execution receipt identifies a remote artifact, but its current storage state and checksum cannot be verified | Keep the reference open until the remote host is reachable and inspected read-only |

## Sealed retention candidates

Directory digests below are SHA-256 hashes of the concatenated per-file
`shasum -a 256` lines with paths sorted bytewise. Sizes are allocated KiB at
inventory time.

| Class | Path | Files | KiB | Directory SHA-256 | Reason |
|---|---|---:|---:|---|---|
| `ACTIVE_REVIEW` | `artifacts/qualification/manual/20260818-evidence-closure-clean` | 43 | 2,952 | `e5b672ba9326caaa4c6b07efaa18464009944e757939a1c0263cce8c3225a46b` | Clean live-runtime evidence bundle; its README still requires independent GPT and Human Review Gate disposition |
| `ACTIVE_REVIEW` | `artifacts/qualification/manual/20260818-evidence-closure-cua-supplement` | 11 | 732 | `07b0f110c245495b48954cab77d8ea809ba728b2284a6662db97ed19f9ed24af` | Real pointer and nested-scroll supplement for Weather and Permission behavior |
| `CANONICAL_REPORT` | `outputs/qualification/contextual-permission-phase2-evidence-v9/result` | 3 | 72 | `b48242d93b99aa47b89aceac2b32bca20ccc5be52b85e0dc74de88a171e9f15f` | Latest contextual-permission report cited by the Phase 3 rev2 closure |
| `CANONICAL_REPORT` | `outputs/qualification/dashboard-phase3-evidence-v5/result` | 30 | 496 | `ef6c2b4325751fcc098ceb48c4c5fc4905981aef821cfe30bb3fff030131430a` | Aggregate Dashboard Phase 3 report cited by the Phase 3 rev2 closure |
| `CANONICAL_REPORT` | `outputs/qualification/dashboard-phase3-focused-shell-v3/result` | 3 | 12 | `4e21e1c7021f4059f3817519f3b632c3916577b46aa3b5267cbd4c5a4a0ae23e` | Latest focused Dashboard shell report cited by the Phase 3 rev2 closure |
| `BASELINE_ARCHIVE` | `outputs/evals/six_forces_600_total_info_v230-qwen3-full1000-20260816T0140Z` | 11 | 97,084 | `4807c6c01cf2fc8d37c967b5eaf9b69827b9ac30da77c653cd8dfd180889110d` | Full 1,000-run Pydantic AI 2.30 baseline |
| `BASELINE_ARCHIVE` | `outputs/evals/six_forces_600_total_info_v230-qwen3-targeted100-full210-20260816T230052Z` | 10 | 24,904 | `0477b1855ce123de0b0bd2dd0036228acad31d70a4e3fbcb820b45b54f63c343` | Targeted 100-question full-run baseline cited by the committed evaluation summary |
| `BASELINE_ARCHIVE` | `outputs/evals/six_forces_600_total_info_v230-qwen3-targeted100-repair2-failures-20260817T010444Z` | 10 | 3,952 | `4054872a6b1cab4e692494bc08a2c4037dc77c36d414a790d7bccaab3f9e366d` | Targeted repair evidence cited by the committed evaluation summary |

The two manual bundles attest Dashboard commit
`446a6eb3182d5adbc683f6c87b88b9332438f80a`; they are historical evidence and
must not be presented as browser qualification of the inventory HEAD above.

## Generated roots retained but not sealed

| Class | Path | Files | KiB | Disposition |
|---|---|---:|---:|---|
| `QUARANTINED_RAW` | `artifacts/qualification/runs/` | 1,932 | 1,449,032 | Keep until the active manual bundles and their referenced raw roots pass independent and human disposition |
| `QUARANTINED_RAW` | `outputs/qualification/` | 8,942 | 78,164 | Preserve current reports; older versions require a reference-aware cleanup inventory |
| `QUARANTINED_RAW` | `outputs/evals/` | 519 | 253,536 | Preserve the sealed baselines above; classify remaining experiments before archiving or cleanup |
| `REGENERABLE` | `outputs/dashboard/` | 89 | 1,120 | Mutable Body Index and living-runtime state; eligible for a later exact-path cleanup approval |
| `REGENERABLE` | `outputs/.obsidian/` | 4 | 24 | Local editor metadata; eligible for a later exact-path cleanup approval |

## Remote artifacts awaiting verification

`docs/evals/scout-ai-targeted-answer-quality-100-aihat2-20260817.md` cites the
following directories. Neither exists in this checkout at inventory time:

- `outputs/evals/six_forces_600_total_info_v230-qwen3-targeted100-final-repair-20260817T015113Z/`
- `outputs/evals/six_forces_600_total_info_v230-qwen3-targeted100-benign-guard-20260817T0205Z/`

Historical execution receipts confirm that both runs completed on `scout.local`
under this remote root:

`/home/alexwang0315/scout-v214-six-forces-20260723T073059Z/workspace/outputs/evals/`

- The final-repair run reported completion at `2026-08-17T02:06:56Z`.
- The benign-guard run reported completion at `2026-08-17T02:12:10Z`.
- Only selected result, summary, and health files were copied temporarily to the
  Mac for review; those `/tmp` copies are no longer present.
- On 2026-08-18, SSH to `scout.local:22` timed out and the current artifact
  directories could not be listed or hashed.

Class: `REMOTE_UNVERIFIED`, not confirmed lost. When the Pi is reachable, inspect
both directories read-only, calculate directory checksums, and select an
approved archive destination before copying or deleting anything. Until then,
the committed evaluation summary describes a historically completed run, not a
locally reproducible evidence package.

## Next gate

1. Restore read-only connectivity to `scout.local` and verify the two remote
   evaluation directories.
2. Independently review the two active manual bundles.
3. Decide an external archive destination for raw screenshots, videos, and
   evaluation traces.
4. Copy only bounded canonical reports and summaries into `docs/evals/`.
5. Verify copied or archived checksums against this manifest.
6. Produce an exact retain/archive/delete allowlist for human approval.

No path listed here is approved for deletion yet.
