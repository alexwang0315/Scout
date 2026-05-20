from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


WEATHER_OVERLAY_LAYER_ID = "weather-api"


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
    secret_ref = active_env.get("SCOUT_WEATHER_API_KEY_REF", "env:SCOUT_WEATHER_API_KEY")
    blockers: list[str] = []
    if not enabled:
        blockers.append("weather_api_not_enabled")
    if enabled and secret_ref.startswith("env:"):
        env_name = secret_ref.removeprefix("env:")
        if not active_env.get(env_name):
            blockers.append(f"missing_weather_api_secret_ref:{secret_ref}")
    elif enabled and not secret_ref:
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
) -> dict[str, Any]:
    status = runtime_status or build_weather_api_runtime_status({})
    daylight = dict(weather.get("daylight") or {})
    weather_window = dict(weather.get("weather_window") or {})
    validation = dict(weather.get("validation") or {})
    threshold_policy = dict(weather.get("threshold_policy") or {})
    policy_daylight = dict(threshold_policy.get("daylight") or {})

    overlay_cards = [
        _card(
            "weather_window",
            "Weather window",
            weather_window.get("summary") or "Weather evidence requires review.",
            weather_window.get("hazard_notes") or [],
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
                f"{validation.get('validation_status', 'unknown')} / "
                f"confidence {validation.get('confidence', 'unknown')} / "
                f"staleness {validation.get('staleness', 'unknown')}"
            ),
            validation.get("notes") or [],
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
            "text": weather_window.get("summary") or "Weather review required",
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
        "provider_mode": "fixture_backed_local_admin_api",
        "api_runtime_status": status.to_dict(),
        "external_api_calls_made": bool(weather.get("external_api_calls_made", False)),
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
        },
        "source_refs": list(weather.get("source_refs") or []),
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


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}
