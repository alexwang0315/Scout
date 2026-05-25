import inspect
from pathlib import Path

import pytest
from pydantic import ValidationError

import pretrip_route_note_candidates
from pretrip_route_note_candidates import (
    RouteNoteCandidateSet,
    build_route_note_candidates_from_gpx,
    load_route_note_candidates,
    route_note_candidates_to_json,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "pretrip"
    / "projects"
    / "chilai_nanhua_day1"
    / "candidates"
    / "route_note_candidates.json"
)


def test_extracts_gpx_waypoint_name_cmt_desc_as_route_note_candidates():
    candidate_set = build_route_note_candidates_from_gpx()
    payload = candidate_set.model_dump(mode="json")

    assert payload["artifact_kind"] == "pretrip_route_note_candidates"
    assert payload["status"] == "candidate_only"
    assert payload["source_artifact_id"] == "source.comparison.rudy_like_gpx"
    assert payload["counts"]["waypoint_count"] == 81
    assert payload["counts"]["note_candidate_count"] == 81
    assert payload["counts"]["hazard_hint_count"] == 3
    assert payload["counts"]["route_condition_hint_count"] == 20
    assert payload["counts"]["camp_or_water_hint_count"] == 8
    assert payload["counts"]["landmark_hint_count"] == 37
    assert payload["counts"]["potential_ln_signal_count"] == 23
    assert payload["counts"]["stale_route_note_count"] == 5
    assert payload["counts"]["route_note_time_unknown_count"] == 0

    hazard = next(
        candidate
        for candidate in payload["candidates"]
        if "大崩塌勿右切" in candidate["normalized_note"]
    )
    assert hazard["note_category"] == "hazard_hint"
    assert hazard["potential_ln_signal"] is True
    assert hazard["source_fields_present"] == ["name", "cmt", "desc"]


def test_route_note_candidates_remain_review_gated_model_interpretations():
    candidate_set = build_route_note_candidates_from_gpx()
    payload = candidate_set.model_dump(mode="json")

    assert payload["boundary"]["candidate_only"] is True
    assert payload["boundary"]["scout_interpretation_only"] is True
    assert payload["boundary"]["requires_human_review_before_ln_upgrade"] is True
    assert payload["boundary"]["observed_fact_allowed"] is False
    assert payload["boundary"]["derived_measurement_allowed"] is False
    assert payload["boundary"]["mission_graph_mutation_allowed"] is False
    assert payload["boundary"]["runtime_mutation_allowed"] is False
    assert payload["boundary"]["phase2_writeback_allowed"] is False
    assert payload["boundary"]["raw_gpx_embedded"] is False
    assert all(candidate["scout_interpretation"] == "ModelInterpretation" for candidate in payload["candidates"])
    assert all(candidate["requires_human_review"] is True for candidate in payload["candidates"])
    assert all(candidate["observed_fact_candidate"] is False for candidate in payload["candidates"])

    serialized = route_note_candidates_to_json(candidate_set)
    for forbidden in [
        "raw_gpx_embedded\": true",
        "observed_fact_candidate\": true",
        "derived_measurement_candidate\": true",
        "runtime_mutation_allowed\": true",
        "phase2_writeback_allowed\": true",
    ]:
        assert forbidden not in serialized

    source = inspect.getsource(pretrip_route_note_candidates)
    for forbidden_source in ["requests.", "httpx.", "urlopen", "BeautifulSoup", "Phase2Brain"]:
        assert forbidden_source not in source


def test_route_note_candidates_flag_stale_waypoint_times(tmp_path: Path):
    gpx = tmp_path / "route-notes-with-time.gpx"
    gpx.write_text(
        "\n".join(
            [
                '<?xml version="1.0" encoding="UTF-8"?>',
                '<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">',
                '<wpt lat="24.001" lon="121.001">',
                "<name>茂密林相</name><cmt>路跡較不明</cmt>",
                "<time>2018-01-01T00:00:00Z</time>",
                "</wpt>",
                '<wpt lat="24.002" lon="121.002">',
                "<name>新水源</name><cmt>需複查</cmt>",
                "<time>2026-05-01T00:00:00Z</time>",
                "</wpt>",
                '<wpt lat="24.003" lon="121.003">',
                "<name>高繞</name><cmt>崩塌地旁路線提示</cmt>",
                "</wpt>",
                "</gpx>",
            ]
        ),
        encoding="utf-8",
    )

    candidate_set = build_route_note_candidates_from_gpx(
        gpx,
        project_id="stale_route_notes",
        source_key="fixture",
        freshness_as_of="2026-05-22T00:00:00+00:00",
    )
    payload = candidate_set.model_dump(mode="json")

    assert payload["counts"]["stale_route_note_count"] == 1
    assert payload["counts"]["route_note_time_unknown_count"] == 1
    stale = payload["candidates"][0]
    recent = payload["candidates"][1]
    unknown = payload["candidates"][2]
    assert stale["route_note_freshness"] == "stale"
    assert stale["stale_route_note"] is True
    assert stale["route_note_age_days"] > 365 * 5
    assert recent["route_note_freshness"] == "recent"
    assert recent["stale_route_note"] is False
    assert unknown["route_note_freshness"] == "unknown"
    assert unknown["route_note_age_days"] is None
    assert unknown["note_category"] == "route_condition_hint"


def test_route_note_candidates_fixture_matches_builder_output():
    fixture_payload = FIXTURE_PATH.read_text(encoding="utf-8")
    fixture = load_route_note_candidates(FIXTURE_PATH)
    regenerated = build_route_note_candidates_from_gpx(
        freshness_as_of="2026-05-22T00:00:00+00:00"
    )

    assert fixture == regenerated
    assert fixture_payload == route_note_candidates_to_json(regenerated)


def test_route_note_candidate_schema_rejects_count_mismatches_and_runtime_claims():
    payload = build_route_note_candidates_from_gpx().model_dump(mode="json")
    payload["counts"]["potential_ln_signal_count"] = 1
    with pytest.raises(ValidationError):
        RouteNoteCandidateSet.model_validate(payload)

    payload = build_route_note_candidates_from_gpx().model_dump(mode="json")
    payload["boundary"]["runtime_mutation_allowed"] = True
    with pytest.raises(ValidationError):
        RouteNoteCandidateSet.model_validate(payload)
