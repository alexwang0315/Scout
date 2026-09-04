from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from pretrip_historical_route_timing import (
    build_directional_route_timing, build_historical_day_budget,
    historical_timezone, moving_interval_days,
)
from pretrip_reference_pace_energy_analysis import _grade_band


def sample(index, direction, seconds, *, source="one", digest=None):
    return {"route_bin_index": index, "direction": direction,
            "duration_seconds": seconds, "route_progress_distance_m": 250,
            "source_id": source, "source_sha256": digest or source}


def timing(samples, grades):
    return build_directional_route_timing(
        samples, route_distance_m=250 * len(grades), route_bin_m=250,
        bin_grades=grades, grade_band=_grade_band,
    )


def test_reverse_observation_is_not_outbound_time():
    result = timing([sample(0, "forward", 600), sample(0, "reverse", 180)], [0.1])
    assert result["bins"][0]["forward"]["average_minutes"] == 10
    assert result["bins"][0]["reverse"]["average_minutes"] == 3
    assert result["bins"][0]["reverse"]["status"] == "observed"


def test_reverse_estimate_uses_other_bin_descent_not_outbound_climb():
    result = timing([
        sample(0, "forward", 600), sample(1, "forward", 180),
        sample(2, "forward", 1200),
    ], [0.1, -0.1, 0.1])
    reverse = result["bins"][0]["reverse"]
    assert reverse["average_minutes"] == 3
    assert reverse["status"] == "estimated"
    assert reverse["grade_band"] == "02_descent"
    assert reverse["method"] == "other_bin_same_signed_grade_mean_pace"


@pytest.mark.parametrize("grades", [[None], [0.1], [0]])
def test_no_matching_reverse_basis_stays_unknown(grades):
    result = timing([sample(0, "forward", 600)], grades)
    assert result["bins"][0]["reverse"]["average_minutes"] is None
    assert result["bins"][0]["reverse"]["status"] == "unavailable"


def test_missing_terrain_cannot_supply_flat_cohort():
    result = timing([sample(1, "forward", 600)], [0, None])
    assert result["bins"][0]["reverse"]["status"] == "unavailable"


def test_pace_average_and_duplicate_sources():
    result = timing([
        sample(0, "reverse", 120, source="a", digest="same"),
        sample(0, "reverse", 120, source="copy", digest="same"),
        sample(0, "reverse", 600, source="b"),
    ], [0.1])
    assert result["bins"][0]["reverse"]["average_minutes"] == 6
    assert result["bins"][0]["reverse"]["sample_count"] == 2


def test_local_midnight_split():
    start = datetime(2020, 12, 25, 15, 59, tzinfo=timezone.utc)
    end = datetime(2020, 12, 25, 16, 2, tzinfo=timezone.utc)
    assert moving_interval_days(start, end, ZoneInfo("Asia/Taipei")) == {
        "2020-12-25": 60, "2020-12-26": 120,
    }


def test_daily_median_deduplicates_actual_source_hash_and_rejects_bad_values():
    tracks = [
        {"source_id": "a", "analysis_source": {"sha256": "same"}, "daily_moving_minutes": [300, 600]},
        {"source_id": "copy", "analysis_source": {"sha256": "same"}, "daily_moving_minutes": [300, 600]},
        {"source_id": "b", "daily_moving_minutes": [480, None, float("nan"), -1, 0]},
    ]
    result = build_historical_day_budget(tracks, timezone_name="Asia/Taipei", timezone_source="fixture")
    assert result["minutes"] == 480
    assert result["sample_day_count"] == 3
    assert result["distinct_source_count"] == 2
    assert result["duplicate_source_count"] == 1
    assert not result["live_remaining_day_budget"]


def test_timezone_basis_and_unknown_budget():
    zone, source = historical_timezone({}, {"timezone": "Asia/Taipei"})
    assert zone.key == "Asia/Taipei"
    assert source == "weather_daylight_evidence#timezone"
    assert historical_timezone({"timezone": "not/a/zone"}, {})[0].key == "UTC"
    result = build_historical_day_budget([], timezone_name="UTC", timezone_source="utc_fallback")
    assert result["minutes"] is None
