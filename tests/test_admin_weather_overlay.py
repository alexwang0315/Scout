from admin_weather_overlay import (
    build_pretrip_weather_overlay,
    build_weather_api_runtime_status,
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
    }
    assert all(card["summary_only"] is True for card in overlay["cards"])
    assert all(glyph["human_review_required"] is True for glyph in overlay["glyphs"])
    assert "raw_payloads_embedded" in weather_overlay_to_json(overlay)
