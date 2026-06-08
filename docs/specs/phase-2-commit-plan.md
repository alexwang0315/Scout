# Phase 2 v0.1 Commit Plan

## Goal

Package the current Phase 2 v0.1 work into reviewable commits without changing
the Phase 1 safety runtime. This plan only describes staging and commit order;
it does not stage, commit, or modify any runtime files.

## Guardrails

- Do not stage or commit `PdrSample/*` unless the owner explicitly asks.
- Do not stage or commit `trajectory_map.png` unless the owner explicitly asks.
- Do not stage or commit `install_skills.sh` unless the owner explicitly asks.
- Do not fold unrelated dirty edits into Phase 2 commits.
- Do not modify Phase 1 safety runtime files as part of packaging.
- Keep review commands read-only until a human chooses a group to stage.

## Current Dirty Files To Exclude

These files were present in the working tree but are outside this Phase 2
packaging plan:

```text
trajectory_map.png
PdrSample/2.json
PdrSample/781F934A4B6A-1.txt
PdrSample/stream Apple Watch 260430 18_04_12.json
PdrSample/stream Apple Watch 260511 08_52_12.gpx
PdrSample/stream Apple Watch 260511 08_52_12.json
PdrSample/stream Apple Watch 260512 08_52_37.json
PdrSample/stream Apple Watch 260512 09_39_31.json
PdrSample/wifiscan.txt
install_skills.sh
```

## Suggested Commit Order

### 1. Phase 2 Docs And Specs

Purpose: land the product/spec/release planning context before code.

Files:

```text
docs/specs/phase-2-personal-safety-os.md
docs/specs/phase-2-implementation-plan.md
docs/specs/phase-2-release-checklist.md
docs/specs/phase-2-release-notes.md
docs/specs/phase-2-admin-api-mount-plan.md
docs/specs/phase-2-artifact-id-convention.md
docs/specs/phase-2-cleanup-review.md
docs/specs/phase-2-commit-plan.md
README.md
```

Review:

```bash
git diff -- docs/specs/phase-2-personal-safety-os.md \
  docs/specs/phase-2-implementation-plan.md \
  docs/specs/phase-2-release-checklist.md \
  docs/specs/phase-2-release-notes.md \
  docs/specs/phase-2-admin-api-mount-plan.md \
  docs/specs/phase-2-artifact-id-convention.md \
  docs/specs/phase-2-cleanup-review.md \
  docs/specs/phase-2-commit-plan.md \
  README.md
```

Stage when ready:

```bash
git add -- docs/specs/phase-2-personal-safety-os.md \
  docs/specs/phase-2-implementation-plan.md \
  docs/specs/phase-2-release-checklist.md \
  docs/specs/phase-2-release-notes.md \
  docs/specs/phase-2-admin-api-mount-plan.md \
  docs/specs/phase-2-artifact-id-convention.md \
  docs/specs/phase-2-cleanup-review.md \
  docs/specs/phase-2-commit-plan.md \
  README.md
```

Suggested commit message:

```text
docs: add phase 2 packaging and release specs
```

### 2. Brain Store And Writeback Foundation

Purpose: introduce the file-based Phase 2 Brain, ingestion, artifact references,
and writeback rules as one coherent foundation.

Files:

```text
phase2_brain_models.py
phase2_brain_store.py
phase2_brain_ingest.py
phase2_refs.py
phase2_store_utils.py
phase2_writeback_policy.py
phase2_artifact_manifest.py
phase2_artifact_manifest_store.py
tests/test_phase2_brain.py
tests/test_phase2_brain_ingest.py
tests/test_phase2_refs.py
tests/test_phase2_store_utils.py
tests/test_phase2_writeback_policy.py
tests/test_phase2_artifact_manifest.py
tests/test_phase2_artifact_manifest_store.py
```

Review:

```bash
git diff -- phase2_brain_models.py phase2_brain_store.py \
  phase2_brain_ingest.py phase2_refs.py phase2_store_utils.py phase2_writeback_policy.py \
  phase2_artifact_manifest.py phase2_artifact_manifest_store.py \
  tests/test_phase2_brain.py tests/test_phase2_brain_ingest.py tests/test_phase2_refs.py \
  tests/test_phase2_store_utils.py tests/test_phase2_writeback_policy.py \
  tests/test_phase2_artifact_manifest.py \
  tests/test_phase2_artifact_manifest_store.py
```

Stage when ready:

```bash
git add -- phase2_brain_models.py phase2_brain_store.py \
  phase2_brain_ingest.py phase2_refs.py phase2_store_utils.py phase2_writeback_policy.py \
  phase2_artifact_manifest.py phase2_artifact_manifest_store.py \
  tests/test_phase2_brain.py tests/test_phase2_brain_ingest.py tests/test_phase2_refs.py \
  tests/test_phase2_store_utils.py tests/test_phase2_writeback_policy.py \
  tests/test_phase2_artifact_manifest.py \
  tests/test_phase2_artifact_manifest_store.py
```

Suggested commit message:

```text
feat: add phase 2 brain store and writeback foundation
```

### 3. Skill Registry, Runtime, And Manifests

Purpose: package the skill manifest schema, registry loader, runtime integration,
and initial Scout manifests together.

Files:

```text
skill_registry_models.py
skill_registry.py
skill_runtime.py
skill_runtime_integration.py
skills/scout/beacon-trend-mock.yaml
skills/scout/checkpoint-delay-analysis.yaml
skills/scout/communication-state-check.yaml
skills/scout/decision-options.yaml
skills/scout/device-capability-check.yaml
skills/scout/latest-team-position-check.yaml
skills/scout/remote-status-json.yaml
skills/scout/team-checkin-summary.yaml
skills/scout/team-rendezvous-beacon.yaml
.gitignore
tests/test_skill_manifest_coverage.py
tests/test_phase2_fixture_skill_manifest_coverage.py
tests/test_skill_registry.py
tests/test_skill_runtime.py
tests/test_skill_runtime_integration.py
```

Review:

```bash
git diff -- skill_registry_models.py skill_registry.py skill_runtime.py \
  skill_runtime_integration.py skills/scout \
  .gitignore \
  tests/test_skill_manifest_coverage.py tests/test_phase2_fixture_skill_manifest_coverage.py \
  tests/test_skill_registry.py \
  tests/test_skill_runtime.py tests/test_skill_runtime_integration.py
```

Stage when ready:

```bash
git add -- skill_registry_models.py skill_registry.py skill_runtime.py \
  skill_runtime_integration.py skills/scout \
  .gitignore \
  tests/test_skill_manifest_coverage.py tests/test_phase2_fixture_skill_manifest_coverage.py \
  tests/test_skill_registry.py \
  tests/test_skill_runtime.py tests/test_skill_runtime_integration.py
```

Suggested commit message:

```text
feat: add phase 2 skill registry and manifests
```

### 4. Gates, Options, Remote Status, Team, And Case Logic

Purpose: land the decision-control layer: activation gates, option generation,
remote status artifacts, team cohesion, and case replay logic.

Files:

```text
ln_constraints.py
decision_options.py
remote_status.py
remote_status_store.py
team_cohesion.py
case_replay.py
phase2_case_replay_integration.py
tests/test_ln_constraints.py
tests/test_decision_option_sets.py
tests/test_phase2_remote_status.py
tests/test_phase2_remote_status_store.py
tests/test_phase2_case_replay.py
tests/test_phase2_case_replay_integration.py
tests/test_phase2_second_fixture_replay_integration.py
tests/test_team_beacon.py
```

Review:

```bash
git diff -- ln_constraints.py decision_options.py remote_status.py \
  remote_status_store.py team_cohesion.py case_replay.py \
  phase2_case_replay_integration.py tests/test_ln_constraints.py \
  tests/test_decision_option_sets.py tests/test_phase2_remote_status.py \
  tests/test_phase2_remote_status_store.py tests/test_phase2_case_replay.py \
  tests/test_phase2_case_replay_integration.py tests/test_phase2_second_fixture_replay_integration.py \
  tests/test_team_beacon.py
```

Stage when ready:

```bash
git add -- ln_constraints.py decision_options.py remote_status.py \
  remote_status_store.py team_cohesion.py case_replay.py \
  phase2_case_replay_integration.py tests/test_ln_constraints.py \
  tests/test_decision_option_sets.py tests/test_phase2_remote_status.py \
  tests/test_phase2_remote_status_store.py tests/test_phase2_case_replay.py \
  tests/test_phase2_case_replay_integration.py tests/test_phase2_second_fixture_replay_integration.py \
  tests/test_team_beacon.py
```

Suggested commit message:

```text
feat: add phase 2 gates options and team status logic
```

### 5. Replay, Demo, Admin, And Artifact Surfaces

Purpose: package user-facing and inspection surfaces separately from core logic.

Files:

```text
phase2_option_replay.py
phase2_demo_defaults.py
phase2_remote_status_replay.py
phase2_team_replay_demo.py
phase2_team_replay_store.py
phase2_admin_api.py
phase2_admin_preview.py
server.py
phase2_release_check.py
tests/test_phase2_option_replay.py
tests/test_phase2_demo_defaults.py
tests/test_phase2_remote_status_replay.py
tests/test_phase2_team_replay.py
tests/test_phase2_team_replay_demo.py
tests/test_phase2_team_replay_demo_golden.py
tests/test_phase2_team_replay_store.py
tests/test_phase2_team_replay_second_fixture.py
tests/test_phase2_admin_api.py
tests/test_phase2_admin_api_mount.py
tests/test_phase2_admin_preview.py
tests/test_phase2_release_check.py
```

Review:

```bash
git diff -- phase2_option_replay.py phase2_demo_defaults.py phase2_remote_status_replay.py \
  phase2_team_replay_demo.py phase2_team_replay_store.py \
  phase2_admin_api.py phase2_admin_preview.py server.py phase2_release_check.py \
  tests/test_phase2_option_replay.py tests/test_phase2_demo_defaults.py \
  tests/test_phase2_remote_status_replay.py \
  tests/test_phase2_team_replay.py tests/test_phase2_team_replay_demo.py \
  tests/test_phase2_team_replay_demo_golden.py tests/test_phase2_team_replay_store.py \
  tests/test_phase2_team_replay_second_fixture.py \
  tests/test_phase2_admin_api.py tests/test_phase2_admin_api_mount.py \
  tests/test_phase2_admin_preview.py \
  tests/test_phase2_release_check.py
```

Stage when ready:

```bash
git add -- phase2_option_replay.py phase2_demo_defaults.py phase2_remote_status_replay.py \
  phase2_team_replay_demo.py phase2_team_replay_store.py \
  phase2_admin_api.py phase2_admin_preview.py server.py phase2_release_check.py \
  tests/test_phase2_option_replay.py tests/test_phase2_demo_defaults.py \
  tests/test_phase2_remote_status_replay.py \
  tests/test_phase2_team_replay.py tests/test_phase2_team_replay_demo.py \
  tests/test_phase2_team_replay_demo_golden.py tests/test_phase2_team_replay_store.py \
  tests/test_phase2_team_replay_second_fixture.py \
  tests/test_phase2_admin_api.py tests/test_phase2_admin_api_mount.py \
  tests/test_phase2_admin_preview.py \
  tests/test_phase2_release_check.py
```

Suggested commit message:

```text
feat: add phase 2 replay demo and admin surfaces
```

### 6. Phase 2 Fixtures

Purpose: stage replay and policy data after the code that consumes it, so fixture
review can focus on scenario quality and expected outputs.

Files:

```text
tests/fixtures/phase2/cases/cold_rain_bivouac_delay.json
tests/fixtures/phase2/cases/fog_delay_ridge_turnaround.json
tests/fixtures/phase2/cases/river_gorge_team_separation.json
tests/fixtures/phase2/demo/team_replay_demo_summary_golden.json
tests/fixtures/phase2/policies/multi_day_expedition.json
tests/fixtures/phase2/policies/same_day_loop.json
tests/fixtures/phase2/policies/traverse.json
tests/fixtures/phase2/team_replay/forest_traverse_two_person_team_replay.json
tests/fixtures/phase2/team_replay/ridge_three_person_team_replay.json
```

Review:

```bash
git diff -- tests/fixtures/phase2
```

Stage when ready:

```bash
git add -- tests/fixtures/phase2
```

Suggested commit message:

```text
test: add phase 2 replay and policy fixtures
```

## Optional Pathspec Workflow

For a safer staging flow, put one group at a time into a temporary pathspec file
and stage from that file:

```bash
mktemp /tmp/scout-phase2-stage.XXXXXX
git diff --name-status --pathspec-from-file=/tmp/scout-phase2-stage.XXXXXX
git add --pathspec-from-file=/tmp/scout-phase2-stage.XXXXXX
```

Before staging, check that the pathspec does not include excluded files:

```bash
rg -n '^(PdrSample/|trajectory_map\.png$|install_skills\.sh$)' /tmp/scout-phase2-stage.XXXXXX
```

The `rg` command should return no matches.

## Pre-Commit Review Checklist

Run these read-only checks before choosing any staging group:

```bash
git status --short --untracked-files=all
rg -n 'PdrSample/|trajectory_map\.png|install_skills\.sh' docs/specs/phase-2-commit-plan.md
rg -n 'phase2_|skill_|ln_constraints|decision_options|remote_status|team_cohesion|case_replay' docs/specs/phase-2-commit-plan.md
```

Expected result: the status still shows excluded local files as unstaged, the
exclusion search names `PdrSample/*`, `trajectory_map.png`, and
`install_skills.sh`, and the Phase 2 search shows all planned implementation
families.
