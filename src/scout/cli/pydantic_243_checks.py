"""Network-free 2.43 stream and CLI contracts for the compatibility harness."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any

import httpx2
from openai import AsyncOpenAI
from pydantic_ai import Agent, Tool
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.profiles.openai import OpenAIModelProfile
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.openrouter import OpenRouterProvider
from pydantic_ai.ui.vercel_ai import VercelAIAdapter
from pydantic_ai.ui.vercel_ai.request_types import SubmitMessage, TextUIPart, UIMessage

from scout.agents.pydantic_ai_compat import pydantic_agent_runtime_kwargs


async def stream_boundary_case(
    provider: str,
    *,
    thinking: bool = False,
    tool_count: int = 1,
) -> dict[str, Any]:
    requests: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    markers = [f"CP-{index:02d}" for index in range(1, tool_count + 1)]
    final_text = "Verified " + ", ".join(markers)

    def read_marker(index: int) -> dict[str, Any]:
        receipt = {
            "marker": markers[index - 1],
            "source_ref": f"fixture://route/checkpoints/{index}",
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
        receipts.append(receipt)
        return receipt

    def respond(request: httpx2.Request) -> httpx2.Response:
        payload = json.loads(request.content)
        assert payload["stream"] is True
        requests.append(payload)
        deltas: list[dict[str, Any]] = []
        if len(requests) == 1:
            deltas.extend(
                [
                    {
                        "role": "assistant",
                        "content": "<think>" if thinking else "Checking ",
                    },
                    {"content": "route evidence."},
                ]
            )
            for index in range(1, tool_count + 1):
                deltas.append(
                    {
                        "tool_calls": [
                            {
                                "index": index - 1,
                                "id": f"fixture-call-{index}",
                                "type": "function",
                                "function": {
                                    "name": "read_marker",
                                    "arguments": json.dumps({"index": index}),
                                },
                            }
                        ]
                    }
                )
                if thinking and index == 1:
                    deltas.append({"content": "</think>"})
                deltas.append({"content": f" Read marker {index}."})
            finish_reason = "tool_calls"
        else:
            assert len(requests) == 2, "unexpected extra model request"
            returns = [m for m in payload["messages"] if m["role"] == "tool"]
            assert {m["tool_call_id"] for m in returns} == {
                f"fixture-call-{index}" for index in range(1, tool_count + 1)
            }
            assert {json.loads(m["content"])["marker"] for m in returns} == set(markers)
            deltas.append({"role": "assistant", "content": final_text})
            finish_reason = "stop"
        chunks = [
            {
                "id": f"fixture-response-{len(requests)}",
                "created": 0,
                "model": payload["model"],
                "object": "chat.completion.chunk",
                "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
            }
            for delta in deltas
        ]
        chunks[-1]["choices"][0]["finish_reason"] = finish_reason
        return httpx2.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content="".join(f"data: {json.dumps(c)}\n\n" for c in chunks)
            + "data: [DONE]\n\n",
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as http:
        async with AsyncOpenAI(
            base_url="https://fixture.invalid/v1",
            api_key="fixture-only",
            http_client=http,
        ) as client:
            profile = OpenAIModelProfile(thinking_tags=("<think>", "</think>"))
            if provider == "openrouter":
                model = OpenRouterModel(
                    "openai/scout-fixture",
                    provider=OpenRouterProvider(openai_client=client),
                    profile=profile,
                )
            else:
                assert provider == "openai"
                model = OpenAIChatModel(
                    "scout-fixture",
                    provider=OpenAIProvider(openai_client=client),
                    profile=profile,
                )
            agent = Agent(
                model, tools=[Tool(read_marker)], **pydantic_agent_runtime_kwargs()
            )
            adapter = VercelAIAdapter(
                agent,
                SubmitMessage(
                    id="fixture",
                    messages=[
                        UIMessage(
                            id="question",
                            role="user",
                            parts=[TextUIPart(text="Read route markers.")],
                        ),
                    ],
                ),
                sdk_version=6,
            )
            events = [
                json.loads(raw.removeprefix("data: "))
                async for raw in adapter.encode_stream(adapter.run_stream())
                if "[DONE]" not in raw
            ]

    # Check the consumer lifecycle, not just the reconstructed final string.
    open_parts: dict[str, set[str]] = {"text": set(), "reasoning": set()}
    visible = []
    for event in events:
        kind, part_id = event.get("type", ""), event.get("id")
        for family, active in open_parts.items():
            if kind == f"{family}-start":
                assert part_id and part_id not in active
                active.add(part_id)
            elif kind == f"{family}-delta":
                assert part_id in active, (
                    f"{family}-delta on ended or missing part: {part_id}"
                )
                if family == "text":
                    visible.append(event["delta"])
            elif kind == f"{family}-end":
                assert part_id in active
                active.remove(part_id)
    assert all(not active for active in open_parts.values()), "unclosed stream parts"
    assert len(requests) == 2 and len(receipts) == tool_count
    assert final_text in "".join(visible)
    assert "</think>" not in "".join(visible)
    assert "<think>" not in "".join(visible)
    tool_returns = [
        event for event in events if event["type"] == "tool-output-available"
    ]
    assert len(tool_returns) == tool_count
    assert {event["toolCallId"] for event in tool_returns} == {
        f"fixture-call-{index}" for index in range(1, tool_count + 1)
    }
    assert {event["output"]["source_ref"] for event in tool_returns} == {
        receipt["source_ref"] for receipt in receipts
    }
    return {
        "provider": provider,
        "thinking": thinking,
        "model_requests": len(requests),
        "tool_calls": len(receipts),
        "stream_lifecycle_valid": True,
        "source_refs_preserved": True,
        "network_performed": False,
        "text_start_count": sum(e["type"] == "text-start" for e in events),
    }


async def check_stream_boundaries() -> dict[str, Any]:
    cases = [
        await stream_boundary_case(provider, thinking=thinking, tool_count=tool_count)
        for provider in ("openai", "openrouter")
        for thinking in (False, True)
        for tool_count in (1, 2)
    ]
    return {"network_performed": False, "case_count": len(cases), "cases": cases}


def banner_output_case(mode: str) -> dict[str, Any]:
    assert mode in {"enabled", "api_disabled", "env_disabled", "ci"}
    script = """
import json, sys
import pydantic_ai
from pydantic_ai import Agent
from pydantic_ai.models import test
import pydantic_ai.models
pydantic_ai.models.ALLOW_MODEL_REQUESTS = False
assert hasattr(pydantic_ai, 'BANNER_ENABLED'), 'public banner opt-out missing'
sys.stderr.isatty = lambda: True
if sys.argv[1] == 'api_disabled':
    pydantic_ai.BANNER_ENABLED = False
agent = Agent(test.TestModel(custom_output_text='fixture-ok'))
outputs = [agent.run_sync('Read fixture.').output for _ in range(2)]
print(json.dumps({'outputs': outputs}))
"""
    # Do not propagate the operator's credentials, CI flags or instrumentation.
    env = {"PATH": os.defpath, "PYTHONIOENCODING": "utf-8"}
    if mode == "env_disabled":
        env["PYDANTIC_AI_NO_BANNER"] = "1"
    if mode == "ci":
        env["CI"] = "1"
    result = subprocess.run(
        [sys.executable, "-c", script, mode],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    assert json.loads(result.stdout) == {"outputs": ["fixture-ok", "fixture-ok"]}
    count = result.stderr.count("pydantic-ai v")
    assert count == (1 if mode == "enabled" else 0), result.stderr
    return {
        "mode": mode,
        "stdout_json_valid": True,
        "banner_count": count,
        "network_performed": False,
    }


def check_banner_output() -> dict[str, Any]:
    return {
        "cases": [
            banner_output_case(mode)
            for mode in ("enabled", "api_disabled", "env_disabled", "ci")
        ],
        "network_performed": False,
    }
