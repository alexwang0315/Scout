from __future__ import annotations

from pathlib import Path

import pytest

from assistant_models import AssistantSurface, ScoutAssistantQuery
from scout_ai_evidence_collection import collect_scout_ai_evidence
from scout_ai_tool_planner import (
    CONTEXTUAL_PERMISSION_TOOL_ID as PERMISSION,
    CWA_ENVIRONMENT_TOOL_ID as CWA,
    GEE_ENVIRONMENT_TOOL_ID as GEE,
    LIVE_NAVIGATION_STATE_TOOL_ID as LIVE,
    PACE_GUARDIAN_TOOL_ID as PACE,
    ROUTE_ARCHITECTURE_TOOL_ID as ARCHITECTURE,
    WEATHER_WINDOW_TOOL_ID as WEATHER,
    plan_scout_ai_tools,
)
from scout_equipment_resource_tool import EQUIPMENT_RESOURCE_TOOL_ID as EQUIPMENT
from scout_team_status_tool import TEAM_STATUS_TOOL_ID as TEAM
from scout_risk_score_tool import RISK_SCORE_TOOL_ID as RISK
from scout_terrain_score_tool import TERRAIN_SCORE_TOOL_ID as TERRAIN
from scout_workspace_search_tools import WORKSPACE_CATALOG_TOOL_ID as CATALOG

PROJECT_ROOT = (
    Path(__file__).resolve().parents[1]
    / "tests/fixtures/pretrip/projects/chilai_nanhua_day1"
)
MICRODECISION = {PERMISSION, LIVE, ARCHITECTURE, WEATHER, PACE, RISK}
ENVIRONMENT_MICRODECISION = MICRODECISION | {CWA, GEE}


def _plan(question: str):
    return plan_scout_ai_tools(
        ScoutAssistantQuery(
            question=question, surface=AssistantSurface.PRETRIP,
            context_ref="chilai_nanhua_day1", project_id="chilai_nanhua_day1",
        ),
        project_root=PROJECT_ROOT,
    )


def _assert_exact_tools(plan, expected: set[str]) -> None:
    ids = [item.tool_id for item in plan.selected_tools]
    assert set(ids) == expected
    assert len(ids) == len(expected)
    assert all(item.status == "ready_to_execute" for item in plan.selected_tools)
    assert plan.max_tool_calls_per_attempt >= 10
    assert plan.max_model_requests_per_attempt >= 10
    assert plan.boundary.runtime_safety_truth is False


@pytest.mark.parametrize(
    ("question", "existing_additional_tools"),
    [
        ("前方是落石區，這段要不要快速通過？", {TERRAIN}),
        ("前方有落石區，這段要不要快速通過？", {TERRAIN}),
        ("前方路段有崩塌，這段要不要快速通過？", set()),
        ("前方路段有崩壁，這段要不要快速通過？", {TERRAIN}),
        ("前方路段有碎石，這段要不要快速通過？", {TERRAIN}),
        ("前方路段有土石堆積，這段要不要快速通過？", set()),
        ("前方路段很泥濘，這段要不要快速通過？", set()),
        ("前方路段很濕滑，這段要不要快速通過？", set()),
        ("前方路段水文狀況不明，這段要不要快速通過？", set()),
        ("前方路段有地形風險，這段要不要快速通過？", {TERRAIN}),
        ("前方路段有風險重疊，這段要不要快速通過？", set()),
        ("前方危險路段重疊，這段要不要快速通過？", set()),
        ("前方路段有 compound 複合災害，這段要不要快速通過？", set()),
        ("前方路段 SMAP 數據偏高，這段要不要快速通過？", set()),
        ("前方路段 GPM 數據偏高，這段要不要快速通過？", set()),
        ("前方是落石區，這段要不要快速通過？後隊在哪？", {TERRAIN, TEAM}),
        (
            "前方是落石區，這段要不要快速通過？手機電量和頭燈水量夠嗎？",
            {TERRAIN, EQUIPMENT},
        ),
        (
            "前方路段 SMAP 數據偏高，這段要不要快速通過？後隊在哪？",
            {TEAM},
        ),
    ],
)
def test_environmental_microdecisions_retain_existing_tools_and_add_support(
    question: str, existing_additional_tools: set[str]
) -> None:
    # Preserve the existing Terrain choice; its separate exact-count review
    # remains unresolved and is not redefined by these support-layer checks.
    _assert_exact_tools(
        _plan(question), ENVIRONMENT_MICRODECISION | existing_additional_tools
    )


@pytest.mark.parametrize(
    "question",
    [
        "土石方工程材料表的規格欄位有哪些？",
        "碎石工程材料有哪些來源檔？",
        "泥濘照片檔案的輸出有哪些？",
        "兩個集合的重疊面積怎麼計算？",
        "化學 compound 的分子式有哪些？",
        "workspace 的 SMAP GPM artifacts 有哪些 metadata？",
        "workspace 中崩塌與濕滑圖層的 artifacts 有哪些？",
        "SMAP 土壤含水資料有哪些欄位？",
    ],
)
def test_background_words_in_data_or_non_field_queries_do_not_add_weather(
    question: str,
) -> None:
    ids = {item.tool_id for item in _plan(question).selected_tools}
    assert ids.isdisjoint({WEATHER, CWA, PERMISSION})


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("SMAP 土壤含水資料有哪些欄位？", {GEE}),
        ("workspace 的 SMAP GPM artifacts 有哪些 metadata？", {CATALOG, GEE}),
    ],
)
def test_explicit_satellite_inventory_keeps_its_independent_tool_set(
    question: str, expected: set[str]
) -> None:
    _assert_exact_tools(_plan(question), expected)


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("前方是落石區，這段要不要快速通過？", ENVIRONMENT_MICRODECISION | {TERRAIN}),
        ("前方路段 SMAP 數據偏高，這段要不要快速通過？", ENVIRONMENT_MICRODECISION),
    ],
)
def test_environmental_microdecision_executes_every_selected_evidence_tool(
    question: str, expected: set[str]
) -> None:
    result = collect_scout_ai_evidence(
        question, project_root=PROJECT_ROOT, project_id="chilai_nanhua_day1", limit=3,
    )
    assert result.selected_tool_count == len(expected)
    assert result.executed_tool_count == len(expected)
    assert result.completed_tool_count == len(expected)
    assert result.missing_input_count == 0
    assert {record.tool_id for record in result.evidence_records} == expected
    assert all(record.collection_status == "completed" for record in result.evidence_records)
    assert all(record.result is not None for record in result.evidence_records)
    assert all(record.boundary.runtime_safety_truth is False for record in result.evidence_records)
