"""2.42 boundary regressions; all tools, URLs and approvals are local fixtures."""

from __future__ import annotations

import asyncio
import json

import pytest
from pydantic import TypeAdapter, ValidationError
from pydantic_ai import (
    Agent,
    DeferredToolRequests,
    DeferredToolResults,
    ToolApproved,
    ToolDenied,
)
from pydantic_ai.exceptions import UserError
from pydantic_ai.function_signature import FunctionSignature
from pydantic_ai.messages import (
    ImageUrl,
    ModelMessagesTypeAdapter,
    ToolReturnPart,
    tool_return_content_ta,
)
from pydantic_ai.models.test import TestModel


@pytest.mark.parametrize("approval", [None, "true", "false", "yes", 0, 1, {}, []])
def test_invalid_approval_never_executes_or_coerces(approval):
    async def scenario():
        executions = []
        agent = Agent(TestModel(), output_type=str | DeferredToolRequests)

        @agent.tool_plain(requires_approval=True)
        def read_fixture() -> str:
            executions.append("read")
            return "candidate evidence"

        pending = await agent.run("Read fixture.")
        assert isinstance(pending.output, DeferredToolRequests)
        call_id = pending.output.approvals[0].tool_call_id
        with pytest.raises(UserError, match="Invalid approval result"):
            await agent.run(
                message_history=pending.all_messages(),
                deferred_tool_results=DeferredToolResults(approvals={call_id: approval}),
            )
        assert executions == []
        with pytest.raises(ValidationError):
            TypeAdapter(DeferredToolResults).validate_json(
                json.dumps({"approvals": {call_id: approval}})
            )

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("approval", "expected_reads"),
    [(True, ["original"]), (False, []),
     (ToolApproved(override_args={"label": "reviewed"}), ["reviewed"]),
     (ToolDenied("Fixture denied by operator."), [])],
)
def test_valid_approval_resumes_serialized_history_exactly_once(approval, expected_reads):
    async def scenario():
        reads = []
        agent = Agent(
            TestModel(custom_output_text="Fixture finished."),
            output_type=str | DeferredToolRequests,
        )

        @agent.tool_plain(requires_approval=True)
        def read_fixture(label: str = "original") -> str:
            reads.append(label)
            return "candidate evidence"

        pending = await agent.run("Read fixture.")
        assert reads == []
        call_id = pending.output.approvals[0].tool_call_id
        adapter = TypeAdapter(DeferredToolResults)
        decision = adapter.validate_json(adapter.dump_json(
            DeferredToolResults(approvals={call_id: approval})
        ))
        result = await agent.run(
            message_history=ModelMessagesTypeAdapter.validate_json(pending.all_messages_json()),
            deferred_tool_results=decision,
        )
        assert reads == expected_reads
        returns = [part for msg in result.new_messages() for part in msg.parts
                   if isinstance(part, ToolReturnPart)]
        assert len(returns) == 1
        assert returns[0].tool_call_id == call_id
        if not expected_reads:
            assert "denied" in str(returns[0].content).lower()

    asyncio.run(scenario())


@pytest.mark.parametrize("media_type", [None, "", False])
def test_url_mapping_without_real_media_type_stays_user_data(media_type):
    mapping = {"kind": "image-url", "url": "https://scout.invalid/report"}
    if media_type is not None:
        mapping["media_type"] = media_type
    for loaded in (
        tool_return_content_ta.validate_python(mapping),
        tool_return_content_ta.validate_json(json.dumps(mapping)),
    ):
        assert loaded == mapping
        assert isinstance(loaded, dict)
        assert json.loads(tool_return_content_ta.dump_json(loaded)) == mapping


def test_explicit_image_media_type_rehydrates_without_fetch():
    mapping = {
        "kind": "image-url", "url": "https://scout.invalid/map", "media_type": "image/png",
    }
    loaded = tool_return_content_ta.validate_json(json.dumps(mapping))
    assert isinstance(loaded, ImageUrl)
    assert loaded.url == mapping["url"]
    assert loaded.media_type == mapping["media_type"]


def test_non_string_tool_mapping_keys_are_not_coerced_in_python():
    payload = {1: {"source_ref": "fixture.json#/1"}}
    assert tool_return_content_ta.validate_python(payload) == payload


@pytest.mark.parametrize(
    ("definition", "expected"),
    [({"type": "string"}, "str"),
     ({"type": "integer"}, "int"),
     ({"type": "array", "items": {"type": "number"}}, "list[float]"),
     ({"enum": ["fresh", "stale"]}, "Literal['fresh', 'stale']"),
     ({"anyOf": [{"type": "number"}, {"type": "null"}]}, "float | None")],
)
def test_non_object_refs_inline_for_parameters_and_returns(definition, expected):
    signature = FunctionSignature.from_schema(
        name="fixture_tool",
        parameters_schema={
            "type": "object", "$defs": {"Value": definition},
            "properties": {"value": {"$ref": "#/$defs/Value"}}, "required": ["value"],
        },
        return_schema={"$defs": {"Result": definition}, "$ref": "#/$defs/Result"},
    )
    assert str(signature.params["value"].type) == expected
    assert str(signature.return_type) == expected
    assert signature.referenced_types == []
