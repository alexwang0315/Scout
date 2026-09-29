import json
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from scout.nextgen.jev_blind_routing import (
    BlindQuestion,
    build_blind_jev_route_request,
    load_blind_questions,
)
from tools import run_scout_ai_jev_blind_authoritative_eval as blind_eval
from tools.run_scout_ai_jev_blind_authoritative_eval import (
    ROUTE_STRUCTURE_TOOL,
    _compact_evidence_cards,
    _verify_answer,
    _workspace_tool_ids,
)


def test_blind_questions_have_no_route_or_answer_key(tmp_path: Path):
    path = tmp_path / "questions.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "scout.ai.jev_blind_questions.v1",
                "questions": [
                    {"question_id": "Q-001", "question": "2 加 2 是多少？"}
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    question_set = load_blind_questions(path)
    assert question_set.questions[0].question_id == "Q-001"
    request = build_blind_jev_route_request(
        question_set.questions[0],
        model_id="typesafe/jev-1.13",
        workspace_context={
            "workspace_id": "test-workspace",
            "projection": {"projection_hash": "a" * 64},
        },
    )
    assert "expected_route" not in request.state
    assert "standard_answer" not in request.state
    assert request.state["workspace"]["workspace_id"] == "test-workspace"


def test_blind_route_allows_local_after_completed_workspace_read():
    question = BlindQuestion(question_id="Q-001", question="本旅程長度多少公里？")
    request = build_blind_jev_route_request(
        question,
        model_id="typesafe/jev-1.13",
        workspace_context={"workspace_evidence_status": "completed"},
    )
    route = request.questions["model_route"]
    assert "completed read-only workspace evidence" in route.criteria["local"]
    assert "workspace_evidence_status" in request.state["workspace"]
    assert "distance_km" not in json.dumps(request.model_dump(mode="json"))


@pytest.mark.parametrize("forbidden", ["expected_route", "standard_answer", "answer"])
def test_blind_questions_reject_answer_key_fields(forbidden: str):
    with pytest.raises(ValidationError):
        BlindQuestion.model_validate(
            {
                "question_id": "Q-001",
                "question": "題目",
                forbidden: "local",
            }
        )


def test_workspace_fact_verifier_requires_exact_route_json_value():
    question = "本旅程長度多少距離，以公里為單位回答我"
    card = {
        "tool_id": ROUTE_STRUCTURE_TOOL,
        "status": "completed",
        "payload": {
            "tool_id": ROUTE_STRUCTURE_TOOL,
            "status": "completed",
            "route_summary": {"distance_m": 89827.14, "distance_km": 89.827},
            "summaries": {"source_paths": {"route_summary": "normalized/routes/route_summary.json"}},
        },
    }
    assert _workspace_tool_ids(question) == [ROUTE_STRUCTURE_TOOL]
    assert _verify_answer(question, "89.827 公里", [card])["status"] == "pass"
    assert _verify_answer(question, "大約 90 公里", [card])["status"] == "fail"
    compact = _compact_evidence_cards(question, [card])
    assert (
        compact[0]["payload"]["summaries"]["source_paths"]["route_summary"]
        == "normalized/routes/route_summary.json"
    )


def test_workspace_list_verifier_does_not_accept_truncated_evidence():
    question = "哪些危險地形"
    card = {
        "tool_id": "pydantic_ai.tool.search_scout_risk_scores.v0",
        "status": "completed",
        "payload": {
            "segment_risk_summary": {
                "matched_segment_count": 215,
                "returned_segment_count": 12,
                "truncated": True,
                "segments": [{"label": "Segment 020"}],
            },
            "results": [{"segment_label": "Segment 020"}],
        },
    }
    assert _verify_answer(question, "Segment 020", [card])["status"] == "not_verified"


def test_blind_run_collects_evidence_before_jev_without_leaking_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    questions = tmp_path / "questions.json"
    questions.write_text(
        json.dumps(
            {
                "schema_version": "scout.ai.jev_blind_questions.v1",
                "questions": [{"question_id": "Q-001", "question": "本旅程長度多少公里？"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    events: list[str] = []
    captured_request = None
    card = {
        "tool_id": ROUTE_STRUCTURE_TOOL,
        "status": "completed",
        "payload": {
            "route_summary": {"distance_km": 89.827},
            "summaries": {"source_paths": {"route_summary": "normalized/routes/route_summary.json"}},
        },
    }

    def collect(*_args, **_kwargs):
        events.append("evidence")
        return [card], [{"tool_id": ROUTE_STRUCTURE_TOOL, "status": "completed"}]

    class FakeJevClient:
        def __init__(self, **_kwargs):
            pass

        def decide(self, request):
            nonlocal captured_request
            events.append("jev")
            captured_request = request
            return SimpleNamespace(id="decision-1", model_dump=lambda **_: {})

    def call_model(*_args, **_kwargs):
        events.append("model")
        return {"answer": "89.827", "model": "qwen3:1.7b", "runtime_metadata": {}}

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-only-key")
    monkeypatch.setattr(blind_eval, "build_anonymized_workspace_projection", lambda _: SimpleNamespace(projection_hash="a" * 64, model_dump=lambda **_: {}))
    monkeypatch.setattr(blind_eval, "hailo_preflight", lambda: {"model_present": True})
    monkeypatch.setattr(blind_eval, "_collect_workspace_evidence", collect)
    monkeypatch.setattr(blind_eval, "OpenRouterJevClient", FakeJevClient)
    monkeypatch.setattr(blind_eval, "parse_jev_route", lambda _: blind_eval.ModelRoute.LOCAL)
    monkeypatch.setattr(blind_eval, "OpenRouterModelCaller", lambda **_: object())
    monkeypatch.setattr(blind_eval, "_call_selected_model", call_model)
    output = tmp_path / "output"
    status = blind_eval.run(
        Namespace(
            questions=questions,
            workspace=workspace,
            workspace_id="workspace",
            jev_model="typesafe/jev-1.13",
            jev_timeout_seconds=10,
            model_timeout_seconds=10,
            output=output,
        )
    )
    assert status == 0
    assert events == ["evidence", "jev", "model"]
    assert captured_request.state["workspace"]["workspace_evidence_status"] == "completed"
    assert "89.827" not in json.dumps(captured_request.model_dump(mode="json"))
