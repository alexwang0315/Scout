from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from scout_hardware_prototype_prep import (
    ScoutHardwarePrototypeTargetProfile,
    build_scout_hardware_prototype_preflight,
)


FIXTURE_PATH = Path("tests/fixtures/hardware/scout_machine_target_profile.example.json")


def load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_target_profile_fixture_is_ready_for_manual_smoke() -> None:
    profile = ScoutHardwarePrototypeTargetProfile.model_validate(load_fixture())

    report = build_scout_hardware_prototype_preflight(profile)

    assert report.status == "ready_for_manual_smoke"
    assert report.blockers == []
    assert report.boundary.preflight_only is True
    assert report.boundary.network_calls_allowed is False
    assert report.boundary.safety_mutation_calls_allowed is False
    assert report.boundary.local_model_start_allowed is False
    assert report.boundary.outbound_messages_allowed is False
    assert report.counts.required_manual_check_count == 4


def test_manual_smoke_commands_are_operator_only_and_separate_safety_mutation() -> None:
    profile = ScoutHardwarePrototypeTargetProfile.model_validate(load_fixture())

    report = build_scout_hardware_prototype_preflight(profile)

    checks = {check.check_id: check for check in report.manual_smoke_checks}
    assert checks["runtime_health"].method == "GET"
    assert checks["runtime_health"].url_template == "http://scout.local:9099/health"
    assert checks["runtime_status"].url_template == "http://scout.local:9099/runtime/status"
    assert checks["provider_status"].url_template == "http://scout.local:9099/providers/status"
    assert checks["fixture_observation_ingest"].method == "POST"
    assert checks["fixture_observation_ingest"].url_template == "http://scout.local:9099/safety/observations"
    assert checks["fixture_observation_ingest"].operator_only is True
    assert checks["fixture_observation_ingest"].mutation is True
    assert "preflight does not execute this request" in checks["fixture_observation_ingest"].notes


def test_preflight_blocks_ai_local_model_and_live_provider_scope() -> None:
    payload = load_fixture()
    payload["ai_inference_enabled"] = True
    payload["live_hardware_enabled"] = True
    payload["event_bus"] = "mqtt"
    payload["expected_services"].append(
        {
            "service_id": "ollama",
            "kind": "local_model",
            "mode": "manual_start",
            "port": 11434,
            "endpoint_path": "/api/tags",
        }
    )

    profile = ScoutHardwarePrototypeTargetProfile.model_validate(payload)
    report = build_scout_hardware_prototype_preflight(profile)

    assert report.status == "blocked"
    assert "live_hardware_must_stay_disabled_for_step1" in report.blockers
    assert "ai_inference_must_stay_disabled_for_step1" in report.blockers
    assert "event_bus_must_stay_none_for_step1" in report.blockers
    assert "local_model_service_must_stay_disabled_for_step1" in report.blockers


def test_target_profile_rejects_secret_like_values() -> None:
    payload = load_fixture()
    payload["assistant_model_config_ref"] = "token=redacted-value"

    with pytest.raises(ValidationError):
        ScoutHardwarePrototypeTargetProfile.model_validate(payload)
