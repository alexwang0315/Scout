"""Pydantic AI tool-selection adapter for AI HAT+2 public research."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

RESEARCH_SEARCH_TOOL = "scout_web_search"
RESEARCH_FETCH_TOOL = "scout_web_fetch"
RESEARCH_TOOL_NAMES = frozenset({RESEARCH_SEARCH_TOOL, RESEARCH_FETCH_TOOL})
_MAX_COMPACT_TOOL_RESULTS = 5
_MAX_COMPACT_CONTENT_CHARS = 3_000


class HailoResearchAction(BaseModel):
    """One model-selected public-research step."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action: Literal["web_search", "web_fetch", "finish"]
    query: str | None = None
    url: str | None = None

    @model_validator(mode="after")
    def validate_action_argument(self) -> HailoResearchAction:
        if self.action == "web_search" and not str(self.query or "").strip():
            raise ValueError("web_search requires query")
        if self.action == "web_fetch" and not str(self.url or "").strip():
            raise ValueError("web_fetch requires url")
        return self


def build_hailo_native_research_model(
    *,
    question: str,
    invoke_model: Callable[[str], str],
    workspace_evidence_summary: str = "",
    raw_rounds: list[dict[str, Any]] | None = None,
) -> FunctionModel:
    """Let Hailo select Pydantic AI WebSearch/WebFetch calls.

    The adapter never executes a URL itself. Pydantic AI capabilities own tool
    execution, use limits, domain policy, and public-host validation.
    """

    rounds = raw_rounds if raw_rounds is not None else []

    def model(messages: list[Any], info: AgentInfo) -> ModelResponse:
        completed_call_count = sum(
            isinstance(part, ToolReturnPart) and part.tool_name in RESEARCH_TOOL_NAMES
            for message in messages
            for part in getattr(message, "parts", ())
        )
        if completed_call_count >= 9:
            return ModelResponse(
                parts=[TextPart("Public research planning complete.")],
                model_name="hailo-native-research-planner",
            )
        available_tools = {
            str(getattr(tool, "name", "")) for tool in info.function_tools
        }
        prompt = render_hailo_research_action_prompt(
            question=question,
            messages=messages,
            available_tools=available_tools,
            workspace_evidence_summary=workspace_evidence_summary,
        )
        raw = invoke_model(prompt)
        action = parse_hailo_research_action(raw)
        rounds.append(
            {
                "round": len(rounds) + 1,
                "raw": raw,
                "action": action.model_dump(mode="json") if action else None,
            }
        )
        if action is None or action.action == "finish":
            return ModelResponse(
                parts=[TextPart("Public research planning complete.")],
                model_name="hailo-native-research-planner",
            )
        tool_name = {
            "web_search": RESEARCH_SEARCH_TOOL,
            "web_fetch": RESEARCH_FETCH_TOOL,
        }[action.action]
        if tool_name not in available_tools:
            return ModelResponse(
                parts=[TextPart("Requested public research tool is unavailable.")],
                model_name="hailo-native-research-planner",
            )
        args: dict[str, str]
        if action.action == "web_search":
            args = {"query": str(action.query).strip()}
        else:
            url = str(action.url).strip()
            if url not in research_result_urls(messages):
                return ModelResponse(
                    parts=[TextPart("Selected URL was not present in search results.")],
                    model_name="hailo-native-research-planner",
                )
            args = {"url": url}
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name=tool_name,
                    args=args,
                    tool_call_id=f"hailo_research_{len(rounds)}",
                )
            ],
            model_name="hailo-native-research-planner",
        )

    return FunctionModel(model, model_name="hailo-native-research-planner")


def render_hailo_research_action_prompt(
    *,
    question: str,
    messages: Iterable[Any],
    available_tools: set[str],
    workspace_evidence_summary: str = "",
) -> str:
    """Build a compact action-only prompt for the local model."""

    completed_tools = completed_research_tools(messages)
    tool_results = compact_research_tool_results(messages)
    return "\n".join(
        (
            "SCOUT_NATIVE_RESEARCH_ACTION_V1",
            "You are Scout AI's public-research tool planner.",
            "Decide whether fresh public evidence is useful for this question.",
            "Use web search for current weather, warnings, closures, official notices, "
            "or facts not available in the selected workspace.",
            "Do not use public research for private data, secrets, hardware control, or "
            "a static workspace fact that is already answerable locally.",
            "After search, fetch an exact URL returned by the search before relying on "
            "its content. Search snippets are discovery only.",
            "Return exactly one JSON object and no explanation:",
            '{"action":"web_search","query":"..."}',
            '{"action":"web_fetch","url":"https://..."}',
            '{"action":"finish"}',
            f"Available tools: {json.dumps(sorted(available_tools), ensure_ascii=False)}",
            f"Completed tools: {json.dumps(sorted(completed_tools), ensure_ascii=False)}",
            f"Question: {question}",
            f"Existing Scout evidence summary: {workspace_evidence_summary or 'none'}",
            f"Tool results: {json.dumps(tool_results, ensure_ascii=False, separators=(',', ':'))}",
        )
    )


def parse_hailo_research_action(value: str) -> HailoResearchAction | None:
    """Parse one JSON action while tolerating fenced model output."""

    text = value.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        payload = json.loads(text[start : end + 1])
        return HailoResearchAction.model_validate(payload)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def completed_research_tools(messages: Iterable[Any]) -> set[str]:
    return {
        str(part.tool_name)
        for message in messages
        for part in getattr(message, "parts", ())
        if isinstance(part, ToolReturnPart) and part.tool_name in RESEARCH_TOOL_NAMES
    }


def research_result_urls(messages: Iterable[Any]) -> set[str]:
    """Return only URLs produced by prior Pydantic AI research tools."""

    urls: set[str] = set()
    for message in messages:
        for part in getattr(message, "parts", ()):
            if not isinstance(part, ToolReturnPart):
                continue
            content = part.content
            if part.tool_name == RESEARCH_SEARCH_TOOL and isinstance(content, Sequence):
                for item in content:
                    if isinstance(item, Mapping) and item.get("url"):
                        urls.add(str(item["url"]))
            elif part.tool_name == RESEARCH_FETCH_TOOL and isinstance(content, Mapping):
                if content.get("url"):
                    urls.add(str(content["url"]))
    return urls


def compact_research_tool_results(messages: Iterable[Any]) -> list[dict[str, Any]]:
    """Keep enough result context for another model-selected research step."""

    results: list[dict[str, Any]] = []
    for message in messages:
        for part in getattr(message, "parts", ()):
            if not isinstance(part, ToolReturnPart):
                continue
            if part.tool_name == RESEARCH_SEARCH_TOOL and isinstance(
                part.content, Sequence
            ):
                content: Any = [
                    {
                        "title": str(item.get("title") or "")[:160],
                        "url": str(item.get("url") or ""),
                        "snippet": str(item.get("snippet") or "")[:240],
                    }
                    for item in part.content[:5]
                    if isinstance(item, Mapping)
                ]
            elif part.tool_name == RESEARCH_FETCH_TOOL and isinstance(
                part.content, Mapping
            ):
                content = {
                    "url": part.content.get("url"),
                    "status": part.content.get("status"),
                    "content_type": part.content.get("content_type"),
                    "content_hash": part.content.get("content_hash"),
                    "fetched_at": part.content.get("fetched_at"),
                    "content": str(part.content.get("content") or "")[
                        :_MAX_COMPACT_CONTENT_CHARS
                    ],
                }
            else:
                continue
            results.append({"tool_name": part.tool_name, "content": content})
    return results[-_MAX_COMPACT_TOOL_RESULTS:]


def research_tool_return_trace(result: Any) -> dict[str, Any]:
    """Build an in-memory content trace for deterministic evidence projection."""

    all_messages = getattr(result, "all_messages", None)
    messages = list(all_messages() if callable(all_messages) else all_messages or [])
    returns = [
        {"tool_name": part.tool_name, "content": part.content}
        for message in messages
        for part in getattr(message, "parts", ())
        if isinstance(part, ToolReturnPart) and part.tool_name in RESEARCH_TOOL_NAMES
    ]
    return {"tool_returns": returns}
