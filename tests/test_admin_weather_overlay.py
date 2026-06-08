from admin_weather_overlay import (
    build_open_meteo_forecast_url,
    build_pretrip_weather_overlay,
    build_weather_api_runtime_status,
    fetch_open_meteo_weather_snapshot,
    weather_overlay_to_json,
)


def test_weather_api_runtime_status_defaults_to_disabled_without_secret_values():
    status = build_weather_api_runtime_status({})

    assert status.enabled is False
    assert status.ready is False
    assert status.blocker_reasons == ["weather_api_not_enabled"]
    assert status.to_dict()["secret_value_embedded"] is False
    assert status.to_dict()["external_api_call_performed"] is False


def test_weather_api_runtime_status_requires_operator_secret_ref_when_enabled():
    missing = build_weather_api_runtime_status({"SCOUT_WEATHER_API_ENABLED": "true"})

    assert missing.enabled is True
    assert missing.ready is False
    assert missing.blocker_reasons == [
        "missing_weather_api_secret_ref:env:SCOUT_WEATHER_API_KEY"
    ]

    ready = build_weather_api_runtime_status(
        {
            "SCOUT_WEATHER_API_ENABLED": "true",
            "SCOUT_WEATHER_API_KEY": "operator-secret-not-exported",
        }
    )

    assert ready.enabled is True
    assert ready.ready is True
    assert ready.blocker_reasons == []
    assert ready.to_dict()["secret_ref"] == "env:SCOUT_WEATHER_API_KEY"


def test_open_meteo_runtime_status_is_opt_in_without_secret_requirement():
    status = build_weather_api_runtime_status(
        {
            "SCOUT_WEATHER_API_ENABLED": "true",
            "SCOUT_WEATHER_API_PROVIDER": "open_meteo",
        }
    )

    assert status.enabled is True
    assert status.ready is True
    assert status.provider == "open_meteo"
    assert status.secret_ref is None
    assert status.blocker_reasons == []


def test_open_meteo_snapshot_is_summary_only_with_injected_transport():
    seen = []

    def fake_fetch(url, headers):
        seen.append((url, headers))
        return {
            "current": {
                "time": "2026-05-20T09:00",
                "temperature_2m": 18.2,
                "relative_humidity_2m": 82,
                "apparent_temperature": 18.0,
                "precipitation": 0.1,
                "rain": 0.1,
                "weather_code": 61,
                "cloud_cover": 88,
                "wind_speed_10m": 12.4,
                "wind_direction_10m": 75,
                "wind_gusts_10m": 28.0,
                "is_day": 1,
            },
            "hourly": {
                "precipitation": [0.1, 0.2, 0, 0, 0.3, 0, 2.0],
                "wind_speed_10m": [10, 11, 12, 13, 14, 15, 30],
                "wind_gusts_10m": [20, 21, 22, 23, 24, 25, 50],
                "visibility": [9000, 8000, 7000, 6000, 5000, 4000, 1000],
            },
        }

    snapshot = fetch_open_meteo_weather_snapshot(
        {"south": 24.0, "west": 121.0, "north": 24.2, "east": 121.4},
        fetch_json=fake_fetch,
    )

    assert seen
    assert seen[0][0].startswith("https://api.open-meteo.com/v1/forecast?")
    assert "current=temperature_2m" in seen[0][0]
    assert seen[0][1]["User-Agent"].startswith("ScoutFusionWeatherOverlay/")
    assert snapshot["provider"] == "open_meteo"
    assert snapshot["coordinate"] == {"latitude": 24.1, "longitude": 121.2}
    assert snapshot["current"]["temperature_2m_c"] == 18.2
    assert snapshot["next_6h"]["precipitation_mm"] == 0.6
    assert snapshot["next_6h"]["max_wind_gusts_10m_kmh"] == 25.0
    assert snapshot["next_6h"]["min_visibility_m"] == 4000.0
    assert snapshot["raw_payloads_embedded"] is False
    assert snapshot["request_url_has_secret"] is False
    assert "raw" not in snapshot


def test_pretrip_weather_overlay_is_summary_only_and_fixture_backed():
    overlay = build_pretrip_weather_overlay(
        {
            "project_id": "chilai_nanhua_day1",
            "source_id": "weather_daylight.chilai_nanhua_day1",
            "source_path": "outputs/weather_daylight_evidence.json",
            "source_refs": ["outputs/weather_daylight_evidence.json"],
            "external_api_calls_made": False,
            "authoritative_weather_computed": False,
            "weather_window": {
                "summary": "Human review required before departure.",
                "hazard_notes": ["placeholder mountain weather"],
            },
            "daylight": {
                "sunset": "2026-05-03T18:28:00+08:00",
                "civil_twilight_end": "2026-05-03T18:53:00+08:00",
            },
            "validation": {
                "validation_status": "human_review_required",
                "confidence": "unknown",
                "staleness": "placeholder",
                "notes": ["no live API call"],
            },
            "threshold_policy": {
                "daylight": {"dark_arrival_warning_margin_min": 60}
            },
        },
        runtime_status=build_weather_api_runtime_status({}),
    )

    assert overlay["artifact_kind"] == "admin_weather_api_overlay"
    assert overlay["layer_id"] == "weather-api"
    assert overlay["status"] == "overlay_ready"
    assert overlay["provider_mode"] == "fixture_backed_local_admin_api"
    assert overlay["external_api_calls_made"] is False
    assert overlay["authoritative_weather_computed"] is False
    assert overlay["raw_payloads_embedded"] is False
    assert overlay["api_runtime_status"]["ready"] is False
    assert overlay["counts"] == {
        "card_count": 3,
        "glyph_count": 2,
        "hazard_note_count": 1,
        "live_snapshot_available": False,
    }
    assert all(card["summary_only"] is True for card in overlay["cards"])
    assert all(glyph["human_review_required"] is True for glyph in overlay["glyphs"])
    assert "raw_payloads_embedded" in weather_overlay_to_json(overlay)


def test_pretrip_weather_overlay_can_render_live_open_meteo_summary_without_raw_payload():
    snapshot = {
        "artifact_kind": "open_meteo_weather_snapshot",
        "status": "live_summary_ready",
        "provider": "open_meteo",
        "source_docs_url": "https://open-meteo.com/en/docs",
        "request_url": build_open_meteo_forecast_url(24.1, 121.2),
        "request_url_has_secret": False,
        "coordinate": {"latitude": 24.1, "longitude": 121.2},
        "current": {
            "temperature_2m_c": 18.2,
            "wind_speed_10m_kmh": 12.4,
            "wind_gusts_10m_kmh": 28.0,
            "weather_code": 61,
            "cloud_cover_pct": 88,
        },
        "next_6h": {
            "precipitation_mm": 0.6,
            "min_visibility_m": 4000.0,
        },
        "raw_payloads_embedded": False,
        "external_api_calls_made": True,
        "authoritative_weather_computed": False,
        "human_review_required": True,
    }
    overlay = build_pretrip_weather_overlay(
        {
            "project_id": "chilai_nanhua_day1",
            "source_id": "weather_daylight.chilai_nanhua_day1",
            "source_path": "outputs/weather_daylight_evidence.json",
            "weather_window": {"summary": "fixture summary", "hazard_notes": []},
            "daylight": {},
            "validation": {"confidence": "unknown", "staleness": "live"},
            "threshold_policy": {},
        },
        runtime_status=build_weather_api_runtime_status(
            {
                "SCOUT_WEATHER_API_ENABLED": "true",
                "SCOUT_WEATHER_API_PROVIDER": "open_meteo",
            }
        ),
        live_weather_snapshot=snapshot,
    )

    assert overlay["provider_mode"] == "live_open_meteo_summary"
    assert overlay["external_api_calls_made"] is True
    assert overlay["authoritative_weather_computed"] is False
    assert overlay["raw_payloads_embedded"] is False
    assert overlay["api_runtime_status"]["external_api_call_performed"] is True
    assert overlay["counts"]["live_snapshot_available"] is True
    assert "Open-Meteo live summary" in overlay["cards"][0]["summary"]
    assert overlay["live_weather_snapshot"]["request_url_has_secret"] is False
    assert "request_url" not in overlay["live_weather_snapshot"]
