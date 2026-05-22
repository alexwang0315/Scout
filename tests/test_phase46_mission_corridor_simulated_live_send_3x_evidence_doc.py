from __future__ import annotations

from pathlib import Path


DOC_PATH = Path(
    "docs/admin/scout-phase4-6-mission-corridor-simulated-live-send-3x-evidence.md"
)


def read_doc() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


def test_mission_corridor_simulated_live_send_3x_records_successful_counters() -> None:
    source = read_doc()

    for token in (
        "Status: `passed_no_new_incident`",
        "`/data/scout/deployments/phase46-mission-corridor-live-send-3x-20260521T032239Z`",
        "`prevalidation_status=passed`",
        "`prevalidation_incident_count=0`",
        "`prevalidation_checkpoint_hit_count=5`",
        "`live_harness_status=sent`",
        "`live_harness_sent_count=5`",
        "`http_accepted_delta=5`",
        "`observations_processed_delta=5`",
        "`incident_delta=0`",
        "`stream_control_status_after=observing`",
    ):
        assert token in source


def test_mission_corridor_simulated_live_send_3x_preserves_boundaries() -> None:
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
        "`scout_260512` as field regression evidence",
        "/runtime/streams/status",
    ):
        assert token in source
