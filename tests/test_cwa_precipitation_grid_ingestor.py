from __future__ import annotations

import json
from pathlib import Path

from cwa_precipitation_grid_ingestor import prepare_cwa_precipitation_workspace


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "cwa" / "qpesums"


def test_prepare_cwa_precipitation_workspace_writes_numeric_frames_and_projection(
    tmp_path: Path,
) -> None:
    payloads = {
        dataset_id: json.loads((FIXTURE_ROOT / f"{dataset_id}.small.json").read_text())
        for dataset_id in ("O-B0045-001", "F-B0046-001")
    }
    calls: list[str] = []

    def fetcher(dataset_id: str, **_kwargs: object) -> dict[str, object]:
        calls.append(dataset_id)
        return payloads[dataset_id]

    refs = prepare_cwa_precipitation_workspace(
        project_root=tmp_path,
        route_points=[(23.0, 121.0), (23.0125, 121.025)],
        route_bbox={"west": 120.99, "south": 22.99, "east": 121.04, "north": 23.03},
        fetched_at="2026-07-13T10:42:00+08:00",
        fetcher=fetcher,
        coordinate_transformer=lambda lat, lon: (lat, lon),
    )

    assert calls == ["O-B0045-001", "F-B0046-001"]
    assert refs["cwa_rainfall_grid_manifest_ref"] == (
        "outputs/environment/cwa/rainfall/rainfall_grid_manifest.json"
    )
    assert refs["cwa_rainfall_route_projection_ref"] == (
        "outputs/environment/cwa/rainfall/route_grid_projection.geojson"
    )
    assert refs["cwa_rainfall_route_trend_ref"] == (
        "outputs/environment/cwa/rainfall/route_precipitation_trend.json"
    )
    for ref_key in (
        "cwa_rainfall_grid_manifest_ref",
        "cwa_rainfall_route_projection_ref",
        "cwa_rainfall_route_trend_ref",
    ):
        assert (tmp_path / refs[ref_key]).is_file()

    projection = json.loads(
        (tmp_path / refs["cwa_rainfall_route_projection_ref"]).read_text()
    )
    assert {feature["properties"]["gridKind"] for feature in projection["features"]} == {
        "qpe_past_1h",
        "qpf_next_1h",
    }
    assert all(feature["properties"]["unit"] == "mm" for feature in projection["features"])
    assert projection["boundary"]["runtimeSafetyTruth"] is False

    trend = json.loads((tmp_path / refs["cwa_rainfall_route_trend_ref"]).read_text())
    assert trend["status"] == "awaiting_position_and_target"
    assert trend["corridor"]["maxNext1hMm"] == 24.0
    assert trend["boundary"]["rawCoordinatesPersisted"] is False
