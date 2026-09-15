from __future__ import annotations

import pytest

from assistant_models import AssistantSourceRef, AssistantSurface, ScoutAssistantQuery
from assistant_skill_router import (
    PRETRIP_CP_COUNT_SKILL_ID,
    PRETRIP_PLACE_TO_CP_SKILL_ID,
    resolve_assistant_query_with_skill,
)


def _query(question: str) -> ScoutAssistantQuery:
    return ScoutAssistantQuery(
        surface=AssistantSurface.PRETRIP,
        question=question,
        project_id="shortcut-fixture",
        context_ref="shortcut-fixture",
    )


@pytest.fixture
def context_source() -> AssistantSourceRef:
    return AssistantSourceRef(
        source_id="assistant_context.pretrip",
        source_path="pretrip_assistant_context",
        evidence_type="assistant_context_summary",
        context_summary={
            "summary": {
                "cp_count": 17,
                "major_critical_point_cp_links": [
                    {
                        "label": "松池",
                        "aliases": ["松池水源"],
                        "nearest_cp_candidate_id": "cp.004",
                        "nearest_cp_label": "CP 004",
                        "nearest_cp_distance_m": 42.5,
                        "support_status": "supported",
                    },
                    {
                        "label": "北鞍",
                        "nearest_cp_candidate_id": "cp.011",
                        "nearest_cp_label": "CP 011",
                        "nearest_cp_distance_m": 18.0,
                    },
                ],
            },
        },
    )


@pytest.mark.parametrize(
    "question",
    [
        "主 GPX 有多少軌跡點？這個數字和 CP 數量有何差別？",
        "How many GPX points versus CPs are recorded?",
        "CP 總數和 GPX 點數相同嗎？",
        "CP 有幾個，同時標出它們的座標？",
        "有多少個 Boss？不要混成 MCP 或 CP 數量。",
        "松池靠哪個 CP 支援，支援半徑多少？",
        "松池靠哪個 CP？請核對 nearest_cp_distance_m 和 support_radius_m。",
        "松池在附近哪個 CP，座標可信度是多少？",
        "松池、北鞍附近各是哪個 CP？",
    ],
)
def test_compound_questions_defer_intact(
    question: str, context_source: AssistantSourceRef
) -> None:
    query = _query(question)
    before = query.model_dump()

    assert resolve_assistant_query_with_skill(query, sources=[context_source]) is None
    assert query.model_dump() == before


@pytest.mark.parametrize(
    ("question", "skill_id", "answer_fragment"),
    [
        ("有多少個 CP？", PRETRIP_CP_COUNT_SKILL_ID, "17 個 CP"),
        ("How many checkpoints?", PRETRIP_CP_COUNT_SKILL_ID, "17 個 CP"),
        ("松池在第幾 CP 附近？", PRETRIP_PLACE_TO_CP_SKILL_ID, "CP 004"),
        ("松池水源靠哪個 CP？", PRETRIP_PLACE_TO_CP_SKILL_ID, "42.500 m"),
    ],
)
def test_single_intent_shortcuts_still_resolve(
    question: str,
    skill_id: str,
    answer_fragment: str,
    context_source: AssistantSourceRef,
) -> None:
    result = resolve_assistant_query_with_skill(_query(question), sources=[context_source])

    assert result is not None
    assert result.sources[0].source_id == skill_id
    assert answer_fragment in result.answer
    assert result.boundary.safety_mutation_allowed is False


def test_unselected_place_does_not_choose_an_arbitrary_link(
    context_source: AssistantSourceRef,
) -> None:
    assert resolve_assistant_query_with_skill(
        _query("這個地點靠哪個 CP？"), sources=[context_source]
    ) is None
