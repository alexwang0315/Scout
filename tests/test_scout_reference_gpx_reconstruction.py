from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from geo_utils import haversine_m
from pretrip_historical_daily_departures import build_historical_daily_departures
from scout_reference_gpx_reconstruction import build_reference_gpx_reconstruction


PRIMARY_REF = "normalized/routes/filtered/primary.reconstruction-fixture.speed_filtered.gpx"
PACE_REF = "outputs/reference_reconstruction_fixture_pace.json"
CP_REF = "outputs/reference_reconstruction_fixture_checkpoint_events.json"
ZONE = ZoneInfo("Asia/Taipei")


def _point(clock: str | None, lon: float) -> dict:
    return {"lat": 23.0, "lon": lon, "time": clock}


def _two_days() -> list[dict]:
    points = [
        _point("2020-12-26T06:00:00+08:00", 121.0),
        _point("2020-12-26T06:10:00+08:00", 121.001),
    ]
    start = datetime.fromisoformat("2020-12-26T06:11:00+08:00")
    points.extend(_point((start + timedelta(seconds=90 * i)).isoformat(),
                         121.001 + 0.00001 * (i % 3)) for i in range(17))
    return [*points,
        _point("2020-12-26T07:00:00+08:00", 121.003),
        _point("2020-12-26T16:00:00+08:00", 121.01),
        _point("2020-12-27T06:00:00+08:00", 121.0102),
        _point("2020-12-27T06:10:00+08:00", 121.012),
        _point(None, 121.0121),
        _point("2020-12-27T06:20:00+08:00", 121.013),
        _point("2020-12-27T06:30:00+08:00", 121.014),
        _point("2020-12-27T12:00:00+08:00", 121.02),
    ]


def add_reference_sources(
    project_root: Path, *, points: list[dict] | None = None,
    checkpoint_indices: tuple[int, ...] | None = None,
) -> dict:
    """Install coherent reference evidence in a disposable integration fixture."""
    points = _two_days() if points is None else points
    if checkpoint_indices is None:
        checkpoint_indices = (0, 1, 19, 20, 21, 22, 23, 24, 25, 26)
    document = ET.Element("gpx", xmlns="http://www.topografix.com/GPX/1/1")
    segment = ET.SubElement(ET.SubElement(document, "trk"), "trkseg")
    axis = [0.0]
    for index, point in enumerate(points):
        element = ET.SubElement(segment, "trkpt", lat=str(point["lat"]), lon=str(point["lon"]))
        if point["time"] is not None:
            ET.SubElement(element, "time").text = point["time"]
        if index:
            previous = points[index - 1]
            axis.append(axis[-1] + haversine_m(previous["lat"], previous["lon"], point["lat"], point["lon"]))
    primary = project_root / PRIMARY_REF
    primary.parent.mkdir(parents=True, exist_ok=True)
    primary.write_bytes(ET.tostring(document))
    schedule = build_historical_daily_departures(
        project_root=project_root, timezone=ZONE, timezone_source="fixture#timezone",
    )
    pace = {"schema_version": "reference_pace_energy_analysis.v0",
            "historical_route_timing": {"daily_departures": schedule}}
    cp = {"events": [{
        "checkpoint_candidate_id": f"cp.{index:03d}",
        "label": f"CP {index}",
        "route_point_index": index,
        "progress_m": round(axis[index], 2),
        "lat": points[index]["lat"],
        "lon": points[index]["lon"],
        "observed_at": points[index]["time"],
    } for index in checkpoint_indices]}
    for ref, content in ((PACE_REF, pace), (CP_REF, cp)):
        path = project_root / ref
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(content))
    project_path = project_root / "project.json"
    project = json.loads(project_path.read_text()) if project_path.exists() else {}
    project.update(reference_pace_energy_analysis_ref=PACE_REF, checkpoint_events_ref=CP_REF)
    project_path.write_text(json.dumps(project))
    return project


def _snapshot(root: Path) -> dict:
    return {path.relative_to(root).as_posix():
            (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
            for path in root.rglob("*") if path.is_file()}


def test_reconstructs_exact_historical_days_without_writes_or_authority(tmp_path):
    project = add_reference_sources(tmp_path)
    before = _snapshot(tmp_path)
    result = build_reference_gpx_reconstruction(tmp_path, project)
    first, second = result["days"]

    assert result["schema_version"] == "reference_gpx_reconstruction.v1"
    assert result["policy_version"] == "1"
    assert result["source_refs"] == [PRIMARY_REF, PACE_REF, CP_REF]
    assert result["source_sha256"] == before[PRIMARY_REF][0]
    assert result["source_hashes"] == {ref: before[ref][0] for ref in result["source_refs"]}
    assert result["source_point_count"] == 27
    assert result["timed_point_count"] == 26
    assert [(d["start"]["point_index"], d["end"]["point_index"]) for d in result["days"]] == [(0, 20), (21, 26)]
    assert (first["departure_clock"], first["arrival_clock"], first["elapsed_minutes"]) == ("06:00:00", "16:00:00", 600)
    assert (second["departure_clock"], second["arrival_clock"], second["elapsed_minutes"]) == ("06:00:00", "12:00:00", 360)
    assert first["end"]["route_order_m"] < second["start"]["route_order_m"]
    assert first["end"]["label"] == "Historical D1 end"
    gap, = result["overnight_gaps"]
    assert (gap["start_point_index"], gap["end_point_index"]) == (20, 21)
    assert (gap["from_day_index"], gap["to_day_index"]) == (1, 2)
    assert gap["duration_minutes"] == 14 * 60
    assert 20 < gap["recording_gap_distance_m"] < 21
    assert result["unassigned_checkpoint_windows"] == []
    assert result["candidate_only"] is True and result["runtime_safety_truth"] is False
    assert result["writes_performed"] is False
    assert result["policy"]["day_end_selection_origin"] == "reference_evidence"
    assert result == build_reference_gpx_reconstruction(tmp_path, project)
    assert _snapshot(tmp_path) == before
    json.dumps(result, allow_nan=False)


def test_exact_checkpoint_pace_starts_at_day_start_and_missing_breaks_chain(tmp_path):
    project = add_reference_sources(tmp_path)
    result = build_reference_gpx_reconstruction(tmp_path, project)
    checkpoints = {cp["anchor_id"]: cp for day in result["days"] for cp in day["checkpoint_windows"]}
    assert checkpoints["cp.021"]["from_previous_minutes"] == 0
    assert checkpoints["cp.021"]["from_previous_distance_m"] == 0
    assert checkpoints["cp.021"]["from_previous_speed_kmh"] is None
    assert checkpoints["cp.022"]["from_previous_minutes"] == 10
    assert checkpoints["cp.022"]["from_previous_speed_kmh"] > 0
    assert checkpoints["cp.022"]["remaining_to_day_end_minutes"] == 350
    missing = checkpoints["cp.023"]
    assert missing["status"] == "unknown"
    assert missing["arrival_clock"] is None
    assert missing["from_previous_minutes"] is None
    assert missing["from_previous_speed_kmh"] is None
    assert missing["remaining_to_day_end_minutes"] is None
    assert missing["from_previous_distance_m"] > 0
    assert checkpoints["cp.024"]["status"] == "exact"
    assert checkpoints["cp.024"]["from_previous_minutes"] is None
    assert checkpoints["cp.025"]["from_previous_minutes"] == 10
    assert result["days"][1]["unknown_ranges"][0]["point_count"] == 1


def test_stays_are_derived_day_bounded_observations_and_never_raw_rest(tmp_path):
    project = add_reference_sources(tmp_path)
    (tmp_path / "outputs/rest_area_candidates.json").write_text(json.dumps({
        "candidates": [{"name": "Untrusted camp name", "duration_minutes": 4289651.53}],
    }))
    result = build_reference_gpx_reconstruction(tmp_path, project)
    stop, = result["days"][0]["rest_stops"]
    assert (stop["start_clock"], stop["end_clock"], stop["duration_minutes"]) == ("06:10:00", "06:35:00", 25)
    assert (stop["start_point_index"], stop["end_point_index"]) == (1, 18)
    assert stop["status"] == "derived" and stop["semantic_rest_verified"] is False
    assert result["days"][1]["rest_stops"] == []
    assert "Untrusted camp name" not in json.dumps(result)
    assert result["policy"]["rest_detection"]["maximum_adjacent_observation_gap_seconds"] == 600


@pytest.mark.parametrize("gap_type", ["missing", "unobserved"])
def test_observation_gaps_and_missing_timestamps_cannot_create_a_stay(tmp_path, gap_type):
    points = _two_days()
    if gap_type == "missing":
        points[10]["time"] = None
    else:
        for point in points[10:19]:
            point["time"] = (datetime.fromisoformat(point["time"]) + timedelta(minutes=11)).isoformat()
    project = add_reference_sources(tmp_path, points=points)
    result = build_reference_gpx_reconstruction(tmp_path, project)
    assert result["days"][0]["rest_stops"] == []


def test_route_sampling_preserves_every_exact_day_boundary(tmp_path):
    points = []
    for day in range(2):
        start = datetime(2020, 12, 26 + day, 6, tzinfo=ZONE)
        points.extend(_point((start + timedelta(seconds=30 * i)).isoformat(),
                             121 + (day * 350 + i) * 0.00001) for i in range(350))
    project = add_reference_sources(tmp_path, points=points, checkpoint_indices=(0, 349, 350, 699))
    result = build_reference_gpx_reconstruction(tmp_path, project)
    route = result["route_points"]
    assert len(route) <= 480
    assert len(result["days"]) == 2
    assert all(set(point) == {"route_order_m", "lat", "lon"} for point in route)
    for day in result["days"]:
        for kind in ("start", "end"):
            assert {key: day[kind][key] for key in ("route_order_m", "lat", "lon")} in route


def test_untimed_outer_points_and_checkpoints_remain_unassigned(tmp_path):
    points = [_point(None, 120.9999), *_two_days(), _point(None, 121.0201)]
    project = add_reference_sources(tmp_path, points=points, checkpoint_indices=(0, 1, 28))
    result = build_reference_gpx_reconstruction(tmp_path, project)
    assert len(result["days"]) == 2
    assert [cp["point_index"] for cp in result["unassigned_checkpoint_windows"]] == [0, 28]
    assert all(cp["status"] == "unknown" and cp["from_previous_minutes"] is None
               for cp in result["unassigned_checkpoint_windows"])
    assert any(span["reason"] == "missing_boundary_timestamp" for span in result["unknown_ranges"])


def test_only_undeclared_legacy_fixture_returns_none(tmp_path):
    assert build_reference_gpx_reconstruction(tmp_path, {}) is None
    with pytest.raises(ValueError, match="pace_analysis_ref_missing"):
        build_reference_gpx_reconstruction(tmp_path, {"reference_pace_energy_analysis_ref": None})
    with pytest.raises(ValueError, match="pace_analysis_unreadable"):
        build_reference_gpx_reconstruction(tmp_path, {"reference_pace_energy_analysis_ref": "outputs/missing.json"})


@pytest.mark.parametrize("field,value,reason", [
    ("route_point_index", 9000, "checkpoint_index_mismatch"),
    ("progress_m", 10000, "checkpoint_axis_mismatch"),
    ("observed_at", "2020-12-26T06:01:00+08:00", "checkpoint_timestamp_mismatch"),
    ("observed_at", "2020-12-26T06:00:00", "checkpoint_timestamp_invalid"),
    ("lat", 0.0, "checkpoint_coordinates_mismatch"),
])
def test_checkpoint_must_match_the_same_primary(tmp_path, field, value, reason):
    project = add_reference_sources(tmp_path)
    path = tmp_path / CP_REF
    events = json.loads(path.read_text())
    events["events"][0][field] = value
    path.write_text(json.dumps(events))
    with pytest.raises(ValueError, match=reason):
        build_reference_gpx_reconstruction(tmp_path, project)


@pytest.mark.parametrize("mutation,reason", [
    ("hash", "cached_schedule_source_mismatch"),
    ("boundary", "cached_day_boundaries_mismatch"),
    ("timezone", "timezone_invalid"),
    ("schedule", "daily_departures_missing"),
])
def test_stale_or_missing_schedule_fails_without_repartition(tmp_path, mutation, reason):
    project = add_reference_sources(tmp_path)
    path = tmp_path / PACE_REF
    pace = json.loads(path.read_text())
    cached = pace["historical_route_timing"]["daily_departures"]
    if mutation == "hash":
        cached["source_sha256"] = "0" * 64
    elif mutation == "boundary":
        cached["days"][0]["end_point_index"] -= 1
    elif mutation == "timezone":
        cached["timezone"] = "Not/A_Zone"
    else:
        pace["historical_route_timing"].pop("daily_departures")
    path.write_text(json.dumps(pace))
    with pytest.raises(ValueError, match=reason):
        build_reference_gpx_reconstruction(tmp_path, project)


def test_invalid_filtered_chronology_fails_closed(tmp_path):
    points = _two_days()
    points[8]["time"] = points[7]["time"]
    project = add_reference_sources(tmp_path, points=points)
    with pytest.raises(ValueError, match="schedule_unavailable:invalid_schedule:.*non_increasing_timestamp"):
        build_reference_gpx_reconstruction(tmp_path, project)


def test_evidence_paths_cannot_escape_project(tmp_path):
    project = add_reference_sources(tmp_path)
    project["checkpoint_events_ref"] = "../outside.json"
    with pytest.raises(ValueError, match="checkpoint_events_outside_project"):
        build_reference_gpx_reconstruction(tmp_path, project)


def test_symlinked_evidence_cannot_escape_project(tmp_path):
    root = tmp_path / "workspace"
    project = add_reference_sources(root)
    outside = tmp_path / "outside.json"
    outside.write_text((root / CP_REF).read_text())
    link = root / "outputs/checkpoint_link.json"
    link.symlink_to(outside)
    project["checkpoint_events_ref"] = "outputs/checkpoint_link.json"
    with pytest.raises(ValueError, match="checkpoint_events_outside_project"):
        build_reference_gpx_reconstruction(root, project)
