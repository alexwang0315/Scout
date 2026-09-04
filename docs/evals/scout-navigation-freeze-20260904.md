# Navigation Freeze Verification

Date: 2026-09-04
Scope: repository change control only, not Navigation runtime qualification.
User authorization: freeze Navigation and require explicit approval before any
Navigation-related change, including effects from work on other pages.

## Delivered

- Root `AGENTS.md` now makes the approval boundary an exception to default
  Construction Mode autonomy.
- `qualification/policies/navigation-freeze.md` defines the protected behavior,
  shared-file policy, per-change approval and baseline-update protocol.
- `qualification/navigation-freeze-baseline.json` records 130 source files from
  the current worktree, preserving existing uncommitted work rather than HEAD.
- `tools/verify_navigation_freeze.py` provides a read-only, standard-library
  check. The pytest suite and new local GitHub workflow configuration invoke it.
- This task did not edit Navigation runtime code, change workspace artifacts,
  regenerate TRH/DEM/R4, restart servers/workers, stage files, commit or push.

## Executable Evidence

1. Initial standalone guard: `FROZEN_UNCHANGED`, 130 files checked, no changes,
   `approval_granted=false`, `runtime_safety_truth=false`.
2. Combined focused run:
   `python -m pytest tests/test_navigation_freeze.py tests/test_dashboard_terrain_route_readiness.py tests/test_navigation_diagnostics.py -q`
   returned **176 passed, 5 failed**. At that run's initial baseline check, the
   frozen source still matched. The five failures were in existing Diagnostic
   tests, not in the newly added guard tests.
3. A subsequent standalone guard found a new modification to
   `docs/admin/scout-dashboard-v0.1.html` and returned
   `NAVIGATION_APPROVAL_REQUIRED` with exit code 1. This task did not edit that
   file. The modifying process and the precise post-freeze delta are UNKNOWN.
4. Subsequent guard-only suite: **30 passed, 1 failed**. The failure is the real
   repository baseline test correctly rejecting that source drift. The 30
   fixture checks cover modified/deleted/new protected files, independent page
   files, missing/corrupt baselines, invalid paths, symlinks, unreadable files,
   immutable approval requirements, deterministic output and CLI exit status.
5. Ruff lint and formatting checks passed for the new Python files. The workflow
   YAML was parsed and its triggers, read-only permissions and guard command
   verified. No remote workflow execution or branch-protection change occurred.

Frozen Dashboard SHA-256:
`117b00b84b0b373c83b39f4da1c748e381b0ad349b6538bf75aaf623666e2466`

Dashboard SHA-256 observed after drift:
`7e439dd107f9c95dbcc3a2168f05bd6339b4813ec2b177d9a88e0d15f333bea0`

The original baseline was not refreshed to accept that change. No file was
reverted. The failed check intentionally remains visible for user disposition.

The final guard invocation detected four modified protected files:

- `docs/admin/scout-dashboard-v0.1.html`
- `docs/admin/scout-maplibre-evidence.js`
- `tests/test_navigation_diagnostics.py`
- `tools/dashboard_diagnostic_browser_smoke.js`

The final isolated guard-fixture run returned **30 passed, 1 deselected**; the
deselected case is the separately executed real repository drift check, which
still fails as intended. This is not an overall passing Navigation gate.
The Diagnostic test file changed after the five-failure run below, so that run
is an observation of the earlier source state, not a claim about the latest
Diagnostic implementation. Acceptance of any of these deltas remains pending
explicit user approval; no automatic rebaselining was performed.

## Diagnostic Test Findings

The checked source includes `DASH-044` and defines `diagnosticCheck044`, but
`test_navigation_diagnostics_register_43_unique_cases_with_executable_handlers`
only constructs handlers 001-043. Its isolated JavaScript harness raises
`ReferenceError: diagnosticCheck044 is not defined`.

Four other isolated-harness tests fail because their `batch_source` fixture does
not include `diagnosticCaseScopeKey`, now called by the extracted functions:

- `test_navigation_batch_runs_only_its_cases_and_preserves_failures_and_warnings`
- `test_navigation_batch_prevents_overlap_and_stops_when_context_changes`
- `test_navigation_initial_idle_result_does_not_claim_a_changed_scope`
- `test_navigation_scope_key_invalidates_changed_default_cache_and_review_evidence`

Both functions exist in the Dashboard source. These failures establish test
harness/source inconsistency; they do not establish that those functions are
missing in the real browser. No tests or runtime code were repaired or weakened.
Repair and acceptance of post-freeze changes require explicit user approval.

## Limits And Pending Decisions

- The guard detects inventoried byte changes; it is not a filesystem write lock,
  complete transitive dependency analysis or proof of browser behavior.
- Shared entrypoints are whole-file protected, so another page may need approval
  simply to wire up otherwise isolated work through those files.
- The baseline is a hash inventory, not a source backup or a production release.
- Remote enforcement needs an authorized commit/push and, separately, a repository
  owner's required-status-check setting. Neither was performed.
- Real Navigation browser behavior after the concurrent HTML change, its author,
  worker/host parity, and the user's disposition of that delta remain UNKNOWN.
- Terrain hypotheses retain candidate-only authority and all terrain uncertainty.

## Scoped Commit Checkpoint

The user subsequently requested a change summary and local commit. This packages
only these seven freeze-control files; it does not approve the four later
Navigation changes or include unrelated work:

- `AGENTS.md`
- `.github/workflows/navigation-freeze.yml`
- `qualification/policies/navigation-freeze.md`
- `qualification/navigation-freeze-baseline.json`
- `tools/verify_navigation_freeze.py`
- `tests/test_navigation_freeze.py`
- `docs/evals/scout-navigation-freeze-20260904.md`

Commit preparation repeated the full guard suite: **30 passed, 1 failed**.
The failure remains the real source-drift gate, with the same four modified
protected paths. Ruff lint and formatting passed. The baseline and all runtime
code were left unchanged; only this verification record was updated.

The frozen inventory also includes prior work not contained in HEAD: **31**
protected source entries are absent or have different committed contents,
excluding this commit's own policy/tool/test files. A clean checkout of this
policy-only checkpoint therefore cannot pass the frozen-source gate. The staged
snapshot must retain that failure rather than accept older HEAD content or
silently include unrelated changes. Source publication and approval of any
post-freeze delta need separately scoped authorization.

This is a local change-control checkpoint, not a green CI/release checkpoint.
No push, branch-protection change, baseline refresh or runtime restart is part
of the request.
