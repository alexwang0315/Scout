# Phase 4 Dirty Worktree Cleanup Plan

這份 cleanup plan 用來整理目前工作樹中大量未提交草稿，避免它們污染 hardware-port commit。

## Commit Groups

1. Phase 4 planning core:
   `pretrip_models.py`, `pretrip_source_ingest.py`, candidate/readiness/artifact manifest tests.
2. Phase 4 admin and map UI:
   `pretrip_admin_view.py`, `admin_map_layers.py`, `admin_basemap_tiles.py`, static admin pages.
3. Phase 1 after-action UI:
   `admin_after_action.py`, `docs/admin/phase1-after-action.html`,
   `tests/test_admin_after_action.py`; keep generated/local map artifacts out
   unless they are explicitly promoted as fixtures.
4. Phase 4.5 runtime handoff:
   `pretrip_runtime_*`, `runtime_activation_loader.py`, `runtime_load_dry_run.py`.
5. Runtime stream, admission, and remote provider drafts:
   `runtime_stream_*`, `runtime_remote_provider_*`,
   `runtime_observation_envelope.py`, `runtime_input_admission.py`,
   `server_safety_observation_admission_config.py`, and safety API/server
   mount changes.
6. Local-only field data:
   `PdrSample/*`, `trajectory_map.png`, `catographydata/`,
   `install_skills.sh`.

## Exclusion Rules

- Do not mix Phase 4/pretrip implementation into hardware-port commits.
- Do not commit `PdrSample/*` or large local field data unless explicitly requested.
- Do not commit live runtime provider send paths with assistant guardrail work.
- Keep `/safety/*` mutation changes separate from read-only assistant/debug/hardware readiness work.
- Keep local model/Ollama compose separate from deterministic Pi runtime-core.
- Keep after-action UI cleanup separate from Phase 4 pretrip planning UI unless
  the change is explicitly an after-action-to-next-plan read-only projection.
- Keep runtime stream/admission commits opt-in, secret-gated, and separate from
  remote provider live-send paths.

## Validation

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_phase4_dirty_worktree_cleanup_plan.py
```

## Batch 1 Result

Batch 1 kept the hardware-port commits narrow and did not stage the Phase 4 dirty worktree flood.

Completed separation:

- hardware runtime-core and Scout machine smoke evidence are documented
  separately from pretrip planning;
- `PdrSample/*`, `catographydata/`, and `trajectory_map.png` remain local-only;
- `runtime_stream_*` and `runtime_remote_provider_*` remain a separate boundary
  review group;
- `docker-compose.pi.ai.yml` remains outside deterministic Docker Step 1;
- `/safety/*` mutation changes remain outside assistant/hardware readiness work.

Next cleanup batch should choose one Phase 4 group at a time, starting with
planning core models/fixtures if the user wants to stabilize Phase 4. Do not combine it with runtime stream/live provider send paths.

## Batch 2 Ready State

The remaining dirty worktree is now grouped for these follow-up slices:

1. Phase 4 planning core models and fixture outputs.
2. Phase 4 admin/map UI and static pretrip page.
3. Phase 1 after-action UI.
4. Runtime stream/admission opt-in contract.
5. Runtime remote provider live-send drafts.

Ordering rule:

- finish and commit Phase 4 planning/admin groups before touching runtime stream/admission;
- commit after-action UI as its own Phase 1 admin surface slice;
- do not stage `PdrSample/*`, `catographydata/`, `trajectory_map.png`, or `install_skills.sh` during these cleanup batches;
- do not enable local model/Ollama or remote provider live-send in the same
  slice as deterministic runtime or planning UI.

## Batch 3 Local Artifact Hygiene

This batch classifies local-only artifacts so future Phase 4, runtime, and
hardware prototype slices do not accidentally stage heavyweight captures.

Repo-owned clarification:

- `docs/specs/case-study-addition-skill.md` is a Scout internal specification
  for future built-in case-study skills. It belongs in this repo and must not be treated as local scratch or ignored by `.gitignore`.

Ignored local artifacts:

- `PdrSample/` contains local raw field captures. Version only curated manifests
  or derived fixtures after explicit approval.
- `catographydata/` contains local raw DTM/map data. Version only clipped or
  summarized metadata fixtures.
- `trajectory_map.png` is a generated/local map image. It is already tracked,
  so `.gitignore` does not hide the current modification. Do not reset, untrack,
  or recommit it without a separate explicit decision.
- `install_skills.sh` is a local operator setup helper, not a Scout runtime or
  planning artifact.

Future visible slices:

- `docker-compose.pi.ai.yml` and `tools/pi_ollama_stress.py` remain visible
  rather than ignored because they may become a separate Pi/Ollama hardware
  experiment slice with docs and tests.

Validation:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_phase4_dirty_worktree_cleanup_plan.py tests/test_local_artifact_hygiene_check.py
/Users/alexwang0315/scout-fusion/venv/bin/python local_artifact_hygiene_check.py --pretty
```

Batch 3 executable gate:

- `local_artifact_hygiene_check.py` is a read-only git status gate for
  local-only artifacts.
- Dirty but unstaged local-only artifacts are allowed and reported. This covers
  the current tracked `trajectory_map.png` case without resetting, untracking,
  or recommitting the image.
- Staged local-only artifacts fail the gate with
  `local_only_staged:<path>` in `missing_required_artifacts`.
- The gate must not mutate the worktree, revert files, stage files, commit
  files, or remove tracked files.
