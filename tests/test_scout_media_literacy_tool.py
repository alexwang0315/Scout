from pathlib import Path

from scout_media_literacy_tool import (
    MEDIA_LITERACY_OUTPUT_KIND,
    MEDIA_LITERACY_TOOL_ID,
    assess_scout_media_literacy,
)


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"


def test_media_literacy_blocks_social_photo_pressure_on_risk_context() -> None:
    result = assess_scout_media_literacy(
        PROJECT_ROOT,
        query="IG 大崩壁美照會不會誤導？想去打卡。",
    )

    assert result["artifact_kind"] == MEDIA_LITERACY_OUTPUT_KIND
    assert result["tool_id"] == MEDIA_LITERACY_TOOL_ID
    assert result["answerability"] == "media_literacy_missing_context"
    assert result["decision"] == "NO_GO"
    assert result["allowed"] is False
    assert result["media_literacy"]["role"] == "Media Literacy / Bias Sentinel"
    assert {bias["bias_id"] for bias in result["media_literacy"]["detected_biases"]} >= {
        "beauty_photo_bias",
        "check_in_pressure",
    }
    assert result["media_bias_analysis"]["target_context_points"][0]["label"] == "大崩壁"
    assert result["media_bias_analysis"]["target_context_points"][0]["risk_context"] is True
    assert "fresh_weather_or_route_condition_review" in result["missing_fields"]
    assert "媒體識讀判斷" in result["field_answer"]
    assert "runtime safety truth" in result["field_answer"]
    assert result["decision_output"]["decisionObjectSchema"] == "ContextualPermission"
    assert result["decision_output"]["decision"] == "NO_GO"
    assert result["decision_output"]["allowed"] is False
    assert result["decision_output"]["firstLayer"]["decision"] == (
        "不建議為媒體點位停留或改線。"
    )
    assert "不得為拍照" in result["decision_output"]["firstLayer"]["limit"]
    assert result["decision_output"]["secondLayer"]["alternativeActions"]
    assert result["decision_output"]["runtimeSafetyTruth"] is False
    assert result["boundary"]["runtime_safety_truth"] is False
    assert result["boundary"]["outbound_send_performed"] is False


def test_media_literacy_guided_content_requires_guided_or_equivalent_support() -> None:
    result = assess_scout_media_literacy(
        PROJECT_ROOT,
        query="網紅跟嚮導走過，攻略說很輕鬆，我們也能複製嗎？",
        user_experience_level="new_to_similar_routes",
        weather_reviewed=True,
        guided_party=False,
    )

    assert result["decision"] == "GUIDED_ONLY"
    assert result["media_bias_analysis"]["bias_pressure_level"] == "medium"
    assert any(
        bias["bias_id"] == "guided_party_bias"
        for bias in result["media_literacy"]["detected_biases"]
    )
    assert result["media_literacy"]["next_action"].startswith("若沒有嚮導")
    assert result["decision_output"]["decision"] == "GUIDED_ONLY"
    assert result["decision_output"]["firstLayer"]["decision"] == (
        "不建議自主複製媒體路線。"
    )
    assert "嚮導" in result["decision_output"]["firstLayer"]["limit"]
    assert result["boundary"]["live_safety_api_calls_allowed"] is False


def test_media_literacy_output_kind_constant() -> None:
    assert MEDIA_LITERACY_OUTPUT_KIND == "scout_ai_media_literacy_tool_output"
