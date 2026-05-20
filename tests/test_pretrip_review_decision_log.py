import inspect
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

import pretrip_review_decision_log
from pretrip_review_decision_log import (
    PreTripReviewDecisionLog,
    ReviewDecisionRecord,
    build_chilai_review_decision_log,
    load_review_decision_log,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
DECISION_LOG_PATH = FIXTURE_ROOT / "reviews" / "review_decision_log.json"


def test_builds_fixture_only_review_decision_log():
    decision_log = build_chilai_review_decision_log(FIXTURE_ROOT)
    payload = decision_log.model_dump(mode="json")

    assert payload["log_id"] == "review_decision_log.chilai_nanhua_day1.v0"
    assert payload["artifact_kind"] == "pretrip_review_decision_log"
    assert payload["project_id"] == "chilai_nanhua_day1"
    assert payload["source_draft_log_ref"] == "reviews/review_draft_log.json"
    assert payload["source_review_queue_manifest_ref"] == "outputs/review_queue_manifest.json"
    assert payload["counts"] == {
        "action_count": 3,
        "accepted_count": 1,
        "corrected_count": 1,
        "rejected_count": 1,
        "source_ref_count": 3,
        "runtime_mutation_count": 0,
        "package_mutation_count": 0,
        "raw_payloads_embedded": False,
    }
    assert payload["apply_summary"]["runtime_mutation_count"] == 0
    assert payload["apply_summary"]["package_mutation_count"] == 0
    assert payload["apply_summary"]["compiles_mission_graph"] is False


def test_decisions_preserve_draft_queue_target_reviewer_and_candidate_refs():
    decision_log = build_chilai_review_decision_log(FIXTURE_ROOT)
    decisions_by_candidate = {
        decision.candidate_ref: decision for decision in decision_log.decisions
    }

    assert set(decisions_by_candidate) == {
        "contour.g11.seg_001_003",
        "policy_candidate.chilai_nanhua_day1.seg.001",
        "poi_readiness_policy.chilai_nanhua_day1.route_corridor_poi_coverage",
    }
    assert all(decision.reviewer_alias == "trip_leader" for decision in decision_log.decisions)
    assert [decision.decided_at for decision in decision_log.decisions] == [
        "2026-05-15T10:00:00+08:00",
        "2026-05-15T10:05:00+08:00",
        "2026-05-15T10:10:00+08:00",
    ]

    contour = decisions_by_candidate["contour.g11.seg_001_003"]
    assert contour.decision == "accepted"
    assert contour.draft_action_id == "review_draft.chilai_nanhua_day1.contour.contour.g11.seg_001_003"
    assert contour.target_ids == ["seg.001", "seg.002", "seg.003"]
    assert contour.source_review_queue_item_refs[0].model_dump(mode="json") == {
        "review_queue_manifest_id": "review_queue.chilai_nanhua_day1.v0",
        "item_id": "review_queue.chilai_nanhua_day1.contour.contour.g11.seg_001_003",
        "source_ref": "outputs/contour_interpretation_candidates.json",
        "candidate_ref": "contour.g11.seg_001_003",
    }

    corrected = decisions_by_candidate["policy_candidate.chilai_nanhua_day1.seg.001"]
    assert corrected.decision == "corrected"
    assert corrected.target_ids == ["seg.001"]
    assert corrected.correction is not None
    assert corrected.correction.field_updates == {
        "review_state_after_edit": "accepted_with_human_correction",
        "water_available": "reviewer_confirmed_unknown",
    }

    rejected = decisions_by_candidate[
        "poi_readiness_policy.chilai_nanhua_day1.route_corridor_poi_coverage"
    ]
    assert rejected.decision == "rejected"
    assert rejected.target_ids == ["route_corridor_poi_coverage"]
    assert rejected.source_review_queue_item_refs[0].model_dump(mode="json") == {
        "review_queue_manifest_id": "review_draft_log.chilai_nanhua_day1.v0",
        "item_id": "review_draft.chilai_nanhua_day1.poi_readiness.poi_readiness_policy.chilai_nanhua_day1.route_corridor_poi_coverage",
        "source_ref": "outputs/poi_readiness_candidates.json",
        "candidate_ref": "poi_readiness_policy.chilai_nanhua_day1.route_corridor_poi_coverage",
    }


def test_review_decision_fixture_matches_builder_output():
    fixture_payload = json.loads(DECISION_LOG_PATH.read_text(encoding="utf-8"))
    fixture = load_review_decision_log(DECISION_LOG_PATH)
    regenerated = build_chilai_review_decision_log(FIXTURE_ROOT)

    assert fixture.model_dump(mode="json") == fixture_payload
    assert fixture_payload == regenerated.model_dump(mode="json")


def test_decision_log_has_no_runtime_api_or_resolver_coupling():
    decision_log = build_chilai_review_decision_log(FIXTURE_ROOT)

    assert decision_log.boundary.model_dump(mode="json") == {
        "append_only": True,
        "source_mutation_allowed": False,
        "package_mutation_allowed": False,
        "runtime_mutation_allowed": False,
        "phase1_runtime_mutation_allowed": False,
        "phase2_writeback_allowed": False,
        "external_api_calls_made": False,
        "admin_api_integration": False,
        "compiles_mission_graph": False,
        "raw_payloads_embedded": False,
        "notes": [
            "Decision log accepts, corrects, or rejects selected draft review actions only.",
            "Records are append-only pointers to review queue items and candidate refs.",
            "No raw source payloads, external API calls, admin API writes, package mutation, runtime mutation, Phase 2 writeback, or MissionGraph compile is performed.",
        ],
    }

    serialized = decision_log.to_json()
    for fragment in [
        "/safety",
        "Phase1IncidentBridge",
        "SCOUT_PHASE2_INCIDENT_BRIDGE",
        "<trkpt",
        '"coordinates"',
        "catographydata",
        "PdrSample",
        ".gpx",
        ".grd",
        ".hdr",
        ".jpg",
        ".jpeg",
        ".tif",
        ".tiff",
        "incident_samples",
        "raw_samples",
        "sample_payload",
        "elevation_grid",
        "terrain_tile",
        "payload_fragment",
    ]:
        assert fragment not in serialized
    assert decision_log.counts.raw_payloads_embedded is False
    assert decision_log.boundary.raw_payloads_embedded is False

    source = inspect.getsource(pretrip_review_decision_log)
    assert "from pretrip_review_resolver" not in source
    assert "resolve_pretrip_reviewed_package" not in source
    assert "from phase1_incident_bridge" not in source
    assert "Phase1IncidentBridge(" not in source
    assert "import admin_api" not in source
    assert "from admin_api" not in source
    assert "import requests" not in source
    assert "import httpx" not in source


def test_decision_schema_rejects_missing_source_refs_mutation_and_raw_payloads():
    payload = build_chilai_review_decision_log(FIXTURE_ROOT).model_dump(mode="json")
    payload["decisions"][0]["source_review_queue_item_refs"] = []

    with pytest.raises(ValidationError):
        PreTripReviewDecisionLog.model_validate(payload)

    payload = build_chilai_review_decision_log(FIXTURE_ROOT).model_dump(mode="json")
    payload["decisions"][0]["source_mutation_allowed"] = True

    with pytest.raises(ValidationError):
        PreTripReviewDecisionLog.model_validate(payload)

    payload = build_chilai_review_decision_log(FIXTURE_ROOT).model_dump(mode="json")
    payload["decisions"][0]["runtime_mutation_allowed"] = True

    with pytest.raises(ValidationError):
        PreTripReviewDecisionLog.model_validate(payload)

    payload = build_chilai_review_decision_log(FIXTURE_ROOT).model_dump(mode="json")
    payload["decisions"][0]["package_mutation_allowed"] = True

    with pytest.raises(ValidationError):
        PreTripReviewDecisionLog.model_validate(payload)

    payload = build_chilai_review_decision_log(FIXTURE_ROOT).model_dump(mode="json")
    payload["decisions"][0]["summary"] = "Attach raw payload from day1.gpx"

    with pytest.raises(ValidationError, match="forbidden raw/runtime fragment"):
        PreTripReviewDecisionLog.model_validate(payload)


def test_decision_record_requires_correction_only_for_corrected_decisions():
    payload = build_chilai_review_decision_log(FIXTURE_ROOT).model_dump(mode="json")
    corrected_payload = payload["decisions"][1]
    corrected_payload["correction"] = None

    with pytest.raises(ValidationError, match="corrected decision requires correction"):
        ReviewDecisionRecord.model_validate(corrected_payload)

    accepted_payload = payload["decisions"][0]
    accepted_payload["correction"] = {
        "summary": "not allowed",
        "field_updates": {"status": "changed"},
        "replacement_ref_ids": [],
    }

    with pytest.raises(ValidationError, match="correction is only allowed"):
        ReviewDecisionRecord.model_validate(accepted_payload)
