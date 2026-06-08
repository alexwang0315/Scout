from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from admin_basemap_tiles import normalize_bbox_wgs84


WEATHER_OVERLAY_LAYER_ID = "weather-api"
OPEN_METEO_PROVIDER = "open_meteo"
OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_DOCS_URL = "https://open-meteo.com/en/docs"
DEFAULT_WEATHER_API_TIMEOUT_SECONDS = 10
DEFAULT_WEATHER_API_USER_AGENT = "ScoutFusionWeatherOverlay/0.1 (+local admin demo)"

WeatherFetchJson = Callable[[str, Mapping[str, str]], Mapping[str, Any]]


@dataclass(frozen=True)
class WeatherApiRuntimeStatus:
    provider: str
    enabled: bool
    ready: bool
    blocker_reasons: list[str]
    secret_ref: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "enabled": self.enabled,
            "ready": self.ready,
            "blocker_reasons": self.blocker_reasons,
            "secret_ref": self.secret_ref,
            "secret_value_embedded": False,
            "external_api_call_performed": False,
        }


def build_weather_api_runtime_status(
    env: Mapping[str, str] | None = None,
) -> WeatherApiRuntimeStatus:
    active_env = env or os.environ
    enabled = _truthy(active_env.get("SCOUT_WEATHER_API_ENABLED"))
    provider = active_env.get("SCOUT_WEATHER_API_PROVIDER", "cwa_like_weather_api")
    if provider == OPEN_METEO_PROVIDER:
        secret_ref = active_env.get("SCOUT_WEATHER_API_KEY_REF") or None
    else:
        secret_ref = active_env.get("SCOUT_WEATHER_API_KEY_REF", "env:SCOUT_WEATHER_API_KEY")
    blockers: list[str] = []
    if not enabled:
        blockers.append("weather_api_not_enabled")
    if enabled and provider != OPEN_METEO_PROVIDER and secret_ref and secret_ref.startswith("env:"):
        env_name = secret_ref.removeprefix("env:")
        if not active_env.get(env_name):
            blockers.append(f"missing_weather_api_secret_ref:{secret_ref}")
    elif enabled and provider != OPEN_METEO_PROVIDER and not secret_ref:
        blockers.append("missing_weather_api_secret_ref")

    return WeatherApiRuntimeStatus(
        provider=provider,
        enabled=enabled,
        ready=enabled and not blockers,
        blocker_reasons=blockers,
        secret_ref=secret_ref,
    )


def build_pretrip_weather_overlay(
    weather: Mapping[str, Any],
    *,
    runtime_status: WeatherApiRuntimeStatus | None = None,
    live_weather_snapshot: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    status = runtime_status or build_weather_api_runtime_status({})
    live_snapshot = dict(live_weather_snapshot or {})
    live_ready = live_snapshot.get("status") == "live_summary_ready"
    daylight = dict(weather.get("daylight") or {})
    weather_window = dict(weather.get("weather_window") or {})
    validation = dict(weather.get("validation") or {})
    threshold_policy = dict(weather.get("threshold_policy") or {})
    policy_daylight = dict(threshold_policy.get("daylight") or {})
    weather_summary = (
        _live_weather_summary(live_snapshot)
        if live_ready
        else weather_window.get("summary") or "Weather evidence requires review."
    )
    weather_notes = (
        _live_weather_notes(live_snapshot)
        if live_ready
        else weather_window.get("hazard_notes") or []
    )
    api_runtime_status = status.to_dict()
    api_runtime_status["external_api_call_performed"] = bool(
        live_snapshot.get("external_api_calls_made")
    )

    overlay_cards = [
        _card(
            "weather_window",
            "Live weather" if live_ready else "Weather window",
            weather_summary,
            weather_notes,
        ),
        _card(
            "daylight",
            "Daylight",
            _daylight_summary(daylight, policy_daylight),
            [],
        ),
        _card(
            "validation",
            "Validation",
            (
                f"{'live_summary_only' if live_ready else validation.get('validation_status', 'unknown')} / "
                f"confidence {validation.get('confidence', 'unknown')} / "
                f"staleness {validation.get('staleness', 'unknown')}"
            ),
            _live_validation_notes(live_snapshot) if live_ready else validation.get("notes") or [],
        ),
    ]
    overlay_glyphs = [
        {
            "glyph_id": f"{weather.get('source_id', weather.get('evidence_id', 'weather'))}.summary",
            "layer_id": WEATHER_OVERLAY_LAYER_ID,
            "glyph_kind": "weather_summary_badge",
            "anchor": "top_right",
            "severity": "review",
            "label": "Weather",
            "label_zh": "氣象",
            "text": weather_summary,
            "human_review_required": True,
            "source_id": weather.get("source_id") or weather.get("evidence_id"),
            "source_path": weather.get("source_path"),
        },
        {
            "glyph_id": f"{weather.get('source_id', weather.get('evidence_id', 'weather'))}.daylight",
            "layer_id": WEATHER_OVERLAY_LAYER_ID,
            "glyph_kind": "daylight_margin_badge",
            "anchor": "top_right",
            "severity": "warning",
            "label": "Daylight",
            "label_zh": "日照",
            "text": _daylight_summary(daylight, policy_daylight),
            "human_review_required": True,
            "source_id": weather.get("source_id") or weather.get("evidence_id"),
            "source_path": weather.get("source_path"),
        },
    ]

    return {
        "artifact_kind": "admin_weather_api_overlay",
        "overlay_id": f"admin_weather_overlay.{weather.get('project_id', 'unknown')}.v0",
        "layer_id": WEATHER_OVERLAY_LAYER_ID,
        "status": "overlay_ready",
        "provider_mode": (
            "live_open_meteo_summary" if live_ready else "fixture_backed_local_admin_api"
        ),
        "api_runtime_status": api_runtime_status,
        "external_api_calls_made": bool(
            weather.get("external_api_calls_made", False)
            or live_snapshot.get("external_api_calls_made", False)
        ),
        "authoritative_weather_computed": bool(
            weather.get("authoritative_weather_computed", False)
        ),
        "human_review_required": bool(weather.get("human_review_required", True)),
        "raw_payloads_embedded": False,
        "cards": overlay_cards,
        "glyphs": overlay_glyphs,
        "counts": {
            "card_count": len(overlay_cards),
            "glyph_count": len(overlay_glyphs),
            "hazard_note_count": len(weather_window.get("hazard_notes") or []),
            "live_snapshot_available": live_ready,
        },
        "live_weather_snapshot": _public_live_snapshot_summary(live_snapshot),
        "source_refs": list(weather.get("source_refs") or []),
    }


def build_open_meteo_forecast_url(
    latitude: float,
    longitude: float,
    *,
    forecast_hours: int = 12,
) -> str:
    params = {
        "latitude": f"{latitude:.6f}",
        "longitude": f"{longitude:.6f}",
        "current": ",".join(
            [
                "temperature_2m",
                "relative_humidity_2m",
                "apparent_temperature",
                "is_day",
                "precipitation",
                "rain",
                "weather_code",
                "cloud_cover",
                "wind_speed_10m",
                "wind_direction_10m",
                "wind_gusts_10m",
            ]
        ),
        "hourly": "precipitation,wind_speed_10m,wind_gusts_10m,visibility",
        "forecast_hours": str(forecast_hours),
        "timezone": "auto",
        "wind_speed_unit": "kmh",
        "precipitation_unit": "mm",
    }
    return f"{OPEN_METEO_FORECAST_URL}?{urllib.parse.urlencode(params)}"


def fetch_open_meteo_weather_snapshot(
    route_bounds: Mapping[str, Any] | object,
    *,
    fetch_json: WeatherFetchJson | None = None,
) -> dict[str, Any]:
    point = weather_point_from_route_bounds(route_bounds)
    url = build_open_meteo_forecast_url(point["latitude"], point["longitude"])
    payload = (
        fetch_json(url, {"User-Agent": DEFAULT_WEATHER_API_USER_AGENT})
        if fetch_json is not None
        else _fetch_json_url(url)
    )
    current = dict(payload.get("current") or {})
    hourly = dict(payload.get("hourly") or {})
    return {
        "artifact_kind": "open_meteo_weather_snapshot",
        "status": "live_summary_ready",
        "provider": OPEN_METEO_PROVIDER,
        "source_docs_url": OPEN_METEO_DOCS_URL,
        "request_url": url,
        "request_url_has_secret": False,
        "coordinate": point,
        "current": {
            "time": current.get("time"),
            "temperature_2m_c": current.get("temperature_2m"),
            "relative_humidity_2m_pct": current.get("relative_humidity_2m"),
            "apparent_temperature_c": current.get("apparent_temperature"),
            "precipitation_mm": current.get("precipitation"),
            "rain_mm": current.get("rain"),
            "weather_code": current.get("weather_code"),
            "cloud_cover_pct": current.get("cloud_cover"),
            "wind_speed_10m_kmh": current.get("wind_speed_10m"),
            "wind_direction_10m_deg": current.get("wind_direction_10m"),
            "wind_gusts_10m_kmh": current.get("wind_gusts_10m"),
            "is_day": current.get("is_day"),
        },
        "next_6h": {
            "precipitation_mm": _sum_first(hourly.get("precipitation"), limit=6),
            "max_wind_speed_10m_kmh": _max_first(hourly.get("wind_speed_10m"), limit=6),
            "max_wind_gusts_10m_kmh": _max_first(hourly.get("wind_gusts_10m"), limit=6),
            "min_visibility_m": _min_first(hourly.get("visibility"), limit=6),
        },
        "raw_payloads_embedded": False,
        "external_api_calls_made": True,
        "authoritative_weather_computed": False,
        "human_review_required": True,
    }


def weather_point_from_route_bounds(route_bounds: Mapping[str, Any] | object) -> dict[str, float]:
    bbox = normalize_bbox_wgs84(route_bounds)
    return {
        "latitude": round((bbox["north"] + bbox["south"]) / 2, 6),
        "longitude": round((bbox["east"] + bbox["west"]) / 2, 6),
    }


def weather_overlay_to_json(overlay: Mapping[str, Any]) -> str:
    return json.dumps(dict(overlay), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _card(
    card_id: str,
    title: str,
    summary: str,
    notes: list[str],
) -> dict[str, Any]:
    return {
        "card_id": card_id,
        "title": title,
        "summary": summary,
        "notes": notes,
        "summary_only": True,
        "raw_payloads_embedded": False,
    }


def _daylight_summary(
    daylight: Mapping[str, Any],
    policy_daylight: Mapping[str, Any],
) -> str:
    sunset = daylight.get("sunset") or "sunset unknown"
    civil_end = daylight.get("civil_twilight_end") or "civil twilight unknown"
    margin = policy_daylight.get("dark_arrival_warning_margin_min", 60)
    return f"Sunset {sunset}; civil twilight end {civil_end}; dark margin {margin} min."


def _live_weather_summary(snapshot: Mapping[str, Any]) -> str:
    current = dict(snapshot.get("current") or {})
    next_6h = dict(snapshot.get("next_6h") or {})
    temp = _format_value(current.get("temperature_2m_c"), "C")
    wind = _format_value(current.get("wind_speed_10m_kmh"), "km/h")
    gust = _format_value(current.get("wind_gusts_10m_kmh"), "km/h")
    rain = _format_value(next_6h.get("precipitation_mm"), "mm next 6h")
    return f"Open-Meteo live summary: temp {temp}; wind {wind}; gust {gust}; precip {rain}."


def _live_weather_notes(snapshot: Mapping[str, Any]) -> list[str]:
    current = dict(snapshot.get("current") or {})
    next_6h = dict(snapshot.get("next_6h") or {})
    notes = [
        "Live weather is summary-only and still requires human review before departure.",
        (
            f"Weather code: {current.get('weather_code', 'unknown')}; "
            f"cloud cover: {_format_value(current.get('cloud_cover_pct'), '%')}."
        ),
    ]
    visibility = next_6h.get("min_visibility_m")
    if visibility is not None:
        notes.append(f"Minimum visibility in next 6h: {_format_value(visibility, 'm')}.")
    return notes


def _live_validation_notes(snapshot: Mapping[str, Any]) -> list[str]:
    return [
        f"Provider: {snapshot.get('provider', OPEN_METEO_PROVIDER)}.",
        "Raw API payload is not embedded in the admin overlay.",
        "This is not an authoritative departure decision.",
    ]


def _public_live_snapshot_summary(snapshot: Mapping[str, Any]) -> dict[str, Any] | None:
    if snapshot.get("status") != "live_summary_ready":
        return None
    return {
        "artifact_kind": snapshot.get("artifact_kind"),
        "status": snapshot.get("status"),
        "provider": snapshot.get("provider"),
        "source_docs_url": snapshot.get("source_docs_url"),
        "request_url_has_secret": snapshot.get("request_url_has_secret"),
        "coordinate": snapshot.get("coordinate"),
        "current": snapshot.get("current"),
        "next_6h": snapshot.get("next_6h"),
        "raw_payloads_embedded": snapshot.get("raw_payloads_embedded"),
        "external_api_calls_made": snapshot.get("external_api_calls_made"),
        "authoritative_weather_computed": snapshot.get("authoritative_weather_computed"),
        "human_review_required": snapshot.get("human_review_required"),
    }


def _fetch_json_url(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": DEFAULT_WEATHER_API_USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=DEFAULT_WEATHER_API_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def _format_value(value: Any, suffix: str) -> str:
    if value is None:
        return "unknown"
    if isinstance(value, float):
        return f"{value:.1f}{suffix}"
    return f"{value}{suffix}"


def _sum_first(values: Any, *, limit: int) -> float | None:
    numbers = _numeric_prefix(values, limit=limit)
    return round(sum(numbers), 3) if numbers else None


def _max_first(values: Any, *, limit: int) -> float | None:
    numbers = _numeric_prefix(values, limit=limit)
    return max(numbers) if numbers else None


def _min_first(values: Any, *, limit: int) -> float | None:
    numbers = _numeric_prefix(values, limit=limit)
    return min(numbers) if numbers else None


def _numeric_prefix(values: Any, *, limit: int) -> list[float]:
    if not isinstance(values, list):
        return []
    numbers: list[float] = []
    for value in values[:limit]:
        if isinstance(value, (int, float)):
            numbers.append(float(value))
    return numbers


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}
