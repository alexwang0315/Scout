from pathlib import Path

import pytest

from scout_ai_answer_synthesis import collect_and_synthesize_scout_ai_answer
from scout_ai_full_workflow import run_scout_ai_full_workflow
from scout_media_literacy_tool import MEDIA_LITERACY_TOOL_ID, assess_scout_media_literacy


PROJECT_ROOT = (
    Path(__file__).resolve().parents[1]
    / "tests/fixtures/pretrip/projects/chilai_nanhua_day1"
)
SPEED_QUESTION = "這個網紅影片說兩小時可到，我們可以照這個速度嗎？"


def _assert_speed_no_go_instruction(output: dict) -> None:
    assert output["action"] == "pace_adjustment"
    assert output["decision"] == "NO_GO"
    assert output["allowed"] is False
    assert output["runtimeSafetyTruth"] is False
    first = output["firstLayer"]
    assert first["decision"] == "不建議直接採用媒體的行走速度。"
    assert "最慢者" in first["limit"]
    assert "最慢者" in first["nextStep"]
    assert "不要追趕媒體配速" in first["nextStep"]
    assert output["nextAction"] == first["nextStep"]
    assert output["locationConstraint"] == first["limit"]
    assert output["alternativeActions"] == output["secondLayer"]["alternativeActions"]
    assert any("最慢者" in value for value in output["alternativeActions"])
    instructions = [
        first["decision"],
        first["limit"],
        first["nextStep"],
        *output["alternativeActions"],
    ]
    # The original bias reasons stay intact; action instructions must address pace.
    assert not any(
        term in value
        for value in instructions
        for term in ("拍照", "拍攝", "打卡", "改線", "點位")
    )
    assert f'[決策] {first["decision"]}' in output["text"]
    assert f'[下一步] {first["nextStep"]}' in output["text"]


@pytest.mark.parametrize(
    ("question", "source_platform"),
    [
        (SPEED_QUESTION, None),
        ("這段腳程可以照影片的速度嗎？", "網紅"),
    ],
    ids=["mixed-influencer-speed", "explicit-media-platform"],
)
def test_speed_no_go_instruction_reaches_all_media_payload_surfaces(
    question: str, source_platform: str | None
) -> None:
    result = assess_scout_media_literacy(
        PROJECT_ROOT, query=question, source_platform=source_platform
    )

    _assert_speed_no_go_instruction(result["decision_output"])
    assert result["decision"] == "NO_GO"
    assert result["allowed"] is False
    assert {
        item["bias_id"] for item in result["media_literacy"]["detected_biases"]
    } == {"check_in_pressure", "speed_bias"}
    assert result["media_literacy"]["next_action"] == result["decision_output"]["nextAction"]
    assert result["media_literacy"]["next_action"] in result["field_answer"]
    assert result["results"][0]["decision_output"] == result["decision_output"]
    assert result["results"][0]["field_answer"] == result["field_answer"]
    assert result["boundary"]["runtime_safety_truth"] is False


@pytest.mark.parametrize(
    "answer_function",
    [collect_and_synthesize_scout_ai_answer, run_scout_ai_full_workflow],
    ids=["synthesis", "full-workflow"],
)
def test_speed_instruction_keeps_media_as_final_no_go_source(answer_function) -> None:
    result = answer_function(
        SPEED_QUESTION,
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=6,
    )

    _assert_speed_no_go_instruction(result.decision_output)
    assert result.decision_output["answerSourceToolId"] == MEDIA_LITERACY_TOOL_ID
    assert result.boundary.runtime_safety_truth is False
    assert result.decision_output["firstLayer"]["decision"] in result.answer
