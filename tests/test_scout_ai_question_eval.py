from __future__ import annotations

import json
from pathlib import Path

from scout_agent_builtin_tools import run_builtin_tool
from scout_agent_tools import load_tool_manifest
from scout_ai_question_eval import (
    ARTIFACT_KIND,
    evaluate_question,
    evaluate_question_corpus,
    load_question_corpus,
    render_markdown_report,
)


ROOT = Path(__file__).resolve().parents[1]
CORPUS_PATH = ROOT / "docs" / "specs" / "scout-ai-200-question-corpus.json"
MANIFEST_PATH = ROOT / "tools" / "scout_agent_tool_manifests" / "scout.ai.question_answerability.eval.json"


def test_scout_ai_question_corpus_preserves_two_100_question_sets() -> None:
    questions = load_question_corpus(CORPUS_PATH)
    source_counts: dict[str, int] = {}
    for question in questions:
        source_counts[question["source_set"]] = source_counts.get(question["source_set"], 0) + 1

    assert len(questions) == 200
    assert source_counts == {
        "assistant_seed_100": 100,
        "user_field_100": 100,
    }
    assert questions[0]["question"] == "這趟行程總共有幾個 CP？"
    assert questions[-1]["question"] == "下次行前規劃要改哪三件事？"


def test_question_eval_classifies_current_tools_and_missing_live_evidence() -> None:
    route_eval = evaluate_question(
        {
            "id": "q-route",
            "source_set": "test",
            "category": "route",
            "question": "黑水塘在第幾個 CP 附近？",
        }
    )
    live_eval = evaluate_question(
        {
            "id": "q-live",
            "source_set": "test",
            "category": "navigation",
            "question": "我現在是不是偏離路線？",
        }
    )
    rescue_eval = evaluate_question(
        {
            "id": "q-rescue",
            "source_set": "test",
            "category": "rescue",
            "question": "是否要通知留守人？",
        }
    )
    route_context_eval = evaluate_question(
        {
            "id": "q-route-context",
            "source_set": "test",
            "category": "route_context",
            "question": "下一個觀察點在哪？哪裡適合拍攝大景？",
        }
    )
    pace_guardian_eval = evaluate_question(
        {
            "id": "q-pace-guardian",
            "source_set": "test",
            "category": "team_pace_fit",
            "question": "隊伍腳程是否能準時抵達下一個 CP？最慢者需要前移午餐點嗎？",
        }
    )
    equipment_eval = evaluate_question(
        {
            "id": "q-equipment-resource",
            "source_set": "test",
            "category": "equipment_resource",
            "question": "手機電量和頭燈水量夠嗎？",
        }
    )
    route_architecture_eval = evaluate_question(
        {
            "id": "q-route-architecture",
            "source_set": "test",
            "category": "route_architecture",
            "question": "最晚折返點在哪？這條路線難點在哪裡？",
        }
    )

    assert route_eval.answerability == "answerable_by_current_read_only_tools"
    assert "pydantic_ai.tool.search_scout_route_structure.v0" in route_eval.current_tool_ids
    assert "pydantic_ai.tool.search_scout_major_points.v0" in route_eval.current_tool_ids
    assert live_eval.answerability == "requires_missing_evidence"
    assert "scout.ai.live_navigation_state.assess.v0" in live_eval.current_tool_ids
    assert "scout.ai.live_navigation_state.assess.v0" in live_eval.recommended_tool_ids
    assert "current_position" in live_eval.missing_evidence
    assert route_context_eval.answerability == "answerable_by_current_read_only_tools"
    assert "scout.ai.route_context.assess.v0" in route_context_eval.current_tool_ids
    assert pace_guardian_eval.answerability == "requires_missing_evidence"
    assert "scout.ai.pace_guardian.assess.v0" in pace_guardian_eval.current_tool_ids
    assert "user_or_team_baseline_profile" in pace_guardian_eval.missing_evidence
    assert equipment_eval.answerability == "requires_missing_evidence"
    assert "scout.ai.equipment_resource.assess.v0" in equipment_eval.current_tool_ids
    assert "equipment_inventory_or_battery_telemetry" in equipment_eval.missing_evidence
    assert route_architecture_eval.answerability == "answerable_by_current_read_only_tools"
    assert (
        "scout.ai.route_architecture.assess.v0"
        in route_architecture_eval.current_tool_ids
    )
    assert rescue_eval.answerability == "blocked_for_direct_action_can_only_explain"
    assert rescue_eval.safety_boundary["outbound_send_performed"] is False


def test_question_corpus_eval_report_lists_tool_and_gap_counts() -> None:
    report = evaluate_question_corpus(load_question_corpus(CORPUS_PATH))
    markdown = render_markdown_report(report)

    assert report["artifact_kind"] == ARTIFACT_KIND
    assert report["question_count"] == 200
    assert report["answerability_counts"]["answerable_by_current_read_only_tools"] > 0
    assert report["answerability_counts"]["requires_missing_evidence"] > 0
    assert report["recommended_tool_counts"]["scout.ai.live_navigation_state.assess.v0"] > 0
    assert report["missing_evidence_counts"]["current_position"] > 0
    assert "| field-100 | 下次行前規劃要改哪三件事？" in markdown
    assert report["boundary"]["safety_api_called"] is False


def test_question_answerability_manifest_and_builtin_tool_are_read_only(tmp_path: Path) -> None:
    manifest = load_tool_manifest(MANIFEST_PATH)
    request_path = tmp_path / "request.json"
    request_path.write_text(
        json.dumps(
            {
                "corpus_path": str(CORPUS_PATH),
                "project_root": str(
                    ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
                ),
            }
        ),
        encoding="utf-8",
    )

    exit_code, payload = run_builtin_tool(
        ["ai-question-answerability", "--input", str(request_path), "--json"]
    )

    assert manifest.id == "scout.ai.question_answerability.eval"
    assert manifest.mode == "local_evidence_query"
    assert manifest.allowed_writes == []
    assert "live.safety_api" in manifest.forbidden_writes
    assert manifest.metadata["read_only"] is True
    assert exit_code == 0
    assert payload["artifact_kind"] == "scout_ai_question_answerability_tool_output"
    assert payload["question_count"] == 200
    assert payload["boundary"]["phase1_l0_l4_state_mutated"] is False
    assert payload["report"]["artifact_kind"] == "scout_ai_question_answerability_eval"
