from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
import json
import logging
from email.utils import parsedate_to_datetime
import os
import re
from typing import Any, TypeVar
import urllib.parse
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

from cwa_imagery_registry import (
    ALLOWED_CWA_IMAGE_HOSTS,
    ANIMATION_WINDOWS_HOURS,
    ImageryProductSpec,
)
from weather_imagery_tile_cache import CachedImageryFrame, WeatherImageryTileCache


MetadataFetcher = Callable[[ImageryProductSpec], Mapping[str, Any]]
HistoryFetcher = Callable[[ImageryProductSpec, int], list[Mapping[str, Any]]]
BytesFetcher = Callable[[str], tuple[bytes, str, str | None]]
DEFAULT_CWA_IMAGERY_TIMEOUT_SECONDS = 30.0
DEFAULT_CWA_IMAGERY_MAX_BYTES = 8 * 1024 * 1024
DEFAULT_CWA_JOB_MAX_FRAMES_PER_PRODUCT = 24
T = TypeVar("T")
LOGGER = logging.getLogger(__name__)


class CwaRadarIngestor:
    def __init__(
        self,
        *,
        registry: Mapping[str, ImageryProductSpec],
        cache: WeatherImageryTileCache,
        latest_metadata_fetcher: MetadataFetcher,
        history_metadata_fetcher: HistoryFetcher,
        bytes_fetcher: BytesFetcher,
    ) -> None:
        self.registry = dict(registry)
        self.cache = cache
        self.latest_metadata_fetcher = latest_metadata_fetcher
        self.history_metadata_fetcher = history_metadata_fetcher
        self.bytes_fetcher = bytes_fetcher

    @classmethod
    def from_cwa_opendata(
        cls,
        *,
        registry: Mapping[str, ImageryProductSpec],
        cache: WeatherImageryTileCache,
        env: Mapping[str, str] | None = None,
        timeout_s: float = DEFAULT_CWA_IMAGERY_TIMEOUT_SECONDS,
    ) -> "CwaRadarIngestor":
        return cls(
            registry=registry,
            cache=cache,
            latest_metadata_fetcher=lambda spec: fetch_cwa_latest_image_metadata(
                spec,
                env=env,
                timeout_s=timeout_s,
            ),
            history_metadata_fetcher=lambda spec, hours: fetch_cwa_history_image_metadata(
                spec,
                hours=hours,
                env=env,
                timeout_s=timeout_s,
            ),
            bytes_fetcher=lambda url: fetch_cwa_image_bytes(url, timeout_s=timeout_s),
        )

    def ingest_latest(
        self,
        product_id: str,
        *,
        allow_network_fetch: bool = False,
        fetched_at: str | None = None,
        dimensions: tuple[int, int] = (0, 0),
        build_display_asset: bool = True,
    ) -> CachedImageryFrame:
        spec = _product(self.registry, product_id, "radar")
        _require_network_approval(allow_network_fetch)
        return _ingest_metadata_item(
            spec,
            self.latest_metadata_fetcher(spec),
            cache=self.cache,
            bytes_fetcher=self.bytes_fetcher,
            fetched_at=fetched_at or _utc_now(),
            dimensions=dimensions,
            build_display_asset=build_display_asset,
        )

    def ingest_recent(
        self,
        product_id: str,
        *,
        hours: int,
        allow_network_fetch: bool = False,
        fetched_at: str | None = None,
        dimensions: tuple[int, int] = (0, 0),
        build_display_asset: bool = True,
        max_frames: int | None = None,
    ) -> list[CachedImageryFrame]:
        spec = _product(self.registry, product_id, "radar")
        _require_network_approval(allow_network_fetch)
        if hours not in ANIMATION_WINDOWS_HOURS:
            raise ValueError(f"unsupported animation window: {hours}")
        items = [
            *_optional_history_metadata(self.history_metadata_fetcher, spec, hours),
            self.latest_metadata_fetcher(spec),
        ]
        ingested = _ingest_metadata_items(
            spec,
            items,
            cache=self.cache,
            bytes_fetcher=self.bytes_fetcher,
            fetched_at=fetched_at or _utc_now(),
            dimensions=dimensions,
            build_display_asset=build_display_asset,
            max_frames=(
                min(DEFAULT_CWA_JOB_MAX_FRAMES_PER_PRODUCT, max(0, int(max_frames)))
                if max_frames is not None
                else min(
                    DEFAULT_CWA_JOB_MAX_FRAMES_PER_PRODUCT,
                    int(hours * 60 / max(1, spec.update_interval_minutes)) + 2,
                )
            ),
        )
        return _merge_recent_cached_frames(
            self.cache,
            spec,
            ingested,
            hours=hours,
            max_frames=(
                min(DEFAULT_CWA_JOB_MAX_FRAMES_PER_PRODUCT, max(0, int(max_frames)))
                if max_frames is not None
                else DEFAULT_CWA_JOB_MAX_FRAMES_PER_PRODUCT
            ),
        )


def _product(
    registry: Mapping[str, ImageryProductSpec],
    product_id: str,
    family: str,
) -> ImageryProductSpec:
    try:
        spec = registry[product_id]
    except KeyError as exc:
        raise KeyError(f"unknown CWA imagery product: {product_id}") from exc
    if spec.family != family:
        raise ValueError(f"{product_id} is not a {family} product")
    if not spec.available or not spec.latest_url:
        raise RuntimeError(f"CWA imagery product is not configured: {product_id}")
    return spec


def _require_network_approval(allow_network_fetch: bool) -> None:
    if not allow_network_fetch:
        raise PermissionError("explicit network approval is required for CWA imagery ingest")


def _ingest_metadata_items(
    spec: ImageryProductSpec,
    items: list[Mapping[str, Any]],
    **kwargs: Any,
) -> list[CachedImageryFrame]:
    unique: dict[str, Mapping[str, Any]] = {}
    for item in items:
        timestamp = _source_timestamp(item)
        unique[timestamp] = item
    ordered = [unique[key] for key in sorted(unique)]
    selected = _evenly_spaced(ordered, int(kwargs.pop("max_frames")))
    return [_ingest_metadata_item(spec, item, **kwargs) for item in selected]


def _evenly_spaced(
    items: list[T],
    limit: int,
) -> list[T]:
    if limit <= 0:
        return []
    if len(items) <= limit:
        return items
    if limit == 1:
        return [items[-1]]
    indexes = {
        round(position * (len(items) - 1) / (limit - 1))
        for position in range(limit)
    }
    return [items[index] for index in sorted(indexes)]


def _merge_recent_cached_frames(
    cache: WeatherImageryTileCache,
    spec: ImageryProductSpec,
    ingested: list[CachedImageryFrame],
    *,
    hours: int,
    max_frames: int,
) -> list[CachedImageryFrame]:
    combined = {
        frame.source_timestamp: frame
        for frame in [*cache.list_frames(spec.product_id), *ingested]
    }
    if not combined:
        return []
    ordered = sorted(combined.values(), key=lambda frame: _parse_source_time(frame.source_timestamp))
    cutoff = _parse_source_time(ordered[-1].source_timestamp) - timedelta(hours=hours)
    recent = [frame for frame in ordered if _parse_source_time(frame.source_timestamp) >= cutoff]
    return _evenly_spaced(recent, max_frames)


def _optional_history_metadata(
    fetcher: HistoryFetcher,
    spec: ImageryProductSpec,
    hours: int,
) -> list[Mapping[str, Any]]:
    try:
        return fetcher(spec, hours)
    except (RuntimeError, ValueError, TimeoutError, urllib.error.URLError) as exc:
        LOGGER.warning(
            "cwa_imagery_history_status=unavailable product_id=%s error_type=%s",
            spec.product_id,
            type(exc).__name__,
        )
        return []


def _parse_source_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _ingest_metadata_item(
    spec: ImageryProductSpec,
    item: Mapping[str, Any],
    *,
    cache: WeatherImageryTileCache,
    bytes_fetcher: BytesFetcher,
    fetched_at: str,
    dimensions: tuple[int, int],
    build_display_asset: bool,
) -> CachedImageryFrame:
    source_timestamp = _source_timestamp(item)
    cached = cache.get_frame_for_source(spec.product_id, source_timestamp)
    if cached is not None:
        return cached
    url = str(item.get("url") or item.get("ProductURL") or spec.latest_url or "")
    _validate_cwa_url(url)
    content, media_type, etag = bytes_fetcher(url)
    if media_type != spec.media_type:
        raise ValueError(f"unexpected media type for {spec.product_id}: {media_type}")
    return cache.put_frame(
        spec,
        source_timestamp=source_timestamp,
        fetched_at=fetched_at,
        content=content,
        media_type=media_type,
        dimensions=(
            tuple(item["dimensions"])
            if isinstance(item.get("dimensions"), (list, tuple))
            and len(item["dimensions"]) == 2
            else dimensions
        ),
        etag=etag or item.get("etag"),
        build_display_asset=build_display_asset,
        bbox_wgs84=(dict(item["bboxWgs84"]) if isinstance(item.get("bboxWgs84"), dict) else None),
    )


def _source_timestamp(item: Mapping[str, Any]) -> str:
    value = item.get("sourceTimestamp") or item.get("DateTime") or item.get("dataTime")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("CWA imagery metadata missing source timestamp")
    return value.strip()


def _validate_cwa_url(url: str) -> None:
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in ALLOWED_CWA_IMAGE_HOSTS
        or parsed.port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("CWA imagery URL is outside the allowlist")


def _validate_cwa_redirect(
    source_url: str,
    target_url: str,
    *,
    authenticated: bool,
) -> None:
    try:
        _validate_cwa_url(target_url)
    except ValueError as exc:
        raise ValueError("CWA redirect target is outside the allowlist") from exc
    source_query_keys = {
        key.lower()
        for key, _value in urllib.parse.parse_qsl(
            urlparse(source_url).query,
            keep_blank_values=True,
        )
    }
    if (
        "authorization" in source_query_keys
        and urlparse(source_url).hostname != urlparse(target_url).hostname
    ):
        raise ValueError("CWA query credential cannot cross redirect origins")


class _ValidatingCwaRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, *, authenticated: bool) -> None:
        super().__init__()
        self.authenticated = authenticated

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        _validate_cwa_redirect(req.full_url, newurl, authenticated=self.authenticated)
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None:
            redirected.remove_header("Authorization")
        if (
            redirected is not None
            and self.authenticated
            and urlparse(req.full_url).hostname == urlparse(newurl).hostname
        ):
            redirected.add_header("Authorization", str(req.headers.get("Authorization") or ""))
        return redirected


def fetch_cwa_latest_image_metadata(
    spec: ImageryProductSpec,
    *,
    env: Mapping[str, str] | None = None,
    timeout_s: float = DEFAULT_CWA_IMAGERY_TIMEOUT_SECONDS,
) -> Mapping[str, Any]:
    if not spec.dataset_id:
        raise RuntimeError(f"{spec.product_id} has no verified CWA OpenData dataset id")
    api_key = _resolve_api_key(env)
    url = (
        "https://opendata.cwa.gov.tw/fileapi/v1/opendataapi/"
        f"{urllib.parse.quote(spec.dataset_id)}?format=JSON"
    )
    raw, content_type, etag, final_url, last_modified = _authenticated_fetch(
        url,
        api_key=api_key,
        timeout_s=timeout_s,
    )
    candidates = _metadata_candidates(raw)
    if not candidates:
        try:
            _sniff_image_media_type(
                raw,
                declared_media_type=content_type,
                url=final_url,
            )
            image_response = True
        except ValueError:
            image_response = False
        if image_response and last_modified:
            return {
                "sourceTimestamp": parsedate_to_datetime(last_modified)
                .astimezone(timezone.utc)
                .isoformat(),
                "url": final_url,
                "etag": etag,
                "bboxWgs84": spec.bbox_wgs84.to_dict(),
            }
        raise ValueError(f"CWA metadata response missing image record for {spec.dataset_id}")
    selected = candidates[-1]
    return {
        **selected,
        "sourceTimestamp": selected["sourceTimestamp"],
        "url": selected.get("url") or spec.latest_url,
        "etag": selected.get("etag"),
    }


def fetch_cwa_direct_image_metadata(
    spec: ImageryProductSpec,
    *,
    timeout_s: float = DEFAULT_CWA_IMAGERY_TIMEOUT_SECONDS,
) -> Mapping[str, Any]:
    """Resolve timestamp metadata for an explicitly configured, allowlisted image URL."""
    if spec.dataset_id or not spec.latest_url:
        raise RuntimeError("direct image metadata requires a configured non-dataset product")
    _validate_cwa_url(spec.latest_url)
    request = urllib.request.Request(
        spec.latest_url,
        method="HEAD",
        headers={"User-Agent": "ScoutFusionCwaImagery/1.0"},
    )
    opener = urllib.request.build_opener(_ValidatingCwaRedirectHandler(authenticated=False))
    with opener.open(request, timeout=timeout_s) as response:  # noqa: S310 - redirects validated.
        final_url = response.geturl()
        _validate_cwa_url(final_url)
        last_modified = response.headers.get("Last-Modified")
        etag = response.headers.get("ETag")
    if not last_modified:
        raise ValueError("configured CWA image URL does not expose Last-Modified timestamp")
    timestamp = parsedate_to_datetime(last_modified).astimezone(timezone.utc).isoformat()
    return {"sourceTimestamp": timestamp, "url": final_url, "etag": etag}


def fetch_cwa_history_image_metadata(
    spec: ImageryProductSpec,
    *,
    hours: int,
    env: Mapping[str, str] | None = None,
    timeout_s: float = DEFAULT_CWA_IMAGERY_TIMEOUT_SECONDS,
) -> list[Mapping[str, Any]]:
    if hours not in ANIMATION_WINDOWS_HOURS:
        raise ValueError(f"unsupported animation window: {hours}")
    if not spec.dataset_id or not spec.history_supported:
        return []
    api_key = _resolve_api_key(env)
    now = datetime.now(timezone(timedelta(hours=8)))
    params = urllib.parse.urlencode(
        {
            "format": "JSON",
            "limit": min(500, max(8, int(hours * 60 / max(1, spec.update_interval_minutes)) + 4)),
            "timeFrom": (now - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S"),
            "timeTo": now.strftime("%Y-%m-%dT%H:%M:%S"),
        }
    )
    url = (
        "https://opendata.cwa.gov.tw/historyapi/v1/getMetadata/"
        f"{urllib.parse.quote(spec.dataset_id)}?{params}"
    )
    raw, _content_type, _etag, _final_url, _last_modified = _authenticated_fetch(
        url,
        api_key=api_key,
        timeout_s=timeout_s,
        authorization_in_query=True,
    )
    return _metadata_candidates(raw)


def fetch_cwa_image_bytes(
    url: str,
    *,
    timeout_s: float = DEFAULT_CWA_IMAGERY_TIMEOUT_SECONDS,
    max_bytes: int = DEFAULT_CWA_IMAGERY_MAX_BYTES,
) -> tuple[bytes, str, str | None]:
    _validate_cwa_url(url)
    request = urllib.request.Request(
        url,
        headers={"Accept": "image/png,image/jpeg", "User-Agent": "ScoutFusionCwaImagery/1.0"},
    )
    opener = urllib.request.build_opener(_ValidatingCwaRedirectHandler(authenticated=False))
    with opener.open(request, timeout=timeout_s) as response:  # noqa: S310 - every redirect is allowlisted.
        final_url = response.geturl()
        _validate_cwa_url(final_url)
        content = response.read(max_bytes + 1)
        if len(content) > max_bytes:
            raise ValueError("CWA imagery response exceeds byte limit")
        declared_content_type = str(response.headers.get_content_type()).lower()
        etag = response.headers.get("ETag")
    content_type = _sniff_image_media_type(
        content,
        declared_media_type=declared_content_type,
        url=final_url,
    )
    return content, content_type, etag


def _authenticated_fetch(
    url: str,
    *,
    api_key: str,
    timeout_s: float,
    authorization_in_query: bool = False,
) -> tuple[bytes, str, str | None, str, str | None]:
    _validate_cwa_url(url)
    request_url = url
    if authorization_in_query:
        parsed = urllib.parse.urlsplit(url)
        query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        query.append(("Authorization", api_key))
        request_url = urllib.parse.urlunsplit(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                urllib.parse.urlencode(query),
                parsed.fragment,
            )
        )
    headers = {
        "Accept": "application/json,application/xml,text/xml",
        "User-Agent": "ScoutFusionCwaImagery/1.0",
    }
    if not authorization_in_query:
        headers["Authorization"] = api_key
    request = urllib.request.Request(
        request_url,
        headers=headers,
    )
    opener = urllib.request.build_opener(
        _ValidatingCwaRedirectHandler(authenticated=not authorization_in_query)
    )
    try:
        with opener.open(request, timeout=timeout_s) as response:  # noqa: S310 - redirects validated.
            final_url = response.geturl()
            _validate_cwa_url(final_url)
            raw = response.read(4 * 1024 * 1024)
            return (
                raw,
                str(response.headers.get_content_type()).lower(),
                response.headers.get("ETag"),
                final_url,
                response.headers.get("Last-Modified"),
            )
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"CWA upstream returned HTTP {exc.code}") from None
    except urllib.error.URLError:
        raise RuntimeError("CWA upstream request failed") from None


def _resolve_api_key(env: Mapping[str, str] | None) -> str:
    active_env = os.environ if env is None else env
    for name in ("SCOUT_CWA_API_KEY", "CWA_API_KEY"):
        value = str(active_env.get(name, "")).strip()
        if value:
            return value
    raise RuntimeError("SCOUT_CWA_API_KEY is required for server-side CWA imagery fetch")


def _metadata_candidates(raw: bytes) -> list[Mapping[str, Any]]:
    try:
        payload: Any = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _xml_metadata_candidates(raw)
    candidates: list[dict[str, Any]] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            timestamps = _nested_values(
                value,
                "sourceTimestamp",
                "DateTime",
                "Datetime",
                "dataTime",
                "time",
            )
            timestamp = timestamps[-1] if timestamps else None
            urls = _nested_values(value, "url", "ProductURL", "productUrl", "downloadUrl")
            if timestamp and urls:
                bbox = _nested_bbox(value)
                dimensions = _nested_dimensions(value)
                for url in urls:
                    candidate: dict[str, Any] = {
                        "sourceTimestamp": str(timestamp),
                        "url": str(url),
                    }
                    if bbox is not None:
                        candidate["bboxWgs84"] = bbox
                    if dimensions is not None:
                        candidate["dimensions"] = dimensions
                    candidates.append(candidate)
            for nested in value.values():
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)

    visit(payload)
    unique = {(item["sourceTimestamp"], item["url"]): item for item in candidates}
    return [unique[key] for key in sorted(unique)]


def _xml_metadata_candidates(raw: bytes) -> list[Mapping[str, Any]]:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return []
    timestamps = [element.text.strip() for element in root.iter() if _xml_name(element.tag) in {"DateTime", "Datetime", "dataTime"} and element.text]
    urls = [element.text.strip() for element in root.iter() if _xml_name(element.tag) in {"ProductURL", "url"} and element.text]
    if not timestamps or not urls:
        return []
    candidate: dict[str, Any] = {"sourceTimestamp": timestamps[-1], "url": urls[-1]}
    longitude_ranges = [element.text.strip() for element in root.iter() if _xml_name(element.tag) == "LongitudeRange" and element.text]
    latitude_ranges = [element.text.strip() for element in root.iter() if _xml_name(element.tag) == "LatitudeRange" and element.text]
    if longitude_ranges and latitude_ranges:
        bbox = _bbox_from_ranges(longitude_ranges[-1], latitude_ranges[-1])
        if bbox is not None:
            candidate["bboxWgs84"] = bbox
    return [candidate]


def _nested_values(value: Any, *keys: str) -> list[Any]:
    found: list[Any] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in keys and nested not in (None, ""):
                found.append(nested)
            else:
                found.extend(_nested_values(nested, *keys))
    elif isinstance(value, list):
        for nested in value:
            found.extend(_nested_values(nested, *keys))
    return found


def _nested_bbox(value: Mapping[str, Any]) -> dict[str, float] | None:
    longitude = _nested_values(value, "LongitudeRange", "longitudeRange")
    latitude = _nested_values(value, "LatitudeRange", "latitudeRange")
    if not longitude or not latitude:
        return None
    return _bbox_from_ranges(str(longitude[-1]), str(latitude[-1]))


def _bbox_from_ranges(longitude: str, latitude: str) -> dict[str, float] | None:
    pattern = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*-\s*(-?\d+(?:\.\d+)?)\s*$")
    longitude_match = pattern.match(longitude)
    latitude_match = pattern.match(latitude)
    if longitude_match is None or latitude_match is None:
        return None
    west, east = (float(item) for item in longitude_match.groups())
    south, north = (float(item) for item in latitude_match.groups())
    if west >= east or south >= north:
        return None
    return {"west": west, "south": south, "east": east, "north": north}


def _nested_dimensions(value: Mapping[str, Any]) -> tuple[int, int] | None:
    dimensions = _nested_values(value, "ImageDimension", "imageDimension")
    if not dimensions:
        return None
    text = str(dimensions[-1]).lower().replace(" ", "")
    try:
        width, height = (int(item) for item in text.split("x", 1))
    except (TypeError, ValueError):
        return None
    return (width, height) if width > 0 and height > 0 else None


def _sniff_image_media_type(
    content: bytes,
    *,
    declared_media_type: str,
    url: str,
) -> str:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if declared_media_type in {"image/png", "image/jpeg"}:
        return declared_media_type
    raise ValueError(f"unexpected CWA imagery content for {urlparse(url).path}")


def _first_value(value: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if value.get(key) not in (None, ""):
            return value[key]
    return None


def _xml_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
