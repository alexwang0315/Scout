import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import pretrip_layer_preparation
from pretrip_layer_preparation import (
    LayerPreparationRequest,
    build_layer_preparation_preview,
    run_layer_preparation,
)
from pretrip_import import PretripImportRequest, run_pretrip_import


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PROJECT_ROOT = (
    ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
)


def test_layer_preparation_preview_is_metadata_only_and_no_write(tmp_path: Path) -> None:
    project_root = _copy_fixture_project(tmp_path)

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
    assert not (project_root / "outputs" / "layers").exists()
    assert "<trkpt" not in json.dumps(preview, ensure_ascii=False).lower()


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
    assert layers_by_id["overpass"]["status"] == "ready_from_project_ref"
    assert layers_by_id["overpass"]["warnings"] == []
    assert project["layer_preparation_manifest_ref"] == (
        "outputs/layers/layer_preparation_manifest.json"
    )
    assert (project_root / project["layer_preparation_manifest_ref"]).is_file()
    assert (project_root / project["layer_preparation_job_ref"]).is_file()


def test_layer_preparation_recovers_local_imagery_refs_from_workspace_manifests(
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
    project = _load(project_root / "project.json")
    imagery_layer = manifest["layers"][0]

    assert imagery_layer["status"] == "ready_from_project_ref"
    assert imagery_layer["counts"]["registered_raster_manifest_count"] == 3
    assert imagery_layer["raster_bbox_wgs84"] == {
        "west": 121.21478855,
        "south": 24.03365911,
        "east": 121.30320941,
        "north": 24.06992621,
    }
    assert imagery_layer["raster_coverage_policy"] == "render_intersecting_tiles_only"
    assert imagery_layer["raster_tile_zoom_range"] == "5-14"
    projection = _load(project_root / manifest["outputs"]["layer_map_projection_ref"])
    projected_imagery = projection["layers"][0]
    assert projected_imagery["raster_bbox_wgs84"] == imagery_layer["raster_bbox_wgs84"]
    assert projected_imagery["local_raster_tile_url_template"] == (
        "/admin/tiles/imagery/{project_id}/{layer_id}/{z}/{x}/{y}.png"
    )
    assert project["imagery_manifest_ref"] == (
        "outputs/layers/manifests/chilai_nanhua_day1.local_raster_source_manifest.json"
    )
    assert project["local_raster_manifest_ref"] == project["imagery_manifest_ref"]
    assert project["raster_tile_manifest_ref"] == (
        "outputs/layers/manifests/chilai_nanhua_day1.raster_tile_pyramid_plan.json"
    )
    assert project["imagery_tile_cache_root"] == "/data/scout/raster-tiles"
    assert project["imagery_source_tiff_ref"] == "/data/scout/raster-sources/map.tiff"
    assert project["imagery_source_kmz_ref"] == "/data/scout/raster-sources/map.kmz"


def test_layer_preparation_copies_known_scout_imagery_manifests(
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

    run_layer_preparation(
        LayerPreparationRequest(
            project_id="chilai_nanhua_day1",
            project_root=project_root,
            layers=("imagery",),
            prepared_at="2026-05-22T00:00:00+00:00",
        )
    )
    project = _load(project_root / "project.json")

    assert (
        project_root
        / "outputs/layers/manifests/chilai_nanhua_day1.local_raster_source_manifest.json"
    ).is_file()
    assert (
        project_root
        / "outputs/layers/manifests/chilai_nanhua_day1.raster_tile_pyramid_plan.json"
    ).is_file()
    assert project["imagery_manifest_ref"] == (
        "outputs/layers/manifests/chilai_nanhua_day1.local_raster_source_manifest.json"
    )
    assert project["raster_tile_manifest_ref"] == (
        "outputs/layers/manifests/chilai_nanhua_day1.raster_tile_pyramid_plan.json"
    )


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
    assert raster_label_plan["ocr_or_vision_performed"] is False
    for artifact in (
        overpass_vector_evidence,
        terrain_route_samples,
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
    assert project["risk_score_point_count"] == 2
    assert project["risk_route_sample_count"] == 3
    assert project["risk_ribbon_segment_count"] == 1
    assert project["calibrated_risk_heatmap_segment_count"] == 2
    assert (project_root / project["risk_score_points_ref"]).is_file()
    assert (project_root / project["risk_ribbon_ref"]).is_file()
    assert (project_root / project["risk_route_profile_ref"]).is_file()
    assert (project_root / project["calibrated_risk_heatmap_ref"]).is_file()
    assert (project_root / project["calibrated_risk_heatmap_metadata_ref"]).is_file()
    terrain_samples = _load(project_root / project["terrain_route_samples_ref"])
    assert terrain_samples["artifact_kind"] == "pretrip_terrain_route_samples"
    assert terrain_samples["status"] == "ready_from_risk_score_points"
    assert terrain_samples["counts"]["feature_count"] == 2
    assert terrain_samples["features"][0]["properties"]["evidence_type"] == (
        "pretrip_terrain_route_sample"
    )
    assert terrain_samples["features"][0]["properties"]["source_risk_score_ref"] == (
        project["risk_score_points_ref"]
    )
    assert terrain_samples["features"][0]["properties"]["runtime_safety_truth"] is False
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


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


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
