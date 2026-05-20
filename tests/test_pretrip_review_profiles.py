import inspect
from pathlib import Path

from pydantic import ValidationError
import pytest

import pretrip_review_profiles
from pretrip_review_profiles import (
    HardBlockerId,
    ReviewProfileId,
    RouteClassId,
    RouteReviewContext,
    build_chilai_review_context,
    classify_route_for_review,
    evaluate_hard_blockers,
    get_baseline_hard_blocker_catalog,
    get_planning_review_profiles,
    select_planning_review_profile,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"


def test_profiles_are_data_backed_and_preserve_safety_invariants():
    profiles = get_planning_review_profiles()

    assert set(profiles) == {
        ReviewProfileId.QUICK,
        ReviewProfileId.GUIDED,
        ReviewProfileId.EXPEDITION,
    }
    assert profiles[ReviewProfileId.QUICK].model_dump(mode="json") == {
        "profile_id": "quick_review.v0",
        "display_name": "Quick Review",
        "display_name_zh": "快捷模式",
        "description_zh": (
            "低摩擦審核模式，不是低安全模式；仍保留 route、retreat、hard blocker 與 handoff 不可略過條件。"
        ),
        "intended_trip_classes": [
            "simple_single_day",
            "long_single_day",
            "deep_mountain_out_and_back",
        ],
        "friction_level": "low",
        "allows_bulk_accept": True,
        "bulk_accept_policy": "low_risk_ai_candidates_only",
        "bulk_accept_policy_zh": "僅允許低風險 AI 候選批次接受。",
        "requires_second_review": False,
        "route_note_review_required": "partial_allowed",
        "retreat_policy_required": True,
        "field_verify_blocks_departure": "critical_only",
        "runtime_handoff_second_confirm": False,
        "second_review_requirement_policy": "none_by_default",
        "professional_review_triggers": [],
        "professional_review_triggers_zh": [],
        "blocker_override_requires_reason": True,
        "hard_blocker_override_allowed": False,
        "hard_blocker_policy_ref": "baseline_hard_blockers.v0",
        "stores_package_hash": True,
        "stores_handoff_manifest": True,
        "boundary": {
            "planning_metadata_only": True,
            "phase1_runtime_mutation_allowed": False,
            "safety_api_calls_allowed": False,
            "reviewed_package_activates_runtime": False,
            "runtime_handoff_required": True,
            "notes": [
                "Quick Review reduces review friction only; it does not reduce safety invariants.",
            ],
        },
    }
    assert profiles[ReviewProfileId.EXPEDITION].requires_second_review is True
    assert profiles[ReviewProfileId.EXPEDITION].runtime_handoff_second_confirm is True


def test_baseline_hard_blocker_catalog_contains_non_overridable_policy_data():
    catalog = get_baseline_hard_blocker_catalog()

    assert catalog.catalog_id == "baseline_hard_blockers.v0"
    blockers = {blocker.blocker_id: blocker for blocker in catalog.blockers}
    assert set(blockers) == {
        HardBlockerId.WEATHER_NO_GO,
        HardBlockerId.NO_VALID_ROUTE,
        HardBlockerId.UNVERIFIED_WILD_ROUTE_WITHOUT_PUBLIC_GPX,
        HardBlockerId.NO_RETREAT_POLICY_FOR_REQUIRED_ROUTE,
        HardBlockerId.NO_REVIEWED_PACKAGE,
        HardBlockerId.NO_FINAL_MISSION_GRAPH,
        HardBlockerId.CORRUPT_PACKAGE_OR_GRAPH_HASH,
        HardBlockerId.MISSING_RUNTIME_TARGET,
    }
    assert blockers[HardBlockerId.WEATHER_NO_GO].label_zh == "天氣不允許"
    assert blockers[HardBlockerId.NO_RETREAT_POLICY_FOR_REQUIRED_ROUTE].allowed_resolution_path_zh
    assert all(blocker.override_allowed is False for blocker in catalog.blockers)


def test_chilai_day1_classifies_as_long_or_deep_mountain_not_simple():
    context = build_chilai_review_context(FIXTURE_ROOT)
    classification = classify_route_for_review(context)

    assert classification.primary_class in {
        RouteClassId.LONG_SINGLE_DAY,
        RouteClassId.DEEP_MOUNTAIN_OUT_AND_BACK,
    }
    assert RouteClassId.LONG_SINGLE_DAY in classification.route_classes
    assert RouteClassId.DEEP_MOUNTAIN_OUT_AND_BACK in classification.route_classes
    assert RouteClassId.SIMPLE_SINGLE_DAY not in classification.route_classes
    assert "深山原路折返" in classification.explanation_zh


def test_chilai_quick_review_can_remain_valid_when_return_to_entry_retreat_is_clear():
    context = build_chilai_review_context(ROOT)
    result = select_planning_review_profile(context, ReviewProfileId.QUICK)

    assert result.requested_profile_id == ReviewProfileId.QUICK
    assert result.selected_profile_id == ReviewProfileId.QUICK
    assert result.quick_review_allowed is True
    assert result.hard_blockers == []
    assert result.recommended_profile_id == ReviewProfileId.QUICK
    assert "快捷模式" in result.explanation_zh
    assert result.boundary.phase1_runtime_mutation_allowed is False
    assert result.boundary.safety_api_calls_allowed is False


def test_profile_escalates_when_retreat_or_weather_evidence_breaks_quick_conditions():
    no_retreat = build_chilai_review_context(FIXTURE_ROOT).model_copy(
        update={
            "retreat_policy_accepted": False,
            "retreat_policy_type": None,
            "retreat_difficulty": "unclear",
        }
    )
    no_retreat_result = select_planning_review_profile(no_retreat, ReviewProfileId.QUICK)

    assert no_retreat_result.selected_profile_id == ReviewProfileId.EXPEDITION
    assert HardBlockerId.NO_RETREAT_POLICY_FOR_REQUIRED_ROUTE in {
        blocker.blocker_id for blocker in no_retreat_result.hard_blockers
    }
    assert any(
        reason.rule_id == "deep_mountain_unclear_retreat"
        for reason in no_retreat_result.escalation_reasons
    )

    weather_no_go = build_chilai_review_context(FIXTURE_ROOT).model_copy(
        update={"weather_no_go": True}
    )
    weather_result = select_planning_review_profile(weather_no_go, ReviewProfileId.QUICK)

    assert weather_result.selected_profile_id == ReviewProfileId.EXPEDITION
    assert weather_result.quick_review_allowed is False
    assert HardBlockerId.WEATHER_NO_GO in {
        blocker.blocker_id for blocker in weather_result.hard_blockers
    }


def test_hard_blockers_include_handoff_only_runtime_requirements_when_requested():
    context = build_chilai_review_context(FIXTURE_ROOT).model_copy(
        update={
            "final_mission_graph_exists": False,
            "runtime_target_present": False,
        }
    )

    planning_blockers = evaluate_hard_blockers(context, handoff_requested=False)
    handoff_blockers = evaluate_hard_blockers(context, handoff_requested=True)

    assert HardBlockerId.NO_FINAL_MISSION_GRAPH not in {
        blocker.blocker_id for blocker in planning_blockers
    }
    assert {
        HardBlockerId.NO_FINAL_MISSION_GRAPH,
        HardBlockerId.MISSING_RUNTIME_TARGET,
    }.issubset({blocker.blocker_id for blocker in handoff_blockers})


def test_models_reject_extra_fields_and_slice_has_no_safety_or_runtime_calls():
    with pytest.raises(ValidationError):
        RouteReviewContext(
            route_name="x",
            distance_m=1,
            unexpected_runtime_write=True,
        )

    source = inspect.getsource(pretrip_review_profiles)
    forbidden_fragments = [
        "requests.",
        "httpx.",
        "urllib.request",
        "from phase1_incident_bridge",
        "Phase1IncidentBridge(",
        "os.environ",
        "/safety",
        "safety/",
    ]
    for fragment in forbidden_fragments:
        assert fragment not in source
