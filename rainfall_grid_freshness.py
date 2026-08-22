from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


QPE_MAX_AGE = timedelta(hours=2)
MAX_FUTURE_SOURCE_SKEW = timedelta(minutes=15)


def evaluate_precipitation_freshness(
    *,
    grid_kind: str,
    source_timestamp: str | datetime | None,
    valid_until: str | datetime | None,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware_datetime(evaluated_at or datetime.now(timezone.utc))
    source = _optional_aware_datetime(source_timestamp)
    valid = _optional_aware_datetime(valid_until)
    deadline = source + QPE_MAX_AGE if grid_kind == "qpe_past_1h" and source else valid
    if source is None or deadline is None:
        return _result("unknown", now=now, deadline=deadline, reason="invalid_time")
    if source > now + MAX_FUTURE_SOURCE_SKEW:
        return _result("stale_data", now=now, deadline=deadline, reason="future_source")
    if now > deadline:
        return _result("stale_data", now=now, deadline=deadline, reason="expired")
    return _result("current", now=now, deadline=deadline, reason=None)


def _result(
    status: str,
    *,
    now: datetime,
    deadline: datetime | None,
    reason: str | None,
) -> dict[str, Any]:
    expired_minutes = None
    if deadline is not None:
        expired_minutes = max(0, round((now - deadline).total_seconds() / 60))
    return {
        "status": status,
        "evaluatedAt": now.isoformat(),
        "freshUntil": deadline.isoformat() if deadline else None,
        "expiredByMinutes": expired_minutes,
        "reason": reason,
    }


def _optional_aware_datetime(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    try:
        return _aware_datetime(value)
    except (TypeError, ValueError):
        return None


def _aware_datetime(value: str | datetime) -> datetime:
    parsed = (
        value
        if isinstance(value, datetime)
        else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    )
    if parsed.tzinfo is None:
        raise ValueError("rainfall freshness timestamps must be timezone-aware")
    return parsed.astimezone(timezone.utc)
