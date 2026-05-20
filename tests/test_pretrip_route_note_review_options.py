import inspect

import pytest
from pydantic import ValidationError

import pretrip_route_note_review_options
from pretrip_route_note_ln_proposals import (
    RouteNoteLnProposal,
    RouteNoteLnProposalBoundary,
    RouteNoteLnProposalCounts,
    RouteNoteLnProposalSet,
)
from pretrip_route_note_review_options import (
    ALLOWED_ADMIN_DISPOSITIONS,
    RouteNoteReviewOptions,
    build_route_note_review_options,
    load_route_note_review_options,
    route_note_review_options_to_json,
)


def test_builds_one_review_options_record_per_ln_proposal():
    proposal_set = _fixture_free_ln_proposal_set()
    review_options = build_route_note_review_options(proposal_set)
    payload = review_options.model_dump(mode="json")

    assert payload["artifact_kind"] == "pretrip_route_note_review_options"
    assert payload["status"] == "candidate_only_draft_only"
    assert payload["source_artifact_id"] == "route_note_ln_proposals.fixture.v0"
    assert payload["counts"] == {
        "source_proposal_count": 2,
        "review_option_count": 2,
        "candidate_only_count": 2,
        "draft_only_count": 2,
        "decision_recorded_count": 0,
        "package_mutation_count": 0,
        "mission_graph_mutation_count": 0,
        "runtime_mutation_count": 0,
        "phase1_runtime_mutation_count": 0,
        "phase2_writeback_count": 0,
        "raw_gpx_payload_count": 0,
    }

    assert [option["source_proposal_id"] for option in payload["options"]] == [
        "ln_proposal.route_note.fixture.wpt_000",
        "ln_proposal.route_note.fixture.wpt_001",
    ]
    assert all(
        tuple(option["allowed_admin_dispositions"]) == ALLOWED_ADMIN_DISPOSITIONS
        for option in payload["options"]
    )


def test_review_options_are_candidate_drafts_without_recorded_decisions_or_writeback():
    review_options = build_route_note_review_options(_fixture_free_ln_proposal_set())
    payload = review_options.model_dump(mode="json")

    assert payload["boundary"]["candidate_only"] is True
    assert payload["boundary"]["draft_only"] is True
    assert payload["boundary"]["review_options_only"] is True
    assert payload["boundary"]["decision_recording_allowed"] is False
    assert payload["boundary"]["package_mutation_allowed"] is False
    assert payload["boundary"]["mission_graph_mutation_allowed"] is False
    assert payload["boundary"]["runtime_mutation_allowed"] is False
    assert payload["boundary"]["phase1_runtime_mutation_allowed"] is False
    assert payload["boundary"]["phase2_writeback_allowed"] is False
    assert payload["boundary"]["raw_gpx_embedded"] is False
    assert payload["boundary"]["crawler_or_network_source_allowed"] is False

    assert all(option["candidate_only"] is True for option in payload["options"])
    assert all(option["draft_only"] is True for option in payload["options"])
    assert all(option["decision_recorded"] is False for option in payload["options"])
    assert all(option["selected_admin_disposition"] is None for option in payload["options"])
    assert all(option["package_mutation_candidate"] is False for option in payload["options"])
    assert all(
        option["mission_graph_mutation_candidate"] is False
        for option in payload["options"]
    )
    assert all(option["runtime_mutation_candidate"] is False for option in payload["options"])
    assert all(
        option["phase1_runtime_mutation_candidate"] is False
        for option in payload["options"]
    )
    assert all(option["phase2_writeback_candidate"] is False for option in payload["options"])
    assert all(option["raw_gpx_embedded"] is False for option in payload["options"])


def test_review_options_json_helpers_are_deterministic(tmp_path):
    proposal_set = _fixture_free_ln_proposal_set()
    review_options = build_route_note_review_options(proposal_set)
    serialized_once = route_note_review_options_to_json(review_options)
    serialized_twice = route_note_review_options_to_json(
        build_route_note_review_options(proposal_set)
    )

    assert serialized_once == serialized_twice
    assert serialized_once.endswith("\n")

    path = tmp_path / "route_note_review_options.json"
    path.write_text(serialized_once, encoding="utf-8")
    assert route_note_review_options_to_json(load_route_note_review_options(path)) == serialized_once


def test_review_options_accept_dict_input_without_mutating_source():
    proposal_set = _fixture_free_ln_proposal_set()
    source_payload = proposal_set.model_dump(mode="json")

    review_options = build_route_note_review_options(source_payload)

    assert review_options.counts.review_option_count == 2
    assert source_payload == proposal_set.model_dump(mode="json")


def test_schema_rejects_count_drift_disposition_drift_and_decisions():
    payload = build_route_note_review_options(_fixture_free_ln_proposal_set()).model_dump(
        mode="json"
    )
    payload["counts"]["review_option_count"] = 1
    with pytest.raises(ValidationError):
        RouteNoteReviewOptions.model_validate(payload)

    payload = build_route_note_review_options(_fixture_free_ln_proposal_set()).model_dump(
        mode="json"
    )
    payload["options"][0]["allowed_admin_dispositions"] = ["ignore"]
    with pytest.raises(ValidationError):
        RouteNoteReviewOptions.model_validate(payload)

    payload = build_route_note_review_options(_fixture_free_ln_proposal_set()).model_dump(
        mode="json"
    )
    payload["options"][0]["decision_recorded"] = True
    with pytest.raises(ValidationError):
        RouteNoteReviewOptions.model_validate(payload)


def test_review_options_module_has_no_network_runtime_or_decision_store_wiring():
    source = inspect.getsource(pretrip_route_note_review_options)
    serialized = route_note_review_options_to_json(
        build_route_note_review_options(_fixture_free_ln_proposal_set())
    )

    for forbidden in [
        "http://",
        "https://",
        "requests.",
        "httpx.",
        "urlopen",
        "BeautifulSoup",
        "selenium",
        "playwright",
        "pretrip_review_decision",
        "pretrip_mission_compiler",
        "pretrip_review_resolver",
        "pretrip_models",
        "admin_api",
    ]:
        assert forbidden not in source
        assert forbidden not in serialized

    assert ".gpx" not in serialized


def _fixture_free_ln_proposal_set() -> RouteNoteLnProposalSet:
    proposals = (
        RouteNoteLnProposal(
            proposal_id="ln_proposal.route_note.fixture.wpt_000",
            source_route_note_candidate_id="route_note.fixture.wpt_000",
            source_waypoint_index=0,
            lat=24.0,
            lon=121.0,
            source_note_category="hazard_hint",
            proposal_kind="warning_coverage",
            proposed_coverage_label="route_note_warning_coverage",
            route_note_summary="崩塌勿右切",
        ),
        RouteNoteLnProposal(
            proposal_id="ln_proposal.route_note.fixture.wpt_001",
            source_route_note_candidate_id="route_note.fixture.wpt_001",
            source_waypoint_index=1,
            lat=24.1,
            lon=121.1,
            source_note_category="route_condition_hint",
            proposal_kind="hint_coverage",
            proposed_coverage_label="route_note_hint_coverage",
            route_note_summary="腰繞路徑明顯",
        ),
    )
    return RouteNoteLnProposalSet(
        artifact_id="route_note_ln_proposals.fixture.v0",
        project_id="fixture_project",
        source_artifact_id="route_note_candidates.fixture.v0",
        counts=RouteNoteLnProposalCounts(
            source_route_note_count=2,
            source_potential_ln_signal_count=2,
            proposal_count=2,
            hint_coverage_proposal_count=1,
            warning_coverage_proposal_count=1,
            human_review_required_count=2,
        ),
        boundary=RouteNoteLnProposalBoundary(),
        proposals=proposals,
    )
