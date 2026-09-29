"""Exact cloud lane probe gates; no provider calls or private workspace reads."""

import json

import pytest

from tools.verify_pydantic_candidate_workspace import verify_probe


@pytest.mark.parametrize("fault", [None, "count", "source", "tool", "model", "native", "changed", "text"])
def test_probe_fails_closed(fault):
    answer = {"checkpoint_count": 19, "source_ref": "candidates/checkpoints.json"}
    metadata = {"response": {"id": "fixture"},
                "native_tool_trace": {"tool_call_count": 1, "tool_return_count": 1}}
    card = {"status": "completed"}
    if fault == "count":
        answer["checkpoint_count"] = 219
    if fault == "source":
        answer["source_ref"] = "wrong.json"
    if fault == "tool":
        card["status"] = "failed"
    if fault == "model":
        metadata["response"] = {}
    if fault == "native":
        metadata["native_tool_trace"]["tool_call_count"] = 0
    checks = verify_probe(
        answer="19 checkpoints" if fault == "text" else json.dumps(answer),
        metadata=metadata, card=card, count=19,
        source_ref="candidates/checkpoints.json", source_unchanged=fault != "changed",
    )
    assert all(checks.values()) is (fault is None)
