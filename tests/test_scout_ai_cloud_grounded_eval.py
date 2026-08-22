from tools.scout_ai_cloud_grounded_eval import build_cloud_grounded_prompt


def test_cloud_grounded_prompt_contains_question_tools_and_evidence_gaps() -> None:
    prompt = build_cloud_grounded_prompt(
        question="目前 route_name 是什麼？",
        tool_results=[
            {
                "tool_id": "pydantic_ai.tool.search_scout_workspace_catalog.v0",
                "status": "completed",
                "records": [{"route_name": "奇萊南華"}],
            }
        ],
        missing_tools=[],
        missing_evidence=["route_manifest:missing:updated_at"],
        total_info={"project_id": "chilai_nanhua_day1_scoutAI"},
    )

    assert "目前 route_name 是什麼？" in prompt
    assert "pydantic_ai.tool.search_scout_workspace_catalog.v0" in prompt
    assert "奇萊南華" in prompt
    assert "route_manifest:missing:updated_at" in prompt
    assert "AI HAT" not in prompt
    assert "不得把缺失證據補成事實" in prompt
