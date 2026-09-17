# Navigation Change Freeze

Status: **TEMPORARILY SUSPENDED / REPORT ONLY**
Effective: 2026-09-04

## User-Directed Suspension

On 2026-09-04 the user explicitly requested temporary cancellation of the
`NAVIGATION_APPROVAL_REQUIRED` blocker. Until the user explicitly reinstates the
freeze, its per-change approval and shared-file restrictions are inactive.
Scoped local Dashboard work proceeds under Construction Mode. The original
freeze scope and approval protocol below are retained for restoration; they do
not require another approval prompt during this suspension.

The guard defaults to report-only mode and returns
`NAVIGATION_FREEZE_SUSPENDED` with exit code 0 when inspection succeeds, including
when protected files have changed. It still lists every inventoried difference,
keeps `approval_granted=false` and `runtime_safety_truth=false`, and never updates
the original baseline. Invalid baselines or unreadable files still return errors.
`--enforce` runs a strict, read-only comparison for verification without restoring
the policy. When the user requests restoration, set `ENFORCE_FREEZE` back to
`True` and restore the active status in this policy and `AGENTS.md`; review the
accumulated changes against the preserved baseline.

Hard safety boundaries and explicit authorization for external or destructive
actions remain active. Suspension is not production or runtime qualification.

## Original Freeze Policy (Inactive During Suspension)

The user requested that Dashboard Navigation be fixed at its current behavior,
that work on other pages must not change it, and that Navigation-related changes
require their approval. This is a change-control boundary, not productization,
runtime qualification, or a claim that every existing issue has been resolved.

## Frozen Baseline

`qualification/navigation-freeze-baseline.json` records SHA-256 hashes of the
**current worktree**, including the existing uncommitted Navigation work. HEAD
is not the baseline. Do not revert those changes or commit unrelated work to
make the check pass. The exact machine inventory is `PROTECTED_GROUPS` in
`tools/verify_navigation_freeze.py`.

The protected functional scope includes:

- Navigation layout, 2D/3D views, camera persistence, Rudy+TW basemap, layers,
  legends, route visibility, selection, highlighting, loading and failure states.
- A/B selection and persistence; R1-R3 hypotheses, cost models, corridor masks,
  cache keys, overlays, explanations, and result preservation on failure.
- R4 text interpretation, Gn alternatives, evidence focus and previous/next
  navigation, corridor filtering, map anchors, human review and guided execution.
- Diagnostic Navigation checks; QGIS/GRASS worker startup, readiness, lifecycle,
  request/response contracts, and Mac/Scout execution configuration.
- Workspace DEM extent, native resolution, clipping, NoData checks, provenance,
  preparation, projection, GPX inputs, workspace publication and persistence.
- Shared HTML/CSS/JavaScript, API handlers, map assets, layer contracts, dependency
  declarations and regression checks capable of changing the above behavior.

Navigation currently shares one large Dashboard HTML file, MapLibre and API
entrypoints with other pages. These inventoried shared files are protected
**as whole files**, including formatting, imports and global styles. A Weather,
Architecture or other page task is not permission to edit them. Keep unrelated
work in independent files; if wiring it up needs a shared entrypoint, stop and
ask first. A future physical separation of Navigation is itself approval-gated.

The policy also applies to indirect changes outside the current inventory when
they could affect Navigation. The inventory is a conservative source-drift
detector, not a complete dependency graph or proof of semantic isolation.
Navigation-related parts of shared specifications, including the Navigation
chapter of `docs/specs/SCOUT_OUTDOOR_AI_AGENT_STANDARD.md`, need the same approval;
unrelated chapters do not become frozen merely by sharing a document.

## Approval Protocol

1. Before editing, identify whether the task changes any protected behavior,
   dependency, shared entrypoint, artifact contract or validation check. Run the
   read-only guard before work and again after work.
2. If Navigation could be affected or the impact is uncertain, describe the exact
   files, intended behavioral change and likely impact. Wait for the user's
   explicit approval naming that Navigation change before implementation.
3. A clearly scoped user request to change Navigation can supply approval for
   that exact change. Generic "continue", "fix the Dashboard", "commit", another
   page request, a test failure or an agent's judgment cannot supply approval.
4. Approval is per change, not a permanent unlock. Record the user's instruction,
   approved scope and verification in the task or change record. Preserve the
   original baseline until the approved change has been verified. Updating the
   affected hashes must be part of that approved scope, never automatic cleanup.
5. Do not remove protected paths, weaken tests, rewrite the baseline, add skip or
   auto-approval flags, or disable the guard to get a passing result. Editing this
   policy, the guard or its baseline also needs explicit user approval.
6. Verify approved behavior through focused tests and the affected real browser
   workflow when available. Report unverified worker/host behavior as UNKNOWN.
   A source hash match never replaces functional or live-runtime evidence.

Read-only inspection and non-mutating tests are allowed. QA does not authorize
changing runtime configuration, restarting workers, regenerating workspace DEM,
TRH or R4 results, rewriting GPX, or replacing a live projection. Existing user
operations within Navigation remain usable; the freeze does not disable the UI.

### Standing Local-Venv Authorization

On 2026-09-04 the user explicitly authorized future local venv upgrades without
repeated approval requests. Installing or upgrading packages in the local venv,
and running focused compatibility checks, is not by itself a Navigation page
change. Record before/after versions and preserve unrelated installed packages.

This standing authorization does not permit changes to Navigation code, shared
GIS/workspace contracts, worker or server restarts, hardware deployment, or the
freeze baseline/guard. Tracked dependency declaration edits stay within the
scope of the requested upgrade. Approved declaration changes may still appear
in the read-only source-drift report; record their approval rather than updating
the baseline or weakening the check to hide them.

## Local And CI Check

```bash
rtk proxy ./venv/bin/python tools/verify_navigation_freeze.py
rtk proxy ./venv/bin/python -m pytest tests/test_navigation_freeze.py -q
```

The standalone guard needs only Python's standard library. It reads source
files and the committed baseline, does not import Scout runtime modules, and
never starts a server, runs GIS, accesses private workspaces, writes a baseline,
restores files, or grants approval. Missing/invalid baselines, unreadable files,
and symlinks fail closed with a nonzero exit code. Changed or deleted protected
files and new files matching the protected patterns return a nonzero exit code
only in strict mode (`--enforce`) while the freeze is suspended.

In strict mode, `FROZEN_UNCHANGED` means only that inventoried source bytes are
unchanged. `NAVIGATION_APPROVAL_REQUIRED` reports drift for human review. It does not infer
whether the user already approved it, and never silently absorbs it. The baseline
contains hashes only, not workspace data, GPX coordinates or credentials.

The same check is configured in `.github/workflows/navigation-freeze.yml` for PRs,
main-branch pushes and merge groups. The local pytest guard runs with the existing
suite. No global Git hook, file permissions or GitHub branch-protection setting
is changed. The workflow takes effect remotely only after an authorized commit
and push. Requiring this status check in branch protection remains a separate
repository-owner operation, not performed here.

This is not tamper-proof access control: a writer who can replace both the guard
and baseline can bypass a hash check. The user's approval policy governs such
changes; repository review/branch protection can strengthen enforcement later.

## Authority Unchanged

TRH and R4 remain `candidate_only`, never runtime safety truth. Neither a frozen
version nor approval to edit code confirms an existing trail, safe route,
passability, legal access or correctness of a GPX. DEM resolution, vegetation,
microterrain, recent landslides and engineered-trail uncertainty remain explicit.
