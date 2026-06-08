from __future__ import annotations

from pathlib import Path


DOC_PATH = Path("docs/admin/scout-phase4-6-simulated-live-send-3x-evidence.md")


def read_doc() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


def test_phase46_simulated_live_send_3x_records_stop_condition() -> None:
    source = read_doc()

    for token in (
        "Status: `stopped_on_incident_delta`",
        "`/data/scout/deployments/phase46-simulated-live-send-3x-20260521T031347Z`",
        "`operator_approved_simulated_live_send=true`",
        "`replay_speed_multiplier=3.0`",
        "`payload_count_sent_before_stop=1`",
        "`incident_delta=1`",
        "`safety_level_after_stop=L2_CONCERN`",
        "`stream_control_status_after_stop=observing`",
    ):
        assert token in source


def test_phase46_simulated_live_send_3x_preserves_safety_boundary() -> None:
    source = read_doc()

    for token in (
        "no automatic SOS send",
        "no SMS send",
        "no satellite send",
        "no remote provider send",
        "no hardware control action",
        "no stream control mutation",
        "no Phase 2 Brain writeback",
        "no raw payload embedded",
        "no secret value embedded",
        "/admin/debug",
        "/runtime/streams/status",
    ):
        assert token in source
