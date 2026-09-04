# Scout AI Synthetic Corpus Human Review Packet

```yaml
review_id: SCOUT-AI-WORKSPACE-CORPUS-REVIEW-20260902
review_status: APPROVED_FOR_EXPERIMENTAL_USE
review_scope: experimental_workspace_behavior_training_only
reviewed_by: alexwang0315
reviewed_at: 2026-09-02T00:44:43Z
source_artifact_sha256: c0eccf64c5012c0f53d0401919459cf0568b82cbb747d11a8b8ebdb750ee1f3f
source_seed_sha256: d608d9bd0b6127da76431aaea33f60560ab4de2877683b2c6dca573ab5215396
candidate_only: true
runtime_safety_truth: false
```

## Review Boundary

This packet requests human confirmation for five deterministic, controlled
synthetic records. Approval would make the records eligible only for an
isolated experimental Workspace-behavior training run. It does not approve a
production model, runtime route, safety claim, mission mutation, or use of the
Frozen Gold benchmark as training data.

The records teach typed behavior, evidence references, domain status, and
authority preservation. They do not contain a complete prose gold answer and
therefore must not be represented as a full answer-quality SFT corpus.

## Record Review

| Mode | Record hash | Expected behavior | Evidence/domain check | Tool trace | Codex pre-review |
| --- | --- | --- | --- | --- | --- |
| `full` | `355b94c7533f773ca473e0cbefef12bb6b4352d64b2bb43e7b908d9f62a54f0d` | `answer_with_evidence` | route + DEM + QGIS available; three candidate features remain candidate-only | snapshot read | recommend approval for bounded behavior training |
| `missing` | `cbf642ec6bba0cb0d57535d763714e6303f2c4f1c7b525d99a99126d7807aada` | `more_evidence_required` | route available; terrain explicitly missing | snapshot read + evidence search | recommend approval for bounded behavior training |
| `stale` | `4db23dc7175298d1551f07a2d2e2416a8a39be450eb63490776b4de43ed9a682` | `refresh_required` | route and terrain evidence retained but marked stale | snapshot read + refresh request | recommend approval; refresh is evidence acquisition, not authority mutation |
| `conflicted` | `26271886f4af996976148d453cf39ab2f43caa9f53843c1c6b2a3e3715efef84` | `preserve_conflict` | terrain conflict remains unresolved | snapshot read + evidence compare | recommend approval for bounded behavior training |
| `no_workspace` | `2c1f9f91d25d4b92802d31142a7bd87c37846e0ebe85f0ae6b36ff6b51a37b77` | `more_evidence_required` | route and terrain remain missing; no evidence is invented | snapshot read + evidence search | recommend approval for bounded behavior training |

## Checks Completed

- All five record hashes and deterministic verification receipts validate.
- Every record is `TRAIN` but remains only `deterministically_verified`.
- Every output is candidate-only and explicitly not runtime safety truth.
- Mission, baseline, permission, safety, emergency, notification, and device
  write capabilities remain denied.
- Required evidence references are subsets of their snapshots.
- Missing, stale, and conflicted domain arrays exactly match snapshot state.
- Frozen evaluation source hash, case IDs, snapshot hashes, and semantic
  fingerprints remain disjoint from the synthetic seed and corpus.
- Synthetic terrain features are labeled synthetic and cannot establish trail
  existence, passability, safety, or authoritative route truth.

## Human Decision

The human reviewer explicitly approved all five exact record hashes for
`experimental_workspace_behavior_training_only` on 2026-09-02. The approval
does not authorize production training, production model promotion, runtime
safety truth, or any mutation of authoritative Scout state.

The promotion process:

1. write the human reviewer identity, timestamp, and this review reference into
   each record;
2. recompute every record hash;
3. issue new verifier receipts bound to the promoted hashes;
4. preserve the original candidate corpus unchanged;
5. rerun the aggregate gate against the untouched Frozen Gold artifact.

## Promotion Result

| Mode | Approved source hash | Promoted record hash |
| --- | --- | --- |
| `full` | `355b94c7533f773ca473e0cbefef12bb6b4352d64b2bb43e7b908d9f62a54f0d` | `b9051b45f4ac760e6a3f7c0869fccb2ea728d59d7a9e9d6f4d433a093cb0e099` |
| `missing` | `cbf642ec6bba0cb0d57535d763714e6303f2c4f1c7b525d99a99126d7807aada` | `a70118786d531f78e106ebe30d2e95254bfa342604537e3230a56302484c2e48` |
| `stale` | `4db23dc7175298d1551f07a2d2e2416a8a39be450eb63490776b4de43ed9a682` | `4a0879426221a0c9fe961eb1809e5c9298ecefd0f45c8a59eb07f07373c3c078` |
| `conflicted` | `26271886f4af996976148d453cf39ab2f43caa9f53843c1c6b2a3e3715efef84` | `88fef3340ed9701b2556282ec0bcb0e0007df3134793acd1d2aa0ee8c5fc4b0c` |
| `no_workspace` | `2c1f9f91d25d4b92802d31142a7bd87c37846e0ebe85f0ae6b36ff6b51a37b77` | `e15598f35910baab289d87c753df8bfeffdaad7003dec74cc706e1a2582c7af1` |

- Promoted corpus artifact hash:
  `8106301eb21bbcdd9fa23ecd01ae6f011047659ab2a90f4f8f33592edb385eed`.
- Promoted corpus file SHA-256:
  `b9f744923262a5c5edeac723c0fe4cbaf65694602873c29d278e5e9420d60ea3`.
- All five new verifier receipts are accepted and bound to the promoted hashes.
- The original source corpus remains unchanged at its approved SHA-256.
- Final gate disposition: `ready_for_experimental_training` with no failed
  checks and `production_promotion_allowed=false`.
