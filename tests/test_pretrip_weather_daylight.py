import inspect
import json
import socket
import urllib.request
from pathlib import Path

import pytest

import pretrip_weather_daylight
from pretrip_artifact_manifest import build_pretrip_artifact_manifest
from pretrip_weather_daylight import (
    PreTripWeatherDaylightEvidence,
    WeatherDaylightValidationStatus,
    load_weather_daylight_evidence,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
PROJECT_PATH = FIXTURE_ROOT / "project.json"
WEATHER_DAYLIGHT = FIXTURE_ROOT / "outputs" / "weather_daylight_evidence.json"


def test_weather_daylight_fixture_serializes_as_json():
    evidence = load_weather_daylight_evidence(WEATHER_DAYLIGHT)
    payload = evidence.model_dump(mode="json")

    assert payload["evidence_id"] == "weather_daylight.chilai_nanhua_day1.2026-05-03.v0"
    assert payload["status"] == "candidate_only"
    assert payload["date"] == "2026-05-03"
    assert payload["route_ref"] == "normalized/routes/route_summary.json"
    assert payload["daylight"]["date"] == payload["date"]
    assert payload["weather_window"]["window_start"] == "2026-05-03T08:55:35+08:00"
    assert payload["weather_window"]["window_end"] == "2026-05-03T15:25:35+08:00"
    assert evidence.to_json().endswith("\n")
    assert json.loads(evidence.to_json()) == payload


def test_threshold_policy_is_optional_reference_data_not_review_status():
    evidence = load_weather_daylight_evidence(WEATHER_DAYLIGHT)
    payload = evidence.model_dump(mode="json")
    policy = payload["threshold_policy"]

    assert policy["policy_status"] == "reference_only"
    assert policy["configurable"] is True
    assert policy["rainfall"]["heavy_rain_1h_mm"] == 40.0
    assert policy["rainfall"]["heavy_rain_24h_mm"] == 80.0
    assert policy["rainfall"]["extremely_heavy_rain_3h_mm"] == 100.0
    assert policy["rainfall"]["extremely_heavy_rain_24h_mm"] == 200.0
    assert policy["dense_fog"]["visibility_comparator"] == "<"
    assert policy["dense_fog"]["dense_fog_visibility_m"] == 200.0
    assert policy["strong_wind"]["yellow_avg_wind_mps"] == 10.8
    assert policy["strong_wind"]["yellow_gust_mps"] == 17.2
    assert policy["strong_wind"]["orange_avg_wind_mps"] == 20.8
    assert policy["strong_wind"]["orange_gust_mps"] == 28.5
    assert policy["daylight"]["dark_arrival_warning_margin_min"] == 60
    assert policy["daylight"]["civil_twilight_blocker_candidate_enabled"] is True
    assert policy["daylight"]["severe_weather_warning_candidate_enabled"] is True
    assert "cwa.weather_warning_thresholds" in payload["source_refs"]
    assert "cwa.weather_warning_thresholds" in policy["rainfall"]["source_refs"]
    assert "cwa.weather_warning_thresholds" in policy["dense_fog"]["source_refs"]
    assert "cwa.weather_warning_thresholds" in policy["strong_wind"]["source_refs"]

    assert payload["validation"]["validation_status"] == "human_review_required"
    assert payload["validation"]["reviewed_by"] is None
    assert payload["validation"]["reviewed_at"] is None
    assert payload["validation"]["confidence"] == "unknown"
    assert payload["validation"]["staleness"] == "placeholder"
    assert payload["human_review_required"] is True
    assert payload["authoritative_weather_computed"] is False
    assert payload["external_api_calls_made"] is False

    payload_without_policy = json.loads(WEATHER_DAYLIGHT.read_text())
    payload_without_policy.pop("threshold_policy")
    without_policy = PreTripWeatherDaylightEvidence.model_validate(payload_without_policy)
    assert without_policy.threshold_policy is None


def test_schema_has_no_network_dependency(monkeypatch):
    def reject_network(*_args, **_kwargs):
        raise AssertionError("weather/daylight schema must not use network")

    monkeypatch.setattr(socket, "create_connection", reject_network)
    monkeypatch.setattr(urllib.request, "urlopen", reject_network)

    evidence = load_weather_daylight_evidence(WEATHER_DAYLIGHT)

    assert evidence.external_api_calls_made is False
    assert evidence.authoritative_weather_computed is False

    source = inspect.getsource(pretrip_weather_daylight)
    assert "requests" not in source
    assert "httpx" not in source
    assert "urlopen" not in source
    assert "create_connection" not in source


def test_fixture_project_manifest_and_release_check_are_compatible():
    project = json.loads(PROJECT_PATH.read_text())
    assert project["weather_daylight_evidence_count"] == 1
    assert project["weather_daylight_evidence_ref"] == "outputs/weather_daylight_evidence.json"

    manifest = build_pretrip_artifact_manifest(PROJECT_PATH).to_dict()
    by_kind = {artifact["artifact_kind"]: artifact for artifact in manifest["artifacts"]}
    artifact = by_kind["weather_daylight_evidence"]
    assert artifact["ref"] == "outputs/weather_daylight_evidence.json"
    assert artifact["status"] == "candidate_only"
    assert artifact["validation_status"] == "human_review_required"
    assert artifact["confidence"] == "unknown"
    assert artifact["staleness"] == "placeholder"
    assert artifact["human_review_required"] is True
    assert artifact["authoritative_weather_computed"] is False
    assert artifact["external_api_calls_made"] is False


def test_candidate_only_boundary_rejects_authoritative_or_reviewed_claims():
    payload = json.loads(WEATHER_DAYLIGHT.read_text())

    payload["authoritative_weather_computed"] = True
    with pytest.raises(ValueError, match="authoritative computation"):
        PreTripWeatherDaylightEvidence.model_validate(payload)

    payload = json.loads(WEATHER_DAYLIGHT.read_text())
    payload["external_api_calls_made"] = True
    with pytest.raises(ValueError, match="external API calls"):
        PreTripWeatherDaylightEvidence.model_validate(payload)

    payload = json.loads(WEATHER_DAYLIGHT.read_text())
    payload["human_review_required"] = False
    with pytest.raises(ValueError, match="requires human review"):
        PreTripWeatherDaylightEvidence.model_validate(payload)

    assert set(WeatherDaylightValidationStatus) == {
        WeatherDaylightValidationStatus.NEEDS_REVIEW,
        WeatherDaylightValidationStatus.HUMAN_REVIEW_REQUIRED,
    }
