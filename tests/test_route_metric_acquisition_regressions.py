from __future__ import annotations

import json
from pathlib import Path

import pytest

from assistant_models import AssistantSurface, ScoutAssistantQuery
from scout.schemas.agent_runtime import QuestionClass
from scout.schemas.workspace_query import WorkspaceQueryOperation
from scout_ai_tool_executor import execute_scout_ai_tool
from scout_ai_tool_planner import (
    ENERGY_VITALS_TOOL_ID,
    LIVE_NAVIGATION_STATE_TOOL_ID,
    ROUTE_CONTEXT_TOOL_ID,
    plan_scout_ai_tools,
)
from scout_workspace_search_tools import (
    MAJOR_POINT_TOOL_ID,
    ROUTE_STRUCTURE_TOOL_ID,
    search_project_major_points,
    search_project_route_structure,
)


PROJECT_ROOT = (
    Path(__file__).resolve().parents[1]
    / "tests/fixtures/pretrip/projects/chilai_nanhua_day1"
)


def _plan(question: str, root: Path = PROJECT_ROOT):
    return plan_scout_ai_tools(
        ScoutAssistantQuery(
            surface=AssistantSurface.PRETRIP,
            question=question,
            project_id=root.name,
            context_ref=root.name,
        ),
        project_root=root,
    )


@pytest.mark.parametrize(
    "question",
    [
        "請列出主路線最低、最高海拔及兩者高差，單位公尺。",
        "主路線的海拔範圍是多少？",
        "主路線的最低海拔是多少公尺？",
        "主路線最高海拔多少？",
        "What are the minimum and maximum elevations of the primary route?",
        "What is the route altitude range?",
    ],
)
def test_route_elevation_bounds_are_summary_facts(question: str) -> None:
    plan = _plan(question)
    items = {item.tool_id: item for item in plan.selected_tools}

    assert ROUTE_STRUCTURE_TOOL_ID in items
    assert ENERGY_VITALS_TOOL_ID not in items
    assert LIVE_NAVIGATION_STATE_TOOL_ID not in items
    assert plan.question_class == QuestionClass.STATIC_WORKSPACE_FACT
    assert plan.expected_operations == [WorkspaceQueryOperation.INSPECT]
    assert plan.requires_live_state is False
    assert items[ROUTE_STRUCTURE_TOOL_ID].request["query"] == question


def test_route_elevation_plan_executes_existing_fixture_without_a_model() -> None:
    question = "主路線最低、最高海拔及高差各是多少？"
    plan = _plan(question)
    item = next(
        item for item in plan.selected_tools if item.tool_id == ROUTE_STRUCTURE_TOOL_ID
    )
    result = execute_scout_ai_tool(item.request)
    route = json.loads(
        (PROJECT_ROOT / "normalized/routes/route_summary.json").read_text()
    )

    assert result.status == "completed"
    assert (
        result.payload["route_summary"]["elevation_min_m"] == route["elevation_min_m"]
    )
    assert (
        result.payload["route_summary"]["elevation_max_m"] == route["elevation_max_m"]
    )
    assert result.payload["route_summary"]["elevation_range_m"] == pytest.approx(
        route["elevation_max_m"] - route["elevation_min_m"]
    )
    assert result.payload["query"] == question


@pytest.mark.parametrize(
    "question", ["請列出目前所有 Boss 的名稱。", "List the current Boss points."]
)
def test_boss_inventory_is_not_live_state(question: str) -> None:
    plan = _plan(question)
    ids = {item.tool_id for item in plan.selected_tools}

    assert MAJOR_POINT_TOOL_ID in ids
    assert LIVE_NAVIGATION_STATE_TOOL_ID not in ids
    assert plan.question_class == QuestionClass.STATIC_WORKSPACE_FACT
    assert plan.expected_operations
    assert plan.requires_live_state is False


def test_boss_without_point_suffix_uses_boss_artifact(tmp_path: Path) -> None:
    (tmp_path / "project.json").write_text(json.dumps({"boss_points_ref": "boss.json"}))
    points = [
        {"boss_point_id": "boss.saddle", "label": "North saddle", "rank": 2},
        {"boss_point_id": "boss.crossing", "label": "Stream crossing", "rank": 1},
    ]
    (tmp_path / "boss.json").write_text(
        json.dumps({"boss_point_count": len(points), "boss_points": points})
    )
    result = search_project_major_points(tmp_path, query="列出 Boss 名稱與數量。")

    assert "2 個 boss point" in result["field_answer"]
    assert "North saddle" in result["field_answer"]
    assert "Stream crossing" in result["field_answer"]
    assert result["field_answer_source_ref"] == "boss.json"


def test_terrain_extreme_ranking_keeps_aggregate_classification() -> None:
    plan = _plan("terrain route samples 中坡度最高的位置與數值是多少？")
    assert plan.question_class == QuestionClass.AGGREGATE_WORKSPACE_FACT
    assert plan.expected_operations == [WorkspaceQueryOperation.ARGMAX]


def test_elevation_with_symptoms_keeps_health_evidence() -> None:
    plan = _plan("主路線最高海拔時頭痛，該不該繼續走？")
    assert ENERGY_VITALS_TOOL_ID in {item.tool_id for item in plan.selected_tools}


@pytest.mark.parametrize(
    "question",
    [
        "Boss 的 route_pressure_peak 和 extreme_terrain_hazard 各有多少個？",
        "MCP 的 nearest CP 距離、支援半徑、座標可信度是多少？",
        "地圖里程和 GPX 累積距離的比較需要哪些證據？",
    ],
)
def test_catalog_count_and_comparison_are_not_safety_decisions(question: str) -> None:
    plan = _plan(question)
    assert plan.question_class != QuestionClass.SAFETY_DECISION
    assert plan.requires_live_state is False


@pytest.mark.parametrize(
    "question",
    [
        "把歷史段落的 P50 加總後是多少小時？",
        "歷史路段最快與最慢樣本差多少分鐘？",
        "Compare the recorded segment timing p25 and p75 statistics.",
        "What is the sum of reference segment median durations?",
    ],
)
def test_historical_timing_acquires_measurements_not_cultural_story(
    question: str,
) -> None:
    plan = _plan(question)
    ids = {item.tool_id for item in plan.selected_tools}
    assert ROUTE_STRUCTURE_TOOL_ID in ids
    assert ROUTE_CONTEXT_TOOL_ID not in ids


@pytest.mark.parametrize(
    "question",
    [
        "沿途警備道的歷史與文化是什麼？",
        "製作一份包含歷史時間統計與文化景點的路線簡報。",
    ],
)
def test_cultural_and_mixed_briefing_preserve_route_context(question: str) -> None:
    assert ROUTE_CONTEXT_TOOL_ID in {
        item.tool_id for item in _plan(question).selected_tools
    }


@pytest.mark.parametrize("low,high,expected", [(-30, 150, 180), (0, 0, 0), (None, 20, None), (30, 20, None)])
def test_elevation_range_preserves_unknown_and_invalid_bounds(low, high, expected):
    from scout_workspace_search_tools import _compact_route_summary

    result = _compact_route_summary({"elevation_min_m": low, "elevation_max_m": high})
    assert result["elevation_range_m"] == expected
    assert result["elevation_min_m"] == low
    assert result["elevation_max_m"] == high


def test_route_identity_field_answer_binds_distance_to_route_summary() -> None:
    result = search_project_route_structure(
        PROJECT_ROOT,
        query="這個專案的主路線名稱是什麼？全長約幾公里？請附資料來源。",
    )
    route = json.loads(
        (PROJECT_ROOT / "normalized/routes/route_summary.json").read_text()
    )

    assert result["field_answer_priority"] == 100
    assert route["route_name"] in result["field_answer"]
    assert str(round(route["distance_m"] / 1000, 3)) in result["field_answer"]
    assert "normalized/routes/route_summary.json" in result["field_answer"]


def test_route_chain_field_answer_keeps_cp_segment_entities_separate() -> None:
    result = search_project_route_structure(
        PROJECT_ROOT,
        query="主路線目前有多少個 CP、多少個相鄰路段？這兩個數量符合一條連續 CP 鏈嗎？",
    )
    summaries = result["summaries"]

    assert result["field_answer_priority"] == 100
    assert f"{summaries['checkpoint_count']} 個 CP" in result["field_answer"]
    assert f"{summaries['segment_count']} 個相鄰路段" in result["field_answer"]
    assert "不是只靠數量推論" in result["field_answer"]
    assert "實體 GPX 幾何" in result["field_answer"]


def test_gpx_point_field_answer_does_not_relabel_points_as_checkpoints() -> None:
    result = search_project_route_structure(
        PROJECT_ROOT,
        query="主 GPX 有多少個軌跡點？這個數字和 CP 數量有什麼差別？",
    )
    route = json.loads(
        (PROJECT_ROOT / "normalized/routes/route_summary.json").read_text()
    )

    assert f"{route['point_count']} 個軌跡點" in result["field_answer"]
    assert f"{result['summaries']['checkpoint_count']} 個 CP" in result["field_answer"]
    assert "兩者不是同一類資料" in result["field_answer"]


def test_elevation_field_answer_derives_range_without_calling_it_ascent() -> None:
    result = search_project_route_structure(
        PROJECT_ROOT,
        query="請列出主路線最低、最高海拔，以及兩者高差，單位公尺。",
    )
    route = result["route_summary"]

    assert f"最低海拔 {route['elevation_min_m']} 公尺" in result["field_answer"]
    assert f"最高海拔 {route['elevation_max_m']} 公尺" in result["field_answer"]
    assert f"高差 {route['elevation_range_m']} 公尺" in result["field_answer"]
    assert "不是累積上升量" in result["field_answer"]


def test_cumulative_gain_loss_field_answer_uses_segment_aggregation() -> None:
    result = search_project_route_structure(
        PROJECT_ROOT,
        query="全程累積上升和下降各多少？請用所有相鄰路段的資料加總，不要用最高點減最低點。",
    )
    aggregate = result["summaries"]["primary_route_elevation_aggregate"]

    assert f"總爬升 {aggregate['total_ascent_m']} m" in result["field_answer"]
    assert f"總下降 {aggregate['total_descent_m']} m" in result["field_answer"]
    assert "segment-level" in result["field_answer"]


def test_checkpoint_label_field_answer_preserves_zero_and_type_counts() -> None:
    result = search_project_route_structure(
        PROJECT_ROOT,
        query="checkpoint 清單有幾組重複標籤？起點、途中 CP、終點各幾個？",
    )
    quality = result["summaries"]

    assert (
        f"重複標籤組數為 {quality['checkpoint_duplicate_label_group_count']}"
        in result["field_answer"]
    )
    assert "start=1" in result["field_answer"]
    assert "route_progress=" in result["field_answer"]
    assert "finish=1" in result["field_answer"]


def test_historical_timing_coverage_field_answer_rejects_unique_hiker_inference() -> None:
    result = search_project_route_structure(
        PROJECT_ROOT,
        query="歷史分段時間資料涵蓋多少段、多少筆時間測量？這等於有同樣多位獨立山友嗎？",
    )
    timing = result["summaries"]["reference_segment_timing"]

    assert f"涵蓋 {timing['segment_count']} 段" in result["field_answer"]
    assert f"{timing['measurement_count']} 筆時間測量" in result["field_answer"]
    assert "不能推論為同樣多位獨立山友" in result["field_answer"]


def test_named_historical_segment_field_answer_keeps_full_distribution() -> None:
    result = search_project_route_structure(
        PROJECT_ROOT,
        query="雲海保線所到天池山莊的時間變異大嗎？請給樣本數及 min、P50、P75、max。",
    )
    expected = result["summaries"]["reference_segment_timing"]["segments"][1]

    assert expected["label"] in result["field_answer"]
    assert f"{expected['sample_count']} 個樣本" in result["field_answer"]
    for name in ("min", "p50", "p75", "max"):
        assert f"{name}={expected['duration_minutes'][name]}" in result["field_answer"]
    assert "max-min 全距=72.1 分鐘" in result["field_answer"]
    assert "未定義變異大或小的判定閾值" in result["field_answer"]
    assert "不能客觀標成變異大或變異小" in result["field_answer"]
    assert "不能直接當成個人即時 ETA" in result["field_answer"]


def test_longest_p50_field_answer_ranks_median_not_maximum_sample() -> None:
    result = search_project_route_structure(
        PROJECT_ROOT,
        query="八段歷史時間中，哪一段 P50 最長？它有多少樣本？",
    )
    rows = result["summaries"]["reference_segment_timing"]["segments"]
    expected = max(rows, key=lambda row: row["duration_minutes"]["p50"])

    assert expected["label"] in result["field_answer"]
    assert f"P50={expected['duration_minutes']['p50']} 分鐘" in result["field_answer"]
    assert f"樣本數={expected['sample_count']}" in result["field_answer"]
    assert "不是依單筆最大值" in result["field_answer"]


def test_timing_quality_field_answer_separates_rejected_and_boundary_counts() -> None:
    result = search_project_route_structure(
        PROJECT_ROOT,
        query="歷史時間整理排除了幾筆距離不符的測量？另有多少筆跨 GPX track 邊界？允許時間跨邊界是否等於證明路線幾何連通？",
    )
    timing = result["summaries"]["reference_segment_timing"]

    assert (
        f"距離不符的測量 {timing['distance_rejected_measurement_count']} 筆"
        in result["field_answer"]
    )
    assert (
        f"track 邊界的時間測量有 {timing['track_boundary_crossed_measurement_count']} 筆"
        in result["field_answer"]
    )
    assert "不等於證明路線幾何連通" in result["field_answer"]
