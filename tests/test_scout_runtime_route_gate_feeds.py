from __future__ import annotations

import json
from pathlib import Path

import pytest

from scout_runtime_route_gate_feeds import (
    RuntimeRouteGateFeedBoundary,
    RuntimeRouteGateFeedInput,
    build_route_gate_events_from_progress_feed,
    load_route_gate_feed_result,
    write_route_gate_event_batch,
    write_route_gate_feed_result,
)
from scout_runtime_safety_reducer import reduce_runtime_safety_gate_events


def _route_feed_payload() -> dict:
    return {
        "source_provider": "local_route_progress_replay_fixture",
        "source_path": "outputs/runtime/route_gate_feed_fixture.json",
        "route_id": "fixture.route",
        "segment_timings": [
            {
                "segment_id": "seg.001",
                "from_checkpoint_id": "cp.start",
                "to_checkpoint_id": "camp.001",
                "distance_m": 3200,
                "reference_p50_minutes": 55,
                "reference_p75_minutes": 70,
                "reference_max_minutes": 105,
                "map_target_ids": ["seg.001", "camp.001"],
                "source_ref": "outputs/reference_segment_timing.json#seg.001",
            }
        ],
        "planned_timeline": [
            {
                "checkpoint_id": "camp.001",
                "checkpoint_kind": "camp",
                "segment_id": "seg.001",
                "planned_arrival_offset_min": 150,
                "latest_arrival_offset_min": 180,
                "map_target_ids": ["camp.001", "seg.001"],
                "source_ref": "outputs/planned_timeline.json#camp.001",
            }
        ],
        "progress_frames": [
            {
                "frame_id": "frame.001",
                "route_id": "fixture.route",
                "observed_at_offset_s": 7200,
                "elapsed_route_minutes": 130,
                "segment_id": "seg.001",
                "target_checkpoint_id": "camp.001",
                "elapsed_segment_minutes": 110,
                "observed_segment_distance_m": 1850,
                "estimated_minutes_to_target": 65,
                "daylight_buffer_minutes": 35,
                "minutes_to_next_safe_objective": 70,
                "emergency_bivy_candidate_distance_m": 450,
                "route_pressure_review_required": True,
                "confidence": "high",
                "evidence_refs": ["outputs/live_navigation_snapshot.reviewed.json"],
            }
        ],
        "data_quality": {
            "confidence": "high",
            "signal_count": 4,
            "live_network_calls_made": False,
        },
    }


def test_route_gate_feed_builds_local_replay_pace_delay_darkness_events() -> None:
    result = build_route_gate_events_from_progress_feed(_route_feed_payload())
    reducer = reduce_runtime_safety_gate_events(result.event_batch)
    serialized = json.dumps(result.model_dump(mode="json"), sort_keys=True)
    events_by_gate = {event.gate_id: event for event in result.events}

    assert result.artifact_kind == "scout_runtime_route_gate_feed_result"
    assert result.frame_count == 1
    assert result.event_count == 3
    assert result.generated_gate_ids == ["pace_gate", "delay_gate", "darkness_gate"]
    assert result.boundary.local_replay_only is True
    assert result.boundary.pi_hardware_required is False
    assert result.boundary.runtime_safety_truth is False
    assert result.boundary.phase1_l0_l4_state_mutated is False
    assert result.boundary.safety_api_called is False
    assert result.data_quality.live_network_calls_made is False

    pace = events_by_gate["pace_gate"]
    delay = events_by_gate["delay_gate"]
    darkness = events_by_gate["darkness_gate"]
    assert pace.severity == "retreat_review"
    assert pace.route_context.segment_id == "seg.001"
    assert pace.route_context.checkpoint_id == "camp.001"
    assert "seg.001" in pace.route_context.map_target_ids
    assert delay.severity == "retreat_review"
    assert delay.gate_payload["camp_deadline_missed"] is True
    assert darkness.severity == "alert_review"
    assert result.event_batch.event_count == 3
    assert reducer.selected_gate_id == "darkness_gate"
    assert reducer.ln_level_candidate == "L4_ALERT_REVIEW"
    assert "/safety/" not in serialized
    assert "raw_payload" not in serialized
    assert "heartRateData" not in serialized


def test_route_gate_feed_skips_missing_optional_delay_and_darkness_inputs() -> None:
    payload = _route_feed_payload()
    frame = payload["progress_frames"][0]
    frame.pop("target_checkpoint_id")
    frame.pop("estimated_minutes_to_target")
    frame.pop("daylight_buffer_minutes")
    frame.pop("minutes_to_next_safe_objective")

    result = build_route_gate_events_from_progress_feed(payload)

    assert result.event_count == 1
    assert result.generated_gate_ids == ["pace_gate"]
    assert result.events[0].gate_id == "pace_gate"
    assert "frame.001:target_checkpoint_id" in result.data_quality.missing_signal_names
    assert "frame.001:darkness_inputs" in result.data_quality.missing_signal_names


def test_route_gate_feed_rejects_missing_segment_timing() -> None:
    payload = _route_feed_payload()
    payload["progress_frames"][0]["segment_id"] = "seg.missing"

    with pytest.raises(ValueError, match="missing segment timing"):
        RuntimeRouteGateFeedInput.model_validate(payload)


def test_route_gate_feed_rejects_raw_payload_fields() -> None:
    payload = _route_feed_payload()
    payload["progress_frames"][0]["raw_payload"] = {"coordinates": []}

    with pytest.raises(ValueError):
        RuntimeRouteGateFeedInput.model_validate(payload)


def test_route_gate_feed_boundary_rejects_pi_hardware_requirement() -> None:
    with pytest.raises(ValueError, match="cannot require Pi hardware"):
        RuntimeRouteGateFeedBoundary(pi_hardware_required=True)


def test_route_gate_feed_result_and_batch_write_round_trip(tmp_path: Path) -> None:
    result = build_route_gate_events_from_progress_feed(_route_feed_payload())
    result_path = tmp_path / "route_gate_feed_result.json"
    batch_path = tmp_path / "runtime_safety_gate_event_batch.json"

    written_result = write_route_gate_feed_result(result, result_path)
    loaded_result = load_route_gate_feed_result(result_path)
    written_batch = write_route_gate_event_batch(result, batch_path)

    assert written_result == loaded_result
    assert written_batch.event_count == 3
    assert json.loads(batch_path.read_text(encoding="utf-8"))["artifact_kind"] == (
        "scout_runtime_safety_gate_event_batch"
    )
