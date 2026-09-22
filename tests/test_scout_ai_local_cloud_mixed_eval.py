from __future__ import annotations

from pathlib import Path

from scout.nextgen.jev_model_routing import ModelRoute, load_routing_corpus


ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "docs/specs/scout-ai-local-cloud-mixed-20-question-eval.json"


def test_mixed_corpus_contains_the_requested_10_plus_10_selection():
    corpus = load_routing_corpus(CORPUS)
    assert len(corpus.questions) == 20
    assert [item.question_id for item in corpus.questions[:10]] == [
        f"LOCAL-{index:03d}" for index in range(1, 11)
    ]
    assert [item.question_id for item in corpus.questions[10:]] == [
        f"EXP-{index:03d}" for index in range(1, 11)
    ]
    assert all(item.expected_route is ModelRoute.LOCAL for item in corpus.questions[:10])
    assert all(item.expected_route is ModelRoute.CLOUD for item in corpus.questions[10:])
