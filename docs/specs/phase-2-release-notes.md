# Phase 2 v0.1 Release Notes And Test Matrix

Phase 2 v0.1 is a replay-first preview of Scout as a personal safety operating
system layered on top of the Phase 1 trail safety black box. It adds file-backed
Brain nodes, audited skill runs, remote status artifacts, decision-support
outputs, case replay, fixture persistence, read-only admin previews, artifact
manifests, a fixture-backed Phase 1 evidence adapter, and a release checker.

Phase 2 does not replace Phase 1. Phase 1 deterministic route-progress,
incident packaging, safety levels, live ingest, and after-action behavior remain
the safety baseline. Phase 2 outputs are bounded support and audit artifacts;
they must not directly decide emergency escalation or mutate Phase 1 runtime
state.

## Implemented Scope

- File-backed Brain models and store recovery for facts, deterministic
  measurements, interpretations, human reviews, skill runs, and artifacts.
- Writeback policy that allows automatic fact and deterministic measurement
  writes while keeping model interpretations provenance-required and
  append-only.
- Scout skill registry, manifest coverage checks, and mock skill runtime records
  with inputs, outputs, preflight results, activation decisions, failure policy,
  and artifact refs.
- Ln activation gates and policy fixtures for allow, disallow, defer, and
  degrade decisions with cooldown, acknowledgement, and new-evidence controls.
- Team hiking remote status JSON, decision option sets, team separation signals,
  and trend-based rendezvous beacon mocks.
- Case replay timelines and bounded verdicts for audit-style incident
  evaluation.
- Team replay fixture persistence, option replay, case replay Brain integration,
  compact demo output, and stored artifact manifests.
- Env-gated Phase 2 admin API mount and read-only Phase 2 admin preview payloads
  for persisted Brain evidence and artifact inspection.
- Shared Phase 2 reference classification, store helpers, artifact ID
  conventions, and cleanup review docs.
- Fixture-backed Phase 1 incident package adapter that imports persisted
  incident package JSON into Phase 2 artifacts, observed facts, and deterministic
  measurements without live `/safety/*` wiring.
- Demo defaults are being isolated behind shared constants, but the broader demo
  boundary remains in progress or next until reusable-builder boundaries are
  verified by the code owner.

## Fixtures And Data

- `tests/fixtures/phase2/team_replay/ridge_three_person_team_replay.json`
  remains the primary Phase 2 team replay fixture and demo baseline.
- `tests/fixtures/phase2/team_replay/forest_traverse_two_person_team_replay.json`
  adds a second synthetic team replay: a two-person forest traverse with an
  eight-minute checkpoint delay, fresh member positions, no separation signal,
  and an `L1` nominal short-delay remote status.
- `tests/fixtures/phase2/cases/*.json` covers realistic incident-style case
  replay inputs.
- `tests/fixtures/phase2/policies/*.json` covers Ln activation policy contexts.
- `tests/fixtures/phase2/demo/team_replay_demo_summary_golden.json` preserves
  the compact demo summary contract.
- `tests/fixtures/phase2/phase1_adapter/*.json` covers fixture-backed Phase 1
  incident package imports into the Phase 2 Brain.
- `skills/scout/*.yaml` contains registry-managed Scout skill manifests covered
  by manifest tests and release-check validation.

## Admin Preview And API

- `phase2_admin_preview.py` projects persisted Brain nodes into a compact,
  read-only admin preview payload.
- `phase2_admin_api.py` exposes the preview under the Phase 2 admin router.
- `server.py` mounts the Phase 2 admin API only when explicitly enabled by
  environment configuration.
- Phase 2 admin routes are namespaced separately from Phase 1 `/admin/*`,
  `/safety/*`, `/pdr/update`, `/status`, and root routes.
- Admin preview, admin API, and artifact manifest outputs are release views over
  persisted Phase 2 data, not write paths into the Phase 1 safety runtime.

## Safety Guardrails

- Phase 1 deterministic safety behavior remains the release baseline.
- The Phase 1 evidence adapter is downstream-only. Future live connection should
  start after incident persistence, stay disabled by default, and fail without
  changing Phase 1 escalation or response behavior.
- LLM or model output must not decide L3 or L4 emergency escalation.
- Model interpretations must not be stored as observed facts.
- Decision option sets express bounded support choices, not commands.
- Beacon mocks are trend-based and must not claim exact position, bearing, or
  distance.
- Case replay verdicts are audit outcomes and do not guarantee rescue, injury
  prevention, or real-world incident resolution.
- Phase 2 v0.1 uses JSON artifacts, local files, mocks, and replay fixtures; it
  does not include cloud transport, live radio hardware, drone control, or a
  production UI.

## Release Checker

`phase2_release_check.py` verifies required Phase 2 docs, core modules,
versioned fixtures, focused tests, demo golden output, and Scout skill manifest
coverage without running pytest. It is a fast artifact-presence and coverage
gate, not a behavioral regression substitute.

Release checker focused test:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_phase2_release_check.py
```

Release checker CLI smoke:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python phase2_release_check.py --repo-root /Users/alexwang0315/scout-fusion
```

## Test Matrix

Read-only docs and inventory checks:

```bash
rg -n "Phase 2 v0.1|Latest known integration result|forest_traverse|release checker|PdrSample|trajectory_map|install_skills" docs/specs/phase-2-release-notes.md docs/specs/phase-2-release-checklist.md docs/specs/phase-2-implementation-plan.md README.md
rg --files docs/specs tests/fixtures/phase2 | rg '(phase-2-release|forest_traverse|team_replay_demo_summary_golden)'
```

Focused Phase 2 behavior and release-gate tests are listed in
`docs/specs/phase-2-release-checklist.md`.

Latest known focused Phase 2 result currently recorded in the docs:
`153 passed, 1 warning, 41 subtests passed`.

Full repository regression gate:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest
```

Latest known full repository result currently recorded in the docs:
`242 passed, 1 warning, 50 subtests passed`.

These numbers should be refreshed before cutting a release. The current focused
number includes the reference-classifier, demo-boundary cleanup, and completed
Milestone 9 Phase 1 evidence adapter slices.

## Known Dirty Exclusions

Keep these out of the Phase 2 v0.1 release stage unless the owner explicitly
asks to include them:

- `PdrSample/*`
- `trajectory_map.png`
- `install_skills.sh`
