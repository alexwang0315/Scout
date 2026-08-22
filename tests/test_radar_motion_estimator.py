from radar_motion_estimator import estimate_motion_toward_route
from route_imagery_sampler import build_route_buffer


def test_motion_estimator_detects_echo_approach_and_arrival() -> None:
    route = build_route_buffer([(24.0, 121.0), (24.0, 121.01)], buffer_m=500)
    samples = [
        {
            "sourceTimestamp": "2026-07-11T03:00:00Z",
            "strongEchoCentroid": {"lat": 24.0, "lon": 120.80},
        },
        {
            "sourceTimestamp": "2026-07-11T03:10:00Z",
            "strongEchoCentroid": {"lat": 24.0, "lon": 120.90},
        },
    ]

    motion = estimate_motion_toward_route(samples, route)

    assert motion["movingTowardRoute"] is True
    assert motion["estimatedArrivalMinutes"] is not None
    assert motion["estimatedArrivalMinutes"] > 0
    assert motion["confidence"] > 0


def test_motion_estimator_is_nullable_when_frames_are_insufficient() -> None:
    route = build_route_buffer([(24.0, 121.0), (24.0, 121.01)], buffer_m=500)

    motion = estimate_motion_toward_route([], route)

    assert motion["movingTowardRoute"] is None
    assert motion["estimatedArrivalMinutes"] is None
    assert motion["confidence"] == 0.0


def test_motion_estimator_does_not_reward_last_frame_jitter() -> None:
    route = build_route_buffer([(24.0, 121.0), (24.0, 121.01)], buffer_m=500)
    samples = [
        {
            "sourceTimestamp": f"2026-07-11T03:{minute:02d}:00Z",
            "strongEchoCentroid": {"lat": 24.0, "lon": lon},
        }
        for minute, lon in ((0, 120.90), (10, 120.90), (20, 120.90), (30, 120.90), (40, 120.99))
    ]

    motion = estimate_motion_toward_route(samples, route)

    assert motion["confidence"] < 0.8
    assert motion["trendFit"] < 0.8


def test_motion_estimator_uses_latest_contiguous_frames_after_cache_gap() -> None:
    route = build_route_buffer([(24.0, 121.0), (24.0, 121.01)], buffer_m=500)
    samples = [
        {
            "sourceTimestamp": "2026-07-11T00:00:00Z",
            "strongEchoCentroid": {"lat": 24.0, "lon": 120.70},
        },
        {
            "sourceTimestamp": "2026-07-11T03:00:00Z",
            "strongEchoCentroid": {"lat": 24.0, "lon": 120.80},
        },
        {
            "sourceTimestamp": "2026-07-11T03:10:00Z",
            "strongEchoCentroid": {"lat": 24.0, "lon": 120.90},
        },
    ]

    motion = estimate_motion_toward_route(samples, route)

    assert motion["reason"] != "invalid_frame_interval"
    assert motion["frameCount"] == 2
    assert motion["movingTowardRoute"] is True
