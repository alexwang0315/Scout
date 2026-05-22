from __future__ import annotations

from pathlib import Path


DOC_PATH = Path("docs/admin/scout-phase4-6-pi-admin-debug-live-replay-evidence.md")


def read_doc() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


def test_pi_admin_debug_live_replay_records_successful_projection() -> None:
    source = read_doc()

    for token in (
        "Status: `passed_pi_admin_debug_live_replay`",
        "`/data/scout/deployments/phase46-pi-admin-debug-live-replay-3x-20260521T051431Z`",
        "`scout-pi-runtime-live`: remained healthy",
        "`scout-pi-phase4-admin`: rebuilt and restarted with debug API support",
        "`http://scout.local:9110/admin/debug`",
        "`/data/scout/admin/debug/runtime-debug-events.jsonl`",
        "unauthenticated `/admin/debug` returned HTTP `401`",
        "`live_harness_status=sent`",
        "`live_harness_sent_count=2`",
        "`projector_event_count=6`",
        "`projector_accepted_delta=2`",
        "`projector_observations_delta=2`",
        "`projector_incident_delta=0`",
        "`admin_debug_event_count=6`",
        "`incident_delta_since_evidence_start=0`",
        "`final_stream_control_status=observing`",
        "`observation_ingested`",
        "`route_progress_evaluated`",
    ):
        assert token in source


def test_pi_admin_debug_live_replay_preserves_boundaries() -> None:
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
    ):
        assert token in source
