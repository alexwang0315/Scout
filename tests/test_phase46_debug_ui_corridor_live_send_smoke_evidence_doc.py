from __future__ import annotations

from pathlib import Path


DOC_PATH = Path(
    "docs/admin/scout-phase4-6-debug-ui-corridor-live-send-smoke-evidence.md"
)


def read_doc() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


def test_phase46_debug_ui_corridor_smoke_records_visible_projection() -> None:
    source = read_doc()

    for token in (
        "Status: `passed_debug_projection_visible`",
        "`/data/scout/deployments/phase46-debug-ui-corridor-live-send-3x-20260521T042829Z`",
        "`http://127.0.0.1:9110/admin/debug?tab=api`",
        "`watch.replay.normal_climb_corridor.debug_smoke2`",
        "`live_harness_sent_count=2`",
        "`projector_event_count=6`",
        "`projector_accepted_delta=2`",
        "`projector_observations_delta=2`",
        "`incident_delta=0`",
        "`final_stream_control_status=observing`",
    ):
        assert token in source


def test_phase46_debug_ui_corridor_smoke_preserves_live_boundaries() -> None:
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
        "/debug/events",
        "/debug/state",
        "/debug/messages",
    ):
        assert token in source
