#!/usr/bin/env python3
"""Evaluate Scout WebSearch/WebFetch tool use on the physical AI HAT+2 model."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from pydantic_ai import Agent, RunContext, Tool, UsageLimits
from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.messages import (
    ModelResponse,
    RetryPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from scout.agents.local_cwa_research import build_local_cwa_research_fetch
from scout.agents.local_web_fetch import build_local_web_fetch
from scout.agents.local_web_search import build_local_web_search
from scout.agents.pydantic_ai_compat import pydantic_agent_runtime_kwargs
from scout.agents.web_research_quality import (
    ResearchQuestionSpec,
    build_web_evidence_bundle,
    compact_evidence_for_synthesis,
    evaluate_web_research,
    extract_research_links,
    question_requests_field_list,
    select_research_url,
    visible_text,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = (
    ROOT / "docs" / "evals" / "scout-pydantic-ai-232-local-web-20-corpus.json"
)
DEFAULT_OUTPUT_ROOT = Path("/data/scout/admin/evals")
DEFAULT_ENDPOINT = "http://127.0.0.1:8000/api/chat"
DEFAULT_MODEL = "qwen3:1.7b"
MAX_CALLS = 10
MAX_HAILO_PROMPT_CHARS = 12_000
MAX_HAILO_INPUT_TOKENS = 1_200


def compact_fetched_content(value: str, *, max_chars: int = 420) -> str:
    return visible_text(value, max_chars=max_chars)


def normalize_hailo_chat_content(value: str) -> str:
    """Flatten control characters rejected by Hailo Ollama 5.3 JSON parsing."""

    return re.sub(r"[\x00-\x1f\x7f]+", " ", value).strip()


def naturalize_labeled_answer(answer: str, *, allow_field_list: bool) -> str:
    """Render verified date/status/url fields without asking the small model again."""

    cleaned = answer.strip()
    if not cleaned or allow_field_list:
        return cleaned
    aliases = {
        "date": "date",
        "日期": "date",
        "status": "status",
        "狀態": "status",
        "url": "url",
        "網址": "url",
        "來源": "url",
        "完整來源網址": "url",
    }
    fields: dict[str, str] = {}
    for line in cleaned.splitlines():
        match = re.match(
            r"^\s*(?:[-*]\s*)?(?:\*\*)?([^:：*\n]{1,24}?)(?:\*\*)?\s*[:：]\s*(.+?)\s*$",
            line,
        )
        if match is None:
            continue
        label = re.sub(r"\s+", "", match.group(1)).casefold()
        canonical = aliases.get(label)
        if canonical is None:
            continue
        value = match.group(2).strip().rstrip("  ").strip("*").strip()
        if value:
            fields[canonical] = value
    if not {"date", "status", "url"} <= fields.keys():
        return cleaned
    return (
        f"公告日期為{fields['date']}，最新公告內容為「{fields['status']}」。"
        f"來源：{fields['url']}"
    )


def _compact_match_text(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def compact_repetitive_answer(
    answer: str,
    *,
    required_literals: tuple[str, ...],
    topic_terms: tuple[str, ...],
    allow_field_list: bool,
) -> str:
    """Keep the smallest complete set of model sentences; provenance is reattached."""

    cleaned = answer.strip()
    if not cleaned or allow_field_list:
        return cleaned
    unique_lines: list[str] = []
    signatures: set[str] = set()
    for raw_line in cleaned.splitlines():
        line = raw_line.strip().strip("*").strip()
        for url in _extract_urls(line):
            line = line.replace(url, "")
        line = re.sub(
            r"(?:完整)?來源(?:網址)?\s*(?:為)?\s*[:：]?\s*$",
            "",
            line,
        ).strip()
        if not line:
            continue
        signature = _compact_match_text(line)
        if signature in signatures:
            continue
        signatures.add(signature)
        unique_lines.append(line)
    if not unique_lines:
        return cleaned
    required = tuple(dict.fromkeys(required_literals))
    topics = tuple(dict.fromkeys(topic_terms))
    for line in unique_lines:
        searchable = _compact_match_text(line)
        if required and not all(
            _compact_match_text(value) in searchable for value in required
        ):
            continue
        if topics and not any(
            _compact_match_text(value) in searchable for value in topics
        ):
            continue
        return line
    return "\n".join(unique_lines[:3])


def validate_hailo_prompt(prompt: str) -> None:
    """Fail before sending input beyond the physical Hailo model context."""

    if len(prompt) > MAX_HAILO_PROMPT_CHARS:
        raise ValueError(
            "Hailo hardware context guard exceeded: "
            f"{len(prompt)} > {MAX_HAILO_PROMPT_CHARS} characters"
        )
    estimated_tokens = estimate_hailo_input_tokens(prompt)
    if estimated_tokens > MAX_HAILO_INPUT_TOKENS:
        raise ValueError(
            "Hailo hardware input token guard exceeded: "
            f"{estimated_tokens} > {MAX_HAILO_INPUT_TOKENS} estimated tokens"
        )


def estimate_hailo_input_tokens(value: str) -> int:
    cjk_characters = len(re.findall(r"[\u3400-\u9fff]", value))
    other_characters = max(0, len(value) - cjk_characters)
    return cjk_characters + (other_characters + 3) // 4


def pack_hailo_prompt(
    *,
    prefix_lines: list[str],
    evidence: str,
    suffix_lines: list[str],
) -> str:
    def render(evidence_value: str) -> str:
        return "\n".join(
            [
                *prefix_lines,
                f"已驗證證據卡:{evidence_value or '尚無'}",
                *suffix_lines,
            ]
        )

    prompt = render(evidence)
    if estimate_hailo_input_tokens(prompt) <= MAX_HAILO_INPUT_TOKENS:
        return prompt
    if estimate_hailo_input_tokens(render("")) > MAX_HAILO_INPUT_TOKENS:
        raise ValueError("Hailo prompt instructions exceed the input token envelope")
    low = 0
    high = len(evidence)
    while low < high:
        middle = (low + high + 1) // 2
        if (
            estimate_hailo_input_tokens(render(evidence[:middle]))
            <= MAX_HAILO_INPUT_TOKENS
        ):
            low = middle
        else:
            high = middle - 1
    return render(evidence[:low])


def _hailo_non_stream_retry(
    *,
    endpoint: str,
    request_payload: dict[str, Any],
    timeout_seconds: float,
    reason: str,
    attempts: int = 1,
    delay_seconds: float = 0.0,
) -> tuple[str, dict[str, Any]]:
    fallback_payload = json.dumps(
        {**request_payload, "stream": False},
        ensure_ascii=False,
    ).encode("utf-8")
    fallback_request = Request(
        endpoint,
        data=fallback_payload,
        headers={"Content-Type": "application/json"},
    )
    body: dict[str, Any] | None = None
    for attempt in range(attempts):
        if delay_seconds and (attempt > 0 or reason.startswith("stream_http_")):
            time.sleep(delay_seconds)
        try:
            with urlopen(fallback_request, timeout=timeout_seconds) as response:
                body = json.load(response)
            break
        except HTTPError as exc:
            if exc.code < 500 or attempt + 1 >= attempts:
                raise
    if body is None:  # pragma: no cover - defensive guard for future retry changes.
        raise RuntimeError("Hailo non-stream retry returned no response body")
    content = str((body.get("message") or {}).get("content") or "").strip()
    return content, {
        key: body.get(key)
        for key in (
            "done_reason",
            "prompt_eval_count",
            "eval_count",
            "total_duration",
            "load_duration",
            "prompt_eval_duration",
            "eval_duration",
        )
    } | {
        "stream_response_count": 0,
        "semantic_json_stop": parse_model_action(content) is not None,
        "semantic_stop_reason": reason,
        "stream_fallback": True,
    }


def load_corpus(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases")
    if not isinstance(cases, list) or len(cases) != 20:
        raise ValueError("local web eval corpus must contain exactly 20 cases")
    case_ids = [str(item.get("case_id") or "") for item in cases]
    if len(set(case_ids)) != len(case_ids) or any(not item for item in case_ids):
        raise ValueError("local web eval case_id values must be unique and non-empty")
    return payload


def parse_model_action(raw: str) -> dict[str, Any] | None:
    cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL | re.IGNORECASE).strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE).strip()
    decoder = json.JSONDecoder()
    for index, char in enumerate(cleaned):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(cleaned[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("action") in {"tool", "answer"}:
            return value
    return None


def _hailo_chat(
    *,
    endpoint: str,
    model: str,
    prompt: str,
    timeout_seconds: float,
    required_source_refs: tuple[str, ...] = (),
    minimum_source_refs: int = 0,
    required_answer_literals: tuple[str, ...] = (),
    required_topic_terms: tuple[str, ...] = (),
) -> tuple[str, dict[str, Any]]:
    validate_hailo_prompt(prompt)
    request_payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": normalize_hailo_chat_content(prompt)}
        ],
        "stream": True,
        "think": False,
        "options": {
            "temperature": 0,
            "stop": ["\n", "<SCOUT_DONE>"],
        },
    }
    payload = json.dumps(
        request_payload,
        ensure_ascii=False,
    ).encode("utf-8")
    request = Request(
        endpoint,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            chunks: list[dict[str, Any]] = []
            content_parts: list[str] = []
            semantic_content: str | None = None
            semantic_stop_reason: str | None = None
            semantic_stream_closed_early = False
            for raw_line in response:
                if not raw_line.strip():
                    continue
                chunk = json.loads(raw_line)
                if not isinstance(chunk, dict):
                    continue
                chunks.append(chunk)
                content_parts.append(
                    str((chunk.get("message") or {}).get("content") or "")
                )
                content_so_far = "".join(content_parts)
                if (
                    semantic_content is None
                    and parse_model_action(content_so_far) is not None
                ):
                    semantic_content = content_so_far
                    semantic_stop_reason = "complete_action_json"
                normalized_content = _compact_match_text(content_so_far)
                if (
                    semantic_content is None
                    and required_answer_literals
                    and all(
                        _compact_match_text(value) in normalized_content
                        for value in required_answer_literals
                    )
                    and (
                        not required_topic_terms
                        or any(
                            _compact_match_text(value) in normalized_content
                            for value in required_topic_terms
                        )
                    )
                    and bool(re.search(r"[。！？\n]", content_so_far))
                    and '"action"' not in content_so_far
                    and "```json" not in content_so_far.casefold()
                ):
                    semantic_content = content_so_far
                    semantic_stop_reason = "required_answer_contract_complete"
                if (
                    semantic_content is None
                    and minimum_source_refs > 0
                    and sum(
                        source_ref in content_so_far
                        for source_ref in dict.fromkeys(required_source_refs)
                    )
                    >= minimum_source_refs
                ):
                    semantic_content = content_so_far
                    semantic_stop_reason = "required_source_refs_complete"
                if (
                    semantic_content is None
                    and _malformed_stream_has_stalled(content_so_far)
                ):
                    semantic_content = content_so_far
                    semantic_stop_reason = "malformed_nonprogress"
                if semantic_content is not None and not chunk.get("done"):
                    semantic_stream_closed_early = True
                    break
                if chunk.get("done"):
                    if semantic_stop_reason is None:
                        semantic_stop_reason = str(
                            chunk.get("done_reason") or "done"
                        )
                    break
            body = chunks[-1] if chunks else {}
        if not chunks:
            return _hailo_non_stream_retry(
                endpoint=endpoint,
                request_payload=request_payload,
                timeout_seconds=timeout_seconds,
                reason="empty_stream_non_stream_retry",
            )
    except HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")[:2_000]
        if exc.code >= 500:
            try:
                return _hailo_non_stream_retry(
                    endpoint=endpoint,
                    request_payload=request_payload,
                    timeout_seconds=timeout_seconds,
                    reason=f"stream_http_{exc.code}_non_stream_retry",
                    attempts=2,
                    delay_seconds=1.0,
                )
            except HTTPError:
                pass
        raise RuntimeError(
            f"Hailo HTTP {exc.code}: {response_body or exc.reason}"
        ) from exc
    content = (semantic_content or "".join(content_parts)).strip()
    return content, {
        key: body.get(key)
        for key in (
            "done_reason",
            "prompt_eval_count",
            "eval_count",
            "total_duration",
            "load_duration",
            "prompt_eval_duration",
            "eval_duration",
        )
    } | {
        "stream_response_count": len(chunks),
        "semantic_json_stop": semantic_stop_reason == "complete_action_json",
        "semantic_stop_reason": semantic_stop_reason,
        "semantic_stream_closed_early": semantic_stream_closed_early,
        "stream_fallback": False,
    }


def _malformed_stream_has_stalled(value: str) -> bool:
    """Freeze repetitive or runaway output while still draining the stream."""

    if len(value) < 600:
        return False
    if "\n\n" in value:
        return True
    tail = value[-120:]
    if len(tail) >= 80 and value[:-120].count(tail) >= 1:
        return True
    return len(value) >= 2_000


def _compact_tool_returns(messages: Iterable[Any], *, max_chars: int = 900) -> str:
    values: list[dict[str, Any]] = []
    for message in messages:
        for part in getattr(message, "parts", ()):
            if not isinstance(part, ToolReturnPart):
                continue
            content = part.content
            if part.tool_name == "scout_web_search" and isinstance(content, list):
                content = [
                    {
                        "title": str(item.get("title") or "")[:100],
                        "url": str(item.get("url") or ""),
                    }
                    for item in content[:3]
                    if isinstance(item, dict)
                ]
            elif part.tool_name == "scout_web_fetch" and isinstance(content, dict):
                content = {
                    "url": content.get("url"),
                    "status": content.get("status"),
                    "content": compact_fetched_content(
                        str(content.get("content") or "")
                    ),
                    "truncated": content.get("truncated"),
                }
            values.append({"tool": part.tool_name, "result": content})
    serialized = json.dumps(values[-3:], ensure_ascii=False, separators=(",", ":"))
    return serialized[:max_chars]


def _retry_text(messages: Iterable[Any]) -> str:
    values: list[str] = []
    for message in messages:
        for part in getattr(message, "parts", ()):
            if isinstance(part, RetryPromptPart):
                content = str(part.content)
                json_start = content.find("{")
                if json_start >= 0:
                    try:
                        payload = json.loads(content[json_start:])
                    except json.JSONDecodeError:
                        payload = None
                    if isinstance(payload, dict):
                        repairs = payload.get("repair_instructions")
                        if isinstance(repairs, list):
                            compact = "；".join(
                                str(item).strip()
                                for item in repairs[:3]
                                if str(item).strip()
                            )
                            if compact:
                                values.append(compact)
                                continue
                values.append(re.sub(r"\s+", " ", content).strip())
    return " | ".join(values[-2:])[:360]


def render_hazard_state_instruction(evidence: str) -> str:
    states = dict(
        re.findall(
            r"([\u4e00-\u9fff]{2,12}):(active|inactive)",
            evidence,
            re.IGNORECASE,
        )
    )
    if not states:
        return ""
    rendered = "；".join(
        f"{hazard}={'生效' if state.casefold() == 'active' else '未生效'}"
        for hazard, state in states.items()
    )
    return f"逐項狀態必須保持：{rendered}。不得省略或顛倒。"


def _completed_tool_names(messages: Iterable[Any]) -> set[str]:
    return {
        part.tool_name
        for message in messages
        for part in getattr(message, "parts", ())
        if isinstance(part, ToolReturnPart)
    }


def _completed_tool_count(messages: Iterable[Any], tool_name: str) -> int:
    return sum(
        isinstance(part, ToolReturnPart) and part.tool_name == tool_name
        for message in messages
        for part in getattr(message, "parts", ())
    )


def _search_results_from_messages(
    messages: Iterable[Any],
    spec: ResearchQuestionSpec,
) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for message in messages:
        for part in getattr(message, "parts", ()):
            if not isinstance(part, ToolReturnPart):
                continue
            candidates: list[dict[str, Any]] = []
            if part.tool_name == "scout_web_search" and isinstance(part.content, list):
                candidates = [item for item in part.content if isinstance(item, dict)]
            elif part.tool_name == "scout_web_fetch" and isinstance(part.content, dict):
                base_url = str(part.content.get("url") or "")
                content = str(part.content.get("content") or "")
                if base_url and content:
                    candidates = extract_research_links(
                        content,
                        base_url=base_url,
                        focus_terms=[
                            *spec.topic_terms,
                            *spec.required_evidence_literals,
                            *spec.required_answer_literals,
                        ],
                        allowed_domains=spec.allowed_domains,
                    )
            for item in candidates:
                if not isinstance(item, dict):
                    continue
                url = str(item.get("url") or "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                results.append(
                    {
                        "title": str(item.get("title") or ""),
                        "url": url,
                        "snippet": str(item.get("snippet") or ""),
                    }
                )
    return results


def _ordered_source_refs(
    compact_evidence: str,
    *,
    fallback_refs: Iterable[str],
) -> tuple[str, ...]:
    ordered: list[str] = []
    try:
        payload = json.loads(compact_evidence)
    except json.JSONDecodeError:
        payload = []
    if isinstance(payload, list):
        for card in payload:
            if not isinstance(card, dict):
                continue
            refs = card.get("source_refs")
            if not isinstance(refs, list):
                continue
            ordered.extend(str(ref) for ref in refs if str(ref).strip())
    ordered.extend(str(ref) for ref in fallback_refs if str(ref).strip())
    return tuple(dict.fromkeys(ordered))


def _structured_datasets_from_messages(messages: Iterable[Any]) -> set[str]:
    datasets: set[str] = set()
    for message in messages:
        for part in getattr(message, "parts", ()):
            if not isinstance(part, ToolReturnPart):
                continue
            if part.tool_name != "scout_cwa_structured_fetch":
                continue
            if isinstance(part.content, dict):
                dataset_id = str(part.content.get("dataset_id") or "")
                if dataset_id:
                    datasets.add(dataset_id)
    return datasets


def _trace_from_messages(messages: Iterable[Any]) -> dict[str, Any]:
    calls: list[dict[str, Any]] = []
    returns: list[dict[str, Any]] = []
    retries: list[str] = []
    response_count = 0
    for message in messages:
        if isinstance(message, ModelResponse):
            response_count += 1
        for part in getattr(message, "parts", ()):
            if isinstance(part, ToolCallPart):
                calls.append(
                    {
                        "tool_name": part.tool_name,
                        "args": part.args,
                        "tool_call_id": part.tool_call_id,
                    }
                )
            elif isinstance(part, ToolReturnPart):
                returns.append(
                    {
                        "tool_name": part.tool_name,
                        "content": part.content,
                        "tool_call_id": part.tool_call_id,
                    }
                )
            elif isinstance(part, RetryPromptPart):
                retries.append(str(part.content))
    return {
        "model_request_count": response_count,
        "tool_call_count": len(calls),
        "tool_return_count": len(returns),
        "tool_calls": calls,
        "tool_returns": returns,
        "retry_prompts": retries,
        "source_urls": _extract_urls([item["content"] for item in returns]),
    }


def build_research_search_query(
    spec: ResearchQuestionSpec,
    *,
    missing_source_groups: dict[str, list[str]],
) -> str:
    group_hints = {
        "weather": "天氣 警特報",
        "trail": "步道 公告",
        "trail_status": "步道 管制公告",
        "road": "道路 交通管制",
    }
    values = list(spec.topic_terms[:3])
    literal_hints = (
        spec.required_answer_literals or spec.required_evidence_literals
    )
    for literal in literal_hints:
        if len(values) >= 4:
            break
        values.append(literal)
    if missing_source_groups:
        first_group = next(iter(missing_source_groups))
        if hint := group_hints.get(first_group):
            values.extend(hint.split())
    if not values:
        values.append(spec.question[:60])
    if spec.freshness_required:
        values.append("最新")
    if not spec.allowed_domains:
        values.append("官方")
    return " ".join(dict.fromkeys(value.strip() for value in values if value.strip()))


def build_hailo_function_model(
    *,
    endpoint: str,
    model: str,
    case: dict[str, Any],
    current_date: str,
    timeout_seconds: float,
    raw_rounds: list[dict[str, Any]],
) -> FunctionModel:
    spec = ResearchQuestionSpec.model_validate(case)
    attempted_fetch_urls: set[str] = set()
    attempted_cwa_datasets: set[str] = set()
    deterministic_dispatch_count = 0
    search_dispatch_count = 0

    async def hailo_tool_model(messages: list[Any], info: AgentInfo) -> ModelResponse:
        nonlocal deterministic_dispatch_count, search_dispatch_count
        del info
        retry = _retry_text(messages)
        trace = _trace_from_messages(messages)
        bundle = build_web_evidence_bundle(trace, spec)
        evidence = compact_evidence_for_synthesis(
            bundle,
            focus_terms=[
                *spec.topic_terms,
                *spec.required_evidence_literals,
                *spec.required_answer_literals,
            ],
        )
        search_results = _search_results_from_messages(messages, spec)
        missing_source_groups = {
            group: domains
            for group, domains in spec.source_groups.items()
            if group not in bundle.source_groups_found
        }
        active_missing_source_groups = dict(
            list(missing_source_groups.items())[:1]
        )
        selector_spec = (
            spec.model_copy(update={"source_groups": active_missing_source_groups})
            if active_missing_source_groups
            else spec
        )
        selected = select_research_url(
            search_results,
            selector_spec,
            attempted_urls=attempted_fetch_urls,
        )
        literals_in_evidence = all(
            value.casefold()
            in " ".join(
                str(card.key_values.get("visible_text") or "")
                for card in bundle.cards
            ).casefold()
            for value in spec.required_evidence_literals
        )
        evidence_ready = (
            not bundle.missing_fields
            and not missing_source_groups
            and literals_in_evidence
        )
        completed_datasets = _structured_datasets_from_messages(messages)
        missing_structured_datasets = [
            dataset_id
            for dataset_id in spec.structured_datasets
            if dataset_id not in completed_datasets
            and dataset_id not in attempted_cwa_datasets
        ]
        if not spec.requires_search:
            required_action: dict[str, Any] | None = None
        elif missing_structured_datasets:
            required_action = {
                "action": "tool",
                "tool_name": "scout_cwa_structured_fetch",
                "args": {
                    "dataset_id": missing_structured_datasets[0],
                    "query": spec.question,
                },
            }
        elif (
            not evidence_ready
            and not search_results
            and search_dispatch_count < 3
        ):
            required_action = {
                "action": "tool",
                "tool_name": "scout_web_search",
                "args": {
                    "query": build_research_search_query(
                        spec,
                        missing_source_groups=active_missing_source_groups,
                    )
                },
            }
        elif spec.requires_fetch and not evidence_ready and selected is not None:
            required_action = {
                "action": "tool",
                "tool_name": "scout_web_fetch",
                "args": {"url": str(selected["url"])},
            }
        elif not evidence_ready and search_dispatch_count < 3:
            required_action = {
                "action": "tool",
                "tool_name": "scout_web_search",
                "args": {
                    "query": build_research_search_query(
                        spec,
                        missing_source_groups=active_missing_source_groups,
                    )
                },
            }
        else:
            required_action = None
        if required_action is not None:
            deterministic_dispatch_count += 1
            tool_name = str(required_action["tool_name"])
            args = dict(required_action["args"])
            if tool_name == "scout_web_fetch":
                attempted_url = str(args.get("url") or "")
                if attempted_url:
                    attempted_fetch_urls.add(attempted_url)
            elif tool_name == "scout_cwa_structured_fetch":
                attempted_dataset = str(args.get("dataset_id") or "")
                if attempted_dataset:
                    attempted_cwa_datasets.add(attempted_dataset)
            elif tool_name == "scout_web_search":
                search_dispatch_count += 1
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name,
                        args,
                        tool_call_id=f"scout_dispatch_{deterministic_dispatch_count}",
                    )
                ],
                model_name="scout-deterministic-tool-planner",
            )
        field_labels = {
            "status": "狀態",
            "url": "完整來源網址",
            "date": "日期",
            "precipitation": "降雨資訊",
            "wind": "風勢資訊",
            "time": "時間",
            "time_range": "時間範圍",
            "notice": "公告重點",
            "control": "管制資訊",
            "position": "位置要領",
            "dataset_code": "資料集代碼",
            "update_frequency": "更新頻率",
            "warning_types": "警特報類型",
            "magnitude": "地震規模",
            "level": "等級",
            "manual_review_reason": "人工審查原因",
            "safety_boundary": "安全邊界",
        }
        required_fields_text = "、".join(
            field_labels.get(field.partition(":")[0], field.partition(":")[0])
            for field in spec.required_fields
        )
        required_literals_text = "、".join(spec.required_answer_literals)
        hazard_state_instruction = render_hazard_state_instruction(evidence)
        field_list_requested = question_requests_field_list(spec.question)
        hazard_instructions = (
            [
                "證據中的 active 代表生效，inactive 代表未生效；"
                "不同狀態必須逐項保留。",
                hazard_state_instruction,
            ]
            if hazard_state_instruction
            else []
        )
        prompt = pack_hailo_prompt(
            prefix_lines=[
                "你是 Scout 的繁體中文回答器。只輸出一到三句繁體中文最終答案，"
                "不要重述問題、規則、工具或證據。",
                f"目前日期是 {current_date}。",
            ],
            evidence=evidence,
            suffix_lines=[
                f"使用者問題是：{spec.question}",
                "只能使用上方已驗證證據。",
                *hazard_instructions,
                (
                    f"答案需要涵蓋：{required_fields_text}。"
                    if required_fields_text
                    else ""
                ),
                (
                    f"答案必須逐字包含：{required_literals_text}。"
                    if required_literals_text
                    else ""
                ),
                (
                    "前次回答需要修正：" + retry
                    if retry
                    else ""
                ),
                "直接回答問題，再補必要細節，最後逐字附上證據中的完整來源網址。"
                "只回答使用者問到的項目，不加入無關樣本時間、網格尺寸或旁支資料。",
                (
                    "使用者已要求欄位清單，可以用簡短的「欄位：內容」逐行回答；"
                    "不得輸出 JSON、CSV、URL 占位符或證據沒有的事實。"
                    if field_list_requested
                    else "不得輸出 JSON、CSV、Markdown 欄位清單、URL 占位符或"
                    "證據沒有的事實。"
                ),
                "網路資料只是候選證據，不可直接當成現場安全命令。",
            ],
        )
        started = time.perf_counter()
        source_refs = _ordered_source_refs(
            evidence,
            fallback_refs=(
                source_ref
                for card in bundle.cards
                for source_ref in card.source_refs
            ),
        )
        minimum_source_refs = (
            min(len(source_refs), max(1, len(spec.source_groups)))
            if spec.requires_search and source_refs
            else 0
        )
        try:
            raw, metadata = await asyncio.to_thread(
                _hailo_chat,
                endpoint=endpoint,
                model=model,
                prompt=prompt,
                timeout_seconds=timeout_seconds,
                required_source_refs=source_refs,
                minimum_source_refs=minimum_source_refs,
                required_answer_literals=tuple(spec.required_answer_literals),
                required_topic_terms=tuple(spec.topic_terms),
            )
        except Exception as exc:
            raw_rounds.append(
                {
                    "call_index": len(raw_rounds) + 1,
                    "raw": "",
                    "parsed_action": None,
                    "latency_ms": round((time.perf_counter() - started) * 1000),
                    "metadata": {},
                    "retry_prompt": retry or None,
                    "prompt_chars": len(prompt),
                    "prompt": prompt,
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                }
            )
            raise
        user_text = raw.replace("<SCOUT_DONE>", "").strip()
        action = parse_model_action(user_text)
        raw_rounds.append(
            {
                "call_index": len(raw_rounds) + 1,
                "raw": raw,
                "parsed_action": action,
                "latency_ms": round((time.perf_counter() - started) * 1000),
                "metadata": metadata,
                "retry_prompt": retry or None,
                "prompt_chars": len(prompt),
                "prompt": prompt,
            }
        )
        if action is None:
            user_text = naturalize_labeled_answer(
                user_text,
                allow_field_list=field_list_requested,
            )
            user_text = compact_repetitive_answer(
                user_text,
                required_literals=tuple(spec.required_answer_literals),
                topic_terms=tuple(spec.topic_terms),
                allow_field_list=field_list_requested,
            )
            return ModelResponse(
                parts=[
                    TextPart(
                        attach_verified_source_refs(
                            user_text,
                            source_refs=source_refs,
                            minimum_source_refs=minimum_source_refs,
                        )
                        or "本地模型沒有產生可解析的回答。"
                    )
                ],
                model_name=f"hailo:{model}",
            )
        if action["action"] == "tool":
            tool_name = str(action.get("tool_name") or "")
            args = action.get("args") if isinstance(action.get("args"), dict) else {}
            if tool_name == "scout_web_fetch":
                attempted_url = str(args.get("url") or "")
                if attempted_url:
                    attempted_fetch_urls.add(attempted_url)
            elif tool_name == "scout_cwa_structured_fetch":
                attempted_dataset = str(args.get("dataset_id") or "")
                if attempted_dataset:
                    attempted_cwa_datasets.add(attempted_dataset)
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name,
                        args,
                        tool_call_id=f"hailo_{len(raw_rounds)}",
                    )
                ],
                model_name=f"hailo:{model}",
            )
        return ModelResponse(
            parts=[
                TextPart(
                    attach_verified_source_refs(
                        compact_repetitive_answer(
                            naturalize_labeled_answer(
                                str(action.get("answer") or "")
                                .replace("<SCOUT_DONE>", "")
                                .strip()
                                or user_text,
                                allow_field_list=field_list_requested,
                            ),
                            required_literals=tuple(spec.required_answer_literals),
                            topic_terms=tuple(spec.topic_terms),
                            allow_field_list=field_list_requested,
                        ),
                        source_refs=source_refs,
                        minimum_source_refs=minimum_source_refs,
                    )
                )
            ],
            model_name=f"hailo:{model}",
        )

    return FunctionModel(hailo_tool_model, model_name=f"hailo-tool-agent:{model}")


def _all_messages(result: Any) -> list[Any]:
    value = getattr(result, "all_messages", None)
    return list(value() if callable(value) else value or [])


def _extract_urls(value: Any) -> list[str]:
    urls: list[str] = []
    if isinstance(value, str):
        urls.extend(re.findall(r"https?://[^\s\]\[()<>\"']+", value))
    elif isinstance(value, dict):
        for item in value.values():
            urls.extend(_extract_urls(item))
    elif isinstance(value, list | tuple):
        for item in value:
            urls.extend(_extract_urls(item))
    return list(dict.fromkeys(url.rstrip(".,，。;；") for url in urls))


def attach_verified_source_refs(
    answer: str,
    *,
    source_refs: tuple[str, ...],
    minimum_source_refs: int,
) -> str:
    """Attach deterministic provenance instead of asking a small model to copy URLs."""

    cleaned = answer.strip()
    if not cleaned or minimum_source_refs <= 0:
        return cleaned
    cited = set(_extract_urls(cleaned))
    missing = [source for source in source_refs if source not in cited]
    needed = max(0, minimum_source_refs - len(cited.intersection(source_refs)))
    if needed <= 0:
        return cleaned
    return f"{cleaned} 來源：{'；'.join(missing[:needed])}"


def trace_result(result: Any) -> dict[str, Any]:
    calls: list[dict[str, Any]] = []
    returns: list[dict[str, Any]] = []
    retries: list[str] = []
    for message in _all_messages(result):
        for part in getattr(message, "parts", ()):
            if isinstance(part, ToolCallPart):
                calls.append(
                    {
                        "tool_name": part.tool_name,
                        "args": part.args,
                        "tool_call_id": part.tool_call_id,
                    }
                )
            elif isinstance(part, ToolReturnPart):
                returns.append(
                    {
                        "tool_name": part.tool_name,
                        "content": part.content,
                        "tool_call_id": part.tool_call_id,
                    }
                )
            elif isinstance(part, RetryPromptPart):
                retries.append(str(part.content))
    source_urls = _extract_urls([item["content"] for item in returns])
    return {
        "model_request_count": sum(
            isinstance(message, ModelResponse) for message in _all_messages(result)
        ),
        "tool_call_count": len(calls),
        "tool_return_count": len(returns),
        "tool_calls": calls,
        "tool_returns": returns,
        "retry_prompts": retries,
        "source_urls": source_urls,
    }


def trace_from_tool_events(
    tool_events: list[dict[str, Any]],
    *,
    raw_rounds: list[dict[str, Any]],
) -> dict[str, Any]:
    calls = [
        {
            "tool_name": item["tool_name"],
            "args": item["args"],
            "tool_call_id": f"recorded_{index}",
        }
        for index, item in enumerate(tool_events, start=1)
    ]
    returns = [
        {
            "tool_name": item["tool_name"],
            "content": item["result"],
            "tool_call_id": f"recorded_{index}",
        }
        for index, item in enumerate(tool_events, start=1)
    ]
    return {
        "model_request_count": len(raw_rounds),
        "tool_call_count": len(calls),
        "tool_return_count": len(returns),
        "tool_calls": calls,
        "tool_returns": returns,
        "retry_prompts": [
            str(item["retry_prompt"])
            for item in raw_rounds
            if item.get("retry_prompt")
        ],
        "source_urls": _extract_urls([item["result"] for item in tool_events]),
    }


def _domain_allowed(url: str, domains: list[str]) -> bool:
    hostname = (urlsplit(url).hostname or "").lower()
    return any(hostname == item or hostname.endswith(f".{item}") for item in domains)


def score_case(
    case: dict[str, Any],
    *,
    answer: str,
    trace: dict[str, Any],
    current_date: str | None = None,
) -> dict[str, Any]:
    return evaluate_web_research(
        case,
        answer=answer,
        trace=trace,
        current_date=(
            current_date or datetime.now(UTC).date().isoformat()
        ),
        max_calls=MAX_CALLS,
    )


def build_structured_answer_projection(
    case: dict[str, Any],
    trace: dict[str, Any],
) -> str | None:
    """Project bounded structured metadata when a small model ignores known fields."""

    spec = ResearchQuestionSpec.model_validate(case)
    required = {field.partition(":")[0] for field in spec.required_fields}
    if not spec.structured_datasets or not {
        "dataset_code",
        "time_range",
        "update_frequency",
        "url",
    } <= required:
        return None
    for item in trace.get("tool_returns") or []:
        if not isinstance(item, dict) or item.get("tool_name") != (
            "scout_cwa_structured_fetch"
        ):
            continue
        payload = item.get("content")
        if not isinstance(payload, dict) or payload.get("status") != 200:
            continue
        metadata = payload.get("dataset_metadata")
        if not isinstance(metadata, dict):
            continue
        dataset_id = str(payload.get("dataset_id") or "").strip()
        description = str(metadata.get("description") or "").strip()
        time_range = str(metadata.get("time_range") or "").strip()
        update_frequency = str(metadata.get("update_frequency") or "").strip()
        source_url = str(
            payload.get("source_url") or payload.get("url") or ""
        ).strip()
        if (
            not dataset_id
            or dataset_id not in spec.structured_datasets
            or not description
            or not time_range
            or not update_frequency
            or not source_url
            or not _domain_allowed(source_url, list(spec.allowed_domains))
        ):
            continue
        dataset_kind = description.removeprefix(time_range).strip() or description
        return (
            f"{dataset_id} 是{dataset_kind}，時間範圍為{time_range}，"
            f"更新頻率為{update_frequency}。來源：{source_url}"
        )
    return None


def build_verifier_repair_instructions(
    grading: dict[str, Any],
) -> list[str]:
    reasons = set(grading.get("hard_fail_reasons") or [])
    checks = grading.get("checks") if isinstance(grading.get("checks"), dict) else {}
    instructions: list[str] = []
    if "unsupported_absence_claim" in reasons:
        instructions.append(
            "不得聲稱無、沒有、皆開放或可正常通行；只陳述證據卡明載的公告，"
            "否則說明官方頁不足以證明不存在。"
        )
    if reasons & {"contradictory_status_claim", "incomplete_hazard_statuses"}:
        instructions.append(
            "若 query_summary 含 requested_hazard_states，必須逐項回答每個災種；"
            "不可把 active 與 inactive 合併成全部沒有。"
        )
    if "prompt_leak" in reasons:
        instructions.append(
            "只輸出答案，不得重複今天日期、問題、規則、工具或停止標記。"
        )
    if "unsupported_factual_tokens" in reasons:
        instructions.append(
            "刪除或逐字修正證據卡未出現的日期、時間、數字、代碼與狀態。"
        )
    if reasons & {
        "machine_structured_user_answer",
        "machine_delimited_user_answer",
        "machine_labeled_user_answer",
    }:
        instructions.append(
            "改用完整繁體中文句子，不可輸出 JSON、逗號欄位或多行標籤清單。"
        )
    missing_fields = [str(value) for value in grading.get("missing_answer_fields") or []]
    if missing_fields:
        instructions.append("答案必須補齊欄位：" + "、".join(missing_fields) + "。")
    missing_literals = [
        str(value) for value in grading.get("missing_answer_literals") or []
    ]
    if missing_literals:
        instructions.append("答案必須逐字包含：" + "、".join(missing_literals) + "。")
    if checks.get("freshness_stated") is False:
        instructions.append("答案要明寫查詢日期，日期只能取自今天日期或證據卡 fetched_at。")
    if checks.get("citation_grounded") is False:
        instructions.append("答案末尾加入證據卡 source_refs 內的完整網址，不可寫 URL 占位符。")
    if checks.get("topic_coverage") is False:
        instructions.append("答案要直接提及問題中的地點與主題，不可改寫成泛稱資料。")
    if checks.get("semantic_claim_supported") is False:
        instructions.append("狀態結論只能逐字依據 query_summary，不可從歷史敘述推測。")
    if reasons & {"missing_required_evidence", "incomplete_source_join"}:
        instructions.append(
            "若證據或來源群組仍不足，明確說明缺哪一項，不得自行補寫結論。"
        )
    return instructions or ["只保留可由已驗證證據卡直接支持的內容。"]


def regrade_results(
    corpus: dict[str, Any],
    results: Iterable[dict[str, Any]],
    *,
    current_date: str,
) -> list[dict[str, Any]]:
    """Re-evaluate recorded traces without issuing model or network calls."""

    cases_by_id = {
        str(case["case_id"]): case for case in corpus.get("cases") or []
    }
    regraded: list[dict[str, Any]] = []
    for item in results:
        case_id = str(item.get("case_id") or "")
        if case_id not in cases_by_id:
            raise ValueError(f"recorded result has unknown case_id: {case_id}")
        answer = str(item.get("answer") or "")
        trace = item.get("trace") if isinstance(item.get("trace"), dict) else {}
        regraded.append(
            {
                **item,
                "grading": score_case(
                    cases_by_id[case_id],
                    answer=answer,
                    trace=trace,
                    current_date=current_date,
                ),
                "regraded_without_model_or_network": True,
            }
        )
    return regraded


async def run_case(case: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    raw_rounds: list[dict[str, Any]] = []
    tool_events: list[dict[str, Any]] = []
    allowed_domains = [str(item) for item in case["allowed_domains"]]
    structured_datasets = [str(item) for item in case.get("structured_datasets") or []]
    search = build_local_web_search(
        allowed_domains=allowed_domains or None,
        max_uses=MAX_CALLS,
        max_results=5,
        timeout_seconds=args.web_timeout_seconds,
    )
    fetch = build_local_web_fetch(
        allowed_domains=allowed_domains or None,
        max_uses=MAX_CALLS,
        max_content_tokens=None,
        timeout_seconds=args.web_timeout_seconds,
    )
    cwa_fetch = (
        build_local_cwa_research_fetch(
            allowed_dataset_ids=structured_datasets,
            max_uses=MAX_CALLS,
            timeout_seconds=args.web_timeout_seconds,
        )
        if structured_datasets
        else None
    )

    async def traced_search(
        ctx: RunContext[Any],
        query: str,
    ) -> list[dict[str, str]]:
        event: dict[str, Any] = {
            "tool_name": "scout_web_search",
            "args": {"query": query},
        }
        try:
            result = await search(ctx, query)
        except Exception as exc:
            event["result"] = {
                "status": "error",
                "error_type": type(exc).__name__,
                "message": str(exc)[:240],
            }
            tool_events.append(event)
            raise
        event["result"] = result
        tool_events.append(event)
        return result

    async def traced_fetch(
        ctx: RunContext[Any],
        url: str,
    ) -> dict[str, Any]:
        event: dict[str, Any] = {
            "tool_name": "scout_web_fetch",
            "args": {"url": url},
        }
        try:
            result = await fetch(ctx, url)
        except Exception as exc:
            event["result"] = {
                "status": "error",
                "error_type": type(exc).__name__,
                "message": str(exc)[:240],
            }
            tool_events.append(event)
            raise
        event["result"] = result
        tool_events.append(event)
        return result

    async def traced_cwa_fetch(
        ctx: RunContext[Any],
        dataset_id: str,
        query: str = "",
    ) -> dict[str, Any]:
        if cwa_fetch is None:
            raise ModelRetry("No CWA structured dataset is configured for this case")
        event: dict[str, Any] = {
            "tool_name": "scout_cwa_structured_fetch",
            "args": {"dataset_id": dataset_id, "query": query},
        }
        try:
            result = await cwa_fetch(ctx, dataset_id, query)
        except Exception as exc:
            event["result"] = {
                "status": "error",
                "error_type": type(exc).__name__,
                "message": str(exc)[:240],
            }
            tool_events.append(event)
            raise
        event["result"] = result
        tool_events.append(event)
        return result

    model = build_hailo_function_model(
        endpoint=args.endpoint,
        model=args.model,
        case=case,
        current_date=args.current_date,
        timeout_seconds=args.model_timeout_seconds,
        raw_rounds=raw_rounds,
    )
    agent_tools = [
        Tool(
            traced_search,
            name="scout_web_search",
            description="搜尋公開網頁並回傳標題、網址與摘要。",
            max_retries=MAX_CALLS,
        ),
        Tool(
            traced_fetch,
            name="scout_web_fetch",
            description="讀取 deterministic selector 指定的官方搜尋結果網址。",
            max_retries=MAX_CALLS,
        ),
    ]
    if cwa_fetch is not None:
        agent_tools.insert(
            0,
            Tool(
                traced_cwa_fetch,
                name="scout_cwa_structured_fetch",
                description=(
                    "以 server-side credential 讀取已核准的 CWA 結構化資料集；"
                    "回傳不含 Authorization 的 candidate evidence。"
                ),
                max_retries=MAX_CALLS,
            ),
        )
    agent = Agent(
        model,
        tools=agent_tools,
        system_prompt=(
            "Scout web research is read-only candidate evidence. The model must select "
            "and call tools through Pydantic AI. Deterministic runtime selects source "
            "URLs, extracts evidence, and verifies the final answer."
        ),
        **pydantic_agent_runtime_kwargs(),
    )
    verification_failures: dict[str, int] = {}
    deterministic_projection: dict[str, Any] | None = None

    @agent.output_validator
    async def validate_grounded_output(
        ctx: RunContext[Any],
        output: str,
    ) -> str:
        nonlocal deterministic_projection
        del ctx
        candidate_trace = trace_from_tool_events(
            tool_events,
            raw_rounds=raw_rounds,
        )
        projected_answer = build_structured_answer_projection(case, candidate_trace)
        if projected_answer is not None:
            projected_grading = score_case(
                case,
                answer=projected_answer,
                trace=candidate_trace,
                current_date=args.current_date,
            )
            if projected_grading["passed"]:
                deterministic_projection = {
                    "used": True,
                    "kind": "structured_dataset_metadata",
                }
                return projected_answer
        grading = score_case(
            case,
            answer=str(output),
            trace=candidate_trace,
            current_date=args.current_date,
        )
        if grading["passed"]:
            return output
        failure_payload = {
            "repair_instructions": build_verifier_repair_instructions(grading),
            "hard_fail_reasons": grading["hard_fail_reasons"],
            "missing_evidence_fields": grading["missing_evidence_fields"],
            "missing_answer_fields": grading["missing_answer_fields"],
            "missing_answer_literals": grading["missing_answer_literals"],
        }
        signature = json.dumps(
            failure_payload,
            ensure_ascii=False,
            sort_keys=True,
        )
        failure_count = verification_failures.get(signature, 0) + 1
        verification_failures[signature] = failure_count
        raise ModelRetry(
            "Deterministic answer verification failed: "
            + json.dumps(failure_payload, ensure_ascii=False, separators=(",", ":"))
        )
    started = time.perf_counter()
    error: dict[str, str] | None = None
    answer = ""
    trace: dict[str, Any] = {
        "model_request_count": 0,
        "tool_call_count": 0,
        "tool_return_count": 0,
        "tool_calls": [],
        "tool_returns": [],
        "retry_prompts": [],
        "source_urls": [],
    }
    try:
        result = await agent.run(
            str(case["question"]),
            usage_limits=UsageLimits(
                request_limit=MAX_CALLS,
                tool_calls_limit=MAX_CALLS,
            ),
        )
        answer = str(result.output).strip()
        trace = trace_from_tool_events(tool_events, raw_rounds=raw_rounds)
    except Exception as exc:  # noqa: BLE001 - eval records provider/tool failures.
        error = {"type": type(exc).__name__, "message": str(exc)[:1_000]}
        trace = trace_from_tool_events(tool_events, raw_rounds=raw_rounds)
    latency_ms = round((time.perf_counter() - started) * 1000)
    grading = score_case(
        case,
        answer=answer,
        trace=trace,
        current_date=args.current_date,
    )
    return {
        "case_id": case["case_id"],
        "question": case["question"],
        "allowed_domains": allowed_domains,
        "answer": answer,
        "error": error,
        "latency_ms": latency_ms,
        "trace": trace,
        "raw_model_rounds": raw_rounds,
        "deterministic_projection": deterministic_projection,
        "grading": grading,
    }


def package_versions() -> dict[str, str]:
    packages = ("pydantic-ai-slim", "pydantic-evals", "pydantic-graph", "ddgs")
    values: dict[str, str] = {}
    for package in packages:
        try:
            values[package] = version(package)
        except PackageNotFoundError:
            values[package] = "not-installed"
    return values


def write_summary(run_dir: Path, report: dict[str, Any]) -> None:
    summary = report["summary"]
    lines = [
        f"# {report['run_id']}",
        "",
        f"- phase: `{report['phase']}`",
        f"- runtime: `{report['runtime']}`",
        f"- model: `{report['model']}`",
        f"- Pydantic AI: `{report['package_versions']['pydantic-ai-slim']}`",
        f"- passed: `{summary['passed']}/{summary['case_count']}`",
        f"- mean score: `{summary['mean_score']}`",
        f"- mean transport score: `{summary['mean_transport_score']}`",
        f"- mean evidence sufficiency score: `{summary['mean_evidence_score']}`",
        f"- mean semantic correctness score: `{summary['mean_semantic_score']}`",
        f"- hard-fail cases: `{summary['hard_fail_cases']}`",
        f"- web search selected: `{summary['search_selected']}/{summary['search_required']}`",
        f"- web fetch selected: `{summary['fetch_selected']}/{summary['fetch_required']}`",
        f"- grounded citations: `{summary['grounded_citations']}/{summary['search_required']}`",
        f"- official source: `{summary['official_source']}/{summary['search_required']}`",
        f"- median latency ms: `{summary['median_latency_ms']}`",
        "",
        "## Cases",
        "",
        "| ID | Total | Transport | Evidence | Semantic | Search | Fetch | Citation | Hard fail | Latency | Answer |",
        "|---|---:|---:|---:|---:|---|---|---|---|---:|---|",
    ]
    for item in report["results"]:
        checks = item["grading"]["checks"]
        answer = item["answer"].replace("|", "\\|").replace("\n", " ")[:180]
        lines.append(
            "| {id} | {score} | {transport} | {evidence} | {semantic} | {search} | {fetch} | {citation} | {hard_fail} | {latency} | {answer} |".format(
                id=item["case_id"],
                score=item["grading"]["score"],
                transport=item["grading"]["layers"]["transport"]["score"],
                evidence=item["grading"]["layers"]["evidence_sufficiency"]["score"],
                semantic=item["grading"]["layers"]["semantic_correctness"]["score"],
                search="PASS" if checks["search_selection"] else "FAIL",
                fetch="PASS" if checks["fetch_selection"] else "FAIL",
                citation="PASS" if checks["citation_grounded"] else "FAIL",
                hard_fail=",".join(item["grading"]["hard_fail_reasons"]) or "-",
                latency=item["latency_ms"],
                answer=answer or (item["error"] or {}).get("type", "empty"),
            )
        )
    (run_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def summarize_results(
    corpus: dict[str, Any],
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    scores = [item["grading"]["score"] for item in results]
    transport_scores = [
        item["grading"]["layers"]["transport"]["score"] for item in results
    ]
    evidence_scores = [
        item["grading"]["layers"]["evidence_sufficiency"]["score"]
        for item in results
    ]
    semantic_scores = [
        item["grading"]["layers"]["semantic_correctness"]["score"]
        for item in results
    ]
    latencies = sorted(int(item.get("latency_ms") or 0) for item in results)
    cases_by_id = {str(item["case_id"]): item for item in corpus["cases"]}
    evaluated_cases = [cases_by_id[str(item["case_id"])] for item in results]
    search_required = sum(bool(item["requires_search"]) for item in evaluated_cases)
    fetch_required = sum(bool(item["requires_fetch"]) for item in evaluated_cases)
    return {
        "case_count": len(results),
        "passed": sum(item["grading"]["passed"] for item in results),
        "mean_score": round(sum(scores) / len(scores), 2) if scores else 0,
        "mean_transport_score": (
            round(sum(transport_scores) / len(transport_scores), 2)
            if transport_scores
            else 0
        ),
        "mean_evidence_score": (
            round(sum(evidence_scores) / len(evidence_scores), 2)
            if evidence_scores
            else 0
        ),
        "mean_semantic_score": (
            round(sum(semantic_scores) / len(semantic_scores), 2)
            if semantic_scores
            else 0
        ),
        "hard_fail_cases": sum(
            bool(item["grading"]["hard_fail_reasons"]) for item in results
        ),
        "search_required": search_required,
        "search_selected": sum(
            item["grading"]["checks"]["search_selection"]
            for item in results
            if item["case_id"] != "WEB-020"
        ),
        "fetch_required": fetch_required,
        "fetch_selected": sum(
            item["grading"]["checks"]["fetch_selection"]
            for item in results
            if item["case_id"] != "WEB-020"
        ),
        "grounded_citations": sum(
            item["grading"]["checks"]["citation_grounded"]
            for item in results
            if item["case_id"] != "WEB-020"
        ),
        "official_source": sum(
            item["grading"]["checks"]["official_source"]
            for item in results
            if item["case_id"] != "WEB-020"
        ),
        "model_requests": sum(
            int(item["trace"].get("model_request_count") or 0) for item in results
        ),
        "tool_calls": sum(
            int(item["trace"].get("tool_call_count") or 0) for item in results
        ),
        "median_latency_ms": latencies[len(latencies) // 2] if latencies else 0,
        "errors": sum(item.get("error") is not None for item in results),
    }


def load_recorded_results(path: Path) -> list[dict[str, Any]]:
    candidate = path
    if candidate.is_dir():
        if (candidate / "results.jsonl").exists():
            candidate = candidate / "results.jsonl"
        elif (candidate / "report.json").exists():
            candidate = candidate / "report.json"
    if not candidate.exists():
        raise ValueError(f"recorded eval artifact does not exist: {candidate}")
    if candidate.suffix == ".jsonl":
        return [
            json.loads(line)
            for line in candidate.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    payload = json.loads(candidate.read_text(encoding="utf-8"))
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        raise TypeError("recorded eval JSON must contain a results list")
    return [item for item in results if isinstance(item, dict)]


def run_regrade(args: argparse.Namespace) -> Path:
    corpus = load_corpus(args.corpus)
    recorded = load_recorded_results(args.regrade_from)
    if args.case_id:
        wanted = set(args.case_id)
        recorded = [item for item in recorded if item.get("case_id") in wanted]
    if args.max_cases is not None:
        recorded = recorded[: args.max_cases]
    results = regrade_results(
        corpus,
        recorded,
        current_date=args.current_date,
    )
    run_id = args.run_id or (
        "pydantic_232_local_web_regrade_"
        + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    )
    run_dir = args.output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    with (run_dir / "results.jsonl").open("w", encoding="utf-8") as output:
        for result in results:
            output.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
    report = {
        "schema_version": corpus["schema_version"],
        "run_id": run_id,
        "phase": "offline_regrade",
        "runtime": "recorded_trace_no_model_no_network",
        "source_artifact": str(args.regrade_from),
        "model": "recorded",
        "started_at": datetime.now(UTC).isoformat(),
        "package_versions": package_versions(),
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "hardware_control_allowed": False,
        },
        "summary": summarize_results(corpus, results),
        "results": results,
    }
    (run_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_summary(run_dir, report)
    return run_dir


async def run_eval(args: argparse.Namespace) -> Path:
    corpus = load_corpus(args.corpus)
    selected = list(corpus["cases"])
    if args.case_id:
        wanted = set(args.case_id)
        selected = [item for item in selected if item["case_id"] in wanted]
    if args.max_cases is not None:
        selected = selected[: args.max_cases]
    run_id = args.run_id or (
        f"pydantic_232_local_web_{args.phase}_"
        f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    )
    run_dir = args.output_root / run_id
    results_path = run_dir / "results.jsonl"
    results: list[dict[str, Any]] = []
    if args.resume:
        if not results_path.exists():
            raise ValueError(f"cannot resume missing results file: {results_path}")
        results = [
            json.loads(line)
            for line in results_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        completed_ids = {str(item["case_id"]) for item in results}
        selected = [item for item in selected if item["case_id"] not in completed_ids]
    else:
        run_dir.mkdir(parents=True, exist_ok=False)
    for index, case in enumerate(selected, start=len(results) + 1):
        result = await run_case(case, args)
        results.append(result)
        with results_path.open("a", encoding="utf-8") as output:
            output.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
        print(
            json.dumps(
                {
                    "index": index,
                    "case_id": result["case_id"],
                    "score": result["grading"]["score"],
                    "tool_calls": result["trace"]["tool_call_count"],
                    "latency_ms": result["latency_ms"],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    summary = summarize_results(corpus, results)
    report = {
        "schema_version": corpus["schema_version"],
        "run_id": run_id,
        "phase": args.phase,
        "runtime": "physical_ai_hat_plus_2_hailo10h",
        "endpoint": args.endpoint,
        "model": args.model,
        "started_at": datetime.now(UTC).isoformat(),
        "package_versions": package_versions(),
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "hardware_control_allowed": False,
        },
        "summary": summary,
        "results": results,
    }
    (run_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_summary(run_dir, report)
    return run_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Scout's 20-question Pydantic AI 2.32 local web eval on AI HAT+2."
    )
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--run-id")
    parser.add_argument("--phase", default="candidate")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--current-date", default=datetime.now(UTC).date().isoformat())
    parser.add_argument("--model-timeout-seconds", type=float, default=120.0)
    parser.add_argument("--web-timeout-seconds", type=float, default=30.0)
    parser.add_argument("--max-cases", type=int)
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--regrade-from",
        type=Path,
        help="Regrade a recorded report/results.jsonl without model or network calls.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.max_cases is not None and args.max_cases <= 0:
        raise SystemExit("--max-cases must be positive")
    if args.regrade_from and args.resume:
        raise SystemExit("--regrade-from cannot be combined with --resume")
    run_dir = (
        run_regrade(args)
        if args.regrade_from
        else asyncio.run(run_eval(args))
    )
    print(json.dumps({"status": "completed", "run_dir": str(run_dir)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
