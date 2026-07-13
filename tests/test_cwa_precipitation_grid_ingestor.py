from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

import cwa_precipitation_grid_ingestor as precipitation_ingestor
from cwa_precipitation_grid_ingestor import prepare_cwa_precipitation_workspace


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "cwa" / "qpesums"


def _payloads() -> dict[str, dict[str, object]]:
    return {
        dataset_id: json.loads((FIXTURE_ROOT / f"{dataset_id}.small.json").read_text())
        for dataset_id in ("O-B0045-001", "F-B0046-001")
    }


def test_prepare_cwa_precipitation_workspace_writes_numeric_frames_and_projection(
    tmp_path: Path,
) -> None:
    payloads = _payloads()
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


def test_prepared_artifacts_bind_project_route_and_source_frame_identity(
    tmp_path: Path,
) -> None:
    payloads = _payloads()
    route_source_ref = "outputs/route/segment_display_geometry.json"
    route_source_sha256 = "a" * 64

    refs = prepare_cwa_precipitation_workspace(
        project_root=tmp_path,
        project_id="fixture-route",
        route_points=[(23.0, 121.0), (23.0125, 121.025)],
        route_bbox={"west": 120.99, "south": 22.99, "east": 121.04, "north": 23.03},
        route_source_ref=route_source_ref,
        route_source_sha256=route_source_sha256,
        fetched_at="2026-07-13T10:42:00+08:00",
        fetcher=lambda dataset_id, **_kwargs: payloads[dataset_id],
        coordinate_transformer=lambda lat, lon: (lat, lon),
    )

    manifest = json.loads(
        (tmp_path / refs["cwa_rainfall_grid_manifest_ref"]).read_text()
    )
    projection = json.loads(
        (tmp_path / refs["cwa_rainfall_route_projection_ref"]).read_text()
    )
    trend = json.loads((tmp_path / refs["cwa_rainfall_route_trend_ref"]).read_text())
    source_frame_ids = {
        kind: frame["frameId"] for kind, frame in manifest["latestByKind"].items()
    }

    assert manifest["projectId"] == "fixture-route"
    for artifact in (projection, trend):
        assert artifact["projectId"] == "fixture-route"
        assert artifact["routeSourceRef"] == route_source_ref
        assert artifact["routeSourceSha256"] == route_source_sha256
        assert artifact["sourceFrameIds"] == source_frame_ids


def test_failed_generation_does_not_publish_a_mixed_artifact_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initial_payloads = _payloads()
    route_points = [(23.0, 121.0), (23.0125, 121.025)]
    route_bbox = {"west": 120.99, "south": 22.99, "east": 121.04, "north": 23.03}
    refs = prepare_cwa_precipitation_workspace(
        project_root=tmp_path,
        route_points=route_points,
        route_bbox=route_bbox,
        fetched_at="2026-07-13T10:42:00+08:00",
        fetcher=lambda dataset_id, **_kwargs: initial_payloads[dataset_id],
        coordinate_transformer=lambda lat, lon: (lat, lon),
    )
    paths = {
        key: tmp_path / refs[key]
        for key in (
            "cwa_rainfall_grid_manifest_ref",
            "cwa_rainfall_route_projection_ref",
            "cwa_rainfall_route_trend_ref",
        )
    }
    previous = {key: path.read_bytes() for key, path in paths.items()}

    replacement_payloads = deepcopy(initial_payloads)
    for payload in replacement_payloads.values():
        parameters = payload["cwaopendata"]["dataset"]["datasetInfo"]["parameterSet"]
        parameters["DateTime"] = "2026-07-13T10:40:00+08:00"

    def fail_projection(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise RuntimeError("projection failed after grid persistence")

    monkeypatch.setattr(
        precipitation_ingestor,
        "build_route_grid_projection",
        fail_projection,
    )

    with pytest.raises(RuntimeError, match="projection failed"):
        prepare_cwa_precipitation_workspace(
            project_root=tmp_path,
            route_points=route_points,
            route_bbox=route_bbox,
            fetched_at="2026-07-13T10:52:00+08:00",
            fetcher=lambda dataset_id, **_kwargs: replacement_payloads[dataset_id],
            coordinate_transformer=lambda lat, lon: (lat, lon),
        )

    assert {key: path.read_bytes() for key, path in paths.items()} == previous
