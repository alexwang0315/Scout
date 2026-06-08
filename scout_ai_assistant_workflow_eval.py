from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from scout_ai_answer_synthesis import ScoutAiAnswerSynthesisOutput
from assistant_models import AssistantSourceRef, ScoutAssistantResponse
from assistant_skill_router import (
    PRETRIP_CONTEXT_REGISTRY_SOURCE_ID,
    PRETRIP_CP_COUNT_SKILL_ID,
    PRETRIP_FULL_WORKFLOW_SOURCE_ID,
    PRETRIP_PLACE_TO_CP_SKILL_ID,
    PRETRIP_TOOL_PLANNER_SKILL_ID,
)
from scout_ai_full_workflow import ScoutAiFullWorkflowOutput
from scout_ai_question_eval import evaluate_question
from scout_ai_tool_planner import (
    ENERGY_VITALS_TOOL_ID,
    INS_DR_TRACE_TOOL_ID,
    LIVE_NAVIGATION_STATE_TOOL_ID,
    SAFETY_BOUNDARY_TOOL_ID,
    WEATHER_WINDOW_TOOL_ID,
)
from scout_risk_score_tool import RISK_SCORE_TOOL_ID
from scout_terrain_score_tool import TERRAIN_SCORE_TOOL_ID


ARTIFACT_KIND = "scout_ai_assistant_workflow_eval"
ARTIFACT_VERSION = "scout_ai_assistant_workflow_eval.v0"
REPORT_ARTIFACT_KIND = "scout_ai_assistant_workflow_eval_report"
REPORT_ARTIFACT_VERSION = "scout_ai_assistant_workflow_eval_report.v0"
TOOL_REGISTRY_SOURCE_ID = "assistant_context.tool_registry"
CONTEXT_REGISTRY_SOURCE_ID = PRETRIP_CONTEXT_REGISTRY_SOURCE_ID
DEFAULT_SELECTED_WORKFLOW_CASE_IDS = (
    "seed-001",
    "seed-008",
    "seed-007",
    "seed-021",
    "seed-024",
    "seed-064",
    "seed-030",
    "seed-031",
)


@dataclass(frozen=True)
class ScoutAiAssistantWorkflowEvalCase:
    case_id: str
    question: str
    expected_answerability: str
    expected_source_ids: tuple[str, ...] = ()
    expected_missing_fields_by_source: dict[str, tuple[str, ...]] = field(
        default_factory=dict
    )
    expected_tool_registry_missing_fields_by_tool: dict[str, tuple[str, ...]] = field(
        default_factory=dict
    )
    expected_tool_registry_tool_ids_by_status: dict[str, tuple[str, ...]] = field(
        default_factory=dict
    )
    expected_context_registry_source_ids_by_domain: dict[str, tuple[str, ...]] = field(
        default_factory=dict
    )
    expected_full_workflow_answerability: str | None = None
    expected_full_workflow_source_tool_ids: tuple[str, ...] = ()
    expected_full_workflow_missing_fields_by_tool: dict[str, tuple[str, ...]] = field(
        default_factory=dict
    )
    expected_full_workflow_step_ids: tuple[str, ...] = ()
    expected_limitation_fragments: tuple[str, ...] = ()
    expected_answer_fragments: tuple[str, ...] = ()
    expected_safe_failure: bool | None = None
    require_read_only_boundary: bool = True


def build_selected_workflow_eval_cases(
    questions: Iterable[dict[str, Any]],
    *,
    case_ids: tuple[str, ...] = DEFAULT_SELECTED_WORKFLOW_CASE_IDS,
) -> list[ScoutAiAssistantWorkflowEvalCase]:
    by_id = {
        str(item.get("id") or item.get("question_id")): item
        for item in questions
        if isinstance(item, dict)
    }
    resolved_case_ids = [_split_case_profile(case_id)[0] for case_id in case_ids]
    missing_case_ids = [
        case_id
        for case_id, base_case_id in zip(case_ids, resolved_case_ids, strict=False)
        if base_case_id not in by_id
    ]
    if missing_case_ids:
        raise ValueError(f"missing workflow eval corpus case ids: {missing_case_ids}")
    return [
        _workflow_eval_case_from_question_item(
            by_id[base_case_id],
            requested_case_id=case_id,
            profile=profile,
        )
        for case_id, (base_case_id, profile) in zip(
            case_ids,
            (_split_case_profile(case_id) for case_id in case_ids),
            strict=False,
        )
    ]


def run_assistant_workflow_eval(
    cases: Iterable[ScoutAiAssistantWorkflowEvalCase],
    *,
    response_resolver: Callable[
        [ScoutAiAssistantWorkflowEvalCase], ScoutAssistantResponse
    ],
) -> dict[str, Any]:
    case_list = list(cases)
    results: list[dict[str, Any]] = []
    for case in case_list:
        try:
            response = response_resolver(case)
            result = evaluate_assistant_workflow_response(case, response)
        except Exception as exc:  # noqa: BLE001 - eval reports failures as data.
            result = _resolver_failure_result(case, exc)
        results.append(result)

    passed_count = sum(1 for result in results if result["passed"])
    answerability_counts: dict[str, int] = {}
    for case in case_list:
        answerability_counts[case.expected_answerability] = (
            answerability_counts.get(case.expected_answerability, 0) + 1
        )
    return {
        "artifact_kind": REPORT_ARTIFACT_KIND,
        "artifact_version": REPORT_ARTIFACT_VERSION,
        "case_count": len(case_list),
        "passed_count": passed_count,
        "failed_count": len(case_list) - passed_count,
        "answerability_counts": dict(sorted(answerability_counts.items())),
        "results": results,
        "boundary": _report_boundary(),
    }


def render_workflow_eval_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Scout AI Assistant Workflow Eval Report",
        "",
        f"- artifact_kind: `{report['artifact_kind']}`",
        f"- artifact_version: `{report['artifact_version']}`",
        f"- case_count: `{report['case_count']}`",
        f"- passed_count: `{report['passed_count']}`",
        f"- failed_count: `{report['failed_count']}`",
        "- boundary: read-only, no `/safety/*`, no Phase 1 mutation, no outbound send",
        "",
        "## Cases",
        "",
        "| Case | Answerability | Passed | Sources | Context Registry | Completed Tools | Contract Gaps | Failed Checks |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for result in report["results"]:
        failed_checks = [
            check["name"]
            for check in result.get("checks", [])
            if isinstance(check, dict) and not check.get("passed")
        ]
        lines.append(
            "| {case_id} | `{answerability}` | {passed} | {sources} | {context_registry} | {completed} | {gaps} | {failed} |".format(
                case_id=_escape_table(str(result["case_id"])),
                answerability=_escape_table(str(result["expected_answerability"])),
                passed="pass" if result["passed"] else "fail",
                sources=_escape_table(", ".join(result.get("source_ids", [])) or "-"),
                context_registry=_escape_table(
                    _markdown_context_registry_summary(result.get("context_registry"))
                ),
                completed=_escape_table(
                    _markdown_completed_tool_summary(result.get("completed_tool_results", []))
                ),
                gaps=_escape_table(
                    _markdown_contract_gap_summary(result.get("contract_gap_sources", []))
                ),
                failed=_escape_table(", ".join(failed_checks) or "-"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def write_workflow_eval_outputs(
    report: dict[str, Any],
    *,
    output_json: Path | str | None = None,
    output_markdown: Path | str | None = None,
) -> None:
    if output_json is not None:
        path = Path(output_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    if output_markdown is not None:
        path = Path(output_markdown)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_workflow_eval_markdown(report), encoding="utf-8")


def evaluate_assistant_workflow_response(
    case: ScoutAiAssistantWorkflowEvalCase,
    response: ScoutAssistantResponse,
) -> dict[str, Any]:
    checks = [
        _check_source_ids(case, response),
        _check_missing_fields(case, response),
        _check_tool_registry_missing_fields(case, response),
        _check_tool_registry_tool_ids_by_status(case, response),
        _check_context_registry_source_ids_by_domain(case, response),
        _check_full_workflow_summary(case, response),
        _check_limitation_fragments(case, response),
        _check_answer_fragments(case, response),
        _check_safe_failure(case, response),
        _check_read_only_boundary(case, response),
        _check_sources_are_not_runtime_truth(response),
    ]
    passed = all(check["passed"] for check in checks)
    return {
        "artifact_kind": ARTIFACT_KIND,
        "artifact_version": ARTIFACT_VERSION,
        "case_id": case.case_id,
        "question": case.question,
        "expected_answerability": case.expected_answerability,
        "passed": passed,
        "checks": checks,
        "source_ids": [source.source_id for source in response.sources],
        "context_registry": _context_registry_summary(response),
        "full_workflow": _full_workflow_summary(response),
        "completed_tool_results": _completed_tool_results(response),
        "contract_gap_sources": _contract_gap_sources(response),
        "limitations": list(response.limitations),
        "boundary": response.boundary.model_dump(mode="json"),
        "observability": response.observability.model_dump(mode="json")
        if response.observability
        else None,
    }


def assert_assistant_workflow_response(
    case: ScoutAiAssistantWorkflowEvalCase,
    response: ScoutAssistantResponse,
) -> dict[str, Any]:
    result = evaluate_assistant_workflow_response(case, response)
    if not result["passed"]:
        failed = [
            f"{check['name']}: {check['detail']}"
            for check in result["checks"]
            if not check["passed"]
        ]
        raise AssertionError(
            f"Scout AI workflow eval failed for {case.case_id}: "
            + "; ".join(failed)
        )
    return result


def evaluate_answer_synthesis_workflow_artifact(
    case: ScoutAiAssistantWorkflowEvalCase,
    artifact: ScoutAiAnswerSynthesisOutput | dict[str, Any],
    *,
    expected_answer_synthesis_answerability: str,
    expected_completed_tool_ids: tuple[str, ...] = (),
    expected_missing_fields_by_tool: dict[str, tuple[str, ...]] | None = None,
    expected_answer_fragments: tuple[str, ...] = (),
    expected_limitation_fragments: tuple[str, ...] = (),
) -> dict[str, Any]:
    parsed = _parse_answer_synthesis_artifact(artifact)
    checks = [
        _check_answer_synthesis_artifact_kind(parsed),
        _check_answer_synthesis_answerability(
            parsed,
            expected_answer_synthesis_answerability,
        ),
        _check_answer_synthesis_completed_tools(
            parsed,
            expected_completed_tool_ids,
        ),
        _check_answer_synthesis_missing_fields(
            parsed,
            expected_missing_fields_by_tool or {},
        ),
        _check_answer_synthesis_answer_fragments(
            parsed,
            expected_answer_fragments,
        ),
        _check_answer_synthesis_limitation_fragments(
            parsed,
            expected_limitation_fragments,
        ),
        _check_answer_synthesis_read_only_boundary(parsed),
        _check_answer_synthesis_sources_are_not_runtime_truth(parsed),
    ]
    passed = all(check["passed"] for check in checks)
    return {
        "artifact_kind": "scout_ai_answer_synthesis_workflow_eval",
        "artifact_version": "scout_ai_answer_synthesis_workflow_eval.v0",
        "case_id": case.case_id,
        "question": case.question,
        "expected_answerability": case.expected_answerability,
        "answer_synthesis_answerability": parsed.answerability,
        "passed": passed,
        "checks": checks,
        "source_ids": [source.tool_id for source in parsed.sources],
        "completed_source_ids": [
            source.tool_id
            for source in parsed.sources
            if source.collection_status == "completed"
        ],
        "missing_evidence": list(parsed.missing_evidence),
        "limitations": list(parsed.limitations),
        "boundary": parsed.boundary.model_dump(mode="json"),
        "synthesis_policy": parsed.synthesis_policy.model_dump(mode="json"),
    }


def assert_answer_synthesis_workflow_artifact(
    case: ScoutAiAssistantWorkflowEvalCase,
    artifact: ScoutAiAnswerSynthesisOutput | dict[str, Any],
    *,
    expected_answer_synthesis_answerability: str,
    expected_completed_tool_ids: tuple[str, ...] = (),
    expected_missing_fields_by_tool: dict[str, tuple[str, ...]] | None = None,
    expected_answer_fragments: tuple[str, ...] = (),
    expected_limitation_fragments: tuple[str, ...] = (),
) -> dict[str, Any]:
    result = evaluate_answer_synthesis_workflow_artifact(
        case,
        artifact,
        expected_answer_synthesis_answerability=expected_answer_synthesis_answerability,
        expected_completed_tool_ids=expected_completed_tool_ids,
        expected_missing_fields_by_tool=expected_missing_fields_by_tool,
        expected_answer_fragments=expected_answer_fragments,
        expected_limitation_fragments=expected_limitation_fragments,
    )
    if not result["passed"]:
        failed = [
            f"{check['name']}: {check['detail']}"
            for check in result["checks"]
            if not check["passed"]
        ]
        raise AssertionError(
            f"Scout AI answer synthesis workflow eval failed for {case.case_id}: "
            + "; ".join(failed)
        )
    return result


def evaluate_full_workflow_artifact(
    case: ScoutAiAssistantWorkflowEvalCase,
    artifact: ScoutAiFullWorkflowOutput | dict[str, Any],
    *,
    expected_full_workflow_answerability: str,
    expected_completed_tool_ids: tuple[str, ...] = (),
    expected_missing_fields_by_tool: dict[str, tuple[str, ...]] | None = None,
    expected_step_ids: tuple[str, ...] = (
        "context_registry_and_tool_plan",
        "evidence_collection",
        "answer_synthesis",
    ),
    expected_answer_fragments: tuple[str, ...] = (),
    expected_limitation_fragments: tuple[str, ...] = (),
) -> dict[str, Any]:
    parsed = _parse_full_workflow_artifact(artifact)
    checks = [
        _check_full_workflow_artifact_kind(parsed),
        _check_full_workflow_answerability(
            parsed,
            expected_full_workflow_answerability,
        ),
        _check_full_workflow_step_ids(parsed, expected_step_ids),
        _check_full_workflow_completed_tools(parsed, expected_completed_tool_ids),
        _check_full_workflow_missing_fields(
            parsed,
            expected_missing_fields_by_tool or {},
        ),
        _check_full_workflow_answer_fragments(parsed, expected_answer_fragments),
        _check_full_workflow_limitation_fragments(
            parsed,
            expected_limitation_fragments,
        ),
        _check_full_workflow_read_only_boundary(parsed),
        _check_full_workflow_sources_are_not_runtime_truth(parsed),
    ]
    passed = all(check["passed"] for check in checks)
    return {
        "artifact_kind": "scout_ai_full_workflow_eval",
        "artifact_version": "scout_ai_full_workflow_eval.v0",
        "case_id": case.case_id,
        "question": case.question,
        "expected_answerability": case.expected_answerability,
        "full_workflow_answerability": parsed.answerability,
        "passed": passed,
        "checks": checks,
        "step_ids": [step.step_id for step in parsed.workflow_steps],
        "source_ids": [
            str(source.get("tool_id"))
            for source in parsed.sources
            if isinstance(source, dict) and source.get("tool_id") is not None
        ],
        "completed_source_ids": [
            str(source.get("tool_id"))
            for source in parsed.sources
            if isinstance(source, dict)
            and source.get("collection_status") == "completed"
            and source.get("tool_id") is not None
        ],
        "missing_evidence": list(parsed.missing_evidence),
        "limitations": list(parsed.limitations),
        "boundary": parsed.boundary.model_dump(mode="json"),
        "workflow_policy": parsed.workflow_policy.model_dump(mode="json"),
    }


def assert_full_workflow_artifact(
    case: ScoutAiAssistantWorkflowEvalCase,
    artifact: ScoutAiFullWorkflowOutput | dict[str, Any],
    *,
    expected_full_workflow_answerability: str,
    expected_completed_tool_ids: tuple[str, ...] = (),
    expected_missing_fields_by_tool: dict[str, tuple[str, ...]] | None = None,
    expected_step_ids: tuple[str, ...] = (
        "context_registry_and_tool_plan",
        "evidence_collection",
        "answer_synthesis",
    ),
    expected_answer_fragments: tuple[str, ...] = (),
    expected_limitation_fragments: tuple[str, ...] = (),
) -> dict[str, Any]:
    result = evaluate_full_workflow_artifact(
        case,
        artifact,
        expected_full_workflow_answerability=expected_full_workflow_answerability,
        expected_completed_tool_ids=expected_completed_tool_ids,
        expected_missing_fields_by_tool=expected_missing_fields_by_tool,
        expected_step_ids=expected_step_ids,
        expected_answer_fragments=expected_answer_fragments,
        expected_limitation_fragments=expected_limitation_fragments,
    )
    if not result["passed"]:
        failed = [
            f"{check['name']}: {check['detail']}"
            for check in result["checks"]
            if not check["passed"]
        ]
        raise AssertionError(
            f"Scout AI full workflow eval failed for {case.case_id}: "
            + "; ".join(failed)
        )
    return result


def _check_source_ids(
    case: ScoutAiAssistantWorkflowEvalCase,
    response: ScoutAssistantResponse,
) -> dict[str, Any]:
    source_ids = {source.source_id for source in response.sources}
    missing = [
        source_id
        for source_id in case.expected_source_ids
        if source_id not in source_ids
    ]
    return _check(
        "expected_source_ids",
        not missing,
        f"missing={missing}; actual={sorted(source_ids)}",
    )


def _check_missing_fields(
    case: ScoutAiAssistantWorkflowEvalCase,
    response: ScoutAssistantResponse,
) -> dict[str, Any]:
    failures: list[str] = []
    sources_by_id = {source.source_id: source for source in response.sources}
    for source_id, expected_fields in case.expected_missing_fields_by_source.items():
        source = sources_by_id.get(source_id)
        if source is None:
            failures.append(f"{source_id}: missing source")
            continue
        actual_fields = set(_source_missing_fields(source))
        missing = [field for field in expected_fields if field not in actual_fields]
        if missing:
            failures.append(
                f"{source_id}: missing_fields={missing}; actual={sorted(actual_fields)}"
            )
    return _check("expected_missing_fields", not failures, "; ".join(failures))


def _check_tool_registry_missing_fields(
    case: ScoutAiAssistantWorkflowEvalCase,
    response: ScoutAssistantResponse,
) -> dict[str, Any]:
    if not case.expected_tool_registry_missing_fields_by_tool:
        return _check("expected_tool_registry_missing_fields", True, "not required")
    sources_by_id = {source.source_id: source for source in response.sources}
    source = sources_by_id.get(TOOL_REGISTRY_SOURCE_ID)
    if source is None:
        return _check(
            "expected_tool_registry_missing_fields",
            False,
            f"missing source: {TOOL_REGISTRY_SOURCE_ID}",
        )
    summary = source.context_summary if isinstance(source.context_summary, dict) else {}
    fields_by_tool = summary.get("missing_evidence_fields_by_tool")
    if not isinstance(fields_by_tool, dict):
        return _check(
            "expected_tool_registry_missing_fields",
            False,
            "tool registry source has no missing_evidence_fields_by_tool",
        )

    failures: list[str] = []
    for tool_id, expected_fields in (
        case.expected_tool_registry_missing_fields_by_tool.items()
    ):
        actual_fields = fields_by_tool.get(tool_id)
        if not isinstance(actual_fields, list):
            failures.append(f"{tool_id}: missing registry entry")
            continue
        actual = {str(field) for field in actual_fields}
        missing = [field for field in expected_fields if field not in actual]
        if missing:
            failures.append(
                f"{tool_id}: missing_fields={missing}; actual={sorted(actual)}"
            )
    return _check(
        "expected_tool_registry_missing_fields",
        not failures,
        "; ".join(failures),
    )


def _check_tool_registry_tool_ids_by_status(
    case: ScoutAiAssistantWorkflowEvalCase,
    response: ScoutAssistantResponse,
) -> dict[str, Any]:
    if not case.expected_tool_registry_tool_ids_by_status:
        return _check("expected_tool_registry_tool_ids_by_status", True, "not required")
    sources_by_id = {source.source_id: source for source in response.sources}
    source = sources_by_id.get(TOOL_REGISTRY_SOURCE_ID)
    if source is None:
        return _check(
            "expected_tool_registry_tool_ids_by_status",
            False,
            f"missing source: {TOOL_REGISTRY_SOURCE_ID}",
        )
    summary = source.context_summary if isinstance(source.context_summary, dict) else {}
    tool_ids_by_status = summary.get("tool_ids_by_status")
    if not isinstance(tool_ids_by_status, dict):
        return _check(
            "expected_tool_registry_tool_ids_by_status",
            False,
            "tool registry source has no tool_ids_by_status",
        )

    failures: list[str] = []
    for status, expected_tool_ids in (
        case.expected_tool_registry_tool_ids_by_status.items()
    ):
        actual_tool_ids = tool_ids_by_status.get(status)
        if not isinstance(actual_tool_ids, list):
            failures.append(f"{status}: missing registry status bucket")
            continue
        actual = {str(tool_id) for tool_id in actual_tool_ids}
        missing = [tool_id for tool_id in expected_tool_ids if tool_id not in actual]
        if missing:
            failures.append(
                f"{status}: missing_tool_ids={missing}; actual={sorted(actual)}"
            )
    return _check(
        "expected_tool_registry_tool_ids_by_status",
        not failures,
        "; ".join(failures),
    )


def _check_context_registry_source_ids_by_domain(
    case: ScoutAiAssistantWorkflowEvalCase,
    response: ScoutAssistantResponse,
) -> dict[str, Any]:
    if not case.expected_context_registry_source_ids_by_domain:
        return _check("expected_context_registry_source_ids_by_domain", True, "not required")
    sources_by_id = {source.source_id: source for source in response.sources}
    source = sources_by_id.get(CONTEXT_REGISTRY_SOURCE_ID)
    if source is None:
        return _check(
            "expected_context_registry_source_ids_by_domain",
            False,
            f"missing source: {CONTEXT_REGISTRY_SOURCE_ID}",
        )
    summary = source.context_summary if isinstance(source.context_summary, dict) else {}
    source_ids_by_domain = summary.get("source_ids_by_domain")
    if not isinstance(source_ids_by_domain, dict):
        return _check(
            "expected_context_registry_source_ids_by_domain",
            False,
            "context registry source has no source_ids_by_domain",
        )

    failures: list[str] = []
    for domain, expected_source_ids in (
        case.expected_context_registry_source_ids_by_domain.items()
    ):
        actual_source_ids = source_ids_by_domain.get(domain)
        if not isinstance(actual_source_ids, list):
            failures.append(f"{domain}: missing context registry domain")
            continue
        actual = {str(source_id) for source_id in actual_source_ids}
        missing = [
            source_id for source_id in expected_source_ids if source_id not in actual
        ]
        if missing:
            failures.append(
                f"{domain}: missing_source_ids={missing}; actual={sorted(actual)}"
            )
    return _check(
        "expected_context_registry_source_ids_by_domain",
        not failures,
        "; ".join(failures),
    )


def _check_full_workflow_summary(
    case: ScoutAiAssistantWorkflowEvalCase,
    response: ScoutAssistantResponse,
) -> dict[str, Any]:
    if (
        case.expected_full_workflow_answerability is None
        and not case.expected_full_workflow_source_tool_ids
        and not case.expected_full_workflow_missing_fields_by_tool
        and not case.expected_full_workflow_step_ids
    ):
        return _check("full_workflow_summary", True, "not required")
    summary = _full_workflow_summary(response)
    if summary is None:
        return _check(
            "full_workflow_summary",
            False,
            f"missing source: {PRETRIP_FULL_WORKFLOW_SOURCE_ID}",
        )

    failures: list[str] = []
    if summary.get("artifact_kind") != "scout_ai_full_workflow":
        failures.append(f"artifact_kind={summary.get('artifact_kind')}")
    if summary.get("artifact_version") != "scout_ai_full_workflow.v0":
        failures.append(f"artifact_version={summary.get('artifact_version')}")
    if (
        case.expected_full_workflow_answerability is not None
        and summary.get("answerability") != case.expected_full_workflow_answerability
    ):
        failures.append(
            "answerability="
            f"{summary.get('answerability')}; expected={case.expected_full_workflow_answerability}"
        )

    actual_step_ids = {
        str(step.get("step_id"))
        for step in _list_of_dicts(summary.get("workflow_steps"))
        if step.get("step_id") is not None
    }
    missing_steps = [
        step_id
        for step_id in case.expected_full_workflow_step_ids
        if step_id not in actual_step_ids
    ]
    if missing_steps:
        failures.append(
            f"missing_steps={missing_steps}; actual_steps={sorted(actual_step_ids)}"
        )

    actual_tool_ids = {
        str(source.get("tool_id"))
        for source in _list_of_dicts(summary.get("sources"))
        if source.get("tool_id") is not None
    }
    missing_tool_ids = [
        tool_id
        for tool_id in case.expected_full_workflow_source_tool_ids
        if tool_id not in actual_tool_ids
    ]
    if missing_tool_ids:
        failures.append(
            f"missing_source_tool_ids={missing_tool_ids}; actual={sorted(actual_tool_ids)}"
        )

    missing_evidence_by_tool = _full_workflow_missing_fields_by_tool(summary)
    for tool_id, expected_fields in (
        case.expected_full_workflow_missing_fields_by_tool.items()
    ):
        actual_fields = missing_evidence_by_tool.get(tool_id, set())
        missing_fields = [
            field for field in expected_fields if field not in actual_fields
        ]
        if missing_fields:
            failures.append(
                f"{tool_id}: missing_fields={missing_fields}; actual={sorted(actual_fields)}"
            )

    boundary = summary.get("boundary")
    if not isinstance(boundary, dict):
        failures.append("boundary missing")
    else:
        if boundary.get("runtime_safety_truth") is not False:
            failures.append("boundary.runtime_safety_truth is not false")
        for field_name in (
            "live_safety_api_calls_allowed",
            "phase1_safety_mutation_allowed",
            "remote_outbound_send_allowed",
            "hardware_control_allowed",
            "raw_payloads_embedded",
            "model_output_is_runtime_truth",
        ):
            if boundary.get(field_name) is not False:
                failures.append(f"boundary.{field_name} is not false")
    policy = summary.get("workflow_policy")
    if not isinstance(policy, dict):
        failures.append("workflow_policy missing")
    else:
        for field_name in (
            "model_provider_used",
            "model_synthesis_performed",
            "workspace_file_write_allowed",
            "safety_api_called",
            "phase1_l0_l4_state_mutated",
            "outbound_send_performed",
            "hardware_control_performed",
        ):
            if policy.get(field_name) is not False:
                failures.append(f"workflow_policy.{field_name} is not false")
    if summary.get("runtime_safety_truth") is not False:
        failures.append("runtime_safety_truth is not false")
    if summary.get("raw_payloads_embedded") is not False:
        failures.append("raw_payloads_embedded is not false")

    return _check(
        "full_workflow_summary",
        not failures,
        "; ".join(failures),
    )


def _check_limitation_fragments(
    case: ScoutAiAssistantWorkflowEvalCase,
    response: ScoutAssistantResponse,
) -> dict[str, Any]:
    limitations = "\n".join(response.limitations)
    missing = [
        fragment
        for fragment in case.expected_limitation_fragments
        if fragment not in limitations
    ]
    return _check("expected_limitations", not missing, f"missing={missing}")


def _check_answer_fragments(
    case: ScoutAiAssistantWorkflowEvalCase,
    response: ScoutAssistantResponse,
) -> dict[str, Any]:
    missing = [
        fragment
        for fragment in case.expected_answer_fragments
        if fragment not in response.answer
    ]
    return _check("expected_answer_fragments", not missing, f"missing={missing}")


def _check_safe_failure(
    case: ScoutAiAssistantWorkflowEvalCase,
    response: ScoutAssistantResponse,
) -> dict[str, Any]:
    if case.expected_safe_failure is None:
        return _check("expected_safe_failure", True, "not required")
    actual = response.observability.safe_failure if response.observability else None
    return _check(
        "expected_safe_failure",
        actual == case.expected_safe_failure,
        f"expected={case.expected_safe_failure}; actual={actual}",
    )


def _check_read_only_boundary(
    case: ScoutAiAssistantWorkflowEvalCase,
    response: ScoutAssistantResponse,
) -> dict[str, Any]:
    if not case.require_read_only_boundary:
        return _check("read_only_boundary", True, "not required")
    boundary = response.boundary
    failures = []
    expected_false = (
        "phase1_mutation_allowed",
        "safety_mutation_allowed",
        "phase2_writeback_allowed",
        "observed_fact_write_allowed",
        "derived_measurement_write_allowed",
        "incident_store_write_allowed",
        "human_review_mutation_allowed",
        "pretrip_review_mutation_allowed",
        "outbound_send_allowed",
        "real_sos_allowed",
        "real_sms_allowed",
        "real_satellite_allowed",
        "hardware_control_allowed",
    )
    if response.read_only is not True:
        failures.append("response.read_only is not true")
    if response.model_interpretation is not True:
        failures.append("response.model_interpretation is not true")
    if boundary.read_only is not True:
        failures.append("boundary.read_only is not true")
    for field_name in expected_false:
        if getattr(boundary, field_name) is not False:
            failures.append(f"boundary.{field_name} is not false")
    return _check("read_only_boundary", not failures, "; ".join(failures))


def _check_sources_are_not_runtime_truth(
    response: ScoutAssistantResponse,
) -> dict[str, Any]:
    failures = []
    for source in response.sources:
        summary = source.context_summary if isinstance(source.context_summary, dict) else {}
        if summary.get("runtime_safety_truth") is True:
            failures.append(f"{source.source_id}: runtime_safety_truth=true")
        boundary = summary.get("boundary")
        if isinstance(boundary, dict) and boundary.get("runtime_safety_truth") is True:
            failures.append(f"{source.source_id}: boundary.runtime_safety_truth=true")
    return _check("sources_not_runtime_truth", not failures, "; ".join(failures))


def _parse_answer_synthesis_artifact(
    artifact: ScoutAiAnswerSynthesisOutput | dict[str, Any],
) -> ScoutAiAnswerSynthesisOutput:
    if isinstance(artifact, ScoutAiAnswerSynthesisOutput):
        return artifact
    payload = dict(artifact)
    payload.pop("status", None)
    return ScoutAiAnswerSynthesisOutput.model_validate(payload)


def _check_answer_synthesis_artifact_kind(
    artifact: ScoutAiAnswerSynthesisOutput,
) -> dict[str, Any]:
    return _check(
        "answer_synthesis_artifact_kind",
        artifact.artifact_kind == "scout_ai_answer_synthesis"
        and artifact.artifact_version == "scout_ai_answer_synthesis.v0",
        f"artifact_kind={artifact.artifact_kind}; artifact_version={artifact.artifact_version}",
    )


def _check_answer_synthesis_answerability(
    artifact: ScoutAiAnswerSynthesisOutput,
    expected: str,
) -> dict[str, Any]:
    return _check(
        "answer_synthesis_answerability",
        artifact.answerability == expected,
        f"expected={expected}; actual={artifact.answerability}",
    )


def _check_answer_synthesis_completed_tools(
    artifact: ScoutAiAnswerSynthesisOutput,
    expected_tool_ids: tuple[str, ...],
) -> dict[str, Any]:
    if not expected_tool_ids:
        return _check("answer_synthesis_completed_tools", True, "not required")
    completed = {
        source.tool_id
        for source in artifact.sources
        if source.collection_status == "completed"
    }
    missing = [tool_id for tool_id in expected_tool_ids if tool_id not in completed]
    return _check(
        "answer_synthesis_completed_tools",
        not missing,
        f"missing={missing}; actual={sorted(completed)}",
    )


def _check_answer_synthesis_missing_fields(
    artifact: ScoutAiAnswerSynthesisOutput,
    expected_fields_by_tool: dict[str, tuple[str, ...]],
) -> dict[str, Any]:
    if not expected_fields_by_tool:
        return _check("answer_synthesis_missing_fields", True, "not required")
    actual_by_tool: dict[str, set[str]] = {}
    for item in artifact.missing_evidence:
        if not isinstance(item, dict):
            continue
        tool_id = str(item.get("tool_id") or "")
        fields = item.get("missing_fields")
        actual_by_tool[tool_id] = (
            {str(field) for field in fields if field is not None}
            if isinstance(fields, list)
            else set()
        )
    failures = []
    for tool_id, expected_fields in expected_fields_by_tool.items():
        actual = actual_by_tool.get(tool_id, set())
        missing = [field for field in expected_fields if field not in actual]
        if missing:
            failures.append(
                f"{tool_id}: missing_fields={missing}; actual={sorted(actual)}"
            )
    return _check(
        "answer_synthesis_missing_fields",
        not failures,
        "; ".join(failures),
    )


def _check_answer_synthesis_answer_fragments(
    artifact: ScoutAiAnswerSynthesisOutput,
    expected_fragments: tuple[str, ...],
) -> dict[str, Any]:
    missing = [
        fragment for fragment in expected_fragments if fragment not in artifact.answer
    ]
    return _check(
        "answer_synthesis_answer_fragments",
        not missing,
        f"missing={missing}",
    )


def _check_answer_synthesis_limitation_fragments(
    artifact: ScoutAiAnswerSynthesisOutput,
    expected_fragments: tuple[str, ...],
) -> dict[str, Any]:
    limitations = "\n".join(artifact.limitations)
    missing = [fragment for fragment in expected_fragments if fragment not in limitations]
    return _check(
        "answer_synthesis_limitations",
        not missing,
        f"missing={missing}",
    )


def _check_answer_synthesis_read_only_boundary(
    artifact: ScoutAiAnswerSynthesisOutput,
) -> dict[str, Any]:
    failures = []
    boundary = artifact.boundary
    policy = artifact.synthesis_policy
    expected_false = (
        "runtime_safety_truth",
        "live_safety_api_calls_allowed",
        "phase1_safety_mutation_allowed",
        "remote_outbound_send_allowed",
        "hardware_control_allowed",
        "raw_payloads_embedded",
        "model_output_is_runtime_truth",
    )
    if boundary.read_only is not True:
        failures.append("boundary.read_only is not true")
    for field_name in expected_false:
        if getattr(boundary, field_name) is not False:
            failures.append(f"boundary.{field_name} is not false")
    policy_false = (
        "model_provider_used",
        "model_synthesis_performed",
        "workspace_file_write_allowed",
        "safety_api_called",
        "phase1_l0_l4_state_mutated",
        "outbound_send_performed",
        "hardware_control_performed",
    )
    for field_name in policy_false:
        if getattr(policy, field_name) is not False:
            failures.append(f"synthesis_policy.{field_name} is not false")
    if policy.evidence_collected_before_synthesis is not True:
        failures.append("synthesis_policy.evidence_collected_before_synthesis is not true")
    return _check(
        "answer_synthesis_read_only_boundary",
        not failures,
        "; ".join(failures),
    )


def _check_answer_synthesis_sources_are_not_runtime_truth(
    artifact: ScoutAiAnswerSynthesisOutput,
) -> dict[str, Any]:
    failures = [
        f"{source.tool_id}: runtime_safety_truth=true"
        for source in artifact.sources
        if source.runtime_safety_truth is True
    ]
    return _check(
        "answer_synthesis_sources_not_runtime_truth",
        not failures,
        "; ".join(failures),
    )


def _parse_full_workflow_artifact(
    artifact: ScoutAiFullWorkflowOutput | dict[str, Any],
) -> ScoutAiFullWorkflowOutput:
    if isinstance(artifact, ScoutAiFullWorkflowOutput):
        return artifact
    payload = dict(artifact)
    payload.pop("status", None)
    return ScoutAiFullWorkflowOutput.model_validate(payload)


def _check_full_workflow_artifact_kind(
    artifact: ScoutAiFullWorkflowOutput,
) -> dict[str, Any]:
    return _check(
        "full_workflow_artifact_kind",
        artifact.artifact_kind == "scout_ai_full_workflow"
        and artifact.artifact_version == "scout_ai_full_workflow.v0",
        f"artifact_kind={artifact.artifact_kind}; artifact_version={artifact.artifact_version}",
    )


def _check_full_workflow_answerability(
    artifact: ScoutAiFullWorkflowOutput,
    expected: str,
) -> dict[str, Any]:
    return _check(
        "full_workflow_answerability",
        artifact.answerability == expected,
        f"expected={expected}; actual={artifact.answerability}",
    )


def _check_full_workflow_step_ids(
    artifact: ScoutAiFullWorkflowOutput,
    expected_step_ids: tuple[str, ...],
) -> dict[str, Any]:
    actual = [step.step_id for step in artifact.workflow_steps]
    return _check(
        "full_workflow_step_ids",
        actual == list(expected_step_ids),
        f"expected={list(expected_step_ids)}; actual={actual}",
    )


def _check_full_workflow_completed_tools(
    artifact: ScoutAiFullWorkflowOutput,
    expected_tool_ids: tuple[str, ...],
) -> dict[str, Any]:
    if not expected_tool_ids:
        return _check("full_workflow_completed_tools", True, "not required")
    completed = {
        str(source.get("tool_id"))
        for source in artifact.sources
        if isinstance(source, dict)
        and source.get("collection_status") == "completed"
        and source.get("tool_id") is not None
    }
    missing = [tool_id for tool_id in expected_tool_ids if tool_id not in completed]
    return _check(
        "full_workflow_completed_tools",
        not missing,
        f"missing={missing}; actual={sorted(completed)}",
    )


def _check_full_workflow_missing_fields(
    artifact: ScoutAiFullWorkflowOutput,
    expected_fields_by_tool: dict[str, tuple[str, ...]],
) -> dict[str, Any]:
    if not expected_fields_by_tool:
        return _check("full_workflow_missing_fields", True, "not required")
    actual_by_tool = _full_workflow_missing_fields_by_tool(
        artifact.model_dump(mode="json")
    )
    failures = []
    for tool_id, expected_fields in expected_fields_by_tool.items():
        actual = actual_by_tool.get(tool_id, set())
        missing = [field for field in expected_fields if field not in actual]
        if missing:
            failures.append(
                f"{tool_id}: missing_fields={missing}; actual={sorted(actual)}"
            )
    return _check(
        "full_workflow_missing_fields",
        not failures,
        "; ".join(failures),
    )


def _check_full_workflow_answer_fragments(
    artifact: ScoutAiFullWorkflowOutput,
    expected_fragments: tuple[str, ...],
) -> dict[str, Any]:
    missing = [
        fragment for fragment in expected_fragments if fragment not in artifact.answer
    ]
    return _check(
        "full_workflow_answer_fragments",
        not missing,
        f"missing={missing}",
    )


def _check_full_workflow_limitation_fragments(
    artifact: ScoutAiFullWorkflowOutput,
    expected_fragments: tuple[str, ...],
) -> dict[str, Any]:
    limitations = "\n".join(artifact.limitations)
    missing = [fragment for fragment in expected_fragments if fragment not in limitations]
    return _check(
        "full_workflow_limitations",
        not missing,
        f"missing={missing}",
    )


def _check_full_workflow_read_only_boundary(
    artifact: ScoutAiFullWorkflowOutput,
) -> dict[str, Any]:
    failures = []
    boundary = artifact.boundary
    policy = artifact.workflow_policy
    expected_false = (
        "runtime_safety_truth",
        "live_safety_api_calls_allowed",
        "phase1_safety_mutation_allowed",
        "remote_outbound_send_allowed",
        "hardware_control_allowed",
        "raw_payloads_embedded",
        "model_output_is_runtime_truth",
    )
    if boundary.read_only is not True:
        failures.append("boundary.read_only is not true")
    for field_name in expected_false:
        if getattr(boundary, field_name) is not False:
            failures.append(f"boundary.{field_name} is not false")
    policy_false = (
        "model_provider_used",
        "model_synthesis_performed",
        "workspace_file_write_allowed",
        "safety_api_called",
        "phase1_l0_l4_state_mutated",
        "outbound_send_performed",
        "hardware_control_performed",
    )
    for field_name in policy_false:
        if getattr(policy, field_name) is not False:
            failures.append(f"workflow_policy.{field_name} is not false")
    if policy.context_registry_discovered is not True:
        failures.append("workflow_policy.context_registry_discovered is not true")
    if policy.tool_plan_created is not True:
        failures.append("workflow_policy.tool_plan_created is not true")
    if policy.evidence_collection_performed is not True:
        failures.append("workflow_policy.evidence_collection_performed is not true")
    if policy.answer_synthesis_performed is not True:
        failures.append("workflow_policy.answer_synthesis_performed is not true")
    return _check(
        "full_workflow_read_only_boundary",
        not failures,
        "; ".join(failures),
    )


def _check_full_workflow_sources_are_not_runtime_truth(
    artifact: ScoutAiFullWorkflowOutput,
) -> dict[str, Any]:
    failures = []
    for source in artifact.sources:
        if not isinstance(source, dict):
            continue
        if source.get("runtime_safety_truth") is True:
            failures.append(f"{source.get('tool_id')}: runtime_safety_truth=true")
    return _check(
        "full_workflow_sources_not_runtime_truth",
        not failures,
        "; ".join(failures),
    )


def _source_missing_fields(source: AssistantSourceRef) -> list[str]:
    summary = source.context_summary if isinstance(source.context_summary, dict) else {}
    missing = summary.get("missing_fields")
    if not isinstance(missing, list):
        latest = summary.get("latest")
        if isinstance(latest, dict):
            missing = latest.get("missing_fields")
    if not isinstance(missing, list):
        plan_item = summary.get("plan_item")
        if isinstance(plan_item, dict):
            missing = plan_item.get("missing_fields")
    if not isinstance(missing, list):
        return []
    return [str(item) for item in missing if item is not None]


def _completed_tool_results(response: ScoutAssistantResponse) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for source in response.sources:
        if source.evidence_type != "assistant_registry_tool_result":
            continue
        summary = source.context_summary if isinstance(source.context_summary, dict) else {}
        latest = summary.get("latest")
        if not isinstance(latest, dict) or latest.get("status") != "completed":
            continue
        missing_fields = latest.get("missing_fields")
        if not isinstance(missing_fields, list):
            missing_fields = []
        summaries.append(
            {
                "source_id": source.source_id,
                "tool_id": str(summary.get("tool_id") or source.source_id),
                "status": "completed",
                "answerability": latest.get("answerability"),
                "missing_fields": [str(field) for field in missing_fields],
                "result_count": _result_count(latest),
                "output_artifact_kind": latest.get("artifact_kind"),
                "runtime_safety_truth": False,
            }
        )
    return summaries


def _contract_gap_sources(response: ScoutAssistantResponse) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    for source in response.sources:
        summary = source.context_summary if isinstance(source.context_summary, dict) else {}
        missing_fields = _source_missing_fields(source)
        if source.evidence_type != "assistant_registry_tool_contract_gap" and not missing_fields:
            continue
        if source.evidence_type == "assistant_registry_tool_result":
            latest = summary.get("latest")
            status = latest.get("status") if isinstance(latest, dict) else summary.get("status")
            implementation_status = (
                latest.get("implementation_status")
                if isinstance(latest, dict)
                else summary.get("implementation_status")
            )
        else:
            status = summary.get("status")
            implementation_status = summary.get("implementation_status")
        gaps.append(
            {
                "source_id": source.source_id,
                "tool_id": str(summary.get("tool_id") or source.source_id),
                "status": status,
                "implementation_status": implementation_status,
                "missing_fields": missing_fields,
                "implementation_gap": summary.get("implementation_gap"),
                "runtime_safety_truth": False,
            }
        )
    return gaps


def _context_registry_summary(
    response: ScoutAssistantResponse,
) -> dict[str, Any] | None:
    source = next(
        (
            source
            for source in response.sources
            if source.source_id == CONTEXT_REGISTRY_SOURCE_ID
        ),
        None,
    )
    if source is None:
        return None
    summary = source.context_summary if isinstance(source.context_summary, dict) else {}
    rows = summary.get("sources")
    if not isinstance(rows, list):
        rows = []
    source_status_counts: dict[str, int] = {}
    missing_source_ids: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        status = str(row.get("status") or "unknown")
        source_status_counts[status] = source_status_counts.get(status, 0) + 1
        if status == "missing" and row.get("source_id"):
            missing_source_ids.append(str(row["source_id"]))
    return {
        "source_id": source.source_id,
        "artifact_kind": summary.get("artifact_kind"),
        "artifact_version": summary.get("artifact_version"),
        "project_id": summary.get("project_id"),
        "source_count": summary.get("source_count"),
        "available_source_count": summary.get("available_source_count"),
        "partial_source_count": summary.get("partial_source_count"),
        "missing_source_count": summary.get("missing_source_count"),
        "source_status_counts": dict(sorted(source_status_counts.items())),
        "source_ids_by_domain": summary.get("source_ids_by_domain", {}),
        "missing_source_ids": missing_source_ids,
        "runtime_safety_truth": False,
    }


def _full_workflow_summary(
    response: ScoutAssistantResponse,
) -> dict[str, Any] | None:
    source = next(
        (
            source
            for source in response.sources
            if source.source_id == PRETRIP_FULL_WORKFLOW_SOURCE_ID
        ),
        None,
    )
    if source is None:
        return None
    summary = source.context_summary if isinstance(source.context_summary, dict) else {}
    return {
        "source_id": source.source_id,
        "evidence_type": source.evidence_type,
        "artifact_kind": summary.get("artifact_kind"),
        "artifact_version": summary.get("artifact_version"),
        "project_id": summary.get("project_id"),
        "answerability": summary.get("answerability"),
        "selected_tool_count": summary.get("selected_tool_count"),
        "executed_tool_count": summary.get("executed_tool_count"),
        "completed_tool_count": summary.get("completed_tool_count"),
        "contract_gap_count": summary.get("contract_gap_count"),
        "missing_evidence_count": summary.get("missing_evidence_count"),
        "workflow_steps": _list_of_dicts(summary.get("workflow_steps")),
        "sources": _list_of_dicts(summary.get("sources")),
        "missing_evidence": _list_of_dicts(summary.get("missing_evidence")),
        "limitations": summary.get("limitations", [])
        if isinstance(summary.get("limitations"), list)
        else [],
        "workflow_policy": summary.get("workflow_policy", {})
        if isinstance(summary.get("workflow_policy"), dict)
        else {},
        "boundary": summary.get("boundary", {})
        if isinstance(summary.get("boundary"), dict)
        else {},
        "runtime_safety_truth": False,
        "raw_payloads_embedded": False,
    }


def _full_workflow_missing_fields_by_tool(
    summary: dict[str, Any],
) -> dict[str, set[str]]:
    fields_by_tool: dict[str, set[str]] = {}
    for item in _list_of_dicts(summary.get("missing_evidence")):
        tool_id = str(item.get("tool_id") or "")
        fields = item.get("missing_fields")
        fields_by_tool[tool_id] = (
            {str(field) for field in fields if field is not None}
            if isinstance(fields, list)
            else set()
        )
    for source in _list_of_dicts(summary.get("sources")):
        tool_id = str(source.get("tool_id") or "")
        fields = source.get("missing_fields")
        if isinstance(fields, list) and fields:
            fields_by_tool.setdefault(tool_id, set()).update(
                str(field) for field in fields if field is not None
            )
    return fields_by_tool


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _result_count(payload: dict[str, Any]) -> int:
    value = payload.get("result_count")
    if isinstance(value, int):
        return value
    for key in ("results", "summaries", "matches", "items"):
        items = payload.get(key)
        if isinstance(items, list):
            return len(items)
    return 0


def _markdown_completed_tool_summary(value: Any) -> str:
    if not isinstance(value, list) or not value:
        return "-"
    parts = []
    for item in value:
        if not isinstance(item, dict):
            continue
        label = str(item.get("tool_id") or item.get("source_id") or "unknown")
        answerability = item.get("answerability")
        if answerability:
            label = f"{label}({answerability})"
        missing_fields = item.get("missing_fields")
        if isinstance(missing_fields, list) and missing_fields:
            label = f"{label}:missing={','.join(str(field) for field in missing_fields)}"
        parts.append(label)
    return ", ".join(parts) or "-"


def _markdown_contract_gap_summary(value: Any) -> str:
    if not isinstance(value, list) or not value:
        return "-"
    parts = []
    for item in value:
        if not isinstance(item, dict):
            continue
        label = str(item.get("tool_id") or item.get("source_id") or "unknown")
        missing_fields = item.get("missing_fields")
        if isinstance(missing_fields, list) and missing_fields:
            label = f"{label}:missing={','.join(str(field) for field in missing_fields)}"
        status = item.get("status")
        if status:
            label = f"{label}({status})"
        parts.append(label)
    return ", ".join(parts) or "-"


def _markdown_context_registry_summary(value: Any) -> str:
    if not isinstance(value, dict) or not value:
        return "-"
    source_ids_by_domain = value.get("source_ids_by_domain")
    domains = (
        ",".join(sorted(str(domain) for domain in source_ids_by_domain))
        if isinstance(source_ids_by_domain, dict)
        else "-"
    )
    available = value.get("available_source_count", "?")
    partial = value.get("partial_source_count", "?")
    missing = value.get("missing_source_count", "?")
    return f"domains={domains}; available={available}; partial={partial}; missing={missing}"


def _workflow_eval_case_from_question_item(
    item: dict[str, Any],
    *,
    requested_case_id: str | None = None,
    profile: str | None = None,
) -> ScoutAiAssistantWorkflowEvalCase:
    evaluation = evaluate_question(item)
    case_id = evaluation.question_id
    profile = profile or "default"
    output_case_id = requested_case_id or case_id
    if profile != "default" and case_id not in {"seed-031", "seed-064"}:
        raise ValueError(
            f"unsupported workflow eval profile for case_id={case_id}: {profile}"
        )
    if case_id == "seed-001":
        return ScoutAiAssistantWorkflowEvalCase(
            case_id=case_id,
            question=evaluation.question,
            expected_answerability=evaluation.answerability,
            expected_source_ids=(
                PRETRIP_CP_COUNT_SKILL_ID,
                CONTEXT_REGISTRY_SOURCE_ID,
                "assistant_context.pretrip",
            ),
            expected_context_registry_source_ids_by_domain={
                "route": ("scout.context.route_structure",),
            },
            expected_limitation_fragments=(f"resolved_by={PRETRIP_CP_COUNT_SKILL_ID}",),
            expected_answer_fragments=("124 個 CP", "runtime safety truth"),
            expected_safe_failure=False,
        )
    if case_id == "seed-008":
        return ScoutAiAssistantWorkflowEvalCase(
            case_id=case_id,
            question=evaluation.question,
            expected_answerability=evaluation.answerability,
            expected_source_ids=(
                PRETRIP_PLACE_TO_CP_SKILL_ID,
                CONTEXT_REGISTRY_SOURCE_ID,
                "assistant_context.pretrip",
            ),
            expected_context_registry_source_ids_by_domain={
                "mcp": ("scout.context.major_points",),
                "route": ("scout.context.route_structure",),
            },
            expected_limitation_fragments=(f"resolved_by={PRETRIP_PLACE_TO_CP_SKILL_ID}",),
            expected_answer_fragments=(
                "CP 002",
                "candidate_only=true",
                "runtime_safety_truth=false",
            ),
            expected_safe_failure=False,
        )
    if case_id == "seed-007":
        return ScoutAiAssistantWorkflowEvalCase(
            case_id=case_id,
            question=evaluation.question,
            expected_answerability=evaluation.answerability,
            expected_source_ids=(
                CONTEXT_REGISTRY_SOURCE_ID,
                TOOL_REGISTRY_SOURCE_ID,
                PRETRIP_TOOL_PLANNER_SKILL_ID,
                PRETRIP_FULL_WORKFLOW_SOURCE_ID,
                WEATHER_WINDOW_TOOL_ID,
            ),
            expected_context_registry_source_ids_by_domain={
                "weather": ("scout.context.weather_window",),
            },
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
    if case_id == "seed-021":
        return ScoutAiAssistantWorkflowEvalCase(
            case_id=case_id,
            question=evaluation.question,
            expected_answerability=evaluation.answerability,
            expected_source_ids=(
                CONTEXT_REGISTRY_SOURCE_ID,
                PRETRIP_TOOL_PLANNER_SKILL_ID,
                RISK_SCORE_TOOL_ID,
            ),
            expected_context_registry_source_ids_by_domain={
                "risk": ("scout.context.risk_scores",),
            },
            expected_limitation_fragments=(f"resolved_by={RISK_SCORE_TOOL_ID}",),
            expected_answer_fragments=(
                "risk score tool fallback",
                "Matched score count",
                "pretrip candidate score layers, not runtime safety truth",
            ),
            expected_safe_failure=True,
        )
    if case_id == "seed-024":
        return ScoutAiAssistantWorkflowEvalCase(
            case_id=case_id,
            question=evaluation.question,
            expected_answerability=evaluation.answerability,
            expected_source_ids=(
                CONTEXT_REGISTRY_SOURCE_ID,
                PRETRIP_TOOL_PLANNER_SKILL_ID,
                TERRAIN_SCORE_TOOL_ID,
            ),
            expected_context_registry_source_ids_by_domain={
                "terrain": ("scout.context.terrain_scores",),
            },
            expected_limitation_fragments=(f"resolved_by={PRETRIP_TOOL_PLANNER_SKILL_ID}",),
            expected_answer_fragments=(
                "registry planner fallback",
                "terrain/slope model search",
                "candidate/planning evidence",
            ),
            expected_safe_failure=True,
        )
    if case_id == "seed-064":
        if profile == "energy_vitals_available":
            return ScoutAiAssistantWorkflowEvalCase(
                case_id=output_case_id,
                question=evaluation.question,
                expected_answerability="energy_vitals_advisory_available",
                expected_source_ids=(
                    CONTEXT_REGISTRY_SOURCE_ID,
                    TOOL_REGISTRY_SOURCE_ID,
                    PRETRIP_TOOL_PLANNER_SKILL_ID,
                    ENERGY_VITALS_TOOL_ID,
                ),
                expected_context_registry_source_ids_by_domain={
                    "health": ("scout.context.sensor_vitals",),
                },
                expected_limitation_fragments=(
                    f"resolved_by={PRETRIP_TOOL_PLANNER_SKILL_ID}",
                    f"resolved_tool={ENERGY_VITALS_TOOL_ID}",
                ),
                expected_answer_fragments=(
                    "energy/vitals fallback",
                    "最新心率=130.0 bpm",
                    "reserve_score=36",
                    "missing_fields=none",
                    "不是醫療診斷",
                    "不是 runtime safety truth",
                ),
                expected_safe_failure=True,
            )
        if profile != "default":
            raise ValueError(
                f"unsupported workflow eval profile for case_id={case_id}: {profile}"
            )
        return ScoutAiAssistantWorkflowEvalCase(
            case_id=case_id,
            question=evaluation.question,
            expected_answerability=evaluation.answerability,
            expected_source_ids=(
                CONTEXT_REGISTRY_SOURCE_ID,
                TOOL_REGISTRY_SOURCE_ID,
                PRETRIP_TOOL_PLANNER_SKILL_ID,
                ENERGY_VITALS_TOOL_ID,
            ),
            expected_context_registry_source_ids_by_domain={
                "health": ("scout.context.sensor_vitals",),
            },
            expected_missing_fields_by_source={
                ENERGY_VITALS_TOOL_ID: (
                    "heart_rate_bpm",
                    "baseline_window_days",
                    "reserve_score",
                    "source_provider",
                ),
            },
            expected_tool_registry_tool_ids_by_status={
                "partial_existing_surface": (ENERGY_VITALS_TOOL_ID,),
            },
            expected_limitation_fragments=(
                f"resolved_by={PRETRIP_TOOL_PLANNER_SKILL_ID}",
                f"resolved_tool={ENERGY_VITALS_TOOL_ID}",
            ),
            expected_answer_fragments=(
                "energy/vitals fallback",
                "missing_fields",
                "heart_rate_bpm",
                "不是醫療診斷",
                "不是 runtime safety truth",
            ),
            expected_safe_failure=True,
        )
    if case_id == "seed-030":
        return ScoutAiAssistantWorkflowEvalCase(
            case_id=case_id,
            question=evaluation.question,
            expected_answerability=evaluation.answerability,
            expected_source_ids=(
                CONTEXT_REGISTRY_SOURCE_ID,
                TOOL_REGISTRY_SOURCE_ID,
                PRETRIP_TOOL_PLANNER_SKILL_ID,
                RISK_SCORE_TOOL_ID,
                LIVE_NAVIGATION_STATE_TOOL_ID,
                SAFETY_BOUNDARY_TOOL_ID,
            ),
            expected_context_registry_source_ids_by_domain={
                "navigation": ("scout.context.ins_dr_trace",),
                "risk": ("scout.context.risk_scores",),
            },
            expected_missing_fields_by_source={
                LIVE_NAVIGATION_STATE_TOOL_ID: (
                    "lat",
                    "lon",
                    "horizontal_accuracy_m",
                    "fix_quality",
                    "ins_dr_source",
                    "uncertainty_m",
                ),
                SAFETY_BOUNDARY_TOOL_ID: (
                    "admission_state",
                    "operator_review_status",
                    "phase1_safety_decision_change_allowed",
                    "remote_outbound_allowed",
                ),
            },
            expected_tool_registry_tool_ids_by_status={
                "partial_existing_surface": (LIVE_NAVIGATION_STATE_TOOL_ID,),
                "boundary_explain_only": (SAFETY_BOUNDARY_TOOL_ID,),
            },
            expected_limitation_fragments=(f"resolved_by={PRETRIP_TOOL_PLANNER_SKILL_ID}",),
            expected_answer_fragments=(
                "registry planner fallback",
                "live navigation state assessor",
                "safety/admission boundary explainer",
                "missing_fields",
                "must not mutate /safety/* or send outbound",
                "not runtime safety truth",
            ),
            expected_safe_failure=True,
        )
    if case_id == "seed-031":
        if profile == "trace_metrics_available":
            return ScoutAiAssistantWorkflowEvalCase(
                case_id=output_case_id,
                question=evaluation.question,
                expected_answerability="trace_metrics_available",
                expected_source_ids=(
                    CONTEXT_REGISTRY_SOURCE_ID,
                    PRETRIP_TOOL_PLANNER_SKILL_ID,
                    INS_DR_TRACE_TOOL_ID,
                ),
                expected_context_registry_source_ids_by_domain={
                    "navigation": ("scout.context.ins_dr_trace",),
                },
                expected_limitation_fragments=(
                    f"resolved_by={PRETRIP_TOOL_PLANNER_SKILL_ID}",
                ),
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
        if profile != "default":
            raise ValueError(
                f"unsupported workflow eval profile for case_id={case_id}: {profile}"
            )
        return ScoutAiAssistantWorkflowEvalCase(
            case_id=output_case_id,
            question=evaluation.question,
            expected_answerability=evaluation.answerability,
            expected_source_ids=(
                CONTEXT_REGISTRY_SOURCE_ID,
                PRETRIP_TOOL_PLANNER_SKILL_ID,
                INS_DR_TRACE_TOOL_ID,
            ),
            expected_context_registry_source_ids_by_domain={
                "navigation": ("scout.context.ins_dr_trace",),
            },
            expected_missing_fields_by_source={
                INS_DR_TRACE_TOOL_ID: (
                    "ins_dr_estimates_jsonl",
                    "gps_only_trajectory",
                ),
            },
            expected_limitation_fragments=(f"resolved_by={PRETRIP_TOOL_PLANNER_SKILL_ID}",),
            expected_answer_fragments=(
                "registry planner fallback",
                "INS/DR trace summary",
                "missing_trace_evidence",
                "ins_dr_estimates_jsonl",
                "not runtime safety truth",
            ),
            expected_safe_failure=True,
        )
    raise ValueError(f"no bounded workflow eval expectation for case_id={case_id}")


def _split_case_profile(case_id: str) -> tuple[str, str | None]:
    raw = str(case_id)
    if "@" not in raw:
        return raw, None
    base_case_id, profile = raw.split("@", 1)
    return base_case_id, profile or None


def _resolver_failure_result(
    case: ScoutAiAssistantWorkflowEvalCase,
    exc: Exception,
) -> dict[str, Any]:
    return {
        "artifact_kind": ARTIFACT_KIND,
        "artifact_version": ARTIFACT_VERSION,
        "case_id": case.case_id,
        "question": case.question,
        "expected_answerability": case.expected_answerability,
        "passed": False,
        "checks": [
            {
                "name": "response_resolver",
                "passed": False,
                "detail": f"{type(exc).__name__}: {exc}",
            }
        ],
        "source_ids": [],
        "limitations": [],
        "boundary": None,
        "observability": None,
    }


def _report_boundary() -> dict[str, bool]:
    return {
        "read_only": True,
        "runtime_safety_truth": False,
        "phase1_l0_l4_state_mutated": False,
        "safety_api_called": False,
        "outbound_send_performed": False,
        "hardware_control_performed": False,
    }


def _escape_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _check(name: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "passed": passed, "detail": detail}
