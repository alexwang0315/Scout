"""Server-side CWA structured research tool for Scout candidate evidence."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError

from pydantic_ai import RunContext
from pydantic_ai.exceptions import ModelRetry

CWA_DATASET_SOURCE_BASE = "https://opendata.cwa.gov.tw/dataset"
_MAX_TRACKED_RUNS = 1_024
_MAX_PROJECTION_ROWS = 120
_MAX_SCALAR_VALUE_CHARS = 512
_MAX_WARNING_MATCHES = 20

_TAIWAN_ADMIN_AREAS = (
    "基隆市",
    "臺北市",
    "新北市",
    "桃園市",
    "新竹縣",
    "新竹市",
    "苗栗縣",
    "臺中市",
    "彰化縣",
    "南投縣",
    "雲林縣",
    "嘉義縣",
    "嘉義市",
    "臺南市",
    "高雄市",
    "屏東縣",
    "宜蘭縣",
    "花蓮縣",
    "臺東縣",
    "澎湖縣",
    "金門縣",
    "連江縣",
)

_WARNING_HAZARD_ALIASES: dict[str, tuple[str, ...]] = {
    "大雨": ("大雨",),
    "豪雨": ("豪雨",),
    "濃霧": ("濃霧",),
    "陸上強風": ("陸上強風", "強風"),
    "低溫": ("低溫", "寒流"),
    "高溫": ("高溫", "熱浪"),
}

CWA_RESEARCH_DATASET_METADATA: dict[str, dict[str, str]] = {
    "W-C0033-001": {
        "description": "天氣警特報資料",
        "source_family": "weather_warning",
        "source_path": "warning",
    },
    "W-C0034-001": {
        "description": "颱風警報資料",
        "source_family": "typhoon_warning",
        "source_path": "warning",
    },
    "F-D0047-021": {
        "description": "南投縣鄉鎮天氣預報",
        "source_family": "township_forecast",
        "source_path": "forecast",
    },
    "A-B0062-001": {
        "description": "日出日沒時刻資料",
        "source_family": "astronomy",
        "source_path": "astronomy",
    },
    "F-C0041-001": {
        "description": "0-6小時定量降水預報",
        "source_family": "qpf",
        "source_path": "forecast",
        "time_range": "0-6小時",
        "update_frequency": "每6小時",
    },
    "E-A0015-001": {
        "description": "顯著有感地震報告",
        "source_family": "earthquake",
        "source_path": "earthquake",
    },
}


def fetch_cwa_research_dataset(
    dataset_id: str,
    *,
    timeout_seconds: float = 30.0,
    rest_fetcher: Callable[..., dict[str, Any]] | None = None,
    file_fetcher: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Fetch structured CWA evidence, using the file API for REST-only 404s."""

    if rest_fetcher is None or file_fetcher is None:
        from scout_weather_integration import (
            fetch_cwa_dataset,
            fetch_cwa_file_dataset,
        )

        active_rest_fetcher = rest_fetcher or fetch_cwa_dataset
        active_file_fetcher = file_fetcher or fetch_cwa_file_dataset
    else:
        active_rest_fetcher = rest_fetcher
        active_file_fetcher = file_fetcher
    try:
        return active_rest_fetcher(dataset_id, timeout_s=timeout_seconds)
    except HTTPError as exc:
        if exc.code != 404:
            raise
    return active_file_fetcher(
        dataset_id,
        file_format="JSON",
        timeout_s=timeout_seconds,
    )


def _flatten_scalars(
    value: Any,
    *,
    path: str = "$",
    depth: int = 0,
) -> list[tuple[str, str]]:
    if depth > 12:
        return []
    if isinstance(value, Mapping):
        rows: list[tuple[str, str]] = []
        for key, item in value.items():
            rows.extend(
                _flatten_scalars(
                    item,
                    path=f"{path}.{key}",
                    depth=depth + 1,
                )
            )
        return rows
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        rows = []
        for index, item in enumerate(value):
            rows.extend(
                _flatten_scalars(
                    item,
                    path=f"{path}[{index}]",
                    depth=depth + 1,
                )
            )
        return rows
    if value is None:
        return []
    text = str(value).strip()
    if len(text) > _MAX_SCALAR_VALUE_CHARS:
        text = text[:_MAX_SCALAR_VALUE_CHARS] + "..."
    return [(path, text)] if text else []


def _query_terms(query: str, dataset_id: str) -> list[str]:
    values = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9][A-Za-z0-9._-]+", query)
    return list(dict.fromkeys([dataset_id.casefold(), *(item.casefold() for item in values)]))


def _projection_score(path: str, value: str, terms: Sequence[str]) -> int:
    haystack = f"{path} {value}".casefold()
    score = sum(20 for term in terms if term and term in haystack)
    if any(
        marker in path.casefold()
        for marker in (
            "dataset",
            "description",
            "location",
            "area",
            "headline",
            "status",
            "time",
            "date",
            "valid",
            "rain",
            "wind",
            "magnitude",
            "longitude",
            "latitude",
        )
    ):
        score += 8
    return score


def _mapping_list(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _normalize_place_name(value: str) -> str:
    return value.replace("台", "臺").strip()


def _requested_warning_locations(query: str) -> list[str]:
    normalized_query = _normalize_place_name(query)
    requested: list[str] = []
    for area in _TAIWAN_ADMIN_AREAS:
        normalized_area = _normalize_place_name(area)
        stem = normalized_area[:-1]
        if normalized_area in normalized_query or stem in normalized_query:
            requested.append(area)
    return requested


def _requested_warning_hazards(query: str) -> list[str]:
    return [
        hazard
        for hazard, aliases in _WARNING_HAZARD_ALIASES.items()
        if any(alias in query for alias in aliases)
    ]


def _hazard_matches_requested(phenomena: str, requested: Sequence[str]) -> bool:
    if not requested:
        return True
    return any(
        any(alias in phenomena or phenomena in alias for alias in _WARNING_HAZARD_ALIASES[item])
        for item in requested
    )


def _requested_hazard_states(
    requested: Sequence[str],
    matches: Sequence[Mapping[str, Any]],
    *,
    official_state: str,
) -> dict[str, str]:
    default_state = (
        "inactive" if official_state in {"active", "inactive"} else "unknown"
    )
    return {
        hazard: (
            "active"
            if any(
                _hazard_matches_requested(
                    str(match.get("phenomena") or ""),
                    [hazard],
                )
                for match in matches
            )
            else default_state
        )
        for hazard in requested
    }


def _warning_locations(records: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    for key in ("location", "locations"):
        locations = _mapping_list(records.get(key))
        if locations or isinstance(records.get(key), list):
            return locations
    return []


def _location_hazards(location: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    conditions = location.get("hazardConditions")
    if not isinstance(conditions, Mapping):
        return []
    return _mapping_list(conditions.get("hazards"))


def _typhoon_warning_state(records: Mapping[str, Any]) -> str:
    infos = _mapping_list(records.get("info"))
    if not infos:
        return "inactive" if isinstance(records.get("info"), list) else "unknown"
    latest = infos[0]
    headline = str(latest.get("headline") or "").strip()
    if "解除" in headline and "颱風警報" in headline:
        return "inactive"
    serialized = json.dumps(latest, ensure_ascii=False)
    if '"警報類別": "END"' in serialized or '"value": "END"' in serialized:
        return "inactive"
    if "颱風警報" in headline:
        return "active"
    return "unknown"


def _warning_record_state(dataset_id: str, payload: Mapping[str, Any]) -> str:
    if dataset_id not in {"W-C0033-001", "W-C0034-001"}:
        return "not_applicable"
    success = str(payload.get("success") or "").casefold()
    records = payload.get("records")
    if not isinstance(records, Mapping) or success not in {"true", "1", "yes"}:
        return "unknown"
    if dataset_id == "W-C0034-001":
        return _typhoon_warning_state(records)
    locations = _warning_locations(records)
    if locations or isinstance(records.get("location"), list):
        return "active" if any(_location_hazards(item) for item in locations) else "inactive"
    for key in ("record", "weatherWarning", "warnings"):
        value = records.get(key)
        if isinstance(value, list):
            return "active" if value else "inactive"
    return "unknown"


def _warning_query_summary(
    dataset_id: str,
    payload: Mapping[str, Any],
    *,
    query: str,
    official_state: str,
) -> dict[str, Any] | None:
    if dataset_id == "W-C0034-001":
        records = payload.get("records")
        infos = _mapping_list(records.get("info")) if isinstance(records, Mapping) else []
        headline = str(infos[0].get("headline") or "").strip() if infos else ""
        return {
            "state": official_state,
            "matching_record_count": 1 if official_state == "active" else 0,
            "requested_locations": [],
            "requested_hazards": ["颱風警報"],
            "matches": ([{"headline": headline}] if official_state == "active" else []),
            "latest_headline": headline or None,
        }
    if dataset_id != "W-C0033-001":
        return None
    records = payload.get("records")
    if not isinstance(records, Mapping):
        requested_hazards = _requested_warning_hazards(query)
        return {
            "state": "unknown",
            "matching_record_count": 0,
            "requested_locations": _requested_warning_locations(query),
            "requested_hazards": requested_hazards,
            "requested_hazard_states": {
                hazard: "unknown" for hazard in requested_hazards
            },
            "matches": [],
        }
    requested_locations = _requested_warning_locations(query)
    requested_hazards = _requested_warning_hazards(query)
    normalized_locations = {
        _normalize_place_name(item) for item in requested_locations
    }
    matches: list[dict[str, str]] = []
    locations = _warning_locations(records)
    for location in locations:
        location_name = str(location.get("locationName") or "").strip()
        if normalized_locations and _normalize_place_name(location_name) not in normalized_locations:
            continue
        for hazard in _location_hazards(location):
            info = hazard.get("info")
            valid_time = hazard.get("validTime")
            info_map = info if isinstance(info, Mapping) else {}
            valid_time_map = valid_time if isinstance(valid_time, Mapping) else {}
            phenomena = str(info_map.get("phenomena") or "").strip()
            if not phenomena or not _hazard_matches_requested(phenomena, requested_hazards):
                continue
            matches.append(
                {
                    "location_name": location_name,
                    "phenomena": phenomena,
                    "significance": str(info_map.get("significance") or "").strip(),
                    "valid_from": str(valid_time_map.get("startTime") or "").strip(),
                    "valid_to": str(valid_time_map.get("endTime") or "").strip(),
                }
            )
            if len(matches) >= _MAX_WARNING_MATCHES:
                break
        if len(matches) >= _MAX_WARNING_MATCHES:
            break
    for warning in _mapping_list(records.get("warnings")):
        location_name = str(
            warning.get("areaName") or warning.get("locationName") or ""
        ).strip()
        if (
            normalized_locations
            and _normalize_place_name(location_name) not in normalized_locations
        ):
            continue
        headline = str(
            warning.get("headline") or warning.get("phenomena") or ""
        ).strip()
        if not headline or not _hazard_matches_requested(
            headline,
            requested_hazards,
        ):
            continue
        matches.append(
            {
                "location_name": location_name,
                "phenomena": headline,
                "significance": str(warning.get("status") or "").strip(),
                "valid_from": str(warning.get("startTime") or "").strip(),
                "valid_to": str(warning.get("endTime") or "").strip(),
            }
        )
        if len(matches) >= _MAX_WARNING_MATCHES:
            break
    query_has_filters = bool(requested_locations or requested_hazards)
    if matches:
        state = "active"
    elif query_has_filters and official_state in {"active", "inactive"}:
        state = "inactive"
    else:
        state = official_state
    return {
        "state": state,
        "matching_record_count": len(matches),
        "requested_locations": requested_locations,
        "requested_hazards": requested_hazards,
        "requested_hazard_states": _requested_hazard_states(
            requested_hazards,
            matches,
            official_state=official_state,
        ),
        "matches": matches,
    }


def _warning_query_content(summary: Mapping[str, Any]) -> str:
    locations = ",".join(str(item) for item in summary.get("requested_locations") or [])
    hazards = ",".join(str(item) for item in summary.get("requested_hazards") or [])
    parts = [
        f"查詢狀態={summary.get('state')}",
        f"符合筆數={summary.get('matching_record_count', 0)}",
    ]
    if locations:
        parts.append(f"查詢地點={locations}")
    if hazards:
        parts.append(f"查詢災種={hazards}")
    hazard_states = summary.get("requested_hazard_states")
    if isinstance(hazard_states, Mapping) and hazard_states:
        parts.append(
            "災種狀態="
            + ",".join(f"{key}:{value}" for key, value in hazard_states.items())
        )
    matches = summary.get("matches")
    if isinstance(matches, list):
        for match in matches[:8]:
            if not isinstance(match, Mapping):
                continue
            match_text = "/".join(
                str(match.get(key) or "").strip()
                for key in ("location_name", "phenomena", "significance", "valid_from", "valid_to")
                if str(match.get(key) or "").strip()
            )
            if match_text:
                parts.append(f"符合={match_text}")
    headline = str(summary.get("latest_headline") or "").strip()
    if headline:
        parts.append(f"最新標題={headline}")
    return "; ".join(parts)


def project_cwa_research_payload(
    dataset_id: str,
    payload: Mapping[str, Any],
    *,
    query: str,
    fetched_at: str | None = None,
) -> dict[str, Any]:
    """Project a raw CWA response without exposing its Authorization URL."""

    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    raw_hash = "sha256:" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    metadata = dict(CWA_RESEARCH_DATASET_METADATA.get(dataset_id, {}))
    source_path = str(metadata.get("source_path") or "").strip("/")
    source_url = "/".join(
        part for part in (CWA_DATASET_SOURCE_BASE, source_path, dataset_id) if part
    )
    terms = _query_terms(
        " ".join([query, *metadata.values()]),
        dataset_id,
    )
    flattened = _flatten_scalars(payload)
    ranked = sorted(
        enumerate(flattened),
        key=lambda item: (
            _projection_score(item[1][0], item[1][1], terms),
            -item[0],
        ),
        reverse=True,
    )
    selected = [row for _index, row in ranked[:_MAX_PROJECTION_ROWS]]
    official_state = _warning_record_state(dataset_id, payload)
    query_summary = _warning_query_summary(
        dataset_id,
        payload,
        query=query,
        official_state=official_state,
    )
    content_parts = [dataset_id, *metadata.values()]
    if query_summary is not None:
        content_parts.append(_warning_query_content(query_summary))
    if official_state == "inactive":
        content_parts.append("官方狀態目前0筆生效記錄")
    elif official_state == "active":
        content_parts.append("官方狀態目前有生效記錄")
    if query_summary is None:
        content_parts.extend(f"{path}={value}" for path, value in selected)
    observed_at = fetched_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    return {
        "tool_id": "scout_cwa_structured_fetch",
        "status": 200,
        "provider": "cwa_opendata",
        "dataset_id": dataset_id,
        "dataset_metadata": metadata,
        "official_state": official_state,
        "query_summary": query_summary,
        "source_url": source_url,
        "url": source_url,
        "content_type": "application/json",
        "content": " | ".join(content_parts),
        "projection_count": len(selected),
        "raw_scalar_count": len(flattened),
        "content_hash": raw_hash,
        "raw_response_hash": raw_hash,
        "fetched_at": observed_at,
        "truncated": len(selected) < len(flattened),
        "candidate_only": True,
        "runtime_safety_truth": False,
        "human_review_required": True,
    }


def build_local_cwa_research_fetch(
    *,
    allowed_dataset_ids: Sequence[str],
    max_uses: int = 10,
    timeout_seconds: float = 30.0,
    fetcher: Callable[..., dict[str, Any]] | None = None,
) -> Any:
    """Return a Pydantic tool that keeps the CWA key fully server-side."""

    allowed = frozenset(str(item) for item in allowed_dataset_ids)
    run_counts: OrderedDict[str, int] = OrderedDict()

    def active_fetcher(dataset_id: str, **kwargs: Any) -> dict[str, Any]:
        if fetcher is not None:
            return fetcher(dataset_id, **kwargs)
        timeout_seconds = float(kwargs.get("timeout_s") or timeout_seconds_default)
        return fetch_cwa_research_dataset(
            dataset_id,
            timeout_seconds=timeout_seconds,
        )

    timeout_seconds_default = timeout_seconds

    async def scout_cwa_structured_fetch(
        ctx: RunContext[Any],
        dataset_id: str,
        query: str = "",
    ) -> dict[str, Any]:
        """Fetch one approved CWA dataset and return verified candidate evidence."""

        run_id = str(ctx.run_id)
        current = run_counts.get(run_id, 0)
        if current >= max_uses:
            raise ModelRetry(
                f"CWA structured fetch use limit reached for this run ({max_uses})"
            )
        if dataset_id not in allowed:
            raise ModelRetry("CWA dataset is not approved for this research question")
        run_counts[run_id] = current + 1
        run_counts.move_to_end(run_id)
        while len(run_counts) > _MAX_TRACKED_RUNS:
            run_counts.popitem(last=False)
        try:
            payload = await asyncio.to_thread(
                active_fetcher,
                dataset_id,
                timeout_s=timeout_seconds,
            )
        except Exception as exc:
            raise ModelRetry(
                f"CWA structured source temporarily unavailable ({type(exc).__name__})"
            ) from exc
        return project_cwa_research_payload(
            dataset_id,
            payload,
            query=query,
        )

    return scout_cwa_structured_fetch


__all__ = [
    "CWA_RESEARCH_DATASET_METADATA",
    "build_local_cwa_research_fetch",
    "fetch_cwa_research_dataset",
    "project_cwa_research_payload",
]
