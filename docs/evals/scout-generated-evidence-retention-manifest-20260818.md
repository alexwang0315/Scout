# Scout Generated Evidence Retention Manifest — 2026-08-18

Status: inventory complete; two Pi evaluation directories restored locally and
checksum-verified; no deletion or external archive authorized
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
| `REMOTE_VERIFIED` | A remote artifact was inspected read-only and has a recorded directory checksum, but has not been copied to the approved archive | Preserve the remote source until an archived copy passes checksum verification |
| `LOCAL_VERIFIED_COPY` | A complete Git-ignored local copy reproduces the recorded remote directory checksum | Preserve both copies until a durable archive destination is approved and independently verified |

## Sealed retention candidates

Directory digests below are SHA-256 hashes of concatenated per-file SHA-256
lines in `hash  ./relative/path` format with paths sorted bytewise. Sizes are
allocated KiB at inventory or remote-verification time.

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
| `LOCAL_VERIFIED_COPY` | `outputs/evals/six_forces_600_total_info_v230-qwen3-targeted100-final-repair-20260817T015113Z` | 10 | 4,028 | `7681ef9acf68bd7dbcac6f72a7d3fee0cf01a2cda5a91e9c310283dfab1290f7` | Complete local copy restored from the Pi; 28 completed runs, 27 verifier passes and 1 verifier failure |
| `LOCAL_VERIFIED_COPY` | `outputs/evals/six_forces_600_total_info_v230-qwen3-targeted100-benign-guard-20260817T0205Z` | 10 | 396 | `b83bc17d7ef2e655c104d37457de9b6f1e4e958c431d69482f9b3b54cd0fdcea` | Complete local copy restored from the Pi; 3 completed runs and 3 verifier passes |
| `REMOTE_VERIFIED` | `scout.local:/home/alexwang0315/scout-v214-six-forces-20260723T073059Z/workspace/outputs/evals/six_forces_600_total_info_v230-qwen3-targeted100-final-repair-20260817T015113Z` | 10 | 4,036 | `7681ef9acf68bd7dbcac6f72a7d3fee0cf01a2cda5a91e9c310283dfab1290f7` | Final compatibility repair package; 28 completed runs, 27 verifier passes and 1 verifier failure |
| `REMOTE_VERIFIED` | `scout.local:/home/alexwang0315/scout-v214-six-forces-20260723T073059Z/workspace/outputs/evals/six_forces_600_total_info_v230-qwen3-targeted100-benign-guard-20260817T0205Z` | 10 | 400 | `b83bc17d7ef2e655c104d37457de9b6f1e4e958c431d69482f9b3b54cd0fdcea` | Focused benign guard package; 3 completed runs and 3 verifier passes |

The two manual bundles attest Dashboard commit
`446a6eb3182d5adbc683f6c87b88b9332438f80a`; they are historical evidence and
must not be presented as browser qualification of the inventory HEAD above.

## Generated roots retained but not sealed

| Class | Path | Files | KiB | Disposition |
|---|---|---:|---:|---|
| `QUARANTINED_RAW` | `artifacts/qualification/runs/` | 1,932 | 1,449,032 | Keep until the active manual bundles and their referenced raw roots pass independent and human disposition |
| `QUARANTINED_RAW` | `outputs/qualification/` | 8,942 | 78,164 | Preserve current reports; older versions require a reference-aware cleanup inventory |
| `QUARANTINED_RAW` | `outputs/evals/` | 539 | 257,960 | Preserve the sealed baselines and verified local copies above; classify remaining experiments before archiving or cleanup |
| `REGENERABLE` | `outputs/dashboard/` | 89 | 1,120 | Mutable Body Index and living-runtime state; eligible for a later exact-path cleanup approval |
| `REGENERABLE` | `outputs/.obsidian/` | 4 | 24 | Local editor metadata; eligible for a later exact-path cleanup approval |

## Pi artifacts restored locally and verified

`docs/evals/scout-ai-targeted-answer-quality-100-aihat2-20260817.md` cites the
following directories. They were absent at inventory time and are now restored
to their original Git-ignored local paths:

- `outputs/evals/six_forces_600_total_info_v230-qwen3-targeted100-final-repair-20260817T015113Z/`
- `outputs/evals/six_forces_600_total_info_v230-qwen3-targeted100-benign-guard-20260817T0205Z/`

Historical execution receipts confirm that both runs completed on `scout.local`
under this remote root:

`/home/alexwang0315/scout-v214-six-forces-20260723T073059Z/workspace/outputs/evals/`

- The final-repair run reported completion at `2026-08-17T02:06:56Z`.
- The benign-guard run reported completion at `2026-08-17T02:12:10Z`.
- Only selected result, summary, and health files were copied temporarily to the
  Mac for review; those `/tmp` copies are no longer present.
- An initial 2026-08-18 SSH check timed out while the Pi was unreachable.
- At `2026-08-18T16:20:33+08:00`, `scout.local` resolved to `192.168.8.230` and
  key-authenticated read-only inspection succeeded.
- Both directories contained ten files. Their sizes and directory checksums are
  recorded in the sealed-retention table above.
- Both run manifests retain `candidate_only=true` and
  `runtime_safety_truth=false`.
- At `2026-08-18T17:55:13+08:00`, both complete directories had been copied to
  the Mac without changing the Pi source. Each local directory checksum matched
  its recorded Pi checksum exactly.
- A post-copy checksum pass on the Pi reproduced both original checksums, so the
  remote source remained unchanged.
- The restored local directories remain ignored by Git; only this bounded
  retention manifest is intended for version control.

Class: `LOCAL_VERIFIED_COPY` for the Mac copies and `REMOTE_VERIFIED` for the Pi
sources. These are now two matching working copies, not a durable external
archive. Preserve both until an approved archive destination receives the
directories and independently reproduces the recorded checksums.

## Next gate

1. Decide a durable external archive destination for the two verified
   evaluation directories, screenshots, videos, traces, and other raw evidence.
2. Copy the locally restored directories to that destination without changing
   either current source, then independently compare their checksums.
3. Independently review the two active manual bundles.
4. Copy only bounded canonical reports and summaries into `docs/evals/`.
5. Verify copied or archived checksums against this manifest.
6. Produce an exact retain/archive/delete allowlist for human approval.

No path listed here is approved for deletion yet.
