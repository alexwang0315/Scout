import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from pretrip_models import CandidateReviewState
from pretrip_resource_plan import (
    PlanningInputStatus,
    PreTripResourcePlan,
    ResourceReviewBoundary,
    build_chilai_resource_plan,
    load_resource_plan,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
PROJECT_PATH = FIXTURE_ROOT / "project.json"


def test_chilai_resource_plan_schema_is_candidate_context_only():
    plan = build_chilai_resource_plan(FIXTURE_ROOT)
    payload = plan.model_dump(mode="json")

    assert payload["plan_id"] == "resource_plan.chilai_nanhua_day1.v0"
    assert payload["artifact_kind"] == "resource_team_departure_plan"
    assert payload["status"] == "candidate_only"
    assert payload["mission_owner"]["owner_id"] == "person.owner_placeholder"
    assert [member["role"] for member in payload["team_members"]] == ["leader", "member"]
    assert {device["device_type"] for device in payload["devices"]} >= {"phone", "watch", "power_bank"}
    assert {item["category"] for item in payload["equipment"]} >= {
        "navigation",
        "water",
        "first_aid",
    }
    assert payload["departure_readiness_context"] == {
        "status": "candidate_context_only",
        "hard_readiness_mutation_allowed": False,
        "blocks_existing_eta_or_readiness": False,
        "warning_candidates": [
            "teammate phone start battery needs confirmation",
            "water carry and refill plan needs reviewer confirmation",
            "headlamp set count is a planning placeholder",
        ],
        "blocker_candidates": [],
        "notes": [
            "Resource plan is candidate-only and does not alter outputs/readiness_report.json.",
            "Accepted placeholders are validation context, not proof of future field conditions.",
        ],
    }


def test_resource_plan_preserves_candidate_and_review_boundary():
    plan = build_chilai_resource_plan(FIXTURE_ROOT)

    assert plan.mission_owner.review.review_state == CandidateReviewState.ACCEPTED
    assert plan.mission_owner.review.review_ref == "reviews/human_reviews.json#resource-plan-placeholder"
    assert plan.team_members[1].review.review_state == CandidateReviewState.NEEDS_REVIEW
    assert plan.remote_contact_plan.review.human_review_required is True
    assert all(device.review.input_status != PlanningInputStatus.MODEL_CANDIDATE for device in plan.devices)

    with pytest.raises(ValidationError, match="accepted resource-plan entries require review_ref"):
        ResourceReviewBoundary(
            input_status=PlanningInputStatus.HUMAN_REVIEWED,
            review_state=CandidateReviewState.ACCEPTED,
        )

    with pytest.raises(ValidationError, match="model candidates require human review"):
        ResourceReviewBoundary(
            input_status=PlanningInputStatus.MODEL_CANDIDATE,
            review_state=CandidateReviewState.PROPOSED,
            human_review_required=False,
        )


def test_resource_plan_excludes_pii_raw_payloads_and_network_effects():
    plan = build_chilai_resource_plan(FIXTURE_ROOT)
    plan_json = plan.model_dump_json()

    assert plan.external_api_calls_made is False
    assert plan.raw_payloads_embedded is False
    assert plan.emergency_plan.secret_contact_details_included is False
    assert plan.remote_contact_plan.secret_contact_details_included is False

    forbidden_fragments = [
        "<trkpt",
        '"coordinates"',
        "candidate_tiles",
        "source_artifacts",
        "checkpoint_candidates",
        "segment_candidates",
        "catographydata",
        "PdrSample",
        ".gpx",
        ".grd",
        ".hdr",
        "incident_samples",
        "raw_samples",
        "tel:",
        "phone:",
        "email:",
        "@",
        "+886",
    ]
    for fragment in forbidden_fragments:
        assert fragment not in plan_json

    payload = plan.model_dump(mode="json")
    payload["remote_contact_plan"]["escalation_policy_summary"] = "email: private@example.test"
    with pytest.raises(ValidationError, match="forbidden shareable fragment"):
        PreTripResourcePlan.model_validate(payload)


def test_chilai_resource_plan_fixture_matches_builder_and_project_ref():
    project = json.loads(PROJECT_PATH.read_text(encoding="utf-8"))
    assert project["resource_plan_ref"] == "outputs/resource_plan.json"
    assert project["resource_plan_device_count"] == 4
    assert project["resource_plan_equipment_count"] == 4

    expected = build_chilai_resource_plan(FIXTURE_ROOT)
    fixture = load_resource_plan(FIXTURE_ROOT / project["resource_plan_ref"])

    assert fixture == expected
