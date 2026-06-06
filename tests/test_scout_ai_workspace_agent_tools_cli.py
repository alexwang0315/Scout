from __future__ import annotations

import json
from pathlib import Path

from scout_agent_cli import run_scout_agent_cli
from scout_agent_trace import load_agent_trace


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
MANIFEST_DIR = ROOT / "tools" / "scout_agent_tool_manifests"
QUESTION_CORPUS = ROOT / "docs" / "specs" / "scout-ai-200-question-corpus.json"


def test_scout_ai_workspace_catalog_manifest_runs_with_trace(tmp_path: Path) -> None:
    request = tmp_path / "workspace-catalog.request.json"
    trace_log = tmp_path / "agent-trace.jsonl"
    request.write_text(
        json.dumps(
            {
                "project_root": str(PROJECT_ROOT),
                "query": "workspace route terrain risk",
                "limit": 4,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    exit_code, payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.ai.workspace_catalog.search",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--trace-log",
            str(trace_log),
            "--json",
        ]
    )

    assert exit_code == 0
    assert payload["status"] == "completed"
    output = json.loads(payload["outputs"]["stdout"])
    assert output["artifact_kind"] == "scout_ai_workspace_catalog_tool_output"
    assert output["summaries"]["artifact_ref_count"] >= 60
    assert output["boundary"]["runtime_safety_truth"] is False
    assert load_agent_trace(trace_log)[0].tool_id == "scout.ai.workspace_catalog.search"


def test_scout_ai_route_structure_manifest_runs(tmp_path: Path) -> None:
    output = _run_manifest(
        "scout.ai.route_structure.search",
        {"project_root": str(PROJECT_ROOT), "query": "有多少個 CP?", "limit": 3},
        tmp_path,
    )

    assert output["artifact_kind"] == "scout_ai_route_structure_tool_output"
    assert output["summaries"]["checkpoint_count"] == 124
    assert output["summaries"]["segment_count"] == 123
    assert output["boundary"]["phase1_safety_mutation_allowed"] is False


def test_scout_ai_major_points_manifest_runs(tmp_path: Path) -> None:
    output = _run_manifest(
        "scout.ai.major_points.search",
        {"project_root": str(PROJECT_ROOT), "query": "黑水塘在第幾 CP 附近?", "limit": 3},
        tmp_path,
    )

    assert output["artifact_kind"] == "scout_ai_major_points_tool_output"
    assert output["results"][0]["candidate_id"] == "mcp.heishuitang.002"
    assert output["results"][0]["nearest_cp_candidate_id"] == "cp.002"
    assert output["boundary"]["runtime_safety_truth"] is False


def test_scout_ai_evidence_fulltext_manifest_runs(tmp_path: Path) -> None:
    output = _run_manifest(
        "scout.ai.evidence_fulltext.search",
        {"project_root": str(PROJECT_ROOT), "query": "黑水塘", "limit": 3},
        tmp_path,
    )

    assert output["artifact_kind"] == "scout_ai_evidence_fulltext_tool_output"
    assert output["result_count"] >= 1
    assert output["results"][0]["record_id"] == "mcp.heishuitang.002"
    assert output["boundary"]["local_evidence_only"] is True


def test_scout_ai_question_answerability_manifest_runs(tmp_path: Path) -> None:
    output = _run_manifest(
        "scout.ai.question_answerability.eval",
        {"project_root": str(PROJECT_ROOT), "corpus_path": str(QUESTION_CORPUS)},
        tmp_path,
    )

    assert output["artifact_kind"] == "scout_ai_question_answerability_tool_output"
    assert output["question_count"] == 200
    assert output["answerability_counts"]["answerable_by_current_read_only_tools"] > 0
    assert output["answerability_counts"].get("needs_general_model_or_new_spec", 0) == 0
    assert output["boundary"]["safety_api_called"] is False
    assert output["report"]["artifact_kind"] == "scout_ai_question_answerability_eval"


def _run_manifest(
    tool_id: str,
    request_payload: dict[str, object],
    tmp_path: Path,
) -> dict[str, object]:
    request = tmp_path / f"{tool_id}.request.json"
    request.write_text(json.dumps(request_payload, ensure_ascii=False), encoding="utf-8")
    exit_code, payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            tool_id,
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--json",
        ]
    )

    assert exit_code == 0
    assert payload["status"] == "completed"
    return json.loads(payload["outputs"]["stdout"])
