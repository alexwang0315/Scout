from __future__ import annotations

import json
from pathlib import Path

import pytest

from scout_runtime_safety_gate_adapters import (
    build_darkness_gate_event,
    build_delay_gate_event,
)
from scout_runtime_safety_reducer import (
    build_phase1_adapter_result,
    reduce_runtime_safety_gate_events,
)
from scout_runtime_safety_state_store import (
    RuntimeSafetyStateStore,
    RuntimeSafetyStateStoreBoundary,
    build_runtime_safety_state_snapshot,
    build_runtime_safety_state_store_index,
    load_runtime_safety_state_snapshot,
    write_runtime_safety_state_snapshot,
    write_runtime_safety_state_store_index,
)


def _decision(route_id: str = "fixture.route", suffix: str = "001"):
    delay = build_delay_gate_event(
        {
            "event_id": f"delay_gate:{suffix}",
            "source_path": f"outputs/runtime/delay-{suffix}.json",
            "delay_minutes": 65,
            "planned_buffer_minutes": -15,
            "camp_deadline_missed": True,
            "route_pressure_review_required": True,
            "route_context": {
                "route_id": route_id,
                "segment_id": f"seg.{suffix}",
                "checkpoint_id": f"camp.{suffix}",
                "map_target_ids": [f"seg.{suffix}", f"camp.{suffix}"],
                "estimated_minutes_to_next_checkpoint": 70,
                "daylight_buffer_minutes": 20,
            },
            "evidence_refs": [f"outputs/planned_timeline.json#camp.{suffix}"],
            "confidence": "high",
        }
    )
    darkness = build_darkness_gate_event(
        {
            "event_id": f"darkness_gate:{suffix}",
            "source_path": f"outputs/runtime/darkness-{suffix}.json",
            "daylight_buffer_minutes": 20,
            "minutes_to_next_safe_objective": 75,
            "emergency_bivy_candidate_distance_m": 450,
            "route_pressure_review_required": True,
            "route_context": {
                "route_id": route_id,
                "segment_id": f"seg.{suffix}",
                "checkpoint_id": f"camp.{suffix}",
                "map_target_ids": [f"seg.{suffix}", f"camp.{suffix}"],
                "estimated_minutes_to_next_checkpoint": 70,
                "daylight_buffer_minutes": 20,
            },
            "evidence_refs": [f"outputs/daylight_window.json#seg.{suffix}"],
            "confidence": "high",
        }
    )
    return reduce_runtime_safety_gate_events(
        [delay, darkness],
        source_path=f"outputs/runtime/reducer-{suffix}.json",
    )


def test_state_store_persists_reducer_snapshot_and_rebuildable_index(
    tmp_path: Path,
) -> None:
    decision = _decision()
    adapter = build_phase1_adapter_result(
        decision,
        phase1_adapter_enabled=True,
        human_review_approved=True,
    )
    store = RuntimeSafetyStateStore(tmp_path / "runtime_safety_state")

    snapshot = store.save_snapshot(decision, phase1_adapter_result=adapter)
    index = store.load_index()
    serialized = json.dumps(snapshot.model_dump(mode="json"), sort_keys=True)

    assert snapshot.artifact_kind == "scout_runtime_safety_state_snapshot"
    assert snapshot.reducer_sha256 == decision.sha256
    assert snapshot.phase1_adapter_sha256 == adapter.sha256
    assert snapshot.route_id == "fixture.route"
    assert snapshot.segment_id == "seg.001"
    assert snapshot.checkpoint_id == "camp.001"
    assert snapshot.selected_gate_id == "darkness_gate"
    assert snapshot.ln_level_candidate == "L4_ALERT_REVIEW"
    assert snapshot.boundary.runtime_safety_truth is False
    assert snapshot.boundary.phase1_l0_l4_state_mutated is False
    assert snapshot.boundary.safety_api_called is False
    assert snapshot.phase1_adapter_result is not None
    assert snapshot.phase1_adapter_result.boundary.phase1_l0_l4_state_mutated is False
    assert store.exists(snapshot.snapshot_id)
    assert index.snapshot_count == 1
    assert index.latest_snapshot_id == snapshot.snapshot_id
    assert index.latest_ln_level_candidate == "L4_ALERT_REVIEW"
    assert index.boundary.runtime_safety_truth is False
    assert "seg.001" in index.snapshots[0].map_target_ids
    assert "/safety/" not in serialized
    assert "raw_payload" not in serialized
    assert "coordinates" not in serialized
    assert '"timestamp":' not in serialized
    assert '"timestamps":' not in serialized


def test_state_store_is_idempotent_for_same_reducer_and_adapter(
    tmp_path: Path,
) -> None:
    decision = _decision()
    adapter = build_phase1_adapter_result(
        decision,
        phase1_adapter_enabled=True,
        human_review_approved=True,
    )
    store = RuntimeSafetyStateStore(tmp_path / "runtime_safety_state")

    first = store.save_snapshot(decision, phase1_adapter_result=adapter)
    second = store.save_snapshot(decision, phase1_adapter_result=adapter)

    assert second.snapshot_id == first.snapshot_id
    assert second.sha256 == first.sha256
    assert len(store.list_snapshots()) == 1
    assert store.load_index().snapshot_count == 1


def test_state_store_lists_latest_by_route(tmp_path: Path) -> None:
    store = RuntimeSafetyStateStore(tmp_path / "runtime_safety_state")
    route_a = store.save_snapshot(_decision(route_id="route.a", suffix="001"))
    route_b = store.save_snapshot(_decision(route_id="route.b", suffix="002"))

    assert [item.snapshot_id for item in store.list_snapshots(route_id="route.a")] == [
        route_a.snapshot_id
    ]
    assert store.latest_snapshot(route_id="route.b") == route_b
    assert store.latest_snapshot(route_id="route.missing") is None


def test_state_snapshot_and_index_write_round_trip(tmp_path: Path) -> None:
    decision = _decision()
    snapshot = build_runtime_safety_state_snapshot(decision)
    index = build_runtime_safety_state_store_index([snapshot])
    snapshot_path = tmp_path / "snapshot.json"
    index_path = tmp_path / "index.json"

    written_snapshot = write_runtime_safety_state_snapshot(snapshot, snapshot_path)
    loaded_snapshot = load_runtime_safety_state_snapshot(snapshot_path)
    written_index = write_runtime_safety_state_store_index(index, index_path)

    assert written_snapshot == loaded_snapshot
    assert written_index.snapshot_count == 1
    assert written_index.latest_snapshot_id == snapshot.snapshot_id


def test_state_snapshot_rejects_adapter_for_different_reducer() -> None:
    first = _decision(route_id="route.a", suffix="001")
    second = _decision(route_id="route.b", suffix="002")
    adapter_for_second = build_phase1_adapter_result(
        second,
        phase1_adapter_enabled=True,
        human_review_approved=True,
    )

    with pytest.raises(ValueError, match="adapter result must reference"):
        build_runtime_safety_state_snapshot(
            first,
            phase1_adapter_result=adapter_for_second,
        )


def test_state_store_boundary_rejects_runtime_mutation_claims() -> None:
    with pytest.raises(ValueError, match="Phase 1 truth"):
        RuntimeSafetyStateStoreBoundary(phase1_l0_l4_state_mutated=True)
