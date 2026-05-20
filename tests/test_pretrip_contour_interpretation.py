import inspect
import json
from pathlib import Path

import pytest

import pretrip_contour_interpretation
from phase4_pretrip_release_check import build_release_check
from pretrip_artifact_manifest import build_pretrip_artifact_manifest
from pretrip_contour_interpretation import (
    ContourInterpretationCandidate,
    ContourInterpretationCandidateSet,
    load_contour_interpretation_candidate_set,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
PROJECT_PATH = FIXTURE_ROOT / "project.json"
CONTOUR_CANDIDATES = FIXTURE_ROOT / "outputs" / "contour_interpretation_candidates.json"


def test_contour_interpretation_fixture_is_candidate_only_not_observed_fact():
    candidate_set = load_contour_interpretation_candidate_set(CONTOUR_CANDIDATES)

    assert candidate_set.status == "candidate"
    assert candidate_set.not_observed_fact is True
    assert len(candidate_set.candidates) == 2
    assert {candidate.interpretation_mode for candidate in candidate_set.candidates} == {
        "manual",
        "ai_assisted",
    }
    assert all(candidate.status == "candidate" for candidate in candidate_set.candidates)
    assert all(candidate.not_observed_fact is True for candidate in candidate_set.candidates)
    assert all(candidate.admin_review_required is True for candidate in candidate_set.candidates)
    assert all(candidate.human_review_required is True for candidate in candidate_set.candidates)
    assert all(
        candidate.accepted_planning_assumption_allowed is False
        for candidate in candidate_set.candidates
    )
    assert all(
        candidate.review_lifecycle.lifecycle_status == "admin_review_pending"
        for candidate in candidate_set.candidates
    )
    assert all(
        candidate.review_lifecycle.review_decision is None
        for candidate in candidate_set.candidates
    )
    assert all(
        candidate.review_lifecycle.human_review_ref is None
        for candidate in candidate_set.candidates
    )
    assert "ObservedFact" not in json.dumps(candidate_set.model_dump(mode="json"))


def test_ai_assisted_contour_candidates_require_admin_review_before_use():
    candidate_set = load_contour_interpretation_candidate_set(CONTOUR_CANDIDATES)
    ai_candidates = [
        candidate
        for candidate in candidate_set.candidates
        if candidate.interpretation_mode == "ai_assisted"
    ]

    assert ai_candidates
    for candidate in ai_candidates:
        assert candidate.candidate_origin == "ai_assisted_model"
        assert candidate.admin_review_required is True
        assert candidate.human_review_required is True
        assert candidate.accepted_planning_assumption_allowed is False
        assert candidate.review_lifecycle.lifecycle_status == "admin_review_pending"
        assert candidate.review_lifecycle.review_decision is None
        assert candidate.review_lifecycle.human_review_ref is None


def test_contour_interpretation_fixture_does_not_embed_raw_image_or_payloads():
    payload_text = CONTOUR_CANDIDATES.read_text()
    payload = json.loads(payload_text)

    assert "artifact.photo.g11_hiking" in payload_text
    assert "/Users/alexwang0315/downloads/G11_hiking.jpg" not in payload_text
    assert "data:image" not in payload_text
    assert "base64," not in payload_text
    assert "JFIF" not in payload_text
    assert "Exif" not in payload_text
    assert "pixels" not in payload_text
    assert "raster" not in payload_text
    assert "content" not in payload
    assert "data" not in payload
    for candidate in payload["candidates"]:
        assert "content" not in candidate
        assert "data" not in candidate
        assert candidate["source_artifact_refs"]["image_artifact_ref"] == "artifact.photo.g11_hiking"


def test_contour_interpretation_has_no_extraction_or_crawling_dependencies():
    source = inspect.getsource(pretrip_contour_interpretation)

    forbidden_fragments = [
        "requests",
        "httpx",
        "urlopen",
        "BeautifulSoup",
        "pytesseract",
        "PIL",
        "cv2",
        "openai",
    ]
    for fragment in forbidden_fragments:
        assert fragment not in source


def test_fixture_project_manifest_and_release_check_are_compatible():
    project = json.loads(PROJECT_PATH.read_text())
    assert project["contour_interpretation_candidate_count"] == 2
    assert project["contour_interpretation_candidates_ref"] == (
        "outputs/contour_interpretation_candidates.json"
    )

    manifest = build_pretrip_artifact_manifest(PROJECT_PATH).to_dict()
    by_kind = {artifact["artifact_kind"]: artifact for artifact in manifest["artifacts"]}
    artifact = by_kind["contour_interpretation_candidates"]
    assert artifact["ref"] == "outputs/contour_interpretation_candidates.json"
    assert artifact["status"] == "candidate"
    assert artifact["candidate_count"] == 2
    assert artifact["not_observed_fact"] is True
    assert artifact["human_review_required_count"] == 2

    release = build_release_check(ROOT)
    check = release["checks"]["contour_interpretation_candidates"]
    assert check["ok"] is True
    assert check["missing"] == []
    assert check["status"] == "candidate"
    assert check["candidate_count"] == 2
    assert check["expected_count"] == 2
    assert check["observed_fact_count"] == 0
    assert check["raw_payload_keys"] == []
    assert check["forbidden_fragment_count"] == 0


def test_schema_rejects_non_candidate_or_observed_fact_claims():
    payload = json.loads(CONTOUR_CANDIDATES.read_text())

    payload["status"] = "reviewed"
    with pytest.raises(ValueError):
        ContourInterpretationCandidateSet.model_validate(payload)

    payload = json.loads(CONTOUR_CANDIDATES.read_text())
    payload["not_observed_fact"] = False
    with pytest.raises(ValueError):
        ContourInterpretationCandidateSet.model_validate(payload)

    payload = json.loads(CONTOUR_CANDIDATES.read_text())
    payload["candidates"][0]["not_observed_fact"] = False
    with pytest.raises(ValueError):
        ContourInterpretationCandidateSet.model_validate(payload)

    payload = json.loads(CONTOUR_CANDIDATES.read_text())
    payload["candidates"][0]["source_artifact_refs"]["image_artifact_ref"] = "artifact.photo.other"
    with pytest.raises(ValueError, match="G11_hiking"):
        ContourInterpretationCandidateSet.model_validate(payload)


def test_schema_gates_accepted_planning_assumptions_behind_human_review():
    candidate = json.loads(CONTOUR_CANDIDATES.read_text())["candidates"][1]

    candidate["status"] = "accepted"
    candidate["accepted_planning_assumption_allowed"] = True
    candidate["review_lifecycle"] = {
        "lifecycle_status": "accepted_after_human_review",
        "review_decision": "accepted",
        "human_review_ref": None,
        "corrected_candidate_ref": None,
    }
    with pytest.raises(ValueError, match="HumanReview"):
        ContourInterpretationCandidate.model_validate(candidate)

    candidate["review_lifecycle"]["human_review_ref"] = "human_review.contour.g11.seg_006_008"
    accepted = ContourInterpretationCandidate.model_validate(candidate)
    assert accepted.status == "accepted"
    assert accepted.accepted_planning_assumption_allowed is True
