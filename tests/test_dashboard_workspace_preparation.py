from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

import dashboard_workspace_preparation as preparation
import pretrip_layer_preparation as layer_preparation
from dashboard_workspace_clone import WorkspaceCloneRequest, clone_pretrip_workspace_from_inputs
from pretrip_import import (
    PretripImportRequest, PretripPreparationInputError, _dtm_raster_sources,
    run_pretrip_import, validate_dtm_raster_source,
)
from pretrip_models import DtmRasterSource
from pretrip_source_ingest import sha256_file, wgs84_to_twd97


@pytest.fixture(autouse=True)
def isolated_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SCOUT_PRETRIP_MATERIAL_ROOT", raising=False)
    monkeypatch.delenv("SCOUT_PRETRIP_DURABLE_EVIDENCE_SOURCE_ROOT", raising=False)

    def no_network(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("preparation wiring tests must not use network")

    monkeypatch.setattr(socket, "create_connection", no_network)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_gpx(path: Path, name: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">'
        f"<trk><name>{name}</name><trkseg>"
        '<trkpt lat="24.000" lon="121.000"><ele>1000</ele><time>2026-05-01T00:00:00Z</time></trkpt>'
        '<trkpt lat="24.001" lon="121.001"><ele>1010</ele><time>2026-05-01T00:10:00Z</time></trkpt>'
        '<trkpt lat="24.002" lon="121.002"><ele>1020</ele><time>2026-05-01T00:20:00Z</time></trkpt>'
        "</trkseg></trk></gpx>",
        encoding="utf-8",
    )
    return path


def _raw_dtm(path: Path) -> Path:
    path.mkdir(parents=True)
    x, y = wgs84_to_twd97(24.001, 121.001)
    (path / "fixture_dem.hdr").write_text(
        "\n".join([
            "fixture tile", "fixture", "TWD97[2010]", "TWVD2001", "5000", "20", "20",
            "0", "144", "144", str(int(x) - 1200), str(int(y) - 1200), "10", "",
        ]),
        encoding="big5",
    )
    (path / "fixture_dem.grd").write_bytes(b"raw fixture grid; no terrain worker is invoked")
    return path


def _import_fixture(tmp_path: Path, *, material: bool = False) -> tuple[Path, Path, dict[str, Any]]:
    dtm = _raw_dtm(tmp_path / "original-dtm")
    material_root = tmp_path / "declared-material" if material else None
    if material_root:
        _write_json(material_root / "material_manifest.json", {"sources": {"dtm_dirs": [str(dtm)]}})
    manifest = run_pretrip_import(PretripImportRequest(
        project_id="source", workspace_root=tmp_path / "workspaces",
        primary_gpx=_write_gpx(tmp_path / "raw" / "golden.gpx", "golden"),
        reference_gpx_paths=(_write_gpx(tmp_path / "raw" / "ref.gpx", "reference"),),
        material_root=material_root, dtm_dirs=(dtm,), profile="pi-offline",
    ))
    return tmp_path / "workspaces" / "source", dtm, manifest


def test_import_then_clone_replays_explicit_dtm_without_material_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, dtm, manifest = _import_fixture(tmp_path)
    saved = manifest["inputs"]["preparation_inputs"]
    assert saved == _read(source / "inbox" / "source_manifest.json")["preparation_inputs"]
    assert saved["material_root"] is None
    assert saved["dtm_dirs"] == [str(dtm.resolve())]
    assert saved["explicit_dtm_dirs"] == [str(dtm.resolve())]
    assert saved["candidate_only"] is True
    assert saved["runtime_safety_truth"] is False
    unrelated_material = tmp_path / "ambient-material"
    _write_json(unrelated_material / "material_manifest.json", {"sources": {"dtm_dirs": [str(tmp_path / "must-not-read")]}})
    monkeypatch.setenv("SCOUT_PRETRIP_MATERIAL_ROOT", str(unrelated_material))
    _write_json(source / "outputs" / "spatial" / "qgis" / "derived.json", {"must_not_copy": True})
    before = {str(path.relative_to(source)): sha256_file(path) for path in source.rglob("*") if path.is_file()}
    seen: list[Any] = []

    def prepared(request: Any) -> dict[str, Any]:
        seen.append(request)
        target_coverage = _read(request.project_root / "normalized/terrain/dtm_coverage_summary.json")
        assert target_coverage["source_dirs"] == [str(dtm.resolve())]
        assert target_coverage["scanned_header_count"] == 1
        assert target_coverage["candidate_tiles"][0]["tile_id"] == "fixture"
        assert not (request.project_root / "outputs/spatial/qgis/derived.json").exists()
        return {"normalized_layers": ["terrain"], "validation": {"status": "partial"},
                "qgis_terrain_feature_stack": {"status": "not_run"}}

    result = clone_pretrip_workspace_from_inputs(WorkspaceCloneRequest(
        source_project_id="source", target_project_id="cloned", source_project_root=source,
        workspace_root=source.parent, network_mode="no-network", allow_network_fetch=False,
        prepare_cwa_imagery=False, seed_imagery_cache=False,
    ), preparation_runner=prepared)
    assert result["status"] == "completed_with_degraded_terrain"
    assert len(seen) == 1
    assert seen[0].route_corridor_m == 500.0
    assert seen[0].reference_track_corridor_m == 300.0
    assert seen[0].run_post_layer_enrichments is True
    assert seen[0].run_map_preparation_spec_artifacts is True
    assert seen[0].run_qgis_terrain_workflow is True
    assert before == {str(path.relative_to(source)): sha256_file(path) for path in source.rglob("*") if path.is_file()}
    target = source.parent / "cloned"
    assert _read(target / "inbox/source_manifest.json")["preparation_inputs"]["dtm_dirs"] == [str(dtm.resolve())]
    assert _read(target / "inbox/source_manifest.json")["sources"][0]["sha256"] == _read(source / "inbox/source_manifest.json")["sources"][0]["sha256"]


def test_material_root_is_saved_even_when_not_an_ancestor_of_any_gpx(tmp_path: Path) -> None:
    source, dtm, manifest = _import_fixture(tmp_path, material=True)
    resolved = preparation.resolve_workspace_preparation_inputs(source)
    saved = manifest["inputs"]["preparation_inputs"]
    assert resolved.material_root == tmp_path / "declared-material"
    assert resolved.dtm_dirs == (dtm,)
    assert saved["material_manifest_sha256"] == sha256_file(tmp_path / "declared-material/material_manifest.json")
    assert resolved.source == "saved_preparation_inputs"


def test_clone_reimports_legacy_raw_raster_without_copying_terrain(tmp_path: Path) -> None:
    source, dtm, _ = _import_fixture(tmp_path)
    raster = tmp_path / "raw-original.tif"
    raster.write_bytes(b"raw raster fixture; metadata-only import")
    metadata = tmp_path / "Metadata.xml"
    metadata.write_text('<metadata><crs>EPSG:3826</crs></metadata>', encoding="utf-8")
    declaration = {
        "path": str(raster), "sha256": sha256_file(raster), "role": "original_dem",
        "crs": "EPSG:3826", "source_resolution_m": 20.0,
        "crs_evidence": str(metadata), "crs_evidence_sha256": sha256_file(metadata),
        "candidate_only": True, "runtime_safety_truth": False,
    }
    inbox = _read(source / "inbox/source_manifest.json")
    inbox.pop("preparation_inputs")
    _write_json(source / "inbox/source_manifest.json", inbox)
    imported = _read(source / "outputs/import_manifest.json")
    imported["inputs"].pop("preparation_inputs")
    _write_json(source / "outputs/import_manifest.json", imported)
    coverage = _read(source / "normalized/terrain/dtm_coverage_summary.json")
    coverage["raster_sources"] = [declaration]
    _write_json(source / "normalized/terrain/dtm_coverage_summary.json", coverage)
    clone_pretrip_workspace_from_inputs(WorkspaceCloneRequest(
        source_project_id="source", target_project_id="clone-raster", source_project_root=source,
        workspace_root=source.parent, allow_network_fetch=False, network_mode="no-network",
    ), preparation_runner=lambda _: {"normalized_layers": ["route"], "validation": {"status": "ready"}})
    target = source.parent / "clone-raster"
    target_coverage = _read(target / "normalized/terrain/dtm_coverage_summary.json")
    assert target_coverage["source_dirs"] == [str(dtm)]
    assert target_coverage["raster_sources"][0]["path"] == str(raster)
    assert target_coverage["raster_sources"][0]["sha256"] == declaration["sha256"]
    assert target_coverage["raster_sources"][0]["crs_evidence_sha256"] == declaration["crs_evidence_sha256"]
    saved = _read(target / "inbox/source_manifest.json")["preparation_inputs"]["dtm_rasters"][0]
    assert saved["crs_evidence"] == str(metadata)
    assert saved["crs_evidence_sha256"] == declaration["crs_evidence_sha256"]
    assert not list(target.rglob("*.tif"))
    assert preparation.resolve_workspace_preparation_inputs(target).dtm_rasters[0]["sha256"] == declaration["sha256"]


@pytest.mark.parametrize("fault", ["missing_metadata", "changed_metadata", "missing_metadata_path"])
def test_dtm_crs_provenance_hash_is_verified(tmp_path: Path, fault: str) -> None:
    raster = tmp_path / "raw.tif"
    raster.write_bytes(b"original DEM")
    metadata = tmp_path / "Metadata.xml"
    metadata.write_bytes(b"original CRS metadata")
    declaration = {
        "path": str(raster), "sha256": sha256_file(raster), "role": "original_dem",
        "crs": "EPSG:3826", "source_resolution_m": 20.0,
        "crs_evidence": str(metadata), "crs_evidence_sha256": sha256_file(metadata),
    }
    assert validate_dtm_raster_source(declaration).crs_evidence_sha256 == declaration["crs_evidence_sha256"]
    if fault == "missing_metadata":
        metadata.rename(tmp_path / "moved-metadata.xml")
    elif fault == "changed_metadata":
        metadata.write_bytes(b"different CRS metadata")
    else:
        declaration["crs_evidence"] = None
    with pytest.raises(PretripPreparationInputError) as raised:
        validate_dtm_raster_source(declaration)
    assert raised.value.field in {"crs_evidence", "crs_evidence_sha256"}
    assert raised.value.code == (
        "PREPARATION_SOURCE_CHANGED" if fault == "changed_metadata" else "PREPARATION_SOURCE_MISSING"
    )


def test_duplicate_material_raster_keeps_declared_crs_metadata_hash(tmp_path: Path) -> None:
    raster = tmp_path / "raw.tif"
    raster.write_bytes(b"original DEM")
    metadata = tmp_path / "Metadata.xml"
    metadata.write_bytes(b"original CRS metadata")
    old = {"path": str(raster), "sha256": sha256_file(raster), "role": "original_dem",
           "crs": "EPSG:3826", "source_resolution_m": 20.0}
    complete = DtmRasterSource.model_validate({**old, "crs_evidence": str(metadata),
        "crs_evidence_sha256": sha256_file(metadata)})
    material = tmp_path / "material"
    _write_json(material / "material_manifest.json", {"sources": {"dtm_rasters": [old]}})
    result = _dtm_raster_sources(PretripImportRequest(
        project_id="source", workspace_root=tmp_path / "workspaces", primary_gpx=tmp_path / "unused.gpx",
        material_root=material, dtm_raster_sources=(complete,),
    ))
    assert result == [complete]


@pytest.mark.parametrize("invalid", [{"crs_evidence_sha256": "invalid"}, {"unrecognized_provenance": "value"}])
def test_dtm_raster_schema_keeps_hash_format_and_extra_field_rejection(invalid: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        DtmRasterSource.model_validate({
            "path": "/unused/raw.tif", "sha256": "a" * 64, "role": "raw_dem",
            "crs": "EPSG:3826", "source_resolution_m": 20.0, **invalid,
        })


def test_new_import_pbf_project_metadata_survives_clone_without_material_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, _, _ = _import_fixture(tmp_path)
    pbf = tmp_path / "original-taiwan.osm.pbf"
    pbf.write_bytes(b"original PBF fixture; extraction is not run")
    project = _read(source / "project.json")
    project.update({"osm_pbf_source_ref": str(pbf), "osm_pbf_source_sha256": sha256_file(pbf),
                    "osm_pbf_source_url": "https://example.invalid/taiwan.osm.pbf", "osm_pbf_cache_ttl_days": 23})
    _write_json(source / "project.json", project)
    resolved = preparation.resolve_workspace_preparation_inputs(source)
    assert resolved.material_root is None
    assert resolved.material_manifest == {}
    assert resolved.local_osm_pbf == {
        "path": str(pbf), "sha256": sha256_file(pbf),
        "source_url": "https://example.invalid/taiwan.osm.pbf", "cache_ttl_days": 23,
        "declaration_source": "project_original_pbf_metadata", "metadata_ref": str(source / "project.json"),
    }
    monkeypatch.setattr("dashboard_workspace_clone._osm_pbf_parser_available", lambda _: True)
    before = {str(path.relative_to(source)): sha256_file(path) for path in source.rglob("*") if path.is_file()}
    seen: list[Any] = []
    clone_pretrip_workspace_from_inputs(WorkspaceCloneRequest(
        source_project_id="source", target_project_id="clone-pbf", source_project_root=source,
        workspace_root=source.parent,
    ), preparation_runner=lambda request: seen.append(request) or {"normalized_layers": ["osm"], "validation": {"status": "ready"}})
    assert seen[0].osm_pbf_path == pbf
    assert seen[0].osm_pbf_cache_ttl_days == 23
    assert seen[0].osm_pbf_source_url == project["osm_pbf_source_url"]
    assert not list((source.parent / "clone-pbf").rglob("*.pbf"))
    assert before == {str(path.relative_to(source)): sha256_file(path) for path in source.rglob("*") if path.is_file()}


@pytest.mark.parametrize("source_kind", ["project", "material"])
def test_explicit_pbf_override_or_none_takes_priority_over_missing_old_source(tmp_path: Path, source_kind: str) -> None:
    root = tmp_path / "imported"
    project: dict[str, Any] = {"project_id": root.name}
    missing = tmp_path / "unavailable-original.pbf"
    if source_kind == "project":
        project.update({"osm_pbf_source_ref": str(missing), "osm_pbf_source_sha256": "a" * 64})
    else:
        material = tmp_path / "material"
        _write_json(material / "material_manifest.json", {"sources": {"local_osm_pbf": {"path": str(missing)}}})
        project["material_root"] = str(material)
    _write_json(root / "project.json", project)
    new_pbf = tmp_path / "explicit.pbf"
    new_pbf.write_bytes(b"explicit raw PBF")
    request = preparation.build_workspace_preparation_request(root, preparation_options={
        "osm_pbf_path": str(new_pbf), "osm_pbf_source_url": None, "osm_pbf_cache_ttl_days": 9,
    })
    assert request.osm_pbf_path == new_pbf
    assert request.osm_pbf_source_url is None and request.osm_pbf_cache_ttl_days == 9
    disabled = preparation.build_workspace_preparation_request(root, preparation_options={"osm_pbf_path": None})
    assert disabled.osm_pbf_path is None
    with pytest.raises(PretripPreparationInputError, match="PREPARATION_SOURCE_MISSING"):
        preparation.build_workspace_preparation_request(root)


@pytest.mark.parametrize("fault", ["hash_changed", "hash_missing", "derived_extract"])
def test_original_pbf_metadata_cannot_bypass_hash_or_promote_extract(tmp_path: Path, fault: str) -> None:
    root = tmp_path / "imported"
    pbf = root / "normalized/map/route_bbox.osm.pbf" if fault == "derived_extract" else tmp_path / "raw.pbf"
    pbf.parent.mkdir(parents=True, exist_ok=True)
    pbf.write_bytes(b"PBF fixture")
    digest = sha256_file(pbf)
    _write_json(root / "project.json", {"project_id": root.name, "osm_pbf_source_ref": str(pbf),
        "osm_pbf_source_sha256": None if fault == "hash_missing" else ("a" * 64 if fault == "hash_changed" else digest)})
    expected = {"hash_changed": "PREPARATION_SOURCE_CHANGED", "hash_missing": "PREPARATION_SOURCE_HASH_MISSING",
                "derived_extract": "PREPARATION_SOURCE_IS_DERIVED"}[fault]
    with pytest.raises(PretripPreparationInputError, match=expected):
        preparation.resolve_workspace_preparation_inputs(root)
    if fault == "derived_extract":
        with pytest.raises(PretripPreparationInputError, match=expected):
            preparation.build_workspace_preparation_request(root, preparation_options={"osm_pbf_path": str(pbf)})


@pytest.mark.parametrize("declaration", ["material_root", "dtm_dirs"])
def test_missing_explicit_import_input_fails_before_target_creation(tmp_path: Path, declaration: str) -> None:
    missing = tmp_path / "unavailable-original"
    options = {declaration: missing if declaration == "material_root" else (missing,)}
    with pytest.raises(PretripPreparationInputError) as raised:
        run_pretrip_import(PretripImportRequest(
            project_id="never-created", workspace_root=tmp_path / "workspaces",
            primary_gpx=_write_gpx(tmp_path / "route.gpx", "golden"), **options,
        ))
    assert raised.value.to_dict() == {"code": "PREPARATION_SOURCE_MISSING", "field": declaration, "path": str(missing)}
    assert not (tmp_path / "workspaces/never-created").exists()


def test_missing_material_dtm_declaration_is_not_silently_dropped(tmp_path: Path) -> None:
    missing = tmp_path / "declared-but-missing-dtm"
    material_root = tmp_path / "material"
    _write_json(material_root / "material_manifest.json", {"sources": {"dtm_dirs": [str(missing)]}})
    with pytest.raises(PretripPreparationInputError, match="dtm_dirs"):
        run_pretrip_import(PretripImportRequest(
            project_id="never-created", workspace_root=tmp_path / "workspaces",
            primary_gpx=_write_gpx(tmp_path / "route.gpx", "golden"), material_root=material_root,
        ))
    assert not (tmp_path / "workspaces/never-created").exists()


def test_legacy_coverage_recovers_only_declared_raw_source_dirs(tmp_path: Path) -> None:
    project = tmp_path / "legacy"
    dtm = _raw_dtm(tmp_path / "raw-dtm")
    _write_json(project / "project.json", {"project_id": project.name})
    _write_json(project / "normalized/terrain/dtm_coverage_summary.json", {
        "source_dirs": [str(dtm)], "candidate_tiles": [{"derived_value_must_not_transfer": True}],
    })
    resolved = preparation.resolve_workspace_preparation_inputs(project)
    assert resolved.dtm_dirs == (dtm,)
    assert resolved.material_manifest == {}
    assert resolved.source == "legacy_raw_source_metadata"
    dtm.rename(tmp_path / "moved-dtm")
    with pytest.raises(PretripPreparationInputError, match="PREPARATION_SOURCE_MISSING"):
        preparation.build_workspace_preparation_request(project)


def test_legacy_coverage_cannot_promote_derived_workspace_dem_to_raw_input(tmp_path: Path) -> None:
    project = tmp_path / "legacy"
    _write_json(project / "project.json", {"project_id": project.name})
    terrain = project / "outputs/spatial/generated-terrain"
    terrain.mkdir(parents=True)
    _write_json(project / "normalized/terrain/dtm_coverage_summary.json", {"source_dirs": [str(terrain)]})
    with pytest.raises(PretripPreparationInputError, match="PREPARATION_SOURCE_IS_DERIVED"):
        preparation.resolve_workspace_preparation_inputs(project)


def test_prepare_helper_keeps_false_options_and_returns_unmodified_pipeline_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "imported"
    _write_json(project / "project.json", {"project_id": project.name})
    result = {"validation": {"status": "partial"}, "qgis_terrain_feature_stack": {"status": "unavailable"}}
    seen: list[Any] = []
    monkeypatch.setattr(preparation, "run_layer_preparation", lambda request: seen.append(request) or result)
    returned = preparation.prepare_imported_workspace(
        project, source_project_id="original", requested_by="fixture_operator",
        preparation_options={
            "layers": ["route", "terrain"], "network_mode": "no-network",
            "allow_network_fetch": False, "prepare_cwa_imagery": False,
            "seed_imagery_cache": False, "imagery_provider_allows_offline_prefetch": False,
            "imagery_min_zoom": 8, "imagery_max_zoom": 11,
        },
    )
    assert returned is result
    request = seen[0]
    assert request.layers == ("route", "terrain")
    assert request.allow_network_fetch is request.prepare_cwa_imagery is request.seed_imagery_cache is False
    assert request.imagery_provider_allows_offline_prefetch is False
    assert request.imagery_min_zoom == 8 and request.imagery_max_zoom == 11
    assert request.imagery_cache_fallback_project_ids == ("original",)
    assert request.qgis_requested_by == "fixture_operator"
    assert request.run_post_layer_enrichments is request.run_map_preparation_spec_artifacts is request.run_qgis_terrain_workflow is True
    assert not (project / "inbox/source_manifest.json").exists()


@pytest.mark.parametrize("flag", [
    "run_post_layer_enrichments", "run_map_preparation_spec_artifacts",
    "run_qgis_terrain_workflow", "publish_preparation_outputs",
])
def test_explicit_partial_pipeline_option_is_rejected(tmp_path: Path, flag: str) -> None:
    project = tmp_path / "imported"
    _write_json(project / "project.json", {"project_id": project.name})
    with pytest.raises(ValueError, match=f"full workspace preparation requires: {flag}"):
        preparation.build_workspace_preparation_request(project, preparation_options={flag: False})


@pytest.mark.parametrize("mode,allow", [("no-network", True), ("explicit-fetch", False)])
def test_network_gates_block_real_provider_entrypoints_before_route_or_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str, allow: bool,
) -> None:
    project = tmp_path / "imported"
    _write_json(project / "project.json", {"project_id": project.name})
    request = preparation.build_workspace_preparation_request(project, preparation_options={
        "network_mode": mode, "allow_network_fetch": allow,
        "prepare_cwa_imagery": True, "seed_imagery_cache": True,
    })
    assert request.allow_network_fetch is allow
    assert request.seed_imagery_cache is False

    def must_not_read_route(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("no-network provider branch must stop before route or credentials lookup")

    monkeypatch.setattr(layer_preparation, "load_cwa_route_identity", must_not_read_route)
    assert layer_preparation._maybe_prepare_cwa_imagery_server_job(
        project_root=project, project={}, request=request, prepared_at="2026-05-01T00:00:00Z",
    )["cwa_weather_imagery_status"] == "blocked_explicit_network_fetch_required"
    assert layer_preparation._maybe_prepare_cwa_precipitation_grid_job(
        project_root=project, project={}, request=request, bbox={}, prepared_at="2026-05-01T00:00:00Z",
    )["cwa_rainfall_grid_status"] == "not_requested_no_explicit_fetch"
    assert layer_preparation._maybe_fetch_overpass_evidence(request) is None
    assert layer_preparation._maybe_seed_imagery_tile_cache(request) is None


@pytest.mark.parametrize("key", ["project_id", "project_root", "workspace_root", "source_project_id"])
def test_options_cannot_rebind_workspace(tmp_path: Path, key: str) -> None:
    project = tmp_path / "imported"
    _write_json(project / "project.json", {"project_id": project.name})
    with pytest.raises(ValueError, match="unsupported preparation options"):
        preparation.build_workspace_preparation_request(project, preparation_options={key: "different"})


def test_preparation_preflight_checks_raw_paths_without_mutating_import_checkpoint(tmp_path: Path) -> None:
    project, dtm, _ = _import_fixture(tmp_path)
    source_before = (project / "inbox/source_manifest.json").read_bytes()
    import_before = (project / "outputs/import_manifest.json").read_bytes()
    preparation.build_workspace_preparation_request(project)
    assert (project / "inbox/source_manifest.json").read_bytes() == source_before
    assert (project / "outputs/import_manifest.json").read_bytes() == import_before
    dtm.rename(tmp_path / "moved-original-dtm")
    with pytest.raises(PretripPreparationInputError) as raised:
        clone_pretrip_workspace_from_inputs(WorkspaceCloneRequest(
            source_project_id=project.name, target_project_id="clone", source_project_root=project,
            workspace_root=project.parent,
        ), import_runner=lambda _: pytest.fail("missing source must block import"))
    assert raised.value.field == "dtm_dirs"
    assert not (project.parent / "clone").exists()
