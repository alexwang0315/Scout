from __future__ import annotations

from pathlib import Path


DOC_PATH = Path("docs/admin/scout-phase4-6-replay-simulated-walk-plan.md")


def read_doc() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


def test_replay_simulated_walk_plan_uses_prerecorded_apple_watch_before_true_device() -> None:
    source = read_doc()

    for token in (
        "Status: `plan_ready_not_executed`",
        "預錄 Apple Watch 軌跡回放",
        "加速 2x 或 3x 回放",
        "`tests/fixtures/routes/scout_260512_field_route.gpx`",
        "`runtime_stream_replay_payloads.py`",
        "`runtime_stream_real_device_harness.py`",
        "`--replay-speed-multiplier 2`",
        "`--replay-speed-multiplier 3`",
        "`replay_timing.send_delays_ms`",
        "10Hz backpressure",
        "100ms",
        "不先建立 HTTPS server",
        "不先處理電池、storage、外殼",
    ):
        assert token in source


def test_replay_simulated_walk_plan_preserves_live_safety_boundary() -> None:
    source = read_doc()

    for token in (
        "no live send in this slice",
        "no `scout.local` network call",
        "no automatic SOS send",
        "no SMS send",
        "no satellite send",
        "no Phase 2 Brain writeback",
        "raw payload batch 可以存在 evidence directory",
        "summary artifact 不嵌入 raw payload",
    ):
        assert token in source
