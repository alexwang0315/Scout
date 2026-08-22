"""Deterministic evidence and answer quality gates for Scout web research."""

from __future__ import annotations

import hashlib
import html.parser
import json
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from enum import StrEnum
from typing import Any
from urllib.parse import urljoin, urlsplit

from pydantic import Field, model_validator

from scout.schemas.agent_runtime import EvidenceCard, EvidenceRecord
from scout.schemas.base import NonEmptyStr, SchemaModel

_URL_PATTERN = re.compile(r"https?://[^\s\]\[()<>\"']+")
_DATASET_PATTERN = re.compile(r"\b[A-Z]-[A-Z]\d{4}-\d{3}\b", re.IGNORECASE)
_DATE_PATTERN = re.compile(
    r"(?<!\d)\d{4}[-/]\d{1,2}[-/]\d{1,2}(?!\d)"
    r"|(?<!\d)\d{4}年\d{1,2}月\d{1,2}日"
)
_TIME_PATTERN = re.compile(r"(?<!\d)(?:[01]?\d|2[0-3]):[0-5]\d(?!\d)")
_MEASUREMENT_PATTERN = re.compile(
    r"(?<![\w.])\d+(?:\.\d+)?\s*(?:mm|cm|km|m/s|km/h|°C|℃|%)(?!\w)",
    re.IGNORECASE,
)
_MAGNITUDE_PATTERN = re.compile(r"(?:規模|芮氏)\s*[:：]?\s*(\d+(?:\.\d+)?)")
_ABSENCE_CLAIM_PATTERN = re.compile(
    r"(?:沒有|並無|目前無|未發布|未發佈|未生效|無生效|無封閉|無管制|"
    r"無(?!法)[^，。；\n]{0,12}(?:封閉|管制|施工|警報|特報)|正常通行|可正常通行)"
)
_BARE_ABSENCE_PATTERN = re.compile(r"^\s*(?:無|沒有)(?:\s|[，。；:：])")
_ABSENCE_SCOPE_PATTERN = re.compile(
    r"(?:沒有|並無|目前無|未發布|未發佈|未生效|無生效|無(?!法))"
)
_HAZARD_STATE_PATTERN = re.compile(
    r"([\u4e00-\u9fff]{2,12}):(active|inactive)",
    re.IGNORECASE,
)
_EXPLICIT_ABSENCE_PATTERN = re.compile(
    r"(?:目前|現正|當前|查詢結果|官方狀態).{0,24}"
    r"(?:沒有|並無|無生效|未發布|未生效|無封閉|無管制|0\s*(?:筆|件|項))"
    r"|(?:沒有|並無|無生效|未發布|未生效|無封閉|無管制).{0,24}"
    r"(?:目前|現正|當前|警報|特報|封閉|管制)",
)
_PLACEHOLDER_PATTERNS = (
    re.compile(r"繁中短答.*(?:日期|實際URL)", re.IGNORECASE),
    re.compile(r"一句繁中短答", re.IGNORECASE),
    re.compile(r"<[^>]*(?:answer|url|date|value)[^>]*>", re.IGNORECASE),
)
_PROMPT_LEAK_PATTERNS = (
    re.compile(r'"action"\s*:\s*"(?:tool|answer)"', re.IGNORECASE),
    re.compile(r'"tool_name"\s*:', re.IGNORECASE),
    re.compile(r"(?:工具證據|重試提示|下一步只能|可用工具|允許網域)\s*[:：]"),
    re.compile(r"(?:^|\n)\s*(?:今天日期|問題|必要答案欄位)\s*[:：]"),
    re.compile(r"<SCOUT_DONE>", re.IGNORECASE),
)
_FIELD_LIST_REQUEST_PATTERN = re.compile(
    r"(?:列成|列為|列出|整理成).{0,10}(?:欄位|清單)"
    r"|(?:欄位|清單).{0,10}(?:列出|呈現|整理)",
)


class EvidenceAvailability(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"


class ResearchQuestionSpec(SchemaModel):
    """Machine-readable evidence contract for one web research question."""

    case_id: NonEmptyStr
    question: NonEmptyStr
    allowed_domains: list[NonEmptyStr] = Field(default_factory=list)
    requires_search: bool = True
    requires_fetch: bool = True
    freshness_required: bool = False
    topic_terms: list[NonEmptyStr] = Field(default_factory=list)
    required_fields: list[NonEmptyStr] = Field(default_factory=list)
    required_evidence_literals: list[NonEmptyStr] = Field(default_factory=list)
    required_answer_literals: list[NonEmptyStr] = Field(default_factory=list)
    source_groups: dict[NonEmptyStr, list[NonEmptyStr]] = Field(default_factory=dict)
    absence_sensitive: bool = False
    structured_datasets: list[NonEmptyStr] = Field(default_factory=list)

    @model_validator(mode="after")
    def default_source_group(self) -> ResearchQuestionSpec:
        if self.requires_fetch and self.allowed_domains and not self.source_groups:
            return self.model_copy(
                update={"source_groups": {"official": list(self.allowed_domains)}}
            )
        return self


class ClaimEvidenceLink(SchemaModel):
    """One factual answer token linked back to fetched evidence."""

    claim_type: NonEmptyStr
    claim_value: NonEmptyStr
    normalized_value: NonEmptyStr
    source_refs: list[NonEmptyStr] = Field(default_factory=list)
    supported: bool
    reason: NonEmptyStr


class WebEvidenceBundle(SchemaModel):
    """Verified model-facing evidence assembled from WebFetch returns."""

    cards: list[EvidenceCard] = Field(default_factory=list)
    source_groups_found: list[NonEmptyStr] = Field(default_factory=list)
    factual_tokens: dict[NonEmptyStr, list[NonEmptyStr]] = Field(default_factory=dict)
    explicit_absence: bool = False
    availability: EvidenceAvailability = EvidenceAvailability.UNKNOWN
    missing_fields: list[NonEmptyStr] = Field(default_factory=list)
    candidate_only: bool = True
    runtime_safety_truth: bool = False


class _VisibleTextParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        del attrs
        if tag.casefold() in {"script", "style", "noscript", "svg"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style", "noscript", "svg"}:
            self._ignored_depth = max(0, self._ignored_depth - 1)

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth and data.strip():
            self.parts.append(data.strip())


class _ResearchLinkParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href = ""
        self._text_parts: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag.casefold() != "a" or self._href:
            return
        href = str(dict(attrs).get("href") or "").strip()
        if href:
            self._href = href
            self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._href and data.strip():
            self._text_parts.append(data.strip())

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() != "a" or not self._href:
            return
        title = " ".join(" ".join(self._text_parts).split())
        self.links.append((self._href, title))
        self._href = ""
        self._text_parts = []


def visible_text(value: str, *, max_chars: int | None = None) -> str:
    parser = _VisibleTextParser()
    try:
        parser.feed(value)
        text = " ".join(parser.parts)
    except Exception:  # noqa: BLE001 - malformed public HTML is untrusted input.
        text = value
    normalized = re.sub(r"\s+", " ", text).strip()
    return normalized if max_chars is None else normalized[:max_chars]


def extract_research_links(
    content: str,
    *,
    base_url: str,
    focus_terms: Sequence[str],
    allowed_domains: Sequence[str],
    max_links: int = 40,
) -> list[dict[str, str]]:
    """Extract bounded, relevant same-policy links for adjacent-page lookup."""

    parser = _ResearchLinkParser()
    try:
        parser.feed(content)
    except Exception:  # noqa: BLE001 - malformed public HTML is untrusted input.
        return []
    normalized_terms = [
        _normalized(term) for term in focus_terms if _normalized(term)
    ]
    ranked: list[tuple[int, int, dict[str, str]]] = []
    seen_urls: set[str] = set()
    for index, (href, title) in enumerate(parser.links):
        parsed = urlsplit(urljoin(base_url, href))
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            continue
        url = parsed._replace(fragment="").geturl()
        if url in seen_urls or not _domain_matches(url, allowed_domains):
            continue
        haystack = _normalized(f"{title} {url}")
        score = sum(
            max(1, len(term)) for term in normalized_terms if term in haystack
        )
        if normalized_terms and score == 0:
            continue
        seen_urls.add(url)
        ranked.append(
            (
                score,
                -index,
                {"title": title or url, "url": url, "snippet": title},
            )
        )
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item[2] for item in ranked[:max_links]]


def _normalized(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold().strip()


def _domain_matches(url: str, patterns: Sequence[str]) -> bool:
    hostname = (urlsplit(url).hostname or "").casefold()
    return any(
        hostname == pattern.casefold().removeprefix("*.")
        or hostname.endswith(f".{pattern.casefold().removeprefix('*.')}")
        for pattern in patterns
    )


def _extract_urls(value: Any) -> list[str]:
    urls: list[str] = []
    if isinstance(value, str):
        urls.extend(_URL_PATTERN.findall(value))
    elif isinstance(value, Mapping):
        for item in value.values():
            urls.extend(_extract_urls(item))
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes):
        for item in value:
            urls.extend(_extract_urls(item))
    return list(dict.fromkeys(url.rstrip(".,，。;；") for url in urls))


def _normalize_date_token(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    match = re.fullmatch(
        r"(\d{4})(?:[-/]|年)(\d{1,2})(?:[-/]|月)(\d{1,2})(?:日)?",
        normalized,
    )
    if match is None:
        return _normalized(normalized)
    year, month, day = (int(item) for item in match.groups())
    return f"{year:04d}-{month:02d}-{day:02d}"


def _contains_required_literal(text: str, literal: str) -> bool:
    normalized_literal = unicodedata.normalize("NFKC", literal).strip()
    if _DATE_PATTERN.fullmatch(normalized_literal):
        return _normalize_date_token(normalized_literal) in _fact_tokens(text).get(
            "date", []
        )
    return _normalized(normalized_literal) in _normalized(text)


def _fact_tokens(value: str) -> dict[str, list[str]]:
    normalized_value = unicodedata.normalize("NFKC", value)
    without_urls = _URL_PATTERN.sub(" ", normalized_value)
    tokens: dict[str, list[str]] = {
        "dataset_code": [item.upper() for item in _DATASET_PATTERN.findall(without_urls)],
        "date": [
            _normalize_date_token(item) for item in _DATE_PATTERN.findall(without_urls)
        ],
        "time": [_normalized(item) for item in _TIME_PATTERN.findall(without_urls)],
        "measurement": [
            _normalized(item) for item in _MEASUREMENT_PATTERN.findall(without_urls)
        ],
        "magnitude": [
            _normalized(item) for item in _MAGNITUDE_PATTERN.findall(without_urls)
        ],
        "url": _extract_urls(value),
    }
    return {
        key: list(dict.fromkeys(items))
        for key, items in tokens.items()
        if items
    }


def _merge_fact_tokens(values: Iterable[dict[str, list[str]]]) -> dict[str, list[str]]:
    merged: dict[str, list[str]] = {}
    for value in values:
        for key, items in value.items():
            merged.setdefault(key, []).extend(items)
    return {
        key: list(dict.fromkeys(items))
        for key, items in merged.items()
    }


def _fetch_results(trace: Mapping[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    results: list[tuple[str, dict[str, Any]]] = []
    for item in trace.get("tool_returns") or []:
        if not isinstance(item, Mapping):
            continue
        tool_name = str(item.get("tool_name") or "")
        if tool_name not in {"scout_web_fetch", "scout_cwa_structured_fetch"}:
            continue
        content = item.get("content")
        if isinstance(content, Mapping):
            normalized = dict(content)
            if not normalized.get("url") and normalized.get("source_url"):
                normalized["url"] = normalized["source_url"]
            results.append((tool_name, normalized))
    return results


def _card_from_fetch(
    tool_id: str,
    result: Mapping[str, Any],
    index: int,
) -> EvidenceCard:
    url = str(result.get("url") or "").strip()
    raw_content = result.get("content")
    serialized = (
        raw_content
        if isinstance(raw_content, str)
        else json.dumps(raw_content, ensure_ascii=False, sort_keys=True)
    )
    text = visible_text(serialized, max_chars=40_000)
    content_hash = str(result.get("content_hash") or "").strip()
    if not content_hash:
        content_hash = "sha256:" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    status = int(result.get("status") or 0)
    fetched_at = str(result.get("fetched_at") or "").strip() or None
    evidence_id = hashlib.sha256(
        f"{url}\n{content_hash}\n{index}".encode()
    ).hexdigest()
    record = EvidenceRecord(
        evidence_id=f"web.{evidence_id[:20]}",
        source_ref=url or f"web-fetch:{index}",
        record_id=f"fetch.{index}",
        locator=url or f"web-fetch:{index}",
        source_hash=content_hash,
        data={
            "status": status,
            "content_type": str(result.get("content_type") or "unknown"),
            "visible_text": text,
        },
        observed_at=fetched_at,
    )
    return EvidenceCard(
        tool_id=tool_id,
        claim_summary=text[:320],
        key_values={
            "url": url,
            "status": status,
            "content_type": str(result.get("content_type") or "unknown"),
            "content_hash": content_hash,
            "fetched_at": fetched_at,
            "visible_text": text,
        },
        freshness="observed" if fetched_at else "unknown",
        quality="official_fetched" if status == 200 else "fetch_failed",
        source_refs=[url] if url else [],
        evidence_records=[record],
        result_count=1 if status == 200 else 0,
        truncated=bool(result.get("truncated")),
    )


def _split_requirement(value: str) -> tuple[str, int]:
    name, separator, raw_count = value.partition(":")
    if separator and raw_count.isdigit():
        return name, max(1, int(raw_count))
    return value, 1


_FIELD_PATTERNS: dict[str, re.Pattern[str]] = {
    "date": _DATE_PATTERN,
    "time": _TIME_PATTERN,
    "dataset_code": _DATASET_PATTERN,
    "time_range": re.compile(r"\d+\s*(?:-|–|—|至)\s*\d+\s*(?:小時|h)|\d+\s*小時", re.IGNORECASE),
    "update_frequency": re.compile(r"(?:每\s*\d+\s*小時|更新頻率|更新週期|每日更新|逐時更新)"),
    "status": re.compile(r"(?:生效|發布|解除|封閉|開放|管制|施工|提醒|未知|無法確認|未取得)"),
    "precipitation": re.compile(r"(?:降雨|雨量|降水|豪雨|大雨|QPF|mm)", re.IGNORECASE),
    "wind": re.compile(r"(?:風勢|風速|強風|陣風|m/s)", re.IGNORECASE),
    "notice": re.compile(r"(?:公告|提醒|注意|申請|入園)"),
    "control": re.compile(r"(?:封閉|開放|管制|施工|預警封路|交通)"),
    "position": re.compile(r"(?:位置|座標|地點|地址|緯度|經度)"),
    "magnitude": re.compile(r"(?:規模|芮氏)\s*[:：]?\s*\d+(?:\.\d+)?"),
    "warning_types": re.compile(r"(?:大雨|豪雨|低溫|高溫|濃霧|強風|颱風|警特報)"),
    "level": re.compile(r"(?:低量級|中量級|高量級|過量級|危險級|紫外線指數|等級)"),
    "manual_review_reason": re.compile(r"(?:人工複核|需複核|建議確認|證據不足|資料缺口)"),
    "safety_boundary": re.compile(
        r"(?:不能|不可|不可以).{0,24}(?:runtime safety truth|安全事實|安全真值)",
        re.IGNORECASE,
    ),
}


def _field_count(field: str, text: str, urls: Sequence[str]) -> int:
    if field == "url":
        return len(set(urls))
    pattern = _FIELD_PATTERNS.get(field)
    return len(pattern.findall(text)) if pattern else 0


def _missing_required_fields(
    required_fields: Sequence[str],
    *,
    text: str,
    urls: Sequence[str],
    synthesis: bool,
) -> list[str]:
    missing: list[str] = []
    for requirement in required_fields:
        field, count = _split_requirement(requirement)
        if not synthesis and field in {"manual_review_reason", "safety_boundary"}:
            continue
        if _field_count(field, text, urls) < count:
            missing.append(requirement)
    return missing


def build_web_evidence_bundle(
    trace: Mapping[str, Any],
    spec: ResearchQuestionSpec,
) -> WebEvidenceBundle:
    cards = [
        _card_from_fetch(tool_id, result, index)
        for index, (tool_id, result) in enumerate(_fetch_results(trace), start=1)
    ]
    source_refs = [source for card in cards for source in card.source_refs]
    source_groups_found = [
        group
        for group, domains in spec.source_groups.items()
        if any(_domain_matches(url, domains) for url in source_refs)
    ]
    evidence_text = " ".join(
        str(card.key_values.get("visible_text") or "") for card in cards
    )
    evidence_text_with_metadata = " ".join(
        [
            evidence_text,
            *[
                str(card.key_values.get("fetched_at") or "")
                for card in cards
            ],
        ]
    )
    missing_fields = _missing_required_fields(
        spec.required_fields,
        text=evidence_text_with_metadata,
        urls=source_refs,
        synthesis=False,
    )
    hazard_states = _hazard_states(evidence_text)
    explicit_absence = bool(
        _EXPLICIT_ABSENCE_PATTERN.search(evidence_text)
        or "查詢狀態=inactive" in evidence_text
        or "inactive" in hazard_states.values()
    )
    successful_cards = [card for card in cards if card.result_count]
    if not cards:
        availability = EvidenceAvailability.UNAVAILABLE
    elif "查詢狀態=active" in evidence_text:
        availability = EvidenceAvailability.ACTIVE
    elif "查詢狀態=inactive" in evidence_text:
        availability = EvidenceAvailability.INACTIVE
    elif explicit_absence:
        availability = EvidenceAvailability.INACTIVE
    elif successful_cards:
        availability = EvidenceAvailability.ACTIVE
    else:
        availability = EvidenceAvailability.UNKNOWN
    return WebEvidenceBundle(
        cards=cards,
        source_groups_found=source_groups_found,
        factual_tokens=_merge_fact_tokens(
            _fact_tokens(
                " ".join(
                    [
                        str(card.key_values.get("visible_text") or ""),
                        *card.source_refs,
                    ]
                )
            )
            for card in cards
        ),
        explicit_absence=explicit_absence,
        availability=availability,
        missing_fields=missing_fields,
    )


def _claim_links(
    answer: str,
    *,
    bundle: WebEvidenceBundle,
    spec: ResearchQuestionSpec,
    current_date: str,
) -> list[ClaimEvidenceLink]:
    answer_tokens = _fact_tokens(answer)
    allowed_tokens = _merge_fact_tokens(
        [bundle.factual_tokens, _fact_tokens(spec.question), _fact_tokens(current_date)]
    )
    links: list[ClaimEvidenceLink] = []
    for claim_type, values in answer_tokens.items():
        for value in values:
            supported_sources = [
                source
                for card in bundle.cards
                for source in card.source_refs
                if value in _fact_tokens(
                    " ".join(
                        [
                            str(card.key_values.get("visible_text") or ""),
                            *card.source_refs,
                        ]
                    )
                ).get(claim_type, [])
            ]
            supported = value in allowed_tokens.get(claim_type, [])
            links.append(
                ClaimEvidenceLink(
                    claim_type=claim_type,
                    claim_value=value,
                    normalized_value=_normalized(value),
                    source_refs=list(dict.fromkeys(supported_sources)),
                    supported=supported,
                    reason=(
                        "matched_fetched_evidence_or_request_scope"
                        if supported
                        else "not_found_in_fetched_evidence"
                    ),
                )
            )
    return links


def _contains_placeholder(answer: str) -> bool:
    return any(pattern.search(answer) for pattern in _PLACEHOLDER_PATTERNS)


def _contains_prompt_leak(answer: str) -> bool:
    return any(pattern.search(answer) for pattern in _PROMPT_LEAK_PATTERNS)


def _hazard_states(value: str) -> dict[str, str]:
    return {
        hazard: state.casefold()
        for hazard, state in _HAZARD_STATE_PATTERN.findall(value)
    }


def _answer_hazard_state_claims(answer: str, hazard: str) -> set[str]:
    aliases = {
        alias
        for alias in (hazard, hazard.removeprefix("陸上"))
        if alias
    }
    claims: set[str] = set()
    for clause in re.split(r"(?:但|然而|不過|[，,。；;\n])", answer):
        if not any(alias in clause for alias in aliases):
            continue
        if re.search(
            r"(?:\binactive\b|未生效|未發[布佈]|沒有|並無|目前無|"
            r"無生效|無(?!法).{0,12}(?:特報|警報)|解除|0\s*筆)",
            clause,
            re.IGNORECASE,
        ):
            claims.add("inactive")
        elif re.search(
            r"(?:\bactive\b|(?<!未)(?<!無)生效|已發[布佈]|列有|"
            r"有.{0,12}(?:特報|警報))",
            clause,
            re.IGNORECASE,
        ):
            claims.add("active")
    return claims


def _status_claim_contradicts_evidence(
    answer: str,
    *,
    evidence_text: str,
    availability: EvidenceAvailability,
) -> bool:
    if availability != EvidenceAvailability.ACTIVE:
        return False
    if _BARE_ABSENCE_PATTERN.search(answer):
        return True
    for hazard, expected_state in _hazard_states(evidence_text).items():
        claims = _answer_hazard_state_claims(answer, hazard)
        if any(claim != expected_state for claim in claims):
            return True
    active_hazards = [
        hazard
        for hazard, state in _hazard_states(evidence_text).items()
        if state == "active"
    ]
    for absence in _ABSENCE_SCOPE_PATTERN.finditer(answer):
        clause = re.split(
            r"(?:但|然而|不過|[，。；\n])",
            answer[absence.start() :],
            maxsplit=1,
        )[0]
        for hazard in active_hazards:
            aliases = {hazard, hazard.removeprefix("陸上")}
            if any(alias and alias in clause for alias in aliases):
                return True
    return False


def _mixed_hazard_statuses_complete(answer: str, *, evidence_text: str) -> bool:
    hazard_states = _hazard_states(evidence_text)
    if len(set(hazard_states.values())) <= 1:
        return True
    for hazard, state in hazard_states.items():
        if _answer_hazard_state_claims(answer, hazard) != {state}:
            return False
    return True


def _is_machine_structured_answer(answer: str) -> bool:
    stripped = answer.strip()
    if not stripped.startswith(("{", "[")):
        return False
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        return False
    return isinstance(value, dict | list)


def _is_machine_delimited_answer(answer: str) -> bool:
    without_urls = _URL_PATTERN.sub("", answer.strip())
    fields = [value.strip() for value in without_urls.split(",") if value.strip()]
    return (
        answer.count(",") >= 3
        and len(fields) >= 4
        and re.search(r"[。！？；\n]", without_urls) is None
    )


def _is_machine_labeled_answer(answer: str) -> bool:
    lines = [line.strip() for line in answer.splitlines() if line.strip()]
    labeled_lines = sum(
        bool(
            re.match(
                r"^(?:[-*]\s*)?(?:\*\*)?[^:：\n]{1,16}(?:\*\*)?\s*[:：]\s*\S",
                line,
            )
        )
        for line in lines
    )
    return labeled_lines >= 2


def question_requests_field_list(question: str) -> bool:
    return bool(_FIELD_LIST_REQUEST_PATTERN.search(question))


def _score(checks: Mapping[str, bool]) -> float:
    if not checks:
        return 100.0
    return round(sum(checks.values()) * 100.0 / len(checks), 2)


def evaluate_web_research(
    case: Mapping[str, Any],
    *,
    answer: str,
    trace: Mapping[str, Any],
    current_date: str,
    max_calls: int = 10,
) -> dict[str, Any]:
    spec = ResearchQuestionSpec.model_validate(case)
    bundle = build_web_evidence_bundle(trace, spec)
    tool_names = [
        str(item.get("tool_name") or "")
        for item in trace.get("tool_calls") or []
        if isinstance(item, Mapping)
    ]
    source_urls = [
        source for card in bundle.cards for source in card.source_refs
    ]
    cited_urls = _extract_urls(answer)
    evidence_text = " ".join(
        str(card.key_values.get("visible_text") or "") for card in bundle.cards
    )
    answer_missing_fields = _missing_required_fields(
        spec.required_fields,
        text=answer,
        urls=cited_urls,
        synthesis=True,
    )
    required_literals_in_evidence = all(
        _contains_required_literal(evidence_text, value)
        for value in spec.required_evidence_literals
    )
    required_literals_in_answer = all(
        _contains_required_literal(answer, value)
        for value in spec.required_answer_literals
    )
    missing_answer_literals = [
        value
        for value in spec.required_answer_literals
        if not _contains_required_literal(answer, value)
    ]
    absence_claim = bool(_ABSENCE_CLAIM_PATTERN.search(answer))
    absence_claim_supported = not absence_claim or bundle.explicit_absence
    status_not_contradictory = not _status_claim_contradicts_evidence(
        answer,
        evidence_text=evidence_text,
        availability=bundle.availability,
    )
    mixed_hazard_statuses_complete = _mixed_hazard_statuses_complete(
        answer,
        evidence_text=evidence_text,
    )
    links = _claim_links(
        answer,
        bundle=bundle,
        spec=spec,
        current_date=current_date,
    )
    factual_tokens_grounded = all(link.supported for link in links)
    topic_coverage = (
        not spec.topic_terms
        or any(_normalized(term) in _normalized(answer) for term in spec.topic_terms)
    )
    required_source_groups = set(spec.source_groups) <= set(bundle.source_groups_found)

    transport_checks = {
        "search_selection": (
            bool(
                {"scout_web_search", "scout_cwa_structured_fetch"}
                & set(tool_names)
            )
            if spec.requires_search
            else not (
                {"scout_web_search", "scout_cwa_structured_fetch"}
                & set(tool_names)
            )
        ),
        "fetch_selection": (
            bool(
                {"scout_web_fetch", "scout_cwa_structured_fetch"}
                & set(tool_names)
            )
            if spec.requires_fetch
            else not (
                {"scout_web_fetch", "scout_cwa_structured_fetch"}
                & set(tool_names)
            )
        ),
        "fetch_completed": bool(bundle.cards) if spec.requires_fetch else True,
        "official_source": (
            any(_domain_matches(url, spec.allowed_domains) for url in source_urls)
            if spec.allowed_domains
            else True
        ),
        "bounded_calls": (
            int(trace.get("tool_call_count") or 0) <= max_calls
            and int(trace.get("model_request_count") or 0) <= max_calls
        ),
    }
    evidence_checks = {
        "required_evidence_fields": not bundle.missing_fields,
        "required_evidence_literals": required_literals_in_evidence,
        "required_source_groups": required_source_groups,
        "absence_claim_supported": absence_claim_supported,
        "fresh_source_observed": (
            all(card.freshness != "unknown" for card in bundle.cards)
            if spec.freshness_required and bundle.cards
            else not spec.freshness_required or bool(bundle.cards)
        ),
    }
    labeled_answer_disallowed = _is_machine_labeled_answer(
        answer
    ) and not question_requests_field_list(spec.question)
    semantic_checks = {
        "answer_present": bool(answer.strip()),
        "no_placeholder": not _contains_placeholder(answer),
        "no_prompt_leak": not _contains_prompt_leak(answer),
        "natural_language_answer": not (
            _is_machine_structured_answer(answer)
            or _is_machine_delimited_answer(answer)
            or labeled_answer_disallowed
        ),
        "required_answer_fields": not answer_missing_fields,
        "required_answer_literals": not missing_answer_literals,
        "required_literals_in_answer": required_literals_in_answer,
        "factual_tokens_grounded": factual_tokens_grounded,
        "topic_coverage": topic_coverage,
        "citation_grounded": (
            bool(set(cited_urls) & set(source_urls)) if spec.requires_search else True
        ),
        "freshness_stated": (
            bool(re.search(r"目前|最新|截至|查詢|\d{4}[-年/]", answer))
            if spec.freshness_required
            else True
        ),
        "status_not_contradictory": status_not_contradictory,
        "mixed_hazard_statuses_complete": mixed_hazard_statuses_complete,
    }

    hard_fail_reasons: list[str] = []
    if not semantic_checks["no_placeholder"]:
        hard_fail_reasons.append("placeholder_output")
    if not semantic_checks["no_prompt_leak"]:
        hard_fail_reasons.append("prompt_leak")
    if _is_machine_structured_answer(answer):
        hard_fail_reasons.append("machine_structured_user_answer")
    if _is_machine_delimited_answer(answer):
        hard_fail_reasons.append("machine_delimited_user_answer")
    if labeled_answer_disallowed:
        hard_fail_reasons.append("machine_labeled_user_answer")
    if not factual_tokens_grounded:
        hard_fail_reasons.append("unsupported_factual_tokens")
    if not absence_claim_supported:
        hard_fail_reasons.append("unsupported_absence_claim")
    if not status_not_contradictory:
        hard_fail_reasons.append("contradictory_status_claim")
    if not mixed_hazard_statuses_complete:
        hard_fail_reasons.append("incomplete_hazard_statuses")
    if not required_literals_in_evidence:
        hard_fail_reasons.append("required_literal_missing_in_evidence")
    if not required_literals_in_answer:
        hard_fail_reasons.append("required_literal_missing_in_answer")
    if missing_answer_literals:
        hard_fail_reasons.append("required_answer_literal_missing")
    if not required_source_groups:
        hard_fail_reasons.append("incomplete_source_join")
    if bundle.missing_fields:
        hard_fail_reasons.append("missing_required_evidence")
    if answer_missing_fields or not topic_coverage:
        hard_fail_reasons.append("incomplete_answer")

    layers = {
        "transport": {
            "score": _score(transport_checks),
            "passed": all(transport_checks.values()),
            "checks": transport_checks,
        },
        "evidence_sufficiency": {
            "score": _score(evidence_checks),
            "passed": all(evidence_checks.values()),
            "checks": evidence_checks,
        },
        "semantic_correctness": {
            "score": _score(semantic_checks),
            "passed": all(semantic_checks.values()),
            "checks": semantic_checks,
        },
    }
    flat_checks = {
        **transport_checks,
        **evidence_checks,
        **semantic_checks,
        "evidence_overlap": factual_tokens_grounded,
        "semantic_claim_supported": (
            factual_tokens_grounded
            and absence_claim_supported
            and status_not_contradictory
        ),
    }
    layer_scores = [float(layer["score"]) for layer in layers.values()]
    return {
        "score": round(sum(layer_scores) / len(layer_scores), 2),
        "passed": all(layer["passed"] for layer in layers.values())
        and not hard_fail_reasons,
        "layers": layers,
        "checks": flat_checks,
        "hard_fail_reasons": list(dict.fromkeys(hard_fail_reasons)),
        "missing_evidence_fields": bundle.missing_fields,
        "missing_answer_fields": answer_missing_fields,
        "missing_answer_literals": missing_answer_literals,
        "claim_evidence_links": [link.model_dump(mode="json") for link in links],
        "cited_urls": cited_urls,
        "official_source_urls": [
            url for url in source_urls if _domain_matches(url, spec.allowed_domains)
        ],
        "evidence_summary": {
            "card_count": len(bundle.cards),
            "source_groups_found": bundle.source_groups_found,
            "availability": bundle.availability.value,
            "explicit_absence": bundle.explicit_absence,
        },
    }


def _result_rank(result: Mapping[str, Any], spec: ResearchQuestionSpec) -> tuple[int, list[str]]:
    url = str(result.get("url") or "")
    title = str(result.get("title") or "")
    snippet = str(result.get("snippet") or "")
    haystack = _normalized(f"{url} {title} {snippet}")
    score = 0
    reasons: list[str] = []
    if _domain_matches(url, spec.allowed_domains):
        score += 100
        reasons.append("allowed_official_domain")
    for group, domains in spec.source_groups.items():
        if _domain_matches(url, domains):
            score += 30
            reasons.append(f"source_group:{group}")
    for value in spec.required_evidence_literals:
        normalized_value = _normalized(value)
        if normalized_value in haystack:
            literal_score = (
                8
                if normalized_value.isdecimal() and len(normalized_value) <= 3
                else 80
            )
            score += literal_score
            reasons.append(f"required_literal:{value}")
    for term in spec.topic_terms:
        if _normalized(term) in haystack:
            score += 12
            reasons.append(f"topic:{term}")
        normalized_term = _normalized(term)
        if (
            len(normalized_term) >= 4
            and not normalized_term.isdecimal()
            and normalized_term in _normalized(title)
        ):
            score += 40
            reasons.append(f"descriptive_title_topic:{term}")
    status_signal = bool(
        re.search(r"(?:公告|開放|封閉|管制|施工|停業|暫停|注意|警報|特報)", f"{title} {snippet}")
    )
    date_signal = bool(
        _DATE_PATTERN.search(f"{title} {snippet}")
        or re.search(r"(?<!\d)\d{2,3}年\d{1,2}月\d{1,2}日", f"{title} {snippet}")
    )
    if "status" in spec.required_fields and status_signal:
        score += 45
        reasons.append("status_signal")
    if "date" in spec.required_fields and date_signal:
        score += 35
        reasons.append("date_signal")
    if status_signal and date_signal:
        score += 20
        reasons.append("dated_status_signal")
    path = urlsplit(url).path.casefold()
    if any(
        marker in path
        for marker in (
            "api/",
            "opendata",
            "dataset",
            "warning",
            "alert",
            "news",
            "announcement",
            "traffic",
        )
    ):
        score += 20
        reasons.append("structured_or_status_path")
    if path in {"", "/", "/ch", "/en"} and not (status_signal and date_signal):
        score -= 35
        reasons.append("generic_homepage_penalty")
    return score, reasons


def select_research_url(
    results: Sequence[Mapping[str, Any]],
    spec: ResearchQuestionSpec,
    *,
    attempted_urls: set[str],
) -> dict[str, Any] | None:
    ranked: list[tuple[int, int, dict[str, Any]]] = []
    for index, raw in enumerate(results):
        result = dict(raw)
        url = str(result.get("url") or "")
        if not url or url in attempted_urls:
            continue
        score, reasons = _result_rank(result, spec)
        ranked.append(
            (
                score,
                -index,
                {
                    **result,
                    "selection_score": score,
                    "selection_reasons": reasons,
                },
            )
        )
    if not ranked:
        return None
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return ranked[0][2]


def compact_evidence_for_synthesis(
    bundle: WebEvidenceBundle,
    *,
    max_cards: int = 5,
    max_chars_per_card: int = 1_200,
    focus_terms: Sequence[str] = (),
) -> str:
    normalized_focus_terms = list(
        dict.fromkeys(_normalized(str(term)) for term in focus_terms if str(term).strip())
    )

    def card_rank(card: EvidenceCard) -> tuple[int, int]:
        haystack = _normalized(
            " ".join(
                [
                    str(card.key_values.get("visible_text") or ""),
                    *[str(value) for value in card.source_refs],
                ]
            )
        )
        matched = [term for term in normalized_focus_terms if term in haystack]
        return len(matched), sum(len(term) for term in matched)

    def focused_excerpt(value: str) -> str:
        text = visible_text(value, max_chars=40_000)
        if len(text) <= max_chars_per_card or not focus_terms:
            return text[:max_chars_per_card]
        folded = text.casefold()
        starts = {0}
        for term in focus_terms:
            needle = str(term).strip().casefold()
            if not needle:
                continue
            offset = 0
            while (index := folded.find(needle, offset)) >= 0:
                starts.add(max(0, index - max_chars_per_card // 3))
                offset = index + max(1, len(needle))
        def rank(start: int) -> tuple[int, int]:
            excerpt = folded[start : start + max_chars_per_card]
            hits = [
                excerpt.count(str(term).strip().casefold())
                for term in focus_terms
                if str(term).strip()
            ]
            return sum(bool(hit) for hit in hits) * 100 + sum(hits), start
        best_start = max(starts, key=rank)
        return text[best_start : best_start + max_chars_per_card]

    ranked_cards = sorted(bundle.cards, key=card_rank, reverse=True)
    payload = []
    for card in ranked_cards[:max_cards]:
        payload.append(
            {
                "source_refs": card.source_refs,
                "freshness": card.freshness,
                "quality": card.quality,
                "content_hash": card.key_values.get("content_hash"),
                "fetched_at": card.key_values.get("fetched_at"),
                "evidence": focused_excerpt(
                    str(card.key_values.get("visible_text") or "")
                ),
            }
        )
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


__all__ = [
    "ClaimEvidenceLink",
    "EvidenceAvailability",
    "ResearchQuestionSpec",
    "WebEvidenceBundle",
    "build_web_evidence_bundle",
    "compact_evidence_for_synthesis",
    "evaluate_web_research",
    "extract_research_links",
    "question_requests_field_list",
    "select_research_url",
    "visible_text",
]
