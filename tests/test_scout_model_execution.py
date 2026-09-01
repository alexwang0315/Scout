from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from scout.agents.model_execution import (
    ModelRunCancellationReceipt,
    ScoutModelExecutionAdapter,
)


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


def test_model_run_cancellation_receipt_is_candidate_only_and_frozen() -> None:
    now = datetime.now(UTC)
    receipt = ModelRunCancellationReceipt(
        status="timed_out",
        reason_code="total_run_deadline_exceeded",
        checkpoint="after_model_request",
        adapter_id="fixture.cloud",
        provider="fixture-provider",
        model_id="fixture/model",
        started_at=now,
        recorded_at=now,
        elapsed_ms=1250,
        total_run_timeout_seconds=1.0,
        completed_model_attempts=1,
        interrupted_request_index=1,
        provider_cancellation_supported=True,
        late_provider_output_discarded=True,
    )

    assert receipt.partial_trace_preserved is True
    assert receipt.candidate_only is True
    assert receipt.runtime_safety_truth is False
    with pytest.raises(Exception):
        receipt.status = "cancelled"  # type: ignore[misc]
