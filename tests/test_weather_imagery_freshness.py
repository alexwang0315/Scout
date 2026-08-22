from datetime import datetime, timezone

import pytest

from weather_imagery_freshness import evaluate_weather_imagery_freshness


EVALUATED_AT = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)


def test_imagery_freshness_marks_future_source_as_stale() -> None:
    freshness = evaluate_weather_imagery_freshness(
        {
            "sourceTimestamp": "2026-07-11T12:06:00Z",
            "updateIntervalMinutes": 10,
            "expectedDelayMinutes": 10,
        },
        evaluated_at=EVALUATED_AT,
    )

    assert freshness["status"] == "stale_data"
    assert freshness["reason"] == "future_source"
    assert freshness["dataDelayMinutes"] == 0


def test_imagery_freshness_keeps_source_current_at_horizon_boundary() -> None:
    freshness = evaluate_weather_imagery_freshness(
        {
            "sourceTimestamp": "2026-07-11T11:00:00Z",
            "updateIntervalMinutes": 10,
            "expectedDelayMinutes": 10,
        },
        evaluated_at=EVALUATED_AT,
    )

    assert freshness["status"] == "current"
    assert freshness["reason"] == "within_read_time_horizon"
    assert freshness["freshUntil"] == EVALUATED_AT.isoformat()
    assert freshness["expiredByMinutes"] == 0


@pytest.mark.parametrize(
    ("frame", "message"),
    [
        ({}, "imagery timestamp is missing"),
        (
            {"sourceTimestamp": "2026-07-11T11:00:00"},
            "imagery timestamp must include timezone",
        ),
    ],
)
def test_imagery_freshness_rejects_missing_or_naive_source_timestamp(
    frame: dict[str, str],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        evaluate_weather_imagery_freshness(
            frame,
            evaluated_at=EVALUATED_AT,
        )
