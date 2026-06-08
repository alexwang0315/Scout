from __future__ import annotations

from pathlib import Path

from spatial_imprint_debug_projection import (
    load_spatial_imprint_debug_events,
    spatial_imprint_store_to_debug_events,
    spatial_imprint_trigger_report_to_debug_events,
)
from spatial_imprint_store import plant_spatial_imprint, spatial_imprint_set_from_store
from spatial_imprint_trigger import evaluate_spatial_imprints
from tests.test_spatial_imprint_trigger import _context, _imprint


def test_store_audit_records_project_to_debug_events(tmp_path: Path) -> None:
    store_path = tmp_path / "runtime-spatial-imprints.json"
    store = plant_spatial_imprint(
        store_path,
        _imprint(
            imprint_id="spatial_imprint.debug.store.001",
            planting_source="operator_runtime",
        ),
        trip_id="chilai_nanhua_day1",
        authorized_by="leader.alex",
        planted_at="2026-05-27T08:00:00Z",
        reason="Leader planted a temporary cue.",
    )

    events = spatial_imprint_store_to_debug_events(
        store,
        source_path=str(store_path),
        sequence_offset=20,
    )

    assert len(events) == 1
    event = events[0]
    assert event.sequence == 21
    assert event.kind == "spatial_imprint_store_updated"
    assert event.subject_ref == "spatial_imprint.debug.store.001"
    assert event.payload["action"] == "planted"
    assert event.payload["imprint_label"] == "前方大崩壁"
    assert event.payload["boundary"]["live_safety_api_calls_allowed"] is False
    assert event.payload["runtime_safety_truth"] is False


def test_trigger_dry_run_report_projects_predicate_details(tmp_path: Path) -> None:
    report = evaluate_spatial_imprints(
        spatial_imprint_set_from_store(
            plant_spatial_imprint(
                tmp_path / "runtime-spatial-imprints.json",
                _imprint(
                    imprint_id="spatial_imprint.debug.trigger.001",
                    planting_source="operator_runtime",
                ),
                trip_id="chilai_nanhua_day1",
                authorized_by="leader.alex",
            )
        ),
        _context(),
    )

    events = spatial_imprint_trigger_report_to_debug_events(
        report,
        source_path="outputs/spatial-imprint-trigger-report.json",
        sequence_offset=30,
    )

    assert len(events) == 1
    event = events[0]
    assert event.sequence == 31
    assert event.kind == "spatial_imprint_trigger_event"
    assert event.severity == "warning"
    assert event.payload["status"] == "triggered"
    assert "route_progress_window" in event.payload["matched_predicates"]
    assert event.payload["queued_payload"]["payload_type"] == "voice_cue"
    assert event.payload["boundary"]["phase1_safety_mutation_allowed"] is False


def test_loader_merges_store_and_trigger_report_paths(tmp_path: Path) -> None:
    store_path = tmp_path / "runtime-spatial-imprints.json"
    report_path = tmp_path / "spatial-imprint-trigger-report.json"
    store = plant_spatial_imprint(
        store_path,
        _imprint(
            imprint_id="spatial_imprint.debug.loader.001",
            planting_source="operator_runtime",
        ),
        trip_id="chilai_nanhua_day1",
        authorized_by="leader.alex",
        planted_at="2026-05-27T08:00:00Z",
    )
    report = evaluate_spatial_imprints(spatial_imprint_set_from_store(store), _context())
    report_path.write_text(report.model_dump_json(), encoding="utf-8")

    events = load_spatial_imprint_debug_events(
        store_path=store_path,
        trigger_report_path=report_path,
        sequence_offset=40,
    )

    assert [event.kind for event in events] == [
        "spatial_imprint_store_updated",
        "spatial_imprint_trigger_event",
    ]
    assert [event.sequence for event in events] == [41, 42]
