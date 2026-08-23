# Scout AI NextGen Failure Qualification Experiment

```yaml
experiment_id: SCOUT-AI-EXP-FAILURE-001
hypothesis: >
  Every required intelligence/model dependency failure can degrade, cancel, or
  reject candidate work while preserving Level 0 deterministic Scout and all
  authoritative state surfaces.
current_baseline: >
  Individual failure tests existed, but there was no single typed matrix binding
  each required scenario to expected UNKNOWN/retry/cloud/provenance behavior and
  an executable probe.
proposed_architecture: >
  Typed failure policy matrix -> exact pytest node IDs -> bounded qualification
  runner -> hashed artifact with attempt-level diagnostics.
implementation_scope:
  - Praison unavailable and MCP disconnect.
  - Local model, AI HAT, cloud, QGIS, and web unavailable.
  - Timeout, invalid structured output, runaway, and model budget exhaustion.
  - Stale result and mission change while work is running.
  - Explicit Level 0/authority/retry/cloud/provenance outcome for every case.
expected_benefit: >
  Failure behavior becomes machine-readable, executable, and reviewable instead
  of being distributed across prose and unrelated tests.
risks:
  - Some probes use faithful local simulations rather than physical Pi/Hailo/QGIS.
  - A passing policy probe does not qualify the unavailable external dependency.
test_dataset: 13 typed failure scenarios bound to 13 focused pytest probes.
metrics:
  - Scenario coverage.
  - Probe pass/fail.
  - Level 0 availability.
  - Authoritative state isolation.
  - Candidate/runtime authority flags.
  - Attempt latency and output hash.
results:
  - First aggregate run: 12/13 passed with one transient failure; artifact retained.
  - Immediate exact-node rerun: 13/13 passed.
  - Final runner artifact: 13/13 passed in 8.58 seconds with one warning.
  - Every case keeps Scout and Level 0 operational and preserves mission,
    baseline, route, permission, deterministic safety, emergency, and
    notification authority.
  - Passing artifact hash:
    df37b6c312c960f3fb691ef7de40b85dac81e153c59bd37996386045219a5995.
regression: >
  Focused matrix tests pass. The runner now permits at most one bounded retry and
  records each attempt's exit code, latency, output hash, summary, and failure
  diagnostic tail.
decision: ACCEPT
rollback_strategy: >
  Remove the experimental matrix/runner/artifacts. Existing individual tests and
  production runtime remain unchanged.
```

Passing artifact:
`artifacts/scout-ai-nextgen/nextgen-failure-qualification-v0-attempt2-20260822.json`.

The first failed aggregate artifact remains evidence and is not relabeled as a
pass:
`artifacts/scout-ai-nextgen/nextgen-failure-qualification-v0-20260822.json`.
