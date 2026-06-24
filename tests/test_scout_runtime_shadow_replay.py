from __future__ import annotations

import json
import platform
from pathlib import Path

import pytest

from scout_runtime_shadow_replay import (
    RuntimeShadowReplayBoundary,
    RuntimeShadowReplayInput,
    load_runtime_shadow_replay_result,
    run_runtime_shadow_replay,
)


def _route_feed_payload() -> dict:
    return {
        "source_provider": "macos_shadow_replay_fixture",
        "source_path": "fixtures/runtime/route_gate_feed_fixture.json",
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
                "source_ref": "fixtures/reference_segment_timing.json#seg.001",
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
                "source_ref": "fixtures/planned_timeline.json#camp.001",
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
                "evidence_refs": ["fixtures/live_navigation_snapshot.reviewed.json"],
            }
        ],
        "data_quality": {
            "confidence": "high",
            "signal_count": 4,
            "live_network_calls_made": False,
        },
    }


def test_shadow_replay_runs_route_feed_to_reducer_adapter_and_state_store(
    tmp_path: Path,
) -> None:
    result = run_runtime_shadow_replay(
        {
            "source_provider": "macos_pytest_shadow_replay",
            "source_path": "fixtures/runtime/shadow_replay_input.json",
            "route_gate_feed": _route_feed_payload(),
            "phase1_adapter_enabled": True,
            "human_review_approved": True,
        },
        output_dir=tmp_path / "shadow",
    )
    loaded = load_runtime_shadow_replay_result(
        tmp_path / "shadow" / "runtime_shadow_replay_result.json"
    )
    serialized = json.dumps(result.model_dump(mode="json"), sort_keys=True)

    assert loaded == result
    assert result.artifact_kind == "scout_runtime_shadow_replay_result"
    assert result.local_platform == platform.system()
    assert result.route_gate_event_count == 3
    assert result.additional_gate_event_count == 0
    assert result.event_count == 3
    assert result.selected_gate_id == "darkness_gate"
    assert result.ln_level_candidate == "L4_ALERT_REVIEW"
    assert result.phase1_adapter_result.status == "transition_request_prepared"
    assert result.phase1_adapter_result.boundary.phase1_l0_l4_state_mutated is False
    assert result.state_snapshot.reducer_sha256 == result.reducer_decision.sha256
    assert result.state_store_index.latest_snapshot_id == result.state_snapshot.snapshot_id
    assert result.state_snapshot.route_id == "fixture.route"
    assert result.boundary.pi_hardware_required is False
    assert result.boundary.hardware_driver_invoked is False
    assert result.boundary.live_network_calls_made is False
    assert result.boundary.safety_api_called is False
    assert result.boundary.phase1_l0_l4_state_mutated is False
    assert result.data_quality.live_network_calls_made is False
    assert (tmp_path / "shadow" / result.artifact_refs.event_batch_path).exists()
    assert (tmp_path / "shadow" / result.artifact_refs.reducer_decision_path).exists()
    assert (tmp_path / "shadow" / result.artifact_refs.phase1_adapter_result_path).exists()
    assert (
        tmp_path
        / "shadow"
        / "runtime_safety_state_store"
        / result.artifact_refs.state_snapshot_path
    ).exists()
    assert "/safety/" not in serialized
    assert "raw_payload" not in serialized
    assert "coordinates" not in serialized
    assert '"timestamp":' not in serialized


def test_shadow_replay_can_record_blocked_adapter_candidate(
    tmp_path: Path,
) -> None:
    result = run_runtime_shadow_replay(
        {
            "route_gate_feed": _route_feed_payload(),
            "phase1_adapter_enabled": False,
            "human_review_approved": False,
        },
        output_dir=tmp_path / "shadow",
    )

    assert result.phase1_adapter_result.status == "blocked_feature_flag_disabled"
    assert result.phase1_adapter_result.transition_request_prepared is False
    assert result.state_snapshot.phase1_adapter_status == (
        "blocked_feature_flag_disabled"
    )
    assert result.state_store_index.snapshot_count == 1


def test_shadow_replay_rejects_empty_input() -> None:
    with pytest.raises(ValueError, match="requires route gate feed or gate events"):
        RuntimeShadowReplayInput.model_validate({})


def test_shadow_replay_rejects_hardware_boundary() -> None:
    with pytest.raises(ValueError, match="cannot require or invoke Scout hardware"):
        RuntimeShadowReplayBoundary(pi_hardware_required=True)


def test_shadow_replay_rejects_raw_payload_fields() -> None:
    payload = {
        "route_gate_feed": _route_feed_payload(),
    }
    payload["route_gate_feed"]["progress_frames"][0]["raw_payload"] = {
        "coordinates": [[0, 0]]
    }

    with pytest.raises(ValueError):
        RuntimeShadowReplayInput.model_validate(payload)
