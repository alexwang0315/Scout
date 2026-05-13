# Phase 2 v0.1 Release Checklist

This checklist is for the Phase 2 v0.1 documentation and replay acceptance
slice. It is intentionally read-only: do not stage or commit as part of this
checklist run.

## Phase 2 Files

Docs and admin surface:

- `docs/specs/phase-2-personal-safety-os.md`
- `docs/specs/phase-2-implementation-plan.md`
- `docs/specs/phase-2-release-checklist.md`
- `docs/specs/phase-2-release-notes.md`
- `docs/admin/phase1-after-action.html`

Core Phase 2 modules:

- `phase2_brain_models.py`
- `phase2_brain_store.py`
- `phase2_writeback_policy.py`
- `phase2_brain_ingest.py`
- `phase2_team_replay_store.py`
- `phase2_remote_status_replay.py`
- `phase2_option_replay.py`
- `phase2_case_replay_integration.py`
- `phase2_team_replay_demo.py`
- `phase2_admin_preview.py`
- `phase2_admin_api.py`
- `phase2_artifact_manifest.py`
- `phase2_artifact_manifest_store.py`
- `remote_status.py`
- `remote_status_store.py`
- `decision_options.py`
- `case_replay.py`
- `ln_constraints.py`
- `team_cohesion.py`
- `skill_registry.py`
- `skill_registry_models.py`
- `skill_runtime.py`
- `skill_runtime_integration.py`

Versioned Phase 2 data:

- `skills/scout/*.yaml`
- `tests/fixtures/phase2/team_replay/ridge_three_person_team_replay.json`
- `tests/fixtures/phase2/team_replay/forest_traverse_two_person_team_replay.json`
- `tests/fixtures/phase2/policies/*.json`
- `tests/fixtures/phase2/cases/*.json`
- `tests/fixtures/phase2/demo/team_replay_demo_summary_golden.json`

Focused tests:

- `tests/test_phase2_brain.py`
- `tests/test_phase2_writeback_policy.py`
- `tests/test_skill_registry.py`
- `tests/test_skill_manifest_coverage.py`
- `tests/test_skill_runtime.py`
- `tests/test_skill_runtime_integration.py`
- `tests/test_ln_constraints.py`
- `tests/test_phase2_remote_status.py`
- `tests/test_phase2_remote_status_replay.py`
- `tests/test_phase2_remote_status_store.py`
- `tests/test_decision_option_sets.py`
- `tests/test_team_beacon.py`
- `tests/test_phase2_team_replay.py`
- `tests/test_phase2_team_replay_store.py`
- `tests/test_phase2_team_replay_demo.py`
- `tests/test_phase2_option_replay.py`
- `tests/test_phase2_case_replay.py`
- `tests/test_phase2_case_replay_integration.py`
- `tests/test_phase2_brain_ingest.py`
- `tests/test_phase2_admin_preview.py`
- `tests/test_phase2_admin_api.py`
- `tests/test_phase2_artifact_manifest.py`
- `tests/test_phase2_artifact_manifest_store.py`
- `tests/test_phase2_team_replay_demo_golden.py`
- `tests/test_admin_after_action.py`

## Verification Commands

Read-only docs consistency check:

```bash
rg -n "Phase 2 v0.1|Latest known integration result|forest_traverse|release checker|PdrSample|trajectory_map|install_skills" docs/specs/phase-2-release-notes.md docs/specs/phase-2-release-checklist.md docs/specs/phase-2-implementation-plan.md README.md
rg -n "admin preview|artifact manifest|manifest coverage|Verification Gate|Phase 2 v0.1" docs/specs/phase-2-implementation-plan.md docs/specs/phase-2-release-checklist.md
rg -n "reference classifier|demo boundary|release-doc|139 passed|PdrSample|trajectory_map|install_skills|artifact naming|manual-write" docs/specs/phase-2-cleanup-review.md docs/specs/phase-2-release-checklist.md docs/specs/phase-2-release-notes.md docs/specs/phase-2-implementation-plan.md
rg --files | rg '(^docs/specs/phase-2|^phase2_|^tests/test_.*phase2|^tests/test_skill_manifest_coverage.py|^tests/test_admin_after_action.py|^skills/scout|^tests/fixtures/phase2)'
```

Expected focused test commands when executing tests is in scope:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_phase2_brain.py
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_phase2_writeback_policy.py
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_skill_registry.py
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_skill_manifest_coverage.py
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_skill_runtime.py
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_skill_runtime_integration.py
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_ln_constraints.py
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_phase2_remote_status.py
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_phase2_remote_status_replay.py
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_phase2_remote_status_store.py
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_decision_option_sets.py
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_team_beacon.py
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_phase2_team_replay.py
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_phase2_team_replay_store.py
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_phase2_team_replay_demo.py
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_phase2_option_replay.py
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_phase2_refs.py
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_phase2_store_utils.py
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_phase2_case_replay.py
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_phase2_case_replay_integration.py
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_phase2_brain_ingest.py
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_phase2_admin_preview.py
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_phase2_admin_api.py
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_phase2_admin_api_mount.py
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_phase2_demo_defaults.py
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_phase2_artifact_manifest.py
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_phase2_artifact_manifest_store.py
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_phase2_team_replay_demo_golden.py
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_phase2_team_replay_second_fixture.py
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_phase2_release_check.py
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_phase2_fixture_skill_manifest_coverage.py
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_phase2_second_fixture_replay_integration.py
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_admin_after_action.py
```

Latest known integration result for this focused Phase 2 target set:
`141 passed, 1 warning, 41 subtests passed`. This checklist records the post
helper-consolidation, forest fixture replay probe, admin-evidence-preview
cleanup, release-notes, fixture skill manifest-coverage, and docs validation
refresh slice integration result, plus artifact naming enforcement,
test-hardening, manual-write-policy verification, and the completed shared
reference classifier and demo-boundary cleanup slices.

Full release gate when test execution is allowed:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest
```

Latest known integration result for the full repository regression:
`238 passed, 1 warning, 50 subtests passed`. This is the completed full repo
regression currently recorded for Phase 2 v0.1 release readiness.

CLI smoke command when execution is allowed:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python phase2_team_replay_demo.py --store-root /tmp/scout-phase2-team-replay-demo
```

## Known Limits

- Phase 1 safety runtime is the deterministic baseline and is not part of this
  release checklist slice.
- Phase 2 v0.1 uses file-backed Brain nodes, JSON artifacts, manifests, and
  mocks; it does not require a graph database, cloud transport, live radio
  hardware, drone control, or a polished production UI.
- Admin preview, admin API, and artifact manifest outputs are read-only
  projections from persisted Brain nodes.
- Beacon behavior remains trend-based and must not claim exact position,
  bearing, or distance.
- Case replay verdicts are bounded audit outcomes, not claims that Scout would
  guarantee rescue or injury prevention.
- Large raw `PdrSample` captures should stay local unless a future change
  explicitly promotes a derived, versioned fixture.
- Local-only dirty artifacts such as `trajectory_map.png` and
  `install_skills.sh` should stay out of the release stage unless the owner
  explicitly asks to include them.

## Suggested Stage and Commit Groups

- Docs release checklist: `docs/specs/phase-2-implementation-plan.md` and
  `docs/specs/phase-2-release-checklist.md`.
- Phase 2 runtime and tests: Phase 2 Python modules, `skills/scout/*.yaml`, and
  focused `tests/test_phase2_*.py` / skill tests.
- Phase 2 fixtures: `tests/fixtures/phase2/**`.
- Admin preview surface: `phase2_admin_preview.py`,
  `phase2_admin_api.py`, `tests/test_phase2_admin_preview.py`,
  `tests/test_phase2_admin_api.py`, `tests/test_admin_after_action.py`, and
  `docs/admin/phase1-after-action.html`.
- Artifact manifest surface: `phase2_artifact_manifest.py`,
  `phase2_artifact_manifest_store.py`,
  `tests/test_phase2_artifact_manifest.py`, and
  `tests/test_phase2_artifact_manifest_store.py`.

Do not include unrelated dirty files, raw `PdrSample` captures,
`trajectory_map.png`, or `install_skills.sh` in these groups unless the owner
explicitly asks for them.
