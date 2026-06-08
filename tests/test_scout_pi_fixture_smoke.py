from __future__ import annotations

import json
from pathlib import Path

from scout_hardware_prototype_prep import ScoutHardwarePrototypeTargetProfile
from scout_pi_fixture_smoke import build_pi_fixture_smoke_plan, load_manual_observation_fixture


PROFILE_PATH = Path("tests/fixtures/hardware/scout_machine_target_profile.example.json")
OBSERVATION_PATH = Path("tests/fixtures/hardware/manual_observation_smoke.example.json")


def load_profile() -> ScoutHardwarePrototypeTargetProfile:
    return ScoutHardwarePrototypeTargetProfile.model_validate_json(PROFILE_PATH.read_text())


def test_manual_observation_fixture_shape_is_phase1_ingest_compatible() -> None:
    payload = load_manual_observation_fixture(OBSERVATION_PATH)

    assert payload["device"] == "apple_watch"
    assert payload["source"] == "fixture_hardware_smoke"
    assert isinstance(payload["payload"], dict)
    assert "locationLatitude(WGS84)" in payload["payload"]
    assert "locationLongitude(WGS84)" in payload["payload"]
    assert "batteryLevel(%)" in payload["payload"]


def test_fixture_smoke_plan_is_manual_only_and_does_not_execute_network() -> None:
    plan = build_pi_fixture_smoke_plan(load_profile(), OBSERVATION_PATH)

    assert plan.status == "manual_smoke_ready"
    assert plan.boundary.network_calls_performed is False
    assert plan.boundary.safety_mutation_performed is False
    assert plan.boundary.operator_must_execute is True
    assert plan.boundary.outbound_messages_allowed is False
    assert plan.counts.command_count == 4
    assert plan.counts.safety_mutation_command_count == 1
    assert plan.commands[-1].method == "POST"
    assert plan.commands[-1].url == "http://scout.local:9099/safety/observations"
    assert str(OBSERVATION_PATH) in plan.commands[-1].example_command


def test_fixture_smoke_plan_blocks_non_ready_target_profile() -> None:
    payload = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    payload["ai_inference_enabled"] = True
    profile = ScoutHardwarePrototypeTargetProfile.model_validate(payload)

    plan = build_pi_fixture_smoke_plan(profile, OBSERVATION_PATH)

    assert plan.status == "blocked"
    assert "ai_inference_must_stay_disabled_for_step1" in plan.blockers
    assert plan.commands == []
