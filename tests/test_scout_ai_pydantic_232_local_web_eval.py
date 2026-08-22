from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest
from pydantic_ai.messages import ModelRequest, RetryPromptPart, ToolReturnPart

from scout.agents.web_research_quality import ResearchQuestionSpec
from tools.scout_ai_pydantic_232_local_web_eval import (
    MAX_HAILO_PROMPT_CHARS,
    MAX_HAILO_INPUT_TOKENS,
    _hailo_chat,
    _ordered_source_refs,
    _retry_text,
    _search_results_from_messages,
    build_verifier_repair_instructions,
    build_research_search_query,
    build_structured_answer_projection,
    compact_fetched_content,
    compact_repetitive_answer,
    estimate_hailo_input_tokens,
    load_corpus,
    naturalize_labeled_answer,
    normalize_hailo_chat_content,
    parse_model_action,
    pack_hailo_prompt,
    regrade_results,
    render_hazard_state_instruction,
    run_case,
    score_case,
    validate_hailo_prompt,
)

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "docs" / "evals" / "scout-pydantic-ai-232-local-web-20-corpus.json"


def test_local_web_corpus_has_twenty_unique_cases() -> None:
    payload = load_corpus(CORPUS)

    assert len(payload["cases"]) == 20
    assert payload["cases"][0]["case_id"] == "WEB-001"
    assert payload["cases"][-1]["case_id"] == "WEB-020"
    assert sum(case["requires_search"] for case in payload["cases"]) == 19


def test_retry_text_keeps_repair_instructions_without_verifier_json() -> None:
    message = ModelRequest(
        parts=[
            RetryPromptPart(
                "Deterministic answer verification failed: "
                + json.dumps(
                    {
                        "repair_instructions": [
                            "不要重述問題。",
                            "依 active 與 inactive 逐項回答。",
                        ],
                        "hard_fail_reasons": ["prompt_leak"],
                    },
                    ensure_ascii=False,
                )
            )
        ]
    )

    value = _retry_text([message])

    assert value == "不要重述問題。；依 active 與 inactive 逐項回答。"
    assert "hard_fail_reasons" not in value


def test_hazard_state_instruction_projects_tool_evidence_to_plain_language() -> None:
    instruction = render_hazard_state_instruction(
        "查詢狀態=active；災種狀態=大雨:inactive,豪雨:active"
    )

    assert instruction == "逐項狀態必須保持：大雨=未生效；豪雨=生效。不得省略或顛倒。"


def test_research_search_query_uses_compact_topic_terms() -> None:
    corpus = load_corpus(CORPUS)
    case = next(item for item in corpus["cases"] if item["case_id"] == "WEB-008")

    query = build_research_search_query(
        ResearchQuestionSpec.model_validate(case),
        missing_source_groups={},
    )

    assert "天池山莊" in query
    assert "能高越嶺" in query
    assert "請查林業保育署官方網站" not in query
    assert len(query) < 80


def test_research_search_query_keeps_disambiguating_emergency_literal() -> None:
    spec = ResearchQuestionSpec.model_validate(
        {
            "case_id": "WEB-012",
            "question": "山域事故打119時最少應提供哪些資訊？",
            "allowed_domains": ["nfa.gov.tw"],
            "topic_terms": ["119", "報案要領", "位置"],
            "required_evidence_literals": [
                "119",
                "案發地點",
                "相對位置",
                "座標",
                "原因",
            ],
            "required_answer_literals": [
                "案發地點",
                "相對位置",
                "座標",
                "原因",
            ],
        }
    )

    query = build_research_search_query(spec, missing_source_groups={})

    assert query == "119 報案要領 位置 案發地點"


def test_ordered_source_refs_follows_compact_evidence_relevance_order() -> None:
    generic_url = "https://www.nfa.gov.tw/cht/?code=list&ids=66"
    relevant_url = "https://www.nfa.gov.tw/cht/index.php?code=list&ids=68"
    evidence = json.dumps(
        [
            {"source_refs": [relevant_url], "evidence": "報案要領"},
            {"source_refs": [generic_url], "evidence": "119、112"},
        ]
    )

    assert _ordered_source_refs(evidence, fallback_refs=[generic_url]) == (
        relevant_url,
        generic_url,
    )


def test_search_results_include_relevant_links_discovered_in_fetched_page() -> None:
    spec = ResearchQuestionSpec.model_validate(
        {
            "case_id": "WEB-012",
            "question": "山域事故打119時最少應提供哪些資訊？",
            "allowed_domains": ["nfa.gov.tw"],
            "topic_terms": ["119", "報案要領", "位置"],
            "required_evidence_literals": ["案發地點", "相對位置", "座標"],
        }
    )
    message = ModelRequest(
        parts=[
            ToolReturnPart(
                tool_name="scout_web_search",
                tool_call_id="search-1",
                content=[
                    {
                        "title": "119、112",
                        "url": "https://www.nfa.gov.tw/cht/?code=list&ids=66",
                        "snippet": "119、112使用時機",
                    }
                ],
            ),
            ToolReturnPart(
                tool_name="scout_web_fetch",
                tool_call_id="fetch-1",
                content={
                    "url": "https://www.nfa.gov.tw/cht/?code=list&ids=66",
                    "content_type": "text/html",
                    "content": (
                        '<a href="index.php?code=list&amp;ids=68">報案要領</a>'
                    ),
                },
            ),
        ]
    )

    results = _search_results_from_messages([message], spec)

    assert [item["url"] for item in results] == [
        "https://www.nfa.gov.tw/cht/?code=list&ids=66",
        "https://www.nfa.gov.tw/cht/index.php?code=list&ids=68",
    ]


def test_verifier_repair_instructions_explain_absence_and_field_failures() -> None:
    instructions = build_verifier_repair_instructions(
        {
            "hard_fail_reasons": [
                "unsupported_absence_claim",
                "incomplete_answer",
                "incomplete_hazard_statuses",
            ],
            "missing_answer_fields": ["date", "status", "url"],
            "missing_answer_literals": [],
        }
    )

    assert any("不得聲稱" in value for value in instructions)
    assert any("date、status、url" in value for value in instructions)
    assert any("逐項回答每個災種" in value for value in instructions)


def test_verifier_repair_instructions_cover_non_hard_semantic_failures() -> None:
    instructions = build_verifier_repair_instructions(
        {
            "checks": {
                "freshness_stated": False,
                "citation_grounded": False,
                "topic_coverage": False,
            },
            "hard_fail_reasons": [],
            "missing_answer_fields": [],
            "missing_answer_literals": [],
        }
    )

    assert any("查詢日期" in value for value in instructions)
    assert any("完整網址" in value for value in instructions)
    assert any("問題中的地點" in value for value in instructions)


def test_parse_model_action_accepts_reasoning_and_json_fence() -> None:
    action = parse_model_action(
        '<think>先查官方來源</think>\n```json\n'
        '{"action":"tool","tool_name":"scout_web_search",'
        '"args":{"query":"中央氣象署 南投 特報"}}\n```'
    )

    assert action == {
        "action": "tool",
        "tool_name": "scout_web_search",
        "args": {"query": "中央氣象署 南投 特報"},
    }


def test_normalize_hailo_chat_content_flattens_control_characters() -> None:
    assert normalize_hailo_chat_content("first\nsecond\tthird") == (
        "first second third"
    )


def test_naturalize_labeled_answer_preserves_verified_field_values() -> None:
    answer = (
        "目前查到的公告如下：\n\n"
        "- **日期**：2026-08-10\n"
        "- **狀態**：減少開放115年10月份部分床位/營地\n"
        "- **完整來源網址**：https://tconline.forest.gov.tw/"
    )

    normalized = naturalize_labeled_answer(answer, allow_field_list=False)

    assert normalized == (
        "公告日期為2026-08-10，最新公告內容為「減少開放115年10月份部分床位/營地」。"
        "來源：https://tconline.forest.gov.tw/"
    )


def test_naturalize_labeled_answer_keeps_explicit_field_list() -> None:
    answer = "欄位：案發地點\n欄位：相對位置\n欄位：座標\n欄位：原因"

    assert naturalize_labeled_answer(answer, allow_field_list=True) == answer


def test_compact_repetitive_answer_keeps_minimal_complete_sentence() -> None:
    source = "https://opendata.cwa.gov.tw/dataset/forecast/F-C0041-001"
    answer = (
        "F-C0041-001 是定量降水預報，時間範圍為一段樣本時間，每6小時更新。\n"
        "F-C0041-001 代表定量降水預報，時間範圍為0-6小時，每6小時更新。\n"
        "F-C0041-001 代表定量降水預報，時間範圍為0-6小時，每6小時更新。"
        f"來源：{source}"
    )

    compact = compact_repetitive_answer(
        answer,
        required_literals=("F-C0041-001", "定量降水預報", "0-6小時", "每6小時"),
        topic_terms=("F-C0041-001", "降水"),
        allow_field_list=False,
    )

    assert compact == (
        "F-C0041-001 代表定量降水預報，時間範圍為0-6小時，每6小時更新。"
    )


def test_hailo_prompt_guard_rejects_external_context_overflow() -> None:
    validate_hailo_prompt("x" * (MAX_HAILO_INPUT_TOKENS * 4))

    with pytest.raises(ValueError, match="input token guard"):
        validate_hailo_prompt("中" * (MAX_HAILO_INPUT_TOKENS + 1))

    with pytest.raises(ValueError, match="hardware context guard"):
        validate_hailo_prompt("x" * (MAX_HAILO_PROMPT_CHARS + 1))


def test_hailo_prompt_pack_keeps_input_within_token_envelope() -> None:
    prompt = pack_hailo_prompt(
        prefix_lines=["問題:" + "中" * 200],
        evidence="證" * 2_000,
        suffix_lines=["回答規則:完整句子。"],
    )

    assert estimate_hailo_input_tokens(prompt) <= MAX_HAILO_INPUT_TOKENS
    assert "問題:" in prompt
    assert "已驗證證據卡:" in prompt
    assert "回答規則:完整句子。" in prompt


def test_hailo_chat_retries_empty_stream_with_non_stream_response(
    monkeypatch,
) -> None:
    requests: list[dict[str, object]] = []

    class FakeResponse:
        def __init__(self, *, body: bytes = b"", lines: list[bytes] | None = None):
            self.body = body
            self.lines = lines or []

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def __iter__(self):
            return iter(self.lines)

        def read(self, size: int = -1) -> bytes:
            return self.body if size < 0 else self.body[:size]

    def fake_urlopen(request: object, *, timeout: float) -> FakeResponse:
        del timeout
        payload = json.loads(request.data.decode("utf-8"))  # type: ignore[attr-defined]
        requests.append(payload)
        if payload["stream"]:
            return FakeResponse(lines=[])
        return FakeResponse(
            body=json.dumps(
                {
                    "message": {
                        "content": '{"action":"answer","answer":"正常回答。"}'
                    },
                    "done_reason": "stop",
                    "eval_count": 8,
                }
            ).encode("utf-8")
        )

    monkeypatch.setattr(
        "tools.scout_ai_pydantic_232_local_web_eval.urlopen",
        fake_urlopen,
    )

    raw, metadata = _hailo_chat(
        endpoint="http://fixture.invalid/api/chat",
        model="qwen3:1.7b",
        prompt="請回答。",
        timeout_seconds=5.0,
    )

    assert raw == '{"action":"answer","answer":"正常回答。"}'
    assert [item["stream"] for item in requests] == [True, False]
    assert requests[0]["options"]["stop"][0] == "\n"
    assert metadata["stream_fallback"] is True


def test_hailo_chat_closes_stream_after_complete_action_json(monkeypatch) -> None:
    class FakeResponse:
        consumed = 0

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def __iter__(self):
            lines = [
                json.dumps(
                    {
                        "message": {
                            "content": '{"action":"answer","answer":"完成。"}'
                        },
                        "done": False,
                    }
                ).encode("utf-8")
                + b"\n",
                json.dumps(
                    {
                        "message": {"content": "should not be consumed"},
                        "done": True,
                        "done_reason": "stop",
                    }
                ).encode("utf-8")
                + b"\n",
            ]
            for line in lines:
                type(self).consumed += 1
                yield line

    monkeypatch.setattr(
        "tools.scout_ai_pydantic_232_local_web_eval.urlopen",
        lambda request, *, timeout: FakeResponse(),
    )

    raw, metadata = _hailo_chat(
        endpoint="http://fixture.invalid/api/chat",
        model="qwen3:1.7b",
        prompt="請回答。",
        timeout_seconds=5.0,
    )

    assert raw == '{"action":"answer","answer":"完成。"}'
    assert metadata["semantic_json_stop"] is True
    assert metadata["stream_response_count"] == 1
    assert metadata["semantic_stream_closed_early"] is True
    assert FakeResponse.consumed == 1


def test_hailo_chat_closes_plain_answer_after_complete_required_source(
    monkeypatch,
) -> None:
    source = "https://opendata.cwa.gov.tw/dataset/warning/W-C0033-001"

    class FakeResponse:
        consumed = 0

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def __iter__(self):
            for content in (
                "南投縣目前有豪雨特報。來源：https://opendata.cwa.gov.tw/",
                "dataset/warning/W-C0033-001",
                "不應繼續輸出 prompt。",
            ):
                type(self).consumed += 1
                yield (
                    json.dumps(
                        {
                            "message": {"content": content},
                            "done": False,
                        }
                    ).encode("utf-8")
                    + b"\n"
                )

    monkeypatch.setattr(
        "tools.scout_ai_pydantic_232_local_web_eval.urlopen",
        lambda request, *, timeout: FakeResponse(),
    )

    raw, metadata = _hailo_chat(
        endpoint="http://fixture.invalid/api/chat",
        model="qwen3:1.7b",
        prompt="請回答。",
        timeout_seconds=5.0,
        required_source_refs=(source,),
        minimum_source_refs=1,
    )

    assert raw.endswith(source)
    assert metadata["semantic_stop_reason"] == "required_source_refs_complete"
    assert metadata["semantic_stream_closed_early"] is True
    assert FakeResponse.consumed == 2


def test_hailo_chat_closes_after_answer_contract_before_source(monkeypatch) -> None:
    class FakeResponse:
        consumed = 0

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def __iter__(self):
            for content in (
                "F-C0041-001 是定量降水預報，時間範圍為0-6小時，",
                "每6小時更新。",
                "不應繼續重複輸出。",
            ):
                type(self).consumed += 1
                yield (
                    json.dumps(
                        {"message": {"content": content}, "done": False}
                    ).encode("utf-8")
                    + b"\n"
                )

    monkeypatch.setattr(
        "tools.scout_ai_pydantic_232_local_web_eval.urlopen",
        lambda request, *, timeout: FakeResponse(),
    )

    raw, metadata = _hailo_chat(
        endpoint="http://fixture.invalid/api/chat",
        model="qwen3:1.7b",
        prompt="請回答。",
        timeout_seconds=5.0,
        required_answer_literals=(
            "F-C0041-001",
            "定量降水預報",
            "0-6小時",
            "每6小時",
        ),
        required_topic_terms=("F-C0041-001", "降水"),
    )

    assert raw.endswith("每6小時更新。")
    assert metadata["semantic_stop_reason"] == "required_answer_contract_complete"
    assert metadata["semantic_stream_closed_early"] is True
    assert FakeResponse.consumed == 2


def test_hailo_chat_retries_stream_http_500_with_non_stream_response(
    monkeypatch,
) -> None:
    requests: list[dict[str, object]] = []

    class FakeResponse:
        def __init__(self, body: bytes):
            self.body = body

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def read(self, size: int = -1) -> bytes:
            return self.body if size < 0 else self.body[:size]

    def fake_urlopen(request: object, *, timeout: float) -> FakeResponse:
        del timeout
        payload = json.loads(request.data.decode("utf-8"))  # type: ignore[attr-defined]
        requests.append(payload)
        if payload["stream"]:
            raise HTTPError(
                "http://fixture.invalid/api/chat",
                500,
                "Internal Server Error",
                {},
                io.BytesIO(b"read failed"),
            )
        return FakeResponse(
            json.dumps(
                {
                    "message": {
                        "content": '{"action":"answer","answer":"正常回答。"}'
                    },
                    "done_reason": "stop",
                }
            ).encode("utf-8")
        )

    monkeypatch.setattr(
        "tools.scout_ai_pydantic_232_local_web_eval.urlopen",
        fake_urlopen,
    )

    raw, metadata = _hailo_chat(
        endpoint="http://fixture.invalid/api/chat",
        model="qwen3:1.7b",
        prompt="請回答。",
        timeout_seconds=5.0,
    )

    assert raw == '{"action":"answer","answer":"正常回答。"}'
    assert [item["stream"] for item in requests] == [True, False]
    assert metadata["semantic_stop_reason"] == "stream_http_500_non_stream_retry"


def test_compact_fetched_content_removes_markup_and_scripts() -> None:
    assert compact_fetched_content(
        "<html><style>hidden</style><body><h1>豪雨特報</h1>"
        "<script>ignored()</script><p>南投縣</p></body></html>"
    ) == "豪雨特報 南投縣"


def test_score_case_requires_actual_tool_source_and_citation() -> None:
    case = load_corpus(CORPUS)["cases"][0]
    source_url = "https://www.cwa.gov.tw/V8/C/W/Warning.html"
    trace = {
        "model_request_count": 3,
        "tool_call_count": 2,
        "tool_calls": [
            {"tool_name": "scout_web_search"},
            {"tool_name": "scout_web_fetch"},
        ],
        "tool_returns": [
            {
                "tool_name": "scout_web_fetch",
                "content": {
                    "url": source_url,
                    "status": 200,
                    "content": "南投縣豪雨特報目前生效中，更新日期2026-08-20",
                    "fetched_at": "2026-08-20T04:00:00Z",
                },
            }
        ],
        "source_urls": [source_url],
    }

    grading = score_case(
        case,
        answer=f"截至2026-08-20，南投縣豪雨特報目前生效中。{source_url}",
        trace=trace,
        current_date="2026-08-20",
    )

    assert grading["score"] == 100
    assert grading["passed"] is True
    assert grading["checks"]["citation_grounded"] is True
    assert grading["layers"]["transport"]["passed"] is True
    assert grading["layers"]["evidence_sufficiency"]["passed"] is True
    assert grading["layers"]["semantic_correctness"]["passed"] is True


def test_structured_cwa_projection_uses_verified_dataset_metadata() -> None:
    case = next(
        item
        for item in load_corpus(CORPUS)["cases"]
        if item["case_id"] == "WEB-013"
    )
    trace = {
        "tool_returns": [
            {
                "tool_name": "scout_cwa_structured_fetch",
                "content": {
                    "status": 200,
                    "dataset_id": "F-C0041-001",
                    "dataset_metadata": {
                        "description": "0-6小時定量降水預報",
                        "time_range": "0-6小時",
                        "update_frequency": "每6小時",
                    },
                    "source_url": (
                        "https://opendata.cwa.gov.tw/dataset/forecast/F-C0041-001"
                    ),
                },
            }
        ]
    }

    answer = build_structured_answer_projection(case, trace)

    assert answer == (
        "F-C0041-001 是定量降水預報，時間範圍為0-6小時，"
        "更新頻率為每6小時。來源："
        "https://opendata.cwa.gov.tw/dataset/forecast/F-C0041-001"
    )


def test_score_case_rejects_model_only_answer_without_web_calls() -> None:
    case = load_corpus(CORPUS)["cases"][0]
    trace = {
        "model_request_count": 1,
        "tool_call_count": 0,
        "tool_calls": [],
        "tool_returns": [],
        "source_urls": [],
    }

    grading = score_case(case, answer="目前沒有豪雨特報。", trace=trace)

    assert grading["passed"] is False
    assert grading["checks"]["search_selection"] is False
    assert grading["checks"]["official_source"] is False
    assert grading["checks"]["citation_grounded"] is False


def test_score_case_does_not_pass_fresh_claim_from_search_snippet_only() -> None:
    case = load_corpus(CORPUS)["cases"][0]
    source_url = "https://www.cwa.gov.tw/V8/C/P/Warning/W26.html"
    trace = {
        "model_request_count": 2,
        "tool_call_count": 1,
        "tool_calls": [{"tool_name": "scout_web_search"}],
        "tool_returns": [
            {
                "tool_name": "scout_web_search",
                "content": [{"url": source_url, "snippet": "南投縣豪雨特報"}],
            }
        ],
        "source_urls": [source_url],
    }

    grading = score_case(
        case,
        answer=f"截至2026-08-20，南投縣無豪雨特報。{source_url}",
        trace=trace,
    )

    assert grading["passed"] is False
    assert grading["checks"]["fetch_selection"] is False
    assert grading["checks"]["semantic_claim_supported"] is False
    assert grading["layers"]["transport"]["passed"] is False
    assert grading["layers"]["evidence_sufficiency"]["passed"] is False


def test_regrade_results_rejects_recorded_false_positive() -> None:
    corpus = load_corpus(CORPUS)
    case = next(item for item in corpus["cases"] if item["case_id"] == "WEB-004")
    source_url = "https://www.cwa.gov.tw/V8/C/W/Astronomy.html"
    recorded = {
        "case_id": "WEB-004",
        "question": case["question"],
        "answer": f"2026-08-21 日出06:00、日沒18:00。{source_url}",
        "trace": {
            "model_request_count": 3,
            "tool_call_count": 2,
            "tool_return_count": 2,
            "tool_calls": [
                {"tool_name": "scout_web_search"},
                {"tool_name": "scout_web_fetch"},
            ],
            "tool_returns": [
                {
                    "tool_name": "scout_web_fetch",
                    "content": {
                        "url": source_url,
                        "status": 200,
                        "content": "南投縣 日出日沒資料 日期2026-08-21",
                        "fetched_at": "2026-08-20T04:00:00Z",
                    },
                }
            ],
            "source_urls": [source_url],
        },
    }

    regraded = regrade_results(
        corpus,
        [recorded],
        current_date="2026-08-20",
    )

    assert regraded[0]["grading"]["passed"] is False
    assert "unsupported_factual_tokens" in regraded[0]["grading"]["hard_fail_reasons"]


def test_boundary_answer_remains_valid_without_web_tools() -> None:
    corpus = load_corpus(CORPUS)
    case = next(item for item in corpus["cases"] if item["case_id"] == "WEB-020")
    grading = score_case(
        case,
        answer="不可以，網路資料不能直接成為 Scout runtime safety truth。",
        trace={
            "model_request_count": 1,
            "tool_call_count": 0,
            "tool_return_count": 0,
            "tool_calls": [],
            "tool_returns": [],
            "source_urls": [],
        },
        current_date="2026-08-20",
    )

    assert grading["passed"] is True


def test_run_case_uses_pydantic_tools_selector_and_verifier(
    monkeypatch,
    tmp_path: Path,
) -> None:
    generic_url = "https://www.taroko.gov.tw/ch"
    status_url = "https://www.taroko.gov.tw/ch/announcement/route-status"
    fetched_urls: list[str] = []

    def fake_search(
        query: str,
        *,
        allowed_domains: list[str] | None,
        blocked_domains: list[str] | None,
        max_results: int,
        timeout_seconds: float,
    ) -> list[dict[str, str]]:
        del query, allowed_domains, blocked_domains, max_results, timeout_seconds
        return [
            {
                "title": "太魯閣國家公園首頁",
                "url": generic_url,
                "snippet": "園區介紹",
            },
            {
                "title": "奇萊步道管制公告",
                "url": status_url,
                "snippet": "奇萊路線目前管制狀態",
            },
        ]

    def fake_fetch(
        url: str,
        *,
        allowed_domains: list[str] | None,
        blocked_domains: list[str] | None,
        max_content_tokens: int | None,
        timeout_seconds: float | None,
    ) -> dict[str, object]:
        del allowed_domains, blocked_domains, max_content_tokens, timeout_seconds
        fetched_urls.append(url)
        content = (
            "奇萊步道管制公告：目前管制中，公告日期2026-08-20"
            if url == status_url
            else "太魯閣國家公園園區介紹"
        )
        return {
            "url": url,
            "status": 200,
            "content_type": "text/html",
            "content": content,
            "fetched_at": "2026-08-20T04:00:00Z",
            "content_hash": "sha256:fixture",
            "truncated": False,
        }

    def fake_hailo_chat(
        *,
        endpoint: str,
        model: str,
        prompt: str,
        timeout_seconds: float,
        required_source_refs: tuple[str, ...],
        minimum_source_refs: int,
        required_answer_literals: tuple[str, ...],
        required_topic_terms: tuple[str, ...],
    ) -> tuple[str, dict[str, object]]:
        del endpoint, model, timeout_seconds, required_answer_literals
        marker = "原樣輸出這個 JSON object:"
        assert marker not in prompt
        assert "只輸出一行JSON" not in prompt
        assert "只輸出一到三句繁體中文最終答案" in prompt
        assert "active 代表生效，inactive 代表未生效" not in prompt
        assert "今天日期:" not in prompt
        assert "可用工具:" not in prompt
        assert "來源：URL" not in prompt
        assert "<SCOUT_DONE>" not in prompt
        assert "答案需要涵蓋：日期、狀態、完整來源網址。" in prompt
        assert required_source_refs == (status_url,)
        assert minimum_source_refs == 1
        assert required_topic_terms == ("奇萊", "管制")
        return (
            "截至2026-08-20，奇萊管制公告顯示目前管制中。",
            {},
        )

    monkeypatch.setattr("scout.agents.local_web_search._search", fake_search)
    monkeypatch.setattr("scout.agents.local_web_fetch._fetch_url", fake_fetch)
    monkeypatch.setattr(
        "tools.scout_ai_pydantic_232_local_web_eval._hailo_chat",
        fake_hailo_chat,
    )
    case = {
        "case_id": "WEB-FIXTURE",
        "question": "請查奇萊步道目前管制公告。",
        "allowed_domains": ["taroko.gov.tw"],
        "requires_search": True,
        "requires_fetch": True,
        "freshness_required": True,
        "topic_terms": ["奇萊", "管制"],
        "required_fields": ["date", "status", "url"],
        "source_groups": {"trail_status": ["taroko.gov.tw"]},
        "absence_sensitive": True,
    }
    args = SimpleNamespace(
        endpoint="http://fixture.invalid/api/chat",
        model="qwen3:1.7b",
        current_date="2026-08-20",
        model_timeout_seconds=5.0,
        web_timeout_seconds=5.0,
        output_root=tmp_path,
    )

    result = asyncio.run(run_case(case, args))

    assert result["error"] is None
    assert result["grading"]["passed"] is True, json.dumps(
        result["grading"], ensure_ascii=False
    )
    tool_names = [call["tool_name"] for call in result["trace"]["tool_calls"]]
    assert tool_names[0] == "scout_web_search"
    assert "scout_web_fetch" in tool_names
    assert status_url in fetched_urls
    assert result["trace"]["model_request_count"] == 1
    assert len(result["raw_model_rounds"]) == 1
    assert result["answer"].endswith(f"來源：{status_url}")
    assert "<SCOUT_DONE>" not in result["answer"]


def test_run_case_prefers_verified_structured_projection(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source_url = "https://opendata.cwa.gov.tw/dataset/forecast/F-C0041-001"

    def fake_cwa_builder(**kwargs: object):
        del kwargs

        async def fake_cwa_fetch(
            ctx: object,
            dataset_id: str,
            query: str = "",
        ) -> dict[str, object]:
            del ctx, query
            return {
                "status": 200,
                "dataset_id": dataset_id,
                "dataset_metadata": {
                    "description": "0-6小時定量降水預報",
                    "time_range": "0-6小時",
                    "update_frequency": "每6小時",
                },
                "content": "F-C0041-001 | 0-6小時定量降水預報 | 每6小時",
                "source_url": source_url,
                "url": source_url,
                "fetched_at": "2026-08-20T04:00:00Z",
                "content_hash": "sha256:fixture",
            }

        return fake_cwa_fetch

    def fake_hailo_chat(**kwargs: object) -> tuple[str, dict[str, object]]:
        del kwargs
        return (
            "F-C0041-001 是定量降水預報，樣本時間為2026-07-12，"
            f"每6小時更新。來源：{source_url}",
            {},
        )

    monkeypatch.setattr(
        "tools.scout_ai_pydantic_232_local_web_eval.build_local_cwa_research_fetch",
        fake_cwa_builder,
    )
    monkeypatch.setattr(
        "tools.scout_ai_pydantic_232_local_web_eval._hailo_chat",
        fake_hailo_chat,
    )
    case = next(
        item
        for item in load_corpus(CORPUS)["cases"]
        if item["case_id"] == "WEB-013"
    )
    args = SimpleNamespace(
        endpoint="http://fixture.invalid/api/chat",
        model="qwen3:1.7b",
        current_date="2026-08-20",
        model_timeout_seconds=5.0,
        web_timeout_seconds=5.0,
        output_root=tmp_path,
    )

    result = asyncio.run(run_case(case, args))

    assert result["error"] is None
    assert result["grading"]["passed"] is True
    assert result["deterministic_projection"] == {
        "used": True,
        "kind": "structured_dataset_metadata",
    }
    assert result["answer"] == (
        "F-C0041-001 是定量降水預報，時間範圍為0-6小時，"
        f"更新頻率為每6小時。來源：{source_url}"
    )


def test_run_case_records_failed_search_and_stops_repeating_it(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from ddgs.exceptions import TimeoutException

    def unavailable_search(*args: object, **kwargs: object) -> list[dict[str, str]]:
        del args, kwargs
        raise TimeoutException("fixture timeout")

    def fake_hailo_chat(
        *,
        endpoint: str,
        model: str,
        prompt: str,
        timeout_seconds: float,
        required_source_refs: tuple[str, ...],
        minimum_source_refs: int,
        required_answer_literals: tuple[str, ...],
        required_topic_terms: tuple[str, ...],
    ) -> tuple[str, dict[str, object]]:
        del (
            endpoint,
            model,
            timeout_seconds,
            required_source_refs,
            minimum_source_refs,
            required_answer_literals,
            required_topic_terms,
        )
        assert "原樣輸出這個 JSON object:" not in prompt
        return (
            json.dumps(
                {
                    "action": "answer",
                    "answer": "官方搜尋目前無法取得，因此沒有足夠證據回答。",
                },
                ensure_ascii=False,
            ),
            {},
        )

    monkeypatch.setattr("scout.agents.local_web_search._search", unavailable_search)
    monkeypatch.setattr(
        "tools.scout_ai_pydantic_232_local_web_eval._hailo_chat",
        fake_hailo_chat,
    )
    case = {
        "case_id": "WEB-SEARCH-FAILURE",
        "question": "請查官方步道公告。",
        "allowed_domains": ["forest.gov.tw"],
        "requires_search": True,
        "requires_fetch": True,
        "freshness_required": True,
        "topic_terms": ["步道", "公告"],
        "required_fields": ["date", "status", "url"],
        "source_groups": {"trail_status": ["forest.gov.tw"]},
        "absence_sensitive": True,
    }
    args = SimpleNamespace(
        endpoint="http://fixture.invalid/api/chat",
        model="qwen3:1.7b",
        current_date="2026-08-20",
        model_timeout_seconds=5.0,
        web_timeout_seconds=5.0,
        output_root=tmp_path,
    )

    result = asyncio.run(run_case(case, args))

    assert result["error"]["type"] == "UsageLimitExceeded"
    assert result["trace"]["tool_call_count"] == 3
    assert 1 <= result["trace"]["model_request_count"] <= 7
    assert all(
        item["content"]["status"] == "error"
        for item in result["trace"]["tool_returns"]
    )
