from __future__ import annotations

import json
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scout_body_index import (
    aggregate_body_index_sources,
    attach_pace_fit_mappings,
    build_body_index_source_analysis,
    flat_ground_metabolic_cost,
)


TZ = timezone(timedelta(hours=8))


def _stamp(seconds: int, *, start: datetime = datetime(2026, 1, 1, tzinfo=TZ)) -> str:
    return (start + timedelta(seconds=seconds)).strftime("%Y-%m-%d %H:%M:%S %z")


def _write_export(
    path: Path,
    *,
    phases: list[tuple[int, int, str]],
    energy_kj: float = 0.1,
    cadence_scale: float = 1.0,
    granularity: int = 1,
    include_daily_metrics: bool = False,
    scalar_energy_factor: float = 1.0,
) -> None:
    end_seconds = max(end for _, end, _ in phases)
    timestamps = list(range(0, end_seconds, granularity))
    active_energy = []
    distance = []
    steps = []
    heart_rate = []
    for second in timestamps:
        phase = next((name for start, end, name in phases if start <= second < end), "missing")
        if phase == "running":
            speed_mps, cadence_spm, hr = 2.4, 180, 150
        elif phase == "walking":
            speed_mps, cadence_spm, hr = 1.0, 90, 115
        elif phase == "stop":
            speed_mps, cadence_spm, hr = 0.0, 0, 90
        else:
            speed_mps, cadence_spm, hr = None, None, None
        active_energy.append({"date": _stamp(second), "qty": energy_kj, "units": "kJ"})
        if speed_mps is not None:
            distance.append({"date": _stamp(second), "qty": speed_mps * granularity / 1000, "units": "km"})
            steps.append({"date": _stamp(second), "qty": cadence_spm * granularity / 60, "units": "步"})
        if hr is not None:
            heart_rate.append({"date": _stamp(second), "qty": hr, "units": "bpm"})
    workout = {
        "id": "synthetic-activity",
        "name": "戶外 跑步",
        "start": _stamp(0),
        "end": _stamp(end_seconds),
        "duration": end_seconds,
        "distance": {"qty": sum(item["qty"] for item in distance), "units": "km"},
        "activeEnergyBurned": {
            "qty": energy_kj * len(active_energy) / 4.184 * scalar_energy_factor,
            "units": "kcal",
        },
        "activeEnergy": active_energy,
        "walkingAndRunningDistance": distance,
        "stepCount": steps,
        "heartRateData": [
            {"date": item["date"], "Avg": item["qty"], "Min": item["qty"], "Max": item["qty"], "units": "bpm"}
            for item in heart_rate
        ],
    }
    data: dict[str, object] = {"workouts": [workout]}
    if include_daily_metrics:
        data["metrics"] = [
            {
                "name": "active_energy",
                "units": "kJ",
                "data": [{"date": _stamp(0), "qty": 120.0, "units": "kJ"}],
            },
            {
                "name": "basal_energy_burned",
                "units": "kJ",
                "data": [{"date": _stamp(0), "qty": 100.0, "units": "kJ"}],
            },
        ]
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("HealthAutoExport.json", json.dumps({"data": data}))


def test_body_index_classifies_run_walk_run_stop_and_preserves_gap_as_unknown(tmp_path: Path) -> None:
    path = tmp_path / "export.zip"
    _write_export(
        path,
        phases=[
            (0, 30, "running"),
            (30, 50, "walking"),
            (50, 80, "running"),
            (80, 95, "stop"),
            # 95-300 intentionally has no speed/cadence/HR samples.
            (300, 335, "running"),
        ],
    )
    analysis = build_body_index_source_analysis(path)
    activity = analysis["activities"][0]
    states = [segment["state"] for segment in activity["segments"]]
    assert "running" in states
    assert "walking" in states
    assert "stop" in states
    assert "unknown" in states
    assert activity["classification_status"] == "estimated_from_time_series"
    assert all("classification_basis" in segment for segment in activity["segments"])
    assert all("confidence" in segment for segment in activity["segments"])
    assert all("data_coverage" in segment for segment in activity["segments"])
    assert any(
        any("heart_rate" in basis for basis in segment["classification_basis"])
        for segment in activity["segments"]
    )
    transitions = activity["transition_events"]
    assert any(event["to_state"] == "walking" and event["recovered_to_running"] for event in transitions)
    assert all("failure" in event["interpretation"] or "observation" in event["interpretation"] for event in transitions)


def test_active_energy_interval_values_are_summed_once_and_kcal_converted(tmp_path: Path) -> None:
    path = tmp_path / "export.zip"
    _write_export(path, phases=[(0, 10, "running")], energy_kj=0.1)
    analysis = build_body_index_source_analysis(path)
    activity = analysis["activities"][0]
    assert activity["active_energy_kj"] == pytest.approx(1.0)
    assert activity["active_energy_kcal"] == pytest.approx(1.0 / 4.184, abs=1e-5)
    assert activity["active_energy_rate_w"] == pytest.approx(100.0, abs=0.1)
    assert activity["scalar_energy_added"] is False
    assert "sum_interval_activeEnergy_kJ" in activity["active_energy_unit_basis"]


def test_minute_granularity_does_not_turn_interval_energy_into_power_by_multiplication(tmp_path: Path) -> None:
    path = tmp_path / "minute.zip"
    _write_export(path, phases=[(0, 600, "running")], energy_kj=6.0, granularity=60)
    analysis = build_body_index_source_analysis(path)
    activity = analysis["activities"][0]
    assert activity["active_energy_kj"] == pytest.approx(60.0)
    assert activity["active_energy_rate_w"] == pytest.approx(100.0, abs=0.1)


def test_duplicate_exports_are_not_added_twice_and_daily_static_is_separate(tmp_path: Path) -> None:
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    _write_export(first, phases=[(0, 600, "running")], energy_kj=0.1, include_daily_metrics=True)
    _write_export(
        second,
        phases=[(0, 600, "running")],
        energy_kj=0.1,
        include_daily_metrics=True,
        scalar_energy_factor=1.5,
    )
    first_analysis = build_body_index_source_analysis(first)
    second_analysis = build_body_index_source_analysis(second)
    aggregate = aggregate_body_index_sources([first_analysis, second_analysis])
    assert aggregate["observations"]["activity_count"] == 1
    assert aggregate["observations"]["all_activity_active_energy_kj"] == pytest.approx(60.0)
    daily = aggregate["daily_energy"]
    assert daily["complete_active_day_count"] == 1
    assert daily["complete_static_day_count"] == 1
    row = daily["days"][0]
    assert row["all_activity_energy_kj"] == pytest.approx(120.0)
    assert row["static_energy_kj"] == pytest.approx(100.0)
    assert row["total_energy_kj"] == pytest.approx(220.0)
    assert row["same_day_run_fraction"] == pytest.approx(0.5)
    assert row["same_day_fraction_status"] == "available"


def test_sustained_windows_do_not_extrapolate_short_run_and_keep_source_refs(tmp_path: Path) -> None:
    path = tmp_path / "short.zip"
    _write_export(path, phases=[(0, 600, "running")], energy_kj=0.1)
    aggregate = aggregate_body_index_sources([build_body_index_source_analysis(path)])
    windows = aggregate["sustained_output"]["windows"]
    assert windows["300"]["status"] == "available"
    assert windows["600"]["status"] == "available"
    assert windows["900"]["status"] == "unavailable"
    assert windows["1200"]["status"] == "unavailable"
    assert windows["600"]["source_segment_refs"]


def test_flat_cost_uses_70kg_assumption_and_marks_out_of_range() -> None:
    result = flat_ground_metabolic_cost(1.0, "walking")
    assert result["body_mass_kg"] == 70
    assert result["body_mass_basis"] == "user_assumption"
    assert result["grade_fraction"] == 0
    assert result["estimated_active_energy_w"] == pytest.approx(146.4, abs=1.0)
    assert result["resting_component_excluded"] is True
    assert flat_ground_metabolic_cost(0.4, "walking")["status"] == "outside_validated_speed_range"
    adjusted = flat_ground_metabolic_cost(1.0, "walking", body_mass_kg=80)
    assert adjusted["body_mass_kg"] == 80
    assert adjusted["body_mass_basis"] == "user_assumption"
    assert adjusted["estimated_active_energy_w"] > result["estimated_active_energy_w"]


def test_pace_fit_requires_explicit_architecture_speed_mapping() -> None:
    payload = {
        "pairs": [
            {
                "pair_id": "a__b",
                "from_route_distance_m": 0,
                "to_route_distance_m": 1000,
                "distance_m": 1000,
                "reference_available": True,
                "duration_minutes": {"average": 20},
            }
        ]
    }
    body = {"flat_speed_by_mode": {"walking": {"median_speed_mps": 1.0}}}
    unavailable = attach_pace_fit_mappings(payload, body)
    assert unavailable["pairs"][0]["personal_mapping"]["status"] == "unavailable"
    assert unavailable["pace_fit_mapping"]["status"] == "unavailable"
    mapped = attach_pace_fit_mappings(
        payload,
        body,
        {"segment_demand_vectors": [{"start_distance_m": 0, "end_distance_m": 1000, "pace_speed_correction_ratio": 0.5}]},
    )
    mapping = mapped["pairs"][0]["personal_mapping"]
    assert mapping["status"] == "available"
    assert mapping["expected_minutes"] == pytest.approx(33.333, abs=0.01)
    assert mapping["pace_fit_percent"] == pytest.approx(167, abs=1)
    assert mapping["energy_not_used_as_time_ratio"] is True
