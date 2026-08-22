from __future__ import annotations

from collections.abc import Iterator

from pydantic_ai import Agent, RunContext
from pydantic_ai.capabilities.web_fetch import WebFetch
from pydantic_ai.capabilities.web_search import WebSearch

from pydantic_ai_runtime_compat import (
    pydantic_agent_runtime_kwargs,
    pydantic_native_research_trace,
)
from scout.agents.hailo_native_research import (
    build_hailo_native_research_model,
    parse_hailo_research_action,
    research_tool_return_trace,
)


def test_parse_hailo_research_action_accepts_fenced_json() -> None:
    action = parse_hailo_research_action(
        '```json\n{"action":"web_search","query":"奇萊南華 最新公告"}\n```'
    )

    assert action is not None
    assert action.action == "web_search"
    assert action.query == "奇萊南華 最新公告"


def test_hailo_research_model_lets_pydantic_execute_search_then_fetch() -> None:
    model_outputs: Iterator[str] = iter(
        (
            '{"action":"web_search","query":"奇萊南華 最新公告"}',
            '{"action":"web_fetch","url":"https://example.com/notice"}',
            '{"action":"finish"}',
        )
    )
    rounds: list[dict[str, object]] = []

    async def scout_web_search(
        _ctx: RunContext[object], query: str
    ) -> list[dict[str, str]]:
        assert query == "奇萊南華 最新公告"
        return [
            {
                "title": "官方公告",
                "url": "https://example.com/notice",
                "snippet": "搜尋摘要不可直接當證據",
            }
        ]

    async def scout_web_fetch(_ctx: RunContext[object], url: str) -> dict[str, object]:
        assert url == "https://example.com/notice"
        return {
            "url": url,
            "status": 200,
            "content_type": "text/html",
            "content": "<main>官方公告內容</main>",
            "content_hash": "sha256:" + "a" * 64,
            "fetched_at": "2026-08-21T01:00:00Z",
            "candidate_only": True,
            "runtime_safety_truth": False,
        }

    result = Agent(
        build_hailo_native_research_model(
            question="請上網找奇萊南華最新公告",
            invoke_model=lambda _prompt: next(model_outputs),
            raw_rounds=rounds,
        ),
        capabilities=[
            WebSearch(native=False, local=scout_web_search),
            WebFetch(native=False, local=scout_web_fetch),
        ],
        **pydantic_agent_runtime_kwargs(),
    ).run_sync("請判斷是否需要公開網路證據")

    trace = pydantic_native_research_trace(result)
    content_trace = research_tool_return_trace(result)

    assert trace["web_search_call_count"] == 1
    assert trace["web_fetch_call_count"] == 1
    assert trace["performed"] is True
    assert len(content_trace["tool_returns"]) == 2
    assert content_trace["tool_returns"][1]["content"]["url"] == (
        "https://example.com/notice"
    )
    assert [item["action"]["action"] for item in rounds] == [
        "web_search",
        "web_fetch",
        "finish",
    ]


def test_hailo_research_model_rejects_fetch_url_not_returned_by_search() -> None:
    model_outputs: Iterator[str] = iter(
        (
            '{"action":"web_search","query":"官方公告"}',
            '{"action":"web_fetch","url":"https://untrusted.example/private"}',
        )
    )

    async def scout_web_search(
        _ctx: RunContext[object], _query: str
    ) -> list[dict[str, str]]:
        return [{"title": "公告", "url": "https://example.com/notice"}]

    async def scout_web_fetch(_ctx: RunContext[object], _url: str) -> dict[str, object]:
        raise AssertionError("unselected URL must not be fetched")

    result = Agent(
        build_hailo_native_research_model(
            question="請查公告",
            invoke_model=lambda _prompt: next(model_outputs),
        ),
        capabilities=[
            WebSearch(native=False, local=scout_web_search),
            WebFetch(native=False, local=scout_web_fetch),
        ],
        **pydantic_agent_runtime_kwargs(),
    ).run_sync("請判斷是否需要公開網路證據")

    trace = pydantic_native_research_trace(result)

    assert trace["web_search_call_count"] == 1
    assert trace["web_fetch_call_count"] == 0
