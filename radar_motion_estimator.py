from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from route_imagery_sampler import RouteBuffer, distance_to_route_km


def estimate_motion_toward_route(
    samples: Iterable[dict[str, Any]],
    route_buffer: RouteBuffer,
    *,
    centroid_key: str = "strongEchoCentroid",
) -> dict[str, Any]:
    usable: list[tuple[datetime, float, float]] = []
    for sample in samples:
        centroid = sample.get(centroid_key)
        timestamp = sample.get("sourceTimestamp")
        if not isinstance(centroid, dict) or not isinstance(timestamp, str):
            continue
        try:
            usable.append((_parse_time(timestamp), float(centroid["lat"]), float(centroid["lon"])))
        except (KeyError, TypeError, ValueError):
            continue
    usable.sort(key=lambda item: item[0])
    if len(usable) < 2:
        return _unknown_motion("insufficient_frames")
    contiguous = [usable[-1]]
    for previous in reversed(usable[:-1]):
        interval = (contiguous[0][0] - previous[0]).total_seconds() / 3600.0
        if interval <= 0 or interval > 2:
            break
        contiguous.insert(0, previous)
    usable = contiguous
    if len(usable) < 2:
        return _unknown_motion("invalid_frame_interval")
    distances = [distance_to_route_km(lat, lon, route_buffer) for _time, lat, lon in usable]
    elapsed = [(item[0] - usable[0][0]).total_seconds() / 3600.0 for item in usable]
    mean_time = sum(elapsed) / len(elapsed)
    mean_distance = sum(distances) / len(distances)
    denominator = sum((item - mean_time) ** 2 for item in elapsed)
    if denominator <= 0:
        return _unknown_motion("invalid_frame_interval")
    slope = sum(
        (time_value - mean_time) * (distance - mean_distance)
        for time_value, distance in zip(elapsed, distances)
    ) / denominator
    closing_speed = -slope
    predictions = [mean_distance + slope * (item - mean_time) for item in elapsed]
    residual = sum((actual - predicted) ** 2 for actual, predicted in zip(distances, predictions))
    total = sum((actual - mean_distance) ** 2 for actual in distances)
    trend_fit = max(0.0, min(1.0, 1.0 - residual / total)) if total > 0 else 0.0
    moving_toward = closing_speed > 0.1 and trend_fit >= 0.25
    previous_distance = distances[-2]
    current_distance = distances[-1]
    arrival = None
    if moving_toward:
        remaining = max(0.0, current_distance - route_buffer.buffer_m / 1000.0)
        arrival = round((remaining / closing_speed) * 60.0) if closing_speed > 0 else None
    confidence = min(0.95, (0.35 + 0.1 * len(usable)) * trend_fit)
    return {
        "artifactKind": "radarMotionEstimate",
        "movingTowardRoute": moving_toward,
        "estimatedArrivalMinutes": arrival,
        "closingSpeedKmh": round(closing_speed, 3),
        "previousDistanceKm": round(previous_distance, 3),
        "currentDistanceKm": round(current_distance, 3),
        "frameCount": len(usable),
        "trendFit": round(trend_fit, 3),
        "confidence": round(confidence, 3),
        "reason": "closing_distance" if moving_toward else "not_closing",
        "candidateOnly": True,
        "runtimeSafetyTruth": False,
    }


def _unknown_motion(reason: str) -> dict[str, Any]:
    return {
        "artifactKind": "radarMotionEstimate",
        "movingTowardRoute": None,
        "estimatedArrivalMinutes": None,
        "closingSpeedKmh": None,
        "frameCount": 0,
        "confidence": 0.0,
        "reason": reason,
        "candidateOnly": True,
        "runtimeSafetyTruth": False,
    }


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
