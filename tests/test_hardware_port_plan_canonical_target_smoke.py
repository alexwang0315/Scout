from pathlib import Path


PLAN_PATH = Path("docs/specs/hardware-port-plan.md")


def test_hardware_port_plan_records_canonical_fixture_target_smoke_status() -> None:
    source = PLAN_PATH.read_text(encoding="utf-8")

    for token in (
        "## Canonical Fixture Target Smoke Status",
        "accepted one canonical fixture observation",
        "moved `observations_processed` from `1` to `2`",
        "moved `checkpoint_hits` from `0` to `1`",
        "hit checkpoint `cp_01`",
        "produced no new incident files",
        "provider `control_allowed=false`",
    ):
        assert token in source


def test_hardware_port_plan_records_step1_runbook_as_completed_next_slice() -> None:
    source = PLAN_PATH.read_text(encoding="utf-8")

    for token in (
        "canonical fixture target smoke",
        "Step 1 deployment runbook freeze",
        "stabilize host-side radio scan provider evidence",
        "stabilize Phase 4 dirty worktree groups",
    ):
        assert token in source
