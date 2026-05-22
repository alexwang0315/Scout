from __future__ import annotations

from pathlib import Path


DOC_PATH = Path("docs/admin/scout-phase4-6-real-device-live-run-plan.md")


def read_doc() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


def test_phase46_live_run_plan_is_plan_not_execution() -> None:
    source = read_doc()

    for token in (
        "Status: `plan_ready_not_executed`",
        "它不是 live run 證據，也不是 operator approval",
        "不得執行 `--send`",
        "`--operator-approve-live-send`",
        "`--execute`",
        "`--operator-approve-control-drill`",
    ):
        assert token in source


def test_phase46_live_run_plan_has_ordered_runbook_and_stop_conditions() -> None:
    source = read_doc()

    for token in (
        "## Step 1: Read-Only Preflight",
        "## Step 2: Real-Device Harness Dry-Run",
        "## Step 3: Bounded Live Send",
        "## Step 4: Optional Control Drill",
        "## Step 5: Post-Run Read-Only Capture",
        "Stop if:",
        "final status is not `observing`",
        "incident file count delta is zero",
        "telemetry accepted delta equals sent count",
        "`docs/admin/scout-phase4-6-replay-simulated-walk-plan.md`",
        "`runtime_stream_replay_payloads.py`",
        "`tests/fixtures/routes/scout_260512_field_route.gpx`",
        "`--replay-speed-multiplier 2`",
        "`--replay-speed-multiplier 3`",
        "`$PHASE46_EVIDENCE_DIR/replay-payloads.json`",
        "replace it with the operator-selected real-device payload batch",
    ):
        assert token in source


def test_phase46_live_run_plan_preserves_safety_boundary_and_evidence_rules() -> None:
    source = read_doc()

    for token in (
        "no automatic SOS send",
        "no SMS send",
        "no satellite send",
        "no incident bridge opt-in",
        "no live remote notification send",
        "no Phase 2 Brain writeback",
        "docs/admin/scout-phase4-6-real-device-live-run-evidence.md",
        "It must not include:",
        "raw payload body",
        "secret value",
    ):
        assert token in source
