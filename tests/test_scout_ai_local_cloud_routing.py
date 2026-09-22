from __future__ import annotations

import json
from pathlib import Path

from scout.nextgen.jev_decisions import JevChoiceAnswer, JevDecisionResponse, JevUsage
from scout.nextgen.jev_model_routing import (
    ModelRoute,
    build_jev_route_request,
    deterministic_route,
    evaluate_jev_route,
    load_routing_corpus,
    validate_routing_corpus,
)


ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "docs/specs/scout-ai-local-cloud-routing-100-question-corpus.json"


def test_routing_corpus_has_70_local_and_30_cloud_cases():
    corpus = load_routing_corpus(CORPUS)
    assert len(corpus.questions) == 100
    assert sum(item.expected_route is ModelRoute.LOCAL for item in corpus.questions) == 70
    assert sum(item.expected_route is ModelRoute.CLOUD for item in corpus.questions) == 30
    assert validate_routing_corpus(corpus) == []


def test_local_case_builds_label_blinded_jev_request():
    question = load_routing_corpus(CORPUS).questions[0]
    request = build_jev_route_request(question, model_id="test-jev")
    state = request.state
    assert isinstance(state, dict)
    assert "expected_route" not in state
    assert "standard_answer" not in state
    assert request.questions["model_route"].criteria["local"]


def test_jev_cannot_downgrade_cloud_required_case():
    question = load_routing_corpus(CORPUS).questions[-1]
    assert deterministic_route(question) is ModelRoute.CLOUD
    response = JevDecisionResponse(
        model="test-jev",
        answers={
            "model_route": JevChoiceAnswer(
                type="choice",
                choice="local",
                probabilities={"local": 1.0},
                confidence=1.0,
            )
        },
        usage=JevUsage(input_tokens=1, output_tokens=1),
    )
    decision = evaluate_jev_route(question, response)
    assert decision.final_route is ModelRoute.CLOUD
    assert decision.downgrade_blocked is True


def test_jev_can_advisory_escalate_local_case_without_becoming_authority():
    question = load_routing_corpus(CORPUS).questions[0]
    response = JevDecisionResponse(
        model="test-jev",
        answers={
            "model_route": JevChoiceAnswer(
                type="choice",
                choice="cloud",
                probabilities={"cloud": 1.0},
                confidence=1.0,
            )
        },
        usage=JevUsage(input_tokens=1, output_tokens=1),
    )
    decision = evaluate_jev_route(question, response)
    assert decision.final_route is ModelRoute.CLOUD
    assert decision.reason == "jev_advisory_escalation_for_local_eligible_question"
    assert decision.candidate_only is True
    assert decision.runtime_safety_truth is False


def test_corpus_is_json_and_all_cases_are_candidate_only():
    document = json.loads(CORPUS.read_text(encoding="utf-8"))
    assert document["candidate_only"] is True
    assert document["runtime_safety_truth"] is False
    assert all(item["candidate_only"] is True for item in document["questions"])
    assert all(item["runtime_safety_truth"] is False for item in document["questions"])

