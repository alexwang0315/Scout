from pathlib import Path


PLAN_PATH = Path("docs/admin/phase4-dirty-worktree-cleanup-plan.md")


def test_phase4_dirty_worktree_cleanup_plan_names_commit_groups() -> None:
    source = PLAN_PATH.read_text(encoding="utf-8")

    for token in (
        "Phase 4 planning core",
        "Phase 4 admin and map UI",
        "Phase 1 after-action UI",
        "Phase 4.5 runtime handoff",
        "Runtime stream, admission, and remote provider drafts",
        "Local-only field data",
    ):
        assert token in source


def test_phase4_dirty_worktree_cleanup_plan_keeps_hardware_port_separate() -> None:
    source = PLAN_PATH.read_text(encoding="utf-8")

    for token in (
        "Do not mix Phase 4/pretrip implementation into hardware-port commits",
        "Do not commit `PdrSample/*`",
        "Keep `/safety/*` mutation changes separate",
        "Keep local model/Ollama compose separate from deterministic Pi runtime-core",
        "Keep after-action UI cleanup separate from Phase 4 pretrip planning UI",
        "Keep runtime stream/admission commits opt-in, secret-gated",
    ):
        assert token in source


def test_phase4_dirty_worktree_cleanup_plan_records_batch_1_result() -> None:
    source = PLAN_PATH.read_text(encoding="utf-8")

    for token in (
        "## Batch 1 Result",
        "did not stage the Phase 4 dirty worktree flood",
        "`runtime_stream_*` and `runtime_remote_provider_*`",
        "`docker-compose.pi.ai.yml` remains outside deterministic Docker Step 1",
        "Do not combine it with runtime stream/live provider send paths",
    ):
        assert token in source


def test_phase4_dirty_worktree_cleanup_plan_records_batch_2_order() -> None:
    source = PLAN_PATH.read_text(encoding="utf-8")

    for token in (
        "## Batch 2 Ready State",
        "Phase 4 planning core models and fixture outputs",
        "Phase 4 admin/map UI and static pretrip page",
        "Phase 1 after-action UI",
        "Runtime stream/admission opt-in contract",
        "Runtime remote provider live-send drafts",
        "finish and commit Phase 4 planning/admin groups before touching runtime stream/admission",
        "do not stage `PdrSample/*`, `catographydata/`, `trajectory_map.png`, or `install_skills.sh`",
    ):
        assert token in source
