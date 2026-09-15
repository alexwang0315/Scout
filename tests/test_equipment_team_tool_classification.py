from __future__ import annotations

from pathlib import Path

import pytest

from assistant_models import AssistantSurface, ScoutAssistantQuery
from scout_ai_evidence_collection import collect_scout_ai_evidence
from scout_ai_tool_planner import plan_scout_ai_tools
from scout_energy_vitals_tool import ENERGY_VITALS_TOOL_ID as ENERGY
from scout_equipment_resource_tool import EQUIPMENT_RESOURCE_TOOL_ID as EQUIPMENT
from scout_team_status_tool import TEAM_STATUS_TOOL_ID as TEAM
from scout_workspace_search_tools import (
    MAJOR_POINT_TOOL_ID as MAJOR_POINT,
    WORKSPACE_CATALOG_TOOL_ID as CATALOG,
)

PROJECT_ROOT = (
    Path(__file__).resolve().parents[1]
    / "tests/fixtures/pretrip/projects/chilai_nanhua_day1"
)


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("手機電量和頭燈水量夠嗎？", {EQUIPMENT}),
        ("背包中剩餘的水量夠嗎？", {EQUIPMENT}),
        ("今天喝的水量是否足夠？", {ENERGY, EQUIPMENT}),
        ("今天飲水量是不是不足？", {ENERGY, EQUIPMENT}),
        ("流汗很多，水量夠嗎？", {ENERGY, EQUIPMENT}),
        ("補水頻率需要調整嗎？", {MAJOR_POINT, ENERGY, EQUIPMENT}),
        (
            "手機電量和頭燈水量夠嗎？我疲勞需要補水。",
            {MAJOR_POINT, ENERGY, EQUIPMENT},
        ),
        ("手機電量和頭燈水量夠嗎？心率上升。", {ENERGY, EQUIPMENT}),
        ("後隊在哪？最後一次有效位置多久前？留守回報準備好了嗎？", {TEAM}),
        ("留守回報還缺少哪些準備？", {TEAM}),
        ("留守回報材料已完成了嗎？", {TEAM}),
        ("workspace 有哪些資料？後隊留守回報準備好了嗎？", {CATALOG, TEAM}),
        ("列出 outputs artifacts，並確認後隊留守回報準備好了嗎？", {CATALOG, TEAM}),
        ("後隊在哪？workspace metadata 準備好了嗎？", {CATALOG, TEAM}),
        ("workspace 準備好了嗎？", {CATALOG}),
        ("有哪些準備資料仍缺少？", {CATALOG}),
        (
            "後隊在哪？目前需要補水並確認留守回報。",
            {MAJOR_POINT, ENERGY, EQUIPMENT, TEAM},
        ),
    ],
)
def test_classification_retains_exact_requested_evidence_domains(
    question: str, expected: set[str]
) -> None:
    plan = plan_scout_ai_tools(
        ScoutAssistantQuery(
            question=question,
            surface=AssistantSurface.PRETRIP,
            context_ref="chilai_nanhua_day1",
            project_id="chilai_nanhua_day1",
        ),
        project_root=PROJECT_ROOT,
    )

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
        "workspace 有哪些資料？後隊留守回報準備好了嗎？",
        "後隊在哪？workspace metadata 準備好了嗎？",
    ],
)
def test_mixed_workspace_and_team_question_executes_both_evidence_sources(
    question: str,
) -> None:
    result = collect_scout_ai_evidence(
        question,
        project_root=PROJECT_ROOT,
        project_id="chilai_nanhua_day1",
        limit=3,
    )

    assert result.selected_tool_count == 2
    assert result.executed_tool_count == 2
    assert result.completed_tool_count == 2
    assert result.missing_input_count == 0
    assert {record.tool_id for record in result.evidence_records} == {CATALOG, TEAM}
    assert all(record.collection_status == "completed" for record in result.evidence_records)
    assert all(record.result is not None for record in result.evidence_records)
    assert all(record.boundary.runtime_safety_truth is False for record in result.evidence_records)
