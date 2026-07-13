from __future__ import annotations

import io
import json
import os
import xml.etree.ElementTree as ET
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Mapping
from datetime import datetime, timezone
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError


CWA_BASE_URL = "https://opendata.cwa.gov.tw/api/v1/rest/datastore"
CWA_FILEAPI_BASE_URL = "https://opendata.cwa.gov.tw/fileapi/v1/opendataapi"
CWA_PROVIDER_ID = "cwa_opendata"
SCOUT_CWA_API_KEY_ENV = "SCOUT_CWA_API_KEY"
LEGACY_CWA_API_KEY_ENV = "CWA_API_KEY"
CWA_TOWNSHIP_WEEKLY_FORECAST = "F-D0047-093"
CWA_36H_FORECAST = "F-C0032-001"
CWA_WEATHER_WARNING = "W-C0033-001"
CWA_FILEAPI_MAX_RESPONSE_BYTES = 64 * 1024 * 1024
CWA_FILEAPI_MAX_ZIP_ENTRIES = 512
CWA_FILEAPI_MAX_ZIP_ENTRY_BYTES = 8 * 1024 * 1024
CWA_FILEAPI_MAX_ZIP_EXPANDED_BYTES = 128 * 1024 * 1024

WEATHER_INTEGRATION_ARTIFACT_KIND = "route_weather_package"


def cwa_dataset_url(
    dataset_id: str,
    *,
    api_key: str,
    params: dict[str, str] | None = None,
    base_url: str = CWA_BASE_URL,
) -> str:
    query = urllib.parse.urlencode(
        {
            "Authorization": api_key,
            "format": "JSON",
            **(params or {}),
        }
    )
    return f"{base_url.rstrip('/')}/{urllib.parse.quote(dataset_id)}?{query}"


def cwa_fileapi_url(
    dataset_id: str,
    *,
    api_key: str,
    file_format: str,
    params: dict[str, str] | None = None,
    base_url: str = CWA_FILEAPI_BASE_URL,
) -> str:
    query = urllib.parse.urlencode(
        {
            "Authorization": api_key,
            "downloadType": "WEB",
            "format": file_format,
            **(params or {}),
        }
    )
    return f"{base_url.rstrip('/')}/{urllib.parse.quote(dataset_id)}?{query}"


def resolve_cwa_api_key(
    env: Mapping[str, str] | None = None,
    *,
    api_key_env: str | None = SCOUT_CWA_API_KEY_ENV,
) -> tuple[str, str]:
    """Resolve the server-side CWA key without exposing the value in artifacts."""
    active_env = os.environ if env is None else env
    env_names: list[str] = []
    if api_key_env:
        env_names.append(api_key_env)
    for fallback in (SCOUT_CWA_API_KEY_ENV, LEGACY_CWA_API_KEY_ENV):
        if fallback not in env_names:
            env_names.append(fallback)

    for env_name in env_names:
        api_key = str(active_env.get(env_name, "")).strip()
        if api_key:
            return api_key, env_name

    expected = f"{SCOUT_CWA_API_KEY_ENV} is required for server-side CWA fetch"
    if LEGACY_CWA_API_KEY_ENV in env_names:
        expected += f" (legacy fallback: {LEGACY_CWA_API_KEY_ENV})"
    raise RuntimeError(expected)


def fetch_cwa_dataset(
    dataset_id: str,
    *,
    params: dict[str, str] | None = None,
    api_key_env: str = SCOUT_CWA_API_KEY_ENV,
    env: Mapping[str, str] | None = None,
    timeout_s: float = 20.0,
) -> dict[str, Any]:
    api_key, resolved_env = resolve_cwa_api_key(env, api_key_env=api_key_env)
    url = cwa_dataset_url(dataset_id, api_key=api_key, params=params)
    request = urllib.request.Request(url, headers={"accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310 - trusted CWA endpoint.
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if dataset_id == CWA_TOWNSHIP_WEEKLY_FORECAST and exc.code == 404:
            return fetch_cwa_file_dataset(
                dataset_id,
                file_format="ZIP",
                api_key_env=resolved_env,
                env=env,
                timeout_s=timeout_s,
            )
        raise
    return payload if isinstance(payload, dict) else {}


def fetch_cwa_file_dataset(
    dataset_id: str,
    *,
    file_format: str = "JSON",
    params: dict[str, str] | None = None,
    api_key_env: str = SCOUT_CWA_API_KEY_ENV,
    env: Mapping[str, str] | None = None,
    timeout_s: float = 20.0,
) -> dict[str, Any]:
    api_key, _resolved_env = resolve_cwa_api_key(env, api_key_env=api_key_env)
    url = cwa_fileapi_url(
        dataset_id,
        api_key=api_key,
        file_format=file_format,
        params=params,
    )
    request = urllib.request.Request(url, headers={"accept": "application/json,application/zip,*/*"})
    with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310 - trusted CWA endpoint.
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > CWA_FILEAPI_MAX_RESPONSE_BYTES:
            raise ValueError("CWA file API response exceeds size limit")
        raw = response.read(CWA_FILEAPI_MAX_RESPONSE_BYTES + 1)
    if len(raw) > CWA_FILEAPI_MAX_RESPONSE_BYTES:
        raise ValueError("CWA file API response exceeds size limit")
    if raw.startswith(b"PK"):
        return _decode_cwa_zip_payload(dataset_id, raw)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {
            "artifact_kind": "cwa_fileapi_raw",
            "dataset_id": dataset_id,
            "bytes": len(raw),
        }
    return payload if isinstance(payload, dict) else {}


def _decode_cwa_zip_payload(dataset_id: str, raw: bytes) -> dict[str, Any]:
    documents: list[dict[str, str]] = []
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        if len(entries) > CWA_FILEAPI_MAX_ZIP_ENTRIES:
            raise ValueError("CWA ZIP response exceeds entry limit")
        expanded_bytes = 0
        for entry in entries:
            name = entry.filename
            if not name.lower().endswith(".xml"):
                continue
            if entry.file_size > CWA_FILEAPI_MAX_ZIP_ENTRY_BYTES:
                raise ValueError("CWA ZIP entry exceeds size limit")
            expanded_bytes += entry.file_size
            if expanded_bytes > CWA_FILEAPI_MAX_ZIP_EXPANDED_BYTES:
                raise ValueError("CWA ZIP response exceeds expanded size limit")
            try:
                payload = archive.read(entry)
                if len(payload) != entry.file_size:
                    raise ValueError("CWA ZIP entry size mismatch")
                text = payload.decode("utf-8")
            except (KeyError, UnicodeDecodeError):
                continue
            documents.append({"name": name, "text": text})
    return {
        "artifact_kind": "cwa_fileapi_zip",
        "dataset_id": dataset_id,
        "entry_count": len(documents),
        "documents": documents,
    }


def normalize_cwa_weather_points(
    dataset_id: str,
    payload: dict[str, Any],
    *,
    source_run_id: str | None = None,
) -> list[dict[str, Any]]:
    if dataset_id == CWA_36H_FORECAST:
        return _normalize_36h_forecast(payload, source_run_id=source_run_id)
    if dataset_id == CWA_TOWNSHIP_WEEKLY_FORECAST:
        return _normalize_township_forecast(payload, source_run_id=source_run_id)
    return []


def normalize_cwa_warnings(
    payload: dict[str, Any],
    *,
    source_run_id: str | None = None,
) -> list[dict[str, Any]]:
    records = payload.get("records") if isinstance(payload.get("records"), dict) else {}
    raw_warnings = records.get("record")
    if not isinstance(raw_warnings, list):
        raw_warnings = records.get("weatherWarning")
    if not isinstance(raw_warnings, list):
        return []
    warnings: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_warnings):
        if not isinstance(raw, dict):
            continue
        info = raw.get("info") if isinstance(raw.get("info"), dict) else raw
        warnings.append(
            {
                "source": CWA_WEATHER_WARNING,
                "source_run_id": source_run_id,
                "warning_id": str(raw.get("identifier") or raw.get("id") or f"warning.{index:03d}"),
                "area_name": _first_text(info, "areaName", "area_name", "area"),
                "headline": _first_text(info, "headline", "event", "phenomena"),
                "severity": _first_text(info, "severity", "significance"),
                "valid_from": _first_text(info, "effective", "onset", "valid_from"),
                "valid_to": _first_text(info, "expires", "ends", "valid_to"),
                "description": _first_text(info, "description", "instruction", "text"),
            }
        )
    return warnings


def build_route_weather_package(
    *,
    route_id: str,
    route_segments: list[dict[str, Any]],
    weather_points: list[dict[str, Any]],
    warnings: list[dict[str, Any]] | None = None,
    generated_at: str | None = None,
    valid_until: str | None = None,
    provider: str = "server_side_cwa_ingestor",
    source_run_ids: list[str] | None = None,
) -> dict[str, Any]:
    generated = generated_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    resolved_valid_until = (
        valid_until or _max_text(point.get("validTo") for point in weather_points)
    )
    package_segments = []
    for raw_segment in route_segments:
        segment = _normalize_route_segment(raw_segment)
        point = _select_weather_point(segment, weather_points)
        active_warnings = _matching_warnings(segment, warnings or [])
        weather_risk, factors = weather_risk_score(point, active_warnings)
        terrain_risk = _float_or_none(segment.get("terrain_risk")) or 0.0
        final_risk = _combine_risk(terrain_risk, weather_risk)
        package_segments.append(
            {
                "segmentId": segment["segment_id"],
                "fromM": segment.get("from_m"),
                "toM": segment.get("to_m"),
                "etaFrom": segment.get("eta_from"),
                "etaTo": segment.get("eta_to"),
                "township": segment.get("township"),
                "terrainRisk": terrain_risk,
                "weatherRisk": weather_risk,
                "finalRisk": final_risk,
                "riskLevel": _risk_level(final_risk),
                "factors": factors,
                "message": _segment_message(factors),
                "source": _segment_source(point, active_warnings),
            }
        )
    return {
        "artifact_kind": WEATHER_INTEGRATION_ARTIFACT_KIND,
        "routeId": route_id,
        "status": "candidate_only",
        "generatedAt": generated,
        "issued_at": generated,
        "valid_from": _min_text(point.get("validFrom") for point in weather_points),
        "valid_to": resolved_valid_until,
        "validUntil": resolved_valid_until,
        "ttl_s": _ttl_seconds(generated, resolved_valid_until),
        "provider": provider,
        "source_run_ids": list(source_run_ids or []),
        "authoritative_weather_computed": True,
        "external_api_calls_made": False,
        "human_review_required": True,
        "segments": package_segments,
        "wx_alerts": compact_wx_alerts(package_segments),
        "boundary": _closed_boundary(),
    }


def segment_gpx_route(
    gpx_path: Path | str,
    *,
    segment_length_m: float = 200.0,
    default_township: str | None = None,
    township_lookup: Callable[[float, float], str | dict[str, Any] | None] | None = None,
    start_at: str | None = None,
    speed_mps: float | None = None,
    terrain_risk: float = 0.0,
) -> list[dict[str, Any]]:
    points = _gpx_track_points(Path(gpx_path))
    if len(points) < 2:
        return []
    segment_length = max(100.0, min(float(segment_length_m), 250.0))
    start_time = _parse_datetime(start_at)
    speed = float(speed_mps) if speed_mps and speed_mps > 0 else None
    segments: list[dict[str, Any]] = []
    segment_start = points[0]
    segment_start_distance = 0.0
    cumulative_distance = 0.0
    next_cut = segment_length
    for previous, current in zip(points, points[1:]):
        cumulative_distance += _haversine_m(
            previous["lat"],
            previous["lon"],
            current["lat"],
            current["lon"],
        )
        if cumulative_distance < next_cut:
            continue
        midpoint_lat = (segment_start["lat"] + current["lat"]) / 2.0
        midpoint_lon = (segment_start["lon"] + current["lon"]) / 2.0
        township, lookup_metadata = _resolve_township_lookup(
            township_lookup,
            midpoint_lat,
            midpoint_lon,
            default_township=default_township,
        )
        segment = {
            "segmentId": f"seg.{len(segments):04d}",
            "fromM": round(segment_start_distance, 2),
            "toM": round(cumulative_distance, 2),
            "lat": midpoint_lat,
            "lon": midpoint_lon,
            "township": township,
            "terrainRisk": terrain_risk,
        }
        if lookup_metadata is not None:
            segment["townshipLookup"] = lookup_metadata
        if start_time is not None and speed is not None:
            segment["etaFrom"] = _offset_iso(start_time, segment_start_distance / speed)
            segment["etaTo"] = _offset_iso(start_time, cumulative_distance / speed)
        segments.append(segment)
        segment_start = current
        segment_start_distance = cumulative_distance
        next_cut = cumulative_distance + segment_length
    if segment_start_distance < cumulative_distance:
        current = points[-1]
        midpoint_lat = (segment_start["lat"] + current["lat"]) / 2.0
        midpoint_lon = (segment_start["lon"] + current["lon"]) / 2.0
        township, lookup_metadata = _resolve_township_lookup(
            township_lookup,
            midpoint_lat,
            midpoint_lon,
            default_township=default_township,
        )
        segment = {
            "segmentId": f"seg.{len(segments):04d}",
            "fromM": round(segment_start_distance, 2),
            "toM": round(cumulative_distance, 2),
            "lat": midpoint_lat,
            "lon": midpoint_lon,
            "township": township,
            "terrainRisk": terrain_risk,
        }
        if lookup_metadata is not None:
            segment["townshipLookup"] = lookup_metadata
        if start_time is not None and speed is not None:
            segment["etaFrom"] = _offset_iso(start_time, segment_start_distance / speed)
            segment["etaTo"] = _offset_iso(start_time, cumulative_distance / speed)
        segments.append(segment)
    return segments


def _resolve_township_lookup(
    township_lookup: Callable[[float, float], str | dict[str, Any] | None] | None,
    lat: float,
    lon: float,
    *,
    default_township: str | None,
) -> tuple[str | None, dict[str, Any] | None]:
    raw = township_lookup(lat, lon) if township_lookup is not None else None
    if isinstance(raw, dict):
        township = _first_present(raw, "township", "areaName", "area_name", "locationName")
        metadata = _compact_township_lookup_metadata(raw)
        return str(township) if township else default_township, metadata
    if isinstance(raw, str) and raw.strip():
        return raw.strip(), None
    return default_township, None


def _compact_township_lookup_metadata(raw: dict[str, Any]) -> dict[str, Any]:
    metadata = {
        "artifact_kind": _first_present(raw, "artifact_kind", "kind"),
        "matched": bool(raw.get("matched")),
        "county": _first_present(raw, "county", "city"),
        "township": _first_present(raw, "township", "areaName", "area_name", "locationName"),
        "distance_km": _float_or_none(_first_present(raw, "distance_km", "distanceKm")),
        "method": _first_present(raw, "method"),
        "confidence": _first_present(raw, "confidence"),
        "candidate_only": bool(raw.get("candidate_only", True)),
        "runtime_safety_truth": bool(raw.get("runtime_safety_truth", False)),
    }
    return {key: value for key, value in metadata.items() if value not in (None, "")}


def write_route_weather_package(path: Path | str, package: dict[str, Any]) -> None:
    Path(path).write_text(
        json.dumps(package, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def weather_risk_score(
    weather_point: dict[str, Any] | None,
    warnings: list[dict[str, Any]] | None = None,
) -> tuple[float, list[str]]:
    if weather_point is None:
        return 0.0, ["weather_missing"]
    factors: list[str] = []
    score = 0.0
    rain_probability = _float_or_none(weather_point.get("rainProbability"))
    rainfall_mm = _float_or_none(weather_point.get("rainfallMm"))
    wind_speed = _float_or_none(weather_point.get("windSpeedMps"))
    wind_gust = _float_or_none(weather_point.get("windGustMps"))
    temp_c = _float_or_none(weather_point.get("tempC"))
    visibility_m = _float_or_none(weather_point.get("visibilityM"))
    text = str(weather_point.get("weatherText") or "").lower()

    if rain_probability is not None:
        if rain_probability >= 80:
            score += 0.4
            factors.append("RAIN_PROB_HIGH")
        elif rain_probability >= 60:
            score += 0.3
            factors.append("RAIN_PROB_ELEVATED")
        elif rain_probability >= 40:
            score += 0.18
            factors.append("RAIN_PROB_MODERATE")
    if rainfall_mm is not None:
        if rainfall_mm >= 40:
            score += 0.35
            factors.append("HEAVY_RAIN")
        elif rainfall_mm >= 10:
            score += 0.2
            factors.append("RAIN_QPF")
    if "雷" in text or "thunder" in text:
        score += 0.3
        factors.append("THUNDER")
    if "霧" in text or "fog" in text or (visibility_m is not None and visibility_m < 200):
        score += 0.25
        factors.append("LOW_VIS")
    if wind_speed is not None and wind_speed >= 10.8:
        score += 0.22
        factors.append("WIND")
    if wind_gust is not None and wind_gust >= 17.2:
        score += 0.22
        factors.append("GUST")
    if temp_c is not None and temp_c <= 5:
        score += 0.2
        factors.append("COLD")
    for warning in warnings or []:
        score += 0.25
        headline = str(warning.get("headline") or warning.get("description") or "").lower()
        if "雨" in headline or "rain" in headline:
            factors.append("WARNING_RAIN")
        elif "風" in headline or "wind" in headline:
            factors.append("WARNING_WIND")
        else:
            factors.append("WARNING")
    return min(round(score, 4), 1.0), _dedupe(factors)


def compact_wx_alerts(segments: list[dict[str, Any]], *, limit: int = 8) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    for segment in segments:
        final_risk = _float_or_none(_first_present(segment, "finalRisk", "final_risk")) or 0.0
        weather_risk = _float_or_none(_first_present(segment, "weatherRisk", "weather_risk")) or 0.0
        if final_risk < 0.7 and weather_risk < 0.55:
            continue
        alerts.append(
            {
                "type": "WX_ALERT",
                "seg": str(_first_present(segment, "segmentId", "segment_id")),
                "risk": 3 if final_risk < 0.85 else 4,
                "ttlMin": None,
                "code": _alert_codes(segment),
            }
        )
    return alerts[:limit]


def _normalize_36h_forecast(
    payload: dict[str, Any],
    *,
    source_run_id: str | None,
) -> list[dict[str, Any]]:
    records = payload.get("records") if isinstance(payload.get("records"), dict) else {}
    locations = records.get("location")
    if not isinstance(locations, list):
        return []
    points: list[dict[str, Any]] = []
    for location in locations:
        if not isinstance(location, dict):
            continue
        area_name = str(location.get("locationName") or "")
        slots: dict[tuple[str | None, str | None], dict[str, Any]] = {}
        for element in location.get("weatherElement", []):
            if not isinstance(element, dict):
                continue
            element_name = str(element.get("elementName") or "")
            for time_item in element.get("time", []):
                if not isinstance(time_item, dict):
                    continue
                key = (time_item.get("startTime"), time_item.get("endTime"))
                slot = slots.setdefault(
                    key,
                    _weather_point_base(
                        source=CWA_36H_FORECAST,
                        source_run_id=source_run_id,
                        area_name=area_name,
                        valid_from=key[0],
                        valid_to=key[1],
                    ),
                )
                _apply_forecast_value(slot, element_name, time_item.get("parameter"))
        points.extend(slots.values())
    return points


def _normalize_township_forecast(
    payload: dict[str, Any],
    *,
    source_run_id: str | None,
) -> list[dict[str, Any]]:
    if payload.get("artifact_kind") == "cwa_fileapi_zip":
        return _normalize_township_forecast_zip(payload, source_run_id=source_run_id)
    records = payload.get("records") if isinstance(payload.get("records"), dict) else {}
    location_groups = records.get("locations")
    if not isinstance(location_groups, list):
        return []
    points: list[dict[str, Any]] = []
    for group in location_groups:
        if not isinstance(group, dict):
            continue
        locations = group.get("location")
        if not isinstance(locations, list):
            continue
        for location in locations:
            if not isinstance(location, dict):
                continue
            area_name = str(location.get("locationName") or "")
            slots: dict[tuple[str | None, str | None], dict[str, Any]] = {}
            for element in location.get("weatherElement", []):
                if not isinstance(element, dict):
                    continue
                element_name = str(element.get("elementName") or "")
                for time_item in element.get("time", []):
                    if not isinstance(time_item, dict):
                        continue
                    key = (time_item.get("startTime"), time_item.get("endTime"))
                    slot = slots.setdefault(
                        key,
                        _weather_point_base(
                            source=CWA_TOWNSHIP_WEEKLY_FORECAST,
                            source_run_id=source_run_id,
                            area_name=area_name,
                            valid_from=key[0],
                            valid_to=key[1],
                        ),
                    )
                    values = time_item.get("elementValue")
                    value = values[0] if isinstance(values, list) and values else values
                    _apply_forecast_value(slot, element_name, value)
            points.extend(slots.values())
    return points


def _normalize_township_forecast_zip(
    payload: dict[str, Any],
    *,
    source_run_id: str | None,
) -> list[dict[str, Any]]:
    documents = payload.get("documents")
    if not isinstance(documents, list):
        return []
    week_documents = [
        document
        for document in documents
        if isinstance(document, dict)
        and str(document.get("name") or "").endswith("Week24_CH.xml")
    ]
    selected_documents = week_documents or [
        document
        for document in documents
        if isinstance(document, dict)
        and str(document.get("name") or "").endswith("_CH.xml")
    ]
    points: list[dict[str, Any]] = []
    for document in selected_documents:
        text = document.get("text")
        if not isinstance(text, str):
            continue
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            continue
        points.extend(
            _normalize_township_forecast_xml_root(
                root,
                source_run_id=source_run_id,
                source_document=str(document.get("name") or ""),
            )
        )
    return points


def _normalize_township_forecast_xml_root(
    root: ET.Element,
    *,
    source_run_id: str | None,
    source_document: str,
) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for locations in _xml_children(root, "Locations"):
        county = _xml_child_text(locations, "LocationsName")
        for location in _xml_children(locations, "Location"):
            area_name = _xml_child_text(location, "LocationName") or ""
            lat = _float_or_none(_xml_child_text(location, "Latitude"))
            lon = _float_or_none(_xml_child_text(location, "Longitude"))
            slots: dict[tuple[str | None, str | None], dict[str, Any]] = {}
            for element in _xml_children(location, "WeatherElement"):
                element_name = _xml_child_text(element, "ElementName") or ""
                for time_item in _xml_children(element, "Time"):
                    start_time = (
                        _xml_child_text(time_item, "StartTime")
                        or _xml_child_text(time_item, "DataTime")
                    )
                    end_time = _xml_child_text(time_item, "EndTime") or start_time
                    key = (start_time, end_time)
                    slot = slots.setdefault(
                        key,
                        {
                            **_weather_point_base(
                                source=CWA_TOWNSHIP_WEEKLY_FORECAST,
                                source_run_id=source_run_id,
                                area_name=area_name,
                                valid_from=start_time,
                                valid_to=end_time,
                            ),
                            "county": county,
                            "lat": lat,
                            "lon": lon,
                            "source_document": source_document,
                        },
                    )
                    value = _xml_element_value(time_item)
                    _apply_forecast_value(slot, element_name, value)
            points.extend(slots.values())
    return points


def _weather_point_base(
    *,
    source: str,
    source_run_id: str | None,
    area_name: str,
    valid_from: str | None,
    valid_to: str | None,
) -> dict[str, Any]:
    return {
        "source": source,
        "source_run_id": source_run_id,
        "validFrom": valid_from,
        "validTo": valid_to,
        "areaName": area_name,
    }


def _gpx_track_points(path: Path) -> list[dict[str, float]]:
    try:
        root = ET.fromstring(path.read_text(encoding="utf-8"))
    except (OSError, ET.ParseError):
        return []
    points = []
    for element in root.iter():
        if _local_name(element.tag) != "trkpt":
            continue
        lat = _float_or_none(element.attrib.get("lat"))
        lon = _float_or_none(element.attrib.get("lon"))
        if lat is None or lon is None:
            continue
        points.append({"lat": lat, "lon": lon})
    return points


def _xml_children(root: ET.Element, local_name: str) -> list[ET.Element]:
    return [element for element in root.iter() if _local_name(element.tag) == local_name]


def _xml_child_text(parent: ET.Element, local_name: str) -> str | None:
    for child in parent:
        if _local_name(child.tag) == local_name:
            value = child.text.strip() if child.text else ""
            return value or None
    return None


def _xml_element_value(time_item: ET.Element) -> dict[str, Any]:
    for child in time_item:
        if _local_name(child.tag) != "ElementValue":
            continue
        values = {}
        for value_child in child:
            text = value_child.text.strip() if value_child.text else ""
            if text:
                values[_local_name(value_child.tag)] = text
        return values
    return {}


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius_m = 6_371_000.0
    d_lat = radians(lat2 - lat1)
    d_lon = radians(lon2 - lon1)
    a = (
        sin(d_lat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2) ** 2
    )
    return earth_radius_m * 2 * asin(sqrt(a))


def _offset_iso(start: datetime, seconds: float) -> str:
    from datetime import timedelta

    value = start + timedelta(seconds=seconds)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _apply_forecast_value(
    slot: dict[str, Any],
    element_name: str,
    parameter: Any,
) -> None:
    value_name = ""
    value = None
    if isinstance(parameter, dict):
        value_name = str(
            parameter.get("parameterName")
            or parameter.get("value")
            or parameter.get("elementValue")
            or ""
        )
        value = parameter.get("parameterName") or parameter.get("value")
        if not value_name:
            for candidate in parameter.values():
                if candidate not in (None, ""):
                    value_name = str(candidate)
                    value = candidate
                    break
    else:
        value_name = str(parameter or "")
        value = parameter
    normalized = element_name.lower()
    if element_name in {"Wx", "天氣現象"} or "wx" == normalized:
        slot["weatherText"] = value_name
    elif element_name in {"PoP", "PoP6h", "PoP12h", "降雨機率"} or "pop" in normalized:
        slot["rainProbability"] = _float_or_none(value)
    elif "降雨機率" in element_name:
        slot["rainProbability"] = _float_or_none(value)
    elif element_name in {
        "MinT",
        "MaxT",
        "T",
        "AT",
        "溫度",
        "平均溫度",
        "最低溫度",
        "最高溫度",
    }:
        slot["tempC"] = _float_or_none(value)
    elif element_name in {"WS", "風速"} or "wind" in normalized:
        slot["windSpeedMps"] = _float_or_none(value)
    elif element_name in {"WD", "風向"}:
        slot["windDirectionDeg"] = _float_or_none(value)
    elif element_name in {"RH", "相對濕度"} or "相對濕度" in element_name:
        slot["humidityPct"] = _float_or_none(value)
    elif element_name in {"QPF", "降雨量"}:
        slot["rainfallMm"] = _float_or_none(value)
    elif element_name in {"CI", "舒適度指數"}:
        slot["comfortText"] = value_name
    elif element_name in {"WeatherDescription", "天氣預報綜合描述"}:
        slot["weatherDescription"] = value_name


def _normalize_route_segment(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "segment_id": str(_first_present(raw, "segment_id", "segmentId", "id")),
        "from_m": _float_or_none(_first_present(raw, "from_m", "fromM")),
        "to_m": _float_or_none(_first_present(raw, "to_m", "toM")),
        "eta_from": _first_present(raw, "eta_from", "etaFrom"),
        "eta_to": _first_present(raw, "eta_to", "etaTo"),
        "township": _first_present(raw, "township", "areaName", "area_name"),
        "terrain_risk": _float_or_none(
            _first_present(raw, "terrain_risk", "terrainRisk", "teii")
        ),
    }


def _select_weather_point(
    segment: dict[str, Any],
    weather_points: list[dict[str, Any]],
) -> dict[str, Any] | None:
    township = str(segment.get("township") or "").strip()
    eta_from = _parse_datetime(segment.get("eta_from"))
    eta_to = _parse_datetime(segment.get("eta_to"))
    area_matches = [
        point
        for point in weather_points
        if not township or township == str(point.get("areaName") or "").strip()
    ]
    for point in area_matches:
        point_from = _parse_datetime(point.get("validFrom"))
        point_to = _parse_datetime(point.get("validTo"))
        if _overlaps(eta_from, eta_to, point_from, point_to):
            return point
    return area_matches[0] if area_matches else weather_points[0] if weather_points else None


def _matching_warnings(
    segment: dict[str, Any],
    warnings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    township = str(segment.get("township") or "").strip()
    eta_from = _parse_datetime(segment.get("eta_from"))
    eta_to = _parse_datetime(segment.get("eta_to"))
    matches = []
    for warning in warnings:
        area_name = str(warning.get("area_name") or "").strip()
        if area_name and township and area_name not in township and township not in area_name:
            continue
        warning_from = _parse_datetime(warning.get("valid_from"))
        warning_to = _parse_datetime(warning.get("valid_to"))
        if _overlaps(eta_from, eta_to, warning_from, warning_to):
            matches.append(warning)
    return matches


def _segment_source(
    point: dict[str, Any] | None,
    warnings: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "weather_source": point.get("source") if isinstance(point, dict) else None,
        "source_run_id": point.get("source_run_id") if isinstance(point, dict) else None,
        "warning_count": len(warnings),
    }


def _segment_message(factors: list[str]) -> str:
    if not factors or factors == ["weather_missing"]:
        return "No route-local weather risk could be computed for this segment."
    return "Weather risk factors: " + ", ".join(factors)


def _combine_risk(terrain_risk: float, weather_risk: float) -> float:
    interaction = terrain_risk * weather_risk
    return round(terrain_risk * 0.55 + weather_risk * 0.30 + interaction * 0.15, 4)


def _risk_level(score: float) -> str:
    if score >= 0.8:
        return "HIGH"
    if score >= 0.6:
        return "ELEVATED"
    if score >= 0.35:
        return "MODERATE"
    return "LOW"


def _alert_codes(segment: dict[str, Any]) -> list[str]:
    factors = " ".join(str(item) for item in segment.get("factors", [])).upper()
    codes = []
    for code, needles in {
        "RAIN": ("RAIN", "QPF"),
        "THUNDER": ("THUNDER",),
        "LOW_VIS": ("LOW_VIS", "FOG"),
        "WIND": ("WIND", "GUST"),
        "COLD": ("COLD",),
        "WARNING": ("WARNING",),
    }.items():
        if any(needle in factors for needle in needles):
            codes.append(code)
    return codes or ["WX"]


def _overlaps(
    a_start: datetime | None,
    a_end: datetime | None,
    b_start: datetime | None,
    b_end: datetime | None,
) -> bool:
    if a_start is None or a_end is None or b_start is None or b_end is None:
        return True
    return a_start <= b_end and b_start <= a_end


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _first_present(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    return None


def _first_text(mapping: dict[str, Any], *keys: str) -> str | None:
    value = _first_present(mapping, *keys)
    return str(value) if value is not None else None


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _min_text(values: Any) -> str | None:
    items = [str(value) for value in values if value]
    return min(items) if items else None


def _max_text(values: Any) -> str | None:
    items = [str(value) for value in values if value]
    return max(items) if items else None


def _ttl_seconds(generated_at: str | None, valid_until: str | None) -> int | None:
    generated = _parse_datetime(generated_at)
    valid = _parse_datetime(valid_until)
    if generated is None or valid is None:
        return None
    return max(0, int((valid - generated).total_seconds()))


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value and value not in seen:
            deduped.append(value)
            seen.add(value)
    return deduped


def _closed_boundary() -> dict[str, bool]:
    return {
        "read_only": True,
        "runtime_safety_truth": False,
        "live_safety_api_calls_allowed": False,
        "phase1_l0_l4_state_mutated": False,
        "safety_api_called": False,
        "outbound_send_performed": False,
        "hardware_control_performed": False,
        "workspace_file_write_allowed": False,
        "raw_payloads_embedded": False,
        "server_side_provider_required": True,
        "client_cwa_api_key_allowed": False,
    }
