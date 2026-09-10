"""A real Planned branch and timetable reach existing deterministic assessors."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from scout_planned_analysis_inputs import build_planned_analysis_inputs, digest
from scout_planned_analysis_producers import run_planned_analyses
from scout_planned_route import compile_planned_route
from scout_planned_route_models import PlannedRouteConflict
from test_scout_planned_route import planned_workspace, _write


def _bundle(root, **kwargs):
    preview = compile_planned_route(root, {"departure_at": "2026-10-01T06:00:00+08:00", **kwargs})
    return {"preview": preview, "manifest": {"project_id": root.name, "version_id": "plan.test",
            "manifest_sha256": digest(preview), "geometry_sha256": preview["geometry_sha256"],
            "itinerary_sha256": preview["itinerary_sha256"], "source_hashes": preview["source_hashes"], "files": {}}}


def _hashes(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


def _raw(run, result, role):
    return json.loads((run / result["projections"][role]["artifact_ref"]).read_text())["result"]


def test_real_branch_reaches_all_six_assessors_without_owner_or_bundle_writes(tmp_path):
    root = planned_workspace(tmp_path)
    bundle = _bundle(root, human_text="從營地 A 單攻山頭 B 後回營地 A；在山頭 B 停留 40 分鐘", default_speed_kmh=2)
    original, before = copy.deepcopy(bundle), _hashes(root)
    run = tmp_path / "analysis.run.branch"
    result = run_planned_analyses(root, bundle, run, {"coverage": {"status": "unverified"}})
    assert set(result["projections"]) == {"permission", "pace_fit", "architecture", "navigation", "weather", "route_context"}
    assert all(p["status"] != "blocked" for p in result["projections"].values()), result["projections"]
    architecture = _raw(run, result, "architecture")
    graph = architecture["full_route_graph"]
    assert max(n["lon"] for n in graph["nodes"]) == 121.002
    assert len(graph["edges"]) >= 4
    assert graph["reviewed_mission_graph"] is False
    assert graph["edges"][-1]["to_m"] == bundle["preview"]["route_axis"][-1]["route_order_m"]
    permission = _raw(run, result, "permission")
    assert permission["planned_stops"][0]["duration_minutes"] == 40
    assert permission["safety_buffer_derived_from_travel_time"] is False
    assert _raw(run, result, "pace_fit")["day_assessments"][0]["assessment"]["schedule_pressure"]["minutes_to_next_cp"] is not None
    history = architecture["reference_segment_timing"]
    assert history["counts"]["eligible_historical_source_file_count"] == 2
    assert history["counts"]["measurement_count"] > 0
    assert history["method"]["checkpoint_source"] == "explicit_target_route_axis"
    assert history["historical_observations_created"] is False
    assert {s["from_m"] for s in history["segments"]} <= {s["from_m"] for s in graph["edges"]}
    for projection in result["projections"].values():
        path = run / projection["artifact_ref"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == projection["artifact_sha256"]
        assert projection["input_binding"]["geometry_sha256"] == bundle["manifest"]["geometry_sha256"]
        assert projection["candidate_only"] is True and projection["runtime_safety_truth"] is False
    assert _hashes(root) == before and bundle == original
    project = json.loads((run / result["workspace_ref"] / "project.json").read_text())
    assert not any("reviewed_mission" in key or "golden" in key for key in project)
    assert result["status"] == "partial"


def test_gap_never_creates_cp_edge_and_cross_midnight_stop_keeps_dates(tmp_path):
    root = planned_workspace(tmp_path)
    bundle = _bundle(root, human_text="在觀景點 C 停留 40 分鐘", departure_at="2026-10-01T23:50:00+08:00")
    # Recorded source gap retained by a saved candidate, not repaired by adapter.
    bundle["preview"]["route_axis"][2]["break_before"] = True
    result = build_planned_analysis_inputs(root, bundle, tmp_path / "run.gap", {})
    assert result["gaps"]
    assert not any(e["start_point_index"] < 2 <= e["end_point_index"] for e in result["graph"]["edges"])
    estimates = result["planned_eta"]["estimates"]
    assert estimates[-1]["eta"].startswith("2026-10-02")
    assert all(e["time_role"] == "planned_estimate" and e["recorded_track"] is False for e in estimates)


def test_weather_rejects_old_forecast_instead_of_first_point_fallback(tmp_path):
    root = planned_workspace(tmp_path)
    _write(root, "normalized/weather/forecast_snapshots.json", {"weather_points": [
        {"lat": 24.001, "lon": 121, "areaName": "test", "validFrom": "2026-09-09T00:00:00+08:00",
         "validTo": "2026-09-10T00:00:00+08:00", "rainProbability": 0, "temperatureC": 18}]})
    run = tmp_path / "run.oldweather"
    result = run_planned_analyses(root, _bundle(root), run, {})
    weather = result["projections"]["weather"]
    assert weather["status"] == "partial"
    assert weather["result"]["matched_segment_count"] == 0
    assert weather["result"]["new_package_built"] is False
    assert "forecast_spatiotemporal_coverage" in {m["code"] for m in weather["missing_inputs"]}
    assert not (run / "workspaces/analysis/outputs/route_weather_package.json").exists()


def test_changed_preparation_identity_and_escape_are_rejected(tmp_path):
    root = planned_workspace(tmp_path)
    bundle = _bundle(root)
    with pytest.raises(PlannedRouteConflict, match="another"):
        build_planned_analysis_inputs(root, bundle, tmp_path / "run.identity", {"subject_binding": {"geometry_sha256": "0" * 64}})
    with pytest.raises(PlannedRouteConflict, match="inside"):
        build_planned_analysis_inputs(root, bundle, tmp_path / "run.escape", {"canonical_refs": {"route_axis": "../project.json"}})


def test_matching_weather_invokes_package_builder_with_planned_eta(tmp_path, monkeypatch):
    root = planned_workspace(tmp_path)
    _write(root, "normalized/weather/forecast_snapshots.json", {"weather_points": [
        {"lat": 24.001, "lon": 121, "areaName": "test", "validFrom": "2026-10-01T00:00:00+08:00",
         "validTo": "2026-10-02T00:00:00+08:00", "issued_at": "2026-10-01T00:00:00+08:00",
         "rainProbability": 10, "temperatureC": 18}]})
    import scout_weather_integration
    original = scout_weather_integration.build_route_weather_package
    calls = []
    def observed(**kwargs):
        calls.append(kwargs)
        return original(**kwargs)
    monkeypatch.setattr(scout_weather_integration, "build_route_weather_package", observed)
    run = tmp_path / "run.weather"
    result = run_planned_analyses(root, _bundle(root), run, {})
    assert calls
    assert all(c["route_segments"][0]["etaFrom"].startswith("2026-10-01") for c in calls)
    weather = result["projections"]["weather"]
    assert weather["result"]["matched_segment_count"] == len(calls)
    assert "planned_eta" in {s.get("source_kind") for s in _raw(run, result, "weather")["source_report"]}
    assert weather["status"] == "partial"  # No reviewed daylight or terrain risk.


def test_native_dem_samples_are_joined_to_exact_branch_visits_and_cp_edges(tmp_path):
    root = planned_workspace(tmp_path)
    bundle = _bundle(root, human_text="從營地 A 單攻山頭 B 後回營地 A", default_speed_kmh=2)
    run = tmp_path / "run.terrain"
    axis = bundle["preview"]["route_axis"]
    samples = [{"planned_point_index": p["point_index"], "lat": p["lat"], "lon": p["lon"],
                "elevation_m": p["ele"] + 10} for p in axis]
    ref = "terrain-parts/p0/outputs/planned_terrain_samples.json"
    sha = _write(run, ref, {"points": samples, "candidate_only": True, "runtime_safety_truth": False,
                           "sampling_method": "native_dem_cell_at_exact_planned_point", "resolution_m": [20,20]})
    preparation = {"terrain_parts": [{"status": "completed", "processor": "qgis_processing_grass", "planned_point_indices": list(range(len(axis))),
                    "output_refs": {"terrain_samples_ref": ref}, "source_hashes": {ref: sha}}]}
    result = run_planned_analyses(root, bundle, run, preparation)
    nav = _raw(run, result, "navigation")
    terrain = nav["route_terrain_analysis"]
    assert terrain["coverage"]["sampled_point_count"] == len(axis)
    assert terrain["coverage"]["unsupported_point_indices"] == []
    assert terrain["coverage"]["fully_sampled_segment_count"] == len(terrain["segments"])
    assert any(s["elevation_gain_m"] == 50 for s in terrain["segments"])
    assert any(s["elevation_loss_m"] == 50 for s in terrain["segments"])
    assert len([p for p in terrain["points"] if p["lon"] == 121.001]) >= 2
    assert nav["terrain_readiness"]["dtm_coverage_available"] is True
    assert "planned_terrain_coverage" not in {m["code"] for m in result["projections"]["navigation"]["missing_inputs"]}


def test_bound_planned_gpx_is_never_a_historical_sample(tmp_path):
    root = planned_workspace(tmp_path)
    bundle = _bundle(root)
    planned = bundle["preview"]["planned_gpx"]
    sha = _write(root, "inputs/a_planned_reference.gpx", planned)
    bundle["manifest"]["source_hashes"]["inputs/a_planned_reference.gpx"] = sha
    run = tmp_path / "run.plannedsource"
    result = run_planned_analyses(root, bundle, run, {})
    history = _raw(run, result, "architecture")["reference_segment_timing"]
    assert history["counts"]["planned_source_file_count"] == 1
    assert any(s["status"] == "excluded_planned_source" for s in history["source_time_quality"])


def test_source_change_during_real_assessment_rejects_publication(tmp_path, monkeypatch):
    root = planned_workspace(tmp_path)
    _write(root, "outputs/team_status.json", {"members": []})
    import scout_route_architecture_tool
    original = scout_route_architecture_tool.assess_scout_route_architecture
    def mutate(*args, **kwargs):
        _write(root, "outputs/team_status.json", {"members": [], "changed": True})
        return original(*args, **kwargs)
    monkeypatch.setattr(scout_route_architecture_tool, "assess_scout_route_architecture", mutate)
    with pytest.raises(PlannedRouteConflict, match="changed"):
        run_planned_analyses(root, _bundle(root), tmp_path / "run.race", {})


def test_source_symlink_is_rejected_even_when_target_stays_inside_owner(tmp_path):
    root = planned_workspace(tmp_path)
    _write(root, "inputs/actual_profile.json", {"members": []})
    (root / "outputs/team_status.json").symlink_to(root / "inputs/actual_profile.json")
    with pytest.raises(PlannedRouteConflict, match="symbolic"):
        run_planned_analyses(root, _bundle(root), tmp_path / "run.link", {})


def test_terrain_coordinate_tampering_is_rejected_after_valid_file_hash(tmp_path):
    root = planned_workspace(tmp_path)
    bundle = _bundle(root)
    run = tmp_path / "run.tamper"
    ref = "terrain-parts/p0/samples.json"
    sha = _write(run, ref, {"points": [{"planned_point_index": 0, "lat": 25, "lon": 122, "elevation_m": 100}],
                           "candidate_only": True, "runtime_safety_truth": False})
    preparation = {"terrain_parts": [{"status": "completed", "processor": "qgis_processing_grass", "planned_point_indices": [0],
        "output_refs": {"terrain_samples_ref": ref}, "source_hashes": {ref: sha}}]}
    with pytest.raises(PlannedRouteConflict, match="coordinate differs"):
        run_planned_analyses(root, bundle, run, preparation)
