"""Candidate-only 2.47 contracts; no live provider requests."""

from importlib.metadata import version
from types import NoneType

import pytest
from packaging.version import Version

pytestmark = pytest.mark.skipif(
    Version(version("pydantic-ai-slim")) < Version("2.47.0"),
    reason="Run with the isolated Pydantic AI 2.47 candidate overlay",
)


@pytest.mark.parametrize("content", [{"question": "hello"}, 42, b"hello", [42]])
def test_invalid_user_content_rejected_before_provider(content):
    from pydantic_ai.messages import UserPromptPart

    with pytest.raises(ValueError, match="UserPromptPart.content"):
        UserPromptPart(content)


@pytest.mark.parametrize("content", ["hello", ["hello"], ("hello", "world")])
def test_valid_user_content_roundtrip(content):
    from pydantic_ai.messages import (
        ModelMessagesTypeAdapter,
        ModelRequest,
        UserPromptPart,
    )

    messages = [ModelRequest(parts=[UserPromptPart(content)])]
    restored = ModelMessagesTypeAdapter.validate_json(
        ModelMessagesTypeAdapter.dump_json(messages)
    )
    assert restored[0].parts[0].content == (
        list(content) if isinstance(content, tuple) else content
    )


@pytest.mark.parametrize("output", [None, NoneType])
def test_none_route_name(output):
    from pydantic_ai._output import _output_type_name

    assert _output_type_name(output) == "None"


def test_described_none_route_is_recognized_and_preserved():
    from pydantic_ai.tools import ToolDefinition

    if Version(version("pydantic-ai-slim")) >= Version("2.50.0"):
        from pydantic_ai.models.decision import (
            _none_route,
            _route_args,
            _route_description,
        )
    else:
        from pydantic_ai.models.typesafe import (
            _none_route,
            _route_args,
            _route_description,
        )

    tool = ToolDefinition(
        name="final_result_None",
        kind="output",
        outer_typed_dict_key="response",
        parameters_json_schema={
            "type": "object",
            "properties": {
                "response": {"type": "null", "description": "Insufficient evidence"},
            },
        },
    )
    assert _none_route(tool)
    assert _route_args(tool) == {"response": None}
    assert _route_description(tool) == "Insufficient evidence"


def test_wrapped_choices_route_description_is_preserved():
    from pydantic_ai.tools import ToolDefinition

    if Version(version("pydantic-ai-slim")) >= Version("2.50.0"):
        from pydantic_ai.models.decision import _route_description
    else:
        from pydantic_ai.models.typesafe import _route_description

    tool = ToolDefinition(
        name="final_result_route",
        kind="output",
        outer_typed_dict_key="response",
        parameters_json_schema={
            "type": "object",
            "properties": {
                "response": {
                    "type": "string",
                    "enum": ["local", "cloud"],
                    "description": "Select an evidence execution lane",
                },
            },
        },
    )
    assert _route_description(tool) == "Select an evidence execution lane"
