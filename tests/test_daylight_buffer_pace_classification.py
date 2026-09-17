from __future__ import annotations

from pathlib import Path

import pytest

from assistant_models import AssistantSurface, ScoutAssistantQuery
from scout_ai_evidence_collection import collect_scout_ai_evidence
from scout_ai_tool_planner import (
    CWA_ENVIRONMENT_TOOL_ID as CWA,
    ENERGY_VITALS_TOOL_ID as ENERGY,
    WEATHER_WINDOW_TOOL_ID as WEATHER,
    PACE_GUARDIAN_TOOL_ID as PACE,
    CONTEXTUAL_PERMISSION_TOOL_ID as PERMISSION,
    LIVE_NAVIGATION_STATE_TOOL_ID as LIVE,
    ROUTE_ARCHITECTURE_TOOL_ID as ARCHITECTURE,
    plan_scout_ai_tools,
)
from scout_risk_score_tool import RISK_SCORE_TOOL_ID as RISK

PROJECT_ROOT = (
    Path(__file__).resolve().parents[1]
    / "tests/fixtures/pretrip/projects/chilai_nanhua_day1"
)
MICRODECISION = {PERMISSION, LIVE, ARCHITECTURE, WEATHER, PACE, RISK}


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
    "question",
    [
        "日照 buffer 是否下降？",
        "日照buffer是否下降？",
        "daylight buffer 是否下降？",
        "日照餘裕是否下降？",
    ],
)
def test_pure_daylight_buffer_selects_exact_weather_and_cwa(question: str) -> None:
    _assert_exact_tools(_plan(question), {WEATHER, CWA})


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("我今天的配速有足夠 buffer 嗎？", {ENERGY, PACE}),
        (
            "我今天的配速有足夠 buffer 嗎？日照 buffer 是否下降？",
            {ENERGY, PACE, WEATHER, CWA},
        ),
        ("依目前腳程，日照 buffer 是否足夠？", {PACE, WEATHER, CWA}),
        ("目前比預估慢 20 分鐘，日照 buffer 是否下降？", {PACE, WEATHER, CWA}),
        ("隊伍最慢者是否需要加快？日照 buffer 是否下降？", {PACE, WEATHER, CWA}),
        ("現在日照 buffer 很低，還能繼續攻頂嗎？", MICRODECISION | {CWA}),
        (
            "現在 13:36，安全 buffer 還有 21 分鐘，如果多停 10 分鐘，代價是什麼？",
            MICRODECISION,
        ),
        ("回程 buffer 是否足夠？", {PACE}),
        ("這個選擇會消耗什麼 buffer？", MICRODECISION),
    ],
)
def test_explicit_pace_and_action_intents_survive_daylight_disambiguation(
    question: str, expected: set[str]
) -> None:
    _assert_exact_tools(_plan(question), expected)


def test_clocked_daylight_keeps_explicit_time_without_implying_pace() -> None:
    plan = _plan("現在 15:10 日照 buffer 是否下降？")
    ids = [item.tool_id for item in plan.selected_tools]
    assert PACE not in ids
    weather = next(item for item in plan.selected_tools if item.tool_id == WEATHER)
    assert weather.request is not None
    assert weather.request["arguments"] == {"current_time": "15:10"}
    assert plan.boundary.runtime_safety_truth is False


def test_pure_daylight_executes_exactly_the_requested_environment_sources() -> None:
    result = collect_scout_ai_evidence(
        "日照 buffer 是否下降？", project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1", limit=3,
    )
    assert result.selected_tool_count == 2
    assert result.executed_tool_count == 2
    assert result.completed_tool_count == 2
    assert result.missing_input_count == 0
    assert {record.tool_id for record in result.evidence_records} == {WEATHER, CWA}
    assert all(record.collection_status == "completed" for record in result.evidence_records)
    assert all(record.result is not None for record in result.evidence_records)
    assert all(record.boundary.runtime_safety_truth is False for record in result.evidence_records)
