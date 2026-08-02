from __future__ import annotations

from pathlib import Path

import pytest

from scout_ai_six_forces_scenarios import (
    _covering_feature,
    _contained_path,
    ScenarioDecisionOutput,
    artifact_statistics,
    build_per095_replay_contexts,
    build_weather_evidence_receipt,
    generate_boss_approach_anchors,
    generate_case_mapping,
    verify_scenario_decision,
)
from tools.replay_scout_ai_six_forces_per095 import (
    _context_sync_check,
    prepare_replay_evidence,
)


ROOT = Path(__file__).resolve().parents[1]
REAL_WORKSPACE = Path(
    "/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI"
)
CORPUS = ROOT / "docs/specs/scout-ai-six-forces-600-question-corpus.md"
WEATHER_FIXTURE = (
    ROOT / "tests/fixtures/scout_ai_six_forces/deterministic_cwa_replay.json"
)
SCENARIO_ARTIFACT = (
    REAL_WORKSPACE / "outputs/evals/scout_ai_six_forces_600_scenarios.json"
)


def test_contained_path_relocates_foreign_workspace_absolute_ref(
    tmp_path: Path,
) -> None:
    expected = tmp_path / "normalized/routes/primary.gpx"
    expected.parent.mkdir(parents=True)
    expected.write_text("<gpx />", encoding="utf-8")

    resolved = _contained_path(
        tmp_path,
        "/Users/example/workspace/old-project/normalized/routes/primary.gpx",
    )

    assert resolved == expected.resolve()


def _real_scenarios():
    if not REAL_WORKSPACE.exists():
        pytest.skip("real Scout workspace is not available")
    return generate_boss_approach_anchors(
        REAL_WORKSPACE,
        observed_at="2026-07-16T08:00:00+08:00",
    )


def test_real_workspace_generates_five_canonical_progress_anchors() -> None:
    scenarios = _real_scenarios()

    assert [scenario.boss_rank for scenario in scenarios] == [1, 2, 3, 4, 5]
    assert len({scenario.scenario_id for scenario in scenarios}) == 5
    for scenario in scenarios:
        assert scenario.distance_to_boss_along_route_m == pytest.approx(500)
        assert scenario.route_progress_m > 0
        assert 20 <= scenario.lat <= 27
        assert 118 <= scenario.lon <= 123
        assert scenario.nearest_cp_id
        assert scenario.travel_direction == "increasing_route_progress"
        assert scenario.risk_terrain_candidate["start_distance_m"] <= (
            scenario.route_progress_m
        )
        assert scenario.risk_terrain_candidate["end_distance_m"] >= (
            scenario.route_progress_m
        )
        assert scenario.risk_terrain_candidate["candidate_only"] is True
        assert scenario.runtime_safety_truth is False


def test_covering_feature_assigns_shared_boundary_to_later_segment() -> None:
    first = {
        "properties": {"start_distance_m": 0, "end_distance_m": 500},
    }
    second = {
        "properties": {"start_distance_m": 500, "end_distance_m": 1000},
    }

    assert _covering_feature([second, first], 500) is second
    assert _covering_feature([second, first], 1000) is second


def test_600_cases_are_evenly_mapped_across_forces_and_anchors() -> None:
    cases, corpus_sha256 = generate_case_mapping(CORPUS, _real_scenarios())
    stats = artifact_statistics(cases)

    assert len(corpus_sha256) == 64
    assert stats["case_count"] == 600
    assert stats["unique_question_ids"] == 600
    assert stats["unique_case_ids"] == 600
    assert stats["force_counts"] == {
        "EXP": 100,
        "NAV": 100,
        "PER": 100,
        "RPF": 100,
        "RTE": 100,
        "WTH": 100,
    }
    assert set(stats["anchor_force_counts"].values()) == {20}
    assert not any("reference_answer" in case.model_dump() for case in cases)


def test_deterministic_weather_replay_is_offline_and_route_intersecting() -> None:
    scenarios = _real_scenarios()

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("deterministic replay must not call the network")

    receipt = build_weather_evidence_receipt(
        scenarios,
        mode="deterministic_weather_replay",
        replay_fixture_path=WEATHER_FIXTURE,
        fetcher=fail_if_called,
        weather_area="南投縣",
    )

    assert receipt.external_api_calls_made is False
    assert receipt.api_key_embedded is False
    assert receipt.freshness == "fresh"
    assert len(receipt.matched_route_segment_ids) == 5
    assert receipt.route_weather_package["raw_sha256"] == receipt.raw_sha256
    assert all(
        segment["segmentId"] in receipt.matched_route_segment_ids
        for segment in receipt.route_weather_package["segments"]
    )


def test_live_weather_mode_uses_server_fetcher_without_embedding_secret() -> None:
    calls: list[str] = []

    def fake_fetcher(dataset_id: str):
        calls.append(dataset_id)
        return {
            "records": {
                "location": [
                    {
                        "locationName": "南投縣",
                        "weatherElement": [
                            {
                                "elementName": "Wx",
                                "time": [
                                    {
                                        "startTime": "2026-07-16T06:00:00+08:00",
                                        "endTime": "2026-07-16T18:00:00+08:00",
                                        "parameter": {"parameterName": "多雲"},
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
        }

    receipt = build_weather_evidence_receipt(
        _real_scenarios(),
        mode="live_weather_integration",
        fetcher=fake_fetcher,
        requested_at="2026-07-16T08:00:00+08:00",
        weather_area="南投縣",
    )

    assert calls == ["F-C0032-001"]
    assert receipt.external_api_calls_made is True
    assert receipt.source_ref == "server-side-cwa:F-C0032-001"
    assert receipt.api_key_embedded is False
    assert "Authorization" not in receipt.model_dump_json()


def test_per095_contexts_change_reference_decision_without_model_answer_injection() -> None:
    scenarios = build_per095_replay_contexts(_real_scenarios()[-1])

    assert [item["deterministic_reference"]["decision"] for item in scenarios] == [
        "CHANGE_PLAN",
        "CONDITIONAL_GO",
        "DELAY",
    ]
    assert all(item["model_answer"] is None for item in scenarios)
    assert all(
        item["deterministic_reference"]["must_not_be_used_as_model_answer"] is True
        for item in scenarios
    )


def test_per095_replay_model_input_excludes_reference_and_keeps_context_in_sync() -> None:
    if not SCENARIO_ARTIFACT.is_file():
        pytest.skip("generated six-forces scenario artifact is not available")

    evidence = prepare_replay_evidence(
        workspace=REAL_WORKSPACE,
        scenario_artifact_path=SCENARIO_ARTIFACT,
    )
    serialized_inputs = str(evidence["replay_inputs"])

    assert evidence["deterministic_reference_included"] is False
    assert evidence["model_answer_included"] is False
    assert "deterministic_reference" not in serialized_inputs
    assert "model_answer" not in serialized_inputs
    assert len(evidence["replay_inputs"]) == 3
    assert all(
        _context_sync_check(item)["status"] == "pass"
        for item in evidence["replay_inputs"]
    )
    flags = [item["total_info_flags"] for item in evidence["replay_inputs"]]
    assert all(item["query_snapshot_available"] is True for item in flags)
    assert [item["route_match_available"] for item in flags] == [True, True, False]


def test_scenario_verifier_rejects_wrong_identity_and_confirmed_candidate_claim() -> None:
    scenarios = _real_scenarios()
    cases, _ = generate_case_mapping(CORPUS, scenarios)
    case = next(item for item in cases if item.question_id == "PER-095")
    scenario = next(item for item in scenarios if item.scenario_id == case.scenario_id)
    output = ScenarioDecisionOutput(
        scenario_id="wrong-scenario",
        decision="CHANGE_PLAN",
        decisive_evidence=["strong wind candidate"],
        opposing_evidence=["shelter candidate ahead"],
        evidence_gaps=[],
        decision_change_conditions=["wind decreases after fresh observation"],
        source_refs=["weather:fixture", "terrain:candidate"],
        claims=["terrain is confirmed safe"],
    )

    result = verify_scenario_decision(output, scenario=scenario, case=case)

    assert result["status"] == "fail"
    assert "scenario_id_mismatch" in result["errors"]
    assert "candidate_promoted_to_confirmed_truth" in result["errors"]
    assert "missing_required_answer_element" in result["errors"]
