from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from cwa_precipitation_grid import parse_qpesums_grid


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "cwa" / "qpesums"


def _fixture(dataset_id: str) -> dict[str, object]:
    return json.loads((FIXTURE_ROOT / f"{dataset_id}.small.json").read_text())


def _identity(lat: float, lon: float) -> tuple[float, float]:
    return lat, lon


@pytest.mark.parametrize(
    ("dataset_id", "kind", "nodata", "south_row", "north_row"),
    [
        ("O-B0045-001", "qpe_past_1h", -1.0, [1.0, 2.0, None], [4.0, 8.0, 12.0]),
        ("F-B0046-001", "qpf_next_1h", -99.0, [2.0, 4.0, None], [6.0, 12.0, 24.0]),
    ],
)
def test_parse_qpesums_grid_preserves_georef_time_units_and_row_order(
    dataset_id: str,
    kind: str,
    nodata: float,
    south_row: list[float | None],
    north_row: list[float | None],
) -> None:
    grid = parse_qpesums_grid(
        _fixture(dataset_id),
        fetched_at="2026-07-13T10:42:00+08:00",
        coordinate_transformer=_identity,
    )

    assert grid.dataset_id == dataset_id
    assert grid.grid_kind == kind
    assert grid.unit == "mm"
    assert grid.source_timestamp.isoformat() == "2026-07-13T10:30:00+08:00"
    assert grid.fetched_at.isoformat() == "2026-07-13T10:42:00+08:00"
    assert grid.data_delay_minutes == 12
    assert grid.width == 3
    assert grid.height == 2
    assert grid.resolution_degrees == pytest.approx(0.0125)
    assert grid.source_crs == "TWD67"
    assert grid.output_crs == "EPSG:4326"
    assert grid.source_nodata == nodata
    assert len(grid.source_payload_sha256) == 64
    assert grid.georeference_metadata_authority == "datasetInfo.parameterSet"
    assert grid.values == (tuple(north_row), tuple(south_row))
    assert grid.bounds_wgs84 == pytest.approx((120.99375, 22.99375, 121.03125, 23.01875))
    assert grid.update_interval_minutes == 10
    assert grid.boundary.candidate_only is True
    assert grid.boundary.runtime_safety_truth is False
    assert grid.boundary.server_side_only is True
    dumped = grid.model_dump(mode="json")
    assert "Authorization" not in json.dumps(dumped)
    assert "cwaopendata" not in dumped


@pytest.mark.parametrize(
    "mutator",
    [
        lambda payload: payload["cwaopendata"]["dataset"]["contents"].update({"content": "1,2"}),
        lambda payload: payload["cwaopendata"]["dataset"]["datasetInfo"]["parameterSet"].update({"GridDimensionX": "0"}),
        lambda payload: payload["cwaopendata"]["dataset"]["contents"].update({"content": "1,2,NaN,4,5,6"}),
        lambda payload: payload["cwaopendata"]["dataset"]["datasetInfo"]["parameterSet"].update({"Precipitation": "dBZ"}),
        lambda payload: payload["cwaopendata"].update({"dataid": "UNKNOWN"}),
    ],
)
def test_parse_qpesums_grid_rejects_malformed_or_unsafe_values(mutator: object) -> None:
    payload = _fixture("O-B0045-001")
    mutator(payload)  # type: ignore[operator]
    with pytest.raises(ValueError):
        parse_qpesums_grid(
            payload,
            fetched_at="2026-07-13T10:42:00+08:00",
            coordinate_transformer=_identity,
        )


def test_qpe_and_qpf_validity_windows_are_not_confused() -> None:
    qpe = parse_qpesums_grid(
        _fixture("O-B0045-001"),
        fetched_at=datetime.fromisoformat("2026-07-13T10:42:00+08:00"),
        coordinate_transformer=_identity,
    )
    qpf = parse_qpesums_grid(
        _fixture("F-B0046-001"),
        fetched_at=datetime.fromisoformat("2026-07-13T10:42:00+08:00"),
        coordinate_transformer=_identity,
    )

    assert (qpe.valid_until - qpe.valid_from).total_seconds() == 3600
    assert qpe.valid_until == qpe.source_timestamp
    assert qpf.valid_from == qpf.source_timestamp
    assert (qpf.valid_until - qpf.valid_from).total_seconds() == 3600


def test_structured_origin_wins_and_records_provider_description_discrepancy() -> None:
    payload = _fixture("F-B0046-001")
    payload["cwaopendata"]["dataset"]["contents"]["contentDescription"] = (
        "左下角為第一點東經117.975、北緯19.975，為TWD67經緯網格"
    )

    grid = parse_qpesums_grid(
        payload,
        fetched_at="2026-07-13T10:42:00+08:00",
        coordinate_transformer=_identity,
    )

    assert grid.source_metadata_warnings == (
        "content_description_origin_disagrees_with_structured_parameter_set",
    )
