import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

import pretrip_layer_preparation
from pretrip_layer_preparation import (
    LayerPreparationRequest,
    build_layer_preparation_preview,
    run_layer_preparation,
)
from pretrip_admin_view import build_pretrip_admin_view
from pretrip_import import PretripImportRequest, run_pretrip_import
from pretrip_source_ingest import wgs84_to_twd97


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PROJECT_ROOT = (
    ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
)


def test_layer_preparation_preview_is_metadata_only_and_no_write(tmp_path: Path) -> None:
    project_root = _copy_fixture_project(tmp_path)
    layer_outputs = project_root / "outputs" / "layers"
    before_files = _relative_file_set(layer_outputs)

    preview = build_layer_preparation_preview(
        LayerPreparationRequest(
            project_id="chilai_nanhua_day1",
            project_root=project_root,
            layers=("osm", "overpass", "terrain", "imagery", "weather"),
            prepared_at="2026-05-22T00:00:00+00:00",
        )
    )

    assert preview["artifact_kind"] == "pretrip_layer_preparation_preview"
    assert preview["preview"] is True
    assert preview["persisted"] is False
    assert preview["counts"]["layer_count"] == 5
    assert preview["counts"]["ready_layer_count"] == 5
    assert preview["network_policy"]["network_calls_made"] is False
    assert preview["boundary"]["workspace_file_mutation_allowed"] is False
    assert preview["boundary"]["phase1_runtime_mutation_allowed"] is False
    assert preview["boundary"]["phase2_brain_writeback_allowed"] is False
    assert _relative_file_set(layer_outputs) == before_files
    assert "<trkpt" not in json.dumps(preview, ensure_ascii=False).lower()


def test_project_source_refs_accept_directory_refs(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    cache_dir = project_root / "outputs" / "layers" / "cache" / "raster_label_ocr_tiles"
    cache_dir.mkdir(parents=True)
    (cache_dir / "tile-cache.json").write_text("{}", encoding="utf-8")
    refs = pretrip_layer_preparation._project_source_refs(
        project_root,
        {"raster_label_ocr_cache_ref": "outputs/layers/cache/raster_label_ocr_tiles"},
    )

    cache_ref = refs["raster_label_ocr_cache_ref"]
    assert cache_ref["exists"] is True
    assert cache_ref["source_kind"] == "directory"
    assert cache_ref["entry_count"] == 1
    assert cache_ref["sha256"] is None


def test_layer_preparation_overpass_plan_uses_route_corridor_bbox(
    tmp_path: Path,
) -> None:
    project_root = _copy_fixture_project(tmp_path)
    route_summary = _load(project_root / "normalized" / "routes" / "route_summary.json")

    preview = build_layer_preparation_preview(
        LayerPreparationRequest(
            project_id="chilai_nanhua_day1",
            project_root=project_root,
            layers=("overpass",),
            route_corridor_m=1_000.0,
            prepared_at="2026-05-22T00:00:00+00:00",
        )
    )
    overpass_layer = preview["layers"][0]
    route_bbox = preview["route_bbox_wgs84"]
    query_bbox = preview["bbox_wgs84"]

    assert route_bbox == {
        "south": route_summary["bbox_wgs84"]["min_lat"],
        "west": route_summary["bbox_wgs84"]["min_lon"],
        "north": route_summary["bbox_wgs84"]["max_lat"],
        "east": route_summary["bbox_wgs84"]["max_lon"],
    }
    assert query_bbox["south"] < route_bbox["south"]
    assert query_bbox["west"] < route_bbox["west"]
    assert query_bbox["north"] > route_bbox["north"]
    assert query_bbox["east"] > route_bbox["east"]
    assert preview["route_corridor"]["route_ref"] == route_summary["artifact_id"]
    assert preview["route_corridor"]["corridor_m"] == 1_000.0
    assert preview["route_corridor"]["route_geometry_refs"][
        "segment_display_geometry_ref"
    ] == "outputs/segment_display_geometry.json"
    assert overpass_layer["route_corridor"] == preview["route_corridor"]
    assert overpass_layer["status"] == "ready_from_project_ref"
    assert overpass_layer["warnings"] == []
    assert overpass_layer["counts"]["candidate_count"] > 0
    assert overpass_layer["planned_request"]["source"] == "route_corridor_bbox"
    assert overpass_layer["planned_request"]["network_calls_made"] is False
    assert "way[\"highway\"" in overpass_layer["planned_request"]["query_body"]
    assert str(round(query_bbox["south"], 7)) in overpass_layer["planned_request"]["query_body"]
    assert "<trkpt" not in json.dumps(preview, ensure_ascii=False).lower()


def test_layer_preparation_overpass_no_network_without_source_is_planned(
    tmp_path: Path,
) -> None:
    project_root = _copy_fixture_project(tmp_path)
    project = _load(project_root / "project.json")
    project.pop("overpass_evidence_ref", None)
    project.pop("overpass_map_context_ref", None)
    (project_root / "project.json").write_text(
        json.dumps(project, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    preview = build_layer_preparation_preview(
        LayerPreparationRequest(
            project_id="chilai_nanhua_day1",
            project_root=project_root,
            layers=("overpass",),
            prepared_at="2026-05-22T00:00:00+00:00",
        )
    )
    overpass_layer = preview["layers"][0]

    assert preview["validation"]["status"] == "ready_with_warnings"
    assert not any(
        warning["layer_id"] == "overpass"
        for warning in preview["validation"]["warnings"]
    )
    assert overpass_layer["status"] == "planned_no_network"
    assert overpass_layer["warnings"] == []
    assert overpass_layer["policy_notes"]
    assert overpass_layer["counts"] == {
        "feature_count": 0,
        "candidate_count": 0,
        "network_calls_made": 0,
    }
    assert overpass_layer["source_refs"] == [
        {
            "ref": "outputs/layers/plans/overpass_query.ql",
            "source_kind": "overpass_query_plan",
            "external_network_required": False,
            "network_calls_made": False,
        }
    ]
    assert overpass_layer["output_refs"]["normalized_geojson_ref"] == (
        "outputs/layers/normalized/overpass_vector_evidence.geojson"
    )
    assert overpass_layer["lifecycle"]["fetch"]["status"] == "planned_no_network"
    assert overpass_layer["lifecycle"]["fetch"]["external_network_calls_made"] is False


def test_layer_preparation_run_writes_planned_overpass_refs_and_allows_live_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _copy_fixture_project(tmp_path)
    project_path = project_root / "project.json"
    project = _load(project_path)
    for key in (
        "overpass_evidence_ref",
        "overpass_map_context_ref",
        "overpass_raw_payload_ref",
        "overpass_query_ref",
        "overpass_candidate_count",
        "overpass_skipped_object_count",
        "overpass_fetched_at",
    ):
        project.pop(key, None)
    project_path.write_text(
        json.dumps(project, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    run_layer_preparation(
        LayerPreparationRequest(
            project_id="chilai_nanhua_day1",
            project_root=project_root,
            layers=("overpass",),
            prepared_at="2026-05-22T00:00:00+00:00",
        )
    )
    planned_project = _load(project_path)
    planned_evidence = _load(project_root / planned_project["overpass_evidence_ref"])

    assert planned_project["overpass_evidence_ref"] == "candidates/overpass_evidence.json"
    assert planned_project["overpass_map_context_ref"] == (
        "outputs/layers/normalized/overpass_vector_evidence.geojson"
    )
    assert planned_project["overpass_query_ref"] == "outputs/layers/plans/overpass_query.ql"
    assert planned_project["overpass_candidate_count"] == 0
    assert planned_evidence["status"] == "planned_no_network"
    assert planned_evidence["source_artifact"]["source_kind"] == "overpass_query_plan"
    assert planned_evidence["request"]["raw_response_sha256"] is None
    assert planned_evidence["request"]["conversion_rule_version"] == "planned_no_network"
    assert planned_evidence["counts"]["candidates"] == 0
    assert planned_evidence["boundary"]["runtime_safety_truth"] is False
    assert (project_root / planned_project["overpass_map_context_ref"]).is_file()
    assert (project_root / planned_project["overpass_query_ref"]).is_file()

    raw_fixture = ROOT / "tests" / "fixtures" / "maps" / "phase_a_overpass_raw.json"
    fetch_count = 0

    def fixture_fetcher(planned_request: dict) -> tuple[bytes, int]:
        nonlocal fetch_count
        fetch_count += 1
        return raw_fixture.read_bytes(), 200

    monkeypatch.setattr(
        pretrip_layer_preparation,
        "_fetch_overpass_raw_payload",
        fixture_fetcher,
    )

    run_layer_preparation(
        LayerPreparationRequest(
            project_id="chilai_nanhua_day1",
            project_root=project_root,
            layers=("overpass",),
            network_mode="explicit-fetch",
            allow_network_fetch=True,
            prepared_at="2026-05-22T01:00:00+00:00",
        )
    )
    refreshed_project = _load(project_path)
    refreshed_evidence = _load(project_root / refreshed_project["overpass_evidence_ref"])

    assert fetch_count == 1
    assert refreshed_project["overpass_fetched_at"] == "2026-05-22T01:00:00+00:00"
    assert refreshed_evidence.get("status") != "planned_no_network"
    assert refreshed_evidence["counts"]["candidates"] == 8


def test_layer_preparation_can_build_overpass_compatible_evidence_from_local_osm_pbf(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _copy_fixture_project(tmp_path)
    pbf_path = project_root / "sources" / "taiwan.osm.pbf"
    pbf_path.write_bytes(b"fixture-pbf")
    fresh_mtime = datetime(2026, 6, 20, tzinfo=timezone.utc).timestamp()
    os.utime(pbf_path, (fresh_mtime, fresh_mtime))
    raw_fixture = ROOT / "tests" / "fixtures" / "maps" / "phase_a_osm_pbf_osmjson.json"

    def fake_extract(**kwargs):
        assert kwargs["pbf_path"] == pbf_path.resolve()
        assert kwargs["bbox"]["south"] < kwargs["bbox"]["north"]
        assert kwargs["bbox"]["west"] < kwargs["bbox"]["east"]
        extracted_pbf_path = kwargs["raw_payload_path"].parent / "osm_pbf_route_bbox.osm.pbf"
        extracted_pbf_path.write_bytes(b"fixture-route-bbox-pbf")
        return (
            raw_fixture.read_bytes(),
            {
                "pbf_path": kwargs["pbf_path"].as_posix(),
                "bbox_wgs84": kwargs["bbox"],
                "extracted_pbf_path": extracted_pbf_path.as_posix(),
                "commands": [["osmium", "extract"]],
                "external_network_calls_made": False,
            },
        )

    monkeypatch.setattr(
        pretrip_layer_preparation,
        "_extract_osm_pbf_raw_payload",
        fake_extract,
    )

    manifest = run_layer_preparation(
        LayerPreparationRequest(
            project_id="chilai_nanhua_day1",
            project_root=project_root,
            layers=("osm", "overpass"),
            network_mode="no-network",
            allow_network_fetch=False,
            osm_pbf_path=pbf_path,
            osm_pbf_source_url=(
                "http://download.geofabrik.de/asia/taiwan-latest.osm.pbf"
            ),
            osm_pbf_cache_ttl_days=30,
            prepared_at="2026-06-25T00:00:00+00:00",
        )
    )
    project = _load(project_root / "project.json")
    evidence = _load(project_root / project["overpass_evidence_ref"])
    normalized = _load(project_root / project["overpass_map_context_ref"])
    layers_by_id = {layer["layer_id"]: layer for layer in manifest["layers"]}

    assert evidence["artifact_kind"] == "pretrip_osm_pbf_evidence"
    assert evidence["boundary"]["live_network_required"] is False
    assert evidence["counts"]["candidates"] == 6
    assert normalized["properties"]["source"] == "local_osm_pbf"
    assert normalized["properties"]["pbf_download_url"] == (
        "http://download.geofabrik.de/asia/taiwan-latest.osm.pbf"
    )
    assert project["osm_pbf_source_ref"] == pbf_path.resolve().as_posix()
    assert project["osm_pbf_source_url"] == (
        "http://download.geofabrik.de/asia/taiwan-latest.osm.pbf"
    )
    assert project["osm_pbf_raw_payload_ref"] == "normalized/map/osm_pbf_phase_a_raw.osm.json"
    assert project["osm_pbf_extracted_at"] == "2026-06-25T00:00:00+00:00"
    assert project["osm_pbf_route_extract_ref"] == (
        "normalized/map/osm_pbf_route_bbox.osm.pbf"
    )
    assert project["osm_pbf_render_extract_ref"] == (
        "normalized/map/osm_pbf_route_bbox.osm.pbf"
    )
    assert project["osm_pbf_render_extract_manifest_ref"] == (
        "normalized/map/osm_pbf_render_extract_manifest.json"
    )
    assert project["osm_pbf_render_extract_source_kind"] == (
        "local_osm_pbf_route_bbox_extract"
    )
    assert project["osm_pbf_render_extract_feature_count"] == 12
    assert project["osm_pbf_feature_index_ref"] == (
        "outputs/layers/normalized/osm_pbf_feature_index.json"
    )
    assert project["osm_pbf_feature_index_feature_count"] == 6
    assert project["osm_pbf_feature_index_category_counts"] == {
        "amenity_poi": 1,
        "peak_terrain": 1,
        "trail_network": 3,
        "water_hydrology": 1,
    }
    assert project["osm_pbf_cache_ttl_days"] == 30
    assert project["osm_pbf_cache_status"] == "fresh"
    assert project["osm_pbf_cache_expires_at"] == "2026-07-20T00:00:00+00:00"
    assert project["osm_pbf_refresh_required"] is False
    assert evidence["pbf_cache"]["cache_status"] == "fresh"
    render_manifest = _load(project_root / project["osm_pbf_render_extract_manifest_ref"])
    assert render_manifest["preferred_render_source_ref"] == (
        "normalized/map/osm_pbf_route_bbox.osm.pbf"
    )
    raw_ref = project["osm_pbf_raw_payload_ref"]
    assert render_manifest["osmjson_extract_ref"] == raw_ref
    assert (project_root / raw_ref).is_file()
    assert layers_by_id["overpass"]["status"] == "ready_from_project_ref"
    assert layers_by_id["overpass"]["lifecycle"]["fetch"]["status"] == (
        "completed_local_osm_pbf_extract"
    )
    assert layers_by_id["overpass"]["lifecycle"]["fetch"][
        "external_network_calls_made"
    ] is False
    assert layers_by_id["overpass"]["lifecycle"]["fetch"][
        "local_pbf_source_url"
    ] == "http://download.geofabrik.de/asia/taiwan-latest.osm.pbf"
    assert layers_by_id["overpass"]["lifecycle"]["fetch"][
        "local_pbf_cache_status"
    ] == "fresh"
    assert layers_by_id["overpass"]["lifecycle"]["fetch"][
        "local_pbf_refresh_required"
    ] is False
    assert layers_by_id["osm"]["counts"]["overpass_candidate_count"] == 6
    assert layers_by_id["osm"]["output_refs"]["local_osm_render_extract_ref"] == (
        "normalized/map/osm_pbf_route_bbox.osm.pbf"
    )
    assert layers_by_id["osm"]["output_refs"]["osm_rendering_policy"] == (
        "workspace_local_osm_extract_available"
    )
    assert layers_by_id["osm"]["counts"]["local_osm_render_extract_feature_count"] == 12
    assert layers_by_id["osm"]["counts"]["local_osm_feature_index_feature_count"] == 6
    assert layers_by_id["osm"]["output_refs"]["local_osm_feature_index_ref"] == (
        "outputs/layers/normalized/osm_pbf_feature_index.json"
    )


def test_local_osm_pbf_cache_metadata_marks_stale_after_ttl(tmp_path: Path) -> None:
    pbf_path = tmp_path / "taiwan.osm.pbf"
    pbf_path.write_bytes(b"fixture-pbf")
    stale_mtime = datetime(2026, 5, 1, tzinfo=timezone.utc).timestamp()
    os.utime(pbf_path, (stale_mtime, stale_mtime))

    metadata = pretrip_layer_preparation._osm_pbf_cache_metadata(
        pbf_path,
        source_url="http://download.geofabrik.de/asia/taiwan-latest.osm.pbf",
        ttl_days=30,
        now_iso="2026-06-25T00:00:00+00:00",
    )

    assert metadata["cache_policy"] == "download_once_reuse_until_ttl_expires"
    assert metadata["cache_status"] == "stale_refresh_recommended"
    assert metadata["refresh_required"] is True
    assert metadata["expires_at"] == "2026-05-31T00:00:00+00:00"


def test_layer_preparation_run_writes_workspace_outputs_and_project_refs(
    tmp_path: Path,
) -> None:
    project_root = _copy_fixture_project(tmp_path)
    manifest = run_layer_preparation(
        LayerPreparationRequest(
            project_id="chilai_nanhua_day1",
            project_root=project_root,
            layers=("osm", "overpass", "terrain", "imagery", "weather"),
            prepared_at="2026-05-22T00:00:00+00:00",
        )
    )
    project = _load(project_root / "project.json")

    assert manifest["artifact_kind"] == "pretrip_layer_preparation_manifest"
    assert manifest["validation"]["status"] in {"ready", "ready_with_warnings"}
    assert manifest["counts"]["layer_count"] == 5
    assert manifest["counts"]["ready_layer_count"] == 5
    warning_layer_ids = {
        warning["layer_id"] for warning in manifest["validation"]["warnings"]
    }
    assert "osm" not in warning_layer_ids
    assert "overpass" not in warning_layer_ids
    assert manifest["network_policy"]["network_calls_made"] is False
    assert manifest["boundary"]["runtime_safety_truth"] is False
    assert manifest["boundary"]["final_mission_graph_compiled"] is False
    layers_by_id = {layer["layer_id"]: layer for layer in manifest["layers"]}
    assert layers_by_id["osm"]["warnings"] == []
    assert layers_by_id["osm"]["policy_notes"]
    assert layers_by_id["osm"]["status"] == "ready_from_project_ref"
    assert layers_by_id["osm"]["counts"]["osm_raster_tile_fetch_required"] is False
    assert layers_by_id["osm"]["counts"]["overpass_candidate_count"] > 0
    assert layers_by_id["osm"]["output_refs"]["osm_data_evidence_policy"] == (
        "covered_by_overpass_vector_evidence"
    )
    assert layers_by_id["overpass"]["status"] == "ready_from_project_ref"
    assert layers_by_id["overpass"]["warnings"] == []
    assert project["layer_preparation_manifest_ref"] == (
        "outputs/layers/layer_preparation_manifest.json"
    )
    assert (project_root / project["layer_preparation_manifest_ref"]).is_file()
    assert (project_root / project["layer_preparation_job_ref"]).is_file()


def test_layer_preparation_exposes_cwa_and_gee_environment_layers_without_network(
    tmp_path: Path,
) -> None:
    project_root = _copy_fixture_project(tmp_path)
    preview = build_layer_preparation_preview(
        LayerPreparationRequest(
            project_id="chilai_nanhua_day1",
            project_root=project_root,
            layers=("cwa-weather", "cwa-qpf", "soil-moisture", "antecedent-rain"),
            prepared_at="2026-05-22T00:00:00+00:00",
        )
    )
    layers_by_id = {layer["layer_id"]: layer for layer in preview["layers"]}

    assert preview["normalized_layers"] == [
        "cwa-weather",
        "cwa-qpf",
        "soil-moisture",
        "antecedent-rain",
    ]
    assert preview["network_policy"]["network_calls_made"] is False
    assert preview["boundary"]["runtime_safety_truth"] is False
    assert layers_by_id["cwa-weather"]["status"] == "missing_source"
    assert layers_by_id["cwa-weather"]["output_refs"]["server_side_api_key_env"] == (
        "SCOUT_CWA_API_KEY"
    )
    assert layers_by_id["cwa-weather"]["output_refs"]["client_api_key_allowed"] is False
    assert layers_by_id["cwa-qpf"]["output_refs"]["cwa_qpf_grid_ref"] == (
        "outputs/environment/cwa/qpf_grid.geojson"
    )
    assert layers_by_id["soil-moisture"]["output_refs"]["soil_moisture_grid_ref"] == (
        "outputs/environment/gee/soil_moisture_grid.geojson"
    )
    assert layers_by_id["soil-moisture"]["output_refs"][
        "gee_fetch_requires_explicit_network"
    ] is True
    assert layers_by_id["antecedent-rain"]["output_refs"][
        "antecedent_rain_grid_ref"
    ] == "outputs/environment/gee/antecedent_rain_grid.geojson"
    assert all(
        layer["lifecycle"]["fetch"]["external_network_calls_made"] is False
        for layer in layers_by_id.values()
    )


def test_layer_preparation_writes_environment_status_artifacts_for_admin_view(
    tmp_path: Path,
) -> None:
    project_root = _copy_fixture_project(tmp_path)

    run_layer_preparation(
        LayerPreparationRequest(
            project_id="chilai_nanhua_day1",
            project_root=project_root,
            layers=("cwa-weather", "cwa-qpf", "soil-moisture", "antecedent-rain"),
            network_mode="no-network",
            allow_network_fetch=False,
            prepared_at="2026-05-22T00:00:00+00:00",
        )
    )

    project = json.loads((project_root / "project.json").read_text(encoding="utf-8"))
    for ref_key in (
        "environment_evidence_package_ref",
        "environment_factor_matrix_ref",
        "go_no_go_review_draft_ref",
        "cwa_qpf_grid_ref",
        "cwa_weather_evidence_ref",
        "cwa_forecast_timeline_ref",
        "cwa_astronomy_timeline_ref",
        "cwa_tide_marine_timeline_ref",
        "soil_moisture_grid_ref",
        "antecedent_rain_grid_ref",
        "gee_gpm_imerg_raw_summary_ref",
        "gee_feature_package_ref",
    ):
        assert ref_key in project
        assert (project_root / project[ref_key]).is_file()

    cwa_evidence = json.loads(
        (project_root / project["cwa_weather_evidence_ref"]).read_text(
            encoding="utf-8"
        )
    )
    qpf = json.loads((project_root / project["cwa_qpf_grid_ref"]).read_text(encoding="utf-8"))
    soil = json.loads(
        (project_root / project["soil_moisture_grid_ref"]).read_text(encoding="utf-8")
    )
    assert project["cwa_cacheable"] is False
    assert project["cwa_ttl_seconds"] == 0
    assert project["cwa_cache_policy"]["must_refetch_on_prepare"] is True
    assert cwa_evidence["cache_policy"]["cacheable"] is False
    assert cwa_evidence["time_precision"] == "hour"
    assert qpf["cache_policy"]["reuse_previous_values"] is False
    assert qpf["features"][0]["properties"]["layer_id"] == "cwa-qpf"
    assert qpf["features"][0]["properties"]["runtime_safety_truth"] is False
    environment_package = json.loads(
        (project_root / project["environment_evidence_package_ref"]).read_text(
            encoding="utf-8"
        )
    )
    factor_matrix = json.loads(
        (project_root / project["environment_factor_matrix_ref"]).read_text(
            encoding="utf-8"
        )
    )
    go_no_go = json.loads(
        (project_root / project["go_no_go_review_draft_ref"]).read_text(
            encoding="utf-8"
        )
    )
    assert environment_package["artifact_kind"] == "environment_evidence_package"
    assert environment_package["runtime_safety_truth"] is False
    assert factor_matrix["artifact_kind"] == "environment_factor_matrix"
    assert go_no_go["artifact_kind"] == "go_no_go_review_draft"
    assert go_no_go["decision_state"] == "hold"
    assert soil["features"][0]["properties"]["status"] in {
        "missing_credentials",
        "configured_pending_fetcher",
        "configured_pending_explicit_fetch",
    }
    feature_package = json.loads(
        (project_root / project["gee_feature_package_ref"]).read_text(encoding="utf-8")
    )
    assert feature_package["artifact_kind"] == "scout_gee_feature_package"
    assert feature_package["mobile_runtime_dependency"] is False
    assert feature_package["raspberry_pi_runtime_dependency"] is False
    assert feature_package["boundary"]["runtime_safety_truth"] is False

    view = build_pretrip_admin_view(
        "chilai_nanhua_day1",
        root=ROOT,
        project_root=project_root,
    )
    assert view["cwa_qpf"]["points"]
    assert view["soil_moisture"]["points"]
    assert view["antecedent_rain"]["points"]
    assert view["cwa_qpf"]["points"][0]["runtime_safety_truth"] is False


def test_layer_preparation_writes_cwa_hourly_fetch_and_validity_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _copy_fixture_project(tmp_path)

    import scout_weather_integration

    def fake_fetch_cwa_dataset(dataset_id: str, **_kwargs: object) -> dict[str, object]:
        return {"dataset_id": dataset_id}

    def fake_normalize_weather_points(
        dataset_id: str,
        _payload: dict[str, object],
        *,
        source_run_id: str | None = None,
    ) -> list[dict[str, object]]:
        return [
            {
                "source": dataset_id,
                "source_run_id": source_run_id,
                "areaName": "南投縣仁愛鄉",
                "validFrom": "2026-06-26T02:30:00+00:00",
                "validTo": "2026-06-26T08:30:00+00:00",
                "rainProbability": 75,
                "rainfallMm": 18.5,
                "weatherText": "午後雷陣雨",
            }
        ]

    def fake_normalize_warnings(
        _payload: dict[str, object],
        *,
        source_run_id: str | None = None,
    ) -> list[dict[str, object]]:
        return [
            {
                "source": "W-C0033-001",
                "source_run_id": source_run_id,
                "warning_id": "warning.001",
                "headline": "大雨特報",
                "valid_from": "2026-06-26T03:15:00+00:00",
                "valid_to": "2026-06-26T09:45:00+00:00",
            }
        ]

    monkeypatch.setenv("SCOUT_CWA_API_KEY", "test-key")
    monkeypatch.setattr(
        scout_weather_integration,
        "fetch_cwa_dataset",
        fake_fetch_cwa_dataset,
    )
    monkeypatch.setattr(
        scout_weather_integration,
        "normalize_cwa_weather_points",
        fake_normalize_weather_points,
    )
    monkeypatch.setattr(
        scout_weather_integration,
        "normalize_cwa_warnings",
        fake_normalize_warnings,
    )

    run_layer_preparation(
        LayerPreparationRequest(
            project_id="chilai_nanhua_day1",
            project_root=project_root,
            layers=("cwa-weather", "cwa-qpf"),
            network_mode="explicit-fetch",
            allow_network_fetch=True,
            prepared_at="2026-06-26T01:12:44+00:00",
        )
    )

    project = json.loads((project_root / "project.json").read_text(encoding="utf-8"))
    cwa_evidence = json.loads(
        (project_root / project["cwa_weather_evidence_ref"]).read_text(
            encoding="utf-8"
        )
    )
    qpf = json.loads((project_root / project["cwa_qpf_grid_ref"]).read_text(encoding="utf-8"))
    qpf_summary = json.loads(
        (project_root / project["cwa_qpf_corridor_summary_ref"]).read_text(
            encoding="utf-8"
        )
    )
    forecast_timeline = json.loads(
        (project_root / project["cwa_forecast_timeline_ref"]).read_text(
            encoding="utf-8"
        )
    )
    environment_package = json.loads(
        (project_root / project["environment_evidence_package_ref"]).read_text(
            encoding="utf-8"
        )
    )
    factor_matrix = json.loads(
        (project_root / project["environment_factor_matrix_ref"]).read_text(
            encoding="utf-8"
        )
    )
    go_no_go = json.loads(
        (project_root / project["go_no_go_review_draft_ref"]).read_text(
            encoding="utf-8"
        )
    )
    view = build_pretrip_admin_view(
        "chilai_nanhua_day1",
        root=ROOT,
        project_root=project_root,
    )

    assert project["cwa_fetched_at_hour"] == "2026-06-26T01:00:00Z"
    assert project["cwa_valid_from_hour"] == "2026-06-26T02:00:00Z"
    assert project["cwa_valid_until_hour"] == "2026-06-26T09:00:00Z"
    assert cwa_evidence["api_fetched_at_hour"] == "2026-06-26T01:00:00Z"
    assert cwa_evidence["cwa_time_metadata"]["api_fetched_at_hour"] == (
        "2026-06-26T01:00:00Z"
    )
    assert cwa_evidence["forecast_valid_until_hour"] == "2026-06-26T08:00:00Z"
    assert cwa_evidence["warning_valid_until_hour"] == "2026-06-26T09:00:00Z"
    assert qpf["cwa_time_metadata"]["valid_until_hour"] == "2026-06-26T09:00:00Z"
    assert qpf["features"][0]["properties"]["api_fetched_at_hour"] == (
        "2026-06-26T01:00:00Z"
    )
    assert qpf["features"][0]["properties"]["cwa_time_metadata"][
        "api_fetched_at_hour"
    ] == "2026-06-26T01:00:00Z"
    assert qpf["features"][0]["properties"]["valid_until_hour"] == (
        "2026-06-26T08:00:00Z"
    )
    assert qpf_summary["valid_until_hour"] == "2026-06-26T09:00:00Z"
    assert forecast_timeline["events"][0]["valid_until_hour"] == (
        "2026-06-26T08:00:00Z"
    )
    assert environment_package["cwa_time_metadata"]["api_fetched_at_hour"] == (
        "2026-06-26T01:00:00Z"
    )
    assert factor_matrix["cwa_time_metadata"]["valid_until_hour"] == (
        "2026-06-26T09:00:00Z"
    )
    assert go_no_go["data_freshness_summary"]["cwa_api_request_attempted_at_hour"] == (
        "2026-06-26T01:00:00Z"
    )
    assert go_no_go["data_freshness_summary"]["cwa_valid_until_hour"] == (
        "2026-06-26T09:00:00Z"
    )
    assert view["cwa_qpf"]["temporal_coverage"]["api_fetched_at_hour"] == (
        "2026-06-26T01:00:00Z"
    )
    cwa_value_item = next(
        item
        for item in view["environment_values"]["items"]
        if item["layer_id"] == "cwa-qpf"
    )
    assert cwa_value_item["value_summary"]["api_fetched_at_hour"] == (
        "2026-06-26T01:00:00Z"
    )


def test_layer_preparation_writes_gee_numeric_artifacts_with_injected_fetcher(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _copy_fixture_project(tmp_path)
    route_gpx = _write_gpx(
        project_root / "sources" / "gee_route.gpx",
        name="gee route",
        points=[
            (23.8700, 121.1700, 1400, "2026-05-22T00:00:00Z"),
            (23.8710, 121.1710, 1420, "2026-05-22T00:10:00Z"),
            (23.8720, 121.1720, 1440, "2026-05-22T00:20:00Z"),
        ],
    )
    project_payload = json.loads((project_root / "project.json").read_text(encoding="utf-8"))
    project_payload["golden_route_gpx_ref"] = str(route_gpx.relative_to(project_root))
    cwa_time_metadata = {
        "api_request_attempted_at_hour": "2026-06-26T01:00:00Z",
        "api_fetched_at_hour": "2026-06-26T01:00:00Z",
        "forecast_valid_until_hour": "2026-06-26T08:00:00Z",
        "valid_until_hour": "2026-06-26T09:00:00Z",
        "time_precision": "hour",
        "timezone": "UTC",
    }
    cwa_root = project_root / "outputs" / "environment" / "cwa"
    cwa_root.mkdir(parents=True, exist_ok=True)
    (cwa_root / "cwa_weather_evidence.json").write_text(
        json.dumps(
            {
                "artifact_kind": "cwa_weather_environment_evidence",
                "status": "ready",
                "cwa_time_metadata": cwa_time_metadata,
                "temporal_coverage": cwa_time_metadata,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    project_payload["cwa_weather_evidence_ref"] = (
        "outputs/environment/cwa/cwa_weather_evidence.json"
    )
    (project_root / "project.json").write_text(
        json.dumps(project_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    class FakeGeeFetchResult:
        def to_dict(self) -> dict[str, object]:
            return {
                "status": "fetched",
                "blocker_reasons": [],
                "external_api_calls_made": True,
                "raw_summary": {
                    "provider": "google_earth_engine",
                    "responses": {
                        "smap_l4_surface_rootzone_soil_moisture": {
                            "http_status": 200,
                            "result": {
                                "sm_surface": 0.37,
                                "sm_rootzone": 0.44,
                            },
                        },
                        "gpm_imerg_precipitation": {
                            "http_status": 200,
                            "result": {"precipitation": 22.5},
                        },
                    },
                    "secret_value_embedded": False,
                },
                "soil_moisture": {
                    "dataset_family": "SMAP",
                    "collection_id": "NASA/SMAP/SPL4SMGP/008",
                    "status": "fetched",
                    "sm_surface_wetness": 0.37,
                    "sm_rootzone_wetness": 0.44,
                    "antecedent_wetness_percentile": None,
                    "sample_count": 1,
                },
                "antecedent_rain": {
                    "dataset_family": "GPM_IMERG",
                    "collection_id": "NASA/GPM_L3/IMERG_V07",
                    "status": "fetched",
                    "last_72h_mm": 22.5,
                    "last_24h_mm": None,
                    "last_3h_mm": None,
                    "sample_count": 1,
                },
                "smap_timeseries": {
                    "artifact_kind": "gee_soil_moisture_timeseries",
                    "layer_id": "soil-moisture",
                    "status": "fetched",
                    "samples": [{"timestamp": "2026-05-22T00:00:00+00:00"}],
                    "runtime_safety_truth": False,
                },
                "gpm_timeseries": {
                    "artifact_kind": "gee_antecedent_rain_timeseries",
                    "layer_id": "antecedent-rain",
                    "status": "fetched",
                    "samples": [{"timestamp": "2026-05-22T00:00:00+00:00"}],
                    "runtime_safety_truth": False,
                },
            }

    def fake_fetcher(**kwargs):
        assert kwargs["project_id"] == "test-project"
        assert kwargs["bbox_wgs84"]["west"] < kwargs["bbox_wgs84"]["east"]
        return FakeGeeFetchResult()

    class FakeRouteFeatureClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def fetch_route_feature_package(self, **kwargs):
            assert kwargs["project_id"] == "chilai_nanhua_day1"
            segment = kwargs["segments"][0]["properties"]["segment_id"]
            return {
                "provider": "google_earth_engine",
                "segment_features": [
                    {
                        "segment_id": segment,
                        "elevation_m": 1500,
                        "slope_deg": 28,
                        "aspect_deg": 115,
                        "terrain_ruggedness": 61,
                        "curvature_proxy": -0.1,
                        "flow_accumulation_proxy": 2300,
                        "dynamic_world_probabilities": {"trees": 0.7, "bare": 0.1},
                        "sentinel2_indices": {"ndvi": 0.44, "bsi": 0.2, "ndwi": -0.1},
                        "sentinel2_before_after_change_score": 0.2,
                        "sentinel1_before_after_backscatter_anomaly_db": -1.5,
                        "gpm_recent_rainfall_mm": 128.0,
                        "chirps_rainfall_anomaly": 0.8,
                        "nearest_firms_active_fire_distance_m": 12000,
                        "sentinel2_cloud_free_count": 2,
                    }
                ],
                "secret_value_embedded": False,
                "external_api_call_performed": True,
                "runtime_safety_truth": False,
            }

    monkeypatch.setenv("SCOUT_GEE_ENABLED", "true")
    monkeypatch.setenv("SCOUT_GEE_PROJECT_ID", "test-project")
    monkeypatch.setenv("EARTHENGINE_TOKEN", "test-token-ref")
    monkeypatch.setattr(
        "scout_gee_integration.fetch_gee_environment_evidence",
        fake_fetcher,
    )
    monkeypatch.setattr(
        "scout_gee_integration.RestGeeRouteFeatureClient",
        FakeRouteFeatureClient,
    )

    manifest = run_layer_preparation(
        LayerPreparationRequest(
            project_id="chilai_nanhua_day1",
            project_root=project_root,
            layers=("soil-moisture", "antecedent-rain"),
            network_mode="explicit-fetch",
            allow_network_fetch=True,
            prepared_at="2026-05-22T00:00:00+00:00",
        )
    )

    project = json.loads((project_root / "project.json").read_text(encoding="utf-8"))
    soil = json.loads(
        (project_root / project["soil_moisture_grid_ref"]).read_text(encoding="utf-8")
    )
    rain = json.loads(
        (project_root / project["antecedent_rain_grid_ref"]).read_text(encoding="utf-8")
    )
    raw_summary = json.loads(
        (project_root / project["gee_raw_summary_ref"]).read_text(encoding="utf-8")
    )
    gpm_raw_summary = json.loads(
        (project_root / project["gee_gpm_imerg_raw_summary_ref"]).read_text(
            encoding="utf-8"
        )
    )
    feature_package = json.loads(
        (project_root / project["gee_feature_package_ref"]).read_text(encoding="utf-8")
    )
    derivatives = json.loads(
        (project_root / project["environment_risk_derivatives_ref"]).read_text(
            encoding="utf-8"
        )
    )
    wetness = json.loads(
        (project_root / project["wetness_flash_flood_susceptibility_ref"]).read_text(
            encoding="utf-8"
        )
    )

    assert project["gee_environment_status"] == "fetched"
    assert project["gee_external_api_calls_made"] is True
    assert project["gee_numeric_cacheable"] is False
    assert project["gee_numeric_ttl_seconds"] == 0
    assert project["gee_cache_policy"]["must_refetch_on_prepare"] is True
    assert manifest["boundary"]["external_api_calls_made"] is True
    assert soil["cache_policy"]["cacheable"] is False
    assert rain["cache_policy"]["ttl_seconds"] == 0
    assert soil["features"][0]["properties"]["sm_surface_wetness"] == 0.37
    assert soil["features"][0]["properties"]["sm_rootzone_wetness"] == 0.44
    assert rain["features"][0]["properties"]["last_72h_mm"] == 22.5
    assert soil["features"][0]["properties"]["raw_summary_sha256"]
    assert (
        soil["features"][0]["properties"]["cache_policy"][
            "reuse_previous_numeric_values"
        ]
        is False
    )
    assert raw_summary["cache_policy"]["cacheable"] is False
    assert raw_summary["secret_value_embedded"] is False
    assert gpm_raw_summary["artifact_kind"] == "gee_gpm_imerg_raw_summary"
    assert gpm_raw_summary["cache_policy"]["cacheable"] is False
    assert gpm_raw_summary["secret_value_embedded"] is False
    assert soil["boundary"]["external_api_calls_made"] is True
    assert soil["features"][0]["properties"]["runtime_safety_truth"] is False
    assert project["gee_feature_package_status"] == "ready"
    assert project["gee_feature_package_segment_count"] > 0
    assert project["environment_risk_derivative_status"].startswith("ready")
    assert (project_root / project["new_landslide_candidates_ref"]).is_file()
    assert (project_root / project["wetness_flash_flood_susceptibility_ref"]).is_file()
    assert (project_root / project["trail_obscurity_risk_ref"]).is_file()
    assert (project_root / project["practical_darkness_time_ref"]).is_file()
    assert (project_root / project["route_revalidation_report_ref"]).is_file()
    assert derivatives["artifact_kind"] == "scout_environment_risk_derivatives"
    assert derivatives["cwa_time_metadata"]["api_fetched_at_hour"] == (
        "2026-06-26T01:00:00Z"
    )
    assert wetness["cwa_time_metadata"]["valid_until_hour"] == "2026-06-26T09:00:00Z"
    assert wetness["features"][0]["properties"]["cwa_api_fetched_at_hour"] == (
        "2026-06-26T01:00:00Z"
    )
    assert derivatives["counts"]["segment_count"] > 0
    assert derivatives["boundary"]["runtime_safety_truth"] is False
    assert feature_package["route"]["buffer_m"] == 500.0
    assert feature_package["segments"][0]["slope_deg"] == 28
    assert feature_package["boundary"]["external_api_calls_made"] is True
    assert feature_package["boundary"]["raspberry_pi_runtime_gee_dependency"] is False


def test_layer_preparation_ignores_local_imagery_refs_for_wmts_runtime(
    tmp_path: Path,
) -> None:
    project_root = _copy_fixture_project(tmp_path)
    manifest_dir = project_root / "outputs" / "layers" / "manifests"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "chilai_nanhua_day1.local_raster_source_manifest.json").write_text(
        json.dumps(
            {
                "source_kind": "local_geotiff",
                "source_file": {"path": "/data/scout/raster-sources/map.tiff"},
                "georeference": {
                    "bbox_wgs84": {
                        "west": 121.21478855,
                        "south": 24.03365911,
                        "east": 121.30320941,
                        "north": 24.06992621,
                    }
                },
                "handoff": {"scout_kmz_path": "/data/scout/raster-sources/map.kmz"},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (manifest_dir / "chilai_nanhua_day1.raster_tile_pyramid_plan.json").write_text(
        json.dumps(
            {
                "cache_root": "/data/scout/raster-tiles",
                "zoom_range": "5-14",
                "total_tile_count": 36,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    manifest = run_layer_preparation(
        LayerPreparationRequest(
            project_id="chilai_nanhua_day1",
            project_root=project_root,
            layers=("imagery",),
            prepared_at="2026-05-22T00:00:00+00:00",
        )
    )
    imagery_layer = manifest["layers"][0]

    assert imagery_layer["status"] == "wmts_runtime_only"
    assert imagery_layer["raster_tile_delivery"] == "direct_wmts_runtime"
    assert imagery_layer["counts"]["registered_raster_manifest_count"] == 0
    assert imagery_layer["counts"]["imagery_tile_cache_plan_tile_count"] == 0
    assert imagery_layer["downloads_tiles_into_repo"] is False
    assert "raster_bbox_wgs84" not in imagery_layer
    assert "raster_tile_zoom_range" not in imagery_layer
    projection = _load(project_root / manifest["outputs"]["layer_map_projection_ref"])
    projected_imagery = projection["layers"][0]
    assert projected_imagery["status"] == "wmts_runtime_only"
    assert projected_imagery["raster_tile_delivery"] == "direct_wmts_runtime"
    assert "local_raster_tile_url_template" not in projected_imagery
    assert "imagery_tile_cache_plan_ref" not in manifest["outputs"]


def test_layer_preparation_keeps_imagery_bbox_metadata_without_cache_plan(
    tmp_path: Path,
) -> None:
    project_root = _copy_fixture_project(tmp_path)
    project_path = project_root / "project.json"
    project = _load(project_path)
    project.pop("imagery_manifest_ref", None)
    project.pop("local_raster_manifest_ref", None)
    project.pop("raster_tile_manifest_ref", None)
    project["imagery_source_id"] = "nlsc_photo2"
    project["imagery_source_registry_id"] = "scout.imagery_sources.default.v1"
    project["imagery_bbox_wgs84"] = {
        "west": 121.2,
        "south": 24.03,
        "east": 121.31,
        "north": 24.08,
    }
    project["imagery_bbox_policy"] = "gpx_bbox_scaled_115_percent"
    project["imagery_bbox_scale_factor"] = 1.15
    project_path.write_text(json.dumps(project, ensure_ascii=False), encoding="utf-8")

    manifest = run_layer_preparation(
        LayerPreparationRequest(
            project_id="chilai_nanhua_day1",
            project_root=project_root,
            layers=("imagery",),
            prepared_at="2026-05-22T00:00:00+00:00",
        )
    )

    imagery_layer = manifest["layers"][0]
    projection = _load(project_root / manifest["outputs"]["layer_map_projection_ref"])
    projected = projection["layers"][0]

    assert imagery_layer["status"] == "wmts_runtime_only"
    assert imagery_layer["imagery_source_id"] == "nlsc_photo2"
    assert imagery_layer["raster_tile_delivery"] == "direct_wmts_runtime"
    assert "raster_bbox_wgs84" not in imagery_layer
    assert "imagery_tile_cache_plan_ref" not in imagery_layer
    assert "imagery_tile_cache_plan" not in imagery_layer
    assert "raster_tile_zoom_range" not in imagery_layer
    assert imagery_layer["counts"]["remote_imagery_source_registered"] is True
    assert projected["imagery_source_id"] == "nlsc_photo2"
    assert projected["raster_tile_delivery"] == "direct_wmts_runtime"
    assert "local_raster_tile_url_template" not in projected
    assert "imagery_tile_cache_plan_ref" not in manifest["outputs"]


def test_layer_preparation_seeds_imagery_cache_for_raster_ocr_pipeline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _copy_fixture_project(tmp_path)
    project_path = project_root / "project.json"
    project = _load(project_path)
    project.pop("imagery_manifest_ref", None)
    project.pop("local_raster_manifest_ref", None)
    project.pop("raster_tile_manifest_ref", None)
    project["imagery_source_id"] = "happyman_rudy"
    project["imagery_bbox_wgs84"] = {
        "west": 121.2,
        "south": 24.03,
        "east": 121.21,
        "north": 24.04,
    }
    project["raster_label_ocr_label_count"] = 99
    project["raster_label_evidence_count"] = 99
    project_path.write_text(json.dumps(project, ensure_ascii=False), encoding="utf-8")
    def fake_seed(plan, **kwargs):
        return {
            "status": "seed_complete",
            "dry_run": False,
            "tiles_seen": 1,
            "tiles_written": 1,
            "tiles_skipped_existing": 0,
            "bytes_written": 123,
            "cache_root": plan["cache_root"],
        }

    def fake_extract(project_root_arg, **kwargs):
        output_ref = kwargs["output_ref"]
        payload = {
            "artifact_kind": "pretrip_raster_label_ocr_output",
            "schema_version": "route_corridor_map_preparation.v1",
            "status": "completed",
            "project_id": "chilai_nanhua_day1",
            "source_path": output_ref,
            "generated_at": "2026-05-22T00:00:00+00:00",
            "labels": [
                {
                    "id": "ocr.rudy_tw.6k",
                    "label_text": "6K",
                    "label_role": "trail_mileage_k_anchor",
                    "lat": 24.053,
                    "lon": 121.245,
                    "confidence": 0.91,
                    "bbox_px": [8, 8, 34, 24],
                    "tile_bbox_wgs84": {
                        "west": 121.244,
                        "south": 24.052,
                        "east": 121.246,
                        "north": 24.054,
                    },
                    "source_ref": "rudy_tw_test_tile",
                    "source_image_hash": "sha256:test",
                    "review_required": True,
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                }
            ],
            "counts": {"label_count": 1},
            "candidate_only": True,
            "runtime_safety_truth": False,
            "boundary": {
                "candidate_only": True,
                "runtime_safety_truth": False,
            },
        }
        (Path(project_root_arg) / output_ref).parent.mkdir(parents=True, exist_ok=True)
        (Path(project_root_arg) / output_ref).write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
        project_data = _load(Path(project_root_arg) / "project.json")
        project_data["raster_label_ocr_output_ref"] = output_ref
        project_data["raster_label_ocr_status"] = "completed"
        project_data["raster_label_ocr_label_count"] = 1
        (Path(project_root_arg) / "project.json").write_text(
            json.dumps(project_data, ensure_ascii=False),
            encoding="utf-8",
        )
        return {
            "status": "completed",
            "project_id": "chilai_nanhua_day1",
            "output_ref": output_ref,
            "label_count": 1,
            "tile_record_count": 1,
            "tile_skipped_count": 0,
            "writes_performed": True,
            "candidate_only": True,
            "runtime_safety_truth": False,
            "missing_dependencies": [],
        }

    import pretrip_raster_label_ocr

    monkeypatch.setattr(pretrip_layer_preparation, "seed_imagery_tile_cache", fake_seed)
    monkeypatch.setattr(pretrip_raster_label_ocr, "extract_raster_label_ocr", fake_extract)

    manifest = run_layer_preparation(
        LayerPreparationRequest(
            project_id="chilai_nanhua_day1",
            project_root=project_root,
            layers=("imagery",),
            network_mode="explicit-fetch",
            allow_network_fetch=True,
            imagery_min_zoom=12,
            imagery_max_zoom=12,
            seed_imagery_cache=True,
            imagery_provider_allows_offline_prefetch=True,
            imagery_seed_max_tiles=2,
            prepared_at="2026-05-22T00:00:00+00:00",
        )
    )
    project = _load(project_path)
    raster_pipeline = manifest["raster_label_preparation"]
    imagery_layer = {layer["layer_id"]: layer for layer in manifest["layers"]}["imagery"]
    projection = _load(project_root / manifest["outputs"]["layer_map_projection_ref"])
    projected_imagery = {layer["layer_id"]: layer for layer in projection["layers"]}[
        "imagery"
    ]

    assert project["imagery_tile_cache_seed_status"] == "seed_complete"
    assert imagery_layer["raster_bbox_wgs84"] == project["imagery_bbox_wgs84"]
    assert imagery_layer["raster_coverage_policy"] == "render_intersecting_tiles_only"
    assert imagery_layer["raster_tile_zoom_range"] == "12-12"
    assert imagery_layer["raster_tile_count"] == 2
    assert imagery_layer["output_refs"]["local_raster_tile_url_template"] == (
        "/admin/tiles/imagery/chilai_nanhua_day1/imagery/{z}/{x}/{y}.png"
    )
    assert projected_imagery["raster_bbox_wgs84"] == project["imagery_bbox_wgs84"]
    assert projected_imagery["raster_coverage_policy"] == (
        "render_intersecting_tiles_only"
    )
    assert projected_imagery["raster_tile_zoom_range"] == "12-12"
    assert projected_imagery["local_raster_tile_url_template"] == (
        "/admin/tiles/imagery/chilai_nanhua_day1/imagery/{z}/{x}/{y}.png"
    )
    assert project["raster_label_ocr_label_count"] == 1
    assert project["raster_label_evidence_count"] == 1
    assert raster_pipeline["status"] == "completed"
    assert raster_pipeline["ocr"]["status"] == "completed"
    assert raster_pipeline["adapter"]["feature_count"] == 1
    raster_label_evidence = _load(project_root / project["raster_label_evidence_ref"])
    assert raster_label_evidence["route_scope_ref"] == (
        "normalized/routes/route_evidence_bundle.json"
    )
    assert raster_label_evidence["boundary"]["raw_gpx_embedded_in_json"] is False
    assert raster_pipeline["route_context_collection"]["status"] == "completed"
    assert project["route_mileage_k_anchor_count"] >= 1
    route_mileage_anchors = _load(project_root / project["route_mileage_k_anchors_ref"])
    assert any(
        anchor["normalized_mileage_k"] == "6K"
        for anchor in route_mileage_anchors["anchors"]
    )
    mileage_tags = _load(project_root / project["mileage_tag_alignment_ref"])
    assert mileage_tags["counts"]["usable_anchor_count"] >= 1


def test_layer_preparation_does_not_copy_known_scout_imagery_manifests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _copy_fixture_project(tmp_path)
    scout_root = tmp_path / "scout-data"
    source_manifest_dir = (
        scout_root
        / "admin"
        / "pretrip-workspaces"
        / "chilai_nanhua_day1"
        / "outputs"
        / "layers"
        / "manifests"
    )
    source_manifest_dir.mkdir(parents=True)
    (source_manifest_dir / "chilai_nanhua_day1.local_raster_source_manifest.json").write_text(
        json.dumps(
            {
                "source_kind": "local_geotiff",
                "source_file": {"path": "/data/scout/raster-sources/copied.tiff"},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (source_manifest_dir / "chilai_nanhua_day1.raster_tile_pyramid_plan.json").write_text(
        json.dumps({"cache_root": "/data/scout/raster-tiles"}, sort_keys=True),
        encoding="utf-8",
    )
    monkeypatch.setattr(pretrip_layer_preparation, "DEFAULT_SCOUT_DATA_ROOT", scout_root)

    manifest = run_layer_preparation(
        LayerPreparationRequest(
            project_id="chilai_nanhua_day1",
            project_root=project_root,
            layers=("imagery",),
            prepared_at="2026-05-22T00:00:00+00:00",
        )
    )
    project = _load(project_root / "project.json")

    assert not (
        project_root
        / "outputs/layers/manifests/chilai_nanhua_day1.local_raster_source_manifest.json"
    ).is_file()
    assert not (
        project_root
        / "outputs/layers/manifests/chilai_nanhua_day1.raster_tile_pyramid_plan.json"
    ).is_file()
    assert "imagery_manifest_ref" not in project
    assert "raster_tile_manifest_ref" not in project
    imagery_layer = manifest["layers"][0]
    assert imagery_layer["status"] == "wmts_runtime_only"


def test_layer_preparation_records_gpx_filter_provenance_from_import_workspace(
    tmp_path: Path,
) -> None:
    golden_route = _write_gpx(
        tmp_path / "golden-route.gpx",
        name="layer prep filtered route",
        points=[
            (24.0, 121.0, 1000.0, "2026-05-01T00:00:00Z"),
            (25.0, 122.0, 1000.0, "2026-05-01T00:01:00Z"),
            (24.001, 121.001, 1001.0, "2026-05-01T00:20:00Z"),
        ],
    )
    workspace_root = tmp_path / "workspaces"
    run_pretrip_import(
        PretripImportRequest(
            project_id="filtered_layer_prep",
            primary_gpx=golden_route,
            workspace_root=workspace_root,
            checkpoint_spacing_m=100.0,
            import_timestamp="2026-05-22T00:00:00+00:00",
        )
    )
    project_root = workspace_root / "filtered_layer_prep"

    manifest = run_layer_preparation(
        LayerPreparationRequest(
            project_id="filtered_layer_prep",
            project_root=project_root,
            layers=(
                "route",
                "segments",
                "checkpoints",
                "reference-tracks",
                "route-notes",
            ),
            route_evidence_bundle=Path("normalized/routes/route_evidence_bundle.json"),
            prepared_at="2026-05-22T00:05:00+00:00",
        )
    )
    project = _load(project_root / "project.json")
    route_bundle = _load(project_root / "normalized" / "routes" / "route_evidence_bundle.json")

    assert manifest["inputs"]["gpx_speed_filter"]["applied"] is True
    assert manifest["inputs"]["route_evidence_bundle"]["available"] is True
    assert manifest["inputs"]["route_evidence_bundle"]["source_ref"] == (
        "normalized/routes/route_evidence_bundle.json"
    )
    assert manifest["route_corridor"]["route_evidence_bundle_ref"] == (
        "normalized/routes/route_evidence_bundle.json"
    )
    assert manifest["route_corridor"]["corridor_policy"] == (
        "bbox_fetch_then_along_track_filter"
    )
    assert manifest["route_corridor"]["reference_track_corridor_m"] == 300.0
    assert manifest["bbox_wgs84"] == {
        "south": route_bundle["route_scope_for_map_preparation"]["bbox_wgs84"][1],
        "west": route_bundle["route_scope_for_map_preparation"]["bbox_wgs84"][0],
        "north": route_bundle["route_scope_for_map_preparation"]["bbox_wgs84"][3],
        "east": route_bundle["route_scope_for_map_preparation"]["bbox_wgs84"][2],
    }
    assert not any(
        warning["layer_id"] == "route_evidence_bundle"
        for warning in manifest["validation"]["warnings"]
    )
    assert manifest["inputs"]["gpx_speed_filter"]["removed_track_point_count"] == 1
    assert manifest["route_corridor"]["gpx_speed_filter"]["applied"] is True
    gpx_filter_layers = {
        layer["layer_id"]: layer
        for layer in manifest["layers"]
        if layer["layer_id"] in {"route", "segments", "checkpoints", "reference-tracks"}
    }
    for layer in gpx_filter_layers.values():
        assert layer["gpx_speed_filter"]["applied"] is True
        assert layer["counts"]["gpx_filter_removed_track_point_count"] == 1
        assert any(
            ref.get("project_ref_key") == "gpx_speed_filter_report_ref"
            for ref in layer["source_refs"]
        )
        assert layer["lifecycle"]["import"]["source_ref_count"] == len(
            layer["source_refs"]
        )
        assert layer["lifecycle"]["summarize"]["counts"] == layer["counts"]
    route_notes_layer = next(
        layer for layer in manifest["layers"] if layer["layer_id"] == "route-notes"
    )
    assert [
        ref.get("project_ref_key") for ref in route_notes_layer["source_refs"]
    ] == [
        "normalized_route_note_candidates_ref",
        "route_note_candidates_ref",
    ]
    assert route_notes_layer["source_refs"][0]["ref"] == (
        "normalized/notes/gpx_route_note_candidates.json"
    )
    assert route_notes_layer["lifecycle"]["import"]["source_ref_count"] == len(
        route_notes_layer["source_refs"]
    )
    assert (project_root / project["layer_preparation_summary_ref"]).is_file()
    assert project["map_preparation_summary_ref"] == (
        "outputs/layers/map_preparation_summary.json"
    )
    assert (project_root / project["map_preparation_summary_ref"]).is_file()
    assert (project_root / project["layer_adapter_manifest_ref"]).is_file()
    assert (project_root / project["layer_validation_report_ref"]).is_file()
    expected_map_prep_refs = {
        "web_case_query_plan_ref": "outputs/layers/plans/web_case_query_plan.json",
        "raster_label_plan_ref": "outputs/layers/plans/raster_label_plan.json",
        "overpass_vector_evidence_ref": (
            "outputs/layers/normalized/overpass_vector_evidence.geojson"
        ),
        "terrain_route_samples_ref": (
            "outputs/layers/normalized/terrain_route_samples.geojson"
        ),
        "terrain_visualization_ref": (
            "outputs/layers/normalized/terrain_visualization.geojson"
        ),
        "web_case_evidence_ref": "outputs/layers/normalized/web_case_evidence.json",
        "raster_label_evidence_ref": (
            "outputs/layers/normalized/raster_label_evidence.geojson"
        ),
    }
    for key, ref in expected_map_prep_refs.items():
        assert project[key] == ref
        assert (project_root / ref).is_file()
    map_preparation_summary = _load(project_root / project["map_preparation_summary_ref"])
    web_case_plan = _load(project_root / project["web_case_query_plan_ref"])
    raster_label_plan = _load(project_root / project["raster_label_plan_ref"])
    overpass_vector_evidence = _load(project_root / project["overpass_vector_evidence_ref"])
    terrain_route_samples = _load(project_root / project["terrain_route_samples_ref"])
    terrain_visualization = _load(project_root / project["terrain_visualization_ref"])
    web_case_evidence = _load(project_root / project["web_case_evidence_ref"])
    raster_label_evidence = _load(project_root / project["raster_label_evidence_ref"])
    assert map_preparation_summary["artifact_kind"] == (
        "pretrip_route_corridor_map_preparation_summary"
    )
    assert map_preparation_summary["schema_version"] == (
        "route_corridor_map_preparation.v1"
    )
    assert map_preparation_summary["route_scope_ref"] == (
        "normalized/routes/route_evidence_bundle.json"
    )
    assert map_preparation_summary["boundary"]["candidate_only"] is True
    assert map_preparation_summary["boundary"]["runtime_safety_truth"] is False
    assert web_case_plan["artifact_kind"] == "pretrip_web_case_query_plan"
    assert web_case_plan["status"] == "planned_no_network"
    assert web_case_plan["boundary"]["network_calls_allowed"] is False
    assert raster_label_plan["artifact_kind"] == "pretrip_raster_label_plan"
    assert raster_label_plan["status"] == "planned_for_map_preparation_ocr"
    assert raster_label_plan["ocr_or_vision_performed"] is False
    assert raster_label_plan["imagery_processing_enabled"] is True
    assert raster_label_plan["ocr_engine"]["entrypoint"] == "pretrip_raster_label_ocr.py"
    assert raster_label_plan["ocr_engine"]["preferred_engine"] == "tesseract"
    assert raster_label_plan["ocr_engine"]["output_ref"] == (
        "outputs/layers/raster_label_ocr_output.json"
    )
    assert raster_label_plan["ocr_engine"]["adapter_entrypoint"] == (
        "pretrip_raster_label_adapter.py"
    )
    assert raster_label_plan["ocr_engine"]["raw_tiles_embedded_in_output"] is False
    assert raster_label_plan["ocr_engine"]["runtime_safety_truth"] is False
    assert (
        raster_label_plan["execution_policy"]["ocr_requires_explicit_adapter_run"]
        is False
    )
    assert (
        raster_label_plan["execution_policy"]["ocr_runs_as_map_preparation_stage"]
        is True
    )
    assert (
        raster_label_plan["execution_policy"]["ocr_engine_output_must_feed_adapter"]
        is True
    )
    assert raster_label_plan["preferred_ocr_source_ids"] == [
        "happyman_rudy_twmap",
        "happyman_rudy",
    ]
    assert raster_label_plan["label_extraction_targets"] == [
        "trail_mileage_k_anchor",
        "road_mileage_stone",
        "trail_name_label",
        "named_place_label",
        "cellular_communication_point",
        "trail_annotation_label",
        "contour_elevation_label",
        "hazard_annotation_label",
    ]
    grouping_policy = raster_label_plan["mileage_anchor_grouping_policy"]
    assert grouping_policy["standalone_mileage_anchor_allowed"] is False
    assert grouping_policy["ambiguous_anchor_review_required"] is True
    assert grouping_policy["same_tile_bbox_grouping_px"] == 256
    assert grouping_policy["route_distance_grouping_window_m"] == 300.0
    assert grouping_policy["required_context_any"] == [
        "trail_name_label",
        "route_family_from_workspace",
        "named_place_label",
        "route_centerline_projection",
    ]
    assert grouping_policy["duplicate_resolution_key"] == [
        "route_context_key",
        "normalized_mileage_k",
    ]
    assert raster_label_plan["ocr_candidate_source_count"] == 2
    ocr_sources = {
        source["source_id"]: source
        for source in raster_label_plan["ocr_candidate_sources"]
    }
    assert set(ocr_sources) == {"happyman_rudy_twmap", "happyman_rudy"}
    assert ocr_sources["happyman_rudy_twmap"]["ocr_capable"] is True
    assert ocr_sources["happyman_rudy_twmap"]["raw_url_template_embedded"] is False
    assert ocr_sources["happyman_rudy_twmap"]["wmts_layer"] == "rudy_twmap"
    assert "trail_mileage_k_anchor" in ocr_sources["happyman_rudy_twmap"][
        "label_extraction_roles"
    ]
    assert "road_mileage_stone" in ocr_sources["happyman_rudy_twmap"][
        "label_extraction_roles"
    ]
    assert "cellular_communication_point" in ocr_sources["happyman_rudy_twmap"][
        "label_extraction_roles"
    ]
    assert "trail_name_label" in ocr_sources["happyman_rudy_twmap"][
        "label_extraction_roles"
    ]
    for artifact in (
        overpass_vector_evidence,
        terrain_route_samples,
        terrain_visualization,
        raster_label_evidence,
    ):
        assert artifact["type"] == "FeatureCollection"
        assert artifact["schema_version"] == "route_corridor_map_preparation.v1"
        assert artifact["features"] == []
        assert artifact["boundary"]["candidate_only"] is True
        assert artifact["boundary"]["runtime_safety_truth"] is False
        assert artifact["boundary"]["raw_gpx_embedded_in_json"] is False
    assert overpass_vector_evidence["status"] == "not_requested"
    assert overpass_vector_evidence["network_policy"]["network_calls_made"] is False
    assert terrain_visualization["artifact_kind"] == "pretrip_terrain_visualization"
    assert terrain_visualization["visualization_spec"]["modes"] == [
        "hillshade",
        "elevation_tint",
        "slope_shading",
        "contours",
    ]
    assert terrain_visualization["visualization_spec"]["raw_dem_embedded_in_json"] is False
    assert terrain_visualization["visualization_spec"]["risk_heat_layer"] is False
    assert web_case_evidence["artifact_kind"] == "pretrip_web_case_evidence"
    assert web_case_evidence["evidence_items"] == []
    assert web_case_evidence["boundary"]["large_scraped_text_embedded"] is False
    assert project["gis_semantic_input_bundle_ref"] == (
        "outputs/layers/semantic/gis_semantic_input_bundle.json"
    )
    assert project["gis_perception_ai_judgements_ref"] == (
        "outputs/layers/semantic/gis_perception_ai_judgements.json"
    )
    semantic_input = _load(project_root / project["gis_semantic_input_bundle_ref"])
    semantic_judgements = _load(
        project_root / project["gis_perception_ai_judgements_ref"]
    )
    for ref_key in (
        "gis_checkpoint_candidates_ref",
        "ln_proposals_ref",
        "poi_candidates_ref",
        "terrain_risk_candidates_ref",
        "detour_route_candidates_ref",
    ):
        assert (project_root / project[ref_key]).is_file()
    assert semantic_input["artifact_kind"] == "pretrip_gis_semantic_input_bundle"
    assert semantic_input["schema_version"] == "route_corridor_map_preparation.v1"
    assert semantic_input["route_scope_ref"] == (
        "normalized/routes/route_evidence_bundle.json"
    )
    assert semantic_input["counts"]["evidence_item_count"] == 0
    assert semantic_input["boundary"]["candidate_only"] is True
    assert semantic_input["boundary"]["runtime_safety_truth"] is False
    assert semantic_input["boundary"]["raw_gpx_embedded_in_json"] is False
    assert all(item["source_refs"] for item in semantic_input["evidence_items"])
    assert semantic_judgements["artifact_kind"] == "gis_perception_ai_judgements"
    assert semantic_judgements["schema_version"] == "gis_perception_ai_judgements.v1"
    assert semantic_judgements["input_bundle_ref"] == project["gis_semantic_input_bundle_ref"]
    assert semantic_judgements["judgement_count"] == 0
    assert semantic_judgements["live_model_call_performed"] is False
    assert semantic_judgements["network_calls_allowed"] is False
    assert semantic_judgements["boundary"]["candidate_only"] is True
    assert semantic_judgements["boundary"]["runtime_safety_truth"] is False
    assert (project_root / project["layer_map_projection_ref"]).is_file()
    assert (project_root / project["layer_debug_projection_events_ref"]).is_file()
    assert "<trkpt" not in (project_root / project["layer_preparation_manifest_ref"]).read_text(
        encoding="utf-8"
    ).lower()


def test_layer_preparation_writes_route_note_semantic_input_bundle(
    tmp_path: Path,
) -> None:
    project_root = _copy_fixture_project(tmp_path)
    project = _load(project_root / "project.json")
    rest_area_ref = "outputs/rest_area_candidates.json"
    project["rest_area_candidates_ref"] = rest_area_ref
    project["rest_area_candidate_count"] = 1
    (project_root / "project.json").write_text(
        json.dumps(project, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (project_root / rest_area_ref).write_text(
        json.dumps(
            {
                "artifact_kind": "pretrip_rest_area_candidates",
                "schema_version": "0.1.0",
                "candidates": [
                    {
                        "candidate_id": "rest_area.fixture.001",
                        "checkpoint_type": "rest_area",
                        "label": "Rest area / camp area 001",
                        "lat": 24.0,
                        "lon": 121.2,
                        "duration_seconds": 2400,
                        "mean_speed_m_per_min": 0.4,
                        "source_point_count": 24,
                        "source_refs": ["artifact.gpx.fixture"],
                        "confidence": "medium",
                        "stale_risk": "medium",
                        "review_state": "needs_review",
                    }
                ],
                "boundary": {
                    "candidate_evidence_only": True,
                    "runtime_safety_truth": False,
                },
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    run_layer_preparation(
        LayerPreparationRequest(
            project_id="chilai_nanhua_day1",
            project_root=project_root,
            layers=("route-notes",),
            route_evidence_bundle=Path("normalized/routes/route_evidence_bundle.json"),
            prepared_at="2026-05-22T00:05:00+00:00",
        )
    )
    project = _load(project_root / "project.json")
    semantic_input = _load(project_root / project["gis_semantic_input_bundle_ref"])
    semantic_judgements = _load(
        project_root / project["gis_perception_ai_judgements_ref"]
    )
    checkpoint_candidates = _load(project_root / project["gis_checkpoint_candidates_ref"])
    ln_proposals = _load(project_root / project["ln_proposals_ref"])
    poi_candidates = _load(project_root / project["poi_candidates_ref"])
    terrain_risk_candidates = _load(project_root / project["terrain_risk_candidates_ref"])
    detour_candidates = _load(project_root / project["detour_route_candidates_ref"])

    assert semantic_input["artifact_kind"] == "pretrip_gis_semantic_input_bundle"
    assert semantic_input["schema_version"] == "route_corridor_map_preparation.v1"
    assert semantic_input["route_scope_ref"] == (
        "normalized/routes/route_evidence_bundle.json"
    )
    assert semantic_input["counts"]["source_kind_counts"]["gpx_route_note"] > 0
    assert semantic_input["counts"]["source_kind_counts"]["rest_area_candidate"] == 1
    assert semantic_input["evidence_items"][0]["source_kind"] == "gpx_route_note"
    rest_item = next(
        item
        for item in semantic_input["evidence_items"]
        if item["source_kind"] == "rest_area_candidate"
    )
    assert rest_item["candidate_type"] == "rest_area"
    assert rest_item["source_refs"] == ["outputs/rest_area_candidates.json#rest_area.fixture.001"]
    assert rest_item["rest_area_metrics"]["mean_speed_m_per_min"] == 0.4
    assert semantic_input["evidence_items"][0]["source_refs"]
    assert semantic_input["boundary"]["candidate_only"] is True
    assert semantic_input["boundary"]["runtime_safety_truth"] is False
    assert semantic_judgements["artifact_kind"] == "gis_perception_ai_judgements"
    assert semantic_judgements["schema_version"] == "gis_perception_ai_judgements.v1"
    assert semantic_judgements["input_bundle_ref"] == (
        "outputs/layers/semantic/gis_semantic_input_bundle.json"
    )
    assert semantic_judgements["input_bundle_sha256"]
    assert semantic_judgements["prompt_version"] == "gis_semantic_classifier.v1"
    assert semantic_judgements["prompt_hash"] == semantic_judgements["prompt_sha256"]
    assert semantic_judgements["judgement_count"] == (
        semantic_input["counts"]["evidence_item_count"]
    )
    assert semantic_judgements["live_model_call_performed"] is False
    assert semantic_judgements["network_calls_allowed"] is False
    assert semantic_judgements["raw_model_output_embedded"] is False
    assert semantic_judgements["boundary"]["candidate_only"] is True
    assert semantic_judgements["boundary"]["observed_fact"] is False
    assert semantic_judgements["boundary"]["runtime_safety_truth"] is False
    assert semantic_judgements["boundary"]["phase1_runtime_mutation_allowed"] is False
    assert semantic_judgements["judgements"][0]["source_evidence_refs"]
    rest_judgement = next(
        judgement
        for judgement in semantic_judgements["judgements"]
        if judgement["source_candidate_id"] == "rest_area.fixture.001"
    )
    assert rest_judgement["proposed_semantic_key"] == "water_or_camp_hint"
    assert rest_judgement["proposed_ln_level"] == "L2_candidate"
    assert rest_judgement["checkpoint_type"] == "water_or_camp_review"
    assert rest_judgement["cp_needed"] is True
    assert semantic_judgements["judgements"][0]["requires_human_review"] is True
    assert semantic_judgements["judgements"][0]["runtime_safety_truth"] is False
    assert checkpoint_candidates["artifact_kind"] == "pretrip_layer_gis_checkpoint_candidates"
    assert checkpoint_candidates["schema_version"] == (
        "route_corridor_map_preparation.candidates.v1"
    )
    assert checkpoint_candidates["counts"]["candidate_count"] > 0
    assert checkpoint_candidates["counts"]["candidate_only_count"] == (
        checkpoint_candidates["counts"]["candidate_count"]
    )
    assert checkpoint_candidates["counts"]["runtime_safety_truth_count"] == 0
    assert checkpoint_candidates["candidates"][0]["source_judgement_id"]
    assert checkpoint_candidates["candidates"][0]["requires_human_review"] is True
    assert ln_proposals["artifact_kind"] == "pretrip_layer_ln_proposals"
    assert ln_proposals["counts"]["candidate_count"] > 0
    assert poi_candidates["artifact_kind"] == "pretrip_layer_poi_candidates"
    assert terrain_risk_candidates["artifact_kind"] == "pretrip_layer_terrain_risk_candidates"
    assert detour_candidates["artifact_kind"] == "pretrip_layer_detour_route_candidates"
    serialized = json.dumps(semantic_input, ensure_ascii=False).lower()
    serialized_judgements = json.dumps(semantic_judgements, ensure_ascii=False).lower()
    assert "<gpx" not in serialized
    assert "<trkpt" not in serialized
    assert "<gpx" not in serialized_judgements
    assert "<trkpt" not in serialized_judgements


def test_layer_preparation_syncs_scout_risk_score_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _copy_fixture_project(tmp_path)
    project = _load(project_root / "project.json")
    gis_ref = "candidates/gis_perception.json"
    project["gis_perception_candidates_ref"] = gis_ref
    (project_root / "project.json").write_text(
        json.dumps(project, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (project_root / gis_ref).write_text(
        json.dumps(
            {
                "checkpoint_candidates": [
                    {
                        "candidate_id": "semantic.warning.high-risk",
                        "checkpoint_type": "warning_review",
                        "route_note_summary": "危險崩壁 route note",
                        "lat": 24.0,
                        "lon": 121.2,
                        "candidate_only": True,
                    },
                    {
                        "candidate_id": "semantic.context.low-risk",
                        "checkpoint_type": "landmark_review",
                        "route_note_summary": "context landmark",
                        "lat": 24.02,
                        "lon": 121.22,
                        "candidate_only": True,
                    },
                ]
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    risk_source = tmp_path / "risk_out"
    _write_risk_score_outputs(risk_source)
    monkeypatch.setattr(
        pretrip_layer_preparation,
        "SCOUT_RISK_OUTPUT_SOURCES",
        {"chilai_nanhua_day1": risk_source},
    )

    manifest = run_layer_preparation(
        LayerPreparationRequest(
            project_id="chilai_nanhua_day1",
            project_root=project_root,
            layers=("risk-score", "risk-ribbon", "risk-heatmap", "risk-delta"),
            prepared_at="2026-05-22T00:00:00+00:00",
        )
    )
    project = _load(project_root / "project.json")
    layers = {layer["layer_id"]: layer for layer in manifest["layers"]}
    layer = layers["risk-score"]
    ribbon_layer = layers["risk-ribbon"]
    heatmap_layer = layers["risk-heatmap"]
    delta_layer = layers["risk-delta"]

    assert layer["layer_id"] == "risk-score"
    assert layer["status"] == "ready_from_project_ref"
    assert layer["counts"]["point_count"] == 2
    assert layer["counts"]["score_field"] == "pretrip_risk"
    assert ribbon_layer["status"] == "ready_from_project_ref"
    assert ribbon_layer["counts"]["segment_count"] == 1
    assert ribbon_layer["counts"]["score_surface_type"] == "route_aligned_risk_ribbon"
    assert heatmap_layer["status"] == "ready_from_project_ref"
    assert heatmap_layer["counts"]["segment_count"] == 2
    assert heatmap_layer["counts"]["score_surface_type"] == "route_aligned_calibrated_heatmap"
    assert delta_layer["status"] == "ready_from_project_ref"
    assert delta_layer["counts"]["baseline_segment_count"] == 1
    assert delta_layer["counts"]["calibrated_segment_count"] == 2
    assert project["risk_score_points_ref"] == "outputs/risk/risk_score_points.geojson"
    assert project["risk_ribbon_ref"] == "outputs/risk/risk_ribbon.geojson"
    assert project["calibrated_risk_heatmap_ref"] == "outputs/risk/calibrated_risk_heatmap.geojson"
    assert project["risk_attribution_diagnostic_ref"] == "outputs/risk/risk_attribution_diagnostic.json"
    assert project["boss_points_ref"] == "outputs/boss_points.json"
    assert project["boss_points_geojson_ref"] == "outputs/boss_points.geojson"
    assert project["route_pressure_profile_ref"] == "outputs/route_pressure_profile.json"
    assert project["route_pressure_profile_geojson_ref"] == (
        "outputs/route_pressure_profile.geojson"
    )
    assert project["mileage_tag_alignment_ref"] == "outputs/mileage_tag_alignment.json"
    assert project["mileage_tag_alignment_geojson_ref"] == (
        "outputs/mileage_tag_alignment.geojson"
    )
    assert project["risk_score_point_count"] == 2
    assert project["risk_route_sample_count"] == 3
    assert project["risk_ribbon_segment_count"] == 1
    assert project["boss_point_count"] >= 0
    assert project["calibrated_risk_heatmap_segment_count"] == 2
    assert (project_root / project["risk_score_points_ref"]).is_file()
    assert (project_root / project["risk_ribbon_ref"]).is_file()
    assert (project_root / project["risk_route_profile_ref"]).is_file()
    assert (project_root / project["calibrated_risk_heatmap_ref"]).is_file()
    assert (project_root / project["calibrated_risk_heatmap_metadata_ref"]).is_file()
    assert (project_root / project["boss_points_ref"]).is_file()
    assert (project_root / project["boss_points_geojson_ref"]).is_file()
    assert (project_root / project["route_pressure_profile_ref"]).is_file()
    assert (project_root / project["mileage_tag_alignment_ref"]).is_file()
    assert (project_root / project["mileage_tag_alignment_geojson_ref"]).is_file()
    boss_synthesis = manifest["boss_point_synthesis"]
    assert boss_synthesis["status"] == "completed"
    assert boss_synthesis["trigger"] == "prepare_layers_with_risk"
    assert boss_synthesis["boundary"]["runtime_safety_truth"] is False
    assert boss_synthesis["boundary"]["phase1_runtime_mutation_allowed"] is False
    mileage_alignment = manifest["mileage_tag_alignment"]
    assert mileage_alignment["status"] == "completed"
    assert mileage_alignment["tag_count"] > 0
    assert mileage_alignment["aligned_tag_count"] > 0
    assert mileage_alignment["boundary"]["runtime_safety_truth"] is False
    boss_points = _load(project_root / project["boss_points_ref"])
    assert boss_points["boundary"]["runtime_safety_truth"] is False
    assert boss_points["boundary"]["phase1_runtime_mutation_allowed"] is False
    mileage_tags = _load(project_root / project["mileage_tag_alignment_ref"])
    assert mileage_tags["boundary"]["runtime_safety_truth"] is False
    assert mileage_tags["counts"]["source_kind_counts"]["checkpoint"] == 124
    assert mileage_tags["counts"]["source_kind_counts"]["segment"] == 123
    route_pressure = _load(project_root / project["route_pressure_profile_ref"])
    assert route_pressure["boundary"]["candidate_only"] is True
    assert route_pressure["boundary"]["runtime_safety_truth"] is False
    terrain_samples = _load(project_root / project["terrain_route_samples_ref"])
    assert terrain_samples["artifact_kind"] == "pretrip_terrain_route_samples"
    assert terrain_samples["status"] == "ready_from_risk_route_profile"
    assert terrain_samples["counts"]["feature_count"] == 3
    assert terrain_samples["features"][0]["properties"]["evidence_type"] == (
        "pretrip_terrain_route_sample"
    )
    assert terrain_samples["features"][0]["properties"]["source_risk_ref"] == (
        project["risk_route_profile_ref"]
    )
    assert terrain_samples["features"][0]["properties"]["runtime_safety_truth"] is False
    terrain_visualization = _load(project_root / project["terrain_visualization_ref"])
    assert terrain_visualization["artifact_kind"] == "pretrip_terrain_visualization"
    assert terrain_visualization["status"] == "ready_from_dtm_20m_corridor_bitmap"
    assert terrain_visualization["visualization_spec"]["modes"] == [
        "hillshade",
        "elevation_tint",
        "slope_shading",
        "contours",
    ]
    assert terrain_visualization["visualization_spec"]["route_aligned_proxy"] is False
    assert terrain_visualization["visualization_spec"]["bitmap_overlay"] is True
    assert terrain_visualization["visualization_spec"]["preferred_processor"] == "gdal"
    assert terrain_visualization["visualization_spec"]["actual_processor"] == (
        "python_dtm_bitmap_fallback"
    )
    assert terrain_visualization["visualization_spec"]["bitmap_cell_resolution_m"] == 20.0
    assert terrain_visualization["visualization_spec"]["corridor_half_width_m"] == 500.0
    assert terrain_visualization["visualization_spec"]["risk_heat_layer"] is False
    assert terrain_visualization["visualization_spec"]["raw_dem_embedded_in_json"] is False
    assert terrain_visualization["counts"]["feature_count"] == 0
    assert terrain_visualization["counts"]["cell_count"] > 0
    assert terrain_visualization["counts"]["bitmap_overlay_count"] == 4
    assert terrain_visualization["counts"]["runtime_safety_truth_count"] == 0
    assert terrain_visualization["features"] == []
    overlays = {overlay["mode"]: overlay for overlay in terrain_visualization["raster_overlays"]}
    assert set(overlays) == {"hillshade", "elevation_tint", "slope_shading", "contours"}
    assert overlays["slope_shading"]["cell_resolution_m"] == 20.0
    assert overlays["slope_shading"]["corridor_half_width_m"] == 500.0
    assert overlays["slope_shading"]["runtime_href"] == (
        "/admin/pretrip/projects/chilai_nanhua_day1"
        "/terrain-overlays/slope_shading.png"
    )
    assert overlays["slope_shading"]["runtime_safety_truth"] is False
    assert (project_root / overlays["slope_shading"]["source_path"]).is_file()
    _assert_risk_features_have_pretrip_provenance(
        project_root / project["risk_route_profile_ref"],
        expected_evidence_type="pretrip_route_risk_sample",
    )
    _assert_risk_features_have_pretrip_provenance(
        project_root / project["risk_score_points_ref"],
        expected_evidence_type="pretrip_risk_score_point",
    )
    _assert_risk_features_have_pretrip_provenance(
        project_root / project["risk_ribbon_ref"],
        expected_evidence_type="pretrip_risk_ribbon_segment",
    )
    _assert_risk_features_have_pretrip_provenance(
        project_root / project["calibrated_risk_heatmap_ref"],
        expected_evidence_type="pretrip_calibrated_risk_heatmap_segment",
    )
    assert manifest["boundary"]["runtime_safety_truth"] is False
    assert manifest["boundary"]["phase1_runtime_mutation_allowed"] is False


def test_layer_preparation_generates_workspace_risk_before_terrain_bitmap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("numpy")
    project_root = _write_minimal_overpass_dtm_workspace(tmp_path)
    project_path = project_root / "project.json"
    project = _load(project_path)
    project["risk_score_generation_status"] = "failed"
    project["risk_score_generation_error"] = "No module named 'numpy'"
    _write_json(project_path, project)
    monkeypatch.setattr(pretrip_layer_preparation, "SCOUT_RISK_OUTPUT_SOURCES", {})

    manifest = run_layer_preparation(
        LayerPreparationRequest(
            project_id="chilai_nanhua_day1",
            project_root=project_root,
            layers=("risk-score", "risk-ribbon", "terrain"),
            prepared_at="2026-05-22T00:00:00+00:00",
        )
    )

    project = _load(project_root / "project.json")
    assert project["risk_score_generation_status"] == "completed"
    assert "risk_score_generation_error" not in project
    assert project["risk_score_source_profile"] == (
        "scout_risk_engine_workspace_generated_overpass_route_profile"
    )
    assert (project_root / project["risk_route_profile_ref"]).is_file()
    assert (project_root / project["risk_score_points_ref"]).is_file()
    assert (project_root / project["risk_ribbon_ref"]).is_file()

    layers = {layer["layer_id"]: layer for layer in manifest["layers"]}
    assert layers["risk-score"]["status"] == "ready_from_project_ref"
    assert layers["terrain"]["status"] == "ready_from_project_ref"
    terrain_visualization = _load(project_root / project["terrain_visualization_ref"])
    assert terrain_visualization["status"] == "ready_from_dtm_20m_corridor_bitmap"
    assert terrain_visualization["counts"]["bitmap_overlay_count"] == 4
    assert terrain_visualization["counts"]["source_dtm_tile_count"] == 1
    assert terrain_visualization["counts"]["cell_count"] > 0
    assert terrain_visualization["dtm_grid"]["source_tile_count"] == 1
    assert terrain_visualization["boundary"]["runtime_safety_truth"] is False


def test_layer_preparation_terrain_can_fallback_to_risk_ribbon_lines(
    tmp_path: Path,
) -> None:
    project_root = _copy_fixture_project(tmp_path)
    project_path = project_root / "project.json"
    project = _load(project_path)
    risk_root = project_root / "outputs" / "risk"
    _write_risk_score_outputs(risk_root)
    project.update(
        {
            "risk_ribbon_ref": "outputs/risk/risk_ribbon.geojson",
            "risk_ribbon_metadata_ref": "outputs/risk/risk_ribbon.metadata.json",
        }
    )
    for key in (
        "risk_route_profile_ref",
        "risk_route_profile_metadata_ref",
        "risk_score_points_ref",
        "risk_score_points_metadata_ref",
    ):
        project.pop(key, None)
    project_path.write_text(
        json.dumps(project, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    manifest = run_layer_preparation(
        LayerPreparationRequest(
            project_id="chilai_nanhua_day1",
            project_root=project_root,
            layers=("terrain",),
            prepared_at="2026-05-22T00:00:00+00:00",
        )
    )
    updated_project = _load(project_path)
    terrain_samples = _load(project_root / updated_project["terrain_route_samples_ref"])
    terrain_visualization = _load(
        project_root / updated_project["terrain_visualization_ref"]
    )

    assert manifest["boundary"]["runtime_safety_truth"] is False
    assert terrain_samples["status"] == "ready_from_risk_ribbon"
    assert terrain_samples["counts"]["feature_count"] == 2
    assert terrain_samples["features"][0]["geometry"]["type"] == "Point"
    assert terrain_samples["features"][0]["properties"]["source_risk_ref_key"] == (
        "risk_ribbon_ref"
    )
    assert terrain_samples["features"][0]["properties"]["source_risk_ref"] == (
        "outputs/risk/risk_ribbon.geojson"
    )
    assert terrain_samples["features"][0]["properties"]["runtime_safety_truth"] is False
    assert terrain_visualization["status"] == "ready_from_dtm_20m_corridor_bitmap"
    assert terrain_visualization["counts"]["bitmap_overlay_count"] == 4
    assert terrain_visualization["visualization_spec"]["bitmap_cell_resolution_m"] == 20.0
    assert terrain_visualization["visualization_spec"]["corridor_half_width_m"] == 500.0
    overlays = {overlay["mode"]: overlay for overlay in terrain_visualization["raster_overlays"]}
    assert overlays["hillshade"]["runtime_href"] == (
        "/admin/pretrip/projects/chilai_nanhua_day1"
        "/terrain-overlays/hillshade.png"
    )
    assert (project_root / overlays["hillshade"]["source_path"]).is_file()


def test_layer_preparation_explicit_fetch_normalizes_overpass_with_fixture_fetcher(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _copy_fixture_project(tmp_path)
    project_path = project_root / "project.json"
    project = _load(project_path)
    for key in (
        "overpass_evidence_ref",
        "overpass_map_context_ref",
        "overpass_raw_payload_ref",
        "overpass_candidate_count",
        "overpass_skipped_object_count",
    ):
        project.pop(key, None)
    project_path.write_text(
        json.dumps(project, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    raw_fixture = ROOT / "tests" / "fixtures" / "maps" / "phase_a_overpass_raw.json"
    captured: dict[str, str] = {}

    def fixture_fetcher(planned_request: dict) -> tuple[bytes, int]:
        captured["query_body"] = planned_request["query_body"]
        captured["endpoint"] = planned_request["endpoint"]
        return raw_fixture.read_bytes(), 200

    monkeypatch.setattr(
        pretrip_layer_preparation,
        "_fetch_overpass_raw_payload",
        fixture_fetcher,
    )

    manifest = run_layer_preparation(
        LayerPreparationRequest(
            project_id="chilai_nanhua_day1",
            project_root=project_root,
            layers=("overpass",),
            network_mode="explicit-fetch",
            allow_network_fetch=True,
            route_corridor_m=1_000.0,
            prepared_at="2026-05-22T00:00:00+00:00",
        )
    )
    updated_project = _load(project_path)
    overpass = manifest["layers"][0]
    evidence = _load(project_root / updated_project["overpass_evidence_ref"])

    assert captured["endpoint"] == "https://overpass-api.de/api/interpreter"
    assert "way[\"highway\"" in captured["query_body"]
    assert overpass["status"] == "ready_from_project_ref"
    assert overpass["lifecycle"]["fetch"]["status"] == "completed_live_fetch"
    assert overpass["lifecycle"]["fetch"]["external_network_calls_made"] is True
    assert manifest["network_policy"]["network_calls_made"] is True
    assert manifest["boundary"]["external_api_calls_made"] is True
    assert evidence["counts"]["candidates"] == 8
    for candidate in evidence["candidates"]:
        assert candidate["source_refs"]
        assert candidate["source_attribution"]
        assert candidate["extractor_version"] == "overpass-vector-evidence.v1"
        assert candidate["pydantic_ai_prompt_version"] == (
            "not_applicable_deterministic_overpass_ingest"
        )
        assert candidate["model_output_sha256"]
        assert candidate["model_output_summary"]
        assert candidate["review_state"] == "needs_review"
        assert candidate["candidate_only"] is True
        assert candidate["runtime_safety_truth"] is False
    assert evidence["request"]["route_corridor"]["route_ref"] == (
        "artifact.gpx.chilai_nanhua_day1"
    )
    assert (project_root / updated_project["overpass_raw_payload_ref"]).is_file()
    assert (project_root / updated_project["overpass_map_context_ref"]).is_file()
    assert (project_root / "outputs" / "layers" / "plans" / "overpass_query.ql").is_file()
    assert "<trkpt" not in json.dumps(evidence, ensure_ascii=False).lower()


def test_layer_preparation_blocks_explicit_fetch_without_network_flag(
    tmp_path: Path,
) -> None:
    project_root = _copy_fixture_project(tmp_path)

    preview = build_layer_preparation_preview(
        LayerPreparationRequest(
            project_id="chilai_nanhua_day1",
            project_root=project_root,
            layers=("osm",),
            network_mode="explicit-fetch",
            allow_network_fetch=False,
            prepared_at="2026-05-22T00:00:00+00:00",
        )
    )

    assert preview["validation"]["status"] == "blocked"
    assert preview["validation"]["blocker_count"] == 1
    assert preview["network_policy"]["network_calls_made"] is False
    assert preview["boundary"]["network_calls_allowed"] is False


def test_layer_preparation_rejects_unknown_layer_id(tmp_path: Path) -> None:
    project_root = _copy_fixture_project(tmp_path)

    with pytest.raises(ValueError, match="unsupported layer id"):
        build_layer_preparation_preview(
            LayerPreparationRequest(
                project_id="chilai_nanhua_day1",
                project_root=project_root,
                layers=("osm", "mystery-layer"),
            )
        )


def test_layer_preparation_cli_writes_manifest(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspaces"
    project_root = _copy_fixture_project(tmp_path, workspace_root=workspace_root)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pretrip_layer_preparation",
            "--project-id",
            "chilai_nanhua_day1",
            "--workspace-root",
            str(workspace_root),
            "--layers",
            "osm,dtm,reference-tracks",
            "--prepared-at",
            "2026-05-22T00:00:00+00:00",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    manifest = json.loads(result.stdout)
    project = _load(project_root / "project.json")

    assert manifest["artifact_kind"] == "pretrip_layer_preparation_manifest"
    assert manifest["normalized_layers"] == ["osm", "terrain", "reference-tracks"]
    assert project["layer_preparation_manifest_ref"] == (
        "outputs/layers/layer_preparation_manifest.json"
    )
    assert (project_root / project["layer_debug_projection_events_ref"]).is_file()


def _copy_fixture_project(
    tmp_path: Path,
    *,
    workspace_root: Path | None = None,
) -> Path:
    workspace = workspace_root or (tmp_path / "workspaces")
    project_root = workspace / "chilai_nanhua_day1"
    shutil.copytree(FIXTURE_PROJECT_ROOT, project_root)
    return project_root


def _write_minimal_overpass_dtm_workspace(tmp_path: Path) -> Path:
    project_root = tmp_path / "workspaces" / "chilai_nanhua_day1"
    (project_root / "normalized" / "routes").mkdir(parents=True)
    (project_root / "normalized" / "map").mkdir(parents=True)
    (project_root / "normalized" / "terrain").mkdir(parents=True)
    (project_root / "source_inbox").mkdir(parents=True)

    route_points = [
        (23.9500, 121.0500, 1200.0, "2026-05-22T00:00:00Z"),
        (23.9510, 121.0510, 1210.0, "2026-05-22T00:10:00Z"),
        (23.9520, 121.0520, 1220.0, "2026-05-22T00:20:00Z"),
        (23.9530, 121.0530, 1230.0, "2026-05-22T00:30:00Z"),
    ]
    gpx_path = _write_gpx(
        project_root / "source_inbox" / "golden_reference.gpx",
        name="golden reference",
        points=route_points,
    )
    lat_values = [point[0] for point in route_points]
    lon_values = [point[1] for point in route_points]
    route_summary_ref = "normalized/routes/route_summary.json"
    route_bundle_ref = "normalized/routes/route_evidence_bundle.json"
    overpass_ref = "normalized/map/overpass_vector_evidence.geojson"
    dtm_ref = "normalized/terrain/dtm_coverage_summary.json"
    segment_dtm_ref = "normalized/terrain/segment_dtm_coverage.json"

    _write_json(
        project_root / route_summary_ref,
        {
            "artifact_id": "artifact.gpx.chilai_nanhua_day1",
            "bbox_wgs84": {
                "min_lat": min(lat_values),
                "min_lon": min(lon_values),
                "max_lat": max(lat_values),
                "max_lon": max(lon_values),
            },
            "distance_m": 450.0,
        },
    )
    _write_json(
        project_root / route_bundle_ref,
        {
            "artifact_kind": "pretrip_historical_gpx_route_evidence_bundle",
            "schema_version": "historical_gpx_importer.v1",
            "golden_route": {
                "source_id": "artifact.gpx.chilai_nanhua_day1",
                "source_path": gpx_path.as_posix(),
                "filtered_geometry_ref": "source_inbox/golden_reference.gpx",
                "role": "golden_route_reference",
                "route_bbox_wgs84": [
                    min(lon_values),
                    min(lat_values),
                    max(lon_values),
                    max(lat_values),
                ],
                "route_distance_m": 450.0,
            },
            "route_scope_for_map_preparation": {
                "bbox_wgs84": [
                    min(lon_values),
                    min(lat_values),
                    max(lon_values),
                    max(lat_values),
                ],
                "corridor_policy": "bbox_fetch_then_along_track_filter",
            },
            "boundary": {"candidate_only": True, "runtime_safety_truth": False},
        },
    )
    _write_json(
        project_root / overpass_ref,
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [lon, lat]
                            for lat, lon, _ele, _time in route_points
                        ],
                    },
                    "properties": {
                        "id": "osm.synthetic.trail.001",
                        "candidate_type": "trail_corridor_candidate",
                        "candidate_only": True,
                        "runtime_safety_truth": False,
                    },
                }
            ],
        },
    )

    projected = [wgs84_to_twd97(lat, lon) for lat, lon, _ele, _time in route_points]
    xs = [point[0] for point in projected]
    ys = [point[1] for point in projected]
    grid_path = project_root / "normalized" / "terrain" / "synthetic_dem.grd"
    min_x = int(min(xs) // 20 * 20) - 360
    max_x = int(max(xs) // 20 * 20) + 360
    min_y = int(min(ys) // 20 * 20) - 360
    max_y = int(max(ys) // 20 * 20) + 360
    lines: list[str] = []
    for x in range(min_x, max_x + 1, 20):
        for y in range(min_y, max_y + 1, 20):
            z = 1000.0 + (x - min_x) * 0.02 + (y - min_y) * 0.01
            lines.append(f"{x} {y} {z:.2f}\n")
    grid_path.write_text("".join(lines), encoding="utf-8")
    _write_json(
        project_root / dtm_ref,
        {
            "summary_id": "dtm_coverage.chilai_nanhua_day1.synthetic",
            "candidate_tiles": [
                {
                    "tile_id": "synthetic",
                    "county": "南投縣",
                    "grid_uri": grid_path.as_posix(),
                    "bbox_twd97": {
                        "min_x": min_x,
                        "min_y": min_y,
                        "max_x": max_x,
                        "max_y": max_y,
                    },
                }
            ],
            "scanned_header_count": 1,
            "missing_grid_count": 0,
        },
    )
    _write_json(
        project_root / segment_dtm_ref,
        {
            "artifact_kind": "pretrip_segment_dtm_coverage",
            "segment_count": 1,
            "candidate_tile_count": 1,
            "missing_grid_count": 0,
        },
    )
    _write_json(
        project_root / "project.json",
        {
            "project_id": "chilai_nanhua_day1",
            "route_summary_ref": route_summary_ref,
            "route_evidence_bundle_ref": route_bundle_ref,
            "overpass_map_context_ref": overpass_ref,
            "dtm_coverage_summary_ref": dtm_ref,
            "segment_dtm_coverage_ref": segment_dtm_ref,
        },
    )
    return project_root


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _relative_file_set(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {
        str(item.relative_to(path))
        for item in path.rglob("*")
        if item.is_file()
    }


def _write_gpx(
    path: Path,
    *,
    name: str,
    points: list[tuple[float, float, float, str]],
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    trkpts = "\n".join(
        f'<trkpt lat="{lat}" lon="{lon}"><ele>{ele}</ele><time>{time}</time></trkpt>'
        for lat, lon, ele, time in points
    )
    path.write_text(
        "\n".join(
            [
                '<?xml version="1.0" encoding="UTF-8"?>',
                '<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">',
                f"<metadata><name>{name}</name></metadata>",
                "<trk><trkseg>",
                trkpts,
                "</trkseg></trk>",
                "</gpx>",
            ]
        ),
        encoding="utf-8",
    )
    return path


def _write_risk_score_outputs(directory: Path) -> None:
    directory.mkdir(parents=True)
    route_risk = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [121.2, 24.0]},
                "properties": {
                    "sample_id": "risk.sample.001",
                    "route_id": "fixture",
                    "pretrip_risk": 61.2,
                    "risk_level": 4,
                    "distance_m": 10.0,
                    "elevation_m": 100.0,
                    "teii_20m": 70.0,
                    "tri": 40.0,
                    "sri": 20.0,
                    "lec": 60.0,
                    "scp": 5.0,
                },
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [121.21, 24.01]},
                "properties": {
                    "sample_id": "risk.sample.002",
                    "route_id": "fixture",
                    "pretrip_risk": 48.5,
                    "risk_level": 3,
                    "distance_m": 30.0,
                    "elevation_m": 110.0,
                    "teii_20m": 55.0,
                    "tri": 20.0,
                    "sri": 5.0,
                    "lec": 40.0,
                    "scp": 0.0,
                },
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [121.22, 24.02]},
                "properties": {
                    "sample_id": "risk.sample.003",
                    "route_id": "fixture",
                    "pretrip_risk": 22.0,
                    "risk_level": 1,
                    "distance_m": 60.0,
                    "elevation_m": 160.0,
                    "teii_20m": 10.0,
                    "tri": 5.0,
                    "sri": 1.0,
                    "lec": 15.0,
                    "scp": 0.0,
                },
            },
        ],
    }
    score_points = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [121.2, 24.0]},
                "properties": {
                    "x": 250000.0,
                    "y": 2650000.0,
                    "rs": 61.2,
                    "score_field": "pretrip_risk",
                    "route_id": "fixture",
                    "sample_id": "risk.sample.001",
                    "distance_m": 10.0,
                    "risk_level": 4,
                    "teii_20m": 70.0,
                    "tri": 20.0,
                    "sri": 5.0,
                    "lec": 60.0,
                    "scp": 0.0,
                },
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [121.21, 24.01]},
                "properties": {
                    "x": 250020.0,
                    "y": 2650020.0,
                    "rs": 48.5,
                    "score_field": "pretrip_risk",
                    "route_id": "fixture",
                    "sample_id": "risk.sample.002",
                    "distance_m": 30.0,
                    "risk_level": 3,
                    "teii_20m": 55.0,
                },
            },
        ],
    }
    files = {
        "route_risk.geojson": route_risk,
        "route_risk.metadata.json": {
            "artifact_kind": "scout_risk_overpass_route_profile_metadata",
            "route_risk_sample_count": 3,
            "boundary": {"candidate_only": True, "runtime_safety_truth": False},
        },
        "risk_score_points.geojson": score_points,
        "risk_score_points.metadata.json": {
            "artifact_kind": "scout_risk_score_point_map",
            "point_count": 2,
            "source_feature_count": 3,
            "score_field": "pretrip_risk",
            "snap_grid_m": 20.0,
            "boundary": {
                "candidate_only": True,
                "runtime_safety_truth": False,
                "route_aligned_samples_only": True,
            },
        },
        "risk_ribbon.geojson": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[121.2, 24.0], [121.21, 24.01]],
                    },
                    "properties": {
                        "segment_id": "risk_ribbon.fixture.001",
                        "rs": 61.2,
                        "score_field": "pretrip_risk",
                        "risk_bucket": "high",
                        "style_class": "risk-ribbon-high",
                        "candidate_only": True,
                        "runtime_safety_truth": False,
                    },
                }
            ],
        },
        "risk_ribbon.metadata.json": {
            "artifact_kind": "scout_risk_route_ribbon",
            "segment_count": 1,
            "source_sample_count": 2,
            "skipped_pair_count": 0,
            "score_field": "pretrip_risk",
            "score_surface_type": "route_aligned_risk_ribbon",
            "boundary": {
                "candidate_only": True,
                "runtime_safety_truth": False,
                "interpolated_surface": False,
                "route_aligned_samples_only": True,
            },
        },
    }
    for filename, payload in files.items():
        (directory / filename).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    (directory / "route_risk.csv").write_text("sample_id,pretrip_risk\n", encoding="utf-8")
    (directory / "risk_score_points.csv").write_text("x,y,rs\n", encoding="utf-8")
    (directory / "risk_score_points.xyz").write_text("250000 2650000 61.2\n", encoding="utf-8")


def _assert_risk_features_have_pretrip_provenance(
    path: Path,
    *,
    expected_evidence_type: str,
) -> None:
    payload = _load(path)
    metadata = payload["metadata"]
    assert metadata["source_refs"]
    assert metadata["extractor_version"] == "pretrip_risk_provenance.v0.1"
    assert metadata["pydantic_ai_prompt_version"] == (
        "not_applicable_deterministic_pretrip_risk"
    )
    assert metadata["review_state"] == "needs_review"
    assert metadata["candidate_only"] is True
    assert metadata["runtime_safety_truth"] is False
    for feature in payload["features"]:
        properties = feature["properties"]
        assert properties["evidence_type"] == expected_evidence_type
        assert properties["source_refs"]
        assert properties["source_attribution"]
        assert properties["extractor_version"] == "pretrip_risk_provenance.v0.1"
        assert properties["pydantic_ai_prompt_version"] == (
            "not_applicable_deterministic_pretrip_risk"
        )
        assert properties["model_output_sha256"]
        assert properties["model_output_summary"]
        assert properties["confidence"] == "medium"
        assert properties["stale_risk"] == "medium"
        assert properties["review_state"] == "needs_review"
        assert properties["candidate_only"] is True
        assert properties["runtime_safety_truth"] is False
