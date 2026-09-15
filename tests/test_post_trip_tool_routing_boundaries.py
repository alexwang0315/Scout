"""Historical review keywords must not select a current pretrip reader."""
from pathlib import Path

import pytest

from assistant_models import AssistantSurface, ScoutAssistantQuery
from scout_ai_tool_planner import (
    LIVE_NAVIGATION_STATE_TOOL_ID,
    POST_TRIP_REVIEW_TOOL_ID,
    SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID,
    plan_scout_ai_tools,
)
from scout_terrain_score_tool import TERRAIN_SCORE_TOOL_ID
from scout_workspace_search_tools import ROUTE_STRUCTURE_TOOL_ID

ROOT = Path(__file__).resolve().parents[1]

def plan(question, folder="pretrip/projects/chilai_nanhua_day1"):
    return plan_scout_ai_tools(
        ScoutAssistantQuery(surface=AssistantSurface.PRETRIP, question=question,
                            context_ref="routing-fixture", project_id="routing-fixture"),
        project_root=ROOT / "tests/fixtures" / folder,
    )

@pytest.mark.parametrize("question,unrelated", [
    ("哪些歷史、自然、文化點值得補充到路線脈絡？", ROUTE_STRUCTURE_TOOL_ID),
    ("這次摸黑差點迷路，要怎麼檢討？", TERRAIN_SCORE_TOOL_ID),
    ("行後比預期難，摸黑前差點錯過岔路，隊友滑倒、脫隊，頭燈電量不足，午後低溫濕冷比預報早，下次要怎麼更新？", TERRAIN_SCORE_TOOL_ID),
])
def test_post_trip_learning_uses_review_artifacts_without_unrequested_pretrip_reader(question, unrelated):
    result = plan(question, "post_analysis/chilai_nanhua_day1_post_analysis")
    ids = {item.tool_id for item in result.selected_tools}
    assert POST_TRIP_REVIEW_TOOL_ID in ids
    assert unrelated not in ids
    assert not result.boundary.runtime_safety_truth

@pytest.mark.parametrize("question,required", [
    ("有多少個 CP？", ROUTE_STRUCTURE_TOOL_ID),
    ("哪些路段的地形不適合摸黑通過？", TERRAIN_SCORE_TOOL_ID),
    ("現在迷路了，前方是陡坡，應該怎麼辦？", SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID),
    ("現在迷路了，前方是陡坡，應該怎麼辦？", TERRAIN_SCORE_TOOL_ID),
    ("行後再檢討，我現在前方陡坡的地形資料是什麼？", TERRAIN_SCORE_TOOL_ID),
    ("行後再檢討，我現在前方陡坡的地形資料是什麼？", LIVE_NAVIGATION_STATE_TOOL_ID),
    ("行後 review，workspace terrain report 的 slope 數值是多少？", TERRAIN_SCORE_TOOL_ID),
])
def test_post_trip_routing_preserves_explicit_current_and_workspace_evidence(question, required):
    result = plan(question)
    assert required in {item.tool_id for item in result.selected_tools}
    assert not result.boundary.runtime_safety_truth
    assert result.max_tool_calls_per_attempt >= 10
