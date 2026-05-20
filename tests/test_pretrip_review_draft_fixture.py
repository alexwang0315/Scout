import inspect
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

import pretrip_review_draft_fixture
from pretrip_review_draft_fixture import (
    PreTripReviewDraftLog,
    build_chilai_review_draft_log,
    load_review_draft_log,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
DRAFT_LOG_PATH = FIXTURE_ROOT / "reviews" / "review_draft_log.json"
SOURCE_PATHS = [
    FIXTURE_ROOT / "outputs" / "contour_interpretation_candidates.json",
    FIXTURE_ROOT / "outputs" / "segment_policy_candidates.json",
    FIXTURE_ROOT / "outputs" / "poi_readiness_candidates.json",
    FIXTURE_ROOT / "outputs" / "pretrip_package.json",
    FIXTURE_ROOT / "reviews" / "human_reviews.json",
]


def test_builds_draft_only_review_output_fixture():
    draft_log = build_chilai_review_draft_log(FIXTURE_ROOT)
    payload = draft_log.model_dump(mode="json")

    assert payload["log_id"] == "review_draft_log.chilai_nanhua_day1.v0"
    assert payload["artifact_kind"] == "pretrip_review_draft_log"
    assert payload["project_id"] == "chilai_nanhua_day1"
    assert payload["status"] == "draft_only"
    assert payload["source_refs"] == [
        "outputs/contour_interpretation_candidates.json",
        "outputs/segment_policy_candidates.json",
        "outputs/poi_readiness_candidates.json",
    ]
    assert payload["counts"] == {
        "action_count": 3,
        "category_counts": {
            "contour": 1,
            "poi_readiness": 1,
            "segment_policy": 1,
        },
        "draft_action_count": 3,
        "mutation_action_count": 0,
        "source_ref_count": 3,
    }


def test_review_draft_actions_are_representative_and_non_mutating():
    draft_log = build_chilai_review_draft_log(ROOT)
    actions_by_category = {action.category.value: action for action in draft_log.actions}

    assert set(actions_by_category) == {"contour", "segment_policy", "poi_readiness"}
    assert all(action.draft_state == "draft" for action in draft_log.actions)
    assert all(action.draft_only is True for action in draft_log.actions)
    assert all(action.decision_recorded is False for action in draft_log.actions)
    assert all(action.source_mutation_allowed is False for action in draft_log.actions)
    assert all(action.package_mutation_allowed is False for action in draft_log.actions)
    assert all(action.runtime_mutation_allowed is False for action in draft_log.actions)
    assert all(action.admin_api_integration is False for action in draft_log.actions)

    assert actions_by_category["contour"].candidate_ref == "contour.g11.seg_001_003"
    assert actions_by_category["contour"].proposed_fields["target_segment_refs"] == [
        "seg.001",
        "seg.002",
        "seg.003",
    ]
    assert (
        actions_by_category["segment_policy"].candidate_ref
        == "policy_candidate.chilai_nanhua_day1.seg.001"
    )
    assert actions_by_category["segment_policy"].proposed_fields == {
        "camp_available": False,
        "requires_daylight": True,
        "retreat_available": True,
        "review_state_after_edit": "proposed",
        "segment_candidate_id": "seg.001",
        "signal_expected": True,
        "water_available": False,
    }
    assert (
        actions_by_category["poi_readiness"].candidate_ref
        == "poi_readiness_policy.chilai_nanhua_day1.route_corridor_poi_coverage"
    )
    assert actions_by_category["poi_readiness"].proposed_fields == {
        "category": "route_corridor_poi_coverage",
        "corridor_distance_m": 1000.0,
        "current_finding_count": 0,
        "minimum_poi_count": 1,
        "review_state_after_edit": "proposed",
        "route_corridor_poi_count": 1,
        "severity": "warning",
    }


def test_review_draft_fixture_matches_builder_output():
    fixture_payload = json.loads(DRAFT_LOG_PATH.read_text(encoding="utf-8"))
    fixture = load_review_draft_log(DRAFT_LOG_PATH)
    regenerated = build_chilai_review_draft_log(FIXTURE_ROOT)

    assert fixture.model_dump(mode="json") == fixture_payload
    assert fixture_payload == regenerated.model_dump(mode="json")


def test_review_draft_has_no_raw_payloads_or_admin_api_integration():
    before = _selected_hashes()
    draft_log = build_chilai_review_draft_log(FIXTURE_ROOT)
    after = _selected_hashes()

    assert after == before
    assert draft_log.boundary.model_dump(mode="json") == {
        "admin_api_integration": False,
        "decisions_recorded": False,
        "draft_only": True,
        "external_api_calls_made": False,
        "notes": [
            "Draft output fixture only; it records proposed review actions, not decisions.",
            "Candidate artifacts, reviewed package outputs, review logs, and runtime stores remain read-only.",
            "No admin API, external API, package mutation, source mutation, or runtime mutation is performed.",
        ],
        "package_mutation_allowed": False,
        "phase1_runtime_mutation_allowed": False,
        "phase2_writeback_allowed": False,
        "raw_payloads_embedded": False,
        "review_log_mutation_allowed": False,
        "runtime_mutation_allowed": False,
        "source_mutation_allowed": False,
    }

    serialized = draft_log.to_json()
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
    ]:
        assert fragment not in serialized

    source = inspect.getsource(pretrip_review_draft_fixture)
    assert "from pretrip_review_resolver" not in source
    assert "resolve_pretrip_reviewed_package" not in source
    assert "from phase1_incident_bridge" not in source
    assert "Phase1IncidentBridge(" not in source
    assert "import admin_api" not in source
    assert "from admin_api" not in source
    assert "import requests" not in source
    assert "import httpx" not in source


def test_review_draft_schema_rejects_decisions_mutation_and_raw_payloads():
    payload = build_chilai_review_draft_log(FIXTURE_ROOT).model_dump(mode="json")
    payload["actions"][0]["decision_recorded"] = True

    with pytest.raises(ValidationError):
        PreTripReviewDraftLog.model_validate(payload)

    payload = build_chilai_review_draft_log(FIXTURE_ROOT).model_dump(mode="json")
    payload["actions"][0]["package_mutation_allowed"] = True

    with pytest.raises(ValidationError):
        PreTripReviewDraftLog.model_validate(payload)

    payload = build_chilai_review_draft_log(FIXTURE_ROOT).model_dump(mode="json")
    payload["actions"][0]["summary"] = "Attach raw track payload from day1.gpx"

    with pytest.raises(ValidationError, match="forbidden raw/runtime fragment"):
        PreTripReviewDraftLog.model_validate(payload)


def _selected_hashes() -> dict[str, tuple[int, int]]:
    return {
        path.relative_to(FIXTURE_ROOT).as_posix(): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in SOURCE_PATHS
    }
