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
    workout_id: str = "synthetic-activity",
    start: datetime = datetime(2026, 1, 1, tzinfo=TZ),
    energy_units: str = "kJ",
    daily_active_kj: float = 120.0,
    daily_static_kj: float = 100.0,
) -> None:
    end_seconds = max(end for _, end, _ in phases)
    timestamps = list(range(0, end_seconds, granularity))
    active_energy = []
    distance = []
    steps = []
    heart_rate = []
    for second in timestamps:
        phase = next((name for phase_start, end, name in phases if phase_start <= second < end), "missing")
        if phase == "running":
            speed_mps, cadence_spm, hr = 2.4, 180, 150
        elif phase == "walking":
            speed_mps, cadence_spm, hr = 1.0, 90, 115
        elif phase == "stop":
            speed_mps, cadence_spm, hr = 0.0, 0, 90
        else:
            speed_mps, cadence_spm, hr = None, None, None
        energy_value = energy_kj
        if energy_units.lower() in {"kcal", "kilocalorie", "kilocalories"}:
            energy_value = energy_kj / 4.184
        elif energy_units.lower() in {"j", "joule", "joules"}:
            energy_value = energy_kj * 1000.0
        active_energy.append({"date": _stamp(second, start=start), "qty": energy_value, "units": energy_units})
        if speed_mps is not None:
            distance.append({"date": _stamp(second, start=start), "qty": speed_mps * granularity / 1000, "units": "km"})
            steps.append({"date": _stamp(second, start=start), "qty": cadence_spm * granularity / 60, "units": "步"})
        if hr is not None:
            heart_rate.append({"date": _stamp(second, start=start), "qty": hr, "units": "bpm"})
    workout = {
        "id": workout_id,
        "name": "戶外 跑步",
        "start": _stamp(0, start=start),
        "end": _stamp(end_seconds, start=start),
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
                "data": [{"date": _stamp(0, start=start), "qty": daily_active_kj, "units": "kJ"}],
            },
            {
                "name": "basal_energy_burned",
                "units": "kJ",
                "data": [{"date": _stamp(0, start=start), "qty": daily_static_kj, "units": "kJ"}],
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
    assert transitions[0]["cumulative_active_energy_before_transition_kj"] == pytest.approx(3.0)
    assert transitions[1]["cumulative_active_energy_before_transition_kj"] == pytest.approx(8.0)
    assert all("failure" in event["interpretation"] or "observation" in event["interpretation"] for event in transitions)
    aggregate = aggregate_body_index_sources([analysis])
    assert aggregate["observations"]["run_active_energy_kj"] == pytest.approx(9.5)
    assert aggregate["observations"]["walk_active_energy_kj"] == pytest.approx(2.0)
    assert aggregate["observations"]["stop_active_energy_kj"] == pytest.approx(1.5)
    assert aggregate["observations"]["unknown_segment_active_energy_kj"] > 0
    cross_check = aggregate["energy_cross_check"]
    assert cross_check["status"] == "available"
    assert cross_check["watch_source"].startswith("HealthExport interval activeEnergy")
    assert cross_check["model_source"].startswith("ACSM flat-ground")
    assert cross_check["difference_watch_minus_model_kj"] == pytest.approx(
        cross_check["watch_interval_active_energy_kj_on_comparable_segments"]
        - cross_check["flat_ground_model_active_energy_kj"]
    )


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


def test_energy_input_units_are_normalized_before_interval_sum(tmp_path: Path) -> None:
    path = tmp_path / "kcal.zip"
    _write_export(
        path,
        phases=[(0, 10, "running")],
        energy_kj=1.0,
        energy_units="kcal",
    )
    activity = build_body_index_source_analysis(path)["activities"][0]
    assert activity["active_energy_kj"] == pytest.approx(10.0)
    assert activity["active_energy_kcal"] == pytest.approx(10.0 / 4.184, abs=1e-5)
    assert activity["active_energy_unit_basis"].startswith("sum_interval_activeEnergy_kJ")


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


def test_daily_energy_splits_cross_midnight_and_uses_running_segments_for_ratios(tmp_path: Path) -> None:
    path = tmp_path / "cross-midnight.zip"
    start = datetime(2026, 1, 1, 23, 59, 30, tzinfo=TZ)
    _write_export(
        path,
        phases=[(0, 90, "running")],
        energy_kj=1.0,
        start=start,
        include_daily_metrics=False,
    )
    analysis = build_body_index_source_analysis(path)
    activity = analysis["activities"][0]
    assert activity["daily_energy_by_date"]["2026-01-01"]["all_active_energy_kj"] == pytest.approx(30.0)
    assert activity["daily_energy_by_date"]["2026-01-02"]["all_active_energy_kj"] == pytest.approx(60.0)

    daily = aggregate_body_index_sources([analysis])["daily_energy"]
    assert daily["date_range"] == {"start": "2026-01-01", "end": "2026-01-02"}
    assert [row["all_activity_energy_kj"] for row in daily["days"]] == [30.0, 60.0]
    assert [row["same_day_run_fraction"] for row in daily["days"]] == [1.0, 1.0]
    assert daily["mean_daily_active_energy_kj"] == pytest.approx(45.0)
    assert daily["days"][1]["run_energy_vs_mean_active_baseline"] == pytest.approx(60.0 / 45.0, abs=1e-5)
    assert daily["complete_active_day_count"] == 2
    assert daily["complete_static_day_count"] == 0
    assert daily["complete_total_day_count"] == 0
def test_conflicting_daily_metric_candidates_are_not_summed_or_filled_from_workouts(tmp_path: Path) -> None:
    first = tmp_path / "conflict-a.zip"
    second = tmp_path / "conflict-b.zip"
    _write_export(
        first,
        phases=[(0, 10, "running")],
        energy_kj=1.0,
        include_daily_metrics=True,
        daily_active_kj=100.0,
        workout_id="conflict-a",
    )
    _write_export(
        second,
        phases=[(0, 10, "running")],
        energy_kj=1.0,
        include_daily_metrics=True,
        daily_active_kj=110.0,
        workout_id="conflict-b",
    )
    daily = aggregate_body_index_sources(
        [build_body_index_source_analysis(first), build_body_index_source_analysis(second)]
    )["daily_energy"]
    row = next(item for item in daily["days"] if item["date"] == "2026-01-01")
    assert row["all_activity_energy_kj"] is None
    assert row["same_day_fraction_status"].startswith("unavailable")
    assert row["active_energy_basis"].startswith("unavailable: conflicting")
    assert daily["mean_daily_active_energy_kj"] is None


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
