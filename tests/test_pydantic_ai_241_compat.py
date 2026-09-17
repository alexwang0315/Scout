"""Offline checks for the 2.41 capability migration; no real provider access."""

from __future__ import annotations

import warnings

import pytest
from pydantic_ai.capabilities import ImageGeneration, XSearch
from pydantic_ai.exceptions import PydanticAIDeprecationWarning, UserError
from pydantic_ai.messages import (
    ModelMessagesTypeAdapter,
    ModelResponse,
    TextPart,
)
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RequestUsage


@pytest.mark.parametrize("capability_type", [ImageGeneration, XSearch])
def test_explicit_fallback_subagent_model_has_no_deprecation(capability_type):
    model = TestModel()
    with warnings.catch_warnings():
        warnings.simplefilter("error", PydanticAIDeprecationWarning)
        capability = capability_type(fallback_subagent_model=model)

    assert capability.fallback_subagent_model is model


@pytest.mark.parametrize("capability_type", [ImageGeneration, XSearch])
def test_legacy_fallback_name_warns_and_preserves_model(capability_type):
    model = TestModel()
    with pytest.warns(PydanticAIDeprecationWarning, match="fallback_subagent_model"):
        capability = capability_type(fallback_model=model)
    assert capability.fallback_subagent_model is model

    with pytest.warns(PydanticAIDeprecationWarning, match="fallback_subagent_model"):
        assert capability.fallback_model is model


@pytest.mark.parametrize("capability_type", [ImageGeneration, XSearch])
def test_ambiguous_fallback_configuration_is_rejected(capability_type):
    model = TestModel()
    with pytest.raises(UserError, match="cannot specify both"):
        capability_type(fallback_model=model, fallback_subagent_model=model)


@pytest.mark.parametrize("capability_type", [ImageGeneration, XSearch])
def test_capability_merge_does_not_silently_replace_subagent_with_local_tool(
    capability_type,
):
    def local_tool(query: str) -> str:
        return "fixture evidence"

    subagent = capability_type(fallback_subagent_model=TestModel())
    local = capability_type(local=local_tool)
    with pytest.raises(UserError, match="fallback_subagent_model"):
        capability_type.combine([subagent, local])


def test_provider_search_usage_survives_message_serialization() -> None:
    messages = [
        ModelResponse(
            parts=[TextPart("Fixture search result.")],
            usage=RequestUsage(input_tokens=12, details={"web_search_requests": 2}),
        )
    ]

    restored = ModelMessagesTypeAdapter.validate_json(
        ModelMessagesTypeAdapter.dump_json(messages)
    )

    assert isinstance(restored[0], ModelResponse)
    assert restored[0].usage.input_tokens == 12
    assert restored[0].usage.details == {"web_search_requests": 2}
