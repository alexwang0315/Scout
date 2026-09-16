
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scout_ai_answer_synthesis import collect_and_synthesize_scout_ai_answer
from scout_ai_full_workflow import run_scout_ai_full_workflow
from scout_cwa_environment_tool import CWA_ENVIRONMENT_TOOL_ID
from scout_gee_environment_tool import GEE_ENVIRONMENT_TOOL_ID
from scout_weather_window_tool import WEATHER_WINDOW_TOOL_ID
from weather_workflow_fixtures import (
    REFERENCE_TIME,
    WEATHER_TOOLS,
    assert_exact_weather_execution,
    weather_tool_calls,
    write_reviewed_weather_project,
    write_reviewed_route_context_project,
)

CWA_REQUIRED_ARTIFACTS = {
    "environment_evidence_package",
    "environment_factor_matrix",
    "go_no_go_review_draft",
    "cwa_weather_evidence",
    "cwa_warnings_geojson",
    "cwa_observations_geojson",
    "cwa_qpf_grid",
    "cwa_qpf_route_timeline",
    "cwa_qpf_corridor_summary",
    "cwa_forecast_timeline",
    "cwa_astronomy_timeline",
    "cwa_tide_marine_timeline",
}


@pytest.mark.parametrize("profile,query,decision", [
    ("thunderstorm", "午後雷雨是否要改變計畫?", "CHANGE_PLAN"),
    ("heat", "高溫曝曬，天氣決策怎麼看？", "CHANGE_PLAN"),
    ("disagreement", "預報來源不一致，天氣決策怎麼看？", "DELAY"),
])
@pytest.mark.parametrize("complete_cwa", [True, False], ids=["complete", "missing-cwa"])
def test_reviewed_weather_does_not_hide_selected_environment_gaps(
    tmp_path, weather_tool_calls, profile, query, decision, complete_cwa,
):
    root = write_reviewed_weather_project(
        tmp_path, profile=profile, include_cwa=complete_cwa, include_gee=False,
    )
    result = run_scout_ai_full_workflow(
        query, project_root=root, reference_time=REFERENCE_TIME,
    )
    assert_exact_weather_execution(result, WEATHER_TOOLS, weather_tool_calls)
    sources = {item["tool_id"]: item for item in result.sources}
    weather = sources[WEATHER_WINDOW_TOOL_ID]
    assert weather["missing_fields"] == []
    assert weather["top_result_summary"]["decision"] == decision
    assert result.boundary.runtime_safety_truth is False
    if complete_cwa:
        assert result.answerability == "evidence_available"
        assert result.missing_evidence_count == 0
        assert sources[CWA_ENVIRONMENT_TOOL_ID]["missing_fields"] == []
        assert result.decision_output["answerSourceToolId"] == WEATHER_WINDOW_TOOL_ID
    else:
        assert result.answerability == "partial_evidence_with_missing_context"
        assert result.missing_evidence_count == 1
        assert set(sources[CWA_ENVIRONMENT_TOOL_ID]["missing_fields"]) == CWA_REQUIRED_ARTIFACTS
        assert {item["tool_id"] for item in result.missing_evidence} == {CWA_ENVIRONMENT_TOOL_ID}
        assert result.decision_output["decision"] == "DELAY"
        # An independently valid route package does not make uncollected CWA
        # evidence present; the original route-local result remains reviewable.
        assert weather["top_result_summary"]["decision_output"]["runtimeSafetyTruth"] is False


@pytest.mark.parametrize("kind", ["future-issued", "expired-window"])
def test_reviewed_weather_requires_valid_acquisition_and_forecast_time(
    tmp_path, weather_tool_calls, kind,
):
    root = write_reviewed_weather_project(
        tmp_path, profile="thunderstorm", include_cwa=True, include_gee=False,
    )
    path = root / "outputs/route_weather_package.json"
    package = json.loads(path.read_text())
    if kind == "future-issued":
        package["issued_at"] = "2026-06-25T05:00:00Z"
        # Keep generatedAt in the past to ensure repackaging cannot hide issue time.
    else:
        package["valid_to"] = "2026-06-24T05:30:00Z"
        package["validUntil"] = "2026-06-24T05:30:00Z"
    path.write_text(json.dumps(package))
    result = collect_and_synthesize_scout_ai_answer(
        "路線天氣證據是否仍然有效？", project_root=root, reference_time=REFERENCE_TIME,
    )
    assert_exact_weather_execution(result, WEATHER_TOOLS, weather_tool_calls)
    weather = next(item for item in result.sources if item.tool_id == WEATHER_WINDOW_TOOL_ID)
    assert "fresh_route_weather_evidence" in weather.missing_fields
    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.missing_evidence_count == 1
    assert result.decision_output["decision"] == "DELAY"
    assert result.boundary.runtime_safety_truth is False


def test_future_forecast_window_can_be_prepared_from_already_available_weather(
    tmp_path, weather_tool_calls,
):
    root = write_reviewed_weather_project(
        tmp_path, profile="thunderstorm", include_cwa=True, include_gee=False,
    )
    path = root / "outputs/route_weather_package.json"
    package = json.loads(path.read_text())
    package["valid_from"] = "2026-06-25T00:00:00Z"
    package["weather_window"]["valid_from"] = "2026-06-25T00:00:00Z"
    path.write_text(json.dumps(package))
    result = collect_and_synthesize_scout_ai_answer(
        "午後雷雨是否要改變計畫?", project_root=root, reference_time=REFERENCE_TIME,
    )
    assert_exact_weather_execution(result, WEATHER_TOOLS, weather_tool_calls)
    assert result.answerability == "evidence_available"
    assert result.missing_evidence_count == 0
    assert result.decision_output["decision"] == "CHANGE_PLAN"
    assert result.boundary.runtime_safety_truth is False


@pytest.mark.parametrize("kind", ["disagreement", "future-issued", "expired-window"])
def test_stronger_cwa_pressure_is_retained_beside_route_local_weather(
    tmp_path, weather_tool_calls, kind,
):
    root = write_reviewed_weather_project(
        tmp_path,
        profile="disagreement" if kind == "disagreement" else "thunderstorm",
        include_cwa=True,
        include_gee=False,
        cwa_profile="elevated",
    )
    if kind != "disagreement":
        path = root / "outputs/route_weather_package.json"
        package = json.loads(path.read_text())
        if kind == "future-issued":
            package["issued_at"] = "2026-06-25T05:00:00Z"
        else:
            package["valid_to"] = "2026-06-24T05:30:00Z"
            package["validUntil"] = "2026-06-24T05:30:00Z"
        path.write_text(json.dumps(package))
    result = run_scout_ai_full_workflow(
        "預報來源不一致，天氣決策怎麼看？" if kind == "disagreement" else "路線天氣證據是否仍然有效？",
        project_root=root,
        reference_time=REFERENCE_TIME,
    )
    assert_exact_weather_execution(result, WEATHER_TOOLS, weather_tool_calls)
    sources = {item["tool_id"]: item for item in result.sources}
    assert sources[WEATHER_WINDOW_TOOL_ID]["top_result_summary"]["decision"] == "DELAY"
    assert sources[CWA_ENVIRONMENT_TOOL_ID]["top_result_summary"]["decision"] == "CHANGE_PLAN"
    assert result.decision_output["answerSourceToolId"] == CWA_ENVIRONMENT_TOOL_ID
    assert result.decision_output["decision"] == "CHANGE_PLAN"
    if kind != "disagreement":
        assert "fresh_route_weather_evidence" in sources[WEATHER_WINDOW_TOOL_ID]["missing_fields"]
        assert result.answerability == "partial_evidence_with_missing_context"
    assert result.boundary.runtime_safety_truth is False


COMMON_ENVIRONMENT_ARTIFACTS = {
    "environment_evidence_package", "environment_factor_matrix", "go_no_go_review_draft",
}
GEE_REQUIRED_ARTIFACTS = COMMON_ENVIRONMENT_ARTIFACTS | {
    "gee_smap_l4_timeseries", "gee_smap_l4_corridor_summary", "gee_soil_moisture_grid",
    "gee_gpm_imerg_raw_summary", "gee_gpm_imerg_timeseries",
    "gee_gpm_imerg_corridor_summary", "gee_antecedent_rain_grid",
}


@pytest.mark.parametrize("include_cwa,include_gee", [
    (True, True), (False, True), (True, False), (False, False),
], ids=["complete", "missing-cwa", "missing-gee", "missing-both"])
def test_rain_terrain_workflow_executes_all_selected_sources_and_preserves_gaps(
    tmp_path, weather_tool_calls, include_cwa, include_gee,
):
    from scout_risk_score_tool import RISK_SCORE_TOOL_ID

    historical = Path(__file__).parent / "fixtures/pretrip/projects/chilai_nanhua_day1"
    root = write_reviewed_route_context_project(
        tmp_path, historical, profile="recent_rain",
        include_cwa=include_cwa, include_gee=include_gee,
    )
    result = run_scout_ai_full_workflow(
        "前 24 小時明顯降雨，溪水和崩塌風險是否升高？今天還能走嗎？",
        project_root=root, reference_time=REFERENCE_TIME,
    )
    expected = (RISK_SCORE_TOOL_ID, WEATHER_WINDOW_TOOL_ID,
                CWA_ENVIRONMENT_TOOL_ID, GEE_ENVIRONMENT_TOOL_ID)
    assert_exact_weather_execution(result, expected, weather_tool_calls)
    sources = {item["tool_id"]: item for item in result.sources}
    assert sources[WEATHER_WINDOW_TOOL_ID]["missing_fields"] == []
    cwa_missing = set() if include_cwa else (
        CWA_REQUIRED_ARTIFACTS - {"cwa_weather_evidence"}
        - (COMMON_ENVIRONMENT_ARTIFACTS if include_gee else set())
    )
    # The imported weather_daylight placeholder is still a documented reader
    # fallback; the eight missing CWA-specific artifacts cannot disappear.
    gee_missing = set() if include_gee else (
        GEE_REQUIRED_ARTIFACTS - (COMMON_ENVIRONMENT_ARTIFACTS if include_cwa else set())
    )
    assert set(sources[CWA_ENVIRONMENT_TOOL_ID]["missing_fields"]) == cwa_missing
    assert set(sources[GEE_ENVIRONMENT_TOOL_ID]["missing_fields"]) == gee_missing
    assert result.missing_evidence_count == int(not include_cwa) + int(not include_gee)
    assert result.answerability == (
        "evidence_available" if include_cwa and include_gee
        else "partial_evidence_with_missing_context"
    )
    for request, response in weather_tool_calls:
        if request["tool_id"] in {CWA_ENVIRONMENT_TOOL_ID, GEE_ENVIRONMENT_TOOL_ID}:
            assert response["payload"]["candidate_only"] is True
            assert response["payload"]["runtime_safety_truth"] is False
            assert response["payload"]["external_api_calls_made"] is False
    assert result.boundary.runtime_safety_truth is False


@pytest.mark.parametrize("provider,tool_id,artifact,freshness_gap", [
    ("cwa", CWA_ENVIRONMENT_TOOL_ID, "qpf_corridor_summary.json", "fresh_cwa_environment_evidence"),
    ("gee", GEE_ENVIRONMENT_TOOL_ID, "smap_l4_corridor_summary.json", "fresh_gee_environment_evidence"),
])
@pytest.mark.parametrize("kind", ["future-generated-alias", "stale-request"])
def test_selected_regional_source_uses_the_explicit_workflow_clock(
    tmp_path, weather_tool_calls, provider, tool_id, artifact, freshness_gap, kind,
):
    from scout_risk_score_tool import RISK_SCORE_TOOL_ID

    historical = Path(__file__).parent / "fixtures/pretrip/projects/chilai_nanhua_day1"
    root = write_reviewed_route_context_project(tmp_path, historical, profile="recent_rain")
    path = root / "outputs/environment" / provider / artifact
    payload = json.loads(path.read_text())
    if kind == "future-generated-alias":
        payload["generated_at"] = "2026-06-25T05:00:00Z"
        assert payload["request_timestamp"] == "2026-06-24T05:00:00Z"
    else:
        payload["request_timestamp"] = "2026-06-22T05:00:00Z"
        payload["generated_at"] = "2026-06-24T05:00:00Z"
    path.write_text(json.dumps(payload))
    result = run_scout_ai_full_workflow(
        "前 24 小時明顯降雨，溪水和崩塌風險是否升高？今天還能走嗎？",
        project_root=root, reference_time=REFERENCE_TIME,
    )
    expected = (RISK_SCORE_TOOL_ID, WEATHER_WINDOW_TOOL_ID,
                CWA_ENVIRONMENT_TOOL_ID, GEE_ENVIRONMENT_TOOL_ID)
    assert_exact_weather_execution(result, expected, weather_tool_calls)
    sources = {item["tool_id"]: item for item in result.sources}
    assert set(sources[tool_id]["missing_fields"]) == {freshness_gap}
    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.missing_evidence_count == 1
    assert {item["tool_id"] for item in result.missing_evidence} == {tool_id}
    response = next(response for request, response in weather_tool_calls if request["tool_id"] == tool_id)
    assert response["payload"]["filters"]["reference_time"] == "2026-06-24T06:00:00+00:00"
    report = next(
        source for source in response["payload"]["source_report"]
        if source["source_path"].endswith("/" + artifact)
    )
    assert report["acquisition_timestamps"]["request_timestamp"] == payload["request_timestamp"]
    assert report["acquisition_timestamps"]["generated_at"] == payload["generated_at"]
    assert response["payload"]["external_api_calls_made"] is False
    assert result.boundary.runtime_safety_truth is False


@pytest.mark.parametrize("kind", ["future-issued", "expired-window"])
def test_query_reported_hazard_does_not_claim_fresh_weather_after_reassessment(
    tmp_path, weather_tool_calls, kind,
):
    root = write_reviewed_weather_project(
        tmp_path, profile="thunderstorm", include_cwa=True, include_gee=False,
    )
    path = root / "outputs/route_weather_package.json"
    package = json.loads(path.read_text())
    if kind == "future-issued":
        package["issued_at"] = "2026-06-25T05:00:00Z"
    else:
        package["valid_to"] = "2026-06-24T05:30:00Z"
        package["validUntil"] = "2026-06-24T05:30:00Z"
    path.write_text(json.dumps(package))
    result = run_scout_ai_full_workflow(
        "午後雷雨是否要改變計畫?", project_root=root, reference_time=REFERENCE_TIME,
    )
    assert_exact_weather_execution(result, WEATHER_TOOLS, weather_tool_calls)
    weather = next(source for source in result.sources if source["tool_id"] == WEATHER_WINDOW_TOOL_ID)
    assert weather["top_result_summary"]["decision"] == "CHANGE_PLAN"
    assert "fresh_route_weather_evidence" in weather["missing_fields"]
    assert result.answerability == "partial_evidence_with_missing_context"
    assert result.missing_evidence_count == 1
    assert result.boundary.runtime_safety_truth is False
