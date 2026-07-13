from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


MIN_IMAGERY_FRESHNESS_MINUTES = 30
IMAGERY_UPDATE_INTERVAL_MULTIPLIER = 6


def evaluate_weather_imagery_freshness(
    frame: dict[str, Any],
    *,
    evaluated_at: datetime,
) -> dict[str, Any]:
    """Derive cache imagery freshness at read time without fetching upstream."""

    evaluated = _aware_datetime(evaluated_at)
    source = _aware_datetime(frame.get("sourceTimestamp"))
    update_interval = _positive_minutes(frame.get("updateIntervalMinutes"), default=10)
    expected_delay = _positive_minutes(frame.get("expectedDelayMinutes"), default=10)
    allowed_age_minutes = max(
        MIN_IMAGERY_FRESHNESS_MINUTES,
        update_interval * IMAGERY_UPDATE_INTERVAL_MULTIPLIER,
        expected_delay + update_interval * 2,
    )
    fresh_until = source + timedelta(minutes=allowed_age_minutes)
    delay_minutes = round((evaluated - source).total_seconds() / 60)
    if source > evaluated + timedelta(minutes=5):
        status = "stale_data"
        reason = "future_source"
    elif evaluated <= fresh_until:
        status = "current"
        reason = "within_read_time_horizon"
    else:
        status = "stale_data"
        reason = "expired"
    return {
        "status": status,
        "reason": reason,
        "evaluatedAt": evaluated.isoformat(),
        "freshUntil": fresh_until.isoformat(),
        "expiredByMinutes": max(
            0, round((evaluated - fresh_until).total_seconds() / 60)
        ),
        "dataDelayMinutes": max(0, delay_minutes),
        "updateIntervalMinutes": update_interval,
    }


def _positive_minutes(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _aware_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    else:
        raise ValueError("imagery timestamp is missing")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("imagery timestamp must include timezone")
    return parsed.astimezone(timezone.utc)
