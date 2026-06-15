from pathlib import Path

from scout_review_gap_tool import (
    REVIEW_GAP_OUTPUT_KIND,
    REVIEW_GAP_TOOL_ID,
    assess_scout_review_gap,
)


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"


def test_review_gap_surfaces_unpromoted_weather_review_item() -> None:
    result = assess_scout_review_gap(
        PROJECT_ROOT,
        query="哪些天氣證據還沒有人工審核，不能升格為出發依據？",
        category="weather_daylight",
    )

    assert result["artifact_kind"] == REVIEW_GAP_OUTPUT_KIND
    assert result["tool_id"] == REVIEW_GAP_TOOL_ID
    assert result["answerability"] == "review_gap_found"
    assert result["decision"] == "DELAY"
    assert result["allowed"] is False
    assert result["review_gap"]["role"] == "Review / Provenance Gap Assessor"
    assert result["review_gap"]["counts"]["unresolved_review_count"] == 1
    assert result["review_gap"]["counts"]["warning_count"] == 1
    assert result["review_gap"]["unpromoted_evidence"][0]["category"] == (
        "weather_daylight"
    )
    assert result["review_gap"]["unpromoted_evidence"][0][
        "human_review_required"
    ] is True
    assert result["decision_output"]["decisionObjectSchema"] == "ContextualPermission"
    assert result["decision_output"]["decision"] == "DELAY"
    assert result["decision_output"]["cost"]["promotionAllowed"] is False
    assert result["decision_output"]["reviewWritePerformed"] is False
    assert result["review_governance"]["review_write_performed"] is False
    assert result["boundary"]["runtime_safety_truth"] is False


def test_review_gap_clear_filter_is_still_candidate_only() -> None:
    result = assess_scout_review_gap(
        PROJECT_ROOT,
        query="有沒有 blocker review gap？",
        severity="blocker",
    )

    assert result["answerability"] == "review_gap_clear"
    assert result["decision"] == "CONDITIONAL_GO"
    assert result["allowed"] is True
    assert result["review_gap"]["counts"]["matched_item_count"] == 0
    assert result["decision_output"]["runtimeSafetyTruth"] is False
    assert "不是 departure approval" in result["decision_output"]["firstLayer"]["limit"]


def test_review_gap_output_kind_constant() -> None:
    assert REVIEW_GAP_OUTPUT_KIND == "scout_ai_review_gap_tool_output"
