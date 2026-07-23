from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from scout.agents.model_execution import ScoutModelExecutionAdapter


def test_model_execution_adapter_keeps_route_metadata_with_callable() -> None:
    def invoke(**_kwargs):
        return "answer", {"request_id": "fixture"}

    adapter = ScoutModelExecutionAdapter(
        adapter_id="fixture.cloud",
        profile="cloud",
        provider="fixture-provider",
        transport="fixture-transport",
        invoke=invoke,
    )

    assert adapter.invoke(prompt="question") == (
        "answer",
        {"request_id": "fixture"},
    )
    with pytest.raises(FrozenInstanceError):
        adapter.provider = "different-provider"  # type: ignore[misc]


def test_model_execution_adapter_can_expose_contextual_native_tool_transport() -> None:
    def invoke(**_kwargs):
        return "answer", {}

    def invoke_with_context(**_kwargs):
        return "answer with tools", {"native_tool_trace": {"tool_call_count": 1}}

    adapter = ScoutModelExecutionAdapter(
        adapter_id="fixture.cloud",
        profile="cloud",
        provider="fixture-provider",
        transport="fixture-transport",
        invoke=invoke,
        invoke_with_context=invoke_with_context,
    )

    assert adapter.invoke_with_context is invoke_with_context
