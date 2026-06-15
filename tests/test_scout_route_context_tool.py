from pathlib import Path

from scout_route_context_tool import (
    ROUTE_CONTEXT_OUTPUT_KIND,
    ROUTE_CONTEXT_TOOL_ID,
    assess_scout_route_context,
)


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = (
    ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
)


def test_route_context_finds_candidate_viewpoint_and_experience_guidance() -> None:
    result = assess_scout_route_context(
        PROJECT_ROOT,
        query="哪裡適合拍攝或觀察大景?",
        limit=4,
    )

    assert result["tool_id"] == ROUTE_CONTEXT_TOOL_ID
    assert result["status"] == "completed"
    assert result["answerability"] == "route_context_available"
    assert result["source_status"] == "candidate_only"
    assert result["decision"] == "CONDITIONAL_GO"
    assert result["decision_output"]["decisionObjectSchema"] == "ContextualPermission"
    assert result["decision_output"]["firstLayer"]["decision"] == "可作為候選觀察點。"
    assert "不是停留授權" in result["decision_output"]["firstLayer"]["limit"]
    assert result["decision_output"]["runtimeSafetyTruth"] is False
    assert result["result_count"] >= 1
    assert result["route_context"]["role"] == "Experience Guide"
    assert result["route_context"]["stop_permission_required"] is True
    assert result["boundary"]["runtime_safety_truth"] is False
    assert result["boundary"]["safety_api_called"] is False
    assert "Experience Guide 候選" in result["field_answer"]
    assert "contextual permission" in result["field_answer"]

    labels = {item["label"] for item in result["results"]}
    assert "稜線啞口觀景點" in labels
    viewpoint = next(item for item in result["results"] if item["label"] == "稜線啞口觀景點")
    assert viewpoint["context_kind"] == "viewpoint"
    assert viewpoint["candidate_only"] is True
    assert viewpoint["runtime_safety_truth"] is False
    assert "停留風險預算" in viewpoint["stop_guidance"]


def test_route_context_keeps_risk_context_from_becoming_stop_permission() -> None:
    result = assess_scout_route_context(
        PROJECT_ROOT,
        query="大崩壁值得停下來看嗎?",
        limit=4,
    )

    risk_items = [item for item in result["results"] if item["label"] == "大崩壁"]
    assert risk_items
    assert result["decision"] == "NO_GO"
    assert result["decision_output"]["firstLayer"]["decision"] == (
        "不建議為觀察或拍攝停留。"
    )
    assert risk_items[0]["context_kind"] == "risk_context"
    assert "不建議" in risk_items[0]["stop_guidance"]
    assert result["route_context"]["stop_permission_tool_id"] == (
        "scout.ai.contextual_permission.assess.v0"
    )


def test_route_context_output_kind_constant() -> None:
    assert ROUTE_CONTEXT_OUTPUT_KIND == "scout_ai_route_context_tool_output"
