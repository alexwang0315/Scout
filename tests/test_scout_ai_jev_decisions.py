"""Typed Jev Decisions API boundary and anonymized workspace context."""

from __future__ import annotations

import hashlib
import io
import json
import urllib.request

import pytest

from scout.nextgen.jev_decisions import (
    OPENROUTER_DECISIONS_ENDPOINT,
    JevChoiceQuestion,
    JevDecisionError,
    JevDecisionRequest,
    OpenRouterJevClient,
    build_anonymized_workspace_projection,
)


def _request() -> JevDecisionRequest:
    return JevDecisionRequest(
        model="typesafe/jev-1.13",
        state={
            "question": "How many checkpoints?",
            "required_tools": ["route_structure"],
        },
        questions={
            "model_route": JevChoiceQuestion(
                instructions="Choose the evidence lane",
                criteria={"local": "No tool needed", "cloud": "Tool evidence needed"},
            )
        },
    )


def _response(choice: str = "cloud") -> bytes:
    return json.dumps(
        {
            "id": "decision-123",
            "model": "typesafe/jev-1.13-20260917",
            "answers": {
                "model_route": {
                    "type": "choice",
                    "choice": choice,
                    "confidence": 0.8,
                    "probabilities": {choice: 0.8, "local": 0.2},
                }
            },
            "usage": {"input_tokens": 20, "output_tokens": 4, "cost": 0.001},
        }
    ).encode()


def _response_without_usage() -> bytes:
    response = json.loads(_response())
    del response["usage"]
    return json.dumps(response).encode()


def _response_with_incomplete_probabilities() -> bytes:
    response = json.loads(_response())
    del response["answers"]["model_route"]["probabilities"]["local"]
    return json.dumps(response).encode()


def test_client_uses_decisions_protocol_and_typed_choice(monkeypatch):
    def fake_urlopen(request: urllib.request.Request, *, timeout: float):
        assert request.full_url == OPENROUTER_DECISIONS_ENDPOINT
        assert timeout == 9
        assert json.loads(request.data) == _request().model_dump(mode="json")
        return io.BytesIO(_response())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    response = OpenRouterJevClient(
        api_key="test-key", model_id="typesafe/jev-1.13", timeout_seconds=9
    ).decide(_request())
    assert response.answers["model_route"].choice == "cloud"
    assert response.usage.input_tokens == 20
    assert response.id == "decision-123"


@pytest.mark.parametrize(
    "body",
    [
        _response("unoffered"),
        _response_without_usage(),
        _response_with_incomplete_probabilities(),
        b'{"answers":{}}',
    ],
)
def test_client_rejects_unoffered_or_missing_decision(monkeypatch, body: bytes):
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda request, timeout: io.BytesIO(body)
    )
    with pytest.raises(JevDecisionError):
        OpenRouterJevClient(api_key="test-key", model_id="typesafe/jev-1.13").decide(
            _request()
        )


def test_workspace_projection_does_not_send_identity_or_fact_values(tmp_path):
    project = {
        "project_id": "private-project-id",
        "route_summary_ref": "private/route.json",
        "checkpoint_candidates_ref": "private/checkpoints.json",
        "checkpoint_count": 219,
    }
    raw = json.dumps(project).encode()
    (tmp_path / "project.json").write_bytes(raw)

    projection = build_anonymized_workspace_projection(tmp_path)
    encoded = projection.model_dump_json()
    assert projection.projection_hash == hashlib.sha256(raw).hexdigest()
    assert projection.available_evidence_groups == ("checkpoint", "route")
    assert projection.hash_scope == ("project.json",)
    assert "private" not in encoded
    assert "219" not in encoded
