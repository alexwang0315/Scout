from __future__ import annotations

from pathlib import Path


DOC_PATH = Path("docs/admin/scout-phase4-6-pi-admin-debug-topology.md")


def read_doc() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


def test_pi_admin_debug_topology_routes_operator_to_scout_local() -> None:
    source = read_doc()

    for token in (
        "Status: `admin_debug_topology_ready`",
        "scout.local:9099 runtime stream ingest",
        "Pi-side projector writes shared debug JSONL",
        "scout.local:9110/admin/debug",
        "`SCOUT_DEBUG_API_ENABLED=true`",
        "`SCOUT_DEBUG_LOG_PATH=/data/scout/admin/debug/runtime-debug-events.jsonl`",
        "`GET /admin/debug`",
        "`GET /debug/events`",
        "`POST /debug/clear`",
        "docker exec scout-pi-phase4-admin python /app/phase46_live_replay_debug_projector.py",
        "http://172.21.0.1:9099/runtime/streams/status",
        "`/data/scout/admin/secrets/phase4-admin-token`",
        "token value is never embedded",
    ):
        assert token in source


def test_pi_admin_debug_topology_preserves_live_boundaries() -> None:
    source = read_doc()

    for token in (
        "does not clear runtime state",
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
