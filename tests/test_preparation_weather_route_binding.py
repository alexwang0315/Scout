"""Replay the new-import ordering with real GPX/alignment/weather artifact code."""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

import pretrip_layer_preparation as preparation
from cwa_precipitation_grid_ingestor import prepare_cwa_precipitation_workspace
from cwa_route_identity import load_cwa_route_identity, validate_cwa_artifact_route_identity
from pretrip_import import PretripImportRequest, run_pretrip_import
from pretrip_layer_preparation import LayerPreparationRequest, run_layer_preparation


SCALAR_TIME = "2026-07-13T02:42:00+00:00"
FINAL_TIME = "2026-07-13T02:45:00+00:00"
SOURCE_TIME = "2026-07-13T10:30:00+08:00"
GRID_FIXTURES = Path(__file__).parent / "fixtures/cwa/qpesums"


def _read(path: Path) -> dict:
    return json.loads(path.read_text())


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


@pytest.fixture
def imported_weather_route(tmp_path, monkeypatch):
    golden = tmp_path / "golden.gpx"
    golden.write_text(
        '<gpx xmlns="http://www.topografix.com/GPX/1/1" version="1.1" creator="test">'
        '<trk><name>Weather binding</name><trkseg>'
        + ''.join(
            f'<trkpt lat="23.00002" lon="{lon}"><ele>1000</ele>'
            f'<time>2026-07-12T00:{minute:02d}:00Z</time></trkpt>'
            for lon, minute in ((121.001, 0), (121.010, 15), (121.020, 30), (121.025, 45))
        ) + '</trkseg></trk></gpx>'
    )
    run_pretrip_import(PretripImportRequest(
        project_id="weather_binding", primary_gpx=golden,
        workspace_root=tmp_path / "workspace", profile="pi-offline",
        checkpoint_spacing_m=500, import_timestamp=SCALAR_TIME,
    ))
    root = tmp_path / "workspace/weather_binding"
    project = _read(root / "project.json")
    base_identity, _ = load_cwa_route_identity(root, project)
    assert base_identity["routeBasis"] == "segment_display_geometry"
    assert not (root / "outputs/overpass_aligned_segment_display_geometry.json").exists()
    events = []
    captured = {}

    # Replace unavailable worker/provider boundaries, keeping importer, local
    # MCP collection, both alignment attempts, projection and sampler code real.
    for name in (
        "_maybe_fetch_overpass_evidence", "_maybe_seed_imagery_tile_cache",
        "_maybe_prepare_local_osm_pbf_evidence", "_write_map_preparation_spec_artifacts",
    ):
        monkeypatch.setattr(preparation, name, lambda *_args, **_kwargs: None)
    for name in (
        "_run_route_context_source_refresh_after_map_preparation",
        "_run_qgis_terrain_route_hypothesis_after_layer_preparation",
        "_prepare_workspace_terrain_dem_after_terrain",
        "_refresh_terrain_risk_candidate_artifact_after_qgis_risk",
        "_run_raster_label_preparation_after_layer_preparation",
        "_run_boss_point_synthesis_after_layer_preparation",
        "_run_mileage_tag_alignment_after_layer_preparation",
        "_run_reference_segment_timing_after_layer_preparation",
        "_run_architecture_preparation_after_layer_preparation",
        "_run_navigation_terrain_dem_after_layer_preparation",
        "_run_navigation_terrain_projection_after_layer_preparation",
    ):
        monkeypatch.setattr(preparation, name, lambda **_kwargs: {
            "status": "not_requested", "output_refs": {},
        })
    monkeypatch.setattr(preparation, "_run_qgis_terrain_feature_stack_after_layer_preparation",
                        lambda **_kwargs: {"status": "completed", "output_refs": {}})

    def publish_risk_centerline(**_kwargs):
        evidence = _read(root / "outputs/environment/cwa/cwa_weather_evidence.json")
        captured["scalar_evidence"] = evidence
        assert evidence["rainfall_grids"]["status"] == "deferred_until_final_route"
        assert "numeric" not in events and "imagery" not in events
        events.append("risk_centerline")
        current = _read(root / "project.json")
        ref = "outputs/risk/risk_ribbon.geojson"
        _write(root / ref, {"type": "FeatureCollection", "features": [{
            "type": "Feature", "properties": {"segment_id": "recorded.overpass.1",
                "start_distance_m": 0, "end_distance_m": 2500},
            "geometry": {"type": "LineString", "coordinates": [
                [121.0, 23.0], [121.01, 23.0], [121.02, 23.0], [121.026, 23.0],
            ]},
        }]})
        _write(root / "project.json", {**current, "risk_ribbon_ref": ref})
        return {"status": "completed"}

    monkeypatch.setattr(preparation, "_finalize_qgis_dependent_risk_state", publish_risk_centerline)
    monkeypatch.setattr(preparation, "_utc_now", lambda: FINAL_TIME if "risk_centerline" in events else SCALAR_TIME)

    import scout_weather_integration as weather
    monkeypatch.setenv("SCOUT_CWA_API_KEY", "test-only")
    monkeypatch.setenv("SCOUT_CWA_SERVER_IMAGERY_CAPABLE", "1")
    monkeypatch.setattr(weather, "fetch_cwa_dataset", lambda dataset_id, **_kwargs:
                        events.append("scalar:" + dataset_id) or {})
    monkeypatch.setattr(weather, "normalize_cwa_weather_points", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(weather, "normalize_cwa_warnings", lambda *_args, **_kwargs: [])

    def grid_fetch(dataset_id, **_kwargs):
        events.append("grid:" + dataset_id)
        return _read(GRID_FIXTURES / f"{dataset_id}.small.json")

    monkeypatch.setattr(weather, "fetch_cwa_file_dataset", grid_fetch)
    numeric_job = preparation._maybe_prepare_cwa_precipitation_grid_job

    def numeric(**kwargs):
        events.append("numeric")
        captured["numeric_identity"], _ = load_cwa_route_identity(root, kwargs["project"])
        captured["numeric_time"] = kwargs["prepared_at"]
        return numeric_job(**kwargs)

    monkeypatch.setattr(preparation, "_maybe_prepare_cwa_precipitation_grid_job", numeric)

    import radar_satellite_risk_extractor as imagery
    from cwa_radar_ingestor import CwaRadarIngestor
    from cwa_satellite_ingestor import CwaSatelliteIngestor
    from route_imagery_sampler import RasterGrid

    def metadata(spec):
        return {"sourceTimestamp": "2026-07-13T02:30:00Z", "url": spec.latest_url}

    def fixture_ingestor(kind, *, registry, cache):
        return kind(registry=registry, cache=cache, latest_metadata_fetcher=metadata,
                    history_metadata_fetcher=lambda spec, _hours: [metadata(spec)],
                    bytes_fetcher=lambda url: (b"fixture-weather-frame",
                        "image/png" if url.endswith(".png") else "image/jpeg", "test"))

    monkeypatch.setattr(CwaRadarIngestor, "from_cwa_opendata",
                        lambda **kwargs: fixture_ingestor(CwaRadarIngestor, **kwargs))
    monkeypatch.setattr(CwaSatelliteIngestor, "from_cwa_opendata",
                        lambda **kwargs: fixture_ingestor(CwaSatelliteIngestor, **kwargs))
    monkeypatch.setattr(imagery.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(imagery, "_is_raspberry_pi_host", lambda: False)
    image_job = imagery.run_server_side_cwa_imagery_job

    def images(**kwargs):
        events.append("imagery")
        captured["imagery_identity"] = kwargs["route_identity"]
        try:
            return image_job(**kwargs, build_display_assets=False, min_job_interval_seconds=0,
                             frame_grid_decoder=lambda _frame, _cache: RasterGrid(
                                 west=120, south=22, east=122, north=24,
                                 values=((1.0, 2.0), (3.0, 4.0))))
        except Exception as exc:
            captured["imagery_exception"] = str(exc)
            raise

    monkeypatch.setattr(imagery, "run_server_side_cwa_imagery_job", images)
    request = LayerPreparationRequest(
        project_id="weather_binding", project_root=root,
        layers=("overpass", "mcp", "cwa-weather", "cwa-qpf"),
        profile="mac-workstation", network_mode="explicit-fetch", allow_network_fetch=True,
        prepare_cwa_imagery=True,
    )
    return root, request, events, captured, base_identity


def test_new_import_publishes_route_weather_after_real_late_alignment(imported_weather_route):
    root, request, events, captured, base_identity = imported_weather_route
    original_geometry = (root / base_identity["routeRef"]).read_bytes()
    manifest = run_layer_preparation(request)
    assert manifest["overpass_route_alignment"]["status"] == "skipped_missing_overpass_centerline"
    assert manifest["mcp_overpass_route_alignment"]["status"] == "completed"
    assert manifest["mcp_overpass_route_alignment"]["counts"]["snapped_point_count"] > 0
    project = _read(root / "project.json")
    identity, _ = load_cwa_route_identity(root, project)
    assert identity["routeBasis"] == "overpass_aligned_segment_display_geometry"
    assert identity["routeSha256"] != base_identity["routeSha256"]
    assert captured["numeric_identity"] == captured["imagery_identity"] == identity
    assert "imagery_exception" not in captured, captured.get("imagery_exception")
    assert events.count("numeric") == events.count("imagery") == 1
    assert events.index("risk_centerline") < events.index("numeric") < events.index("imagery")
    assert events.count("grid:O-B0045-001") == events.count("grid:F-B0046-001") == 1
    assert sum(event.startswith("scalar:") for event in events) == 3
    assert captured["numeric_time"] == FINAL_TIME
    assert (root / base_identity["routeRef"]).read_bytes() == original_geometry

    rainfall_keys = ("cwa_rainfall_grid_manifest_ref", "cwa_rainfall_route_projection_ref",
                     "cwa_rainfall_route_trend_ref")
    image_keys = ("cwa_weather_imagery_manifest_ref", "route_imagery_sampling_ref",
                  "route_weather_risk_package_ref")
    for ref_keys in (rainfall_keys, image_keys):
        artifacts = [_read(root / project[key]) for key in ref_keys]
        for artifact in artifacts:
            assert validate_cwa_artifact_route_identity(root, project, artifact, artifact_label="test") == "verified"
            assert artifact["pairId"] == artifacts[0]["pairId"]
            assert artifact["sourceFrameIds"] == artifacts[0]["sourceFrameIds"]
    grid_manifest = _read(root / project[rainfall_keys[0]])
    assert all(frame["sourceTimestamp"] == SOURCE_TIME for frame in grid_manifest["frames"])
    assert all(frame["fetchedAt"] == FINAL_TIME for frame in grid_manifest["frames"])
    evidence = _read(root / project["cwa_weather_evidence_ref"])
    assert evidence["cwa_time_metadata"] == captured["scalar_evidence"]["cwa_time_metadata"]
    assert evidence["generated_at"] == SCALAR_TIME
    assert evidence["route_evidence"]["prepared_at"] == FINAL_TIME
    assert manifest["cwa_route_evidence"]["substatuses"] == {"rainfall": "ready", "imagery": "ready"}
    for layer in manifest["layers"]:
        if layer["layer_id"] in {"cwa-weather", "cwa-qpf"}:
            assert layer["route_evidence"]["status"] == "ready"
            for source in layer["source_refs"]:
                assert source["sha256"] == hashlib.sha256((root / source["ref"]).read_bytes()).hexdigest()
    for key in ("layer_preparation_summary_ref", "map_preparation_summary_ref"):
        assert _read(root / project[key])["cwa_route_evidence"] == manifest["cwa_route_evidence"]
    environment = _read(root / project["environment_evidence_package_ref"])
    assert environment["cwa_route_evidence"] == evidence["route_evidence"]
    assert environment["provider_status"]["cwa_rainfall_grid_status"] == "ready"
    assert set(project[key] for key in rainfall_keys + image_keys).issubset(environment["source_refs"])
    assert evidence["route_evidence"]["runtime_safety_truth"] is False
    assert {"O-B0045-001", "F-B0046-001"}.issubset(
        {item["dataset_id"] for item in evidence["datasets"]})


@pytest.mark.parametrize("failure_mode", ["fetch_failed", "stale_ready"])
def test_failure_preserves_old_route_data_and_strict_rejection(imported_weather_route, monkeypatch, failure_mode):
    root, request, _events, _captured, base_identity = imported_weather_route
    project = _read(root / "project.json")
    _, points = load_cwa_route_identity(root, project)
    old_outputs = prepare_cwa_precipitation_workspace(
        project_root=root, project_id=project["project_id"], route_points=points,
        route_bbox={"west": 120.99, "south": 22.99, "east": 121.04, "north": 23.03},
        route_source_ref=base_identity["routeRef"], route_source_sha256=base_identity["routeSha256"],
        route_basis=base_identity["routeBasis"], fetched_at=SCALAR_TIME,
        fetcher=lambda dataset_id, **_kwargs: _read(GRID_FIXTURES / f"{dataset_id}.small.json"),
    )
    _write(root / "project.json", {**project, **old_outputs})
    snapshots = {path: path.read_bytes() for path in (root / "outputs/environment/cwa/rainfall").rglob("*") if path.is_file()}
    if failure_mode == "fetch_failed":
        import scout_weather_integration
        def fail_fetch(*_args, **_kwargs):
            raise RuntimeError("provider fixture failure")
        monkeypatch.setattr(scout_weather_integration, "fetch_cwa_file_dataset", fail_fetch)
    else:
        monkeypatch.setattr(preparation, "_maybe_prepare_cwa_precipitation_grid_job", lambda **_kwargs: old_outputs)
    manifest = run_layer_preparation(request)
    project = _read(root / "project.json")
    assert manifest["cwa_route_evidence"]["status"] == "partial"
    assert project["cwa_rainfall_grid_status"] == (
        "fetch_or_processing_failed" if failure_mode == "fetch_failed" else "blocked_route_identity")
    assert all(path.read_bytes() == data for path, data in snapshots.items())
    old_projection = _read(root / old_outputs["cwa_rainfall_route_projection_ref"])
    with pytest.raises(ValueError, match="route identity mismatch"):
        validate_cwa_artifact_route_identity(root, project, old_projection, artifact_label="rainfall projection")
    evidence = _read(root / project["cwa_weather_evidence_ref"])
    assert evidence["rainfall_grids"]["route_projection_ref"] is None
    layer = next(row for row in manifest["layers"] if row["layer_id"] == "cwa-qpf")
    assert layer["status"] == "partial_route_evidence" and layer["warnings"]
    environment = _read(root / project["environment_evidence_package_ref"])
    assert any(gap["source_kind"] == "cwa_route_rainfall" for gap in environment["missing_evidence"])


def test_connected_refresh_retains_immediate_route_jobs(imported_weather_route, monkeypatch):
    root, request, events, captured, base_identity = imported_weather_route
    primary_manifest = root / "outputs/layers/layer_preparation_manifest.json"
    _write(primary_manifest, {"preserve": "full preparation"})
    original = primary_manifest.read_bytes()
    monkeypatch.setattr(preparation, "_finalize_qgis_dependent_risk_state", lambda **_kwargs: {"status": "not_requested"})
    manifest = run_layer_preparation(replace(
        request, layers=("cwa-weather", "cwa-qpf"),
        run_post_layer_enrichments=False, run_map_preparation_spec_artifacts=False,
        publish_preparation_outputs=False,
    ))
    assert "cwa_route_evidence" not in manifest
    assert "risk_centerline" not in events
    assert events.count("numeric") == events.count("imagery") == 1
    assert captured["numeric_identity"] == captured["imagery_identity"] == base_identity
    assert primary_manifest.read_bytes() == original
    evidence = _read(root / "outputs/environment/cwa/cwa_weather_evidence.json")
    assert evidence["rainfall_grids"]["status"] == evidence["weather_imagery"]["status"] == "ready"


def test_current_route_with_mixed_numeric_pair_is_not_ready(imported_weather_route, monkeypatch):
    root, request, _events, _captured, _base_identity = imported_weather_route
    real_numeric = preparation._maybe_prepare_cwa_precipitation_grid_job
    def mixed_pair(**kwargs):
        outputs = real_numeric(**kwargs)
        trend_path = root / outputs["cwa_rainfall_route_trend_ref"]
        trend = _read(trend_path)
        trend["pairId"] = "cwa.rainfall.pair.other"
        _write(trend_path, trend)
        return outputs
    monkeypatch.setattr(preparation, "_maybe_prepare_cwa_precipitation_grid_job", mixed_pair)
    manifest = run_layer_preparation(request)
    assert manifest["cwa_route_evidence"]["substatuses"]["rainfall"] == "blocked_route_identity"
    assert manifest["cwa_route_evidence"]["status"] == "partial"


def test_imagery_failure_keeps_verified_numeric_result_and_reports_gap(imported_weather_route, monkeypatch):
    root, request, _events, _captured, _base_identity = imported_weather_route
    monkeypatch.setattr(preparation, "_maybe_prepare_cwa_imagery_server_job", lambda **_kwargs: {
        "cwa_weather_imagery_status": "fetch_or_processing_failed",
    })
    manifest = run_layer_preparation(request)
    project = _read(root / "project.json")
    assert manifest["cwa_route_evidence"]["substatuses"] == {
        "rainfall": "ready", "imagery": "fetch_or_processing_failed",
    }
    projection = _read(root / project["cwa_rainfall_route_projection_ref"])
    assert validate_cwa_artifact_route_identity(root, project, projection, artifact_label="rainfall") == "verified"
    evidence = _read(root / project["cwa_weather_evidence_ref"])
    assert evidence["weather_imagery"]["manifest_ref"] is None
    weather_layer = next(row for row in manifest["layers"] if row["layer_id"] == "cwa-weather")
    assert weather_layer["status"] == "partial_route_evidence"
    environment = _read(root / project["environment_evidence_package_ref"])
    assert any(gap["source_kind"] == "cwa_route_imagery" for gap in environment["missing_evidence"])
