from __future__ import annotations

from tools.scout_ai_aihat2_fallback_eval import (
    assess_aihat_answer_quality,
    build_prompt,
)


def test_aihat2_eval_prompt_does_not_instruct_template_copy() -> None:
    prompt = build_prompt(
        question="哪些地方下雨後會變危險？",
        qeval={"id": "field-001", "category": "terrain_risk"},
        total_info=None,
        tool_results=[],
        missing_tools=[],
        missing_evidence=[],
        context={
            "deterministic_answer_hint": (
                "雨後需優先人工複核的最高候選風險點在最近 CP 213 約 190 m；"
                "GPX 累積約 106.27 km；score=99.58；bucket=extreme。"
            )
        },
    )

    assert "幾乎照抄" not in prompt
    assert "不得整段照抄" in prompt
    assert "Scout 工具摘要" in prompt


def test_aihat2_eval_quality_fails_template_copy_of_deterministic_hint() -> None:
    hint = (
        "雨後需優先人工複核的最高候選風險點在最近 CP 213 約 190 m；"
        "GPX 累積約 106.27 km；座標 23.9349004,121.2072142；"
        "score=99.58；bucket=extreme。"
    )

    quality = assess_aihat_answer_quality(
        f"結論：{hint}",
        missing_tools=[],
        missing_evidence=[],
        tool_results=[
            {
                "tool_id": "pydantic_ai.tool.search_scout_risk_scores.v0",
                "records": [
                    {
                        "readable_location": "最近 CP 213 約 190 m",
                        "score": 99.58,
                        "risk_bucket": "extreme",
                    }
                ],
            }
        ],
        deterministic_answer_hint=hint,
    )

    assert quality["classification"] == "quality_fail"
    assert "template_copy_of_deterministic_hint" in quality["failure_reasons"]
