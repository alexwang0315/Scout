# Immutable workspace training fixtures

These are byte-for-byte copies of the existing September 1/2 experimental artifacts. They are checked in so the original promotion and behavior tests can run in a clean checkout. No corpus, human-review decision, expected behavior, approval scope or record hash has been regenerated.

Historical source-reference strings inside each JSON file are preserved as provenance, not rewritten as current file locations. The original review is `docs/evals/scout-ai-synthetic-corpus-human-review-20260902.md`. These fixtures do not grant new training or runtime authority.

| File | SHA-256 | Original artifact |
| --- | --- | --- |
| synthetic-training-corpus.json | `c0eccf64c5012c0f53d0401919459cf0568b82cbb747d11a8b8ebdb750ee1f3f` | `artifacts/scout-ai-nextgen/workspace-training-gates-20260901/synthetic-training-corpus.json` |
| frozen-workspace-benchmark.json | `7e43e1154325bf83f22d6e0f713e02b68bfa2e692846413a5db39d205130312e` | `artifacts/scout-ai-nextgen/workspace-training-gates-20260901/frozen-workspace-benchmark.json` |
| training-seed-workspace-benchmark.json | `d608d9bd0b6127da76431aaea33f60560ab4de2877683b2c6dca573ab5215396` | `artifacts/scout-ai-nextgen/workspace-training-gates-20260901/training-seed-workspace-benchmark.json` |
| synthetic-training-corpus-human-reviewed.json | `b9f744923262a5c5edeac723c0fe4cbaf65694602873c29d278e5e9420d60ea3` | `artifacts/scout-ai-nextgen/workspace-training-gates-20260902/synthetic-training-corpus-human-reviewed.json` |
