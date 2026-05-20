import pytest

from pretrip_mission_compiler import compile_pretrip_mission_graph
from pretrip_models import CandidateReviewState, PreTripPackage
from pretrip_review_models import PreTripCorrection, PreTripHumanReview
from pretrip_review_resolver import resolve_pretrip_reviewed_package


def test_resolver_applies_latest_review_decisions_without_mutating_source_package():
    package = PreTripPackage.model_validate(_package_with_all_candidate_types())

    resolved = resolve_pretrip_reviewed_package(
        package,
        [
            {"candidate_id": "cp.start", "decision": "accepted"},
            {"candidate_id": "cp.start", "decision": "rejected"},
            {"candidate_id": "cp.start", "decision": "accepted"},
            {"candidate_id": "cp.finish", "decision": "noted", "notes": "Looks plausible."},
            {"candidate_id": "seg.001", "decision": "accepted"},
            {"candidate_id": "retreat.001", "decision": "rejected"},
        ],
    )

    assert package.checkpoint_candidates[0].review_state == CandidateReviewState.PROPOSED
    assert package.segment_candidates[0].review_state == CandidateReviewState.PROPOSED
    assert package.retreat_route_candidates[0].review_state == CandidateReviewState.PROPOSED

    assert resolved.checkpoint_candidates[0].review_state == CandidateReviewState.ACCEPTED
    assert resolved.checkpoint_candidates[1].review_state == CandidateReviewState.PROPOSED
    assert resolved.segment_candidates[0].review_state == CandidateReviewState.ACCEPTED
    assert resolved.retreat_route_candidates[0].review_state == CandidateReviewState.REJECTED


def test_corrected_reviews_apply_payload_and_result_state_to_each_candidate_type():
    package = _package_with_all_candidate_types()

    resolved = resolve_pretrip_reviewed_package(
        package,
        [
            {
                "candidate_id": "cp.start",
                "decision": "corrected",
                "correction_payload": {"label": "Corrected Start", "arrival_radius_m": 45.0},
                "review_state": "accepted",
            },
            {
                "candidate_id": "seg.001",
                "decision": "corrected",
                "correction_payload": {"distance_m": 140.0, "elevation_gain_m": 24.0},
                "review_state": "needs_review",
            },
            {
                "candidate_id": "retreat.001",
                "decision": "corrected",
                "correction_payload": {"expected_use": "retreat", "distance_m": 125.0},
            },
            {
                "candidate_id": "timing.001",
                "decision": "corrected",
                "correction_payload": {
                    "route_guide_segment_time_minutes": 18,
                    "fixed_rest_minutes": 5,
                },
                "review_state": "accepted",
            },
        ],
    )

    assert resolved.checkpoint_candidates[0].label == "Corrected Start"
    assert resolved.checkpoint_candidates[0].arrival_radius_m == 45.0
    assert resolved.checkpoint_candidates[0].review_state == CandidateReviewState.ACCEPTED

    assert resolved.segment_candidates[0].distance_m == 140.0
    assert resolved.segment_candidates[0].elevation_gain_m == 24.0
    assert resolved.segment_candidates[0].review_state == CandidateReviewState.NEEDS_REVIEW

    assert resolved.retreat_route_candidates[0].expected_use == "retreat"
    assert resolved.retreat_route_candidates[0].distance_m == 125.0
    assert resolved.retreat_route_candidates[0].review_state == CandidateReviewState.ACCEPTED

    assert resolved.route_guide_timing_candidates[0].route_guide_segment_time_minutes == 18
    assert resolved.route_guide_timing_candidates[0].fixed_rest_minutes == 5
    assert resolved.route_guide_timing_candidates[0].review_state == CandidateReviewState.ACCEPTED


def test_default_compiler_rejects_original_package_but_accepts_resolved_checkpoint_and_segment_reviews():
    package = _minimal_compile_package()

    with pytest.raises(ValueError, match="allow_unreviewed=True"):
        compile_pretrip_mission_graph(package)

    resolved = resolve_pretrip_reviewed_package(
        package,
        [
            {"candidate_id": "cp.start", "decision": "accepted"},
            {"candidate_id": "cp.finish", "decision": "accepted"},
            {"candidate_id": "seg.001", "decision": "accepted"},
        ],
    )

    graph = compile_pretrip_mission_graph(resolved)

    assert [checkpoint.checkpoint_id for checkpoint in graph.checkpoints] == [
        "cp.start",
        "cp.finish",
    ]
    assert [segment.segment_id for segment in graph.segments] == ["seg.001"]
    assert package["checkpoint_candidates"][0]["review_state"] == "proposed"
    assert package["segment_candidates"][0]["review_state"] == "proposed"


def test_resolver_accepts_typed_human_reviews_with_reviewed_ref_and_correction_payload():
    package = _minimal_compile_package()

    resolved = resolve_pretrip_reviewed_package(
        package,
        [
            _human_review("review.cp.start", "cp.start", "checkpoint", "accepted"),
            _human_review("review.cp.finish", "cp.finish", "checkpoint", "accepted"),
            PreTripHumanReview(
                review_id="review.seg.001",
                reviewer_id="person.leader",
                reviewed_ref="seg.001",
                reviewed_ref_kind="segment",
                reviewed_at="2026-05-14T10:05:00+08:00",
                decision="corrected",
                correction=PreTripCorrection(payload={"distance_m": 125.0}),
                source_candidate_snapshot_hash="b" * 64,
            ),
        ],
    )

    graph = compile_pretrip_mission_graph(resolved)

    assert graph.segments[0].distance_m == 125.0
    assert resolved.segment_candidates[0].review_state == CandidateReviewState.ACCEPTED


def test_resolver_rejects_unknown_candidate_reviews_and_candidate_id_corrections():
    package = _minimal_compile_package()

    with pytest.raises(ValueError, match="unknown PreTrip candidate"):
        resolve_pretrip_reviewed_package(
            package,
            [{"candidate_id": "cp.missing", "decision": "accepted"}],
        )

    with pytest.raises(ValueError, match="cannot change candidate_id"):
        resolve_pretrip_reviewed_package(
            package,
            [
                {
                    "candidate_id": "cp.start",
                    "decision": "corrected",
                    "correction_payload": {"candidate_id": "cp.other"},
                }
            ],
        )


def _minimal_compile_package() -> dict:
    return {
        "package_id": "pretrip.synthetic.v0",
        "project_id": "synthetic",
        "version": "v0",
        "status": "candidate",
        "route_summary": {
            "artifact_id": "artifact.gpx.synthetic",
            "route_name": "Synthetic route",
            "point_count": 2,
            "distance_m": 100.0,
            "bbox_wgs84": {
                "min_lat": 24.0,
                "min_lon": 121.0,
                "max_lat": 24.001,
                "max_lon": 121.001,
            },
        },
        "source_artifacts": [
            {
                "artifact_id": "artifact.gpx.synthetic",
                "kind": "gpx",
                "uri": "/tmp/synthetic-route.gpx",
                "media_type": "application/gpx+xml",
                "provenance": {
                    "source_ref": "artifact.gpx.synthetic",
                    "source_kind": "gpx",
                    "uri": "/tmp/synthetic-route.gpx",
                    "method": "pytest",
                },
            }
        ],
        "checkpoint_candidates": [
            {
                "candidate_id": "cp.start",
                "label": "Start",
                "review_state": "proposed",
                "confidence": "high",
                "lat": 24.0,
                "lon": 121.0,
                "route_point_index": 0,
                "checkpoint_type": "start",
                "source_refs": ["artifact.gpx.synthetic"],
            },
            {
                "candidate_id": "cp.finish",
                "label": "Finish",
                "review_state": "proposed",
                "confidence": "high",
                "lat": 24.001,
                "lon": 121.001,
                "route_point_index": 1,
                "checkpoint_type": "finish",
                "source_refs": ["artifact.gpx.synthetic"],
            },
        ],
        "segment_candidates": [
            {
                "candidate_id": "seg.001",
                "label": "Segment 001",
                "review_state": "proposed",
                "confidence": "high",
                "from_candidate_id": "cp.start",
                "to_candidate_id": "cp.finish",
                "route_point_start_index": 0,
                "route_point_end_index": 1,
                "distance_m": 100.0,
                "elevation_gain_m": 20.0,
                "elevation_loss_m": 0.0,
                "source_refs": ["artifact.gpx.synthetic"],
            }
        ],
    }


def _package_with_all_candidate_types() -> dict:
    package = _minimal_compile_package()
    package["retreat_route_candidates"] = [
        {
            "candidate_id": "retreat.001",
            "label": "Return to start",
            "review_state": "proposed",
            "confidence": "medium",
            "entry_checkpoint_candidate_id": "cp.start",
            "trigger_checkpoint_candidate_id": "cp.finish",
            "distance_m": 100.0,
            "expected_use": "both",
        }
    ]
    package["route_guide_timing_candidates"] = [
        {
            "candidate_id": "timing.001",
            "label": "Guide time",
            "review_state": "needs_review",
            "confidence": "medium",
            "segment_candidate_id": "seg.001",
            "route_guide_segment_time_minutes": 20,
        }
    ]
    return package


def _human_review(
    review_id: str,
    reviewed_ref: str,
    reviewed_ref_kind: str,
    decision: str,
) -> PreTripHumanReview:
    return PreTripHumanReview(
        review_id=review_id,
        reviewer_id="person.leader",
        reviewed_ref=reviewed_ref,
        reviewed_ref_kind=reviewed_ref_kind,
        reviewed_at="2026-05-14T10:00:00+08:00",
        decision=decision,
        source_candidate_snapshot_hash="a" * 64,
    )
