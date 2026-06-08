import pytest
from pydantic import ValidationError

from pretrip_models import PreTripCheckpointCandidate
from pretrip_review_models import (
    PreTripCorrection,
    PreTripHumanReview,
    PreTripHumanReviewLog,
    index_reviews_by_reviewed_ref,
    latest_review_for,
    source_candidate_snapshot_hash,
)


def test_pretrip_review_schema_is_strict_and_source_backed():
    review = PreTripHumanReview(
        review_id="review.cp.start.leader.20260514T090000",
        reviewer_id="person.leader",
        reviewed_ref="cp.start",
        reviewed_ref_kind="checkpoint",
        reviewed_at="2026-05-14T09:00:00+08:00",
        decision="accepted",
        notes="Trailhead checkpoint is correct.",
        source_candidate_snapshot_hash="a" * 64,
    )

    assert review.reviewed_ref_kind == "checkpoint"
    assert review.decision == "accepted"

    with pytest.raises(ValidationError):
        PreTripHumanReview(
            review_id="review.extra",
            reviewer_id="person.leader",
            reviewed_ref="cp.start",
            reviewed_ref_kind="checkpoint",
            reviewed_at="2026-05-14T09:00:00+08:00",
            decision="accepted",
            source_candidate_snapshot_hash="a" * 64,
            unexpected=True,
        )

    with pytest.raises(ValidationError):
        PreTripHumanReview(
            review_id="review.invalid_decision",
            reviewer_id="person.leader",
            reviewed_ref="cp.start",
            reviewed_ref_kind="checkpoint",
            reviewed_at="2026-05-14T09:00:00+08:00",
            decision="approved",
            source_candidate_snapshot_hash="a" * 64,
        )

    with pytest.raises(ValidationError, match="source_candidate_snapshot_hash or source_candidate_artifact_ref"):
        PreTripHumanReview(
            review_id="review.no_source_pointer",
            reviewer_id="person.leader",
            reviewed_ref="cp.start",
            reviewed_ref_kind="checkpoint",
            reviewed_at="2026-05-14T09:00:00+08:00",
            decision="accepted",
        )


def test_corrected_review_requires_and_preserves_correction_payload_or_refs():
    review = PreTripHumanReview(
        review_id="review.segment.001.leader.20260514T091500",
        reviewer_id="person.leader",
        reviewed_ref="seg.001",
        reviewed_ref_kind="segment",
        reviewed_at="2026-05-14T09:15:00+08:00",
        decision="corrected",
        correction=PreTripCorrection(
            payload={"distance_m": 1280.0},
            refs=["artifact.field_note.segment_001"],
        ),
        source_candidate_artifact_ref="artifact.pretrip.segment_candidates.v1",
    )

    dumped = review.model_dump(mode="json")

    assert dumped["correction"]["payload"] == {"distance_m": 1280.0}
    assert dumped["correction"]["refs"] == ["artifact.field_note.segment_001"]

    with pytest.raises(ValidationError, match="corrected review requires correction"):
        PreTripHumanReview(
            review_id="review.corrected_without_payload",
            reviewer_id="person.leader",
            reviewed_ref="seg.001",
            reviewed_ref_kind="segment",
            reviewed_at="2026-05-14T09:15:00+08:00",
            decision="corrected",
            source_candidate_artifact_ref="artifact.pretrip.segment_candidates.v1",
        )


def test_log_helpers_preserve_append_order_and_latest_review_by_ref():
    first = _review(
        review_id="review.cp.start.leader.20260514T090000",
        reviewed_ref="cp.start",
        reviewed_ref_kind="checkpoint",
        reviewed_at="2026-05-14T09:00:00+08:00",
        decision="noted",
    )
    unrelated = _review(
        review_id="review.map.hazard_01.leader.20260514T090500",
        reviewed_ref="map.hazard_01",
        reviewed_ref_kind="map_candidate",
        reviewed_at="2026-05-14T09:05:00+08:00",
        decision="rejected",
    )
    second = _review(
        review_id="review.cp.start.leader.20260514T091000",
        reviewed_ref="cp.start",
        reviewed_ref_kind="checkpoint",
        reviewed_at="2026-05-14T09:10:00+08:00",
        decision="accepted",
    )

    original_log = PreTripHumanReviewLog(log_id="review_log.chilai_nanhua_day1")
    updated_log = original_log.append(first).append(unrelated).append(second)

    assert original_log.reviews == ()
    assert [review.review_id for review in updated_log.reviews] == [
        first.review_id,
        unrelated.review_id,
        second.review_id,
    ]
    assert updated_log.index_by_reviewed_ref()["cp.start"] == [first, second]
    assert updated_log.latest_review_for("cp.start") == second
    assert updated_log.latest_review_for("missing.ref") is None

    indexed = index_reviews_by_reviewed_ref(updated_log.reviews)
    assert indexed["map.hazard_01"] == [unrelated]
    assert latest_review_for(updated_log.reviews, "cp.start") == second


def test_snapshot_hash_does_not_mutate_source_candidate():
    candidate = PreTripCheckpointCandidate(
        candidate_id="cp.start",
        label="Trailhead",
        lat=24.142,
        lon=121.282,
        checkpoint_type="start",
    )
    before = candidate.model_dump(mode="json")

    snapshot_hash = source_candidate_snapshot_hash(candidate)
    review = PreTripHumanReview(
        review_id="review.cp.start.leader.20260514T090000",
        reviewer_id="person.leader",
        reviewed_ref=candidate.candidate_id,
        reviewed_ref_kind="checkpoint",
        reviewed_at="2026-05-14T09:00:00+08:00",
        decision="accepted",
        source_candidate_snapshot_hash=snapshot_hash,
    )

    assert candidate.model_dump(mode="json") == before
    assert review.source_candidate_snapshot_hash == snapshot_hash
    assert source_candidate_snapshot_hash(candidate) == snapshot_hash


@pytest.mark.parametrize(
    "reviewed_ref_kind",
    [
        "checkpoint",
        "segment",
        "retreat_route",
        "map_candidate",
        "route_guide_timing",
        "planning_reference",
        "package",
    ],
)
def test_review_supports_phase4_pretrip_ref_kinds(reviewed_ref_kind):
    review = _review(
        review_id=f"review.{reviewed_ref_kind}.leader.20260514T090000",
        reviewed_ref=f"{reviewed_ref_kind}.candidate",
        reviewed_ref_kind=reviewed_ref_kind,
        reviewed_at="2026-05-14T09:00:00+08:00",
        decision="noted",
    )

    assert review.reviewed_ref_kind == reviewed_ref_kind


def _review(
    *,
    review_id: str,
    reviewed_ref: str,
    reviewed_ref_kind: str,
    reviewed_at: str,
    decision: str,
) -> PreTripHumanReview:
    return PreTripHumanReview(
        review_id=review_id,
        reviewer_id="person.leader",
        reviewed_ref=reviewed_ref,
        reviewed_ref_kind=reviewed_ref_kind,
        reviewed_at=reviewed_at,
        decision=decision,
        source_candidate_snapshot_hash="a" * 64,
    )
