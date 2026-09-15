from pathlib import Path

import pytest

from assistant_models import ScoutAssistantQuery
from scout_ins_dr_trace_tool import INS_DR_TRACE_TOOL_ID
from scout_ai_tool_planner import plan_scout_ai_tools
from scout_navigation_terrain_tool import NAVIGATION_TERRAIN_TOOL_ID
from scout_workspace_search_tools import MAJOR_POINT_TOOL_ID, ROUTE_STRUCTURE_TOOL_ID


@pytest.mark.parametrize(
    "question",
    [
        "哪兩個 CP 之間距離最長？約幾公尺？",
        "這個 workspace 的主路線叫什麼？全長多少公里？",
        "最高點減最低點是多少？這能當成全程累積爬升嗎？",
        "屯原經雲海到天池山莊，兩段歷史中位時間相加約多久？",
        "主 GPX 的軌跡點總數是多少？",
        "請比較主路線的累積上升和累積下降。",
        "這條路線總距離和海拔範圍分別是多少？",
        "Give the primary route distance and total ascent.",
    ],
)
def test_route_metrics_reach_structured_route_tool(question):
    plan = plan_scout_ai_tools(
        ScoutAssistantQuery(surface="pretrip", question=question),
        project_root=Path(__file__).parent
        / "fixtures/pretrip/projects/chilai_nanhua_day1",
    )
    assert ROUTE_STRUCTURE_TOOL_ID in {item.tool_id for item in plan.selected_tools}


@pytest.mark.parametrize(
    "question",
    [
        "今天會下多少毫米雨？",
        "沿途有哪些歷史與文化故事？",
        "手錶電量還剩多少？",
    ],
)
def test_non_route_metric_question_does_not_load_route_structure(question):
    plan = plan_scout_ai_tools(
        ScoutAssistantQuery(surface="pretrip", question=question)
    )
    assert ROUTE_STRUCTURE_TOOL_ID not in {item.tool_id for item in plan.selected_tools}


def test_static_gpx_point_inventory_does_not_load_live_navigation_tools():
    plan = plan_scout_ai_tools(
        ScoutAssistantQuery(
            surface="pretrip",
            question="主 GPX 有多少個軌跡點？這個數字和 CP 數量有什麼差別？",
        )
    )
    tool_ids = {item.tool_id for item in plan.selected_tools}

    assert ROUTE_STRUCTURE_TOOL_ID in tool_ids
    assert NAVIGATION_TERRAIN_TOOL_ID not in tool_ids
    assert INS_DR_TRACE_TOOL_ID not in tool_ids


def test_named_segment_distribution_uses_route_timing_not_major_points():
    plan = plan_scout_ai_tools(
        ScoutAssistantQuery(
            surface="pretrip",
            question=(
                "雲海保線所到天池山莊的時間變異大嗎？"
                "請給樣本數及 min、P50、P75、max，不要和上一段混淆。"
            ),
        )
    )
    tool_ids = {item.tool_id for item in plan.selected_tools}

    assert ROUTE_STRUCTURE_TOOL_ID in tool_ids
    assert MAJOR_POINT_TOOL_ID not in tool_ids
