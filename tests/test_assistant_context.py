from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

from admin_assistant_context import build_admin_assistant_context
from assistant_context import assistant_source_refs_from_context, create_assistant_context_resolver
from assistant_models import ScoutAssistantQuery
from debug_assistant_context import build_debug_assistant_context
from hardware_readiness_admin_view import build_hardware_readiness_admin_view, load_hardware_readiness_fixture
from hardware_readiness_assistant_context import build_hardware_readiness_assistant_context
from pretrip_assistant_context import build_pretrip_assistant_context
from runtime_debug_log import MemoryRuntimeDebugEventLog
from runtime_debug_models import RuntimeDebugEvent


ROOT = Path(__file__).resolve().parents[1]


class _MessageSource:
    def list_messages(self) -> list[dict[str, Any]]:
        return [
            {
                "message_id": "mock_message.001",
                "transport": "mock",
                "state": "mock-delivered",
                "subject_ref": "incident.test",
                "body_preview": "Mock delivery only.",
                "boundary": {
                    "real_sos_sent": False,
                    "real_sms_sent": False,
                    "real_satellite_sent": False,
                },
            }
        ]


def test_debug_context_is_bounded_read_only_and_traceable():
    log = MemoryRuntimeDebugEventLog(
        [
            _event(sequence=1, kind="debug_session_started", summary="Debug started."),
            _event(
                sequence=2,
                kind="safety_event_emitted",
                summary="Route deviation emitted L2 concern.",
                payload={"safety_level": "L2_CONCERN", "reason": "off_route"},
            ),
            _event(
                sequence=3,
                kind="provider_status_recorded",
                summary="GPS provider degraded.",
                payload={"provider": "gps", "status": "degraded"},
            ),
        ]
    )

    context = build_debug_assistant_context(
        log,
        selected_event_id="debug_event.test.000002",
        message_source=_MessageSource(),
    )

    assert context["surface"] == "debug"
    assert context["read_only"] is True
    assert context["bounded"] is True
    assert context["auditable"] is True
    assert context["summary"]["event_count"] == 3
    assert context["summary"]["message_count"] == 1
    assert context["summary"]["latest_safety_level"] == "L2_CONCERN"
    assert context["selected_event"]["event_id"] == "debug_event.test.000002"
    assert context["timeline"][0]["source_id"] == "debug_event.test.000001"
    assert context["messages"][0]["transport"] == "mock"
    assert context["messages"][0]["boundary"]["real_sos_sent"] is False
    assert context["boundary"]["phase1_mutation_allowed"] is False
    assert context["boundary"]["phase2_writeback_allowed"] is False
    assert context["boundary"]["outbound_send_allowed"] is False
    assert {
        "source_id": "debug_event.test.000002",
        "source_path": "runtime_debug_event_log",
        "evidence_type": "runtime_debug_event",
    } in context["sources"]


def test_debug_context_resolver_includes_selected_event_detail_for_model_context():
    log = MemoryRuntimeDebugEventLog(
        [
            _event(sequence=1, kind="debug_session_started", summary="Debug started."),
            _event(
                sequence=2,
                kind="safety_event_emitted",
                summary="CP2 emitted L2 concern after route deviation.",
                payload={
                    "checkpoint_id": "CP2",
                    "safety_level": "L2_CONCERN",
                    "reason": "off_route",
                    "distance_from_route_m": 82,
                },
            ),
        ]
    )
    resolver = create_assistant_context_resolver(debug_event_log=log)

    sources = resolver(
        ScoutAssistantQuery(
            surface="debug",
            question="Why did CP2 become L2?",
            selected_event_id="debug_event.test.000002",
        )
    )

    context_source = next(
        source
        for source in sources
        if source.source_id == "assistant_context.debug"
    )
    selected_event = context_source.context_summary["selected_event"]

    assert selected_event["event_id"] == "debug_event.test.000002"
    assert selected_event["kind"] == "safety_event_emitted"
    assert selected_event["summary"] == "CP2 emitted L2 concern after route deviation."
    assert selected_event["payload"]["checkpoint_id"] == "CP2"
    assert selected_event["payload"]["safety_level"] == "L2_CONCERN"
    assert selected_event["payload"]["reason"] == "off_route"


def test_admin_context_wraps_after_action_view_as_compact_summary():
    context = build_admin_assistant_context("scout_260512_field_golden", root=ROOT)

    assert context["surface"] == "admin"
    assert context["read_only"] is True
    assert context["bounded"] is True
    assert context["summary"]["case_id"] == "scout_260512_field_golden"
    assert context["summary"]["route_point_count"] > 0
    assert context["summary"]["timeline_item_count"] > 0
    assert context["compact_view"]["route"]["point_count"] == context["summary"]["route_point_count"]
    assert "points" not in context["compact_view"]["route"]
    assert "raw_samples" not in str(context)
    assert context["boundary"]["incident_store_write_allowed"] is False
    assert context["boundary"]["phase2_writeback_allowed"] is False
    assert any(source["evidence_type"] == "replay_summary" for source in context["sources"])


def test_admin_context_resolver_includes_selected_evidence_detail_for_model_context():
    context = build_admin_assistant_context(
        "scout_260512_field_golden",
        root=ROOT,
        selected_source_id="cp_01",
    )

    sources = assistant_source_refs_from_context(
        context,
        query=ScoutAssistantQuery(
            surface="admin",
            question="Why is this checkpoint evidence important?",
            context_ref="scout_260512_field_golden",
            selected_artifact_id="cp_01",
        ),
    )

    context_source = next(
        source
        for source in sources
        if source.source_id == "assistant_context.admin"
    )
    selected_evidence = context_source.context_summary["selected_evidence"]

    assert selected_evidence["source_id"] == "cp_01"
    assert selected_evidence["evidence_type"] == "replay_checkpoint"
    assert selected_evidence["label"] == "cp_01"
    assert "Checkpoint cp_01 reached" in selected_evidence["reason"]
    assert "raw_samples" not in str(selected_evidence)


def test_admin_context_resolves_after_action_ui_selection_aliases():
    route_context = build_admin_assistant_context(
        "scout_260512_field_golden",
        root=ROOT,
        selected_source_id="route",
    )
    map_context = build_admin_assistant_context(
        "scout_260512_field_golden",
        root=ROOT,
        selected_source_id="map_corridors",
    )
    segment_context = build_admin_assistant_context(
        "scout_260512_field_golden",
        root=ROOT,
        selected_source_id="seg_01",
    )

    assert route_context["selected_evidence"]["source_id"] == "field_route"
    assert route_context["selected_evidence"]["evidence_type"] == "field_route_summary"
    assert route_context["selected_evidence"]["point_count"] > 1500
    assert map_context["selected_evidence"]["source_id"] == "field_map_context"
    assert map_context["selected_evidence"]["evidence_type"] == "map_layer_summary"
    assert map_context["selected_evidence"]["selected_layer_id"] == "map_corridors"
    assert map_context["selected_evidence"]["layer_count"] > 0
    assert segment_context["selected_evidence"]["source_id"] == "seg_01"
    assert segment_context["selected_evidence"]["evidence_type"] == "mission_segment"
    assert segment_context["selected_evidence"]["from_checkpoint_id"] == "cp_01"
    assert segment_context["selected_evidence"]["to_checkpoint_id"] == "cp_02"
    assert "raw_samples" not in str(route_context["selected_evidence"])
    assert "coordinates" not in str(map_context["selected_evidence"])


def test_admin_context_resolves_map_layer_aliases_with_readable_source_labels():
    expected = {
        "map_corridors": {
            "selected_layer_id": "map_corridors",
            "label": "Map corridors",
            "layer_evidence_type": "map_corridor",
        },
        "map_hazards": {
            "selected_layer_id": "map_hazards",
            "label": "Map hazards",
            "layer_evidence_type": "map_hazard",
        },
        "map_pois": {
            "selected_layer_id": "map_pois",
            "label": "Map POIs",
            "layer_evidence_type": "map_poi",
        },
    }

    for selected_source_id, expected_fields in expected.items():
        context = build_admin_assistant_context(
            "scout_260512_field_golden",
            root=ROOT,
            selected_source_id=selected_source_id,
        )
        selected_evidence = context["selected_evidence"]

        assert selected_evidence["source_id"] == "field_map_context"
        assert selected_evidence["evidence_type"] == "map_layer_summary"
        assert selected_evidence["source_path"].endswith("scout_260512_overpass_map_context.geojson")
        assert selected_evidence["selected_layer_id"] == expected_fields["selected_layer_id"]
        assert selected_evidence["label"] == expected_fields["label"]
        assert selected_evidence["layer_evidence_type"] == expected_fields["layer_evidence_type"]
        assert selected_evidence["layer_count"] >= 0
        if selected_source_id == "map_corridors":
            assert selected_evidence["layer_count"] > 0
            assert selected_evidence["sample_labels"]
        assert "coordinates" not in str(selected_evidence)
        assert "polygon" not in str(selected_evidence)
        assert "coordinate" not in str(selected_evidence)


def test_pretrip_context_wraps_admin_view_sections_without_review_writes():
    context = build_pretrip_assistant_context(
        "chilai_nanhua_day1",
        root=ROOT,
        view_builder=_fake_pretrip_view,
    )

    assert context["surface"] == "pretrip"
    assert context["read_only"] is True
    assert context["summary"]["project_id"] == "chilai_nanhua_day1"
    assert context["summary"]["route_name"] == "奇萊南華-能高越嶺步道Day1"
    assert context["summary"]["review_queue_status"]
    assert context["summary"]["readiness_status"]
    assert context["compact_view"]["review_queue"]["boundary"]["decisions_recorded"] is False
    assert context["compact_view"]["review_draft_log"]["boundary"]["draft_only"] is True
    assert context["compact_view"]["raw_sample_summary"]["raw_payloads_embedded"] is False
    assert context["boundary"]["pretrip_review_mutation_allowed"] is False
    assert context["boundary"]["observed_fact_write_allowed"] is False
    assert context["boundary"]["phase1_mutation_allowed"] is False
    assert any(
        source["evidence_type"] == "pretrip_review_queue_manifest"
        for source in context["sources"]
    )


def test_pretrip_context_resolver_includes_selected_evidence_detail_for_model_context():
    context = build_pretrip_assistant_context(
        "chilai_nanhua_day1",
        root=ROOT,
        selected_source_id="candidate.cp2",
        view_builder=_fake_pretrip_view,
    )

    sources = assistant_source_refs_from_context(
        context,
        query=ScoutAssistantQuery(
            surface="pretrip",
            question="Why does CP2 need review?",
            project_id="chilai_nanhua_day1",
            selected_artifact_id="candidate.cp2",
        ),
    )

    context_source = next(
        source
        for source in sources
        if source.source_id == "assistant_context.pretrip"
    )
    selected_evidence = context_source.context_summary["selected_evidence"]

    assert selected_evidence["source_id"] == "candidate.cp2"
    assert selected_evidence["evidence_type"] == "pretrip_checkpoint_candidate"
    assert selected_evidence["category"] == "checkpoint"
    assert selected_evidence["priority"] == "high"
    assert selected_evidence["candidate_ref"] == "cp2"
    assert selected_evidence["review_focus"] == ["timing"]
    assert selected_evidence["map_target_ids"] == ["cp2"]


def test_pretrip_context_fails_closed_when_admin_view_is_not_available():
    context = build_pretrip_assistant_context(
        "missing_project",
        view_builder=lambda *_args, **_kwargs: (_ for _ in ()).throw(ModuleNotFoundError()),
    )

    assert context["surface"] == "pretrip"
    assert context["read_only"] is True
    assert context["summary"]["status"] == "unavailable"
    assert context["boundary"]["pretrip_review_mutation_allowed"] is False
    assert context["sources"][0]["evidence_type"] == "pretrip_context_unavailable"


def test_hardware_readiness_context_is_bounded_and_does_not_control_providers():
    context = build_hardware_readiness_assistant_context(
        provider_health=[
            {
                "provider_ref": "provider.gnss.primary",
                "provider_type": "gnss",
                "status": "degraded",
                "degraded_reason": "fixture signal dropout",
                "source_path": "tests/fixtures/hardware/provider_health.json",
            }
        ],
        sample_replay_timeline=[
            {
                "event_id": "hardware_replay.001",
                "kind": "sample_replay",
                "summary": "GNSS degraded during replay.",
            }
        ],
        runtime_debug_events=[
            {
                "event_id": "debug_event.hardware.001",
                "kind": "provider_status_recorded",
                "summary": "Provider degraded in debug log.",
            }
        ],
        mock_transport_queue=[
            {
                "message_id": "mock_message.hardware.001",
                "transport": "mock",
                "state": "queued",
                "boundary": {
                    "real_sos_sent": False,
                    "real_sms_sent": False,
                    "real_satellite_sent": False,
                },
            }
        ],
        selected_provider_ref="provider.gnss.primary",
    )

    assert context["surface"] == "hardware_readiness"
    assert context["read_only"] is True
    assert context["bounded"] is True
    assert context["summary"]["provider_count"] == 1
    assert context["summary"]["degraded_provider_count"] == 1
    assert context["selected_provider"]["provider_ref"] == "provider.gnss.primary"
    assert context["boundary"]["hardware_control_allowed"] is False
    assert context["boundary"]["provider_control_allowed"] is False
    assert context["boundary"]["outbound_send_allowed"] is False
    assert context["mock_transport_queue"][0]["boundary"]["real_sos_sent"] is False
    assert {
        "source_id": "provider.gnss.primary",
        "source_path": "tests/fixtures/hardware/provider_health.json",
        "evidence_type": "hardware_provider_health",
    } in context["sources"]


def test_hardware_readiness_fixture_context_is_read_only_and_traceable():
    fixture = load_hardware_readiness_fixture(ROOT / "tests" / "fixtures" / "hardware" / "readiness_context.json")
    context = build_hardware_readiness_assistant_context(
        provider_health=fixture["provider_health"],
        sample_replay_timeline=fixture["sample_replay_timeline"],
        runtime_debug_events=fixture["runtime_debug_events"],
        mock_transport_queue=fixture["mock_transport_queue"],
        selected_provider_ref="provider.gnss.primary",
    )
    view = build_hardware_readiness_admin_view(selected_provider_ref="provider.gnss.primary")

    assert context["surface"] == "hardware_readiness"
    assert context["summary"]["provider_count"] == 2
    assert context["summary"]["degraded_provider_count"] == 1
    assert context["selected_provider"]["provider_ref"] == "provider.gnss.primary"
    assert context["selected_provider"]["status"] == "degraded"
    assert context["boundary"]["hardware_control_allowed"] is False
    assert context["boundary"]["provider_control_allowed"] is False
    assert context["boundary"]["real_sos_allowed"] is False
    assert view["read_only"] is True
    assert view["summary"]["mock_message_count"] == 1
    assert any(source["source_id"] == "provider.gnss.primary" for source in view["sources"])


def test_context_adapters_have_no_forbidden_mutation_imports():
    import admin_assistant_context
    import debug_assistant_context
    import hardware_readiness_assistant_context
    import pretrip_assistant_context

    combined_source = "\n".join(
        inspect.getsource(module)
        for module in (
            admin_assistant_context,
            debug_assistant_context,
            hardware_readiness_assistant_context,
            pretrip_assistant_context,
        )
    )
    for forbidden_fragment in (
        "SafetyRuntimeSession",
        "BrainFileStore",
        "IncidentStore",
        "append_review_decision",
        "append_route_note_disposition",
    ):
        assert forbidden_fragment not in combined_source


def _event(
    *,
    sequence: int,
    kind: str,
    summary: str,
    payload: dict[str, Any] | None = None,
) -> RuntimeDebugEvent:
    return RuntimeDebugEvent(
        event_id=f"debug_event.test.{sequence:06d}",
        session_id="debug_session.test",
        timestamp=f"2026-05-18T00:00:0{sequence}Z",
        sequence=sequence,
        kind=kind,
        source="test",
        phase="phase35",
        summary=summary,
        payload=payload or {},
    )


def _fake_pretrip_view(
    project_id: str,
    *,
    root: Path,
    project_root: Path | None,
) -> dict[str, Any]:
    review_queue = {
        "source_id": f"review_queue.{project_id}",
        "source_path": "tests/fixtures/pretrip/fake_review_queue.json",
        "evidence_type": "pretrip_review_queue_manifest",
        "status": "needs_review",
        "counts": {"pending": 1},
        "boundary": {"decisions_recorded": False},
        "items": [
            {
                "source_id": "candidate.cp2",
                "source_path": "tests/fixtures/pretrip/fake_candidates.json",
                "evidence_type": "pretrip_checkpoint_candidate",
                "category": "checkpoint",
                "priority": "high",
                "status": "candidate",
                "candidate_ref": "cp2",
                "review_focus": ["timing"],
                "map_target_ids": ["cp2"],
            }
        ],
    }
    review_draft_log = {
        "source_id": f"review_draft.{project_id}",
        "source_path": "tests/fixtures/pretrip/fake_review_draft.json",
        "evidence_type": "pretrip_review_draft_log",
        "status": "drafted",
        "counts": {"actions": 1},
        "boundary": {"draft_only": True},
    }
    return {
        "project_id": project_id,
        "summary": {
            "route_name": "奇萊南華-能高越嶺步道Day1",
            "package_id": f"pretrip_package.{project_id}",
            "status": "candidate",
        },
        "artifacts": {},
        "route": {
            "source_id": f"route.{project_id}",
            "source_path": "tests/fixtures/pretrip/fake_route.json",
            "evidence_type": "pretrip_route_summary",
            "route_name": "奇萊南華-能高越嶺步道Day1",
            "bounds": [121.0, 23.9, 121.2, 24.1],
            "point_count": 12,
            "distance_m": 5400,
            "elevation_min_m": 2200,
            "elevation_max_m": 3060,
        },
        "readiness": {
            "source_id": f"readiness.{project_id}",
            "source_path": "tests/fixtures/pretrip/fake_readiness.json",
            "evidence_type": "pretrip_readiness_report",
            "status": "blocked",
        },
        "review_queue": review_queue,
        "review_draft_log": review_draft_log,
        "review_decision_log": {
            "source_id": f"review_decision.{project_id}",
            "source_path": "tests/fixtures/pretrip/fake_decision.json",
            "evidence_type": "pretrip_review_decision_log",
            "status": "empty",
            "counts": {},
        },
        "review_decision_apply_plan": {
            "source_id": f"review_apply.{project_id}",
            "source_path": "tests/fixtures/pretrip/fake_apply.json",
            "evidence_type": "pretrip_review_decision_apply_plan",
            "status": "not_applied",
            "counts": {},
        },
        "external_import_queue": {
            "source_id": f"external_import.{project_id}",
            "source_path": "tests/fixtures/pretrip/fake_external_import.json",
            "evidence_type": "pretrip_external_import_queue",
            "status": "empty",
            "counts": {},
        },
        "expert_contributions": {
            "source_id": f"expert_contributions.{project_id}",
            "source_path": "tests/fixtures/pretrip/fake_expert.json",
            "evidence_type": "pretrip_expert_contribution_log",
            "status": "empty",
            "counts": {},
        },
        "departure_bundle": {
            "source_id": f"departure_bundle.{project_id}",
            "source_path": "tests/fixtures/pretrip/fake_departure.json",
            "evidence_type": "pretrip_departure_bundle",
            "status": "not_approved",
            "counts": {},
        },
        "resources": {"status": "candidate"},
        "weather": {"status": "candidate"},
        "contours": {"status": "candidate"},
        "raw_sample_summary": {"raw_payloads_embedded": False},
        "tabs": {
            "pre_trip_planning": {"sections": []},
            "post_analysis": {"sections": []},
        },
    }
