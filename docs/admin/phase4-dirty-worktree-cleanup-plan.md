# Phase 4 Dirty Worktree Cleanup Plan

這份 cleanup plan 用來整理目前工作樹中大量未提交草稿，避免它們污染 hardware-port commit。

## Commit Groups

1. Phase 4 planning core:
   `pretrip_models.py`, `pretrip_source_ingest.py`, candidate/readiness/artifact manifest tests.
2. Phase 4 admin and map UI:
   `pretrip_admin_view.py`, `admin_map_layers.py`, `admin_basemap_tiles.py`, static admin pages.
3. Phase 4.5 runtime handoff:
   `pretrip_runtime_*`, `runtime_activation_loader.py`, `runtime_load_dry_run.py`.
4. Runtime stream and remote provider drafts:
   `runtime_stream_*`, `runtime_remote_provider_*`.
5. Local-only field data:
   `PdrSample/*`, `trajectory_map.png`, `catographydata/`.

## Exclusion Rules

- Do not mix Phase 4/pretrip implementation into hardware-port commits.
- Do not commit `PdrSample/*` or large local field data unless explicitly requested.
- Do not commit live runtime provider send paths with assistant guardrail work.
- Keep `/safety/*` mutation changes separate from read-only assistant/debug/hardware readiness work.
- Keep local model/Ollama compose separate from deterministic Pi runtime-core.

## Validation

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_phase4_dirty_worktree_cleanup_plan.py
```
