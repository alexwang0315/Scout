from __future__ import annotations

import json
from pathlib import Path

import pytest

from assistant_models import ScoutAssistantQuery
from scout.services.workspace_query import WorkspaceQueryService
from scout_ai_tool_planner import plan_scout_ai_tools
from tools.scout_ai_workspace_query_eval import (
    WorkspaceQueryGoldLabel,
    grade_workspace_query_responses,
    load_workspace_query_gold_labels,
    run_workspace_query_eval,
)


ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = (
    ROOT
    / "outputs"
    / "evals"
    / "scout_ai_workspace_grounded_100_questions_20260713_glm52_cases.json"
)
GOLD_PATH = ROOT / "tests" / "fixtures" / "scout_ai_workspace_query_gold_100.json"


def test_gold_labels_cover_the_100_case_corpus_with_operation_metadata() -> None:
    labels = load_workspace_query_gold_labels(GOLD_PATH, cases_path=CASES_PATH)

    assert len(labels) == 100
    assert len({label.case_id for label in labels}) == 100
    assert all(label.artifact_keys for label in labels)
    assert all(label.operations for label in labels)
    assert all(label.fields for label in labels)
    assert all(label.assertions for label in labels)
    by_id = {label.case_id: label for label in labels}
    assert by_id["workspace-20260713-032"].requires_join is True
    assert by_id["workspace-20260713-066"].requires_freshness is True
    assert by_id["workspace-20260713-097"].requires_live_state is True
    assert by_id["workspace-20260713-093"].operations == ("diff",)


def test_reference_gpx_gold_requires_count_and_first_five_filenames() -> None:
    labels = load_workspace_query_gold_labels(GOLD_PATH, cases_path=CASES_PATH)
    label = next(
        item for item in labels if item.case_id == "workspace-20260713-003"
    )

    assert label.artifact_keys == (
        "reference_tracks_ref",
        "historical_gpx_source_index_ref",
    )
    assert label.operations == ("inspect", "top_k")
    assert label.requests[1] == {
        "operation": "top_k",
        "artifact": {
            "project_ref_key": "historical_gpx_source_index_ref",
            "collection_path": "sources",
        },
        "predicates": [
            {"field": "role", "operator": "eq", "value": "reference_track"}
        ],
        "field": "original_filename",
        "fields": ["original_filename"],
        "k": 5,
        "descending": False,
    }
    expected_filenames = {
        "20161119_20奇萊連峰.gpx",
        "2024-09-14馬君山_萬里池(萬馬線)_ㄚ國_p.gpx",
        "990418能高安東軍GDB檔.gpx",
        "C_Documents and Settings_Administrator_桌面_20111127-29.gdb-GPX自動轉檔.gpx",
        "C_UsersltcDesktop20141010奇萊南峰.gdb.gpx",
    }
    asserted_filenames = {
        str(assertion["value"])
        for assertion in label.assertions
        if assertion.get("kind") == "exact_value"
        and assertion.get("field") == "original_filename"
    }
    assert asserted_filenames == expected_filenames


def test_gold_loader_rejects_case_drift(tmp_path: Path) -> None:
    cases = tmp_path / "cases.json"
    gold = tmp_path / "gold.json"
    cases.write_text(
        json.dumps({"cases": [{"case_id": "case-1", "question": "count"}]}),
        encoding="utf-8",
    )
    gold.write_text(
        json.dumps(
            {
                "labels": [
                    {
                        "case_id": "case-2",
                        "artifact_keys": ["items_ref"],
                        "operations": ["count"],
                        "fields": ["id"],
                        "assertions": [{"kind": "structured_evidence"}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="case IDs do not match"):
        load_workspace_query_gold_labels(gold, cases_path=cases)


def test_deterministic_grader_checks_exact_numeric_group_and_boundary(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "project.json").write_text(
        json.dumps({"items_ref": "items.json"}), encoding="utf-8"
    )
    (workspace / "items.json").write_text(
        json.dumps(
            {
                "items": [
                    {"id": "a", "score": 2.0, "bucket": "low"},
                    {"id": "b", "score": 9.5, "bucket": "high"},
                    {"id": "c", "score": 7.0, "bucket": "high"},
                ]
            }
        ),
        encoding="utf-8",
    )
    service = WorkspaceQueryService(workspace)
    responses = [
        service.execute(
            {
                "operation": "count",
                "artifact": {"project_ref_key": "items_ref"},
            }
        ),
        service.execute(
            {
                "operation": "argmax",
                "artifact": {"project_ref_key": "items_ref"},
                "field": "score",
                "fields": ["id", "score"],
            }
        ),
        service.execute(
            {
                "operation": "group_by",
                "artifact": {"project_ref_key": "items_ref"},
                "field": "bucket",
            }
        ),
    ]
    label = WorkspaceQueryGoldLabel.from_mapping(
        {
            "case_id": "case-1",
            "artifact_keys": ["items_ref"],
            "operations": ["count", "argmax", "group_by"],
            "fields": ["id", "score", "bucket"],
            "assertions": [
                {"kind": "exact_count", "value": 3},
                {"kind": "exact_record_id", "value": "b"},
                {
                    "kind": "numeric_tolerance",
                    "field": "score",
                    "value": 9.5,
                    "tolerance": 0.001,
                },
                {
                    "kind": "group_distribution",
                    "value": {"high": 2, "low": 1},
                },
                {"kind": "candidate_boundary"},
            ],
        }
    )

    grade = grade_workspace_query_responses(label, responses)

    assert grade["passed"] is True
    assert grade["assertion_count"] == 5
    assert grade["failed_assertions"] == []


def test_eval_reports_operation_fact_budget_and_class_metrics(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "project.json").write_text(
        json.dumps({"items_ref": "items.json"}), encoding="utf-8"
    )
    (workspace / "items.json").write_text(
        json.dumps({"items": [{"id": "a"}, {"id": "b"}]}),
        encoding="utf-8",
    )
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "case_id": "case-1",
                        "question": "workspace items 有多少筆？",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    gold_path = tmp_path / "gold.json"
    gold_path.write_text(
        json.dumps(
            {
                "labels": [
                    {
                        "case_id": "case-1",
                        "artifact_keys": ["items_ref"],
                        "operations": ["count"],
                        "fields": ["id"],
                        "assertions": [{"kind": "exact_count", "value": 2}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    report = run_workspace_query_eval(
        cases_path=cases_path,
        gold_path=gold_path,
        project_root=workspace,
        project_id="fixture",
    )

    assert report["case_count"] == 1
    assert report["metrics"]["operation_selection_accuracy"] == 1.0
    assert report["metrics"]["answer_completion_rate"] == 1.0
    assert report["metrics"]["grounded_answer_rate"] == 1.0
    assert report["metrics"]["deterministic_fact_accuracy"] == 1.0
    assert report["metrics"]["unsupported_claim_count"] == 0
    assert report["metrics"]["budget_exhaustion_count"] == 0
    assert report["metrics"]["duplicate_identical_tool_call_count"] == 0
    assert report["question_class_metrics"]["aggregate_workspace_fact"][
        "case_count"
    ] == 1
    assert report["samples"][0]["tool_call_count"] == 1
    assert report["samples"][0]["budget"]["max_tool_calls"] == 10


def test_eval_gold_collection_path_selects_the_intended_record_set(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "project.json").write_text(
        json.dumps({"items_ref": "items.json"}),
        encoding="utf-8",
    )
    (workspace / "items.json").write_text(
        json.dumps(
            {
                "noise": [{"id": "wrong"}],
                "target_records": [
                    {"id": "a"},
                    {"id": "b"},
                    {"id": "c"},
                ],
            }
        ),
        encoding="utf-8",
    )
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps(
            {"cases": [{"case_id": "case-1", "question": "有多少筆？"}]}
        ),
        encoding="utf-8",
    )
    gold_path = tmp_path / "gold.json"
    gold_path.write_text(
        json.dumps(
            {
                "labels": [
                    {
                        "case_id": "case-1",
                        "artifact_keys": ["items_ref"],
                        "collection_paths": {"items_ref": "target_records"},
                        "operations": ["count"],
                        "fields": ["id"],
                        "assertions": [{"kind": "exact_count", "value": 3}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    report = run_workspace_query_eval(
        cases_path=cases_path,
        gold_path=gold_path,
        project_root=workspace,
        project_id="fixture",
    )

    assert report["metrics"]["deterministic_fact_accuracy"] == 1.0
    assert report["samples"][0]["responses"][0]["result_count"] == 3


def test_eval_counts_a_sourced_missing_field_gap_as_grounded(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "project.json").write_text(
        json.dumps({"routes_ref": "routes.json"}),
        encoding="utf-8",
    )
    (workspace / "routes.json").write_text(
        json.dumps({"routes": [{"id": "retreat-1"}]}),
        encoding="utf-8",
    )
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps(
            {"cases": [{"case_id": "case-1", "question": "哪條最近？"}]}
        ),
        encoding="utf-8",
    )
    gold_path = tmp_path / "gold.json"
    gold_path.write_text(
        json.dumps(
            {
                "labels": [
                    {
                        "case_id": "case-1",
                        "artifact_keys": ["routes_ref"],
                        "operations": ["nearest"],
                        "fields": ["id"],
                        "assertions": [
                            {
                                "kind": "answerability",
                                "value": "missing_required_fields",
                            }
                        ],
                        "requires_join": True,
                        "requests": [
                            {
                                "operation": "nearest",
                                "artifact": {"project_ref_key": "routes_ref"},
                                "origin": {"lat": 23.0, "lon": 121.0},
                                "fields": ["id"],
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    report = run_workspace_query_eval(
        cases_path=cases_path,
        gold_path=gold_path,
        project_root=workspace,
        project_id="fixture",
    )

    assert report["metrics"]["answer_completion_rate"] == 1.0
    assert report["metrics"]["grounded_answer_rate"] == 1.0


def test_100_case_planner_meets_operation_and_required_tool_gates() -> None:
    labels = load_workspace_query_gold_labels(GOLD_PATH, cases_path=CASES_PATH)
    operation_passes = 0
    tool_passes = 0

    for label in labels:
        plan = plan_scout_ai_tools(
            ScoutAssistantQuery(
                surface="pretrip",
                question=label.question,
                project_id="fixture",
            ),
            project_root=ROOT,
        )
        planned_operations = {item.value for item in plan.expected_operations}
        selected_tools = {item.tool_id for item in plan.selected_tools}
        operation_passes += planned_operations == set(label.operations)
        tool_passes += set(label.expected_tool_ids) <= selected_tools

    assert operation_passes / len(labels) >= 0.95
    assert tool_passes / len(labels) >= 0.97
