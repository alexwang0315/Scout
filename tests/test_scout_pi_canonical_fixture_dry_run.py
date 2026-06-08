from __future__ import annotations

from pathlib import Path

from observation_adapter import sensorlog_payload_to_observations
from scout_pi_fixture_smoke import (
    build_canonical_fixture_local_dry_run,
    load_manual_observation_fixture,
)


ROOT = Path(__file__).resolve().parents[1]
MISSION_PATH = ROOT / "tests" / "fixtures" / "mission_graph" / "normal_climb_mission.json"
CANONICAL_FIXTURE_PATH = Path(
    "tests/fixtures/hardware/manual_observation_smoke.canonical.example.json"
)


def test_canonical_manual_observation_fixture_uses_adapter_keys() -> None:
    fixture = load_manual_observation_fixture(CANONICAL_FIXTURE_PATH)
    payload = fixture["payload"]

    assert fixture["device"] == "apple_watch"
    assert fixture["source"] == "fixture_hardware_smoke_canonical"
    for key in (
        "locationLatitude",
        "locationLongitude",
        "locationHorizontalAccuracy",
        "accelerometerAccelerationX",
        "accelerometerAccelerationY",
        "accelerometerAccelerationZ",
        "batteryLevel",
        "pedometerDistance",
        "pedometerNumberOfSteps",
    ):
        assert key in payload

    assert "locationLatitude(WGS84)" not in payload
    assert "batteryLevel(%)" not in payload


def test_canonical_fixture_capabilities_are_available_before_runtime_dry_run() -> None:
    fixture = load_manual_observation_fixture(CANONICAL_FIXTURE_PATH)

    observation = sensorlog_payload_to_observations(
        fixture["payload"],
        device=fixture["device"],
        source=fixture["source"],
        received_at=fixture["received_at"],
    )[0]
    capabilities = observation.raw["capabilities"]

    for name in (
        "gps",
        "gps_horizontal_accuracy",
        "imu",
        "battery",
        "pedometer_distance",
        "pedometer_steps",
    ):
        assert capabilities[name]["status"] == "available"


def test_canonical_fixture_local_dry_run_is_route_aware_and_target_read_only() -> None:
    result = build_canonical_fixture_local_dry_run(
        CANONICAL_FIXTURE_PATH,
        mission_graph_path=MISSION_PATH,
    )

    assert result.status == "passed"
    assert result.blockers == []
    assert result.safety_level == "L0_NORMAL"
    assert result.counts.observations_delta == 1
    assert result.counts.checkpoint_hits_delta == 1
    assert result.counts.incident_file_count == 0
    assert "cp_01" in result.checkpoint_ids
    assert set(result.available_capabilities).issuperset(
        {
            "gps",
            "gps_horizontal_accuracy",
            "imu",
            "battery",
            "pedometer_distance",
            "pedometer_steps",
        }
    )
    assert result.boundary.local_runtime_only is True
    assert result.boundary.target_network_calls_performed is False
    assert result.boundary.target_safety_mutation_performed is False
    assert result.boundary.local_safety_mutation_performed is True
    assert result.boundary.outbound_messages_allowed is False
    assert result.boundary.local_model_start_allowed is False
    assert result.boundary.hardware_provider_control_allowed is False
