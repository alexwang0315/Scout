from __future__ import annotations

from pathlib import Path


DOC_PATH = Path("docs/admin/scout-phase4-6-live-replay-debug-projector.md")


def read_doc() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


def test_live_replay_debug_projector_doc_connects_debug_endpoints() -> None:
    source = read_doc()

    for token in (
        "Status: `tooling_ready`",
        "`/admin/debug` 已經整合 `/debug/events`、`/debug/state`、",
        "http://127.0.0.1:9110/admin/debug",
        "http://127.0.0.1:9110/debug/events",
        "http://127.0.0.1:9110/debug/state",
        "http://127.0.0.1:9110/debug/messages",
        "`SCOUT_DEBUG_LOG_PATH=/tmp/scout-phase35-ui-demo.jsonl`",
        "`phase46_live_replay_debug_projector.py`",
        "`debug_session.phase46_live_replay.local_smoke`",
        "`observation_ingested`",
        "`route_progress_evaluated`",
    ):
        assert token in source


def test_live_replay_debug_projector_doc_preserves_boundaries() -> None:
    source = read_doc()

    for token in (
        "read-only",
        "no raw observation payload",
        "no latitude/longitude values",
        "no secret values",
        "no runtime mutation",
        "no stream control mutation",
        "no remote provider send",
        "no hardware control action",
        "no Phase 2 Brain writeback",
        "no automatic SOS/SMS/satellite send",
    ):
        assert token in source
