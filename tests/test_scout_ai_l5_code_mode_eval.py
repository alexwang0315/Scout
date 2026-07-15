from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scout.schemas.agent_runtime import EvidenceCard, QuestionClass
from pydantic_ai.messages import ModelRequest, ToolReturnPart
from tools.scout_ai_workspace_query_eval import WorkspaceQueryGoldLabel
from tools.scout_ai_l5_code_mode_eval import (
    DEFAULT_L5_MODEL,
    L5_MAX_REQUESTS,
    L5_MAX_TOOL_CALLS,
    L5CodeModeEvalRunner,
    _deterministic_evidence_answer,
    _l5_tool_choice,
    _l5_nested_tool_limit,
    _l5_system_prompt,
    _l5_attempt_succeeded,
    _l5_no_progress_signature,
    _relevant_manifest_ref_keys,
    _grade_l5_workspace_responses,
    augment_l5_report,
    check_l5_eval_readiness,
)


class UsageLimitExceeded(Exception):
    pass


def test_l5_eval_readiness_accepts_exact_100_cases_and_confined_project(
    tmp_path: Path,
) -> None:
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps(
                        {
                "cases": [
                    {
                        "case_id": f"case-{index:03d}",
                        "question": f"question {index}",
                        "required_tool_ids": [],
                    }
                    for index in range(100)
                ]
            }
        ),
        encoding="utf-8",
    )
    workspace = tmp_path / "workspace"
    project = workspace / "fixture"
    project.mkdir(parents=True)
    (project / "project.json").write_text(
        json.dumps({"project_id": "fixture"}), encoding="utf-8"
    )

    readiness = check_l5_eval_readiness(
        cases_file=cases_path,
        workspace_root=workspace,
        project_id="fixture",
        expected_case_count=100,
    )

    assert readiness.ready is True
    assert readiness.case_count == 100
    assert readiness.runtime.available is True
    assert readiness.allowed_tool_ids == ["scout.ai.workspace.query.v1"]
    assert readiness.blockers == []


def test_l5_eval_readiness_reports_case_count_and_project_blockers(
    tmp_path: Path,
) -> None:
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(json.dumps({"cases": []}), encoding="utf-8")

    readiness = check_l5_eval_readiness(
        cases_file=cases_path,
        workspace_root=tmp_path / "missing",
        project_id="missing",
        expected_case_count=100,
    )

    assert readiness.ready is False
    assert "expected_100_cases_got_0" in readiness.blockers
    assert "project_manifest_unavailable" in readiness.blockers


def test_l5_eval_defaults_to_free_router_and_reports_pass_at_k_attempts() -> None:
    assert DEFAULT_L5_MODEL == "openrouter:poolside/laguna-m.1:free"
    report = {
        "samples": [
            {
                "question": "q",
                "grounding_verification": {"passed": True},
            }
        ]
    }
    failed = {
        "status": "fail_closed",
        "code_mode_call_count": 0,
        "nested_tool_call_count": 0,
        "nested_tool_calls": [],
    }
    passed = {
        "status": "success",
        "code_mode_call_count": 1,
        "nested_tool_call_count": 1,
        "nested_tool_calls": [{"operation": "count"}],
    }

    augmented = augment_l5_report(
        report,
        [
            {"question": "q", "attempt": 1, "receipt": failed},
            {"question": "q", "attempt": 2, "receipt": passed},
        ],
    )

    assert augmented["samples"][0]["l5_attempt_count"] == 2
    assert augmented["samples"][0]["l5_attempt_receipts"] == [failed, passed]
    assert augmented["samples"][0]["l5_execution_receipt"] == passed
    assert augmented["l5_metrics"]["attempt_count"] == 2
    assert augmented["l5_metrics"]["grounded_answer_count"] == 1


def test_l5_eval_runner_accepts_explicit_single_attempt_model_gate() -> None:
    runner = L5CodeModeEvalRunner(
        model_name=DEFAULT_L5_MODEL,
        base_url=None,
        api_key=None,
        max_attempts=1,
    )

    assert runner.max_attempts == 1
    assert L5_MAX_REQUESTS == 10
    assert L5_MAX_TOOL_CALLS == 10


def test_l5_runner_stops_repeated_evidence_free_failure_before_wasting_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = L5CodeModeEvalRunner(
        model_name=DEFAULT_L5_MODEL,
        base_url=None,
        api_key=None,
        max_attempts=10,
    )
    calls = 0

    def fail_without_evidence(self: L5CodeModeEvalRunner, *_: object, **__: object) -> str:
        nonlocal calls
        calls += 1
        self.last_l5_execution_receipt = {
            "status": "fail_closed",
            "stop_reason": "model_run_UsageLimitExceeded",
            "code_mode_call_count": 0,
            "nested_tool_call_count": 0,
            "nested_tool_calls": [],
        }
        raise UsageLimitExceeded("same external failure")

    monkeypatch.setattr(
        L5CodeModeEvalRunner,
        "_run_once_with_workspace_tools",
        fail_without_evidence,
    )

    output = runner.run_with_workspace_tools(
        "question",
        timeout_seconds=0,
        tool_context=SimpleNamespace(invocations=[]),
    )

    assert output == ""
    assert calls == 2
    assert runner.max_attempts == 10


def test_l5_no_progress_signature_is_disabled_when_evidence_exists() -> None:
    receipt = {
        "status": "fail_closed",
        "stop_reason": "model_run_UsageLimitExceeded",
    }

    assert _l5_no_progress_signature(receipt, {}, []) is not None
    assert _l5_no_progress_signature(receipt, {}, [{"source_refs": ["a.json"]}]) is None


def test_l5_deterministic_answer_keeps_evidence_values_with_summary() -> None:
    answer = _deterministic_evidence_answer(
        [
            EvidenceCard(
                tool_id="scout.ai.workspace.query.v1",
                claim_summary="artifact inspected",
                key_values={
                    "project_id": "fixture",
                    "route_name": "route-a",
                },
                source_refs=["project.json"],
            )
        ]
    )

    assert "artifact inspected" in answer
    assert '"project_id": "fixture"' in answer
    assert '"route_name": "route-a"' in answer
    assert "[project.json]" in answer

    record_answer = _deterministic_evidence_answer(
        [
            EvidenceCard(
                tool_id="scout.ai.workspace.query.v1",
                claim_summary="artifact inspected",
                source_refs=["project.json"],
                evidence_records=[
                    {
                        "evidence_id": "ev-project",
                        "source_ref": "project.json",
                        "record_id": "inspect",
                        "locator": "/$aggregate/inspect",
                        "source_hash": "sha256:" + "a" * 64,
                        "data": {
                            "selected_fields": {
                                "project_id": "fixture",
                                "route_name": "route-a",
                            }
                        },
                    },
                    {
                        "evidence_id": "ev-fields",
                        "source_ref": "project.json",
                        "record_id": "fields",
                        "locator": "/$aggregate/fields",
                        "source_hash": "sha256:" + "b" * 64,
                        "data": {"available_fields": ["notes", "features"]},
                    },
                    {
                        "evidence_id": "ev-gpx",
                        "source_ref": "project.json",
                        "record_id": "gpx",
                        "locator": "/$aggregate/gpx",
                        "source_hash": "sha256:" + "c" * 64,
                        "data": {"uri": "/Users/example/route.gpx"},
                    },
                ],
            )
        ]
    )
    assert '"project_id": "fixture"' in record_answer
    assert '"route_name": "route-a"' in record_answer
    assert '["' not in record_answer
    assert '"uri": "route.gpx"' in record_answer
    assert "/Users/example" not in record_answer

    clean_answer = _deterministic_evidence_answer(
        [
            EvidenceCard(
                tool_id="scout.ai.workspace.query.v1",
                claim_summary="status=error",
                key_values={"status": "error"},
            ),
            EvidenceCard(
                tool_id="scout.ai.workspace.query.v1",
                claim_summary="artifact inspected",
                key_values={
                    "status": "warning",
                    "results": "[nested content omitted]",
                },
                source_refs=["project.json"],
                evidence_records=[
                    {
                        "evidence_id": "ev-project",
                        "source_ref": "project.json",
                        "record_id": "inspect",
                        "locator": "/$aggregate/inspect",
                        "source_hash": "sha256:" + "a" * 64,
                        "data": {
                            "selected_fields": {"project_id": "fixture"},
                            "top_level_keys": ["notes", "features"],
                        },
                    }
                ],
            ),
        ]
    )
    assert "status=error" not in clean_answer
    assert "nested content omitted" not in clean_answer
    assert '["' not in clean_answer
    assert clean_answer.endswith("[project.json]")


def test_l5_tool_choice_forces_one_code_phase_then_synthesis() -> None:
    assert _l5_tool_choice([]) == "required"
    messages = [
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="run_code",
                    content={"ok": True},
                    tool_call_id="code-1",
                )
            ]
        )
    ]

    assert _l5_tool_choice(messages) == "none"


def test_l5_nested_tool_limit_scales_with_question_class() -> None:
    assert _l5_nested_tool_limit(
        question_class=QuestionClass.STATIC_WORKSPACE_FACT,
        expected_operations=("inspect",),
    ) == 10
    assert _l5_nested_tool_limit(
        question_class=QuestionClass.WEATHER_TERRAIN_COMPOUND,
        expected_operations=("freshness", "nearest"),
    ) == 10


def test_l5_prompt_discloses_compact_project_identity_query_example() -> None:
    prompt = _l5_system_prompt()

    assert "source_ref': 'project.json'" in prompt
    assert "fields=['project_id', 'route_name']" in prompt
    assert "inputs.golden_route_gpx.uri" in prompt
    assert "reference_track_count" in prompt
    assert "historical_gpx_source_index_ref" in prompt
    assert "collection_path': 'sources'" in prompt
    assert "original_filename" in prompt
    assert "'descending': False" in prompt


def test_l5_attempt_requires_both_grounding_and_success_receipt() -> None:
    assert _l5_attempt_succeeded(
        {"passed": True}, {"status": "success"}
    ) is True
    assert _l5_attempt_succeeded(
        {"passed": True}, {"status": "fail_closed"}
    ) is False


def test_l5_manifest_ref_ranking_prioritizes_reference_gpx(tmp_path: Path) -> None:
    (tmp_path / "project.json").write_text(
        json.dumps(
            {
                "project_id": tmp_path.name,
                "brain_seed_nodes_ref": "outputs/brain.json",
                "reference_tracks_ref": "outputs/reference_tracks.json",
                "historical_gpx_source_index_ref": "sources/gpx.json",
            }
        ),
        encoding="utf-8",
    )

    refs = _relevant_manifest_ref_keys(
        tmp_path,
        question="共有多少條 reference GPX，列出前五個檔名",
    )

    assert refs[0] == "reference_tracks_ref"
    assert "historical_gpx_source_index_ref" in refs[:3]


def test_l5_semantic_grade_requires_expected_artifact_operation_and_assertions() -> None:
    label = WorkspaceQueryGoldLabel(
        case_id="case-1",
        artifact_keys=("@project",),
        operations=("inspect",),
        fields=("project_id", "route_name"),
        assertions=(
            {"kind": "field_presence", "value": ["project_id", "route_name"]},
            {"kind": "candidate_boundary"},
        ),
    )
    response = {
        "status": "success",
        "answerability": "complete",
        "operation": "inspect",
        "summary": "artifact inspected",
        "results": [
            {
                "evidence_id": "ev-project",
                "source_ref": "project.json",
                "record_id": "inspect",
                "locator": "/$aggregate/inspect",
                "source_hash": "sha256:" + "a" * 64,
                "data": {
                    "selected_fields": {
                        "project_id": "fixture",
                        "route_name": "route-a",
                    }
                },
            }
        ],
        "result_count": 1,
        "scanned_record_count": 1,
        "source_refs": ["project.json"],
    }

    passed = _grade_l5_workspace_responses(label, [response], {})
    wrong_artifact = _grade_l5_workspace_responses(
        label,
        [{**response, "source_refs": ["outputs/wrong.json"]}],
        {},
    )

    assert passed["passed"] is True
    assert passed["artifact_pass"] is True
    assert passed["operation_pass"] is True
    assert wrong_artifact["passed"] is False
    assert wrong_artifact["artifact_pass"] is False
    assert _l5_attempt_succeeded(
        {"passed": False}, {"status": "success"}
    ) is False
