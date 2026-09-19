from __future__ import annotations

from scout_pace_correction_calibration import (
    PANDOLF_POWER_DOMAIN,
    apply_successful_climb_calibration,
    architecture_route_power_summary,
    default_pace_correction_calibration,
    pandolf_metabolic_power_w,
)


def test_pandolf_power_keeps_route_conditions_in_one_declared_domain() -> None:
    flat = pandolf_metabolic_power_w(1.0, body_mass_kg=70)
    uphill = pandolf_metabolic_power_w(
        1.0,
        body_mass_kg=70,
        load_kg=10,
        grade_fraction=0.10,
        terrain_factor=2.0,
        psychological_stress_multiplier=1.1,
    )
    assert flat["status"] == "available"
    assert uphill["status"] == "available"
    assert flat["power_domain"] == PANDOLF_POWER_DOMAIN
    assert uphill["power_w"] > flat["power_w"]
    assert uphill["not_mechanical_power"] is True
    assert uphill["not_provider_active_energy"] is True


def test_route_power_is_time_weighted_at_fixed_reference_schedule_speed() -> None:
    result = architecture_route_power_summary(
        [
            {
                "start_distance_m": 0,
                "end_distance_m": 1000,
                "reference_speed_kmh": {"p50": 3.6},
                "signed_grade_ratio_p50": 0,
            },
            {
                "start_distance_m": 1000,
                "end_distance_m": 2000,
                "reference_speed_kmh": {"p50": 1.8},
                "signed_grade_ratio_p50": 0.1,
            },
        ],
        body_mass_kg=70,
        load_kg=0,
        terrain_factor=1,
        psychological_stress_multiplier=1,
    )
    assert result["status"] == "available"
    assert result["power_domain"] == PANDOLF_POWER_DOMAIN
    assert result["usable_bin_count"] == 2
    assert result["covered_distance_m"] == 2000
    assert result["route_total_power_w"] > 0
    assert result["route_total_energy_kj"] > 0
    assert "schedule" in result["speed_basis"]


def test_default_calibration_is_one_but_explicitly_unvalidated() -> None:
    calibration = default_pace_correction_calibration("route-a")
    assert calibration["correction_ratio"] == 1
    assert calibration["status"] == "prior_uninformed"
    assert calibration["calibrated_success_count"] == 0
    assert calibration["prior"]["basis"].startswith("no successful")
    assert calibration["boundary"]["candidate_only"] is True


def test_calibration_rejects_domain_mismatch_and_duplicate_receipts() -> None:
    prior = default_pace_correction_calibration("route-a")
    mismatch = apply_successful_climb_calibration(
        prior,
        {
            "climb_id": "climb-1",
            "success": True,
            "completion_status": "completed",
            "power_domain": "apple_active_energy_w",
            "route_total_power_w": 200,
            "body_flat_total_power_w": 100,
        },
        project_id="route-a",
    )
    assert mismatch["correction_ratio"] == 1
    assert mismatch["last_update"]["reason"] == "power_domain_mismatch"

    accepted = apply_successful_climb_calibration(
        prior,
        {
            "climb_id": "climb-1",
            "success": True,
            "completion_status": "completed",
            "power_domain": PANDOLF_POWER_DOMAIN,
            "route_total_power_w": 200,
            "body_flat_total_power_w": 100,
        },
        project_id="route-a",
    )
    duplicate = apply_successful_climb_calibration(
        accepted,
        {
            "climb_id": "climb-1",
            "success": True,
            "completion_status": "completed",
            "power_domain": PANDOLF_POWER_DOMAIN,
            "route_total_power_w": 900,
            "body_flat_total_power_w": 100,
        },
        project_id="route-a",
    )
    assert duplicate["correction_ratio"] == accepted["correction_ratio"]
    assert duplicate["calibrated_success_count"] == 1
    assert duplicate["last_update"]["reason"] == "duplicate_climb_receipt"
