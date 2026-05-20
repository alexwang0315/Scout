import json
from pathlib import Path

from pretrip_review_models import PreTripHumanReviewLog
from pretrip_review_resolver import resolve_pretrip_reviewed_package


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"


def test_chilai_review_log_resolves_reviewed_package_without_mutating_candidate_package():
    original_payload = json.loads((FIXTURE_ROOT / "outputs" / "pretrip_package.json").read_text())
    review_log = PreTripHumanReviewLog.model_validate(
        json.loads((FIXTURE_ROOT / "reviews" / "human_reviews.json").read_text())
    )
    reviewed_fixture = json.loads((FIXTURE_ROOT / "outputs" / "pretrip_package.reviewed.json").read_text())

    resolved = resolve_pretrip_reviewed_package(original_payload, list(review_log.reviews))
    resolved_payload = resolved.model_copy(update={"status": "reviewed"}).model_dump(mode="json")

    assert len(review_log.reviews) == 47
    assert resolved_payload == reviewed_fixture
    assert original_payload["checkpoint_candidates"][0]["review_state"] == "proposed"
    assert reviewed_fixture["checkpoint_candidates"][0]["review_state"] == "accepted"
    assert reviewed_fixture["segment_candidates"][0]["review_state"] == "accepted"
    assert reviewed_fixture["retreat_route_candidates"][0]["review_state"] == "accepted"
    assert reviewed_fixture["route_guide_timing_candidates"][0]["review_state"] == "needs_review"


def test_chilai_review_log_keeps_timing_and_map_context_out_of_compile_path():
    review_log = PreTripHumanReviewLog.model_validate(
        json.loads((FIXTURE_ROOT / "reviews" / "human_reviews.json").read_text())
    )
    decisions_by_kind = {}
    for review in review_log.reviews:
        decisions_by_kind.setdefault(review.reviewed_ref_kind, set()).add(review.decision)

    assert decisions_by_kind["checkpoint"] == {"accepted"}
    assert decisions_by_kind["segment"] == {"accepted"}
    assert decisions_by_kind["retreat_route"] == {"accepted"}
    assert decisions_by_kind["map_candidate"] == {"noted"}
    assert decisions_by_kind["route_guide_timing"] == {"noted"}
    assert decisions_by_kind["planning_reference"] == {"noted"}
