from __future__ import annotations

import asyncio
from importlib.metadata import version

import pytest
from packaging.version import Version
from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    PartStartEvent,
    ToolAvailabilityDeltaPart,
    ToolReturnPart,
    ToolSearchCallPart,
    ToolSearchReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import _synthesize_tool_availability_delta_messages
from pydantic_ai.models.test import TestModel


pytestmark = pytest.mark.skipif(
    Version(version("pydantic-ai-slim")) < Version("2.40.0"),
    reason="Pydantic AI 2.40 compatibility regression",
)


def test_filtered_agent_event_hook_observes_run_without_changing_output() -> None:
    async def run_case() -> tuple[str, list[str]]:
        observed: list[str] = []
        agent = Agent(TestModel(custom_output_text="Scout evidence ready."))

        @agent.on_event(PartStartEvent)
        async def capture(
            ctx: RunContext[None], event: PartStartEvent
        ) -> None:
            del ctx
            observed.append(type(event).__name__)

        result = await agent.run("Read one bounded evidence response.")
        return result.output, observed

    output, observed = asyncio.run(run_case())

    assert output == "Scout evidence ready."
    assert observed == ["PartStartEvent"]


def test_parallel_tool_results_precede_synthetic_deferred_reveals() -> None:
    messages = [
        ModelRequest(
            parts=[
                ToolAvailabilityDeltaPart(tools_added=["route_map"]),
                ToolReturnPart(
                    tool_name="risk",
                    content="risk ready",
                    tool_call_id="risk-1",
                ),
                ToolAvailabilityDeltaPart(tools_added=["weather_map"]),
                ToolReturnPart(
                    tool_name="weather",
                    content="weather ready",
                    tool_call_id="weather-1",
                ),
                UserPromptPart("Do not cross this message boundary."),
            ]
        )
    ]

    projected = _synthesize_tool_availability_delta_messages(
        messages,
        {"route_map", "weather_map"},
    )

    assert len(projected) == 5
    assert isinstance(projected[0], ModelRequest)
    assert [type(part) for part in projected[0].parts] == [
        ToolReturnPart,
        ToolReturnPart,
    ]
    assert isinstance(projected[1], ModelResponse)
    assert isinstance(projected[1].parts[0], ToolSearchCallPart)
    assert isinstance(projected[2], ModelRequest)
    assert isinstance(projected[2].parts[0], ToolSearchReturnPart)
    assert projected[1].parts[0].tool_call_id == projected[2].parts[0].tool_call_id
    assert isinstance(projected[3], ModelResponse)
    assert isinstance(projected[3].parts[0], ToolSearchCallPart)
    assert isinstance(projected[4], ModelRequest)
    assert isinstance(projected[4].parts[0], ToolSearchReturnPart)
    assert projected[3].parts[0].tool_call_id == projected[4].parts[0].tool_call_id
    assert isinstance(projected[4].parts[1], UserPromptPart)
