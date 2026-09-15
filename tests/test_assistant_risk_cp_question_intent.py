"""Risk rank questions near existing CPs must not imply checkpoint creation."""
from pathlib import Path

import pytest

from assistant_pydantic_provider import RISK_SCORE_TOOL_ID, _risk_score_answer_prefix
from scout_agent_builtin_tools import _resolve_assistant_workflow_eval_case


@pytest.mark.parametrize(
    "question",
    [
        "哪些 CP 附近 risk score 最高？",
        "哪個CP附近的risk score最高？",
        "哪些 checkpoint 附近 risk score 最高？",
        "哪些檢查點附近的風險分數最高？",
        "Compare risk scores near CP 2 and CP 4",
    ],
)
def test_existing_cp_risk_fact_question_does_not_request_checkpoint_creation(question):
    assert _risk_score_answer_prefix(question) == "最高候選風險點"


@pytest.mark.parametrize(
    "question",
    [
        "應該在哪裡設checkpoint？",
        "應該在哪裡設 checkpoint？",
        "應該在哪裡設CP？",
        "哪裡需要新增CP？",
        "哪裡需要新增 CP？",
        "哪裡需要新增checkpoint？",
        "哪裡需要新增檢查點？",
        "哪些地方漏設了檢查點？",
        "檢查點設在哪裡比較合適？",
        "Where should I add a checkpoint?",
        "Which risk location needs a new CP?",
    ],
)
def test_explicit_checkpoint_creation_keeps_design_intent(question):
    assert _risk_score_answer_prefix(question) == "優先考慮設 checkpoint 的候選風險點"


@pytest.mark.parametrize(
    ("question", "prefix"),
    [
        ("CP4 附近有哪些雨後風險？", "雨後需優先人工複核的最高候選風險點"),
        ("CP4 附近哪裡不要停留拍照？", "避免停留拍照的候選風險點"),
        ("CP4 附近哪裡低容錯？", "低容錯或不適合放大時間成本的候選風險點"),
    ],
)
def test_cp_reference_does_not_replace_the_question_specific_risk_purpose(question, prefix):
    assert _risk_score_answer_prefix(question) == prefix


def test_builtin_risk_rank_summary_stays_evidence_only_and_uses_factual_cp_intent():
    root = (
        Path(__file__).resolve().parents[1]
        / "tests/fixtures/pretrip/projects/chilai_nanhua_day1"
    )
    response = _resolve_assistant_workflow_eval_case(
        "哪些 CP 附近 risk score 最高？",
        project_id="chilai_nanhua_day1",
        project_root=root,
        limit=3,
    )
    assert "model answer unavailable" in response.answer
    assert "deterministic_tool_fallback_only=true" in response.limitations
    assert f"resolved_by={RISK_SCORE_TOOL_ID}" in response.limitations
    assert "最高候選風險點" in response.evidence_backed_answer
    assert "設 checkpoint" not in response.evidence_backed_answer
    assert "score=" in response.evidence_backed_answer
    assert response.observability.safe_failure is True
    assert response.boundary.phase1_mutation_allowed is False
    assert response.boundary.outbound_send_allowed is False
