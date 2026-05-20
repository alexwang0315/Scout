import inspect
from pathlib import Path

import pytest
from pydantic import ValidationError

import pretrip_route_note_ln_proposals
from pretrip_route_note_candidates import (
    RouteNoteBoundary,
    RouteNoteCandidate,
    RouteNoteCandidateSet,
    RouteNoteCounts,
)
from pretrip_route_note_ln_proposals import (
    RouteNoteLnProposalSet,
    build_route_note_ln_proposals,
    load_route_note_ln_proposals_from_route_note_fixture,
    route_note_ln_proposals_to_json,
)


ROOT = Path(__file__).resolve().parents[1]
ROUTE_NOTE_CANDIDATES = (
    ROOT
    / "tests"
    / "fixtures"
    / "pretrip"
    / "projects"
    / "chilai_nanhua_day1"
    / "candidates"
    / "route_note_candidates.json"
)


def test_builds_ln_proposals_from_existing_route_note_fixture():
    proposal_set = load_route_note_ln_proposals_from_route_note_fixture(
        ROUTE_NOTE_CANDIDATES
    )
    payload = proposal_set.model_dump(mode="json")

    assert payload["artifact_kind"] == "pretrip_route_note_ln_proposals"
    assert payload["status"] == "candidate_only"
    assert payload["source_artifact_id"] == (
        "route_note_candidates.chilai_nanhua_day1.rudy_like_gpx.v0"
    )
    assert payload["counts"]["source_route_note_count"] == 81
    assert payload["counts"]["source_potential_ln_signal_count"] == 21
    assert payload["counts"]["proposal_count"] == 21
    assert payload["counts"]["hint_coverage_proposal_count"] == 19
    assert payload["counts"]["warning_coverage_proposal_count"] == 2
    assert payload["counts"]["human_review_required_count"] == 21

    assert all(
        proposal["source_note_category"] in {"hazard_hint", "route_condition_hint"}
        for proposal in payload["proposals"]
    )
    assert {
        proposal["proposal_kind"] for proposal in payload["proposals"]
    } == {"hint_coverage", "warning_coverage"}


def test_ln_proposals_remain_review_gated_candidates_without_writeback():
    proposal_set = load_route_note_ln_proposals_from_route_note_fixture(
        ROUTE_NOTE_CANDIDATES
    )
    payload = proposal_set.model_dump(mode="json")

    assert payload["boundary"]["candidate_only"] is True
    assert payload["boundary"]["human_review_required_before_use"] is True
    assert payload["boundary"]["observed_fact_allowed"] is False
    assert payload["boundary"]["derived_measurement_allowed"] is False
    assert payload["boundary"]["package_mutation_allowed"] is False
    assert payload["boundary"]["mission_graph_mutation_allowed"] is False
    assert payload["boundary"]["runtime_mutation_allowed"] is False
    assert payload["boundary"]["phase1_runtime_mutation_allowed"] is False
    assert payload["boundary"]["phase2_writeback_allowed"] is False
    assert payload["boundary"]["raw_gpx_embedded"] is False

    assert all(proposal["human_review_required"] is True for proposal in payload["proposals"])
    assert all(proposal["candidate_only"] is True for proposal in payload["proposals"])
    assert all(
        proposal["scout_interpretation"] == "ModelInterpretation"
        for proposal in payload["proposals"]
    )
    assert all(
        proposal["observed_fact_candidate"] is False
        for proposal in payload["proposals"]
    )
    assert all(
        proposal["derived_measurement_candidate"] is False
        for proposal in payload["proposals"]
    )
    assert all(
        proposal["runtime_mutation_candidate"] is False
        for proposal in payload["proposals"]
    )
    assert all(
        proposal["phase1_runtime_mutation_candidate"] is False
        for proposal in payload["proposals"]
    )
    assert all(
        proposal["phase2_writeback_candidate"] is False
        for proposal in payload["proposals"]
    )
    assert all(proposal["raw_gpx_embedded"] is False for proposal in payload["proposals"])

    serialized = route_note_ln_proposals_to_json(proposal_set)
    assert "ObservedFact" not in serialized
    assert "DerivedMeasurement" not in serialized
    assert ".gpx" not in serialized


def test_fixture_free_deterministic_build_from_route_note_candidate_set():
    source = _fixture_free_route_note_candidate_set()
    proposal_set = build_route_note_ln_proposals(source)
    serialized_once = route_note_ln_proposals_to_json(proposal_set)
    serialized_twice = route_note_ln_proposals_to_json(build_route_note_ln_proposals(source))

    assert serialized_once == serialized_twice
    assert proposal_set.counts.source_route_note_count == 3
    assert proposal_set.counts.source_potential_ln_signal_count == 2
    assert proposal_set.counts.proposal_count == 2
    assert [
        proposal.proposal_id for proposal in proposal_set.proposals
    ] == [
        "ln_proposal.route_note.fixture.wpt_000",
        "ln_proposal.route_note.fixture.wpt_001",
    ]
    assert [
        proposal.proposal_kind for proposal in proposal_set.proposals
    ] == ["warning_coverage", "hint_coverage"]


def test_schema_rejects_count_mismatches_and_boundary_claims():
    payload = load_route_note_ln_proposals_from_route_note_fixture(
        ROUTE_NOTE_CANDIDATES
    ).model_dump(mode="json")
    payload["counts"]["proposal_count"] = 1
    with pytest.raises(ValidationError):
        RouteNoteLnProposalSet.model_validate(payload)

    payload = load_route_note_ln_proposals_from_route_note_fixture(
        ROUTE_NOTE_CANDIDATES
    ).model_dump(mode="json")
    payload["boundary"]["phase2_writeback_allowed"] = True
    with pytest.raises(ValidationError):
        RouteNoteLnProposalSet.model_validate(payload)

    payload = load_route_note_ln_proposals_from_route_note_fixture(
        ROUTE_NOTE_CANDIDATES
    ).model_dump(mode="json")
    payload["proposals"][0]["human_review_required"] = False
    with pytest.raises(ValidationError):
        RouteNoteLnProposalSet.model_validate(payload)


def test_ln_proposals_have_no_crawler_or_network_source_strings():
    proposal_set = load_route_note_ln_proposals_from_route_note_fixture(
        ROUTE_NOTE_CANDIDATES
    )
    serialized = route_note_ln_proposals_to_json(proposal_set)
    source = inspect.getsource(pretrip_route_note_ln_proposals)

    for forbidden in [
        "http://",
        "https://",
        "requests.",
        "httpx.",
        "urlopen",
        "BeautifulSoup",
        "selenium",
        "playwright",
    ]:
        assert forbidden not in serialized
        assert forbidden not in source


def _fixture_free_route_note_candidate_set() -> RouteNoteCandidateSet:
    candidates = (
        RouteNoteCandidate(
            candidate_id="route_note.fixture.wpt_000",
            source_waypoint_index=0,
            lat=24.0,
            lon=121.0,
            normalized_note="崩塌勿右切",
            note_category="hazard_hint",
            potential_ln_signal=True,
            source_fields_present=("name",),
        ),
        RouteNoteCandidate(
            candidate_id="route_note.fixture.wpt_001",
            source_waypoint_index=1,
            lat=24.1,
            lon=121.1,
            normalized_note="腰繞路徑明顯",
            note_category="route_condition_hint",
            potential_ln_signal=True,
            source_fields_present=("name",),
        ),
        RouteNoteCandidate(
            candidate_id="route_note.fixture.wpt_002",
            source_waypoint_index=2,
            lat=24.2,
            lon=121.2,
            normalized_note="水源",
            note_category="camp_or_water_hint",
            potential_ln_signal=False,
            source_fields_present=("name",),
        ),
    )
    return RouteNoteCandidateSet(
        artifact_id="route_note_candidates.fixture.v0",
        project_id="fixture_project",
        source_artifact_id="source.fixture",
        source_uri="fixture:route-notes",
        source_sha256="0" * 64,
        counts=RouteNoteCounts(
            waypoint_count=3,
            note_candidate_count=3,
            hazard_hint_count=1,
            route_condition_hint_count=1,
            camp_or_water_hint_count=1,
            landmark_hint_count=0,
            potential_ln_signal_count=2,
        ),
        boundary=RouteNoteBoundary(),
        candidates=candidates,
    )
