from __future__ import annotations

from pathlib import Path

import pytest

from assistant_models import AssistantSurface, ScoutAssistantQuery
from scout_ai_tool_planner import (
    MEDIA_LITERACY_TOOL_ID as MEDIA,
    ROUTE_CONTEXT_TOOL_ID as ROUTE_CONTEXT,
    plan_scout_ai_tools,
)

PROJECT_ROOT = (
    Path(__file__).resolve().parents[1]
    / "tests/fixtures/pretrip/projects/chilai_nanhua_day1"
)


def _tool_ids(question: str) -> set[str]:
    plan = plan_scout_ai_tools(
        ScoutAssistantQuery(
            question=question, surface=AssistantSurface.PRETRIP,
            context_ref="chilai_nanhua_day1", project_id="chilai_nanhua_day1",
        ),
        project_root=PROJECT_ROOT,
    )
    assert plan.boundary.runtime_safety_truth is False
    return {item.tool_id for item in plan.selected_tools}


@pytest.mark.parametrize(
    "question",
    [
        "IG",
        "ig",
        "Instagram",
        "IG照片可信嗎？",
        "在IG上看到的行程可信嗎？",
        "IG photo",
        "an IG photo",
        "IG 的地名故事？",
        "IG photo 地名故事？",
    ],
)
def test_ig_abbreviation_and_instagram_keep_media_evidence(question: str) -> None:
    assert MEDIA in _tool_ids(question)


@pytest.mark.parametrize(
    "question",
    [
        "daylight buffer 是否下降？",
        "navigation",
        "right",
        "height",
        "signal",
        "night",
        "big",
        "digital",
        "navigation 地名故事？",
    ],
)
def test_embedded_ig_letters_do_not_imply_social_media(question: str) -> None:
    assert MEDIA not in _tool_ids(question)


@pytest.mark.parametrize("question", ["IG 的地名故事？", "IG photo 地名故事？"])
def test_actual_media_intent_still_excludes_route_context(question: str) -> None:
    ids = _tool_ids(question)
    assert MEDIA in ids
    assert ROUTE_CONTEXT not in ids


def test_navigation_word_does_not_suppress_actual_route_context() -> None:
    ids = _tool_ids("navigation 地名故事？")
    assert MEDIA not in ids
    assert ROUTE_CONTEXT in ids
