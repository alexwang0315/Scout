from __future__ import annotations

import json
from pathlib import Path

import pytest

import route_precipitation_sampler as precipitation_sampler
from cwa_precipitation_grid import parse_qpesums_grid
from route_precipitation_sampler import build_route_precipitation_trend


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "cwa" / "qpesums"


def _grid(dataset_id: str):
    payload = json.loads((FIXTURE_ROOT / f"{dataset_id}.small.json").read_text())
    return parse_qpesums_grid(
        payload,
        fetched_at="2026-07-13T10:42:00+08:00",
        coordinate_transformer=lambda lat, lon: (lat, lon),
    )


def test_route_current_and_target_rainfall_trend_is_compact_and_explicit() -> None:
    package = build_route_precipitation_trend(
        qpe_grid=_grid("O-B0045-001"),
        qpf_grid=_grid("F-B0046-001"),
        route_points=[(23.0, 121.0), (23.0125, 121.025)],
        current_position={
            "lat": 23.0,
            "lon": 121.0,
            "observedAt": "2026-07-13T10:40:00+08:00",
            "accuracyM": 15,
        },
        target_position={"lat": 23.0125, "lon": 121.025, "id": "CP-02"},
    )

    assert package["currentPosition"]["past1hMm"] == 1.0
    assert package["currentPosition"]["next1hMm"] == 2.0
    assert package["currentPosition"]["trend"] == "intensifying"
    assert package["target"]["id"] == "CP-02"
    assert package["target"]["past1hMm"] == 12.0
    assert package["target"]["next1hMm"] == 24.0
    assert package["corridor"]["maxNext1hMm"] == 24.0
    assert package["corridor"]["coveredRouteSampleCount"] <= package["corridor"][
        "sampleCount"
    ]
    assert package["dataDelayMinutes"] == 12
    assert 0 < package["confidence"] < 1
    serialized = json.dumps(package)
    assert '"lat"' not in serialized
    assert '"lon"' not in serialized
    assert "values" not in serialized
    assert package["boundary"]["runtimeSafetyTruth"] is False


def test_position_sampling_is_unknown_outside_grid_or_on_missing_cell() -> None:
    package = build_route_precipitation_trend(
        qpe_grid=_grid("O-B0045-001"),
        qpf_grid=_grid("F-B0046-001"),
        route_points=[(23.0, 121.0), (23.0125, 121.025)],
        current_position={
            "lat": 22.0,
            "lon": 120.0,
            "observedAt": "2026-07-13T10:40:00+08:00",
        },
        target_position={"lat": 23.0, "lon": 121.025, "id": "CP-MISSING"},
    )

    assert package["currentPosition"]["status"] == "outside_grid"
    assert package["target"]["status"] == "missing_cell"
    assert package["target"]["next1hMm"] is None


def test_route_only_package_waits_for_explicit_location_and_target() -> None:
    package = build_route_precipitation_trend(
        qpe_grid=_grid("O-B0045-001"),
        qpf_grid=_grid("F-B0046-001"),
        route_points=[(23.0, 121.0), (23.0125, 121.025)],
    )

    assert package["status"] == "awaiting_position_and_target"
    assert package["currentPosition"]["status"] == "not_provided"
    assert package["target"]["status"] == "not_provided"
    assert package["corridor"]["sampleCount"] > 0


def test_route_trend_rejects_misaligned_qpe_qpf_grids() -> None:
    qpf = _grid("F-B0046-001")
    shifted = qpf.model_copy(
        update={
            "bounds_wgs84": (
                qpf.bounds_wgs84[0] + 0.1,
                qpf.bounds_wgs84[1],
                qpf.bounds_wgs84[2] + 0.1,
                qpf.bounds_wgs84[3],
            )
        }
    )

    with pytest.raises(ValueError, match="bounds do not align"):
        build_route_precipitation_trend(
            qpe_grid=_grid("O-B0045-001"),
            qpf_grid=shifted,
            route_points=[(23.0, 121.0), (23.0125, 121.025)],
        )


def test_expired_qpf_is_stale_with_zero_confidence() -> None:
    package = build_route_precipitation_trend(
        qpe_grid=_grid("O-B0045-001"),
        qpf_grid=_grid("F-B0046-001"),
        route_points=[(23.0, 121.0), (23.0125, 121.025)],
        evaluated_at="2026-07-13T13:00:00+08:00",
    )

    assert package["status"] == "stale_data"
    assert package["confidence"] == 0
    assert package["dataFreshness"]["qpfExpired"] is True


def test_route_trend_never_reports_ready_without_route_or_point_coverage() -> None:
    package = build_route_precipitation_trend(
        qpe_grid=_grid("O-B0045-001"),
        qpf_grid=_grid("F-B0046-001"),
        route_points=[(22.0, 120.0), (22.1, 120.1)],
        current_position={
            "lat": 22.0,
            "lon": 120.0,
            "observedAt": "2026-07-13T10:40:00+08:00",
        },
        target_position={"lat": 22.1, "lon": 120.1, "id": "OUTSIDE"},
    )

    assert package["currentPosition"]["status"] == "outside_grid"
    assert package["target"]["status"] == "outside_grid"
    assert package["corridor"]["coveredRouteSampleCount"] == 0
    assert package["confidence"] == 0
    assert package["status"] != "ready"


def test_route_trend_never_reports_ready_for_no_data_positions() -> None:
    package = build_route_precipitation_trend(
        qpe_grid=_grid("O-B0045-001"),
        qpf_grid=_grid("F-B0046-001"),
        route_points=[(23.0, 121.0), (23.0125, 121.025)],
        current_position={
            "lat": 23.0,
            "lon": 121.025,
            "observedAt": "2026-07-13T10:40:00+08:00",
        },
        target_position={"lat": 23.0, "lon": 121.025, "id": "NO-DATA"},
    )

    assert package["currentPosition"]["status"] == "missing_cell"
    assert package["target"]["status"] == "missing_cell"
    assert package["status"] != "ready"


def test_current_position_observed_at_is_compared_with_evaluated_at() -> None:
    package = build_route_precipitation_trend(
        qpe_grid=_grid("O-B0045-001"),
        qpf_grid=_grid("F-B0046-001"),
        route_points=[(23.0, 121.0), (23.0125, 121.025)],
        current_position={
            "lat": 23.0,
            "lon": 121.0,
            "observedAt": "2026-07-13T13:00:00+08:00",
        },
        target_position={"lat": 23.0125, "lon": 121.025, "id": "CP-02"},
        evaluated_at="2026-07-13T13:00:00+08:00",
    )

    assert package["status"] == "stale_data"
    assert package["confidence"] == 0


def test_route_data_status_is_partial_when_only_part_of_route_is_covered() -> None:
    status = precipitation_sampler._route_data_status(
        requested_status="ready",
        current={"status": "ready"},
        target={"status": "outside_grid"},
        corridor={"sampleCount": 4, "coveredRouteSampleCount": 2},
        provided=2,
    )

    assert status == "partial"


@pytest.mark.parametrize(
    ("accuracy_m", "expected"),
    [(35, 0.9), (75, 0.8), (200, 0.65), (501, 0.4)],
)
def test_accuracy_factor_uses_expected_distance_buckets(
    accuracy_m: int,
    expected: float,
) -> None:
    assert precipitation_sampler._accuracy_factor({"accuracyM": accuracy_m}) == expected
