import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from application_router import ApplicationObservation
from assistant_api import create_assistant_app
from assistant_context import assistant_source_refs_from_context
from assistant_models import ScoutAssistantQuery, ScoutAssistantResponse
from scout_agent_builtin_tools import run_builtin_tool
from scout_agent_tools import load_tool_manifest
from assistant_skill_router import (
    PRETRIP_FULL_WORKFLOW_SOURCE_ID,
    PRETRIP_PLACE_TO_CP_SKILL_ID,
    PRETRIP_TOOL_PLANNER_SKILL_ID,
    augment_pretrip_sources_with_local_evidence_search,
)
from pretrip_assistant_context import build_pretrip_assistant_context
from scout_ai_assistant_workflow_eval import (
    ARTIFACT_KIND,
    CONTEXT_REGISTRY_SOURCE_ID,
    DEFAULT_SELECTED_WORKFLOW_CASE_IDS,
    REPORT_ARTIFACT_KIND,
    TOOL_REGISTRY_SOURCE_ID,
    ScoutAiAssistantWorkflowEvalCase,
    assert_answer_synthesis_workflow_artifact,
    assert_assistant_workflow_response,
    assert_full_workflow_artifact,
    build_selected_workflow_eval_cases,
    evaluate_answer_synthesis_workflow_artifact,
    evaluate_assistant_workflow_response,
    evaluate_full_workflow_artifact,
    render_workflow_eval_markdown,
    run_assistant_workflow_eval,
    write_workflow_eval_outputs,
)
from scout_ai_answer_synthesis import collect_and_synthesize_scout_ai_answer
from scout_ai_full_workflow import run_scout_ai_full_workflow
from scout_ai_question_eval import evaluate_question, load_question_corpus
from scout_ai_tool_planner import (
    ENERGY_VITALS_TOOL_ID,
    INS_DR_TRACE_TOOL_ID,
    LIVE_NAVIGATION_STATE_TOOL_ID,
    SAFETY_BOUNDARY_TOOL_ID,
    WEATHER_WINDOW_TOOL_ID,
)
from ingress_evidence import IngressTransport
from scout_risk_score_tool import RISK_SCORE_TOOL_ID
from scout_sensor_vitals_record import (
    append_sensor_vitals_records_jsonl,
    sensor_vitals_records_from_observations,
)
from scout_terrain_score_tool import TERRAIN_SCORE_TOOL_ID


ROOT = Path(__file__).resolve().parents[1]
CORPUS_PATH = ROOT / "docs" / "specs" / "scout-ai-200-question-corpus.json"
MANIFEST_PATH = (
    ROOT
    / "tools"
    / "scout_agent_tool_manifests"
    / "scout.ai.assistant_workflow_eval.run.json"
)
PROJECT_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"


class FailingProvider:
    def answer(self, query: ScoutAssistantQuery, *, sources=None):
        raise RuntimeError("provider unavailable")


def test_workflow_eval_passes_answerable_cp_question_from_200_question_rules():
    question = "黑水塘在第幾個 CP 附近？"
    question_eval = evaluate_question(
        {
            "id": "seed-008",
            "question": question,
            "category": "route_structure",
            "source_set": "assistant_seed_100",
        }
    )
    assert question_eval.answerability == "answerable_by_current_read_only_tools"
    assert "pydantic_ai.tool.search_scout_major_points.v0" in question_eval.current_tool_ids

    response = _query_pretrip(question)
    case = ScoutAiAssistantWorkflowEvalCase(
        case_id="seed-008",
        question=question,
        expected_answerability=question_eval.answerability,
        expected_source_ids=(PRETRIP_PLACE_TO_CP_SKILL_ID, "assistant_context.pretrip"),
        expected_limitation_fragments=(f"resolved_by={PRETRIP_PLACE_TO_CP_SKILL_ID}",),
        expected_answer_fragments=("CP 002", "candidate_only=true", "runtime_safety_truth=false"),
        expected_safe_failure=False,
    )

    result = assert_assistant_workflow_response(case, response)

    assert result["artifact_kind"] == ARTIFACT_KIND
    assert result["passed"] is True


def test_workflow_eval_passes_missing_weather_question_from_200_question_rules():
    question = "哪些 CP 附近適合紮營？"
    question_eval = evaluate_question(
        {
            "id": "seed-007",
            "question": question,
            "category": "route_structure",
            "source_set": "assistant_seed_100",
        }
    )
    assert question_eval.answerability == "requires_missing_evidence"
    assert WEATHER_WINDOW_TOOL_ID in question_eval.recommended_tool_ids
    assert "fresh_weather_or_nowcast_with_ttl" in question_eval.missing_evidence

    response = _query_pretrip(question)
    case = ScoutAiAssistantWorkflowEvalCase(
        case_id="seed-007",
        question=question,
        expected_answerability=question_eval.answerability,
        expected_source_ids=(
            TOOL_REGISTRY_SOURCE_ID,
            PRETRIP_TOOL_PLANNER_SKILL_ID,
            PRETRIP_FULL_WORKFLOW_SOURCE_ID,
            WEATHER_WINDOW_TOOL_ID,
        ),
        expected_missing_fields_by_source={
            WEATHER_WINDOW_TOOL_ID: ("provider", "ttl_s", "route_weather_package"),
        },
        expected_full_workflow_answerability="partial_evidence_with_missing_context",
        expected_full_workflow_source_tool_ids=(WEATHER_WINDOW_TOOL_ID,),
        expected_full_workflow_missing_fields_by_tool={
            WEATHER_WINDOW_TOOL_ID: ("provider", "ttl_s", "route_weather_package"),
        },
        expected_full_workflow_step_ids=(
            "context_registry_and_tool_plan",
            "evidence_collection",
            "answer_synthesis",
        ),
        expected_limitation_fragments=(f"resolved_by={PRETRIP_TOOL_PLANNER_SKILL_ID}",),
        expected_answer_fragments=(
            "registry planner fallback",
            "weather_placeholder_only",
            "provider",
            "ttl_s",
        ),
        expected_safe_failure=True,
    )

    result = assert_assistant_workflow_response(case, response)

    assert result["artifact_kind"] == ARTIFACT_KIND
    assert result["passed"] is True
    assert CONTEXT_REGISTRY_SOURCE_ID in result["source_ids"]
    assert TOOL_REGISTRY_SOURCE_ID in result["source_ids"]
    assert result["context_registry"]["runtime_safety_truth"] is False
    assert result["context_registry"]["source_count"] == 9
    assert result["context_registry"]["source_ids_by_domain"]["weather"] == [
        "scout.context.weather_window"
    ]
    assert result["full_workflow"]["source_id"] == PRETRIP_FULL_WORKFLOW_SOURCE_ID
    assert result["full_workflow"]["artifact_kind"] == "scout_ai_full_workflow"
    assert result["full_workflow"]["answerability"] == "partial_evidence_with_missing_context"
    assert result["full_workflow"]["contract_gap_count"] == 0
    assert result["full_workflow"]["missing_evidence_count"] == 1
    assert result["full_workflow"]["workflow_policy"]["model_provider_used"] is False
    assert result["full_workflow"]["boundary"]["runtime_safety_truth"] is False
    assert result["full_workflow"]["sources"][0]["tool_id"] == WEATHER_WINDOW_TOOL_ID
    assert {"provider", "ttl_s"}.issubset(
        set(result["full_workflow"]["missing_evidence"][0]["missing_fields"])
    )
    registry_source = _source_by_id(response, TOOL_REGISTRY_SOURCE_ID)
    assert registry_source.context_summary["runtime_safety_truth"] is False
    assert WEATHER_WINDOW_TOOL_ID not in registry_source.context_summary[
        "missing_evidence_fields_by_tool"
    ]
    assert result["completed_tool_results"][0]["tool_id"] == WEATHER_WINDOW_TOOL_ID
    assert result["completed_tool_results"][0]["answerability"] == "weather_placeholder_only"
    assert result["contract_gap_sources"][0]["tool_id"] == WEATHER_WINDOW_TOOL_ID
    assert result["contract_gap_sources"][0]["status"] == "completed"
    assert {
        "provider",
        "ttl_s",
    }.issubset(set(result["contract_gap_sources"][0]["missing_fields"]))
    assert result["contract_gap_sources"][0]["runtime_safety_truth"] is False


def test_workflow_eval_reports_failure_for_missing_expected_source():
    response = _query_pretrip("這趟行程總共有幾個 CP？")
    case = ScoutAiAssistantWorkflowEvalCase(
        case_id="negative-missing-source",
        question="這趟行程總共有幾個 CP？",
        expected_answerability="answerable_by_current_read_only_tools",
        expected_source_ids=("missing.source",),
        expected_safe_failure=False,
    )

    result = evaluate_assistant_workflow_response(case, response)

    assert result["passed"] is False
    failed_checks = [check for check in result["checks"] if not check["passed"]]
    assert any(check["name"] == "expected_source_ids" for check in failed_checks)


def test_workflow_eval_reports_failure_when_full_workflow_source_is_missing():
    response = _query_pretrip("這趟行程總共有幾個 CP？")
    case = ScoutAiAssistantWorkflowEvalCase(
        case_id="negative-missing-full-workflow",
        question="這趟行程總共有幾個 CP？",
        expected_answerability="requires_missing_evidence",
        expected_full_workflow_answerability="missing_evidence",
    )

    result = evaluate_assistant_workflow_response(case, response)

    assert result["passed"] is False
    assert result["full_workflow"] is None
    failed_checks = [check for check in result["checks"] if not check["passed"]]
    assert any(check["name"] == "full_workflow_summary" for check in failed_checks)


def test_workflow_eval_passes_risk_and_terrain_selected_cases_from_corpus():
    cases = build_selected_workflow_eval_cases(
        load_question_corpus(CORPUS_PATH),
        case_ids=("seed-021", "seed-024"),
    )

    report = run_assistant_workflow_eval(
        cases,
        response_resolver=lambda case: _query_pretrip(case.question),
    )

    assert report["passed_count"] == 2
    assert report["failed_count"] == 0
    assert report["answerability_counts"] == {
        "answerable_by_current_read_only_tools": 2,
    }
    risk_result = _result_by_case(report, "seed-021")
    terrain_result = _result_by_case(report, "seed-024")
    assert CONTEXT_REGISTRY_SOURCE_ID in risk_result["source_ids"]
    assert CONTEXT_REGISTRY_SOURCE_ID in terrain_result["source_ids"]
    assert RISK_SCORE_TOOL_ID in risk_result["source_ids"]
    assert TERRAIN_SCORE_TOOL_ID in terrain_result["source_ids"]
    assert risk_result["context_registry"]["source_ids_by_domain"]["risk"] == [
        "scout.context.risk_scores"
    ]
    assert terrain_result["context_registry"]["source_ids_by_domain"]["terrain"] == [
        "scout.context.terrain_scores"
    ]
    assert risk_result["observability"]["safe_failure"] is True
    assert terrain_result["observability"]["safe_failure"] is True


def test_workflow_eval_checks_answer_synthesis_risk_terrain_artifact():
    question = "危險地形在哪些位置?"
    artifact = collect_and_synthesize_scout_ai_answer(
        question,
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )
    case = ScoutAiAssistantWorkflowEvalCase(
        case_id="answer-synthesis-risk-terrain",
        question=question,
        expected_answerability="answerable_by_current_read_only_tools",
        expected_safe_failure=True,
    )

    result = assert_answer_synthesis_workflow_artifact(
        case,
        artifact,
        expected_answer_synthesis_answerability="evidence_available",
        expected_completed_tool_ids=(RISK_SCORE_TOOL_ID, TERRAIN_SCORE_TOOL_ID),
        expected_answer_fragments=(
            "deterministic evidence was collected before synthesis",
            RISK_SCORE_TOOL_ID,
            "runtime safety truth",
        ),
        expected_limitation_fragments=(
            "no model provider was called",
            "Candidate/planning evidence was not promoted",
        ),
    )

    assert result["passed"] is True
    assert result["completed_source_ids"] == [
        RISK_SCORE_TOOL_ID,
        TERRAIN_SCORE_TOOL_ID,
    ]
    assert result["synthesis_policy"]["model_provider_used"] is False
    assert result["synthesis_policy"]["model_synthesis_performed"] is False
    assert result["boundary"]["runtime_safety_truth"] is False


def test_workflow_eval_checks_answer_synthesis_weather_missing_evidence_artifact():
    question = "明天午後雷雨是否要紮營?"
    artifact = collect_and_synthesize_scout_ai_answer(
        question,
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )
    case = ScoutAiAssistantWorkflowEvalCase(
        case_id="answer-synthesis-weather-gap",
        question=question,
        expected_answerability="requires_missing_evidence",
        expected_safe_failure=True,
    )

    result = evaluate_answer_synthesis_workflow_artifact(
        case,
        artifact,
        expected_answer_synthesis_answerability="partial_evidence_with_missing_context",
        expected_missing_fields_by_tool={
            WEATHER_WINDOW_TOOL_ID: ("provider", "ttl_s", "route_weather_package"),
        },
        expected_answer_fragments=(
            "weather_placeholder_only",
            "provider",
            "ttl_s",
            "runtime safety truth",
        ),
        expected_limitation_fragments=(
            "no model provider was called",
            "No /safety/* call",
        ),
    )

    assert result["passed"] is True
    assert result["completed_source_ids"] == [WEATHER_WINDOW_TOOL_ID]
    assert result["missing_evidence"][0]["tool_id"] == WEATHER_WINDOW_TOOL_ID
    assert {"provider", "ttl_s"}.issubset(
        set(result["missing_evidence"][0]["missing_fields"])
    )
    assert result["synthesis_policy"]["model_provider_used"] is False
    assert result["boundary"]["runtime_safety_truth"] is False


def test_workflow_eval_checks_full_workflow_risk_terrain_artifact():
    question = "危險地形在哪些位置?"
    artifact = run_scout_ai_full_workflow(
        question,
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )
    case = ScoutAiAssistantWorkflowEvalCase(
        case_id="full-workflow-risk-terrain",
        question=question,
        expected_answerability="answerable_by_current_read_only_tools",
        expected_safe_failure=True,
    )

    result = assert_full_workflow_artifact(
        case,
        artifact,
        expected_full_workflow_answerability="evidence_available",
        expected_completed_tool_ids=(RISK_SCORE_TOOL_ID, TERRAIN_SCORE_TOOL_ID),
        expected_answer_fragments=(
            "deterministic evidence was collected before synthesis",
            RISK_SCORE_TOOL_ID,
            "runtime safety truth",
        ),
        expected_limitation_fragments=(
            "no model provider was called",
            "Candidate/planning evidence was not promoted",
        ),
    )

    assert result["passed"] is True
    assert result["step_ids"] == [
        "context_registry_and_tool_plan",
        "evidence_collection",
        "answer_synthesis",
    ]
    assert result["completed_source_ids"] == [
        RISK_SCORE_TOOL_ID,
        TERRAIN_SCORE_TOOL_ID,
    ]
    assert result["workflow_policy"]["model_provider_used"] is False
    assert result["workflow_policy"]["model_synthesis_performed"] is False
    assert result["boundary"]["runtime_safety_truth"] is False


def test_workflow_eval_checks_full_workflow_weather_missing_evidence_artifact():
    question = "明天午後雷雨是否要紮營?"
    artifact = run_scout_ai_full_workflow(
        question,
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )
    case = ScoutAiAssistantWorkflowEvalCase(
        case_id="full-workflow-weather-gap",
        question=question,
        expected_answerability="requires_missing_evidence",
        expected_safe_failure=True,
    )

    result = evaluate_full_workflow_artifact(
        case,
        artifact,
        expected_full_workflow_answerability="partial_evidence_with_missing_context",
        expected_missing_fields_by_tool={
            WEATHER_WINDOW_TOOL_ID: ("provider", "ttl_s", "route_weather_package"),
        },
        expected_answer_fragments=(
            "weather_placeholder_only",
            "provider",
            "ttl_s",
            "runtime safety truth",
        ),
        expected_limitation_fragments=(
            "no model provider was called",
            "No /safety/* call",
        ),
    )

    assert result["passed"] is True
    assert result["completed_source_ids"] == [WEATHER_WINDOW_TOOL_ID]
    assert result["missing_evidence"][0]["tool_id"] == WEATHER_WINDOW_TOOL_ID
    assert {"provider", "ttl_s"}.issubset(
        set(result["missing_evidence"][0]["missing_fields"])
    )
    assert result["workflow_policy"]["model_provider_used"] is False
    assert result["boundary"]["runtime_safety_truth"] is False


def test_workflow_eval_checks_full_workflow_no_registry_tool_artifact():
    question = "請用一句話描述登山心情"
    artifact = run_scout_ai_full_workflow(
        question,
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )
    case = ScoutAiAssistantWorkflowEvalCase(
        case_id="full-workflow-no-registry-tool",
        question=question,
        expected_answerability="needs_general_model_or_new_spec",
        expected_safe_failure=False,
    )

    result = evaluate_full_workflow_artifact(
        case,
        artifact,
        expected_full_workflow_answerability="no_registry_tool_selected",
        expected_answer_fragments=(
            "No registry-backed Scout AI tool was selected",
            "no deterministic evidence",
            "runtime safety truth",
        ),
        expected_limitation_fragments=(
            "answerability=no_registry_tool_selected",
            "no model provider was called",
        ),
    )

    assert result["passed"] is True
    assert result["source_ids"] == []
    assert result["completed_source_ids"] == []
    assert result["missing_evidence"] == []
    assert result["workflow_policy"]["deterministic_tools_executed"] is False
    assert result["workflow_policy"]["model_provider_used"] is False
    assert result["boundary"]["runtime_safety_truth"] is False


def test_workflow_eval_passes_safety_boundary_candidate_ln_case_from_corpus():
    cases = build_selected_workflow_eval_cases(
        load_question_corpus(CORPUS_PATH),
        case_ids=("seed-030",),
    )

    report = run_assistant_workflow_eval(
        cases,
        response_resolver=lambda case: _query_pretrip(case.question),
    )

    assert report["passed_count"] == 1
    assert report["failed_count"] == 0
    result = _result_by_case(report, "seed-030")
    assert TOOL_REGISTRY_SOURCE_ID in result["source_ids"]
    assert RISK_SCORE_TOOL_ID in result["source_ids"]
    assert LIVE_NAVIGATION_STATE_TOOL_ID in result["source_ids"]
    assert SAFETY_BOUNDARY_TOOL_ID in result["source_ids"]
    checks = {check["name"]: check for check in result["checks"]}
    assert checks["expected_tool_registry_tool_ids_by_status"]["passed"] is True
    assert result["observability"]["safe_failure"] is True
    assert result["boundary"]["safety_mutation_allowed"] is False
    assert result["boundary"]["outbound_send_allowed"] is False


def test_workflow_eval_passes_ins_dr_trace_missing_evidence_case_from_corpus():
    cases = build_selected_workflow_eval_cases(
        load_question_corpus(CORPUS_PATH),
        case_ids=("seed-031",),
    )

    report = run_assistant_workflow_eval(
        cases,
        response_resolver=lambda case: _query_pretrip(case.question),
    )

    assert report["passed_count"] == 1
    assert report["failed_count"] == 0
    result = _result_by_case(report, "seed-031")
    assert PRETRIP_TOOL_PLANNER_SKILL_ID in result["source_ids"]
    assert INS_DR_TRACE_TOOL_ID in result["source_ids"]
    assert result["observability"]["safe_failure"] is True
    assert result["boundary"]["safety_mutation_allowed"] is False
    assert result["boundary"]["outbound_send_allowed"] is False


def test_workflow_eval_passes_energy_vitals_missing_evidence_case_from_corpus():
    cases = build_selected_workflow_eval_cases(
        load_question_corpus(CORPUS_PATH),
        case_ids=("seed-064",),
    )

    report = run_assistant_workflow_eval(
        cases,
        response_resolver=lambda case: _query_pretrip(case.question),
    )

    assert report["passed_count"] == 1
    assert report["failed_count"] == 0
    result = _result_by_case(report, "seed-064")
    assert TOOL_REGISTRY_SOURCE_ID in result["source_ids"]
    assert PRETRIP_TOOL_PLANNER_SKILL_ID in result["source_ids"]
    assert ENERGY_VITALS_TOOL_ID in result["source_ids"]
    checks = {check["name"]: check for check in result["checks"]}
    assert checks["expected_missing_fields"]["passed"] is True
    assert checks["expected_tool_registry_tool_ids_by_status"]["passed"] is True
    assert result["observability"]["safe_failure"] is True
    assert result["boundary"]["safety_mutation_allowed"] is False
    assert result["boundary"]["outbound_send_allowed"] is False


def test_workflow_eval_passes_energy_vitals_available_fixture(tmp_path):
    project_root = _write_energy_vitals_project_fixture(tmp_path)
    cases = build_selected_workflow_eval_cases(
        load_question_corpus(CORPUS_PATH),
        case_ids=("seed-064@energy_vitals_available",),
    )

    report = run_assistant_workflow_eval(
        cases,
        response_resolver=lambda case: _query_pretrip_for_project(
            case.question,
            project_root=project_root,
            project_id="energy_vitals_fixture",
        ),
    )

    assert report["passed_count"] == 1
    assert report["failed_count"] == 0
    assert report["answerability_counts"] == {
        "energy_vitals_advisory_available": 1,
    }
    result = _result_by_case(report, "seed-064@energy_vitals_available")
    assert TOOL_REGISTRY_SOURCE_ID in result["source_ids"]
    assert PRETRIP_TOOL_PLANNER_SKILL_ID in result["source_ids"]
    assert ENERGY_VITALS_TOOL_ID in result["source_ids"]
    assert result["completed_tool_results"] == [
        {
            "source_id": ENERGY_VITALS_TOOL_ID,
            "tool_id": ENERGY_VITALS_TOOL_ID,
            "status": "completed",
            "answerability": "energy_vitals_advisory_available",
            "missing_fields": [],
            "result_count": 1,
            "output_artifact_kind": "scout_ai_energy_vitals_tool_output",
            "runtime_safety_truth": False,
        }
    ]
    assert result["contract_gap_sources"] == []
    assert result["observability"]["safe_failure"] is True
    assert result["boundary"]["safety_mutation_allowed"] is False
    assert result["boundary"]["outbound_send_allowed"] is False

    response = _query_pretrip_for_project(
        cases[0].question,
        project_root=project_root,
        project_id="energy_vitals_fixture",
    )
    energy_source = _source_by_id(response, ENERGY_VITALS_TOOL_ID)
    latest = energy_source.context_summary["latest"]
    assert latest["answerability"] == "energy_vitals_advisory_available"
    assert latest["missing_fields"] == []
    assert latest["provided_fields"]["heart_rate_bpm"] == 130.0
    assert latest["provided_fields"]["reserve_score"] == 36
    assert latest["time_window"]["heart_rate_trend"]["trend"] == "decreasing"
    assert latest["boundary"]["medical_diagnosis"] is False
    assert latest["boundary"]["safety_api_called"] is False
    assert latest["boundary"]["outbound_send_performed"] is False


def test_workflow_eval_passes_ins_dr_trace_metrics_available_fixture(tmp_path):
    project_root = _write_trace_project_fixture(tmp_path)
    question = "GPS-only 軌跡和 INS/DR 軌跡差多少？"
    response = _query_pretrip_for_project(
        question,
        project_root=project_root,
        project_id="trace_fixture",
    )
    case = ScoutAiAssistantWorkflowEvalCase(
        case_id="seed-031-trace-fixture",
        question=question,
        expected_answerability="trace_metrics_available",
        expected_source_ids=(PRETRIP_TOOL_PLANNER_SKILL_ID, INS_DR_TRACE_TOOL_ID),
        expected_limitation_fragments=(f"resolved_by={PRETRIP_TOOL_PLANNER_SKILL_ID}",),
        expected_answer_fragments=(
            "registry planner fallback",
            "INS/DR trace summary",
            "paired=3",
            "max_deviation_m",
            "gps_dropout_segments=1",
            "not runtime safety truth",
        ),
        expected_safe_failure=True,
    )

    result = assert_assistant_workflow_response(case, response)
    trace_source = _source_by_id(response, INS_DR_TRACE_TOOL_ID)
    trace_latest = trace_source.context_summary["latest"]

    assert result["passed"] is True
    assert trace_latest["answerability"] == "trace_metrics_available"
    assert trace_latest["paired_fix_count"] == 3
    assert trace_latest["gps_dropout_segment_count"] == 1
    assert trace_latest["pdr_only_sample_count"] == 2
    assert trace_latest["metrics"]["max_deviation_m"] > 100.0
    assert trace_latest["boundary"]["runtime_safety_truth"] is False
    assert trace_latest["boundary"]["safety_api_called"] is False


def test_workflow_eval_runner_writes_bounded_json_and_markdown_report(tmp_path):
    cases = build_selected_workflow_eval_cases(
        load_question_corpus(CORPUS_PATH),
        case_ids=("seed-008", "seed-007"),
    )

    report = run_assistant_workflow_eval(
        cases,
        response_resolver=lambda case: _query_pretrip(case.question),
    )
    markdown = render_workflow_eval_markdown(report)
    output_json = tmp_path / "workflow-eval.json"
    output_markdown = tmp_path / "workflow-eval.md"

    write_workflow_eval_outputs(
        report,
        output_json=output_json,
        output_markdown=output_markdown,
    )

    assert report["artifact_kind"] == REPORT_ARTIFACT_KIND
    assert report["case_count"] == 2
    assert report["passed_count"] == 2
    assert report["failed_count"] == 0
    assert report["answerability_counts"] == {
        "answerable_by_current_read_only_tools": 1,
        "requires_missing_evidence": 1,
    }
    assert report["boundary"]["read_only"] is True
    assert report["boundary"]["safety_api_called"] is False
    assert report["boundary"]["outbound_send_performed"] is False
    assert "| seed-007 | `requires_missing_evidence` | pass |" in markdown
    assert "Context Registry" in markdown
    assert "domains=" in markdown
    assert "Completed Tools" in markdown
    assert "Contract Gaps" in markdown
    assert WEATHER_WINDOW_TOOL_ID in markdown
    assert "provider" in markdown
    assert "ttl_s" in markdown

    persisted = json.loads(output_json.read_text(encoding="utf-8"))
    assert persisted["passed_count"] == 2
    weather_result = _result_by_case(persisted, "seed-007")
    assert weather_result["context_registry"]["source_id"] == CONTEXT_REGISTRY_SOURCE_ID
    assert weather_result["contract_gap_sources"][0]["tool_id"] == WEATHER_WINDOW_TOOL_ID
    assert weather_result["completed_tool_results"][0]["tool_id"] == WEATHER_WINDOW_TOOL_ID
    assert weather_result["completed_tool_results"][0]["answerability"] == (
        "weather_placeholder_only"
    )
    assert "Scout AI Assistant Workflow Eval Report" in output_markdown.read_text(
        encoding="utf-8"
    )


def test_selected_workflow_eval_cases_reject_unsupported_case():
    with pytest.raises(ValueError, match="no bounded workflow eval expectation"):
        build_selected_workflow_eval_cases(
            [
                {
                    "id": "field-055",
                    "question": "目前位置是不是偏離路徑？",
                    "category": "live_navigation",
                    "source_set": "field_questions",
                }
            ],
            case_ids=("field-055",),
        )


def test_workflow_eval_builtin_tool_manifest_and_payload_are_read_only(tmp_path):
    manifest = load_tool_manifest(MANIFEST_PATH)
    request_path = tmp_path / "workflow-eval-request.json"
    request_path.write_text(
        json.dumps(
            {
                "corpus_path": str(CORPUS_PATH),
                "project_root": str(PROJECT_ROOT),
                "project_id": "chilai_nanhua_day1",
                "case_ids": ["seed-008", "seed-007"],
                "limit": 3,
            }
        ),
        encoding="utf-8",
    )

    exit_code, payload = run_builtin_tool(
        ["ai-assistant-workflow-eval", "--input", str(request_path), "--json"]
    )

    assert manifest.id == "scout.ai.assistant_workflow_eval.run"
    assert manifest.mode == "local_evidence_query"
    assert manifest.allowed_writes == []
    assert "live.safety_api" in manifest.forbidden_writes
    assert "transport.egress" in manifest.forbidden_writes
    assert manifest.metadata["read_only"] is True
    assert exit_code == 0
    assert payload["artifact_kind"] == "scout_ai_assistant_workflow_eval_tool_output"
    assert payload["status"] == "completed"
    assert payload["report"]["artifact_kind"] == REPORT_ARTIFACT_KIND
    assert payload["report"]["case_count"] == 2
    assert payload["report"]["passed_count"] == 2
    assert payload["boundary"]["read_only"] is True
    assert payload["boundary"]["safety_api_called"] is False
    assert payload["boundary"]["outbound_send_performed"] is False
    assert "Scout AI Assistant Workflow Eval Report" in payload["markdown"]


def test_workflow_eval_builtin_tool_uses_default_selected_cases(tmp_path):
    request_path = tmp_path / "workflow-eval-default-request.json"
    request_path.write_text(
        json.dumps(
            {
                "corpus_path": str(CORPUS_PATH),
                "project_root": str(PROJECT_ROOT),
                "project_id": "chilai_nanhua_day1",
                "limit": 3,
            }
        ),
        encoding="utf-8",
    )

    exit_code, payload = run_builtin_tool(
        ["ai-assistant-workflow-eval", "--input", str(request_path), "--json"]
    )

    assert exit_code == 0
    assert payload["case_ids"] == list(DEFAULT_SELECTED_WORKFLOW_CASE_IDS)
    assert payload["report"]["case_count"] == len(DEFAULT_SELECTED_WORKFLOW_CASE_IDS)
    assert payload["report"]["passed_count"] == len(DEFAULT_SELECTED_WORKFLOW_CASE_IDS)
    assert "seed-030" in payload["markdown"]
    assert "seed-031" in payload["markdown"]


def test_workflow_eval_builtin_tool_supports_case_project_root_profiles(tmp_path):
    trace_project_root = _write_trace_project_fixture(tmp_path)
    request_path = tmp_path / "workflow-eval-profile-request.json"
    request_path.write_text(
        json.dumps(
            {
                "corpus_path": str(CORPUS_PATH),
                "project_root": str(PROJECT_ROOT),
                "project_id": "chilai_nanhua_day1",
                "case_ids": [
                    "seed-031",
                    "seed-031@trace_metrics_available",
                ],
                "case_project_roots": {
                    "seed-031@trace_metrics_available": str(trace_project_root),
                },
                "case_project_ids": {
                    "seed-031@trace_metrics_available": "trace_fixture",
                },
                "limit": 3,
            }
        ),
        encoding="utf-8",
    )

    exit_code, payload = run_builtin_tool(
        ["ai-assistant-workflow-eval", "--input", str(request_path), "--json"]
    )

    assert exit_code == 0
    assert payload["case_ids"] == [
        "seed-031",
        "seed-031@trace_metrics_available",
    ]
    assert payload["case_project_roots_configured"] == [
        "seed-031@trace_metrics_available",
    ]
    assert payload["report"]["case_count"] == 2
    assert payload["report"]["passed_count"] == 2
    assert payload["report"]["answerability_counts"] == {
        "requires_missing_evidence": 1,
        "trace_metrics_available": 1,
    }
    missing_result = _result_by_case(payload["report"], "seed-031")
    trace_result = _result_by_case(payload["report"], "seed-031@trace_metrics_available")
    assert INS_DR_TRACE_TOOL_ID in missing_result["source_ids"]
    assert INS_DR_TRACE_TOOL_ID in trace_result["source_ids"]
    assert "seed-031@trace_metrics_available" in payload["markdown"]


def test_default_selected_workflow_cases_include_route_weather_risk_and_terrain():
    assert DEFAULT_SELECTED_WORKFLOW_CASE_IDS == (
        "seed-001",
        "seed-008",
        "seed-007",
        "seed-021",
        "seed-024",
        "seed-064",
        "seed-030",
        "seed-031",
    )


def _query_pretrip(question: str) -> ScoutAssistantResponse:
    client = TestClient(
        create_assistant_app(
            provider=FailingProvider(),
            context_resolver=_pretrip_router_context_resolver(PROJECT_ROOT),
        )
    )
    response = client.post(
        "/assistant/query",
        json={
            "surface": "pretrip",
            "question": question,
            "project_id": "chilai_nanhua_day1",
        },
    )
    assert response.status_code == 200
    return ScoutAssistantResponse.model_validate(response.json())


def _query_pretrip_for_project(
    question: str,
    *,
    project_root: Path,
    project_id: str,
) -> ScoutAssistantResponse:
    client = TestClient(
        create_assistant_app(
            provider=FailingProvider(),
            context_resolver=_tool_plan_only_context_resolver(project_root),
        )
    )
    response = client.post(
        "/assistant/query",
        json={
            "surface": "pretrip",
            "question": question,
            "project_id": project_id,
        },
    )
    assert response.status_code == 200
    return ScoutAssistantResponse.model_validate(response.json())


def _pretrip_router_context_resolver(project_root: Path):
    def resolve(query: ScoutAssistantQuery):
        project_id = query.project_id or query.context_ref or project_root.name
        context = build_pretrip_assistant_context(
            project_id,
            project_root=project_root,
            selected_source_id=query.selected_artifact_id,
        )
        sources = assistant_source_refs_from_context(context, query=query)
        return augment_pretrip_sources_with_local_evidence_search(
            query,
            sources=sources,
            project_root=project_root,
            limit=3,
        )

    return resolve


def _tool_plan_only_context_resolver(project_root: Path):
    def resolve(query: ScoutAssistantQuery):
        return augment_pretrip_sources_with_local_evidence_search(
            query,
            sources=[],
            project_root=project_root,
            limit=3,
        )

    return resolve


def _result_by_case(report: dict, case_id: str) -> dict:
    matches = [result for result in report["results"] if result["case_id"] == case_id]
    assert len(matches) == 1
    return matches[0]


def _source_by_id(response: ScoutAssistantResponse, source_id: str):
    matches = [source for source in response.sources if source.source_id == source_id]
    assert len(matches) == 1
    return matches[0]


def _write_trace_project_fixture(tmp_path: Path) -> Path:
    project_root = tmp_path / "trace_project"
    output_dir = project_root / "outputs" / "navigation"
    output_dir.mkdir(parents=True)
    (project_root / "project.json").write_text(
        json.dumps({"project_id": "trace_fixture"}, ensure_ascii=False),
        encoding="utf-8",
    )
    _write_jsonl(
        output_dir / "ins_dr_estimates.jsonl",
        [
            {
                "timestamp_s": 0,
                "gps_lat": 24.0,
                "gps_lon": 121.0,
                "gps_horizontal_accuracy_m": 4.0,
                "estimate_lat": 24.0,
                "estimate_lon": 121.0,
                "estimate_source": "wearable_route_constrained",
                "primary_truth_source": "gnss_anchor",
            },
            {
                "timestamp_s": 1,
                "gps_lat": 24.0,
                "gps_lon": 121.0001,
                "gps_horizontal_accuracy_m": 5.0,
                "estimate_lat": 24.001,
                "estimate_lon": 121.0001,
                "estimate_source": "wearable_route_constrained",
                "primary_truth_source": "dead_reckoning",
                "pdr_delta_m": 11.0,
            },
            {
                "timestamp_s": 2,
                "estimate_lat": 24.0,
                "estimate_lon": 121.0,
                "estimate_source": "wearable_route_constrained",
                "primary_truth_source": "dead_reckoning",
                "pdr_delta_m": 10.0,
            },
            {
                "timestamp_s": 3,
                "estimate_lat": 24.001,
                "estimate_lon": 121.0001,
                "estimate_source": "wearable_route_constrained",
                "primary_truth_source": "dead_reckoning",
                "pdr_delta_m": 10.0,
            },
            {
                "timestamp_s": 4,
                "gps_lat": 24.0,
                "gps_lon": 121.0002,
                "gps_horizontal_accuracy_m": 4.0,
                "estimate_lat": 24.0,
                "estimate_lon": 121.0002,
                "estimate_source": "wearable_route_constrained",
                "primary_truth_source": "gnss_anchor",
            },
        ],
    )
    return project_root


def _write_energy_vitals_project_fixture(tmp_path: Path) -> Path:
    project_root = tmp_path / "energy_vitals_project"
    project_root.mkdir()
    (project_root / "project.json").write_text(
        json.dumps({"project_id": "energy_vitals_fixture"}, ensure_ascii=False),
        encoding="utf-8",
    )
    observations = [
        ApplicationObservation(
            observation_id="obs-energy-1",
            source_adapter="sensorlogger",
            ingress_transport=IngressTransport.WAN_MQTT,
            observation_name="energy_reserve",
            values={
                "heartRate": 150,
                "hrvMs": 48,
                "bodyBattery": 37,
                "paceMps": 0.72,
                "cadence": 88,
                "activityLoad": 128.0,
                "baselineWindowDays": 90,
                "reserveScore": 39,
                "reserveBand": "rest_suggested",
                "heartRateDriftRatio": 0.14,
            },
            observed_at="2026-06-07T08:01:00Z",
            timestamp_s=1780828860.0,
            received_at="2026-06-07T08:01:01Z",
            session_id="session-energy",
            device_id="watch-1",
            raw_evidence_refs=("ingress-energy:payload[1]",),
            payload_sha256="7" * 64,
            capability_tags=("health", "resource", "vitals"),
        ),
        ApplicationObservation(
            observation_id="obs-energy-2",
            source_adapter="sensorlogger",
            ingress_transport=IngressTransport.WAN_MQTT,
            observation_name="energy_reserve",
            values={
                "heartRate": 130,
                "hrvMs": 44,
                "bodyBattery": 34,
                "paceMps": 0.7,
                "cadence": 86,
                "activityLoad": 134.0,
                "baselineWindowDays": 90,
                "reserveScore": 36,
                "reserveBand": "rest_suggested",
                "heartRateDriftRatio": 0.16,
            },
            observed_at="2026-06-07T08:02:00Z",
            timestamp_s=1780828920.0,
            received_at="2026-06-07T08:02:01Z",
            session_id="session-energy",
            device_id="watch-1",
            raw_evidence_refs=("ingress-energy:payload[2]",),
            payload_sha256="8" * 64,
            capability_tags=("health", "resource", "vitals"),
        ),
    ]
    append_sensor_vitals_records_jsonl(
        project_root / "outputs" / "sensorlogger_mqtt_sensor_vitals_records.jsonl",
        sensor_vitals_records_from_observations(observations),
    )
    return project_root


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )
