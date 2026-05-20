from pathlib import Path


PLAN_PATH = Path("docs/specs/hardware-port-plan.md")


def test_hardware_port_plan_records_step1_runbook_status() -> None:
    source = PLAN_PATH.read_text(encoding="utf-8")

    for token in (
        "## Step 1 Deployment Runbook Status",
        "scout-machine-step1-deployment-runbook.md",
        "scout-machine-step1-evidence-index.md",
        "`/data/scout/deployments/20260520T031746Z`",
        "`observations_processed=2`",
        "`checkpoint_hits=1`",
        "`safety_level=L0_NORMAL`",
    ):
        assert token in source


def test_hardware_port_plan_next_slice_is_radio_scan_or_phase4_cleanup() -> None:
    source = PLAN_PATH.read_text(encoding="utf-8")

    for token in (
        "Step 1 deployment runbook freeze",
        "stabilize host-side radio scan provider evidence",
        "separate read-only provider slice",
        "stabilize Phase 4 dirty worktree groups",
    ):
        assert token in source
