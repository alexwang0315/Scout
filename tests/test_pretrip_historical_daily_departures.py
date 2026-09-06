from __future__ import annotations

import hashlib
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from geo_utils import haversine_m
from pretrip_historical_daily_departures import build_historical_daily_departures


SOURCE_REF = "normalized/routes/filtered/primary.fixture.speed_filtered.gpx"
ZONE = ZoneInfo("Asia/Taipei")


def _point(clock: str | None, lon: float = 121.0, lat: float = 23.0) -> dict:
    return {"lat": lat, "lon": lon, "time": clock}


def _write(
    root: Path,
    segments: list[list[dict]],
    *,
    ref: str = SOURCE_REF,
    namespaced: bool = True,
) -> Path:
    namespace = "{http://www.topografix.com/GPX/1/1}" if namespaced else ""
    document = ET.Element(f"{namespace}gpx")
    track = ET.SubElement(document, f"{namespace}trk")
    for points in segments:
        segment = ET.SubElement(track, f"{namespace}trkseg")
        for point in points:
            element = ET.SubElement(
                segment,
                f"{namespace}trkpt",
                {
                    "lat": str(point["lat"]),
                    "lon": str(point["lon"]),
                },
            )
            if point["time"] is not None:
                ET.SubElement(element, f"{namespace}time").text = point["time"]
    path = root / ref
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(ET.tostring(document))
    return path


def _build(root: Path, *, zone: ZoneInfo = ZONE) -> dict:
    return build_historical_daily_departures(
        project_root=root,
        timezone=zone,
        timezone_source="fixture#timezone",
    )


def _axis(points: list[dict]) -> list[float]:
    values = [0.0]
    for first, second in zip(points, points[1:]):
        values.append(
            values[-1]
            + haversine_m(
                first["lat"],
                first["lon"],
                second["lat"],
                second["lon"],
            )
        )
    return values


def _two_days() -> list[dict]:
    return [
        _point("2020-12-25T05:36:30+08:00"),
        _point("2020-12-25T16:00:00+08:00", 121.01),
        _point("2020-12-26T06:00:00+08:00", 121.0102),
        _point("2020-12-26T09:00:00+08:00", 121.02),
    ]


def test_two_day_overnight_keeps_exact_axis_and_candidate_departures(tmp_path):
    points = _two_days()
    path = _write(tmp_path, [points])
    before = path.read_bytes()
    result = _build(tmp_path)
    first, second = result["days"]
    axis = _axis(points)

    assert result["status"] == "ready"
    assert result["schema_version"] == "historical_daily_departures.v1"
    assert result["route_distance_m"] == axis[-1]
    assert result["route_axis"] == "filtered_primary_cumulative_haversine_all_points"
    assert result["timezone"] == "Asia/Taipei"
    assert result["timezone_source"] == "fixture#timezone"
    assert result["source_ref"] == SOURCE_REF
    assert result["source_sha256"] == hashlib.sha256(before).hexdigest()
    assert result["cutoff_policy"] == "fixed_18_00_not_astronomical_sunset"
    assert result["cutoff_minute_of_day"] == 1080
    assert result["candidate_only"] is True
    assert result["runtime_safety_truth"] is False
    assert [
        (d["start_point_index"], d["end_point_index"]) for d in (first, second)
    ] == [(0, 1), (2, 3)]
    assert [(d["start_distance_m"], d["end_distance_m"]) for d in (first, second)] == [
        (axis[0], axis[1]),
        (axis[2], axis[3]),
    ]
    assert [d["day_index"] for d in (first, second)] == [1, 2]
    assert first["day_id"] != second["day_id"]
    assert first["departure_minute_of_day"] == 336.5
    assert first["preceding_gap_hours"] is None
    assert second["preceding_gap_hours"] == 14
    assert second["departure_minute_of_day"] == 360
    assert first["departure_basis"] == "initial_record"
    assert second["departure_basis"] == "first_record_after_overnight_gap"
    assert all(d["departure_status"] == "estimated" for d in (first, second))
    assert all(d["source_refs"] == [SOURCE_REF] for d in (first, second))
    (overnight,) = result["overnight_breaks"]
    assert overnight["candidate_only"] is True
    assert overnight["overnight_assignment_verified"] is False
    assert overnight["preceding_gap_hours"] == 14
    assert overnight["start_point_index"] == 1
    assert overnight["end_point_index"] == 2
    assert result["unknown_ranges"][0]["reason"] == "overnight_recording_gap"
    assert _build(tmp_path) == result
    assert path.read_bytes() == before
    assert [p for p in tmp_path.rglob("*") if p.is_file()] == [path]
    encoded = json.dumps(result, allow_nan=False)
    assert "2020-12-25" not in encoded
    assert '"lat"' not in encoded and '"lon"' not in encoded


def test_continuous_midnight_walking_does_not_reset(tmp_path):
    _write(
        tmp_path,
        [
            [
                _point("2020-12-25T23:50:00+08:00"),
                _point("2020-12-26T00:10:00+08:00", 121.001),
                _point("2020-12-26T06:00:00+08:00", 121.002),
            ]
        ],
    )
    result = _build(tmp_path)
    (day,) = result["days"]
    assert result["status"] == "ready"
    assert day["departure_minute_of_day"] == 1430
    assert day["end_point_index"] == 2
    assert "continuous_midnight_retained" in day["quality_flags"]
    assert result["overnight_breaks"] == []


def test_same_day_long_stop_does_not_reset_even_beyond_six_hours(tmp_path):
    _write(
        tmp_path,
        [
            [
                _point("2020-12-25T06:00:00+08:00"),
                _point("2020-12-25T15:00:00+08:00", 121.0001),
                _point("2020-12-25T16:00:00+08:00", 121.01),
            ]
        ],
    )
    result = _build(tmp_path)
    (day,) = result["days"]
    assert result["status"] == "ready"
    assert day["departure_minute_of_day"] == 360
    assert "same_day_long_stop_retained" in day["quality_flags"]
    assert result["overnight_breaks"] == []


@pytest.mark.parametrize(
    "end, expected_status, day_count",
    [
        ("2020-12-26T01:59:59+08:00", "ready", 1),
        ("2020-12-26T02:00:00+08:00", "ready", 2),
        ("2020-12-27T08:00:00+08:00", "ready", 2),
        ("2020-12-27T08:00:01+08:00", "unavailable", 0),
    ],
)
def test_overnight_gap_thresholds_are_inclusive(
    tmp_path, end, expected_status, day_count
):
    _write(
        tmp_path,
        [
            [
                _point("2020-12-25T19:00:00+08:00"),
                _point("2020-12-25T20:00:00+08:00", 121.001),
                _point(end, 121.0011),
            ]
        ],
    )
    result = _build(tmp_path)
    assert result["status"] == expected_status
    assert len(result["days"]) == day_count


@pytest.mark.parametrize(
    "separation_m, expected", [(149.9, "ready"), (150.1, "unavailable")]
)
def test_overnight_physical_separation_guard(tmp_path, separation_m, expected):
    delta_lat = separation_m / 6_371_000.0 * 180 / math.pi
    _write(
        tmp_path,
        [
            [
                _point("2020-12-25T15:00:00+08:00", lat=23.0),
                _point("2020-12-25T16:00:00+08:00", lat=23.0001),
                _point("2020-12-26T06:00:00+08:00", lat=23.0001 + delta_lat),
            ]
        ],
    )
    result = _build(tmp_path)
    assert result["status"] == expected
    if expected == "unavailable":
        assert "overnight_gap_spatial_discontinuity" in result["quality_flags"]
        assert result["schedule_breaks"]
        assert result["days"] == []


def test_local_date_not_utc_date_controls_overnight(tmp_path):
    _write(
        tmp_path,
        [
            [
                _point("2020-12-25T08:00:00Z"),
                _point("2020-12-25T22:00:00Z", 121.0001),
            ]
        ],
    )
    result = _build(tmp_path)
    assert len(result["days"]) == 2
    assert [d["departure_minute_of_day"] for d in result["days"]] == [960, 360]
    assert len(_build(tmp_path, zone=ZoneInfo("UTC"))["days"]) == 1


def test_missing_internal_times_preserve_all_point_distance_without_interpolation(
    tmp_path,
):
    points = [
        _point("2020-12-25T06:00:00+08:00"),
        _point(None, 121.01),
        _point(None, 121.0),
        _point("2020-12-25T07:00:00+08:00", 121.02),
    ]
    _write(tmp_path, [points])
    result = _build(tmp_path)
    (day,) = result["days"]
    assert result["status"] == "ready"
    assert result["route_distance_m"] == _axis(points)[-1]
    assert day["start_point_index"] == 0 and day["end_point_index"] == 3
    assert "missing_timestamps" in day["quality_flags"]
    assert result["counts"]["untimed_point_count"] == 2
    assert result["unknown_ranges"] == []


def test_missing_boundary_times_leave_unknown_holes(tmp_path):
    points = [
        _point(None),
        _point("2020-12-25T06:00:00+08:00", 121.001),
        _point("2020-12-25T07:00:00+08:00", 121.002),
        _point(None, 121.003),
    ]
    _write(tmp_path, [points])
    result = _build(tmp_path)
    (day,) = result["days"]
    assert result["status"] == "ready"
    assert day["start_distance_m"] == _axis(points)[1]
    assert day["end_distance_m"] == _axis(points)[2]
    assert [
        (r["start_point_index"], r["end_point_index"]) for r in result["unknown_ranges"]
    ] == [(0, 1), (2, 3)]
    assert "leading_untimed_points" in day["quality_flags"]
    assert "trailing_untimed_points" in day["quality_flags"]


def test_missing_points_do_not_prevent_valid_timed_overnight_pair(tmp_path):
    points = _two_days()
    points.insert(2, _point(None, 121.0101))
    _write(tmp_path, [points])
    result = _build(tmp_path)
    assert result["status"] == "ready"
    assert len(result["days"]) == 2
    assert result["days"][1]["start_point_index"] == 3
    assert "untimed_points_in_gap" in result["overnight_breaks"][0]["quality_flags"]


@pytest.mark.parametrize(
    "bad_time, flag",
    [
        ("2012-10-28T07:00:00+08:00", "non_increasing_timestamp"),
        ("2030-12-25T07:00:00+08:00", "temporal_gap_exceeds_36h"),
        ("2020-12-25T06:00:00+08:00", "non_increasing_timestamp"),
        ("not-a-time", "invalid_timestamp"),
        ("2020-12-25T07:00:00", "timestamp_timezone_missing"),
    ],
)
def test_corrupt_schedule_is_unavailable_without_fabricated_departures(
    tmp_path, bad_time, flag
):
    _write(
        tmp_path,
        [
            [
                _point("2020-12-25T06:00:00+08:00"),
                _point(bad_time, 121.001),
                _point("2020-12-25T08:00:00+08:00", 121.002),
            ]
        ],
    )
    result = _build(tmp_path)
    assert result["status"] == "unavailable"
    assert result["reason"] == "invalid_schedule"
    assert result["days"] == []
    assert flag in result["quality_flags"]
    assert result["schedule_breaks"]
    assert result["unknown_ranges"][0]["end_distance_m"] == result["route_distance_m"]


def test_multi_year_splice_is_not_counted_as_extra_days(tmp_path):
    _write(
        tmp_path,
        [
            [
                _point("2020-12-25T06:00:00+08:00"),
                _point("2012-10-28T07:00:00+08:00", 121.001),
                _point("2012-10-28T07:05:00+08:00", 121.0011),
                _point("2020-12-25T08:00:00+08:00", 121.0012),
            ]
        ],
    )
    result = _build(tmp_path)
    assert result["status"] == "unavailable"
    assert result["days"] == []
    assert len(result["schedule_breaks"]) == 2
    assert result["overnight_breaks"] == []


@pytest.mark.parametrize("namespaced", [True, False])
def test_multi_segment_axis_matches_existing_primary_helper(tmp_path, namespaced):
    from pretrip_reference_pace_energy_analysis import _primary_route_progress

    points = [
        _point("2020-12-25T06:00:00+08:00"),
        _point(None, 121.001),
        _point("2020-12-25T07:00:00+08:00", 121.002),
        _point("2020-12-25T08:00:00+08:00", 121.003),
    ]
    _write(tmp_path, [points[:2], [], points[2:]], namespaced=namespaced)
    result = _build(tmp_path)
    assert result["status"] == "ready"
    assert result["route_distance_m"] == _primary_route_progress(tmp_path)[-1]
    assert result["route_distance_m"] == _axis(points)[-1]
    assert len(result["days"]) == 1
    assert "multiple_track_segments" in result["quality_flags"]


def test_no_primary_does_not_fall_back_to_reference_or_raw_gpx(tmp_path):
    _write(tmp_path, [_two_days()], ref="inbox/gpx/primary.raw.gpx")
    _write(
        tmp_path,
        [_two_days()],
        ref="normalized/routes/filtered/reference.one.speed_filtered.gpx",
    )
    result = _build(tmp_path)
    assert result["status"] == "unavailable"
    assert result["reason"] == "primary_missing"
    assert result["days"] == []


def test_ambiguous_primary_is_not_selected_lexically(tmp_path):
    _write(tmp_path, [_two_days()])
    _write(
        tmp_path,
        [_two_days()],
        ref="normalized/routes/filtered/primary.other.speed_filtered.gpx",
    )
    result = _build(tmp_path)
    assert result["status"] == "unavailable"
    assert result["reason"] == "ambiguous_primary"
    assert result["source_ref"] is None
    assert result["days"] == []


@pytest.mark.parametrize("directory_link", [False, True])
def test_primary_symlinks_outside_workspace_are_not_read(tmp_path, directory_link):
    workspace, outside = tmp_path / "workspace", tmp_path / "outside"
    foreign = _write(outside, [_two_days()])
    target = workspace / SOURCE_REF
    if directory_link:
        target.parent.parent.mkdir(parents=True)
        target.parent.symlink_to(foreign.parent, target_is_directory=True)
    else:
        target.parent.mkdir(parents=True)
        target.symlink_to(foreign)
    result = _build(workspace)
    assert result["status"] == "unavailable"
    assert result["reason"] == "source_outside_project_root"
    assert result["source_sha256"] is None
    assert result["days"] == []


def test_in_workspace_primary_symlink_keeps_selected_source_ref(tmp_path):
    original = _write(tmp_path, [_two_days()], ref="inbox/filtered-copy.gpx")
    selected = tmp_path / SOURCE_REF
    selected.parent.mkdir(parents=True)
    selected.symlink_to(original)
    result = _build(tmp_path)
    assert result["status"] == "ready"
    assert result["source_ref"] == SOURCE_REF
    assert result["source_sha256"] == hashlib.sha256(original.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    "points, reason",
    [
        ([], "insufficient_track_points"),
        ([_point("2020-12-25T06:00:00Z")], "insufficient_track_points"),
        ([_point(None), _point(None, 121.001)], "insufficient_timed_records"),
        (
            [_point(None), _point("2020-12-25T06:00:00Z", 121.001)],
            "insufficient_timed_records",
        ),
        (
            [_point("2020-12-25T06:00:00Z"), _point("2020-12-25T07:00:00Z")],
            "zero_length_route_axis",
        ),
    ],
)
def test_insufficient_schedule_returns_unavailable(tmp_path, points, reason):
    _write(tmp_path, [points])
    result = _build(tmp_path)
    assert result["status"] == "unavailable"
    assert result["reason"] == reason
    assert result["days"] == []


@pytest.mark.parametrize(
    "lat, lon", [(float("nan"), 121), (23, float("inf")), (91, 121), (23, 181)]
)
def test_invalid_coordinate_does_not_drop_or_rebase_axis(tmp_path, lat, lon):
    _write(
        tmp_path,
        [
            [
                _point("2020-12-25T06:00:00Z"),
                _point("2020-12-25T07:00:00Z", lon=lon, lat=lat),
            ]
        ],
    )
    result = _build(tmp_path)
    assert result["status"] == "unavailable"
    assert result["reason"] == "invalid_coordinates"
    assert result["route_distance_m"] is None
    assert result["days"] == []
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize(
    "payload",
    [
        b"<gpx>",
        b"<not-gpx/>",
        b'<!DOCTYPE gpx [<!ENTITY t "x">]><gpx/>',
        '<!DOCTYPE gpx [<!ENTITY t "x">]><gpx/>'.encode("utf-16"),
    ],
)
def test_invalid_xml_is_unavailable_and_does_not_leak_source_content(tmp_path, payload):
    path = tmp_path / SOURCE_REF
    path.parent.mkdir(parents=True)
    path.write_bytes(payload)
    result = _build(tmp_path)
    assert result["status"] == "unavailable"
    assert result["days"] == []
    assert "<gpx" not in json.dumps(result)
