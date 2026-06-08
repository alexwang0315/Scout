"""Pydantic AI backed provider for Scout AI OS agent facades."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from scout.agents.deps import (
    DeterministicScoutAgentProvider,
    ScoutAgentProvider,
    ScoutAgentRequest,
    validate_provider_output,
)


class PydanticScoutAgentProvider:
    """Run Scout typed agent requests through Pydantic AI.

    By default this uses a local ``FunctionModel`` so Mac-side smoke runs do not
    require cloud credentials. Callers may pass a Pydantic AI model object or
    model name to use a configured external provider instead.
    """

    def __init__(
        self,
        model: Any | None = None,
        *,
        local_provider: ScoutAgentProvider | None = None,
    ) -> None:
        self._model = model
        self._local_provider = local_provider or DeterministicScoutAgentProvider()

    def run(self, request: ScoutAgentRequest) -> BaseModel:
        """Run a typed Scout request via ``pydantic_ai.Agent``."""

        agent = Agent(
            self._model or self._local_function_model(request),
            output_type=request.output_type,
            instructions=request.instructions,
            name=request.agent_name,
            tools=_read_only_tools(request),
        )
        result = agent.run_sync(request.prompt)
        return validate_provider_output(result.output, request.output_type)

    def _local_function_model(self, request: ScoutAgentRequest) -> FunctionModel:
        def scout_local_model(
            messages: list[ModelMessage],
            agent_info: AgentInfo,
        ) -> ModelResponse:
            del messages
            output = validate_provider_output(
                self._local_provider.run(request),
                request.output_type,
            )
            if not agent_info.output_tools:
                raise ValueError("Pydantic AI did not expose an output tool.")

            output_tool = agent_info.output_tools[0]
            output_args: Any = output.model_dump(mode="json")
            if output_tool.outer_typed_dict_key:
                output_args = {output_tool.outer_typed_dict_key: output_args}
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        output_tool.name,
                        output_args,
                        tool_call_id=f"scout_output__{request.agent_name}",
                    )
                ],
                model_name="scout-local-function-model",
            )

        return FunctionModel(
            scout_local_model,
            model_name=f"scout-local-function:{request.agent_name}",
        )


def _read_only_tools(request: ScoutAgentRequest) -> list[Callable[..., Any]]:
    """Expose the Scout read-only toolbox as Pydantic AI tools."""

    def search_memory(query: str) -> list[str]:
        return request.tools.search_memory(query)

    def search_capabilities(query: str) -> list[dict[str, Any]]:
        return request.tools.search_capabilities(query)

    def get_active_context() -> dict[str, Any]:
        return request.tools.get_active_context()

    def get_capability(name: str) -> dict[str, Any] | None:
        return request.tools.get_capability(name)

    return [
        search_memory,
        search_capabilities,
        get_active_context,
        get_capability,
    ]


__all__ = ["PydanticScoutAgentProvider"]
