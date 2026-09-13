"""A genuine no-GPX intake, native raster preparation and source-bound exports."""
from __future__ import annotations

import copy
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from pydantic import ValidationError

import scout_exploration_workspace as exploration
from scout_exploration_models import ExplorationAOI, ExplorationPoint, ExplorationWorkspaceRequest
from scout_planned_route_sources import fetch_trail_source_candidates


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _request(**updates):
    request = {"project_id": "zero_ref", "intent": "研究沒有既有 GPX 的山區路線",
               "aoi": {"crs": "EPSG:3826", "bbox": [280200, 2658500, 280800, 2659500]}}
    request.update(updates)
    return request


def _native_raster(tmp_path, *, nodata=False):
    import numpy as np
    from osgeo import gdal, osr
    path = tmp_path / "raw_regional.tif"
    data = gdal.GetDriverByName("GTiff").Create(str(path), 100, 100, 1, gdal.GDT_Float32)
    data.SetGeoTransform((280000, 20, 0, 2660000, 0, -20))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(3826)
    data.SetProjection(srs.ExportToWkt())
    values = np.arange(10000, dtype=np.float32).reshape((100, 100)) / 10 + 1000
    if nodata:
        values[35:45, 20:30] = -9999
    data.GetRasterBand(1).SetNoDataValue(-9999)
    data.GetRasterBand(1).WriteArray(values)
    data.FlushCache()
    data = None
    return {"dtm_rasters": [{"path": str(path), "role": "raw_regional_dem", "sha256": _sha(path),
                            "crs": "EPSG:3826", "source_resolution_m": 20}], "dtm_dirs": []}


def _point(x, y, label=None):
    return {"x": x, "y": y, "crs": "EPSG:3826", **({"label": label} if label else {})}


def _map_fetcher(*, empty=False):
    ways = []
    if not empty:
        for number, coords in enumerate([[(280240, 2659200), (280340, 2659100)],
                                        [(280640, 2658800), (280700, 2658700)]], 1):
            points = [ExplorationPoint(**_point(x, y)).wgs84() for x, y in coords]
            ways.append({"type": "way", "id": number, "nodes": [number * 10, number * 10 + 1],
                         "tags": {"highway": "path", "name": f"trail-{number}"},
                         "geometry": [{"lon": lon, "lat": lat} for lon, lat in points]})
    raw = json.dumps({"elements": ways}).encode()
    return lambda bbox: fetch_trail_source_candidates(bbox, fetcher=lambda *_: raw,
                                                      requested_at="2026-09-10T00:00:00Z")


def _create(tmp_path, **updates):
    receipt = exploration.create_exploration_workspace(tmp_path / "workspaces", _request(**updates))
    return Path(receipt["project_root"]), receipt


def test_area_only_intake_has_no_primary_golden_or_reference_and_get_is_readonly(tmp_path):
    root, result = _create(tmp_path, waypoints=[{"label": "尚未對位的古道遺址"}])
    assert result["golden_source_id"] is None and result["reference_gpxs"] == []
    assert result["preparation"]["status"] == "queued"
    assert not list(root.rglob("*.gpx"))
    sources = json.loads((root / exploration.SOURCE_REF).read_bytes())
    assert sources["primary_gpx"] is None and sources["golden_gpx"] is None and sources["reference_gpxs"] == []
    before = {p.relative_to(root): _sha(p) for p in root.rglob("*") if p.is_file()}
    for _ in range(2):
        current = exploration.read_exploration_workspace(root)
        catalog = exploration.load_exploration_catalog(root)
        assert current["preparation"]["attempt"] == 0
        assert catalog["sources"] == [] and catalog["golden_source_id"] is None
    assert {p.relative_to(root): _sha(p) for p in root.rglob("*") if p.is_file()} == before
    assert "waypoint_unlocated" in {row["code"] for row in current["unknowns"]}


@pytest.mark.parametrize("change", [
    {"aoi": {"crs": "EPSG:3857", "bbox": [1, 2, 3, 4]}},
    {"aoi": {"crs": "EPSG:4326", "bbox": [121, 24, 121, 25]}},
    {"aoi": {"crs": "EPSG:4326", "bbox": [121, 24, 122, 91]}},
    {"aoi": {"crs": "EPSG:4326", "bbox": [float("nan"), 24, 122, 25]}},
    {"aoi": {"crs": "EPSG:4326", "polygon": [[121, 24], [122, 24], [122, 25]]}},
    {"aoi": {"crs": "EPSG:4326", "polygon": [[121, 24], [122, 25], [121, 25], [122, 24], [121, 24]]}},
    {"start": _point(281000, 2659200)},
    {"start": _point(280400, 2659200), "destination": _point(280400, 2659200)},
    {"limits": {"departure_at": "2026-10-01T06:00:00"}},
    {"limits": {"speed_range_kmh": [3, 1]}},
    {"limits": {"days": 1}, "waypoints": [{"label": "營地", "day": 2}]},
    {"project_id": "../owner"},
    {"primary_gpx": "invented.gpx"},
])
def test_invalid_aoi_crs_endpoints_limits_and_fake_primary_are_rejected(change):
    with pytest.raises((ValidationError, ValueError)):
        ExplorationWorkspaceRequest.model_validate(_request(**change))


def test_polygon_checks_real_area_instead_of_bbox_and_projected_crs_roundtrips():
    aoi = ExplorationAOI(crs="EPSG:3826", polygon=[(280200, 2658500), (280800, 2658500),
        (280200, 2659500), (280200, 2658500)])
    assert aoi.contains(ExplorationPoint(**_point(280250, 2658700)))
    assert not aoi.contains(ExplorationPoint(**_point(280750, 2659400)))
    lon, lat = ExplorationPoint(**_point(280250, 2658700)).wgs84()
    assert aoi.contains(ExplorationPoint(x=lon, y=lat, crs="EPSG:4326"))


def test_existing_workspace_is_never_overwritten_and_exact_create_is_idempotent(tmp_path):
    root, first = _create(tmp_path)
    second = exploration.create_exploration_workspace(root.parent, _request())
    assert second == first
    with pytest.raises(exploration.ExplorationWorkspaceError, match="different"):
        exploration.create_exploration_workspace(root.parent, _request(intent="changed intent"))
    assert exploration.read_exploration_workspace(root) == first


def test_map_evidence_survives_missing_dem_without_generating_a_route(tmp_path):
    root, _ = _create(tmp_path)
    report = exploration.prepare_exploration_workspace(root, map_fetcher=_map_fetcher())
    assert report["status"] == "completed_with_gaps"
    assert report["map"]["source_count"] == 2 and report["terrain"]["status"] == "unavailable"
    catalog = exploration.load_exploration_catalog(root)
    assert {source["kind"] for source in catalog["sources"]} == {"overpass"}
    assert catalog["golden_source_id"] is None
    assert len(catalog["anchors"]) == 4
    assert all(source["provenance"]["candidate_only"] for source in catalog["sources"])
    assert not list(root.rglob("*.gpx"))
    assert exploration.prepare_exploration_workspace(root, map_fetcher=lambda _: pytest.fail("completed GET-like replay must not fetch")) == report


def test_no_trail_and_missing_ab_preserve_real_native_dem_and_raw_response(tmp_path):
    raw = _native_raster(tmp_path)
    root, _ = _create(tmp_path, preparation_inputs=raw)
    report = exploration.prepare_exploration_workspace(root, map_fetcher=_map_fetcher(empty=True))
    assert report["map"]["status"] == "no_trail_candidates"
    assert report["terrain"]["status"] == "completed"
    assert report["terrain"]["aoi_cell_count"] == report["terrain"]["finite_cell_count"] == 1500
    assert report["terrain"]["resolution_m"] == 20
    assert report["terrain"]["terrain_feature_stack_status"] == "not_run_no_selected_route"
    parent = json.loads((root / report["terrain"]["parent_manifest_ref"]).read_bytes())
    assert parent["actual_processor"] == "native_gdal_aoi_dem" and parent["route_input"] is None
    assert parent["source_resolution"]["adds_source_resolution"] is False
    assert list(root.rglob("overpass_raw.json")) and not list(root.rglob("*.gpx"))
    with pytest.raises(exploration.ExplorationWorkspaceError, match="explicit A/B"):
        exploration.build_exploration_trh_requests(root)


def test_native_dem_partial_mask_and_missing_values_remain_visible(tmp_path):
    raw = _native_raster(tmp_path, nodata=True)
    root, _ = _create(tmp_path, preparation_inputs=raw)
    report = exploration.prepare_exploration_workspace(root, map_fetcher=_map_fetcher(empty=True))
    assert report["terrain"]["status"] == "partial"
    assert report["terrain"]["nodata_cell_count"] == 100
    assert "aoi_dem_partial_coverage" in {row["code"] for row in report["unknowns"]}


def test_ab_and_waypoints_compile_existing_worker_requests_without_worker_or_fake_gpx(tmp_path):
    raw = _native_raster(tmp_path)
    root, _ = _create(tmp_path, preparation_inputs=raw, start=_point(280240, 2659200),
        destination=_point(280700, 2658700), waypoints=[{"label": "明確中繼點", "point": _point(280400, 2659000)}],
        limits={"days": 1, "fixed_speed_kmh": 2})
    report = exploration.prepare_exploration_workspace(root, map_fetcher=_map_fetcher())
    assert report["trh_request_available"] is True
    requests = exploration.build_exploration_trh_requests(root, corridor_m=0)
    assert len(requests) == 2
    for request in requests:
        assert request.workflow_id == "terrain_route_hypothesis.v1"
        assert request.candidate_only is True and request.runtime_safety_truth is False
        assert len(request.dem_refs) == 1 and request.source_resolution["x_m"] == 20
        assert request.terrain_route_cache_keys
    assert not list(root.rglob("*.gpx"))
    assert not list(root.rglob("terrain_route_hypothesis.json"))


def test_partial_map_failure_is_durable_and_resume_retains_first_attempt(tmp_path):
    root, receipt = _create(tmp_path)
    def fail(_):
        raise OSError("fixture provider unavailable")
    first = exploration.prepare_exploration_workspace(root, map_fetcher=fail)
    state = exploration.read_exploration_workspace(root)["preparation"]
    old_sha = _sha(root / state["report_ref"])
    assert first["map"]["status"] == "unavailable"
    second = exploration.prepare_exploration_workspace(root, map_fetcher=_map_fetcher(), force=True)
    assert second["attempt"] == 2 and second["map"]["source_count"] == 2
    assert _sha(root / state["report_ref"]) == old_sha
    with pytest.raises(exploration.ExplorationWorkspaceError, match="another exploration"):
        exploration.prepare_exploration_workspace(root, "explore.wrong")


def test_changed_raw_source_rejected_and_source_declared_hash_preserved(tmp_path):
    raw = _native_raster(tmp_path)
    root, _ = _create(tmp_path, preparation_inputs=raw)
    source_manifest_before = _sha(root / exploration.SOURCE_REF)
    report = exploration.prepare_exploration_workspace(root, map_fetcher=_map_fetcher())
    assert report["terrain"]["status"] == "completed"
    Path(raw["dtm_rasters"][0]["path"]).write_bytes(b"changed external source")
    with pytest.raises(exploration.ExplorationWorkspaceError, match="evidence changed"):
        exploration.prepare_exploration_workspace(root)
    assert _sha(root / exploration.SOURCE_REF) == source_manifest_before


def test_candidate_export_keeps_disconnected_parts_and_explicit_time_assumptions(tmp_path):
    root, _ = _create(tmp_path)
    exploration.prepare_exploration_workspace(root, map_fetcher=_map_fetcher())
    catalog = exploration.load_exploration_catalog(root)
    selections = [{"source_id": source["source_id"], "part_index": 0} for source in catalog["sources"]]
    exported = exploration.export_exploration_candidates(root, selections, fixed_speed_kmh=2,
        assumptions=["人工固定腳程，尚未校準到此地形", "營地水源與合法性仍待查"])
    assert exported["golden_source_id"] is None and exported["reference_gpxs"] == []
    assert len(exported["gaps"]) == 1 and exported["gaps"][0]["distance_m"] > 100
    assert exported["gaps"][0]["filled"] is False and exported["full_route_complete"] is False
    assert exported["timing"]["known_segment_minutes"] > 0 and exported["timing"]["full_route_minutes"] is None
    xml = ET.fromstring((root / exported["gpx_ref"]).read_bytes())
    assert len(xml.findall(".//{*}trkseg")) == 2 and len(xml.findall(".//{*}trkpt")) == 4
    assert not xml.findall(".//{*}time")
    provenance = xml.find(".//{https://scout.local/schemas/planned-route/v1}provenance")
    assert provenance.get("role") == "planned" and provenance.get("recorded_track") == "false"
    assert exported["candidate_only"] is True and exported["runtime_safety_truth"] is False


def test_unresolved_waypoint_blocks_concrete_trh_but_not_area_research(tmp_path):
    raw = _native_raster(tmp_path)
    root, _ = _create(tmp_path, preparation_inputs=raw, start=_point(280240, 2659200),
        destination=_point(280700, 2658700), waypoints=[{"label": "待定位古道"}])
    report = exploration.prepare_exploration_workspace(root, map_fetcher=_map_fetcher())
    assert report["terrain"]["status"] == "completed"
    assert report["trh_request_available"] is False
    with pytest.raises(exploration.ExplorationWorkspaceError, match="unresolved"):
        exploration.build_exploration_trh_requests(root)


def test_workspace_symlink_intake_tamper_and_source_hash_tamper_are_rejected(tmp_path):
    root, _ = _create(tmp_path)
    original = json.loads((root / exploration.INTAKE_REF).read_bytes())
    (root / exploration.INTAKE_REF).write_text(json.dumps({**original, "intent": "tampered"}))
    with pytest.raises(exploration.ExplorationWorkspaceError, match="provenance changed"):
        exploration.read_exploration_workspace(root)
    alias = tmp_path / "alias"
    alias.symlink_to(root.parent, target_is_directory=True)
    with pytest.raises(exploration.ExplorationWorkspaceError, match="symlink"):
        exploration.create_exploration_workspace(alias, _request(project_id="other"))


def test_explicit_endpoint_and_waypoint_names_merge_onto_actual_map_anchor(tmp_path):
    root, _ = _create(tmp_path, start=_point(280240, 2659200, "A"),
        destination=_point(280700, 2658700, "B"), waypoints=[{"label": "同一個登山口", "point": _point(280240, 2659200)}])
    exploration.prepare_exploration_workspace(root, map_fetcher=_map_fetcher())
    catalog = exploration.load_exploration_catalog(root)
    assert len(catalog["anchors"]) == len({row["anchor_id"] for row in catalog["anchors"]}) == 4
    start = next(row for row in catalog["anchors"] if row["label"] == "同一個登山口")
    assert "A" in start["aliases"] and start["snap_distance_m"] < 0.001
    exported = exploration.export_exploration_candidates(root, [{"source_id": catalog["sources"][0]["source_id"]}], fixed_speed_kmh=2)
    assert exported["selected_geometry_connected"] is True
    assert exported["full_route_complete"] is False
    assert exported["timing"]["connected_segment_moving_minutes"] > 0
    assert exported["timing"]["full_route_minutes"] is None
