from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from scout.schemas.mser import SignalAvailability
from scout.services.mser_projectors import (
    project_scenario_context,
    project_total_info,
)
from scout.services.mser_state_store import (
    MSERStateStore,
    StateVersionConflictError,
)
from scout_ai_six_forces_scenarios import ScenarioContext, SourceArtifactRef


NOW = datetime(2026, 7, 24, 8, 0, tzinfo=UTC)


def _scenario(
    scenario_id: str,
    *,
    overlays: tuple[str, ...],
    risk: dict[str, object] | None = None,
    observed_at: datetime = NOW,
    fix_quality: str = "synthetic_route_interpolation",
) -> ScenarioContext:
    return ScenarioContext(
        scenario_id=scenario_id,
        source_mode="synthetic_replay",
        project_id="chilai_nanhua_day1",
        observed_at=observed_at.isoformat(),
        boss_point_id="boss-03",
        boss_rank=3,
        lat=24.073,
        lon=121.286,
        elevation_m=3_060.0,
        horizontal_accuracy_m=5.0,
        fix_quality=fix_quality,
        route_progress_m=18_200.0,
        distance_to_boss_along_route_m=500.0,
        nearest_cp_id="CP-18",
        nearest_cp_route_progress_m=18_050.0,
        nearest_route_distance_m=4.0,
        heading_deg=72.0,
        travel_direction="increasing_route_progress",
        risk_terrain_candidate={
            "risk_score": 22.0,
            "risk_bucket": "low",
            "exposure_risk": 0.18,
            "slip_risk": 0.2,
            "rockfall_risk": 0.12,
            "escape_cost": 0.32,
            "terrain_complexity": 0.36,
            **(risk or {}),
            "candidate_only": True,
            "runtime_safety_truth": False,
        },
        source_refs=[
            SourceArtifactRef(
                role="risk_ribbon",
                path="outputs/risk/risk_ribbon.geojson",
                sha256="a" * 64,
            ),
            SourceArtifactRef(
                role="terrain_samples",
                path="outputs/layers/normalized/terrain_route_samples.geojson",
                sha256="b" * 64,
            ),
        ],
        condition_overlay_refs=list(overlays),
    )


def _five_scenarios() -> dict[str, ScenarioContext]:
    common = ("communication:reliable", "mission:on_schedule")
    return {
        "normal": _scenario(
            "scenario-1-normal",
            overlays=(*common, "weather:stable", "human:normal", "daylight:ample"),
        ),
        "rain_fog": _scenario(
            "scenario-2-rain-fog",
            overlays=(
                *common,
                "weather:rain_fog",
                "human:normal",
                "daylight:ample",
            ),
        ),
        "dark": _scenario(
            "scenario-3-dark",
            overlays=(*common, "weather:stable", "human:normal", "daylight:dark"),
        ),
        "cliff": _scenario(
            "scenario-4-cliff",
            overlays=(*common, "weather:stable", "human:normal", "daylight:ample"),
            risk={
                "risk_score": 94.0,
                "risk_bucket": "extreme",
                "exposure_risk": 0.96,
                "slip_risk": 0.82,
                "rockfall_risk": 0.78,
                "escape_cost": 0.93,
                "terrain_complexity": 0.91,
            },
        ),
        "fatigue": _scenario(
            "scenario-5-fatigue",
            overlays=(
                *common,
                "weather:stable",
                "human:fatigue_decline",
                "daylight:ample",
            ),
        ),
    }


def test_five_scenarios_project_to_distinct_compact_states() -> None:
    projected = {
        name: project_scenario_context(scenario, now=NOW)
        for name, scenario in _five_scenarios().items()
    }

    assert (
        projected["rain_fog"].weather.weather_stability.value
        < projected["normal"].weather.weather_stability.value
    )
    assert (
        projected["rain_fog"].terrain.visibility.value
        < projected["normal"].terrain.visibility.value
    )
    assert projected["dark"].operation.remaining_daylight.value == 0.0
    assert (
        projected["cliff"].terrain.exposure_risk.value
        > projected["normal"].terrain.exposure_risk.value
    )
    assert (
        projected["fatigue"].human.fatigue_index.value
        > projected["normal"].human.fatigue_index.value
    )
    assert (
        projected["fatigue"].human.energy_reserve.value
        < projected["normal"].human.energy_reserve.value
    )
    assert len({item.representation_id for item in projected.values()}) == 5


def test_every_available_scenario_signal_has_provenance_confidence_and_freshness() -> (
    None
):
    for scenario in _five_scenarios().values():
        representation = project_scenario_context(scenario, now=NOW)
        for signal in representation.all_signals():
            if signal.availability != SignalAvailability.AVAILABLE:
                continue
            assert signal.source_refs
            assert signal.confidence > 0.0
            assert signal.observed_at is not None
            assert signal.valid_until is not None


def test_stale_and_unknown_navigation_remain_explicit() -> None:
    stale = project_scenario_context(
        _scenario(
            "scenario-stale",
            overlays=("weather:stable",),
            observed_at=NOW - timedelta(hours=2),
        ),
        now=NOW,
    )
    unknown = project_scenario_context(
        _scenario(
            "scenario-unknown",
            overlays=("weather:stable",),
            fix_quality="stale_unknown",
        ),
        now=NOW,
    )

    assert stale.operation.gps_confidence.availability == SignalAvailability.STALE
    assert unknown.operation.gps_confidence.availability == SignalAvailability.MISSING
    assert unknown.operation.gps_confidence.value is None
    assert unknown.operation.route_alignment.availability == SignalAvailability.MISSING


def test_total_info_projection_uses_real_context_shapes_without_safe_defaults() -> None:
    total_info = {
        "artifact_kind": "assistant_workspace_total_info_context",
        "artifact_version": "assistant_workspace_total_info_context.v0",
        "project_id": "chilai_nanhua_day1",
        "candidate_only": True,
        "runtime_safety_truth": False,
        "route_context": {
            "status": "available",
            "source_path": "normalized/routes/route_summary.json",
            "distance_m": 44_200.0,
        },
        "location_context": {
            "status": "available",
            "source": "assistant_query.live_navigation_snapshot",
            "route_match_available": True,
            "live_navigation_snapshot": {
                "observed_at": NOW.isoformat(),
                "fix_quality": "3d_fix",
                "horizontal_accuracy_m": 4.5,
                "confidence": 0.94,
                "nearest_route_distance_m": 3.0,
                "route_progress_m": 18_200.0,
            },
        },
        "body_resource_context": {
            "status": "available",
            "observed_at": NOW.isoformat(),
            "source_path": "outputs/health/energy_vitals_snapshot.json",
            "energy_reserve_band": "high",
        },
        "weather_environment_context": {
            "status": "available",
            "freshness": {"cwa_qpf": "fresh"},
            "cwa_qpf": {
                "status": "available",
                "source_path": "outputs/environment/cwa/qpf_corridor_summary.json",
                "generated_at": NOW.isoformat(),
                "forecast_valid_until": (NOW + timedelta(hours=6)).isoformat(),
                "max_rain_probability": 0.78,
                "max_observed_24h_mm": 48.0,
            },
            "gee_gpm": {
                "status": "available",
                "source_path": "outputs/environment/gee/gpm_corridor_summary.json",
                "generated_at": NOW.isoformat(),
                "values": {"trend": "increasing"},
            },
        },
        "terrain_risk_context": {
            "status": "available",
            "risk_route_profile": {
                "status": "available",
                "source_path": "outputs/risk/risk_route_profile_metadata.json",
                "generated_at": NOW.isoformat(),
                "score_summary": {"mean_score": 61.0, "max_score": 89.0},
            },
        },
        "communication_context": {
            "status": "available",
            "observed_at": NOW.isoformat(),
            "source_path": "outputs/communication/current_reachability.json",
            "communication_reliability": 0.76,
            "coverage_confidence": 0.7,
            "emergency_reachability": 0.68,
        },
        "mission_context": {
            "status": "available",
            "observed_at": NOW.isoformat(),
            "source_path": "outputs/mission/current_margin.json",
            "remaining_daylight_minutes": 210.0,
            "team_distance_m": 16.0,
            "mission_margin": 0.72,
        },
        "sensor_snapshot_context": {"status": "not_configured"},
    }

    representation = project_total_info(total_info, now=NOW)

    assert representation.operation.gps_confidence.value == pytest.approx(0.94)
    assert representation.operation.route_progress.value == pytest.approx(18_200.0)
    assert representation.human.energy_reserve.value == pytest.approx(0.82)
    assert representation.weather.weather_stability.value < 0.5
    assert representation.communication.emergency_reachability.value == pytest.approx(
        0.68
    )
    assert (
        representation.operation.water_margin.availability == SignalAvailability.MISSING
    )
    assert representation.operation.water_margin.value is None
    for signal in representation.all_signals():
        if signal.availability != SignalAvailability.AVAILABLE:
            continue
        assert signal.source_refs
        assert signal.confidence > 0.0
        assert signal.observed_at is not None
        assert signal.valid_until is not None


def test_state_store_publishes_immutable_versioned_snapshots() -> None:
    projected = {
        name: project_scenario_context(scenario, now=NOW)
        for name, scenario in _five_scenarios().items()
    }
    store = MSERStateStore(clock=lambda: NOW)

    first = store.publish(projected["normal"], reason="scenario-1")
    second = store.publish(
        projected["rain_fog"],
        reason="scenario-2",
        expected_version=first.version,
    )

    assert first.version == 1
    assert second.version == 2
    assert second.parent_version == 1
    assert store.current().snapshot_id == second.snapshot_id
    assert tuple(item.version for item in store.history()) == (1, 2)
    assert second.materialize().runtime_safety_truth is False
    assert second.phase1_safety_mutation_allowed is False

    with pytest.raises(ValidationError):
        second.version = 99

    materialized = first.materialize()
    materialized.representation_id = "caller-mutated-copy"
    assert first.materialize().representation_id != "caller-mutated-copy"

    with pytest.raises(StateVersionConflictError):
        store.publish(
            projected["dark"],
            reason="stale-writer",
            expected_version=1,
        )
