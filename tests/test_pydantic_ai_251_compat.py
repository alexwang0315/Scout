"""Isolated 2.51 decision-route contracts; not a Scout Jev integration test."""

from importlib.metadata import version

import pytest
from packaging.version import Version

pytestmark = pytest.mark.skipif(
    Version(version("pydantic-ai-slim")) < Version("2.50.0"),
    reason="DecisionModel route helpers were introduced in 2.50",
)


def test_none_and_multiple_tool_routes_keep_distinct_labels():
    from pydantic_ai.models.decision import ChoiceAnswer, _route_labels, _route_picked
    from pydantic_ai.tools import ToolDefinition

    none_output = ToolDefinition(
        name="final_result_None", kind="output", parameters_json_schema={"type": "null"}
    )
    local = ToolDefinition(name="local", parameters_json_schema={"type": "object"})
    cloud = ToolDefinition(name="cloud", parameters_json_schema={"type": "object"})
    routes = _route_labels([none_output], [local, cloud], None)

    assert list(routes) == ["None", "local", "cloud"]
    assert routes["None"] is none_output
    picked = _route_picked(
        ChoiceAnswer(
            choice="cloud",
            confidence=0.8,
            probabilities={"None": 0.1, "local": 0.1, "cloud": 0.8},
        ),
        routes,
    )
    assert picked == {
        "choice": "cloud",
        "probabilities": {"None": 0.1, "local": 0.1, "cloud": 0.8},
        "offered": ["None", "local", "cloud"],
    }


def test_unoffered_route_fails_closed():
    from pydantic_ai.exceptions import UnexpectedModelBehavior
    from pydantic_ai.models.decision import ChoiceAnswer, _route_picked
    from pydantic_ai.tools import ToolDefinition

    routes = {
        "local": ToolDefinition(name="local", parameters_json_schema={"type": "object"})
    }
    answer = ChoiceAnswer(choice="cloud", confidence=1.0, probabilities={"cloud": 1.0})
    with pytest.raises(UnexpectedModelBehavior, match="not offered"):
        _route_picked(answer, routes)
