from __future__ import annotations

from pathlib import Path

from assistant_models import AssistantSurface, ScoutAssistantQuery
from scout_ai_answer_synthesis import collect_and_synthesize_scout_ai_answer
from scout_ai_tool_contracts import tool_registry_output
from scout_ai_tool_executor import execute_scout_ai_tool
from scout_ai_tool_planner import plan_scout_ai_tools
from scout_cwa_environment_tool import (
    CWA_ENVIRONMENT_OUTPUT_KIND,
    CWA_ENVIRONMENT_TOOL_ID,
    assess_scout_cwa_environment,
)
from scout_gee_environment_tool import (
    GEE_ENVIRONMENT_OUTPUT_KIND,
    GEE_ENVIRONMENT_TOOL_ID,
    assess_scout_gee_environment,
)


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"


def test_cwa_environment_tool_reads_workspace_artifacts_without_network() -> None:
    payload = assess_scout_cwa_environment(
        PROJECT_ROOT,
        query="CWA QPF corridor summary?",
        reference_time="2026-06-24T06:00:00Z",
        limit=4,
    )

    assert payload["tool_id"] == CWA_ENVIRONMENT_TOOL_ID
    assert payload["external_api_calls_made"] is False
    assert payload["candidate_only"] is True
    assert payload["runtime_safety_truth"] is False
    assert payload["human_review_required"] is True
    assert payload["missing_fields"] == []
    assert payload["cwa_summary"]["warning_count"] == 1
    assert payload["cwa_summary"]["observation_count"] == 1
    assert payload["cwa_summary"]["qpf_grid_feature_count"] == 1
    assert payload["cwa_summary"]["qpf_route_timeline_event_count"] == 1
    assert payload["cwa_summary"]["qpf_corridor_summary"]["max_mm"] == 32.0
    assert "F-C0041-001" in payload["cwa_summary"]["datasets"]
    assert "QPF max=32.0mm" in payload["field_answer"]
    assert payload["boundary"]["live_safety_api_calls_allowed"] is False


def test_cwa_environment_tool_marks_old_workspace_evidence_partial() -> None:
    payload = assess_scout_cwa_environment(
        PROJECT_ROOT,
        query="目前 CWA QPF 還有效嗎？",
        reference_time="2026-07-11T00:00:00Z",
        limit=4,
    )

    assert payload["answerability"] == "cwa_environment_partial"
    assert "fresh_cwa_environment_evidence" in payload["missing_fields"]
    assert payload["decision"] == "DELAY"
    assert any("age_hours=" in warning for warning in payload["warnings"])


def test_gee_environment_tool_reads_workspace_artifacts_without_gee_init() -> None:
    payload = assess_scout_gee_environment(
        PROJECT_ROOT,
        query="SMAP GPM hydrologic evidence?",
        limit=4,
    )

    assert payload["tool_id"] == GEE_ENVIRONMENT_TOOL_ID
    assert payload["external_api_calls_made"] is False
    assert payload["earth_engine_initialized"] is False
    assert payload["candidate_only"] is True
    assert payload["runtime_safety_truth"] is False
    assert payload["human_review_required"] is True
    assert payload["missing_fields"] == []
    assert payload["gee_summary"]["smap_collection_id"] == "NASA/SMAP/SPL4SMGP/008"
    assert payload["gee_summary"]["gpm_collection_id"] == "NASA/GPM_L3/IMERG_V07"
    assert payload["gee_summary"]["smap_timeseries_count"] == 1
    assert payload["gee_summary"]["soil_moisture_grid_feature_count"] == 1
    assert payload["gee_summary"]["gpm_timeseries_count"] == 1
    assert payload["gee_summary"]["antecedent_rain_grid_feature_count"] == 1
    assert "NASA/SMAP/SPL4SMGP/008" in payload["field_answer"]
    assert "coarse 11km/3h candidate-only hydrologic background" in payload["field_answer"]
    assert "not a single-slope passability or runtime safety conclusion" in payload[
        "field_answer"
    ]
    smap_l4 = next(
        dataset
        for dataset in payload["gee_summary"]["supported_environment_datasets"]
        if dataset["collection_id"] == "NASA/SMAP/SPL4SMGP/008"
    )
    assert smap_l4["spatial_resolution_m"] == 11000
    assert smap_l4["human_review_required"] is True
    assert payload["boundary"]["live_safety_api_calls_allowed"] is False


def test_environment_tools_are_registered_and_executable() -> None:
    registry = tool_registry_output(include_not_implemented=False)
    by_id = {tool.tool_id: tool for tool in registry.tools}

    assert CWA_ENVIRONMENT_TOOL_ID in by_id
    assert GEE_ENVIRONMENT_TOOL_ID in by_id
    assert by_id[CWA_ENVIRONMENT_TOOL_ID].output_artifact_kind == CWA_ENVIRONMENT_OUTPUT_KIND
    assert by_id[GEE_ENVIRONMENT_TOOL_ID].output_artifact_kind == GEE_ENVIRONMENT_OUTPUT_KIND
    assert "scout.ai.cwa_weather.assess" in by_id[CWA_ENVIRONMENT_TOOL_ID].aliases
    assert "scout.ai.smap_gpm_environment.assess" in by_id[GEE_ENVIRONMENT_TOOL_ID].aliases

    cwa_result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.cwa_environment.assess",
            "project_root": str(PROJECT_ROOT),
            "query": "官方 CWA QPF 有什麼?",
            "limit": 3,
        }
    )
    assert cwa_result.status == "completed"
    assert cwa_result.output_artifact_kind == CWA_ENVIRONMENT_OUTPUT_KIND
    assert cwa_result.payload["cwa_summary"]["qpf_summary_available"] is True

    gee_result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.gee_environment.assess",
            "project_root": str(PROJECT_ROOT),
            "query": "GEE SMAP GPM 有什麼?",
            "limit": 3,
        }
    )
    assert gee_result.status == "completed"
    assert gee_result.output_artifact_kind == GEE_ENVIRONMENT_OUTPUT_KIND
    assert gee_result.payload["gee_summary"]["smap_collection_id"] == "NASA/SMAP/SPL4SMGP/008"


def test_planner_selects_separate_cwa_and_gee_environment_tools() -> None:
    cwa_plan = plan_scout_ai_tools(
        _query("中央氣象署 CWA QPF 對這條路線有什麼警示？"),
        project_root=PROJECT_ROOT,
    )
    cwa_ids = [item.tool_id for item in cwa_plan.selected_tools]
    assert CWA_ENVIRONMENT_TOOL_ID in cwa_ids

    gee_plan = plan_scout_ai_tools(
        _query("GEE SMAP 土壤含水和 GPM 累積雨量顯示什麼？"),
        project_root=PROJECT_ROOT,
    )
    gee_ids = [item.tool_id for item in gee_plan.selected_tools]
    assert GEE_ENVIRONMENT_TOOL_ID in gee_ids


def test_answer_synthesis_uses_environment_tool_field_answers() -> None:
    cwa_answer = collect_and_synthesize_scout_ai_answer(
        "中央氣象署 CWA QPF 對這條路線有什麼警示？",
        project_root=PROJECT_ROOT,
        surface=AssistantSurface.PRETRIP,
        limit=4,
    )
    assert cwa_answer.completed_source_count >= 1
    assert CWA_ENVIRONMENT_TOOL_ID in {source.tool_id for source in cwa_answer.sources}
    assert "CWA workspace evidence" in cwa_answer.answer
    assert cwa_answer.boundary.runtime_safety_truth is False

    gee_answer = collect_and_synthesize_scout_ai_answer(
        "GEE SMAP 土壤含水和 GPM 累積雨量顯示什麼？",
        project_root=PROJECT_ROOT,
        surface=AssistantSurface.PRETRIP,
        limit=4,
    )
    assert gee_answer.completed_source_count >= 1
    assert GEE_ENVIRONMENT_TOOL_ID in {source.tool_id for source in gee_answer.sources}
    assert "GEE workspace evidence" in gee_answer.answer
    assert "candidate-only hydrologic background" in gee_answer.answer
    assert gee_answer.boundary.runtime_safety_truth is False


def _query(question: str) -> ScoutAssistantQuery:
    return ScoutAssistantQuery(
        surface=AssistantSurface.PRETRIP,
        question=question,
        project_id="chilai_nanhua_day1",
    )
