from __future__ import annotations

import pytest

from assistant_models import AssistantSourceRef, ScoutAssistantQuery
from assistant_skill_router import resolve_assistant_query_with_skill


def resolve(question, count=74, fallback=99):
    return resolve_assistant_query_with_skill(
        ScoutAssistantQuery(surface="pretrip", question=question),
        sources=[
            AssistantSourceRef(
                source_id="assistant_context.pretrip",
                context_summary={
                    "summary": {
                        "cp_count": count,
                        "checkpoint_candidate_count": fallback,
                    }
                },
            )
        ],
    )


@pytest.mark.parametrize(
    "question",
    [
        "目前有多少個 Boss Point？不要把 MCP 混進去。",
        "目前有多少個 MCP？",
        "CP 與 MCP 分別有多少個？",
        "checkpoint candidates 共有多少個，第一個與最後一個 CP 是什麼？",
        "CP 和 segments 各有多少個？",
        "哪兩個 CP 間的距離最長，多少公尺？",
        "CP 總數與主路線名稱分別是什麼？",
    ],
)
def test_count_shortcut_does_not_hijack_other_entities_or_multi_part_queries(question):
    assert resolve(question) is None


@pytest.mark.parametrize(
    "question",
    [
        "目前這條路線有多少個 CP？",
        "嗨，現在有幾個CP點？",
        "How many checkpoints are there?",
    ],
)
def test_simple_cp_count_still_uses_exact_count(question):
    assert "74" in resolve(question).answer


def test_zero_checkpoint_count_is_not_replaced_by_another_source():
    assert "0 個 CP" in resolve("共有幾個 CP？", count=0).answer


def test_boolean_checkpoint_count_is_not_a_numeric_fact():
    assert resolve("共有幾個 CP？", count=True) is None
