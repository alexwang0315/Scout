"""Bounded preparation tests: real canonical bundle, isolated provider seams."""
from __future__ import annotations

import copy
import hashlib
import json
import xml.etree.ElementTree as ET

import pytest

import scout_planned_preparation as preparation
from scout_planned_analysis import planned_binding
from scout_planned_route import compile_planned_route
from scout_planned_route_artifacts import PlannedSaveRequest, get_planned_version, save_planned_version
from scout_planned_route_models import PlannedRouteRequest
from scout_planned_route_sources import fetch_trail_source_candidates
from test_scout_planned_route import _gpx, _write, planned_workspace
from test_scout_planned_route_sources import _way


def _hashes(root):
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file()}


def _save(root, **changes):
    request = PlannedRouteRequest(departure_at="2026-10-01T06:00:00+08:00", default_speed_kmh=2, **changes)
    preview = compile_planned_route(root, request)
    saved = save_planned_version(root, PlannedSaveRequest(request=request,
        expected_preview_sha256=preview["preview_sha256"], idempotency_key="prepare.fixture", explicit_confirmation=True))
    return get_planned_version(root, saved["version_id"])


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    root = planned_workspace(tmp_path)
    raw = tmp_path / "raw_dem.tif"
    raw.write_bytes(b"fixture-raw-raster-only-provider-is-mocked")
    source = {"path": str(raw), "role": "raw_regional_dem", "sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
              "crs": "EPSG:3826", "source_resolution_m": 20}
    _write(root, "inbox/source_manifest.json", {"project_id": root.name,
        "preparation_inputs": {"dtm_rasters": [source], "dtm_dirs": []}})
    bundle = _save(root, human_text="從營地 A 單攻山頭 B 後回營地 A")
    calls = []

    def fetch(bbox):
        data = json.dumps({"elements": [_way(10, [1, 2], [(121, 24), (121.002, 24.003)])]}).encode()
        return fetch_trail_source_candidates(bbox, fetcher=lambda *_: data, requested_at="2026-09-10T00:00:00Z")

    def terrain(part_root, *, backend, request_id):
        project = json.loads((part_root / "project.json").read_bytes())
        route = json.loads((part_root / project["route_evidence_bundle_ref"]).read_bytes())
        xml = ET.parse(part_root / route["golden_route"]["filtered_geometry_ref"])
        points = [(float(point.attrib["lat"]), float(point.attrib["lon"]))
                  for point in xml.getroot().iter() if point.tag.rsplit("}", 1)[-1] == "trkpt"]
        calls.append({"root": part_root, "points": points, "request_id": request_id})
        output = {"terrain_dem_route_bbox_raster_ref": "outputs/dem.tif",
                  "terrain_feature_manifest_ref": "outputs/terrain.json",
                  "terrain_visualization_ref": "outputs/visualization.json"}
        for key, ref in output.items():
            preparation._write(part_root, ref, b"fixture-computed-dem" if ref.endswith(".tif") else
                               {"source_hashes": {"inputs/route.gpx": route["golden_route"]["filtered_geometry_sha256"]}, **preparation.BOUNDARY})
        preparation._write(part_root, "project.json", {**project, **output}, immutable=False)
        return {"status": "completed", "actual_processor": "qgis_processing_grass", "workflow_run_id": request_id,
                "output_refs": output}

    monkeypatch.setattr(preparation, "fetch_trail_source_candidates", fetch)
    monkeypatch.setattr(preparation, "_qgis_backend", lambda: object())
    monkeypatch.setattr(preparation, "_run_terrain_part", terrain)
    monkeypatch.setattr(preparation, "_sample_dem", lambda path, points: {
        "values": [100 + index for index, _ in enumerate(points)], "resolution_m": [20, 20], "crs": "EPSG:3826",
        "sampling_method": "native_dem_cell_at_exact_planned_point", "interpolated": False})
    return root, bundle, tmp_path / "run", raw, calls


def test_canonical_graph_is_byte_identical_and_owner_unchanged(inputs):
    root, bundle, run, _, calls = inputs
    before = _hashes(root)
    progress = []
    result = preparation.prepare_planned_inputs(root, bundle, run, progress=progress.append)
    assert result["status"] == "completed", result["gaps"]
    assert result["subject_binding"] == planned_binding(bundle)
    assert result["coverage"]["terrain_point_coverage"] == "verified"
    assert _hashes(root) == before
    for key, filename in preparation.CANONICAL_FILES.items():
        assert hashlib.sha256((run / result["canonical_refs"][key]).read_bytes()).hexdigest() == bundle["manifest"]["files"][filename]["sha256"]
    mapping = json.loads((run / result["mapping_ref"]).read_bytes())
    assert [p for part in mapping["parts"] for p in part["planned_point_indices"]] == list(range(len(bundle["preview"]["route_axis"])))
    assert len(calls) == len(mapping["parts"])
    assert mapping["checkpoint_count"] == len(bundle["preview"]["checkpoints"])
    assert result["coverage"]["gaps_filled"] is False
    assert all(part["analysis_margin_m"] == 500 for part in result["terrain_parts"])
    assert result["candidate_only"] is True and result["runtime_safety_truth"] is False
    assert all(event["stage"] in {"canonical_inputs", "map", "terrain"} for event in progress)
    assert not list(run.rglob("reviewed*.json"))


def test_nested_job_attempt_only_writes_its_own_namespace(inputs):
    root, bundle, _, _, _ = inputs
    before = _hashes(root)
    run = root / "outputs/planned_analysis/runs/run.test/attempts/0001"
    result = preparation.prepare_planned_inputs(root, bundle, run)
    assert result["status"] == "completed"
    after = _hashes(root)
    assert all(after[ref] == sha for ref, sha in before.items())
    assert all(ref in before or ref.startswith("outputs/planned_analysis/runs/run.test/attempts/0001/") for ref in after)


def test_original_long_gap_remains_separate_worker_inputs(inputs):
    root, old, run, _, calls = inputs
    parent = run.parent / "gap_fixture"
    parent.mkdir()
    target = planned_workspace(parent)
    points = [(24, 121, 100, None), (24.00001, 121, 100, None),
              (24.011, 121, 100, None), (24.012, 121, 120, None)]
    sha = _write(target, "normalized/golden.gpx", _gpx([points]))
    report = json.loads((target / "outputs/gpx_speed_filter_report.json").read_bytes())
    report["primary"]["output_sha256"] = sha
    _write(target, "outputs/gpx_speed_filter_report.json", report)
    _write(target, "inbox/source_manifest.json", json.loads((root / "inbox/source_manifest.json").read_bytes()) | {"project_id": target.name})
    bundle = _save(target)
    result = preparation.prepare_planned_inputs(target, bundle, run)
    mapping = json.loads((run / result["mapping_ref"]).read_bytes())
    assert len(mapping["parts"]) == 2
    assert mapping["parts"][1]["gap_before"]["distance_m"] > 1_000
    assert calls[0]["points"] == [(24, 121), (24.00001, 121)]
    assert calls[1]["points"] == [(24.011, 121), (24.012, 121)]
    assert bundle["preview"]["itinerary"]["unknowns"]
    assert json.loads((run / result["canonical_refs"]["itinerary"]).read_bytes()) == bundle["preview"]["itinerary"]


@pytest.mark.parametrize("change", ["missing", "hash", "derived"])
def test_missing_changed_or_derived_dem_leaves_explicit_gap_without_old_ready(inputs, change):
    root, bundle, run, raw, calls = inputs
    if change == "missing":
        raw.rename(raw.with_suffix(".unavailable"))
    elif change == "hash":
        raw.write_bytes(b"new raw bytes")
    else:
        derived = root / "outputs/old_dem.tif"
        derived.parent.mkdir(exist_ok=True)
        derived.write_bytes(raw.read_bytes())
        source = json.loads((root / "inbox/source_manifest.json").read_bytes())
        source["preparation_inputs"]["dtm_rasters"][0]["path"] = str(derived)
        _write(root, "inbox/source_manifest.json", source)
    result = preparation.prepare_planned_inputs(root, bundle, run)
    assert result["status"] == "completed_with_gaps"
    assert result["coverage"]["terrain_point_coverage"] != "verified"
    assert "planned_raw_dem_unavailable" in {gap["code"] for gap in result["gaps"]}
    assert not calls


def test_remote_path_mapping_preserves_original_dem_hash(inputs):
    root, bundle, run, raw, _ = inputs
    remote = run.parent / "remote_source.tif"
    raw.rename(remote)
    result = preparation.prepare_planned_inputs(root, bundle, run, source_path_map={str(raw): str(remote)})
    assert result["status"] == "completed"
    assert result["external_source_bindings"] == [{"original_path": str(raw), "resolved_path": str(remote),
        "sha256": hashlib.sha256(remote.read_bytes()).hexdigest(), "role": "raw_dem"}]
    assert json.loads((root / "inbox/source_manifest.json").read_bytes())["preparation_inputs"]["dtm_rasters"][0]["path"] == str(raw)


def test_nodata_and_map_failure_are_concrete_partial_results(inputs, monkeypatch):
    root, bundle, run, _, _ = inputs
    monkeypatch.setattr(preparation, "fetch_trail_source_candidates", lambda *_: (_ for _ in ()).throw(OSError("offline")))
    monkeypatch.setattr(preparation, "_sample_dem", lambda path, points: {"values": [None] * len(points), "resolution_m": [20, 20]})
    result = preparation.prepare_planned_inputs(root, bundle, run)
    assert result["status"] == "completed_with_gaps"
    assert {"planned_map_unavailable", "planned_dem_nodata"} <= {gap["code"] for gap in result["gaps"]}
    assert result["coverage"]["status"] == "partial"


def test_tampered_bundle_rejected_before_network_or_writes(inputs, monkeypatch):
    root, bundle, run, _, _ = inputs
    changed = copy.deepcopy(bundle)
    changed["preview"]["route_axis"][0]["lon"] += 1
    monkeypatch.setattr(preparation, "fetch_trail_source_candidates", lambda *_: pytest.fail("network attempted"))
    with pytest.raises(preparation.PlannedPreparationError, match="saved Planned"):
        preparation.prepare_planned_inputs(root, changed, run)
    assert not run.exists()


@pytest.mark.parametrize("target", ["project", "reviews", "normalized"])
def test_output_roots_cannot_overwrite_owner_sources(inputs, target):
    root, bundle, _, _, _ = inputs
    destination = root if target == "project" else root / target
    with pytest.raises(preparation.PlannedPreparationError, match="isolated"):
        preparation.prepare_planned_inputs(root, bundle, destination)


def test_symlink_under_run_is_rejected_before_owner_write(inputs):
    root, bundle, run, _, _ = inputs
    run.mkdir()
    (run / "inputs").symlink_to(root)
    before = _hashes(root)
    with pytest.raises(preparation.PlannedPreparationError, match="symlinks"):
        preparation.prepare_planned_inputs(root, bundle, run)
    assert before == _hashes(root)


def test_pending_write_cannot_follow_symlink_into_owner(inputs):
    root, bundle, run, _, _ = inputs
    (run / "inputs").mkdir(parents=True)
    (run / "inputs/subject_binding.json.pending").symlink_to(root / "project.json")
    before = _hashes(root)
    with pytest.raises(preparation.PlannedPreparationError, match="symlinks"):
        preparation.prepare_planned_inputs(root, bundle, run)
    assert before == _hashes(root)


def test_large_parts_are_chunked_with_one_shared_endpoint_without_sampling(inputs, monkeypatch):
    root, bundle, run, _, calls = inputs
    monkeypatch.setattr(preparation, "MAX_WORKER_POINTS", 3)
    result = preparation.prepare_planned_inputs(root, bundle, run)
    mapping = json.loads((run / result["mapping_ref"]).read_bytes())
    for part in mapping["parts"]:
        chunks = [item for item in result["terrain_parts"] if item["part_index"] == part["part_index"]]
        edges = [(a, b) for chunk in chunks for a, b in zip(chunk["planned_point_indices"], chunk["planned_point_indices"][1:])]
        assert edges == list(zip(part["planned_point_indices"], part["planned_point_indices"][1:]))
    assert all(len(call["points"]) <= 3 for call in calls)


def test_real_qgis_bridge_receives_exact_planned_part_without_reimport(inputs, monkeypatch):
    from qgis_spatial_backend import QgisSpatialBackend, QgisSpatialBackendConfig
    from test_qgis_spatial_worker_bridge import TerrainFeatureWorkerTransport, _fixed_now, _test_access_value
    monkeypatch.undo()

    owner, bundle, run, _, _ = inputs
    axis = bundle["preview"]["route_axis"]
    part = preparation.build_planned_route_mapping(bundle["preview"])["parts"][0]
    indices = part["planned_point_indices"]
    points = [axis[index] for index in indices]
    root, _ = preparation._part_workspace(run, points, indices, preparation._raw_dem_inputs(owner, {}),
                                          planned_binding(bundle), 0, 0)

    class PlannedTransport(TerrainFeatureWorkerTransport):
        request_payload = {}

        def post_json(self, url, payload, *, timeout_s):
            self.request_payload = payload
            response = super().post_json(url, payload, timeout_s=timeout_s)
            return {**response, "project_id": root.name, "request_id": payload["request_id"]}

        def get_json(self, url, *, timeout_s):
            response = super().get_json(url, timeout_s=timeout_s)
            if url.endswith("/status"):
                return response
            return {**response, "project_id": root.name, "request_id": self.request_payload["request_id"]}

    transport = PlannedTransport()
    backend = QgisSpatialBackend(config=QgisSpatialBackendConfig(enabled=True,
        worker_url="http://127.0.0.1:9876", worker_token=_test_access_value()),
        transport=transport, now_factory=_fixed_now)
    # The production function uses this exact existing bridge. This replay only
    # replaces the HTTP transport; it never starts or contacts a worker.
    result = preparation._run_terrain_part(root, backend=backend, request_id="planned-recorded-bridge")
    assert result["status"] == "completed", json.dumps(result, indent=2)
    assert result["actual_processor"] == "qgis_processing_grass"
    coordinates = transport.request_payload["route_geojson"]["features"][0]["geometry"]["coordinates"]
    assert coordinates == [[point["lon"], point["lat"]] for point in points]
    assert transport.request_payload["source_hashes"]["inputs/route.gpx"] == hashlib.sha256((root / "inputs/route.gpx").read_bytes()).hexdigest()
    assert transport.request_payload["source_resolution"]["x_m"] == 20
    assert transport.request_payload["corridor_m"] == 500
    assert not list(root.rglob("*reviewed*"))


@pytest.mark.parametrize(("point_count", "length_m"), [(117, 6), (84, 23)])
def test_short_parts_keep_full_axis_with_sufficient_unchanged_coarse_window(inputs, point_count, length_m):
    from pretrip_source_ingest import wgs84_to_twd97
    from qgis_worker import _GEOMORPHON_SCALES, _route_rectangle_extent

    owner, _, run, _, _ = inputs
    points = [{"lat": 24 + length_m * index / (point_count-1) / 111_320, "lon": 121, "ele": 100}
              for index in range(point_count)]
    root, coverage = preparation._part_workspace(run, points, list(range(point_count)),
        preparation._raw_dem_inputs(owner, {}), {"fixture": "dense-short-part"}, 0, 0)
    gpx_points = [node for node in ET.parse(root / "inputs/route.gpx").getroot().iter()
                  if node.tag.rsplit("}", 1)[-1] == "trkpt"]
    assert [(float(node.attrib["lat"]), float(node.attrib["lon"])) for node in gpx_points] == [(p["lat"], p["lon"]) for p in points]
    assert coverage["coverage_scope"] == "planned_part_bbox_plus_500m"
    assert coverage["analysis_margin_m"] == 500
    expected_bbox = preparation._bbox(points, 500)
    assert coverage["route_bbox_wgs84"] == {"min_lat": expected_bbox["south"], "max_lat": expected_bbox["north"],
        "min_lon": expected_bbox["west"], "max_lon": expected_bbox["east"]}
    projected = [wgs84_to_twd97(point["lat"], point["lon"]) for point in points]
    # Invoke the actual worker extent builder, without running GIS processing.
    extent = _route_rectangle_extent({"xmin": min(p[0] for p in projected), "xmax": max(p[0] for p in projected),
        "ymin": min(p[1] for p in projected), "ymax": max(p[1] for p in projected)},
        corridor_m=coverage["analysis_margin_m"], resolution_m=20)
    assert dict(_GEOMORPHON_SCALES)["coarse"] == 20
    assert min(extent["width"], extent["height"]) >= 50
    assert min(extent["width"], extent["height"]) > 2 * dict(_GEOMORPHON_SCALES)["coarse"]


def test_selected_raw_tile_and_header_are_hash_bound(inputs):
    from pretrip_source_ingest import wgs84_to_twd97
    from test_pretrip_source_ingest import _write_header

    root, bundle, run, _, _ = inputs
    tiles = run.parent / "raw-tiles"
    tiles.mkdir()
    x, y = wgs84_to_twd97(24, 121)
    header = tiles / "inside_dem.hdr"
    grid = tiles / "inside_dem.grd"
    _write_header(header, tile_id="inside", origin_x=int(x) - 500, origin_y=int(y) - 500)
    grid.write_bytes(b"native-tile-fixture")
    _write(root, "inbox/source_manifest.json", {"project_id": root.name,
        "preparation_inputs": {"dtm_rasters": [], "dtm_dirs": [str(tiles)]}})
    result = preparation.prepare_planned_inputs(root, bundle, run)
    assert result["status"] == "completed", result["gaps"]
    assert {(item["resolved_path"], item["sha256"]) for item in result["external_source_bindings"]} == {
        (str(header), hashlib.sha256(header.read_bytes()).hexdigest()),
        (str(grid), hashlib.sha256(grid.read_bytes()).hexdigest())}
    for part in result["terrain_parts"]:
        coverage = json.loads((run / part["output_refs"]["dtm_coverage_summary_ref"]).read_bytes())
        assert coverage["candidate_tiles"][0]["grid_sha256"] == hashlib.sha256(grid.read_bytes()).hexdigest()


def test_raw_tile_change_during_worker_fails_publication(inputs, monkeypatch):
    root, bundle, run, raw, _ = inputs
    execute = preparation._run_terrain_part

    def mutate(*args, **kwargs):
        result = execute(*args, **kwargs)
        raw.write_bytes(b"changed-during-preparation")
        return result

    monkeypatch.setattr(preparation, "_run_terrain_part", mutate)
    with pytest.raises(preparation.PlannedPreparationError, match="changed during preparation"):
        preparation.prepare_planned_inputs(root, bundle, run)
    assert not (run / "preparation_result.json").exists()


def test_corridor_projection_does_not_create_a_line_across_original_gap():
    axis = [{"point_index": 0, "lat": 24.0, "lon": 121.0},
            {"point_index": 1, "lat": 24.0001, "lon": 121.0},
            {"point_index": 2, "lat": 24.02, "lon": 121.0, "break_before": True},
            {"point_index": 3, "lat": 24.0201, "lon": 121.0}]
    sources = [{"source_id": "gap-midpoint", "parts": [[{"lat": 24.01, "lon": 120.9999}, {"lat": 24.01, "lon": 121.0001}]]},
               {"source_id": "first-part", "parts": [[{"lat": 23.9999, "lon": 121.0}, {"lat": 24.0002, "lon": 121.0}]]}]
    projected = preparation._corridor_sources(sources, axis)
    assert [source["source_id"] for source in projected] == ["first-part"]
    assert projected[0]["parts"] == sources[1]["parts"]
    assert projected[0]["planned_projection"]["end_point_index"] < 2


def test_native_dem_sampling_keeps_revisits_nodata_and_outside_unknown(tmp_path):
    import importlib.util
    import numpy as np
    from pretrip_source_ingest import wgs84_to_twd97

    if importlib.util.find_spec("rasterio") is None and importlib.util.find_spec("osgeo") is None:
        pytest.skip("Native DEM reader runs on the Scout GIS runtime, not the lightweight Mac venv")
    path = tmp_path / "native-20m-dem.tif"
    point = {"lat": 24, "lon": 121}
    nodata_point = {"lat": 24.00018, "lon": 121}
    x, y = wgs84_to_twd97(point["lat"], point["lon"])
    transform = (x-50, 20, 0, y+50, 0, -20)
    data = np.full((5, 5), 713, dtype="float32")
    nx, ny = wgs84_to_twd97(nodata_point["lat"], nodata_point["lon"])
    data[int((ny-transform[3])/transform[5]), int((nx-transform[0])/transform[1])] = -9999
    if importlib.util.find_spec("rasterio") is not None:
        import rasterio
        from rasterio.transform import Affine
        with rasterio.open(path, "w", driver="GTiff", width=5, height=5, count=1,
                           dtype="float32", crs="EPSG:3826", transform=Affine.from_gdal(*transform), nodata=-9999) as dataset:
            dataset.write(data, 1)
    else:
        from osgeo import gdal, osr
        dataset = gdal.GetDriverByName("GTiff").Create(str(path), 5, 5, 1, gdal.GDT_Float32)
        crs = osr.SpatialReference()
        crs.ImportFromEPSG(3826)
        dataset.SetProjection(crs.ExportToWkt())
        dataset.SetGeoTransform(transform)
        dataset.GetRasterBand(1).SetNoDataValue(-9999)
        dataset.GetRasterBand(1).WriteArray(data)
        dataset = None
    sampled = preparation._sample_dem(path, [point, nodata_point, point, {"lat": 24.1, "lon": 121}])
    assert sampled["values"] == [713, None, 713, None]
    assert sampled["resolution_m"] == [20, 20]
    assert sampled["interpolated"] is False
