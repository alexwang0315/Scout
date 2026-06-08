from __future__ import annotations

from pathlib import Path


DOC_PATH = Path("docs/admin/scout-phase4-6-tooling-milestone-closeout.md")


def read_doc() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


def test_phase46_tooling_closeout_marks_pi_admin_debug_live_replay_passed() -> None:
    source = read_doc()

    for token in (
        "Status: `tooling_closed_pi_admin_debug_live_replay_passed`",
        "mission-corridor simulated live-send 已經在",
        "`scout.local` 驗證",
        "`docs/admin/scout-phase4-6-pi-admin-debug-live-replay-evidence.md`",
        "`http://scout.local:9110/admin/debug`",
        "`/data/scout/deployments/phase46-pi-admin-debug-live-replay-3x-20260521T051431Z`",
        "`live_harness_sent_count=2`",
        "`projector_event_count=6`",
        "`projector_accepted_delta=2`",
        "`projector_observations_delta=2`",
        "`projector_incident_delta=0`",
        "`admin_debug_event_count=6`",
        "`incident_delta_since_evidence_start=0`",
        "no real Apple Watch/mobile live stream run",
        "no HTTPS mobile endpoint",
        "The next milestone should perform a separate true-device run",
    ):
        assert token in source


def test_phase46_tooling_closeout_lists_tools_and_safety_boundary() -> None:
    source = read_doc()

    for token in (
        "`runtime_stream_device_identity.py`",
        "`runtime_stream_replay_payloads.py`",
        "`runtime_stream_real_device_harness.py`",
        "`runtime_stream_real_device_policy_drill.py`",
        "`runtime_stream_real_device_control_drill.py`",
        "`phase46_live_replay_debug_projector.py`",
        "`docs/admin/scout-phase4-6-live-replay-debug-projector.md`",
        "`docs/admin/scout-phase4-6-pi-admin-debug-topology.md`",
        "2x/3x accelerated",
        "`--replay-speed-multiplier 2`",
        "`docs/admin/scout-phase4-6-replay-simulated-walk-plan.md`",
        "`/data/scout/admin/debug/runtime-debug-events.jsonl`",
        "no automatic SOS send",
        "no SMS send",
        "no satellite send",
        "no incident bridge opt-in or live remote notification send",
        "no Phase 2 Brain writeback",
        "no raw payload or secret value persistence",
    ):
        assert token in source
