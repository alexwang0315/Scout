from __future__ import annotations

import json
from pathlib import Path

from scout_runtime_safety_gate_adapters import (
    build_darkness_gate_event,
    build_delay_gate_event,
)
from scout_runtime_safety_reducer import (
    build_phase1_adapter_result,
    reduce_runtime_safety_gate_events,
)
from scout_runtime_safety_state_store import RuntimeSafetyStateStore
from scout_runtime_state_store_projection import (
    build_runtime_safety_state_store_projection,
    runtime_safety_state_store_projection_events,
)


def _decision():
    delay = build_delay_gate_event(
        {
            "event_id": "delay_gate:state-store-projection",
            "source_path": "outputs/runtime/delay.json",
            "delay_minutes": 65,
            "planned_buffer_minutes": -15,
            "camp_deadline_missed": True,
            "route_pressure_review_required": True,
            "route_context": {
                "route_id": "fixture.route",
                "segment_id": "seg.001",
                "checkpoint_id": "camp.001",
                "map_target_ids": ["seg.001", "camp.001"],
            },
            "confidence": "high",
        }
    )
    darkness = build_darkness_gate_event(
        {
            "event_id": "darkness_gate:state-store-projection",
            "source_path": "outputs/runtime/darkness.json",
            "daylight_buffer_minutes": 20,
            "minutes_to_next_safe_objective": 75,
            "emergency_bivy_candidate_distance_m": 450,
            "route_pressure_review_required": True,
            "route_context": {
                "route_id": "fixture.route",
                "segment_id": "seg.001",
                "checkpoint_id": "camp.001",
                "map_target_ids": ["seg.001", "camp.001"],
            },
            "confidence": "high",
        }
    )
    return reduce_runtime_safety_gate_events(
        [delay, darkness],
        source_path="outputs/runtime/reducer.json",
    )


def test_state_store_projection_builds_admin_and_debug_replay_event(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    store = RuntimeSafetyStateStore(project_root / "outputs" / "runtime_state_store")
    decision = _decision()
    adapter = build_phase1_adapter_result(
        decision,
        phase1_adapter_enabled=True,
        human_review_approved=True,
    )
    snapshot = store.save_snapshot(decision, phase1_adapter_result=adapter)

    projection = build_runtime_safety_state_store_projection(
        "fixture.route",
        project_root=project_root,
        state_store_dir_ref="outputs/runtime_state_store",
    )
    events = runtime_safety_state_store_projection_events(
        projection,
        project_id="fixture.route",
        start_sequence=42,
    )
    serialized = json.dumps(projection.model_dump(mode="json"), sort_keys=True)

    assert projection.artifact_kind == "scout_runtime_state_store_replay_projection"
    assert projection.status == "ready"
    assert projection.surface_targets == ["/admin/debug", "/admin"]
    assert projection.source_provider == "scout_runtime_safety_state_store"
    assert projection.source_path.endswith("runtime_safety_state_store_index.json")
    assert projection.sha256
    assert projection.snapshot_count == 1
    assert projection.latest_snapshot_id == snapshot.snapshot_id
    assert projection.latest_selected_gate_id == "darkness_gate"
    assert projection.latest_snapshot is not None
    assert projection.latest_snapshot.phase1_adapter_status == "transition_request_prepared"
    assert projection.boundary.runtime_safety_truth is False
    assert projection.boundary.phase1_l0_l4_state_mutated is False
    assert projection.boundary.safety_api_called is False
    assert projection.privacy["raw_health_payload_shared"] is False
    assert projection.privacy["precise_timestamps_shared"] is False
    assert len(events) == 1
    assert events[0]["kind"] == "runtime_safety_state_store_snapshot"
    assert events[0]["sequence"] == 42
    assert events[0]["payload"]["runtime_safety_truth"] is False
    assert events[0]["payload"]["boundary"]["safety_api_called"] is False
    assert events[0]["payload"]["snapshot_id"] == snapshot.snapshot_id
    assert events[0]["payload"]["map_target_ids"] == ["seg.001", "camp.001"]
    assert "/admin" in events[0]["payload"]["surface_targets"]
    assert "/admin/debug" in events[0]["payload"]["surface_targets"]
    assert "/safety/" not in serialized
    assert "raw_payload" not in serialized
    assert '"timestamp":' not in serialized


def test_state_store_projection_reports_missing_without_creating_store(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"

    projection = build_runtime_safety_state_store_projection(
        "fixture.route",
        project_root=project_root,
        state_store_dir_ref="outputs/missing_state_store",
    )

    assert projection.status == "missing"
    assert projection.snapshot_count == 0
    assert projection.boundary.runtime_safety_truth is False
    assert not (project_root / "outputs" / "missing_state_store").exists()
