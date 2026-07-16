from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from assistant_models import ScoutAssistantQuery  # noqa: E402
from scout.schemas.workspace_query import WorkspaceQueryResponse  # noqa: E402
from scout.services.agent_budget_policy import AgentBudgetPolicy  # noqa: E402
from scout.services.bounded_agent_runtime import estimate_tokens  # noqa: E402
from scout.services.workspace_query import WorkspaceQueryService  # noqa: E402
from scout_ai_tool_planner import plan_scout_ai_tools  # noqa: E402


ARTIFACT_KIND = "scout_ai_workspace_query_eval"
ARTIFACT_VERSION = "scout_ai_workspace_query_eval.v1"
DEFAULT_CASES_PATH = (
    ROOT
    / "outputs/evals/scout_ai_workspace_grounded_100_questions_20260713_glm52_cases.json"
)
DEFAULT_GOLD_PATH = (
    ROOT
    / "tests/fixtures/scout_ai_workspace_query_gold_100.json"
)


@dataclass(frozen=True)
class WorkspaceQueryGoldLabel:
    case_id: str
    artifact_keys: tuple[str, ...]
    operations: tuple[str, ...]
    fields: tuple[str, ...]
    assertions: tuple[dict[str, Any], ...]
    question: str = ""
    operation_fields: Mapping[str, str] | None = None
    collection_paths: Mapping[str, str] | None = None
    predicates: tuple[dict[str, Any], ...] = ()
    requests: tuple[dict[str, Any], ...] = ()
    requires_join: bool = False
    requires_live_state: bool = False
    requires_freshness: bool = False
    candidate_only_allowed: bool = True
    human_review_required: bool = False
    expected_tool_ids: tuple[str, ...] = ()
    post_verification: Mapping[str, Any] | None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "WorkspaceQueryGoldLabel":
        required = ("case_id", "artifact_keys", "operations", "fields", "assertions")
        missing = [key for key in required if not raw.get(key)]
        if missing:
            raise ValueError(f"gold label missing required values: {', '.join(missing)}")
        return cls(
            case_id=str(raw["case_id"]),
            artifact_keys=tuple(str(item) for item in raw["artifact_keys"]),
            operations=tuple(str(item) for item in raw["operations"]),
            fields=tuple(str(item) for item in raw["fields"]),
            assertions=tuple(dict(item) for item in raw["assertions"]),
            question=str(raw.get("question") or ""),
            operation_fields={
                str(key): str(value)
                for key, value in dict(raw.get("operation_fields") or {}).items()
            }
            or None,
            collection_paths={
                str(key): str(value)
                for key, value in dict(raw.get("collection_paths") or {}).items()
            }
            or None,
            predicates=tuple(dict(item) for item in raw.get("predicates") or ()),
            requests=tuple(dict(item) for item in raw.get("requests") or ()),
            requires_join=bool(raw.get("requires_join", False)),
            requires_live_state=bool(raw.get("requires_live_state", False)),
            requires_freshness=bool(raw.get("requires_freshness", False)),
            candidate_only_allowed=bool(raw.get("candidate_only_allowed", True)),
            human_review_required=bool(raw.get("human_review_required", False)),
            expected_tool_ids=tuple(
                str(item) for item in raw.get("expected_tool_ids") or ()
            ),
            post_verification=(
                dict(raw.get("post_verification") or {}) or None
            ),
        )


def load_workspace_query_gold_labels(
    path: Path,
    *,
    cases_path: Path,
) -> tuple[WorkspaceQueryGoldLabel, ...]:
    gold_payload = json.loads(path.read_text(encoding="utf-8"))
    raw_labels = gold_payload.get("labels") if isinstance(gold_payload, dict) else None
    if not isinstance(raw_labels, list):
        raise ValueError("gold file must contain a labels list")
    labels = tuple(WorkspaceQueryGoldLabel.from_mapping(item) for item in raw_labels)
    expected_count = gold_payload.get("expected_case_count")
    if expected_count is not None and len(labels) != int(expected_count):
        raise ValueError("gold label count does not match expected_case_count")
    if len({label.case_id for label in labels}) != len(labels):
        raise ValueError("gold label case IDs must be unique")

    case_payload = json.loads(cases_path.read_text(encoding="utf-8"))
    raw_cases = case_payload.get("cases") if isinstance(case_payload, dict) else None
    if not isinstance(raw_cases, list):
        raise ValueError("cases file must contain a cases list")
    questions = {
        str(item["case_id"]): str(item["question"])
        for item in raw_cases
        if isinstance(item, dict) and item.get("case_id") and item.get("question")
    }
    gold_ids = {label.case_id for label in labels}
    if gold_ids != set(questions):
        raise ValueError("gold label case IDs do not match source case IDs")
    return tuple(replace(label, question=questions[label.case_id]) for label in labels)


def grade_workspace_query_responses(
    label: WorkspaceQueryGoldLabel,
    responses: Sequence[WorkspaceQueryResponse],
) -> dict[str, Any]:
    failures: list[str] = []
    for assertion in label.assertions:
        kind = str(assertion.get("kind") or "")
        if not _assertion_passes(kind, assertion, responses):
            failures.append(kind or "invalid_assertion")
    return {
        "passed": not failures,
        "assertion_count": len(label.assertions),
        "failed_assertions": failures,
    }


def run_workspace_query_eval(
    *,
    cases_path: Path,
    gold_path: Path,
    project_root: Path,
    project_id: str,
) -> dict[str, Any]:
    labels = load_workspace_query_gold_labels(gold_path, cases_path=cases_path)
    service = WorkspaceQueryService(project_root)
    manifest = json.loads((project_root / "project.json").read_text(encoding="utf-8"))
    samples: list[dict[str, Any]] = []

    for label in labels:
        query = ScoutAssistantQuery(
            surface="pretrip",
            question=label.question,
            project_id=project_id,
        )
        plan = plan_scout_ai_tools(query, project_root=project_root)
        requests = _requests_for_label(label)
        responses = [service.execute(request) for request in requests]
        grade = grade_workspace_query_responses(label, responses)
        expected_refs = _expected_source_refs(label, manifest)
        returned_refs = {
            ref for response in responses for ref in response.source_refs
        }
        actual_operations = tuple(item.value for item in plan.expected_operations)
        operation_pass = set(actual_operations) == set(label.operations)
        artifact_pass = expected_refs <= returned_refs
        selected_tool_ids = {item.tool_id for item in plan.selected_tools}
        tool_selection_pass = (
            set(label.expected_tool_ids) <= selected_tool_ids
            if label.expected_tool_ids
            else bool(plan.expected_operations)
        )
        exact_tool_match = selected_tool_ids == set(label.expected_tool_ids)
        duplicate_calls = len(requests) - len({_canonical_json(item) for item in requests})
        expected_gap = (
            label.requires_live_state
            or label.requires_freshness
            or any(
                assertion.get("kind") == "answerability"
                and assertion.get("value") != "complete"
                for assertion in label.assertions
            )
        )
        completion = (
            grade["passed"]
            and all(response.status != "error" for response in responses)
            and (
                all(
                    response.answerability != "unsafe_to_infer"
                    for response in responses
                )
                or expected_gap
            )
        )
        grounded = completion and artifact_pass and all(
            _response_is_grounded(response, expected_gap=expected_gap)
            for response in responses
        )
        budget = AgentBudgetPolicy.for_query(
            question_class=plan.question_class,
            expected_operations=actual_operations,
            selected_tool_ids=tuple(selected_tool_ids),
            requires_join=plan.requires_join,
            requires_live_state=plan.requires_live_state,
        )
        tool_call_count = len(requests)
        request_count = min(budget.max_requests, 2 + tool_call_count)
        serialized_results = json.dumps(
            [response.model_dump(mode="json") for response in responses],
            ensure_ascii=False,
            sort_keys=True,
        )
        input_tokens = estimate_tokens(label.question) + estimate_tokens(
            serialized_results
        )
        output_tokens = estimate_tokens(" ".join(item.summary for item in responses))
        budget_exhausted = (
            tool_call_count > budget.max_tool_calls
            or request_count > budget.max_requests
        )
        samples.append(
            {
                "case_id": label.case_id,
                "question": label.question,
                "question_class": plan.question_class.value,
                "expected_artifact_keys": list(label.artifact_keys),
                "expected_source_refs": sorted(expected_refs),
                "returned_source_refs": sorted(returned_refs),
                "artifact_selection_pass": artifact_pass,
                "expected_operations": list(label.operations),
                "planned_operations": list(actual_operations),
                "operation_selection_pass": operation_pass,
                "expected_tool_ids": list(label.expected_tool_ids),
                "selected_tool_ids": sorted(selected_tool_ids),
                "tool_selection_pass": tool_selection_pass,
                "exact_required_tool_match": exact_tool_match,
                "answer_completed": completion,
                "grounded": grounded,
                "deterministic_fact_grade": grade,
                "unsupported_claim_count": 0,
                "request_count": request_count,
                "tool_call_count": tool_call_count,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "duplicate_identical_tool_call_count": duplicate_calls,
                "no_progress_stop": False,
                "budget_exhausted": budget_exhausted,
                "budget": budget.model_dump(mode="json"),
                "responses": [
                    response.model_dump(mode="json") for response in responses
                ],
            }
        )

    metrics = _aggregate_metrics(samples)
    return {
        "artifact_kind": ARTIFACT_KIND,
        "artifact_version": ARTIFACT_VERSION,
        "evaluation_semantics": (
            "offline deterministic operation-level architecture replay; "
            "not a cloud-model quality score"
        ),
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "project_id": project_id,
        "case_count": len(samples),
        "metrics": metrics,
        "question_class_metrics": _question_class_metrics(samples),
        "failed_case_ids": {
            "artifact_selection": _failed_ids(samples, "artifact_selection_pass"),
            "operation_selection": _failed_ids(samples, "operation_selection_pass"),
            "tool_selection": _failed_ids(samples, "tool_selection_pass"),
            "exact_required_tool_match": _failed_ids(
                samples,
                "exact_required_tool_match",
            ),
            "answer_completion": _failed_ids(samples, "answer_completed"),
            "grounding": _failed_ids(samples, "grounded"),
            "deterministic_fact": [
                sample["case_id"]
                for sample in samples
                if not sample["deterministic_fact_grade"]["passed"]
            ],
        },
        "samples": samples,
    }


def write_workspace_query_eval_report(report: Mapping[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _requests_for_label(label: WorkspaceQueryGoldLabel) -> list[dict[str, Any]]:
    if label.requests:
        return [deepcopy(item) for item in label.requests]
    if "diff" in label.operations:
        if len(label.artifact_keys) != 2:
            raise ValueError(f"{label.case_id}: diff requires exactly two artifacts")
        return [
            {
                "operation": "diff",
            "left_artifact": _artifact_selector(
                label.artifact_keys[0],
                collection_path=(label.collection_paths or {}).get(
                    label.artifact_keys[0]
                ),
            ),
            "right_artifact": _artifact_selector(
                label.artifact_keys[1],
                collection_path=(label.collection_paths or {}).get(
                    label.artifact_keys[1]
                ),
            ),
            }
        ]

    requests: list[dict[str, Any]] = []
    targets: list[tuple[str, str]]
    if len(label.operations) == 1 and len(label.artifact_keys) > 1:
        targets = [
            (label.operations[0], artifact_key)
            for artifact_key in label.artifact_keys
        ]
    else:
        targets = [
            (operation, label.artifact_keys[min(index, len(label.artifact_keys) - 1)])
            for index, operation in enumerate(label.operations)
        ]
    for operation, artifact_key in targets:
        request: dict[str, Any] = {
            "operation": operation,
            "artifact": _artifact_selector(
                artifact_key,
                collection_path=(label.collection_paths or {}).get(artifact_key),
            ),
        }
        if operation in {"inspect", "filter"}:
            request["fields"] = list(label.fields)
        if operation == "filter" and label.predicates:
            request["predicates"] = [dict(item) for item in label.predicates]
        field = (label.operation_fields or {}).get(operation)
        if operation in {"distinct", "group_by", "top_k", "argmax"}:
            if not field:
                raise ValueError(f"{label.case_id}: {operation} requires operation field")
            request["field"] = field
        if operation in {"top_k", "argmax"}:
            request["fields"] = list(label.fields)
        if operation == "top_k":
            request["k"] = 5
        if operation == "argmax" and (label.operation_fields or {}).get(
            "subtract_field"
        ):
            request["subtract_field"] = (label.operation_fields or {})[
                "subtract_field"
            ]
        if operation == "exists" and field:
            request["field"] = field
        if operation == "freshness":
            if field:
                request["timestamp_field"] = field
            request["now"] = "2030-01-01T00:00:00Z"
            request["stale_after_seconds"] = 86400
        if operation in {"nearest", "interval", "route_forward"}:
            raise ValueError(f"{label.case_id}: {operation} requires explicit request")
        requests.append(request)
    return requests


def _assertion_passes(
    kind: str,
    assertion: Mapping[str, Any],
    responses: Sequence[WorkspaceQueryResponse],
) -> bool:
    if kind == "structured_evidence":
        return all(
            response.status != "error"
            and bool(response.source_refs)
            and bool(response.results)
            for response in responses
        )
    if kind == "exact_count":
        expected = int(assertion["value"])
        return any(
            response.operation.value == "count" and response.result_count == expected
            for response in responses
        )
    if kind == "exact_record_id":
        expected = str(assertion["value"])
        return any(
            item.record_id == expected
            for response in responses
            for item in response.results
        )
    if kind == "numeric_tolerance":
        expected = float(assertion["value"])
        tolerance = float(assertion.get("tolerance", 1e-6))
        values = _result_values(responses, str(assertion["field"]))
        return any(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isclose(float(value), expected, abs_tol=tolerance, rel_tol=0.0)
            for value in values
        )
    if kind == "field_presence":
        return all(
            bool(_result_values(responses, str(field)))
            for field in assertion.get("value") or ()
        )
    if kind == "exact_value":
        return assertion.get("value") in _result_values(
            responses,
            str(assertion["field"]),
        )
    if kind == "scanned_record_count":
        expected = int(assertion["value"])
        return any(
            response.scanned_record_count == expected for response in responses
        )
    if kind == "group_distribution":
        actual = {
            str(item.data["group"]): int(item.data["count"])
            for response in responses
            for item in response.results
            if "group" in item.data and "count" in item.data
        }
        return actual == dict(assertion["value"])
    if kind == "top_k_record_ids":
        expected = [str(item) for item in assertion["value"]]
        actual = [
            item.record_id
            for response in responses
            if response.operation.value == "top_k"
            for item in response.results
        ]
        return actual[: len(expected)] == expected
    if kind == "canonical_equal":
        expected = bool(assertion["value"])
        return expected in _result_values(responses, "equal")
    if kind == "answerability":
        return str(assertion["value"]) in {
            response.answerability for response in responses
        }
    if kind == "candidate_boundary":
        return all(
            response.candidate_only is True
            and response.runtime_safety_truth is False
            and all(
                item.candidate_only is True and item.runtime_safety_truth is False
                for item in response.results
            )
            for response in responses
        )
    if kind == "source_ref_presence":
        expected = {str(item) for item in assertion["value"]}
        actual = {ref for response in responses for ref in response.source_refs}
        return expected <= actual
    return False


def _response_is_grounded(
    response: WorkspaceQueryResponse,
    *,
    expected_gap: bool,
) -> bool:
    if response.status == "error":
        return False
    if expected_gap and response.answerability in {
        "missing_artifact",
        "missing_required_fields",
        "requires_human_review",
        "requires_live_state",
        "stale",
    }:
        has_gap_provenance = bool(response.root_cause or response.freshness)
        has_source = bool(response.source_refs) or response.answerability == "requires_live_state"
        return has_gap_provenance and has_source
    if not response.source_refs or not response.results:
        return False
    return all(
        bool(item.evidence_id and item.source_ref and item.source_hash and item.locator)
        for item in response.results
    )


def _aggregate_metrics(samples: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    case_count = len(samples)
    tool_calls = [int(item["tool_call_count"]) for item in samples]
    requests = [int(item["request_count"]) for item in samples]
    input_tokens = [int(item["input_tokens"]) for item in samples]
    successful_tokens = [
        int(item["input_tokens"]) + int(item["output_tokens"])
        for item in samples
        if item["grounded"]
    ]
    return {
        "artifact_selection_accuracy": _rate(samples, "artifact_selection_pass"),
        "operation_selection_accuracy": _rate(samples, "operation_selection_pass"),
        "tool_selection_pass_rate": _rate(samples, "tool_selection_pass"),
        "exact_required_tool_match_rate": _rate(
            samples,
            "exact_required_tool_match",
        ),
        "answer_completion_rate": _rate(samples, "answer_completed"),
        "grounded_answer_rate": _rate(samples, "grounded"),
        "deterministic_fact_accuracy": round(
            sum(bool(item["deterministic_fact_grade"]["passed"]) for item in samples)
            / case_count,
            4,
        )
        if case_count
        else 0.0,
        "unsupported_claim_count": sum(
            int(item["unsupported_claim_count"]) for item in samples
        ),
        "model_requests": _distribution(requests),
        "tool_calls": _distribution(tool_calls),
        "input_tokens": _distribution(input_tokens),
        "tokens_per_successful_grounded_answer": (
            round(sum(successful_tokens) / len(successful_tokens), 2)
            if successful_tokens
            else None
        ),
        "recovery_attempt_count": 0,
        "recovery_success_rate": None,
        "no_progress_stop_count": sum(bool(item["no_progress_stop"]) for item in samples),
        "budget_exhaustion_count": sum(bool(item["budget_exhausted"]) for item in samples),
        "duplicate_identical_tool_call_count": sum(
            int(item["duplicate_identical_tool_call_count"]) for item in samples
        ),
    }


def _question_class_metrics(
    samples: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for sample in samples:
        grouped[str(sample["question_class"])].append(sample)
    return {
        question_class: {
            "case_count": len(items),
            "answer_completion_rate": _rate(items, "answer_completed"),
            "grounded_answer_rate": _rate(items, "grounded"),
            "requests": _distribution([int(item["request_count"]) for item in items]),
            "tool_calls": _distribution(
                [int(item["tool_call_count"]) for item in items]
            ),
        }
        for question_class, items in sorted(grouped.items())
    }


def _expected_source_refs(
    label: WorkspaceQueryGoldLabel,
    manifest: Mapping[str, Any],
) -> set[str]:
    refs: set[str] = set()
    for key in label.artifact_keys:
        if key == "@project":
            refs.add("project.json")
            continue
        value = manifest.get(key)
        if isinstance(value, str) and value:
            refs.add(value)
    return refs


def _artifact_selector(
    key: str,
    *,
    collection_path: str | None = None,
) -> dict[str, str]:
    selector = (
        {"source_ref": "project.json"}
        if key == "@project"
        else {"project_ref_key": key}
    )
    if collection_path:
        selector["collection_path"] = collection_path
    return selector


def _result_values(
    responses: Sequence[WorkspaceQueryResponse],
    field: str,
) -> list[Any]:
    values: list[Any] = []
    leaf = field.rsplit(".", 1)[-1]
    for response in responses:
        for item in response.results:
            values.extend(_nested_values(item.data, field, leaf))
    return values


def _nested_values(value: Any, field: str, leaf: str) -> list[Any]:
    found: list[Any] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key) in {field, leaf}:
                found.append(item)
            found.extend(_nested_values(item, field, leaf))
    elif isinstance(value, list):
        for item in value:
            found.extend(_nested_values(item, field, leaf))
    return found


def _failed_ids(samples: Sequence[Mapping[str, Any]], field: str) -> list[str]:
    return [str(item["case_id"]) for item in samples if not bool(item[field])]


def _rate(samples: Sequence[Mapping[str, Any]], field: str) -> float:
    return (
        round(sum(bool(item[field]) for item in samples) / len(samples), 4)
        if samples
        else 0.0
    )


def _distribution(values: Sequence[int]) -> dict[str, float | int]:
    if not values:
        return {"mean": 0.0, "p50": 0, "p95": 0}
    return {
        "mean": round(statistics.fmean(values), 4),
        "p50": _nearest_rank_percentile(values, 0.5),
        "p95": _nearest_rank_percentile(values, 0.95),
    }


def _nearest_rank_percentile(values: Sequence[int], percentile: float) -> int:
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD_PATH)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    report = run_workspace_query_eval(
        cases_path=args.cases,
        gold_path=args.gold,
        project_root=args.project_root,
        project_id=args.project_id,
    )
    write_workspace_query_eval_report(report, args.output)
    print(json.dumps(report["metrics"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
