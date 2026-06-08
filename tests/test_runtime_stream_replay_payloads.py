from __future__ import annotations

import json
from pathlib import Path

from runtime_stream_replay_payloads import (
    build_replay_payload_batch,
    build_replay_payload_batch_cli,
)


ROOT = Path(__file__).resolve().parents[1]
FIELD_ROUTE = ROOT / "tests" / "fixtures" / "routes" / "scout_260512_field_route.gpx"


def test_build_replay_payload_batch_from_prerecorded_apple_watch_gpx(tmp_path: Path) -> None:
    payloads_path = tmp_path / "payloads.json"
    summary_path = tmp_path / "summary.json"

    summary = build_replay_payload_batch(
        route_path=FIELD_ROUTE,
        payloads_output_path=payloads_path,
        summary_output_path=summary_path,
        source_id="runtime_source.apple_watch.v0",
        source_kind="apple_watch",
        device_id="watch.replay.260512",
        sample_stride=250,
        max_points=5,
        replay_speed_multiplier=2.0,
    )
    payloads = json.loads(payloads_path.read_text(encoding="utf-8"))
    serialized_summary = summary_path.read_text(encoding="utf-8")

    assert summary.status == "replay_payload_batch_ready"
    assert summary.route_point_count == 1568
    assert summary.payload_count == 5
    assert summary.sample_stride == 250
    assert summary.source_id == "runtime_source.apple_watch.v0"
    assert summary.source_kind == "apple_watch"
    assert summary.device_id == "watch.replay.260512"
    assert summary.payloads_output_path == str(payloads_path)
    assert summary.replay_speed_multiplier == 2.0
    assert summary.send_delay_count == 5
    assert len(summary.send_delays_ms) == 5
    assert summary.send_delays_ms[0] == 0
    assert all(delay >= 100 for delay in summary.send_delays_ms[1:])
    assert summary.original_duration_ms >= summary.accelerated_duration_ms
    assert summary.accelerated_duration_ms > 0
    assert summary.boundary.live_send_performed is False
    assert summary.boundary.https_server_created is False
    assert summary.boundary.portable_hardware_validated is False
    assert summary.boundary.phase2_writeback_allowed is False
    assert payloads["replay_timing"]["timing_source"] == "prerecorded_observed_at"
    assert payloads["replay_timing"]["replay_speed_multiplier"] == 2.0
    assert payloads["replay_timing"]["send_delays_ms"] == summary.send_delays_ms
    assert payloads["payloads"][0]["source"] == "apple_watch_replay"
    assert "locationLatitude" in payloads["payloads"][0]
    assert "locationLongitude" in payloads["payloads"][0]
    assert "locationLatitude" not in serialized_summary
    assert "locationLongitude" not in serialized_summary
    assert "watch.replay.260512" in serialized_summary


def test_replay_payload_batch_cli_writes_payload_and_summary(tmp_path: Path) -> None:
    payloads_path = tmp_path / "payloads.json"
    summary_path = tmp_path / "summary.json"

    exit_code, summary = build_replay_payload_batch_cli(
        [
            "--route",
            str(FIELD_ROUTE),
            "--payloads-output",
            str(payloads_path),
            "--summary-output",
            str(summary_path),
            "--device-id",
            "watch.replay.260512",
            "--sample-stride",
            "300",
            "--max-points",
            "4",
            "--replay-speed-multiplier",
            "3",
        ]
    )

    assert exit_code == 0
    assert summary.payload_count == 4
    assert summary.replay_speed_multiplier == 3.0
    assert payloads_path.exists()
    assert summary_path.exists()
