from __future__ import annotations

import argparse
import hashlib
import json
import re
import ssl
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


ARTIFACT_KIND = "pretrip_p0_p1_source_collection"
SCHEMA_VERSION = "pretrip_p0_p1_source_collection.v1"
MAP_PREPARATION_SCHEMA_VERSION = "route_corridor_map_preparation.v1"
DEFAULT_WEB_CASE_QUERY_PLAN_REF = "outputs/layers/plans/web_case_query_plan.json"
DEFAULT_WEB_CASE_EVIDENCE_REF = "outputs/layers/normalized/web_case_evidence.json"
DEFAULT_ROUTE_SCOPE_REF = "normalized/routes/route_evidence_bundle.json"


DEFAULT_CHILAI_NANHUA_SOURCES: tuple[dict[str, str], ...] = (
    {
        "source_id": "forest_tianchi_open_20260613",
        "source_tier": "P0",
        "source_family": "official_forest_notice",
        "label": "天池山莊 2026-06-13 起開放公告",
        "url": "https://tconline.forest.gov.tw/news/index.php?id=521&mode=data",
    },
    {
        "source_id": "forest_yuntiangong_difficulty_notice",
        "source_tier": "P0",
        "source_family": "official_forest_notice",
        "label": "雲天宮線難度提醒",
        "url": "https://tconline.forest.gov.tw/news/index.php?id=505&mode=data",
    },
    {
        "source_id": "forest_recreation_nenggao_west_trail",
        "source_tier": "P0",
        "source_family": "official_trail_profile",
        "label": "台灣山林悠遊網 能高越嶺道西段",
        "url": "https://recreation.forest.gov.tw/Trail/RT?tr_id=064",
    },
    {
        "source_id": "forest_tianchi_lodging_rules",
        "source_tier": "P0",
        "source_family": "official_lodging_rules",
        "label": "天池山莊住宿申請須知",
        "url": "https://tconline.forest.gov.tw/ifa/?parent_id=253",
    },
    {
        "source_id": "hike_taiwan_permit_beds",
        "source_tier": "P0",
        "source_family": "official_permit_status",
        "label": "臺灣登山申請一站式服務網",
        "url": "https://hike.taiwan.gov.tw/bed_5.aspx",
    },
    {
        "source_id": "hiking_biji_chilai_nanhua",
        "source_tier": "P1",
        "source_family": "community_route_profile",
        "label": "健行筆記 奇萊南華",
        "url": "https://hiking.biji.co/index.php?act=detail&id=430&q=trail",
    },
    {
        "source_id": "culture_memory_gb_babiao",
        "source_tier": "P1",
        "source_family": "culture_memory_place",
        "label": "國家文化記憶庫 光被八表",
        "url": "https://tcmb.culture.tw/zh-tw/detail?id=625957&indexCode=Culture_Place",
    },
)


FetchResult = dict[str, Any]
Fetcher = Callable[[str, float], FetchResult]


def collect_pretrip_p0_p1_sources(
    project_root: Path | str,
    *,
    allow_network_fetch: bool = False,
    dry_run: bool = False,
    source_records: list[dict[str, Any]] | None = None,
    source_list_html: Path | str | None = None,
    route_keywords: list[str] | None = None,
    generated_at: str | None = None,
    timeout_seconds: float = 15.0,
    fetcher: Fetcher | None = None,
) -> dict[str, Any]:
    """Collect allowlisted P0/P1 route-context web evidence into the workspace.

    This is an operator-triggered pretrip evidence tool. It fetches only explicit
    source records, stores bounded snippets and hashes, and never creates runtime
    safety truth.
    """

    root = Path(project_root)
    project_path = root / "project.json"
    project = _load_json(project_path)
    project_id = str(project.get("project_id") or project.get("id") or root.name)
    generated_at = generated_at or _utc_now()
    query_plan_ref = str(project.get("web_case_query_plan_ref") or DEFAULT_WEB_CASE_QUERY_PLAN_REF)
    evidence_ref = str(project.get("web_case_evidence_ref") or DEFAULT_WEB_CASE_EVIDENCE_REF)
    route_scope_ref = _route_scope_ref(project)
    keywords = route_keywords or _route_keywords_from_workspace(root, project, project_id)
    base_sources = (
        [dict(source) for source in DEFAULT_CHILAI_NANHUA_SOURCES]
        if source_records is None
        else source_records
    )
    sources = _merge_source_records(
        base_sources,
        _source_records_from_html(source_list_html) if source_list_html else [],
    )

    network_calls_made = False
    source_statuses: list[dict[str, Any]] = []
    evidence_items: list[dict[str, Any]] = []
    fetch = fetcher or _fetch_url
    for source in sources:
        record = _normalize_source_record(source)
        if not allow_network_fetch:
            source_statuses.append({**record, "status": "planned_no_network"})
            continue
        network_calls_made = True
        try:
            fetched = fetch(record["url"], timeout_seconds)
        except Exception as exc:  # pragma: no cover - defensive external path
            fetched = {
                "ok": False,
                "status_code": None,
                "content_type": None,
                "body": "",
                "error": str(exc),
            }
        if not fetched.get("ok"):
            source_statuses.append(
                {
                    **record,
                    "status": "fetch_failed",
                    "http_status": fetched.get("status_code"),
                    "error": fetched.get("error"),
                }
            )
            continue
        body = str(fetched.get("body") or "")
        extracted = _extract_html_summary(body, keywords)
        content_sha256 = hashlib.sha256(body.encode("utf-8")).hexdigest()
        item = _evidence_item(
            project_id=project_id,
            source=record,
            extracted=extracted,
            keywords=keywords,
            generated_at=generated_at,
            http_status=fetched.get("status_code"),
            content_type=fetched.get("content_type"),
            content_sha256=content_sha256,
        )
        evidence_items.append(item)
        source_statuses.append(
            {
                **record,
                "status": "fetched",
                "http_status": fetched.get("status_code"),
                "content_type": fetched.get("content_type"),
                "content_sha256": content_sha256,
                "raw_html_embedded": False,
            }
        )

    boundary = _boundary(
        allow_network_fetch=allow_network_fetch,
        network_calls_made=network_calls_made,
    )
    query_plan = {
        "artifact_kind": "pretrip_web_case_query_plan",
        "schema_version": MAP_PREPARATION_SCHEMA_VERSION,
        "collector_schema_version": SCHEMA_VERSION,
        "project_id": project_id,
        "source_id": f"{project_id}.p0_p1_source_query_plan",
        "source_path": query_plan_ref,
        "status": "ready_for_explicit_fetch" if allow_network_fetch else "planned_no_network",
        "route_scope_ref": route_scope_ref,
        "route_keywords": keywords,
        "source_count": len(sources),
        "sources": sources,
        "network_policy": {
            "allow_network_fetch": allow_network_fetch,
            "explicit_fetch_required": True,
            "network_calls_made": network_calls_made,
        },
        "output_ref": evidence_ref,
        "boundary": boundary,
    }
    evidence = {
        "artifact_kind": "pretrip_web_case_evidence",
        "schema_version": MAP_PREPARATION_SCHEMA_VERSION,
        "collector_schema_version": SCHEMA_VERSION,
        "project_id": project_id,
        "source_id": f"{project_id}.p0_p1_web_case_evidence",
        "source_path": evidence_ref,
        "status": _evidence_status(allow_network_fetch, evidence_items, source_statuses),
        "generated_at": generated_at,
        "route_scope_ref": route_scope_ref,
        "source_plan_ref": query_plan_ref,
        "route_keywords": keywords,
        "source_statuses": source_statuses,
        "evidence_items": evidence_items,
        "points": evidence_items,
        "counts": _counts(evidence_items, source_statuses),
        "boundary": boundary,
    }
    result = {
        "artifact_kind": ARTIFACT_KIND,
        "schema_version": SCHEMA_VERSION,
        "status": "completed",
        "dry_run": dry_run,
        "project_id": project_id,
        "source_count": len(sources),
        "evidence_item_count": len(evidence_items),
        "network_calls_made": network_calls_made,
        "outputs": {
            "web_case_query_plan_ref": query_plan_ref,
            "web_case_evidence_ref": evidence_ref,
        },
        "boundary": boundary,
    }
    if not dry_run:
        _write_json(root / query_plan_ref, query_plan)
        _write_json(root / evidence_ref, evidence)
        _update_project(
            project_path,
            project,
            {
                "web_case_query_plan_ref": query_plan_ref,
                "web_case_evidence_ref": evidence_ref,
                "web_case_evidence_count": len(evidence_items),
                "web_case_source_count": len(sources),
                "web_case_collection_updated_at": generated_at,
                "web_case_collection_schema_version": SCHEMA_VERSION,
            },
        )
        result["writes_performed"] = True
    else:
        result["writes_performed"] = False
        result["planned_artifacts"] = {
            "query_plan": query_plan,
            "evidence": evidence,
        }
    return result


def _normalize_source_record(source: dict[str, Any]) -> dict[str, Any]:
    url = str(source.get("url") or "").strip()
    if not url:
        raise ValueError("source record requires url")
    guessed = _classify_url(url)
    return {
        "source_id": str(source.get("source_id") or guessed["source_id"]),
        "source_tier": str(source.get("source_tier") or guessed["source_tier"]),
        "source_family": str(source.get("source_family") or guessed["source_family"]),
        "label": str(source.get("label") or guessed["label"]),
        "url": url,
    }


def _merge_source_records(
    primary: list[dict[str, Any]],
    extra: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in [*primary, *extra]:
        try:
            record = _normalize_source_record(source)
        except ValueError:
            continue
        if record["url"] in seen:
            continue
        seen.add(record["url"])
        merged.append(record)
    return merged


def _source_records_from_html(path: Path | str | None) -> list[dict[str, Any]]:
    if not path:
        return []
    html_path = Path(path)
    if not html_path.exists():
        return []
    parser = _AnchorExtractor()
    parser.feed(html_path.read_text(encoding="utf-8"))
    return [_classify_url(url, label=label) | {"url": url} for url, label in parser.links]


def _classify_url(url: str, *, label: str | None = None) -> dict[str, str]:
    host = urlparse(url).netloc.lower()
    slug = re.sub(r"[^a-z0-9]+", "_", host).strip("_") or "source"
    tier = "P1"
    family = "community_or_reference_source"
    if host.endswith("forest.gov.tw") or host.endswith("hike.taiwan.gov.tw"):
        tier = "P0"
        family = "official_route_or_status_source"
    elif host.endswith("culture.tw"):
        tier = "P1"
        family = "culture_memory_source"
    elif host.endswith("hiking.biji.co"):
        tier = "P1"
        family = "community_route_profile"
    return {
        "source_id": f"source.{slug}.{hashlib.sha1(url.encode('utf-8')).hexdigest()[:10]}",
        "source_tier": tier,
        "source_family": family,
        "label": label or host or url,
    }


def _evidence_item(
    *,
    project_id: str,
    source: dict[str, Any],
    extracted: dict[str, Any],
    keywords: list[str],
    generated_at: str,
    http_status: Any,
    content_type: Any,
    content_sha256: str,
) -> dict[str, Any]:
    title = extracted.get("title") or source["label"]
    candidate_id = _candidate_id(project_id, source["source_id"])
    return {
        "id": candidate_id,
        "candidate_id": candidate_id,
        "label": title,
        "title": title,
        "summary": extracted.get("summary"),
        "snippets": extracted.get("snippets", []),
        "url": source["url"],
        "source_id": source["source_id"],
        "source_kind": "p0_p1_web_source",
        "source_tier": source["source_tier"],
        "source_family": source["source_family"],
        "source_families": [source["source_family"]],
        "http_status": http_status,
        "content_type": content_type,
        "content_sha256": content_sha256,
        "route_keywords": keywords,
        "retrieved_at": generated_at,
        "raw_html_embedded": False,
        "large_scraped_text_embedded": False,
        "candidate_only": True,
        "requires_human_review": True,
        "runtime_safety_truth": False,
        "source_refs": [
            {
                "source_kind": "p0_p1_web_source",
                "source_id": source["source_id"],
                "source_tier": source["source_tier"],
                "source_family": source["source_family"],
                "url": source["url"],
                "content_sha256": content_sha256,
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        ],
    }


def _extract_html_summary(body: str, keywords: list[str]) -> dict[str, Any]:
    parser = _TextExtractor()
    parser.feed(body)
    title = parser.title or (parser.headings[0] if parser.headings else "")
    text = _collapse_ws(" ".join(parser.text_chunks))
    snippets = _snippets(text, keywords)
    summary = " / ".join(snippets)[:640] if snippets else text[:360]
    return {
        "title": _collapse_ws(title or "")[:120],
        "summary": summary,
        "snippets": snippets,
    }


def _snippets(text: str, keywords: list[str]) -> list[str]:
    terms = [
        *keywords,
        "奇萊",
        "南華",
        "能高",
        "天池山莊",
        "雲天宮",
        "光被八表",
        "入園",
        "落石",
        "風險",
        "住宿",
    ]
    sentences = re.split(r"(?<=[。！？!?])\s+|\n+", text)
    matches: list[str] = []
    for sentence in sentences:
        value = _collapse_ws(sentence)
        if len(value) < 8:
            continue
        if any(term and term in value for term in terms):
            matches.append(value[:180])
        if len(matches) >= 4:
            break
    return matches


def _route_keywords_from_workspace(
    root: Path,
    project: dict[str, Any],
    project_id: str,
) -> list[str]:
    crawl_ref = project.get("route_context_crawl_seed_plan_ref")
    if isinstance(crawl_ref, str) and crawl_ref:
        payload = _load_json(root / crawl_ref)
        keywords = payload.get("route_keywords")
        if isinstance(keywords, list) and keywords:
            return [str(item) for item in keywords if str(item).strip()]
    if project_id == "chilai_nanhua_day1":
        return ["奇萊-南華", "chilai_nanhua_day1", "奇萊南華", "奇萊南峰 南華山"]
    return [project_id]


def _route_scope_ref(project: dict[str, Any]) -> str:
    value = project.get("route_evidence_bundle_ref")
    return str(value) if isinstance(value, str) and value else DEFAULT_ROUTE_SCOPE_REF


def _fetch_url(url: str, timeout_seconds: float) -> FetchResult:
    request = Request(
        url,
        headers={
            "User-Agent": "ScoutAlphaPretrip/0.1 (+https://local.scout.invalid)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    try:
        with urlopen(request, timeout=timeout_seconds, context=_https_context()) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            raw = response.read(1_500_000)
            return {
                "ok": True,
                "status_code": getattr(response, "status", 200),
                "content_type": response.headers.get("content-type"),
                "body": raw.decode(charset, errors="replace"),
            }
    except HTTPError as exc:
        return {
            "ok": False,
            "status_code": exc.code,
            "content_type": exc.headers.get("content-type") if exc.headers else None,
            "body": "",
            "error": str(exc),
        }
    except URLError as exc:
        return {
            "ok": False,
            "status_code": None,
            "content_type": None,
            "body": "",
            "error": str(exc),
        }


def _https_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    strict_flag = getattr(ssl, "VERIFY_X509_STRICT", 0)
    if strict_flag and hasattr(context, "verify_flags"):
        context.verify_flags &= ~strict_flag
    return context


def _counts(
    evidence_items: list[dict[str, Any]],
    source_statuses: list[dict[str, Any]],
) -> dict[str, Any]:
    by_tier: dict[str, int] = {}
    by_family: dict[str, int] = {}
    for item in evidence_items:
        by_tier[item["source_tier"]] = by_tier.get(item["source_tier"], 0) + 1
        by_family[item["source_family"]] = by_family.get(item["source_family"], 0) + 1
    return {
        "evidence_item_count": len(evidence_items),
        "source_count": len(source_statuses),
        "fetched_source_count": sum(1 for item in source_statuses if item.get("status") == "fetched"),
        "failed_source_count": sum(1 for item in source_statuses if item.get("status") == "fetch_failed"),
        "by_source_tier": dict(sorted(by_tier.items())),
        "by_source_family": dict(sorted(by_family.items())),
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _evidence_status(
    allow_network_fetch: bool,
    evidence_items: list[dict[str, Any]],
    source_statuses: list[dict[str, Any]],
) -> str:
    if not allow_network_fetch:
        return "planned_no_network"
    if evidence_items:
        return "ready_from_p0_p1_sources"
    if any(item.get("status") == "fetch_failed" for item in source_statuses):
        return "empty_fetch_failed"
    return "empty_no_matching_sources"


def _boundary(*, allow_network_fetch: bool, network_calls_made: bool) -> dict[str, Any]:
    return {
        "candidate_only": True,
        "review_gated": True,
        "observed_fact": False,
        "runtime_safety_truth": False,
        "phase1_runtime_mutation_allowed": False,
        "phase2_brain_writeback_allowed": False,
        "safety_api_called": False,
        "network_calls_allowed": allow_network_fetch,
        "network_calls_made": network_calls_made,
        "raw_gpx_embedded_in_json": False,
        "raw_dem_embedded_in_json": False,
        "raw_tile_embedded_in_json": False,
        "raw_html_embedded_in_json": False,
        "large_scraped_text_embedded": False,
    }


def _candidate_id(project_id: str, source_id: str) -> str:
    raw = f"web_case.{project_id}.{source_id}"
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("_")[:180]


def _collapse_ws(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)


def _update_project(path: Path, project: dict[str, Any], updates: dict[str, Any]) -> None:
    if not path.exists():
        return
    _write_json(path, {**project, **updates})


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self.headings: list[str] = []
        self.text_chunks: list[str] = []
        self._skip_depth = 0
        self._current_tag = ""
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
        self._current_tag = tag
        if tag in {"title", "h1", "h2"}:
            self._buffer = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self.title = _collapse_ws(" ".join(self._buffer))
            self._buffer = []
        elif tag in {"h1", "h2"}:
            heading = _collapse_ws(" ".join(self._buffer))
            if heading:
                self.headings.append(heading)
            self._buffer = []
        self._current_tag = ""

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        value = _collapse_ws(data)
        if not value:
            return
        self.text_chunks.append(value)
        if self._current_tag in {"title", "h1", "h2"}:
            self._buffer.append(value)


class _AnchorExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._label: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attrs_dict = dict(attrs)
        href = attrs_dict.get("href")
        if href and href.startswith(("http://", "https://")):
            self._href = href
            self._label = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href:
            self.links.append((self._href, _collapse_ws(" ".join(self._label))))
            self._href = None
            self._label = []

    def handle_data(self, data: str) -> None:
        if self._href:
            self._label.append(data)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect Scout P0/P1 route context web evidence.")
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--allow-network-fetch", action="store_true")
    parser.add_argument("--source-list-html", type=Path, default=None)
    parser.add_argument("--source-url", action="append", default=[])
    parser.add_argument("--route-keyword", action="append", default=[])
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--generated-at", default=None)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    extra_sources = [{"url": url} for url in args.source_url]
    source_records = [dict(source) for source in DEFAULT_CHILAI_NANHUA_SOURCES]
    source_records.extend(extra_sources)
    payload = collect_pretrip_p0_p1_sources(
        args.project_root,
        allow_network_fetch=args.allow_network_fetch,
        dry_run=args.dry_run,
        source_records=source_records,
        source_list_html=args.source_list_html,
        route_keywords=args.route_keyword or None,
        generated_at=args.generated_at,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
