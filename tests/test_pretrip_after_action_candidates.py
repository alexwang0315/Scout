import json
from pathlib import Path

import pytest

from pretrip_after_action_candidates import (
    AfterActionBrainNodeKind,
    AfterActionEvidenceKind,
    AfterActionEvidenceRef,
    AfterActionNextPlanCandidateExport,
    build_scout_260512_after_action_next_plan_candidates,
    load_after_action_next_plan_candidate_export,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
EXPORT_PATH = FIXTURE_ROOT / "outputs" / "after_action_next_plan_candidates.json"
SOURCE_FIXTURE_PATHS = [
    ROOT / "tests" / "fixtures" / "field_cases" / "scout_260512_golden.json",
    ROOT / "tests" / "fixtures" / "mission_graph" / "scout_260512_field_mission.json",
    ROOT / "tests" / "fixtures" / "maps" / "scout_260512_overpass_map_context.geojson",
    ROOT / "tests" / "fixtures" / "route_progress" / "scout_260512_field_config.json",
]


def test_scout_260512_after_action_candidates_are_candidate_only():
    report = build_scout_260512_after_action_next_plan_candidates(ROOT)

    assert report.artifact_kind == "after_action_next_plan_candidates"
    assert report.project_id == "chilai_nanhua_day1"
    assert report.source_case_id == "scout_260512_field_golden"
    assert report.status == "candidate_only"
    assert report.raw_payloads_embedded is False
    assert report.observed_fact_writeback_allowed is False
    assert report.historical_evidence_mutation_allowed is False
    assert report.counts == {
        "candidate_count": 3,
        "source_ref_count": 5,
        "evidence_ref_count": 11,
        "human_review_required_count": 3,
        "incident_package_ref_count": 0,
        "deterministic_finding": 1,
        "reviewer_note": 1,
        "model_suggestion": 1,
        "source_route_ref_count": 1,
        "checkpoint_ref_count": 2,
        "segment_capsule_ref_count": 4,
        "map_evidence_ref_count": 1,
        "brain_node_ref_count": 3,
    }
    assert {candidate.finding_kind for candidate in report.candidates} == {
        "deterministic_finding",
        "reviewer_note",
        "model_suggestion",
    }
    assert all(candidate.candidate_only for candidate in report.candidates)
    assert all(candidate.human_review_required for candidate in report.candidates)
    assert all(
        candidate.future_mission_graph_compile == "blocked_until_human_review"
        for candidate in report.candidates
    )
    assert all(
        candidate.historical_evidence_mutation_allowed is False
        for candidate in report.candidates
    )


def test_after_action_candidate_fixture_matches_builder_output():
    fixture_payload = json.loads(EXPORT_PATH.read_text(encoding="utf-8"))
    fixture = load_after_action_next_plan_candidate_export(EXPORT_PATH)
    regenerated = build_scout_260512_after_action_next_plan_candidates(ROOT)

    assert fixture.model_dump(mode="json") == fixture_payload
    assert fixture_payload == regenerated.model_dump(mode="json")


def test_after_action_candidate_export_excludes_raw_samples_and_payloads():
    report = build_scout_260512_after_action_next_plan_candidates(ROOT)
    payload = report.model_dump(mode="json")
    serialized = report.model_dump_json()

    assert AfterActionNextPlanCandidateExport.model_validate(payload).model_dump(
        mode="json"
    ) == payload
    assert all(
        ref.raw_payload_embedded is False
        for candidate in report.candidates
        for ref in candidate.evidence_refs
    )

    for fragment in [
        "raw_samples",
        "incident_samples",
        "representative_samples",
        '"coordinates"',
        '"features"',
        "<trkpt",
        "PdrSample/",
        "source_files",
    ]:
        assert fragment not in serialized


def test_after_action_candidate_export_has_no_observed_fact_writeback():
    report = build_scout_260512_after_action_next_plan_candidates(ROOT)
    brain_refs = [
        ref
        for candidate in report.candidates
        for ref in candidate.evidence_refs
        if ref.evidence_kind == AfterActionEvidenceKind.BRAIN_NODE
    ]

    assert len(brain_refs) == 3
    assert {ref.brain_node_kind for ref in brain_refs} == {
        AfterActionBrainNodeKind.DERIVED_MEASUREMENT,
        AfterActionBrainNodeKind.HUMAN_REVIEW,
        AfterActionBrainNodeKind.MODEL_INTERPRETATION,
    }
    assert "ObservedFact" not in report.model_dump_json()
    assert all(candidate.observed_fact_writeback_allowed is False for candidate in report.candidates)


def test_builder_does_not_mutate_existing_after_action_or_admin_fixtures():
    before = {path: path.read_text(encoding="utf-8") for path in SOURCE_FIXTURE_PATHS}

    build_scout_260512_after_action_next_plan_candidates(ROOT)

    assert {path: path.read_text(encoding="utf-8") for path in SOURCE_FIXTURE_PATHS} == before


def test_brain_node_refs_cannot_claim_observed_fact_shape():
    with pytest.raises(ValueError, match="brain_node evidence refs must include brain_node_kind"):
        AfterActionEvidenceRef(
            ref_id="brain.missing_kind",
            evidence_kind=AfterActionEvidenceKind.BRAIN_NODE,
            source_path="tests/fixtures/field_cases/scout_260512_golden.json",
            source_id="brain.missing_kind",
            summary="Invalid brain node ref.",
        )
