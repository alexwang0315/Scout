import json
from pathlib import Path

from mission_models import RecordingPolicy, RecordingProfile, SegmentRequirement
from pretrip_segment_policy import (
    SegmentPolicyCandidateReport,
    build_chilai_segment_policy_candidates,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
PACKAGE_PATH = FIXTURE_ROOT / "outputs" / "pretrip_package.json"
SEGMENT_POLICY_CANDIDATES_PATH = FIXTURE_ROOT / "outputs" / "segment_policy_candidates.json"


def test_chilai_segment_policy_candidates_are_candidate_only_review_boundary():
    package = json.loads(PACKAGE_PATH.read_text())

    report = build_chilai_segment_policy_candidates(package)

    assert report.artifact_kind == "segment_policy_candidates"
    assert report.status == "candidate_only"
    assert report.counts == {
        "segment_policy_candidate_count": 109,
        "candidate_only_count": 109,
        "human_review_required_count": 109,
        "requires_daylight_count": 109,
        "retreat_available_count": 2,
        "signal_expected_count": 1,
    }
    assert all(candidate.candidate_only for candidate in report.candidates)
    assert all(candidate.human_review_required for candidate in report.candidates)
    assert all(candidate.compile_boundary == "candidate_only_not_runtime" for candidate in report.candidates)
    assert all(candidate.review_state == "proposed" for candidate in report.candidates)


def test_segment_policy_candidates_use_mission_model_compatible_payloads():
    report = build_chilai_segment_policy_candidates(json.loads(PACKAGE_PATH.read_text()))

    for candidate in report.candidates:
        requirement = SegmentRequirement.model_validate(candidate.requirement.model_dump(mode="json"))
        policy = RecordingPolicy.model_validate(candidate.recording_policy.model_dump(mode="json"))

        assert requirement.requires_daylight is True
        assert requirement.min_device_battery == 0.25
        assert requirement.min_estimated_human_energy == 0.40
        assert policy.normal_profile == RecordingProfile.MEDIUM
        assert policy.watch_profile == RecordingProfile.HIGH
        assert policy.concern_profile == RecordingProfile.RAW_LOCK
        assert policy.checkpoint_seals_segment is True


def test_chilai_segment_policy_candidate_fields_are_deterministic():
    report = build_chilai_segment_policy_candidates(json.loads(PACKAGE_PATH.read_text()))
    by_segment_id = {candidate.segment_candidate_id: candidate for candidate in report.candidates}

    first = by_segment_id["seg.001"]
    middle = by_segment_id["seg.005"]
    last = by_segment_id["seg.109"]

    assert first.requirement.expected_duration_seconds == 2555
    assert first.expected_duration_source == "route_geometry_distance_fallback"
    assert first.expected_duration_source_ref == "seg.001"
    assert first.requirement.retreat_available is True
    assert first.requirement.signal_expected is True
    assert first.recording_policy.raw_ring_seconds == 300

    assert middle.requirement.retreat_available is False
    assert middle.requirement.signal_expected is False
    assert middle.recording_policy.raw_ring_seconds == 240

    assert last.requirement.retreat_available is True
    assert last.requirement.signal_expected is False
    assert last.recording_policy.policy_id == "policy.chilai_nanhua_day1.seg.109.candidate"


def test_chilai_segment_policy_fixture_matches_builder_output():
    payload = json.loads(SEGMENT_POLICY_CANDIDATES_PATH.read_text())
    regenerated = build_chilai_segment_policy_candidates(json.loads(PACKAGE_PATH.read_text()))

    assert SegmentPolicyCandidateReport.model_validate(payload).model_dump(mode="json") == payload
    assert payload == regenerated.model_dump(mode="json")
